#!/bin/bash
# One caged run: peer lists from the crawler's latest runs, the session in the cage, then the analysis.
#   run.sh <name> [session script]   (env: SIGNET_BIRTHDAY, TESTNET4_BIRTHDAY, PHASES, RESTARTS, ...)
set -euo pipefail
source "$(dirname "$0")/env.sh"
RUN="$RUNS/$1"; SESSION="${2:-$HARNESS/session.sh}"
mkdir -p "$RUN"
# Signet: every candidate of the crawler's latest run; testnet4: those that passed its handshake check.
python3 -I - "$RUN" <<'PY'
import glob, json, os, sys
run = sys.argv[1]
for net, passed_only in (("signet", False), ("testnet4", True)):
    files = sorted(glob.glob(os.path.expanduser(f"~/btc-peer-list/runs/{net}/*.json")))
    peers = [p["addr"] for p in json.load(open(files[-1]))["peers"] if p["passed"] or not passed_only] if files else []
    json.dump(peers, open(f"{run}/peers-{net}.json", "w"))
    print(f"{net}: {len(peers)} peers from {files[-1] if files else 'no run'}")
PY
# The node module takes at most 16 own peers: the 16 that answer a bare connect through our Tor fastest.
python3 -I "$HARNESS/peers_probe.py" "$RUN/peers-signet.json" "$RUN/peers-signet.json" 16
env | grep -E '^(SIGNET_|TESTNET4_|T4_|PHASES|RESTART)' > "$RUN/params.env" || true
date -u +%FT%TZ > "$RUN/started"
bash "$HARNESS/cage.sh" "$RUN" "$SESSION" 2>&1 | tee "$RUN/cage.log"
date -u +%FT%TZ > "$RUN/finished"
python3 -I "$HARNESS/analyze.py" "$RUN" | tee "$RUN/isolation.txt"
