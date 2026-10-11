#!/bin/bash
# The logosctl session (in the cage, under strace): keystore side, the Bitcoin modules, the public test phrase
# restored and opened read-only, per PHASES (below). Usage: session.sh <run-dir> (cage.sh runs it)
set -uo pipefail
source "$(dirname "$0")/env.sh"; source "$HARNESS/lib.sh"
RUN="$1"; cd "$RUN"; mkdir -p out home session/modules; mkdir -m 700 -p secret
CORE=bitcoin_wallet_core_module NODE=bitcoin_node_module CLI=bitcoin_wallet_cli KCLI=evm_keystore_cli
SIGNET_BIRTHDAY="${SIGNET_BIRTHDAY:-}" TESTNET4_BIRTHDAY="${TESTNET4_BIRTHDAY:-}"
SIGNET_SYNC_SECS="${SIGNET_SYNC_SECS:-10800}" T4_SECS="${T4_SECS:-7200}" SERVER_SECS="${SERVER_SECS:-2700}"
RESTARTS="${RESTARTS:-10}" RESTART_SECS="${RESTART_SECS:-1200}" SET_BIRTHDAY="${SET_BIRTHDAY:-196000}"
# Phases, in this order: signet-kyoto restarts signet-servers testnet4 testnet4-servers nobirthday
PHASES="${PHASES:-signet-kyoto restarts signet-servers testnet4 testnet4-servers}"
rc=1
finish() { stamp "teardown"; call $CLI close_wallet > /dev/null 2>&1; sleep 5; ctl daemon stop > /dev/null 2>&1; sleep 3; echo "$rc" > "$RUN/cage/session.done"; }
trap finish EXIT
export HOME="$RUN/home"

stamp "lay out"
for r in logos result-keystore result-manager result-kcli result-scli result-node result-core result-backend result-wcli; do cp -RL "$BUILDS/$r/modules/." session/modules/; done
chmod -R u+w session/modules
stamp "daemon start"; ctl daemon start --detach; sleep 3

stamp "keystore side"
for m in keystore_module signer_manager_module $KCLI evm_signer_cli; do ctl module load "$m"; done
sleep 2
call keystore_module configure '{"approvers":["evm_signer_ui","evm_signer_cli"],"custodians":["evm_keystore_ui","evm_keystore_cli"],"managers":["signer_manager_module"]}' > out/keystore-configure.json
call signer_manager_module configure '{"approvers":["evm_signer_ui","evm_signer_cli"],"custodians":["evm_keystore_ui","evm_keystore_cli"],"signers":["keystore_module"]}' > out/manager-configure.json
# A generated test password, kept in the run's secret/ (0600); the phrase is BIP39's public test vector.
( umask 077; python3 -I -c 'import secrets; print(secrets.token_urlsafe(24), end="")' > secret/pw.txt
  python3 -I - > secret/import.json <<'PY'
import json
print(json.dumps({"phrase": " ".join(["abandon"] * 11 + ["about"]), "family": "bitcoin", "chain": "test",
                  "password": open("secret/pw.txt").read(), "label": "Privacy test (BIP39 test phrase)"}))
PY
)
stamp "restore through evm_keystore_cli"
call $KCLI import_bitcoin @secret/import.json > out/import.json; rm -f secret/import.json
GROUP="$(js 'v["group"]' < out/import.json)"; echo "group $GROUP"

stamp "the Bitcoin modules"
for m in $NODE $CORE bitcoin_wallet_backend $CLI; do ctl module load "$m"; done
sleep 3
stamp "enrol the CLI with the backend"
ROLES="$(call $CLI status | js 'v["rolesFile"]')"
printf '%s\n' '{"custodians":["bitcoin_wallet_ui","bitcoin_wallet_cli"]}' > "$ROLES"
ctl module reload bitcoin_wallet_backend; sleep 3
save cli-status $CLI status
until_for 120 'v.get("state") == "configured"' $NODE config_status > out/node-config.json || true

# open_net <net> <params>: opens through the CLI, decided by the custodian; the open job's state in out/.
open_net() {
  local net="$1" r jid handle
  r="$(call $CLI open_wallet "$2")"; echo "$r" >> "out/$net-open-replies.jsonl"
  jid="$(printf '%s' "$r" | js 'v.get("jobId") or ""')"
  handle="$(printf '%s' "$r" | js 'v.get("openHandle") or ""')"
  [ -n "$handle" ] || handle="$(until_for 90 'v.get("openHandle")' $CLI wallet_status | js 'v["openHandle"]')"
  [ -n "$handle" ] || { echo "no open handle: $r"; return 1; }
  call $KCLI show_access "$handle" > secret/shown.json
  # Approve only what this phase asked for: a request for another network is rejected.
  if ! python3 -I -c "import json,sys; sys.exit(0 if json.load(open('secret/shown.json'))['asked']['network'] == sys.argv[1] else 1)" "$net"; then
    echo "open asked for $(python3 -I -c "import json; print(json.load(open('secret/shown.json'))['asked'])"), not $net: rejected"
    call $KCLI reject_access "$handle" > /dev/null; return 1
  fi
  ( umask 077; python3 -I - "$GROUP" > secret/decision.json <<'PY'
import json, sys
s = json.load(open("secret/shown.json"))
print(json.dumps({"handle": s["handle"], "bundle_id": s["bundle_id"], "group": sys.argv[1], "password": open("secret/pw.txt").read()}))
PY
  )
  call $KCLI approve_access @secret/decision.json > "out/$net-approve.json" 2>&1; rm -f secret/decision.json
  until_for 300 'v.get("state") in ("done","failed","cancelled")' $CLI job_status "$jid" >> "out/$net-open-jobs.jsonl"; echo >> "out/$net-open-jobs.jsonl"
}
# close_net [net]: closes, then waits for the backend to release the node module's lock on net (its 9 s tick).
close_net() {
  # A close with nothing open still starts a backend job, which then refuses network and source changes.
  if [ "$(call $CORE status | js 'v.get("state")')" != no_wallet ]; then call $CLI close_wallet > /dev/null; fi
  until_for 120 'v.get("state") == "no_wallet"' $CORE status > /dev/null
  [ -z "${1:-}" ] || until_for 60 "'$1' not in (v.get('walletOpen') or [])" $NODE config_status > /dev/null
}
# retry_ok <name> <call args...>: repeats a change until the backend accepts it (a pending job refuses it), up to 90 s.
retry_ok() {
  local n="$1"; shift
  for _ in $(seq 45); do
    save "$n" "$@" > /dev/null
    python3 -I -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('ok') else 1)" "out/$n.json" 2>/dev/null && return 0
    sleep 2
  done
  echo "refused: $n: $(cat "out/$n.json")"; return 1
}
# own_peers <net> <file of a JSON array>: Kyoto's own peers through the CLI and the backend.
own_peers() {
  python3 -I -c "import json,sys; print(json.dumps({'network': sys.argv[1], 'peers': json.load(open(sys.argv[2]))}))" "$1" "$2" > "out/$1-own-peers-req.json"
  retry_ok "$1-own-peers" $CLI set_own_peers "@$RUN/out/$1-own-peers-req.json"
}
# servers_tip <net>: the highest tip the node module's probes saw (address-free, through Tor).
servers_tip() { call $NODE source_health "$1" | js 'max([int(s.get("tipHeight") or 0) for s in v.get("sources", [])] or [0])'; }
# wait_tip <net> <secs> <log>: until the core is ready, synced and its authority reaches the servers' tip.
wait_tip() {
  local net="$1" end=$(( $(date +%s) + $2 )) st tip next=0
  while [ "$(date +%s)" -lt "$end" ]; do
    st="$(call $CORE status 2>/dev/null || true)"
    if [ "$(date +%s)" -ge "$next" ]; then tip="$(servers_tip "$net" 2>/dev/null || echo 0)"; printf '%s tip=%s %s\n' "$(date -u +%T)" "$tip" "$st" >> "$3"; next=$(( $(date +%s) + 30 )); fi
    if printf '%s' "$st" | python3 -I -c "
import sys, json; v = json.load(sys.stdin); a = v.get('authority') or {}; k = v.get('kyoto') or {}
tip = int(sys.argv[1] or 0)
# No server tip (testnet4's servers unreachable): Kyoto's own synced, checked against the explorer afterwards.
ref = tip if tip > 0 else (a.get('height') or 0) if k.get('phase') == 'synced' else 0
ok = v.get('state') == 'ready' and v.get('synced') is True and (a.get('height') or 0) >= ref > 0 and (v.get('walletTip') or 0) >= ref
ok = ok and (a.get('kind') != 'kyoto' or k.get('phase') == 'synced') and v.get('rescanFrom') is None
sys.exit(0 if ok else 1)" "${tip:-0}" 2>/dev/null; then return 0; fi
    sleep 5
  done
  return 1
}
# snapshot <prefix>: every read the report compares, through the CLI and the core.
snapshot() {
  local p="$1" page=0
  save "$p-wallet-status" $CLI wallet_status; save "$p-core-status" $CORE status
  save "$p-balances" $CLI balances; save "$p-core-balance" $CORE balance
  save "$p-receive-address" $CLI receive_address; save "$p-fee-rates" $CLI fee_rates
  save "$p-sources" $CLI sources; save "$p-source-health" $CLI source_health; save "$p-exposure" $CLI exposure
  save "$p-sources-status" $CORE sources_status; save "$p-descriptors" $CLI descriptors
  while :; do
    save "$p-history-$page" $CLI history $page > /dev/null
    [ "$(js 'len(v.get("rows") or [])' < "out/$p-history-$page.json" 2>/dev/null || echo 0)" -ge 50 ] || break
    page=$((page + 1))
  done
}
node_reads() {  # node_reads <net> <prefix>
  save "$2-node-sources" $NODE get_sources "$1"
  save "$2-node-peers" $NODE peer_list "$1"; save "$2-node-probe" $NODE probe "$1" str:
  save "$2-node-health" $NODE source_health "$1"
}
bday() { [ -n "$1" ] && printf ',"birthday":%s' "$1"; }
# wait_server <secs> <log>: until a history server has synced (lastSync set) and two balance reads 60 s apart agree.
wait_server() {
  local end=$(( $(date +%s) + $1 )) prev="" cur ss
  while [ "$(date +%s)" -lt "$end" ]; do
    ss="$(call $CORE sources_status 2>/dev/null || true)"; printf '%s %s\n' "$(date -u +%T)" "$ss" >> "$2"
    if printf '%s' "$ss" | python3 -I -c "import sys,json; v=json.load(sys.stdin); sys.exit(0 if [x for x in v.get('sources', []) if x.get('history') and x.get('lastSync')] else 1)" 2>/dev/null; then
      cur="$(call $CORE balance 2>/dev/null)"; [ -n "$prev" ] && [ "$cur" = "$prev" ] && return 0; prev="$cur"; sleep 60; continue
    fi
    sleep 15
  done
  return 1
}

# kstat <status json on stdin>: the Kyoto and birthday fields a restart line or a phase keeps.
kstat() { python3 -I -c "
import sys, json; v = json.load(sys.stdin); k = v.get('kyoto') or {}
print(json.dumps({'authority': v.get('authority'), 'birthday': v.get('birthday'), 'birthdaySource': v.get('birthdaySource'), 'rescanFrom': v.get('rescanFrom'),
  'kyoto': {x: k.get(x) for x in ('phase', 'headers', 'quorum', 'onePeerDecides', 'connected', 'dialled', 'skipped', 'restarts', 'rebuilds', 'rescans', 'window', 'lastWarning', 'lastStop', 'lastConflict')}}))"; }
# sync_phase <net> <label> <secs> <prefix> [server-secs]: open, wait for the tip (and a server's sync), snapshot.
sync_phase() {
  local net="$1" label="$2" secs="$3" p="$4" T0 T1
  stamp "$label: open"
  T0=$(ms); open_net "$net" "{\"family\":\"bitcoin\"$(bday "$5")}" || { echo "$label: open failed"; exit 1; }
  if wait_tip "$net" "$secs" "out/$p-progress.log"; then echo "$label: at the tip in $(( $(ms) - T0 )) ms" | tee -a out/timings.txt
  else echo "$label: not at the tip after ${secs}s" | tee -a out/timings.txt; fi
  if [ -n "${6:-}" ]; then
    T1=$(ms)
    if wait_server "$6" "out/$p-server-progress.log"; then echo "$label: history server synced and stable $(( $(ms) - T1 )) ms after the tip" | tee -a out/timings.txt
    else echo "$label: history server not synced after ${6}s" | tee -a out/timings.txt; fi
  fi
  call $CORE status | kstat > "out/$p-kyoto.json"
  stamp "$label: snapshot"; snapshot "$p"; node_reads "$net" "$p-after"
}
# history_on <net> <prefix> <kind...>: history on for every source of those kinds the node module offers.
history_on() {
  local net="$1" p="$2"; shift 2
  for id in $(python3 -I -c "import json,sys; print(' '.join(s['id'] for s in json.load(open(sys.argv[1]))['sources'] if s['kind'] in sys.argv[2:]))" "out/$p-node-sources.json" "$@"); do
    retry_ok "$p-set-$id" $CLI set_source "$id" '{"use":true,"history":true}'
  done
}
has() { [[ " $PHASES " == *" $1 "* ]]; }

if has signet-kyoto; then
  stamp "signet, Kyoto alone on the node module's verified list"
  retry_ok sk-set-network $CLI set_active_network signet || exit 1
  node_reads signet sk-before
  sync_phase signet "signet Kyoto" "$SIGNET_SYNC_SECS" sk "$SIGNET_BIRTHDAY"
fi

if has restarts; then
  for i in $(seq 1 "$RESTARTS"); do
    stamp "restart $i"
    close_net signet; tip="$(servers_tip signet)"
    T0=$(ms); open_net signet "{\"family\":\"bitcoin\"}" || echo "restart $i: open failed"; T1=$(ms)
    if wait_tip signet "$RESTART_SECS" "out/restart-$i.log"; then res=tip; else res=timeout; fi
    T2=$(ms)
    call $CORE status | kstat | python3 -I -c "
import sys, json; v = json.load(sys.stdin)
v.update({'run': $i, 'result': '$res', 'tipBefore': int('$tip' or 0), 'openMs': $T1 - $T0, 'syncMs': $T2 - $T1, 'totalMs': $T2 - $T0}); print(json.dumps(v))" | tee -a out/restarts.jsonl
  done
  snapshot after-restarts
fi

if has signet-servers; then
  stamp "signet with every history server it offers"
  close_net signet
  retry_ok ss-set-network $CLI set_active_network signet || exit 1
  node_reads signet ss-before
  history_on signet ss-before esplora electrum
  node_reads signet ss-before
  sync_phase signet "signet servers" "$SIGNET_SYNC_SECS" ss "" "$SERVER_SECS"
fi

if has testnet4; then
  stamp "testnet4 on the node module's defaults"
  close_net signet
  retry_ok t4-set-network $CLI set_active_network testnet4 || exit 1
  node_reads testnet4 t4-before
  sync_phase testnet4 "testnet4 defaults" "$T4_SECS" t4 "$TESTNET4_BIRTHDAY"
fi

if has testnet4-servers; then
  stamp "testnet4 with every history server it offers"
  close_net testnet4
  retry_ok t4s-set-network $CLI set_active_network testnet4 || exit 1
  node_reads testnet4 t4s-before
  history_on testnet4 t4s-before esplora electrum
  node_reads testnet4 t4s-before
  sync_phase testnet4 "testnet4 servers" "$T4_SECS" t4s "" "$SERVER_SECS"
fi

if has nobirthday; then
  stamp "signet restore without a birthday, then set_birthday $SET_BIRTHDAY"
  close_net signet
  retry_ok nb-set-network $CLI set_active_network signet || exit 1
  T0=$(ms); open_net signet '{"family":"bitcoin"}' || { echo "no-birthday open failed"; exit 1; }
  sleep 10; save nb-open-status $CORE status > /dev/null
  r="$(call $CLI set_birthday "{\"height\":$SET_BIRTHDAY}")"; echo "$r" > out/nb-set-birthday.json
  jid="$(printf '%s' "$r" | js 'v.get("jobId") or ""')"
  until_for 300 'v.get("state") in ("done","failed","cancelled")' $CLI job_status "$jid" > out/nb-set-birthday-job.json || true
  if wait_tip signet "$SIGNET_SYNC_SECS" out/nb-progress.log; then echo "no birthday, then set_birthday: at the tip in $(( $(ms) - T0 )) ms" | tee -a out/timings.txt
  else echo "no birthday, then set_birthday: not at the tip after ${SIGNET_SYNC_SECS}s" | tee -a out/timings.txt; fi
  call $CORE status | kstat > out/nb-kyoto.json
  stamp "no birthday: snapshot"; snapshot nb; node_reads signet nb-after
fi
rc=0
