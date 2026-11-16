"""
THE DAILY DRIVE - the 100-prompt pool (DRAFT, NOT WIRED IN)
==========================================================
A data-defined replacement for FANTASY_TEMPLATES in engine/daily_drive.py. Nothing imports this module yet; the owner
reviews the list first (analysis/dd_prompts_100.md). Every prompt follows the owner rules:
  1. only THIS season's stats (nflverse weekly player stats + this season's schedule; the draft table is used only to
     tell who the season's rookies are and which college a player came from),
  2. it updates weekly (thresholds walk a `ladder` through the real tiering path, dd.pick_threshold, exactly like
     dd.build_season_prompt; volume gates and "last week / last 3 weeks" windows move with the latest finished week),
  3. every prompt has at least one tier-6 answer (dd.has_hall_of_famer, enforced by dd.pick_threshold),
  4. at least dd.MIN_ANSWERS valid answers (also enforced by dd.pick_threshold).
Answers are always a typed PLAYER name (tiers come from dd's three-signal fame score via dd._answers_at).

A template is a dict:
  key, cat, kind, text, ladder, label            (always)
  pos            tuple of positions, or one of the POS_SETS names
  stat / num+den / cond   what is measured (see KINDS)
  where          list of game-context flags a game must satisfy (WHERES)
  window         "last" (only the latest finished week) | 3 (the last three finished weeks)
  scope          "division" | "conference" | "team" | "college" (rotates by date via scope_for; text has {scope})
  rookie         True -> only this season's rookies
  min_games / min_den_pg / also      volume gates
  group          near-duplicate families (the day picker allows one per group)
Kinds: sum, max, games, ratio, mean, streak, topfinish, range.
"""

import hashlib
import operator
import re

import pandas as pd

from engine import daily_drive as dd

# ----------------------------------------------------------------------------------------------- static NFL facts
# Division membership is a fixed fact of the league; it is cross-checked against the schedule's own div_game flag
# in the tests/analysis (every div_game row must pair two teams of the same division here).
DIVISIONS = {
    "AFC East": ("BUF", "MIA", "NE", "NYJ"), "AFC North": ("BAL", "CIN", "CLE", "PIT"),
    "AFC South": ("HOU", "IND", "JAX", "TEN"), "AFC West": ("DEN", "KC", "LAC", "LV"),
    "NFC East": ("DAL", "NYG", "PHI", "WAS"), "NFC North": ("CHI", "DET", "GB", "MIN"),
    "NFC South": ("ATL", "CAR", "NO", "TB"), "NFC West": ("ARI", "LA", "SEA", "SF"),
}
TEAM_DIV = {t: d for d, ts in DIVISIONS.items() for t in ts}
TEAM_NAME = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears",
    "CIN": "Bengals", "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs", "LA": "Rams", "LAC": "Chargers",
    "LV": "Raiders", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers",
    "TEN": "Titans", "WAS": "Commanders",
}
# Conferences by TODAY'S membership (the college string is the nflverse draft-table spelling).
COLLEGE_CONF = {
    "SEC": ("Alabama", "Arkansas", "Auburn", "Florida", "Georgia", "Kentucky", "LSU", "Mississippi", "Mississippi St.",
            "Missouri", "Oklahoma", "South Carolina", "Tennessee", "Texas", "Texas A&M", "Vanderbilt"),
    "Big Ten": ("Illinois", "Indiana", "Iowa", "Maryland", "Michigan", "Michigan St.", "Minnesota", "Nebraska",
                "Northwestern", "Ohio St.", "Oregon", "Penn St.", "Purdue", "Rutgers", "UCLA", "USC", "Washington", "Wisconsin"),
    "ACC": ("Boston Col.", "California", "Clemson", "Duke", "Florida St.", "Georgia Tech", "Louisville", "Miami (FL)",
            "North Carolina St.", "North Carolina", "Pittsburgh", "SMU", "Stanford", "Syracuse", "Virginia", "Virginia Tech",
            "Wake Forest"),
    "Big 12": ("Arizona", "Arizona St.", "Baylor", "BYU", "Cincinnati", "Colorado", "Houston", "Iowa St.", "Kansas",
               "Kansas St.", "Oklahoma St.", "TCU", "Texas Tech", "Central Florida", "Utah", "West Virginia"),
}
SCOPES = {
    "division": list(DIVISIONS),
    "conference": ["AFC", "NFC"],
    "team": sorted(TEAM_NAME),
    "college": list(COLLEGE_CONF),
}
POS_SETS = {
    "SKILL": ("QB", "RB", "WR", "TE"),
    "FLEX": ("RB", "WR", "TE"),
    "REC": ("WR", "TE", "RB"),
    "DEF": ("DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "MLB", "CB", "DB", "S", "SAF", "FS"),
    "PASSRUSH": ("DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "MLB"),
    "BACK7": ("LB", "OLB", "ILB", "MLB", "CB", "DB", "S", "SAF", "FS"),
    "DB": ("CB", "DB", "S", "SAF", "FS"),
    "K": ("K",),
    "P": ("P",),
}

# named game-context flags (columns f_* on the game table built by build_context)
WHERES = {"div", "road", "home", "night", "dome", "ot", "win", "loss", "close_loss", "upset", "vs_winning", "shootout", "blowout_win", "dog"}

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}


# ----------------------------------------------------------------------------------------------- the pool
def T(key, cat, kind, text, ladder, label, **kw):
    return dict(key=key, cat=cat, kind=kind, text=text, ladder=tuple(ladder), label=label, **kw)


POOL = [
    # ---- SEASON TOTALS -------------------------------------------------------------------------
    T("wr_rec_yds", "Season totals", "sum", "Name a WR with {t}+ receiving yards", (150, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1200, 1400), "rec yds", pos=("WR",), stat="receiving_yards"),
    T("te_rec_yds", "Season totals", "sum", "Name a TE with {t}+ receiving yards", (60, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 1000), "rec yds", pos=("TE",), stat="receiving_yards"),
    T("rb_rush_yds", "Season totals", "sum", "Name a RB with {t}+ rushing yards", (100, 200, 300, 400, 500, 600, 700, 800, 1000, 1200, 1400, 1600), "rush yds", pos=("RB",), stat="rushing_yards"),
    T("qb_pass_yds", "Season totals", "sum", "Name a QB with {t}+ passing yards", (500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500), "pass yds", pos=("QB",), stat="passing_yards"),
    T("qb_pass_td", "Season totals", "sum", "Name a QB who has thrown {t}+ touchdown passes", (3, 5, 8, 10, 12, 15, 18, 20, 22, 25, 28, 30, 35), "pass TD", pos=("QB",), stat="passing_tds"),
    T("rb_catches", "Season totals", "sum", "Name a RB with {t}+ catches", (5, 10, 15, 20, 30, 40, 50, 60, 70, 80), "rec", pos=("RB",), stat="receptions"),
    T("wte_rec_td", "Season totals", "sum", "Name a WR or TE with {t}+ receiving TDs", (1, 2, 3, 4, 5, 6, 8, 10, 12), "rec TD", pos=("WR", "TE"), stat="receiving_tds"),
    T("any_total_td", "Season totals", "sum", "Name a player with {t}+ touchdowns (rushing + receiving)", (1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16), "total TD", pos="SKILL", stat="tds"),
    T("any_ppr", "Season totals", "sum", "Name a player with {t}+ PPR fantasy points", (30, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350), "PPR pts", pos="SKILL", stat="fpts"),
    T("any_targets", "Season totals", "sum", "Name a player who has been targeted {t}+ times", (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140), "targets", pos="REC", stat="targets"),
    T("rb_carries", "Season totals", "sum", "Name a RB with {t}+ carries", (30, 50, 75, 100, 125, 150, 175, 200, 225, 250, 275), "carries", pos=("RB",), stat="carries"),
    T("any_scrim", "Season totals", "sum", "Name a player with {t}+ scrimmage yards (rushing + receiving)", (150, 250, 350, 450, 550, 650, 800, 1000, 1200, 1400, 1600), "scrim yds", pos="SKILL", stat="scrim"),
    T("wr_yac", "Season totals", "sum", "Name a WR with {t}+ yards after the catch", (50, 100, 150, 200, 250, 300, 350, 400, 450, 500), "YAC", pos=("WR",), stat="receiving_yards_after_catch"),

    # ---- SINGLE-GAME FEATS ---------------------------------------------------------------------
    T("wr_game_yds", "One-game feats", "max", "Name a WR with a {t}+ yard receiving game", (80, 100, 110, 120, 130, 140, 150, 160, 175, 200), "rec yds in a game", pos=("WR",), stat="receiving_yards"),
    T("te_game_yds", "One-game feats", "max", "Name a TE with a {t}+ yard receiving game", (40, 50, 60, 70, 80, 90, 100, 110, 125, 150), "rec yds in a game", pos=("TE",), stat="receiving_yards"),
    T("rb_game_yds", "One-game feats", "max", "Name a RB with a {t}+ yard rushing game", (60, 70, 80, 90, 100, 110, 125, 150, 175, 200), "rush yds in a game", pos=("RB",), stat="rushing_yards"),
    T("qb_game_yds", "One-game feats", "max", "Name a QB with a {t}+ yard passing game", (200, 225, 250, 275, 300, 325, 350, 375, 400, 450), "pass yds in a game", pos=("QB",), stat="passing_yards"),
    T("any_game_ppr", "One-game feats", "max", "Name a player with a {t}+ PPR point game", (15, 20, 25, 30, 35, 40, 45, 50), "PPR pts in a game", pos="SKILL", stat="fpts"),
    T("qb_game_td", "One-game feats", "max", "Name a QB who threw {t}+ touchdown passes in one game", (1, 2, 3, 4, 5), "pass TD in a game", pos=("QB",), stat="passing_tds"),
    T("any_game_rec", "One-game feats", "max", "Name a player with {t}+ catches in one game", (4, 5, 6, 7, 8, 9, 10, 11, 12, 13), "rec in a game", pos="REC", stat="receptions"),
    T("qb_game_rush", "One-game feats", "max", "Name a QB with {t}+ rushing yards in one game", (20, 30, 40, 50, 60, 70, 80, 100), "rush yds in a game", pos=("QB",), stat="rushing_yards"),
    T("rb_game_rec", "One-game feats", "max", "Name a RB with {t}+ receiving yards in one game", (25, 35, 45, 55, 65, 75, 90, 100), "rec yds in a game", pos=("RB",), stat="receiving_yards"),

    # ---- SAME-GAME COMBOS ----------------------------------------------------------------------
    T("combo_rb_100_td", "Same-game combos", "games", "Name a RB who ran for 100+ yards AND scored in the same game{times}", (1, 2, 3, 4, 5), "games", pos=("RB",), cond=[("rushing_yards", ">=", 100), ("tds", ">=", 1)], count_games=True),
    T("combo_wr_100_td", "Same-game combos", "games", "Name a WR with 100+ receiving yards AND a TD in the same game{times}", (1, 2, 3, 4, 5), "games", pos=("WR",), cond=[("receiving_yards", ">=", 100), ("receiving_tds", ">=", 1)], count_games=True),
    T("combo_qb_dual", "Same-game combos", "games", "Name a QB who threw a TD AND ran for a TD in the same game{times}", (1, 2, 3, 4), "games", pos=("QB",), cond=[("passing_tds", ">=", 1), ("rushing_tds", ">=", 1)], count_games=True),
    T("combo_rb_5050", "Same-game combos", "games", "Name a RB with 50+ rushing AND 50+ receiving yards in the same game{times}", (1, 2, 3, 4), "games", pos=("RB",), cond=[("rushing_yards", ">=", 50), ("receiving_yards", ">=", 50)], count_games=True),
    T("combo_rush_rec_td", "Same-game combos", "games", "Name a player with a rushing TD AND a receiving TD in the same game{times}", (1, 2, 3), "games", pos="SKILL", cond=[("rushing_tds", ">=", 1), ("receiving_tds", ">=", 1)], count_games=True),
    T("combo_qb_300_3td", "Same-game combos", "games", "Name a QB with 300+ passing yards AND 3+ TD passes in the same game{times}", (1, 2, 3, 4), "games", pos=("QB",), cond=[("passing_yards", ">=", 300), ("passing_tds", ">=", 3)], count_games=True),
    T("combo_wr_8_100", "Same-game combos", "games", "Name a WR with 8+ catches AND 100+ yards in the same game{times}", (1, 2, 3, 4), "games", pos=("WR",), cond=[("receptions", ">=", 8), ("receiving_yards", ">=", 100)], count_games=True),
    T("combo_te_td_5", "Same-game combos", "games", "Name a TE with a TD AND 5+ catches in the same game{times}", (1, 2, 3), "games", pos=("TE",), cond=[("receiving_tds", ">=", 1), ("receptions", ">=", 5)], count_games=True),

    # ---- CONSISTENCY (count the games) ---------------------------------------------------------
    T("n_wr_100", "Repeat performers", "games", "Name a WR with {t}+ games of 100+ receiving yards", (1, 2, 3, 4, 5, 6, 7), "100-yd games", pos=("WR",), cond=[("receiving_yards", ">=", 100)]),
    T("n_rb_100", "Repeat performers", "games", "Name a RB with {t}+ games of 100+ rushing yards", (1, 2, 3, 4, 5, 6, 7), "100-yd games", pos=("RB",), cond=[("rushing_yards", ">=", 100)]),
    T("n_any_td", "Repeat performers", "games", "Name a player who has scored in {t}+ games (rushing/receiving TD)", (1, 2, 3, 4, 5, 6, 7, 8), "games with a TD", pos="SKILL", cond=[("tds", ">=", 1)]),
    T("n_boom", "Repeat performers", "games", "Name a player with {t}+ games of 20+ PPR points", (1, 2, 3, 4, 5, 6, 7, 8), "20+ PPR games", pos="SKILL", cond=[("fpts", ">=", 20)]),
    T("n_qb_300", "Repeat performers", "games", "Name a QB with {t}+ games of 300+ passing yards", (1, 2, 3, 4, 5, 6), "300-yd games", pos=("QB",), cond=[("passing_yards", ">=", 300)]),
    T("n_multi_td", "Repeat performers", "games", "Name a player with {t}+ multi-TD games (2+ rushing/receiving TDs)", (1, 2, 3), "multi-TD games", pos="SKILL", cond=[("tds", ">=", 2)]),

    # ---- STREAKS (consecutive team games) ------------------------------------------------------
    T("s_td", "Streaks", "streak", "Name a player who has scored in {t}+ straight games", (2, 3, 4, 5, 6, 7), "straight TD games", pos="SKILL", cond=[("tds", ">=", 1)]),
    T("s_wr_100", "Streaks", "streak", "Name a WR with 75+ receiving yards in {t}+ straight games", (2, 3, 4, 5, 6), "straight 75-yd games", pos=("WR",), cond=[("receiving_yards", ">=", 75)]),
    T("s_rb_100", "Streaks", "streak", "Name a RB with 60+ rushing yards in {t}+ straight games", (2, 3, 4, 5, 6), "straight 60-yd games", pos=("RB",), cond=[("rushing_yards", ">=", 60)]),

    # ---- EFFICIENCY (with a volume minimum that grows with the season) --------------------------
    T("e_rb_ypc", "Efficiency", "ratio", "Name a RB averaging {t}+ yards per carry (min {min} carries)", (4.0, 4.5, 5.0, 5.5, 6.0, 6.5), "yds/carry", pos=("RB",), num="rushing_yards", den="carries", min_den_pg=6),
    T("e_wr_ypt", "Efficiency", "ratio", "Name a WR averaging {t}+ yards per target (min {min} targets)", (7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 11.0), "yds/target", pos=("WR",), num="receiving_yards", den="targets", min_den_pg=4),
    T("e_qb_cmp", "Efficiency", "ratio", "Name a QB completing {t}%+ of his passes (min {min} attempts)", (60, 62, 64, 66, 68, 70), "comp %", pos=("QB",), num="completions", den="attempts", mult=100, min_den_pg=18),
    T("e_qb_ypa", "Efficiency", "ratio", "Name a QB averaging {t}+ yards per attempt (min {min} attempts)", (6.5, 7.0, 7.5, 8.0, 8.5, 9.0), "yds/att", pos=("QB",), num="passing_yards", den="attempts", min_den_pg=18),
    T("e_wr_ypr", "Efficiency", "ratio", "Name a WR averaging {t}+ yards per catch (min {min} catches)", (12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0), "yds/catch", pos=("WR",), num="receiving_yards", den="receptions", min_den_pg=2.5),
    T("e_qb_tdpct", "Efficiency", "ratio", "Name a QB throwing a TD on {t}%+ of his attempts (min {min} attempts)", (3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0), "TD %", pos=("QB",), num="passing_tds", den="attempts", mult=100, min_den_pg=18),
    T("e_qb_safe", "Efficiency", "ratio", "Name a QB with an interception rate under {t}% (min {min} attempts)", (-3.0, -2.5, -2.0, -1.5, -1.0, -0.5), "INT %", pos=("QB",), num="interceptions", den="attempts", mult=100, min_den_pg=18, neg=True),
    T("e_wr_share", "Efficiency", "mean", "Name a WR with a {t}%+ target share (min {min} games played)", (15, 18, 20, 22, 25, 28, 30), "target share %", pos=("WR",), stat="target_share", mult=100, min_games_pg=0.7),

    # ---- DIVISION / CONFERENCE / TEAM SCOPED (the scope rotates by date) -----------------------
    T("sc_conf_rush_td", "Scoped to a conference", "sum", "Name an {scope} player with {t}+ rushing TDs", (1, 2, 3, 4, 5, 6, 8), "rush TD", pos="SKILL", stat="rushing_tds", scope="conference"),
    T("sc_div_rec_td", "Scoped to a division", "sum", "Name a {scope} player with {t}+ receiving TDs", (1, 2, 3, 4, 5), "rec TD", pos="REC", stat="receiving_tds", scope="division"),
    T("sc_conf_wr_yds", "Scoped to a conference", "sum", "Name an {scope} WR with {t}+ receiving yards", (200, 300, 400, 500, 600, 700, 800, 900, 1000), "rec yds", pos=("WR",), stat="receiving_yards", scope="conference"),
    T("sc_conf_rb_yds", "Scoped to a conference", "sum", "Name an {scope} RB with {t}+ rushing yards", (100, 200, 300, 400, 500, 600, 700, 800, 1000), "rush yds", pos=("RB",), stat="rushing_yards", scope="conference"),
    T("sc_div_ppr_game", "Scoped to a division", "max", "Name a {scope} player with a {t}+ PPR point game", (15, 18, 20, 22, 25, 30, 35), "PPR pts in a game", pos="SKILL", stat="fpts", scope="division"),
    T("sc_conf_qb_td", "Scoped to a conference", "sum", "Name an {scope} QB with {t}+ touchdown passes", (2, 4, 6, 8, 10, 12, 15, 18, 20, 25), "pass TD", pos=("QB",), stat="passing_tds", scope="conference"),
    T("sc_conf_te_td", "Scoped to a conference", "sum", "Name an {scope} TE with {t}+ receiving TDs", (1, 2, 3, 4), "rec TD", pos=("TE",), stat="receiving_tds", scope="conference"),
    T("sc_col_td", "Scoped to a college conference", "sum", "Name an {scope} alum with {t}+ rushing or receiving TDs", (1, 2, 3, 4, 5), "TD", pos="SKILL", stat="tds", scope="college"),

    # ---- GAME CONTEXT (opponent, night, roof, margin) ------------------------------------------
    T("x_div_td", "Game context", "sum", "Name a player who scored against a division rival{times}", (1, 2, 3), "TD vs division", pos="SKILL", stat="tds", where=["div"]),
    T("x_div_wr_100", "Game context", "max", "Name a WR with {t}+ receiving yards in a game against a division rival", (60, 80, 90, 100, 110, 120, 130, 150), "rec yds vs division", pos=("WR",), stat="receiving_yards", where=["div"]),
    T("x_night_td", "Game context", "sum", "Name a player who scored in a primetime game{times}", (1, 2, 3), "primetime TD", pos="SKILL", stat="tds", where=["night"]),
    T("x_road_rb", "Game context", "max", "Name a RB with a {t}+ yard rushing game on the road", (50, 60, 70, 80, 90, 100, 110, 125), "rush yds on the road", pos=("RB",), stat="rushing_yards", where=["road"]),
    T("x_dome_td", "Game context", "sum", "Name a player who scored in a dome or closed-roof game{times}", (1, 2, 3), "dome TD", pos="SKILL", stat="tds", where=["dome"]),
    T("x_ot_ppr", "Game context", "max", "Name a player with {t}+ PPR points in an overtime game", (8, 12, 15, 18, 20, 25, 30), "PPR pts in OT game", pos="SKILL", stat="fpts", where=["ot"]),
    T("x_loss_td", "Game context", "sum", "Name a player who scored in a one-score loss (8 points or fewer){times}", (1, 2, 3), "TD in a close loss", pos="SKILL", stat="tds", where=["close_loss"]),
    T("x_loss_ppr", "Game context", "max", "Name a player with {t}+ PPR points in a loss", (15, 20, 25, 30, 35, 40), "PPR pts in a loss", pos="SKILL", stat="fpts", where=["loss"]),
    T("x_upset_td", "Game context", "sum", "Name a player who scored in an upset win (his team was the underdog){times}", (1, 2, 3), "TD in an upset", pos="SKILL", stat="tds", where=["upset"]),
    T("x_shootout", "Game context", "sum", "Name a player who scored in a shootout (60+ combined points){times}", (1, 2, 3), "TD in a shootout", pos="SKILL", stat="tds", where=["shootout"]),

    # ---- LAST WEEK / LAST THREE WEEKS ----------------------------------------------------------
    T("w_ppr20", "Last week", "max", "Name a player with {t}+ PPR points last week", (12, 15, 18, 20, 22, 25, 30), "PPR pts last week", pos="SKILL", stat="fpts", window="last"),
    T("w_rb_td", "Last week", "sum", "Name a RB with {t}+ rushing TDs last week", (1, 2), "rush TD last week", pos=("RB",), stat="rushing_tds", window="last"),
    T("w_wr_100", "Last week", "max", "Name a WR with {t}+ receiving yards last week", (50, 60, 70, 80, 90, 100, 110), "rec yds last week", pos=("WR",), stat="receiving_yards", window="last"),
    T("w_rb_100", "Last week", "max", "Name a RB with {t}+ rushing yards last week", (40, 50, 60, 70, 80, 90, 100), "rush yds last week", pos=("RB",), stat="rushing_yards", window="last"),
    T("w_qb_300", "Last week", "max", "Name a QB with {t}+ passing yards last week", (150, 200, 225, 250, 275, 300), "pass yds last week", pos=("QB",), stat="passing_yards", window="last"),
    T("w3_td", "Last three weeks", "sum", "Name a player with {t}+ TDs over the last three weeks", (1, 2, 3, 4), "TD, last 3 wks", pos="SKILL", stat="tds", window=3),
    T("w3_ppr", "Last three weeks", "sum", "Name a player with {t}+ PPR points over the last three weeks", (15, 20, 25, 30, 35, 40, 45, 50, 60), "PPR pts, last 3 wks", pos="SKILL", stat="fpts", window=3),
    T("w3_wr_yds", "Last three weeks", "sum", "Name a WR with {t}+ receiving yards over the last three weeks", (60, 80, 100, 125, 150, 175, 200, 225), "rec yds, last 3 wks", pos=("WR",), stat="receiving_yards", window=3),
    T("w3_rb_yds", "Last three weeks", "sum", "Name a RB with {t}+ rushing yards over the last three weeks", (50, 75, 100, 125, 150, 175, 200, 225, 250), "rush yds, last 3 wks", pos=("RB",), stat="rushing_yards", window=3),

    # ---- ROOKIES -------------------------------------------------------------------------------
    T("r_td", "Rookies", "sum", "Name a rookie with {t}+ rushing or receiving TDs", (1, 2, 3, 4), "TD", pos="SKILL", stat="tds", rookie=True),
    T("r_wr_yds", "Rookies", "sum", "Name a rookie WR with {t}+ receiving yards", (20, 40, 60, 80, 100, 150, 200, 300), "rec yds", pos=("WR",), stat="receiving_yards", rookie=True),
    T("r_game_ppr", "Rookies", "max", "Name a rookie with a {t}+ PPR point game", (6, 8, 10, 12, 15, 18, 20, 25), "PPR pts in a game", pos="SKILL", stat="fpts", rookie=True),
    T("r_scrim", "Rookies", "sum", "Name a rookie with {t}+ scrimmage yards (rushing + receiving)", (20, 40, 60, 80, 100, 150, 200, 300), "scrim yds", pos="SKILL", stat="scrim", rookie=True),
    T("r_catch", "Rookies", "sum", "Name a rookie with {t}+ catches", (2, 4, 6, 8, 10, 15, 20, 30), "rec", pos="REC", stat="receptions", rookie=True),

    # ---- DEFENSE / KICKING / RETURNS -----------------------------------------------------------
    T("d_sacks", "Defense", "sum", "Name a defender with {t}+ sacks", (1, 2, 3, 4, 5, 6, 7, 8, 10, 12), "sacks", pos="DEF", stat="def_sacks", tie="val"),
    T("d_picks", "Defense", "sum", "Name a defender with {t}+ interceptions", (1, 2, 3, 4, 5), "INT", pos="DEF", stat="def_interceptions", tie="val"),
    T("d_tackles", "Defense", "sum", "Name a defender with {t}+ tackles", (10, 20, 30, 40, 50, 60, 70, 80, 90, 100), "tackles", pos="DEF", stat="tkl", tie="val"),
    T("d_ff", "Defense", "sum", "Name a defender who has forced {t}+ fumbles", (1, 2, 3, 4, 5), "forced fumbles", pos="DEF", stat="def_fumbles_forced", tie="val"),
    T("d_pbu", "Defense", "sum", "Name a defender with {t}+ passes defended", (1, 2, 3, 4, 5, 6, 8, 10, 12), "PD", pos="DEF", stat="def_pass_defended", tie="val"),
    T("d_game_tkl", "Defense", "max", "Name a defender with {t}+ tackles in one game", (6, 8, 9, 10, 11, 12, 13, 14, 15), "tackles in a game", pos="DEF", stat="tkl", tie="val"),
    T("k_fg", "Kicking", "sum", "Name a kicker with {t}+ field goals made", (3, 5, 8, 10, 12, 14, 16, 18, 20, 22), "FG", pos="K", stat="fg_made", tie="val"),
    T("k_long", "Kicking", "max", "Name a kicker with a {t}+ yard field goal", (40, 45, 48, 50, 52, 54, 56, 58, 60), "long FG", pos="K", stat="fg_long", tie="val"),
    T("k_50", "Kicking", "sum", "Name a kicker with {t}+ field goals from 50 or more yards", (1, 2, 3, 4, 5), "FG 50+", pos="K", stat="fg_50p", tie="val"),
    T("p_in20", "Kicking", "sum", "Name a punter with {t}+ punts downed inside the 20", (3, 5, 8, 10, 12, 15, 18, 20, 25), "punts inside 20", pos="P", stat="pt_inside_20", tie="val"),

    # ---- BALL SECURITY, SACKS AND ODDITIES -----------------------------------------------------
    T("o_qb_sacked", "Odd angles", "sum", "Name a QB who has been sacked {t}+ times", (5, 10, 15, 20, 25, 30, 35), "sacks taken", pos=("QB",), stat="sacks"),
    T("o_qb_int", "Odd angles", "sum", "Name a QB who has thrown {t}+ interceptions", (1, 2, 3, 4, 5, 6, 8, 10, 12), "INT", pos=("QB",), stat="interceptions"),
    T("o_fum_lost", "Odd angles", "sum", "Name a player who has lost {t}+ fumbles", (1, 2, 3, 4), "fumbles lost", pos="SKILL", stat="fumlost"),
    T("o_wr_rush", "Odd angles", "sum", "Name a WR with {t}+ rushing attempts", (1, 2, 3, 4, 5), "carries", pos=("WR",), stat="carries"),
    T("o_qb_rush_td", "Odd angles", "sum", "Name a QB who has rushed for {t}+ touchdowns", (1, 2, 3, 4, 5, 6), "rush TD", pos=("QB",), stat="rushing_tds"),
    T("o_qb_run", "Odd angles", "sum", "Name a QB with {t}+ rushing attempts", (5, 10, 15, 20, 30, 40, 50, 60, 70, 80), "carries", pos=("QB",), stat="carries"),
    T("o_swing", "Odd angles", "range", "Name a player whose best and worst PPR weeks are {t}+ points apart (min {min} games)", (10, 15, 20, 25, 30, 35, 40), "swing", pos="SKILL", stat="fpts", min_games_pg=0.6),

    # ---- FANTASY FINISHES ----------------------------------------------------------------------
    T("f_wr1", "Fantasy finishes", "topfinish", "Name a WR who has finished a week as a top-12 WR in PPR scoring {t}+ times", (1, 2, 3, 4, 5, 6), "WR1 weeks", pos=("WR",), top=12),
    T("f_rb1", "Fantasy finishes", "topfinish", "Name a RB who has finished a week as a top-12 RB in PPR scoring {t}+ times", (1, 2, 3, 4, 5, 6), "RB1 weeks", pos=("RB",), top=12),
    T("f_te1", "Fantasy finishes", "topfinish", "Name a TE who has finished a week as a top-6 TE in PPR scoring {t}+ times", (1, 2, 3, 4, 5), "TE1 weeks", pos=("TE",), top=6),
    T("f_qb1", "Fantasy finishes", "topfinish", "Name a QB who has finished a week as a top-6 QB in PPR scoring {t}+ times", (1, 2, 3, 4, 5, 6), "QB1 weeks", pos=("QB",), top=6),
]


# ----------------------------------------------------------------------------------------------- scope rotation
def scope_for(tpl, date_str):
    """The scope variant (division / conference / team / college conference) a scoped template uses on `date_str`.
    Deterministic: the same date always gives the same scope."""
    options = SCOPES[tpl["scope"]]
    h = int(hashlib.sha256(f"dd-pool:{tpl['key']}:{date_str}".encode()).hexdigest()[:8], 16)
    return options[h % len(options)]


def scope_label(kind, scope):
    return TEAM_NAME[scope] if kind == "team" else scope


# ----------------------------------------------------------------------------------------------- context
def _prep(wk):
    """The derived columns the pool uses, on top of the nflverse weekly player stats."""
    wk = wk.copy()
    z = lambda c: wk[c].fillna(0) if c in wk.columns else 0
    wk["fpts"] = wk["fantasy_points_ppr"]
    wk["tds"] = z("rushing_tds") + z("receiving_tds")
    wk["all_tds"] = wk["tds"] + z("passing_tds")
    wk["scrim"] = z("rushing_yards") + z("receiving_yards")
    wk["fd"] = z("rushing_first_downs") + z("receiving_first_downs")
    wk["tkl"] = z("def_tackles_solo") + z("def_tackle_assists")
    wk["two_pt"] = z("passing_2pt_conversions") + z("rushing_2pt_conversions") + z("receiving_2pt_conversions")
    wk["fg_50p"] = z("fg_made_50_59") + z("fg_made_60_")
    wk["fumlost"] = z("fumbles_lost_total")
    wk["def_td_any"] = z("def_tds") + z("fumble_recovery_tds")
    return wk


def _game_table(sched, through):
    """One row per (team, game) of finished regular-season games: venue, result, the context flags, team-game index."""
    s = sched[(sched["game_type"] == "REG") & sched["home_score"].notna() & (sched["week"] <= through)] if "game_type" in sched.columns else \
        sched[sched["home_score"].notna() & (sched["week"] <= through)]
    s = s.copy()
    ot = s["overtime"].fillna(0) if "overtime" in s.columns else 0
    hour = s["gametime"].fillna("13:00").str.slice(0, 2).astype(int) if "gametime" in s.columns else 13
    night = hour >= 19                                            # 7pm ET kickoff or later: Thu / Sun / Mon night games
    total = s["home_score"] + s["away_score"]
    wins = {}
    for r in s.itertuples(index=False):
        w, l = (r.home_team, r.away_team) if r.home_score > r.away_score else (r.away_team, r.home_team)
        if r.home_score != r.away_score:
            wins.setdefault(w, [0, 0])[0] += 1
            wins.setdefault(l, [0, 0])[1] += 1
    over500 = {t: (w > l) for t, (w, l) in wins.items()}
    rows = []
    for side in ("home", "away"):
        mine, theirs = f"{side}_team", ("away_team" if side == "home" else "home_team")
        my_pts, their_pts = f"{side}_score", ("away_score" if side == "home" else "home_score")
        g = pd.DataFrame({
            "game_id": s["game_id"], "week": s["week"], "team": s[mine], "opp": s[theirs], "home": side == "home",
            "pts": s[my_pts], "opp_pts": s[their_pts], "div_game": s["div_game"].fillna(0).astype(bool),
            "ot_game": ot.astype(float) > 0 if hasattr(ot, "astype") else False,
            "night_game": night, "roof": s["roof"] if "roof" in s.columns else None, "total": total,
            "fav_pts": s["spread_line"] if side == "home" else -s["spread_line"],
        })
        rows.append(g)
    g = pd.concat(rows, ignore_index=True)
    g["margin"] = g["pts"] - g["opp_pts"]
    g["f_div"] = g["div_game"]
    g["f_road"] = ~g["home"]
    g["f_home"] = g["home"]
    g["f_night"] = g["night_game"]
    g["f_dome"] = g["roof"].isin(["dome", "closed"])
    g["f_ot"] = g["ot_game"]
    g["f_win"] = g["margin"] > 0
    g["f_loss"] = g["margin"] < 0
    g["f_close_loss"] = (g["margin"] < 0) & (g["margin"] >= -8)
    g["f_dog"] = g["fav_pts"].notna() & (g["fav_pts"] < 0)               # spread_line > 0 = home favored; fav_pts < 0 = this team not favored
    g["f_upset"] = g["f_dog"] & g["f_win"]
    g["f_vs_winning"] = g["opp"].map(over500).fillna(False).astype(bool)
    g["f_shootout"] = g["total"] >= 60
    g["f_blowout_win"] = g["margin"] >= 17
    g = g.sort_values(["team", "week"]).reset_index(drop=True)
    g["gidx"] = g.groupby("team").cumcount()
    return g


def build_context(wk, sched, season, through, draft=None):
    """Everything the evaluators read, for `season` through its latest finished week `through`.
    wk = that season's weekly player rows, sched = that season's schedule, draft = the draft-picks table (optional:
    without it rookie and college prompts are simply unavailable, never guessed)."""
    wk = wk[wk["season_type"] == "REG"] if "season_type" in wk.columns else wk
    wk = _prep(wk[wk["week"] <= through])
    g = _game_table(sched, through)
    flags = g[["game_id", "team", "gidx"] + [c for c in g.columns if c.startswith("f_")]].rename(columns={"team": "recent_team"})
    gm = wk.merge(flags, on=["game_id", "recent_team"], how="left")
    for c in [c for c in gm.columns if c.startswith("f_")]:
        gm[c] = gm[c].fillna(False).astype(bool)
    # weekly finish among the same position (PPR), for the top-finish prompts
    gm["pos_rank"] = gm.groupby(["week", "position"])["fpts"].rank(method="min", ascending=False)
    ctx = {"g": gm, "season": season, "through": int(through), "rookies": None, "college": None,
           "ppr": gm.groupby("player_id")["fpts"].sum()}
    if draft is not None and len(draft):
        d = draft[draft["gsis_id"].notna()]
        ctx["rookies"] = set(d.loc[d["season"] == season, "gsis_id"])
        ctx["college"] = dict(zip(d["gsis_id"], d["college"]))
    return ctx


# ----------------------------------------------------------------------------------------------- evaluators
def _pos(tpl):
    p = tpl["pos"]
    return POS_SETS[p] if isinstance(p, str) else tuple(p)


def _cond_mask(df, cond):
    m = pd.Series(True, index=df.index)
    for col, op, v in cond:
        m &= _OPS[op](df[col].fillna(0), v)
    return m


def _rows(tpl, ctx, scope=None):
    """The game rows a template looks at: position, rookie, scope, game-context and time-window filters applied."""
    g = ctx["g"]
    g = g[g["position"].isin(_pos(tpl))]
    if tpl.get("rookie"):
        if ctx["rookies"] is None:
            return g.iloc[0:0]
        g = g[g["player_id"].isin(ctx["rookies"])]
    for f in tpl.get("where", ()):
        g = g[g[f"f_{f}"]]
    w = tpl.get("window")
    if w == "last":
        g = g[g["week"] == ctx["through"]]
    elif isinstance(w, int):
        g = g[g["week"] > ctx["through"] - w]
    kind = tpl.get("scope")
    if kind == "division":
        g = g[g["recent_team"].isin(DIVISIONS[scope])]
    elif kind == "conference":
        g = g[g["recent_team"].map(lambda t: TEAM_DIV.get(t, "")[:3] == scope)]
    elif kind == "team":
        g = g[g["recent_team"] == scope]
    elif kind == "college":
        if ctx["college"] is None:
            return g.iloc[0:0]
        g = g[g["player_id"].map(ctx["college"]).isin(COLLEGE_CONF[scope])]
    return g


def _frame(rows, vals, ctx, tie):
    """Standard per-player frame the tiering path expects (player_id, name, pos, team, headshot, val, ppr)."""
    last = rows.sort_values("week").groupby("player_id").last()
    out = pd.DataFrame({"name": last["player_display_name"], "pos": last["position"], "team": last["recent_team"],
                        "headshot": last["headshot_url"] if "headshot_url" in last.columns else None})
    out["val"] = vals.reindex(out.index)
    out["ppr"] = out["val"] if tie == "val" else ctx["ppr"].reindex(out.index).fillna(0.0)
    return out.dropna(subset=["val"]).reset_index().rename(columns={"index": "player_id"})


def evaluate(tpl, ctx, scope=None):
    """Per-player frame for a template: one row per player with `val` (the number the ladder is walked against)."""
    rows = _rows(tpl, ctx, scope)
    tie = tpl.get("tie", "ppr")
    kind = tpl["kind"]
    through = ctx["through"]
    if rows.empty:
        return _frame(rows, pd.Series(dtype=float), ctx, tie)
    grp = rows.groupby("player_id")
    if kind == "sum":
        vals = grp[tpl["stat"]].sum()
        for col, mn in tpl.get("also", ()):
            vals = vals[grp[col].sum().reindex(vals.index) >= mn]
    elif kind == "max":
        vals = grp[tpl["stat"]].max()
    elif kind == "games":
        ok = rows[_cond_mask(rows, tpl["cond"])]
        vals = ok.groupby("player_id").size().astype(float)
    elif kind == "ratio":
        num, den = grp[tpl["num"]].sum(), grp[tpl["den"]].sum()
        need = tpl["min_den_pg"] * through
        vals = (num / den.where(den >= need)) * tpl.get("mult", 1)
        vals = -vals if tpl.get("neg") else vals
    elif kind == "mean":
        n = grp.size()
        vals = (grp[tpl["stat"]].mean() * tpl.get("mult", 1)).where(n >= tpl["min_games_pg"] * through)
    elif kind == "range":
        n = grp.size()
        vals = (grp[tpl["stat"]].max() - grp[tpl["stat"]].min()).where(n >= tpl["min_games_pg"] * through)
    elif kind == "topfinish":
        vals = rows[rows["pos_rank"] <= tpl["top"]].groupby("player_id").size().astype(float)
    elif kind == "streak":
        ok = rows[_cond_mask(rows, tpl["cond"])].sort_values(["player_id", "week"])
        out = {}
        for pid, grp2 in ok.groupby("player_id"):
            run, prev, top = 0, None, 0
            for team, idx in zip(grp2["recent_team"], grp2["gidx"]):
                run = run + 1 if prev is not None and prev == (team, idx - 1) else 1
                prev = (team, idx)
                top = max(top, run)
            out[pid] = top
        vals = pd.Series(out, dtype=float)
    else:
        raise ValueError(f"unknown kind {kind!r}")
    return _frame(rows, vals, ctx, tie)


def min_volume(tpl, through):
    """The volume minimum shown in the text of efficiency prompts: per-week rate x weeks played (rounded)."""
    rate = tpl.get("min_den_pg") if "min_den_pg" in tpl else tpl.get("min_games_pg")
    if rate is None:
        return None
    return max(1, int(round(rate * through)))


def fmt_threshold(t):
    t = abs(t)
    if float(t) == int(t):
        return f"{int(t):,}"
    return f"{t:g}"


def render_text(tpl, t, through, scope=None):
    fields = {"t": fmt_threshold(t), "times": "" if t == 1 else f", {fmt_threshold(t)}+ times", "min": min_volume(tpl, through), "scope": scope_label(tpl.get("scope"), scope) if scope else ""}
    text = tpl["text"].format(**fields)
    text = re.sub(r"\b([Aa]) (8|11|18)(?=[\d,]*\+)", lambda m: m.group(1) + "n " + m.group(2), text)    # "a 80+" -> "an 80+"
    return tidy_text(text)


_TIDY = [
    (r"\b1\+ (rushing|receiving|passing) TDs\b", r"a \1 TD"),       # "with 1+ rushing TDs" -> "with a rushing TD"
    (r"\b1\+ touchdowns\b", "a touchdown"),
    (r"\bwith 1\+ games of ", "with a game of "),
    (r" 1\+ times\b", " at least once"),
    (r"\b([Aa]) (AFC|NFC|ACC|SEC)\b", lambda m: m.group(1) + "n " + m.group(2)),   # "a NFC North" -> "an NFC North"
]


def tidy_text(text):
    """Plain English for the bottom rung of a ladder: no "1+ TDs", no "a NFC"."""
    for pat, rep in _TIDY:
        text = re.sub(pat, rep, text)
    return text


def build_pool_prompt(tpl, ctx, ecr_rank=None, fame=None, scope=None):
    """One prompt through the real tiering path (dd.pick_threshold). Returns None when no ladder rung leaves
    dd.MIN_ANSWERS answers with a tier-6 (Highlight Reel TD) answer."""
    through, season = ctx["through"], ctx["season"]
    per = evaluate(tpl, ctx, scope)
    if per.empty:
        return None
    t, answers = dd.pick_threshold(per, tpl["ladder"], ecr_rank, tpl["label"], fame)
    if t is None:
        return None
    sid = f":{scope}" if scope else ""
    return {"id": f"p:{tpl['key']}:{season}:w{through}:t{t}{sid}".replace(" ", "_"), "template": tpl["key"], "kind": "fantasy",
            "text": render_text(tpl, t, through, scope), "category": f"This season · through Week {through}",
            "cat": tpl["cat"], "answers": answers, "threshold": t, "group": tpl.get("group", tpl["key"])}


def pool_candidates(ctx, date_str, ecr_rank=None, fame=None, pool=None):
    """Every buildable prompt for `date_str` (one per template; scoped templates use that day's scope)."""
    out = []
    for tpl in (POOL if pool is None else pool):
        scope = scope_for(tpl, date_str) if tpl.get("scope") else None
        p = build_pool_prompt(tpl, ctx, ecr_rank, fame, scope)
        if p:
            out.append(p)
    return out
