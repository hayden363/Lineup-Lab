"""
MATCHUP TAGS
============
matchup_tag() labels the matchup multiplier PROJ actually uses: the
multi-stat composite from engine/defense.py (composite_multiplier, via
board.matchup_multiplier), not fantasy points allowed.

  > 1.10  -> "soft"
  < 0.90  -> "tough"
  else    -> "average"
"""


def matchup_tag(factor):
    if factor > 1.10:
        return "soft"
    if factor < 0.90:
        return "tough"
    return "average"
