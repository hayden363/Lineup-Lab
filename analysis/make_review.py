import collections, json, sys
sys.path.insert(0, "analysis")
import run_pool as r
from engine import daily_drive_pool as pool

DATE = "2026-11-16"
ctx, ecr, fame = r.setup(2026, 10)
cands = {c["template"]: c for c in pool.pool_candidates(ctx, DATE, ecr, fame)}
D = {k: json.load(open(f"analysis/{f}")) for k, f in {"3": "r2025_w3.json", "5": "r2025_w5.json", "8": "r2025_w8.json"}.items()}
def frag(key):
    bad = [w for w in D if not all(D[w][key].values())]
    return ("early-season gaps at wk " + ",".join(bad)) if bad else ""
cats = collections.OrderedDict()
for t in pool.POOL: cats.setdefault(t["cat"], []).append(t)
lines = ["# The Daily Drive: 100-prompt pool for owner review", "",
         "Data: 2026 season through Week 10, scope variants as of 2026-11-16. Tier numbers: 1 = 10 yds (most obvious) ... 6 = 100 yds (rarest).",
         "Every prompt below passed the real tiering path (dd.pick_threshold): at least 12 answers (target 15+), at least one tier-6 answer.",
         "Scoped prompts rotate by date; all variants were also run. `*` = fragile early in a season (see fragility section).", "",
         "| # | Prompt (today's threshold) | Answers | Tier-6 | Obvious (tier 1) | Rare (tier 6) |", "|---|---|---|---|---|---|"]
n = 0
rows = []
for cat, tpls in cats.items():
    rows.append(f"| | **{cat}** | | | | |")
    for t in tpls:
        n += 1
        c = cands[t["key"]]
        a = c["answers"]
        t6 = sum(x["tier"] == 6 for x in a)
        t1 = next(x["name"] for x in a if x["tier"] == 1); r6 = next(x["name"] for x in a if x["tier"] == 6)
        star = "*" if frag(t["key"]) else ""
        rows.append(f"| {n} | {c['text']}{star} | {len(a)} | {t6} | {t1} | {r6} |")
lines += rows
assert n == 100
lines += ["", "## Fragile early in a season (2025 replayed at Weeks 3, 5, 8)", "",
          "The ladder walks down to its lowest rung when counts are thin, and the game already needs 3 finished weeks. These prompts still return nothing at one of the early weeks (the day picker just skips them, others fill in):", ""]
for t in pool.POOL:
    f = frag(t["key"])
    if f: lines.append(f"- `{t['key']}`: {f}")
lines += ["- `w_rb_td` (RB rushing TD last week) is also thin on a single-week window: it returned nothing for 2025 Week 12.", ""]
open("analysis/dd_prompts_100.md", "w").write("\n".join(lines))
json.dump({k: {"threshold": c["threshold"], "n": len(c["answers"])} for k, c in cands.items()}, open("analysis/today.json", "w"))
print(n, len(cands))
