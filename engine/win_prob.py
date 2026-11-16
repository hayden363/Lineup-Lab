"""Matchup win probability for My Team.

P(my final > opponent final) = Phi((mu_me - mu_opp) / sqrt(var_me + var_opp)), where a team's mu is the sum of its
starters' expected finals (points so far + expected rest of game) and its var is the sum of their rest-of-game variances.
Starters' scores are treated as INDEPENDENT (no game-script correlation between teammates, no shared-game effect between
my player and his), so the SD of a margin is a little narrower than reality when both sides own players from one game.

Per-player rest-of-game SD is sd = max(floor, a * rog_exp ** b) by position, fitted on 2023-2025 real data by
analysis/live_var_fit.py (engine/live_var_params.json, held-out 2026 calibration is stored in the same file). K, DEF and
unknown positions use the position-agnostic "ALL" fit. A finished player has no rest of game: variance 0.
Pure: the params JSON is read once, nothing else is touched."""
import json
import math
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_var_params.json")
_P = None


def params():
    global _P
    if _P is None:
        try:
            with open(_PATH) as fh:
                _P = json.load(fh).get("sd") or {}
        except (OSError, ValueError):
            _P = {}
        if "ALL" not in _P:                       # params missing: a documented, conservative fallback (the 2023-2025 pooled fit)
            _P["ALL"] = {"a": 2.476, "b": 0.426, "floor": 1.607}
    return _P


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (v != v or math.isinf(v)) else v


def rog_sd(position, rog_exp):
    """SD of a player's remaining points given his expected remaining points. 0 when nothing is left to play."""
    r = _num(rog_exp)
    if r is None or r <= 0:
        return 0.0
    p = params().get(str(position or "").upper()) or params()["ALL"]
    return max(p["floor"], p["a"] * r ** p["b"])


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def win_probability(mu_me, var_me, mu_opp, var_opp):
    """P(me > opponent) in 0..1, or None when a mean is missing. No variance left: 1 / 0 for a margin, 0.5 on a tie."""
    a, b, va, vb = _num(mu_me), _num(mu_opp), _num(var_me), _num(var_opp)
    if a is None or b is None:
        return None
    v = max(0.0, va or 0.0) + max(0.0, vb or 0.0)
    d = a - b
    if v <= 1e-12:
        return 1.0 if d > 1e-9 else (0.0 if d < -1e-9 else 0.5)
    return phi(d / math.sqrt(v))


def team_mu_var(rows):
    """rows: iterable of (expected_final, position, rog_exp) -> (mu, var). An expected_final of None counts as 0."""
    mu = var = 0.0
    for final, pos, rog in rows:
        mu += _num(final) or 0.0
        var += rog_sd(pos, rog) ** 2
    return mu, var


def pregame_win_prob(mine, opp):
    """From /api/myteam teams (players with is_starter, PROJ, position, final): starters only; a settled starter's PROJ is
    his real score and carries no variance. None without an opponent."""
    if not mine or not opp:
        return None

    def rows(team):
        for p in team.get("players") or []:
            if not p.get("is_starter"):
                continue
            proj = _num(p.get("PROJ")) or 0.0
            yield proj, p.get("position"), 0.0 if p.get("final") else proj

    m1, v1 = team_mu_var(rows(mine))
    m2, v2 = team_mu_var(rows(opp))
    return win_probability(m1, v1, m2, v2)
