"""
CORRELATED OUTCOMES — a quarterback's big game is his receivers' big game
=========================================================================
engine/decision.outcomes draws every player's score on its own. That is right
for one player and wrong for a lineup: when a quarterback throws for 400 yards
his receivers score, so a QB + WR1 stack has a wider range than two unrelated
players, and "A outscores B" is a different question when A and B share an
offence.

Measured, not assumed. From every team-week in 2023-2025 plus this season we
took each offence's QB, top two RBs (by carries), top three WRs and top TE
(by targets) and computed the rank correlation of their fantasy points:

    QB with WR1/WR2/WR3   0.42 / 0.31 / 0.23     QB with TE   0.28
    QB with RB            0.09                   WR with WR   0.13
    RB with RB           -0.07 (they split one pile of carries)
    WR/TE with RB         about 0
    opposing QBs          0.13 (shootouts lift both)

`table()` recomputes these from the data on hand (pooled by position pair),
so the numbers track the league instead of being typed in.

How the correlation is applied: Iman-Conover. Each player keeps the exact
distribution of draws `decision.outcomes` already gave him (percentiles,
P(20+), the Start/Sit ranges are unchanged); only which draw lands in which
trial is rearranged so the trials carry the target rank correlation. A
Questionable player's missed games stay independent of everyone else's
scores: availability is not correlated here (it would need a team-level
model of who is ruled out together), only how the playing games turn out.

The position-pair values are pooled, so a WR3 is stacked as tightly as a WR1.
The measured depth gradient (0.42 down to 0.23) says that overstates the
WR3 and understates the WR1; there is no reliable depth label on a lineup
player to do better.
"""

import itertools
import threading

import numpy as np
import pandas as pd

from . import history

POS = ("QB", "RB", "WR", "TE")
SLOTS = (("RB", "carries", 2), ("WR", "targets", 3), ("TE", "targets", 1))
MIN_PAIRS = 300           # team-weeks a pair needs before its correlation is used
_LOCK = threading.Lock()
_CACHE = {}


def _team_weeks(wk):
    """One row per team-week: points of the QB, RB1-2, WR1-3, TE1 plus the
    opponent, from history and this season's weekly stats."""
    cols = ["season", "week", "recent_team", "opponent_team", "player_id", "position",
            "targets", "carries", "attempts", "fantasy_points_ppr"]
    parts = []
    skill = history._frames()["skill"]
    if not skill.empty:
        parts.append(skill[[c for c in cols if c in skill.columns]])
    parts.append(wk[[c for c in cols if c in wk.columns]])
    df = pd.concat(parts, ignore_index=True)
    df = df[df["position"].isin(POS)]
    df[["targets", "carries", "attempts"]] = df[["targets", "carries", "attempts"]].fillna(0.0)
    rows = []
    for (season, week, team), g in df.groupby(["season", "week", "recent_team"]):
        row = {"season": season, "week": week, "team": team, "opp": g["opponent_team"].iloc[0]}
        qb = g[g["position"] == "QB"].nlargest(1, "attempts")
        if len(qb) and qb.iloc[0]["attempts"] >= 15:
            row["QB"] = float(qb.iloc[0]["fantasy_points_ppr"])
        for pos, key, n in SLOTS:
            top = g[g["position"] == pos].nlargest(n, key)
            for i, v in enumerate(top["fantasy_points_ppr"], 1):
                row[f"{pos}{i}"] = float(v)
        rows.append(row)
    return pd.DataFrame(rows)


def _pooled(values_by_pair):
    return {k: float(np.nanmean(v)) for k, v in values_by_pair.items() if len(v)}


def measure(wk):
    """{"same": {(posA, posB): rho}, "opp": {(posA, posB): rho}, "n": team-weeks}.
    Rank (Spearman) correlation of fantasy points, pooled over the slot pairs
    that make up each position pair. Pairs with fewer than MIN_PAIRS
    observations are left out (treated as 0)."""
    w = _team_weeks(wk)
    if w.empty:
        return {"same": {}, "opp": {}, "n": 0}
    slots = [c for c in w.columns if c[:2] in POS or c == "QB"]
    pos_of = lambda c: c.rstrip("123")  # noqa: E731
    ranks = w[slots].rank(pct=True)
    same = {}
    for a, b in itertools.combinations(slots, 2):
        pair = ranks[[a, b]].dropna()
        if len(pair) >= MIN_PAIRS:
            same.setdefault(tuple(sorted((pos_of(a), pos_of(b)))), []).append(float(pair.corr().iloc[0, 1]))
    m = w.merge(w, left_on=["season", "week", "opp"], right_on=["season", "week", "team"], suffixes=("", "_o"))
    opp = {}
    for a in slots:
        for b in slots:
            pair = pd.concat([m[a].rank(pct=True), m[b + "_o"].rank(pct=True)], axis=1).dropna()
            if len(pair) >= MIN_PAIRS:
                opp.setdefault(tuple(sorted((pos_of(a), pos_of(b)))), []).append(float(pair.corr().iloc[0, 1]))
    # a same-position same-slot pair (e.g. QB with QB) appears once per ordering; the mean is the same
    return {"same": _pooled(same), "opp": _pooled(opp), "n": int(len(w))}


def table(wk):
    """The measured table, cached on the size of the weekly frame."""
    key = (len(wk), len(history._frames()["skill"]))
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    t = measure(wk)
    with _LOCK:
        _CACHE.clear()
        _CACHE[key] = t
    return t


def matrix(players, tab):
    """Target correlation matrix for `players` (dicts with team, position and
    optionally opponent). Same-team pairs use tab["same"], opposing pairs
    tab["opp"], everyone else 0. Pushed to the nearest valid correlation
    matrix if the pooled pairs aren't jointly consistent."""
    k = len(players)
    c = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            a, b = players[i], players[j]
            key = tuple(sorted((a.get("position"), b.get("position"))))
            if a.get("team") and a.get("team") == b.get("team"):
                r = tab["same"].get(key, 0.0)
            elif (a.get("opponent") and a.get("opponent") == b.get("team")) or \
                    (b.get("opponent") and b.get("opponent") == a.get("team")):
                r = tab["opp"].get(key, 0.0)
            else:
                r = 0.0
            c[i, j] = c[j, i] = r
    return nearest_correlation(c)


def nearest_correlation(c, floor=1e-6):
    """Clip negative eigenvalues and rescale to a unit diagonal."""
    vals, vecs = np.linalg.eigh(c)
    if vals.min() >= floor:
        return c
    fixed = (vecs * np.clip(vals, floor, None)) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    out = fixed / np.outer(d, d)
    np.fill_diagonal(out, 1.0)
    return out


def correlate(samples, corr, seed=0):
    """Rearrange each player's draws so the trials carry rank correlation
    `corr` (Iman-Conover). `samples` is a list of equal-length arrays; the
    return is a list of arrays with exactly the same values per player.
    Exact zeros (games he missed) are scattered independently of everyone
    else, so injuries don't pick up a spurious link to teammates' scores."""
    k = len(samples)
    n = len(samples[0]) if k else 0
    if k < 2 or n == 0 or not np.any(corr[np.triu_indices(k, 1)]):
        return [np.array(s, copy=True) for s in samples]
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, k))
    z = (z - z.mean(axis=0)) / z.std(axis=0)
    # make the normal scores exactly uncorrelated, then give them the target structure
    z = z @ np.linalg.inv(np.linalg.cholesky(np.corrcoef(z, rowvar=False))).T
    y = z @ np.linalg.cholesky(corr).T
    out = []
    for j, s in enumerate(samples):
        s = np.asarray(s, dtype=float)
        new = np.zeros(n)
        zero = int((s == 0).sum())
        keep = np.sort(rng.permutation(n)[zero:]) if zero else np.arange(n)
        vals = np.sort(s[s != 0])
        order = np.argsort(y[keep, j], kind="stable")
        new[keep[order]] = vals[: len(keep)]
        out.append(new)
    return out


def apply(rows, wk, seed=0):
    """Correlate the `outcomes["_samples"]` of Start/Sit rows in place. Rows
    need position and team (`recent_team`); `opponent` is optional. Does
    nothing unless two or more rows are related (same team or opposing)."""
    live = [r for r in rows if r.get("outcomes") and r["outcomes"].get("_samples") is not None
            and not r["outcomes"].get("out")]
    if len(live) < 2:
        return False
    plain = [{"team": r.get("recent_team"), "position": r.get("position"), "opponent": r.get("opponent")} for r in live]
    c = matrix(plain, table(wk))
    if not np.any(c[np.triu_indices(len(live), 1)]):
        return False
    for r, s in zip(live, correlate([r["outcomes"]["_samples"] for r in live], c, seed)):
        r["outcomes"]["_samples"] = s
    return True


def lineup_range(sample_lists, constants=0.0, seed=0):
    """Range of a lineup's total. `sample_lists` are trial-aligned arrays for
    the starters (already correlated by apply); `constants` is the summed
    projection of starters with no outcome model (K, D/ST). Returns the
    correlated total's p10/p50/p90 and, for comparison, the same total if every
    starter were independent (each column shuffled)."""
    if not sample_lists:
        return None
    arr = np.vstack([np.asarray(s, dtype=float) for s in sample_lists])
    joint = arr.sum(axis=0) + constants
    rng = np.random.default_rng(seed)
    indep = np.vstack([rng.permutation(row) for row in arr]).sum(axis=0) + constants
    q = lambda v: [round(float(x), 1) for x in np.percentile(v, [10, 50, 90])]  # noqa: E731
    p10, p50, p90 = q(joint)
    i10, i50, i90 = q(indep)
    return {"p10": p10, "p50": p50, "p90": p90, "mean": round(float(joint.mean()), 1),
            "independent": {"p10": i10, "p50": i50, "p90": i90},
            "widening": round((p90 - p10) - (i90 - i10), 1)}
