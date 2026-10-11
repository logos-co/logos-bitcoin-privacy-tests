#!/bin/bash
# Our own Tor: own DataDirectory, a Unix SocksPort only (IsolateDestAddr), its PID in tor.pid.
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p "$TORDIR/data" "$TORDIR/run" && chmod 700 "$TORDIR" "$TORDIR/data" "$TORDIR/run"
if [ -f "$TORDIR/tor.pid" ] && kill -0 "$(cat "$TORDIR/tor.pid")" 2>/dev/null; then echo "tor already running: $(cat "$TORDIR/tor.pid")"; exit 0; fi
cat > "$TORDIR/torrc" <<EOT
DataDirectory $TORDIR/data
SocksPort unix:$TOR_SOCK IsolateDestAddr
ControlPort 0
PidFile $TORDIR/tor.pid
Log notice file $TORDIR/tor.log
RunAsDaemon 1
EOT
: > "$TORDIR/tor.log"
"$TOOLS/tor/bin/tor" -f "$TORDIR/torrc" --quiet
for _ in $(seq 1 180); do grep -q 'Bootstrapped 100%' "$TORDIR/tor.log" && break; sleep 1; done
grep -q 'Bootstrapped 100%' "$TORDIR/tor.log" || { echo "tor did not bootstrap"; tail -5 "$TORDIR/tor.log"; exit 1; }
echo "tor up: pid $(cat "$TORDIR/tor.pid"), socket $TOR_SOCK"
