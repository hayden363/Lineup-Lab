"""
LINEUP OPTIMIZER — the exact best starting lineup, not a greedy guess
=======================================================================
Filling slots one at a time (most restrictive first) is optimal only when the
slots' eligible sets nest inside each other. They don't always: with a
WR/RB flex and a WR/TE flex in the same league, grabbing the best WR for the
first flex can leave the second one short. This module solves it as an
assignment problem (slots x players, maximise total value), so the answer is
the true maximum for any slot layout.

Method: Hungarian algorithm (Kuhn-Munkres, O(slots^2 * players)). Pure
Python on purpose — lineups are ~10 slots x ~30 players, the trade finder
calls this thousands of times, and a native solver would add a build
dependency for no gain at this size.

  * Slots fill whenever an eligible player exists (cardinality first, then
    value), matching what every caller did before: a slot is only left empty
    when nobody on the roster can play it.
  * Eligibility is passed in, so this stays free of league/ESPN slot naming
    (engine/lineup.py owns that) and importing it can't be circular.
"""

# Added to every eligible pairing so filling a slot always beats leaving it
# empty, whatever the values are. Far larger than any fantasy score.
FILL_BONUS = 1_000_000.0
_INF = float("inf")


def _assign(weights):
    """Max-weight assignment for a rows<=cols matrix. Returns col index per row.
    Standard potentials-based Hungarian, minimising cost = -weight."""
    n, m = len(weights), len(weights[0])
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv, used = [_INF] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], _INF, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = -weights[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def best_assignment(slots, players, eligible, key="value"):
    """Best legal starting lineup.

    slots     list of slot names, in lineup order
    players   list of dicts with 'player_id', 'position' and `key`
    eligible  eligible(slot, position) -> bool
    Returns (total, chosen) where chosen[i] is the player dict for slots[i],
    or None when no one can play it. `total` sums the chosen players' `key`.
    """
    if not slots or not players:
        return 0.0, [None] * len(slots)
    cols = max(len(players), len(slots))  # pad so every slot has a column
    weights = [[0.0] * cols for _ in slots]
    for i, slot in enumerate(slots):
        for j, p in enumerate(players):
            if eligible(slot, p["position"]):
                weights[i][j] = FILL_BONUS + (p.get(key) or 0.0)
    picks = _assign(weights)
    chosen, total = [], 0.0
    for i, j in enumerate(picks):
        if j < len(players) and weights[i][j] > 0:
            chosen.append(players[j])
            total += players[j].get(key) or 0.0
        else:
            chosen.append(None)
    return total, chosen
