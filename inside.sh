#!/bin/bash
# In the cage (uid 0 in its user ns, only lo): hide host resolvers, log DNS, bridge Tor, capture every
# interface, then run the session under strace. Usage: inside.sh <run-dir> <session script> [args...]
set -euo pipefail
source "$(dirname "$0")/env.sh"
RUN="$1"; SESSION="$2"; shift 2
cd "$RUN"
C="$RUN/cage"
stamp() { printf '%s %s\n' "$(date -u +%FT%T.%3NZ)" "$*" | tee -a "$C/phases.log"; }

# Resolvers: resolv.conf names 127.0.0.1 only; resolved's, nscd's, avahi's and D-Bus sockets are hidden.
mount -t tmpfs -o mode=755 tmpfs /run/systemd/resolve
printf 'nameserver 127.0.0.1\noptions timeout:1 attempts:1\n' > /run/systemd/resolve/stub-resolv.conf
cp /run/systemd/resolve/stub-resolv.conf /run/systemd/resolve/resolv.conf
[ -L /etc/resolv.conf ] || mount --bind /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
for d in /run/dbus /run/avahi-daemon /run/nscd "/run/user/$OUTER_UID"; do [ -d "$d" ] && mount -t tmpfs -o mode=700 tmpfs "$d"; done
# A private /tmp: Logos IPC sockets live there, and the host's other daemons must stay out of reach.
mount -t tmpfs -o mode=1777 tmpfs /tmp
unset DBUS_SESSION_BUS_ADDRESS DBUS_SYSTEM_BUS_ADDRESS
export XDG_RUNTIME_DIR="$C/xdg"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
cp /etc/resolv.conf "$C/resolv.conf.seen"
{ ip -br link; ip -br addr; ip route; ip -6 route; } > "$C/net-start.txt" 2>&1

"$TOOLS/tcpdump/bin/tcpdump" -i any -s 192 -U -w "$RUN/capture.pcap" 2> "$C/tcpdump.err" &
TCPDUMP=$!
python3 -I "$HARNESS/dnslog.py" "$RUN/dns.jsonl" "$C/dnslog.ready" 2> "$C/dnslog.err" &
DNSLOG=$!
"$TOOLS/socat/bin/socat" -d -d -lf "$C/socat.log" TCP4-LISTEN:9050,bind=127.0.0.1,reuseaddr,fork "UNIX-CONNECT:$TOR_SOCK" &
SOCAT=$!
echo "tcpdump $TCPDUMP dnslog $DNSLOG socat $SOCAT" > "$C/helpers.pids"
for _ in $(seq 100); do grep -q 'listening on' "$C/tcpdump.err" 2>/dev/null && [ -f "$C/dnslog.ready" ] && break; sleep 0.1; done

# Canaries, before the session: both glibcs reach the logger; strace shows a refused non-loopback connect.
stamp "canaries"
getent hosts canary-system-glibc.invalid > /dev/null || true
"$TOOLS/socat/bin/socat" -T 2 - TCP:canary-nix-glibc.invalid:80 < /dev/null 2> /dev/null || true
"$TOOLS/strace/bin/strace" -f -e trace=connect -o "$C/strace-canary.log" python3 -I -c '
import socket
for a in (("192.0.2.1", 443), ("127.0.0.1", 9050)):
    s = socket.socket(); s.settimeout(2)
    try: s.connect(a)
    except OSError: pass' || true
sleep 1

stamp "session start"
rm -f "$C/session.done"
"$TOOLS/strace/bin/strace" -f --seccomp-bpf -tt -yy -s 64 -o "$RUN/strace.log" \
  -e trace=connect,sendto,sendmsg,sendmmsg,execve,clone,clone3,fork,vfork \
  bash "$SESSION" "$RUN" "$@" &
STRACE=$!
while kill -0 "$STRACE" 2>/dev/null && [ ! -f "$C/session.done" ]; do sleep 1; done
for _ in $(seq 90); do kill -0 "$STRACE" 2>/dev/null || break; sleep 1; done
# Tracees that outlived the session (a daemon left running): exactly those whose TracerPid is our strace.
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  [ "$(awk '/^TracerPid:/ {print $2}' "/proc/$p/status" 2>/dev/null)" = "$STRACE" ] || continue
  echo "left over tracee $p: $(tr '\0' ' ' < "/proc/$p/cmdline" | cut -c1-120)" | tee -a "$C/phases.log"
  kill "$p" 2>/dev/null || true
done
rc=0; wait "$STRACE" || rc=$?
stamp "session end rc=$(cat "$C/session.done" 2>/dev/null || echo none) strace=$rc"

{ ip -br link; ip -br addr; ip route; ip -6 route; } > "$C/net-end.txt" 2>&1
sleep 2
kill "$SOCAT" "$DNSLOG" 2>/dev/null || true
kill -INT "$TCPDUMP" 2>/dev/null || true
wait "$TCPDUMP" 2>/dev/null || true
exit $rc
