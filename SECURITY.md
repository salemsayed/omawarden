# Security policy

OmaWarden handles access to a decrypted Bitwarden vault. Security regressions
take priority over features and visual polish.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, session key, or
vault data. Use GitHub's private vulnerability reporting for this repository.
Include the affected version, reproduction steps, observed impact, and any
suggested mitigation. Remove real credentials from logs and screenshots.

## Threat model

OmaWarden protects secrets from accidental persistence and exposure through
the Omarchy shell UI, shell configuration, process arguments, logs, and normal
clipboard history.

The following are trusted:

- the local user account and Linux kernel;
- Omarchy, Quickshell, Pinentry, `bw`, and `wl-copy` binaries;
- the active Wayland compositor;
- this plugin's installed source.

The following are outside the security boundary:

- malware running as the same user;
- debuggers or memory readers with permission to inspect the shell, the
  helper, or `bw`;
- a compromised clipboard consumer, compositor, Pinentry, or Bitwarden CLI;
- physical observation of usernames or item names when display privacy is on.

## Secret flow

### Unlock

Two prompts are offered. Both end the same way: the password is written to a
mode-`0600` FIFO consumed by `bw unlock --passwordfile`, the FIFO is deleted,
mutable Python password buffers are overwritten, and the returned session key
stays in the helper's memory, supplied to child `bw` processes through their
environment and never their arguments.

**Pinentry** (default, stricter). The helper runs a separate Pinentry process
and reads the password over its Assuan pipe. The master password never exists
inside the Omarchy shell process.

**Native** (optional). The shell draws an Omarchy-themed prompt on an overlay
layer with exclusive keyboard focus, the same arrangement the lock screen and
polkit dialog use. The password exists in the shell only in that field and
the buffer handed to the helper: it is written to the helper's stdin (never
argv, never the environment), relayed to the agent over the private socket as
raw bytes behind a JSON header, and cleared from each application-level holder
as soon as it moves on. The field is cleared on submit, dismiss, and whenever
the session lock engages; Python's mutable copies are overwritten. QML strings
are managed by the JavaScript runtime, so
clearing their references cannot promise a physical memory overwrite. A
bounded maximum length rejects oversized input before it is read. Choosing
this prompt means trusting the shell process with the password for the
duration of one unlock. It must be selected explicitly in Settings.

### Search

The Bitwarden CLI necessarily decrypts full item objects. The agent immediately
projects them to an allowlist containing only item ID, name, optional
username, first safe web URL, favorite state, item type, and password/TOTP
capability flags, and drops everything that is not a login item. Full objects
and captured CLI output are discarded after projection. The allowlisted
metadata is indexed in memory while the vault is unlocked so later searches do
not decrypt the vault again; ranking works on that metadata only. The index is
never written to disk and is wiped on lock, sign-out, profile change, privacy
change, or agent exit.

### Recently used

The helper remembers the opaque item IDs of the last five entries copied or
opened so the panel can list them first. IDs alone reveal nothing about the
vault and are never written to disk. They survive a lock (so the list is
useful after a relock) and are forgotten on sign-out, CLI or profile change,
and helper exit.

### Screen lock

When enabled, the QML service observes Omarchy's native `omarchy.lock` service.
As soon as the compositor session lock is requested, it queues the same agent
lock action as the panel button. Busy copy or sync actions cannot drop the
event: the service retries until the session key and metadata index are wiped.
An open native unlock prompt is dismissed and cleared at the same moment.

### Copy

The agent connects `bw get <field>` stdout directly to `wl-copy` stdin. Neither
Python nor QML captures the copied value. `--sensitive` prevents Omarchy's
clipboard history from recording it, and the foreground clipboard owner is
terminated at the configured deadline, on lock, and on sign-out. `--paste-once`
is deliberately not used: Omarchy's history watcher requests every new
selection to inspect its sensitivity marker, which would consume the user's
only paste before it reaches the target application. Copy fields and item IDs
must match a capability in the current projected login index. A timed-out or
failed pipeline is terminated and reaped as a process group. The panel's
countdown is cosmetic; the agent owns the clipboard lifetime.

### Local protocol

The Unix socket and advisory lock live only in a real, user-owned runtime
directory with no group or world permissions. The lock cannot be a symlink;
the socket is mode `0600`; every Linux peer UID is checked. Requests, responses
and native-password frames have independent size limits and a protocol version.
An incomplete client is disconnected after three seconds so it cannot stall
auto-lock or daemon shutdown. Concurrent clients race safely behind the
advisory lock, leaving one agent per user.

### Sign-in, sign-out, server

`bw login` runs in a terminal window so credentials and two-step codes are
typed into the CLI's own prompt. A configured server URL is applied with
`bw config server` before login and only while signed out. Sign-out runs
`bw logout`, stops any live clipboard, and wipes the session, index, and
recents.

## Intentional limitations

- No password reveal UI.
- No create, edit, delete, attachment, card, identity, or secure-note actions.
- No REST server (`bw serve`).
- No session keys in files, shell configuration, IPC responses, or argv.
- No copy action over IPC: secrets are only ever copied from the panel.
- Only credential-free `http` and `https` URLs from projected login items can
  be launched.
