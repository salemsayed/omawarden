# OmaWarden

**Bitwarden in the Omarchy bar.** Type a few letters, press Enter, and the
password is on a sensitive clipboard for thirty seconds, kept out of Omarchy's
clipboard history. Vault secrets never reach the shell UI.

## Demo

![OmaWarden demo: the locked gate, an unlock through the Pinentry prompt, the vault list with favourites first, a ranked search narrowing as the query grows, and the settings page](docs/images/demo.gif)

Recorded on a live Omarchy desktop and driven entirely over the shell's IPC.
The vault is a stand-in Bitwarden CLI with fictional logins — a password
manager demo should never show a real one.

## Screenshots

![The OmaWarden panel browsing an unlocked vault: favourites first, then every login, each row with password, username, one-time code and website actions](docs/images/panel-vault.png)

![Searching for "git": GitHub, Gitea and DigitalOcean ranked by how well the name matches, with a "3 matches" pill in the header](docs/images/panel-search.png)

![The settings page: locking and unlock, clipboard and search, account and advanced sections with native Omarchy switches and steppers](docs/images/panel-settings.png)

The three states before a vault is open — missing packages, signed out, and
locked — each get one sentence and one button, with a strip showing how far
along you are:

![The onboarding states side by side: Set up OmaWarden with the requirement list, Sign in to Bitwarden, and Vault locked](docs/images/onboarding.png)

The bar icon is a padlock that follows the theme's accent while the vault is
open and turns to the urgent colour when something needs you:

![The bar icon in its locked, unlocked and needs-attention states](docs/images/bar-states.png)

## Why you'd want it

- **Fast.** The first search after unlock builds a memory-only index of login
  names, usernames and sites; every search after that is local and instant.
  Results are ranked, so `git` puts *GitHub* ahead of *DigitalOcean*, and the
  panel opens on the logins you used most recently.
- **Safe by construction.** The shell only ever sees names, usernames, sites
  and capability flags. Passwords, one-time codes and the unlocked session key
  live in a small per-user helper and travel from the Bitwarden CLI straight
  to a sensitive, automatically expiring Wayland clipboard.
- **Keyboard first.** `Enter` copies the password, `Shift+Enter` the
  username, `Ctrl+T` the one-time code, `Ctrl+U` opens the site — all while
  you're still typing in the search box.
- **At home in Omarchy.** Built on the shell's own component kit, so it
  follows your theme, corner radius, font and spacing, and locks with your
  screen.

## Requirements

- Omarchy 4.0 or newer
- Python 3.11 or newer (already part of Omarchy)
- `bitwarden-cli` (the `bw` command) and `wl-clipboard`
- `pinentry` — used by the safer default unlock prompt (see below)

The panel offers to install anything that's missing.

## Install

```bash
omarchy plugin add https://github.com/salemsayed/omawarden.git --enable
```

The manifest places the widget in the right section of the bar; move it with
`omarchy bar move io.github.salemsayed.omawarden --section right --index 0`
if you want it elsewhere.

A padlock appears in the bar. Click it and follow the three steps the panel
walks you through:

1. **Install** — if `bw` or `wl-clipboard` is missing, one click installs them
   in a terminal window through `omarchy pkg add`.
2. **Sign in** — a terminal window runs `bw login`. Your email, master
   password and two-step code go straight into Bitwarden's own prompt. If you
   set a server URL in Settings first, it's applied automatically.
3. **Unlock** — enter your master password in the unlock prompt. That's it.

To work from a local checkout instead:

```bash
omarchy plugin validate ~/Coding/omawarden
omarchy plugin add file://$HOME/Coding/omawarden --enable
```

`omarchy plugin add` clones the source, so a local path must be a Git
repository.

## Everyday use

Open the panel (click the bar icon), start typing, press Enter.

Each login row has quick actions for password, username, one-time code, and
website. Actions missing from that login appear faintly on the selected row;
for example, the one-time-code button becomes clickable when the login has an
authenticator key saved in Bitwarden.

| Key | Action |
| --- | --- |
| `↑` `↓` | Move between results |
| `Enter` | Copy the default field (password, configurable) |
| `Shift+Enter` | Copy the other one (username) |
| `Ctrl+C` | Copy password |
| `Ctrl+B` | Copy username |
| `Ctrl+T` | Copy the current one-time code |
| `Ctrl+U` | Open the website |
| `Alt+←` `Alt+→` | Pick a different action for the highlighted row |
| `Ctrl+R` | Sync with the server |
| `Ctrl+L` | Lock the vault |
| `Ctrl+D` | Open the Bitwarden desktop app |
| `Ctrl+,` | Settings |
| `Esc` | Clear the search, then close |

The copy shortcuts follow KeePassXC's, so they're already in many people's
fingers. While the vault is locked or you're signed out, `Enter` (or `u`)
does the one obvious thing, `r` refreshes, `s` opens settings and `d` opens
the Bitwarden desktop app.

Every copy shows a countdown: the sensitive clipboard vanishes after 30
seconds by default, or immediately when you lock. Nothing copied through
OmaWarden appears in Omarchy's clipboard history.

**Bar icon:** left-click opens the panel, right-click opens settings,
middle-click syncs (or refreshes the status while locked).

## Settings

Everything lives on the panel's settings page (the gear, `Ctrl+,`, or `s`
while the vault is locked):

- **Locking & unlock** — lock after inactivity (with the delay), lock when
  the screen locks, and which unlock prompt to use.
- **Clipboard & search** — clipboard timeout, what Enter copies, whether
  usernames are shown, how many results to list, sync after unlock.
- **Account** — where you're signed in, a two-tap sign-out, the server URL
  and an optional separate CLI profile folder.
- **Advanced** — the Bitwarden CLI command and how often the bar re-reads the
  vault state, plus a requirements check.

Settings are stored in Omarchy's `shell.json`, so the same keys work from the
command line:

```bash
omarchy bar set io.github.salemsayed.omawarden autoLockMinutes 10 --json
omarchy bar set io.github.salemsayed.omawarden lockOnScreenLock true --json
omarchy bar set io.github.salemsayed.omawarden showUsernames false --json
omarchy bar set io.github.salemsayed.omawarden defaultCopy Username
```

| Key | Default | Meaning |
| --- | --- | --- |
| `inactivityLockEnabled` | `true` | Relock the vault when it goes unused |
| `autoLockMinutes` | `15` | Inactivity delay, 5–240 minutes |
| `lockOnScreenLock` | `true` | Relock the moment Omarchy's lock screen engages |
| `unlockPrompt` | `Pinentry` | `Pinentry` or `Native` (see below) |
| `pinentryCommand` | `auto` | Pinentry program to use; `auto` picks one |
| `clipboardTimeoutSec` | `30` | Sensitive clipboard lifetime, 5–120 seconds |
| `defaultCopy` | `Password` | What Enter copies; Shift+Enter copies the other |
| `showUsernames` | `true` | Show usernames under login names |
| `resultLimit` | `20` | Rows listed at once, 5–50 |
| `syncOnUnlock` | `true` | Pull changes from the server after each unlock |
| `serverUrl` | *(empty)* | Self-hosted or EU server, applied at sign-in |
| `appDataDir` | *(empty)* | Separate CLI profile folder for a second account |
| `cliCommand` | `bw` | Bitwarden CLI command, arguments allowed |
| `refreshIntervalSec` | `30` | How often the bar re-reads the local vault state |

### Unlock prompts

- **Pinentry** (default, recommended) — the GnuPG-style prompt runs as a
  separate process, so the master password never exists inside the shell at
  all. `auto` picks the first of `pinentry-gnome3`, `pinentry-qt`,
  `pinentry` and `pinentry-curses` that is installed; name a specific
  `pinentry-*` program to override it.
- **Native** — a themed Omarchy prompt drawn by the shell itself, like the
  lock screen and the polkit dialog. The password is handed to OmaWarden's
  helper over a private pipe and cleared as soon as Bitwarden has it. Choose
  this only when tighter visual integration matters more than process
  isolation.

### Self-hosted, EU and multiple accounts

Set **Server URL** in Settings *before* you sign in — it's applied to the CLI
automatically as part of sign-in. To switch servers later, sign out from the
Account section and sign in again.

To keep a second account completely separate, give it its own **CLI profile
folder**; OmaWarden creates it with private permissions and refuses to use a
folder other users can read.

### Unusual CLI installs

The default command is `bw`. Full paths and commands with arguments work and
never go through a shell, so a Flatpak CLI can be:

```text
flatpak run --command=bw com.bitwarden.desktop
```

## Bind it to a key

Every panel action is reachable over the shell's IPC, which makes a global
shortcut a one-liner in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + SHIFT + B", "Bitwarden", "omarchy-shell shell toggle io.github.salemsayed.omawarden")
```

Other methods:

```bash
omarchy-shell io.github.salemsayed.omawarden open        # also: close, toggle
omarchy-shell io.github.salemsayed.omawarden search git  # open with a query filled in
omarchy-shell io.github.salemsayed.omawarden settings
omarchy-shell io.github.salemsayed.omawarden unlock      # prompts, as the panel button would
omarchy-shell io.github.salemsayed.omawarden lock
omarchy-shell io.github.salemsayed.omawarden sync
omarchy-shell io.github.salemsayed.omawarden refresh
omarchy-shell io.github.salemsayed.omawarden status
```

There is deliberately no `copy` over IPC: secrets are only ever copied from
the panel.

## How it keeps secrets safe

- The QML panel receives names, optional usernames, safe web URLs and
  capability flags — never passwords, one-time-code seeds, notes or custom
  fields. Cards, identities and notes aren't listed at all.
- The unlocked session key lives only in the helper's memory and is passed to
  child `bw` processes through their environment, never their arguments.
- The helper listens in a private runtime directory on a user-only (`0600`)
  Unix socket, checks the peer's UID, bounds every frame, and drops clients
  that do not finish a request.
- Copies pipe `bw get` straight into `wl-copy --sensitive`; Omarchy's history
  watcher ignores the selection, while the previous owner and its whole
  process group are retired before a new copy, at the configured deadline,
  and on lock.
- Copy and open requests are checked against the current projected login
  index. Only credential-free `http` and `https` sites can be opened;
  configurable commands are parsed as argument arrays, never by a shell.
- The metadata index is memory-only and wiped on lock, sign-out, profile
  change or helper exit.

[SECURITY.md](SECURITY.md) has the full threat model, both unlock flows in
detail, and how to report a vulnerability. Like any desktop password-manager
integration, OmaWarden can't protect you from malware already running as your
user, a compromised Bitwarden CLI, or a compromised compositor.

## Troubleshooting

- **"Setup required" with everything installed** — the CLI might live
  somewhere unusual. Set the full path under Settings → Advanced →
  *Bitwarden CLI command*.
- **Sign-in terminal says you're already signed in** — good; close it and
  choose *Unlock vault*.
- **A copied password won't paste twice** — by design. Copy it again.
- **Nothing happens after unlock** — give the first search a moment; it
  builds the index from the vault once. Large vaults take a second or two.
- **Helper won't start** — `python3 omawarden-agent.py request` prints the
  error; `XDG_RUNTIME_DIR` must be a user-owned directory.

## Remove

```bash
omarchy plugin disable io.github.salemsayed.omawarden
omarchy plugin remove io.github.salemsayed.omawarden
```

OmaWarden keeps nothing on disk: no cache, no state directory, no session.
Removing it does not sign you out of the Bitwarden CLI; run `bw logout` for
that.

## Development

```bash
tests/run                      # Python agent tests + Node model tests + manifest check
python3 tests/benchmark.py     # reproducible 10k-login index/search benchmark
omarchy plugin validate .      # manifest validation against the running shell
```

Plugin code under `~/.config/omarchy/plugins/` hot-reloads on save; after
changing `Panel.qml` a `omarchy restart shell` is the reliable way to see it.
Never edit the packaged source under `/usr/share/omarchy`. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE)
