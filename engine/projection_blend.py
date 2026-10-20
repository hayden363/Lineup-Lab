"""
PROJECTION BLEND — our number and the experts' number, weighted by the clock
==============================================================================
    blended = a * ours + (1 - a) * expert

`a` is how much weight our model keeps. Early in the week our usage-based
number has had the most time to be right and the experts' number is the
stalest, so `a` is high; as kickoff nears, injury news, inactives and
weather are in the experts' number but not (yet) in ours, so `a` drops:

    more than 96 h out   0.70
    24 - 96 h            0.50
    4 - 24 h             0.35
    under 4 h            0.25

The steps and the weights are judgment calls, not fitted to data (nobody
publishes expert-vs-model accuracy by hours-to-kickoff). They are constants
so they are easy to change, and every response carries the weight it used so
the UI can show it rather than present the blend as settled fact.

Never fabricates: with no expert number, or no kickoff time (bye week, feed
not posted yet), `blended` is None and `reason` says why. The caller keeps
showing our own number.
"""

from datetime import datetime, timezone
from typing import Any, Dict

# (lower bound in hours, lower bound inclusive?, weight on our model).
# >96 is strict so exactly four days out already counts as the 24-96 band.
ALPHA_TIERS = ((96.0, False, 0.70), (24.0, True, 0.50), (4.0, True, 0.35), (0.0, True, 0.25))


def alpha(hours_to_kickoff):
    """Weight on our model at this many hours before kickoff (negative hours,
    i.e. the game already started, use the closest tier)."""
    for bound, inclusive, weight in ALPHA_TIERS:
        if hours_to_kickoff > bound or (inclusive and hours_to_kickoff == bound):
            return weight
    return ALPHA_TIERS[-1][2]


def blend(ours, expert, hours_to_kickoff):
    """{blended, alpha, disagreement, reason}. `disagreement` is
    ours - expert, so the sign says who is higher."""
    out: Dict[str, Any] = {"blended": None, "alpha": None, "disagreement": None, "reason": None}
    if ours is None or expert is None:
        out["reason"] = "no expert number to blend with"
        return out
    if hours_to_kickoff is None:
        out["reason"] = "no kickoff time yet (bye week or schedule not posted)"
        return out
    a = alpha(hours_to_kickoff)
    out.update({"blended": round(a * ours + (1 - a) * expert, 1), "alpha": a,
                "disagreement": round(ours - expert, 1)})
    return out


def hours_until(kickoff, now=None):
    """Hours from `now` (default: the real clock) to a timezone-aware
    kickoff, or None when the kickoff is unknown."""
    if kickoff is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (kickoff - now).total_seconds() / 3600.0
