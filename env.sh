# Paths on the test host; sourced by every script. Pins live in pins.env beside it.
HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HARNESS/pins.env"
BPT_HOME="${BPT_HOME:-$HOME/btc-privacy-tests}"
MODS="$BPT_HOME/mods" BUILDS="$BPT_HOME/builds" TORDIR="$BPT_HOME/tor" RUNS="$BPT_HOME/runs" TOOLS="$BPT_HOME/tools"
TOR_SOCK="$TORDIR/run/socks.sock"
NIX_FLAGS=(--cores 8 --max-jobs 2)
tool() { readlink -f "$TOOLS/$1"; }
