const assert = require("node:assert/strict")
const { readFileSync } = require("node:fs")
const path = require("node:path")
const test = require("node:test")

const barSource = readFileSync(path.join(__dirname, "..", "BarWidget.qml"), "utf8")
const panelSource = readFileSync(path.join(__dirname, "..", "Panel.qml"), "utf8")
const serviceSource = readFileSync(path.join(__dirname, "..", "Service.qml"), "utf8")
const promptSource = readFileSync(path.join(__dirname, "..", "UnlockPrompt.qml"), "utf8")
const manifest = JSON.parse(readFileSync(path.join(__dirname, "..", "manifest.json"), "utf8"))

test("bar and panel IPC wait for a relocated slot to retire", () => {
  assert.match(barSource, /property bool ipcRegistrationReady: false/)
  assert.match(barSource, /id: ipcRegistrationTimer\s+interval: 100/)
  assert.match(barSource, /IpcHandler \{\s+enabled: root\.ipcRegistrationReady\s+target: root\.moduleName/)
  assert.match(panelSource, /IpcHandler \{\s+enabled: root\.hostWidget && root\.hostWidget\.ipcRegistrationReady === true\s+target: root\.ipcTarget/)
})

test("native unlock is widget-owned so panel hotkeys cannot summon it", () => {
  assert.deepEqual(manifest.kinds, ["bar-widget"])
  assert.equal(manifest.entryPoints.overlay, undefined)
  assert.match(barSource, /function openUnlock\(config\)/)
  assert.match(barSource, /source: Qt\.resolvedUrl\("UnlockPrompt\.qml"\)/)
  assert.match(panelSource, /root\.hostWidget\.openUnlock\(config/)
  assert.match(promptSource, /PanelWindow \{/)
  assert.match(promptSource, /signal unlockSucceeded\(\)/)
  assert.match(promptSource, /signal unlockCancelled\(\)/)
  assert.match(promptSource, /password: true/)
  assert.match(promptSource, /maximumLength: 16384/)
  assert.match(promptSource, /command: \["python3", root\.helperPath, "unlock-stdin"/)
  assert.match(promptSource, /write\(secret\)/)
  assert.match(promptSource, /write\(secret\)[\s\S]*secret = ""[\s\S]*stdinEnabled = false/)
  assert.doesNotMatch(promptSource, /environment\s*:/)
  assert.doesNotMatch(promptSource, /omarchy-shell/)
  assert.match(barSource, /root\.service\.nativeUnlockComplete\(\)/)
  assert.match(barSource, /root\.service\.nativeUnlockCancelled\(\)/)
})

test("external Pinentry is the fail-safe default unlock prompt", () => {
  assert.equal(manifest.barWidget.defaults.unlockPrompt, "Pinentry")
  const promptSetting = manifest.barWidget.schema.find(row => row.key === "unlockPrompt")
  assert.equal(promptSetting.defaultValue, "Pinentry")
  assert.match(serviceSource, /setting\("unlockPrompt", "pinentry"\)/)
  assert.match(serviceSource, /=== "native"[\s\S]*\? "native" : "pinentry"/)
})

test("QML bounds every user-controlled helper argument and IPC query", () => {
  assert.match(serviceSource, /cliCommand:[^\n]*\.slice\(0, 512\)/)
  assert.match(serviceSource, /pinentryCommand[\s\S]*\.slice\(0, 512\)/)
  assert.match(serviceSource, /appDataDir:[^\n]*\.slice\(0, 4096\)/)
  assert.match(serviceSource, /configuredServerUrl:[^\n]*\.slice\(0, 8192\)/)
  assert.match(barSource, /panelLoader\.item\.query = Model\.sanitizeQuery\(query\)/)
  assert.match(panelSource, /root\.query = Model\.sanitizeQuery\(query\)/)
})

test("unlock rechecks shared agent state and clears stale prompt copy", () => {
  assert.match(serviceSource, /property bool _unlockAfterStatus: false/)
  assert.match(serviceSource, /function unlock\(\)[\s\S]*_unlockAfterStatus = true[\s\S]*refresh\(\)/)
  assert.match(serviceSource, /displayActionStatus: unlocked && actionStatus === nativeUnlockMessage/)
  assert.match(serviceSource, /if \(nextStatus === "unlocked"\)[\s\S]*actionStatus === nativeUnlockMessage[\s\S]*actionStatus = ""/)
  assert.match(serviceSource, /function beginUnlock\(\)[\s\S]*vaultStatus !== "locked"/)
  assert.match(panelSource, /bitwarden\.displayActionStatus/)
})

test("status changes retire hand-off notices without clobbering active work", () => {
  assert.match(serviceSource, /var statusChanged = nextStatus !== vaultStatus/)
  assert.match(serviceSource, /if \(nextStatus === "unlocked"\)[\s\S]*nativeUnlockPending = false/)
  assert.match(serviceSource, /else if \(statusChanged && !actionBusy && !nativeUnlockPending\) actionStatus = ""/)
})

test("empty vault copy waits for the current panel search to finish", () => {
  assert.match(panelSource, /property bool searchReady: false/)
  assert.match(panelSource, /readonly property bool searchLoading: !searchReady \|\| bitwarden\.searchBusy/)
  assert.match(panelSource, /function open\(\) \{\s+root\.searchReady = false/)
  assert.match(panelSource, /function onUnlockedChanged\(\) \{\s+root\.searchReady = false/)
  assert.match(panelSource, /function onSearchCompleted\(\)[\s\S]*root\.opened && bitwarden\.unlocked[\s\S]*root\.searchReady = true/)
  assert.match(panelSource, /text: root\.searchLoading\s+\? \(root\.browsing \? "Loading your vault…" : "Searching…"\)/)
  assert.match(serviceSource, /if \(root\._searchQueued\)[\s\S]*root\.search\(next\)[\s\S]*else if \(!cancelled\) root\.searchCompleted\(\)/)
})

test("closed panels neither launch nor retain searches", () => {
  assert.match(panelSource, /function close\(\)[\s\S]*bitwarden\.discardSearch\(\)[\s\S]*root\.controller\.hide\(\)/)
  assert.match(serviceSource, /function discardSearch\(\)[\s\S]*_searchCancelled = true[\s\S]*_searchQueued = false[\s\S]*items = \[\]/)
  assert.match(panelSource, /id: searchDebounce[\s\S]*onTriggered: if \(root\.opened && bitwarden\.unlocked/)
  assert.match(panelSource, /id: searchAfterAction[\s\S]*onTriggered: if \(root\.opened && bitwarden\.unlocked/)
  assert.match(panelSource, /function onUnlockedChanged\(\)[\s\S]*bitwarden\.unlocked && root\.opened[\s\S]*searchDebounce\.restart\(\)/)
})

test("desktop launch reports helper failure through a managed process", () => {
  assert.doesNotMatch(serviceSource, /execDetached\([^\n]*open-desktop/)
  assert.match(serviceSource, /function openDesktop\(\)[\s\S]*actionStatus = "Opening Bitwarden…"[\s\S]*desktopProcess\.running = true/)
  assert.match(serviceSource, /id: desktopProcess\s+command: \["python3", root\.helperPath, "open-desktop"\]/)
  assert.match(serviceSource, /onExited: function\(exitCode, exitStatus\)[\s\S]*exitCode === 0[\s\S]*actionMessageTimer\.restart\(\)[\s\S]*The Bitwarden desktop app isn't installed/)
})

test("native unlock only closes the panel after the prompt opens", () => {
  assert.match(promptSource, /function open\(payloadJson\)[\s\S]*unlockProcess\.running\) return false/)
  assert.match(promptSource, /lockService\.locked === true\) return false/)
  assert.match(promptSource, /opened = true[\s\S]*return true/)
  assert.match(barSource, /var opened = unlockLoader\.item\.open\([\s\S]*if \(opened === true\) root\.close\(\)[\s\S]*return opened === true/)
})

test("search echoes are trimmed without weakening stale-result checks", () => {
  assert.match(serviceSource, /if \(!unlocked \|\| _searchCancelled \|\| _runningQuery !== _desiredQuery\) return/)
  assert.match(serviceSource, /String\(parsed\.query \|\| ""\) !== Model\.normalizedQuery\(_runningQuery\)/)
})

test("new action notices cannot be erased by an older message timer", () => {
  assert.match(serviceSource, /function runAction\(action, extra\)[\s\S]*actionMessageTimer\.stop\(\)[\s\S]*actionBusy = true/)
  assert.match(serviceSource, /function login\(\)[\s\S]*actionMessageTimer\.stop\(\)[\s\S]*Continue in the terminal/)
  assert.match(serviceSource, /function installRequirements\(\)[\s\S]*actionMessageTimer\.stop\(\)[\s\S]*Continue in the terminal/)
})

test("a failed status check drops metadata from the no-longer-open vault", () => {
  assert.match(serviceSource, /if \(!parsed\.ok\)[\s\S]*vaultStatus = "error"[\s\S]*items = \[\][\s\S]*return/)
  assert.match(serviceSource, /function applySearch\(raw\)[\s\S]*if \(!unlocked \|\| _searchCancelled/)
})

test("returning from settings refreshes a vault opened directly into settings", () => {
  assert.match(panelSource, /function toggleSettings\(\)[\s\S]*!settingsOpen && root\.opened && bitwarden\.unlocked[\s\S]*searchDebounce\.restart\(\)/)
})
