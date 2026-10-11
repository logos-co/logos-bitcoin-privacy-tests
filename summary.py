#!/usr/bin/env python3
# summary.txt for one run: isolation, the wallet's reads per network, explorer comparisons, Kyoto restarts.
#   summary.py <run-dir>
import collections, glob, json, os, statistics, sys

RUN = sys.argv[1]
J = lambda p: json.load(open(p)) if os.path.exists(p) else None
O = lambda n: J(f"{RUN}/out/{n}.json")
out = []
w = out.append

iso = J(f"{RUN}/isolation.json")
if iso:
    p, d, s = iso["pcap"], iso["dns"], iso["strace"]
    w(f"ISOLATION ({iso['window']['seconds']} s session; cage interfaces: {[l.split()[0] for l in iso['netStart'].splitlines() if l and not l.startswith(('127', '::'))][:3]})")
    w(f"  capture: {p['frames']} frames / {p['bytes']} bytes on ifindex {dict(p['ifindex'])}; {dict(p['l3'])}")
    w(f"  capture: non-loopback frames {len(p['nonLoopback'])}; DNS frames in session {len(p['dnsFrames'])}; ports {p['ports']}")
    w(f"  Tor streams (SOCKS5 in the capture): {p['socks']['streams']}, address types {p['socks']['byAddressType']}, unparsed {p['socks']['unparsed']}")
    for dst, n in p["socks"]["destinations"].items(): w(f"    x{n} {dst}")
    w(f"  DNS logger: session queries {len(d['sessionQueries'])}; canaries seen {d['canariesSeen']}")
    by = collections.Counter(e["process"] for e in s["nonLoopback"])
    w(f"  strace: {s['events']} connect/send events; DNS attempts {len(s['dns'])}; non-loopback attempts {len(s['nonLoopback'])} by process {dict(by)}")
    for (proc, addr, port, res), n in collections.Counter((e["process"], e["addr"], e["port"], e["result"].split(" (")[0]) for e in s["nonLoopback"]).most_common():
        w(f"    x{n} {proc} {addr}:{port} {res}")
    btc = {k: v for k, v in s["loopback"].items() if "bitcoin" in k}
    w(f"  Bitcoin modules' inet connects: {btc}")
    w(f"  Bitcoin modules' connected-socket peers: { {k: v for k, v in s['connectedPeers'].items() if 'bitcoin' in k} }")
    foreign = {k: v for k, v in s["unixPaths"].items() if "<own>" not in k}
    w(f"  Unix sockets outside our daemon's instance: {foreign or 'none'}")

for net, pre in (("signet, Kyoto alone", "sk"), ("signet after the restarts", "after-restarts"), ("signet with history servers", "ss"),
                 ("testnet4, defaults", "t4"), ("testnet4 with history servers", "t4s"), ("signet without a birthday, then set_birthday", "nb"),
                 ("signet", "signet"), ("testnet4 (shipped peer list)", "t4p")):
    st = O(f"{pre}-core-status")
    if not st: continue
    a, k = st.get("authority") or {}, st.get("kyoto") or {}
    b, fee, ra = O(f"{pre}-core-balance") or {}, O(f"{pre}-fee-rates") or {}, O(f"{pre}-receive-address") or {}
    rows = sum(len((J(f) or {}).get("rows") or []) for f in glob.glob(f"{RUN}/out/{pre}-history-*.json"))
    w(f"{net.upper()}: state {st.get('state')}, synced {st.get('synced')}, authority {a.get('kind')} {a.get('height')}, walletTip {st.get('walletTip')}, "
      f"birthday {st.get('birthday')} ({st.get('birthdaySource')}), rescanFrom {st.get('rescanFrom')}, kyoto {k.get('phase')} headers {k.get('headers')} "
      f"quorum {k.get('quorum')} onePeerDecides {k.get('onePeerDecides')} connected {k.get('connected')}/{k.get('dialled')} restarts {k.get('restarts')} "
      f"rebuilds {k.get('rebuilds')} rescans {k.get('rescans')} window {k.get('window')} lastConflict {k.get('lastConflict')}, "
      f"history server {st.get('historyServer')}, lastError {st.get('lastError')}")
    w(f"  balance: confirmed {b.get('confirmed')} unchecked {b.get('unchecked')} waiting {b.get('waiting')} pending {b.get('pending')} immature {b.get('immature')}; history rows {rows}; "
      f"receive_address {ra.get('address')} (index {ra.get('index')}); fee_rates {fee}")
    ex = O(f"{pre}-exposure"); w(f"  exposure: {ex}")
    for side in ("before", "after"):
        h = O(f"{pre}-{side}-node-health")
        if h: w(f"  node source_health ({side}): " + "; ".join(f"{x['id']}={x.get('state')} tip {x.get('tipHeight')} rtt {x.get('rttMs')} {('err ' + x['error'][:60]) if x.get('error') else ''}" for x in h.get("sources", [])))

for f in sorted(glob.glob(f"{RUN}/compare-*.json")):
    c = J(f)
    w(f"EXPLORER vs WALLET ({os.path.basename(f)}): authority {c['authorityKind']} {c['authorityHeight']}; explorer txs {c['explorerTxs']} ({c['explorerAtOrBelowH']} at or below), "
      f"wallet rows {c['walletRows']}, matched {c['matched']} (unchecked {c.get('matchedUnchecked')}, via a descendant {c.get('matchedViaDescendant')}), "
      f"extra past the gap {c.get('extraPastGap')}, after the explorer's scan {c.get('afterExplorerScan')}, differences {len(c['differences'])}; balance {c['balance']}")
    for dd in c["differences"]: w(f"    {dd}")
    if c["explorerAfterSnapshot"]: w(f"    after the wallet's height: {c['explorerAfterSnapshot']}")

rs = [json.loads(l) for l in open(f"{RUN}/out/restarts.jsonl")] if os.path.exists(f"{RUN}/out/restarts.jsonl") else []
if rs:
    ok = [r for r in rs if r["result"] == "tip"]
    w(f"KYOTO RESTARTS (close + reopen through the CLI, then until authority and wallet reach the servers' tip): {len(ok)} of {len(rs)} reached the tip")
    if ok: w(f"  sync after open: median {statistics.median(r['syncMs'] for r in ok) / 1000:.1f} s, max {max(r['syncMs'] for r in ok) / 1000:.1f} s; open approval median {statistics.median(r['openMs'] for r in ok) / 1000:.1f} s")
    for r in rs: w(f"  #{r['run']} {r['result']} open {r['openMs']} ms sync {r['syncMs']} ms tipBefore {r['tipBefore']} authority {(r.get('authority') or {}).get('height')} kyoto {r['kyoto']}")
if os.path.exists(f"{RUN}/out/timings.txt"): w("TIMINGS: " + " | ".join(open(f"{RUN}/out/timings.txt").read().splitlines()))
open(f"{RUN}/summary.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
