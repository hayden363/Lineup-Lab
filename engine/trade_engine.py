"""
TRADE ENGINE — trades both managers would actually accept
=========================================================
A suggestion has to clear three bars, in this order:

1. Market fairness — what the other manager SEES. Every player is ranked
   by points per week over the best player nobody in the league rosters at
   his position (a QB in a 1-QB league, where good QBs sit on waivers, ranks
   lower), averaged with the expert consensus rank (what most managers go
   by), and valued on a trade-chart curve (rank 1 = 100, steep at the top,
   never zero, so bench players still carry some value). Packages are valued the
   way people trade: best player at full value, the second at 60%, a third
   at 40% — two mid players don't buy a star. The other side has to receive
   at least 90% of what it gives by that measure.

2. Both lineups. Each team's strength is its best legal starting lineup
   (rest-of-season points/week, the league's real slots) plus 15% of its
   three best bench players (bye and injury cover). A team that takes in
   more players than it sends drops its lowest-valued players to stay at
   roster size. You must gain at least 0.5 pts/week. The other team can't
   lose more than 0.5 pts/week, and "Likely" means it gains too.

3. Ranking by mutual benefit, not by your edge: deals both sides like rank
   first, at most two per opponent and three per player of yours, so one
   player isn't shopped to the whole league.

Shapes: 1-for-1, 2-for-1, 1-for-2 and 2-for-2 — the three real trades in the
connected 2026 league were 2-for-1, 2-for-2 and 2-for-1.
"""

import itertools

import numpy as np

from . import consensus, lineup as lineup_layer, sleeper, value as value_layer, waivers

MARKET_FLOOR = 0.90          # they must receive >= 90% of the market value they give
MARKET_CEIL = 1.30           # beyond this you're overpaying badly; not suggested
PACKAGE_WEIGHTS = (1.0, 0.6, 0.4)
BENCH_DEPTH_WEIGHT = 0.15
MY_MIN_GAIN = 0.5
THEIR_MAX_LOSS = -0.5
CANDIDATES_PER_SIDE = 10
THROW_IN = 8.0               # trade value under this is filler, not a real piece
POSITIONS = ("QB", "RB", "WR", "TE")


def league_shape(roster_positions, teams):
    slots = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "SUPERFLEX": 0}
    for s in roster_positions or []:
        if s in ("QB", "RB", "WR", "TE"):
            slots[s] += 1
        elif s in ("FLEX", "WRRB_FLEX", "REC_FLEX"):
            slots["FLEX"] += 1
        elif s in ("SUPER_FLEX", "OP"):
            slots["SUPERFLEX"] += 1
    return {"teams": max(2, int(teams)), "slots": slots}


def waiver_levels(pool, rostered_ids, league):
    """{position: ROS pts/week of the best player nobody rosters}. That's the
    real floor of a player's trade value: anyone below it is replaceable for
    free. Falls back to the starter-replacement rank when rosters are unknown."""
    out = {}
    fallback = value_layer.replacement_ranks(league)
    for pos in POSITIONS:
        sub = pool[pool["position"] == pos]
        free = sub[~sub.index.isin(rostered_ids)]["value"] if rostered_ids else None
        if free is not None and len(free):
            out[pos] = float(free.max())
        else:
            s = sub["value"].sort_values(ascending=False)
            out[pos] = float(s.iloc[min(fallback[pos], len(s)) - 1]) if len(s) else 0.0
    return out


CURVE_SCALE = 45.0     # rank 1 = 100, ~24 = 60, ~60 = 27, ~100 = 11, ~150 = 4


def rank_value(rank):
    """Trade-chart value for an overall rank: steep at the top, never zero."""
    return 100.0 * float(np.exp(-(rank - 1) / CURVE_SCALE))


def trade_values(pool, league, rostered_ids=None, ecr=None):
    """{player_id: {over_waiver, our_rank, ecr, rank, trade}}.
    Our rank orders every player by ROS pts/week over the best free player at
    his position; the expert consensus rank is what most managers go by. The
    two ranks are averaged (ours alone when he's not in the consensus list),
    re-ranked, and turned into a 0-100 trade value on a trade-chart curve."""
    levels = waiver_levels(pool, set(rostered_ids or []), league)
    ours = {pid: float(r["value"]) - levels.get(r["position"], 0.0) for pid, r in pool.iterrows()}
    our_rank = {pid: i + 1 for i, pid in enumerate(sorted(ours, key=lambda k: -ours[k]))}
    ecr = ecr if ecr is not None else consensus.overall_lookup()
    blend, ecr_rank = {}, {}
    for pid, r in pool.iterrows():
        info = ecr.get(consensus.match_key(r["player_display_name"], r["position"])) if ecr else None
        e = info.get("ecr") if info else None
        e = int(e) if e is not None and e == e else None
        ecr_rank[pid] = e
        blend[pid] = our_rank[pid] if e is None else 0.5 * our_rank[pid] + 0.5 * e
    final = {pid: i + 1 for i, pid in enumerate(sorted(blend, key=lambda k: blend[k]))}
    return {pid: {"over_waiver": round(ours[pid], 2), "our_rank": our_rank[pid], "ecr": ecr_rank[pid],
                  "rank": final[pid], "trade": round(rank_value(final[pid]), 1)} for pid in pool.index}


def package_value(values):
    """Market value of a package: best at 100%, then 60%, then 40%."""
    vals = sorted(values, reverse=True)
    return sum(w * v for w, v in zip(PACKAGE_WEIGHTS, vals))


def starters(players, slots):
    """player_ids in the best legal starting lineup."""
    order = sorted(slots, key=lambda s: len(lineup_layer.ELIGIBLE.get(s, {s})))
    used = set()
    for slot in order:
        best = None
        for p in players:
            if p["player_id"] not in used and lineup_layer.eligible(slot, p["position"]) and (best is None or p["value"] > best["value"]):
                best = p
        if best:
            used.add(best["player_id"])
    return used


def _names(ps):
    ps = list(ps)
    return ", ".join(p["name"] for p in ps[:-1]) + (" and " if len(ps) > 1 else "") + ps[-1]["name"] if ps else ""


def reasons(s, mine, theirs, slots, their_name):
    """Plain-English why for both sides, from the same numbers the engine used."""
    give_ids = {p["player_id"] for p in s["you_give"]}
    get_ids = {p["player_id"] for p in s["you_get"]}
    you, them = [], []

    def lineup_change(before, sent_ids, recv, drop):
        """(incoming players who'd start, players who stay but lose their spot)."""
        drop_ids = {p["player_id"] for p in drop}
        after = [p for p in before if p["player_id"] not in sent_ids | drop_ids] + list(recv)
        b, a = starters(before, slots), starters(after, slots)
        new_starters = [p for p in recv if p["player_id"] in a]
        benched = [p for p in before if p["player_id"] in b - a and p["player_id"] not in sent_ids | drop_ids]
        return new_starters, benched

    def sentence(ins, benched, who):
        if not ins:
            return None
        verb = "start" if len(ins) > 1 else "starts"
        line = f"{_names(ins)} {verb} for {who}"
        if benched:
            line += f"; {_names(benched)} {'move' if len(benched) > 1 else 'moves'} to the bench"
        return line

    ins, benched = lineup_change(mine, give_ids, s["you_get"], s["my_drop"])
    you.append(f"+{s['my_gain']:.1f} pts/week to your starting lineup")
    line = sentence(ins, benched, "you")
    if line:
        you.append(line)
    t_ins, t_benched = lineup_change(theirs, get_ids, s["you_give"], s["their_drop"])
    if s["their_gain"] >= 0.3:
        them.append(f"+{s['their_gain']:.1f} pts/week to their starting lineup")
    else:
        them.append(f"Their starting lineup stays about the same ({s['their_gain']:+.1f} pts/week)")
    line = sentence(t_ins, t_benched, "them")
    if line:
        them.append(line)
    for pos in ("QB", "RB", "WR", "TE"):
        need = sum(1 for x in slots if x == pos)
        have = sum(1 for p in theirs if p["position"] == pos and p.get("injury_status") not in ("IR", "Out"))
        if need and have < need and any(p["position"] == pos for p in s["you_give"]):
            them.append(f"Fills a hole: they have {have} healthy {pos}{'s' if have != 1 else ''} for {need} {pos} slot{'s' if need != 1 else ''}")
    gv, gt = s["market_give"], s["market_get"]
    if s["market_ratio"] >= 1.0:
        them.append(f"Wins on the trade chart: {gv:.0f} in for {gt:.0f} out")
    else:
        them.append(f"Close on the trade chart: {gv:.0f} in for {gt:.0f} out")
    you.append(f"Trade chart: you give {gv:.0f}, get {gt:.0f} (consensus rankings + our projections)")
    for p in s["you_get"]:
        if p.get("injury_status"):
            you.append(f"Risk: {p['name']} is listed {p['injury_status']}")
    for p in s["you_give"]:
        if p.get("injury_status"):
            them.append(f"Risk for them: {p['name']} is listed {p['injury_status']}")
    if s["my_drop"]:
        you.append(f"You'd drop {_names(s['my_drop'])} to make room")
    if s["their_drop"]:
        them.append(f"They'd drop {_names(s['their_drop'])} to make room")
    return {"you": you, "them": them}


def strength(players, slots):
    """Best starting lineup + 15% of the three best bench players."""
    if not players:
        return 0.0
    order = sorted(slots, key=lambda s: len(lineup_layer.ELIGIBLE.get(s, {s})))
    used, total = set(), 0.0
    for slot in order:
        best = None
        for p in players:
            if p["player_id"] not in used and lineup_layer.eligible(slot, p["position"]) and (best is None or p["value"] > best["value"]):
                best = p
        if best:
            used.add(best["player_id"])
            total += best["value"]
    bench = sorted((p["value"] for p in players if p["player_id"] not in used), reverse=True)[:3]
    return total + BENCH_DEPTH_WEIGHT * sum(bench)


def after_trade(roster, out_ids, incoming, roster_limit):
    """Roster after sending `out_ids` and taking `incoming`, dropping its
    lowest-valued players (never the new ones) to stay at the limit.
    Returns (players, dropped)."""
    kept = [p for p in roster if p["player_id"] not in out_ids]
    new = kept + list(incoming)
    over = len(new) - roster_limit
    dropped = []
    if over > 0:
        incoming_ids = {p["player_id"] for p in incoming}
        # Managers cut whoever they value least on the market, not by this
        # week's projection (nobody drops a hurt star to make room).
        cut = sorted((p for p in kept if p["player_id"] not in incoming_ids),
                     key=lambda p: (p.get("trade", 0), p["value"]))[:over]
        dropped = cut
        cut_ids = {p["player_id"] for p in cut}
        new = [p for p in new if p["player_id"] not in cut_ids]
    return new, dropped


def evaluate(give, get, mine, theirs, slots, my_limit, their_limit, base_me, base_them):
    """Score one proposal; None when it fails a bar."""
    m_give = package_value(p["trade"] for p in give)
    m_get = package_value(p["trade"] for p in get)
    if m_get <= 0 or m_give <= 0:
        return None
    ratio = m_give / m_get          # what THEY receive vs what they give, by market
    if ratio < MARKET_FLOOR or ratio > MARKET_CEIL:
        return None
    me_after, my_drop = after_trade(mine, {p["player_id"] for p in give}, get, my_limit)
    my_gain = strength(me_after, slots) - base_me
    if my_gain < MY_MIN_GAIN:
        return None
    them_after, their_drop = after_trade(theirs, {p["player_id"] for p in get}, give, their_limit)
    their_gain = strength(them_after, slots) - base_them
    if their_gain < THEIR_MAX_LOSS:
        return None
    # Likely: they gain on the field AND don't lose on the trade chart — or
    # they gain a lot (a real hole filled) while staying within 10% on value.
    likely = their_gain >= 0.3 and (ratio >= 1.0 or (their_gain >= 2.0 and ratio >= MARKET_FLOOR))
    acceptance = "Likely" if likely else "Possible"
    # Simpler deals get made more often: each piece past 1-for-1 costs a bit.
    score = (my_gain + 0.8 * min(their_gain, my_gain) + (1.0 if acceptance == "Likely" else 0.0)
             - 0.4 * (len(give) + len(get) - 2))
    return {"my_gain": round(my_gain, 1), "their_gain": round(their_gain, 1), "market_give": round(m_give, 1),
            "market_get": round(m_get, 1), "market_ratio": round(ratio, 2), "acceptance": acceptance,
            "score": score, "my_drop": my_drop, "their_drop": their_drop}


def _combos(players, sizes, must=None):
    must = set(must or [])
    for n in sizes:
        for combo in itertools.combinations(players, n):
            if must and not must.issubset({p["player_id"] for p in combo}):
                continue
            yield combo


def find_trades(rosters, my_roster_id, slots, roster_limit, values, give_ids=None, target_ids=None,
                max_suggestions=6):
    """rosters: {roster_id: {"name", "players": [player dicts with value, trade, position...]}}.
    Returns ranked suggestions (see module docstring)."""
    mine = rosters[my_roster_id]["players"]
    base_me = strength(mine, slots)
    tradeable = lambda ps: sorted([p for p in ps if p["trade"] > 0 and p.get("injury_status") not in ("IR",)],
                                  key=lambda p: -p["trade"])[:CANDIDATES_PER_SIDE]
    if give_ids:
        my_pool = [p for p in mine if p["player_id"] in give_ids] + \
                  [p for p in tradeable(mine) if p["player_id"] not in give_ids][:4]
        my_sizes = (len(give_ids),) if len(give_ids) >= 2 else (1, 2)
    else:
        my_pool, my_sizes = tradeable(mine), (1, 2)
    out = []
    for rid, team in rosters.items():
        if rid == my_roster_id or (target_ids and rid not in target_ids):
            continue
        theirs = team["players"]
        base_them = strength(theirs, slots)
        their_pool = tradeable(theirs)
        for give in _combos(my_pool, my_sizes, must=give_ids):
            for get in _combos(their_pool, (1, 2)):
                if len(give) + len(get) > 4:
                    continue
                # Each team keeps its current number of skill players: whoever
                # takes in more than they send drops their least valuable.
                res = evaluate(give, get, mine, theirs, slots, len(mine), len(theirs), base_me, base_them)
                if res:
                    sug = {**res, "opponent_roster_id": rid, "opponent_team_name": team["name"],
                           "you_give": list(give), "you_get": list(get)}
                    out.append(sug)
    out.sort(key=lambda s: -s["score"])
    picked, per_opp, per_player, cores = [], {}, {}, set()
    for s in out:
        # The same deal with a near-worthless throw-in added is a duplicate.
        core = (s["opponent_roster_id"],
                frozenset(p["player_id"] for p in s["you_give"] if p["trade"] >= THROW_IN),
                frozenset(p["player_id"] for p in s["you_get"] if p["trade"] >= THROW_IN))
        if core in cores:
            continue
        if per_opp.get(s["opponent_roster_id"], 0) >= 2:
            continue
        if any(per_player.get(p["player_id"], 0) >= 3 for p in s["you_give"]):
            continue
        picked.append(s)
        cores.add(core)
        per_opp[s["opponent_roster_id"]] = per_opp.get(s["opponent_roster_id"], 0) + 1
        for p in s["you_give"]:
            per_player[p["player_id"]] = per_player.get(p["player_id"], 0) + 1
        if len(picked) >= max_suggestions:
            break
    for s in picked:
        s["reasons"] = reasons(s, mine, rosters[s["opponent_roster_id"]]["players"], slots, s["opponent_team_name"])
    return picked


def build_rosters(league_id, pool, values, crosswalk=None):
    """{roster_id: {"name", "players"}} from Sleeper, QB/RB/WR/TE we can value."""
    snap = sleeper.league_snapshot(league_id)
    names = {t["roster_id"]: t["team_name"] for t in snap["teams"]}
    cw = crosswalk or sleeper.id_crosswalk()
    out = {}
    for r in sleeper.get_rosters(league_id):
        rid = r.get("roster_id")
        reserve = set(r.get("reserve") or []) | set(r.get("taxi") or [])
        ps = []
        for raw in r.get("players") or []:
            if raw in reserve:
                continue
            g = cw.get(str(raw))
            if not g or g not in pool.index or g not in values:
                continue
            row = pool.loc[g]
            st = row.get("injury_status")
            ps.append({"player_id": g, "name": row["player_display_name"], "player_display_name": row["player_display_name"],
                       "position": row["position"], "recent_team": row["recent_team"], "headshot_url": row.get("headshot_url"),
                       "value": round(float(row["value"]), 1), "trade": values[g]["trade"], "ecr": values[g]["ecr"],
                       "injury_status": st if isinstance(st, str) else None})
        out[rid] = {"name": names.get(rid, f"Team {rid}"), "players": ps}
    return out
