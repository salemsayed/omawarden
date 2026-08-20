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
itself so cached results appear immediately. It also observes Omarchy's
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
executes Bitwarden operations, projects item metadata (login items only),
ranks searches, tracks recently used item IDs, manages clipboard owner
processes, and enforces the inactivity lock. On the first search after
unlock it builds an in-memory index containing only the same allowlisted
metadata returned to QML. Sync and relevant configuration changes invalidate
the index; lock, sign-out, and agent exit wipe it.

Search keeps a compact, case-folded haystack per projected login. Ranking uses
a bounded top-K selection because the UI can show at most 50 rows, avoiding a
full sort for broad queries in large vaults. The last five recent IDs are
resolved with a bounded scan instead of building another vault-sized map.
Near-simultaneous status requests from per-monitor widget instances share a
one-second cache measured from completion of the underlying CLI poll, which
every state or configuration change invalidates.

The socket lives in `$XDG_RUNTIME_DIR/omawarden.sock`, falling back to a
user-owned runtime directory only when necessary. An advisory lock prevents
duplicate daemons. Each connection carries a single newline-terminated JSON
request (optionally followed by raw secret bytes for the native unlock) and
is subject to protocol-version, peer-UID, size, and read-deadline checks. Child
commands run without a shell in their own process groups so timeout and lock
cleanup also reap wrappers. The agent exits when its source file changes, so
plugin updates never leave a stale helper running.
