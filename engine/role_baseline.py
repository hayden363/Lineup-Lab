"""
ROLE-RANK BASELINE
===================
For a skill-position player (RB/WR/TE — QB starters are essentially
never stat-less, so this doesn't apply there) with no personal game log
of his own — most commonly a rookie, but also a new signing — the
fallback used when there's a real CURRENT team and a real CURRENT
depth-chart rank (both live, from Sleeper) but no real box-score history
to build SCORE/FORM/floor/ceiling from.

Same "the team's own real production, not a guess about this specific
human" idea as engine/kicker_scoring.py's team baseline, extended from a
single role (one kicker on the field at a time) to a multi-player
position group: rank this team's own real players at the position by who
actually produced last season, then match the CURRENT live depth-chart
rank to that SAME rank's real historical production. "We don't know his
skill, but we know this team's real RB2 usage last year, and he's the
RB2 right now" — a rank-for-rank swap of real numbers, no invented split
percentages.

This is a deliberately conservative approximation, not a personal
valuation: a genuine scheme change, coaching change, or a workload this
specific player earns that his rank-predecessor never had isn't
captured here. That's exactly why SCORE/FORM/floor/ceiling stay None for
these players (see engine/tools.py) — PROJ gets a real, sourced estimate;
everything claiming to describe HIS skill stays honest about not
knowing it.
"""

RANK_POSITIONS = ("RB", "WR", "TE")


def team_position_rank_baseline(wk, position, min_games=2):
    """team -> {rank: fpts_per_game}, rank 1 = the team's own highest real
    per-game producer at this position last season, rank 2 the next, etc.
    — built entirely from real per-player weekly production."""
    sub = wk[wk["position"] == position]
    per_player = sub.groupby(["player_id", "recent_team"])["fpts_active"].agg(["mean", "count"])
    per_player = per_player[per_player["count"] >= min_games]

    out = {}
    for team, group in per_player.groupby("recent_team"):
        ranked = group.sort_values("mean", ascending=False)["mean"].round(2)
        out[team] = {i + 1: float(v) for i, v in enumerate(ranked.tolist())}
    return out


def build_role_rank_baselines(wk, min_games=2):
    """{position: {team: {rank: fpts_per_game}}} for every position this
    fallback applies to — computed once per season/scoring, reused across
    every unpriceable player it's asked about."""
    return {pos: team_position_rank_baseline(wk, pos, min_games=min_games) for pos in RANK_POSITIONS}


def resolve_role_rank_projection(team, depth_chart_order, position, rank_baselines):
    """A real fpts/game number for `depth_chart_order` on `team` at
    `position`, from that team's own real historical same-rank producer —
    or None if there's nothing real to draw on (no live depth-chart order
    at all, or this team/position combination never showed up with
    qualifying games in our data). A team's real depth rarely runs past
    3-4 meaningfully-used players; anyone deeper than the team's own real
    bench gets the team's thinnest real rank rather than nothing —
    better grounded than extrapolating past real data, and still
    honestly low, since a team's real 4th-string RB barely dents the
    box score most seasons."""
    if not depth_chart_order or position not in rank_baselines:
        return None
    team_ranks = rank_baselines[position].get(team)
    if not team_ranks:
        return None
    order = min(depth_chart_order, max(team_ranks.keys()))
    return team_ranks.get(order)
