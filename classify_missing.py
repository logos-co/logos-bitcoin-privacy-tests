#!/usr/bin/env python3
# Classifies what the wallet lacks, from an explorer scan with insOurs/outsOurs/parentsOurs: inside Kyoto's
# initial watch window (indices < W) or not, a watched output or not, parents held by the wallet or not.
#   classify_missing.py <run-dir> <prefix> <explorer.json> [W=25]
import collections, glob, json, sys

run, prefix, ex = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
W = int(sys.argv[4]) if len(sys.argv) > 4 else 25
wallet = {r["txid"] for f in glob.glob(f"{run}/out/{prefix}-history-*.json") for r in json.load(open(f)).get("rows") or []}
txs = {t["txid"]: t for t in ex["txs"]}
missing = [t for t in txs.values() if t["txid"] not in wallet and t["confirmed"]]
c, lines = collections.Counter(), []
for t in sorted(missing, key=lambda t: t["height"]):
    w_in, w_out = any(i < W for _, i in t["insOurs"]), any(i < W for _, i in t["outsOurs"])
    known = all(p in wallet for p in t["parentsOurs"])
    key = ("spend" if t["insOurs"] else "receive", "watched-input" if w_in else "-", "watched-output" if w_out else "no-watched-output",
           ("parents-known" if known else "parent-missing") if t["parentsOurs"] else "-")
    c[key] += 1
    lines.append(f"{t['txid']} h={t['height']} net={t['netSat']} in={t['insOurs']} out={t['outsOurs']} {' '.join(key)}")
print("\n".join(lines))
print(f"missing {len(missing)} of {len(txs)}")
for k, v in sorted(c.items()): print(f"  {v:4d} {' / '.join(k)}")
