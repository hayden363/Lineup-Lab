"""
FANTASY VALUATION ENGINE  (prototype v1)
Runs on FREE data from nfl_data_py. Builds your own player value the way
you described:

  1. Pull real stats (weekly + play-by-play).
  2. Compute custom metrics per position (efficiency, pressure, volume...).
  3. Weight each metric -> a single 0-100 PLAYER SCORE.
  4. FORM: +/- adjustment from recent games vs season baseline.
  5. MATCHUP: project points vs a specific opposing defense, using how
     that defense treated similar players.

HOW TO RUN (on your own machine, not needed here):
    pip install nfl_data_py pandas numpy
    python valuation_engine.py

If nfl_data_py is available it uses REAL data. If not (like in a sandbox),
it falls back to a small built-in SAMPLE so you can see the math work.
"""

import numpy as np
import pandas as pd

SEASON = 2025

# ----------------------------------------------------------------------
# METRIC WEIGHTS  — THIS IS YOUR SECRET SAUCE. Tune these.
# Each position values different things. Numbers are relative weights;
# they get normalized, so only their ratios matter.
# ----------------------------------------------------------------------
QB_WEIGHTS = {
    "yards_per_attempt":      25,   # efficiency
    "td_rate":                20,   # scoring
    "completion_pct":         15,   # accuracy
    "int_rate":              -15,   # negative: turnovers hurt
    "sack_rate":             -10,   # negative: pressure/sacks hurt
    "rush_yards_per_game":    15,   # mobility adds fantasy points
}

RB_WEIGHTS = {
    "yards_per_carry":        25,
    "td_rate":                20,
    "touches_per_game":       25,   # volume = opportunity
    "yards_per_target":       15,   # receiving efficiency
    "explosive_rate":         15,   # % of runs 10+ yds
}


# ----------------------------------------------------------------------
# DATA LOADING
# ----------------------------------------------------------------------
def load_data():
    """Return weekly player data. Real if nfl_data_py works, else sample."""
    try:
        import nfl_data_py as nfl
        wk = nfl.import_weekly_data([SEASON])
        print(f"[data] loaded REAL nfl_data_py weekly data: {len(wk)} rows")
        return wk, True
    except Exception as e:
        print(f"[data] nfl_data_py unavailable ({type(e).__name__}); using SAMPLE data")
        return _sample_data(), False


def _sample_data():
    """Tiny realistic stand-in so the math is demonstrable offline."""
    rows = [
        # name, pos, week, att, cmp, pass_yds, pass_td, int, sacks, rush_att, rush_yds, rush_td, targets, rec, rec_yds, fpts
        ("Josh Allen","QB",1,38,28,320,3,0,2,9,56,1,0,0,0,28.9),
        ("Josh Allen","QB",2,32,20,240,2,1,3,7,40,0,0,0,0,18.2),
        ("Josh Allen","QB",3,40,30,360,3,0,1,6,45,1,0,0,0,30.1),
        ("Josh Allen","QB",4,29,18,205,1,2,4,5,22,0,0,0,0,11.4),
        ("Patrick Mahomes","QB",1,35,25,280,2,1,2,3,15,0,0,0,0,19.5),
        ("Patrick Mahomes","QB",2,41,29,330,3,0,1,5,20,0,0,0,0,26.2),
        ("Patrick Mahomes","QB",3,33,22,250,1,1,3,8,12,0,0,0,0,14.0),
        ("Patrick Mahomes","QB",4,38,27,300,2,0,2,10,18,1,0,0,0,24.0),
        ("Christian McCaffrey","RB",1,0,0,0,0,0,0,22,110,1,7,6,48,27.8),
        ("Christian McCaffrey","RB",2,0,0,0,0,0,0,18,85,0,9,7,60,22.5),
        ("Christian McCaffrey","RB",3,0,0,0,0,0,0,24,130,2,5,4,30,31.0),
        ("Christian McCaffrey","RB",4,0,0,0,0,0,0,15,60,0,6,5,40,15.0),
        ("Saquon Barkley","RB",1,0,0,0,0,0,0,20,95,1,4,3,25,20.0),
        ("Saquon Barkley","RB",2,0,0,0,0,0,0,26,145,1,3,2,18,24.3),
        ("Saquon Barkley","RB",3,0,0,0,0,0,0,17,70,0,5,4,35,13.5),
        ("Saquon Barkley","RB",4,0,0,0,0,0,0,28,160,2,2,2,15,30.7),
    ]
    cols = ["player_name","position","week","attempts","completions","passing_yards",
            "passing_tds","interceptions","sacks","carries","rushing_yards","rushing_tds",
            "targets","receptions","receiving_yards","fantasy_points"]
    return pd.DataFrame(rows, columns=cols)


# ----------------------------------------------------------------------
# METRIC COMPUTATION  (your own advanced metrics from raw stats)
# ----------------------------------------------------------------------
def qb_metrics(df):
    g = df.groupby("player_name")
    out = pd.DataFrame({
        "games":              g.size(),
        "yards_per_attempt":  g["passing_yards"].sum() / g["attempts"].sum(),
        "completion_pct":     g["completions"].sum() / g["attempts"].sum() * 100,
        "td_rate":            g["passing_tds"].sum() / g["attempts"].sum() * 100,
        "int_rate":           g["interceptions"].sum() / g["attempts"].sum() * 100,
        "sack_rate":          g["sacks"].sum() / (g["attempts"].sum() + g["sacks"].sum()) * 100,
        "rush_yards_per_game":g["rushing_yards"].sum() / g.size(),
        "fpts_per_game":      g["fantasy_points"].sum() / g.size(),
    })
    return out


def rb_metrics(df):
    g = df.groupby("player_name")
    carries = g["carries"].sum()
    out = pd.DataFrame({
        "games":            g.size(),
        "yards_per_carry":  g["rushing_yards"].sum() / carries.replace(0, np.nan),
        "td_rate":          (g["rushing_tds"].sum()) / carries.replace(0, np.nan) * 100,
        "touches_per_game": (carries + g["receptions"].sum()) / g.size(),
        "yards_per_target": g["receiving_yards"].sum() / g["targets"].sum().replace(0, np.nan),
        "explosive_rate":   15.0,  # placeholder; real version computes from play-by-play
        "fpts_per_game":    g["fantasy_points"].sum() / g.size(),
    })
    return out


# ----------------------------------------------------------------------
# SCORING  — normalize each metric 0-100, apply weights, combine
# ----------------------------------------------------------------------
def score_players(metrics, weights):
    scores = pd.Series(0.0, index=metrics.index)
    total_w = sum(abs(w) for w in weights.values())
    for metric, w in weights.items():
        col = metrics[metric].astype(float)
        rng = col.max() - col.min()
        norm = (col - col.min()) / rng if rng > 0 else pd.Series(0.5, index=col.index)
        if w < 0:                     # negative metric: invert (less is better)
            norm = 1 - norm
        scores += norm * abs(w)
    return (scores / total_w * 100).round(1)


# ----------------------------------------------------------------------
# FORM  — recent games vs season baseline -> +/- adjustment
# ----------------------------------------------------------------------
def form_adjustment(df, recent=2):
    adj = {}
    for name, pdata in df.groupby("player_name"):
        pdata = pdata.sort_values("week")
        season_avg = pdata["fantasy_points"].mean()
        recent_avg = pdata["fantasy_points"].tail(recent).mean()
        if season_avg > 0:
            pct = (recent_avg - season_avg) / season_avg
            adj[name] = round(np.clip(pct, -0.35, 0.35) * 100, 1)  # cap at +/-35%
        else:
            adj[name] = 0.0
    return pd.Series(adj)


# ----------------------------------------------------------------------
# MATCHUP  — project points vs a defense that allows X% vs position avg
# ----------------------------------------------------------------------
def project_points(metrics, form, def_factor):
    """
    def_factor: 1.0 = league-average defense, 1.15 = allows 15% MORE than avg
    (a soft matchup), 0.85 = tough defense. In the real version you compute
    this from how the defense treated similar players.
    """
    base = metrics["fpts_per_game"]
    form_mult = 1 + form / 100.0
    return (base * form_mult * def_factor).round(1)


# ----------------------------------------------------------------------
# RUN
# ----------------------------------------------------------------------
def run():
    wk, is_real = load_data()

    for pos, metric_fn, weights in [("QB", qb_metrics, QB_WEIGHTS),
                                    ("RB", rb_metrics, RB_WEIGHTS)]:
        sub = wk[wk["position"] == pos] if "position" in wk else wk
        if sub.empty:
            continue
        metrics = metric_fn(sub)
        metrics["SCORE"] = score_players(metrics, weights)
        form = form_adjustment(sub)
        metrics["FORM"] = form
        # example matchup: soft defense that allows 12% more than average
        metrics["PROJ_vs_softD"] = project_points(metrics, form, def_factor=1.12)

        table = metrics[["SCORE","FORM","fpts_per_game","PROJ_vs_softD"]] \
                    .sort_values("SCORE", ascending=False)
        print(f"\n===== {pos} RANKINGS =====")
        print(table.to_string())

    print("\n(SCORE = your weighted value 0-100 | FORM = recent +/- % | "
          "PROJ = projected pts vs a soft defense)")


if __name__ == "__main__":
    run()
