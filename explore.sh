#!/bin/bash
# A short session in the cage: every module loaded, a few reads, the persistence layout listed.
set -uo pipefail
source "$(dirname "$0")/env.sh"; source "$HARNESS/lib.sh"
RUN="$1"; cd "$RUN"; mkdir -p out home session/modules
trap 'ctl daemon stop > /dev/null 2>&1; echo "${rc:-1}" > "$RUN/cage/session.done"' EXIT
export HOME="$RUN/home"
for r in logos result-keystore result-manager result-kcli result-scli result-node result-core result-backend result-wcli; do cp -RL "$BUILDS/$r/modules/." session/modules/; done
chmod -R u+w session/modules
stamp "daemon start"; ctl daemon start --detach; sleep 3
for m in keystore_module signer_manager_module evm_keystore_cli evm_signer_cli bitcoin_node_module bitcoin_wallet_core_module bitcoin_wallet_backend bitcoin_wallet_cli; do
  stamp "load $m"; ctl module load "$m" || echo "load $m failed"
done
sleep 5
ctl module list 2>&1 | head -30
save explore-node-config bitcoin_node_module config_status
save explore-node-sources-signet bitcoin_node_module get_sources signet
save explore-cli-status bitcoin_wallet_cli status
save explore-backend-identity bitcoin_wallet_backend caller_identity
save explore-core-status bitcoin_wallet_core_module status
find session home -type f -newer session/modules 2>/dev/null | grep -v '/modules/' | head -40
rc=0
