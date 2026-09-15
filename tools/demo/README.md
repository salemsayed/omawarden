# Demo vault

The screenshots and GIF are captured against the fake Bitwarden CLI in this
folder, with fictional logins and a card.

- `bw` — fake CLI with a JSON state file. Reads only the first line of
  `--passwordfile`, like the real one.
- `pinentry` — fake Assuan pinentry that answers after a pause.
- `capture.sh setup|shots|prompt|gif|restore` — points the widget at the
  fakes, drives the panel over IPC, captures with `grim`, restores the real
  `bw`.
- `finish.py <out> <final>` — trims the shots and the native prompt, encodes
  the GIF, composes the preview card and strips.
- `social.py` — composes `docs/images/announcement.png` from the final shots.

`setup` ends the current vault session; `restore` resets `cliCommand` and
`pinentryCommand` to their defaults. `prompt` leaves the native unlock prompt
open; press Esc to close it. `DEMO_KEYS=1 capture.sh gif` presses Enter with
`wtype` to show a copy and its countdown — only in a VM, since the key goes
to whatever has focus.

Capture on a stock Omarchy desktop at 1920x1080, such as a disposable QEMU
guest, so the media show the default theme rather than a customised one.
`finish.py` finds the panel by the default theme's accent border; set
`PANEL_BORDER` to another theme's accent colour (for example `1e66f5`) to
use a different one.
