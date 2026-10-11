#!/usr/bin/env python3
# One line per wait_tip sample: state, authority, wallet tip, Kyoto's counters, the history server.
#   progress.py <progress.log> [last N]
import json, sys

lines = open(sys.argv[1]).read().splitlines()[-int(sys.argv[2]) if len(sys.argv) > 2 else 0:]
for l in lines:
    t, tip, js = l.split(" ", 2)
    try: v = json.loads(js)
    except ValueError: print(t, tip, "unreadable status"); continue
    k, a = v.get("kyoto") or {}, v.get("authority") or {}
    print(t, tip, v.get("state"), "synced" if v.get("synced") else "-", f"auth={a.get('kind')}:{a.get('height')}", f"wallet={v.get('walletTip')}",
          f"kyoto={k.get('phase')} hdr={k.get('headers')} prog={k.get('progress')} conn={k.get('connected')}/{k.get('dialled')} skip={k.get('skipped')} rs={k.get('restarts')} rb={k.get('rebuilds')}",
          f"hist={v.get('historyServer')}", f"warn={(k.get('lastWarning') or '')[:60]}", f"err={(v.get('lastError') or '')[:80]}")
