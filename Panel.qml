import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.salemsayed.omawarden"
  ipcTarget: "io.github.salemsayed.omawarden.panel"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  property alias service: bitwarden
  property bool settingsOpen: false
  property string query: ""
  property int selectedIndex: 0
  property int selectedAction: 0
  property bool settingsEditing: false
  property bool searchModeRequested: false
  // Empty copy is honest only after this panel opening has received its
  // current search; before that the cleared list means "not loaded yet".
  property bool searchReady: false

  // A successful copy fills this to 1 and drains it over the configured
  // sensitive-clipboard lifetime, so the notice can count the paste window
  // down instead of just claiming something was copied.
  property real copyProgress: 0

  // Wall clock for the "synced 4 minutes ago" clause. Bound rather than
  // computed once so the header ages while the panel stays open.
  property real nowMs: 0

  // ---------------------------------------------------------------- palette
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Util.alpha(foreground, 0.62)
  readonly property color faint: Util.alpha(foreground, 0.42)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Corner treatment follows the theme the same way the shared kit does:
  // pill/rounded tiles when Hyprland rounds its corners, square when sharp.
  readonly property bool rounded: Style.cornerRadius > 0
  readonly property int tileRadius: rounded ? Style.space(8) : 0

  // Rows run edge to edge so their hover fill reads as a list row; their
  // text is inset by this much, and section headers match so labels align.
  readonly property int rowInset: Style.space(9)

  readonly property string displayStatus: bitwarden.vaultStatus === "checking"
    ? "checking" : (bitwarden.ready ? bitwarden.vaultStatus : "unavailable")
  readonly property bool attention: displayStatus === "error"
    || displayStatus === "unavailable" || displayStatus === "unauthenticated"
  readonly property color stateColor: displayStatus === "unlocked"
    ? accent : (attention ? urgent : foreground)
  readonly property bool browsing: query.trim() === ""
  readonly property bool searchLoading: !searchReady || bitwarden.searchBusy
  readonly property var currentItem: bitwarden.items.length > 0
    ? bitwarden.items[Math.max(0, Math.min(selectedIndex, bitwarden.items.length - 1))]
    : null
  readonly property var actions: Model.itemActions(currentItem)
  readonly property var gate: Model.gateCopy(
    displayStatus, bitwarden.ready, bitwarden.missingRequirements, bitwarden.unlockPrompt)
  readonly property var steps: Model.setupSteps(displayStatus, bitwarden.ready)
  readonly property string serverName: Model.serverLabel(bitwarden.configuredServerUrl, bitwarden.serverUrl)

  readonly property string heroMeta: settingsOpen
    ? "Settings"
    : Model.statusDetail(displayStatus, bitwarden.lastSync, nowMs)
  readonly property string heroDetail: settingsOpen || !bitwarden.unlocked || browsing || searchLoading
    ? "" : Model.matchLabel(bitwarden.items.length)

  readonly property int clipboardRemaining: Math.ceil(copyProgress * bitwarden.clipboardTimeoutSec)
  readonly property bool copyNoticeShown: copyProgress > 0 && bitwarden.lastCopyField !== ""
    && bitwarden.lastError === "" && bitwarden.actionStatus === ""
  readonly property string noticeText: bitwarden.lastError !== ""
    ? bitwarden.lastError
    : (bitwarden.displayActionStatus !== ""
      ? bitwarden.displayActionStatus
      : (copyNoticeShown ? Model.copyNotice(bitwarden.lastCopyField, clipboardRemaining) : ""))

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function persistSettings(changes) {
    var entry = { id: root.moduleName }
    for (var key in root.settings) if (key !== "id") entry[key] = root.settings[key]
    for (var changed in changes) entry[changed] = changes[changed]
    root.settings = entry
    if (root.hostWidget && "settings" in root.hostWidget) root.hostWidget.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  function focusForState() {
    root.searchModeRequested = false
    Qt.callLater(function() {
      if (!root.opened) return
      keyCatcher.forceActiveFocus()
    })
  }

  function focusSearch(selectExisting) {
    root.searchModeRequested = true
    Qt.callLater(function() {
      if (!root.opened || root.settingsOpen || !bitwarden.unlocked) return
      searchField.forceActiveFocus()
      if (selectExisting === true) searchField.selectAll()
    })
  }

  function prepareOpen() {
    root.searchReady = false
    root.nowMs = Date.now()
    // The service already polls status in the background. A fresh `bw status`
    // takes seconds on some systems and the single-file agent would make this
    // local index request wait behind it, so opening goes straight to search.
    if (bitwarden.unlocked && !root.settingsOpen) bitwarden.search(root.query)
    else if (!root.settingsOpen) bitwarden.refresh()
    if (root.searchModeRequested) focusSearch(false)
    else focusForState()
  }

  function open() {
    if (root.opened) prepareOpen()
    else root.controller.show()
  }

  function close() {
    root.query = ""
    root.settingsOpen = false
    root.searchModeRequested = false
    root.searchReady = false
    bitwarden.discardSearch()
    root.controller.hide()
  }

  function toggleSettings() {
    settingsOpen = !settingsOpen
    settingsEditing = false
    searchModeRequested = false
    if (!settingsOpen && root.opened && bitwarden.unlocked) {
      searchReady = false
      bitwarden.search(root.query)
    }
    focusForState()
  }

  function resetAction() {
    var preferred = Model.defaultAction(currentItem, bitwarden.defaultCopy)
    var actionIndex = actions.indexOf(preferred)
    selectedAction = actionIndex < 0 ? 0 : actionIndex
  }

  function selectRow(index) {
    if (bitwarden.items.length === 0) return
    selectedIndex = Math.max(0, Math.min(bitwarden.items.length - 1, index))
    resetAction()
  }

  function moveSelection(delta) {
    if (bitwarden.items.length === 0) return
    selectRow(selectedIndex + delta)
    ensureSelectedVisible()
  }

  function moveAction(delta) {
    if (!currentItem) return
    var next = selectedAction
    for (var count = 0; count < actions.length; count++) {
      next = (next + delta + actions.length) % actions.length
      if (Model.actionAvailable(currentItem, actions[next])) {
        selectedAction = next
        return
      }
    }
  }

  function actionForEnter() {
    if (Model.actionAvailable(currentItem, actions[selectedAction])) return actions[selectedAction]
    return Model.defaultAction(currentItem, bitwarden.defaultCopy)
  }

  function activate(action) {
    if (bitwarden.actionBusy) return
    var item = currentItem
    var chosen = action || actionForEnter()
    if (!item || chosen === "" || !Model.actionAvailable(item, chosen)) return
    if (chosen === "open") bitwarden.openUrl(item)
    else bitwarden.copy(item, chosen)
  }

  function ensureSelectedVisible() {
    Qt.callLater(function() {
      if (selectedIndex >= 0 && selectedIndex < resultList.count)
        resultList.positionViewAtIndex(selectedIndex, ListView.Contain)
    })
  }

  // The one thing the gate's big button does in each state.
  function stateAction() {
    if (bitwarden.busy) return
    if (!bitwarden.ready) bitwarden.installRequirements()
    else if (bitwarden.vaultStatus === "unauthenticated") bitwarden.login()
    else if (bitwarden.locked) bitwarden.unlock()
    else if (bitwarden.unlocked) bitwarden.sync()
    else bitwarden.refresh()
  }

  function openNativeUnlock(config) {
    var opened = root.hostWidget && typeof root.hostWidget.openUnlock === "function"
      ? root.hostWidget.openUnlock(config || ({})) : false
    if (opened !== true) bitwarden.nativeUnlockCancelled()
  }

  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function") return bar.switchPanelFrom(barIdentity, direction)
    return false
  }

  // Shortcuts shared by the search field and the key catcher so they behave
  // the same whether or not the cursor is in the search box. Returns true
  // when the event was handled.
  function handleShortcut(event) {
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
    var alt = (event.modifiers & Qt.AltModifier) !== 0
    var shift = (event.modifiers & Qt.ShiftModifier) !== 0
    if (ctrl && event.key === Qt.Key_F && bitwarden.unlocked && !settingsOpen) {
      focusSearch(true); return true
    }
    if (ctrl && event.key === Qt.Key_Comma) { toggleSettings(); return true }
    if (ctrl && event.key === Qt.Key_D) { bitwarden.openDesktop(); return true }
    if (settingsOpen) return false
    if (ctrl && event.key === Qt.Key_R) { bitwarden.unlocked ? bitwarden.sync() : bitwarden.refresh(); return true }
    if (ctrl && event.key === Qt.Key_L && bitwarden.unlocked) { bitwarden.lock(); return true }
    if (!bitwarden.unlocked) return false
    if (event.key === Qt.Key_Down) { moveSelection(1); return true }
    if (event.key === Qt.Key_Up) { moveSelection(-1); return true }
    if (event.key === Qt.Key_PageDown) { moveSelection(5); return true }
    if (event.key === Qt.Key_PageUp) { moveSelection(-5); return true }
    if (alt && event.key === Qt.Key_Right) { moveAction(1); return true }
    if (alt && event.key === Qt.Key_Left) { moveAction(-1); return true }
    if (shift && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
      activate(Model.alternateAction(bitwarden.defaultCopy, currentItem)); return true
    }
    if (ctrl && event.key === Qt.Key_C && searchField.selectedText === "") {
      activate(Model.isCard(currentItem) ? "number" : "password"); return true
    }
    if (ctrl && event.key === Qt.Key_B) {
      activate(Model.isCard(currentItem) ? "cardholder" : "username"); return true
    }
    if (ctrl && event.key === Qt.Key_T) {
      activate(Model.isCard(currentItem) ? "cardCode" : "totp"); return true
    }
    if (ctrl && event.key === Qt.Key_U && !Model.isCard(currentItem)) { activate("open"); return true }
    return false
  }

  onOpenedChanged: if (opened) prepareOpen()
  onQueryChanged: {
    searchReady = false
    selectedIndex = 0
    resetAction()
    searchDebounce.restart()
  }
  onCurrentItemChanged: resetAction()

  Service {
    id: bitwarden
    settings: root.settings
    shell: root.bar ? root.bar.shell : null
  }

  Connections {
    target: bitwarden
    function onNativeUnlockRequested(config) { root.openNativeUnlock(config) }
    function onSearchCompleted() {
      if (root.opened && bitwarden.unlocked) root.searchReady = true
      if (root.selectedIndex >= bitwarden.items.length)
        root.selectedIndex = Math.max(0, bitwarden.items.length - 1)
      root.resetAction()
      root.ensureSelectedVisible()
    }
    // The first open after a shell start races the status call: the panel asks
    // for a search while the vault still reads "checking", so nothing runs and
    // an unlocked vault greets the user with an empty list. Search as soon as
    // the state actually resolves.
    function onUnlockedChanged() {
      root.searchReady = false
      if (bitwarden.unlocked && root.opened && !root.settingsOpen) bitwarden.search(root.query)
      if (root.searchModeRequested && bitwarden.unlocked) root.focusSearch(false)
      else root.focusForState()
    }
    function onActionCompleted(action, ok) {
      if (ok && (action === "unlock" || action === "sync")) {
        searchAfterAction.restart()
        root.focusForState()
      }
      if (ok && (action === "lock" || action === "logout")) root.query = ""
      if (ok && action === "copy") clipboardCountdown.restart()
      else if (action === "lock" || action === "logout" || action === "copy") {
        // The agent dropped the clipboard (lock, sign-out) or never filled it.
        clipboardCountdown.stop()
        root.copyProgress = 0
      }
    }
  }

  // Mirrors the agent's bounded wl-copy lifetime. Purely cosmetic — the
  // clipboard is cleared by the agent, not by this animation.
  NumberAnimation {
    id: clipboardCountdown
    target: root
    property: "copyProgress"
    from: 1
    to: 0
    duration: Math.max(1, bitwarden.clipboardTimeoutSec) * 1000
    easing.type: Easing.Linear
  }

  Timer {
    id: searchDebounce
    // The agent searches a warm, metadata-only memory index. A short debounce
    // absorbs key-repeat noise without making normal typing feel delayed.
    interval: 90
    onTriggered: if (root.opened && bitwarden.unlocked && !root.settingsOpen) bitwarden.search(root.query)
  }

  Timer {
    id: searchAfterAction
    interval: 700
    onTriggered: if (root.opened && bitwarden.unlocked) bitwarden.search(root.query)
  }

  Timer {
    interval: 30000
    repeat: true
    running: root.opened
    onTriggered: root.nowMs = Date.now()
  }

  IpcHandler {
    enabled: root.hostWidget && root.hostWidget.ipcRegistrationReady === true
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function settings(): void { root.settingsOpen = true; root.open() }
    function search(query: string): void {
      root.settingsOpen = false
      root.searchModeRequested = true
      root.open()
      root.query = Model.sanitizeQuery(query)
      root.focusSearch(false)
    }
    function refresh(): string { bitwarden.refresh(); return "ok" }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    // Opening starts in command mode. Search is an explicit mode entered with
    // `/` or Ctrl+F, so single-letter panel shortcuts never steal query text.
    focusTarget: root.searchModeRequested && bitwarden.unlocked ? searchField : keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(520))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(700))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: searchField.activeFocus || root.settingsEditing
      onMoveRequested: function(dx, dy) {
        if (root.settingsOpen || !bitwarden.unlocked) return
        if (dy !== 0) root.moveSelection(dy)
        else if (dx !== 0) root.moveAction(dx)
      }
      onActivateRequested: {
        if (root.settingsOpen) return
        if (bitwarden.unlocked) root.activate("")
        else root.stateAction()
      }
      onCloseRequested: {
        if (root.settingsOpen) root.toggleSettings()
        else root.close()
      }
      onTabRequested: function(direction) {
        if (!root.settingsOpen) root.switchPanel(direction)
      }
      onTextKey: function(text) {
        var key = text.toLowerCase()
        if (key === "/" && bitwarden.unlocked && !root.settingsOpen) root.focusSearch(false)
        else if (key === "s") root.toggleSettings()
        else if (root.settingsOpen) return
        else if (key === "r") bitwarden.unlocked ? bitwarden.sync() : bitwarden.refresh()
        else if (key === "d") bitwarden.openDesktop()
        else if (key === "u" && !bitwarden.unlocked) root.stateAction()
      }
      // Modifier shortcuts arrive here as control characters that textKey
      // cannot name, so they are matched on the key code instead.
      Keys.onPressed: function(event) {
        if (keyCatcher.blocked) return
        if ((event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)) === 0) return
        if (root.handleShortcut(event)) event.accepted = true
      }

      Flickable {
        id: panelScroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: SlimScrollBar {}

        Column {
          id: content
          width: panelScroll.width
          spacing: Style.space(12)

          // ------------------------------------------------------------ header
          PanelHero {
            width: parent.width
            title: "OmaWarden"
            meta: root.heroMeta
            detail: root.heroDetail
            foreground: root.foreground
            fontFamily: root.fontFamily

            iconComponent: Component {
              StateBadge {
                size: Style.space(40)
                glyph: Model.statusGlyph(root.displayStatus)
                tint: root.stateColor
                busy: bitwarden.busy
              }
            }

            trailingControl: Component {
              Row {
                spacing: Style.space(2)
                PanelActionButton {
                  visible: !root.settingsOpen
                  iconText: "󰍹"
                  tooltipText: "Open the Bitwarden desktop app  ·  " + (bitwarden.unlocked ? "Ctrl+D" : "d")
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  onClicked: bitwarden.openDesktop()
                }
                PanelActionButton {
                  iconText: root.settingsOpen ? "󰁍" : "󰒓"
                  tooltipText: root.settingsOpen ? "Back  ·  Esc" : (bitwarden.unlocked ? "Settings  ·  Ctrl+," : "Settings  ·  s")
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  onClicked: root.toggleSettings()
                }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ------------------------------------------------------------ notice
          // Kept in the layout at zero height so appearing and clearing are
          // animated instead of snapping the rest of the panel up and down.
          Notice {
            width: parent.width
            shown: root.noticeText !== ""
            text: root.noticeText
            progress: root.copyNoticeShown ? root.copyProgress : 0
            tint: bitwarden.lastError !== ""
              ? root.urgent : (root.copyNoticeShown ? root.accent : root.foreground)
            glyph: bitwarden.lastError !== ""
              ? "󰀦" : (root.copyNoticeShown ? "󰆏" : "󰋼")
          }

          // ---------------------------------------------------------- settings
          Column {
            id: settingsView
            visible: root.settingsOpen
            width: parent.width
            spacing: Style.space(4)
            opacity: visible ? 1 : 0

            Behavior on opacity {
              NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
            }

            SectionHeader { glyph: "󰌾"; label: "LOCKING & UNLOCK" }

            ToggleRow {
              label: "Lock after inactivity"
              description: "Relock the vault when it goes unused"
              checked: bitwarden.inactivityLockEnabled
              onToggle: {
                if (bitwarden.inactivityLockEnabled)
                  root.persistSettings({ inactivityLockEnabled: false })
                else
                  root.persistSettings({
                    inactivityLockEnabled: true,
                    autoLockMinutes: bitwarden.autoLockMinutes > 0 ? bitwarden.autoLockMinutes : 15
                  })
              }
            }
            StepperRow {
              visible: bitwarden.inactivityLockEnabled
              label: "Inactivity delay"
              valueText: Model.minutesLabel(bitwarden.effectiveAutoLockMinutes)
              minusEnabled: bitwarden.effectiveAutoLockMinutes > 5
              plusEnabled: bitwarden.effectiveAutoLockMinutes < 240
              onMinus: root.persistSettings({ autoLockMinutes: Math.max(5, bitwarden.effectiveAutoLockMinutes - 5) })
              onPlus: root.persistSettings({ autoLockMinutes: Math.min(240, bitwarden.effectiveAutoLockMinutes + 5) })
            }
            ToggleRow {
              label: "Lock when the screen locks"
              description: "Follows Omarchy's lock screen, whatever the timer says"
              checked: bitwarden.lockOnScreenLock
              onToggle: root.persistSettings({ lockOnScreenLock: !bitwarden.lockOnScreenLock })
            }
            ChoiceRow {
              id: promptChoice
              label: "Unlock prompt"
              description: bitwarden.unlockPrompt === "native"
                ? "Drawn by the Omarchy shell" : "A separate password window · recommended"
              options: ["Pinentry", "Native"]
              value: bitwarden.unlockPrompt === "pinentry" ? "Pinentry" : "Native"
              onChanged: function(next) {
                root.persistSettings({ unlockPrompt: next === "Pinentry" ? "pinentry" : "native" })
              }
            }
            FieldRow {
              visible: bitwarden.unlockPrompt === "pinentry"
              label: "Pinentry command"
              value: bitwarden.pinentryCommand
              placeholder: "auto"
              hint: "auto picks one for you. Or name a pinentry program, on PATH or by full path."
              onSave: function(next) {
                root.persistSettings({ pinentryCommand: next === "" ? "auto" : next })
              }
            }

            SectionSpacer {}
            SectionHeader { glyph: "󰆏"; label: "CLIPBOARD & SEARCH" }

            StepperRow {
              label: "Clipboard timeout"
              description: "Copied secrets vanish when this timer ends"
              valueText: Model.secondsLabel(bitwarden.clipboardTimeoutSec)
              minusEnabled: bitwarden.clipboardTimeoutSec > 5
              plusEnabled: bitwarden.clipboardTimeoutSec < 120
              onMinus: root.persistSettings({ clipboardTimeoutSec: bitwarden.clipboardTimeoutSec - 5 })
              onPlus: root.persistSettings({ clipboardTimeoutSec: bitwarden.clipboardTimeoutSec + 5 })
            }
            ChoiceRow {
              label: "Enter copies"
              description: "For logins; cards start with the number"
              options: ["Password", "Username"]
              value: Model.primaryAction(bitwarden.defaultCopy) === "username" ? "Username" : "Password"
              onChanged: function(next) { root.persistSettings({ defaultCopy: next }) }
            }
            ToggleRow {
              label: "Show account names"
              description: "Usernames and cardholders · turn off for privacy"
              checked: bitwarden.showUsernames
              onToggle: root.persistSettings({ showUsernames: !bitwarden.showUsernames })
            }
            StepperRow {
              label: "Results shown"
              valueText: String(bitwarden.resultLimit)
              minusEnabled: bitwarden.resultLimit > 5
              plusEnabled: bitwarden.resultLimit < 50
              onMinus: root.persistSettings({ resultLimit: bitwarden.resultLimit - 5 })
              onPlus: root.persistSettings({ resultLimit: bitwarden.resultLimit + 5 })
            }
            ToggleRow {
              label: "Sync after unlock"
              description: "Pull changes from the server each time you unlock"
              checked: bitwarden.syncOnUnlock
              onToggle: root.persistSettings({ syncOnUnlock: !bitwarden.syncOnUnlock })
            }

            SectionSpacer {}
            SectionHeader { glyph: "󰀄"; label: "ACCOUNT" }

            AccountRow {}

            FieldRow {
              label: "Server URL"
              value: bitwarden.configuredServerUrl
              placeholder: "https://vault.example.com"
              hint: bitwarden.authenticated
                ? "Takes effect the next time you sign in. Leave empty for bitwarden.com."
                : "Applied automatically when you sign in. Leave empty for bitwarden.com."
              onSave: function(next) { root.persistSettings({ serverUrl: next }) }
            }
            FieldRow {
              label: "CLI profile folder"
              value: bitwarden.appDataDir
              placeholder: "Default profile"
              hint: "A separate CLI data folder, for keeping a second account apart"
              onSave: function(next) { root.persistSettings({ appDataDir: next }) }
            }

            SectionSpacer {}
            SectionHeader { glyph: "󰒓"; label: "ADVANCED" }

            FieldRow {
              label: "Bitwarden CLI command"
              value: bitwarden.cliCommand
              placeholder: "bw"
              hint: "A command name or full path, arguments allowed."
              onSave: function(next) { root.persistSettings({ cliCommand: next === "" ? "bw" : next }) }
            }
            StepperRow {
              label: "Status check"
              description: "How often the bar re-reads the local vault state"
              valueText: Model.secondsLabel(bitwarden.refreshIntervalSec)
              minusEnabled: bitwarden.refreshIntervalSec > 10
              plusEnabled: bitwarden.refreshIntervalSec < 3600
              onMinus: root.persistSettings({ refreshIntervalSec: Math.max(10, bitwarden.refreshIntervalSec - 10) })
              onPlus: root.persistSettings({ refreshIntervalSec: Math.min(3600, bitwarden.refreshIntervalSec + 10) })
            }

            Item { width: 1; height: Style.space(4) }

            RequirementList {
              compact: true
            }

            Item { width: 1; height: Style.space(4) }

            Paragraph {
              faded: true
              text: "Settings live in Omarchy's shell.json and can also be changed with "
                + "omarchy bar set " + root.moduleName + " <key> <value>."
            }
          }

          // -------------------------------------------------------------- gate
          // Everything before an open vault: missing packages, signed out,
          // locked, or an unreadable state. One badge, one sentence, one action.
          Column {
            id: gateView
            visible: !root.settingsOpen && (!bitwarden.unlocked || !bitwarden.ready)
            width: parent.width
            spacing: Style.space(12)
            opacity: visible ? 1 : 0

            Behavior on opacity {
              NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
            }

            StepStrip {
              visible: root.steps.length > 0
              anchors.horizontalCenter: parent.horizontalCenter
              steps: root.steps
            }

            Item { width: 1; height: Style.space(2) }

            StateBadge {
              anchors.horizontalCenter: parent.horizontalCenter
              size: Style.space(58)
              glyph: root.gate.glyph
              tint: root.stateColor
              busy: bitwarden.busy
              fontSize: Style.font.display
            }

            Text {
              textFormat: Text.PlainText
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.gate.title
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
            }

            Text {
              textFormat: Text.PlainText
              visible: text !== ""
              x: Style.space(22)
              width: parent.width - Style.space(44)
              text: root.gate.body
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: Text.WordWrap
              horizontalAlignment: Text.AlignHCenter
              lineHeight: 1.25
            }

            RequirementList {
              visible: !bitwarden.ready && root.displayStatus !== "checking"
              x: Style.space(40)
              width: parent.width - Style.space(80)
            }

            Button {
              visible: root.gate.action !== ""
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.gate.action
              iconText: root.gate.glyph
              bordered: true
              active: true
              foreground: root.accent
              accent: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.subtitle
              horizontalPadding: Style.space(16)
              verticalPadding: Style.space(8)
              enabled: !bitwarden.busy
              onClicked: root.stateAction()
            }

            // Where a sign-in will land, so a self-hosted user notices before
            // the terminal opens rather than after.
            Text {
              textFormat: Text.PlainText
              visible: bitwarden.ready && bitwarden.vaultStatus === "unauthenticated"
              anchors.horizontalCenter: parent.horizontalCenter
              width: parent.width - Style.space(44)
              horizontalAlignment: Text.AlignHCenter
              text: "Signing in to " + root.serverName + ". Self-hosted? Set the server URL in Settings first."
              color: root.faint
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Flow {
              anchors.horizontalCenter: parent.horizontalCenter
              width: parent.width - Style.space(24)
              spacing: Style.space(12)
              KeyHint { visible: root.gate.action !== ""; keys: ["↵"]; label: root.gate.action.toLowerCase() }
              KeyHint { keys: ["r"]; label: "refresh" }
              KeyHint { keys: ["s"]; label: "settings" }
              KeyHint { keys: ["d"]; label: "desktop app" }
            }

            Item { width: 1; height: Style.space(4) }
          }

          // ------------------------------------------------------------- vault
          Column {
            id: vaultView
            visible: !root.settingsOpen && bitwarden.unlocked && bitwarden.ready
            width: parent.width
            spacing: Style.space(10)
            opacity: visible ? 1 : 0

            Behavior on opacity {
              NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
            }

            RowLayout {
              width: parent.width
              spacing: Style.space(6)

              Item {
                Layout.fillWidth: true
                implicitHeight: searchField.implicitHeight

                TextField {
                  id: searchField
                  anchors.fill: parent
                  leftPadding: Style.space(32)
                  rightPadding: clearButton.visible ? clearButton.width + Style.space(12) : Style.space(10)
                  foreground: root.foreground
                  placeholderText: activeFocus ? "Search vault…" : "Press / or Ctrl+F to search"

                  // Typing replaces any binding on `text`, so field and panel
                  // are kept in step explicitly: the field pushes what the user
                  // types, and the panel pushes its own clears (Esc, close,
                  // lock) back into the field.
                  Component.onCompleted: text = root.query
                  onTextChanged: if (root.query !== text) root.query = text
                  onActiveFocusChanged: if (activeFocus) root.searchModeRequested = true

                  Connections {
                    target: root
                    function onQueryChanged() {
                      if (searchField.text !== root.query) searchField.text = root.query
                    }
                  }

                  Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_Escape) {
                      if (text !== "") root.query = ""
                      else {
                        root.searchModeRequested = false
                        keyCatcher.forceActiveFocus()
                      }
                      event.accepted = true
                    } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
                      root.switchPanel(event.key === Qt.Key_Backtab || (event.modifiers & Qt.ShiftModifier) ? -1 : 1)
                      event.accepted = true
                    } else if (root.handleShortcut(event)) {
                      event.accepted = true
                    }
                  }
                  onAccepted: root.activate("")
                }

                Text {
                  textFormat: Text.PlainText
                  anchors.left: parent.left
                  anchors.leftMargin: Style.space(12)
                  anchors.verticalCenter: parent.verticalCenter
                  text: "󰍉"
                  color: searchField.activeFocus ? root.accent : root.faint
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.icon
                  Behavior on color { ColorAnimation { duration: 120 } }
                }

                PanelActionButton {
                  id: clearButton
                  visible: root.query !== ""
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(4)
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "󰅖"
                  tooltipText: "Clear  ·  Esc"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  size: Style.space(22)
                  onClicked: { root.query = ""; searchField.forceActiveFocus() }
                }
              }

              PanelActionButton {
                iconText: "󰑐"
                tooltipText: "Sync with the server  ·  Ctrl+R"
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                size: searchField.implicitHeight
                enabled: !bitwarden.actionBusy
                onClicked: bitwarden.sync()
              }
              PanelActionButton {
                iconText: "󰌾"
                tooltipText: "Lock vault  ·  Ctrl+L"
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                size: searchField.implicitHeight
                enabled: !bitwarden.actionBusy
                onClicked: bitwarden.lock()
              }
            }

            ProgressLine {
              width: parent.width
              active: root.searchLoading
            }

            // Empty and no-match states share one shape so the panel does not
            // change silhouette while you type.
            Column {
              visible: bitwarden.items.length === 0
              width: parent.width
              spacing: Style.space(6)

              Item { width: 1; height: Style.space(14) }

              Text {
                textFormat: Text.PlainText
                id: emptyGlyph
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.searchLoading ? "󰑓" : (root.browsing ? "󰍉" : "󰧬")
                color: root.faint
                font.family: root.fontFamily
                font.pixelSize: Style.font.display

                RotationAnimator on rotation {
                  from: 0
                  to: 360
                  duration: 1400
                  loops: Animation.Infinite
                  running: root.searchLoading
                }

                onTextChanged: if (!root.searchLoading) rotation = 0
              }

              Text {
                textFormat: Text.PlainText
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.searchLoading
                  ? (root.browsing ? "Loading your vault…" : "Searching…")
                  : (root.browsing ? "No logins or cards yet" : "No matching items")
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }

              Text {
                textFormat: Text.PlainText
                anchors.horizontalCenter: parent.horizontalCenter
                visible: !root.searchLoading
                width: parent.width - Style.space(44)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: root.browsing
                  ? "Logins and cards you add in Bitwarden show up here after a sync."
                  : "Nothing named “" + root.query.trim() + "” — try an account, site, card brand, or last four digits."
                color: root.faint
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Item { width: 1; height: Style.space(10) }
            }

            ListView {
              id: resultList
              visible: bitwarden.items.length > 0
              width: parent.width
              height: visible ? Math.min(contentHeight, Style.space(430)) : 0
              model: bitwarden.items
              spacing: Style.space(3)
              clip: true
              boundsBehavior: Flickable.StopAtBounds
              ScrollBar.vertical: SlimScrollBar {}

              delegate: Column {
                id: rowDelegate
                required property var modelData
                required property int index
                width: resultList.width
                spacing: Style.space(3)

                SectionLabel {
                  visible: Model.isSectionStart(bitwarden.items, rowDelegate.index, root.browsing)
                  text: Model.sectionLabel(rowDelegate.modelData, true)
                  first: rowDelegate.index === 0
                }

                ResultRow {
                  width: rowDelegate.width
                  item: rowDelegate.modelData
                  rowIndex: rowDelegate.index
                }
              }
            }

            PanelSeparator {
              visible: bitwarden.items.length > 0
              foreground: root.foreground
            }

            Flow {
              visible: bitwarden.items.length > 0
              width: parent.width
              spacing: Style.space(11)
              KeyHint {
                keys: searchField.activeFocus ? ["Esc"] : ["/"]
                label: searchField.activeFocus ? "command mode" : "search"
              }
              KeyHint {
                keys: ["↵"]
                label: Model.actionLabel(Model.primaryAction(bitwarden.defaultCopy, root.currentItem)).toLowerCase()
              }
              KeyHint {
                visible: Model.alternateAction(bitwarden.defaultCopy, root.currentItem) !== ""
                keys: ["⇧", "↵"]
                label: Model.actionLabel(Model.alternateAction(bitwarden.defaultCopy, root.currentItem)).toLowerCase()
              }
              KeyHint { keys: ["Ctrl", "T"]; label: Model.isCard(root.currentItem) ? "security code" : "code" }
              KeyHint { visible: !Model.isCard(root.currentItem); keys: ["Ctrl", "U"]; label: "open site" }
            }
          }
        }
      }
    }
  }

  // ============================================================ components

  // Rounded state tile behind the lock glyph — the panel's one piece of
  // color. `busy` orbits a dot around it instead of swapping the glyph, so
  // the state stays readable while work is in flight.
  component StateBadge: BorderSurface {
    id: badge
    property string glyph: ""
    property color tint: root.foreground
    property bool busy: false
    property real size: Style.space(40)
    property real fontSize: Style.font.iconLarge

    implicitWidth: size
    implicitHeight: size
    radius: root.rounded ? Math.round(size / 2) : 0
    color: Util.alpha(tint, 0.13)
    borderSpec: Border.flat(Util.alpha(tint, 0.32), 1)

    Behavior on color { ColorAnimation { duration: 180 } }

    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: badge.glyph
      color: badge.tint
      font.family: root.fontFamily
      font.pixelSize: badge.fontSize
    }

    Item {
      anchors.fill: parent
      visible: badge.busy

      Rectangle {
        width: Style.space(4)
        height: width
        radius: width / 2
        color: badge.tint
        x: parent.width / 2 - width / 2
        y: -Style.spaceReal(2)
      }

      RotationAnimator on rotation {
        from: 0
        to: 360
        duration: 1600
        loops: Animation.Infinite
        running: badge.busy
      }
    }
  }

  // Install → Sign in → Unlock, with the current step lit. Tells a new user
  // how far along they are instead of presenting each state as a dead end.
  component StepStrip: Row {
    id: strip
    property var steps: []
    spacing: Style.space(6)

    Repeater {
      model: strip.steps

      Row {
        id: stepItem
        required property var modelData
        required property int index
        readonly property bool done: modelData.state === "done"
        readonly property bool current: modelData.state === "current"
        readonly property color tone: done || current ? root.accent : root.faint
        spacing: Style.space(6)

        BorderSurface {
          anchors.verticalCenter: parent.verticalCenter
          implicitWidth: Style.space(18)
          implicitHeight: Style.space(18)
          radius: root.rounded ? Style.space(9) : 0
          color: stepItem.done ? Util.alpha(root.accent, 0.22) : (stepItem.current ? Util.alpha(root.accent, 0.12) : "transparent")
          borderSpec: Border.flat(Util.alpha(stepItem.tone, stepItem.current ? 0.9 : 0.4), 1)

          Text {
            textFormat: Text.PlainText
            anchors.centerIn: parent
            text: stepItem.done ? "󰄬" : String(stepItem.index + 1)
            color: stepItem.tone
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }
        }

        Text {
          textFormat: Text.PlainText
          anchors.verticalCenter: parent.verticalCenter
          text: stepItem.modelData.label
          color: stepItem.current ? root.foreground : (stepItem.done ? root.dim : root.faint)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: stepItem.current
        }

        Rectangle {
          visible: stepItem.index < strip.steps.length - 1
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(16)
          height: 1
          color: Util.alpha(root.foreground, 0.18)
        }
      }
    }
  }

  // One line per runtime requirement with a check or a cross. In the gate it
  // shows what Install will fetch; in Settings it doubles as a health check
  // with its own install button when something is missing.
  component RequirementList: Column {
    id: requirements
    property bool compact: false
    readonly property var rows: Model.requirementRows(
      bitwarden.dependencies, bitwarden.unlockPrompt === "pinentry")
    readonly property bool allOk: bitwarden.ready

    width: parent ? parent.width : implicitWidth
    spacing: Style.space(compact ? 2 : 5)

    Item {
      visible: requirements.compact
      width: parent.width
      implicitHeight: Math.max(requirementLabels.implicitHeight, installButton.implicitHeight) + Style.space(6)

      RowLabels {
        id: requirementLabels
        anchors.left: parent.left
        anchors.right: installButton.left
        anchors.leftMargin: root.rowInset
        anchors.rightMargin: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter
        label: "Requirements"
        description: requirements.allOk ? "Everything OmaWarden needs is installed" : "Something is missing"
      }

      Button {
        id: installButton
        anchors.right: parent.right
        anchors.rightMargin: root.rowInset
        anchors.verticalCenter: parent.verticalCenter
        visible: !requirements.allOk
        text: "Install"
        iconText: "󰏔"
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        onClicked: bitwarden.installRequirements()
      }
    }

    Repeater {
      model: requirements.rows

      Row {
        id: requirementRow
        required property var modelData
        x: requirements.compact ? root.rowInset + Style.space(2) : 0
        spacing: Style.space(8)

        Text {
          textFormat: Text.PlainText
          anchors.verticalCenter: parent.verticalCenter
          text: requirementRow.modelData.ok ? "󰄬" : "󰅖"
          color: requirementRow.modelData.ok ? root.accent : root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          textFormat: Text.PlainText
          anchors.verticalCenter: parent.verticalCenter
          text: requirementRow.modelData.label
          color: requirementRow.modelData.ok ? root.dim : root.foreground
          font.family: root.fontFamily
          font.pixelSize: requirements.compact ? Style.font.caption : Style.font.bodySmall
        }

        Text {
          textFormat: Text.PlainText
          anchors.verticalCenter: parent.verticalCenter
          text: requirementRow.modelData.detail
          color: root.faint
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  // "Signed in to vault.example.com" with a two-tap sign-out: the first
  // click arms the button, the second within a few seconds signs out.
  // Signing back in needs email, password and a two-step code, so a plain
  // one-click button would be a trap.
  component AccountRow: Item {
    id: accountRow
    property bool armed: false

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(accountLabels.implicitHeight, signOutButton.implicitHeight) + Style.space(10)

    Timer {
      id: disarmTimer
      interval: 4000
      onTriggered: accountRow.armed = false
    }

    RowLabels {
      id: accountLabels
      anchors.left: parent.left
      anchors.right: signOutButton.left
      anchors.leftMargin: root.rowInset
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      label: bitwarden.authenticated ? "Signed in to " + root.serverName : "Signed out"
      description: bitwarden.authenticated
        ? (accountRow.armed ? "Signing back in needs your email, password and two-step code" : "Sign out to switch accounts or servers")
        : "Sign in from the main page"
    }

    Button {
      id: signOutButton
      anchors.right: parent.right
      anchors.rightMargin: root.rowInset
      anchors.verticalCenter: parent.verticalCenter
      visible: bitwarden.authenticated
      text: accountRow.armed ? "Confirm sign out" : "Sign out"
      iconText: "󰍃"
      bordered: true
      foreground: accountRow.armed ? root.urgent : root.foreground
      accent: accountRow.armed ? root.urgent : root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      enabled: !bitwarden.actionBusy
      onClicked: {
        if (!accountRow.armed) {
          accountRow.armed = true
          disarmTimer.restart()
          return
        }
        accountRow.armed = false
        disarmTimer.stop()
        bitwarden.logout()
      }
    }
  }

  // Inline status strip: agent messages, errors, and the clipboard countdown.
  component Notice: BorderSurface {
    id: notice
    property bool shown: false
    property string glyph: ""
    property string text: ""
    property color tint: root.foreground
    property real progress: 0

    readonly property real fullHeight: noticeRow.implicitHeight + Style.space(16)

    visible: height > 1
    clip: true
    height: shown ? fullHeight : 0
    opacity: shown ? 1 : 0
    radius: Style.cornerRadius
    color: Util.alpha(tint, 0.09)
    borderSpec: Border.flat(Util.alpha(tint, 0.24), 1)

    Behavior on height { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: 160 } }
    Behavior on color { ColorAnimation { duration: 180 } }

    Row {
      id: noticeRow
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      anchors.topMargin: Style.space(8)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: notice.glyph
        color: notice.tint
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
      }

      Text {
        textFormat: Text.PlainText
        width: noticeRow.width - x
        text: notice.text
        color: notice.tint
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }
    }

    // Drains left to right for the sensitive-clipboard lifetime.
    Rectangle {
      anchors.left: parent.left
      anchors.bottom: parent.bottom
      anchors.margins: Style.space(1)
      height: Style.space(2)
      width: (parent.width - Style.space(2)) * Math.max(0, Math.min(1, notice.progress))
      radius: height / 2
      color: notice.tint
      opacity: notice.progress > 0 ? 0.85 : 0
    }
  }

  // Indeterminate sweep shown while a vault search is in flight.
  component ProgressLine: Item {
    id: line
    property bool active: false

    implicitHeight: Style.space(2)
    opacity: active ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Rectangle {
      anchors.fill: parent
      radius: height / 2
      color: Util.alpha(root.foreground, 0.09)
    }

    Rectangle {
      id: sweep
      width: parent.width * 0.3
      height: parent.height
      radius: height / 2
      color: root.accent

      SequentialAnimation on x {
        running: line.active
        loops: Animation.Infinite
        NumberAnimation { from: 0; to: line.width - sweep.width; duration: 850; easing.type: Easing.InOutQuad }
        NumberAnimation { from: line.width - sweep.width; to: 0; duration: 850; easing.type: Easing.InOutQuad }
      }
    }
  }

  component SlimScrollBar: ScrollBar {
    id: slim
    policy: ScrollBar.AsNeeded
    implicitWidth: Style.space(7)
    padding: Style.space(2)

    background: Item {}
    contentItem: Rectangle {
      implicitWidth: Style.space(3)
      radius: width / 2
      color: Util.alpha(root.foreground, slim.pressed ? 0.5 : 0.22)
      opacity: slim.active || slim.hovered ? 1 : 0.55
      Behavior on opacity { NumberAnimation { duration: 200 } }
      Behavior on color { ColorAnimation { duration: 120 } }
    }
  }

  component SectionHeader: Row {
    id: sectionHeader
    property string glyph: ""
    property string label: ""

    x: root.rowInset
    spacing: Style.space(7)
    topPadding: Style.space(2)
    bottomPadding: Style.space(2)

    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      text: sectionHeader.glyph
      color: root.faint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    PanelSectionHeader {
      textFormat: Text.PlainText
      text: sectionHeader.label
      foreground: root.foreground
      fontFamily: root.fontFamily
    }
  }

  // Group label above a run of result rows while browsing.
  component SectionLabel: Item {
    id: sectionLabel
    property string text: ""
    property bool first: false
    width: parent ? parent.width : implicitWidth
    implicitHeight: visible ? sectionText.implicitHeight + Style.space(first ? 4 : 12) : 0

    Text {
      textFormat: Text.PlainText
      id: sectionText
      x: root.rowInset
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(2)
      text: sectionLabel.text.toUpperCase()
      color: root.faint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 1.2
    }
  }

  // Rule plus breathing room between settings sections.
  component SectionSpacer: Column {
    width: parent ? parent.width : implicitWidth
    spacing: Style.space(10)
    topPadding: Style.space(6)
    Item { width: 1; height: 1 }
    PanelSeparator { foreground: root.foreground }
  }

  component Paragraph: Text {
    textFormat: Text.PlainText
    property bool faded: false
    x: root.rowInset
    width: (parent ? parent.width : implicitWidth) - root.rowInset * 2
    color: faded ? root.faint : root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
    lineHeight: 1.3
    bottomPadding: Style.space(4)
  }

  // Current value of a setting, sized like a chip so the row has a right edge
  // to land on instead of loose text.
  component ValueChip: BorderSurface {
    id: chip
    property string text: ""
    property color tint: root.foreground

    implicitWidth: Math.max(Style.space(52), chipText.implicitWidth + Style.space(16))
    implicitHeight: chipText.implicitHeight + Style.space(7)
    radius: Style.cornerRadius
    color: Util.alpha(tint, 0.05)
    borderSpec: Border.flat(Util.alpha(tint, 0.15), 1)

    Text {
      textFormat: Text.PlainText
      id: chipText
      anchors.centerIn: parent
      text: chip.text
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  component RowLabels: Column {
    id: rowLabels
    property string label: ""
    property string description: ""

    spacing: Style.space(2)

    Text {
      textFormat: Text.PlainText
      width: rowLabels.width
      text: rowLabels.label
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }

    Text {
      textFormat: Text.PlainText
      visible: rowLabels.description !== ""
      width: rowLabels.width
      text: rowLabels.description
      color: root.faint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }

  component StepperRow: Item {
    id: stepperRow
    property string label: ""
    property string description: ""
    property string valueText: ""
    property bool minusEnabled: true
    property bool plusEnabled: true
    signal minus()
    signal plus()

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(stepperLabels.implicitHeight, stepperControls.implicitHeight) + Style.space(10)

    RowLabels {
      id: stepperLabels
      anchors.left: parent.left
      anchors.right: stepperControls.left
      anchors.leftMargin: root.rowInset
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      label: stepperRow.label
      description: stepperRow.description
    }

    Row {
      id: stepperControls
      anchors.right: parent.right
      anchors.rightMargin: root.rowInset
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(5)

      ValueChip {
        anchors.verticalCenter: parent.verticalCenter
        text: stepperRow.valueText
      }
      PanelActionButton {
        anchors.verticalCenter: parent.verticalCenter
        iconText: "󰍴"
        tooltipText: "Less"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        enabled: stepperRow.minusEnabled
        onClicked: stepperRow.minus()
      }
      PanelActionButton {
        anchors.verticalCenter: parent.verticalCenter
        iconText: "󰐕"
        tooltipText: "More"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        enabled: stepperRow.plusEnabled
        onClicked: stepperRow.plus()
      }
    }
  }

  // The settings page has no keyboard cursor of its own, so hover is the only
  // cursor here and drives the row highlight directly.
  component ToggleRow: CursorSurface {
    id: toggleRow
    property string label: ""
    property string description: ""
    property bool checked: false
    signal toggle()

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(toggleLabels.implicitHeight, toggleSwitch.implicitHeight) + Style.space(9)
    foreground: root.foreground
    accent: root.accent
    hasCursor: toggleMouse.containsMouse

    MouseArea {
      id: toggleMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: toggleRow.toggle()
    }

    RowLabels {
      id: toggleLabels
      anchors.left: parent.left
      anchors.right: toggleSwitch.left
      anchors.leftMargin: root.rowInset
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      label: toggleRow.label
      description: toggleRow.description
    }

    ToggleSwitch {
      id: toggleSwitch
      anchors.right: parent.right
      anchors.rightMargin: root.rowInset
      anchors.verticalCenter: parent.verticalCenter
      checked: toggleRow.checked
      interactive: false
      hasCursor: toggleMouse.containsMouse
      foreground: root.foreground
      accent: root.accent
      trackHeight: Style.space(20)
    }
  }

  component ChoiceRow: Item {
    id: choiceRow
    property string label: ""
    property string description: ""
    property var options: []
    property string value: ""
    signal changed(string next)

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(choiceLabels.implicitHeight, choiceGroup.implicitHeight) + Style.space(10)

    RowLabels {
      id: choiceLabels
      anchors.left: parent.left
      anchors.right: choiceGroup.left
      anchors.leftMargin: root.rowInset
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      label: choiceRow.label
      description: choiceRow.description
    }

    ButtonGroup {
      id: choiceGroup
      anchors.right: parent.right
      anchors.rightMargin: root.rowInset
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)
      options: choiceRow.options
      value: choiceRow.value
      foreground: root.foreground
      background: Color.popups.background
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      focusable: false
      onChanged: function(next) { choiceRow.changed(next) }
    }
  }

  // Label, text field, and an optional hint. Saves on Enter and when the
  // field loses focus, and says so for a moment, so there is no separate
  // button to hunt for.
  component FieldRow: Column {
    id: fieldRoot
    property string label: ""
    property string value: ""
    property string placeholder: ""
    property string hint: ""
    property bool justSaved: false
    signal save(string next)

    function commit() {
      var next = editor.text.trim()
      if (next === fieldRoot.value.trim()) return
      fieldRoot.save(next)
      fieldRoot.justSaved = true
      savedTimer.restart()
    }

    x: root.rowInset
    width: (parent ? parent.width : implicitWidth) - root.rowInset * 2
    spacing: Style.space(4)
    bottomPadding: Style.space(6)

    Timer {
      id: savedTimer
      interval: 1600
      onTriggered: fieldRoot.justSaved = false
    }

    Row {
      spacing: Style.space(6)

      Text {
        textFormat: Text.PlainText
        text: fieldRoot.label
        color: root.faint
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Text {
        textFormat: Text.PlainText
        text: "󰄬 Saved"
        visible: opacity > 0
        opacity: fieldRoot.justSaved ? 1 : 0
        color: root.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        Behavior on opacity { NumberAnimation { duration: 160 } }
      }
    }

    TextField {
      id: editor
      width: parent.width
      text: fieldRoot.value
      foreground: root.foreground
      placeholderText: fieldRoot.placeholder
      onActiveFocusChanged: {
        root.settingsEditing = activeFocus
        if (!activeFocus) fieldRoot.commit()
      }
      onAccepted: {
        fieldRoot.commit()
        keyCatcher.forceActiveFocus()
      }
      Keys.onEscapePressed: {
        text = fieldRoot.value
        keyCatcher.forceActiveFocus()
      }

      // A setting changed elsewhere (omarchy bar set, a preset chip) should
      // show up here without waiting for the next reopen.
      Connections {
        target: fieldRoot
        function onValueChanged() { if (!editor.activeFocus) editor.text = fieldRoot.value }
      }
    }

    Text {
      textFormat: Text.PlainText
      visible: fieldRoot.hint !== ""
      width: parent.width
      text: fieldRoot.hint
      color: root.faint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
      lineHeight: 1.25
    }
  }

  // Key caps plus what the key does — the panel's shortcut legend.
  component KeyHint: Row {
    id: hint
    property var keys: []
    property string label: ""

    spacing: Style.space(4)

    Repeater {
      model: hint.keys

      BorderSurface {
        required property string modelData
        anchors.verticalCenter: parent.verticalCenter
        implicitWidth: Math.max(Style.space(17), capText.implicitWidth + Style.space(8))
        implicitHeight: capText.implicitHeight + Style.space(4)
        radius: root.rounded ? Style.space(4) : 0
        color: Util.alpha(root.foreground, 0.06)
        borderSpec: Border.flat(Util.alpha(root.foreground, 0.18), 1)

        Text {
          textFormat: Text.PlainText
          id: capText
          anchors.centerIn: parent
          text: modelData
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      leftPadding: Style.space(2)
      text: hint.label
      color: root.faint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  component ResultRow: CursorSurface {
    id: resultRow
    required property var item
    required property int rowIndex

    hasCursor: root.selectedIndex === rowIndex
    readonly property bool groupStart: Model.isGroupStart(bitwarden.items, rowIndex)
    foreground: root.foreground
    accent: root.accent
    radius: Style.cornerRadius
    implicitHeight: rowContent.implicitHeight + Style.space(14)

    // Accent rail on the row the keyboard cursor owns.
    Rectangle {
      anchors.left: parent.left
      anchors.leftMargin: Style.space(3)
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(2)
      height: resultRow.hasCursor ? parent.height * 0.55 : 0
      radius: width / 2
      color: root.accent
      opacity: resultRow.hasCursor ? 1 : 0
      Behavior on height { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
      Behavior on opacity { NumberAnimation { duration: 130 } }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.LeftButton
      onEntered: root.selectRow(resultRow.rowIndex)
      onClicked: {
        root.selectRow(resultRow.rowIndex)
        root.activate("")
      }
    }

    RowLayout {
      id: rowContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: root.rowInset
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(10)

      // Monogram tile: an entry is recognizable by its first letter long
      // before the name has finished being read.
      BorderSurface {
        Layout.alignment: Qt.AlignVCenter
        implicitWidth: Style.space(30)
        implicitHeight: Style.space(30)
        radius: root.tileRadius
        color: resultRow.hasCursor ? Util.alpha(root.accent, 0.16) : Util.alpha(root.foreground, 0.05)
        borderSpec: resultRow.hasCursor ? Border.flat(Util.alpha(root.accent, 0.4), 1) : Border.none()

        Behavior on color { ColorAnimation { duration: 90 } }

        // Vaults sort alphabetically, so a browse list stacks the same initial
        // many rows deep. Only the first of each run carries it at full
        // strength; the rest recede into a quiet column.
        Text {
          textFormat: Text.PlainText
          anchors.centerIn: parent
          text: Model.monogram(resultRow.item.name)
          color: resultRow.hasCursor ? root.accent : root.dim
          opacity: resultRow.hasCursor || resultRow.groupStart || !root.browsing ? 1 : 0.4
          font.family: root.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
          Behavior on opacity { NumberAnimation { duration: 130 } }
        }

        // Favorites carry their star on the tile corner rather than beside
        // the name, so it never competes with an elided title.
        Text {
          textFormat: Text.PlainText
          visible: resultRow.item.favorite === true
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.rightMargin: -Style.spaceReal(4)
          anchors.topMargin: -Style.spaceReal(5)
          text: "󰓎"
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: String(resultRow.item.name || "Untitled")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          visible: text !== ""
          text: Model.itemSubtitle(resultRow.item, bitwarden.showUsernames)
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      // Available actions stay visible on every row. The selected row also
      // shows unavailable actions faintly, so capabilities such as TOTP are
      // discoverable without making a dead control look clickable.
      Repeater {
        model: Model.itemActions(resultRow.item)

        PanelActionButton {
          required property string modelData
          required property int index
          // Unavailable actions keep their slot rather than collapsing it, so
          // the icon columns stay straight from the first row to the last.
          readonly property bool available: Model.actionAvailable(resultRow.item, modelData)
          enabled: available
          iconText: Model.actionGlyph(modelData)
          tooltipText: available
            ? Model.actionTooltip(modelData)
            : Model.unavailableActionTooltip(modelData)
          foreground: root.foreground
          fontFamily: root.fontFamily
          hasCursor: resultRow.hasCursor && root.selectedAction === index
          opacity: available ? (resultRow.hasCursor ? 1 : 0.42)
            : (resultRow.hasCursor ? 0.22 : 0)
          Behavior on opacity { NumberAnimation { duration: 130 } }
          onHovered: function(on) {
            if (on) { root.selectRow(resultRow.rowIndex); root.selectedAction = index }
          }
          onClicked: {
            root.selectRow(resultRow.rowIndex)
            root.selectedAction = index
            root.activate(modelData)
          }
        }
      }
    }
  }
}
