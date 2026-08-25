#!/usr/bin/env python3
"""Local, secret-isolating backend for the OmaWarden Omarchy plugin.

The Quickshell UI only receives vault metadata. The session key stays in this
agent's memory and copied secrets travel directly from `bw` to a sensitive
Wayland clipboard without crossing Python or QML stdout.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import heapq
import json
import os
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLUGIN_ID = "io.github.salemsayed.omawarden"
PROTOCOL_VERSION = 1
AGENT_IDLE_EXIT_SECONDS = 10 * 60
CLIENT_IO_TIMEOUT_SECONDS = 3.0
STATUS_CACHE_SECONDS = 1.0
COPY_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_MASTER_PASSWORD_BYTES = 16 * 1024
MAX_ITEM_ID_CHARS = 128
SAFE_URL_SCHEMES = {"http", "https"}
LOGIN_COPY_FIELDS = {"password", "username", "totp"}
CARD_COPY_FIELDS = {"number", "cardholder", "cardCode", "expiry"}
COPY_FIELDS = LOGIN_COPY_FIELDS | CARD_COPY_FIELDS
LOGIN_ITEM_TYPE = 1
CARD_ITEM_TYPE = 3
RECENT_LIMIT = 5
DESKTOP_LAUNCH_WAIT_SECONDS = 2.0

SearchEntry = tuple[dict[str, Any], str]


class PublicError(RuntimeError):
    """An error whose message is safe to show in the panel."""


@dataclass
class Config:
    bw_command: str = "bw"
    pinentry_command: str = "auto"
    app_data_dir: str = ""
    auto_lock_minutes: int = 15
    clipboard_timeout_sec: int = 30
    result_limit: int = 20
    sync_on_unlock: bool = True
    show_usernames: bool = True

    @classmethod
    def from_request(cls, data: Any) -> Config:
        raw = data if isinstance(data, dict) else {}
        return cls(
            bw_command=_safe_string(raw.get("bwCommand"), "bw", 512),
            pinentry_command=_safe_string(raw.get("pinentryCommand"), "auto", 512),
            app_data_dir=_safe_string(raw.get("appDataDir"), "", 4096),
            auto_lock_minutes=_bounded_int(raw.get("autoLockMinutes"), 15, 0, 240),
            clipboard_timeout_sec=_bounded_int(raw.get("clipboardTimeoutSec"), 30, 5, 120),
            result_limit=_bounded_int(raw.get("resultLimit"), 20, 5, 50),
            sync_on_unlock=_as_bool(raw.get("syncOnUnlock"), True),
            show_usernames=_as_bool(raw.get("showUsernames"), True),
        )

    def bw_argv(self) -> list[str]:
        try:
            argv = shlex.split(self.bw_command)
        except ValueError as exc:
            raise PublicError("The Bitwarden CLI command in Settings can't be parsed") from exc
        if not argv:
            raise PublicError("The Bitwarden CLI command in Settings is empty")
        return argv

    def environment(self, session: str = "") -> dict[str, str]:
        env = dict(os.environ)
        if self.app_data_dir.strip():
            try:
                app_dir = Path(os.path.abspath(os.path.expanduser(self.app_data_dir.strip())))
                info = app_dir.lstat()
            except FileNotFoundError:
                try:
                    app_dir.mkdir(mode=0o700, parents=True)
                    info = app_dir.lstat()
                except (OSError, ValueError) as exc:
                    raise PublicError("Couldn't create the CLI profile folder") from exc
            except (OSError, ValueError) as exc:
                raise PublicError("Couldn't read the CLI profile folder") from exc
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise PublicError("The CLI profile folder must belong to you")
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise PublicError("The CLI profile folder must not be readable by other users")
            env["BITWARDENCLI_APPDATA_DIR"] = str(app_dir)
        if session:
            env["BW_SESSION"] = session
        else:
            env.pop("BW_SESSION", None)
        return env


def _safe_string(value: Any, fallback: str, maximum: int) -> str:
    if value is None:
        return fallback
    return str(value)[:maximum]


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _private_runtime_directory(path: Path) -> bool:
    """Return whether path is a real, user-owned directory with mode 0700."""
    try:
        info = path.lstat()
    except (OSError, ValueError):
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) & 0o077 == 0
    )


def runtime_dir() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(f"/run/user/{os.getuid()}"))
    for candidate in candidates:
        if _private_runtime_directory(candidate):
            return candidate
    fallback = Path(tempfile.gettempdir()) / f"omawarden-{os.getuid()}"
    try:
        fallback.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except (OSError, ValueError) as exc:
        raise PublicError("OmaWarden couldn't create a private runtime folder") from exc
    if not _private_runtime_directory(fallback):
        raise PublicError("OmaWarden's fallback runtime folder isn't private")
    return fallback


def socket_path() -> Path:
    return runtime_dir() / "omawarden.sock"


def lock_path() -> Path:
    return runtime_dir() / "omawarden.lock"


def resolve_executable(command: str) -> str | None:
    if os.path.sep in command:
        path = os.path.abspath(os.path.expanduser(command))
        return path if os.path.isfile(path) and os.access(path, os.X_OK) else None
    return shutil.which(command)


def safe_url(value: Any) -> str:
    url = str(value or "").strip()
    if len(url) > 8192:
        raise PublicError("That website address is too long to open")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url):
        raise PublicError("That website address isn't valid")
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise PublicError("That website address isn't valid") from exc
    if parsed.scheme.lower() not in SAFE_URL_SCHEMES or not parsed.netloc or not hostname:
        raise PublicError("Only http and https websites can be opened")
    if parsed.username is not None or parsed.password is not None:
        raise PublicError("Website addresses containing sign-in details can't be opened")
    return url


def _display_text(value: Any, fallback: str, maximum: int) -> str:
    text = str(value or fallback).strip()
    # Normal vault metadata takes the zero-allocation fast path. Only malformed
    # control/format characters require rebuilding the string.
    if text and not text.isprintable():
        text = "".join(character if character.isprintable() else " " for character in text).strip()
    return (text or fallback)[:maximum]


def project_item_metadata(items: Any, show_usernames: bool) -> list[dict[str, Any]]:
    """Reduce full Bitwarden objects to the metadata the UI is allowed to see."""
    if not isinstance(items, list):
        return []
    projected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = _display_text(item.get("id"), "", MAX_ITEM_ID_CHARS + 1)
        if not item_id or len(item_id) > MAX_ITEM_ID_CHARS or item_id in seen_ids:
            continue
        try:
            item_type = int(item.get("type") or 0)
        except (TypeError, ValueError):
            continue
        if item_type not in {LOGIN_ITEM_TYPE, CARD_ITEM_TYPE}:
            continue
        common = {
            "id": item_id,
            "name": _display_text(item.get("name"), "Untitled", 512),
            "favorite": bool(item.get("favorite")),
            "type": item_type,
        }
        if item_type == LOGIN_ITEM_TYPE:
            raw_login = item.get("login")
            login: dict[str, Any] = raw_login if isinstance(raw_login, dict) else {}
            raw_uris = login.get("uris")
            uris: list[Any] = raw_uris if isinstance(raw_uris, list) else []
            first_url = ""
            for uri in uris:
                if not isinstance(uri, dict):
                    continue
                candidate = str(uri.get("uri") or "").strip()
                try:
                    first_url = safe_url(candidate)
                    break
                except PublicError:
                    continue
            username = _display_text(login.get("username"), "", 512) if show_usernames else ""
            projected.append(dict(
                common,
                username=username,
                url=first_url,
                hasPassword=bool(login.get("password")),
                hasTotp=bool(login.get("totp")),
            ))
        else:
            raw_card = item.get("card")
            card: dict[str, Any] = raw_card if isinstance(raw_card, dict) else {}
            raw_number = str(card.get("number") or "").strip()
            digits = "".join(character for character in raw_number if character.isdigit())
            projected.append(dict(
                common,
                username="",
                url="",
                brand=_display_text(card.get("brand"), "", 128),
                cardholder=(
                    _display_text(card.get("cardholderName"), "", 512)
                    if show_usernames else ""
                ),
                # Four trailing digits are useful recognition metadata; never
                # send the complete card number or security code to QML.
                last4=digits[-4:] if len(digits) >= 4 else "",
                hasNumber=bool(raw_number),
                hasCardholder=bool(str(card.get("cardholderName") or "").strip()),
                hasCardCode=bool(str(card.get("code") or "").strip()),
                hasExpiry=bool(str(card.get("expMonth") or "").strip())
                and bool(str(card.get("expYear") or "").strip()),
            ))
        seen_ids.add(item_id)
    projected.sort(key=lambda row: (not row["favorite"], row["name"].casefold(), row["username"].casefold()))
    return projected


def project_items(items: Any, limit: int, show_usernames: bool) -> list[dict[str, Any]]:
    """Project and limit items for callers that do not need a reusable index."""
    return project_item_metadata(items, show_usernames)[:limit]


def url_host(url: str) -> str:
    try:
        host = (urllib.parse.urlsplit(str(url or "")).hostname or "").casefold()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def build_search_index(items: list[dict[str, Any]]) -> list[SearchEntry]:
    """Precompute a case-insensitive haystack from allowlisted metadata only.

    Each entry is (item, haystack) where the haystack joins the item name,
    secondary display metadata, and host with newlines so ``term in haystack``
    stays a cheap containment test and the ranker can still tell the fields
    apart.
    """
    indexed: list[SearchEntry] = []
    for item in items:
        name = str(item.get("name") or "").casefold()
        secondary = str(item.get("username") or "").casefold()
        if item.get("type") == CARD_ITEM_TYPE:
            secondary = "card " + " ".join(
                str(item.get(field) or "").casefold()
                for field in ("cardholder", "brand", "last4")
            )
        host = url_host(str(item.get("url") or ""))
        indexed.append((item, f"{name}\n{secondary}\n{host}"))
    return indexed


def _term_rank(term: str, name: str, username: str, host: str) -> int | None:
    """Lower is better. None means the term does not match this row at all."""
    if name == term:
        return 0
    if name.startswith(term):
        return 1
    if any(word.startswith(term) for word in name.replace("-", " ").replace(".", " ").split()):
        return 2
    if host == term or host.startswith(term):
        return 3
    if any(part.startswith(term) for part in host.split(".")):
        return 4
    if term in name:
        return 5
    if username.startswith(term):
        return 6
    if term in host:
        return 7
    if term in username:
        return 8
    return None


def search_index(
    index: list[SearchEntry], query: str, limit: int
) -> list[dict[str, Any]]:
    """Return the best-ranked rows containing every whitespace-delimited term.

    Name matches outrank host matches, which outrank username matches, and
    prefix matches outrank mid-string ones, so typing "git" puts "GitHub"
    ahead of "Digital Ocean" even though both contain the letters. Ties keep
    favorites first and then fall back to the index's alphabetical order.
    """
    terms = query.casefold().split()
    if not terms:
        return [entry[0] for entry in index[:limit]]

    def ranked_matches():
        for position, (item, haystack) in enumerate(index):
            if not all(term in haystack for term in terms):
                continue
            name, username, host = haystack.split("\n", 2)
            score = 0
            for term in terms:
                rank = _term_rank(term, name, username, host)
                if rank is None:
                    break
                score += rank
            else:
                yield (score, 0 if item.get("favorite") else 1, position, item)

    # The panel can display at most 50 rows. Selecting the bounded top K avoids
    # sorting every broad match in very large vaults.
    ranked = heapq.nsmallest(limit, ranked_matches())
    return [item for _score, _favorite, _position, item in ranked]


def browse_index(
    index: list[SearchEntry],
    recent_ids: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Rows for an empty query: recently used first, then the index order.

    The index is already sorted favorites-first, so the browse list reads
    Recent → Favorites → everything else. Recent rows are flagged so the
    panel can label the group without a second lookup.
    """
    # At most five recents are retained. Scan once for just those IDs instead
    # of allocating a vault-sized lookup table every time the panel opens.
    wanted = set(recent_ids)
    by_id: dict[str, dict[str, Any]] = {}
    if wanted:
        for item, _haystack in index:
            item_id = item["id"]
            if item_id in wanted:
                by_id[item_id] = item
                if len(by_id) == len(wanted):
                    break
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item_id in recent_ids:
        recent_item = by_id.get(item_id)
        if recent_item is None or item_id in seen:
            continue
        rows.append(dict(recent_item, recent=True))
        seen.add(item_id)
    for item, _haystack in index:
        if len(rows) >= limit:
            break
        if item["id"] in seen:
            continue
        rows.append(item)
        seen.add(item["id"])
    return rows[:limit]


def card_field_value(item: Any, field: str) -> str:
    """Extract one copyable value inside the short-lived card filter process."""
    if not isinstance(item, dict) or item.get("type") != CARD_ITEM_TYPE:
        raise PublicError("That vault entry is not a card")
    raw_card = item.get("card")
    card: dict[str, Any] = raw_card if isinstance(raw_card, dict) else {}
    if field == "number":
        value = str(card.get("number") or "").strip()
    elif field == "cardholder":
        value = str(card.get("cardholderName") or "").strip()
    elif field == "cardCode":
        value = str(card.get("code") or "").strip()
    elif field == "expiry":
        month = str(card.get("expMonth") or "").strip()
        year = str(card.get("expYear") or "").strip()
        try:
            month = f"{int(month):02d}"
        except ValueError:
            month = ""
        if len(year) == 4 and year.isdigit():
            year = year[-2:]
        value = f"{month}/{year}" if month and year else ""
    else:
        raise PublicError("That card field can't be copied")
    if not value:
        raise PublicError("That card field is empty")
    return value[:4096]


def extract_card_field(args: argparse.Namespace) -> int:
    """Filter `bw get item` output without exposing the full item to the agent."""
    try:
        raw = sys.stdin.buffer.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PublicError("The card entry is too large")
        item = json.loads(raw.decode("utf-8"))
        sys.stdout.write(card_field_value(item, args.field))
        return 0
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, PublicError):
        return 1


def pinentry_executable(configured: str) -> str | None:
    mode = configured.strip().lower()
    if mode not in {"auto", "omarchy"}:
        try:
            parts = shlex.split(configured)
        except ValueError:
            return None
        return resolve_executable(parts[0]) if len(parts) == 1 else None
    # `omarchy` is retained as a compatibility value for early plugin configs;
    # it meant Qt Pinentry, not Omarchy's native shell UI. New installs use
    # `auto` for the default external prompt.
    candidates = (
        ("pinentry-qt", "pinentry-gnome3", "pinentry", "pinentry-curses")
        if mode == "omarchy"
        else ("pinentry-gnome3", "pinentry-qt", "pinentry", "pinentry-curses")
    )
    for name in candidates:
        found = resolve_executable(name)
        if found:
            return found
    return None


def _pinentry_command(proc: subprocess.Popen[str], command: str) -> tuple[bool, list[str]]:
    if proc.stdin is None or proc.stdout is None:
        raise PublicError("The unlock prompt closed unexpectedly")
    proc.stdin.write(command + "\n")
    proc.stdin.flush()
    data: list[str] = []
    while True:
        line = proc.stdout.readline()
        if line == "":
            return False, data
        line = line.rstrip("\r\n")
        if line.startswith("D "):
            data.append(urllib.parse.unquote(line[2:]))
        elif line == "OK" or line.startswith("OK "):
            return True, data
        elif line.startswith("ERR "):
            return False, data


def obtain_master_password(pinentry: str) -> bytearray:
    try:
        proc = subprocess.Popen(
            [pinentry],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
    )
    except OSError as exc:
        raise PublicError("The unlock prompt couldn't start") from exc
    try:
        if proc.stdout is None:
            raise PublicError("The unlock prompt couldn't start")
        greeting = proc.stdout.readline()
        if not greeting.startswith("OK"):
            raise PublicError("The unlock prompt couldn't start")
        for command in (
            "SETTITLE Unlock Bitwarden",
            "SETPROMPT Master password:",
            "SETDESC Unlock your Bitwarden vault for OmaWarden",
            "SETOK Unlock",
            "SETCANCEL Cancel",
        ):
            ok, _ = _pinentry_command(proc, command)
            if not ok:
                raise PublicError("The unlock prompt refused the request")
        ok, data = _pinentry_command(proc, "GETPIN")
        if not ok:
            raise PublicError("Unlock cancelled")
        return bytearray("\n".join(data), "utf-8")
    finally:
        if proc.poll() is None:
            try:
                _pinentry_command(proc, "BYE")
            except (BrokenPipeError, OSError):
                proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    """Best-effort bounded child cleanup, safe to call more than once."""
    try:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, ProcessLookupError, OSError):
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (AttributeError, ProcessLookupError, OSError):
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    except (ChildProcessError, OSError):
        pass


def _run_captured(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a bounded command and reap its whole wrapper process group."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


class Agent:
    def __init__(self) -> None:
        self.session = ""
        self.config = Config()
        # Only allowlisted display metadata is retained. Full Bitwarden item
        # objects are discarded as soon as this index has been built.
        self._item_index: list[SearchEntry] = []
        self._index_ready = False
        # Opaque item IDs of the last few entries copied or opened, newest
        # first. Lets the panel open on what you actually use instead of the
        # top of the alphabet. Memory only; cleared on sign-out and whenever
        # the CLI or profile changes.
        self._recent_ids: list[str] = []
        self.last_access = time.monotonic()
        self.last_request = time.monotonic()
        self.clipboards: set[subprocess.Popen[bytes]] = set()
        self._clipboard_lock = threading.Lock()
        self._status_cache: dict[str, Any] | None = None
        self._status_cached_at = 0.0

    def _bw(
        self,
        *arguments: str,
        session: bool = False,
        timeout: int = 30,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        argv = self.config.bw_argv() + list(arguments)
        try:
            return _run_captured(
                argv,
                env=self.config.environment(self.session if session else ""),
                timeout=timeout,
                input_bytes=input_bytes,
            )
        except FileNotFoundError as exc:
            raise PublicError("The Bitwarden CLI (bw) isn't installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise PublicError("Bitwarden took too long to respond") from exc

    def _json(self, completed: subprocess.CompletedProcess[bytes], failure: str) -> Any:
        if completed.returncode != 0:
            raise PublicError(failure)
        try:
            return json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicError("Bitwarden returned data OmaWarden couldn't read") from exc

    def _touch(self) -> None:
        self.last_access = time.monotonic()

    def _clear_index(self) -> None:
        self._item_index.clear()
        self._index_ready = False

    def _clear_status_cache(self) -> None:
        self._status_cache = None
        self._status_cached_at = 0.0

    def _drop_session(self, *, forget_recents: bool = False) -> None:
        self._stop_clipboards()
        self.session = ""
        self._clear_index()
        self._clear_status_cache()
        if forget_recents:
            self._forget_recents()

    def _remember_recent(self, item_id: str) -> None:
        if not item_id:
            return
        self._recent_ids = [item_id] + [known for known in self._recent_ids if known != item_id]
        del self._recent_ids[RECENT_LIMIT:]

    def _forget_recents(self) -> None:
        self._recent_ids = []

    def _load_index(self) -> None:
        completed = self._bw("list", "items", "--raw", "--nointeraction", session=True, timeout=45)
        items: Any = None
        try:
            items = self._json(completed, "Couldn't load the vault. Try syncing again.")
            metadata = project_item_metadata(items, self.config.show_usernames)
            self._item_index = build_search_index(metadata)
            self._index_ready = True
        finally:
            # Drop both decoded full objects and captured raw CLI output as
            # soon as the metadata projection is complete.
            if isinstance(items, list):
                items.clear()
            completed.stdout = b""

    def _warm_index(self) -> bool:
        """Best-effort index preparation that never turns a good sync into a failure."""
        self._clear_index()
        try:
            self._load_index()
        except PublicError:
            # Search will retry and surface the useful error if the user
            # actually asks for vault contents later.
            self._clear_index()
            return False
        return True

    def _vault_item(self, item_id: str) -> dict[str, Any]:
        if not item_id or len(item_id) > MAX_ITEM_ID_CHARS:
            raise PublicError("That vault entry is no longer available")
        if not self._index_ready:
            self._load_index()
        for item, _haystack in self._item_index:
            if item["id"] == item_id:
                return item
        raise PublicError("That vault entry is no longer available")

    def dependencies(self) -> dict[str, bool]:
        try:
            bw_first = self.config.bw_argv()[0]
        except PublicError:
            bw_first = ""
        return {
            "bw": bool(bw_first and resolve_executable(bw_first)),
            "pinentry": bool(pinentry_executable(self.config.pinentry_command)),
            "wlCopy": bool(resolve_executable("wl-copy")),
        }

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        # This process owns the only session OmaWarden can use, so an unlocked
        # status stays authoritative until an action, configuration change, or
        # automatic lock clears it. Avoid serializing fast index searches
        # behind the comparatively slow Node-based `bw status` command.
        cache_is_fresh = now - self._status_cached_at < STATUS_CACHE_SECONDS
        if self._status_cache is not None and (self.session or cache_is_fresh):
            cached = dict(self._status_cache)
            cached["dependencies"] = dict(self._status_cache.get("dependencies") or {})
            return cached
        dependencies = self.dependencies()
        if not dependencies["bw"]:
            self._drop_session()
            response = {
                "ok": True,
                "installed": False,
                "dependencies": dependencies,
                "status": "unavailable",
                "statusText": "Bitwarden CLI isn't installed",
            }
            self._status_cache = response
            self._status_cached_at = now
            return dict(response)
        try:
            completed = self._bw("status", "--raw", timeout=10, session=bool(self.session))
            payload = self._json(completed, "Couldn't read the vault status")
        except PublicError:
            self._drop_session()
            raise
        state = str(payload.get("status") or "unauthenticated") if isinstance(payload, dict) else "unauthenticated"
        labels = {
            "unlocked": "Vault unlocked",
            "locked": "Vault locked",
            "unauthenticated": "Sign in required",
        }
        if state not in labels:
            state = "error"
        # A usable unlocked state must be backed by the session held here. The
        # CLI cannot safely donate an unknown session from elsewhere.
        if state == "unlocked" and not self.session:
            state = "locked"
        if state != "unlocked":
            self._drop_session()
        reported_server = str(payload.get("serverUrl") or "") if isinstance(payload, dict) else ""
        if reported_server:
            try:
                reported_server = safe_url(reported_server)
            except PublicError:
                reported_server = ""
        response = {
            "ok": True,
            "installed": True,
            "dependencies": dependencies,
            "status": state,
            "statusText": labels.get(state, "Bitwarden status unknown"),
            "lastSync": _display_text(payload.get("lastSync"), "", 128) if isinstance(payload, dict) else "",
            "serverUrl": reported_server,
        }
        self._status_cache = response
        # Cache from completion, not from before the potentially slow CLI
        # call. Real `bw status` can take several seconds; using the earlier
        # timestamp made every queued monitor immediately repeat the work.
        self._status_cached_at = time.monotonic()
        return dict(response, dependencies=dict(dependencies))

    def _unlock_with_password(self, password: bytearray) -> dict[str, Any]:
        fifo: Path | None = None
        fifo_descriptor = -1
        response: dict[str, Any] | None = None
        try:
            self._clear_index()
            self._clear_status_cache()
            dependencies = self.dependencies()
            if not dependencies["bw"]:
                raise PublicError("The Bitwarden CLI (bw) isn't installed")
            if not password:
                raise PublicError("Enter your master password")
            if len(password) > MAX_MASTER_PASSWORD_BYTES:
                raise PublicError("The master password is too long")
            fifo = runtime_dir() / f"omawarden-password-{os.getpid()}-{time.monotonic_ns()}"
            os.mkfifo(fifo, mode=0o600)
            flags = os.O_RDWR | os.O_NONBLOCK
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            fifo_descriptor = os.open(fifo, flags)
            password_view = memoryview(password)
            written = 0
            while written < len(password_view):
                try:
                    count = os.write(fifo_descriptor, password_view[written:])
                except BlockingIOError as exc:
                    raise PublicError("The master password is too long") from exc
                if count <= 0:
                    raise PublicError("The master password couldn't be handed to Bitwarden")
                written += count
            os.write(fifo_descriptor, b"\n")
            argv = self.config.bw_argv() + ["unlock", "--raw", "--nointeraction", "--passwordfile", str(fifo)]
            try:
                completed = _run_captured(
                    argv,
                    env=self.config.environment(),
                    timeout=45,
                )
            except FileNotFoundError as exc:
                raise PublicError("The Bitwarden CLI (bw) isn't installed") from exc
            except subprocess.TimeoutExpired as exc:
                raise PublicError("Unlocking took too long. Try again.") from exc
            if completed.returncode != 0:
                raise PublicError("That master password didn't work")
            try:
                session = completed.stdout.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError as exc:
                raise PublicError("Bitwarden returned an unusable session") from exc
            if not session or any(character.isspace() for character in session):
                raise PublicError("Bitwarden returned an unusable session")
            self.session = session
            self._clear_status_cache()
            self._touch()
            # Syncing remains the panel's job so unlock can release the secret
            # inputs first. That sync warms the index before it reports done.
            response = {"ok": True, "status": "unlocked", "message": "Vault unlocked"}
        finally:
            for index in range(len(password)):
                password[index] = 0
            if fifo_descriptor >= 0:
                os.close(fifo_descriptor)
            if fifo is not None:
                try:
                    fifo.unlink()
                except FileNotFoundError:
                    pass
        if response is None:
            raise PublicError("Unlocking didn't return a usable response")
        # With server sync disabled there is no follow-up action to hide the
        # cold CLI load, so prepare the index now, after the password and FIFO
        # have both been cleared.
        if not self.config.sync_on_unlock:
            response["indexReady"] = self._warm_index()
        return response

    def unlock(self) -> dict[str, Any]:
        pinentry = pinentry_executable(self.config.pinentry_command)
        if not pinentry:
            raise PublicError("No Pinentry program was found for the unlock prompt")
        return self._unlock_with_password(obtain_master_password(pinentry))

    def unlock_with_password(self, password: bytearray) -> dict[str, Any]:
        """Consume a password delivered over the private native-prompt channel."""
        return self._unlock_with_password(password)

    def lock(self, *, automatic: bool = False) -> dict[str, Any]:
        # Wipe local capability state before waiting on the external CLI. Even
        # a broken or hung `bw lock` cannot prolong access through this agent.
        self._drop_session()
        try:
            if self.dependencies()["bw"]:
                self._bw("lock", "--quiet", "--nointeraction", timeout=15)
        except PublicError:
            pass
        return {
            "ok": True,
            "status": "locked",
            "message": "Vault locked automatically" if automatic else "Vault locked",
        }

    def logout(self) -> dict[str, Any]:
        self._stop_clipboards()
        self._clear_status_cache()
        try:
            if self.dependencies()["bw"]:
                completed = self._bw("logout", "--quiet", "--nointeraction", timeout=15)
                if completed.returncode != 0 and self.status().get("status") != "unauthenticated":
                    raise PublicError("Bitwarden couldn't sign out")
        finally:
            self._drop_session(forget_recents=True)
        return {"ok": True, "status": "unauthenticated", "message": "Signed out"}

    def sync(self) -> dict[str, Any]:
        self._require_unlocked()
        completed = self._bw("sync", "--quiet", "--nointeraction", session=True, timeout=60)
        if completed.returncode != 0:
            raise PublicError("Sync failed. Check your connection and try again.")
        self._clear_status_cache()
        index_ready = self._warm_index()
        self._touch()
        return {"ok": True, "message": "Vault synced", "indexReady": index_ready}

    def search(self, query: str) -> dict[str, Any]:
        self._require_unlocked()
        clean_query = query.strip()[:512]
        if not self._index_ready:
            self._load_index()
        self._touch()
        if clean_query:
            items = search_index(self._item_index, clean_query, self.config.result_limit)
        else:
            items = browse_index(self._item_index, self._recent_ids, self.config.result_limit)
        return {"ok": True, "query": clean_query, "items": items}

    def copy(self, item_id: str, field: str) -> dict[str, Any]:
        self._require_unlocked()
        if field not in COPY_FIELDS:
            raise PublicError("That field can't be copied")
        item = self._vault_item(item_id)
        item_type = item.get("type")
        available = ({
            "password": item.get("hasPassword") is True,
            "username": bool(item.get("username")),
            "totp": item.get("hasTotp") is True,
        } if item_type == LOGIN_ITEM_TYPE else {
            "number": item.get("hasNumber") is True,
            "cardholder": item.get("hasCardholder") is True,
            "cardCode": item.get("hasCardCode") is True,
            "expiry": item.get("hasExpiry") is True,
        } if item_type == CARD_ITEM_TYPE else {})
        if not available.get(field, False):
            noun = "code" if field in {"totp", "cardCode"} else field
            kind = "card" if item_type == CARD_ITEM_TYPE else "login"
            raise PublicError(f"That {kind} has no {noun} to copy")
        wl_copy = resolve_executable("wl-copy")
        if not wl_copy:
            raise PublicError("wl-clipboard isn't installed, so nothing can be copied")

        # A Wayland seat has one current clipboard. Retiring the old owner first
        # also bounds process/timer growth during repeated copy shortcuts.
        self._stop_clipboards()
        bw_process: subprocess.Popen[bytes] | None = None
        filter_process: subprocess.Popen[bytes] | None = None
        clipboard: subprocess.Popen[bytes] | None = None
        try:
            bw_arguments = [field, item_id] if item_type == LOGIN_ITEM_TYPE else ["item", item_id]
            bw_process = subprocess.Popen(
                self.config.bw_argv() + ["get"] + bw_arguments + ["--raw", "--nointeraction"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self.config.environment(self.session),
                start_new_session=True,
            )
            if bw_process.stdout is None:
                raise PublicError("Bitwarden couldn't open the secure copy pipe")
            copy_source = bw_process.stdout
            if item_type == CARD_ITEM_TYPE:
                filter_process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "extract-card-field", field],
                    stdin=bw_process.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                bw_process.stdout.close()
                if filter_process.stdout is None:
                    raise PublicError("OmaWarden couldn't open the card copy pipe")
                copy_source = filter_process.stdout
            clipboard = subprocess.Popen(
                [wl_copy, "--foreground", "--sensitive", "--trim-newline"],
                stdin=copy_source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            copy_source.close()
            deadline = time.monotonic() + COPY_TIMEOUT_SECONDS
            try:
                return_code = bw_process.wait(timeout=max(0.01, deadline - time.monotonic()))
                filter_code = (
                    filter_process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    if filter_process is not None else 0
                )
            except subprocess.TimeoutExpired as exc:
                _terminate_process(clipboard)
                if filter_process is not None:
                    _terminate_process(filter_process)
                _terminate_process(bw_process)
                raise PublicError("Bitwarden took too long to copy that value") from exc
            if return_code != 0 or filter_code != 0:
                _terminate_process(clipboard)
                label = "code" if field in {"totp", "cardCode"} else field
                raise PublicError(f"Couldn't copy the {label}")
            clipboard_status = clipboard.poll()
            if clipboard_status not in {None, 0}:
                raise PublicError("The secure clipboard couldn't be opened")
        except OSError as exc:
            if clipboard is not None:
                _terminate_process(clipboard)
            if filter_process is not None:
                _terminate_process(filter_process)
            if bw_process is not None:
                _terminate_process(bw_process)
            raise PublicError("The secure copy process couldn't start") from exc

        if clipboard is None:
            raise PublicError("The secure clipboard couldn't be opened")

        if clipboard.poll() is None:
            with self._clipboard_lock:
                self.clipboards.add(clipboard)
            timer = threading.Timer(self.config.clipboard_timeout_sec, self._expire_clipboard, args=(clipboard,))
            timer.daemon = True
            timer.start()
        self._touch()
        self._remember_recent(item_id)
        labels = {
            "totp": "Code",
            "number": "Card number",
            "cardholder": "Cardholder",
            "cardCode": "Security code",
            "expiry": "Expiry",
        }
        label = labels.get(field, field.capitalize())
        return {"ok": True, "message": f"{label} copied", "field": field}

    def configure_server(self, url: str) -> dict[str, Any]:
        state = self.status().get("status")
        if state != "unauthenticated":
            raise PublicError("Sign out before changing the server")
        clean = safe_url(url)
        completed = self._bw("config", "server", clean, "--quiet", "--nointeraction", timeout=30)
        if completed.returncode != 0:
            raise PublicError("Bitwarden rejected that server URL")
        self._clear_index()
        self._clear_status_cache()
        return {"ok": True, "message": "Server set to " + urllib.parse.urlparse(clean).netloc, "serverUrl": clean}

    def open_url(self, url: str, item_id: str = "") -> dict[str, Any]:
        self._require_unlocked()
        item = self._vault_item(item_id)
        clean = safe_url(item.get("url"))
        if safe_url(url) != clean:
            raise PublicError("That vault entry's website changed. Search again and retry.")
        launcher = resolve_executable("omarchy-launch-browser") or resolve_executable("xdg-open")
        if not launcher:
            raise PublicError("No browser launcher was found")
        try:
            subprocess.Popen([launcher, clean], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise PublicError("The browser couldn't be opened") from exc
        self._remember_recent(item_id)
        self._touch()
        return {"ok": True, "message": "Opened " + urllib.parse.urlparse(clean).netloc}

    def _require_unlocked(self) -> None:
        if not self.session:
            raise PublicError("The vault is locked")

    def _expire_clipboard(self, process: subprocess.Popen[bytes]) -> None:
        _terminate_process(process)
        with self._clipboard_lock:
            self.clipboards.discard(process)

    def _stop_clipboards(self) -> None:
        with self._clipboard_lock:
            active = list(self.clipboards)
        for process in active:
            self._expire_clipboard(process)

    def maybe_auto_lock(self) -> None:
        minutes = self.config.auto_lock_minutes
        if self.session and minutes > 0 and time.monotonic() - self.last_access >= minutes * 60:
            try:
                self.lock(automatic=True)
            except PublicError:
                self.session = ""
                self._clear_index()

    def dispatch(self, request: Any, password: bytearray | None = None) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise PublicError("Invalid request")
        self.last_request = time.monotonic()
        next_config = Config.from_request(request.get("config"))
        source_changed = (
            next_config.bw_command != self.config.bw_command
            or next_config.app_data_dir != self.config.app_data_dir
        )
        projection_changed = next_config.show_usernames != self.config.show_usernames
        config_changed = next_config != self.config
        if source_changed:
            # A session belongs to one CLI/profile. Never carry it into a
            # different command or BITWARDENCLI_APPDATA_DIR.
            self._drop_session(forget_recents=True)
        if source_changed or projection_changed:
            self._clear_index()
        if config_changed:
            self._clear_status_cache()
        self.config = next_config
        action = str(request.get("action") or "")
        if action == "status":
            return self.status()
        if action == "unlock":
            return self.unlock()
        if action == "unlock-with-password":
            if password is None:
                raise PublicError("The native unlock request had no password")
            return self.unlock_with_password(password)
        if action == "lock":
            return self.lock()
        if action == "logout":
            return self.logout()
        if action == "sync":
            return self.sync()
        if action == "search":
            return self.search(str(request.get("query") or ""))
        if action == "copy":
            return self.copy(str(request.get("id") or ""), str(request.get("field") or ""))
        if action == "configure-server":
            return self.configure_server(str(request.get("url") or ""))
        if action == "open-url":
            return self.open_url(str(request.get("url") or ""), str(request.get("id") or ""))
        if action == "shutdown":
            self.lock()
            return {"ok": True, "shutdown": True}
        raise PublicError("OmaWarden doesn't know that action")

    def idle_without_session(self) -> bool:
        return not self.session and time.monotonic() - self.last_request >= AGENT_IDLE_EXIT_SECONDS


def _peer_is_current_user(connection: socket.socket) -> bool:
    if not hasattr(socket, "SO_PEERCRED"):
        return True
    try:
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        peer_uid = int.from_bytes(credentials[4:8], byteorder=sys.byteorder)
        return peer_uid == os.getuid()
    except OSError:
        return False


def _receive_secret(connection: socket.socket, length: int) -> bytearray:
    if length <= 0:
        raise PublicError("Enter your master password")
    if length > MAX_MASTER_PASSWORD_BYTES:
        raise PublicError("The master password is too long")
    secret = bytearray(length)
    view = memoryview(secret)
    received = 0
    while received < length:
        count = connection.recv_into(view[received:])
        if count <= 0:
            for index in range(len(secret)):
                secret[index] = 0
            raise PublicError("The native unlock request ended early")
        received += count
    return secret


def _request_payload(request: dict[str, Any]) -> bytes:
    try:
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicError("Invalid request") from exc
    if len(payload) > MAX_REQUEST_BYTES:
        raise PublicError("Request is too large")
    return payload


def _open_lock_file(path: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise PublicError("OmaWarden's runtime lock isn't a private file")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


def serve() -> int:
    path = socket_path()
    lock_descriptor = _open_lock_file(lock_path())
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_descriptor)
        return 0
    if path.exists():
        try:
            path.unlink()
        except OSError:
            return 1
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    # A panel on several monitors can start a small burst of request clients.
    # Keep enough queued connections that a slow first Bitwarden status poll
    # does not reject otherwise valid local clients.
    server.listen(64)
    server.settimeout(1.0)
    agent = Agent()
    try:
        source_mtime = os.stat(__file__).st_mtime_ns
    except OSError:
        source_mtime = 0
    should_stop = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not should_stop:
            agent.maybe_auto_lock()
            try:
                source_changed = source_mtime != 0 and os.stat(__file__).st_mtime_ns != source_mtime
            except OSError:
                source_changed = True
            if source_changed or agent.idle_without_session():
                break
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            with connection:
                if not _peer_is_current_user(connection):
                    continue
                connection.settimeout(CLIENT_IO_TIMEOUT_SECONDS)
                stream = connection.makefile("rwb", buffering=0)
                password: bytearray | None = None
                response: dict[str, Any]
                try:
                    line = stream.readline(MAX_REQUEST_BYTES + 1)
                    if len(line) > MAX_REQUEST_BYTES:
                        response = {"ok": False, "error": "Request is too large"}
                    else:
                        request = json.loads(line.decode("utf-8"))
                        if not isinstance(request, dict):
                            raise PublicError("Invalid request")
                        if type(request.get("protocolVersion")) is not int or request["protocolVersion"] != PROTOCOL_VERSION:
                            raise PublicError("OmaWarden was updated; restart the shell and try again")
                        if request.get("action") == "unlock-with-password":
                            raw_secret_length = request.get("secretLength")
                            if type(raw_secret_length) is not int:
                                raise PublicError("The native unlock request is invalid")
                            secret_length = raw_secret_length
                            password = _receive_secret(connection, secret_length)
                        response = agent.dispatch(request, password)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    response = {"ok": False, "error": "Invalid request"}
                except TimeoutError:
                    response = {"ok": False, "error": "Request timed out"}
                except PublicError as exc:
                    response = {"ok": False, "error": str(exc)}
                except (BrokenPipeError, ConnectionResetError, OSError):
                    response = {"ok": False, "error": "Request ended early"}
                # A malformed CLI payload must not take down the long-lived
                # helper. The detail stays private; the UI gets a safe error.
                except Exception:  # noqa: BLE001
                    response = {"ok": False, "error": "Something went wrong inside OmaWarden's helper"}
                finally:
                    if password is not None:
                        for index in range(len(password)):
                            password[index] = 0
                payload = (json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8")
                if len(payload) > MAX_RESPONSE_BYTES:
                    payload = b'{"ok":false,"error":"Response is too large"}\n'
                try:
                    stream.write(payload)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                try:
                    stream.close()
                except OSError:
                    pass
                if response.get("shutdown"):
                    should_stop = True
    finally:
        try:
            agent.lock()
        except PublicError:
            agent.session = ""
            agent._stop_clipboards()
        server.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        os.close(lock_descriptor)
    return 0


def _connect(request: dict[str, Any], timeout: float = 70.0) -> dict[str, Any]:
    path = socket_path()
    payload = _request_payload(request)
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    started = False
    while time.monotonic() < deadline:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(max(1.0, deadline - time.monotonic()))
        try:
            client.connect(str(path))
            client.sendall(payload)
            stream = client.makefile("rb")
            line = stream.readline(MAX_RESPONSE_BYTES + 1)
            if not line or len(line) > MAX_RESPONSE_BYTES:
                raise PublicError("OmaWarden's helper returned no usable response")
            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicError("OmaWarden's helper returned data that couldn't be read") from exc
            return response if isinstance(response, dict) else {"ok": False, "error": "Invalid agent response"}
        except (TimeoutError, FileNotFoundError, BrokenPipeError, ConnectionRefusedError, ConnectionResetError) as exc:
            last_error = exc
            if not started:
                start_agent()
                started = True
            time.sleep(0.05)
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EINTR, errno.ENOBUFS}:
                last_error = exc
                if not started:
                    start_agent()
                    started = True
                time.sleep(0.05)
                continue
            raise PublicError("OmaWarden's helper couldn't be reached") from exc
        finally:
            client.close()
    raise PublicError("OmaWarden's helper didn't start. Check that python3 is available.") from last_error


def _connect_secret(request: dict[str, Any], secret: bytearray, timeout: float = 70.0) -> dict[str, Any]:
    """Send a JSON header followed by raw secret bytes over the private socket."""
    path = socket_path()
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    started = False
    request["secretLength"] = len(secret)
    header = _request_payload(request)
    while time.monotonic() < deadline:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(max(1.0, deadline - time.monotonic()))
        try:
            client.connect(str(path))
            client.sendall(header)
            client.sendall(secret)
            stream = client.makefile("rb")
            line = stream.readline(MAX_RESPONSE_BYTES + 1)
            if not line or len(line) > MAX_RESPONSE_BYTES:
                raise PublicError("OmaWarden's helper returned no usable response")
            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicError("OmaWarden's helper returned data that couldn't be read") from exc
            return response if isinstance(response, dict) else {"ok": False, "error": "Invalid agent response"}
        except (TimeoutError, FileNotFoundError, BrokenPipeError, ConnectionRefusedError, ConnectionResetError) as exc:
            last_error = exc
            if not started:
                start_agent()
                started = True
            time.sleep(0.05)
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EINTR, errno.ENOBUFS}:
                last_error = exc
                if not started:
                    start_agent()
                    started = True
                time.sleep(0.05)
                continue
            raise PublicError("OmaWarden's helper couldn't be reached") from exc
        finally:
            client.close()
    raise PublicError("OmaWarden's helper didn't start. Check that python3 is available.") from last_error


def unlock_stdin(args: argparse.Namespace) -> int:
    """Relay one native-prompt password from stdin to the private agent."""
    password = bytearray()
    try:
        raw_config = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not raw_config or len(raw_config) > MAX_REQUEST_BYTES:
            raise PublicError("The native unlock configuration is invalid")
        config = json.loads(raw_config.decode("utf-8"))
        if not isinstance(config, dict):
            raise PublicError("The native unlock configuration is invalid")
        password = bytearray(sys.stdin.buffer.read(MAX_MASTER_PASSWORD_BYTES + 1))
        if len(password) > MAX_MASTER_PASSWORD_BYTES:
            raise PublicError("The master password is too long")
        request = {
            "action": "unlock-with-password",
            "config": config,
            "protocolVersion": PROTOCOL_VERSION,
        }
        response = _connect_secret(request, password, timeout=max(1.0, min(120.0, args.timeout)))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, PublicError) as exc:
        response = {"ok": False, "error": str(exc)}
    finally:
        for index in range(len(password)):
            password[index] = 0
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    return 0 if response.get("ok") else 1


def start_agent() -> None:
    # Multiple clients may arrive together. Each may briefly spawn a daemon,
    # but serve() holds an advisory lock for its full lifetime so only one can
    # ever bind or replace the socket.
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise PublicError("OmaWarden's helper couldn't start") from exc


def config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "bwCommand": args.bw_command,
        "pinentryCommand": args.pinentry_command,
        "appDataDir": args.app_data_dir,
        "autoLockMinutes": args.auto_lock_minutes,
        "clipboardTimeoutSec": args.clipboard_timeout_sec,
        "resultLimit": args.result_limit,
        "syncOnUnlock": args.sync_on_unlock,
        "showUsernames": args.show_usernames,
    }


def interactive_environment(args: argparse.Namespace) -> tuple[list[str], dict[str, str]]:
    config = Config.from_request(config_from_args(args))
    return config.bw_argv(), config.environment()


def _pause(message: str = "Press Enter to close this window.") -> None:
    try:
        input(f"\n{message}")
    except EOFError:
        pass


def _cli_status(argv: list[str], env: dict[str, str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv + ["status", "--raw"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False
        )
        payload = json.loads(completed.stdout.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def login_terminal(args: argparse.Namespace) -> int:
    """Interactive `bw login`, run in a terminal so the email, master password,
    and two-step code are typed straight into Bitwarden's own prompt."""
    try:
        argv, env = interactive_environment(args)
        print("OmaWarden — Sign in to Bitwarden")
        print("=" * 32)
        status = _cli_status(argv, env)
        if status.get("status") in {"locked", "unlocked"}:
            print("\nYou're already signed in. Back in the bar, choose Unlock vault.")
            _pause()
            return 0
        wanted = str(getattr(args, "server_url", "") or "").strip()
        if wanted:
            try:
                wanted = safe_url(wanted)
            except PublicError as exc:
                print(f"\nThe configured server URL was ignored: {exc}")
                wanted = ""
        current = str(status.get("serverUrl") or "").strip()
        if wanted and wanted.rstrip("/") != current.rstrip("/"):
            print(f"\nPointing the Bitwarden CLI at {wanted} …")
            configured = subprocess.run(argv + ["config", "server", wanted, "--quiet", "--nointeraction"], env=env, check=False)
            if configured.returncode != 0:
                print("Bitwarden rejected that server URL. Fix it in OmaWarden's settings and try again.")
                _pause()
                return configured.returncode
        host = urllib.parse.urlparse(wanted or current).netloc or "bitwarden.com"
        print(f"\nSigning in to {host}.")
        print("Bitwarden will ask for your email, master password and,")
        print("if enabled, a two-step code.\n")
        completed = subprocess.run(argv + ["login"], env=env, check=False)
        if completed.returncode == 0:
            print("\nSigned in. Back in the bar, choose Unlock vault.")
        else:
            print("\nSign-in didn't complete. Close this window and try again from the bar.")
        _pause()
        return completed.returncode
    except (PublicError, FileNotFoundError) as exc:
        print(f"\nOmaWarden: {exc}", file=sys.stderr)
        _pause()
        return 1


def install_terminal(args: argparse.Namespace) -> int:
    print("OmaWarden — Install requirements")
    print("=" * 32)
    print("\nOmaWarden needs bitwarden-cli and wl-clipboard.")
    if args.with_pinentry:
        print("The Pinentry unlock prompt also needs pinentry.")
    print()
    omarchy = resolve_executable("omarchy")
    if not omarchy:
        print("The omarchy command wasn't found, so the packages can't be installed from here.", file=sys.stderr)
        names = "bitwarden-cli, wl-clipboard and pinentry" if args.with_pinentry else "bitwarden-cli and wl-clipboard"
        print(f"Install {names} with your package manager instead.")
        _pause()
        return 1
    packages = ["bitwarden-cli", "wl-clipboard"]
    if args.with_pinentry:
        packages.append("pinentry")
    completed = subprocess.run(
        [omarchy, "pkg", "add"] + packages,
        check=False,
    )
    if completed.returncode == 0:
        print("\nAll set. Back in the bar, choose Sign in.")
    else:
        print("\nInstallation didn't finish. Review the output above, then try again from the bar.")
    _pause()
    return completed.returncode


def open_desktop(_args: argparse.Namespace) -> int:
    candidates = [
        ["uwsm", "app", "--", "bitwarden.desktop"],
        ["gtk-launch", "bitwarden.desktop"],
        ["flatpak", "run", "com.bitwarden.desktop"],
        ["bitwarden"],
    ]
    for command in candidates:
        executable = resolve_executable(command[0])
        if executable:
            try:
                process = subprocess.Popen(
                    [executable] + command[1:],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                try:
                    return_code = process.wait(timeout=DESKTOP_LAUNCH_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    return 0
                if return_code == 0:
                    return 0
            except OSError:
                continue
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OmaWarden local agent")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("serve", help="Run the private per-user agent")
    request_parser = subparsers.add_parser("request", help="Send one JSON request from stdin")
    request_parser.add_argument("--timeout", type=float, default=70.0)
    unlock_parser = subparsers.add_parser("unlock-stdin", help="Relay a native prompt over stdin")
    unlock_parser.add_argument("--timeout", type=float, default=55.0)
    card_filter = subparsers.add_parser("extract-card-field", help=argparse.SUPPRESS)
    card_filter.add_argument("field", choices=sorted(CARD_COPY_FIELDS))
    interactive = argparse.ArgumentParser(add_help=False)
    interactive.add_argument("--bw-command", default="bw")
    interactive.add_argument("--pinentry-command", default="auto")
    interactive.add_argument("--app-data-dir", default="")
    interactive.add_argument("--auto-lock-minutes", type=int, default=15)
    interactive.add_argument("--clipboard-timeout-sec", type=int, default=30)
    interactive.add_argument("--result-limit", type=int, default=20)
    interactive.add_argument("--sync-on-unlock", action=argparse.BooleanOptionalAction, default=True)
    interactive.add_argument("--show-usernames", action=argparse.BooleanOptionalAction, default=True)
    interactive.add_argument("--server-url", default="")
    subparsers.add_parser("login-terminal", parents=[interactive], help="Run interactive Bitwarden login")
    install_parser = subparsers.add_parser("install-terminal", help="Install runtime dependencies through Omarchy")
    install_parser.add_argument("--with-pinentry", action="store_true")
    subparsers.add_parser("open-desktop", help="Open Bitwarden Desktop")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "serve":
        return serve()
    if args.mode == "unlock-stdin":
        return unlock_stdin(args)
    if args.mode == "extract-card-field":
        return extract_card_field(args)
    if args.mode == "request":
        try:
            # Quickshell keeps the Process stdin pipe open for the process
            # lifetime, so one newline-delimited request must be sufficient;
            # waiting for EOF would deadlock the top-bar service.
            raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if len(raw) > MAX_REQUEST_BYTES:
                raise PublicError("Request is too large")
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise PublicError("Invalid request")
            request["protocolVersion"] = PROTOCOL_VERSION
            response = _connect(request, timeout=max(1.0, min(120.0, args.timeout)))
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, PublicError) as exc:
            response = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        return 0 if response.get("ok") else 1
    if args.mode == "login-terminal":
        return login_terminal(args)
    if args.mode == "install-terminal":
        return install_terminal(args)
    if args.mode == "open-desktop":
        return open_desktop(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
