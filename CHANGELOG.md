# Changelog

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
