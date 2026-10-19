"""
START/SIT CONTEXT — the game environment and usage behind a projection
=========================================================================
Three things the base projection (season rate x form x defensive matchup)
doesn't know, all from data already in the schedule and weekly tables:

  * game_context     the betting-market view of this game: implied team total,
                     expected margin, roof, and (when published) wind/temp
  * environment_factor   a small, capped multiplier from that view
  * usage_trend      last-3-games opportunity vs. his own earlier games

The multiplier is deliberately modest (never more than +/-10%): market totals
and spreads are real information about volume, but they are not a substitute
for the player's own rate. The caps and the exact rules are below so any
number can be recomputed by hand.

Honest limits, so nobody mistakes them for features:
  * The schedule feed carries lines only for the nearest games, so games a few
    weeks out come back without them and get no adjustment.
  * Weather for upcoming outdoor games is a forecast at kickoff (engine/
    weather.py, Open-Meteo, about 15 days out); played games use the
    schedule's recorded wind and temperature.
  * No shadow-coverage, route-participation or practice-report data exists in
    the free feeds, so none is modelled or implied.
"""

import numpy as np
import pandas as pd

from . import weather

LEAGUE_AVG_TEAM_TOTAL = 22.5
ENV_MIN, ENV_MAX = 0.90, 1.10
PASS_CATCHERS = ("QB", "WR", "TE")


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else float(v)


def game_context(schedule, team, week, with_weather=True):
    """The market view of `team`'s game in `week`, or None if no such game.
    margin > 0 means the team is the favourite by that many points. Lines come
    back None when the feed doesn't have them yet (see module docstring)."""
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    g = s[(s["week"] == week) & ((s["home_team"] == team) | (s["away_team"] == team))]
    if g.empty:
        return None
    g = g.iloc[0]
    home = g["home_team"] == team
    spread = _num(g.get("spread_line"))   # nflverse: positive = home team favoured
    total = _num(g.get("total_line"))
    margin = None if spread is None else (spread if home else -spread)
    implied = None if (total is None or margin is None) else round((total + margin) / 2, 1)
    roof = g.get("roof") if isinstance(g.get("roof"), str) else None
    wind, temp = _num(g.get("wind")), _num(g.get("temp"))
    wx = None
    if wind is None and with_weather:
        wx = weather.kickoff_forecast(g.get("stadium_id"), roof, g.get("gameday"), g.get("gametime"))
    elif wind is not None or temp is not None:
        idx, label, why = weather.degradation(wind, None, None, temp)
        wx = {"temp": temp, "wind": wind, "index": idx, "label": label, "reasons": why, "maybe_closed": False}
    return {
        "week": int(week), "opponent": g["away_team"] if home else g["home_team"], "home": bool(home),
        "game_total": total, "margin": margin, "implied_total": implied,
        "roof": roof, "weather": wx,
        "wind": wx["wind"] if wx else wind, "temp": wx["temp"] if wx else temp,
        "gameday": g.get("gameday"), "gametime": g.get("gametime"),
    }


def environment_factor(position, ctx, target_share=None):
    """(multiplier, notes) for one player from his game's context.

      * Team total: +/-35% of the gap between the implied total and the league
        average of 22.5, so a 28-point implied total is about +7% (capped).
      * Game script: trailing by 4+ pushes volume to the air: QB/WR/TE gain 2%
        per 3 points past 3 (cap +4%); RBs lose the same, half as much if he is
        a real receiver (target share >= 12%). A favourite by 4+ lifts RBs.
      * Wind >= 20 mph cuts QB/WR/TE 5% (>= 15 mph, 2%). No-op without data.
    Always within [0.90, 1.10]."""
    if not ctx:
        return 1.0, []
    f, notes = 1.0, []
    implied, margin = ctx.get("implied_total"), ctx.get("margin")
    if implied is not None:
        tf = 1 + (implied - LEAGUE_AVG_TEAM_TOTAL) / LEAGUE_AVG_TEAM_TOTAL * 0.35
        tf = min(1.07, max(0.93, tf))
        f *= tf
        if abs(tf - 1) >= 0.02:
            notes.append(f"Implied team total {implied:g} ({'high' if tf > 1 else 'low'}-scoring spot)")
    if margin is not None:
        steps = max(0.0, (abs(margin) - 3) / 3)
        shift = min(0.04, 0.02 * steps)
        if margin <= -4:
            if position in PASS_CATCHERS:
                f *= 1 + shift
                notes.append(f"Underdog by {abs(margin):g}: likely to throw more")
            elif position == "RB":
                receiver = target_share is not None and target_share >= 12
                f *= 1 - (shift / 2 if receiver else shift)
                notes.append(f"Underdog by {abs(margin):g}: fewer rushing chances" + (" (he catches passes, so less)" if receiver else ""))
        elif margin >= 4 and position == "RB":
            f *= 1 + shift
            notes.append(f"Favoured by {margin:g}: run-heavy script")
    wx = ctx.get("weather")
    if wx and not wx.get("maybe_closed") and position in PASS_CATCHERS:
        why = ", ".join(wx.get("reasons") or [])
        if wx["index"] >= 50:
            f *= 0.95
            notes.append(f"Bad passing weather ({why})")
        elif wx["index"] >= 25:
            f *= 0.98
            notes.append(f"Some weather drag ({why})")
    if ctx.get("roof") in ("dome", "closed"):
        notes.append("Indoors")
    return round(min(ENV_MAX, max(ENV_MIN, f)), 3), notes


USAGE_METRIC = {"QB": ("attempts", "pass attempts"), "RB": ("touches", "touches"),
                "WR": ("targets", "targets"), "TE": ("targets", "targets")}


def usage_trend(wk, player_id, position, recent=3, min_games=4):
    """Last `recent` games' opportunity vs his earlier games this season:
    {metric, recent_avg, earlier_avg, change_pct, label}. None when he hasn't
    played enough games for the comparison to mean anything."""
    metric, name = USAGE_METRIC[position]
    g = wk[wk["player_id"] == player_id].sort_values("week")
    if len(g) < min_games:
        return None
    vals = (g["carries"].fillna(0) + g["targets"].fillna(0)) if metric == "touches" else g[metric].fillna(0)
    vals = vals.to_numpy(dtype=float)
    r, e = vals[-recent:].mean(), vals[:-recent].mean()
    if e <= 0:
        return None
    change = (r - e) / e * 100
    label = "rising" if change >= 15 else "falling" if change <= -15 else "steady"
    return {"metric": name, "recent_avg": round(float(r), 1), "earlier_avg": round(float(e), 1),
            "change_pct": round(float(change), 0), "label": label}


def rank_value(proj, floor, ceiling, mode):
    """The number players are ranked by under each lens: balanced = projection;
    safe = half projection, half floor; upside = half projection, half ceiling."""
    if mode == "safe" and floor is not None:
        return 0.5 * proj + 0.5 * floor
    if mode == "upside" and ceiling is not None:
        return 0.5 * proj + 0.5 * ceiling
    return proj


def build_reasons(r):
    """Short plain-English reasons for one player's row, in order of weight,
    each tied to a real number on the row. Returns a list of strings."""
    out = []
    tag, factor = r.get("matchup_tag"), r.get("matchup_factor")
    if r.get("opponent") and tag and factor is not None and abs(factor - 1) >= 0.03:
        out.append(f"{'Soft' if factor > 1 else 'Tough'} matchup vs {r['opponent']} ({factor:.2f}x)")
    env = r.get("environment") or {}
    out.extend(env.get("notes", []))
    u = r.get("usage")
    if u and u["label"] != "steady":
        out.append(f"{u['metric'].capitalize()} {u['label']}: {u['recent_avg']:g}/game lately vs {u['earlier_avg']:g} earlier")
    if r.get("injury_status") in ("Questionable", "Doubtful", "Out"):
        part = f" ({r['injury_body_part']})" if r.get("injury_body_part") else ""
        out.append(f"{r['injury_status']}{part}")
    if r.get("cv") is not None and r["cv"] >= 0.5:
        out.append("Boom-or-bust week to week")
    floor, ceiling, proj = r.get("floor"), r.get("ceiling"), r.get("PROJ")
    if floor is not None and proj and floor / proj >= 0.7:
        out.append(f"Safe floor ({floor:.1f})")
    elif ceiling is not None and proj and ceiling / proj >= 1.5:
        out.append(f"High ceiling ({ceiling:.1f})")
    if r.get("snap_pct") is not None and r["snap_pct"] >= 0.8:
        out.append(f"Plays {round(r['snap_pct'] * 100)}% of snaps")
    return out


def comparison_reason(best, others, mode):
    """One sentence for why `best` wins: the projection gap, and what the lens is."""
    if not others:
        return None
    runner = max(others, key=lambda o: o.get("rank_value") or 0)
    gap = (best.get("PROJ") or 0) - (runner.get("PROJ") or 0)
    lens = {"safe": "the safest floor", "upside": "the highest ceiling"}.get(mode)
    name_a, name_b = best.get("player_display_name"), runner.get("player_display_name")
    if lens and gap < 0:
        return f"Start {name_a} for {lens} even though {name_b} projects {abs(gap):.1f} more."
    if lens:
        return f"Start {name_a}: projects {gap:+.1f} higher than {name_b} and has {lens}."
    return f"Start {name_a}: projects {best['PROJ']:.1f} vs {runner['PROJ']:.1f} for {name_b}."
