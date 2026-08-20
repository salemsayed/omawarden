# Changelog

## 1.0.0 - 2026-08-20

First public release.

- The plugin id is now `io.github.salemsayed.omawarden`, matching the plugin
  name and the repository. Earlier private builds used
  `io.github.salemsayed.omabitwarden`; re-add the widget under the new id.
- Settings wording aligned between the panel, the manifest and the README:
  *Unlock prompt* (Pinentry / Native) and *Pinentry command*, with the
  inactivity delay bounded to 5–240 minutes behind its own switch.
- The settings and desktop-app buttons now advertise shortcuts that work in
  the current view (`Ctrl+,` and the new `Ctrl+D` while the vault is open,
  `s` and `d` while it is locked). An *Enter copies* value written in any
  case from the command line is reflected correctly in the panel.
- The terminal hand-off notices read naturally and clear themselves once the
  vault state moves on, and an older notice timer can no longer erase a newer
  message.
- The vault view no longer flashes "No logins yet" while the first search of a
  freshly opened (or freshly unlocked) panel is still on its way; the empty
  copy only appears once a search has actually completed.
- Closing the panel discards any running or queued search instead of letting
  it repopulate the hidden list, and a failed status check drops the list too.
- Queries with leading or trailing spaces update the results like any other;
  previously the helper's trimmed echo was mistaken for a stale response.
- Opening the Bitwarden desktop app now reports when it isn't installed
  instead of doing nothing, tries the Flatpak (`com.bitwarden.desktop`) as
  well, and treats a launcher that fails immediately as a failure.
- The native unlock prompt only closes the panel when it really opened, so a
  busy or screen-locked prompt can't leave a stale "enter your master
  password" notice behind; it asks to unlock *your vault* rather than
  OmaWarden.
- Coming back from Settings re-runs the search, so a panel opened straight
  into Settings shows the vault when you return.
- The header's match count hides while a new search is in flight instead of
  describing the previous list, and the panel may grow to 700 units so a
  notice (sync, clipboard countdown) no longer pushes the key legend below
  the fold.
- New README, screenshots and demo GIF captured against a stand-in CLI with
  fictional logins; a marketplace preview card.

## 0.2.0 - 2026-08-20

A release-readiness pass over the whole user experience.

### Search and results

- Ranked search: name prefixes outrank site matches, which outrank username
  matches, so `git` finds GitHub before DigitalOcean. Favorites win ties.
- Recently used logins (the last five copied or opened) appear first when the
  panel opens, followed by Favorites and All logins, with group labels while
  browsing.
- Only login items are listed; cards, identities, and secure notes carried no
  actions and were dead rows.
- The first row is always highlighted, so Enter's target is never a mystery.
- A clear button in the search field, friendlier empty states.

### Keyboard

- Shortcuts now work while typing in the search box: `Ctrl+C` password,
  `Ctrl+B` username, `Ctrl+T` one-time code, `Ctrl+U` open site (KeePassXC's
  map), `Shift+Enter` for the other copy field, `Ctrl+R` sync, `Ctrl+L` lock,
  `Ctrl+,` settings, `PageUp`/`PageDown`. The previous single-letter hotkeys
  were unreachable in the vault view because the search field always had
  focus.

### Onboarding

- A three-step strip (Install → Sign in → Unlock) shows where you are.
- The setup state lists each requirement with a check or a cross and the
  package behind it.
- A configured server URL is applied automatically as part of sign-in; the
  sign-in state says which server it will use. The separate "Apply server"
  step is gone.
- The sign-in terminal explains what it will ask for and skips `bw login`
  when you are already signed in.

### Unlock

- Pinentry is the default and recommended unlock prompt, keeping the master
  password outside the long-lived shell process.
- Native Omarchy unlock remains available as a themed overlay drawn by the
  shell, with the password relayed to the helper over stdin and cleared from
  each application-level holder after transfer.
- The native prompt is owned privately by the widget, so Omarchy's numbered
  panel shortcuts open the vault panel instead of accidentally summoning the
  password prompt.
- Unlock now rechecks the shared agent state before prompting, and cancellation
  or an unlocked status clears the prompt message immediately. This prevents a
  stale monitor or dismissed prompt from claiming a master password is needed.
- Unknown or missing prompt settings fail safely to Pinentry; Native must be
  selected explicitly in Settings.
- Unlock returns immediately; sync-after-unlock now runs in the background so
  results show at once from the local cache and refresh when the sync lands.

### Clipboard

- The copy notice counts the remaining sensitive-clipboard lifetime down and
  is cleared when the vault locks.

### Settings

- Reorganised into Locking & unlock, Clipboard & search, Account, and
  Advanced, with plain-language descriptions.
- Account section shows where you are signed in and offers a two-tap sign-out
  (new `logout` agent action).
- Text fields save on Enter or focus loss and confirm with a brief "Saved".
- Opening settings no longer drops the cursor into the CLI command field.
- Requirements check with an inline install button.

### Writing

- Every user-facing string was rewritten for people: errors read as
  sentences, the gate copy explains what happens without mentioning session
  keys or agents, the manifest and README describe what the plugin does for
  you.

### IPC

- `search <text>` opens the panel with a query filled in, for keybindings.

### Release hardening

- Private runtime directories, symlink-safe lock files, peer UID checks,
  protocol versions, frame limits, and a three-second incomplete-client
  deadline harden the local socket against stale and malformed clients.
- Copy and website actions are authorized against projected login metadata.
  Failed and timed-out CLI/clipboard pipelines now reap their complete process
  groups; lock, sign-out, status failure, and profile changes retire every
  clipboard owner.
- Native unlock no longer needs a FIFO writer thread, so an early CLI exit
  cannot strand a secret-holding thread. Password limits and cleanup apply on
  every failure path.
- Warm search uses bounded top-K ranking, recent browsing avoids a vault-sized
  lookup allocation, and per-monitor status polls share a strictly invalidated
  one-second cache measured after slow CLI polls complete. The local socket
  backlog and transient-connect retries absorb monitor startup bursts.
- Sensitive copies use a timed foreground clipboard owner instead of
  `--paste-once`, because Omarchy's clipboard-history watcher consumes the
  first transfer while checking the sensitivity marker. The watcher still
  excludes the value from history, and the agent clears it at the configured
  deadline, on replacement, lock, sign-out, or failure.
- The expanded test suite covers concurrency, malformed and partial IPC,
  oversized/truncated secrets, permission and symlink failures, process
  cleanup, inactivity locking, large-vault ranking, manifest drift, and QML
  input bounds. CI now adds Ruff, mypy, Bandit, and release-schema checks.

## 0.1.0 - 2026-08-20

- Initial Omarchy Quattro bar widget and panel.
- Metadata-only Bitwarden search.
- Secure password, username, and TOTP copy actions.
- Pinentry unlock with in-memory session ownership.
- Sync, lock, login, server configuration, desktop launch, and dependency
  installation flows.
- Complete in-panel settings with native Omarchy persistence.
- Panel design built on the Omarchy component kit: a status hero with the
  vault state and sync age, monogram result rows with a keyboard cursor rail,
  native switches and a segmented Enter-key control, key-cap shortcut legend,
  and an inline notice that counts the sensitive clipboard down.
- Self-hosted, EU, alternate-profile, and custom CLI support.
- Automated model, protocol, projection, clipboard, and security tests.
- Near-instant warm search through a memory-only allowlisted metadata index,
  with stale-query coalescing and index invalidation on sync or lock.
- Optional vault lock tied directly to Omarchy's compositor session lock.
- Theme-aware Qt Pinentry as the default unlock prompt, preserving the
  separate secure prompt process.
