"""
EXPERT CONSENSUS RANK (ECR) — what the rest of the fantasy world thinks
=========================================================================
A cross-check on our own valuation, not a replacement for it. FantasyPros
publishes an "expert consensus rank" (an average over many analysts' ranks)
and the DynastyProcess project mirrors it as a public CSV on GitHub,
refreshed about daily. Reading a published CSV is not scraping a site, and
this app only uses it to show "here is where other sites rank this player"
next to our own rank — never as its own projection.

`redraft-overall` is the rest-of-season, all-positions list (the one that puts
Gibbs and Bijan above every quarterback); `weekly-<pos>` is the current
week's positional list.

Works fine offline: any fetch failure returns an empty table and every ECR
column degrades to None, same pattern as external_projections.py.

Matched to nflverse players by normalized name + position (the file has no
gsis_id): see `match_key`. A name that is ambiguous across positions isn't
guessed at.
"""

import re

import pandas as pd

from engine import data

ECR_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_fpecr_latest.csv"
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_KEEP = ["page_type", "player", "pos", "team", "ecr", "sd", "best", "worst", "bye", "scrape_date"]


def normalize_name(name):
    """'Kenneth Walker III' -> 'kenneth walker'; "Ja'Marr Chase" -> 'jamarr chase'."""
    if not isinstance(name, str):
        return ""
    s = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("-", " ").replace(".", ""))
    return " ".join(t for t in s.split() if t not in _SUFFIXES)


def match_key(name, position):
    return f"{normalize_name(name)}|{str(position).upper()}"


def load_ecr(force=False):
    """The raw ECR table (only the columns we use), or an empty frame if the
    source is unreachable."""
    def fetch():
        df = pd.read_csv(ECR_URL)
        print(f"[consensus] fetched ECR: {len(df)} rows, scraped {df['scrape_date'].max()}")
        return df[_KEEP]
    try:
        return data._disk_cached("ecr", "live", fetch, force=force)
    except Exception as e:
        print(f"[consensus] couldn't load ECR (consensus columns will be empty): {e}")
        return pd.DataFrame(columns=_KEEP)


def overall_lookup(ecr=None):
    """{match_key: {ecr, sd, best, worst, bye}} from the rest-of-season overall list."""
    ecr = load_ecr() if ecr is None else ecr
    sub = ecr[ecr["page_type"] == "redraft-overall"]
    out = {}
    for r in sub.itertuples(index=False):
        out[match_key(r.player, r.pos)] = {
            "ecr": float(r.ecr), "ecr_sd": float(r.sd) if pd.notna(r.sd) else None,
            "ecr_best": int(r.best) if pd.notna(r.best) else None,
            "ecr_worst": int(r.worst) if pd.notna(r.worst) else None,
            "bye_week": int(r.bye) if pd.notna(r.bye) else None,
        }
    return out


# How much of a weekly projection comes from the expert consensus rank. Chosen by backtest
# (analysis/weekly_sweep.py, 2021-2025, 280 season-week-position groups, real PPR points): rank
# correlation with real points rises steadily as the consensus share rises and is flat from 0.8 up
# (all positions: 0.0 -> .549, 0.5 -> .581, 0.8 -> .589, 1.0 -> .591). 0.8 keeps a fifth of our own
# number so players the experts do not list, and the matchup/injury/weather layers, still count.
WEEKLY_WEIGHT = 0.80
# Waivers rank a rest-of-season number, not one game, so the one-week consensus gets less say. This
# one is a judgment call between the weekly result and no change; it has no backtest of its own.
WAIVER_WEEKLY_WEIGHT = 0.50
# A weekly page counts only if scraped from 4 days before that week's first game on (the same
# window the backtest used); a leftover page from last week must never be read as this week's.
FRESH_DAYS_BEFORE_KICKOFF = 4


def fresh_after(schedule, week):
    """Earliest scrape date a weekly consensus page may have to count for `week`, or None when the
    schedule has no game dates for it."""
    try:
        s = schedule[(schedule["week"] == week) & (schedule["game_type"] == "REG")] \
            if "game_type" in schedule.columns else schedule[schedule["week"] == week]
        first = pd.to_datetime(s["gameday"]).min()
    except Exception:
        return None
    return None if pd.isna(first) else first - pd.Timedelta(days=FRESH_DAYS_BEFORE_KICKOFF)


def weekly_lookup(position, ecr=None, fresh_after=None):
    """{match_key: weekly positional ECR} for one position (QB/RB/WR/TE). With `fresh_after`, only
    pages scraped on or after that date count (an empty dict when the cached page is older)."""
    ecr = load_ecr() if ecr is None else ecr
    sub = ecr[ecr["page_type"] == f"weekly-{position.lower()}"]
    if fresh_after is not None and len(sub):
        sub = sub[pd.to_datetime(sub["scrape_date"]) >= pd.Timestamp(fresh_after)]
    return {match_key(r.player, r.pos): float(r.ecr) for r in sub.itertuples(index=False)}


def points_for_rank(rank, ref_sorted_desc):
    """The points a player at positional rank `rank` would score on our own scale: the rank-th
    highest of `ref_sorted_desc` (our projections for that position, best first). Experts publish
    ranks, not points, so this puts their order on the same axis as ours."""
    n = len(ref_sorted_desc)
    if rank is None or n == 0:
        return None
    return float(ref_sorted_desc[min(max(int(round(rank)), 1), n) - 1])


def blend_with_rank(ours, rank, ref_sorted_desc, weight):
    """(blended points, consensus points). Falls back to (ours, None) when there is no rank to use."""
    pts = points_for_rank(rank, ref_sorted_desc)
    if ours is None or pts is None:
        return ours, None
    return weight * pts + (1.0 - weight) * float(ours), pts
