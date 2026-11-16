"""
THE DAILY DRIVE — a daily football trivia game built on real nflverse data
===========================================================================
Seven prompts a day ("Name a RB who scored a rushing TD in Week 10"). Every prompt's answer set is COMPUTED from
nflverse tables the app already downloads, never typed in, so each accepted answer is correct by construction.

Pieces, all pure functions except the two `live_*` / `get_puzzle` helpers at the bottom:
  * prompt builders  — turn a DataFrame into {prompt, answer set}
  * rarity tiers     — rank an answer set by popularity, cut by percentile into 6 tiers
  * daily puzzle     — deterministic (seeded by the date) pick of 4 fantasy + 3 history prompts
  * answer matching  — full name / "F. Last" / last name, typo tolerance that depends on the tier
"""

import datetime as dt
import hashlib
import json
import os
import random
import re
import unicodedata

import pandas as pd

MIN_ANSWERS = 12          # a prompt is used only if at least this many answers exist
N_FANTASY, N_HISTORY = 4, 3

# tier -> (name, yards, share emoji). Rarer = harder to think of = more yards.
TIERS = {
    6: ("Hall of Famer", 100, "\U0001F3C6"),
    5: ("All-Pro", 85, "\U0001F7E3"),
    4: ("Pro Bowler", 60, "\U0001F535"),
    3: ("Starter", 30, "\U0001F7E2"),
    2: ("Rotation", 15, "\U0001F7E1"),
    1: ("Benchwarmer", 10, "⚪"),
}
# percentile of the popularity ranking (0 = most popular answer) at which each tier starts, from the
# easiest tier up: top 20% Benchwarmer, next 20% Rotation, next 20% Starter, next 15% Pro Bowler, next 15%
# All-Pro, last 10% Hall of Famer.
_TIER_STARTS = [(0, 1), (20, 2), (40, 3), (60, 4), (75, 5), (90, 6)]


# ----------------------------------------------------------------------------------------------- names
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name):
    """'Kenneth Walker III' -> 'kenneth walker'; "Ja'Marr Chase" -> 'jamarr chase'; 'D.J. Moore' -> 'dj moore'."""
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`’]", "", s.replace("-", " "))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in _SUFFIXES)


# ----------------------------------------------------------------------------------------------- tiers
def tier_for_rank(rank, n):
    """Tier of the answer at popularity rank `rank` (0 = most popular) in a set of `n`."""
    pct = rank * 100.0 / n
    tier = 1
    for start, t in _TIER_STARTS:
        if pct >= start:
            tier = t
    return tier


def rank_and_tier(rows):
    """rows: [(answer_id, display_name, sort_key)] where a LOWER sort_key means a more popular answer.
    Returns [{id, name, tier}] most popular first, one answer per distinct normalized name (the more popular
    player keeps the name when two players share it)."""
    seen, ordered = set(), []
    for aid, name, key in sorted(rows, key=lambda r: (r[2], r[1])):
        n = norm_name(name)
        if not n or n in seen:
            continue
        seen.add(n)
        ordered.append((aid, name))
    total = len(ordered)
    return [{"id": aid, "name": name, "tier": tier_for_rank(i, total)} for i, (aid, name) in enumerate(ordered)]


# ----------------------------------------------------------------------------------------------- fantasy prompts
# scope "week": one game week.  scope "season": totals through the latest finished week.
# stat "fpts" = the nflverse PPR column (the app's default scoring).
FANTASY_TEMPLATES = [
    dict(key="rb_rush_td", scope="week", pos=("RB",), stat="rushing_tds", min=1, text="Name a RB who scored a rushing TD"),
    dict(key="wr_100_rec", scope="week", pos=("WR",), stat="receiving_yards", min=100, text="Name a WR with 100+ receiving yards"),
    dict(key="qb_2_td", scope="week", pos=("QB",), stat="passing_tds", min=2, text="Name a QB who threw 2+ TD passes"),
    dict(key="any_20_ppr", scope="week", pos=("QB", "RB", "WR", "TE"), stat="fpts", min=20, text="Name a player who scored 20+ PPR points"),
    dict(key="te_rec_td", scope="week", pos=("TE",), stat="receiving_tds", min=1, text="Name a TE who caught a TD"),
    dict(key="rb_80_rush", scope="week", pos=("RB",), stat="rushing_yards", min=80, text="Name a RB with 80+ rushing yards"),
    dict(key="qb_250_pass", scope="week", pos=("QB",), stat="passing_yards", min=250, text="Name a QB with 250+ passing yards"),
    dict(key="wr_rec_td", scope="week", pos=("WR",), stat="receiving_tds", min=1, text="Name a WR who caught a TD"),
    dict(key="s_te_td", scope="season", pos=("TE",), stat="receiving_tds", min=1, text="Name a TE who caught a TD"),
    dict(key="s_rb_400", scope="season", pos=("RB",), stat="rushing_yards", min=400, text="Name a RB with 400+ rushing yards"),
    dict(key="s_wr_600", scope="season", pos=("WR",), stat="receiving_yards", min=600, text="Name a WR with 600+ receiving yards"),
    dict(key="s_qb_10_td", scope="season", pos=("QB",), stat="passing_tds", min=10, text="Name a QB with 10+ TD passes"),
]


def _with_fpts(wk):
    return wk.assign(fpts=wk["fantasy_points_ppr"]) if "fpts" not in wk.columns else wk


def build_fantasy_prompt(tpl, wk, season, week, ecr_rank=None):
    """One fantasy prompt from weekly stats `wk` (REG season rows only). `week` is the game week for a "week"
    template, or the latest finished week for a "season" template. `ecr_rank` maps normalize-name|POS ->
    FantasyPros consensus rank; a player the experts don't list counts as the least popular. Returns the
    prompt dict or None when the answer set is smaller than MIN_ANSWERS."""
    wk = _with_fpts(wk)
    wk = wk[wk["position"].isin(tpl["pos"])]
    if tpl["scope"] == "week":
        rows = wk[wk["week"] == week]
        when, cat = f"in Week {week}", f"Fantasy · Week {week}"
        per = rows.groupby("player_id", as_index=False).agg(
            name=("player_display_name", "first"), pos=("position", "first"), val=(tpl["stat"], "sum"))
    else:
        rows = wk[wk["week"] <= week]
        when, cat = f"this season (through Week {week})", f"Fantasy · {season} season"
        per = rows.groupby("player_id", as_index=False).agg(
            name=("player_display_name", "first"), pos=("position", "first"), val=(tpl["stat"], "sum"))
    tot = rows.groupby("player_id")["fpts"].sum()
    per = per[per["val"] >= tpl["min"]]
    if len(per) < MIN_ANSWERS:
        return None
    from engine.consensus import match_key
    ecr_rank = ecr_rank or {}
    keyed = []
    for r in per.itertuples(index=False):
        rank = ecr_rank.get(match_key(r.name, r.pos), 99999.0)
        keyed.append((r.player_id, r.name, (rank, -float(tot.get(r.player_id, 0.0)))))
    answers = rank_and_tier(keyed)
    if len(answers) < MIN_ANSWERS:
        return None
    scope_id = f"w{week}" if tpl["scope"] == "week" else f"s{week}"
    return {"id": f"f:{tpl['key']}:{season}:{scope_id}", "template": tpl["key"], "kind": "fantasy",
            "text": f"{tpl['text']} {when}", "category": cat, "answers": answers}


# ----------------------------------------------------------------------------------------------- history prompts
# Season-total templates: players with ANY finished season (1999+) at or above the line.
HISTORY_TEMPLATES = [
    dict(key="h_wr_1500", pos=("WR",), stat="receiving_yards", min=1500, text="Name a WR with 1,500+ receiving yards in a season since 1999"),
    dict(key="h_wr_1300", pos=("WR",), stat="receiving_yards", min=1300, text="Name a WR with 1,300+ receiving yards in a season since 1999"),
    dict(key="h_rb_1800", pos=("RB",), stat="rushing_yards", min=1800, text="Name a RB with 1,800+ rushing yards in a season since 1999"),
    dict(key="h_rb_1500", pos=("RB",), stat="rushing_yards", min=1500, text="Name a RB with 1,500+ rushing yards in a season since 1999"),
    dict(key="h_qb_4500", pos=("QB",), stat="passing_yards", min=4500, text="Name a QB with 4,500+ passing yards in a season since 1999"),
    dict(key="h_qb_35_td", pos=("QB",), stat="passing_tds", min=35, text="Name a QB who threw 35+ TD passes in a season since 1999"),
    dict(key="h_te_1000", pos=("TE",), stat="receiving_yards", min=1000, text="Name a TE with 1,000+ receiving yards in a season since 1999"),
    dict(key="h_rb_15_td", pos=("RB",), stat="rushing_tds", min=15, text="Name a RB with 15+ rushing TDs in a season since 1999"),
    dict(key="h_any_100_rec", pos=("RB", "WR", "TE"), stat="receptions", min=100, text="Name a player with 100+ catches in a season since 1999"),
    dict(key="h_wr_12_td", pos=("WR",), stat="receiving_tds", min=12, text="Name a WR with 12+ receiving TDs in a season since 1999"),
]
# Draft templates: (key, first draft year, round filter, positions or None, text)
DRAFT_TEMPLATES = [
    dict(key="d_first_overall", since=2000, rnd=None, pick=1, pos=None, text="Name a #1 overall NFL draft pick since 2000"),
    dict(key="d_qb_r1", since=2000, rnd=1, pick=None, pos=("QB",), text="Name a QB drafted in the first round since 2000"),
    dict(key="d_wr_r1", since=2005, rnd=1, pick=None, pos=("WR",), text="Name a WR drafted in the first round since 2005"),
    dict(key="d_rb_r1", since=2005, rnd=1, pick=None, pos=("RB",), text="Name a RB drafted in the first round since 2005"),
    dict(key="d_te_r1_2", since=2000, rnd=(1, 2), pick=None, pos=("TE",), text="Name a TE drafted in the first two rounds since 2000"),
]


def career_points(history, current_weekly=None):
    """{player_id: career PPR points} over the finished seasons, plus the in-progress season's weeks."""
    pts = history.groupby("player_id")["fantasy_points_ppr"].sum()
    if current_weekly is not None and len(current_weekly):
        pts = pts.add(current_weekly.groupby("player_id")["fantasy_points_ppr"].sum(), fill_value=0.0)
    return pts


# How famous a history answer is. One signal alone misleads: career PPR points (1999+ data only) make this
# year's star rookies and pre-1999 legends look obscure. So fame is the HIGHEST of three real signals, each on
# a 0-1 scale: career points percentile within the answer set, career Approximate Value percentile within the
# set (Pro Football Reference via nflverse draft data: whole careers, pre-1999 included, drafted players only),
# and today's FantasyPros consensus rank (rank 1 -> 1.0, rank ECR_FAME_SCALE or worse -> 0; current players).
ECR_FAME_SCALE = 300.0


def _pct_desc(values):
    """Within-set position on a 0-1 scale: 0 = the smallest value, 1.0 = the biggest (ties share). A set of one gets 1.0."""
    s = pd.Series([float(v) for v in values], dtype=float)
    n = len(s)
    return [1.0] * n if n <= 1 else list((s.rank(method="average") - 1) / (n - 1))


def fame_scores(career_vals, av_vals, ecr_ranks):
    """[fame 0-1] for parallel lists; av/ecr entries may be None (unknown counts as no fame from that signal)."""
    car = _pct_desc(career_vals)
    av_known = [v for v in av_vals if v is not None]
    av_pct = iter(_pct_desc(av_known)) if av_known else iter(())
    av = [next(av_pct) if v is not None else 0.0 for v in av_vals]
    ecr = [0.0 if r is None else max(0.0, 1.0 - min(float(r), ECR_FAME_SCALE) / ECR_FAME_SCALE) for r in ecr_ranks]
    return [max(c, a, e) for c, a, e in zip(car, av, ecr)]


def _famed_rows(ids, names, positions, career, av_by_id=None, ecr_rank=None):
    """rank_and_tier rows sorted by fame (most famous first), career points as the tie-break."""
    from engine.consensus import match_key
    av_by_id, ecr_rank = av_by_id or {}, ecr_rank or {}
    car = [float(career.get(i, 0.0)) for i in ids]
    fame = fame_scores(car, [av_by_id.get(i) for i in ids],
                       [ecr_rank.get(match_key(n, p)) for n, p in zip(names, positions)])
    return [(i, n, (-f, -c)) for i, n, f, c in zip(ids, names, fame, car)]


def build_history_prompt(tpl, history, career, av_by_id=None, ecr_rank=None):
    """Season-total prompt from the stacked season history; popularity = fame (see fame_scores)."""
    h = history[history["position"].isin(tpl["pos"]) & (history[tpl["stat"]] >= tpl["min"])]
    if h.empty:
        return None
    first = h.groupby("player_id", as_index=False).agg(name=("player_display_name", "first"), pos=("position", "first"))
    if len(first) < MIN_ANSWERS:
        return None
    rows = _famed_rows(list(first["player_id"]), list(first["name"]), list(first["pos"]), career, av_by_id, ecr_rank)
    answers = rank_and_tier(rows)
    if len(answers) < MIN_ANSWERS:
        return None
    return {"id": f"h:{tpl['key']}", "template": tpl["key"], "kind": "history", "text": tpl["text"],
            "category": "History · NFL seasons since 1999", "answers": answers}


def build_draft_prompt(tpl, picks, career, last_year, ecr_rank=None):
    """Draft-pick prompt; popularity = fame (career PPR, career Approximate Value, current consensus rank)."""
    p = picks[(picks["season"] >= tpl["since"]) & (picks["season"] <= last_year)]
    if tpl["rnd"] is not None:
        rounds = tpl["rnd"] if isinstance(tpl["rnd"], tuple) else (tpl["rnd"],)
        p = p[p["round"].isin(rounds)]
    if tpl["pick"] is not None:
        p = p[p["pick"] == tpl["pick"]]
    if tpl["pos"]:
        p = p[p["position"].isin(tpl["pos"])]
    p = p[p["pfr_player_name"].notna()]
    if len(p) < MIN_ANSWERS:
        return None
    ids, names, positions, av_by_id = [], [], [], {}
    for r in p.itertuples(index=False):
        gid = r.gsis_id if isinstance(r.gsis_id, str) else f"pfr:{r.pfr_player_id}"
        ids.append(gid); names.append(r.pfr_player_name); positions.append(r.position)
        av_by_id[gid] = float(r.car_av) if pd.notna(r.car_av) else 0.0
    answers = rank_and_tier(_famed_rows(ids, names, positions, career, av_by_id, ecr_rank))
    if len(answers) < MIN_ANSWERS:
        return None
    return {"id": f"d:{tpl['key']}", "template": tpl["key"], "kind": "history", "text": tpl["text"],
            "category": "History · NFL Draft", "answers": answers}


# ----------------------------------------------------------------------------------------------- daily puzzle
def _seed(date_str):
    return int(hashlib.sha256(f"daily-drive:{date_str}".encode()).hexdigest()[:12], 16)


def pick_day(date_str, candidates, recent_ids=()):
    """The same 7 prompts for the same date, every time: 4 fantasy + 3 history from `candidates` (prompt dicts),
    no template twice, no id in `recent_ids` unless the pool runs dry. Returned in a seeded shuffled order."""
    rng = random.Random(_seed(date_str))
    recent = set(recent_ids)
    out = []
    for kind, n in (("fantasy", N_FANTASY), ("history", N_HISTORY)):
        pool = sorted((c for c in candidates if c["kind"] == kind and len(c["answers"]) >= MIN_ANSWERS), key=lambda c: c["id"])
        rng.shuffle(pool)
        pool.sort(key=lambda c: c["id"] in recent)       # fresh prompts first; stable, so the shuffle still decides
        used_templates = set()
        for c in pool:
            if c["template"] in used_templates:
                continue
            used_templates.add(c["template"])
            out.append(c)
            if len(used_templates) == n:
                break
    rng.shuffle(out)
    return out


def public_view(prompt):
    """What the browser may see before the game ends: no answers, only how many there are."""
    return {"id": prompt["id"], "text": prompt["text"], "category": prompt["category"], "count": len(prompt["answers"])}


# ----------------------------------------------------------------------------------------------- matching
def levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def check_answer(answers, typed, used=()):
    """Judge one typed answer against a prompt's answer set (`[{id, name, tier}]`).

    Order: exact full name -> "F. Last" -> last name alone (only if it names exactly one answer; two or more is
    ambiguous and returns suggestions) -> typo within Levenshtein 2 (1 for names under 6 letters). A typo may
    auto-accept only tiers 1-4; All-Pro / Hall of Famer need an exact name or alias, otherwise the correction is
    offered as a suggestion. Each answer counts once (`used` = ids already accepted).

    Returns {"ok": True, "answer": {id, name, tier}} or {"ok": False, "reason": str, "suggestions": [names]}."""
    t = norm_name(typed)
    if not t:
        return {"ok": False, "reason": "type a player's name", "suggestions": []}
    used = set(used)
    by_full, by_last, by_initial = {}, {}, {}
    for a in answers:
        n = norm_name(a["name"])
        by_full[n] = a
        toks = n.split()
        by_last.setdefault(toks[-1], []).append(a)
        by_initial.setdefault(toks[0][0] + " " + toks[-1], []).append(a)

    def hit(a):
        if a["id"] in used:
            return {"ok": False, "reason": "already used", "suggestions": []}
        return {"ok": True, "answer": a}

    if t in by_full:
        return hit(by_full[t])
    toks = t.split()
    for pool in ((by_initial.get(toks[0][0] + " " + toks[-1], []) if len(toks) >= 2 and len(toks[0]) == 1 else []),
                 (by_last.get(t, []) if len(toks) == 1 else [])):
        if len(pool) == 1:
            return hit(pool[0])
        if len(pool) > 1:
            return {"ok": False, "reason": "more than one answer fits - which one?",
                    "suggestions": [a["name"] for a in sorted(pool, key=lambda a: -a["tier"])[:4]]}
    # typo tolerance
    limit = 1 if len(t) < 6 else 2
    best = sorted(((levenshtein(t, n), n) for n in by_full), key=lambda x: x[0])
    near = [by_full[n] for d, n in best if d <= limit]
    if len(near) == 1 or (near and best[0][0] < best[1][0]):
        a = near[0]
        if a["tier"] >= 5:
            return {"ok": False, "reason": "close, but check the spelling", "suggestions": [a["name"]]}
        return hit(a)
    if len(near) > 1:
        return {"ok": False, "reason": "more than one answer fits - which one?", "suggestions": [a["name"] for a in near[:4]]}
    return {"ok": False, "reason": "not in the answer bank", "suggestions": []}


def tier_info(tier):
    name, yards, emoji = TIERS[tier]
    return {"tier": tier, "tier_name": name, "yards": yards, "emoji": emoji}


def reveal_view(prompt):
    """Full tiered answer list (most popular first inside each tier), highest tier first. Only after the game."""
    tiers = []
    for t in sorted(TIERS, reverse=True):
        tiers.append({**tier_info(t), "answers": [a["name"] for a in prompt["answers"] if a["tier"] == t]})
    return {"id": prompt["id"], "text": prompt["text"], "tiers": tiers}


def share_text(date_str, tiers, base_url="lineup-lab-awdv.onrender.com"):
    """Spoiler-free share card. `tiers` = per-prompt tier numbers, 0 for Sacked."""
    d = dt.date.fromisoformat(date_str)
    yards = sum(TIERS[t][1] for t in tiers if t)
    squares = "".join(TIERS[t][2] if t else "\U0001F7E5" for t in tiers)
    return f"The Daily Drive · {d.strftime('%b')} {d.day} · {yards} yds\n{squares}\n{base_url}/play"


# ----------------------------------------------------------------------------------------------- dates
ARCHIVE_DAYS = 60         # oldest past date the API will generate (stops arbitrary dates filling the disk)


def today_et(now=None):
    """Today's date in US Eastern: the Daily Drive's day rolls over at midnight there."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:                                    # no tz database: Eastern standard time, off by an hour in summer
        tz = dt.timezone(dt.timedelta(hours=-5))
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz).date()


# ----------------------------------------------------------------------------------------------- live data
def eligible_weeks(schedule, before_date):
    """Regular-season weeks whose every game finished (has a score) and was played before `before_date`."""
    s = schedule[schedule["game_type"] == "REG"] if "game_type" in schedule.columns else schedule
    s = s.assign(day=pd.to_datetime(s["gameday"]).dt.date)
    ok = []
    for week, g in s.groupby("week"):
        if g["home_score"].notna().all() and g["day"].max() < before_date:
            ok.append(int(week))
    return sorted(ok)


def live_candidates(date_str):
    """Every buildable prompt for `date_str`, from the app's real data (network-cached via engine.data)."""
    from engine import consensus, data
    d = dt.date.fromisoformat(date_str)
    season = data.resolve_season()
    wk = sched = weeks = None
    for s in (season, season - 1):                       # fall back to last season if this one has < 3 finished weeks
        try:
            sched = data.load_schedule(s)
            weeks = eligible_weeks(sched, d)
            if len(weeks) >= 3:
                wk, season = data.load_weekly(s), s
                break
        except Exception as e:
            print(f"[daily_drive] season {s} unavailable: {e}")
    cands = []
    ecr_rank = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
    if wk is not None:
        wk = wk[wk["season_type"] == "REG"] if "season_type" in wk.columns else wk
        for tpl in FANTASY_TEMPLATES:
            for w in (weeks if tpl["scope"] == "week" else weeks[-1:]):
                p = build_fantasy_prompt(tpl, wk, season, w, ecr_rank)
                if p:
                    cands.append(p)
    try:
        current = data.resolve_season()
        history = data.load_season_history(current - 1)    # finished seasons only
        cur = data.load_weekly(current)                    # the in-progress season still counts toward career points
        cur = cur[cur["season_type"] == "REG"] if "season_type" in cur.columns else cur
        career = career_points(history, cur)
        picks = data.load_draft_picks()
        av_by_id = {g: float(v) for g, v in zip(picks["gsis_id"], picks["car_av"]) if isinstance(g, str) and pd.notna(v)}
        for tpl in HISTORY_TEMPLATES:
            p = build_history_prompt(tpl, history, career, av_by_id, ecr_rank)
            if p:
                cands.append(p)
        for tpl in DRAFT_TEMPLATES:
            p = build_draft_prompt(tpl, picks, career, d.year, ecr_rank)
            if p:
                cands.append(p)
    except Exception as e:                               # fewer history prompts rather than invented ones
        print(f"[daily_drive] history data unavailable: {e}")
    return cands


def _puzzle_path(cache_dir, date_str):
    return os.path.join(cache_dir, f"puzzle_{date_str}.json")


def recent_prompt_ids(cache_dir, date_str, days=30):
    """Ids used by cached puzzles in the `days` before `date_str` (the no-repeat window)."""
    d = dt.date.fromisoformat(date_str)
    ids = set()
    for i in range(1, days + 1):
        path = _puzzle_path(cache_dir, (d - dt.timedelta(days=i)).isoformat())
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    ids.update(p["id"] for p in json.load(fh)["prompts"])
            except Exception:
                pass
    return ids


def get_puzzle(date_str, cache_dir, candidates_fn=live_candidates):
    """The day's puzzle {date, prompts:[full prompt dicts]}, from the disk cache or generated and cached."""
    path = _puzzle_path(cache_dir, date_str)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    prompts = pick_day(date_str, candidates_fn(date_str), recent_prompt_ids(cache_dir, date_str))
    puzzle = {"date": date_str, "prompts": prompts}
    if len(prompts) == N_FANTASY + N_HISTORY:           # never freeze a short day: it may just be missing data
        os.makedirs(cache_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(puzzle, fh)
        os.replace(tmp, path)
    return puzzle
