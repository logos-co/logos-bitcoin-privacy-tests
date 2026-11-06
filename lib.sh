# Session helpers (after common.sh in the wallet core's tools/e2e): logosctl calls, polls, JSON picks.
ctl() { "$BUILDS/logos/bin/logosctl" --config-dir "$RUN/session" "$@"; }
call() { ctl call "$@" --human; }
js() { python3 -I -c "import sys,json; v=json.load(sys.stdin); print($1)"; }
ms() { date +%s%3N; }
stamp() { printf '%s %s\n' "$(date -u +%FT%T.%3NZ)" "$*" | tee -a "$RUN/cage/phases.log"; }
# save <name> <call args...>: keeps a call's reply under out/ and prints it.
save() { local n="$1"; shift; call "$@" > "$RUN/out/$n.json" 2> "$RUN/out/$n.err" || true; cat "$RUN/out/$n.json"; echo; }
# until_for <secs> <python expr over v> <call args...>: polls until true; prints the reply.
until_for() {
  local secs="$1" expr="$2"; shift 2
  local end=$(( $(date +%s) + secs )) r=""
  while [ "$(date +%s)" -lt "$end" ]; do
    r="$(call "$@" 2>/dev/null || true)"
    if [ -n "$r" ] && printf '%s' "$r" | python3 -I -c "import sys,json; v=json.load(sys.stdin); sys.exit(0 if ($expr) else 1)" 2>/dev/null; then
      printf '%s' "$r"; return 0
    fi
    sleep "${POLL:-1}"
  done
  echo "timed out after ${secs}s: $*: $expr; last: ${r:0:300}" >&2; return 1
}
# The modules every session lays out, from $BUILDS.
RESULTS="logos result-keystore result-manager result-kcli result-scli result-tor result-node result-core result-backend result-wcli"
# node_on_our_tor: the host admitted (callers.json) to set Use Tor for all, and our Tor bridge as the
# proxy before the backend's init_defaults would name tor_module. Returns 1 unless both took.
node_on_our_tor() {
  local d
  ctl module load bitcoin_node_module; sleep 2
  d="$(ls -d "$RUN/session/data/bitcoin_node_module"/*/ 2>/dev/null | head -1)"
  [ -n "$d" ] || { echo "no persistence directory for bitcoin_node_module"; return 1; }
  printf '%s\n' '{"modules":[],"allowHost":true}' > "${d}callers.json"
  ctl module unload bitcoin_node_module; sleep 1; ctl module load bitcoin_node_module; sleep 2
  save node-proxy bitcoin_node_module set_proxy socks5h://127.0.0.1:9050 > /dev/null
  # Use Tor for is kept per network: both networks the session runs.
  save node-tor-use bitcoin_node_module set_tor_use signet all > /dev/null
  save node-tor-use-testnet4 bitcoin_node_module set_tor_use testnet4 all > /dev/null
  python3 -I -c "import json,sys; sys.exit(0 if all(json.load(open(f)).get('ok') for f in sys.argv[1:]) else 1)" \
    "$RUN/out/node-proxy.json" "$RUN/out/node-tor-use.json" "$RUN/out/node-tor-use-testnet4.json"
}
# The instance persistence directory of a loaded module, found by a file it keeps there.
persist_dir() { dirname "$(find "$RUN/session" "$RUN/home" -path "*$1*" -name "$2" 2>/dev/null | head -1)"; }
