"""
WEEKLY LINEUP — slots, kickoff locks and swap validation
==========================================================
Pure rules, no network: given the league's slot layout, the players on the
roster, the NFL schedule and the clock, decide what a lineup looks like and
whether a proposed change is legal.

A slot freezes the moment the player in it kicks off (engine/locks.py), so:
  * a started player can't be benched or moved out of his slot
  * a started player sitting on the bench can't be moved in
  * nobody can be moved into a slot whose occupant has started
  * a player on a bye can still be set (he scores 0) — a warning, not an error

Sleeper's public API is read-only: this validates and projects the lineup you
build here; it can't push it to Sleeper.
"""

from . import locks

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


def build_lineup(slots, starter_ids, players, schedule, week, now=None):
    """One row per slot: who is in it, his projection, bye flag and lock state.
    `players` is {player_id: {name, position, team, PROJ}}. A slot with no
    starter (or an unknown one) comes back empty."""
    rows = []
    for i, slot in enumerate(slots):
        pid = starter_ids[i] if i < len(starter_ids) else None
        p = players.get(pid) if pid else None
        row = {"slot": slot, "index": i, "player_id": pid if p else None}
        if p:
            st = locks.lock_status(schedule, p.get("team"), week, now)
            row.update({"name": p.get("name"), "position": p.get("position"), "team": p.get("team"),
                        "PROJ": p.get("PROJ") or 0.0, **st})
        else:
            row.update({"name": None, "position": None, "team": None, "PROJ": 0.0,
                        "kickoff": None, "locked": False, "bye": False, "inactive": False})
        rows.append(row)
    return rows


def validate(slots, proposed_ids, previous_ids, players, schedule, week, now=None):
    """Check a proposed lineup against the previous one. Returns
    {ok, errors: [str], warnings: [str], lineup: [...], total_proj}.
    Players not in `players` (not on the roster) are rejected."""
    errors, warnings = [], []
    proposed = list(proposed_ids) + [None] * (len(slots) - len(proposed_ids))
    previous = list(previous_ids) + [None] * (len(slots) - len(previous_ids))
    if len(proposed_ids) > len(slots):
        errors.append(f"Lineup has {len(proposed_ids)} players for {len(slots)} slots.")
        proposed = proposed[:len(slots)]

    def locked(pid):
        p = players.get(pid)
        return bool(p) and locks.is_locked(schedule, p.get("team"), week, now)

    seen = set()
    for i, pid in enumerate(proposed):
        if not pid:
            continue
        if pid in seen:
            errors.append(f"{_name(players, pid)} is in the lineup twice.")
        seen.add(pid)
        if pid not in players:
            errors.append(f"Player {pid} is not on your roster.")
            continue
        p = players[pid]
        if not eligible(slots[i], p.get("position")):
            errors.append(f"{p['name']} ({p.get('position')}) can't play {slots[i]}.")
        if locks.kickoff(schedule, p.get("team"), week) is None:
            if locks.plays_in_league(schedule, p.get("team")):
                warnings.append(f"{p['name']} is on a bye in week {week}.")
            else:
                warnings.append(f"{p['name']} has no NFL team and won't score.")

    for i, slot in enumerate(slots):
        old, new = previous[i], proposed[i]
        if old == new:
            continue
        if old and locked(old):
            errors.append(f"{slot} is locked: {_name(players, old)} already played.")
        elif new and locked(new):
            errors.append(f"{_name(players, new)} already played, so he can't be moved into {slot}.")

    lineup = build_lineup(slots, proposed, players, schedule, week, now)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "lineup": lineup,
            "total_proj": round(sum(r["PROJ"] for r in lineup), 1)}


def _name(players, pid):
    return (players.get(pid) or {}).get("name") or str(pid)


def best_lineup(slots, previous_ids, players, schedule, week, now=None):
    """Greedy best legal lineup: locked slots keep their occupant, then each
    remaining slot (most restrictive first) takes the highest-PROJ eligible
    player not already used and not already started. Players on a bye project
    to 0. Returns the same shape as validate()."""
    prev = list(previous_ids) + [None] * (len(slots) - len(previous_ids))
    chosen = [None] * len(slots)
    used = set()
    for i, pid in enumerate(prev):
        if pid in players and locks.is_locked(schedule, players[pid].get("team"), week, now):
            chosen[i] = pid
            used.add(pid)

    def value(pid):
        p = players[pid]
        return 0.0 if locks.kickoff(schedule, p.get("team"), week) is None else (p.get("PROJ") or 0.0)

    order = sorted((i for i in range(len(slots)) if chosen[i] is None),
                   key=lambda i: len(ELIGIBLE.get(slots[i], {slots[i]})))
    for i in order:
        pool = [pid for pid, p in players.items()
                if pid not in used and eligible(slots[i], p.get("position"))
                and not locks.is_locked(schedule, p.get("team"), week, now)]
        if pool:
            best = max(pool, key=value)
            chosen[i] = best
            used.add(best)
    return validate(slots, chosen, prev, players, schedule, week, now)
