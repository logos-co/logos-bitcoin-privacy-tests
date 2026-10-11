#!/bin/bash
# The cage: bwrap makes user+net namespaces (only lo); nsenter joins them unconfined as uid 0, unshare adds a mount ns.
# (`unshare --user` is refused by AppArmor here.) Usage: cage.sh <run-dir> <session script> [args...]
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p "$1/cage" && RUN="$(cd "$1" && pwd)" && SESSION="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2
/usr/bin/bwrap --unshare-user --uid 0 --gid 0 --unshare-net --die-with-parent --bind / / --dev /dev --proc /proc -- sleep infinity < /dev/null > /dev/null 2>&1 &
BW=$!
HOLDER=""
for _ in $(seq 100); do HOLDER=$(pgrep -P "$BW" || true); [ -n "$HOLDER" ] && break; sleep 0.1; done
[ -n "$HOLDER" ] || { echo "cage: no namespace holder"; kill "$BW"; exit 1; }
readlink "/proc/$HOLDER/ns/net" > "$RUN/cage/netns"
echo "bwrap $BW holder $HOLDER netns $(cat "$RUN/cage/netns")"
rc=0
OUTER_UID=$(id -u) nsenter --preserve-credentials -U -n -t "$HOLDER" -- \
  unshare --mount --propagation private -- bash "$HARNESS/inside.sh" "$RUN" "$SESSION" "$@" || rc=$?
# Anything still in the cage's netns is ours alone: stop it by PID.
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  [ "$p" = "$HOLDER" ] && continue
  [ "$(readlink "/proc/$p/ns/net" 2>/dev/null)" = "$(cat "$RUN/cage/netns")" ] || continue
  { echo "cage: left over $p $(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-120)"; kill "$p" 2>/dev/null || true; }
done
kill "$HOLDER" "$BW" 2>/dev/null || true
exit $rc
