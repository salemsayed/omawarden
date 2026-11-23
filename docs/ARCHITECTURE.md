# Architecture

```text
BarWidget.qml
  ├── Panel.qml ──► Service.qml ──► omawarden-agent.py request ──┐
  └── UnlockPrompt.qml ──────────► omawarden-agent.py unlock-stdin│
                                                                ▼
                    private Unix socket (0600 + peer UID + frame deadlines)
                              local agent (one per user, idle-exits)
                                ├── bw
                                ├── pinentry   (Pinentry prompt only)
                                └── wl-copy
```

`BarWidget.qml` is the manifest entry point for the bar widget. It owns the
bar icon, forwards Omarchy's bar, settings, popout, and IPC contracts to the
panel, and exposes the public IPC surface (`open`, `toggle`, `settings`,
`search`, `sync`, `lock`, `unlock`, `status`, …).

`Panel.qml` owns presentation: the three-step gate (install → sign in →
unlock), the vault view (search box, ranked and grouped results, keyboard
cursor, shortcut legend), the clipboard countdown notice, and the in-panel
settings page. Settings are written through `bar.shell.updateEntryInline`,
making `shell.json` the only persistent UI configuration. All copy for the
gate, notices, and groups comes from `Model.js` so it can be unit-tested.

`Model.js` is pure functions: response parsing, state labels, gate copy,
setup steps, requirement rows, result grouping, action availability, and
human-readable durations. The Node test suite exercises it directly.

`Service.qml` serializes bounded requests and parses allowlisted responses.
Status and actions run one helper process per request; separate status and
action processes keep the bar responsive while preventing duplicate actions.
Searches go straight to the agent's socket, whose path the status response
reports, and fall back to a helper process if the socket can't be reached.
Search input uses a 30 ms debounce, just above the usual key-repeat interval,
and coalesces in-flight requests without presenting stale results. After a
successful unlock it triggers the sync itself in the background.
`ScreenLockMonitor.qml` checks
the compositor through `omarchy-hyprland-session-locked` every 500 ms with a
one-second process timeout. It uses no private shell authentication objects.
Unknown, failed, or stale results block unlocking; with screen-lock protection
enabled they also queue a vault lock. A lock event stays pending across busy
operations and a later desktop unlock until the vault lock succeeds.

`UnlockPrompt.qml` is the native unlock overlay, privately owned by the bar
widget rather than advertised as another plugin kind. This keeps Omarchy's
numbered bar-panel routing pointed at the vault panel. The prompt takes
exclusive keyboard focus and hands the password to
`omawarden-agent.py unlock-stdin` over stdin. It clears its field on submit,
dismiss, and session lock. An in-flight native unlock may finish after its
surface closes; its completion carries the observed lock event so the service
relocks the vault even if the desktop has since been unlocked again.

`omawarden-agent.py` is standard-library Python. The short-lived `request`
mode starts or connects to a long-lived per-user agent; `unlock-stdin` does
the same for one native-prompt password. The agent holds the session key,
executes Bitwarden operations, projects allowlisted login and card metadata,
ranks searches, tracks recently used item IDs, manages clipboard owner
processes, and enforces the inactivity lock. Card copies pipe `bw get item`
through a short-lived field filter because the CLI has no direct card-field
command. After unlock, once the password and its FIFO are cleared, the agent
builds an in-memory index from the local vault containing only the same
allowlisted metadata returned to QML. Searches that arrive first wait for that
one load rather than starting another. Sync rebuilds the index from the fresh
vault and swaps it in when it is ready, so searches keep answering from the
previous index meanwhile; relevant configuration changes rebuild it too, and
lock, sign-out and agent exit wipe it.

The agent serves each client on its own thread. Bitwarden CLI commands run one
at a time; searches, cached status and recents never wait for them. A session
is only set while the CLI lock is held, and every CLI result is applied only if
no lock, sign-out or profile change happened meanwhile, so a sync that finishes
after a lock cannot bring its index back. Lock wipes the session, index and
clipboard at once, before waiting for the CLI. Every CLI command runs with
`--response`, and the agent takes the reply as soon as its JSON is complete:
the CLI keeps its process alive for one to two seconds after answering while
internal caches expire, so the finished process is reaped in the background
and terminated if it lingers past 30 seconds. CLI storage is guarded by its own
file lock, so a lingering process cannot overwrite a newer one. The CLI also
gets a private Node compile cache under `~/.cache/omawarden` (compiled CLI code
only) unless `NODE_COMPILE_CACHE` is already set. On exit the agent finishes
requests it has already accepted before it locks.

Search keeps a compact, case-folded haystack per projected item. Ranking uses
a bounded top-K selection because the UI can show at most 50 rows, avoiding a
full sort for broad queries in large vaults. The last five recent IDs are
resolved with a bounded scan instead of building another vault-sized map.
Near-simultaneous locked or signed-out status requests from per-monitor widget
instances share a one-second cache measured from completion of the underlying
CLI poll. While the agent owns an unlocked session, that response remains
authoritative until a state or configuration change invalidates it.

The socket lives in `$XDG_RUNTIME_DIR/omawarden.sock`, falling back to a
user-owned runtime directory only when necessary. An advisory lock prevents
duplicate daemons. Each connection carries a single newline-terminated JSON
request (optionally followed by raw secret bytes for the native unlock) and
is subject to protocol-version, peer-UID, size, and read-deadline checks. Child
commands run without a shell in their own process groups so timeout and lock
cleanup also reap wrappers. The agent exits when its source file changes, so
plugin updates never leave a stale helper running.
