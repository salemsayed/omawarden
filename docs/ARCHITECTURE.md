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

`Service.qml` serializes bounded requests, runs one helper process per
request, and parses allowlisted responses. Separate status, search, and
action processes keep the bar responsive while preventing duplicate actions.
Search input uses a short debounce and coalesces in-flight requests without
presenting stale results. After a successful unlock it triggers the sync
itself; that background action prepares the metadata index before reporting
completion, so the first panel search is warm. It also observes Omarchy's
native lock service and reliably queues a vault lock when the screen locks.

`UnlockPrompt.qml` is the native unlock overlay, privately owned by the bar
widget rather than advertised as another plugin kind. This keeps Omarchy's
numbered bar-panel routing pointed at the vault panel. The prompt takes
exclusive keyboard focus and hands the password to
`omawarden-agent.py unlock-stdin` over stdin. It clears its field on submit,
dismiss, and session lock.

`omawarden-agent.py` is standard-library Python. The short-lived `request`
mode starts or connects to a long-lived per-user agent; `unlock-stdin` does
the same for one native-prompt password. The agent holds the session key,
executes Bitwarden operations, projects allowlisted login and card metadata,
ranks searches, tracks recently used item IDs, manages clipboard owner
processes, and enforces the inactivity lock. Card copies pipe `bw get item`
through a short-lived field filter because the CLI has no direct card-field
command. After unlock the agent builds an in-memory index containing only the
same allowlisted metadata returned to QML;
the automatic sync performs that cold work before it reports completion, or
unlock does so after clearing its secret inputs when automatic sync is off.
Sync and relevant configuration changes rebuild the index; lock, sign-out,
and agent exit wipe it.

Search keeps a compact, case-folded haystack per projected item. Ranking uses
a bounded top-K selection because the UI can show at most 50 rows, avoiding a
full sort for broad queries in large vaults. The last five recent IDs are
resolved with a bounded scan instead of building another vault-sized map.
Near-simultaneous locked or signed-out status requests from per-monitor widget
instances share a one-second cache measured from completion of the underlying
CLI poll. While the agent owns an unlocked session, that response remains
authoritative until a state or configuration change invalidates it; this keeps
routine status polling from blocking interactive searches behind `bw status`.

The socket lives in `$XDG_RUNTIME_DIR/omawarden.sock`, falling back to a
user-owned runtime directory only when necessary. An advisory lock prevents
duplicate daemons. Each connection carries a single newline-terminated JSON
request (optionally followed by raw secret bytes for the native unlock) and
is subject to protocol-version, peer-UID, size, and read-deadline checks. Child
commands run without a shell in their own process groups so timeout and lock
cleanup also reap wrappers. The agent exits when its source file changes, so
plugin updates never leave a stale helper running.
