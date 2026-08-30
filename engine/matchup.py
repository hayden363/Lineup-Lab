"""
MATCHUP FACTORS
================
How many fantasy points has each defense allowed to each position,
relative to league average?

  factor = (PPR pts that DEF allows to POS, per game) / (league avg for POS)

  > 1.0  -> soft matchup, allows more than average -> boost projection
  < 1.0  -> tough matchup -> lower projection

Computed directly from real weekly data (opponent_team + fpts_active),
grouped by (defense, position) — nothing proprietary, just real results.
"""

import pandas as pd


def build_matchup_table(wk, positions=("QB", "RB", "WR", "TE")):
    sub = wk[wk["position"].isin(positions)]
    league_avg = sub.groupby("position")["fpts_active"].mean()
    by_def = sub.groupby(["opponent_team", "position"])["fpts_active"].mean()

    factors = {}
    for (defense, pos), allowed in by_def.items():
        avg = league_avg.get(pos, 0)
        factors[(defense, pos)] = round(float(allowed / avg), 3) if avg else 1.0
    return factors, league_avg


def matchup_tag(factor):
    if factor > 1.10:
        return "soft"
    if factor < 0.90:
        return "tough"
    return "average"
