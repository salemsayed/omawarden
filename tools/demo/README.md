# Demo vault and media capture

Everything in `docs/images/` and `preview.png` is captured against the
stand-in CLI in this folder, never a real vault.

- `bw` — a fake Bitwarden CLI with fictional logins and a JSON state file.
  Like the real CLI it reads only the first line of `--passwordfile`; a reader
  that waits for EOF would hang on the helper's FIFO.
- `pinentry` — a fake Assuan pinentry that answers `GETPIN` after a pause.
- `capture.sh setup|shots|gif|restore` — points the widget at the fakes,
  drives the panel over IPC (no synthetic input), screenshots with `grim`,
  records GIF frames, and puts the real `bw` back.
- `finish.py <out> <final>` — trims shots to the panel border, encodes the
  GIF with ImageMagick, and composes the bar strip, onboarding strip and
  marketplace card.

`setup` drops the real vault session (the helper holds one session per CLI
command); `restore` resets `cliCommand` and `pinentryCommand` to the
defaults, so re-apply any custom values afterwards.
