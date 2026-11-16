"""
THE DAILY DRIVE — a daily football trivia game built on real nflverse data
===========================================================================
Seven prompts a day ("Name a WR with 700+ receiving yards this season"). Every prompt's answer set is COMPUTED from
nflverse tables the app already downloads, never typed in, so each accepted answer is correct by construction.

Pieces, all pure functions except the two `live_*` / `get_puzzle` helpers at the bottom:
  * prompt builders  — turn a DataFrame into {prompt, answer set}
  * rarity tiers     — rank an answer set by popularity, cut by percentile into 6 tiers
  * daily puzzle     — deterministic (seeded by the date) pick of 7 season prompts (history/draft are behind HISTORY_ENABLED)
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
N_FANTASY, N_HISTORY = 4, 3     # the mix when HISTORY_ENABLED; otherwise the whole day is fantasy season prompts
HISTORY_ENABLED = False         # owner decision 2026-11-16: every prompt is about THIS season's stats. Flip to bring back history + draft
PUZZLE_VERSION = 2              # bump when the cached puzzle shape changes: older cached days are regenerated
TARGET_MIN, TARGET_MAX = 15, 50  # the answer count a threshold rung should land in (the hard floor stays MIN_ANSWERS)


def day_counts():
    """(fantasy, history) prompts in a day."""
    return (N_FANTASY, N_HISTORY) if HISTORY_ENABLED else (N_FANTASY + N_HISTORY, 0)


def day_size():
    return sum(day_counts())

# tier -> (name, yards, share emoji). Rarer = harder to think of = more yards.
# Owner's tier colors (2026-11-16), lowest to highest: grey, light blue, red, purple, yellow, gold. The share
# emoji follows the same colors.
TIERS = {
    6: ("Hall of Famer", 100, "\U0001F3C6"),   # gold trophy
    5: ("All-Pro", 85, "\U0001F7E1"),          # yellow
    4: ("Pro Bowler", 60, "\U0001F7E3"),       # purple
    3: ("Starter", 30, "\U0001F534"),          # red
    2: ("Rotation", 15, "\U0001F535"),         # (light) blue
    1: ("Benchwarmer", 10, "⚪"),               # grey/white
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
    for row in sorted(rows, key=lambda r: (r[2], r[1])):
        aid, name = row[0], row[1]
        n = norm_name(name)
        if not n or n in seen:
            continue
        seen.add(n)
        ordered.append((aid, name, row[3] if len(row) > 3 else {}))
    total = len(ordered)
    return [{"id": aid, "name": name, "tier": tier_for_rank(i, total), **extra} for i, (aid, name, extra) in enumerate(ordered)]


# ----------------------------------------------------------------------------------------------- fantasy prompts
# Every fantasy prompt is about the CURRENT season through the latest fully completed regular-season week.
#   per="season": the player's season total of `stat` is >= the threshold.
#   per="game":   the player's best single game of `stat` is >= the threshold.
# The threshold is NOT fixed: build_season_prompt walks the template's `ladder` (round numbers) from the top and uses
# the highest rung that still leaves at least TARGET_MIN answers, so the prompt keeps its difficulty as the season grows.
# stat "fpts" = nflverse fantasy_points_ppr (the app's default scoring); "tds" = rushing + receiving TDs.
_YDS = (300, 400, 500, 600, 700, 800, 1000, 1200, 1500)
FANTASY_TEMPLATES = [
    # season totals
    dict(key="wr_rec_yds", per="season", pos=("WR",), stat="receiving_yards", ladder=_YDS, label="rec yds",
         text="Name a WR with {t}+ receiving yards this season"),
    dict(key="te_rec_yds", per="season", pos=("TE",), stat="receiving_yards", ladder=(100, 150, 200, 250, 300, 400, 500, 600, 800), label="rec yds",
         text="Name a TE with {t}+ receiving yards this season"),
    dict(key="rb_rec_yds", group="rb_rec", per="season", pos=("RB",), stat="receiving_yards", ladder=(100, 150, 200, 250, 300, 400, 500, 600, 800), label="rec yds",
         text="Name a RB with {t}+ receiving yards this season"),
    dict(key="rb_rush_yds", per="season", pos=("RB",), stat="rushing_yards", ladder=(200, 300, 400, 500, 600, 700, 800, 1000, 1200, 1500), label="rush yds",
         text="Name a RB with {t}+ rushing yards this season"),
    dict(key="qb_pass_yds", per="season", pos=("QB",), stat="passing_yards", ladder=(1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500), label="pass yds",
         text="Name a QB with {t}+ passing yards this season"),
    dict(key="qb_pass_td", per="season", pos=("QB",), stat="passing_tds", ladder=(5, 8, 10, 12, 15, 18, 20, 22, 25, 28, 30, 35), label="pass TD",
         text="Name a QB with {t}+ passing TDs this season"),
    dict(key="wr_rec", per="season", pos=("WR",), stat="receptions", ladder=(20, 30, 40, 50, 60, 70, 80, 90, 100), label="rec",
         text="Name a WR with {t}+ receptions this season"),
    dict(key="any_total_td", per="season", pos=("RB", "WR", "TE"), stat="tds", ladder=(3, 4, 5, 6, 8, 10, 12, 15), label="total TD",
         text="Name a player with {t}+ total TDs (rushing + receiving) this season"),
    dict(key="any_ppr", per="season", pos=("QB", "RB", "WR", "TE"), stat="fpts", ladder=(50, 75, 100, 125, 150, 175, 200, 250, 300), label="PPR pts",
         text="Name a player with {t}+ PPR points this season"),
    dict(key="rb_rush_td", per="season", pos=("RB",), stat="rushing_tds", ladder=(2, 3, 4, 5, 6, 8, 10, 12), label="rush TD",
         text="Name a RB with {t}+ rushing TDs this season"),
    dict(key="rec_td", group="rec_td", per="season", pos=("WR", "TE"), stat="receiving_tds", ladder=(2, 3, 4, 5, 6, 8, 10, 12), label="rec TD",
         text="Name a WR or TE with {t}+ receiving TDs this season"),
    # single-game feats
    dict(key="wr_game_rec", per="game", pos=("WR",), stat="receiving_yards", ladder=(100, 125, 150, 175, 200), label="rec yds in a game",
         text="Name a WR with a {t}+ yard receiving game this season"),
    dict(key="rb_game_rush", per="game", pos=("RB",), stat="rushing_yards", ladder=(80, 100, 125, 150, 175, 200), label="rush yds in a game",
         text="Name a RB with a {t}+ yard rushing game this season"),
    dict(key="qb_game_pass", per="game", pos=("QB",), stat="passing_yards", ladder=(250, 300, 350, 400, 450), label="pass yds in a game",
         text="Name a QB with a {t}+ yard passing game this season"),
    dict(key="any_game_ppr", per="game", pos=("QB", "RB", "WR", "TE"), stat="fpts", ladder=(20, 25, 30, 35, 40, 50), label="PPR pts in a game",
         text="Name a player with a {t}+ PPR point game this season"),
    dict(key="any_game_td", per="game", pos=("QB", "RB", "WR", "TE"), stat="tds", ladder=(2, 3, 4), label="TD in a game",
         text="Name a player with {t}+ rushing/receiving TDs in one game this season"),
    dict(key="te_game_rec", per="game", pos=("TE",), stat="receiving_yards", ladder=(50, 75, 100, 125, 150), label="rec yds in a game",
         text="Name a TE with a {t}+ yard receiving game this season"),
    # mixed
    dict(key="rb_catches", group="rb_rec", per="season", pos=("RB",), stat="receptions", ladder=(10, 15, 20, 30, 40, 50, 60, 70), label="rec",
         text="Name a RB with {t}+ catches this season"),
    dict(key="wr_rec_td", group="rec_td", per="season", pos=("WR",), stat="receiving_tds", ladder=(2, 3, 4, 5, 6, 8, 10), label="rec TD",
         text="Name a WR with {t}+ receiving TDs this season"),
    dict(key="qb_rush_yds", per="season", pos=("QB",), stat="rushing_yards", ladder=(50, 75, 100, 150, 200, 250, 300, 400), label="rush yds",
         text="Name a QB with {t}+ rushing yards this season"),
]


def _prep(wk):
    """Adds the derived columns the templates use: fpts (PPR) and tds (rushing + receiving TDs)."""
    out = wk
    if "fpts" not in out.columns:
        out = out.assign(fpts=out["fantasy_points_ppr"])
    if "tds" not in out.columns:
        out = out.assign(tds=out["rushing_tds"].fillna(0) + out["receiving_tds"].fillna(0))
    return out


def _num(v):
    v = float(v)
    return int(v) if v == int(v) else round(v, 1)


def _season_players(tpl, wk, through):
    """One row per player with the value that counts toward the template (season total, or best single game)."""
    wk = _prep(wk)
    rows = wk[wk["position"].isin(tpl["pos"]) & (wk["week"] <= through)].sort_values("week")
    g = rows.groupby("player_id")
    per = g.agg(name=("player_display_name", "last"), pos=("position", "last"), team=("recent_team", "last"),
                headshot=("headshot_url", "last") if "headshot_url" in rows.columns else ("player_id", lambda s: None),
                val=(tpl["stat"], "max" if tpl["per"] == "game" else "sum"), ppr=("fpts", "sum")).reset_index()
    return per


def _answers_at(per, threshold, ecr_rank, label, fame=None):
    """Tiered answers at `threshold`. With `fame` = (career_points, av_by_id), popularity is the same three-signal
    fame score the history prompts use (career PPR, career Approximate Value, current consensus rank), so a star
    who is hurt or ranked low right now (Lamar Jackson, Jalen Hurts) is still an obvious answer. Without it,
    popularity is the consensus rank alone (unlisted = least popular), tie-broken by season PPR."""
    from engine.consensus import match_key
    ecr_rank = ecr_rank or {}
    q = per[per["val"] >= threshold]
    rows = list(q.itertuples(index=False))
    if fame is not None and rows:
        career, av_by_id = fame
        score = fame_scores([float(career.get(r.player_id, 0.0)) for r in rows],
                            [(av_by_id or {}).get(r.player_id) for r in rows],
                            [ecr_rank.get(match_key(r.name, r.pos)) for r in rows])
        keys = [(-f, -float(r.ppr)) for f, r in zip(score, rows)]
    else:
        keys = [(ecr_rank.get(match_key(r.name, r.pos), 99999.0), -float(r.ppr)) for r in rows]
    keyed = []
    for r, k in zip(rows, keys):
        head = r.headshot if isinstance(r.headshot, str) and r.headshot else None
        extra = {"team": r.team if isinstance(r.team, str) else None, "position": r.pos, "headshot": head,
                 "stat": _num(r.val), "stat_label": label}
        keyed.append((r.player_id, r.name, k, extra))
    return rank_and_tier(keyed)


def has_hall_of_famer(answers):
    """Owner rule: every prompt needs at least one tier-6 (Hall of Famer) answer."""
    return any(a["tier"] == 6 for a in answers)


def pick_threshold(per, ladder, ecr_rank, label, fame=None):
    """Highest ladder rung whose answer set still has at least TARGET_MIN players (so the prompt is as hard as the
    data allows while staying playable). Falls back to the highest rung with at least MIN_ANSWERS. Returns
    (threshold, answers) or (None, [])."""
    fallback = (None, [])
    for t in sorted(ladder, reverse=True):
        ans = _answers_at(per, t, ecr_rank, label, fame)
        if not has_hall_of_famer(ans):                 # too small a set to reach the top tier: step down the ladder
            continue
        if len(ans) >= TARGET_MIN:
            return t, ans
        if fallback[0] is None and len(ans) >= MIN_ANSWERS:
            fallback = (t, ans)
    return fallback


def build_season_prompt(tpl, wk, season, through, ecr_rank=None, fame=None):
    """One fantasy prompt about `season` through its latest finished regular-season week `through`. `wk` = that
    season's REG weekly rows. `ecr_rank` maps normalized-name|POS -> FantasyPros consensus rank; a player the
    experts don't list counts as the least popular (tie-break: season PPR points). Returns None when no ladder
    rung leaves MIN_ANSWERS answers."""
    per = _season_players(tpl, wk, through)
    t, answers = pick_threshold(per, tpl["ladder"], ecr_rank, tpl["label"], fame)
    if t is None:
        return None
    return {"id": f"f:{tpl['key']}:{season}:w{through}:t{t}", "template": tpl["key"], "kind": "fantasy",
            "text": tpl["text"].format(t=f"{t:,}"), "category": f"This season · through Week {through}", "answers": answers,
            "threshold": t, "group": tpl.get("group", tpl["key"])}


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


def pick_day(date_str, candidates, avoid_templates=()):
    """The same prompts for the same date, every time: day_counts() prompts per kind from `candidates` (prompt
    dicts), no template (or near-duplicate group) twice in a day, and none of `avoid_templates` (yesterday's) unless the pool runs dry.
    Returned in a seeded shuffled order."""
    rng = random.Random(_seed(date_str))
    avoid = set(avoid_templates)
    out = []
    for kind, n in zip(("fantasy", "history"), day_counts()):
        if n <= 0:
            continue
        pool = sorted((c for c in candidates if c["kind"] == kind and len(c["answers"]) >= MIN_ANSWERS and has_hall_of_famer(c["answers"])), key=lambda c: c["id"])
        rng.shuffle(pool)
        pool.sort(key=lambda c: c["template"] in avoid)   # fresh templates first; stable, so the shuffle still decides
        used = set()                                      # template groups: near-duplicates (WR rec TDs vs WR/TE rec TDs) count as one
        for c in pool:
            grp = c.get("group", c["template"])
            if grp in used:
                continue
            used.add(grp)
            out.append(c)
            if len(used) == n:
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


SACKED_EMOJI = "\u2B1B"   # black square (red is now the Starter tier)
TIER_COLORS = {1: "#b3bccd", 2: "#6fd0ff", 3: "#ff4b55", 4: "#b866ff", 5: "#fff04d", 6: "#ffab1a"}  # same as play.css --t1..--t6


def tier_info(tier):
    name, yards, emoji = TIERS[tier]
    return {"tier": tier, "tier_name": name, "yards": yards, "emoji": emoji, "color": TIER_COLORS[tier]}


ANSWER_EXTRAS = ("team", "position", "headshot", "stat", "stat_label")


def answer_details(a):
    """The visual extras for one answer; every key is always present (None when the bank row has none)."""
    return {k: a.get(k) for k in ANSWER_EXTRAS}


def reveal_view(prompt):
    """Full tiered answer list (most popular first inside each tier), highest tier first. Only after the game.
    "answers" stays a list of names; "details" runs parallel to it with {name, team, position, headshot, stat, stat_label}."""
    tiers = []
    for t in sorted(TIERS, reverse=True):
        inside = [a for a in prompt["answers"] if a["tier"] == t]
        tiers.append({**tier_info(t), "answers": [a["name"] for a in inside], "details": [{"name": a["name"], **answer_details(a)} for a in inside]})
    return {"id": prompt["id"], "text": prompt["text"], "tiers": tiers}


def share_text(date_str, tiers, base_url="lineup-lab-awdv.onrender.com"):
    """Spoiler-free share card. `tiers` = per-prompt tier numbers, 0 for Sacked."""
    d = dt.date.fromisoformat(date_str)
    yards = sum(TIERS[t][1] for t in tiers if t)
    squares = "".join(TIERS[t][2] if t else SACKED_EMOJI for t in tiers)
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
        through = weeks[-1]                                # latest fully completed regular-season week
        fame = None
        try:                                               # career signals for fame; consensus-only if they can't load
            history = data.load_season_history(season - 1)
            picks = data.load_draft_picks()
            av_by_id = {g: float(v) for g, v in zip(picks["gsis_id"], picks["car_av"]) if isinstance(g, str) and pd.notna(v)}
            fame = (career_points(history, wk), av_by_id)
        except Exception as e:
            print(f"[daily_drive] career data unavailable, rarity from consensus only: {e}")
        for tpl in FANTASY_TEMPLATES:
            p = build_season_prompt(tpl, wk, season, through, ecr_rank, fame)
            if p:
                cands.append(p)
    if not HISTORY_ENABLED:
        return cands
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


def _read_puzzle(path):
    try:
        with open(path, encoding="utf-8") as fh:
            puz = json.load(fh)
        return puz if puz.get("v") == PUZZLE_VERSION else None     # an older shape (pre season-prompts) is regenerated
    except Exception:
        return None


def yesterday_templates(cache_dir, date_str, candidates):
    """Templates used the day before `date_str`: from its cached puzzle, else what that day's deterministic pick
    would be from the same candidates. Feeds the no-same-template-on-consecutive-days rule."""
    prev = (dt.date.fromisoformat(date_str) - dt.timedelta(days=1)).isoformat()
    puz = _read_puzzle(_puzzle_path(cache_dir, prev))
    if puz:
        return {p["template"] for p in puz["prompts"]}
    return {p["template"] for p in pick_day(prev, candidates)}


def get_puzzle(date_str, cache_dir, candidates_fn=live_candidates):
    """The day's puzzle {v, date, prompts:[full prompt dicts]}, from the disk cache or generated and cached. The day
    is built from data through the latest completed week, so a new week flows in on its own (new ids)."""
    path = _puzzle_path(cache_dir, date_str)
    if os.path.exists(path):
        puz = _read_puzzle(path)
        if puz:
            return puz
    cands = candidates_fn(date_str)
    prompts = pick_day(date_str, cands, yesterday_templates(cache_dir, date_str, cands))
    puzzle = {"v": PUZZLE_VERSION, "date": date_str, "prompts": prompts}
    if len(prompts) == day_size():                      # never freeze a short day: it may just be missing data
        os.makedirs(cache_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(puzzle, fh)
        os.replace(tmp, path)
    return puzzle
