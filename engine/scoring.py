"""
CUSTOM LEAGUE SCORING
======================
WalterPicks' whole pitch is "advice custom to your exact league settings."
This module is that: fantasy points get recomputed from raw counting stats
using YOUR point values, instead of trusting nflverse's fixed PPR column.

SCORE (the 0-100 value composite in engine/metrics.py) stays scoring-agnostic
on purpose — it's "how good is this player," which shouldn't change because
your league pays 1.5 PPR. Everything downstream of raw production — FPTS/G,
FORM, PROJ, start/sit, trade value — uses whatever scoring settings are
active, via the `fpts_active` column this module computes.
"""

from dataclasses import dataclass, asdict

import pandas as pd

PRESETS = {
    "standard": dict(reception=0.0, pass_yard=0.04, pass_td=4, interception=-2,
                      rush_yard=0.1, rush_td=6, rec_yard=0.1, rec_td=6,
                      fumble_lost=-2, two_pt=2, return_td=6),
    "half_ppr": dict(reception=0.5, pass_yard=0.04, pass_td=4, interception=-2,
                      rush_yard=0.1, rush_td=6, rec_yard=0.1, rec_td=6,
                      fumble_lost=-2, two_pt=2, return_td=6),
    "ppr": dict(reception=1.0, pass_yard=0.04, pass_td=4, interception=-2,
                rush_yard=0.1, rush_td=6, rec_yard=0.1, rec_td=6,
                fumble_lost=-2, two_pt=2, return_td=6),
    # Full PPR plus half a point per tight-end catch (the common TE premium).
    "te_premium": dict(reception=1.0, te_reception=0.5, pass_yard=0.04, pass_td=4, interception=-2,
                       rush_yard=0.1, rush_td=6, rec_yard=0.1, rec_td=6,
                       fumble_lost=-2, two_pt=2, return_td=6),
}


@dataclass
class ScoringSettings:
    reception: float = 1.0
    pass_yard: float = 0.04
    pass_td: float = 4.0
    interception: float = -2.0
    rush_yard: float = 0.1
    rush_td: float = 6.0
    rec_yard: float = 0.1
    rec_td: float = 6.0
    fumble_lost: float = -2.0
    two_pt: float = 2.0
    # Kick/punt return and other special-teams touchdowns credited to an
    # individual player (nflverse `special_teams_tds`; Sleeper's `st_td`).
    # Not in the UI's SCORING_FIELDS yet, so it's always 6 unless a league
    # sync sets it — the value both real synced leagues and nflverse use.
    return_td: float = 6.0
    # League bonuses, all off (0) unless a league or preset turns them on.
    # te_reception is TE premium: added on top of `reception` for tight ends.
    te_reception: float = 0.0
    pass_fd: float = 0.0
    rush_fd: float = 0.0
    rec_fd: float = 0.0
    # Yardage milestones: points for a game at or past the line. Each line
    # met pays its own bonus (a 210-yard rushing day earns both 100 and 200).
    bonus_pass_300: float = 0.0
    bonus_pass_400: float = 0.0
    bonus_rush_100: float = 0.0
    bonus_rush_200: float = 0.0
    bonus_rec_100: float = 0.0
    bonus_rec_200: float = 0.0

    @classmethod
    def from_preset(cls, name):
        return cls(**PRESETS.get(name, PRESETS["ppr"]))

    @classmethod
    def from_dict(cls, d):
        base = asdict(cls())
        base.update({k: float(v) for k, v in (d or {}).items() if k in base})
        return cls(**base)

    def as_dict(self):
        return asdict(self)


def compute_fantasy_points(wk, settings: ScoringSettings):
    """Recompute fantasy points per row from raw weekly counting stats."""

    def col(name):
        # Always a Series, even when the column is missing — a bare `0`
        # fallback would let `pts` below degrade from Series to a plain
        # int/float whenever a counting-stat column is absent (e.g. a
        # thinner data source), and .round(2) at the end would then crash
        # with a real AttributeError, not just a type-checker complaint.
        return wk[name].fillna(0) if name in wk.columns else pd.Series(0.0, index=wk.index)

    fumbles_lost = col("rushing_fumbles_lost") + col("receiving_fumbles_lost") + col("sack_fumbles_lost")
    two_pts = col("passing_2pt_conversions") + col("rushing_2pt_conversions") + col("receiving_2pt_conversions")

    pts = (
        col("passing_yards") * settings.pass_yard
        + col("passing_tds") * settings.pass_td
        + col("interceptions") * settings.interception
        + col("rushing_yards") * settings.rush_yard
        + col("rushing_tds") * settings.rush_td
        + col("receiving_yards") * settings.rec_yard
        + col("receiving_tds") * settings.rec_td
        + col("receptions") * settings.reception
        + fumbles_lost * settings.fumble_lost
        + two_pts * settings.two_pt
        # Special-teams TDs were missing, so custom scoring gave a return TD 0
        # where nflverse's own PPR column gives 6 — 28 player-weeks of 2025 off
        # by exactly -6. With this line the PPR preset reproduces
        # fantasy_points_ppr on every cached row (tests/test_scoring.py).
        # fumble_recovery_tds is deliberately NOT added: nflverse doesn't count
        # it, and the rows that have one already match without it.
        + col("special_teams_tds") * settings.return_td
    )
    if settings.te_reception and "position" in wk.columns:
        pts = pts + col("receptions") * (wk["position"] == "TE") * settings.te_reception
    pts = (pts + col("passing_first_downs") * settings.pass_fd + col("rushing_first_downs") * settings.rush_fd
           + col("receiving_first_downs") * settings.rec_fd)
    for stat, line, val in (("passing_yards", 300, settings.bonus_pass_300), ("passing_yards", 400, settings.bonus_pass_400),
                            ("rushing_yards", 100, settings.bonus_rush_100), ("rushing_yards", 200, settings.bonus_rush_200),
                            ("receiving_yards", 100, settings.bonus_rec_100), ("receiving_yards", 200, settings.bonus_rec_200)):
        if val:
            pts = pts + (col(stat) >= line) * val
    return pts.round(2)


def apply_scoring(wk, scoring=None):
    """Return a copy of `wk` with an `fpts_active` column: either the raw
    nflverse PPR column (scoring=None / 'ppr' with no overrides) or a fully
    recomputed column for custom league settings."""
    wk = wk.copy()
    if scoring is None:
        wk["fpts_active"] = wk["fantasy_points_ppr"]
        return wk, ScoringSettings.from_preset("ppr")

    settings = scoring if isinstance(scoring, ScoringSettings) else ScoringSettings.from_dict(scoring)
    wk["fpts_active"] = compute_fantasy_points(wk, settings)
    return wk, settings
