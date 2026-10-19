"""
WEEKLY PROJECTIONS — what a player was projected for each past week
===================================================================
Sleeper publishes a pre-game projected stat line for every player, every week
(source: Rotowire, served at api.sleeper.app/projections). The player card's
weekly breakdown grades each game against it: did he beat his projection that
week or fall short.

Checked before shipping: for 2026 weeks 1-6, projected vs actual PPR points
correlate 0.2-0.7 by position and players beat their projection 35-50% of the
time — what pre-game projections look like, not numbers rewritten after the
games.

Fantasy points are recomputed from the projected stat line under the caller's
scoring, so a half-PPR league is judged against a half-PPR projection.
"""

from concurrent.futures import ThreadPoolExecutor

from . import sleeper
from .scoring import ScoringSettings

PROJ_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular&position%5B%5D={pos}"
PROJ_TTL = 6 * 60 * 60

# Sleeper projected-stat key -> our weekly_log column.
STAT_MAP = {
    "pass_cmp": "completions", "pass_att": "attempts", "pass_yd": "passing_yards", "pass_td": "passing_tds",
    "pass_int": "interceptions",
    "rush_att": "carries", "rush_yd": "rushing_yards", "rush_td": "rushing_tds",
    "rec_tgt": "targets", "rec": "receptions", "rec_yd": "receiving_yards", "rec_td": "receiving_tds",
}


def points(stats, settings, position=None):
    """Fantasy points for a projected Sleeper stat line under our settings.

    Includes the league extras the actual weekly points already include
    (engine/scoring.compute_fantasy_points): first downs, and TE premium when
    `position` is "TE". Without them a TE-premium or first-down league's
    player card judged every actual score against a projection that was
    missing part of the scoring, so players "beat" it far too often.
    Yardage milestone bonuses stay out: a projected stat line is an average,
    and an average of 95 yards says nothing about how often 100 is reached."""
    s = settings if isinstance(settings, ScoringSettings) else ScoringSettings.from_dict(settings or {})
    g = lambda k: float(stats.get(k) or 0.0)
    pts = (g("pass_yd") * s.pass_yard + g("pass_td") * s.pass_td + g("pass_int") * s.interception
           + g("rush_yd") * s.rush_yard + g("rush_td") * s.rush_td
           + g("rec_yd") * s.rec_yard + g("rec_td") * s.rec_td + g("rec") * s.reception
           + g("fum_lost") * s.fumble_lost
           + (g("pass_2pt") + g("rush_2pt") + g("rec_2pt")) * s.two_pt
           + g("pass_fd") * s.pass_fd + g("rush_fd") * s.rush_fd + g("rec_fd") * s.rec_fd)
    if position == "TE":
        pts += g("rec") * s.te_reception
    return round(pts, 1)


def projected_line(stats, settings, position=None):
    """{fpts, completions, ...} in our column names; only stats Sleeper projects.
    A player projected not to play (gp 0, or no points at all) comes back as
    {"out": True} — beating a zero says nothing about how he played."""
    if float(stats.get("gp", 1) or 0) == 0 or points(stats, settings, position) <= 0.5:
        return {"out": True}
    out = {ours: round(float(stats[k]), 1) for k, ours in STAT_MAP.items() if stats.get(k) is not None}
    out["fpts"] = points(stats, settings, position)
    return out


def _week_rows(season, week, position):
    url = PROJ_URL.format(season=season, week=week, pos=position)
    return sleeper._cached_get(url, f"proj_{season}_{week}_{position}", PROJ_TTL)


def player_projections(gsis_id, position, season, weeks, settings=None):
    """{week: projected line} for one player over the given weeks. A week whose
    fetch fails, or with no projection for him, is simply missing."""
    weeks = sorted(set(int(w) for w in weeks))
    if not weeks:
        return {}
    sleeper_ids = {s for s, g in sleeper.id_crosswalk().items() if g == gsis_id}
    if not sleeper_ids:
        return {}

    def one(week):
        try:
            rows = _week_rows(season, week, position)
        except Exception as e:
            print(f"[weekly_proj] week {week} {position} unavailable: {e}")
            return week, None
        for r in rows:
            if str(r.get("player_id")) in sleeper_ids and r.get("stats"):
                return week, r["stats"]
        return week, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        found = dict(pool.map(one, weeks))
    return {w: projected_line(st, settings, position) for w, st in found.items() if st}


def attach(weekly_rows, projections):
    """Put each played week's projection on its row as `proj` (in place)."""
    for r in weekly_rows:
        if r.get("status", "played") == "played" and r.get("week") in projections:
            r["proj"] = projections[r["week"]]
    return weekly_rows
