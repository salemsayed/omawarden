# Demo vault

The screenshots and GIF are captured against the fake Bitwarden CLI in this
folder, with fictional logins.

- `bw` — fake CLI with a JSON state file. Reads only the first line of
  `--passwordfile`, like the real one.
- `pinentry` — fake Assuan pinentry that answers after a pause.
- `capture.sh setup|shots|gif|restore` — points the widget at the fakes,
  drives the panel over IPC, captures with `grim`, restores the real `bw`.
- `finish.py <out> <final>` — trims the shots, encodes the GIF, composes the
  preview card and strips.

`setup` ends the current vault session; `restore` resets `cliCommand` and
`pinentryCommand` to their defaults.
