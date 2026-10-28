"""
AGING — how a player's production is expected to move with age
==============================================================
A projection that leans on past seasons is describing a younger player. This
module is the age curve: the expected change in per-game fantasy points over
one year, by position and age (DELTAS). It is applied only to the share of a
projection that came from history (board.shrunk_rate's history_weight): this
season's games already reflect the age he is now.

The numbers are judgment calls shaped by the usual position curves (backs fall
off first, receivers and tight ends hold through their late twenties,
quarterbacks last longest), cross-checked against the 2023-25 year-over-year
changes in history_data: backs lost about 10-20% a year from 27, receivers
30-40% from 30. The raw data overstates the fall (the best players regress to
the mean whatever their age, which the projection's shrinkage already covers),
so these are deliberately milder. Not fitted; the README says that of the other
model weights too.
"""

import numpy as np
import pandas as pd

MAX_DELTA = 0.15      # no age moves a projection more than 15%

# age -> change over the next year; an age between two keys takes the lower key's value, below the first key the
# first, above the last the last.
DELTAS = {
    "QB": {0: 0.08, 23: 0.06, 24: 0.04, 25: 0.02, 26: 0.0, 34: -0.02, 35: -0.04, 36: -0.07, 38: -0.10},
    "RB": {0: 0.07, 22: 0.07, 23: 0.04, 24: 0.02, 25: 0.0, 26: -0.03, 27: -0.06, 28: -0.09, 29: -0.12, 30: -0.15},
    "WR": {0: 0.08, 22: 0.08, 23: 0.06, 24: 0.04, 25: 0.02, 26: 0.0, 29: -0.03, 30: -0.06, 31: -0.09, 32: -0.12},
    "TE": {0: 0.07, 23: 0.07, 24: 0.05, 25: 0.03, 26: 0.0, 29: -0.03, 30: -0.05, 31: -0.08, 33: -0.11},
}


def delta(position, age):
    """Expected one-year change (+0.04 = 4% better) for a player this age. 0 when the age or position is unknown."""
    table = DELTAS.get(position)
    if table is None or age is None or pd.isna(age):
        return 0.0
    out = 0.0
    for floor in sorted(table):
        if age >= floor:
            out = table[floor]
    return float(np.clip(out, -MAX_DELTA, MAX_DELTA))


def multiplier(position, ages, history_weight):
    """Series of rate multipliers: 1 + delta(age) x the share of his rate that came from past seasons. Both inputs
    are Series on the same index; a missing age is neutral."""
    hw = pd.to_numeric(history_weight, errors="coerce").fillna(0.0).clip(0, 1)
    d = ages.reindex(hw.index).map(lambda a: delta(position, a))
    return 1.0 + d * hw


def ages_from(crosswalk, season):
    """{gsis_id: age on September 1 of `season`} from a crosswalk with gsis_id and birthdate columns."""
    cw = crosswalk.dropna(subset=["gsis_id", "birthdate"]).drop_duplicates("gsis_id").copy()
    born = pd.to_datetime(cw["birthdate"], errors="coerce")
    cw["age"] = (pd.Timestamp(int(season), 9, 1) - born).dt.days / 365.25
    return cw.dropna(subset=["age"]).set_index("gsis_id")["age"]


_AGES = {}


def ages(season):
    """Cached ages for the season; empty when the crosswalk cannot be loaded (nothing is adjusted then)."""
    if season not in _AGES:
        try:
            import os
            from . import sleeper
            sleeper.id_crosswalk()      # makes sure the cached crosswalk file exists; it holds the birthdates
            path = os.path.join(sleeper.CACHE_DIR, "id_crosswalk.parquet")
            _AGES[season] = ages_from(pd.read_parquet(path, columns=["gsis_id", "birthdate"]), season)
        except Exception as e:
            print(f"[aging] ages unavailable, no age adjustment: {e}")
            return pd.Series(dtype=float)
    return _AGES[season]
