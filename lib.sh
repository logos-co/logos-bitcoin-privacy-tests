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
# The instance persistence directory of a loaded module, found by a file it keeps there.
persist_dir() { dirname "$(find "$RUN/session" "$RUN/home" -path "*$1*" -name "$2" 2>/dev/null | head -1)"; }
