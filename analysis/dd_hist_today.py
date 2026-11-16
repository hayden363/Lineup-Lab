import sys, time
sys.path.insert(0, ".")
from engine import daily_drive_history_pool as h
date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-17"
t0 = time.time()
cands = h.history_candidates(date)
print(f"{len(cands)} prompts in {time.time()-t0:.1f}s")
for i, p in enumerate(cands, 1):
    a = p["answers"]; t6 = [x for x in a if x["tier"] == 6]
    print(f"{i:3d} {p['cat']:<16} n={len(a):<3} t6={len(t6)} | {a[0]['name']} | {t6[-1]['name']} | {p['text']}")
