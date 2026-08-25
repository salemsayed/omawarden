# Security policy

OmaWarden handles access to a decrypted Bitwarden vault. Security fixes take
priority over features and polish.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not
open a public issue containing an exploit, credential, session key or vault
data. Include the version, steps to reproduce, observed impact and, if you
have one, a suggested fix.

## Threat model

OmaWarden keeps secrets out of the Omarchy shell UI, shell configuration,
process arguments, logs and clipboard history.

Trusted: the local user account and kernel; Omarchy, Quickshell, Pinentry,
`bw` and `wl-copy`; the Wayland compositor; the plugin's installed source.

Out of scope: malware running as the same user; debuggers or memory readers
with access to the shell, the helper or `bw`; a compromised clipboard
consumer, compositor, Pinentry or Bitwarden CLI; someone reading usernames
or item names off your screen.

## How secrets move

### Unlock

Both prompts end the same way: the password is written to a mode-`0600`
FIFO that `bw unlock --passwordfile` reads, the FIFO is deleted, the Python
buffers are overwritten, and the session key stays in the helper's memory —
passed to child `bw` processes through their environment, never their
arguments.

**Pinentry** (default). The helper runs a separate Pinentry process and reads
the password over its Assuan pipe. The master password never exists inside
the shell process.

**Native** (optional, selected explicitly in Settings). The shell draws a
themed prompt on an overlay with exclusive keyboard focus, as the lock screen
does. The password is written to the helper's stdin (never argv or the
environment), relayed to the agent over the private socket, and cleared from
each holder as soon as it moves on. The field is cleared on submit, dismiss
and session lock. QML strings are garbage-collected, so clearing them cannot
promise a physical overwrite — that is the trade-off this prompt makes.

### Search

The Bitwarden CLI decrypts full items. The helper immediately keeps only login
and card entries and reduces them to allowlisted metadata. For logins that is
the item ID, name, optional username, first safe web URL, favourite flag, type
and password/TOTP capability flags. For cards it is the item ID, name,
optional cardholder, brand, last four digits, favourite flag, type and field
capability flags. Full card numbers, security codes and expiration dates are
not indexed or returned to QML. Unlock and sync prepare that index before
their background work reports ready; when sync is disabled, preparation
starts only after the unlock password and its FIFO have been cleared. The
metadata stays in memory for the life of the session and is wiped on lock,
sign-out, profile change, privacy change and exit. It is never written to
disk.

### Recently used

The helper remembers the IDs of the last five entries copied or opened, in
memory only. They survive a lock and are forgotten on sign-out, CLI or
profile change, and exit.

While the agent owns an unlocked session, routine status polls reuse its
metadata-only status response instead of repeatedly launching the Bitwarden
CLI. Lock, sign-out, profile changes, failed status checks and inactivity
locking clear that response together with the session capability, so this
cache cannot keep an otherwise closed vault accessible.

### Screen lock

When enabled, the service watches Omarchy's `omarchy.lock` service and
queues the same lock action as the panel button the moment the session locks.
A busy copy or sync cannot drop the event; the service retries until the
session key and index are gone. An open native prompt is dismissed at the
same time.

### Copy

For login fields, `bw get <field>` is piped straight into
`wl-copy --sensitive`; neither Python nor QML sees the value. The CLI has no
equivalent card-field command, so `bw get item` is piped through a short-lived
filter process that emits only the requested card value into `wl-copy`. The
full card object never enters QML, IPC responses or the long-lived agent and
the filter exits immediately after the copy pipe is filled. The clipboard
owner is terminated at the configured deadline, on the next copy, on lock and
on sign-out. `--paste-once` is not used because Omarchy's clipboard-history
watcher would consume the single paste while checking the sensitivity flag.
Copy requests must match a capability in the current index. The panel's
countdown is cosmetic; the helper owns the clipboard lifetime.

### Local protocol

The Unix socket and lock file live in a user-owned runtime directory with no
group or world permissions. The socket is mode `0600`, the lock cannot be a
symlink, and every peer's UID is checked. Requests, responses and password
frames have size limits and a protocol version; an incomplete client is
dropped after three seconds. An advisory lock keeps it to one helper per
user.

### Sign-in, sign-out, server

`bw login` runs in a terminal so credentials and two-step codes go to the
CLI's own prompt. A configured server URL is applied with `bw config server`
before login, only while signed out. Sign-out runs `bw logout`, clears the
clipboard and wipes the session, index and recents.

## Deliberate limitations

- No password reveal.
- No create, edit, delete, attachments, identities or notes.
- No `bw serve`.
- No session keys in files, configuration, IPC responses or arguments.
- No copy over IPC; secrets are copied from the panel only.
- Only credential-free `http` and `https` URLs from your own vault entries
  can be opened.
