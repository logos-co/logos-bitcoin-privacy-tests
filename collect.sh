#!/bin/bash
# On the Mac: copies a run's summary, logs, outputs and (compressed) capture and strace to [dest],
# else $BPT_COLLECT, else ~/btc-privacy. Never secret/, the wallet database, HOME or module binaries.
#   collect.sh <run name> [dest]   (env: BPT_HOST, the test host as ssh names it; BPT_SSH, the ssh command)
set -euo pipefail
NAME="$1"; DEST="${2:-${BPT_COLLECT:-$HOME/btc-privacy}}/$NAME"
SSH="${BPT_SSH:-ssh}"; H="${BPT_HOST:-test-host}"; R="btc-privacy-tests/runs/$NAME"
mkdir -p "$DEST"
$SSH $H "cd $R && for f in strace.log capture.pcap; do [ -f \$f ] && { [ -f \$f.xz ] && [ \$f.xz -nt \$f ] || xz -T4 -k -f \$f; }; done; ls -la strace.log* capture.pcap*"
rsync -a -e "$SSH" --prune-empty-dirs \
  --include='/summary.txt' --include='/isolation.*' --include='/compare-*' --include='/explorer-*.json' --include='/classify-*.txt' --include='/diag-*.txt' --include='/params.env' \
  --include='/started' --include='/finished' --include='/cage.log' --include='/peers-*' --include='/dns.jsonl' \
  --include='/strace.log.xz' --include='/capture.pcap.xz' --include='/cage/***' --include='/out/***' \
  --include='/session/' --include='/session/logs/***' --include='/session/data/' --include='/session/data/*/' \
  --include='/session/data/*/*/' --include='/session/data/*/*/core.log' --exclude='*' "$H:$R/" "$DEST/"
rsync -a -e "$SSH" "$H:btc-privacy-tests/precheck/" "$DEST/../precheck/" --exclude='*.log' || true
du -sh "$DEST"; ls "$DEST"
