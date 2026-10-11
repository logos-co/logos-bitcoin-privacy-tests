#!/usr/bin/env python3
# Checks each transaction the wallet shows and the explorer's gap-limit scan lacks, against the explorer itself.
#   extras.py <run-dir> <prefix> <explorer.json> [--host H] [--ext N]   -> <run-dir>/extras-<prefix>.json
import glob, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import derive, explorer, torget

run, prefix, ex = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
host = sys.argv[sys.argv.index("--host") + 1] if "--host" in sys.argv else "mempool.space"
ext = int(sys.argv[sys.argv.index("--ext") + 1]) if "--ext" in sys.argv else 1000
net = ex["network"]
rows = {r["txid"]: r for f in glob.glob(f"{run}/out/{prefix}-history-*.json") for r in json.load(open(f)).get("rows") or []}
known = {t["txid"] for t in ex["txs"]}
scanned = {(v["branch"], v["index"]) for v in ex["addresses"].values()}
amap = explorer.extended_map(ex["xpub"], ext)
c = torget.Https(os.path.expanduser("~/btc-privacy-tests/tor/run/socks.sock"), host)


def fetch(txid):
    for n in range(40):  # exits fail often in front of mempool.space: new circuit, back off, again
        try:
            st, body = c.get(f"/{net}/api/tx/{txid}")
            if st == 200: return json.loads(body)
            if st == 404: return None
        except Exception as e:
            print(f"  retry {n + 1} {txid[:16]}: {e!r}"[:120], file=sys.stderr, flush=True)
        c.close(); c.circuit = None; time.sleep(min(30, 2 ** n))
    raise RuntimeError(f"gave up on {txid}")


out = {"prefix": prefix, "explorerTip": ex.get("tipAfter"), "ext": ext, "extra": [], "afterScan": [], "differences": []}
for txid, w in sorted(rows.items(), key=lambda kv: kv[1].get("height") or 0):
    if txid in known: continue
    t = fetch(txid)
    if t is None:
        out["differences"].append({"txid": txid, "kind": "not on the explorer", "wallet": [w["state"], w.get("height")]}); continue
    ins, outs = explorer.ours(t, amap)
    st = t["status"]
    e = {"txid": txid, "height": st.get("block_height"), "confirmed": st["confirmed"], "insExt": ins, "outsExt": outs,
         "netExt": sum(v for *_, v in outs) - sum(v for *_, v in ins), "wallet": [w["state"], w.get("height"), w["intent"], w["amountSat"]]}
    touched = {(b, i) for b, i, _ in ins + outs}
    if not touched:
        out["differences"].append(dict(e, kind=f"none of our first {ext} addresses per keychain")); continue
    if touched & scanned:
        out["differences"].append(dict(e, kind="touches an address the gap-limit scan covered, yet the scan lacks it")); continue
    if st["confirmed"] and (ex.get("tipAfter") or 0) < st["block_height"]:
        out["afterScan"].append(e); continue
    if st["confirmed"] != (w["state"] in ("confirmed", "unchecked")) or (st["confirmed"] and st["block_height"] != w.get("height")):
        out["differences"].append(dict(e, kind="past the gap, but at another height or state")); continue
    out["extra"].append(dict(e, lowestIndex=min(i for _, i in touched)))
out["extraNetSat"] = sum(e["netExt"] for e in out["extra"] if e["confirmed"])
json.dump(out, open(f"{run}/extras-{prefix}.json", "w"), indent=1)
print(json.dumps({"extra": len(out["extra"]), "afterScan": len(out["afterScan"]), "differences": len(out["differences"]),
                  "extraNetSat": out["extraNetSat"], "lowestExtraIndex": min((e["lowestIndex"] for e in out["extra"]), default=None)}))
for d in out["differences"]: print(f"  {d}")
