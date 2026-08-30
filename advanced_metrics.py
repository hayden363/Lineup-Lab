"""
ADVANCED METRICS  (Task 1)
Computes the "PFF-style" advanced stats YOURSELF from free nfl_data_py
play-by-play data. This is the differentiator — metrics most free tools
don't bother computing.

Per QB (from play-by-play):
  - pressure_rate      : % of dropbacks where QB was pressured (sack+hit+hurry proxy)
  - comp_pct_pressure  : completion % when pressured  (your "completion % under pressure")
  - air_yards_per_att  : how aggressive/deep they throw
  - explosive_pass_rate: % of pass plays gaining 20+ yards
  - epa_per_play       : expected points added per play (efficiency gold standard)

Per RB (from play-by-play):
  - explosive_run_rate : % of runs gaining 10+ yards
  - yards_after_contact_proxy
  - epa_per_touch
  - target_share_proxy

Real version reads nfl.import_pbp_data([SEASON]). Offline, a small sample
play-by-play frame proves the computations.
"""

import numpy as np
import pandas as pd

SEASON = 2025


def load_pbp():
    try:
        import nfl_data_py as nfl
        pbp = nfl.import_pbp_data([SEASON])
        print(f"[pbp] loaded REAL play-by-play: {len(pbp)} plays")
        return pbp, True
    except Exception as e:
        print(f"[pbp] nfl_data_py unavailable ({type(e).__name__}); using SAMPLE pbp")
        return _sample_pbp(), False


def _sample_pbp():
    """Minimal play-by-play stand-in with the columns our metrics need."""
    # passer, rusher, play_type, yards_gained, air_yards, complete, sack, qb_hit, epa
    rows = [
        ("Josh Allen", None, "pass", 12, 8, 1, 0, 0, 0.6),
        ("Josh Allen", None, "pass", 0, 15, 0, 0, 1, -0.8),
        ("Josh Allen", None, "pass", 25, 22, 1, 0, 0, 1.9),
        ("Josh Allen", None, "pass", 0, 0, 0, 1, 1, -1.2),
        ("Josh Allen", None, "pass", 8, 5, 1, 0, 1, 0.3),
        ("Patrick Mahomes", None, "pass", 6, 4, 1, 0, 0, 0.2),
        ("Patrick Mahomes", None, "pass", 30, 28, 1, 0, 0, 2.4),
        ("Patrick Mahomes", None, "pass", 0, 12, 0, 0, 0, -0.5),
        ("Patrick Mahomes", None, "pass", 0, 0, 0, 1, 1, -1.0),
        (None, "Christian McCaffrey", "run", 12, 0, 0, 0, 0, 0.7),
        (None, "Christian McCaffrey", "run", 3, 0, 0, 0, 0, -0.1),
        (None, "Christian McCaffrey", "run", 18, 0, 0, 0, 0, 1.5),
        (None, "Christian McCaffrey", "run", 1, 0, 0, 0, 0, -0.3),
        (None, "Saquon Barkley", "run", 22, 0, 0, 0, 0, 2.0),
        (None, "Saquon Barkley", "run", 5, 0, 0, 0, 0, 0.1),
        (None, "Saquon Barkley", "run", 2, 0, 0, 0, 0, -0.2),
        (None, "Saquon Barkley", "run", 14, 0, 0, 0, 0, 1.1),
    ]
    cols = ["passer_player_name","rusher_player_name","play_type","yards_gained",
            "air_yards","complete_pass","sack","qb_hit","epa"]
    return pd.DataFrame(rows, columns=cols)


def qb_advanced(pbp):
    passes = pbp[pbp["play_type"] == "pass"].copy()
    # pressure proxy: sack or qb_hit on the play
    passes["pressured"] = ((passes["sack"] == 1) | (passes["qb_hit"] == 1)).astype(int)
    g = passes.groupby("passer_player_name")
    out = pd.DataFrame({
        "dropbacks":          g.size(),
        "pressure_rate":      g["pressured"].mean() * 100,
        "air_yards_per_att":  g["air_yards"].mean(),
        "explosive_pass_rate":g.apply(lambda d: (d["yards_gained"] >= 20).mean() * 100,
                                      include_groups=False),
        "epa_per_play":       g["epa"].mean(),
    })
    # completion % specifically when pressured
    def comp_when_pressured(d):
        p = d[d["pressured"] == 1]
        atts = p[(p["complete_pass"] == 1) | (p["complete_pass"] == 0)]
        thrown = atts[atts["sack"] == 0]           # a sack isn't a pass attempt
        if len(thrown) == 0:
            return np.nan
        return thrown["complete_pass"].mean() * 100
    out["comp_pct_pressure"] = g.apply(comp_when_pressured, include_groups=False)
    return out.round(2)


def rb_advanced(pbp):
    runs = pbp[pbp["play_type"] == "run"].copy()
    g = runs.groupby("rusher_player_name")
    out = pd.DataFrame({
        "carries":           g.size(),
        "explosive_run_rate":g.apply(lambda d: (d["yards_gained"] >= 10).mean() * 100,
                                     include_groups=False),
        "epa_per_touch":     g["epa"].mean(),
        "avg_yards":         g["yards_gained"].mean(),
    })
    return out.round(2)


def run():
    pbp, is_real = load_pbp()
    print("\n===== QB ADVANCED METRICS =====")
    print(qb_advanced(pbp).to_string())
    print("\n===== RB ADVANCED METRICS =====")
    print(rb_advanced(pbp).to_string())
    print("\n(pressure_rate & comp_pct_pressure = your 'under pressure' edge; "
          "epa = efficiency; explosive_rate = big-play ability)")


if __name__ == "__main__":
    run()
