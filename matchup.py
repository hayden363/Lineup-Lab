"""
MATCHUP CALCULATOR  (Task 2)
Replaces the hardcoded def_factor with a REAL number per defense, per
position: how many fantasy points that defense allows to a position vs
the league average.

  def_factor = (points that defense allows to POS) / (league avg allowed to POS)

  1.15  -> soft matchup (allows 15% more than average) -> boost projection
  0.85  -> tough matchup -> lower projection

Real version: nfl.import_weekly_data([SEASON]) has opponent + fantasy_points,
so you group by (defense, position). Offline sample proves the math.
"""

import numpy as np
import pandas as pd

SEASON = 2025


def load_weekly_with_opp():
    try:
        import nfl_data_py as nfl
        wk = nfl.import_weekly_data([SEASON])
        print(f"[matchup] loaded REAL weekly data: {len(wk)} rows")
        return wk, True
    except Exception as e:
        print(f"[matchup] nfl_data_py unavailable ({type(e).__name__}); using SAMPLE")
        return _sample(), False


def _sample():
    # position, opponent_team (the DEFENSE faced), fantasy_points
    rows = [
        ("QB","NYJ",14.0),("QB","NYJ",12.0),("QB","NYJ",16.0),   # NYJ tough on QBs
        ("QB","WAS",26.0),("QB","WAS",24.0),("QB","WAS",30.0),   # WAS soft on QBs
        ("QB","DAL",20.0),("QB","DAL",22.0),("QB","DAL",18.0),   # DAL average
        ("RB","NYJ",22.0),("RB","NYJ",25.0),("RB","NYJ",20.0),   # NYJ soft on RBs
        ("RB","WAS",10.0),("RB","WAS",12.0),("RB","WAS",8.0),    # WAS tough on RBs
        ("RB","DAL",15.0),("RB","DAL",16.0),("RB","DAL",14.0),   # DAL average
    ]
    return pd.DataFrame(rows, columns=["position","opponent_team","fantasy_points"])


def build_matchup_table(wk):
    """Return dict: (defense, position) -> def_factor."""
    # league average fantasy points allowed, per position
    league_avg = wk.groupby("position")["fantasy_points"].mean()
    # points each defense allows per position
    by_def = wk.groupby(["opponent_team","position"])["fantasy_points"].mean()

    factors = {}
    for (defense, pos), allowed in by_def.items():
        avg = league_avg[pos]
        factors[(defense, pos)] = round(allowed / avg, 3) if avg > 0 else 1.0
    return factors, league_avg


def run():
    wk, is_real = load_weekly_with_opp()
    factors, league_avg = build_matchup_table(wk)

    print("\n===== LEAGUE AVG FANTASY PTS ALLOWED (per position) =====")
    print(league_avg.round(2).to_string())

    print("\n===== DEFENSE MATCHUP FACTORS =====")
    print("(>1.0 = soft/good to attack | <1.0 = tough matchup)\n")
    tbl = pd.Series(factors).sort_index()
    for (defense, pos), f in tbl.items():
        tag = "SOFT ✅" if f > 1.08 else ("TOUGH ⛔" if f < 0.92 else "avg")
        print(f"  {defense:>4} vs {pos}: {f:>5}  {tag}")


if __name__ == "__main__":
    run()
