#!/usr/bin/env python3
# For each transaction the wallet lacks: which of our addresses (keychain/index) it touches, as input or output.
#   diag_missing.py <compare.json> <explorer.json> [--host H] -> per-tx lines and the lowest index touched
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torget

cmp, ex = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
run, prefix = os.path.dirname(os.path.abspath(sys.argv[1])), cmp["prefix"]
import glob
wallet = {r["txid"] for f in glob.glob(f"{run}/out/{prefix}-history-*.json") for r in json.load(open(f)).get("rows") or []}
exp_h = {r["txid"]: r["height"] for r in ex["txs"]}
host = sys.argv[sys.argv.index("--host") + 1] if "--host" in sys.argv else "mempool.space"
net = ex["network"]
idx = {a: (v["branch"], v["index"]) for a, v in ex["addresses"].items()}
c = torget.Https(os.path.expanduser("~/btc-privacy-tests/tor/run/socks.sock"), host)
rows = []
for d in cmp["differences"]:
    if d["kind"] != "missing in wallet": continue
    st, body = c.get(f"/{net}/api/tx/{d['txid']}")
    t = json.loads(body)
    ins = sorted({idx[i["prevout"]["scriptpubkey_address"]] for i in t["vin"] if (i.get("prevout") or {}).get("scriptpubkey_address") in idx})
    outs = sorted({idx[o["scriptpubkey_address"]] for o in t["vout"] if o.get("scriptpubkey_address") in idx})
    low = min(i for _, i in ins + outs)
    # Parents of our inputs: is each funding transaction in the wallet's history?
    parents = sorted({(i["txid"], exp_h.get(i["txid"]), i["txid"] in wallet) for i in t["vin"] if (i.get("prevout") or {}).get("scriptpubkey_address") in idx}, key=lambda p: p[1] or 0)
    rows.append((d["txid"], d["explorer"]["height"], d["explorer"]["netSat"], ins, outs, low, parents))
    pz = " ".join(f"{p[0][:8]}@{p[1]}:{'in-wallet' if p[2] else 'MISSING'}" for p in parents)
    print(f"{d['txid'][:16]} h={d['explorer']['height']} net={d['explorer']['netSat']} in={ins} out={outs} lowest-index={low} parents: {pz}")
spends = [r for r in rows if r[6]]
print(f"missing {len(rows)}; touching only indices >= 25: {sum(1 for r in rows if r[5] >= 25)}; touching an index < 25: {sum(1 for r in rows if r[5] < 25)}")
print(f"missing spends {len(spends)}: all parents in the wallet {sum(1 for r in spends if all(p[2] for p in r[6]))}; a parent missing {sum(1 for r in spends if not all(p[2] for p in r[6]))}")
