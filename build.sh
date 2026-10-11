#!/bin/bash
# Builds logosctl, the keystore side and the four Bitcoin modules (from git archives in $MODS) into $BUILDS.
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p "$BUILDS" "$TOOLS"
for t in tor socat strace tcpdump; do nix build "$NIXPKGS_REF#$t" -o "$TOOLS/$t" "${NIX_FLAGS[@]}"; done
nix build "$CTL_REF#ctl" -o "$BUILDS/logos" "${NIX_FLAGS[@]}"
nix build "$KEYSTORE_REF#install" -o "$BUILDS/result-keystore" "${NIX_FLAGS[@]}"
nix build "$MANAGER_REF#install" -o "$BUILDS/result-manager" "${NIX_FLAGS[@]}"
nix build "$KCLI_REF#install" -o "$BUILDS/result-kcli" "${NIX_FLAGS[@]}"
nix build "$SCLI_REF#install" -o "$BUILDS/result-scli" "${NIX_FLAGS[@]}"
lockrev() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["nodes"][sys.argv[2]]["locked"]["rev"])' "$1" "$2"; }
for m in core backend wcli node; do
  rev_var="$(echo "$m" | tr a-z A-Z)_REV"; dir="$MODS/$m-${!rev_var:0:12}"
  [ -f "$dir/flake.nix" ] || { echo "missing $dir: extract the archive first"; exit 1; }
  ovr=()
  # bitcoind_module and its core-nix at the revs the node module locks, from our own clones in $BPT_HOME/deps.
  if [ "$m" = node ]; then
    ovr=(--override-input bitcoind_module "git+file://$BPT_HOME/deps/logos-bitcoind-module?ref=refs/heads/master&rev=$(lockrev "$dir/flake.lock" bitcoind_module)"
      --override-input bitcoind_module/logos-bitcoin-core-nix "git+file://$BPT_HOME/deps/logos-bitcoin-core-nix?ref=refs/heads/master&rev=$(lockrev "$dir/flake.lock" logos-bitcoin-core-nix)")
  fi
  nix build "path:$dir#install" "${ovr[@]}" -o "$BUILDS/result-$m" "${NIX_FLAGS[@]}" ${DRY:+--dry-run}
done
ls -la "$BUILDS"
