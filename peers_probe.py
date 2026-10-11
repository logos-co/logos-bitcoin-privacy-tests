#!/usr/bin/env python3
# Ranks candidate onion peers by a bare SOCKS connect through our Tor (nothing sent past SOCKS); keeps the best N.
#   peers_probe.py <candidates.json> <out.json> [N]
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torget

SOCK = os.path.expanduser(os.environ.get("TOR_SOCK", "~/btc-privacy-tests/tor/run/socks.sock"))


def probe(addr):
    host, port = addr.rsplit(":", 1)
    t = time.time()
    try:
        torget.socks_connect(SOCK, host, int(port), f"peer-{host[:16]}", 90).close()
        return addr, round(time.time() - t, 1), None
    except Exception as e:
        return addr, None, repr(e)[:80]


cands, n = json.load(open(sys.argv[1])), int(sys.argv[3]) if len(sys.argv) > 3 else 16
with ThreadPoolExecutor(8) as ex: res = list(ex.map(probe, cands))
ok = sorted([r for r in res if r[1] is not None], key=lambda r: r[1])
rest = [r for r in res if r[1] is None]
keep = [r[0] for r in ok + rest][:n]
json.dump(keep, open(sys.argv[2], "w"))
json.dump([{"addr": a, "connectS": s, "error": e} for a, s, e in res], open(sys.argv[2] + ".probe.json", "w"), indent=1)
print(f"{len(ok)} of {len(cands)} accepted a connection; kept {len(keep)}: {len([1 for r in ok[:n]])} that answered")
