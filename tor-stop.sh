#!/bin/bash
# Stops our Tor by the PID in its PidFile, never by name.
set -euo pipefail
source "$(dirname "$0")/env.sh"
[ -f "$TORDIR/tor.pid" ] || { echo "no tor.pid"; exit 0; }
pid=$(cat "$TORDIR/tor.pid")
if [ "$(readlink -f /proc/$pid/exe 2>/dev/null)" = "$(readlink -f "$TOOLS/tor/bin/tor")" ]; then kill "$pid"; echo "stopped tor $pid"; else echo "pid $pid is not our tor; left alone"; fi
