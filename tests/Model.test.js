const assert = require("node:assert/strict")
const test = require("node:test")
const Model = require("../Model.js")

test("response parsing fails closed", () => {
  assert.equal(Model.parseResponse('{"ok":true}').ok, true)
  assert.deepEqual(Model.parseResponse('{"ok":true}').items, [])
  assert.equal(Model.parseResponse("broken").ok, false)
  assert.equal(Model.parseResponse("[]").ok, false)
})

test("state presentation covers every agent state", () => {
  assert.equal(Model.statusLabel("unlocked"), "Vault unlocked")
  assert.equal(Model.statusLabel("locked"), "Vault locked")
  assert.equal(Model.statusLabel("unauthenticated"), "Sign in required")
  assert.equal(Model.statusLabel("unavailable"), "Setup required")
  assert.notEqual(Model.statusGlyph("error"), Model.statusGlyph("unlocked"))
})

test("settings coercion is bounded and predictable", () => {
  assert.equal(Model.bool("TRUE", false), true)
  assert.equal(Model.bool("false", true), false)
  assert.equal(Model.bool(null, true), true)
  assert.equal(Model.boundedInt("200", 20, 5, 50), 50)
  assert.equal(Model.boundedInt("bad", 20, 5, 50), 20)
})

test("screen lock only relocks an open vault when enabled", () => {
  assert.equal(Model.shouldLockForScreen(true, true, true), true)
  assert.equal(Model.shouldLockForScreen(false, true, true), false)
  assert.equal(Model.shouldLockForScreen(true, false, true), false)
  assert.equal(Model.shouldLockForScreen(true, true, false), false)
})

test("inactivity locking has an explicit off switch and bounded delay", () => {
  assert.equal(Model.effectiveInactivityMinutes(false, 15), 0)
  assert.equal(Model.effectiveInactivityMinutes(true, 0), 5)
  assert.equal(Model.effectiveInactivityMinutes(true, 15), 15)
  assert.equal(Model.effectiveInactivityMinutes(true, 999), 240)
})

test("locked-state copy distinguishes native and external prompts", () => {
  assert.match(Model.gateCopy("locked", true, "", "native").body, /native Omarchy prompt/)
  assert.match(Model.gateCopy("locked", true, "", "pinentry").body, /separate password window/)
})

test("item labels honor username privacy", () => {
  const item = { username: "person@example.test", url: "https://example.test/login" }
  assert.equal(Model.itemSubtitle(item, true), "person@example.test · example.test")
  assert.equal(Model.itemSubtitle(item, false), "example.test")
})

test("card labels and actions expose only safe recognition metadata", () => {
  const card = {
    type: 3,
    cardholder: "Example Person",
    brand: "Visa",
    last4: "1111",
    hasNumber: true,
    hasCardholder: true,
    hasCardCode: true,
    hasExpiry: true
  }
  assert.equal(Model.itemSubtitle(card, true), "Example Person · Visa · •••• 1111")
  assert.equal(Model.itemSubtitle(card, false), "Visa · •••• 1111")
  assert.deepEqual(Model.itemActions(card), ["number", "cardholder", "cardCode", "expiry"])
  assert.equal(Model.defaultAction(card, "Password"), "number")
  assert.equal(Model.primaryAction("Password", card), "number")
  assert.equal(Model.alternateAction("Password", card), "cardholder")
  assert.equal(Model.actionAvailable(card, "cardCode"), true)
  assert.equal(Model.actionAvailable(card, "password"), false)
})

test("actions are only enabled when metadata allows them", () => {
  const item = {
    username: "person",
    url: "https://example.test",
    hasPassword: true,
    hasTotp: false
  }
  assert.equal(Model.actionAvailable(item, "password"), true)
  assert.equal(Model.actionAvailable(item, "totp"), false)
  assert.equal(Model.actionAvailable(item, "open"), true)
  assert.equal(Model.defaultAction(item, "Password"), "password")
  assert.equal(Model.defaultAction(item, "Username"), "username")
})

test("unavailable action tooltips explain missing login fields", () => {
  assert.equal(Model.unavailableActionTooltip("password"), "No password saved for this login")
  assert.equal(Model.unavailableActionTooltip("username"), "No username saved for this login")
  assert.equal(Model.unavailableActionTooltip("totp"), "No authenticator key saved for this login")
  assert.equal(Model.unavailableActionTooltip("open"), "No website saved for this login")
  assert.equal(Model.unavailableActionTooltip("unknown"), "")
})

test("query sanitation removes controls and caps length", () => {
  assert.equal(Model.sanitizeQuery("hello\nworld"), "hello world")
  assert.equal(Model.sanitizeQuery("x".repeat(1000)).length, 512)
})

test("search response queries use the helper's trimmed echo", () => {
  assert.equal(Model.normalizedQuery(" g"), "g")
  assert.equal(Model.normalizedQuery("git "), "git")
  assert.equal(Model.normalizedQuery(" hello\nworld "), "hello world")
  assert.ok(Model.normalizedQuery(" x ".repeat(300)).length <= 512)
})

test("plugin file URLs support spaces", () => {
  assert.equal(Model.filePath("file:///tmp/Oma%20Warden/agent.py"), "/tmp/Oma Warden/agent.py")
})

test("monograms pick the first meaningful character", () => {
  assert.equal(Model.monogram("GitHub"), "G")
  assert.equal(Model.monogram("  [work] github"), "W")
  assert.equal(Model.monogram("1password"), "1")
  assert.equal(Model.monogram("übung"), "Ü")
  assert.equal(Model.monogram("   "), "•")
  assert.equal(Model.monogram(null), "•")
})

test("sync age is phrased for people and fails to empty", () => {
  const now = Date.parse("2026-08-20T12:00:00.000Z")
  const ago = (seconds) => new Date(now - seconds * 1000).toISOString()
  assert.equal(Model.relativeSync("", now), "")
  assert.equal(Model.relativeSync("whenever", now), "")
  assert.equal(Model.relativeSync(ago(10), now), "just now")
  assert.equal(Model.relativeSync(ago(60), now), "1 minute ago")
  assert.equal(Model.relativeSync(ago(300), now), "5 minutes ago")
  assert.equal(Model.relativeSync(ago(7200), now), "2 hours ago")
  assert.equal(Model.relativeSync(ago(3 * 86400), now), "3 days ago")
  assert.equal(Model.relativeSync(ago(400 * 86400), now), "a while ago")
})

test("the header only claims a sync when the vault is open", () => {
  const now = Date.parse("2026-08-20T12:00:00.000Z")
  const synced = new Date(now - 300 * 1000).toISOString()
  assert.equal(Model.statusDetail("unlocked", synced, now), "Vault unlocked · synced 5 minutes ago")
  assert.equal(Model.statusDetail("unlocked", "", now), "Vault unlocked")
  assert.equal(Model.statusDetail("locked", synced, now), "Vault locked")
})

test("the match pill is singular, plural, or absent", () => {
  assert.equal(Model.matchLabel(0), "")
  assert.equal(Model.matchLabel(1), "1 match")
  assert.equal(Model.matchLabel(12), "12 matches")
  assert.equal(Model.matchLabel("nope"), "")
})

test("a host that only repeats the entry name is dropped", () => {
  const row = (name, url) => Model.itemSubtitle({ name, username: "person@example.test", url }, true)
  assert.equal(row("48e.co", "https://48e.co"), "person@example.test")
  assert.equal(row("4shared", "https://www.4shared.com"), "person@example.test")
  assert.equal(row("164.92.195.195", "http://164.92.195.195:8080"), "person@example.test")
  assert.equal(row("1Password Account", "https://my.1password.com"), "person@example.test · my.1password.com")
  assert.equal(Model.itemHost("https://dash.cloudflare.com/login"), "dash.cloudflare.com")
})

test("monogram groups start when the initial changes", () => {
  const items = [{ name: "1a" }, { name: "1b" }, { name: "2c" }]
  assert.equal(Model.isGroupStart(items, 0), true)
  assert.equal(Model.isGroupStart(items, 1), false)
  assert.equal(Model.isGroupStart(items, 2), true)
  assert.equal(Model.isGroupStart(null, 3), true)
})

test("the gate explains each state without implementation jargon", () => {
  for (const [status, ready] of [["unavailable", false], ["unauthenticated", true], ["locked", true], ["error", true]]) {
    const copy = Model.gateCopy(status, ready, "")
    assert.ok(copy.title.length > 0 && copy.body.length > 0 && copy.action.length > 0, status)
    assert.doesNotMatch(copy.body, /session key|agent|pinentry|argv|fifo/i, status)
  }
  assert.equal(Model.gateCopy("locked", false, "").action, "Install requirements")
  assert.equal(Model.gateCopy("checking", true, "").action, "")
})

test("setup steps track the install, sign in, unlock path", () => {
  const states = (status, ready) => Model.setupSteps(status, ready).map((step) => step.state)
  assert.deepEqual(states("locked", false), ["current", "todo", "todo"])
  assert.deepEqual(states("unauthenticated", true), ["done", "current", "todo"])
  assert.deepEqual(states("locked", true), ["done", "done", "current"])
  assert.deepEqual(states("unlocked", true), ["done", "done", "done"])
  assert.deepEqual(states("error", true), [])
  assert.deepEqual(states("checking", true), [])
})

test("requirement rows name the package behind each missing piece", () => {
  const nativeRows = Model.requirementRows({ bw: true, pinentry: false, wlCopy: false }, false)
  assert.deepEqual(nativeRows.map((row) => row.ok), [true, false])
  assert.deepEqual(nativeRows.map((row) => row.detail), ["bitwarden-cli", "wl-clipboard"])
  const externalRows = Model.requirementRows({ bw: true, pinentry: false, wlCopy: false }, true)
  assert.deepEqual(externalRows.map((row) => row.ok), [true, false, false])
  assert.deepEqual(externalRows.map((row) => row.detail), ["bitwarden-cli", "pinentry", "wl-clipboard"])
})

test("server labels fall back to the official cloud", () => {
  assert.equal(Model.serverLabel("", ""), "bitwarden.com")
  assert.equal(Model.serverLabel("", "https://vault.bitwarden.eu"), "vault.bitwarden.eu")
  assert.equal(Model.serverLabel("https://vault.example.test:8443/", "https://other.test"), "vault.example.test")
})

test("browse sections group recent, favorite, and remaining items", () => {
  const items = [
    { name: "Recent one", recent: true, favorite: true },
    { name: "Fav", favorite: true },
    { name: "Fav two", favorite: true },
    { name: "Plain" }
  ]
  assert.equal(Model.sectionLabel(items[0], true), "Recent")
  assert.equal(Model.sectionLabel(items[1], true), "Favorites")
  assert.equal(Model.sectionLabel(items[3], true), "All items")
  assert.equal(Model.sectionLabel(items[3], false), "")
  assert.deepEqual(items.map((_, index) => Model.isSectionStart(items, index, true)), [true, true, false, true])
  assert.deepEqual(items.map((_, index) => Model.isSectionStart(items, index, false)), [false, false, false, false])
})

test("the copy notice counts the clipboard lifetime down", () => {
  assert.equal(Model.copyNotice("password", 24.2), "Password copied · clears in 25 s")
  assert.equal(Model.copyNotice("totp", 3), "Code copied · clears in 3 s")
  assert.equal(Model.copyNotice("username", 0), "Username copied · clipboard cleared")
  assert.equal(Model.copyNotice("number", 10), "Card number copied · clears in 10 s")
})

test("shift+enter copies whichever field enter does not", () => {
  assert.equal(Model.primaryAction("Password"), "password")
  assert.equal(Model.primaryAction("username"), "username")
  assert.equal(Model.primaryAction("nonsense"), "password")
  assert.equal(Model.alternateAction("Password"), "username")
  assert.equal(Model.alternateAction("Username"), "password")
  assert.equal(Model.alternateAction(undefined), "username")
})

test("durations read as people say them", () => {
  assert.equal(Model.minutesLabel(0), "Off")
  assert.equal(Model.minutesLabel(15), "15 min")
  assert.equal(Model.minutesLabel(60), "1 hour")
  assert.equal(Model.minutesLabel(120), "2 hours")
  assert.equal(Model.secondsLabel(30), "30 s")
  assert.equal(Model.secondsLabel(120), "2 min")
})
