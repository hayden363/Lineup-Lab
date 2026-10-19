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


def weekly_lookup(position, ecr=None):
    """{match_key: weekly positional ECR} for one position (QB/RB/WR/TE)."""
    ecr = load_ecr() if ecr is None else ecr
    sub = ecr[ecr["page_type"] == f"weekly-{position.lower()}"]
    return {match_key(r.player, r.pos): float(r.ecr) for r in sub.itertuples(index=False)}
