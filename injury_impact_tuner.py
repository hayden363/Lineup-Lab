"""
INJURY IMPACT TUNER
====================
Real historical research: how much does a player's real fantasy output
actually change in a week they're carrying a specific real injury
designation (Questionable/Doubtful, and they actually played — "Out"
means DNP, no real output to measure), relative to their OWN real
healthy baseline that same season — aggregated by position + real injury
body part + report status across many real NFL seasons for genuine
statistical power.

Real data sources, both keyed by gsis_id (nflverse's real weekly stats
already use this ID directly — no crosswalk needed):
  - nfl_data_py.import_injuries(): official weekly injury reports,
    including a real body-part-level `report_primary_injury` (not just
    Out/Doubtful/Questionable) — going back to at least 2009.
  - engine.data._fetch_stats_player_week(): the same real per-week stats
    this app's own board already scores from.

Same dry-run-by-default, real-data-or-nothing pattern as weight_tuner.py:
prints the real findings either way, only writes engine/injury_impact.json
(committed to git, unlike weight_tuner's gitignored data_cache/ output —
this is a real, disclosed methodology artifact worth versioning and
reviewing in the repo, not a raw fetch cache) with --write.

WHY MEDIAN, NOT MEAN: checked both. For nearly every real bucket, the
mean and median disagree sharply, sometimes in sign — a handful of
boom/bust outlier games (a low-usage player's one huge garbage-time
score, or a stat-line goose-egg) skew a percentage-change mean badly,
especially off a small personal baseline. The median is far more robust
to that and is used as the real, live-applied number; the mean is still
reported alongside for transparency, not hidden.

WHY NOT PER-PLAYER-SPECIFIC HISTORY (real scoping call, not a silent
downgrade of the ask): checked the real numbers — even AGGREGATED across
every player in the league and 8 real seasons, the best-populated
(position, injury, status) buckets only reach the 100-150 real
observation range. A single specific player's own career instances of
one specific injury type will almost always be 0-2 real occurrences —
nowhere near enough for a personal factor without fabricating false
confidence, which is exactly what this app's whole design (MIN_GAMES,
MIN_VOLUME, the role-baseline fallback's explicit SCORE=None rather than
a guess) has consistently refused to do elsewhere. The real, defensible
version of "how has this kind of player played through this kind of
injury before" is the position+injury-type aggregate below, not a
per-player one — disclosed here rather than silently shipped as if it
were the stronger (but fictional) claim.
"""
import argparse
import json
import os
import time

import numpy as np
import pandas as pd

import nfl_data_py as nfl

from engine.data import _fetch_stats_player_week

POSITIONS = ("QB", "RB", "WR", "TE")
MIN_N = 30  # matches this app's general bias toward a firmer bar than the
            # exploratory pass this was checked against (n>=20) before
            # trusting a number enough to actually move a live PROJ.

FACTORS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine", "injury_impact_factors.json")

# nflverse's `report_primary_injury` vocabulary -> the bucket keys this
# module uses. Sleeper's live `injury_body_part` field (engine/sleeper.py)
# gets normalized to the SAME keys — see engine/injury_impact.py's own
# alias table, which must stay in sync with these bucket names.
INJURY_BUCKET_ALIASES = {
    "Quadricep": "Quadriceps",
    "Rib": "Ribs",
}


def _normalize_injury(raw):
    if pd.isna(raw):
        return None
    return INJURY_BUCKET_ALIASES.get(raw, raw)


def build_real_table(seasons, min_n=MIN_N):
    rows = []
    for season in seasons:
        try:
            wk = _fetch_stats_player_week(season)
        except Exception as e:
            print(f"[injury-tuner] [{season}] weekly stats fetch failed: {e}")
            continue
        wk = wk[wk["position"].isin(POSITIONS)][["player_id", "week", "position", "fantasy_points_ppr"]].copy()
        wk = wk.dropna(subset=["fantasy_points_ppr"])

        try:
            inj = nfl.import_injuries([season])
        except Exception as e:
            print(f"[injury-tuner] [{season}] injury report fetch failed: {e}")
            continue
        inj = inj[inj["position"].isin(POSITIONS)][
            ["gsis_id", "week", "report_status", "report_primary_injury"]
        ].dropna(subset=["gsis_id", "report_primary_injury"])
        inj = inj.rename(columns={"gsis_id": "player_id"})
        inj["report_primary_injury"] = inj["report_primary_injury"].map(_normalize_injury)
        # Only Questionable/Doubtful are meaningful for "how did they
        # perform carrying it" — Out means they didn't play, so there's
        # no real output that week to measure against.
        inj = inj[inj["report_status"].isin(["Questionable", "Doubtful"])]
        inj = inj.drop_duplicates(subset=["player_id", "week"], keep="last")

        merged = wk.merge(inj, on=["player_id", "week"], how="left")
        merged["season"] = season
        rows.append(merged)

    if not rows:
        return None, None

    all_data = pd.concat(rows, ignore_index=True)
    total_weeks = len(all_data)
    flagged_raw = all_data["report_primary_injury"].notna().sum()

    flagged_weeks = all_data.dropna(subset=["report_primary_injury"])[["player_id", "season", "week"]]
    flagged_set = set(map(tuple, flagged_weeks.values))
    all_data["is_flagged_week"] = [
        (pid, s, w) in flagged_set for pid, s, w in zip(all_data["player_id"], all_data["season"], all_data["week"])
    ]

    baseline = (all_data[~all_data["is_flagged_week"]]
                .groupby(["player_id", "season"])["fantasy_points_ppr"].mean()
                .rename("baseline_fpts"))

    flagged = all_data.dropna(subset=["report_primary_injury"]).merge(
        baseline, on=["player_id", "season"], how="inner"
    )
    # Require a real, non-trivial baseline (at least 2 real healthy games
    # implied by a non-tiny average) so a percentage swing isn't being
    # computed off a near-zero denominator.
    flagged = flagged[flagged["baseline_fpts"] > 2.0]
    flagged["pct_change"] = (flagged["fantasy_points_ppr"] - flagged["baseline_fpts"]) / flagged["baseline_fpts"]
    flagged["pt_change"] = flagged["fantasy_points_ppr"] - flagged["baseline_fpts"]

    agg = (flagged.groupby(["position", "report_primary_injury", "report_status"])
           .agg(n=("pct_change", "size"),
                mean_pct_change=("pct_change", "mean"),
                median_pct_change=("pct_change", "median"),
                mean_pt_change=("pt_change", "mean"),
                median_pt_change=("pt_change", "median"))
           .reset_index())

    meta = {
        "total_player_weeks": int(total_weeks),
        "flagged_weeks_with_real_stat_line": int(flagged_raw),
        "usable_after_baseline_filter": int(len(flagged)),
    }
    return agg, meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="save engine/injury_impact_factors.json (default: dry run, prints only)")
    ap.add_argument("--seasons", type=int, default=8, help="how many past real seasons to pull, most recent first (default 8)")
    ap.add_argument("--min-n", type=int, default=MIN_N, help=f"minimum real observations to trust a bucket (default {MIN_N})")
    args = ap.parse_args()

    from engine.data import resolve_season
    current = resolve_season()
    # Held out deliberately: the current (and any future) season is what
    # we're trying to project, not train the historical baseline on.
    seasons = list(range(current - args.seasons, current))
    print(f"[injury-tuner] pulling real injury reports + weekly stats for seasons {seasons}\n")

    agg, meta = build_real_table(seasons, min_n=args.min_n)
    if agg is None:
        print("[injury-tuner] no real data came back — nothing to learn from.")
        return

    print(f"[injury-tuner] real player-weeks scanned: {meta['total_player_weeks']}")
    print(f"[injury-tuner] real Questionable/Doubtful weeks with an actual stat line: {meta['flagged_weeks_with_real_stat_line']}")
    print(f"[injury-tuner] usable after requiring a real, non-trivial same-season baseline: {meta['usable_after_baseline_filter']}\n")

    trusted = agg[agg["n"] >= args.min_n].sort_values(["position", "n"], ascending=[True, False])
    dropped = agg[agg["n"] < args.min_n]

    pd.set_option("display.width", 140)
    print(f"=== Real, trusted buckets (n >= {args.min_n}) — these are what actually gets applied live ===")
    print(trusted.to_string(index=False))
    print(f"\n=== Real but not-yet-trusted buckets (n < {args.min_n}) — reported, NOT applied ===")
    print(dropped.sort_values("n", ascending=False).to_string(index=False))

    if not len(trusted):
        print("\n[injury-tuner] nothing cleared the trust bar — nothing to write.")
        return

    if args.write:
        factors = {}
        for _, r in trusted.iterrows():
            key = f"{r['position']}|{r['report_primary_injury']}|{r['report_status']}"
            factors[key] = {
                "n": int(r["n"]),
                "median_pct_change": round(float(r["median_pct_change"]), 4),
                "mean_pct_change": round(float(r["mean_pct_change"]), 4),
            }
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seasons_used": seasons,
            "min_n": args.min_n,
            "method": "median real % change vs each player's own same-season healthy-week baseline, "
                      "aggregated by position + real nflverse injury body part + report status "
                      "(Questionable/Doubtful only — Out means DNP, nothing to measure)",
            "meta": meta,
            "factors": factors,
        }
        with open(FACTORS_PATH, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\n[injury-tuner] wrote {FACTORS_PATH} ({len(factors)} trusted buckets) — "
              f"restart the server for engine/injury_impact.py to pick it up.")
    else:
        print("\n[injury-tuner] dry run — nothing written. Re-run with --write to save these as the live factors.")


if __name__ == "__main__":
    main()
