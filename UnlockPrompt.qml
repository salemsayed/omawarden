import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Native Omarchy unlock surface. The password exists in QML only while this
// short-lived form is being edited, then moves over stdin to the private agent.
Item {
  id: root

  property var shell: null
  property bool opened: false
  property bool busy: false
  property string errorText: ""
  property var unlockConfig: ({})

  readonly property string helperPath: decodeURIComponent(
    String(Qt.resolvedUrl("omawarden-agent.py")).replace("file://", ""))
  readonly property var lockService: shell && typeof shell.serviceFor === "function"
    ? shell.serviceFor("omarchy.lock") : null

  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property color dim: Util.alpha(foreground, 0.62)
  readonly property color scrim: Color.menu.scrim
  readonly property var borderSpec: Border.surfaceSpec(
    "menu", "border", Color.menu.border, Math.max(1, Style.space(2)))
  readonly property string fontFamily: Style.font.menuFamily
  readonly property int cardWidth: Math.min(
    Style.space(390), panel.width - Style.gapsOut * 2)

  signal unlockSucceeded()
  signal unlockCancelled()

  function parsePayload(payloadJson) {
    try {
      var payload = JSON.parse(payloadJson || "{}")
      return payload && typeof payload.config === "object" ? payload.config : ({})
    } catch (error) {
      return ({})
    }
  }

  function open(payloadJson) {
    if (unlockProcess.running) return false
    if (lockService && lockService.locked === true) return false
    unlockConfig = parsePayload(payloadJson)
    errorText = ""
    busy = false
    passwordField.text = ""
    unlockProcess.secret = ""
    unlockProcess.configLine = ""
    opened = true
    Qt.callLater(function() {
      if (root.opened) passwordField.forceActiveFocus()
    })
    return true
  }

  function clearSecret() {
    passwordField.text = ""
    unlockProcess.secret = ""
  }

  function close() {
    clearSecret()
    errorText = ""
    opened = false
  }

  function dismiss() {
    if (busy) return
    close()
    unlockCancelled()
  }

  function submit() {
    if (busy) return
    if (passwordField.text.length === 0) {
      errorText = "Enter your master password"
      passwordField.forceActiveFocus()
      return
    }
    errorText = ""
    busy = true
    unlockProcess.responseText = ""
    unlockProcess.configLine = JSON.stringify(unlockConfig || ({}))
    unlockProcess.secret = passwordField.text
    passwordField.text = ""
    unlockProcess.stdinEnabled = true
    unlockProcess.running = true
  }

  function finish(raw) {
    var response = ({})
    try {
      response = JSON.parse(String(raw || "").trim())
    } catch (error) {
      response = { ok: false, error: "The unlock helper returned an unreadable response" }
    }
    busy = false
    if (!response.ok) {
      errorText = String(response.error || "That master password didn't work")
      Qt.callLater(function() {
        if (root.opened) passwordField.forceActiveFocus()
      })
      return
    }

    unlockSucceeded()
    close()
  }

  Connections {
    target: root.lockService
    function onLockedChanged() {
      if (!root.lockService || root.lockService.locked !== true) return
      root.close()
      root.unlockCancelled()
    }
  }

  Process {
    id: unlockProcess
    property string configLine: ""
    property string secret: ""
    property string responseText: ""

    // When automatic sync is disabled, unlock prepares the index itself after
    // clearing the password input; allow for both bounded CLI operations.
    command: ["python3", root.helperPath, "unlock-stdin", "--timeout", "120"]
    stdinEnabled: true

    onStarted: {
      write(configLine + "\n")
      configLine = ""
      write(secret)
      secret = ""
      // EOF tells unlock-stdin it has received the complete password.
      stdinEnabled = false
    }

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: unlockProcess.responseText = text
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: root.finish(responseText)
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omawarden-unlock"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      enabled: !root.busy
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: content.implicitHeight + Style.spacing.panelPadding * 2
      anchors.centerIn: parent
      color: root.background
      borderSpec: root.borderSpec
      radius: Style.cornerRadius

      MouseArea { anchors.fill: parent; onClicked: {} }

      Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.panelPadding
        anchors.rightMargin: Style.spacing.panelPadding
        spacing: Style.space(12)

        Row {
          spacing: Style.space(9)

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "󰌾"
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Unlock Bitwarden"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
        }

        Text {
          width: parent.width
          text: root.errorText !== ""
            ? root.errorText
            : "Enter your master password to unlock your vault."
          color: root.errorText !== "" ? root.urgent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        TextField {
          id: passwordField
          width: parent.width
          password: true
          maximumLength: 16384
          enabled: !root.busy
          foreground: root.foreground
          placeholderText: root.busy ? "Unlocking…" : "Master password"
          onAccepted: root.submit()
          Keys.onEscapePressed: root.dismiss()
        }

        Row {
          anchors.right: parent.right
          spacing: Style.space(8)

          Button {
            text: "Cancel"
            enabled: !root.busy
            bordered: true
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.dismiss()
          }

          Button {
            text: root.busy ? "Unlocking…" : "Unlock"
            enabled: !root.busy
            active: !root.busy
            bordered: true
            foreground: root.accent
            accent: root.accent
            fontFamily: root.fontFamily
            onClicked: root.submit()
          }
        }
      }
    }
  }
}
