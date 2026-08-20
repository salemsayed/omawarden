# Changelog

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
