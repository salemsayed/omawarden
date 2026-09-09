#!/usr/bin/env python3
"""Run the actual QML service and probe against an isolated fake vault/compositor."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
QS = shutil.which("qs")

FAKE_AGENT = r'''
import json, os, sys, time
from pathlib import Path
request = json.loads(sys.stdin.readline())
action = request["action"]
state = Path(os.environ["TEST_AGENT_STATE"])
with open(os.environ["TEST_AGENT_LOG"], "a") as log:
    log.write(action + "\n")
if action == "unlock":
    time.sleep(1.5)
    state.write_text("unlocked")
elif action == "lock":
    state.write_text("locked")
print(json.dumps({"ok": True, "status": state.read_text(), "statusText": state.read_text(),
                  "message": "fixture", "dependencies": {"bw": True, "wlCopy": True, "pinentry": True}}))
'''
HARNESS = '''
import QtQuick
import Quickshell
import Quickshell.Io
ShellRoot {
  Service {
    id: vault
    shell: QtObject { property var barConfig: ({}) }
  }
  IpcHandler {
    target: "test"
    function snapshot(): string {
      return JSON.stringify({ screen: vault.screenLock.state, vault: vault.vaultStatus,
        busy: vault.actionBusy, pending: vault._screenLockPending })
    }
    function refresh(): void { vault.refresh() }
    function unlock(): void { vault.unlock() }
  }
}
'''

@unittest.skipUnless(QS, "Quickshell is required for the QML integration test")
class ScreenLockQmlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="omawarden-screen-lock-test-")
        self.path = Path(self.temp.name)
        self.config = self.path / "config"
        self.config.mkdir()
        self.runtime = self.path / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.bin = self.path / "bin"
        self.bin.mkdir()
        for name in ("Service.qml", "ScreenLockMonitor.qml", "Model.js"):
            shutil.copy2(ROOT / name, self.config / name)
        (self.config / "omawarden-agent.py").write_text(FAKE_AGENT)
        (self.config / "shell.qml").write_text(HARNESS)
        self.probe_state = self.path / "probe-state"
        self.agent_state = self.path / "agent-state"
        self.agent_log = self.path / "agent-log"
        self.probe_state.write_text("unlocked")
        self.agent_state.write_text("locked")
        fake_probe = self.bin / "omarchy-hyprland-session-locked"
        fake_probe.write_text('''#!/bin/bash
case "$(cat "$TEST_PROBE_STATE")" in
  unlocked) exit 1 ;;
  locked) exit 0 ;;
  hang) sleep 20 ;;
  *) exit 2 ;;
esac
''')
        fake_probe.chmod(0o755)
        self.env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(self.runtime),
                        TEST_PROBE_STATE=str(self.probe_state), TEST_AGENT_STATE=str(self.agent_state),
                        TEST_AGENT_LOG=str(self.agent_log), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.log = (self.path / "qml.log").open("w+")
        self.process = None

    def tearDown(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.log.seek(0)
        log = self.log.read()
        self.log.close()
        self.temp.cleanup()
        self.assertNotIn("ReferenceError", log)
        self.assertNotIn("TypeError", log)
        self.assertNotIn("Failed to load configuration", log)

    def start(self):
        self.process = subprocess.Popen([QS, "-p", str(self.config)], env=self.env,
                                        stdout=self.log, stderr=subprocess.STDOUT)

    def call(self, method):
        return subprocess.run([QS, "ipc", "-p", str(self.config), "call", "test", method],
                              env=self.env, text=True, capture_output=True, timeout=3)

    def snapshot(self):
        result = self.call("snapshot")
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError):
            return {}

    def wait_for(self, predicate, timeout=7):
        deadline = time.monotonic() + timeout
        latest = {}
        while time.monotonic() < deadline:
            latest = self.snapshot()
            if predicate(latest):
                return latest
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        self.log.flush()
        self.log.seek(0)
        self.fail(f"Timed out: {latest}\n{self.log.read()}")

    def test_startup_locked_relocks_an_unlocked_fake_vault(self):
        self.probe_state.write_text("locked")
        self.agent_state.write_text("unlocked")
        self.start()
        self.wait_for(lambda s: s.get("screen") == "locked" and s.get("vault") == "locked" and not s.get("pending"))
        self.assertEqual(self.agent_state.read_text(), "locked")
        self.assertIn("lock", self.agent_log.read_text().splitlines())

    def test_lock_during_unlock_is_latched_after_desktop_unlock(self):
        self.start()
        self.wait_for(lambda s: s.get("screen") == "unlocked" and s.get("vault") == "locked")
        self.call("unlock")
        self.wait_for(lambda s: s.get("busy") is True)
        self.probe_state.write_text("locked")
        self.wait_for(lambda s: s.get("pending") is True)
        self.probe_state.write_text("unlocked")
        self.wait_for(lambda s: s.get("screen") == "unlocked" and s.get("vault") == "locked" and s.get("busy") is False and s.get("pending") is False)
        actions = self.agent_log.read_text().splitlines()
        self.assertIn("unlock", actions)
        self.assertIn("lock", actions[actions.index("unlock") + 1:])
        self.assertNotIn("sync", actions)
        self.assertEqual(self.agent_state.read_text(), "locked")

    def test_probe_timeout_fails_closed_and_recovers(self):
        self.start()
        self.wait_for(lambda s: s.get("screen") == "unlocked" and s.get("vault") == "locked")
        self.agent_state.write_text("unlocked")
        self.call("refresh")
        self.wait_for(lambda s: s.get("vault") == "unlocked")
        self.probe_state.write_text("hang")
        self.wait_for(lambda s: s.get("screen") == "unknown" and s.get("vault") == "locked")
        self.probe_state.write_text("unlocked")
        self.wait_for(lambda s: s.get("screen") == "unlocked")
        self.assertEqual(self.agent_state.read_text(), "locked")

if __name__ == "__main__":
    unittest.main(verbosity=2)
