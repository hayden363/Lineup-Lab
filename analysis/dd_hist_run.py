"""Run every history template (and every scope variant) on real data. Usage: python analysis/dd_hist_run.py [key-prefix ...]"""
import sys, time, json
sys.path.insert(0, ".")
import pandas as pd
from engine import daily_drive_history_pool as h
from engine import consensus

t0 = time.time()
ecr = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
ctx = h._prepare_ctx(h.build_context(None, ecr))
print(f"ctx {time.time()-t0:.1f}s last={ctx['last']}", file=sys.stderr)
pref = sys.argv[1:]
rows = []
OUT = {}
for tpl in h.HISTORY_POOL:
    if pref and not any(tpl["key"].startswith(p) for p in pref):
        continue
    scopes = h.scope_options(tpl, ctx['last']) or [None]
    res = []
    for sc in scopes:
        try:
            p = h.build_history_prompt(tpl, ctx, sc)
        except Exception as e:
            p = None; print("ERR", tpl["key"], sc, repr(e), file=sys.stderr)
        if p:
            a = p["answers"]
            t6 = [x for x in a if x["tier"] == 6]
            res.append((sc, p["threshold"], len(a), len(t6), a[0]["name"], t6[-1]["name"], p["text"]))
        else:
            res.append((sc, None, 0, 0, "", "", ""))
    ok = [r for r in res if r[1] is not None]
    OUT[tpl["key"]] = {"cat": tpl["cat"], "variants": [list(x) for x in res]}
    print(f"{tpl['key']:<16} {len(ok)}/{len(res)}")
    for r in res:
        if len(res) == 1 or True:
            print(f"    {str(r[0]):<14} t={r[1]} n={r[2]} t6={r[3]} | {r[4]} | {r[5]} | {r[6]}")
print(f"total {time.time()-t0:.1f}s", file=sys.stderr)
if not pref:
    json.dump(OUT, open("analysis/dd_hist_results.json", "w"), indent=1)
