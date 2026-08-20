import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  property var settings: ({})
  property var shell: null
  property string vaultStatus: "checking"
  property string statusText: "Checking Bitwarden…"
  property string lastSync: ""
  property string serverUrl: ""
  property var dependencies: ({})
  property var items: []
  property string activeQuery: ""
  property string lastError: ""
  property string actionStatus: ""
  readonly property string displayActionStatus: unlocked && actionStatus === nativeUnlockMessage
    ? "" : actionStatus
  // Field of the most recent successful copy ("password", "username",
  // "totp"); the panel phrases its clipboard countdown from it.
  property string lastCopyField: ""
  property bool statusBusy: false
  property bool searchBusy: false
  property bool actionBusy: false
  readonly property bool busy: statusBusy || searchBusy || actionBusy
  readonly property bool installed: dependencies.bw === true
  readonly property bool ready: dependencies.bw === true && dependencies.wlCopy === true
    && (unlockPrompt === "native" || dependencies.pinentry === true)
  readonly property string missingRequirements: {
    var missing = []
    if (dependencies.bw !== true) missing.push("Bitwarden CLI")
    if (unlockPrompt === "pinentry" && dependencies.pinentry !== true) missing.push("Pinentry")
    if (dependencies.wlCopy !== true) missing.push("wl-clipboard")
    return missing.join(", ")
  }
  readonly property bool unlocked: vaultStatus === "unlocked"
  readonly property bool locked: vaultStatus === "locked"
  readonly property bool authenticated: unlocked || locked

  readonly property string helperPath: Model.filePath(Qt.resolvedUrl("omawarden-agent.py"))
  readonly property int refreshIntervalSec: Model.boundedInt(setting("refreshIntervalSec", 30), 30, 10, 3600)
  readonly property int autoLockMinutes: Model.boundedInt(setting("autoLockMinutes", 15), 15, 0, 240)
  readonly property bool inactivityLockEnabled: Model.bool(
    setting("inactivityLockEnabled", autoLockMinutes > 0), autoLockMinutes > 0)
  readonly property int effectiveAutoLockMinutes: Model.effectiveInactivityMinutes(
    inactivityLockEnabled, autoLockMinutes)
  readonly property int clipboardTimeoutSec: Model.boundedInt(setting("clipboardTimeoutSec", 30), 30, 5, 120)
  readonly property int resultLimit: Model.boundedInt(setting("resultLimit", 20), 20, 5, 50)
  readonly property bool syncOnUnlock: Model.bool(setting("syncOnUnlock", true), true)
  readonly property bool lockOnScreenLock: Model.bool(setting("lockOnScreenLock", true), true)
  readonly property bool showUsernames: Model.bool(setting("showUsernames", true), true)
  readonly property string defaultCopy: String(setting("defaultCopy", "Password"))
  readonly property string cliCommand: String(setting("cliCommand", "bw")).slice(0, 512)
  // Pinentry is the fail-safe default: only an explicit "native" setting
  // allows the master password to enter the long-lived shell process.
  readonly property string unlockPrompt: String(setting("unlockPrompt", "pinentry")).toLowerCase() === "native"
    ? "native" : "pinentry"
  readonly property string pinentryCommand: {
    var configured = String(setting("pinentryCommand", "auto")).trim().slice(0, 512)
    // Early builds stored "omarchy" for what was actually Qt Pinentry. Treat
    // that legacy value as automatic external selection without rewriting the
    // user's shell.json behind their back.
    return configured.toLowerCase() === "omarchy" || configured === "" ? "auto" : configured
  }
  readonly property string appDataDir: String(setting("appDataDir", "")).slice(0, 4096)
  readonly property string configuredServerUrl: String(setting("serverUrl", "")).slice(0, 8192)
  readonly property string nativeUnlockMessage: "Enter your master password in the OmaWarden prompt"
  readonly property var systemLockService: shell && typeof shell.serviceFor === "function"
    ? shell.serviceFor("omarchy.lock") : null

  property string _statusInput: ""
  property string _searchInput: ""
  property string _actionInput: ""
  property string _pendingAction: ""
  property string _queuedQuery: ""
  property string _desiredQuery: ""
  property string _runningQuery: ""
  property bool _searchQueued: false
  property bool _searchCancelled: false
  property bool _screenLockPending: false
  property bool _syncAfterUnlock: false
  property bool _unlockAfterStatus: false
  property bool nativeUnlockPending: false

  signal searchCompleted()
  signal actionCompleted(string action, bool ok)
  signal nativeUnlockRequested(var config)

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function configObject() {
    return {
      bwCommand: cliCommand,
      pinentryCommand: pinentryCommand,
      appDataDir: appDataDir,
      autoLockMinutes: effectiveAutoLockMinutes,
      clipboardTimeoutSec: clipboardTimeoutSec,
      resultLimit: resultLimit,
      syncOnUnlock: syncOnUnlock,
      showUsernames: showUsernames
    }
  }

  function requestObject(action, extra) {
    var request = { action: action, config: configObject() }
    if (extra) for (var key in extra) request[key] = extra[key]
    return JSON.stringify(request)
  }

  function refresh() {
    if (statusProcess.running || actionProcess.running || helperPath === "") return
    _statusInput = requestObject("status")
    statusBusy = true
    statusProcess.running = true
  }

  function search(query) {
    var clean = Model.sanitizeQuery(query)
    _desiredQuery = clean
    if (!unlocked) {
      items = []
      activeQuery = clean
      return
    }
    if (searchProcess.running) {
      _queuedQuery = clean
      _searchQueued = true
      return
    }
    _searchQueued = false
    _searchCancelled = false
    _runningQuery = clean
    _searchInput = requestObject("search", { query: clean })
    searchBusy = true
    searchProcess.running = true
  }

  function discardSearch() {
    // A running request cannot be stopped safely, so make its response stale
    // and drop any queued follow-up before the panel releases its metadata.
    _searchCancelled = true
    _searchQueued = false
    _queuedQuery = ""
    items = []
    activeQuery = ""
  }

  function runAction(action, extra) {
    if (actionBusy || helperPath === "") return false
    _pendingAction = action
    _actionInput = requestObject(action, extra || {})
    lastError = ""
    actionStatus = action === "unlock" ? "Waiting for your master password…"
      : (action === "sync" ? "Syncing…"
        : (action === "lock" ? "Locking…"
          : (action === "logout" ? "Signing out…"
            : (action === "copy" ? "Copying…" : "Working…"))))
    actionMessageTimer.stop()
    actionBusy = true
    actionProcess.running = true
    return true
  }

  function beginUnlock() {
    if (unlocked || vaultStatus !== "locked" || actionBusy) {
      nativeUnlockCancelled()
      return
    }
    if (unlockPrompt === "native") {
      lastError = ""
      actionMessageTimer.stop()
      actionStatus = nativeUnlockMessage
      nativeUnlockPending = true
      nativeUnlockRequested(configObject())
    } else {
      runAction("unlock")
    }
  }

  function unlock() {
    // Every bar surface owns a Service instance, while the agent session is
    // shared. Recheck the agent before prompting so a stale monitor cannot ask
    // for a password after another monitor has already unlocked the vault.
    if (unlocked || actionBusy) {
      nativeUnlockCancelled()
      return
    }
    _unlockAfterStatus = true
    if (!statusProcess.running) refresh()
  }

  function nativeUnlockCancelled() {
    _unlockAfterStatus = false
    nativeUnlockPending = false
    if (actionStatus === nativeUnlockMessage) actionStatus = ""
  }

  function nativeUnlockComplete() {
    _unlockAfterStatus = false
    nativeUnlockPending = false
    vaultStatus = "unlocked"
    statusText = "Vault unlocked"
    lastError = ""
    actionStatus = "Vault unlocked"
    actionMessageTimer.restart()
    actionCompleted("unlock", true)

    var screenLocked = systemLockService && systemLockService.locked === true
    if (lockOnScreenLock && screenLocked) {
      Qt.callLater(handleScreenLock)
      return
    }
    if (syncOnUnlock) Qt.callLater(sync)
    else refreshTimer.restart()
  }
  function lock() { runAction("lock") }
  function sync() { runAction("sync") }
  function logout() { runAction("logout") }

  function handleScreenLock() {
    var shouldLock = Model.shouldLockForScreen(
      lockOnScreenLock,
      systemLockService ? systemLockService.locked === true : false,
      unlocked
    )
    if (!shouldLock) {
      _screenLockPending = false
      screenLockRetry.stop()
      return
    }
    if (runAction("lock")) {
      _screenLockPending = false
      screenLockRetry.stop()
      return
    }
    // Copy/sync may already own the action process. Keep retrying until the
    // vault is relocked; a screen-lock event must not be silently dropped.
    _screenLockPending = true
    screenLockRetry.restart()
  }
  function copy(item, field) {
    if (!item || !item.id) return
    runAction("copy", { id: String(item.id), field: String(field) })
  }
  function openUrl(item) {
    if (!item || String(item.url || "") === "") return
    runAction("open-url", { url: String(item.url), id: String(item.id || "") })
  }
  function terminalArguments(mode) {
    var command = ["omarchy-launch-terminal", "python3", helperPath, mode,
      "--bw-command", cliCommand,
      "--pinentry-command", pinentryCommand,
      "--app-data-dir", appDataDir,
      "--auto-lock-minutes", String(effectiveAutoLockMinutes),
      "--clipboard-timeout-sec", String(clipboardTimeoutSec),
      "--result-limit", String(resultLimit),
      "--server-url", configuredServerUrl.trim()]
    command.push(syncOnUnlock ? "--sync-on-unlock" : "--no-sync-on-unlock")
    command.push(showUsernames ? "--show-usernames" : "--no-show-usernames")
    return command
  }

  function login() {
    if (helperPath === "") return
    Quickshell.execDetached(terminalArguments("login-terminal"))
    actionMessageTimer.stop()
    actionStatus = "Continue in the terminal window, then come back here"
  }

  function installRequirements() {
    if (helperPath === "") return
    var command = ["omarchy-launch-terminal", "python3", helperPath, "install-terminal"]
    if (unlockPrompt === "pinentry") command.push("--with-pinentry")
    Quickshell.execDetached(command)
    actionMessageTimer.stop()
    actionStatus = "Continue in the terminal window, then come back here"
  }

  function openDesktop() {
    if (actionBusy || helperPath === "") return
    lastError = ""
    actionMessageTimer.stop()
    actionStatus = "Opening Bitwarden…"
    actionBusy = true
    desktopProcess.running = true
  }

  function applyStatus(raw) {
    var parsed = Model.parseResponse(raw)
    if (!parsed.ok) {
      _unlockAfterStatus = false
      vaultStatus = "error"
      statusText = "Bitwarden unavailable"
      lastError = parsed.error || "Couldn't read the vault status"
      items = []
      return
    }
    dependencies = parsed.dependencies || {}
    var nextStatus = String(parsed.status || "error")
    var statusChanged = nextStatus !== vaultStatus
    vaultStatus = nextStatus
    statusText = String(parsed.statusText || Model.statusLabel(vaultStatus))
    lastSync = String(parsed.lastSync || "")
    serverUrl = String(parsed.serverUrl || "")
    lastError = ""
    if (nextStatus === "unlocked") {
      nativeUnlockPending = false
      if (actionStatus === nativeUnlockMessage) actionStatus = ""
    } else if (statusChanged && !actionBusy && !nativeUnlockPending) actionStatus = ""
    if (!unlocked) items = []
    if (_unlockAfterStatus) {
      _unlockAfterStatus = false
      Qt.callLater(beginUnlock)
    }
    // Covers shell/plugin startup while the compositor is already locked.
    Qt.callLater(handleScreenLock)
  }

  function applySearch(raw) {
    var parsed = Model.parseResponse(raw)
    if (!unlocked || _searchCancelled || _runningQuery !== _desiredQuery) return
    if (!parsed.ok) {
      items = []
      lastError = parsed.error || "Search failed"
      if (lastError.toLowerCase().indexOf("locked") !== -1) vaultStatus = "locked"
      return
    }
    // Fast typing may finish an older in-flight request after a newer query
    // has been queued. Do not flash those stale results into the panel.
    if (String(parsed.query || "") !== Model.normalizedQuery(_runningQuery)) return
    items = parsed.items || []
    activeQuery = _desiredQuery
    lastError = ""
  }

  function applyAction(raw) {
    var parsed = Model.parseResponse(raw)
    var action = _pendingAction
    if (!parsed.ok) {
      actionStatus = ""
      lastError = parsed.error || "That didn't work"
      if (lastError.toLowerCase().indexOf("locked") !== -1) vaultStatus = "locked"
      actionCompleted(action, false)
      return
    }
    // Copies get no transient message: the panel phrases the clipboard
    // countdown itself from lastCopyField.
    actionStatus = action === "copy" ? "" : String(parsed.message || "Done")
    lastError = ""
    if (action === "copy") lastCopyField = String(parsed.field || "password")
    if (parsed.status) vaultStatus = String(parsed.status)
    if (!unlocked) items = []
    // A fresh unlock syncs in the background: the panel shows cached results
    // at once and refreshes them when the sync lands.
    if (action === "unlock" && syncOnUnlock) _syncAfterUnlock = true
    actionMessageTimer.restart()
    actionCompleted(action, true)
    Qt.callLater(handleScreenLock)
    if (action === "unlock" || action === "lock" || action === "logout" || action === "sync") refreshTimer.restart()
  }

  Component.onCompleted: refresh()
  onSettingsChanged: {
    refreshTimer.restart()
    Qt.callLater(handleScreenLock)
  }
  onSystemLockServiceChanged: Qt.callLater(handleScreenLock)
  onLockOnScreenLockChanged: Qt.callLater(handleScreenLock)

  Connections {
    target: root.systemLockService
    function onLockedChanged() { root.handleScreenLock() }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  Timer {
    id: refreshTimer
    interval: 350
    onTriggered: root.refresh()
  }

  Timer {
    id: actionMessageTimer
    interval: 3500
    onTriggered: root.actionStatus = ""
  }

  Timer {
    id: screenLockRetry
    interval: 250
    onTriggered: root.handleScreenLock()
  }

  Process {
    id: statusProcess
    command: ["python3", root.helperPath, "request", "--timeout", "20"]
    stdinEnabled: true
    onStarted: write(root._statusInput + "\n")
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyStatus(text)
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: root.statusBusy = false
  }

  Process {
    id: searchProcess
    command: ["python3", root.helperPath, "request", "--timeout", "55"]
    stdinEnabled: true
    onStarted: write(root._searchInput + "\n")
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applySearch(text)
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: {
      var cancelled = root._searchCancelled
      root.searchBusy = false
      if (root._searchQueued) {
        var next = root._queuedQuery
        root._searchQueued = false
        root._queuedQuery = ""
        root.search(next)
      } else if (!cancelled) root.searchCompleted()
    }
  }

  Process {
    id: actionProcess
    command: ["python3", root.helperPath, "request", "--timeout", "90"]
    stdinEnabled: true
    onStarted: write(root._actionInput + "\n")
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyAction(text)
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: {
      root.actionBusy = false
      if (root._screenLockPending) {
        root._syncAfterUnlock = false
        screenLockRetry.restart()
      } else if (root._syncAfterUnlock) {
        root._syncAfterUnlock = false
        root.sync()
      }
    }
  }

  Process {
    id: desktopProcess
    command: ["python3", root.helperPath, "open-desktop"]
    onExited: function(exitCode, exitStatus) {
      root.actionBusy = false
      root.actionStatus = ""
      if (exitCode === 0) actionMessageTimer.restart()
      else root.lastError = "The Bitwarden desktop app isn't installed"
    }
  }
}
