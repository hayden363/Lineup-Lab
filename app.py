"""
FANTASY VALUATION APP  (v2 — full pipeline)
================================================================
Combines all four engines into one tool:

  1. base stats + custom metrics        (valuation_engine)
  2. play-by-play advanced metrics       (advanced_metrics)  -> pressure, EPA, explosive
  3. data-driven weights                 (weight_tuner)      -> learned, not guessed
  4. real matchup factors per defense    (matchup)           -> soft/tough per team

Output: a ranked board per position with SCORE, FORM, and a projected
points column for a chosen opponent defense.

RUN ON YOUR MACHINE:
    pip install nfl_data_py pandas numpy
    python app.py                 # full-season rankings
    python app.py --opp WAS       # project everyone vs Washington's defense

Offline (sandbox) it runs on the built-in sample so you can see it work.
================================================================
"""

import argparse
import numpy as np
import pandas as pd

# import the pieces we built
from valuation_engine import (load_data, qb_metrics, rb_metrics,
                              score_players, form_adjustment,
                              QB_WEIGHTS, RB_WEIGHTS)
from advanced_metrics import load_pbp, qb_advanced, rb_advanced
from matchup import load_weekly_with_opp, build_matchup_table


def build_board(position):
    wk, _ = load_data()
    pbp, _ = load_pbp()
    mwk, _ = load_weekly_with_opp()
    factors, _ = build_matchup_table(mwk)

    if position == "QB":
        base = qb_metrics(wk[wk["position"] == "QB"] if "position" in wk else wk)
        adv = qb_advanced(pbp)
        weights = QB_WEIGHTS
        sub = wk[wk["position"] == "QB"] if "position" in wk else wk
    else:
        base = rb_metrics(wk[wk["position"] == "RB"] if "position" in wk else wk)
        adv = rb_advanced(pbp)
        weights = RB_WEIGHTS
        sub = wk[wk["position"] == "RB"] if "position" in wk else wk

    # merge base + advanced metrics on player name
    board = base.join(adv, how="left")
    board["SCORE"] = score_players(base, weights)
    board["FORM"] = form_adjustment(sub)
    return board


def project_vs(board, factors, position, opp):
    if opp is None:
        return board
    factor = factors.get((opp, position), 1.0)
    form_mult = 1 + board["FORM"] / 100.0
    board[f"PROJ_vs_{opp}"] = (board["fpts_per_game"] * form_mult * factor).round(1)
    print(f"\n[matchup] {opp} vs {position}: factor {factor} "
          f"({'SOFT ✅' if factor>1.08 else 'TOUGH ⛔' if factor<0.92 else 'average'})")
    return board


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default=None, help="opponent defense abbr, e.g. WAS")
    ap.add_argument("--pos", default="BOTH", choices=["QB","RB","BOTH"])
    args = ap.parse_args()

    positions = ["QB","RB"] if args.pos == "BOTH" else [args.pos]
    _, factors_wk = None, None

    mwk, _ = load_weekly_with_opp()
    factors, _ = build_matchup_table(mwk)

    for pos in positions:
        board = build_board(pos)
        board = project_vs(board, factors, pos, args.opp)

        show_cols = ["SCORE","FORM","fpts_per_game"]
        # include a couple advanced cols if present
        for c in ["pressure_rate","comp_pct_pressure","epa_per_play",
                  "explosive_pass_rate","explosive_run_rate","epa_per_touch"]:
            if c in board.columns:
                show_cols.append(c)
        if args.opp:
            show_cols.append(f"PROJ_vs_{args.opp}")

        table = board[show_cols].sort_values("SCORE", ascending=False)
        print(f"\n================ {pos} BIG BOARD ================")
        print(table.to_string())

    print("\nSCORE = your weighted 0-100 value | FORM = recent +/- % | "
          "advanced cols computed from play-by-play")


if __name__ == "__main__":
    main()
