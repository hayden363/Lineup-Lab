"""
LINEUP ADVISOR — the best whole lineup under a risk lens
=========================================================
Start/Sit compares two or three players at a time. This looks at the whole
lineup at once: every starter slot, flex and superflex included, filled with
the exact optimizer (engine/optimizer.py) so a swap that frees a flex slot for
someone else is found, which a same-position comparison cannot see.

Each player is valued by the same win-condition lens Start/Sit uses
(engine/decision.mode_value): the average for "balanced", mostly the 10th
percentile for "safe", mostly the 90th for "upside". A player who is ruled out
or on a bye is worth 0. Slots whose game has already kicked off keep their
occupant.

Honest limit: maximising the sum of these values is not the same as
maximising the chance of winning your matchup. It ranks lineups by the lens
you picked, nothing more.
"""

from . import decision, locks, optimizer
from .lineup import eligible


def player_value(p, mode, week_has_game=True):
    """What one player is worth in `mode`. `p` may carry `outcomes` (from
    Start/Sit); DEF/K and anyone without them fall back to PROJ."""
    if not week_has_game:
        return 0.0
    o = p.get("outcomes")
    if o:
        if o.get("out"):
            return 0.0
        return float(decision.mode_value(o, mode))
    return float(p.get("PROJ") or 0.0)


def _mean(p, week_has_game=True):
    if not week_has_game:
        return 0.0
    o = p.get("outcomes")
    if o:
        return 0.0 if o.get("out") else float(o.get("mean") or 0.0)
    return float(p.get("PROJ") or 0.0)


def advise(slots, starter_ids, players, schedule, week, mode="balanced", now=None):
    """Best legal lineup for `mode` and what it changes about the current one.
    `players` is {player_id: {name, position, team, PROJ, outcomes?}}."""
    prev = list(starter_ids) + [None] * (len(slots) - len(starter_ids))

    def has_game(pid):
        return locks.kickoff(schedule, players[pid].get("team"), week) is not None

    def locked(pid):
        return locks.is_locked(schedule, players[pid].get("team"), week, now)

    chosen = [None] * len(slots)
    used = set()
    for i, pid in enumerate(prev):
        if pid in players and locked(pid):
            chosen[i] = pid
            used.add(pid)

    open_idx = [i for i in range(len(slots)) if chosen[i] is None]
    pool = [{"player_id": pid, "position": p.get("position"), "value": player_value(p, mode, has_game(pid))}
            for pid, p in players.items() if pid not in used and not locked(pid)]
    _, picks = optimizer.best_assignment([slots[i] for i in open_idx], pool, eligible)
    for i, pick in zip(open_idx, picks):
        if pick:
            chosen[i] = pick["player_id"]

    def total(ids, fn):
        return sum(fn(players[pid], has_game(pid)) for pid in ids if pid in players)

    cur_ids = [pid for pid in prev if pid in players]
    new_ids = [pid for pid in chosen if pid]
    val = lambda p, g: player_value(p, mode, g)  # noqa: E731
    # Who comes into the lineup and who leaves it. Two starters trading slots
    # (RB1 <-> RB2) is not a change, so this compares people, not slots.
    adds = [pid for pid in new_ids if pid not in cur_ids]
    drops = [pid for pid in cur_ids if pid not in new_ids]
    slot_of = {pid: slots[i] for i, pid in enumerate(chosen) if pid}
    changes, left = [], list(drops)
    for new in adds:
        # pair each arrival with the leaver at the same position, else the next one
        old = next((d for d in left if players[d].get("position") == players[new].get("position")), None)
        if old is None and left:
            old = left[0]
        if old is not None:
            left.remove(old)
        o, n = players.get(old), players[new]
        changes.append({
            "slot": slot_of[new], "out": old, "out_name": o.get("name") if o else None,
            "in": new, "in_name": n.get("name"),
            "delta_mode": round(val(n, has_game(new)) - (val(o, has_game(old)) if o else 0.0), 1),
            "delta_mean": round(_mean(n, has_game(new)) - (_mean(o, has_game(old)) if o else 0.0), 1),
        })
    return {
        "mode": mode, "chosen": chosen,
        "current_mode_value": round(total(cur_ids, val), 1), "best_mode_value": round(total(new_ids, val), 1),
        "current_mean": round(total(cur_ids, _mean), 1), "best_mean": round(total(new_ids, _mean), 1),
        "changes": changes, "adds": adds, "drops": drops,
        "locked_slots": [slots[i] for i in range(len(slots)) if chosen[i] and prev[i] == chosen[i] and locked(chosen[i])],
    }
