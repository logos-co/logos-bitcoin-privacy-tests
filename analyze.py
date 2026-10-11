#!/usr/bin/env python3
# Isolation checks for one run: the capture, the DNS log and strace, each attempt attributed to its process.
#   analyze.py <run-dir>   -> isolation.json, and a text summary on stdout
import collections, datetime, ipaddress, json, os, re, struct, sys

RUN = sys.argv[1]
CANARY = re.compile(r"^canary-.*\.invalid$")
# Our daemon's instance id names its sockets; any other id is another daemon's.
_cfg = f"{RUN}/session/client/config.yaml"
OWN = (re.search(r"instance_id: (\w+)", open(_cfg).read()) or [None, None])[1] if os.path.exists(_cfg) else None


def window():
    t = {}
    for line in open(f"{RUN}/cage/phases.log"):
        ts, _, what = line.strip().partition(" ")
        stamp = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc).timestamp()
        if what.startswith("session start"): t["start"] = stamp
        if what.startswith("session end"): t["end"] = stamp
    return t.get("start", 0), t.get("end", 1e12)


def loopback(a):
    try:
        ip = ipaddress.ip_address(a.split("%")[0])
        return ip.is_loopback or (ip.version == 6 and ip.ipv4_mapped is not None and ip.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def pcap(path, start, end):
    out = {"frames": 0, "bytes": 0, "sessionFrames": 0, "beforeSession": 0, "ifindex": collections.Counter(), "l3": collections.Counter(),
           "nonLoopback": [], "dnsFrames": [], "ports": collections.Counter()}
    with open(path, "rb") as f:
        gh = f.read(24)
        e = "<" if gh[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
        nano = gh[:4] in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
        link = struct.unpack(e + "I", gh[20:24])[0]
        out["linktype"] = link
        while len(ph := f.read(16)) == 16:
            s, us, incl, orig = struct.unpack(e + "IIII", ph)
            d, ts = f.read(incl), s + us / (1e9 if nano else 1e6)
            out["frames"] += 1; out["bytes"] += orig
            ifx = None
            if link == 276: proto, ifx, d3 = struct.unpack(">H", d[0:2])[0], struct.unpack(">I", d[4:8])[0], d[20:]
            elif link == 113: proto, d3 = struct.unpack(">H", d[14:16])[0], d[16:]
            elif link == 1: proto, d3 = struct.unpack(">H", d[12:14])[0], d[14:]
            else: proto, d3 = None, d
            out["ifindex"][str(ifx)] += 1
            if proto == 0x0800 and len(d3) >= 20:
                ihl, l4 = (d3[0] & 15) * 4, d3[9]
                src, dst, rest = str(ipaddress.ip_address(d3[12:16])), str(ipaddress.ip_address(d3[16:20])), d3[(d3[0] & 15) * 4:]
            elif proto == 0x86DD and len(d3) >= 40:
                l4, src, dst, rest = d3[6], str(ipaddress.ip_address(d3[8:24])), str(ipaddress.ip_address(d3[24:40])), d3[40:]
            else:
                out["l3"][f"other-{proto}"] += 1
                out["nonLoopback"].append({"t": ts, "proto": proto, "note": "not IP"})
                continue
            name = {6: "tcp", 17: "udp", 1: "icmp", 58: "icmp6"}.get(l4, str(l4))
            sp, dp = struct.unpack(">HH", rest[:4]) if l4 in (6, 17) and len(rest) >= 4 else (None, None)
            out["l3"][f"{'ipv4' if proto == 0x0800 else 'ipv6'}/{name}"] += 1
            if ts < start: out["beforeSession"] += 1
            elif ts <= end: out["sessionFrames"] += 1
            if not (loopback(src) and loopback(dst)):
                out["nonLoopback"].append({"t": ts, "src": src, "dst": dst, "proto": name, "sport": sp, "dport": dp})
            if 53 in (sp, dp) and start <= ts <= end:
                out["dnsFrames"].append({"t": ts, "src": src, "dst": dst, "sport": sp, "dport": dp})
            if sp is not None:
                out["ports"][f"{name}/{min(sp, dp) if 9050 not in (sp, dp) and 53 not in (sp, dp) else (9050 if 9050 in (sp, dp) else 53)}"] += 1
    out["ports"] = dict(out["ports"].most_common(12))
    return out


def dns(path, start, end):
    rows = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
    canaries = sorted({r["qname"] for r in rows if r["qname"] and CANARY.match(r["qname"])})
    session = [r for r in rows if not (r["qname"] and CANARY.match(r["qname"])) and r["t"] >= start - 1]
    return {"total": len(rows), "canariesSeen": canaries, "sessionQueries": session}


LINE = re.compile(r"^(\d+) (\d\d:\d\d:\d\d\.\d+) (.*)$")


def strace(path):
    parent, cmd, events = {}, {}, []
    for line in open(path, errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if not m: continue
        pid, ts, rest = int(m.group(1)), m.group(2), m.group(3)
        c = re.match(r"(?:<\.\.\. )?(clone3?|fork|vfork)\b.*\) += (\d+)", rest)
        if c: parent[int(c.group(2))] = pid; continue
        x = re.match(r'execve\("([^"]+)", \[(.*?)\]', rest)
        if x and "= -1" not in rest:
            args = re.findall(r'"((?:[^"\\]|\\.)*)"', x.group(2))
            base = os.path.basename(x.group(1)).lstrip(".").replace("-wrapped", "")
            if "--name" in args and args.index("--name") + 1 < len(args): name = "logos_host:" + args[args.index("--name") + 1]
            elif base == "logosctl":
                sub = [a for a in args[1:] if not a.startswith("-") and "/" not in a]
                name = "logosctl " + " ".join(sub[:3])
            else: name = base
            cmd[pid] = name
            continue
        s = re.match(r"(?:<\.\.\. )?(connect|sendto|sendmsg|sendmmsg)\b", rest)
        if not s or "resumed>" in rest[:40]: continue
        events.append((pid, ts, s.group(1), rest))

    def who(p):
        seen = 0
        while p not in cmd and p in parent and seen < 64: p, seen = parent[p], seen + 1
        return cmd.get(p, "?")

    res = {"counts": collections.Counter(), "nonLoopback": [], "dns": [], "unixPaths": collections.Counter(), "loopback": collections.Counter(),
           "connectedPeers": collections.Counter(), "netlink": collections.Counter()}
    for pid, ts, sc, rest in events:
        proc = who(pid)
        fam = re.search(r"sa_family=(AF_\w+)", rest)
        fam = fam.group(1) if fam else None
        dec = re.match(r"\w+\((\d+)<([^>]*)>", rest)
        result = rest.rsplit(" = ", 1)[1] if " = " in rest else "unfinished"
        res["counts"][f"{proc} {sc} {fam or 'no-addr'}"] += 1
        if fam == "AF_INET" or fam == "AF_INET6":
            a = re.search(r'inet_addr\("([^"]+)"\)', rest) or re.search(r'inet_pton\(AF_INET6, "([^"]+)"', rest)
            p = re.search(r"sin6?_port=htons\((\d+)\)", rest)
            addr, port = (a.group(1) if a else "?"), (int(p.group(1)) if p else None)
            ev = {"time": ts, "pid": pid, "process": proc, "syscall": sc, "addr": addr, "port": port, "result": result}
            if port == 53: res["dns"].append(ev)
            if loopback(addr): res["loopback"][f"{proc} -> {addr}:{port}"] += 1
            else: res["nonLoopback"].append(ev)
        elif fam == "AF_UNIX":
            u = re.search(r'sun_path=(@?)"([^"]*)"', rest)
            path = (u.group(1) + u.group(2)) if u else "?"
            res["unixPaths"][f"{proc} -> {path.replace(OWN, '<own>') if OWN else path}"] += 1
        elif fam == "AF_NETLINK":
            res["netlink"][proc] += 1
        elif fam is None and dec:
            peer = re.search(r"->\[?([0-9a-f.:]+?)\]?:(\d+)\]", dec.group(2))
            kind = dec.group(2).split(":")[0]
            if peer:
                res["connectedPeers"][f"{proc} {kind} -> {peer.group(1)}:{peer.group(2)}"] += 1
                if not loopback(peer.group(1)):
                    res["nonLoopback"].append({"time": ts, "pid": pid, "process": proc, "syscall": sc, "addr": peer.group(1), "port": int(peer.group(2)), "result": result, "via": "connected socket"})
                if peer.group(2) == "53": res["dns"].append({"time": ts, "pid": pid, "process": proc, "syscall": sc, "addr": peer.group(1), "port": 53, "result": result})
    for k in ("counts", "unixPaths", "loopback", "connectedPeers", "netlink"): res[k] = dict(res[k].most_common())
    res["events"] = len(events)
    return res


def main():
    start, end = window()
    out = {"window": {"start": start, "end": end, "seconds": round(end - start)}}
    out["pcap"] = pcap(f"{RUN}/capture.pcap", start, end)
    out["dns"] = dns(f"{RUN}/dns.jsonl", start, end)
    out["strace"] = strace(f"{RUN}/strace.log")
    out["canaryStrace"] = [l.strip() for l in open(f"{RUN}/cage/strace-canary.log") if "connect(" in l] if os.path.exists(f"{RUN}/cage/strace-canary.log") else []
    out["socatConnections"] = sum(1 for l in open(f"{RUN}/cage/socat.log") if "accepting connection" in l) if os.path.exists(f"{RUN}/cage/socat.log") else None
    out["netStart"] = open(f"{RUN}/cage/net-start.txt").read() if os.path.exists(f"{RUN}/cage/net-start.txt") else ""
    out["netEnd"] = open(f"{RUN}/cage/net-end.txt").read() if os.path.exists(f"{RUN}/cage/net-end.txt") else ""
    json.dump(out, open(f"{RUN}/isolation.json", "w"), indent=1, default=str)
    p, d, s = out["pcap"], out["dns"], out["strace"]
    nl = collections.Counter(f"{e['process']} {e['syscall']} {e['addr']}:{e['port']} {e['result'].split(' (')[0]}" for e in s["nonLoopback"])
    print(f"window {out['window']['seconds']} s; interfaces at start/end: {out['netStart'].splitlines()[:1]} / {out['netEnd'].splitlines()[:1]}")
    print(f"pcap: {p['frames']} frames, {p['bytes']} bytes, linktype {p['linktype']}, ifindex {dict(p['ifindex'])}, l3 {dict(p['l3'])}")
    print(f"pcap: non-loopback frames {len(p['nonLoopback'])}; DNS frames in the session {len(p['dnsFrames'])}; top ports {p['ports']}")
    print(f"dns log: canaries seen {d['canariesSeen']}; session queries {len(d['sessionQueries'])}")
    for q in d["sessionQueries"][:20]: print(f"  query {q}")
    print(f"strace: {s['events']} connect/send events; DNS attempts {len(s['dns'])}; non-loopback attempts {len(s['nonLoopback'])}")
    for k, v in nl.most_common(): print(f"  non-loopback x{v}: {k}")
    print(f"strace loopback destinations: {s['loopback']}")
    print(f"strace connected-socket peers: {dict(list(s['connectedPeers'].items())[:12])}")
    print(f"strace unix paths: {dict(list(s['unixPaths'].items())[:40])}")
    print(f"socat (Tor bridge) connections: {out['socatConnections']}; canary strace: {out['canaryStrace']}")


if __name__ == "__main__":
    main()
