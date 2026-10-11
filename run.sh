#!/bin/bash
# One caged run: the session in the cage, then the isolation analysis.
#   run.sh <name> [session script]   (env: PHASES, SIGNET_BIRTHDAY, TESTNET4_BIRTHDAY, SET_BIRTHDAY, OWN_PEERS, ...)
set -euo pipefail
source "$(dirname "$0")/env.sh"
RUN="$RUNS/$1"; SESSION="${2:-$HARNESS/session.sh}"
mkdir -p "$RUN"
# Own peers only on request (OWN_PEERS=1): the crawler's latest candidates, the 16 fastest to answer a bare connect.
if [ -n "${OWN_PEERS:-}" ]; then
  python3 -I - "$RUN" <<'PY'
import glob, json, os, sys
for net, passed_only in (("signet", False), ("testnet4", True)):
    files = sorted(glob.glob(os.path.expanduser(f"~/btc-peer-list/runs/{net}/*.json")))
    peers = [p["addr"] for p in json.load(open(files[-1]))["peers"] if p["passed"] or not passed_only] if files else []
    json.dump(peers, open(f"{sys.argv[1]}/peers-{net}.json", "w"))
PY
  python3 -I "$HARNESS/peers_probe.py" "$RUN/peers-signet.json" "$RUN/peers-signet.json" 16
fi
env | grep -E '^(SIGNET_|TESTNET4_|T4_|PHASES|RESTART|SERVER_|SET_BIRTHDAY|OWN_PEERS)' > "$RUN/params.env" || true
date -u +%FT%TZ > "$RUN/started"
bash "$HARNESS/cage.sh" "$RUN" "$SESSION" 2>&1 | tee "$RUN/cage.log" || echo "cage exited non-zero; analysing anyway" | tee -a "$RUN/cage.log"
date -u +%FT%TZ > "$RUN/finished"
python3 -I "$HARNESS/analyze.py" "$RUN" | tee "$RUN/isolation.txt"
