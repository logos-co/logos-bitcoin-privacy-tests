#!/bin/bash
# Builds logosctl, the keystore side, tor_module and the four Bitcoin modules (from git archives in $MODS) into $BUILDS.
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p "$BUILDS" "$TOOLS"
for t in tor socat strace tcpdump; do nix build "$NIXPKGS_REF#$t" -o "$TOOLS/$t" "${NIX_FLAGS[@]}"; done
nix build "$CTL_REF#ctl" -o "$BUILDS/logos" "${NIX_FLAGS[@]}"
nix build "$KEYSTORE_REF#install" -o "$BUILDS/result-keystore" "${NIX_FLAGS[@]}"
nix build "$MANAGER_REF#install" -o "$BUILDS/result-manager" "${NIX_FLAGS[@]}"
nix build "$KCLI_REF#install" -o "$BUILDS/result-kcli" "${NIX_FLAGS[@]}"
nix build "$SCLI_REF#install" -o "$BUILDS/result-scli" "${NIX_FLAGS[@]}"
# The node module's hard dependency; it stays idle, as no proxy here is tor_module.
nix build "$TOR_REF#install" -o "$BUILDS/result-tor" "${NIX_FLAGS[@]}"
for m in core backend wcli node; do
  rev_var="$(echo "$m" | tr a-z A-Z)_REV"; dir="$MODS/$m-${!rev_var:0:12}"
  [ -f "$dir/flake.nix" ] || { echo "missing $dir: extract the archive first"; exit 1; }
  nix build "path:$dir#install" -o "$BUILDS/result-$m" "${NIX_FLAGS[@]}" ${DRY:+--dry-run}
done
ls -la "$BUILDS"
