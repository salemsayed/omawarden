# Contributing

Issues and pull requests are welcome. Changes involving authentication,
session handling, clipboard behavior, command execution, profile permissions,
or vault projection must include tests and an explanation of their security
impact.

## Local checks

```bash
tests/run
shellcheck tests/run
omarchy plugin validate .
```

CI also runs pinned Python quality tools. To reproduce those checks locally:

```bash
python3 -m pip install --requirement requirements-dev.txt
ruff check omawarden-agent.py tests
mypy --python-version 3.11 --check-untyped-defs omawarden-agent.py tests/Agent.test.py tests/Manifest.test.py
bandit --quiet --recursive omawarden-agent.py --skip B404,B603
```

Before submitting a UI change, load the plugin on Omarchy 4, exercise every
vault state, open the settings page, and inspect the shell log for QML errors
(`/run/user/$UID/quickshell/by-pid/<pid>/log.log`). `omarchy restart shell` is
the reliable way to pick up `Panel.qml` changes. Drive the panel over IPC
(`omarchy-shell io.github.salemsayed.omawarden open|settings|search …`)
rather than with synthetic keystrokes, which can land in other windows.

Do not include real vault names, usernames, URLs, credentials, or session keys
in test fixtures, screenshots, issues, or commits. For screenshots, point
`cliCommand` at a small fake `bw` that prints `example.com` logins, and restore
the setting afterwards.

User-facing text should read as a sentence a person would say: no "agent",
"session key", "argv", or "FIFO" in the panel. Put new copy in `Model.js`
where the Node tests can see it.

## Compatibility

Keep the runtime dependency-free beyond standard Python and the packages
listed in the README. Avoid distro-specific paths, shell evaluation, and APIs
outside Omarchy's documented plugin contract. User-facing changes must remain
usable with mouse and keyboard and must have a clear missing-dependency state.

## Release checklist

1. Update `manifest.json` and `CHANGELOG.md` together.
2. Run the complete test suite on a current Omarchy installation.
3. Test native, custom-path, and argument-bearing Bitwarden CLI commands.
4. Test signed-out, locked, unlocked, failed-login, offline-sync, empty-search,
   missing-TOTP, malformed-URL, timed-out-copy, and partial-IPC cases.
5. Confirm copied values are absent from Omarchy clipboard history.
6. Confirm no credential or session value appears in process arguments or
   journal output.
7. Run `python3 tests/benchmark.py` and investigate meaningful regressions in
   index memory, build time, warm search, or recent browsing.
8. Refresh `preview.png` and `docs/images/` when the panel changed. Capture
   against a fake `bw` with fictional logins, drive the panel over IPC, and
   crop to the panel border — never screenshot a real vault.
9. Commit as `Release OmaWarden X.Y.Z`, tag `vX.Y.Z`, and publish a GitHub
   release whose notes are the matching `CHANGELOG.md` section.
