#!/usr/bin/env python3
# The test wallet's view from an Esplora API over our Tor: gap-limit address scan, every tx, balances.
#   explorer.py <signet|testnet4> <tpub or wpkh descriptor> <out.json> [--gap N] [--stats-only] [--host H]
# Default host mempool.space (https); blockstream's onion is http. Failing circuits are retried, patiently.
import json, os, queue, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import derive, torget

SOCK = os.path.expanduser(os.environ.get("TOR_SOCK", "~/btc-privacy-tests/tor/run/socks.sock"))
WORKERS = 10
HOST = sys.argv[sys.argv.index("--host") + 1] if "--host" in sys.argv else "mempool.space"
POOL = queue.Queue()
for _ in range(WORKERS): POOL.put(torget.Https(SOCK, HOST))
STATS = {"requests": 0, "retries": 0}
LOCK = threading.Lock()


def api(net, path, tries=60):
    c = POOL.get()
    try:
        for n in range(tries):
            try:
                st, body = c.get(f"/{net}/api{path}")
                with LOCK: STATS["requests"] += 1
                if st == 200: return json.loads(body)
                err = f"HTTP {st} {body[:60]!r}"
                c.close()
            except Exception as e:
                err = repr(e)
            with LOCK: STATS["retries"] += 1
            print(f"  retry {n + 1}/{tries} {path[:70]}: {err}", file=sys.stderr, flush=True)
            time.sleep(min(30, 2 ** n))
        raise RuntimeError(f"explorer: gave up on {path}")
    finally:
        POOL.put(c)


def scan(net, xpub, gap, ex):
    addrs = {}
    for branch in (0, 1):
        i, last_used = 0, -1
        while i - last_used <= gap:
            batch = derive.addresses(xpub, branch, i, gap, "tb")
            for k, (a, s) in enumerate(zip(batch, ex.map(lambda a: api(net, f"/address/{a}"), batch))):
                addrs[a] = {"branch": branch, "index": i + k, "chain": s["chain_stats"], "mempool": s["mempool_stats"]}
                if s["chain_stats"]["tx_count"] + s["mempool_stats"]["tx_count"]: last_used = i + k
            i += gap
            print(f"  branch {branch}: {i} scanned, last used {last_used}, {STATS}", file=sys.stderr, flush=True)
        print(f"  branch {branch}: {i} scanned, last used index {last_used}", file=sys.stderr, flush=True)
    return addrs


def txs_of(net, a):
    out = api(net, f"/address/{a}/txs")
    chain = [t for t in out if t["status"]["confirmed"]]
    while chain and len(chain) % 25 == 0:
        more = api(net, f"/address/{a}/txs/chain/{chain[-1]['txid']}")
        if not more: break
        chain += more
        out += more
    return out


def main():
    net, key, path = sys.argv[1], sys.argv[2], sys.argv[3]
    gap = int(sys.argv[sys.argv.index("--gap") + 1]) if "--gap" in sys.argv else 20
    xpub = derive.from_descriptor(key)[0] if key.startswith("wpkh(") else key
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        # Every connection builds its circuit at once; the ones that reach mempool.space are kept.
        def warm(_):
            try: return api(net, "/blocks/tip/height", tries=3)
            except RuntimeError: return 0
        tip = max(ex.map(warm, range(WORKERS))) or api(net, "/blocks/tip/height")
        addrs = scan(net, xpub, gap, ex)
        used = [a for a, v in addrs.items() if v["chain"]["tx_count"] + v["mempool"]["tx_count"]]
        res = {"network": net, "xpub": xpub, "gap": gap, "tipBefore": tip, "addresses": addrs,
               "balance": {"confirmed": sum(v["chain"]["funded_txo_sum"] - v["chain"]["spent_txo_sum"] for v in addrs.values()),
                           "mempool": sum(v["mempool"]["funded_txo_sum"] - v["mempool"]["spent_txo_sum"] for v in addrs.values())}}
        if "--stats-only" not in sys.argv:
            seen = {t["txid"]: t for lst in ex.map(lambda a: txs_of(net, a), used) for t in lst}
            mine, rows = set(addrs), []
            for t in seen.values():
                recv = sum(o["value"] for o in t["vout"] if o.get("scriptpubkey_address") in mine)
                spent = sum(i["prevout"]["value"] for i in t["vin"] if (i.get("prevout") or {}).get("scriptpubkey_address") in mine)
                foreign_in = sum(1 for i in t["vin"] if (i.get("prevout") or {}).get("scriptpubkey_address") not in mine)
                paid = sum(o["value"] for o in t["vout"] if o.get("scriptpubkey_address") not in mine)
                st = t["status"]
                rows.append({"txid": t["txid"], "netSat": recv - spent, "recvSat": recv, "spentSat": spent, "paidForeignSat": paid,
                             "foreignInputs": foreign_in, "feeSat": t.get("fee"), "confirmed": st["confirmed"],
                             "height": st.get("block_height"), "blockHash": st.get("block_hash"), "time": st.get("block_time"),
                             "spendsOurs": spent > 0})
            rows.sort(key=lambda r: (r["height"] or 1 << 31, r["txid"]))
            res["txs"] = rows
            res["firstHeight"] = min((r["height"] for r in rows if r["height"]), default=None)
        res["tipAfter"] = api(net, "/blocks/tip/height")
    res["requests"], res["seconds"], res["host"] = dict(STATS), round(time.time() - t0), HOST
    json.dump(res, open(path, "w"), indent=1)
    print(json.dumps({"network": net, "used": len(used), "txs": len(res.get("txs", [])), "balance": res["balance"],
                      "firstHeight": res.get("firstHeight"), "tip": res["tipAfter"], "requests": STATS, "seconds": res["seconds"]}))


if __name__ == "__main__":
    main()
