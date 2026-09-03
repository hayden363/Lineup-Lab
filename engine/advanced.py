"""
ADVANCED METRICS — the "PFF-grade, without PFF" layer
========================================================
Two free, legal sources, both from nflverse:

  1. Next Gen Stats (NGS) — real player-tracking data the NFL publishes
     publicly: separation, cushion, completion % above expectation, time
     to throw, rush yards over expected. This is the closest free
     equivalent to what a paid grading service like PFF sells.
  2. Play-by-play (pbp) — used for EPA/play and explosive-play rate,
     which NGS doesn't provide directly.

Joined on player_id (nflverse gsis_id), which is consistent across every
nflverse table.
"""

import numpy as np
import pandas as pd


def qb_advanced(pbp, ngs_passing):
    passes = pbp[pbp["play_type"] == "pass"].copy()
    passes["pressured"] = ((passes["sack"] == 1) | (passes["qb_hit"] == 1)).astype(int)
    g = passes.groupby("passer_player_id")

    def comp_when_pressured(d):
        thrown = d[(d["pressured"] == 1) & (d["sack"] == 0)]
        if len(thrown) == 0:
            return np.nan
        return thrown["complete_pass"].mean() * 100

    pbp_out = pd.DataFrame({
        "dropbacks": g.size(),
        "pressure_rate": g["pressured"].mean() * 100,
        "explosive_pass_rate": g.apply(lambda d: (d["yards_gained"] >= 20).mean() * 100),
        "epa_per_play": g["epa"].mean(),
    })
    pbp_out["comp_pct_pressure"] = g.apply(comp_when_pressured)

    ngs = ngs_passing.groupby("player_gsis_id").agg(
        avg_time_to_throw=("avg_time_to_throw", "mean"),
        aggressiveness=("aggressiveness", "mean"),
        cpoe=("completion_percentage_above_expectation", "mean"),
    )
    return pbp_out.join(ngs, how="outer")


def rb_advanced(pbp, ngs_rushing):
    runs = pbp[pbp["play_type"] == "run"].copy()
    g = runs.groupby("rusher_player_id")
    pbp_out = pd.DataFrame({
        "carries_pbp": g.size(),
        "explosive_run_rate": g.apply(lambda d: (d["yards_gained"] >= 10).mean() * 100),
        "epa_per_touch": g["epa"].mean(),
    })

    ngs = ngs_rushing.groupby("player_gsis_id").agg(
        rush_yards_over_expected_per_att=("rush_yards_over_expected_per_att", "mean"),
        rush_efficiency=("efficiency", "mean"),
        pct_stacked_box=("percent_attempts_gte_eight_defenders", "mean"),
    )
    return pbp_out.join(ngs, how="outer")


def _receiver_advanced(pbp, ngs_receiving, position_hint=None):
    catches = pbp[pbp["play_type"] == "pass"].copy()
    g = catches.groupby("receiver_player_id")
    pbp_out = pd.DataFrame({
        "targets_pbp": g.size(),
        "explosive_rec_rate": g.apply(lambda d: (d["yards_gained"] >= 20).mean() * 100),
        "epa_per_target": g["epa"].mean(),
    })

    ngs = ngs_receiving.groupby("player_gsis_id").agg(
        avg_separation=("avg_separation", "mean"),
        avg_cushion=("avg_cushion", "mean"),
        yac_above_expectation=("avg_yac_above_expectation", "mean"),
    )
    return pbp_out.join(ngs, how="outer")


def wr_advanced(pbp, ngs_receiving):
    return _receiver_advanced(pbp, ngs_receiving, "WR")


def te_advanced(pbp, ngs_receiving):
    return _receiver_advanced(pbp, ngs_receiving, "TE")


_EPA_PLAY_COL = {"QB": "passer_player_id", "RB": "rusher_player_id", "WR": "receiver_player_id", "TE": "receiver_player_id"}
_EPA_PLAY_TYPE = {"QB": "pass", "RB": "run", "WR": "pass", "TE": "pass"}


def weekly_epa(pbp, position):
    """Real per-play efficiency (EPA — Expected Points Added, from the same
    play-by-play the season-level *_advanced() functions above already
    use), kept at (player, week) grain instead of collapsed to one
    season number.

    This is the "how did the play actually go, independent of whether it
    happened to end in a touchdown" signal — EPA already accounts for
    down/distance/field position/score context, so a broken-tackle
    house call and a stuffed-at-the-two carry that both "worked" in
    box-score terms don't look identical here the way they would in raw
    yards or points. engine/metrics.form_adjustment uses this to tell a
    real hot streak (efficiency moved with the fantasy points) from a
    touchdown-variance spike (points moved, efficiency didn't) — see that
    function's docstring."""
    col = _EPA_PLAY_COL[position]
    plays = pbp[pbp["play_type"] == _EPA_PLAY_TYPE[position]]
    g = plays.groupby([col, "week"])["epa"].mean()
    g.index = g.index.set_names(["player_id", "week"])
    return g.rename("epa")


ADVANCED_COLS = {
    "QB": ["pressure_rate", "comp_pct_pressure", "cpoe", "avg_time_to_throw",
           "aggressiveness", "epa_per_play", "explosive_pass_rate"],
    "RB": ["explosive_run_rate", "epa_per_touch", "rush_yards_over_expected_per_att",
           "rush_efficiency", "pct_stacked_box"],
    "WR": ["avg_separation", "avg_cushion", "yac_above_expectation",
           "epa_per_target", "explosive_rec_rate"],
    "TE": ["avg_separation", "avg_cushion", "yac_above_expectation",
           "epa_per_target", "explosive_rec_rate"],
}
