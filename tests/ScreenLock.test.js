const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const test = require("node:test")

// Execute production QML methods with deterministic process/timer doubles.
// This covers state transitions rather than matching implementation text.
function methods(file, names) {
  const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8")
  return names.map(name => {
    const start = source.indexOf("  function " + name + "(")
    assert.notEqual(start, -1, name)
    const brace = source.indexOf("{", start)
    let depth = 1, end = brace + 1, quote = "", comment = ""
    for (; end < source.length && depth; end++) {
      const c = source[end], next = source[end + 1]
      if (comment === "line") { if (c === "\n") comment = ""; continue }
      if (comment === "block") { if (c === "*" && next === "/") { comment = ""; end++ }; continue }
      if (quote) { if (c === "\\") end++; else if (c === quote) quote = ""; continue }
      if (c === "/" && next === "/") { comment = "line"; end++; continue }
      if (c === "/" && next === "*") { comment = "block"; end++; continue }
      if (c === '"' || c === "'" || c === "`") { quote = c; continue }
      if (c === "{") depth++
      else if (c === "}") depth--
    }
    assert.equal(depth, 0, name)
    return source.slice(start, end)
  }).join("\n")
}
const timer = () => ({ restarts: 0, restart() { this.restarts++ }, stop() {} })

function service() {
  const callbacks = []
  const c = {
    screenLock: { unlocked: true }, lockOnScreenLock: true,
    vaultStatus: "unlocked", nativeUnlockPending: false, actionBusy: false,
    _screenLockPending: false, _syncAfterUnlock: false, _pendingAction: "",
    _unlockAfterStatus: false, _searchCancelled: false, _searchQueued: false,
    _queuedQuery: "", items: [{ id: "fixture" }], activeQuery: "", helperPath: "fake",
    _actionInput: "", actionStatus: "", lastError: "", statusText: "", lastCopyField: "",
    syncOnUnlock: true, unlockPrompt: "pinentry", nativeUnlockMessage: "prompt",
    actionProcess: { running: false }, searchProcess: { running: false },
    screenLockRetry: timer(), actionMessageTimer: timer(), refreshTimer: timer(),
    requestObject: (action, extra) => JSON.stringify({ action, ...extra }),
    actionCompleted: () => {}, nativeUnlockRequested: () => {},
    Model: { parseResponse: JSON.parse },
    Qt: { callLater: fn => callbacks.push(fn) },
  }
  Object.defineProperty(c, "unlocked", { get: () => c.vaultStatus === "unlocked" })
  c.root = c
  vm.createContext(c)
  vm.runInContext(methods("Service.qml", ["runAction", "handleScreenLock", "discardSearch", "applyAction", "nativeUnlockComplete", "nativeUnlockCancelled", "beginUnlock", "sync"]), c)
  c.flush = () => { while (callbacks.length) callbacks.shift()() }
  return c
}

test("screen lock latches through a busy sync and a later desktop unlock", () => {
  const c = service()
  c.actionBusy = true; c._pendingAction = "sync"; c.screenLock.unlocked = false
  c.handleScreenLock()
  assert.equal(c._screenLockPending, true)
  assert.equal(c.items.length, 0)
  c.screenLock.unlocked = true; c.actionBusy = false
  c.handleScreenLock()
  assert.equal(JSON.parse(c._actionInput).action, "lock")
  assert.equal(c._screenLockPending, true, "not cleared until lock succeeds")
  c.applyAction(JSON.stringify({ ok: true, status: "locked" }))
  assert.equal(c._screenLockPending, false)
})

test("screen lock during Pinentry unlock queues a lock instead of a sync", () => {
  const c = service()
  c.vaultStatus = "locked"; c.actionBusy = true; c._pendingAction = "unlock"
  c.screenLock.unlocked = false; c.handleScreenLock()
  c.screenLock.unlocked = true
  c.applyAction(JSON.stringify({ ok: true, status: "unlocked" }))
  assert.equal(c._syncAfterUnlock, false)
  c.actionBusy = false; c.flush()
  assert.equal(c._pendingAction, "lock")
})

test("native completion carries a lock event even after an earlier lock completed", () => {
  const c = service()
  c.vaultStatus = "locked"; c.nativeUnlockPending = true
  c.nativeUnlockComplete(true)
  c.flush()
  assert.equal(c._pendingAction, "lock")
  assert.equal(c._syncAfterUnlock, false)
})

test("failed lock remains pending and retries; opt-out is respected", () => {
  const c = service()
  c.screenLock.unlocked = false; c.handleScreenLock()
  c.applyAction(JSON.stringify({ ok: false, error: "fixture failure" }))
  assert.equal(c._screenLockPending, true)
  c.actionBusy = false; c.handleScreenLock()
  assert.equal(c.actionBusy, true)
  c.lockOnScreenLock = false; c.handleScreenLock()
  assert.equal(c._screenLockPending, false)
})

test("unknown/locked state blocks prompting and sensitive actions", () => {
  const c = service()
  c.screenLock.unlocked = false; c.vaultStatus = "locked"
  c.beginUnlock()
  assert.equal(c.actionBusy, false)
  assert.match(c.lastError, /cannot be checked/)
  assert.equal(c.runAction("unlock"), false)
  assert.equal(c.runAction("copy", { id: "fixture" }), false)
  c.lockOnScreenLock = false
  assert.equal(c.runAction("copy", { id: "fixture" }), true)
})

function prompt() {
  const events = []
  const c = {
    opened: false, busy: false, cancelledForLock: false, errorText: "", unlockConfig: {},
    screenUnlocked: true, passwordField: { text: "", forceActiveFocus() {} },
    unlockProcess: { running: false, secret: "", configLine: "" },
    unlockSucceeded: observed => events.push(["success", observed]),
    unlockCancelled: () => events.push(["cancel"]),
    Qt: { callLater: fn => fn() },
  }
  c.root = c; c.events = events
  vm.createContext(c)
  vm.runInContext(methods("UnlockPrompt.qml", ["parsePayload", "open", "clearSecret", "close", "submit", "finish", "cancelForScreenLock"]), c)
  return c
}

test("native prompt fails closed and clears unsubmitted secrets", () => {
  const c = prompt()
  c.screenUnlocked = false
  assert.equal(c.open("{}"), false)
  c.screenUnlocked = true; assert.equal(c.open("{}"), true)
  c.passwordField.text = "fake password"
  c.screenUnlocked = false; c.cancelForScreenLock()
  assert.equal(c.opened, false)
  assert.equal(c.passwordField.text, "")
  assert.deepEqual(c.events, [["cancel"]])
})

test("native prompt hides on lock but waits for its in-flight result", () => {
  const c = prompt()
  c.open("{}"); c.passwordField.text = "fake password"; c.submit()
  assert.equal(c.busy, true)
  c.screenUnlocked = false; c.cancelForScreenLock()
  assert.equal(c.opened, false)
  assert.equal(c.unlockProcess.secret, "")
  assert.deepEqual(c.events, [])
  c.screenUnlocked = true; c.finish('{"ok":true}')
  assert.deepEqual(c.events, [["success", true]])
})

test("failed native unlock after lock reports cancellation without reopening", () => {
  const c = prompt()
  c.open("{}"); c.passwordField.text = "fake password"; c.submit()
  c.screenUnlocked = false; c.cancelForScreenLock()
  c.finish('{"ok":false,"error":"fixture"}')
  assert.equal(c.opened, false)
  assert.deepEqual(c.events, [["cancel"]])
})
