#!/usr/bin/env python3
# The wallet's snapshot against the explorer's view, at the wallet's authority height; every difference by txid.
#   compare.py <run-dir> <snapshot prefix> <explorer.json>
import glob, json, sys

RUN, P, EXP = sys.argv[1], sys.argv[2], sys.argv[3]
load = lambda n: json.load(open(f"{RUN}/out/{P}-{n}.json"))
st, bal, ex = load("core-status"), load("core-balance"), json.load(open(EXP))
rows = [r for f in sorted(glob.glob(f"{RUN}/out/{P}-history-*.json"), key=lambda f: int(f.rsplit("-", 1)[1][:-5])) for r in json.load(open(f)).get("rows", [])]
H = (st.get("authority") or {}).get("height") or 0
wallet = {r["txid"]: r for r in rows}
explorer = {r["txid"]: r for r in ex.get("txs", [])}


def expected(e):
    """The row the core's classifier should show for the explorer's tx: (intent, amount)."""
    if not e["spendsOurs"]: return "receive", e["recvSat"]
    if e["foreignInputs"]: return ("receive", e["recvSat"]) if e["recvSat"] > e["paidForeignSat"] else ("send", e["paidForeignSat"])
    if e["paidForeignSat"]: return "send", e["paidForeignSat"]
    return "self", None


diffs, matched = [], 0
for txid, e in explorer.items():
    w = wallet.get(txid)
    if e["confirmed"] and e["height"] <= H:
        if not w: diffs.append({"txid": txid, "kind": "missing in wallet", "explorer": {"height": e["height"], "netSat": e["netSat"]}}); continue
        if w["state"] != "confirmed" or w["height"] != e["height"]:
            diffs.append({"txid": txid, "kind": "state/height", "wallet": [w["state"], w["height"]], "explorer": ["confirmed", e["height"]]}); continue
        intent, amount = expected(e)
        bad = []
        if str(e["feeSat"]) != str(w.get("feeSat")) and e["spendsOurs"]: bad.append(f"fee {w.get('feeSat')} vs {e['feeSat']}")
        if amount is not None and str(amount) != str(w["amountSat"]): bad.append(f"amount {w['amountSat']} vs {amount}")
        if intent != "self" and w["intent"] not in (intent, "fee_bump"): bad.append(f"intent {w['intent']} vs {intent}")
        if bad: diffs.append({"txid": txid, "kind": "row", "detail": bad}); continue
        matched += 1
    elif w and w["state"] == "confirmed":
        diffs.append({"txid": txid, "kind": "confirmed in wallet, not at or below its height in explorer", "wallet": w["height"], "explorer": e["height"]})
for txid, w in wallet.items():
    if txid not in explorer: diffs.append({"txid": txid, "kind": "in wallet only", "wallet": [w["state"], w["height"], w["intent"], w["amountSat"]]})

after = [e for e in explorer.values() if not e["confirmed"] or e["height"] > H]
exp_conf = sum(e["netSat"] for e in explorer.values() if e["confirmed"] and e["height"] <= H)
res = {"prefix": P, "authorityHeight": H, "authorityKind": (st.get("authority") or {}).get("kind"), "walletRows": len(wallet),
       "explorerTxs": len(explorer), "explorerAtOrBelowH": len(explorer) - len(after), "matched": matched, "differences": diffs,
       "explorerAfterSnapshot": [{"txid": e["txid"], "height": e["height"], "netSat": e["netSat"]} for e in after],
       "balance": {"walletConfirmed": bal.get("confirmed"), "walletWaiting": bal.get("waiting"), "walletPending": bal.get("pending"),
                   "walletImmature": bal.get("immature"), "explorerConfirmedAtH": exp_conf, "explorerConfirmedNow": ex["balance"]["confirmed"],
                   "explorerMempool": ex["balance"]["mempool"]},
       "explorerTip": ex.get("tipAfter"), "usedAddresses": sum(1 for v in ex["addresses"].values() if v["chain"]["tx_count"] + v["mempool"]["tx_count"])}
res["balance"]["match"] = str(res["balance"]["walletConfirmed"]) == str(exp_conf)
json.dump(res, open(f"{RUN}/compare-{P}.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ("differences", "explorerAfterSnapshot")}))
print(f"differences: {len(diffs)}")
for d in diffs[:40]: print(f"  {d}")
print(f"explorer txs after the wallet's height (not compared): {len(after)}")
