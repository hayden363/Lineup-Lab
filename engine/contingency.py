"""
CONTINGENCY PROJECTIONS — what a teammate's absence does to everyone else
=========================================================================
A player listed Questionable has two futures: he plays and scores his
projection, or he sits and his work goes to his teammates. This module prices
the second future from what actually happened in past games where a regular
missed one.

Measured, not assumed (2023-2025 plus this season's weeks so far):
  An "absence" is a team-week where a player who carried at least 22% of his
  team's rushing attempts or 12% of its targets over the previous three team
  games (and played the one before) has no stat line, and no other regular
  missed the same game. For each absence we take every teammate's share of the
  team's targets and carries that week against his own previous-three-game
  share. The shares sum to 1, so the shares the absent player vacated reappear
  somewhere: with same-position teammates, other positions, or players with no
  recent role ("new" faces). The pooled split is the table
  absorption(). Typical result: a WR1 out sends most of his targets to the
  other WRs, a smaller piece to the TE and RB, and a visible chunk to players
  who had no role.

Applied to a live teammate:
  1. The absent player's recent share of team targets and carries is averaged
     over the last four team games with a zero for each one he missed. That
     matches the window the teammate's baseline is built from, so work the
     baseline already reflects (he missed two of the last four) is not counted
     twice.
  2. The slice his position group absorbs is split among the group by current
     share (the pooled split says how much goes to a group, not who inside it;
     proportional to current role is the assumption).
  3. Extra targets and carries become points at what a target and a carry are
     worth for that position under the viewer's scoring (a no-intercept
     regression of this season's fantasy points on targets and carries).
  4. The expected uplift is probability(out) x uplift: 1.0 for Out/IR/PUP/Sus,
     1 - P(play) for Questionable/Doubtful (engine/play_prob).

QB absences are not modelled: a backup quarterback changes the whole offence,
which a share table cannot price.
"""

import threading

import numpy as np
import pandas as pd

from . import history
from .scoring import apply_scoring

LOOKBACK = 3                      # prior team games the "regular" test and baseline shares use
WINDOW = 4                        # team games the live absent-player share is averaged over
REGULAR = {"targets": 0.12, "carries": 0.22}
GROUPS = ("RB", "WR", "TE", "QB")
SKILL = ("RB", "WR", "TE")        # positions that receive an uplift
UPLIFT_CAP = 0.50                 # an absence can add at most half a teammate's baseline
MIN_SHARE = 0.03                  # ignore absent players with less than this much of the volume

_LOCK = threading.Lock()
_CACHE = {}


def _games_frame(wk):
    """One row per player-game across history and this season: season, week,
    team, player_id, position, targets, carries."""
    cols = ["season", "week", "recent_team", "player_id", "position", "targets", "carries"]
    parts = []
    skill = history._frames()["skill"]
    if not skill.empty:
        parts.append(skill[[c for c in cols if c in skill.columns]])
    cur = wk[[c for c in cols if c in wk.columns]]
    if "season_type" in wk.columns:
        cur = cur[wk["season_type"] == "REG"]
    parts.append(cur)
    df = pd.concat(parts, ignore_index=True)
    df[["targets", "carries"]] = df[["targets", "carries"]].fillna(0.0).astype(float)
    return df[df["position"].isin(GROUPS)]


def _share_table(df):
    """{(season, team): (weeks, {stat: DataFrame players x weeks of team share},
    played DataFrame players x weeks of 0/1, position Series)}"""
    out = {}
    for (season, team), g in df.groupby(["season", "recent_team"]):
        weeks = sorted(g["week"].unique())
        if len(weeks) < LOOKBACK + 1:
            continue
        played = g.pivot_table(index="player_id", columns="week", values="targets", aggfunc="size").reindex(columns=weeks)
        played = played.notna().astype(float)
        share = {}
        for stat in ("targets", "carries"):
            piv = g.pivot_table(index="player_id", columns="week", values=stat, aggfunc="sum").reindex(columns=weeks).fillna(0.0)
            tot = piv.sum(axis=0).replace(0, np.nan)
            share[stat] = (piv / tot).fillna(0.0)
        pos = g.drop_duplicates("player_id").set_index("player_id")["position"]
        out[(season, team)] = (weeks, share, played, pos)
    return out


def measure_absorption(df):
    """Pool every qualifying absence in `df` (see module doc) into
    {(absent_position, stat): {"RB": f, "WR": f, "TE": f, "QB": f, "new": f, "events": n, "share": s}}
    where f is the fraction of the absent player's vacated share that
    landed with that group. Fractions sum to 1 per cell."""
    traded = df.groupby(["season", "player_id"])["recent_team"].nunique()
    traded = set(traded[traded > 1].index)
    acc = {}
    for (season, team), (weeks, share, played, pos) in _share_table(df).items():
        for j in range(LOOKBACK, len(weeks)):
            prior = weeks[j - LOOKBACK:j]
            now = weeks[j]
            absent = [p for p in played.index if played.at[p, now] == 0 and played.at[p, prior[-1]] == 1
                      and (season, p) not in traded]
            if not absent:
                continue
            base_all = {stat: share[stat][prior].mean(axis=1) for stat in REGULAR}
            reg = {}
            for p in absent:
                hit = [stat for stat, thr in REGULAR.items() if base_all[stat][p] >= thr]
                if hit:
                    reg[p] = hit
            minor = [p for p in absent if p not in reg
                     and any(base_all[stat][p] >= 0.5 * thr for stat, thr in REGULAR.items())]
            if len(reg) != 1 or minor:
                continue            # none, or more than one, notable player missing: the split would be confounded
            (pid, stats), = reg.items()
            apos = pos[pid]
            if apos not in SKILL:
                continue
            for stat in stats:
                base = base_all[stat]
                s_a = float(base[pid])
                delta = (share[stat][now] - base).drop(pid)
                cell = acc.setdefault((apos, stat), {"RB": 0.0, "WR": 0.0, "TE": 0.0, "QB": 0.0, "new": 0.0, "share": 0.0, "events": 0})
                for q, d in delta.items():
                    has_role = bool(played.loc[q, prior].sum() > 0)
                    cell[pos[q] if has_role and pos[q] in GROUPS else "new"] += float(d)
                cell["share"] += s_a
                cell["events"] += 1
    table = {}
    for key, c in acc.items():
        if c["events"] < 5 or c["share"] <= 0:
            continue
        parts = {k: c[k] / c["share"] for k in ("RB", "WR", "TE", "QB", "new")}
        table[key] = {**parts, "events": c["events"], "share": round(c["share"] / c["events"], 3)}
    return table


def absorption(wk):
    """The pooled table for this season's data plus history, cached on the row
    count of the weekly frame (it grows each week)."""
    key = ("absorb", len(wk), len(history._frames()["skill"]))
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    table = measure_absorption(_games_frame(wk))
    with _LOCK:
        for k in [k for k in _CACHE if k[0] == "absorb"]:
            del _CACHE[k]
        _CACHE[key] = table
    return table


def points_per_opportunity(wk, scoring):
    """{position: (points per target, points per carry)} from a no-intercept
    regression of this season's scored fantasy points on targets and carries."""
    key = ("ppo", len(wk), tuple(sorted(scoring.items())) if scoring else None)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    out = {}
    scored, _ = apply_scoring(wk[wk["position"].isin(SKILL)], scoring)
    for pos, g in scored.groupby("position"):
        g = g[(g["targets"].fillna(0) + g["carries"].fillna(0)) > 0]
        if len(g) < 30:
            continue
        x = g[["targets", "carries"]].fillna(0).to_numpy(float)
        coef, *_ = np.linalg.lstsq(x, g["fpts_active"].to_numpy(float), rcond=None)
        out[pos] = (max(0.0, float(coef[0])), max(0.0, float(coef[1])))
    with _LOCK:
        if len(_CACHE) > 24:
            _CACHE.clear()
        _CACHE[key] = out
    return out


def recent_shares(wk, team, season, window=WINDOW):
    """(team targets/game, team carries/game, DataFrame of each player's mean
    share over the team's last `window` games, zeros for games missed, position)
    for the live season."""
    g = wk[(wk["recent_team"] == team) & (wk["season"] == season)]
    if "season_type" in g.columns:
        g = g[g["season_type"] == "REG"]
    weeks = sorted(g["week"].unique())[-window:]
    if not weeks:
        return None
    g = g[g["week"].isin(weeks)]
    tt = g.groupby("week")["targets"].sum()
    tc = g.groupby("week")["carries"].sum()
    rows = {}
    for stat, tot in (("targets", tt), ("carries", tc)):
        piv = g.pivot_table(index="player_id", columns="week", values=stat, aggfunc="sum").reindex(columns=weeks).fillna(0.0)
        rows[stat] = (piv / tot.reindex(weeks).replace(0, np.nan)).fillna(0.0).mean(axis=1)
    shares = pd.DataFrame(rows)
    pos = g.drop_duplicates("player_id").set_index("player_id")["position"]
    return float(tt.mean()), float(tc.mean()), shares, pos


def p_out(status, p_play):
    """Chance a listed teammate misses the next game."""
    if status in ("Out", "IR", "PUP", "Sus", "NA"):
        return 1.0
    if status in ("Questionable", "Doubtful") and p_play is not None:
        return float(np.clip(1.0 - p_play, 0.0, 1.0))
    return 0.0


def uplift(wk, scoring, team, season, target_id, target_pos, absent_id, absent_pos, baseline):
    """Points per game the target gains if `absent_id` does not play, or None
    when the pair can't be priced. Returns {"points", "targets", "carries",
    "share"} where share is the absent player's recent hold on the volume."""
    if target_pos not in SKILL or absent_pos not in SKILL or target_id == absent_id:
        return None
    rs = recent_shares(wk, team, season)
    table = absorption(wk)
    ppo = points_per_opportunity(wk, scoring).get(target_pos)
    if rs is None or ppo is None or absent_id not in rs[2].index:
        return None
    t_tgt, t_car, shares, pos = rs
    gain = {"targets": 0.0, "carries": 0.0}
    for stat, volume in (("targets", t_tgt), ("carries", t_car)):
        cell = table.get((absent_pos, stat))
        s_a = float(shares.at[absent_id, stat])
        if not cell or s_a <= 0:
            continue
        members = shares[(pos.reindex(shares.index) == target_pos) & (shares.index != absent_id)][stat]
        if target_id not in members.index or members.sum() <= 0:
            continue
        mine = float(members[target_id]) / float(members.sum())
        gain[stat] = max(0.0, cell[target_pos]) * s_a * mine * volume   # a noisy negative cell means no uplift, not a penalty
    pts = gain["targets"] * ppo[0] + gain["carries"] * ppo[1]
    cap = UPLIFT_CAP * max(float(baseline), 0.0)
    pts = min(pts, cap)
    if pts <= 0.05:
        return None
    return {"points": round(pts, 2), "targets": round(gain["targets"], 2), "carries": round(gain["carries"], 2),
            "share": round(max(float(shares.at[absent_id, "targets"]), float(shares.at[absent_id, "carries"])), 3)}
