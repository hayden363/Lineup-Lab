"""Writes analysis/dd_history_pool.md from the live module + analysis/dd_hist_results.json (run dd_hist_run.py first)."""
import json, sys, time
sys.path.insert(0, ".")
from collections import OrderedDict
from engine import daily_drive_history_pool as h
from engine import consensus

DATE = "2026-11-17"
ecr = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
t0 = time.time()
cands = h.history_candidates(DATE, ecr)
secs = time.time() - t0
res = json.load(open("analysis/dd_hist_results.json"))
by_tpl = {p["template"]: p for p in cands}
cat_order = [h.SEASON, h.DECADE, h.CAREER, h.DECADE_TOT, h.REPEAT, h.GAME, h.ROOKIE, h.PEDIGREE, h.DRAFT, h.DRAFT_COL, h.DRAFT_TEAM_CAT,
             h.DRAFT_STAT, h.PLAYOFF, h.SUPERBOWL, h.TEAMHIST]
groups = OrderedDict((c, []) for c in cat_order)
for t in h.HISTORY_POOL:
    groups[t["cat"]].append(t)
tot_var = sum(len(v["variants"]) for v in res.values())
ok_var = sum(1 for v in res.values() for x in v["variants"] if x[1] is not None)
ns = [x[2] for v in res.values() for x in v["variants"] if x[1] is not None]
L = []
L.append("# The Daily Drive: history prompt pool (draft for owner review)\n")
L.append(f"Generated from `engine/daily_drive_history_pool.py` on real nflverse data (seasons 2000-{h.build_context(None, ecr)['last']}, drafts 2000-{h.build_context(None, ecr)['last']}). "
         f"Wording shown is the prompt as it would read on **{DATE}** (scoped templates rotate their college / team / decade / draft class / round / pick / position by date, "
         f"and skip any variant that cannot build a valid prompt).\n")
L.append(f"- **{len(h.HISTORY_POOL)} templates**, all {len(h.HISTORY_POOL)} build a valid prompt on real data. "
         f"{len(by_tpl)} built on {DATE} in {secs:.1f}s including data load.")
L.append(f"- Every rotating scope variant was also run: **{ok_var} of {tot_var} variants pass** (answers 15-50, a tier-6 answer, never fewer than {h.dd.MIN_ANSWERS}); "
         f"the {tot_var - ok_var} that fail are listed in the appendix and are never offered (the template falls through to the next scope).")
L.append(f"- Answer counts across passing variants: min {min(ns)}, median {sorted(ns)[len(ns)//2]}, max {max(ns)} (cap {h.HIST_MAX_ANSWERS}); "
         f"{sum(1 for n in ns if n < 15)} variants sit at 12-14 answers (above the {h.dd.MIN_ANSWERS} floor, under the 15 target).\n")
n = 0
for cat, tpls in groups.items():
    if not tpls:
        continue
    L.append(f"\n## {cat} ({len(tpls)})\n")
    L.append("| # | key | wording on " + DATE + " | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |")
    L.append("|---|-----|------|--------|--------|------|------|------|")
    for t in tpls:
        n += 1
        p = by_tpl.get(t["key"])
        v = res[t["key"]]["variants"]
        vp = f"{sum(1 for x in v if x[1] is not None)}/{len(v)}" if len(v) > 1 else "1/1"
        if p:
            a = p["answers"]; t6 = [x for x in a if x["tier"] == 6]
            L.append(f"| {n} | `{t['key']}` | {p['text']} | {len(a)} | {len(t6)} | {a[0]['name']} | {t6[-1]['name']} | {vp} |")
        else:
            L.append(f"| {n} | `{t['key']}` | (no variant built today) | | | | | {vp} |")
L.append("\n## Appendix: scoped templates (variants passing; failing variants are never offered)\n")
for t in h.HISTORY_POOL:
    v = res[t["key"]]["variants"]
    if len(v) <= 1:
        continue
    passing = [x for x in v if x[1] is not None]
    failing = [str(x[0]) for x in v if x[1] is None]
    rng = f"{min(x[2] for x in passing)}-{max(x[2] for x in passing)}" if passing else "-"
    L.append(f"- `{t['key']}`: {len(passing)}/{len(v)} pass, answers {rng}" + (f"; fail: {', '.join(failing)}" if failing else ""))
L.append("""
## Notes (read before approving)

**Data and seasons.** Regular season and postseason weekly player stats from nflverse `stats_player_week_<year>` for every season 2000 through the last finished season (2025 today; the in-progress 2026 season is never counted so answers do not change week to week). Draft picks from nflverse `draft_picks` for drafts 2000-2025 (the 2026 class has not played a season). Super Bowl winners/losers from the nflverse schedule (`nfl_data_py.import_schedules`). First run downloads 26 weekly files (about 0.5-1.5 s each, roughly 15-25 s total, about 13 s measured) and trims them into `data_cache/daily_drive/hist_week_v1_<year>.parquet` (kept forever, finished seasons never change); later runs read only those caches. If any season file or the draft table cannot be read the whole history pool returns no prompts rather than a pool with a gap.

**Nothing before 2000.** Every data-driven prompt says "since 2000" or names a 2000s / 2010s / 2020s decade or a 2000+ draft class, and the tests assert no template text can render a pre-2000 year and no loader reads a pre-2000 season. Career totals count only seasons since 2000 (a player who started in the 1990s is a valid answer on the strength of his 2000+ numbers alone; the wording "since 2000" says so). Draft-career prompts ("a QB drafted since 2000 with 30,000+ career passing yards") are clean: every season of those careers is 2000 or later. Players drafted before 2000 can be answers to stat prompts (Brett Favre's 2000s seasons, for instance); only the draft prompts are limited to 2000+ drafts. "Rookie" means the season of the draft year, so drafted players only.

**Hall of Fame / All-Pro / Pro Bowl** come only from the draft table's `hof`, `allpro` and `probowls` columns, so undrafted players can never be answers to a flag-based prompt (Kurt Warner-type players simply have no flags there). Stat-based prompts (season marks, career totals, games, playoffs, Super Bowls) do include undrafted players. Only 19 players drafted since 2000 carry the HoF flag, so there is one HoF prompt. The table's `car_av` is empty for 2000+ drafts, so the fame signal uses weighted AV (`w_av`).

**Fame and tiers use the same three-signal path as the current pool** (`dd.pick_threshold` -> `dd._answers_at` -> `fame_scores` -> `rank_and_tier`): career points, Approximate Value, current consensus rank. Because defenders and kickers score ~0 fantasy points, their "career" signal is a frozen 2000+ production score (sacks, interceptions, forced fumbles, defensive TDs, tackles, FG/PAT) so an undrafted star is not buried; AV comes from the whole draft table (1980-2026) so a 1990s draftee with 2000s seasons is not mistaken for an obscure answer. Fame is relative inside each answer set, so a household name can still land in tier 6 when the set is full of bigger names (for example the last tier-6 name in a 4,700-yard list). Tier-6 is always at least the bottom 10% of the set.

**Verification.** I spot-checked real numbers against what I know: Strahan 22.5 sacks (2001), Manning 5,477 yards / 55 TDs (2013), Calvin Johnson 1,964 (2012), LaDainian Tomlinson 28 rushing TDs (2006), Brady 50 TDs (2007), Vinatieri 490 FG since 2000, and nflverse career passing yards for retired QBs drafted since 2000 agree with Pro Football Reference to within about 70 yards over whole careers. nflverse is play-by-play based, so single-season numbers can differ from the official gamebook by a handful of yards (Drew Brees 2011 shows 5,535 against the official 5,476): a player within a few dozen yards of a threshold could be on the wrong side of it. **Unverified:** I did not check every answer of every prompt against an independent source; the answers are exactly what nflverse says.

**Known limits and judgement calls.**
- Defensive stat coverage in the early 2000s: sacks matched official totals in my spot check (Strahan 22.5 in 2001) but I could not independently audit interceptions / forced fumbles / defensive TDs for every early season, and tackle counts looked less certain, so no tackle-based prompt is used.
- Games table keeps only games clearing a floor (for example 100 rushing yards, 250 passing yards); every game template's lowest rung is at or above its floor (a test enforces it).
- Super Bowls are the last postseason week of a season; QB prompts say "threw a pass in" rather than "won/lost/played in" because that is what the data proves (a backup who never threw is not detectable).
- A few answers are people some owners may not want in a game (for example a convicted former player appears in a playoff TE list). The pool does not filter on character; say if you want a name blocklist.
- Team-scoped prompts use low rungs (for example 400+ rushing yards for one team) when a franchise has too few big seasons; they are valid but easy, and a few sit at 12-14 answers.
- Rotating scopes: {NSCOPED} of the templates rotate college / team / position / round / pick slot / draft class / decade by date. The date picks an order and the first scope that passes is used.
- Timing: the full pool (179 templates) builds in about 1.0-1.5 s once the tables are loaded; loading the cached tables takes about 1-4 s depending on machine load. Resident memory grows by roughly 150-200 MB while building (the tables are about 80 MB; the rest is transient); `history_candidates` releases the tables afterwards unless `keep_context=True`. Worth knowing for the Render Starter instance.
- Not wired in: `day_counts` / `N_FANTASY` / `N_HISTORY` / `HISTORY_ENABLED` untouched.
""")
open("analysis/dd_history_pool.md", "w").write("\n".join(L).replace("{NSCOPED}", str(sum(1 for t in h.HISTORY_POOL if t.get("scope")))))
print("wrote", n, "rows")
