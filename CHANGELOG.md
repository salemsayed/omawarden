# Changelog

## 1.2.1 - 2026-11-23

Copying is three times faster. Measured on the same 911-item test vault and
Bitwarden CLI (2026.2.0) as 1.2.0, median of 36 copies through the real panel
service, against 1.2.0:

- A password, username, one-time code or card field lands on the clipboard
  about 1.0 second after Enter, down from 3.0. `bw get` has the value ready
  after about a second but keeps its process alive for almost two more while
  internal caches expire, and the copy used to wait for it to exit. Every copy
  now pipes `bw get --response` through a short-lived filter that hands the
  value to `wl-copy` and exits as soon as the CLI's JSON is complete; the CLI
  exits in the background. Login fields now use the same filter cards already
  used, so the value still never passes through the helper or the panel.
- Copy, lock, sync and the other panel actions go straight to the helper's
  socket instead of starting a helper process each time, saving about 70 ms,
  and fall back to the process if the socket can't be reached.
- Fixed a Quickshell crash, present since 1.2.0, when a search reached the
  helper while it was shutting down (for example during an update): the
  helper closed the connection unanswered and the panel tore the socket down
  inside its own error handler. The panel now retries through a helper
  process once that handler has returned.

## 1.2.0 - 2026-11-23

Measured on a 911-item test vault with the same Bitwarden CLI (2026.2.0),
median of repeated runs, against 1.1.8:

- Results appear 3.7 seconds after you enter the master password, down from
  9.4. Right after unlock the helper builds its search index from the vault on
  disk, then syncs in the background.
- Search answers in about a millisecond, down from 79 ms. The panel sends
  searches straight to the helper's socket instead of starting a helper
  process for every keystroke, and falls back to the process if the socket
  can't be reached. The search debounce is 30 ms, down from 90.
- Searching while a sync runs answers at once instead of waiting up to six
  seconds for the sync to finish. The helper serves each request on its own
  thread and runs Bitwarden CLI commands one at a time.
- A manual sync takes 3.5 seconds, down from 6.2; a status check 1.0, down
  from 3.0; locking 1.2, down from 2.9. The CLI keeps running for one to two
  seconds after it has answered, so the helper takes each answer as soon as
  it is complete and lets the process exit in the background. The CLI also
  gets a private Node compile cache.
- Lock wipes the session, index and clipboard at once, even while a sync is
  running, and a sync that finishes after a lock is discarded.
- `bw login` prints a session key when it succeeds. The sign-in terminal now
  locks the CLI right after, so that key no longer works, and clears the
  screen and scrollback.
- A helper that is shutting down still answers requests it has already
  accepted, and clients keep retrying to start a fresh helper, so an update
  no longer strands a request.

## 1.1.8 - 2026-10-21

- Self-hosted servers behind mutual TLS work with a client certificate.
  `tools/client-certificate.cjs` lets the Node.js Bitwarden CLI present one,
  and [docs/CLIENT-CERTIFICATES.md](docs/CLIENT-CERTIFICATES.md) covers the
  setup, including a local proxy for the standalone `bw` binary (#1).
- Background status checks keep the 1.1.7 profile cache when the CLI command
  is `env NAME=value … bw`, as the client-certificate setup uses.

## 1.1.7 - 2026-10-07

- Avoid starting the Bitwarden CLI every background poll while its standard
  profile is unchanged. Detect profile edits and replacements using file
  metadata, keep manual refresh immediate, and recheck at least every five
  minutes. Locking and vault capabilities are unchanged.

## 1.1.6 - 2026-09-15

- The README now shows a card search, the native unlock prompt and, in the
  demo GIF, a copy with its countdown. It documents command-mode keys and
  the `screenLockState` IPC call, and explains screen-lock protection under
  Security. Runtime behavior is unchanged from 1.1.5.
- `tools/demo` can capture the card and native prompt shots, and press Enter
  in a disposable VM to record a copy.

## 1.1.5 - 2026-09-15

- The bar icon and panel badges now show a closed padlock while the vault
  is locked and an open one while it is unlocked; the two were swapped. The
  open padlock swings its shackle wide so it stays distinct at bar size, and
  the Unlock vault button uses it too.
- Copy card number shows a card instead of an empty circle, and a search
  with no matches shows a crossed-out magnifier instead of an envelope.
- Screenshots, the demo GIF and the preview images are retaken on a stock
  Omarchy 4.0.3 desktop.

## 1.1.4 - 2026-09-09

- Make the new QML screen-lock test satisfy the repository’s executable-file, import-order, and subprocess lint rules. Runtime behavior is unchanged from 1.1.3.

## 1.1.3 - 2026-09-09

- Restore screen-lock protection on Omarchy 4.0.3 using a bounded, read-only compositor probe. Fail closed on unknown state and preserve lock events across in-flight native/Pinentry unlocks.
- Add deterministic transition tests and isolated Quickshell integration tests with a fake vault.

## 1.1.2 - 2026-08-31

- Render vault names, usernames, domains, and CLI-derived messages as literal
  plain text so markup-shaped shared-vault data cannot be interpreted by the
  shell, including helper errors routed through the shared Omarchy 4.0.1 bar
  tooltip.
- Make slow-process and concurrent-client regression tests deterministic on
  the single-vCPU Omarchy compatibility VM.

## 1.1.1 - 2026-08-31

- Bound and concurrently drain the secret-bearing `bw list items --raw`
  streams, terminating the full CLI process group on timeout or overflow.
- Discard captured vault bytes before reporting a generic failure so oversized
  output cannot exhaust the long-lived agent or leak through an error.
- Check every CI run against the current Omarchy Quattro manifest validator.

## 1.1.0 - 2026-08-25

- Credit cards now appear beside logins and can be searched by name, brand,
  cardholder or last four digits.
- Card number, cardholder, security code and expiry can be copied with the
  same sensitive, self-clearing clipboard used for login secrets.
- Full card numbers and security codes remain outside QML and the long-lived
  agent; only safe recognition metadata reaches the panel.
- Keyboard-opened panels now start in an unambiguous command mode. `/` or
  `Ctrl+F` enters search mode, where letters cannot trigger panel shortcuts;
  `Esc` walks back through query → command mode → close.

## 1.0.1 - 2026-08-21

- Opening an unlocked panel goes straight to its local index instead of
  waiting behind the Bitwarden CLI status check.
- Unlock and sync prepare the memory-only search index in the background, so
  the first panel search no longer pays the CLI's cold-start cost.
- Unlocked status polls reuse the agent's authoritative state until a real
  lock or configuration change, eliminating periodic multi-second stalls.
- Unlock and sync clients now cover the full bounded index-warmup window on
  large or slow vaults.

## 1.0.0 - 2026-08-20

First public release.

- Ranked, instant search over an in-memory index of login names, usernames
  and sites; recently used logins first.
- Password, username, one-time code and website actions on every row, with
  KeePassXC-style shortcuts that work while typing.
- Copies go straight from the Bitwarden CLI to a sensitive clipboard that
  clears after a timeout, on the next copy, and on lock — never into
  Omarchy's clipboard history.
- Pinentry unlock by default; an Omarchy-themed native prompt as an option.
- Locks with the screen and after inactivity; sync after unlock.
- Guided setup: install the missing packages, sign in, unlock.
- Self-hosted and EU servers, separate CLI profiles, custom CLI commands.
- Settings page built from Omarchy's components; every setting also works
  with `omarchy bar set`.
- IPC for keybindings: `toggle`, `search <query>`, `lock`, `sync` and more.
