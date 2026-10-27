"""
LINEUP SLOTS — which positions can fill which starting slot
=============================================================
Pure rules, no network. Sleeper names slots FLEX / WRRB_FLEX / REC_FLEX / SUPER_FLEX;
ESPN spells the same slots "RB/WR/TE", "RB/WR", "WR/TE", "OP" and "D/ST". Everything that
builds or optimises a lineup (trades, waivers, the Start/Sit lineup advisor) asks
`eligible(slot, position)` instead of keeping its own table.
"""

ELIGIBLE = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"}, "K": {"K"}, "DEF": {"DEF"},
    # ESPN's lineup-slot labels (espn_api POSITION_MAP), which an ESPN team's
    # slots arrive as (engine/espn.roster_lineup). Without these every ESPN
    # flex starter read as "can't play RB/WR/TE", the D/ST slot as "can't
    # play D/ST" (its player is position DEF here), and best_lineup left
    # those slots empty.
    "RB/WR/TE": {"RB", "WR", "TE"}, "RB/WR": {"RB", "WR"}, "WR/TE": {"WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"}, "D/ST": {"DEF"},
}


def eligible(slot, position):
    return position in ELIGIBLE.get(slot, {slot})
