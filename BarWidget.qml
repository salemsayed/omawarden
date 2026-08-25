import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "io.github.salemsayed.omawarden"
  // Moving a bar widget briefly overlaps its old and replacement instances.
  // Wait for the retired slot to release this process-wide IPC target.
  property bool ipcRegistrationReady: false

  readonly property var service: panelLoader.item ? panelLoader.item.service : null
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  readonly property string state: service
    ? (service.vaultStatus === "checking" ? "checking" : (service.ready ? service.vaultStatus : "unavailable"))
    : "checking"
  readonly property bool working: service ? service.actionBusy === true : false
  readonly property bool needsAttention: state === "error" || state === "unavailable" || state === "unauthenticated"
  readonly property color glyphColor: needsAttention
    ? (bar ? bar.urgent : Color.urgent)
    : (state === "unlocked" ? Color.accent : (bar ? bar.barForeground : Color.foreground))

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if (target.service && typeof target.service.refresh === "function") target.service.refresh()
    if (unlockLoader.item) unlockLoader.item.shell = root.bar ? root.bar.shell : null
  }

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }
  function openSettings() {
    if (!panelLoader.item) return
    panelLoader.item.settingsOpen = true
    panelLoader.item.open()
  }
  function openUnlock(config) {
    if (!unlockLoader.item || !root.service || root.service.unlocked) return false
    var opened = unlockLoader.item.open(JSON.stringify({ config: config || ({}) }))
    if (opened === true) root.close()
    return opened === true
  }
  // Open straight into a search — handy behind a keybinding such as
  // `omarchy-shell io.github.salemsayed.omawarden search github`.
  function openSearch(query) {
    if (!panelLoader.item) return
    panelLoader.item.settingsOpen = false
    panelLoader.item.searchModeRequested = true
    panelLoader.item.open()
    panelLoader.item.query = Model.sanitizeQuery(query)
    panelLoader.item.focusSearch(false)
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()
  Component.onCompleted: ipcRegistrationTimer.start()

  Timer {
    id: ipcRegistrationTimer
    interval: 100
    onTriggered: root.ipcRegistrationReady = true
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  // Keep the password surface private to the bar widget. Advertising it as a
  // second plugin kind under this same id makes Omarchy's numbered-panel
  // router choose the overlay instead of the bar panel.
  Loader {
    id: unlockLoader
    active: true
    source: Qt.resolvedUrl("UnlockPrompt.qml")
    visible: false
    onLoaded: root.injectPanel()
  }

  Connections {
    target: unlockLoader.item
    function onUnlockSucceeded() {
      if (root.service) root.service.nativeUnlockComplete()
    }
    function onUnlockCancelled() {
      if (root.service) root.service.nativeUnlockCancelled()
    }
  }

  Connections {
    target: root.service
    function onUnlockedChanged() {
      if (root.service && root.service.unlocked && unlockLoader.item)
        unlockLoader.item.close()
    }
  }

  IpcHandler {
    enabled: root.ipcRegistrationReady
    target: root.moduleName
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }
    function settings(): void { root.openSettings() }
    function search(query: string): void { root.openSearch(query) }
    function refresh(): string { if (root.service) root.service.refresh(); return "ok" }
    function sync(): string { if (root.service) root.service.sync(); return "ok" }
    function lock(): string { if (root.service) root.service.lock(); return "ok" }
    function unlock(): string { if (root.service) root.service.unlock(); return "ok" }
    function status(): string { return root.service ? root.service.statusText : "Checking…" }
  }

  QtObject {
    id: spin
    property real angle: 0
  }

  NumberAnimation {
    target: spin
    property: "angle"
    from: 0
    to: 360
    duration: 1400
    loops: Animation.Infinite
    running: root.working
    onRunningChanged: if (!running) spin.angle = 0
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // An unlock, sync, or copy swaps the lock for a turning spinner: those
    // are the only moments OmaWarden makes the user wait. Routine status
    // polling leaves the bar still.
    text: root.working ? "󰑓" : Model.statusGlyph(root.state)
    textRotation: spin.angle
    foreground: root.glyphColor
    active: root.state === "unlocked"
    tooltipText: Model.tooltip(root.service)
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) root.openSettings()
      else if (buttonCode === Qt.MiddleButton && root.service) {
        if (root.service.unlocked) root.service.sync()
        else root.service.refresh()
      } else root.togglePanel()
    }
  }
}
