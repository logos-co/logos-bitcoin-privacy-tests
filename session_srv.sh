#!/bin/bash
# As session.sh, signet only, and the snapshot waits for the first history server's sync to be applied.
# Usage: session_srv.sh <run-dir> (cage.sh runs it). Env: SERVER_SECS (default 2700).
set -uo pipefail
source "$(dirname "$0")/env.sh"; source "$HARNESS/lib.sh"
RUN="$1"; cd "$RUN"; mkdir -p out home session/modules; mkdir -m 700 -p secret
CORE=bitcoin_wallet_core_module NODE=bitcoin_node_module CLI=bitcoin_wallet_cli KCLI=evm_keystore_cli
SIGNET_BIRTHDAY="${SIGNET_BIRTHDAY:-}" TESTNET4_BIRTHDAY="${TESTNET4_BIRTHDAY:-}"
SIGNET_SYNC_SECS="${SIGNET_SYNC_SECS:-10800}" T4_SECS="${T4_SECS:-900}" T4_PEER_SECS="${T4_PEER_SECS:-5400}"
RESTARTS="${RESTARTS:-10}" RESTART_SECS="${RESTART_SECS:-1200}" PHASES="${PHASES:-signet}" SERVER_SECS="${SERVER_SECS:-2700}"
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

stamp "node module; the test gate admits logosctl for set_own_peers"
ctl module load $NODE; sleep 2
NODE_DIR="$(find "$RUN/session/data/$NODE" -mindepth 1 -maxdepth 1 -type d | head -1)"
printf '%s\n' '{"allowHost":true}' > "$NODE_DIR/callers.json"
ctl module reload $NODE; sleep 2
for m in $CORE bitcoin_wallet_backend $CLI; do ctl module load "$m"; done
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
  ( umask 077; python3 -I - "$GROUP" > secret/decision.json <<'PY'
import json, sys
s = json.load(open("secret/shown.json"))
print(json.dumps({"handle": s["handle"], "bundle_id": s["bundle_id"], "group": sys.argv[1], "password": open("secret/pw.txt").read()}))
PY
  )
  call $KCLI approve_access @secret/decision.json > /dev/null; rm -f secret/decision.json
  until_for 300 'v.get("state") in ("done","failed","cancelled")' $CLI job_status "$jid" >> "out/$net-open-jobs.jsonl"; echo >> "out/$net-open-jobs.jsonl"
}
close_net() { call $CLI close_wallet > /dev/null; until_for 120 'v.get("state") == "no_wallet"' $CORE status > /dev/null; }
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
ok = v.get('state') == 'ready' and v.get('synced') is True and (a.get('height') or 0) >= tip > 0 and (v.get('walletTip') or 0) >= tip
ok = ok and (a.get('kind') != 'kyoto' or k.get('phase') == 'synced')
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
  save "$2-node-sources" $NODE get_sources "$1"; save "$2-node-routes" $NODE route_table "$1"
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

if [[ " $PHASES " == *" signet "* ]]; then
  stamp "signet: sources"
  save signet-set-network $CLI set_active_network signet
  for s in blockstream.info-onion blockstream.info mempool.space-onion mempool.space; do save "signet-set-$s" $CLI set_source "$s" '{"use":true,"history":true}' > /dev/null; done
  save signet-own-peers $NODE set_own_peers signet "@$RUN/peers-signet.json" > /dev/null
  node_reads signet signet-before
  stamp "signet: open"
  T0=$(ms); open_net signet "{\"family\":\"bitcoin\"$(bday "$SIGNET_BIRTHDAY")}"
  stamp "signet: syncing"
  if wait_tip signet "$SIGNET_SYNC_SECS" out/signet-progress.log; then echo "SIGNET synced in $(( $(ms) - T0 )) ms" | tee -a out/timings.txt
  else echo "SIGNET not at the tip after ${SIGNET_SYNC_SECS}s" | tee -a out/timings.txt; fi
  stamp "signet: Kyoto-only snapshot"; snapshot signet-kyoto
  stamp "signet: waiting for the history server's sync"
  T1=$(ms)
  if wait_server "$SERVER_SECS" out/signet-server-progress.log; then echo "SIGNET history server synced and stable $(( $(ms) - T1 )) ms after the tip" | tee -a out/timings.txt
  else echo "SIGNET history server not synced after ${SERVER_SECS}s" | tee -a out/timings.txt; fi
  stamp "signet: snapshot"; snapshot signet; node_reads signet signet-after
fi

if [[ " $PHASES " == *" restarts "* ]]; then
  for i in $(seq 1 "$RESTARTS"); do
    stamp "restart $i"
    close_net; tip="$(servers_tip signet)"
    T0=$(ms); open_net signet "{\"family\":\"bitcoin\"$(bday "$SIGNET_BIRTHDAY")}" || echo "restart $i: open failed"; T1=$(ms)
    if wait_tip signet "$RESTART_SECS" "out/restart-$i.log"; then res=tip; else res=timeout; fi
    T2=$(ms)
    call $CORE status | python3 -I -c "
import sys, json; v = json.load(sys.stdin); k = v.get('kyoto') or {}
print(json.dumps({'run': $i, 'result': '$res', 'tipBefore': int('$tip' or 0), 'openMs': $T1 - $T0, 'syncMs': $T2 - $T1, 'totalMs': $T2 - $T0,
  'authority': v.get('authority'), 'kyoto': {x: k.get(x) for x in ('phase', 'headers', 'connected', 'dialled', 'skipped', 'restarts', 'rebuilds', 'lastWarning', 'lastStop')}}))" | tee -a out/restarts.jsonl
  done
  snapshot after-restarts
fi

if [[ " $PHASES " == *" testnet4 "* ]]; then
  # Read late: the explorer's first height for testnet4 may arrive while signet runs.
  [ -n "$TESTNET4_BIRTHDAY" ] || TESTNET4_BIRTHDAY="$(cat "$RUN/testnet4-birthday" 2>/dev/null || true)"
  stamp "testnet4: sources as the node module offers them (birthday ${TESTNET4_BIRTHDAY:-none})"
  close_net
  save t4-set-network $CLI set_active_network testnet4
  for s in mempool.space mempool.space-onion; do save "t4-set-$s" $CLI set_source "$s" '{"use":true,"history":true}' > /dev/null; done
  node_reads testnet4 t4-before
  stamp "testnet4: open (shipped peer list)"
  T0=$(ms); open_net testnet4 "{\"family\":\"bitcoin\"$(bday "$TESTNET4_BIRTHDAY")}"
  if wait_tip testnet4 "$T4_SECS" out/t4-progress.log; then echo "TESTNET4 synced in $(( $(ms) - T0 )) ms" | tee -a out/timings.txt
  else echo "TESTNET4 not at the tip after ${T4_SECS}s (shipped peer list)" | tee -a out/timings.txt; fi
  stamp "testnet4: snapshot (shipped peer list)"; snapshot t4; node_reads testnet4 t4-after
  if [ -s "$RUN/peers-testnet4.json" ]; then
    stamp "testnet4: the crawler's peer as own peer"
    close_net
    save t4-own-peers $NODE set_own_peers testnet4 "@$RUN/peers-testnet4.json" > /dev/null
    T0=$(ms); open_net testnet4 "{\"family\":\"bitcoin\"$(bday "$TESTNET4_BIRTHDAY")}"
    if wait_tip testnet4 "$T4_PEER_SECS" out/t4p-progress.log; then echo "TESTNET4 (own peer) synced in $(( $(ms) - T0 )) ms" | tee -a out/timings.txt
    else echo "TESTNET4 (own peer) not at the tip after ${T4_PEER_SECS}s" | tee -a out/timings.txt; fi
    sleep 60
    stamp "testnet4: snapshot (own peer)"; snapshot t4p; node_reads testnet4 t4p-after
  fi
fi
rc=0
