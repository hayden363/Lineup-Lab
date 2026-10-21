"""
REST-OF-SEASON PROJECTION — game by game
=========================================
For every unplayed game on a player's team schedule:

    P_game = baseline x M_vegas x M_defense x M_h2h

  baseline   what his role is worth per game. For RB/WR/TE it is mostly his
             trailing-4-game expected fantasy points (xFP: every target and
             carry valued at the league-average points of that kind of
             opportunity, engine/waivers.xfp_by_player), so fluky touchdown
             games don't set the number. 70% xFP / 30% the season rate with
             form already on it (BASELINE_XFP_WEIGHT). QBs have no passing
             xFP in this app, so a QB baseline is the rate alone.
  M_vegas    engine/context.environment_factor: implied team total and
             spread, capped to +/-10% (the same number Start/Sit uses).
             Neutral (1.0) for games the schedule feed has no lines for yet.
  M_defense  engine/defense: the opponent's per-stat matchup factor for his
             position, clamped to [0.80, 1.20].
  M_h2h      his own record against this opponent over the prior three seasons
             (engine/history.h2h_factor): his average there against his average
             in the same seasons, pulled hard toward 1.0 by how few meetings there
             are and capped at +/-8%. 1.0 with fewer than two meetings. A new
             coordinator or scheme makes old meetings weaker evidence, which is
             why it is small.

History also shapes the baseline itself: this season's rate is shrunk toward
his own career rate, not the position average (engine/board.shrunk_rate), and
the game-to-game spread behind floor/ceiling uses all seasons.

The range for each game (10th / 50th / 90th percentile) comes from the same
gamma outcome model Start/Sit uses (engine/decision.py). The season total
adds the game means. All weights and clamps are judgment calls, not fitted
to data.
"""

import pandas as pd

from . import context, decision, history, waivers
from .scoring import apply_scoring
from .board import (_injury_multiplier_col, _rate, build_board, load_bundle, matchup_multiplier)

BASELINE_XFP_WEIGHT = 0.70
TRAILING_GAMES = 4
DEF_MIN, DEF_MAX = 0.80, 1.20
GRADES = [(0.15, "A"), (0.35, "B"), (0.65, "C"), (0.85, "D")]   # share of defenses easier than this one


# ---- matchup difficulty and past matchups ---------------------------------
SOFT_SHARE, TOUGH_SHARE = 0.30, 0.70   # share of defenses easier than this one


def defense_tier(rank, n):
    """"soft" | "neutral" | "tough" from the defense's rank (1 = easiest), or None."""
    if not rank or not n:
        return None
    share = (rank - 1) / max(1, n - 1)
    return "soft" if share <= SOFT_SHARE else "tough" if share >= TOUGH_SHARE else "neutral"


def past_matchups(played, rank_of):
    """His games so far, each tagged with how hard that defense is for his
    position, plus the average per tier.

    played   [{week, opponent, points}] oldest first
    rank_of  opponent -> (rank, n)

    The tag uses the defense's season-to-date rank, which includes the game
    against him, so it is a fair but not perfect read of that week's matchup."""
    games, by = [], {}
    for g in played:
        rank, n = rank_of(g["opponent"])
        tier = defense_tier(rank, n)
        games.append({**g, "tier": tier, "rank": rank})
        if tier:
            by.setdefault(tier, []).append(g["points"])
    summary = {t: {"games": len(v), "avg": round(sum(v) / len(v), 1)} for t, v in by.items()}
    return games, summary


def waterfall(baseline, m_vegas, m_defense, m_h2h=1.0, m_injury=1.0):
    """Running value after each multiplier, so the card can show where the
    number came from."""
    a = baseline * m_vegas
    b = a * m_defense
    c = b * m_h2h
    d = c * m_injury
    return {"baseline": round(baseline, 1), "after_environment": round(a, 1), "after_defense": round(b, 1),
            "after_history": round(c, 1), "final": round(max(0.0, d), 1)}


H2H_NOTE = ("Uses his own games against this team over the last three seasons, pulled toward neutral and "
            "capped at 8%. It overlaps a little with the defense factor, and a new coordinator or scheme makes old "
            "meetings weaker evidence.")


def blend_baseline(xfp_trailing, rate):
    """Role-first baseline. Without xFP (QBs, or a player with no opportunity
    data) the rate stands alone."""
    if xfp_trailing is None:
        return rate
    return BASELINE_XFP_WEIGHT * xfp_trailing + (1 - BASELINE_XFP_WEIGHT) * rate


def clamp_defense(f):
    return min(DEF_MAX, max(DEF_MIN, f))


def grade_for(rank, n):
    """A (best matchup) to F from the defense's rank among all defenses."""
    if not rank or not n:
        return None
    share = (rank - 1) / max(1, n - 1)
    for cut, letter in GRADES:
        if share <= cut:
            return letter
    return "F"


def combine(baseline, m_vegas, m_defense, m_h2h=1.0, m_injury=1.0):
    return max(0.0, baseline * m_vegas * m_defense * m_h2h * m_injury)


def remaining_games(schedule, team):
    s = schedule
    if "game_type" in s.columns:
        s = s[s["game_type"] == "REG"]
    s = s[(s["home_team"] == team) | (s["away_team"] == team)]
    if "home_score" in s.columns:
        s = s[s["home_score"].isna()]
    return sorted(int(w) for w in s["week"])


def _usage(player_id, pos, bundle, xf_mine):
    """Last-4-games opportunity next to his season average (engine/decision.recent_usage)."""
    try:
        snaps = waivers.weekly_snaps(bundle["season"]).get(player_id) or {}
        pbp = bundle["pbp"]
        rz = pbp[(pbp["play_type"] == "run") & (pbp["rusher_player_id"] == player_id)
                 & (pbp["yardline_100"].fillna(100) <= 20)]
        rz_by = {int(w): int(n) for w, n in rz.groupby("week").size().items()}
        xfp = None if xf_mine is None else dict(zip(xf_mine["week"].astype(int), xf_mine["xfp"]))
        return decision.recent_usage(player_id, pos, bundle["wk"], snaps, xfp, rz_by, n=TRAILING_GAMES)
    except Exception as e:  # usage is garnish; never lose the projection over it
        print(f"[ros] usage unavailable for {player_id}: {e}")
        return None


def merge_tiers(current_by_tier, earlier):
    """Fold earlier seasons' games into the per-tier averages. Each tier keeps
    games/avg over everything and a split into this season vs earlier."""
    cur = {t: v for t, v in current_by_tier.items()}
    old = {}
    for g in earlier:
        if g.get("tier"):
            old.setdefault(g["tier"], []).append(g["points"])
    out = {}
    for t in set(cur) | set(old):
        c = cur.get(t)
        o = old.get(t, [])
        n_c = c["games"] if c else 0
        tot = (c["avg"] * n_c if c else 0.0) + sum(o)
        n = n_c + len(o)
        out[t] = {"games": n, "avg": round(tot / n, 1),
                  "current": c, "earlier": {"games": len(o), "avg": round(sum(o) / len(o), 1)} if o else None}
    return out


def player_ros(player_id, scoring=None, season=None, max_games=None):
    """Per-game rows plus a season total, or None when he can't be found."""
    bundle = load_bundle(season)
    wk = bundle["wk"]
    mine = wk[wk["player_id"] == player_id]
    if mine.empty:
        return None
    pos = mine.sort_values("week").iloc[-1]["position"]
    board = build_board(pos, bundle["season"], min_games=0, scoring=scoring)
    if player_id not in board.index:
        return None
    row = board.loc[player_id]
    team = row.get("recent_team")
    form_mult = 1 + float(row["FORM"]) / 100.0 if pd.notna(row.get("FORM")) else 1.0
    rate = float(_rate(board.loc[[player_id]]).iloc[0]) * form_mult

    xfp_t = None
    xf_mine = None
    if pos != "QB":
        xf = waivers.xfp_by_player(bundle["pbp"], scoring)
        xf_mine = xf[xf["player_id"] == player_id].sort_values("week")
        xf = xf_mine.tail(TRAILING_GAMES)
        if len(xf):
            xfp_t = float(xf["xfp"].mean())
    baseline = blend_baseline(xfp_t, rate)

    games_played = int(row["games"]) if pd.notna(row.get("games")) else 0
    q = board[(board["games"] >= 3) & (board["fpts_per_game"] >= 5)]["cv"].dropna()
    pos_cv = float(q.median()) if len(q) else 0.55
    season_now = bundle["season"]
    hist_on = history.available()
    career = history.weighted_career(pos, scoring, season_now, player_id) if hist_on else None
    hist_h = float(career["h"]) if career else 0.0
    cv_all = history.blend_cv(row.get("cv"), games_played, career["cv"] if career else None, hist_h)
    cv = decision.shrunk_cv(cv_all, games_played + hist_h, pos_cv)
    seed = int("".join(ch for ch in player_id if ch.isdigit()) or 0) % (2 ** 32)
    injury = float(_injury_multiplier_col(board.loc[[player_id]], pos).iloc[0])
    target_share = float(row["target_share"]) if pd.notna(row.get("target_share")) else None
    factors = bundle["defense_factors"]

    # What his role looks like lately, and how he has done against easy and
    # hard defenses so far (one season of data, so these are small samples).
    usage = _usage(player_id, pos, bundle, xf_mine)
    wk_scored, _ = apply_scoring(wk[wk["player_id"] == player_id], scoring)
    played = [{"week": int(r.week), "opponent": r.opponent_team, "points": round(float(r.fpts_active), 1)}
              for r in wk_scored.sort_values("week").itertuples(index=False)
              if isinstance(getattr(r, "opponent_team", None), str)]
    past_games, past_by_tier = past_matchups(played, lambda o: decision.defense_rank(pos, o, factors))
    earlier = history.tag_games(history.player_games(player_id, scoring, season_now), pos, scoring, season_now,
                                defense_tier) if hist_on else []
    past_by_tier = merge_tiers(past_by_tier, earlier)
    all_games = earlier + [{"season": season_now, "week": g["week"], "opponent": g["opponent"],
                            "points": g["points"]} for g in played]

    weeks = remaining_games(bundle["schedule"], team)
    if max_games:
        weeks = weeks[:max_games]
    games, total = [], 0.0
    for i, w in enumerate(weeks):
        ctx = context.game_context(bundle["schedule"], team, w)
        opp = ctx["opponent"] if ctx else None
        m_v, notes = context.environment_factor(pos, ctx, target_share)
        m_d = clamp_defense(matchup_multiplier(pos, opp, bundle)) if opp else 1.0
        m_i = injury if i == 0 else 1.0
        meet = history.versus(all_games, opp) if opp else None
        m_h = history.h2h_factor(all_games, opp, baseline) if opp else 1.0
        proj = combine(baseline, m_v, m_d, m_h, m_i)
        out = decision.ruled_out() if (i == 0 and row.get("injury_status") in decision.WONT_PLAY) \
            else decision.outcomes(proj, cv, seed + w)
        rank, n = decision.defense_rank(pos, opp, factors) if opp else (None, None)
        tier = defense_tier(rank, n)
        good, bad = decision.matchup_flags(pos, opp, factors) if opp else ([], [])
        prior = next((g for g in reversed(past_games) if g["opponent"] == opp), None)
        wx = (ctx or {}).get("weather")
        total += out["mean"]
        games.append({
            "week": w, "opponent": opp, "home": ctx["home"] if ctx else None,
            "proj": round(out["mean"], 1), "floor": out["p10"], "median": out["p50"], "ceiling": out["p90"],
            "m_vegas": m_v, "m_defense": round(m_d, 3), "m_h2h": m_h, "vs_opponent": meet,
            "grade": grade_for(rank, n), "defense_rank": rank,
            "implied_total": ctx.get("implied_total") if ctx else None,
            "margin": ctx.get("margin") if ctx else None,
            "has_lines": bool(ctx and ctx.get("implied_total") is not None),
            "notes": notes,
            "tier": tier, "defense_count": n,
            "similar": past_by_tier.get(tier) if tier else None,
            "prior_meeting": prior,
            "flags_good": good, "flags_bad": bad,
            "game_total": ctx.get("game_total") if ctx else None,
            "kickoff": {"day": str(ctx["gameday"]) if ctx and ctx.get("gameday") else None,
                        "time": str(ctx["gametime"]) if ctx and ctx.get("gametime") else None},
            "roof": ctx.get("roof") if ctx else None,
            "weather": {"label": wx.get("label"), "temp": wx.get("temp"), "wind": wx.get("wind"),
                        "reasons": wx.get("reasons")} if wx else None,
            "steps": waterfall(baseline, m_v, m_d, m_h, m_i),
        })
    best = max(games, key=lambda g: g["proj"]) if games else None
    worst = min(games, key=lambda g: g["proj"]) if games else None
    return {
        "player_id": player_id, "position": pos, "team": team,
        "baseline": round(baseline, 1), "baseline_xfp": None if xfp_t is None else round(xfp_t, 1),
        "baseline_rate": round(rate, 1),
        "usage": usage, "past_games": past_games, "past_by_tier": past_by_tier, "h2h_note": H2H_NOTE,
        "history": history.summary(player_id, pos, scoring, season_now, row.get("history_weight")) if hist_on else None,
        "earlier_games": earlier,
        "games": games, "total": round(total, 1), "n_games": len(games),
        "smash_week": best["week"] if best else None, "trap_week": worst["week"] if worst else None,
    }
