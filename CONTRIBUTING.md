# Contributing

Issues and pull requests are welcome. Changes that touch authentication,
sessions, the clipboard, command execution, profile permissions or vault
projection need tests and a note on their security impact.

## Checks

```bash
tests/run
shellcheck tests/run
omarchy plugin validate .
```

CI also runs the pinned Python tools:

```bash
python3 -m pip install -r requirements-dev.txt
ruff check omawarden-agent.py tests
mypy --python-version 3.11 --check-untyped-defs omawarden-agent.py tests/Agent.test.py tests/Manifest.test.py
bandit --quiet --recursive omawarden-agent.py --skip B404,B603
```

Before submitting a UI change, load the plugin on Omarchy 4, go through
every vault state and the settings page, and check the shell log for QML
errors (`/run/user/$UID/quickshell/by-pid/<pid>/log.log`).
`omarchy restart shell` picks up `Panel.qml` changes reliably. Drive the
panel over IPC (`omarchy-shell io.github.salemsayed.omawarden open|settings|search …`),
not with synthetic keystrokes.

Never put real vault names, usernames, URLs, credentials or session keys in
fixtures, screenshots, issues or commits. Capture screenshots with
`tools/demo`.

User-facing text should read like something a person would say: no "agent",
"session key", "argv" or "FIFO" in the panel. Put new copy in `Model.js` so
the tests can see it.

## Compatibility

No runtime dependencies beyond standard Python and the packages in the
README. No distro-specific paths, no shell evaluation, no APIs outside
Omarchy's plugin contract. Everything must work with mouse and keyboard and
show a clear state when a requirement is missing.

## Releasing

1. Update `manifest.json` and `CHANGELOG.md` together.
2. Run the full test suite on a current Omarchy.
3. Test a plain `bw`, a full path, and a command with arguments.
4. Test signed-out, locked, unlocked, failed login, offline sync, empty
   search, missing TOTP and timed-out copy.
5. Confirm copied values never appear in Omarchy's clipboard history,
   process arguments or the journal.
6. Run `python3 tests/benchmark.py` and look for regressions.
7. Refresh `preview.png` and `docs/images/` with `tools/demo` if the panel
   changed.
8. Commit as `Release OmaWarden X.Y.Z`, tag `vX.Y.Z`, and publish a GitHub
   release with the CHANGELOG section as its notes.
