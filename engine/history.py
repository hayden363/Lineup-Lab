"""
HISTORY — what each player (and defense, and kicker) has done before this season
================================================================================
Projections used to know one season. This module adds the three before it
(history_data/*.parquet, built by scripts/build_history.py) and turns them
into four things:

  career rate    per-game fantasy points over prior seasons, newest weighted
                 most (SEASON_WEIGHTS). Scored under the VIEWER'S league
                 scoring, never a stored PPR number.
  prior          that career rate pulled toward the position average by how
                 few games back it rests on. A rookie has no history, so his
                 prior is the position average and nothing changes for him.
  blend          this season's rate shrunk toward the prior. The prior counts
                 as BASE_K games of evidence with no history, up to
                 BASE_K + HIST_K with a full one (HIST_FULL weighted games).
  steadiness     the same prior idea for game-to-game spread (cv).

It also answers two look-back questions for the player card: his season-by-
season line, and how he has scored against one specific opponent.

Every weight here is a judgment call, not fitted to data (the README says so
for the other model weights too). Players who changed teams or roles carry
old numbers; the shrinkage limits that but does not remove it.
"""

import json
import os
import threading

import numpy as np
import pandas as pd

from .scoring import ScoringSettings, apply_scoring

HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history_data")
LOOKBACK = 3
REG_SEASON_LAST_WEEK = 18   # history is regular-season games; playoff rows (weeks 19-22) are dropped on load
SEASON_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.5}   # years before the current season -> weight

BASE_K = 3.0          # prior's weight in games with no history (matches board.SHRINK_GAMES)
HIST_K = 4.0          # extra prior weight a full history earns
HIST_FULL = 24.0      # weighted games that count as a "full" history
K_HIST_K = 1.5        # kickers and defenses repeat less year to year: lower ceiling
DEF_HIST_K = 1.5

H2H_SHRINK = 12.0     # games against one opponent needed to trust it half way
H2H_CAP = 0.08        # head-to-head factor stays within +/-8%
H2H_MIN_GAMES = 2

_LOCK = threading.Lock()
_FRAMES = {}
_SCORED = {}
_SCORED_LIMIT = 16


def _frames():
    """The three history tables, loaded once. Missing files give empty tables,
    so a deploy without history_data simply projects the way it used to."""
    if _FRAMES:
        return _FRAMES
    with _LOCK:
        if _FRAMES:
            return _FRAMES
        for name in ("skill", "kicker", "defense"):
            path = os.path.join(HISTORY_DIR, f"{name}_weekly.parquet")
            try:
                df = pd.read_parquet(path)
                # The kicker and defense tables were built from play-by-play with the playoffs still in
                # them (the skill table never had them). A playoff game is by a better-than-average team
                # and would lift next season's prior for exactly those teams.
                _FRAMES[name] = df[df["week"] <= REG_SEASON_LAST_WEEK].reset_index(drop=True)
            except Exception as e:
                print(f"[history] {name} unavailable ({e}); projections run without it")
                _FRAMES[name] = pd.DataFrame()
    return _FRAMES


def available():
    return not _frames()["skill"].empty


def _weight(season, current):
    return SEASON_WEIGHTS.get(int(current) - int(season), 0.0)


def _key(obj):
    return json.dumps(obj, sort_keys=True, default=str)


def _cached(key, build):
    if key in _SCORED:
        return _SCORED[key]
    val = build()
    with _LOCK:
        if len(_SCORED) >= _SCORED_LIMIT:
            _SCORED.clear()
        _SCORED[key] = val
    return val


def _scored_skill(scoring, current):
    """Prior-season QB/RB/WR/TE games under this scoring, with a season weight."""
    def build():
        df = _frames()["skill"]
        if df.empty:
            return df
        df = df[df["season"] < int(current)]
        df, _ = apply_scoring(df, scoring)
        df["w"] = df["season"].map(lambda s: _weight(s, current))
        # keep only what the look-ups read: one scored copy per scoring setting
        # is cached, and the raw counting stats are most of the frame's size
        keep = ["player_id", "position", "season", "week", "recent_team", "opponent_team", "fpts_active", "w"]
        return df.loc[df["w"] > 0, keep].reset_index(drop=True)
    return _cached(("skill", _key(scoring), int(current)), build)


def _scored_kicker(k_settings, current):
    def build():
        from .kicker_scoring import score_kicker_weekly
        df = _frames()["kicker"]
        if df.empty:
            return df
        df = df[df["season"] < int(current)].copy()
        df["fpts_active"] = score_kicker_weekly(df, k_settings)
        df["w"] = df["season"].map(lambda s: _weight(s, current))
        return df[df["w"] > 0].reset_index(drop=True)
    return _cached(("kicker", _key(k_settings), int(current)), build)


def _scored_defense(def_settings, current):
    def build():
        from .defense_scoring import score_defense_weekly
        df = _frames()["defense"]
        if df.empty:
            return df
        df = df[df["season"] < int(current)].copy()
        df["fpts_active"] = score_defense_weekly(df, def_settings)
        df["w"] = df["season"].map(lambda s: _weight(s, current))
        return df[df["w"] > 0].reset_index(drop=True)
    return _cached(("defense", _key(def_settings), int(current)), build)


# ---- career table ----------------------------------------------------------
def _career(df, id_col):
    """One row per id: weighted games h, weighted per-game points, pooled
    game-to-game cv, plain game count and seasons played."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["h", "ppg", "cv", "games", "seasons"])
    per = (df.groupby([id_col, "season"])
             .agg(count=("fpts_active", "count"), mean=("fpts_active", "mean"),
                  var=("fpts_active", "var"), w=("w", "first")).reset_index())
    per["var"] = per["var"].fillna(0.0)
    per["wg"] = per["w"] * per["count"]
    per["wmean"] = per["wg"] * per["mean"]
    per["wvar"] = per["w"] * (per["count"] - 1).clip(lower=0) * per["var"]
    per["wdf"] = per["w"] * (per["count"] - 1).clip(lower=0)
    g = per.groupby(id_col)
    out = pd.DataFrame({
        "h": g["wg"].sum(),
        "games": g["count"].sum(),
        "seasons": g["season"].nunique(),
        "_sum": g["wmean"].sum(),
        "_var": g["wvar"].sum(),
        "_df": g["wdf"].sum(),
    })
    out["ppg"] = out["_sum"] / out["h"]
    out["cv"] = np.sqrt(out["_var"] / out["_df"].replace(0, np.nan)) / out["ppg"].where(out["ppg"] > 0)
    return out[["h", "ppg", "cv", "games", "seasons"]]


def skill_career(position, scoring, current):
    def build():
        df = _scored_skill(scoring, current)
        return _career(df[df["position"] == position] if not df.empty else df, "player_id")
    return _cached(("career", position, _key(scoring), int(current)), build)


def kicker_career(k_settings, current):
    return _cached(("kcareer", _key(k_settings), int(current)),
                   lambda: _career(_scored_kicker(k_settings, current), "player_id"))


def defense_career(def_settings, current):
    return _cached(("dcareer", _key(def_settings), int(current)),
                   lambda: _career(_scored_defense(def_settings, current), "defteam"))


# ---- the blend --------------------------------------------------------------
def blend(cur_rate, n_games, career, pool_mean, base_k=BASE_K, hist_k=HIST_K):
    """This season's per-game rate pulled toward a history-aware prior.

    cur_rate, n_games  Series indexed by id (this season)
    career             _career() table
    pool_mean          position average used when a player has no history

    Returns (rate, history_weight): the blended rate and the share of it that
    came from history (0 with none)."""
    c = career.reindex(cur_rate.index)
    h = c["h"].fillna(0.0)
    ppg = c["ppg"].where(c["h"].notna(), pool_mean).fillna(pool_mean)
    prior = (h * ppg + base_k * pool_mean) / (h + base_k)
    k = base_k + hist_k * (h / HIST_FULL).clip(upper=1.0)
    n = n_games.astype(float)
    rate = (n * cur_rate + k * prior) / (n + k)
    hist_share = (k / (n + k)) * (h / (h + base_k))
    return rate, hist_share.fillna(0.0)


def blend_cv(cur_cv, n_games, hist_cv, hist_games):
    """Game-to-game spread over this season plus history, weighted by games.
    Falls back to whichever exists."""
    have_cur = cur_cv is not None and not pd.isna(cur_cv) and n_games
    have_hist = hist_cv is not None and not pd.isna(hist_cv) and hist_games
    if have_cur and have_hist:
        return (n_games * float(cur_cv) + hist_games * float(hist_cv)) / (n_games + hist_games)
    if have_hist:
        return float(hist_cv)
    return float(cur_cv) if have_cur else None


# ---- look-back for the card -------------------------------------------------
def _num(v, nd=1):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def player_seasons(player_id, position, scoring, current):
    """Season-by-season line for the card: games, PPG, best/worst game, spread."""
    df = _scored_skill(scoring, current)
    if df.empty:
        return []
    mine = df[(df["player_id"] == player_id)]
    out = []
    for season, g in mine.groupby("season"):
        pts = g["fpts_active"]
        out.append({
            "season": int(season), "games": int(len(g)), "ppg": _num(pts.mean()),
            "best": _num(pts.max()), "worst": _num(pts.min()),
            "std": _num(pts.std(ddof=0)),
            "team": g.sort_values("week")["recent_team"].iloc[-1],
            "total": _num(pts.sum(), 0),
        })
    return sorted(out, key=lambda r: -r["season"])


def player_games(player_id, scoring, current):
    """Every prior-season game as {season, week, opponent, points}, oldest first."""
    df = _scored_skill(scoring, current)
    if df.empty:
        return []
    mine = df[df["player_id"] == player_id].sort_values(["season", "week"])
    return [{"season": int(r.season), "week": int(r.week), "opponent": r.opponent_team,
             "points": round(float(r.fpts_active), 1)}
            for r in mine.itertuples(index=False) if isinstance(r.opponent_team, str)]


def defense_ranks(position, scoring, current):
    """For each past season: opponent -> (rank, n) by fantasy points allowed per
    game to this position, 1 = most generous (easiest). Computed from the
    stored games themselves, so past games can be tagged soft / neutral / tough
    the same way this season's are."""
    def build():
        df = _scored_skill(scoring, current)
        if df.empty:
            return {}
        df = df[df["position"] == position]
        ranks = {}
        for season, g in df.groupby("season"):
            # points allowed per defense per game, summed over the position's
            # players that week, averaged over the weeks played
            week_tot = g.groupby(["opponent_team", "week"])["fpts_active"].sum()
            per = week_tot.groupby("opponent_team").mean().sort_values(ascending=False)
            n = len(per)
            ranks[int(season)] = {team: (i + 1, n) for i, team in enumerate(per.index)}
        return ranks
    return _cached(("dranks", position, _key(scoring), int(current)), build)


def tag_games(games, position, scoring, current, tier_fn):
    """Attach each past game's difficulty tier (tier_fn(rank, n))."""
    ranks = defense_ranks(position, scoring, current)
    out = []
    for g in games:
        rank, n = ranks.get(g["season"], {}).get(g["opponent"], (None, None))
        out.append({**g, "rank": rank, "tier": tier_fn(rank, n)})
    return out


def versus(games, opponent):
    """How he has scored against one team across prior seasons."""
    mine = [g for g in games if g["opponent"] == opponent]
    if not mine:
        return None
    pts = [g["points"] for g in mine]
    return {"games": len(mine), "avg": round(sum(pts) / len(pts), 1),
            "best": max(pts), "worst": min(pts),
            "last": {"season": mine[-1]["season"], "week": mine[-1]["week"], "points": mine[-1]["points"]}}


def h2h_factor(games, opponent, baseline_ppg):
    """Multiplier for one opponent from his own history against them.

    His average vs that team over his average across the same seasons, pulled
    hard toward 1.0 by how few games there are (H2H_SHRINK) and capped at
    +/-H2H_CAP. One or zero meetings return 1.0. A coordinator or scheme
    change makes this weaker evidence than it looks, which is why it is small."""
    mine = [g for g in games if g["opponent"] == opponent]
    if len(mine) < H2H_MIN_GAMES or not baseline_ppg or baseline_ppg <= 0:
        return 1.0
    seasons = {g["season"] for g in mine}
    same = [g["points"] for g in games if g["season"] in seasons]
    ref = sum(same) / len(same) if same else baseline_ppg
    if ref <= 0:
        return 1.0
    raw = (sum(g["points"] for g in mine) / len(mine)) / ref - 1.0
    shrink = len(mine) / (len(mine) + H2H_SHRINK)
    return round(1.0 + max(-H2H_CAP, min(H2H_CAP, raw * shrink)), 3)


def weighted_career(position, scoring, current, player_id):
    """The career row for one player, or None."""
    t = skill_career(position, scoring, current)
    return t.loc[player_id].to_dict() if player_id in t.index else None


def summary(player_id, position, scoring, current, weight=None):
    """The card's history block: season lines, career rate, and how much of the
    projection rests on history (None when there is nothing on file)."""
    career = weighted_career(position, scoring, current, player_id)
    seasons = player_seasons(player_id, position, scoring, current)
    if not seasons:
        return {"seasons": [], "career_ppg": None, "career_games": 0, "weight": 0.0, "lookback": LOOKBACK}
    return {
        "seasons": seasons,
        "career_ppg": None if not career else round(float(career["ppg"]), 1),
        "career_games": 0 if not career else int(career["games"]),
        "weight": None if weight is None or pd.isna(weight) else round(float(weight), 2),
        "lookback": LOOKBACK,
    }
