"""
DRAFT RUNS — when a position is going off the board fast
==========================================================
A "run" is the stretch of a draft where one position keeps getting taken
(four running backs in eight picks) and the tier you were waiting on empties
before your turn. The draft board nudges that position up while the run is on.

The window (8 picks), threshold (4 of them) and the 1.25 boost are judgment
calls, not fitted to data: no public dataset says how much a run should move
a pick. They are exposed as constants so they are easy to change, and the
board returns which positions are in a run so the UI can show why a score
moved instead of hiding it.
"""

from collections import Counter

RUN_WINDOW = 8
RUN_THRESHOLD = 4
RUN_MULTIPLIER = 1.25


def run_positions(picks, window=RUN_WINDOW, threshold=RUN_THRESHOLD):
    """Positions with at least `threshold` of the last `window` picks.
    `picks` is any sequence of dicts with a 'position', oldest first."""
    recent = [p.get("position") for p in list(picks)[-window:]]
    return sorted(pos for pos, n in Counter(recent).items() if pos and n >= threshold)
