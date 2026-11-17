"""
THE DAILY DRIVE - the HISTORY prompt pool (DRAFT, NOT WIRED IN)
===============================================================
The history side of the day: the owner's mix is 2 current-season prompts (engine/daily_drive_pool.py) + 5 history
prompts (this module). Same machinery as the current pool: a template is a data dict, an evaluator turns it into one
row per candidate player with a `val`, and dd.pick_threshold walks the template's `ladder` through the REAL fame /
tiering path (dd._answers_at -> fame_scores -> rank_and_tier) so famous players are tier 1 and obscure-but-valid
players are tier 6. Answers are never typed: every answer is computed from nflverse tables.

Owner rules this module enforces:
  * at most 5% of ALL questions may be pre-2000, so every template here is scoped to the 2000 season or later (the
    text says so: "since 2000", "in the 2010s", "drafted since 2000"); the tests assert no template text mentions a
    pre-2000 year, and the data layer never loads a season before 2000.
  * at least dd.MIN_ANSWERS answers and a tier-6 answer (pick_threshold enforces both), and a ceiling of
    HIST_MAX_ANSWERS so a prompt is never "name any of 200 players".
  * players only; HoF / All-Pro / Pro Bowl come from the draft table's own flags, so undrafted players can never be
    answers to a flag-based prompt (they simply have no flags there).

DATA (all nflverse, all offline-cached under data_cache/daily_drive/ after the first run):
  * stats_player_week_<year>, 2000..last finished season: regular season AND postseason rows (a Super Bowl is the
    last POST week of a season). Trimmed to the columns below and cached once per season, forever.
  * draft_picks (data.load_draft_picks): 1980-2026 drafts; only drafts from 2000..last finished season are used.
  * schedules via nfl_data_py (Super Bowl winners), cached once.
Missing or failed season files make the WHOLE history pool return no prompts rather than a pool built on a gap.

A template (see T()): key, cat, kind, text, ladder, label, group, plus the kind's own fields:
  kind "best"     best single season (REG) of `stat` for players at `pos`            -> "a season with 1,500+ rush yds"
  kind "career"   total of `stat` over the seasons in range                         -> "10,000+ career rush yds since 2000"
  kind "nseas"    number of seasons with `stat` >= `line`                            -> "3+ seasons with 1,000+ rec yds"
  kind "game"     best single REG game of `stat`; "ngame": count of games with `cond`
  kind "post"     best single playoff game of `stat` ("postn": count of playoff games with cond; "sb": same, Super Bowl only)
  kind "draft"    one row per drafted player; `val` is a draft-table column or a stat from the frozen career table
Scopes (`scope`): decade (2000s/2010s/2020s), team, college, pos. The scope for a date is picked deterministically,
skipping any variant that cannot build a prompt (scope_for / candidates).
"""

import hashlib
import operator
import os
import re
import time

import numpy as np
import pandas as pd

from engine import daily_drive as dd
from engine import daily_drive_pool as pool

FIRST_SEASON = 2000                 # nothing earlier is ever loaded (owner rule 3: at most 5% pre-2000)
HIST_MAX_ANSWERS = 50               # a rung with more answers is "too broad": the prompt is dropped, never widened
CACHE_VERSION = "v1"

# ----------------------------------------------------------------------------------------------- data layer
# Columns kept from stats_player_week (float32 where numeric). Everything the templates read.
_ID_COLS = ["player_id", "player_display_name", "position", "headshot_url", "season", "week", "season_type", "team"]
_NUM_COLS = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
             "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
             "def_tackles_solo", "def_tackle_assists", "def_sacks", "def_interceptions", "def_tds", "def_pass_defended",
             "def_fumbles_forced", "def_safeties", "def_tackles_for_loss", "def_qb_hits", "fumble_recovery_tds",
             "special_teams_tds", "kickoff_return_yards", "punt_return_yards", "fg_made", "fg_att", "fg_long",
             "fg_made_50_59", "fg_made_60_", "pat_made", "pt_att", "pt_inside_20", "fantasy_points_ppr"]
_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.parquet"
_WEEK_FILL = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries",
              "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
              "def_tackles_solo", "def_tackle_assists", "def_sacks", "def_interceptions", "def_tds", "fg_made",
              "special_teams_tds", "fumble_recovery_tds", "fantasy_points_ppr"]

_MEM = {}                           # per-process cache of the built context (key: last finished season)


def _week_path(y):
    from engine import data
    return os.path.join(data.HISTORY_DIR, f"hist_week_{CACHE_VERSION}_{y}.parquet")


def load_week_year(y):
    """One season of weekly player rows (REG + POST), trimmed and cached forever (a finished season never changes).
    A season file that cannot be read raises: the pool must not be built on a gap."""
    path = _week_path(y)
    if os.path.exists(path):
        return pd.read_parquet(path)
    df = pd.read_parquet(_URL.format(y=y))
    df = df.rename(columns={"recent_team": "team"}) if "recent_team" in df.columns else df
    keep = _ID_COLS + [c for c in _NUM_COLS if c in df.columns]
    df = df[[c for c in keep if c in df.columns]].copy()
    for c in _NUM_COLS:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = df[c].fillna(0).astype("float32")
    df = df[df["player_id"].notna()]
    df["season"] = df["season"].astype("int16")
    df["week"] = df["week"].astype("int8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    df.to_parquet(tmp)
    os.replace(tmp, path)
    return df


def _derive(df):
    """Derived stat columns shared by the season, game and playoff tables."""
    df["tds"] = df["rushing_tds"] + df["receiving_tds"]
    df["all_tds"] = df["tds"] + df["passing_tds"]
    df["scrim"] = df["rushing_yards"] + df["receiving_yards"]
    df["tkl"] = df["def_tackles_solo"] + df["def_tackle_assists"]
    df["fpts"] = df["fantasy_points_ppr"]
    df["fg_50p"] = df["fg_made_50_59"] + df["fg_made_60_"]
    df["fg_miss"] = df["fg_att"] - df["fg_made"]
    return df


_SUM_COLS = [c for c in _NUM_COLS if c != "fg_long"]


def _season_rows(df):
    """Player x season x team totals from one year's REG rows."""
    reg = df[df["season_type"] == "REG"].sort_values("week")
    g = reg.groupby(["player_id", "season", "team"], sort=False)
    out = g[_SUM_COLS].sum()
    out["fg_long"] = g["fg_long"].max()
    out["games"] = g.size().astype("int16")
    meta = g.agg(name=("player_display_name", "last"), pos=("position", "last"), headshot=("headshot_url", "last"))
    return _derive(out.join(meta).reset_index())


_GAME_KEEP = ["player_id", "player_display_name", "position", "headshot_url", "season", "week", "team"] + _SUM_COLS


def _all_team_seasons(ps):
    """One row per player x season (stints with several teams summed; name/pos/team/headshot from the longest stint)."""
    cols = _SUM_COLS + ["tds", "all_tds", "scrim", "tkl", "fpts", "fg_50p", "fg_miss", "games"]
    s = ps.sort_values(["player_id", "season", "games"], kind="stable")
    g = s.groupby(["player_id", "season"], sort=False)
    out = g[[c for c in cols if c != "fg_long"]].sum()
    out["fg_long"] = g["fg_long"].max()
    meta = g[["name", "pos", "team", "headshot"]].last()
    return out.join(meta).reset_index()


def _big_games(df):
    """Single REG games worth keeping for the game-feat templates (a superset of anything a ladder can ask for)."""
    reg = df[df["season_type"] == "REG"]
    m = ((reg["passing_yards"] >= 250) | (reg["rushing_yards"] >= 100) | (reg["receiving_yards"] >= 100)
         | (reg["receptions"] >= 8) | (reg["passing_tds"] >= 3) | (reg["rushing_tds"] + reg["receiving_tds"] >= 2)
         | (reg["fantasy_points_ppr"] >= 30) | (reg["def_sacks"] >= 2.5) | (reg["def_interceptions"] >= 2)
         | (reg["fg_made"] >= 5) | (reg["def_tds"] + reg["fumble_recovery_tds"] + reg["special_teams_tds"] >= 2)
         | (reg["def_tackles_solo"] + reg["def_tackle_assists"] >= 14))
    g = reg.loc[m, [c for c in _GAME_KEEP if c in reg.columns]].rename(columns={"player_display_name": "name", "position": "pos", "headshot_url": "headshot"})
    return _derive(g.reset_index(drop=True))


def _post_rows(df):
    p = df[df["season_type"] != "REG"]
    p = p[(p[_SUM_COLS].abs().sum(axis=1) > 0)]
    g = p[[c for c in _GAME_KEEP if c in p.columns]].rename(columns={"player_display_name": "name", "position": "pos", "headshot_url": "headshot"})
    return _derive(g.reset_index(drop=True))


def _super_bowls(first, last):
    """{season: (winner, loser, week)} from the schedule; empty when the schedule can't be read."""
    from engine import data
    path = os.path.join(data.HISTORY_DIR, f"hist_superbowls_{CACHE_VERSION}_{first}_{last}.parquet")
    if os.path.exists(path):
        s = pd.read_parquet(path)
    else:
        import nfl_data_py as nfl
        s = nfl.import_schedules(list(range(first, last + 1)))
        s = s[s["game_type"] == "SB"][["season", "week", "home_team", "away_team", "home_score", "away_score"]].copy()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        s.to_parquet(path)
    out = {}
    for r in s.itertuples(index=False):
        if pd.isna(r.home_score) or pd.isna(r.away_score) or r.home_score == r.away_score:
            continue
        home_won = r.home_score > r.away_score
        out[int(r.season)] = (r.home_team if home_won else r.away_team, r.away_team if home_won else r.home_team, int(r.week))
    return out


# draft-table team codes (PFR style) -> the modern franchise code the weekly tables use
DRAFT_TEAM = {"GNB": "GB", "KAN": "KC", "NOR": "NO", "SFO": "SF", "NWE": "NE", "TAM": "TB", "STL": "LA", "RAM": "LA", "LAR": "LA",
              "SDG": "LAC", "OAK": "LV", "RAI": "LV", "LVR": "LV", "PHO": "ARI", "SD": "LAC", "HST": "HOU", "CRD": "ARI",
              "CLT": "IND", "RAV": "BAL", "SEA": "SEA"}


def _norm_team(t):
    return DRAFT_TEAM.get(t, t)


def _slim(df):
    """Repeated strings (names, positions, teams, headshot URLs) as categoricals: the frames are held for the process."""
    for c in ("name", "pos", "team", "headshot"):
        if c in df.columns and df[c].dtype == object:
            df[c] = df[c].astype("category")
    return df


def assemble_context(ps, games, post, sbs, picks, last_season, ecr_rank=None):
    """The derived tables the evaluators read, from the stacked loaded data (also what the tests feed synthetic frames).
    `post` needs season/week/team columns; the Super Bowl rows and winners are marked from `sbs`."""
    ps = _slim(ps)
    games = _slim(games)
    post = _slim(post.copy())
    psa = _slim(_all_team_seasons(ps))
    # which POST rows are the Super Bowl: the last POST week of a season (only when that season's result is known)
    post["sb"] = False
    for s, (_w, _l, wk) in sbs.items():
        post.loc[(post["season"] == s) & (post["week"] == wk), "sb"] = True
    post["won_sb"] = False
    for s, (w, _l, wk) in sbs.items():
        post.loc[(post["season"] == s) & (post["week"] == wk) & (post["team"] == w), "won_sb"] = True
    dr = picks[(picks["season"] >= FIRST_SEASON) & (picks["season"] <= int(last_season)) & picks["pfr_player_name"].notna()].copy()
    dr["pid"] = [g if isinstance(g, str) else f"pfr:{p}" for g, p in zip(dr["gsis_id"], dr["pfr_player_id"])]
    dr["name"] = dr["pfr_player_name"]
    dr["dteam"] = dr["team"].map(_norm_team)
    # Approximate Value: the table's career AV (car_av) is empty for these drafts, so the weighted AV (w_av) is the signal
    dr["av"] = dr["car_av"].where(dr["car_av"].notna(), dr["w_av"]).fillna(0.0)
    for c in ("allpro", "probowls", "seasons_started"):
        dr[c] = dr[c].fillna(0).astype(int)
    # frozen career table (seasons 2000..last) per player: sums of every counting stat
    career = ps.groupby("player_id")[_SUM_COLS + ["tds", "all_tds", "scrim", "tkl", "fg_50p"]].sum()
    first_seen = ps.groupby("player_id")["season"].min()
    career["first_season"] = first_seen
    ppr = career["fantasy_points_ppr"].to_dict()
    # career signals for the fame score where PPR means nothing (defenders, kickers/punters have ~0 fantasy points),
    # built only from the frozen 2000+ stats so an undrafted star (no draft-table AV) is still a famous answer
    defval = (career["def_sacks"] * 3 + career["def_interceptions"] * 3 + career["def_fumbles_forced"] * 1.5 + career["def_tds"] * 6
              + career["def_pass_defended"] * 0.5 + career["tkl"] * 0.3).to_dict()
    kickval = (career["fg_made"] * 3 + career["pat_made"] + career["pt_att"] * 0.5).to_dict()
    # fame must see players drafted before 2000 too (a 2000s season by a 1990s draftee is still a famous answer), so the
    # AV lookup covers the whole draft table (1980-2026), not just the drafts this pool asks about
    av_all = picks["car_av"].where(picks["car_av"].notna(), picks["w_av"])
    av_by_id = {g: float(a) for g, a in zip(picks["gsis_id"], av_all) if isinstance(g, str) and pd.notna(a)}
    av_by_id.update({p: float(a) for p, a in zip(dr["pid"], dr["av"]) if p not in av_by_id})
    heads = (pd.concat([ps[["player_id", "headshot"]]]).dropna().drop_duplicates("player_id", keep="last")
             .set_index("player_id")["headshot"].to_dict())
    ctx = {"last": int(last_season), "ps": ps, "psa": psa, "games": games, "post": post, "sbs": sbs, "draft": dr, "career": career,
           "ppr": ppr, "defval": defval, "kickval": kickval, "av": av_by_id, "heads": heads, "ecr": ecr_rank or {}}
    return ctx


def build_context(last_season=None, ecr_rank=None, picks=None, verbose=False):
    """Everything the evaluators need, built once per process. Raises when a season 2000..last is unreadable."""
    from engine import data
    t0 = time.time()
    if last_season is None:
        last_season = data.resolve_season() - 1             # the current season is in progress: finished seasons only
    key = (int(last_season), picks is None)
    if key in _MEM:
        return _MEM[key]
    ps_parts, game_parts, post_parts = [], [], []
    for y in range(FIRST_SEASON, int(last_season) + 1):
        df = load_week_year(y)
        ps_parts.append(_season_rows(df))
        game_parts.append(_big_games(df))
        post_parts.append(_post_rows(df))
        del df
    ps = pd.concat(ps_parts, ignore_index=True)
    games = pd.concat(game_parts, ignore_index=True)
    post = pd.concat(post_parts, ignore_index=True)
    try:
        sbs = _super_bowls(FIRST_SEASON, int(last_season))
    except Exception as e:
        print(f"[daily_drive_history] schedule unavailable, Super Bowl prompts dropped: {e}")
        sbs = {}
    if picks is None:
        picks = data.load_draft_picks()
    ctx = assemble_context(ps, games, post, sbs, picks, last_season, ecr_rank)
    ctx["load_seconds"] = round(time.time() - t0, 2)
    _MEM[key] = ctx
    return ctx


# ----------------------------------------------------------------------------------------------- vocab
HPOS = {
    "QB": ("QB",), "RB": ("RB", "FB"), "WR": ("WR",), "TE": ("TE",), "K": ("K",), "P": ("P",),
    "SKILL": ("QB", "RB", "FB", "WR", "TE"), "FLEX": ("RB", "FB", "WR", "TE"), "REC": ("RB", "FB", "WR", "TE"),
    "DEF": ("DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "MLB", "CB", "DB", "S", "SAF", "FS"),
    "DB": ("CB", "DB", "S", "SAF", "FS"), "PASSRUSH": ("DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "MLB"),
}
# draft-table position codes grouped for the position scope, with the text that goes into a prompt
DRAFT_POS = {
    "QB": ("QB",), "RB": ("RB", "FB"), "WR": ("WR",), "TE": ("TE",),
    "OL": ("T", "G", "C", "OL", "OT", "OG"), "DL": ("DE", "DT", "NT", "DL"),
    "LB": ("LB", "OLB", "ILB", "MLB"), "DB": ("DB", "CB", "S", "SAF", "FS"),
}
DRAFT_POS_TEXT = {"QB": "a QB", "RB": "a running back", "WR": "a wide receiver", "TE": "a tight end",
                  "OL": "an offensive lineman", "DL": "a defensive lineman", "LB": "a linebacker", "DB": "a defensive back"}
DECADES = {"2000s": (2000, 2009), "2010s": (2010, 2019), "2020s": (2020, 9999)}
COLLEGES = ["Alabama", "Ohio St.", "LSU", "Georgia", "USC", "Michigan", "Florida", "Clemson", "Oklahoma", "Texas", "Miami (FL)",
            "Notre Dame", "Florida St.", "Auburn", "Penn St.", "Wisconsin", "Oregon", "Tennessee", "Iowa", "Virginia Tech",
            "Stanford", "Texas A&M", "UCLA", "South Carolina", "Nebraska", "North Carolina", "Arkansas", "California",
            "Washington", "Mississippi", "Michigan St.", "Utah", "Pittsburgh", "TCU", "Louisville", "North Carolina St.",
            "Arizona St.", "Mississippi St.", "Maryland", "Kansas St.", "Missouri", "Purdue", "Oregon St.", "West Virginia"]
_COLLEGE_TEXT = {"Mississippi": "Ole Miss"}
TEAMS = sorted(pool.TEAM_NAME)

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}
# a REG game is kept in ctx["games"] only if it clears one of these floors, so every game template's lowest rung/cond
# must clear the floor of its stat (checked by tests via game_floor_ok)
GAME_FLOORS = {"passing_yards": 250, "rushing_yards": 100, "receiving_yards": 100, "receptions": 8, "passing_tds": 3,
               "tds": 2, "rushing_tds": 2, "receiving_tds": 2, "fpts": 30, "def_sacks": 3, "def_interceptions": 2, "fg_made": 5, "tkl": 14}


def T(key, cat, kind, text, ladder, label, **kw):
    return dict(key=key, cat=cat, kind=kind, text=text, ladder=tuple(ladder), label=label, **kw)


# ----------------------------------------------------------------------------------------------- scopes
ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh"}


def scope_options(tpl, last=2025):
    s = tpl.get("scope")
    if s == "round":
        return list(tpl.get("rounds") or range(2, 8))
    if s == "slot":
        return list(tpl.get("slots") or range(1, 33))
    if s == "year":
        return list(range(FIRST_SEASON, int(last) + 1))
    if s == "decade":
        return list(DECADES)
    if s == "team":
        return list(TEAMS)
    if s == "college":
        return list(tpl.get("colleges") or COLLEGES)
    if s == "pos":
        return list(tpl.get("poses") or DRAFT_POS)
    return []


def scope_order(tpl, date_str, last=2025):
    """The scope variants of a template in the deterministic order `date_str` tries them (first that builds wins)."""
    opts = scope_options(tpl, last)
    return sorted(opts, key=lambda o: hashlib.sha256(f"dd-hist:{tpl['key']}:{date_str}:{o}".encode()).hexdigest())


def scope_text(tpl, scope):
    s = tpl.get("scope")
    if s == "team":
        return pool.TEAM_NAME[scope]
    if s == "college":
        return _COLLEGE_TEXT.get(scope) or re.sub(r"\bSt\.$", "State", scope).replace("Col.", "College")
    if s == "pos":
        return DRAFT_POS_TEXT[scope]
    if s == "round":
        return ORDINAL[scope]
    if s == "slot":
        return f"#{scope}"
    return str(scope)


def season_range(tpl, ctx, scope=None):
    lo, hi = tpl.get("since", FIRST_SEASON), tpl.get("until", ctx["last"])
    if tpl.get("scope") == "decade" and scope:
        a, b = DECADES[scope]
        lo, hi = max(lo, a), min(hi, b, ctx["last"])
    return max(lo, FIRST_SEASON), min(hi, ctx["last"])


# ----------------------------------------------------------------------------------------------- evaluators
def _pos_set(tpl):
    p = tpl.get("pos")
    if p is None:
        return None
    return HPOS[p] if isinstance(p, str) else tuple(p)


def _conds(df, conds):
    m = pd.Series(True, index=df.index)
    for col, op, v in conds or ():
        m &= _OPS[op](df[col], v)
    return m


def _frame(rows, vals, ctx, sort_col="season", best_col=None):
    """Per-player frame in the shape dd.pick_threshold expects. Team / position / headshot come from the player's
    latest row, or from the row that holds the best value when `best_col` is given (so the team shown is the one he
    set the mark with)."""
    vals = vals[vals.notna()]
    if vals.empty:
        return pd.DataFrame(columns=["player_id", "name", "pos", "team", "headshot", "val", "ppr"])
    order = [best_col, sort_col] if best_col else [sort_col]
    last = rows.sort_values(order).drop_duplicates("player_id", keep="last").set_index("player_id").reindex(vals.index)
    out = pd.DataFrame({"player_id": vals.index, "name": np.asarray(last["name"], dtype=object), "pos": np.asarray(last["pos"], dtype=object),
                        "team": np.asarray(last["team"], dtype=object), "headshot": np.asarray(last["headshot"], dtype=object),
                        "val": vals.values.astype(float)})
    out["ppr"] = [float(ctx["ppr"].get(p, 0.0)) for p in out["player_id"]]
    return out.reset_index(drop=True)


def _draft_filter(rows, tpl, ctx):
    """Join the draft table onto stat rows for rookie / draft-round filters (undrafted players drop out)."""
    if not (tpl.get("rookie") or tpl.get("rd")):
        return rows
    d = ctx["draft_by_pid"]
    rnd = rows["player_id"].map(d["round"])
    keep = rnd.notna()
    if tpl.get("rd"):
        lo, hi = tpl["rd"]
        keep &= (rnd >= lo) & (rnd <= hi)
    if tpl.get("rookie"):
        keep &= rows["season"] == rows["player_id"].map(d["season"])
    return rows[keep]


def _stat_rows(tpl, ctx, scope):
    """Season rows for the template: scope/seasons/position/draft filters applied (kinds best / career / nseas)."""
    lo, hi = season_range(tpl, ctx, scope)
    df = ctx["ps"] if tpl.get("scope") == "team" else ctx["psa"]
    m = (df["season"] >= lo) & (df["season"] <= hi)
    if tpl.get("scope") == "team":
        m &= df["team"] == scope
    ps = _pos_set(tpl)
    if ps:
        m &= df["pos"].isin(ps)
    rows = df[m]
    rows = rows[_conds(rows, tpl.get("where"))]
    return _draft_filter(rows, tpl, ctx)


def _event_rows(tpl, ctx, scope, table):
    lo, hi = season_range(tpl, ctx, scope)
    df = ctx[table]
    m = (df["season"] >= lo) & (df["season"] <= hi)
    if tpl.get("scope") == "team":
        m &= df["team"] == scope
    ps = _pos_set(tpl)
    if ps:
        m &= df["pos"].isin(ps)
    if tpl.get("sb"):
        m &= df["sb"]
    if tpl.get("won_sb"):
        m &= df["won_sb"]
    if tpl.get("lost_sb"):
        m &= df["sb"] & ~df["won_sb"]
    rows = df[m]
    return _draft_filter(rows, tpl, ctx)


def _evaluate_draft(tpl, ctx, scope):
    d = ctx["draft"]
    lo, hi = tpl.get("since", FIRST_SEASON), tpl.get("until", ctx["last"])
    if tpl.get("scope") == "decade" and scope:
        a, b = DECADES[scope]
        lo, hi = max(lo, a), min(hi, b)
    sc = tpl.get("scope")
    if sc == "year":
        lo = hi = int(scope)
    m = (d["season"] >= lo) & (d["season"] <= min(hi, ctx["last"]))
    rd, pk = tpl.get("rd"), tpl.get("pick")
    if sc == "round":
        rd = (int(scope), int(scope))
    if sc == "slot":
        pk = (int(scope), int(scope))
    if rd:
        m &= (d["round"] >= rd[0]) & (d["round"] <= rd[1])
    if pk:
        m &= (d["pick"] >= pk[0]) & (d["pick"] <= pk[1])
    if tpl.get("dpos"):
        m &= d["position"].isin(DRAFT_POS[tpl["dpos"]] if isinstance(tpl["dpos"], str) else tpl["dpos"])
    if tpl.get("side"):
        m &= d["side"] == tpl["side"]
    if tpl.get("hof"):
        m &= d["hof"]
    if tpl.get("min_pb"):
        m &= d["probowls"] >= tpl["min_pb"]
    if tpl.get("min_ap"):
        m &= d["allpro"] >= tpl["min_ap"]
    if sc == "team":
        m &= d["dteam"] == scope
    elif sc == "college":
        m &= d["college"] == scope
    elif sc == "pos":
        m &= d["position"].isin(DRAFT_POS[scope])
    rows = d[m]
    if rows.empty:
        return _frame(rows.assign(team=None, headshot=None, pos=None), pd.Series(dtype=float), ctx)
    val = tpl.get("val", "probowls")
    if val.startswith("career:"):
        col = val.split(":", 1)[1]
        v = rows["pid"].map(ctx["career"][col])
        rows = rows[v.notna()]
        v = v[v.notna()]
    else:
        v = rows[val].astype(float)
    out = pd.DataFrame({"player_id": rows["pid"].values, "name": rows["name"].values, "pos": rows["position"].values,
                        "team": rows["dteam"].values, "headshot": [ctx["heads"].get(p) for p in rows["pid"]],
                        "val": v.values.astype(float)})
    out["ppr"] = [float(ctx["ppr"].get(p, 0.0)) for p in out["player_id"]]
    return out.drop_duplicates("player_id").reset_index(drop=True)


def evaluate(tpl, ctx, scope=None):
    """Per-player frame for a template: one row per player with `val` (the number the ladder is walked against)."""
    kind = tpl["kind"]
    if kind == "draft":
        return _evaluate_draft(tpl, ctx, scope)
    stat = tpl.get("stat")
    if kind in ("best", "career", "nseas"):
        rows = _stat_rows(tpl, ctx, scope)
        if rows.empty:
            return _frame(rows, pd.Series(dtype=float), ctx)
        g = rows.groupby("player_id")
        if kind == "best":
            vals = g[stat].max()
            return _frame(rows, vals, ctx, best_col=stat)
        elif kind == "career":
            vals = g[stat].sum()
        else:
            ok = rows[rows[stat] >= tpl["line"]]
            vals = ok.groupby("player_id").size().astype(float)
            rows = ok
        return _frame(rows, vals, ctx)
    table = "games" if kind in ("game", "ngame") else "post"
    rows = _event_rows(tpl, ctx, scope, table)
    if rows.empty:
        return _frame(rows, pd.Series(dtype=float), ctx, "week")
    rows = rows.assign(_k=rows["season"] * 100 + rows["week"])
    if kind in ("game", "post"):
        vals = rows.groupby("player_id")[stat].max()
        return _frame(rows, vals, ctx, "_k", best_col=stat)
    elif kind == "postsum":
        vals = rows.groupby("player_id")[stat].sum()
    else:                                              # ngame / postn: count the games meeting every cond
        ok = rows[_conds(rows, tpl["cond"])]
        vals = ok.groupby("player_id").size().astype(float)
        rows = ok
    return _frame(rows, vals, ctx, "_k")


# ----------------------------------------------------------------------------------------------- text
def fmt_threshold(t):
    return pool.fmt_threshold(t)


def render_text(tpl, t, scope=None):
    pb = "" if t <= 0 else (" who made a Pro Bowl" if t == 1 else f" who made {fmt_threshold(t)}+ Pro Bowls")
    ap = "" if t <= 0 else (" who was an All-Pro" if t == 1 else f" who was an All-Pro {fmt_threshold(t)}+ times")
    n = fmt_threshold(t)
    fields = {"t": n, "scope": scope_text(tpl, scope) if scope else "", "pb": pb, "ap": ap,
              "times": "" if t <= 1 else f" {n}+ times", "nseasons": "a season" if t == 1 else f"{n}+ seasons"}
    text = tpl["text"].format(**fields)
    text = re.sub(r"\b([Aa]) (8|11|18)(?=[\d,]*\+)", lambda m: m.group(1) + "n " + m.group(2), text)
    return pool.tidy_text(text)


# ----------------------------------------------------------------------------------------------- build
def _fame_for(tpl, ctx):
    src = tpl.get("fame")
    if src is None:
        p = tpl.get("pos")
        if tpl["kind"] == "draft":
            src = "av"
        elif p in ("QB", "RB", "WR", "TE", "SKILL", "FLEX", "REC"):
            src = "ppr"
        elif p in ("K", "P"):
            src = "kick"
        else:
            src = "def"
    career = {"ppr": ctx["ppr"], "def": ctx["defval"], "kick": ctx["kickval"], "av": ctx["av"]}[src]
    return (career, ctx["av"])


def era_text(tpl, scope):
    if tpl.get("scope") == "decade":
        return f"the {scope}"
    return "since 2000"


def build_history_prompt(tpl, ctx, scope=None, ecr_rank=None):
    """One prompt through the real tiering path (dd.pick_threshold). None when no ladder rung leaves MIN_ANSWERS
    answers with a tier-6 answer, or when the chosen rung is too broad (more than HIST_MAX_ANSWERS)."""
    per = evaluate(tpl, ctx, scope)
    if per.empty:
        return None
    t, answers = dd.pick_threshold(per, tpl["ladder"], ecr_rank if ecr_rank is not None else ctx["ecr"], tpl["label"], _fame_for(tpl, ctx))
    if t is None or len(answers) > HIST_MAX_ANSWERS:
        return None
    sid = f":{scope}" if scope else ""
    kind_cat = {"draft": "Draft since 2000", "post": "Playoffs since 2000", "postn": "Playoffs since 2000", "postsum": "Playoffs since 2000"}
    cat_line = kind_cat.get(tpl["kind"], "Since 2000") if tpl.get("scope") != "decade" else f"The {scope}"
    if tpl["cat"] in (SUPERBOWL,) and tpl.get("scope") != "decade":
        cat_line = "Super Bowls since 2000"
    return {"id": f"hh:{tpl['key']}:{ctx['last']}:t{fmt_threshold(t)}{sid}".replace(" ", "_"), "template": tpl["key"], "kind": "history",
            "text": render_text(tpl, t, scope), "category": f"NFL history · {cat_line}", "cat": tpl["cat"], "answers": answers,
            "threshold": t, "group": tpl.get("group", tpl["key"]), "scope": scope}


SHAPE = {"best": "season", "game": "game", "post": "game"}


def _hist_pos_tag(tpl):
    if tpl["kind"] == "draft":
        return None
    p = tpl.get("pos")
    return "DEF" if p is None else dd.pos_tag(p)


def build_history_bands(tpl, ctx, scope=None, ecr_rank=None):
    """Up to one prompt per difficulty band (dd.BANDS) for the easy -> hard days. The ladder gets the template's
    `easy_lines` (hand-picked round lines) as the only easy rungs; there is no 50-answer ceiling here, a warm-up
    may have hundreds of answers (owner, 2026-11-17). Each variant is playable: dd.FLOOR answers, every tier."""
    per = evaluate(tpl, ctx, scope)
    if per.empty:
        return []
    got = dd.band_thresholds(per, tpl["ladder"], ecr_rank if ecr_rank is not None else ctx["ecr"], tpl["label"], _fame_for(tpl, ctx),
                             easy_lines=tpl.get("easy_lines", ()), warmup=tpl.get("warmup", False))
    sid = f":{scope}" if scope else ""
    kind_cat = {"draft": "Draft since 2000", "post": "Playoffs since 2000", "postn": "Playoffs since 2000", "postsum": "Playoffs since 2000"}
    cat_line = kind_cat.get(tpl["kind"], "Since 2000") if tpl.get("scope") != "decade" else f"The {scope}"
    if tpl["cat"] in (SUPERBOWL,) and tpl.get("scope") != "decade":
        cat_line = "Super Bowls since 2000"
    if tpl.get("since") and tpl.get("scope") != "decade":
        cat_line = cat_line.replace("since 2000", f"since {tpl['since']}")
    out = []
    for band, (t, answers) in got.items():
        out.append({"id": f"hh:{tpl['key']}:{ctx['last']}:t{fmt_threshold(t)}{sid}".replace(" ", "_"), "template": tpl["key"],
                    "kind": "history", "text": render_text(tpl, t, scope), "category": f"NFL history · {cat_line}", "cat": tpl["cat"],
                    "answers": answers, "threshold": t, "group": tpl.get("group", tpl["key"]), "scope": scope, "band": band,
                    "pos_tag": _hist_pos_tag(tpl), "shape": SHAPE.get(tpl["kind"])})
    return out


def build_any_scope(tpl, ctx, date_str, ecr_rank=None):
    """The prompt for `date_str`: unscoped templates build directly; scoped ones try their scope variants in the
    date's deterministic order and use the first that passes."""
    if not tpl.get("scope"):
        return build_history_prompt(tpl, ctx, None, ecr_rank)
    for sc in scope_order(tpl, date_str, ctx["last"]):
        p = build_history_prompt(tpl, ctx, sc, ecr_rank)
        if p:
            return p
    return None


def _prepare_ctx(ctx):
    if "draft_by_pid" not in ctx:
        ctx["draft_by_pid"] = ctx["draft"].drop_duplicates("pid").set_index("pid")
    return ctx


def release():
    """Drop the process-level context (about 100 MB of tables); the next history_candidates call rebuilds it (~1 s)."""
    import gc
    _MEM.clear()
    gc.collect()


def history_candidates(date_str, ecr_rank=None, templates=None, ctx=None, last_season=None, keep_context=False):
    """Every buildable history prompt for `date_str` (one per template). Fails soft: any data problem gives fewer
    prompts (or none), never an exception. The data tables are dropped afterwards unless `keep_context` (the puzzle
    for a day is cached on disk by dd.get_puzzle, so this runs once per day, not per request)."""
    own_ctx = ctx is None
    try:
        if ecr_rank is None:
            try:
                from engine import consensus
                ecr_rank = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
            except Exception as e:
                print(f"[daily_drive_history] consensus unavailable, fame from career data only: {e}")
                ecr_rank = {}
        if ctx is None:
            ctx = build_context(last_season, ecr_rank)
        ctx = _prepare_ctx(ctx)
    except Exception as e:
        print(f"[daily_drive_history] history data unavailable, no history prompts: {type(e).__name__}: {e}")
        return []
    out = []
    for tpl in (HISTORY_POOL if templates is None else templates):
        try:
            p = build_any_scope(tpl, ctx, date_str, ecr_rank)
        except Exception as e:
            print(f"[daily_drive_history] {tpl['key']} failed: {type(e).__name__}: {e}")
            continue
        if p:
            out.append(p)
    if own_ctx and not keep_context:
        del ctx
        release()
    return out



# ----------------------------------------------------------------------------------------------- the pool
SEASON, DECADE, CAREER, DECADE_TOT, REPEAT, GAME = "Season marks", "Decade marks", "Career totals", "Decade totals", "Repeat seasons", "Big games"
ROOKIE, PEDIGREE, DRAFT, DRAFT_COL, DRAFT_TEAM_CAT, DRAFT_STAT = "Rookie seasons", "Draft pedigree", "NFL Draft", "Draft: colleges", "Draft: teams", "Draft careers"
PLAYOFF, SUPERBOWL, TEAMHIST = "Playoffs", "Super Bowls", "Team history"

_SINCE = "since 2000"
_DEC = "of the {scope}"


def _season(key, pos, stat, ladder, label, text, **kw):
    return T(key, SEASON, "best", text, ladder, label, pos=pos, stat=stat, **kw)


def _decade(key, pos, stat, ladder, label, text, **kw):
    return T(key, DECADE, "best", text, ladder, label, pos=pos, stat=stat, scope="decade", **kw)


def _career(key, pos, stat, ladder, label, text, **kw):
    return T(key, CAREER, "career", text, ladder, label, pos=pos, stat=stat, **kw)


def _game(key, pos, stat, ladder, label, text, **kw):
    return T(key, GAME, "game", text, ladder, label, pos=pos, stat=stat, **kw)


HISTORY_POOL = [
    # ---- SEASON MARKS (regular seasons since 2000) -------------------------------------------------------------
    _season("h_qb_pass_yds", "QB", "passing_yards", (3500, 4000, 4200, 4400, 4500, 4700, 5000), "pass yds", "Name a QB who threw for {t}+ yards in a season since 2000"),
    _season("h_qb_pass_td", "QB", "passing_tds", (25, 28, 30, 32, 34, 36, 38, 40, 45), "pass TD", "Name a QB who threw {t}+ touchdown passes in a season since 2000"),
    _season("h_qb_rush_yds", "QB", "rushing_yards", (300, 400, 500, 600, 700, 800, 900, 1000), "rush yds", "Name a QB who ran for {t}+ yards in a season since 2000"),
    _season("h_qb_rush_td", "QB", "rushing_tds", (4, 5, 6, 7, 8, 10, 12, 14), "rush TD", "Name a QB with {t}+ rushing TDs in a season since 2000"),
    _season("h_qb_int", "QB", "passing_interceptions", (15, 17, 19, 20, 22, 24), "INT", "Name a QB who threw {t}+ interceptions in a season since 2000"),
    _season("h_qb_sacked", "QB", "sacks_suffered", (40, 45, 48, 50, 52, 55, 60), "times sacked", "Name a QB who was sacked {t}+ times in a season since 2000"),
    _season("h_rb_rush_yds", "RB", "rushing_yards", (1200, 1400, 1500, 1600, 1700, 1800, 1900, 2000), "rush yds", "Name a RB who ran for {t}+ yards in a season since 2000"),
    _season("h_rb_rush_td", "RB", "rushing_tds", (10, 12, 14, 15, 16, 17, 18, 20, 22), "rush TD", "Name a RB with {t}+ rushing TDs in a season since 2000"),
    _season("h_rb_carries", "RB", "carries", (300, 325, 350, 365, 375, 385, 390, 400), "carries", "Name a RB with {t}+ carries in a season since 2000"),
    _season("h_rb_rec", "RB", "receptions", (55, 60, 65, 70, 75, 80, 85, 90, 100), "rec", "Name a RB with {t}+ catches in a season since 2000"),
    _season("h_rb_scrim", "RB", "scrim", (1700, 1800, 1900, 2000, 2100, 2200), "scrim yds", "Name a RB with {t}+ yards from scrimmage in a season since 2000"),
    _season("h_wr_rec_yds", "WR", "receiving_yards", (1300, 1400, 1450, 1500, 1550, 1600, 1700), "rec yds", "Name a WR with {t}+ receiving yards in a season since 2000"),
    _season("h_wr_rec", "WR", "receptions", (95, 100, 105, 110, 115, 120, 125, 130), "rec", "Name a WR with {t}+ catches in a season since 2000"),
    _season("h_wr_rec_td", "WR", "receiving_tds", (10, 11, 12, 13, 14, 15, 16), "rec TD", "Name a WR with {t}+ receiving TDs in a season since 2000"),
    _season("h_wr_targets", "WR", "targets", (140, 150, 160, 170, 180, 190, 200), "targets", "Name a WR who was targeted {t}+ times in a season since 2000"),
    _season("h_te_rec_yds", "TE", "receiving_yards", (800, 900, 1000, 1100, 1200), "rec yds", "Name a TE with {t}+ receiving yards in a season since 2000"),
    _season("h_te_rec", "TE", "receptions", (70, 75, 80, 85, 90, 95, 100), "rec", "Name a TE with {t}+ catches in a season since 2000"),
    _season("h_te_td", "TE", "receiving_tds", (7, 8, 9, 10, 11, 12, 13), "rec TD", "Name a TE with {t}+ receiving TDs in a season since 2000"),
    _season("h_any_td", "SKILL", "tds", (14, 15, 16, 17, 18, 19, 20, 22), "total TD", "Name a player with {t}+ rushing and receiving TDs in a season since 2000"),
    _season("h_sacks", None, "def_sacks", (12, 13, 14, 15, 16, 17, 18, 20), "sacks", "Name a defender with {t}+ sacks in a season since 2000"),
    _season("h_def_int", None, "def_interceptions", (6, 7, 8, 9, 10), "INT", "Name a defender with {t}+ interceptions in a season since 2000"),
    _season("h_def_td", None, "def_tds", (2, 3, 4), "defensive TD", "Name a defender with {t}+ defensive TDs in a season since 2000"),
    _season("h_k_fg", "K", "fg_made", (30, 32, 34, 36, 38, 40), "FG made", "Name a kicker who made {t}+ field goals in a season since 2000"),
    _season("h_k_long", "K", "fg_long", (54, 55, 56, 57, 58, 59, 60, 62), "long FG", "Name a kicker with a {t}+ yard field goal in a season since 2000"),
    _season("h_p_in20", "P", "pt_inside_20", (30, 33, 36, 39, 42, 45), "punts inside 20", "Name a punter with {t}+ punts inside the 20 in a season since 2000"),

    # ---- DECADE MARKS (same stat lines, the decade rotates by date) --------------------------------------------
    _decade("h_dec_qb_yds", "QB", "passing_yards", (3500, 3800, 4000, 4200, 4400, 4500, 4700, 5000), "pass yds", "Name a QB who threw for {t}+ yards in a season " + _DEC),
    _decade("h_dec_qb_td", "QB", "passing_tds", (22, 25, 28, 30, 32, 34, 36, 38, 40), "pass TD", "Name a QB who threw {t}+ touchdown passes in a season " + _DEC),
    _decade("h_dec_qb_rush", "QB", "rushing_yards", (250, 300, 350, 400, 450, 500, 600, 700), "rush yds", "Name a QB who ran for {t}+ yards in a season " + _DEC),
    _decade("h_dec_rb_yds", "RB", "rushing_yards", (1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800), "rush yds", "Name a RB who ran for {t}+ yards in a season " + _DEC),
    _decade("h_dec_rb_td", "RB", "rushing_tds", (8, 10, 11, 12, 13, 14, 15, 16, 18), "rush TD", "Name a RB with {t}+ rushing TDs in a season " + _DEC),
    _decade("h_dec_rb_rec", "RB", "receptions", (45, 50, 55, 60, 65, 70, 75, 80), "rec", "Name a RB with {t}+ catches in a season " + _DEC),
    _decade("h_dec_wr_yds", "WR", "receiving_yards", (1000, 1100, 1200, 1300, 1400, 1500), "rec yds", "Name a WR with {t}+ receiving yards in a season " + _DEC),
    _decade("h_dec_wr_rec", "WR", "receptions", (80, 85, 90, 95, 100, 105, 110, 115), "rec", "Name a WR with {t}+ catches in a season " + _DEC),
    _decade("h_dec_wr_td", "WR", "receiving_tds", (8, 9, 10, 11, 12, 13, 14), "rec TD", "Name a WR with {t}+ receiving TDs in a season " + _DEC),
    _decade("h_dec_te_yds", "TE", "receiving_yards", (600, 700, 800, 900, 1000, 1100), "rec yds", "Name a TE with {t}+ receiving yards in a season " + _DEC),
    _decade("h_dec_sacks", None, "def_sacks", (9, 10, 11, 12, 13, 14, 15, 16), "sacks", "Name a defender with {t}+ sacks in a season " + _DEC),
    _decade("h_dec_int", None, "def_interceptions", (4, 5, 6, 7, 8), "INT", "Name a defender with {t}+ interceptions in a season " + _DEC),

    # ---- CAREER TOTALS (counting only seasons since 2000) -------------------------------------------------------
    _career("h_c_qb_yds", "QB", "passing_yards", (20000, 25000, 30000, 35000, 40000, 45000, 50000), "pass yds", "Name a QB with {t}+ career passing yards counting only seasons since 2000"),
    _career("h_c_qb_td", "QB", "passing_tds", (120, 150, 180, 200, 250, 300, 350), "pass TD", "Name a QB who has thrown {t}+ touchdown passes since 2000"),
    _career("h_c_qb_rush", "QB", "rushing_yards", (1500, 2000, 2500, 3000, 4000, 5000), "rush yds", "Name a QB with {t}+ career rushing yards since 2000"),
    _career("h_c_rb_yds", "RB", "rushing_yards", (5000, 6000, 7000, 8000, 9000, 10000, 11000), "rush yds", "Name a RB with {t}+ career rushing yards since 2000"),
    _career("h_c_rb_td", "RB", "rushing_tds", (40, 50, 60, 70, 80, 90, 100), "rush TD", "Name a RB with {t}+ career rushing TDs since 2000"),
    _career("h_c_rb_rec", "RB", "receptions", (300, 400, 500, 600, 700), "rec", "Name a RB with {t}+ career catches since 2000"),
    _career("h_c_wr_yds", "WR", "receiving_yards", (7000, 8000, 9000, 10000, 12000, 14000), "rec yds", "Name a WR with {t}+ career receiving yards since 2000"),
    _career("h_c_wr_rec", "WR", "receptions", (500, 600, 700, 800, 900, 1000), "rec", "Name a WR with {t}+ career catches since 2000"),
    _career("h_c_wr_td", "WR", "receiving_tds", (50, 60, 70, 80, 90, 100), "rec TD", "Name a WR with {t}+ career receiving TDs since 2000"),
    _career("h_c_te_yds", "TE", "receiving_yards", (4000, 5000, 6000, 7000, 8000, 10000), "rec yds", "Name a TE with {t}+ career receiving yards since 2000"),
    _career("h_c_te_td", "TE", "receiving_tds", (30, 40, 50, 60, 70, 80), "rec TD", "Name a TE with {t}+ career receiving TDs since 2000"),
    _career("h_c_any_td", "SKILL", "tds", (70, 80, 90, 100, 110, 120, 130), "rush + rec TD", "Name a player with {t}+ career rushing and receiving TDs since 2000"),
    _career("h_c_sacks", None, "def_sacks", (80, 90, 100, 110, 120, 130), "sacks", "Name a defender with {t}+ career sacks since 2000"),
    _career("h_c_int", None, "def_interceptions", (30, 35, 40, 45, 50), "INT", "Name a defender with {t}+ career interceptions since 2000"),
    _career("h_c_k", "K", "fg_made", (250, 300, 350, 400, 450, 500), "FG made", "Name a kicker with {t}+ career field goals since 2000"),

    # ---- DECADE TOTALS (career numbers inside one decade) -------------------------------------------------------
    T("h_dt_qb_yds", DECADE_TOT, "career", "Name a QB with {t}+ passing yards in the {scope}", (12000, 15000, 18000, 20000, 25000, 30000, 35000, 40000), "pass yds", pos="QB", stat="passing_yards", scope="decade"),
    T("h_dt_qb_td", DECADE_TOT, "career", "Name a QB with {t}+ touchdown passes in the {scope}", (80, 100, 120, 150, 180, 200, 250), "pass TD", pos="QB", stat="passing_tds", scope="decade"),
    T("h_dt_rb_yds", DECADE_TOT, "career", "Name a RB with {t}+ rushing yards in the {scope}", (3000, 4000, 5000, 6000, 7000, 8000, 9000), "rush yds", pos="RB", stat="rushing_yards", scope="decade"),
    T("h_dt_wr_yds", DECADE_TOT, "career", "Name a WR with {t}+ receiving yards in the {scope}", (4000, 5000, 6000, 7000, 8000, 9000, 10000), "rec yds", pos="WR", stat="receiving_yards", scope="decade"),
    T("h_dt_te_yds", DECADE_TOT, "career", "Name a TE with {t}+ receiving yards in the {scope}", (2000, 3000, 4000, 5000, 6000), "rec yds", pos="TE", stat="receiving_yards", scope="decade"),
    T("h_dt_sacks", DECADE_TOT, "career", "Name a defender with {t}+ sacks in the {scope}", (40, 50, 60, 70, 80, 90, 100), "sacks", stat="def_sacks", scope="decade"),
    T("h_dt_int", DECADE_TOT, "career", "Name a defender with {t}+ interceptions in the {scope}", (15, 20, 25, 30, 35), "INT", stat="def_interceptions", scope="decade"),

    # ---- REPEAT SEASONS (how many seasons cleared a bar) ---------------------------------------------------------
    T("h_n_wr_1000", REPEAT, "nseas", "Name a WR with {nseasons} of 1,000+ receiving yards since 2000", (3, 4, 5, 6, 7, 8, 9, 10), "1,000-yd seasons", pos="WR", stat="receiving_yards", line=1000),
    T("h_n_rb_1000", REPEAT, "nseas", "Name a RB with {nseasons} of 1,000+ rushing yards since 2000", (2, 3, 4, 5, 6, 7, 8), "1,000-yd seasons", pos="RB", stat="rushing_yards", line=1000),
    T("h_n_qb_4000", REPEAT, "nseas", "Name a QB with {nseasons} of 4,000+ passing yards since 2000", (2, 3, 4, 5, 6, 8, 10, 12), "4,000-yd seasons", pos="QB", stat="passing_yards", line=4000),
    T("h_n_qb_30td", REPEAT, "nseas", "Name a QB with {nseasons} of 30+ touchdown passes since 2000", (2, 3, 4, 5, 6, 8, 10), "30-TD seasons", pos="QB", stat="passing_tds", line=30),
    T("h_n_sack10", REPEAT, "nseas", "Name a defender with {nseasons} of 10+ sacks since 2000", (2, 3, 4, 5, 6, 7, 8), "10-sack seasons", stat="def_sacks", line=10),
    T("h_n_te_700", REPEAT, "nseas", "Name a TE with {nseasons} of 700+ receiving yards since 2000", (2, 3, 4, 5, 6, 7), "700-yd seasons", pos="TE", stat="receiving_yards", line=700),
    T("h_n_td10", REPEAT, "nseas", "Name a player with {nseasons} of 10+ rushing and receiving TDs since 2000", (2, 3, 4, 5, 6, 7), "10-TD seasons", pos="SKILL", stat="tds", line=10),
    T("h_n_rec90", REPEAT, "nseas", "Name a WR with {nseasons} of 90+ catches since 2000", (2, 3, 4, 5, 6, 7, 8), "90-catch seasons", pos="WR", stat="receptions", line=90),
    T("h_n_int5", REPEAT, "nseas", "Name a defender with {nseasons} of 5+ interceptions since 2000", (2, 3, 4, 5), "5-INT seasons", stat="def_interceptions", line=5),

    # ---- BIG GAMES (one regular-season game since 2000) ----------------------------------------------------------
    _game("h_g_qb_yds", "QB", "passing_yards", (400, 425, 450, 475, 500), "pass yds in a game", "Name a QB who threw for {t}+ yards in a game since 2000"),
    _game("h_g_qb_td", "QB", "passing_tds", (5, 6, 7), "pass TD in a game", "Name a QB who threw {t}+ touchdown passes in a game of the {scope}", scope="decade"),
    _game("h_g_qb_rush", "QB", "rushing_yards", (100, 110, 120, 130, 140, 150), "rush yds in a game", "Name a QB who ran for {t}+ yards in a game since 2000"),
    _game("h_g_rb_yds", "RB", "rushing_yards", (190, 200, 210, 220, 230, 240, 250), "rush yds in a game", "Name a RB who ran for {t}+ yards in a game since 2000"),
    _game("h_g_rb_td", "RB", "tds", (4, 5, 6), "TD in a game", "Name a RB with {t}+ rushing and receiving TDs in a game since 2000"),
    _game("h_g_rb_rec", "RB", "receiving_yards", (130, 140, 150, 160, 180, 200), "rec yds in a game", "Name a RB with {t}+ receiving yards in a game since 2000"),
    _game("h_g_wr_yds", "WR", "receiving_yards", (190, 200, 210, 220, 230, 250), "rec yds in a game", "Name a WR with {t}+ receiving yards in a game since 2000"),
    _game("h_g_wr_rec", "WR", "receptions", (14, 15, 16, 17, 18, 20), "rec in a game", "Name a WR with {t}+ catches in a game since 2000"),
    _game("h_g_wr_td", "WR", "receiving_tds", (3, 4), "rec TD in a game", "Name a WR with {t}+ receiving TDs in a game of the {scope}", scope="decade"),
    _game("h_g_te_yds", "TE", "receiving_yards", (150, 160, 170, 180, 190, 200), "rec yds in a game", "Name a TE with {t}+ receiving yards in a game since 2000"),
    _game("h_g_ppr", "SKILL", "fpts", (50, 55, 60, 65, 70), "PPR pts in a game", "Name a player with a {t}+ PPR point game since 2000"),
    _game("h_g_sacks", None, "def_sacks", (3.5, 4, 4.5, 5), "sacks in a game", "Name a defender with {t}+ sacks in a game since 2000"),
    T("h_ng_qb_400", GAME, "ngame", "Name a QB with {t}+ games of 400+ passing yards since 2000", (1, 2, 3, 4, 5, 6), "400-yd games", pos="QB", cond=[("passing_yards", ">=", 400)]),
    T("h_ng_qb_5td", GAME, "ngame", "Name a QB with {t}+ games of 5+ touchdown passes since 2000", (1, 2, 3, 4, 5), "5-TD games", pos="QB", cond=[("passing_tds", ">=", 5)]),
    T("h_ng_rb_200", GAME, "ngame", "Name a RB with {t}+ games of 200+ rushing yards since 2000", (1, 2, 3, 4), "200-yd games", pos="RB", cond=[("rushing_yards", ">=", 200)]),
    T("h_ng_wr_200", GAME, "ngame", "Name a WR with {t}+ games of 200+ receiving yards since 2000", (1, 2, 3, 4), "200-yd games", pos="WR", cond=[("receiving_yards", ">=", 200)]),
    T("h_ng_wr_150", GAME, "ngame", "Name a WR with {t}+ games of 150+ receiving yards since 2000", (4, 5, 6, 7, 8, 9, 10, 12), "150-yd games", pos="WR", cond=[("receiving_yards", ">=", 150)]),
    T("h_ng_rb_150", GAME, "ngame", "Name a RB with {t}+ games of 150+ rushing yards since 2000", (4, 5, 6, 7, 8, 9, 10, 12), "150-yd games", pos="RB", cond=[("rushing_yards", ">=", 150)]),
    T("h_ng_sack3", GAME, "ngame", "Name a defender with {t}+ games of 3+ sacks since 2000", (2, 3, 4, 5, 6), "3-sack games", cond=[("def_sacks", ">=", 3)]),

    # ---- ROOKIE SEASONS (the season he was drafted; players drafted since 2000) ----------------------------------
    T("h_r_qb_yds", ROOKIE, "best", "Name a QB who threw for {t}+ yards as a rookie (drafted since 2000)", (2500, 2800, 3000, 3200, 3400, 3600, 3800, 4000), "pass yds", pos="QB", stat="passing_yards", rookie=True),
    T("h_r_qb_td", ROOKIE, "best", "Name a QB who threw {t}+ touchdown passes as a rookie (drafted since 2000)", (14, 16, 18, 20, 22, 24, 26, 28), "pass TD", pos="QB", stat="passing_tds", rookie=True),
    T("h_r_rb_yds", ROOKIE, "best", "Name a RB who ran for {t}+ yards as a rookie (drafted since 2000)", (800, 900, 1000, 1100, 1200, 1300, 1400, 1500), "rush yds", pos="RB", stat="rushing_yards", rookie=True),
    T("h_r_wr_yds", ROOKIE, "best", "Name a WR with {t}+ receiving yards as a rookie (drafted since 2000)", (600, 700, 800, 900, 1000, 1100, 1200, 1300), "rec yds", pos="WR", stat="receiving_yards", rookie=True),
    T("h_r_sacks", ROOKIE, "best", "Name a defender with {t}+ sacks as a rookie (drafted since 2000)", (7, 8, 9, 10, 11, 12, 14), "sacks", stat="def_sacks", rookie=True),
    T("h_r_int", ROOKIE, "best", "Name a defender with {t}+ interceptions as a rookie (drafted since 2000)", (3, 4, 5, 6, 7), "INT", stat="def_interceptions", rookie=True),

    # ---- DRAFT PEDIGREE (where a player was picked vs what he did) -----------------------------------------------
    T("h_p_r1_rb", PEDIGREE, "best", "Name a first-round pick who ran for {t}+ yards in a season since 2000", (1000, 1100, 1200, 1300, 1400, 1500, 1600), "rush yds", pos="RB", stat="rushing_yards", rd=(1, 1)),
    T("h_p_late_rb", PEDIGREE, "best", "Name a RB drafted in round 4 or later who ran for {t}+ yards in a season since 2000", (900, 1000, 1100, 1200, 1300, 1400), "rush yds", pos="RB", stat="rushing_yards", rd=(4, 7)),
    T("h_p_late_qb", PEDIGREE, "best", "Name a QB drafted in round 3 or later who threw for {t}+ yards in a season since 2000", (3000, 3200, 3400, 3500, 3800, 4000, 4200, 4500), "pass yds", pos="QB", stat="passing_yards", rd=(3, 7)),
    T("h_p_r1_wr", PEDIGREE, "best", "Name a first-round WR with {t}+ receiving yards in a season since 2000", (1200, 1300, 1400, 1500, 1600), "rec yds", pos="WR", stat="receiving_yards", rd=(1, 1)),
    T("h_p_r1_qb", PEDIGREE, "best", "Name a first-round QB who threw for {t}+ yards in a season since 2000", (3500, 4000, 4200, 4400, 4600, 4800), "pass yds", pos="QB", stat="passing_yards", rd=(1, 1)),
    T("h_p_late_sack", PEDIGREE, "best", "Name a defender drafted in round 3 or later with {t}+ sacks in a season since 2000", (10, 11, 12, 13, 14, 15), "sacks", stat="def_sacks", rd=(3, 7)),
    T("h_p_r2_te", PEDIGREE, "best", "Name a TE drafted in round 2 or later with {t}+ receiving yards in a season since 2000", (700, 800, 900, 1000, 1100), "rec yds", pos="TE", stat="receiving_yards", rd=(2, 7)),
]

# ---- THE NFL DRAFT (drafts 2000..last finished season; flags = the draft table's own HoF / All-Pro / Pro Bowl columns) ----
def _d(key, text, ladder=(0,), label="Pro Bowls", cat=DRAFT, **kw):
    return T(key, cat, "draft", text, ladder, label, **kw)


HISTORY_POOL += [
    _d("h_d_first_overall", "Name a #1 overall NFL draft pick since 2000", pick=(1, 1)),
    _d("h_d_slot", "Name a player taken with the {scope} overall pick since 2000", scope="slot", slots=list(range(1, 33))),
    _d("h_d_top5_dec", "Name a top-5 NFL draft pick of the {scope}", scope="decade", pick=(1, 5)),
    _d("h_d_year_r1", "Name a first-round pick in the {scope} NFL Draft", scope="year", rd=(1, 1)),
    _d("h_d_year_pb", "Name a player from the {scope} NFL Draft class{pb}", ladder=(1, 2, 3, 4, 5), scope="year"),
    _d("h_d_hof", "Name a Hall of Famer drafted since 2000", hof=True),
    _d("h_d_top10_pos", "Name {scope} taken in the top 10 of the draft since 2000{pb}", ladder=(0, 1, 2, 3, 4), scope="pos", pick=(1, 10)),
    _d("h_d_round", "Name a {scope}-round NFL draft pick since 2000{pb}", ladder=(1, 2, 3, 4, 5, 6, 8), scope="round", rounds=[2, 3, 4, 5, 6, 7]),
    _d("h_d_late_pos", "Name {scope} drafted in round 4 or later since 2000{pb}", ladder=(1, 2, 3, 4, 5), scope="pos", rd=(4, 7)),
    _d("h_d_r1_pos", "Name {scope} taken in the first round since 2000{pb}", ladder=(2, 3, 4, 5, 6, 7, 8), scope="pos", rd=(1, 1)),
    _d("h_d_r1_ap", "Name a first-round pick since 2000{ap}", ladder=(1, 2, 3, 4, 5, 6), val="allpro", rd=(1, 1), label="All-Pro"),
    _d("h_d_later_ap", "Name a player drafted after the first round since 2000{ap}", ladder=(1, 2, 3, 4, 5), val="allpro", rd=(2, 7), label="All-Pro"),
    _d("h_d_r1_dec_qb", "Name a QB taken in the first round of the {scope} drafts{pb}", ladder=(0, 1, 2, 3, 4), scope="decade", dpos="QB", rd=(1, 1)),
    _d("h_d_r1_dec_rb", "Name a running back taken in the first round of the {scope} drafts{pb}", ladder=(0, 1, 2, 3), scope="decade", dpos="RB", rd=(1, 1)),
    _d("h_d_r1_dec_wr", "Name a wide receiver taken in the first round of the {scope} drafts{pb}", ladder=(0, 1, 2, 3, 4), scope="decade", dpos="WR", rd=(1, 1)),
    _d("h_d_r12_dec_te", "Name a tight end taken in the first two rounds of the {scope} drafts{pb}", ladder=(0, 1, 2, 3), scope="decade", dpos="TE", rd=(1, 2)),
    _d("h_d_r1_dec_ol", "Name an offensive lineman taken in the first round of the {scope} drafts{pb}", ladder=(1, 2, 3, 4, 5), scope="decade", dpos="OL", rd=(1, 1)),
    _d("h_d_r1_dec_dl", "Name a defensive lineman taken in the first round of the {scope} drafts{pb}", ladder=(1, 2, 3, 4, 5), scope="decade", dpos="DL", rd=(1, 1)),
    _d("h_d_r1_dec_lb", "Name a linebacker taken in the first round of the {scope} drafts{pb}", ladder=(0, 1, 2, 3, 4), scope="decade", dpos="LB", rd=(1, 1)),
    _d("h_d_r1_dec_db", "Name a defensive back taken in the first round of the {scope} drafts{pb}", ladder=(0, 1, 2, 3, 4), scope="decade", dpos="DB", rd=(1, 1)),
    _d("h_d_late_dec", "Name a player drafted in round 5 or later in the {scope} drafts{pb}", ladder=(1, 2, 3, 4, 5, 6), scope="decade", rd=(5, 7)),
]

# ---- DRAFT: COLLEGES (the college rotates by date) -----------------------------------------------------------------
HISTORY_POOL += [
    _d("h_dc_pb", "Name a player from {scope} drafted since 2000{pb}", ladder=(0, 1, 2, 3, 4, 5, 6, 8), scope="college", cat=DRAFT_COL),
    _d("h_dc_r1", "Name a first-round pick from {scope} since 2000{pb}", ladder=(0, 1, 2, 3, 4), scope="college", rd=(1, 1), cat=DRAFT_COL),
    _d("h_dc_def", "Name a defender from {scope} drafted since 2000{pb}", ladder=(0, 1, 2, 3, 4, 5), scope="college", side="D", cat=DRAFT_COL),
    _d("h_dc_off", "Name an offensive player from {scope} drafted since 2000{pb}", ladder=(0, 1, 2, 3, 4, 5), scope="college", side="O", cat=DRAFT_COL),
    _d("h_dc_late", "Name a player from {scope} drafted after round 2 since 2000{pb}", ladder=(0, 1, 2, 3, 4), scope="college", rd=(3, 7), cat=DRAFT_COL),
]

# ---- DRAFT: TEAMS (the franchise rotates by date; draft-table team codes are mapped to today's franchise) ------------
HISTORY_POOL += [
    _d("h_dtm_pb", "Name a player the {scope} drafted since 2000{pb}", ladder=(1, 2, 3, 4, 5, 6), scope="team", cat=DRAFT_TEAM_CAT),
    _d("h_dtm_r1", "Name a first-round pick of the {scope} since 2000", scope="team", rd=(1, 1), cat=DRAFT_TEAM_CAT),
    _d("h_dtm_r1_pb", "Name a first-round pick of the {scope} since 2000{pb}", ladder=(1, 2, 3), scope="team", rd=(1, 1), cat=DRAFT_TEAM_CAT),
    _d("h_dtm_day2", "Name a player the {scope} drafted in rounds 2-4 since 2000{pb}", ladder=(1, 2, 3), scope="team", rd=(2, 4), cat=DRAFT_TEAM_CAT),
    _d("h_dtm_ap", "Name a player the {scope} drafted since 2000{ap}", ladder=(1, 2), scope="team", val="allpro", label="All-Pro", cat=DRAFT_TEAM_CAT),
]

# ---- DRAFT CAREERS (players drafted since 2000, so every career season is 2000 or later) ---------------------------
HISTORY_POOL += [
    _d("h_dk_qb_yds", "Name a QB drafted since 2000 with {t}+ career passing yards", ladder=(10000, 15000, 20000, 25000, 30000, 40000), dpos="QB", val="career:passing_yards", label="pass yds", cat=DRAFT_STAT, group="dk_career"),
    _d("h_dk_rb_yds", "Name a RB drafted since 2000 with {t}+ career rushing yards", ladder=(3000, 4000, 5000, 6000, 7000, 8000, 9000), dpos="RB", val="career:rushing_yards", label="rush yds", cat=DRAFT_STAT, group="dk_career"),
    _d("h_dk_wr_yds", "Name a WR drafted since 2000 with {t}+ career receiving yards", ladder=(5000, 6000, 7000, 8000, 9000, 10000, 12000), dpos="WR", val="career:receiving_yards", label="rec yds", cat=DRAFT_STAT, group="dk_career"),
    _d("h_dk_te_yds", "Name a TE drafted since 2000 with {t}+ career receiving yards", ladder=(2000, 3000, 4000, 5000, 6000), dpos="TE", val="career:receiving_yards", label="rec yds", cat=DRAFT_STAT, group="dk_career"),
    _d("h_dk_sacks", "Name a player drafted since 2000 with {t}+ career sacks", ladder=(50, 60, 70, 80, 90, 100), val="career:def_sacks", label="sacks", cat=DRAFT_STAT, group="dk_career"),
    _d("h_dk_int", "Name a player drafted since 2000 with {t}+ career interceptions", ladder=(20, 25, 30, 35, 40), val="career:def_interceptions", label="INT", cat=DRAFT_STAT, group="dk_career"),
]

# ---- PLAYOFFS AND SUPER BOWLS (postseason games since 2000; a Super Bowl is the last playoff week of a season) -------
def _po(key, kind, text, ladder, label, cat=PLAYOFF, **kw):
    return T(key, cat, kind, text, ladder, label, **kw)


HISTORY_POOL += [
    _po("h_po_qb_yds", "post", "Name a QB who threw for {t}+ yards in a playoff game since 2000", (300, 325, 350, 375, 400), "pass yds in a game", pos="QB", stat="passing_yards"),
    _po("h_po_qb_td", "post", "Name a QB who threw {t}+ touchdown passes in a playoff game since 2000", (3, 4, 5, 6), "pass TD in a game", pos="QB", stat="passing_tds"),
    _po("h_po_rb_yds", "post", "Name a RB who ran for {t}+ yards in a playoff game since 2000", (100, 110, 120, 130, 140, 150, 175, 200), "rush yds in a game", pos="RB", stat="rushing_yards"),
    _po("h_po_wr_yds", "post", "Name a WR with {t}+ receiving yards in a playoff game since 2000", (110, 120, 130, 140, 150, 160, 180), "rec yds in a game", pos="WR", stat="receiving_yards"),
    _po("h_po_te_yds", "post", "Name a TE with {t}+ receiving yards in a playoff game since 2000", (70, 80, 90, 100, 110, 120), "rec yds in a game", pos="TE", stat="receiving_yards"),
    _po("h_po_td_game", "post", "Name a player with {t}+ rushing and receiving TDs in a playoff game since 2000", (2, 3, 4), "TD in a game", pos="SKILL", stat="tds"),
    _po("h_po_sack_game", "post", "Name a defender with {t}+ sacks in a playoff game since 2000", (2, 2.5, 3, 3.5), "sacks in a game", stat="def_sacks"),
    _po("h_po_qb_300_n", "postn", "Name a QB with {t}+ playoff games of 300+ passing yards since 2000", (1, 2, 3, 4), "300-yd playoff games", pos="QB", cond=[("passing_yards", ">=", 300)]),
    _po("h_po_rb_100_n", "postn", "Name a RB with {t}+ playoff games of 100+ rushing yards since 2000", (1, 2, 3, 4), "100-yd playoff games", pos="RB", cond=[("rushing_yards", ">=", 100)]),
    _po("h_po_qb_sum", "postsum", "Name a QB with {t}+ career playoff passing yards since 2000", (1500, 2000, 2500, 3000, 4000, 5000, 6000), "playoff pass yds", pos="QB", stat="passing_yards"),
    _po("h_po_rb_sum", "postsum", "Name a RB with {t}+ career playoff rushing yards since 2000", (400, 500, 600, 700, 800, 1000, 1200), "playoff rush yds", pos="RB", stat="rushing_yards"),
    _po("h_po_wr_sum", "postsum", "Name a WR with {t}+ career playoff receiving yards since 2000", (500, 600, 700, 800, 1000, 1200), "playoff rec yds", pos="WR", stat="receiving_yards"),
    _po("h_po_te_sum", "postsum", "Name a TE with {t}+ career playoff receiving yards since 2000", (250, 300, 400, 500, 600, 800), "playoff rec yds", pos="TE", stat="receiving_yards"),
    _po("h_po_td_sum", "postsum", "Name a player with {t}+ career playoff rushing and receiving TDs since 2000", (4, 5, 6, 7, 8, 9, 10), "playoff TD", pos="SKILL", stat="tds"),
    _po("h_po_sack_sum", "postsum", "Name a defender with {t}+ career playoff sacks since 2000", (3, 4, 5, 6, 7, 8, 10), "playoff sacks", stat="def_sacks"),
    _po("h_po_int_sum", "postsum", "Name a defender with {t}+ career playoff interceptions since 2000", (2, 3, 4, 5), "playoff INT", stat="def_interceptions"),
    _po("h_po_dec_qb", "post", "Name a QB who threw for {t}+ yards in a playoff game of the {scope}", (275, 300, 325, 350, 375), "pass yds in a game", pos="QB", stat="passing_yards", scope="decade"),
    _po("h_po_dec_rb", "post", "Name a RB who ran for {t}+ yards in a playoff game of the {scope}", (90, 100, 110, 120, 130, 140, 150), "rush yds in a game", pos="RB", stat="rushing_yards", scope="decade"),
    _po("h_po_dec_wr", "post", "Name a WR with {t}+ receiving yards in a playoff game of the {scope}", (90, 100, 110, 120, 130, 140), "rec yds in a game", pos="WR", stat="receiving_yards", scope="decade"),
    _po("h_po_dec_td", "postn", "Name a player who scored a rushing or receiving TD in {t}+ playoff games of the {scope}", (2, 3, 4, 5, 6), "playoff TD games", pos="SKILL", cond=[("tds", ">=", 1)], scope="decade"),

    # ---- SUPER BOWLS (2000 season onward) ------------------------------------------------------------------------------------
    _po("h_sb_qb_played", "postn", "Name a QB who threw a pass in a Super Bowl since 2000", (1,), "Super Bowls", cat=SUPERBOWL, pos="QB", sb=True, cond=[("attempts", ">=", 1)]),
    _po("h_sb_qb_won", "postn", "Name a QB who threw a pass in a Super Bowl win since 2000", (1,), "Super Bowl wins", cat=SUPERBOWL, pos="QB", sb=True, won_sb=True, cond=[("attempts", ">=", 1)]),
    _po("h_sb_qb_lost", "postn", "Name a QB who threw a pass in a Super Bowl loss since 2000", (1,), "Super Bowl losses", cat=SUPERBOWL, pos="QB", sb=True, lost_sb=True, cond=[("attempts", ">=", 1)]),
    _po("h_sb_qb_yds", "post", "Name a QB who threw for {t}+ yards in a Super Bowl since 2000", (250, 275, 300, 325, 350), "pass yds", cat=SUPERBOWL, pos="QB", stat="passing_yards", sb=True),
    _po("h_sb_pass_td", "postn", "Name a QB who threw a touchdown pass in a Super Bowl since 2000", (1,), "Super Bowls with a pass TD", cat=SUPERBOWL, pos="QB", sb=True, cond=[("passing_tds", ">=", 1)]),
    _po("h_sb_td_dec", "postn", "Name a player who scored a rushing or receiving TD in a Super Bowl of the {scope}", (1,), "Super Bowls with a TD", cat=SUPERBOWL, pos="SKILL", sb=True, cond=[("tds", ">=", 1)], scope="decade"),
    _po("h_sb_rec_yds", "post", "Name a player with {t}+ receiving yards in a Super Bowl since 2000", (60, 70, 80, 90, 100, 110), "rec yds", cat=SUPERBOWL, pos="REC", stat="receiving_yards", sb=True),
    _po("h_sb_sack_dec", "postn", "Name a defender who sacked the QB in a Super Bowl of the {scope}", (1,), "Super Bowls with a sack", cat=SUPERBOWL, sb=True, cond=[("def_sacks", ">=", 1)], scope="decade"),
    _po("h_sb_int", "postn", "Name a defender who intercepted a pass in a Super Bowl win since 2000", (1,), "Super Bowl wins with an INT", cat=SUPERBOWL, sb=True, won_sb=True, cond=[("def_interceptions", ">=", 1)]),
    _po("h_sb_k", "postn", "Name a kicker who made a field goal in a Super Bowl since 2000", (1,), "Super Bowls with a FG", cat=SUPERBOWL, pos="K", sb=True, cond=[("fg_made", ">=", 1)]),
    _po("h_sb_rb_champ", "postn", "Name a RB who carried the ball 5+ times in a Super Bowl win since 2000", (1,), "Super Bowl wins", cat=SUPERBOWL, pos="RB", sb=True, won_sb=True, cond=[("carries", ">=", 5)]),
    _po("h_sb_wr_champ", "postn", "Name a receiver (WR, TE or RB) with 60+ receiving yards in a Super Bowl win since 2000", (1,), "Super Bowl wins", cat=SUPERBOWL, pos="REC", sb=True, won_sb=True, cond=[("receiving_yards", ">=", 60)]),
]

# ---- TEAM HISTORY (the franchise rotates by date; players only) -----------------------------------------------------------
def _tm(key, kind, text, ladder, label, **kw):
    return T(key, TEAMHIST, kind, text, ladder, label, scope="team", **kw)


HISTORY_POOL += [
    _tm("h_t_rb", "best", "Name a RB who ran for {t}+ yards in a season for the {scope} since 2000", (400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300), "rush yds", pos="RB", stat="rushing_yards"),
    _tm("h_t_wr", "best", "Name a WR with {t}+ receiving yards in a season for the {scope} since 2000", (600, 700, 800, 900, 1000, 1100, 1200), "rec yds", pos="WR", stat="receiving_yards"),
    _tm("h_t_qb", "best", "Name a QB who threw for {t}+ yards in a season for the {scope} since 2000", (1000, 1500, 2000, 2500, 3000, 3500, 4000), "pass yds", pos="QB", stat="passing_yards"),
    _tm("h_t_te", "best", "Name a TE with {t}+ receiving yards in a season for the {scope} since 2000", (200, 250, 300, 400, 500, 600, 700, 800), "rec yds", pos="TE", stat="receiving_yards"),
    _tm("h_t_sacks", "best", "Name a defender with {t}+ sacks in a season for the {scope} since 2000", (4, 5, 6, 7, 8, 9, 10, 12), "sacks", stat="def_sacks"),
    _tm("h_t_int", "best", "Name a defender with {t}+ interceptions in a season for the {scope} since 2000", (2, 3, 4, 5, 6), "INT", stat="def_interceptions"),
    _tm("h_t_td", "best", "Name a player with {t}+ rushing and receiving TDs in a season for the {scope} since 2000", (4, 5, 6, 7, 8, 9, 10, 12), "rush + rec TD", pos="SKILL", stat="tds"),
    _tm("h_t_c_rush", "career", "Name a player with {t}+ rushing yards for the {scope} since 2000", (1000, 1500, 2000, 2500, 3000, 4000, 5000), "rush yds", pos="SKILL", stat="rushing_yards"),
    _tm("h_t_c_rec", "career", "Name a player with {t}+ receiving yards for the {scope} since 2000", (1500, 2000, 3000, 4000, 5000, 6000), "rec yds", pos="SKILL", stat="receiving_yards"),
    _tm("h_t_c_sacks", "career", "Name a defender with {t}+ sacks for the {scope} since 2000", (15, 20, 25, 30, 35, 40, 50), "sacks", stat="def_sacks"),
]


# ---- EASY DAYS (owner 2026-11-17): warm-up questions anyone can answer, still with deep cuts at the bottom ----------
# The hand-picked round lines a casual fan knows (a 4,000-yard season, a 1,000-yard season, 10+ sacks). Only these ever
# make an easy-band question (dd.band_rungs); medium and hard walk the template's own ladder, which is unchanged, so the
# days before dd.VARIETY_START are unchanged too.
EASY_LINES = {
    "h_qb_pass_yds": (4000,), "h_qb_pass_td": (30,), "h_rb_rush_yds": (1000, 1200), "h_rb_rush_td": (10,),
    "h_wr_rec_yds": (1000, 1200), "h_wr_rec": (90, 100), "h_wr_rec_td": (10,), "h_te_rec_yds": (800, 1000), "h_sacks": (10, 12),
    "h_c_qb_yds": (20000, 30000), "h_c_rb_yds": (5000, 7000), "h_c_wr_yds": (7000, 8000, 10000), "h_c_sacks": (50, 80),
    "h_n_wr_1000": (2,), "h_n_rb_1000": (2,), "h_n_qb_4000": (2,), "h_t_catches": (25, 50, 100), "h_t_c_rec": (1000, 2000),
    "h_t_c_rush": (1000, 2000), "h_d_r1_pos": (0,), "h_d_r1_recent": (0,), "h_dc_r1": (0,), "h_dc_pb": (0,),
    "h_sb_qb_played": (1,), "h_po_qb_yds": (300,), "h_ng_qb_400": (1,),
}
WARMUPS = {"h_sb_qb_played"}                    # a Super Bowl QB is a warm-up even with ~40 answers
HISTORY_POOL += [
    _tm("h_t_catches", "career", "Name a player with {t}+ catches for the {scope} since 2000", (10, 25, 50, 75, 100, 150, 200, 300),
        "rec", pos="SKILL", stat="receptions"),
    _d("h_d_r1_recent", "Name a first-round pick since 2020{pb}", ladder=(0, 1, 2, 3), since=2020, rd=(1, 1)),
]
for _tpl in HISTORY_POOL:
    if _tpl["key"] in EASY_LINES:
        _tpl["easy_lines"] = EASY_LINES[_tpl["key"]]
    if _tpl["key"] in WARMUPS:
        _tpl["warmup"] = True
