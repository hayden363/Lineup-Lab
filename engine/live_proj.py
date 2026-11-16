"""Live (in-game) projection: points so far + expected rest-of-game (ROG) points.

ROG = pregame projection x f(position, seconds left, score margin from the player's team's side) x (1 + beta x z),
where f is a table learned from 2023-2025 play-by-play (analysis/live_proj_fit.py writes live_proj_params.json) and
z says how far his points so far run ahead of / behind pregame x elapsed share. The table is non-decreasing in time left,
and ROG is never negative, so a live projection never drops below the points already scored.

The fallback ("naive") is pregame x seconds_left / 3600. It is used for positions the table does not cover (K, DEF), a
missing pregame number, or if the params file says the model did not beat naive on held-out data.
Pure: the params JSON is read once, nothing else is touched."""
import json
import math
import os

_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_proj_params.json")
_PARAMS = None
GAME_SECONDS = 3600.0


def _params():
    global _PARAMS
    if _PARAMS is None:
        try:
            with open(_PARAMS_PATH) as fh:
                _PARAMS = json.load(fh)
        except (OSError, ValueError):
            _PARAMS = {}
    return _PARAMS


def _num(x):
    """float(x), or None for None / NaN / non-numbers."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _interp(ts, vals, t):
    """Linear in seconds left between the knots; 0 at t=0, flat beyond the last knot."""
    xs = [0.0] + [float(v) for v in ts]
    ys = [0.0] + [float(v) for v in vals]
    if t >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if t <= xs[i]:
            w = (t - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + w * (ys[i] - ys[i - 1])
    return ys[-1]


def _bin(cuts, d):
    n = 0
    for c in cuts:
        if d > c:
            n += 1
    return n


def live_projection(position, pregame_proj, points_so_far, seconds_left, score_diff, quarter=None, final=False):
    """Return {"live_proj", "rog", "method"}. `score_diff` is his team's points minus the opponent's; `quarter` is accepted
    for the caller's convenience (the clock already carries it). Never raises on None / NaN inputs."""
    so_far = _num(points_so_far)
    so_far = 0.0 if so_far is None else so_far
    t = _num(seconds_left)
    pre = _num(pregame_proj)

    def out(rog, method):
        rog = max(0.0, rog)
        return {"live_proj": so_far + rog, "rog": rog, "method": method}

    if final or t is None or t <= 0:
        return out(0.0, "naive")
    t = min(t, GAME_SECONDS)
    if pre is None or pre <= 0:
        return out(0.0, "naive")                      # nothing to scale: the projection is just what he has
    naive = pre * t / GAME_SECONDS
    p = _params()
    pos = str(position or "").upper()
    if not p.get("ship_model") or pos not in p.get("f", {}):
        return out(naive, "naive")
    ts = p["ts"]
    d = _num(score_diff)
    if d is None or "curve" not in p:
        vals = p["curve"][pos] if "curve" in p else p["f"][pos][_bin(p["diff_cuts"], 0.0)]
    else:
        vals = p["f"][pos][_bin(p["diff_cuts"], d)]
    rog = pre * _interp(ts, vals, t)
    beta = (p.get("usage_beta") or {}).get(pos)
    if beta:
        elapsed = 1.0 - t / GAME_SECONDS
        z = max(-1.0, min(1.0, (so_far - pre * elapsed) / pre))
        rog *= 1.0 + beta * z
    return out(rog, "model")
