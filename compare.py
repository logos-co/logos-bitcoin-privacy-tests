#!/usr/bin/env python3
# The wallet's snapshot against the explorer, at the wallet's authority height; every difference by txid.
#   compare.py <run-dir> <snapshot prefix> <explorer.json>   (folds in extras-<prefix>.json from extras.py)
import glob, json, os, sys

RUN, P, EXP = sys.argv[1], sys.argv[2], sys.argv[3]
load = lambda n: json.load(open(f"{RUN}/out/{P}-{n}.json"))
st, bal, ex = load("core-status"), load("core-balance"), json.load(open(EXP))
rows = [r for f in sorted(glob.glob(f"{RUN}/out/{P}-history-*.json"), key=lambda f: int(f.rsplit("-", 1)[1][:-5])) for r in json.load(open(f)).get("rows", [])]
xf = f"{RUN}/extras-{P}.json"
xs = json.load(open(xf)) if os.path.exists(xf) else {"extra": [], "afterScan": [], "differences": []}
H = (st.get("authority") or {}).get("height") or 0
win = (st.get("kyoto") or {}).get("window") or [None, None]
wallet = {r["txid"]: r for r in rows}
explorer = {r["txid"]: r for r in ex.get("txs", [])}
CONFIRMED = ("confirmed", "unchecked")


def expected(e):
    """The row the core's classifier should show for the explorer's tx: (intent, amount)."""
    if not e["spendsOurs"]: return "receive", e["recvSat"]
    if e["foreignInputs"]: return ("receive", e["recvSat"]) if e["recvSat"] > e["paidForeignSat"] else ("send", e["paidForeignSat"])
    if e["paidForeignSat"]: return "send", e["paidForeignSat"]
    return "self", None


def net_window(e):
    """What a tx moves for the wallet over the addresses its window watches (all of ours past the gap if unknown)."""
    if "outsExt" not in e: return e.get("netSat", e.get("netExt", 0))
    inside = lambda b, i: win[b] is None or i <= win[b]
    return sum(v for b, i, v in e["outsExt"] if inside(b, i)) - sum(v for b, i, v in e["insExt"] if inside(b, i))


diffs, matched, unchecked, via = [], 0, 0, 0
for txid, e in explorer.items():
    w = wallet.get(txid)
    if e["confirmed"] and e["height"] <= H:
        if not w: diffs.append({"txid": txid, "kind": "missing in wallet", "explorer": {"height": e["height"], "netSat": e["netSat"]}}); continue
        if w["state"] not in CONFIRMED or (w["height"] != e["height"] and not w.get("confirmedVia")):
            diffs.append({"txid": txid, "kind": "state/height", "wallet": [w["state"], w["height"], w.get("confirmedVia")], "explorer": ["confirmed", e["height"]]}); continue
        intent, amount = expected(e)
        bad = []
        if str(e["feeSat"]) != str(w.get("feeSat")) and e["spendsOurs"]: bad.append(f"fee {w.get('feeSat')} vs {e['feeSat']}")
        # A payment to an address past the gap counts in the wallet's amount, not in the gap-limited one.
        if amount is not None and str(amount) != str(w["amountSat"]):
            ext_amount = sum(v for b, i, v in e.get("outsExt", []) if win[b] is None or i <= win[b]) if intent == "receive" else None
            if str(ext_amount) != str(w["amountSat"]): bad.append(f"amount {w['amountSat']} vs {amount}")
        if intent != "self" and w["intent"] not in (intent, "fee_bump"): bad.append(f"intent {w['intent']} vs {intent}")
        if bad: diffs.append({"txid": txid, "kind": "row", "detail": bad}); continue
        matched += 1; unchecked += w["state"] == "unchecked"; via += bool(w.get("confirmedVia"))
    elif w and w["state"] in CONFIRMED:
        diffs.append({"txid": txid, "kind": "confirmed in wallet above the explorer's height", "wallet": w["height"], "explorer": e["height"]})
accounted = {e["txid"] for e in xs["extra"] + xs["afterScan"]}
for txid, w in wallet.items():
    if txid not in explorer and txid not in accounted and txid not in {d["txid"] for d in xs["differences"]}:
        diffs.append({"txid": txid, "kind": "in wallet only, not checked with extras.py", "wallet": [w["state"], w["height"], w["intent"], w["amountSat"]]})
diffs += [dict(d, kind="extra: " + d["kind"]) for d in xs["differences"]]

after = [e for e in explorer.values() if not e["confirmed"] or e["height"] > H]
gap_conf = sum(e["netSat"] for e in explorer.values() if e["confirmed"] and e["height"] <= H)
with_extras = sum(net_window(e) for e in explorer.values() if e["confirmed"] and e["height"] <= H) + \
    sum(net_window(e) for e in xs["extra"] if e["confirmed"] and e["height"] <= H)
wc = int(bal.get("confirmed") or 0) + int(bal.get("unchecked") or 0)
res = {"prefix": P, "authorityHeight": H, "authorityKind": (st.get("authority") or {}).get("kind"), "window": win, "walletRows": len(wallet),
       "explorerTxs": len(explorer), "explorerAtOrBelowH": len(explorer) - len(after), "matched": matched, "matchedUnchecked": unchecked,
       "matchedViaDescendant": via, "extraPastGap": len(xs["extra"]), "afterExplorerScan": len(xs["afterScan"]), "differences": diffs,
       "explorerAfterSnapshot": [{"txid": e["txid"], "height": e["height"], "netSat": e["netSat"]} for e in after],
       "balance": {"walletConfirmed": bal.get("confirmed"), "walletUnchecked": bal.get("unchecked"), "walletWaiting": bal.get("waiting"),
                   "walletPending": bal.get("pending"), "explorerGapLimitAtH": gap_conf, "explorerWithExtrasInWindowAtH": with_extras,
                   "explorerMempool": ex["balance"]["mempool"], "matchGapLimit": wc == gap_conf, "matchWithExtras": wc == with_extras},
       "explorerTip": ex.get("tipAfter"), "usedAddresses": sum(1 for v in ex["addresses"].values() if v["chain"]["tx_count"] + v["mempool"]["tx_count"])}
json.dump(res, open(f"{RUN}/compare-{P}.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ("differences", "explorerAfterSnapshot")}))
print(f"differences: {len(diffs)}")
for d in diffs: print(f"  {d}")
print(f"explorer txs after the wallet's height (not compared): {len(after)}")
