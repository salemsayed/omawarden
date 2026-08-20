#!/bin/bash
# Drive the OmaWarden panel over IPC against the fake bw and capture
# screenshots + a demo GIF. Never injects keyboard or mouse input.
#
#   capture.sh setup      switch the widget to the fake CLI (drops the real session!)
#   capture.sh shots      take the state screenshots into $OUT
#   capture.sh gif        record the demo GIF into $OUT
#   capture.sh restore    put the widget back on the real bw

set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ID=io.github.salemsayed.omawarden
OUT=${OUT:-$HERE/out}
STATE=$HERE/state.json
export FAKE_BW_STATE=$STATE

# Panel geometry on the 1920x1080 display (filled in after a probe capture).
PANEL_GEOM=${PANEL_GEOM:-"1355,31 520x780"}
GIF_GEOM=${GIF_GEOM:-"1355,31 520x700"}
BAR_GEOM=${BAR_GEOM:-"1600,0 32x31"}
MON=HDMI-A-1

ipc() { omarchy-shell "$ID" "$@"; }
shot() { # shot <name> [geometry]
  local geom=${2:-$PANEL_GEOM}
  grim -g "$geom" "$OUT/$1.png"
  echo "shot $1"
}
state() { printf '{"status":"%s"}' "$1" > "$STATE"; }

setup() {
  mkdir -p "$OUT"
  chmod +x "$HERE/bw" "$HERE/pinentry"
  state locked
  omarchy bar set "$ID" cliCommand "$HERE/bw"
  omarchy bar set "$ID" pinentryCommand "$HERE/pinentry"
  sleep 1
  ipc refresh; sleep 1.5
  ipc status
}

restore() {
  omarchy bar set "$ID" cliCommand bw
  omarchy bar set "$ID" pinentryCommand auto
  # Stop the demo helper so no fake session outlives the shoot.
  printf '{"action":"shutdown"}\n' | python3 "$HERE/../../omawarden-agent.py" request >/dev/null 2>&1 || true
  sleep 1
  ipc refresh; sleep 1.5
  ipc status
}

wait_status() { # wait_status <substring> [seconds]
  local want=$1 limit=${2:-10} i
  for ((i = 0; i < limit * 4; i++)); do
    if ipc status 2>/dev/null | grep -qi "$want"; then return 0; fi
    (( i % 8 == 7 )) && ipc refresh >/dev/null 2>&1 || true
    sleep 0.25
  done
  echo "timed out waiting for status '$want' (got: $(ipc status))" >&2
  return 1
}

shots() {
  mkdir -p "$OUT"
  # 1. Locked gate (default state after setup)
  ipc close; sleep 0.4
  state locked; ipc lock >/dev/null; sleep 1.0; ipc refresh; wait_status "locked"
  sleep 4  # let the "Vault locked" action message age out
  shot bar-locked "$BAR_GEOM"
  ipc open; sleep 1.0; shot panel-locked
  ipc close; sleep 0.5

  # 2. Unlock and browse
  ipc unlock; wait_status "unlocked" 15; sleep 5  # let "Vault synced" age out
  shot bar-unlocked "$BAR_GEOM"
  ipc open; sleep 2.2; shot panel-vault
  ipc close; sleep 0.5

  # 3. Ranked search
  ipc search "git"; sleep 1.6; shot panel-search
  ipc close; sleep 0.5

  # 4. Settings (show the defaults rather than the demo helper paths)
  omarchy bar set "$ID" pinentryCommand auto >/dev/null
  omarchy bar set "$ID" inactivityLockEnabled true --json >/dev/null
  omarchy bar set "$ID" autoLockMinutes 15 --json >/dev/null
  sleep 0.8
  ipc settings; sleep 1.2; shot panel-settings
  ipc close; sleep 0.5
  omarchy bar set "$ID" pinentryCommand "$HERE/pinentry" >/dev/null
  sleep 0.6

  # 5. Sign-in gate
  state unauthenticated; ipc lock >/dev/null; sleep 1.0; ipc refresh; wait_status "sign in"
  sleep 4  # let the "Vault locked" action message age out
  shot bar-signin "$BAR_GEOM"
  ipc open; sleep 1.0; shot panel-signin
  ipc close; sleep 0.5

  # 6. Setup gate (CLI missing)
  omarchy bar set "$ID" cliCommand "$HERE/no-such-bw"; sleep 0.6
  ipc refresh; wait_status "setup\|install\|unavailable" 8 || true
  ipc open; sleep 1.0; shot panel-setup
  ipc close; sleep 0.5
  omarchy bar set "$ID" cliCommand "$HERE/bw"; sleep 0.6
  state locked; ipc refresh; wait_status "locked"
}

# Frame recorder: grim as fast as it goes into $1 until $1/stop exists.
record() {
  local dir=$1 n=0
  rm -rf "$dir"; mkdir -p "$dir"
  : > "$dir/times.txt"
  while [[ ! -e $dir/stop ]]; do
    local name
    name=$(printf 'f%05d.png' "$n")
    grim -g "$GIF_GEOM" "$dir/$name" 2>/dev/null || true
    echo "$name $(date +%s%N)" >> "$dir/times.txt"
    n=$((n + 1))
  done
}

gif() {
  mkdir -p "$OUT"
  local frames=$OUT/frames
  state locked; ipc lock >/dev/null; sleep 0.8; ipc refresh; wait_status "locked"
  ipc close; sleep 0.5

  record "$frames" &
  local rec=$!
  sleep 0.8
  ipc open;               sleep 2.2     # locked gate
  ipc unlock;             sleep 0.3     # "Waiting for your master password…"
  wait_status "unlocked" 15; sleep 2.6  # vault list appears
  ipc search "g";         sleep 1.1
  ipc search "gi";        sleep 1.0
  ipc search "git";       sleep 2.4     # ranked matches
  ipc search "";          sleep 1.6
  ipc search "hetz";      sleep 2.2
  ipc settings;           sleep 2.8     # settings page
  ipc close;              sleep 1.2
  touch "$frames/stop"; wait "$rec" || true
  echo "frames: $(ls "$frames" | grep -c png)"
}

case ${1:-} in
  setup) setup ;;
  shots) shots ;;
  gif) gif ;;
  restore) restore ;;
  *) echo "usage: $0 setup|shots|gif|restore" >&2; exit 2 ;;
esac
