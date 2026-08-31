#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("omawarden_agent", ROOT / "omawarden-agent.py")
assert SPEC and SPEC.loader
AGENT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AGENT
SPEC.loader.exec_module(AGENT)


FAKE_BW = r'''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
log = os.environ.get("FAKE_BW_LOG")
if log:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(args) + "\n")
if not args:
    raise SystemExit(2)
command = args[0]
pid_file = os.environ.get("FAKE_BW_PID_FILE")
if pid_file:
    with open(pid_file, "w", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
delay = os.environ.get("FAKE_BW_DELAY_" + command.upper())
if delay:
    time.sleep(float(delay))
if os.environ.get("FAKE_BW_FAIL_" + command.upper()):
    print("forced failure", file=sys.stderr)
    raise SystemExit(1)
if command == "status":
    print(json.dumps({
        "status": "unlocked" if os.environ.get("BW_SESSION") else os.environ.get("FAKE_BW_STATUS", "locked"),
        "serverUrl": "https://vault.example.test",
        "lastSync": "2026-08-20T12:00:00Z",
        "userEmail": "private@example.test"
    }))
elif command == "list":
    overflow_stream = os.environ.get("FAKE_BW_OVERSIZE_LIST_STREAM")
    if overflow_stream:
        stream = sys.stdout.buffer if overflow_stream == "stdout" else sys.stderr.buffer
        while True:
            stream.write(b"DO_NOT_LEAK_OVERSIZED_VAULT_OUTPUT" * 1024)
            stream.flush()
    print(json.dumps([{
        "id": "item-1", "name": "Example", "favorite": True, "type": 1,
        "login": {
            "username": "person@example.test", "password": "DO_NOT_LEAK_PASSWORD",
            "totp": "DO_NOT_LEAK_TOTP_SECRET",
            "uris": [{"uri": "https://example.test/login"}]
        },
        "notes": "DO_NOT_LEAK_NOTES",
        "fields": [{"name": "secret", "value": "DO_NOT_LEAK_FIELD"}]
    }, {
        "id": "card-1", "name": "Travel Card", "favorite": False, "type": 3,
        "card": {
            "brand": "Visa", "cardholderName": "Example Person",
            "number": "4111111111111111", "code": "999",
            "expMonth": "7", "expYear": "2030"
        }
    }]))
elif command == "get":
    if args[1] == "item" and args[2] == "card-1":
        print(json.dumps({
            "id": "card-1", "name": "Travel Card", "type": 3,
            "card": {
                "brand": "Visa", "cardholderName": "Example Person",
                "number": "4111111111111111", "code": "999",
                "expMonth": "7", "expYear": "2030"
            }
        }))
    else:
        values = {"password": "COPIED_PASSWORD", "username": "COPIED_USERNAME", "totp": "123456"}
        print(values[args[1]])
elif command == "unlock":
    if os.environ.get("FAKE_BW_SKIP_PASSWORD_FILE"):
        raise SystemExit(1)
    path = args[args.index("--passwordfile") + 1]
    with open(path, "rb", buffering=0) as stream:
        password = stream.readline().rstrip(b"\n")
    if password != b"correct horse battery staple":
        print("bad password", file=sys.stderr)
        raise SystemExit(1)
    print("SESSION_KEY_FOR_TESTS")
elif command in {"sync", "lock", "logout", "config"}:
    pass
else:
    print("unsupported", file=sys.stderr)
    raise SystemExit(2)
'''


FAKE_WL_COPY = r'''#!/usr/bin/env python3
import os, sys, time
pid_file = os.environ.get("FAKE_WL_COPY_PID_FILE")
if pid_file:
    with open(pid_file, "w", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
if os.environ.get("FAKE_WL_COPY_FAIL"):
    raise SystemExit(1)
payload = sys.stdin.buffer.read()
with open(os.environ["FAKE_CLIPBOARD"], "wb") as stream:
    stream.write(payload)
with open(os.environ["FAKE_WL_COPY_ARGS"], "w", encoding="utf-8") as stream:
    stream.write("\n".join(sys.argv[1:]))
delay = os.environ.get("FAKE_WL_COPY_DELAY")
if delay:
    time.sleep(float(delay))
'''


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.bin_dir = self.directory / "bin"
        self.bin_dir.mkdir()
        self.bw = self.bin_dir / "fake-bw"
        self.wl_copy = self.bin_dir / "wl-copy"
        self.bw.write_text(FAKE_BW, encoding="utf-8")
        self.wl_copy.write_text(FAKE_WL_COPY, encoding="utf-8")
        self.bw.chmod(0o755)
        self.wl_copy.chmod(0o755)
        self.clipboard = self.directory / "clipboard"
        self.copy_args = self.directory / "wl-copy-args"
        self.bw_log = self.directory / "bw-args.jsonl"
        self.bw_pid = self.directory / "bw.pid"
        self.wl_copy_pid = self.directory / "wl-copy.pid"
        self.environment = mock.patch.dict(os.environ, {
            "PATH": str(self.bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "XDG_RUNTIME_DIR": str(self.directory),
            "FAKE_CLIPBOARD": str(self.clipboard),
            "FAKE_WL_COPY_ARGS": str(self.copy_args),
            "FAKE_BW_LOG": str(self.bw_log),
            "FAKE_BW_PID_FILE": str(self.bw_pid),
            "FAKE_WL_COPY_PID_FILE": str(self.wl_copy_pid),
        })
        self.environment.start()
        self.agent = AGENT.Agent()
        self.agent.config = AGENT.Config(
            bw_command=str(self.bw),
            clipboard_timeout_sec=5,
            result_limit=20,
            show_usernames=True,
        )

    def tearDown(self) -> None:
        self.agent._stop_clipboards()
        self.environment.stop()
        self.temp.cleanup()

    def test_projection_never_returns_vault_secrets(self) -> None:
        self.agent.session = "session"
        response = self.agent.search("example")
        serialized = json.dumps(response)
        for secret in ("DO_NOT_LEAK_PASSWORD", "DO_NOT_LEAK_TOTP_SECRET", "DO_NOT_LEAK_NOTES", "DO_NOT_LEAK_FIELD"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(response["items"][0]["username"], "person@example.test")

        card_response = self.agent.search("travel")
        card_serialized = json.dumps(card_response)
        self.assertNotIn("4111111111111111", card_serialized)
        self.assertNotIn('"999"', card_serialized)
        self.assertEqual(card_response["items"][0]["last4"], "1111")
        self.assertEqual(card_response["items"][0]["brand"], "Visa")
        self.assertEqual(self.agent.search("card")["items"][0]["id"], "card-1")
        self.assertTrue(response["items"][0]["hasPassword"])
        self.assertNotIn("DO_NOT_LEAK", json.dumps(self.agent._item_index))

    def test_oversized_vault_list_output_is_capped_and_its_process_is_terminated(self) -> None:
        self.agent.session = "session"
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), \
                 mock.patch.object(AGENT, "MAX_VAULT_LIST_STDOUT_BYTES", 4096), \
                 mock.patch.object(AGENT, "MAX_VAULT_LIST_STDERR_BYTES", 4096), \
                 mock.patch.dict(os.environ, {"FAKE_BW_OVERSIZE_LIST_STREAM": stream}):
                with self.assertRaisesRegex(AGENT.PublicError, "Couldn't load the vault") as caught:
                    self.agent.search("")
                self.assertNotIn("DO_NOT_LEAK_OVERSIZED_VAULT_OUTPUT", str(caught.exception))
                self.assertFalse(self.agent._index_ready)
                pid = int(self.bw_pid.read_text(encoding="utf-8"))
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_timed_out_vault_list_is_terminated_without_retaining_an_index(self) -> None:
        self.agent.session = "session"
        with mock.patch.object(AGENT, "VAULT_LIST_TIMEOUT_SECONDS", 0.05), \
             mock.patch.dict(os.environ, {"FAKE_BW_DELAY_LIST": "5"}), \
             self.assertRaisesRegex(AGENT.PublicError, "Bitwarden took too long"):
            self.agent.search("")
        self.assertFalse(self.agent._index_ready)
        self.assertEqual(self.agent._item_index, [])
        pid = int(self.bw_pid.read_text(encoding="utf-8"))
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_search_reuses_memory_index_without_reinvoking_bw(self) -> None:
        self.agent.session = "session"
        first = self.agent.search("example")
        second = self.agent.search("person")
        self.assertEqual(first["items"][0]["id"], "item-1")
        self.assertEqual(second["items"][0]["id"], "item-1")
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(command[:2] == ["list", "items"] for command in commands), 1)

    def test_search_supports_casefolded_multi_term_metadata_matching(self) -> None:
        metadata = [
            {"id": "1", "name": "Alpha Portal", "username": "Alice", "url": "https://work.example", "favorite": False},
            {"id": "2", "name": "Beta", "username": "Bob", "url": "https://alpha.example", "favorite": False},
        ]
        index = AGENT.build_search_index(metadata)
        self.assertEqual([item["id"] for item in AGENT.search_index(index, "ALPHA alice", 20)], ["1"])
        self.assertEqual([item["id"] for item in AGENT.search_index(index, "alpha", 1)], ["1"])

    def test_sync_refreshes_the_index_before_returning_and_lock_wipes_it(self) -> None:
        self.agent.session = "session"
        self.agent.search("")
        self.assertTrue(self.agent._index_ready)
        self.agent.sync()
        self.assertTrue(self.agent._index_ready)
        self.agent.search("")
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(command[:2] == ["list", "items"] for command in commands), 2)
        self.agent.lock()
        self.assertFalse(self.agent._index_ready)
        self.assertEqual(self.agent._item_index, [])

    def test_failed_sync_warmup_is_retried_by_the_next_search(self) -> None:
        self.agent.session = "session"
        with mock.patch.dict(os.environ, {"FAKE_BW_FAIL_LIST": "1"}):
            response = self.agent.sync()
        self.assertTrue(response["ok"])
        self.assertFalse(response["indexReady"])
        self.assertFalse(self.agent._index_ready)
        self.agent.search("")
        self.assertTrue(self.agent._index_ready)

    def test_projection_setting_change_rebuilds_index_without_exposing_usernames(self) -> None:
        request_config = {
            "bwCommand": str(self.bw),
            "clipboardTimeoutSec": 5,
            "resultLimit": 20,
            "showUsernames": True,
        }
        self.agent.session = "session"
        self.agent.dispatch({"action": "search", "query": "", "config": request_config})
        request_config["showUsernames"] = False
        response = self.agent.dispatch({"action": "search", "query": "", "config": request_config})
        self.assertEqual(response["items"][0]["username"], "")
        self.assertNotIn("person@example.test", json.dumps(self.agent._item_index))

    def test_cli_profile_change_discards_index_and_session(self) -> None:
        self.agent.session = "session"
        self.agent.search("")
        self.agent.dispatch({
            "action": "status",
            "config": {
                "bwCommand": str(self.bw),
                "appDataDir": str(self.directory / "another-profile"),
                "showUsernames": True,
            },
        })
        self.assertEqual(self.agent.session, "")
        self.assertFalse(self.agent._index_ready)
        self.assertEqual(self.agent._item_index, [])

    def test_username_privacy_is_applied_in_agent(self) -> None:
        self.agent.session = "session"
        self.agent.config.show_usernames = False
        response = self.agent.search("")
        self.assertEqual(response["items"][0]["username"], "")

    def test_secret_is_piped_to_sensitive_timed_clipboard(self) -> None:
        self.agent.session = "session"
        response = self.agent.copy("item-1", "password")
        self.assertNotIn("COPIED_PASSWORD", json.dumps(response))
        deadline = time.monotonic() + 2
        while not self.clipboard.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.clipboard.read_text(encoding="utf-8").strip(), "COPIED_PASSWORD")
        arguments = self.copy_args.read_text(encoding="utf-8")
        self.assertIn("--sensitive", arguments)
        # Omarchy's clipboard-history watcher requests each new selection to
        # inspect its sensitivity marker. `--paste-once` would let that
        # internal request consume the user's only paste.
        self.assertNotIn("--paste-once", arguments)
        self.assertIn("--foreground", arguments)

    def test_unlock_uses_fifo_not_password_arguments(self) -> None:
        self.agent.config.sync_on_unlock = True
        password = bytearray(b"correct horse battery staple")
        with mock.patch.object(AGENT, "pinentry_executable", return_value="fake-pinentry"), \
             mock.patch.object(AGENT, "obtain_master_password", return_value=password):
            response = self.agent.unlock()
        self.assertTrue(response["ok"])
        self.assertEqual(self.agent.session, "SESSION_KEY_FOR_TESTS")
        logged = self.bw_log.read_text(encoding="utf-8")
        self.assertNotIn("correct horse battery staple", logged)
        self.assertIn("--passwordfile", logged)
        self.assertEqual(password, bytearray(len(password)))

    def test_native_unlock_consumes_wipeable_password_without_pinentry(self) -> None:
        password = bytearray(b"correct horse battery staple")
        request = {
            "action": "unlock-with-password",
            "config": {"bwCommand": str(self.bw), "pinentryCommand": "missing-pinentry"},
        }
        with mock.patch.object(AGENT, "obtain_master_password", side_effect=AssertionError("pinentry used")):
            response = self.agent.dispatch(request, password)
        self.assertTrue(response["ok"])
        self.assertEqual(self.agent.session, "SESSION_KEY_FOR_TESTS")
        self.assertEqual(password, bytearray(len(password)))
        logged = self.bw_log.read_text(encoding="utf-8")
        self.assertNotIn("correct horse battery staple", logged)
        self.assertIn("--passwordfile", logged)

    def test_status_does_not_return_account_identity(self) -> None:
        self.agent.session = "session"
        response = self.agent.status()
        self.assertEqual(response["status"], "unlocked")
        self.assertNotIn("userEmail", response)
        self.assertNotIn("private@example.test", json.dumps(response))

    def test_urls_fail_closed(self) -> None:
        self.assertEqual(AGENT.safe_url("https://example.test/path"), "https://example.test/path")
        self.assertEqual(AGENT.url_host("https://[2001:db8::1]:8443/login"), "2001:db8::1")
        for value in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "example.test",
            "https://user:password@example.test",
            "https://example.test:invalid",
            "https://[2001:db8::1",
            "https://example.test/line\nbreak",
        ):
            with self.assertRaises(AGENT.PublicError):
                AGENT.safe_url(value)

    def test_legacy_omarchy_pinentry_value_prefers_qt(self) -> None:
        available = {
            "pinentry-qt": "/usr/bin/pinentry-qt",
            "pinentry-gnome3": "/usr/bin/pinentry-gnome3",
        }
        with mock.patch.object(AGENT, "resolve_executable", side_effect=available.get):
            self.assertEqual(AGENT.pinentry_executable("omarchy"), "/usr/bin/pinentry-qt")
            self.assertEqual(AGENT.pinentry_executable("auto"), "/usr/bin/pinentry-gnome3")
            self.assertEqual(AGENT.pinentry_executable("pinentry-qt"), "/usr/bin/pinentry-qt")

    def test_cli_command_is_split_without_a_shell(self) -> None:
        config = AGENT.Config(bw_command="/opt/Bitwarden\\ CLI/bw --profile work")
        self.assertEqual(config.bw_argv(), ["/opt/Bitwarden CLI/bw", "--profile", "work"])
        config = AGENT.Config(bw_command="bw; touch /tmp/should-not-exist")
        self.assertEqual(config.bw_argv()[0], "bw;")

    def test_custom_profile_is_created_private_and_rejects_open_permissions(self) -> None:
        profile = self.directory / "Work Profile"
        config = AGENT.Config(app_data_dir=str(profile))
        environment = config.environment()
        self.assertEqual(environment["BITWARDENCLI_APPDATA_DIR"], str(profile))
        self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o700)
        profile.chmod(0o755)
        with self.assertRaises(AGENT.PublicError):
            config.environment()
        private = self.directory / "private-profile"
        private.mkdir(mode=0o700)
        linked = self.directory / "linked-profile"
        linked.symlink_to(private, target_is_directory=True)
        with self.assertRaises(AGENT.PublicError):
            AGENT.Config(app_data_dir=str(linked)).environment()

    def test_missing_cli_reports_setup_state_without_throwing(self) -> None:
        self.agent.config.bw_command = str(self.directory / "not-installed")
        response = self.agent.status()
        self.assertFalse(response["installed"])
        self.assertEqual(response["status"], "unavailable")

    def test_socket_is_user_only_and_protocol_is_metadata_only(self) -> None:
        request = {
            "action": "search",
            "config": {
                "bwCommand": str(self.bw),
                "pinentryCommand": "auto",
                "clipboardTimeoutSec": 5,
                "resultLimit": 5,
                "showUsernames": True,
            },
        }
        # Seed a session in a directly-launched daemon through an unlock request
        # would require a graphical pinentry. Protocol coverage here therefore
        # uses status; search projection is covered directly above.
        request["action"] = "status"
        # Simulate a daemon crash that left a stale socket pathname behind.
        stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale_socket.bind(str(self.directory / "omawarden.sock"))
        stale_socket.close()
        completed = subprocess.run(
            [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            env=dict(os.environ),
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertNotIn("userEmail", response)
        socket_path = self.directory / "omawarden.sock"
        self.assertTrue(socket_path.exists())
        self.assertEqual(stat.S_IMODE(socket_path.stat().st_mode), 0o600)
        subprocess.run(
            [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
            input=json.dumps({"action": "shutdown", "config": {"bwCommand": str(self.bw)}}),
            text=True,
            stdout=subprocess.DEVNULL,
            timeout=10,
            check=False,
            env=dict(os.environ),
        )

    def test_unlock_stdin_uses_binary_secret_frame_end_to_end(self) -> None:
        config = {
            "bwCommand": str(self.bw),
            "pinentryCommand": "missing-pinentry",
            "clipboardTimeoutSec": 5,
            "resultLimit": 5,
            "showUsernames": True,
        }
        password = b"correct horse battery staple"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "omawarden-agent.py"), "unlock-stdin"],
            input=json.dumps(config).encode() + b"\n" + password,
            capture_output=True,
            env=dict(os.environ),
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        response = json.loads(completed.stdout)
        self.assertEqual(response["status"], "unlocked")
        self.assertNotIn(password, completed.stdout)
        self.assertNotIn(password, self.bw_log.read_bytes())
        subprocess.run(
            [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
            input=json.dumps({"action": "shutdown", "config": config}),
            text=True,
            stdout=subprocess.DEVNULL,
            timeout=10,
            check=False,
            env=dict(os.environ),
        )

    def test_daemon_recovers_from_malformed_partial_and_incompatible_clients(self) -> None:
        config = {"bwCommand": str(self.bw)}
        started = subprocess.run(
            [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
            input=json.dumps({"action": "status", "config": config}),
            text=True,
            capture_output=True,
            env=dict(os.environ),
            timeout=10,
            check=False,
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        path = self.directory / "omawarden.sock"

        def raw_request(payload: bytes) -> dict[str, object]:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(6)
            try:
                client.connect(str(path))
                client.sendall(payload)
                response = b""
                while not response.endswith(b"\n"):
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                return json.loads(response)
            finally:
                client.close()

        try:
            malformed = raw_request(b"not-json\n")
            self.assertFalse(malformed["ok"])
            incompatible = raw_request(json.dumps({
                "action": "status", "config": config, "protocolVersion": AGENT.PROTOCOL_VERSION + 1,
            }).encode() + b"\n")
            self.assertFalse(incompatible["ok"])
            self.assertIn("updated", str(incompatible["error"]))
            oversized = raw_request(b'{"padding":"' + b"x" * AGENT.MAX_REQUEST_BYTES + b'"}\n')
            self.assertEqual(oversized["error"], "Request is too large")

            partial = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            partial.settimeout(6)
            try:
                partial.connect(str(path))
                began = time.monotonic()
                response = partial.recv(4096)
                elapsed = time.monotonic() - began
                self.assertGreaterEqual(elapsed, AGENT.CLIENT_IO_TIMEOUT_SECONDS * 0.8)
                self.assertEqual(json.loads(response)["error"], "Request timed out")
            finally:
                partial.close()

            recovered = subprocess.run(
                [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
                input=json.dumps({"action": "status", "config": config}),
                text=True,
                capture_output=True,
                env=dict(os.environ),
                timeout=10,
                check=False,
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertTrue(json.loads(recovered.stdout)["ok"])
        finally:
            subprocess.run(
                [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
                input=json.dumps({"action": "shutdown", "config": config}),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                env=dict(os.environ),
            )

    def test_concurrent_clients_share_one_daemon_and_one_status_poll(self) -> None:
        config = {"bwCommand": str(self.bw)}
        # Longer than the one-second cache window. The cache must begin when
        # the slow CLI poll completes, otherwise every queued request repeats
        # the poll and eventually times out.
        environment = dict(os.environ, FAKE_BW_DELAY_STATUS="1.25")
        processes = [
            subprocess.Popen(
                [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            for _ in range(20)
        ]
        try:
            results = [
                (process, process.communicate(json.dumps({"action": "status", "config": config}), timeout=10))
                for process in processes
            ]
            for process, (stdout, stderr) in results:
                self.assertEqual(process.returncode, 0, stderr)
                self.assertTrue(json.loads(stdout)["ok"])
            commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sum(command[:1] == ["status"] for command in commands), 1)
            self.assertEqual(stat.S_IMODE((self.directory / "omawarden.sock").stat().st_mode), 0o600)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
            subprocess.run(
                [sys.executable, str(ROOT / "omawarden-agent.py"), "request"],
                input=json.dumps({"action": "shutdown", "config": config}),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                env=environment,
            )

    def test_projection_keeps_login_and_card_items(self) -> None:
        rows = AGENT.project_item_metadata([
            {"id": "login", "name": "Login", "type": 1, "login": {"password": "x"}},
            {"id": "note", "name": "Secure note", "type": 2, "notes": "DO_NOT_LEAK"},
            {"id": "card", "name": "Card", "type": 3, "card": {
                "brand": "Visa", "cardholderName": "Example Person", "number": "4111111111111111",
                "code": "999", "expMonth": "7", "expYear": "2030",
            }},
            {"id": "identity", "name": "Identity", "type": 4},
        ], True)
        self.assertEqual([row["id"] for row in rows], ["card", "login"])
        card = rows[0]
        self.assertEqual(card["last4"], "1111")
        self.assertEqual(card["cardholder"], "Example Person")
        self.assertTrue(card["hasCardCode"])
        self.assertNotIn("number", card)
        self.assertNotIn("code", card)

    def test_projection_tolerates_malformed_rows_and_sanitizes_display_metadata(self) -> None:
        rows = AGENT.project_item_metadata([
            {"id": "bad-type", "type": "login", "login": {}},
            {"id": "x" * (AGENT.MAX_ITEM_ID_CHARS + 1), "type": 1, "login": {}},
            {"id": "duplicate", "name": "First\nName", "type": 1, "login": {
                "username": "person\texample", "uris": [
                    {"uri": "https://user:secret@example.test"},
                    {"uri": "https://safe.example.test/login"},
                ],
            }},
            {"id": "duplicate", "name": "Second", "type": 1, "login": {}},
        ], True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "duplicate")
        self.assertEqual(rows[0]["name"], "First Name")
        self.assertEqual(rows[0]["username"], "person example")
        self.assertEqual(rows[0]["url"], "https://safe.example.test/login")

    def test_search_matches_control_sanitized_fields_and_top_k_matches_reference(self) -> None:
        metadata = [
            {
                "id": str(index),
                "name": f"Entry {index}",
                "username": f"user{index % 13}@example.test",
                "url": f"https://service{index % 17}.example.test",
                "favorite": index % 19 == 0,
            }
            for index in range(500)
        ]
        index = AGENT.build_search_index(metadata)

        def reference(query: str, limit: int) -> list[str]:
            terms = query.casefold().split()
            ranked = []
            for position, (item, haystack) in enumerate(index):
                if not all(term in haystack for term in terms):
                    continue
                name, username, host = haystack.split("\n", 2)
                ranks = [AGENT._term_rank(term, name, username, host) for term in terms]
                if any(rank is None for rank in ranks):
                    continue
                ranked.append((sum(ranks), 0 if item.get("favorite") else 1, position, item["id"]))
            return [row[3] for row in sorted(ranked)[:limit]]

        for query in ("entry", "user3", "service5 example", "entry user7", "nothing"):
            actual = [item["id"] for item in AGENT.search_index(index, query, 20)]
            self.assertEqual(actual, reference(query, 20), query)

    def test_search_ranks_name_prefixes_over_incidental_matches(self) -> None:
        metadata = [
            {"id": "digital", "name": "Digital Ocean", "username": "ops", "url": "https://cloud.digitalocean.com", "favorite": True},
            {"id": "gitlab", "name": "GitLab", "username": "dev", "url": "https://gitlab.example", "favorite": False},
            {"id": "github", "name": "GitHub", "username": "dev", "url": "https://github.com", "favorite": False},
            {"id": "mail", "name": "Mail", "username": "git.person@example.test", "url": "https://mail.example", "favorite": False},
            {"id": "forge", "name": "Forge", "username": "dev", "url": "https://git.example.test", "favorite": False},
        ]
        index = AGENT.build_search_index(metadata)
        ordered = [item["id"] for item in AGENT.search_index(index, "git", 20)]
        self.assertEqual(sorted(ordered[:2]), ["github", "gitlab"])
        self.assertLess(ordered.index("forge"), ordered.index("digital"))
        self.assertLess(ordered.index("digital"), ordered.index("mail"))
        self.assertEqual(sorted(item["id"] for item in AGENT.search_index(index, "dev git", 20)[:2]), ["github", "gitlab"])
        self.assertEqual(AGENT.search_index(index, "nothing-here", 20), [])

    def test_browse_lists_recent_entries_first_without_persisting_them(self) -> None:
        metadata = [
            {"id": "a", "name": "Alpha", "username": "", "url": "", "favorite": False},
            {"id": "b", "name": "Beta", "username": "", "url": "", "favorite": False},
            {"id": "c", "name": "Gamma", "username": "", "url": "", "favorite": False},
        ]
        index = AGENT.build_search_index(metadata)
        self.assertEqual([item["id"] for item in AGENT.browse_index(index, [], 20)], ["a", "b", "c"])
        rows = AGENT.browse_index(index, ["c", "missing", "c"], 20)
        self.assertEqual([item["id"] for item in rows], ["c", "a", "b"])
        self.assertTrue(rows[0]["recent"])
        self.assertNotIn("recent", rows[1])
        self.assertEqual(len(AGENT.browse_index(index, ["c"], 2)), 2)

    def test_copy_and_open_remember_recents_and_sign_out_forgets_them(self) -> None:
        self.agent.session = "session"
        self.agent.copy("item-1", "username")
        self.assertEqual(self.agent._recent_ids, ["item-1"])
        with mock.patch.object(AGENT.subprocess, "Popen") as popen, \
             mock.patch.object(AGENT, "resolve_executable", return_value="/usr/bin/xdg-open"):
            self.agent.open_url("https://example.test/login", "item-1")
            popen.assert_called_once()
        self.assertEqual(self.agent._recent_ids, ["item-1"])
        self.agent.lock()
        self.assertEqual(self.agent._recent_ids, ["item-1"], "recents survive a lock")
        self.agent.session = "session"
        response = self.agent.logout()
        self.assertEqual(response["status"], "unauthenticated")
        self.assertEqual(self.agent.session, "")
        self.assertEqual(self.agent._recent_ids, [])
        self.assertFalse(self.agent._index_ready)
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertIn(["logout", "--quiet", "--nointeraction"], commands)

    def test_copy_and_open_are_restricted_to_projected_item_capabilities(self) -> None:
        self.agent.session = "session"
        self.agent.search("")
        self.agent._item_index[0][0]["hasTotp"] = False
        with self.assertRaisesRegex(AGENT.PublicError, "no code"):
            self.agent.copy("item-1", "totp")
        with self.assertRaisesRegex(AGENT.PublicError, "no longer available"):
            self.agent.copy("missing", "password")
        with self.assertRaisesRegex(AGENT.PublicError, "changed"):
            self.agent.open_url("https://attacker.example", "item-1")
        with self.assertRaisesRegex(AGENT.PublicError, "no longer available"):
            self.agent.open_url("https://example.test", "missing")

    def test_card_fields_copy_through_the_ephemeral_filter(self) -> None:
        self.agent.session = "session"
        self.agent.search("")
        expected = {
            "number": b"4111111111111111",
            "cardholder": b"Example Person",
            "cardCode": b"999",
            "expiry": b"07/30",
        }
        for field, value in expected.items():
            with self.subTest(field=field):
                response = self.agent.copy("card-1", field)
                self.assertEqual(response["field"], field)
                self.assertEqual(self.clipboard.read_bytes(), value)
        with self.assertRaisesRegex(AGENT.PublicError, "login has no number"):
            self.agent.copy("item-1", "number")
        with self.assertRaisesRegex(AGENT.PublicError, "card has no password"):
            self.agent.copy("card-1", "password")

    def test_copy_timeout_terminates_the_cli_and_clipboard_processes(self) -> None:
        self.agent.session = "session"
        with mock.patch.dict(os.environ, {"FAKE_BW_DELAY_GET": "5"}), \
             mock.patch.object(AGENT, "COPY_TIMEOUT_SECONDS", 0.05), \
             self.assertRaisesRegex(AGENT.PublicError, "too long"):
            self.agent.copy("item-1", "password")
        self.assertEqual(self.agent.clipboards, set())
        for pid_file in (self.bw_pid, self.wl_copy_pid):
            pid = int(pid_file.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_clipboard_owner_expires_and_lock_reaps_it_immediately(self) -> None:
        self.agent.session = "session"
        self.agent.config.clipboard_timeout_sec = 0.05
        with mock.patch.dict(os.environ, {"FAKE_WL_COPY_DELAY": "5"}):
            self.agent.copy("item-1", "password")
            first_pid = int(self.wl_copy_pid.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 2
            while self.agent.clipboards and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.agent.clipboards, set())
            with self.assertRaises(ProcessLookupError):
                os.kill(first_pid, 0)

            self.agent.config.clipboard_timeout_sec = 5
            self.agent.copy("item-1", "password")
            second_pid = int(self.wl_copy_pid.read_text(encoding="utf-8"))
            self.assertTrue(self.agent.clipboards)
            self.agent.lock()
            self.assertEqual(self.agent.clipboards, set())
            with self.assertRaises(ProcessLookupError):
                os.kill(second_pid, 0)

    def test_unlock_failure_never_strands_a_fifo_writer_or_password_buffer(self) -> None:
        password = bytearray(b"correct horse battery staple")
        before = {thread.ident for thread in threading.enumerate()}
        with mock.patch.dict(os.environ, {"FAKE_BW_SKIP_PASSWORD_FILE": "1"}), \
             self.assertRaises(AGENT.PublicError):
            self.agent.unlock_with_password(password)
        self.assertEqual(password, bytearray(len(password)))
        self.assertEqual(before, {thread.ident for thread in threading.enumerate()})
        self.assertEqual(list(self.directory.glob("omawarden-password-*")), [])

    def test_unlock_wipes_password_when_dependencies_are_missing(self) -> None:
        password = bytearray(b"do not retain")
        self.agent.config.bw_command = str(self.directory / "missing-bw")
        with self.assertRaises(AGENT.PublicError):
            self.agent.unlock_with_password(password)
        self.assertEqual(password, bytearray(len(password)))

    def test_unlocked_status_cache_survives_poll_interval_and_invalidates_on_lock(self) -> None:
        self.agent.session = "session"
        self.agent.status()
        self.agent._status_cached_at -= AGENT.STATUS_CACHE_SECONDS + 1
        self.agent.status()
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(command[:1] == ["status"] for command in commands), 1)
        self.agent.lock()
        self.agent.status()
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(command[:1] == ["status"] for command in commands), 2)

    def test_locked_status_cache_expires_normally(self) -> None:
        self.agent.status()
        self.agent._status_cached_at -= AGENT.STATUS_CACHE_SECONDS + 1
        self.agent.status()
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(command[:1] == ["status"] for command in commands), 2)

    def test_inactivity_auto_lock_and_idle_exit_boundaries(self) -> None:
        self.agent.session = "session"
        self.agent.config.auto_lock_minutes = 1
        self.agent.last_access = time.monotonic() - 61
        self.agent.maybe_auto_lock()
        self.assertEqual(self.agent.session, "")
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertIn(["lock", "--quiet", "--nointeraction"], commands)

        self.agent.last_request = time.monotonic() - AGENT.AGENT_IDLE_EXIT_SECONDS - 1
        self.assertTrue(self.agent.idle_without_session())
        self.agent.session = "session"
        self.assertFalse(self.agent.idle_without_session())

    def test_secret_frame_rejects_empty_oversized_and_truncated_inputs(self) -> None:
        left, right = socket.socketpair()
        try:
            with self.assertRaisesRegex(AGENT.PublicError, "Enter"):
                AGENT._receive_secret(left, 0)
            with self.assertRaisesRegex(AGENT.PublicError, "too long"):
                AGENT._receive_secret(left, AGENT.MAX_MASTER_PASSWORD_BYTES + 1)
            right.sendall(b"abc")
            right.shutdown(socket.SHUT_WR)
            with self.assertRaisesRegex(AGENT.PublicError, "ended early"):
                AGENT._receive_secret(left, 5)
        finally:
            left.close()
            right.close()

    def test_lock_file_rejects_symlinks(self) -> None:
        target = self.directory / "target"
        target.write_text("do not follow", encoding="utf-8")
        linked = self.directory / "linked-lock"
        linked.symlink_to(target)
        with self.assertRaises(OSError):
            AGENT._open_lock_file(linked)
        self.assertEqual(target.read_text(encoding="utf-8"), "do not follow")

    def test_status_failure_drops_session_index_and_clipboard_owners(self) -> None:
        self.agent.session = "session"
        self.agent.search("")
        fake_clipboard = mock.Mock()
        fake_clipboard.poll.return_value = 0
        self.agent.clipboards.add(fake_clipboard)
        self.agent._clear_status_cache()
        with mock.patch.dict(os.environ, {"FAKE_BW_FAIL_STATUS": "1"}), \
             self.assertRaises(AGENT.PublicError):
            self.agent.status()
        self.assertEqual(self.agent.session, "")
        self.assertFalse(self.agent._index_ready)
        self.assertEqual(self.agent.clipboards, set())

    def test_source_change_drops_session_recents_and_clipboard_owners(self) -> None:
        self.agent.session = "session"
        self.agent._recent_ids = ["item-1"]
        fake_clipboard = mock.Mock()
        fake_clipboard.poll.return_value = 0
        self.agent.clipboards.add(fake_clipboard)
        self.agent.dispatch({
            "action": "status",
            "config": {"bwCommand": str(self.directory / "missing-new-bw")},
        })
        self.assertEqual(self.agent.session, "")
        self.assertEqual(self.agent._recent_ids, [])
        self.assertEqual(self.agent.clipboards, set())

    def test_runtime_and_request_boundaries_fail_closed(self) -> None:
        private = self.directory / "private"
        private.mkdir(mode=0o700)
        self.assertTrue(AGENT._private_runtime_directory(private))
        private.chmod(0o755)
        self.assertFalse(AGENT._private_runtime_directory(private))
        with self.assertRaises(AGENT.PublicError):
            AGENT._request_payload({"value": "x" * AGENT.MAX_REQUEST_BYTES})

    def test_unlock_leaves_sync_to_the_panel(self) -> None:
        self.agent.config.sync_on_unlock = True
        password = bytearray(b"correct horse battery staple")
        with mock.patch.object(AGENT, "pinentry_executable", return_value="fake-pinentry"), \
             mock.patch.object(AGENT, "obtain_master_password", return_value=password):
            self.agent.unlock()
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertFalse(any(command[:1] == ["sync"] for command in commands))

    def test_unlock_without_sync_warms_only_after_secret_inputs_are_cleared(self) -> None:
        self.agent.config.sync_on_unlock = False
        password = bytearray(b"correct horse battery staple")
        original_load = self.agent._load_index

        def checked_load() -> None:
            self.assertEqual(password, bytearray(len(password)))
            self.assertEqual(list(self.directory.glob("omawarden-password-*")), [])
            original_load()

        with mock.patch.object(self.agent, "_load_index", side_effect=checked_load):
            response = self.agent.unlock_with_password(password)
        self.assertTrue(response["indexReady"])
        self.assertTrue(self.agent._index_ready)

    def test_sign_in_terminal_applies_the_configured_server_first(self) -> None:
        args = AGENT.build_parser().parse_args([
            "login-terminal", "--bw-command", str(self.bw), "--server-url", "https://eu.example.test",
        ])
        with mock.patch.dict(os.environ, {"FAKE_BW_STATUS": "unauthenticated"}), \
             mock.patch("builtins.input", return_value=""), \
             mock.patch("sys.stdout"):
            AGENT.login_terminal(args)
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        config_calls = [index for index, command in enumerate(commands) if command[:3] == ["config", "server", "https://eu.example.test"]]
        login_calls = [index for index, command in enumerate(commands) if command == ["login"]]
        self.assertEqual(len(config_calls), 1)
        self.assertEqual(len(login_calls), 1)
        self.assertLess(config_calls[0], login_calls[0])

    def test_sign_in_terminal_skips_bw_login_when_already_signed_in(self) -> None:
        args = AGENT.build_parser().parse_args(["login-terminal", "--bw-command", str(self.bw)])
        with mock.patch.dict(os.environ, {"FAKE_BW_STATUS": "locked"}), \
             mock.patch("builtins.input", return_value=""), \
             mock.patch("sys.stdout"):
            self.assertEqual(AGENT.login_terminal(args), 0)
        commands = [json.loads(line) for line in self.bw_log.read_text(encoding="utf-8").splitlines()]
        self.assertNotIn(["login"], commands)

    def test_desktop_launcher_falls_through_immediate_failures_to_flatpak(self) -> None:
        failed = mock.Mock()
        failed.wait.return_value = 1
        succeeded = mock.Mock()
        succeeded.wait.return_value = 0
        launchers = {
            "gtk-launch": "/usr/bin/gtk-launch",
            "flatpak": "/usr/bin/flatpak",
        }
        with mock.patch.object(AGENT, "resolve_executable", side_effect=launchers.get), \
             mock.patch.object(AGENT.subprocess, "Popen", side_effect=[failed, succeeded]) as popen:
            self.assertEqual(AGENT.open_desktop(mock.Mock()), 0)
        self.assertEqual(
            [call.args[0] for call in popen.call_args_list],
            [
                ["/usr/bin/gtk-launch", "bitwarden.desktop"],
                ["/usr/bin/flatpak", "run", "com.bitwarden.desktop"],
            ],
        )
        failed.wait.assert_called_once_with(timeout=AGENT.DESKTOP_LAUNCH_WAIT_SECONDS)
        succeeded.wait.assert_called_once_with(timeout=AGENT.DESKTOP_LAUNCH_WAIT_SECONDS)

    def test_desktop_launcher_treats_a_still_running_app_as_success(self) -> None:
        running = mock.Mock()
        running.wait.side_effect = subprocess.TimeoutExpired(["bitwarden"], 2)
        with mock.patch.object(AGENT, "resolve_executable", side_effect=lambda name: f"/usr/bin/{name}"), \
             mock.patch.object(AGENT.subprocess, "Popen", return_value=running) as popen:
            self.assertEqual(AGENT.open_desktop(mock.Mock()), 0)
        popen.assert_called_once()
        running.wait.assert_called_once_with(timeout=AGENT.DESKTOP_LAUNCH_WAIT_SECONDS)

    def test_desktop_launcher_returns_failure_when_none_are_available(self) -> None:
        with mock.patch.object(AGENT, "resolve_executable", return_value=None), \
             mock.patch.object(AGENT.subprocess, "Popen") as popen:
            self.assertEqual(AGENT.open_desktop(mock.Mock()), 1)
        popen.assert_not_called()

    def test_public_errors_read_like_sentences_for_people(self) -> None:
        self.agent.session = ""
        with self.assertRaises(AGENT.PublicError) as caught:
            self.agent.search("x")
        message = str(caught.exception)
        self.assertIn("locked", message.lower())
        self.assertNotIn("agent", message.lower())
        self.assertNotIn("cli", message.lower())



if __name__ == "__main__":
    unittest.main(verbosity=2)
