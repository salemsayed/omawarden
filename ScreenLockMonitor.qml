import QtQuick
import Quickshell.Io

// Read-only compositor state. Omarchy 4.0.3 deliberately keeps its lock
// QObject private; plugins must not retain or traverse that service.
Item {
  id: root
  property string state: "unknown"
  readonly property bool unlocked: state === "unlocked"
  property double lastCheckedAt: 0

  function refresh() {
    if (!probe.running) probe.running = true
  }

  Process {
    id: probe
    command: ["timeout", "--kill-after=1s", "1s", "omarchy-hyprland-session-locked"]
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(exitCode, exitStatus) {
      root.lastCheckedAt = Date.now()
      root.state = exitStatus === 0 && exitCode === 1 ? "unlocked"
        : (exitStatus === 0 && exitCode === 0 ? "locked" : "unknown")
    }
  }

  Timer {
    interval: 500
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: {
      // Also fail closed if a process never starts or no longer reports back.
      if (Date.now() - root.lastCheckedAt > 2000) root.state = "unknown"
      root.refresh()
    }
  }
}
