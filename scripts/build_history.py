"""
Build the prior-season history the projections lean on (engine/history.py).

Run locally, commit the output:

    .venv/bin/python scripts/build_history.py            # default 2023-2025
    .venv/bin/python scripts/build_history.py 2024 2025 2026

Why a build step instead of loading old seasons at runtime: a raw season of
weekly stats is ~27 MB resident and a play-by-play season is far more, and
the production host has a 512 MiB cap it has already been OOM-killed on.
This keeps only the columns that fantasy scoring reads, regular season only,
so three seasons come to a few MB on disk and in memory.

Three files in history_data/:
  skill_weekly.parquet  QB/RB/WR/TE player-games with the counting stats
                        engine/scoring.compute_fantasy_points reads
  kicker_weekly.parquet engine/kicker_scoring.build_kicker_weekly rows
  defense_weekly.parquet engine/defense_scoring.build_defense_weekly rows
Every row carries its season. Fantasy points are NOT stored: they depend on
the viewer's league scoring, so engine/history.py scores them at read time.
"""

import os
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import data, defense_scoring, kicker_scoring  # noqa: E402

OUT_DIR = os.path.join(ROOT, "history_data")
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
SKILL_COLUMNS = [
    "player_id", "player_display_name", "position", "season", "week", "recent_team", "opponent_team",
    "passing_yards", "passing_tds", "interceptions", "rushing_yards", "rushing_tds",
    "receiving_yards", "receiving_tds", "receptions", "targets", "carries", "attempts",
    "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost",
    "passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions",
    "special_teams_tds", "passing_first_downs", "rushing_first_downs", "receiving_first_downs",
    "fantasy_points_ppr",
]


def build(seasons):
    skill, kick, deff = [], [], []
    for s in seasons:
        print(f"[history] {s}: weekly stats")
        wk = data.load_weekly(s)
        wk = wk[wk["position"].isin(SKILL_POSITIONS)]
        if "season_type" in wk.columns:
            wk = wk[wk["season_type"] == "REG"]
        wk = wk.assign(season=s)
        keep = [c for c in SKILL_COLUMNS if c in wk.columns]
        part = wk[keep].copy()
        for c in keep:
            if part[c].dtype == "float64":
                part[c] = part[c].astype("float32")
        skill.append(part)

        print(f"[history] {s}: play-by-play (kickers, defenses)")
        pbp = data.load_pbp(s)
        k = kicker_scoring.build_kicker_weekly(pbp)
        k = k[k["week"] <= 18]          # regular season only, as the docstring promises (pbp includes the playoffs)
        k["season"] = s
        kick.append(k)
        d = defense_scoring.build_defense_weekly(pbp, data.load_schedule(s))
        d = d.reset_index() if "defteam" not in d.columns else d
        d = d[d["week"] <= 18]
        d["season"] = s
        deff.append(d)

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, frames in (("skill_weekly", skill), ("kicker_weekly", kick), ("defense_weekly", deff)):
        df = pd.concat(frames, ignore_index=True)
        path = os.path.join(OUT_DIR, f"{name}.parquet")
        df.to_parquet(path, index=False, compression="zstd")
        print(f"[history] wrote {path}: {len(df)} rows, {os.path.getsize(path) / 1e6:.2f} MB on disk, "
              f"{df.memory_usage(deep=True).sum() / 1e6:.1f} MB in memory")


if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or [2023, 2024, 2025]
    build(years)
