#!/usr/bin/env python3
# Logs every DNS query to 127.0.0.1:53 and [::1]:53, UDP and TCP, and answers REFUSED.
#   dnslog.py <log.jsonl> <ready-file>
import json, socket, struct, sys, threading, time

LOG = open(sys.argv[1], "a", buffering=1)
LOCK = threading.Lock()


def question(msg):
    try:
        i, labels = 12, []
        while msg[i]:
            labels.append(msg[i + 1:i + 1 + msg[i]].decode(errors="replace"))
            i += 1 + msg[i]
        return ".".join(labels), struct.unpack(">H", msg[i + 1:i + 3])[0]
    except Exception:
        return None, None


def log(proto, peer, msg):
    name, qtype = question(msg)
    with LOCK:
        LOG.write(json.dumps({"t": time.time(), "proto": proto, "peer": list(peer[:2]), "qname": name, "qtype": qtype, "bytes": len(msg)}) + "\n")


def refused(msg):
    return msg[:2] + bytes([msg[2] | 0x80, (msg[3] & 0xF0) | 5]) + msg[4:6] + b"\0" * 6 + msg[12:] if len(msg) >= 12 else b""


def udp(fam, host):
    s = socket.socket(fam, socket.SOCK_DGRAM)
    s.bind((host, 53))
    while True:
        msg, peer = s.recvfrom(65535)
        log("udp", peer, msg)
        if refused(msg): s.sendto(refused(msg), peer)


def tcp_client(c, peer):
    with c:
        c.settimeout(5)
        try:
            while (h := c.recv(2)) and len(h) == 2:
                n, msg = struct.unpack(">H", h)[0], b""
                while len(msg) < n and (chunk := c.recv(n - len(msg))): msg += chunk
                log("tcp", peer, msg)
                r = refused(msg)
                c.sendall(struct.pack(">H", len(r)) + r)
        except OSError:
            pass


def tcp(fam, host):
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, 53))
    s.listen(64)
    while True:
        c, peer = s.accept()
        log("tcp-connect", peer, b"")
        threading.Thread(target=tcp_client, args=(c, peer), daemon=True).start()


for fam, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
    for f in (udp, tcp):
        threading.Thread(target=f, args=(fam, host), daemon=True).start()
time.sleep(0.5)
open(sys.argv[2], "w").write("ready\n")
while True:
    time.sleep(3600)
