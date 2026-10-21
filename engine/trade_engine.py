"""
TRADE ENGINE — realistic trades, judged the way managers judge them
====================================================================
Every proposal (from the finder or typed into the analyzer) runs the same
pipeline. All numbers are real: rest-of-season projections (points per game)
and a market value built from the expert consensus rank plus our own rank.

Market value (0-100 trade chart)
    Players are ranked by points/game over the best player nobody in the
    league rosters at their position, that rank is averaged with the expert
    consensus rank, and the result is put on a trade-chart curve:
    value = 100 * exp(-(rank - 1) / 45). Tiers: 1 = 80-100, 2 = 55-79,
    3 = 30-54, 4 = under 30.

1. Starting Lineup Delta
    dSL = best legal starting lineup after - before (points/game, the league's
    real slots). A received player who wouldn't start adds 0. Bench depth is
    never counted as starting value.

2. Effective Package Value (no "20 + 20 = 40")
    V_eff = V1 + w2*V2 + w3*V3 - extra_players * V_cut
    w = 0.80 (2 players) / 0.70, 0.50 (3 players); deep leagues (12+ teams,
    10+ starters) decay half as fast (0.90 / 0.80, 0.60); shallow leagues
    (8-9 starters) take another 15% off every secondary piece. V_cut is the
    market value of the worst bench player the receiving team must drop for
    each extra body it takes in.

3. Fairness Index = V_eff(you give) / V_eff(you get) * 100
    95-105 fair, 85-94 slight underpay (only with a big need on their side),
    106-115 slight overpay (only when you land a tier-1 player), otherwise
    rejected.

Gates (fail fast, in order)
    G1 tier break: a tier-1 player can't go out for a package unless it holds
       a tier-2+ player; never for only tier-3/4 pieces.
    G2 lineups: they must gain >= +1.5 starting points/game; you must gain
       >= +0.5 (no trade is "viable" if your own lineup doesn't improve).
    G3 roster fit: no 3-for-1 in 8- or 10-team leagues; every extra body
       needs a bench player to cut, never a starter.
    G4 incentives: a contender (win % >= .700) won't sell a tier-1/2 player
       for depth; only a struggling team (<= .400) trades a tier-1 player
       for two starters. Skipped before anyone has a record.

Acceptance probability is a transparent model estimate, not a measured rate
(there is no public data on accepted vs rejected offers): it starts from the
fairness band and moves with their lineup gain, holes filled, their record
and injuries on what they receive. The breakdown is returned with it.
"""

import itertools

import numpy as np

from . import consensus, lineup as lineup_layer, optimizer, sleeper, value as value_layer

POSITIONS = ("QB", "RB", "WR", "TE")
CURVE_SCALE = 45.0
TIERS = ((80, 1), (55, 2), (30, 3), (0, 4))
OPP_MIN_DSL = 1.5
MY_MIN_DSL = 0.5
CANDIDATES_PER_SIDE = 9
THROW_IN = 8.0


# --------------------------------------------------------------- values ----
def rank_value(rank):
    return 100.0 * float(np.exp(-(rank - 1) / CURVE_SCALE))


def tier(v):
    return next(t for floor, t in TIERS if v >= floor)


def league_shape(roster_positions, teams):
    slots = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "SUPERFLEX": 0}
    for s in roster_positions or []:
        if s in ("QB", "RB", "WR", "TE"):
            slots[s] += 1
        elif s in ("FLEX", "WRRB_FLEX", "REC_FLEX", "RB/WR/TE", "RB/WR", "WR/TE"):   # last three: ESPN's labels
            slots["FLEX"] += 1
        elif s in ("SUPER_FLEX", "OP"):
            slots["SUPERFLEX"] += 1
    starters = sum(1 for s in roster_positions or [] if s not in ("BN", "IR", "TAXI"))
    return {"teams": max(2, int(teams)), "slots": slots, "starters": starters}


def depth_profile(shape):
    """'shallow' (8-9 starters), 'deep' (12+ teams and 10+ starters) or 'standard'."""
    if shape.get("starters", 9) <= 9:
        return "shallow"
    if shape["teams"] >= 12 and shape.get("starters", 9) >= 10:
        return "deep"
    return "standard"


def waiver_levels(pool, rostered_ids, league):
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


def trade_values(pool, league, rostered_ids=None, ecr=None):
    """{player_id: {over_waiver, our_rank, ecr, rank, trade, tier}}."""
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
    out = {}
    for pid in pool.index:
        v = round(rank_value(final[pid]), 1)
        out[pid] = {"over_waiver": round(ours[pid], 2), "our_rank": our_rank[pid], "ecr": ecr_rank[pid],
                    "rank": final[pid], "trade": v, "tier": tier(v)}
    return out


# ------------------------------------------------------------- lineups ----
def lineup(players, slots):
    """(starting total, set of starter ids) for the best legal lineup."""
    total, chosen = optimizer.best_assignment(slots, players, lineup_layer.eligible)
    return total, {p["player_id"] for p in chosen if p}


def after_trade(roster, out_ids, incoming, slots):
    """(roster after the trade, cut players). Extra bodies are covered by
    cutting the lowest market-value BENCH players; (None, None) if that would
    mean cutting a starter (roster fit fails)."""
    kept = [p for p in roster if p["player_id"] not in out_ids]
    extra = len(incoming) - len(out_ids)
    if extra <= 0:
        return kept + list(incoming), []
    new = kept + list(incoming)
    _, starters = lineup(new, slots)
    incoming_ids = {p["player_id"] for p in incoming}
    bench = sorted((p for p in kept if p["player_id"] not in starters and p["player_id"] not in incoming_ids),
                   key=lambda p: (p["trade"], p["value"]))
    if len(bench) < extra:
        return None, None
    cut = bench[:extra]
    cut_ids = {p["player_id"] for p in cut}
    return [p for p in new if p["player_id"] not in cut_ids], cut


# ------------------------------------------------------------- packages ----
def package_weights(n, profile):
    if n <= 1:
        return [1.0]
    if profile == "deep":
        w = [1.0, 0.9] if n == 2 else [1.0, 0.8, 0.6]
    else:
        w = [1.0, 0.8] if n == 2 else [1.0, 0.7, 0.5]
    if profile == "shallow":
        w = [w[0]] + [x * 0.85 for x in w[1:]]
    return w


def effective_value(players, profile, extra_bodies=0, v_cut=0.0):
    vals = sorted((p["trade"] for p in players), reverse=True)
    w = package_weights(len(vals), profile)
    return sum(a * b for a, b in zip(w, vals)) - extra_bodies * v_cut


# ---------------------------------------------------------------- teams ----
def record(r):
    st = (r or {}).get("settings") or {}
    w, l, t = int(st.get("wins") or 0), int(st.get("losses") or 0), int(st.get("ties") or 0)
    g = w + l + t
    return {"wins": w, "losses": l, "ties": t, "pct": round((w + 0.5 * t) / g, 3) if g else None,
            "text": f"{w}-{l}" + (f"-{t}" if t else "")}


def record_espn(team):
    """Same shape as record(), from an espn_api Team."""
    w, l, t = int(getattr(team, "wins", 0) or 0), int(getattr(team, "losses", 0) or 0), int(getattr(team, "ties", 0) or 0)
    g = w + l + t
    return {"wins": w, "losses": l, "ties": t, "pct": round((w + 0.5 * t) / g, 3) if g else None,
            "text": f"{w}-{l}" + (f"-{t}" if t else "")}


def _player_entry(g, pool, values, usage, byes):
    row = pool.loc[g]
    st = row.get("injury_status")
    return {"player_id": g, "name": row["player_display_name"], "player_display_name": row["player_display_name"],
            "position": row["position"], "recent_team": row["recent_team"], "headshot_url": row.get("headshot_url"),
            "value": round(float(row["value"]), 1), "trade": values[g]["trade"], "tier": values[g]["tier"],
            "ecr": values[g]["ecr"], "injury_status": st if isinstance(st, str) else None,
            "usage": (usage or {}).get(g), "bye": (byes or {}).get(row["recent_team"])}


def build_rosters_espn(league, pool, values, crosswalk, usage=None, byes=None):
    """{team_id: {name, players, record}} from an ESPN league, QB/RB/WR/TE we can
    value. Players on IR are left out, as Sleeper's reserve/taxi spots are."""
    out = {}
    for t in league.teams:
        ps = []
        for p in t.roster:
            if p.lineupSlot == "IR":
                continue
            g = crosswalk.get(str(p.playerId))
            if not g or g not in pool.index or g not in values:
                continue
            ps.append(_player_entry(g, pool, values, usage, byes))
        out[t.team_id] = {"name": (t.team_name or f"Team {t.team_id}").strip(), "players": ps, "record": record_espn(t)}
    return out


def archetype(rec):
    if not rec or rec["pct"] is None:
        return "Unknown"
    return "Contender" if rec["pct"] >= 0.7 else "Desperate" if rec["pct"] <= 0.4 else "Middle"


def slot_profile(players, slots, league_rosters):
    """(weaknesses, strengths) like 'WR2' / 'RB' vs the league median at each
    starting rank: under 85% of median is a weakness, over 115% a strength."""
    weak, strong = [], []
    for pos in POSITIONS:
        k = slots.count(pos)
        mine = sorted((p["value"] for p in players if p["position"] == pos), reverse=True)
        for i in range(k):
            others = []
            for r in league_rosters:
                vals = sorted((p["value"] for p in r if p["position"] == pos), reverse=True)
                others.append(vals[i] if len(vals) > i else 0.0)
            med = float(np.median(others)) if others else 0.0
            v = mine[i] if len(mine) > i else 0.0
            if med and v < 0.85 * med:
                weak.append(f"{pos}{i + 1}" if k > 1 else pos)
            elif med and v > 1.15 * med and pos not in strong:
                strong.append(pos)
    return weak, strong


# --------------------------------------------------------------- assess ----
def _names(ps):
    ps = list(ps)
    if not ps:
        return ""
    return ps[0]["name"] if len(ps) == 1 else ", ".join(p["name"] for p in ps[:-1]) + " and " + ps[-1]["name"]


INSULT_RETURN = 0.85   # must send back at least this share of the best player's value to ask for him


def grade_trade(fi, my_dsl, opp_dsl, fails):
    """Letter grade A+ to F from the trade balance ratio (what you receive over
    what you send, so 100/fairness index), both lineup deltas and the gates.
      F  a tier-break or contender/stud gate failed, or they would get worse
      D  lopsided on paper (TBR under 0.80 or over 1.30) or a side can't fill a slot
      A+ both gain 2+ PPG with TBR .95-1.08; A / A- you gain 1.5+, they gain 1.0+, TBR .90-1.15
      B+ / B  fair on paper, one side modest (+0.5 to +1.0) and the other 1.0+
      C  fair on paper but neither side really improves
    Anything that fits none of these is a C: it isn't broken, it isn't good."""
    tbr = (100.0 / fi) if fi and fi > 0 else 0.0
    if "tier" in fails or "contender" in fails or "stud_for_two" in fails or "insult" in fails or opp_dsl < 0:
        return "F"
    if tbr < 0.80 or tbr > 1.30 or "roster" in fails or "bye" in fails:
        return "D"
    if my_dsl >= 2.0 and opp_dsl >= 2.0 and 0.95 <= tbr <= 1.08:
        return "A+"
    if my_dsl >= 1.5 and opp_dsl >= 1.0 and 0.90 <= tbr <= 1.15:
        return "A" if opp_dsl >= 1.5 else "A-"
    if 0.85 <= tbr <= 1.20:
        gains = sorted((my_dsl, opp_dsl))
        if gains[1] >= 1.0 and gains[0] >= 0.5:
            return "B+" if gains[0] >= 0.8 else "B"
        if my_dsl < 0.5 and opp_dsl < 0.5 and 0.90 <= tbr <= 1.10:
            return "C"
    return "C"


def bye_crash(roster_before, roster_after, slots, week=None):
    """The first bye week where the trade leaves this team with fewer filled
    starting slots than before it, or None. Only byes from `week` on count."""
    byes = {p.get("bye") for p in roster_after if p.get("bye") and (week is None or p["bye"] >= week)}
    for w in sorted(byes):
        def filled(players):
            return len(lineup([p for p in players if p.get("bye") != w], slots)[1])
        if filled(roster_after) < filled(roster_before):
            return w
    return None


def fairness_band(fi):
    if fi < 85:
        return "underpay"
    if fi < 95:
        return "slight_underpay"
    if fi <= 105:
        return "fair"
    if fi <= 115:
        return "slight_overpay"
    return "overpay"


def assess(give, get, me, opp, ctx, full=True):
    """Judge one proposal. `me`/`opp`: {"players", "record", "name", "weak",
    "strong"}; ctx: {"slots", "profile", "teams"}. With full=False (the
    finder's fast path) returns None as soon as a gate fails, otherwise the
    numbers only; with full=True, the complete analysis whatever the verdict."""
    slots, profile = ctx["slots"], ctx["profile"]
    give_ids, get_ids = {p["player_id"] for p in give}, {p["player_id"] for p in get}
    gate = {"tier_break_passed": True, "lineup_delta_passed": True, "roster_fit_passed": True,
            "incentive_passed": True, "fairness_passed": True, "insult_passed": True, "bye_passed": True}
    fails = []

    # G1 tier break (both directions)
    def tier_ok(sent, received):
        best_sent = min(tier(p["trade"]) for p in sent)
        if best_sent == 1 and len(received) >= 2 and not any(tier(p["trade"]) <= 2 for p in received):
            return False
        if best_sent == 1 and all(tier(p["trade"]) >= 3 for p in received):
            return False
        return True
    if not (tier_ok(give, get) and tier_ok(get, give)):
        gate["tier_break_passed"] = False
        fails.append("tier")
        if not full:
            return None

    # G3 roster fit
    if (len(give) >= 3 or len(get) >= 3) and ctx["teams"] <= 10:
        gate["roster_fit_passed"] = False
        fails.append("3for1")
        if not full:
            return None
    me_after, my_cut = after_trade(me["players"], give_ids, get, slots)
    opp_after, opp_cut = after_trade(opp["players"], get_ids, give, slots)
    if me_after is None or opp_after is None:
        gate["roster_fit_passed"] = False
        fails.append("roster")
        if not full:
            return None
        if me_after is None:
            me_after, my_cut = [p for p in me["players"] if p["player_id"] not in give_ids] + list(get), []
        if opp_after is None:
            opp_after, opp_cut = [p for p in opp["players"] if p["player_id"] not in get_ids] + list(give), []

    # 1. Starting lineup deltas
    my_before, my_st0 = lineup(me["players"], slots)
    my_now, my_st1 = lineup(me_after, slots)
    opp_before, opp_st0 = lineup(opp["players"], slots)
    opp_now, opp_st1 = lineup(opp_after, slots)
    my_dsl, opp_dsl = round(my_now - my_before, 1), round(opp_now - opp_before, 1)
    if opp_dsl < OPP_MIN_DSL or my_dsl < MY_MIN_DSL:
        gate["lineup_delta_passed"] = False
        fails.append("lineup")
        if not full and (my_dsl < MY_MIN_DSL or opp_dsl < 0.5):
            return None

    # 2-3. Package values and fairness
    v_cut_opp = opp_cut[0]["trade"] if opp_cut else 0.0
    v_cut_me = my_cut[0]["trade"] if my_cut else 0.0
    v_give = effective_value(give, profile, max(0, len(give) - len(get)), v_cut_opp)
    v_get = effective_value(get, profile, max(0, len(get) - len(give)), v_cut_me)
    fi = round(100 * v_give / v_get, 1) if v_get > 0 else 999.0
    band = fairness_band(fi)
    opp_weak = opp.get("weak") or []
    big_need = opp_dsl >= 3.0 or any(w.startswith(p["position"]) for w in opp_weak for p in give)
    gets_elite = any(tier(p["trade"]) == 1 for p in get)
    if band in ("underpay", "overpay") or (band == "slight_underpay" and not big_need) or \
            (band == "slight_overpay" and not gets_elite):
        gate["fairness_passed"] = False
        fails.append("fairness")
        if not full and not 78 <= fi <= 122:
            return None

    # G4 incentives
    o_arch = archetype(opp.get("record"))
    opp_best_out = min((tier(p["trade"]) for p in get), default=4)
    opp_best_in = min((tier(p["trade"]) for p in give), default=4)
    if o_arch == "Contender" and opp_best_out <= 2 and (len(give) > len(get) or opp_best_in > opp_best_out):
        gate["incentive_passed"] = False
        fails.append("contender")
    if opp_best_out == 1 and len(give) >= 2 and o_arch not in ("Desperate", "Unknown"):
        gate["incentive_passed"] = False
        fails.append("stud_for_two")
    if not gate["incentive_passed"] and not full:
        return None

    # G5 insult filter: asking for their best player needs real value back.
    best_theirs = max(opp["players"], key=lambda p: p["trade"], default=None)
    if best_theirs and best_theirs["player_id"] in get_ids and v_give < INSULT_RETURN * best_theirs["trade"]:
        gate["insult_passed"] = False
        fails.append("insult")
        if not full:
            return None

    # G6 bye-week crash test: they must not be left short on a bye they weren't short on before.
    crash = bye_crash(opp["players"], opp_after, slots, ctx.get("week"))
    if crash is not None:
        gate["bye_passed"] = False
        fails.append("bye")
        if not full:
            return None

    # Acceptance probability (model estimate; see module docstring)
    base = {"fair": 55, "slight_overpay": 70, "slight_underpay": 30, "underpay": 8, "overpay": 80}[band]
    parts = [("fairness: " + band.replace("_", " "), base)]
    parts.append(("their starting lineup change", int(min(20, max(-20, 5 * (opp_dsl - OPP_MIN_DSL))))))
    if big_need:
        parts.append(("fills a hole for them", 10))
    if o_arch == "Desperate" and opp_dsl >= OPP_MIN_DSL:
        parts.append(("they need wins now", 5))
    if o_arch == "Contender" and opp_best_in == 1:
        parts.append(("contender adding a stud", 5))
    for p in give:
        if p.get("injury_status") in ("Questionable", "Doubtful"):
            parts.append((f"{p['name']} is {p['injury_status']}", -5))
        elif p.get("injury_status") in ("Out", "IR"):
            parts.append((f"{p['name']} is {p['injury_status']}", -15))
    prob = int(max(5, min(90, sum(v for _, v in parts))))
    if fails:
        prob = min(prob, 15 if len(fails) > 1 else 30)

    # Status and grade
    near_miss = len(fails) == 1 and (
        (fails[0] == "fairness" and 78 <= fi <= 122) or (fails[0] == "lineup" and opp_dsl >= 0.5 and my_dsl >= MY_MIN_DSL))
    status = "APPROVED" if not fails else "MODIFICATION_REQUIRED" if near_miss else "VETOED"
    grade = grade_trade(fi, my_dsl, opp_dsl, fails)
    if status == "APPROVED" and grade in ("C", "D", "F"):
        grade = "B"   # every gate passed; the matrix alone must not sink an approved deal
    if status == "VETOED" and grade not in ("D", "F"):
        grade = "D"
    if status == "MODIFICATION_REQUIRED" and grade not in ("C", "D", "F"):
        grade = "C"

    out = {"_my_dsl": my_dsl, "_opp_dsl": opp_dsl, "_fi": fi, "_prob": prob, "_status": status,
           "_score": my_dsl + 0.5 * opp_dsl + prob / 20 - 0.4 * (len(give) + len(get) - 2)}
    if not full:
        return out

    raw_gap = round(sum(p["trade"] for p in give) - sum(p["trade"] for p in get), 1)
    adj_gap = round(v_give - v_get, 1)

    def favor(g):
        return f"{g:+.1f} in favor of {'them' if g > 0 else 'you' if g < 0 else 'nobody'}"
    my_new = [p for p in get if p["player_id"] in my_st1]
    my_replaced = [p for p in me["players"] if p["player_id"] in my_st0 - my_st1 and p["player_id"] not in give_ids]
    opp_new = [p for p in give if p["player_id"] in opp_st1]
    opp_replaced = [p for p in opp["players"] if p["player_id"] in opp_st0 - opp_st1 and p["player_id"] not in get_ids]
    out.update({
        "verdict": {"status": status, "acceptance_probability_pct": prob, "fairness_grade": grade,
                    "summary_reason": _summary(status, fails, fi, my_dsl, opp_dsl, opp)},
        "quantitative_breakdown": {
            "user_starting_delta_ppg": f"{my_dsl:+.1f}", "opponent_starting_delta_ppg": f"{opp_dsl:+.1f}",
            "raw_value_gap": favor(raw_gap), "package_adjusted_gap": favor(adj_gap),
            "fairness_index": fi, "you_give_effective_value": round(v_give, 1), "you_get_effective_value": round(v_get, 1),
            "opponent_drop_candidate": ({"name": opp_cut[0]["name"], "value_lost": opp_cut[0]["trade"]} if opp_cut else None),
            "user_drop_candidate": ({"name": my_cut[0]["name"], "value_lost": my_cut[0]["trade"]} if my_cut else None),
            "acceptance_model": [{"factor": k, "points": v} for k, v in parts],
        },
        "gate_audit": dict(gate),
        "team_impact_diagnostics": _diagnostics(me, opp, give, get, my_new, my_replaced, opp_new, opp_replaced,
                                                my_dsl, opp_dsl, my_cut, opp_cut, o_arch),
        # Messages only make sense for a deal worth sending.
        "negotiation_scripts": _scripts(opp, give, get, opp_dsl, v_give, v_get) if status == "APPROVED" else None,
        "context": {
            "user_record": (me.get("record") or {}).get("text"), "opponent_record": (opp.get("record") or {}).get("text"),
            "opponent_archetype": o_arch, "user_weaknesses": me.get("weak", []), "user_strengths": me.get("strong", []),
            "opponent_weaknesses": opp_weak, "opponent_strengths": opp.get("strong", []),
            "user_starter_replaced": [{"name": p["name"], "proj_ppg": p["value"]} for p in my_replaced],
            "opponent_starter_replaced": [{"name": p["name"], "proj_ppg": p["value"]} for p in opp_replaced],
            "players": [{"name": p["name"], "side": side, "pos": p["position"], "tier": tier(p["trade"]),
                         "market_val": p["trade"], "proj_ppg": p["value"]}
                        for side, ps in (("user_gives", give), ("opponent_gives", get)) for p in ps],
        },
    })
    return out


def _summary(status, fails, fi, my_dsl, opp_dsl, opp):
    if status == "APPROVED":
        return (f"They gain {opp_dsl:+.1f} starting PPG and you gain {my_dsl:+.1f}, at a fairness index of {fi:.0f} "
                f"({'even' if 95 <= fi <= 105 else 'close'} on the trade chart).")
    why = {
        "tier": "a tier-1 player can't be bought with lesser pieces",
        "lineup": (f"{opp['name']}'s starting lineup only changes {opp_dsl:+.1f} PPG (needs +1.5)" if opp_dsl < OPP_MIN_DSL
                   else f"your starting lineup only changes {my_dsl:+.1f} PPG"),
        "fairness": f"the fairness index is {fi:.0f} ({'you underpay' if fi < 95 else 'you overpay'})",
        "3for1": "3-for-1 deals don't work in a league this size",
        "roster": "one side would have to cut a starter to make room",
        "contender": f"{opp['name']} is contending and won't sell a top player for depth",
        "stud_for_two": "only a struggling team sells a tier-1 player for two pieces",
        "insult": f"{opp['name']}'s best player is worth more than what you're offering (send back at least 85% of his value)",
        "bye": f"it would leave {opp['name']} with an empty starting slot in a bye week",
    }
    # Lead with the reason a person would see first: a wildly uneven trade
    # is "unfair" before it is anything else.
    first = "fairness" if "fairness" in fails and not 70 <= fi <= 130 else fails[0]
    lead = why[first]
    others = [why[f] for f in fails if f != first]
    if status == "MODIFICATION_REQUIRED":
        fix = ("add a little value to your side" if fails[0] == "fairness" and fi < 95 else
               "ask for a bit more back" if fails[0] == "fairness" else
               "swap in a player who would start for them")
        return f"Close but not there: {lead}; {fix}."
    return f"Dead on arrival: {lead}." + (f" Also: {others[0]}." if others else "")


def _diagnostics(me, opp, give, get, my_new, my_replaced, opp_new, opp_replaced, my_dsl, opp_dsl, my_cut, opp_cut, o_arch):
    pros = f"{my_dsl:+.1f} starting PPG for you."
    if my_new:
        pros += f" {_names(my_new)} {'start' if len(my_new) > 1 else 'starts'}"
        pros += f"; {_names(my_replaced)} {'move' if len(my_replaced) > 1 else 'moves'} to the bench." if my_replaced else "."
    else:
        pros += " Nobody you receive would crack your starting lineup."
    weak_hit = [w for w in me.get("weak", []) if any(w.startswith(p["position"]) for p in get)]
    if weak_hit:
        pros += f" Shores up your weak {', '.join(weak_hit)}."
    cons = [f"You lose {_names(give)}."]
    if my_cut:
        cons.append(f"You'd have to drop {_names(my_cut)}.")
    for p in get:
        if p.get("injury_status"):
            cons.append(f"{p['name']} is listed {p['injury_status']}.")
    give_ids = {g["player_id"] for g in give}
    byes = {}
    for p in [x for x in me["players"] if x["player_id"] not in give_ids] + list(get):
        if p.get("bye"):
            byes.setdefault(p["bye"], []).append(p)
    crowd = [(w, ps) for w, ps in byes.items() if len(ps) >= 4]
    if crowd:
        w, ps = max(crowd, key=lambda x: len(x[1]))
        cons.append(f"{len(ps)} of your players would share the week {w} bye.")
    if opp_dsl < 0:
        rationale = f"{opp['name']} would lose {abs(opp_dsl):.1f} starting PPG"
    else:
        rationale = f"{opp['name']} gains {opp_dsl:+.1f} starting PPG"
    if opp_new:
        rationale += f": {_names(opp_new)} {'start' if len(opp_new) > 1 else 'starts'} for them"
        rationale += f" and {_names(opp_replaced)} {'go' if len(opp_replaced) > 1 else 'goes'} to the bench" if opp_replaced else ""
    rationale += "."
    their_weak = [w for w in opp.get("weak", []) if any(w.startswith(p["position"]) for p in give)]
    if their_weak:
        rationale += f" It fills their weak {', '.join(their_weak)}."
    rec = (opp.get("record") or {}).get("text")
    if o_arch == "Desperate":
        rationale += f" At {rec} they need points now."
    elif o_arch == "Contender":
        rationale += f" At {rec} they're loading up for a title run."
    if opp_cut:
        rationale += f" They'd cut {_names(opp_cut)} to make room."
    return {"user_roster_pros": pros, "user_roster_cons": " ".join(cons), "opponent_rationale": rationale}


_SUFFIX = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


def _last(name):
    parts = [w for w in name.split() if w.lower() not in _SUFFIX]
    return parts[-1] if parts else name


def _short(ps):
    ps = list(ps)
    names = [_last(p["name"]) for p in ps]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _cap(text, n):
    w = text.split()
    return text if len(w) <= n else " ".join(w[:n]).rstrip(",.;") + "…"


def _scripts(opp, give, get, opp_dsl, v_give, v_get):
    star = max(give, key=lambda p: p["value"])
    need = (opp.get("weak") or [star["position"]])[0]
    usage = star.get("usage") or {}
    bits = []
    if usage.get("xfp_pg"):
        bits.append(f"{usage['xfp_pg']:.1f} xFP/g")
    if usage.get("target_share"):
        bits.append(f"{usage['target_share']:.0f}% target share")
    if usage.get("hvt_pg"):
        bits.append(f"{usage['hvt_pg']:.1f} HVT/g")
    usage_txt = ", ".join(bits) or f"{star['value']:.1f} projected PPG"
    rec = (opp.get("record") or {}).get("text") or "this point"
    g, t, st = _short(give), _short(get), _last(star["name"])
    adds = "add" if len(give) > 1 else "adds"
    fi = 100 * v_give / v_get if v_get else 100
    balance = ("close to even" if 95 <= fi <= 105 else "a little in your favor" if fi > 105
               else "close, and it fills a real need for you")
    return {
        "casual_manager": _cap(f"Hey! {need} looks like a tough spot for you. Would you do {g} for {t}? {st} slides right into your lineup.", 30),
        "quantitative_analyst": _cap(f"{st}: {usage_txt}. By my math that's {opp_dsl:+.1f} starting PPG for you. {g} for {t}?", 35),
        "skeptical_manager": _cap(f"Ran it against the consensus trade chart: {g} ({v_give:.0f}) vs {t} ({v_get:.0f}), {balance}, and it helps your {need}. Open to tweaking it together.", 35),
        "desperate_manager": _cap(f"At {rec}, every week counts. {g} {adds} {opp_dsl:+.1f} starting points for you this Sunday. Would you do it for {t}?", 30),
    }


# --------------------------------------------------------------- rosters ----
def build_rosters(league_id, pool, values, crosswalk=None, usage=None, byes=None):
    """{roster_id: {name, players, record}} from Sleeper, QB/RB/WR/TE we can value."""
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
                       "value": round(float(row["value"]), 1), "trade": values[g]["trade"], "tier": values[g]["tier"],
                       "ecr": values[g]["ecr"], "injury_status": st if isinstance(st, str) else None,
                       "usage": (usage or {}).get(g), "bye": (byes or {}).get(row["recent_team"])})
        out[rid] = {"name": (names.get(rid) or f"Team {rid}").strip(), "players": ps, "record": record(r)}
    return out


def annotate(rosters, slots):
    all_players = [t["players"] for t in rosters.values()]
    for t in rosters.values():
        t["weak"], t["strong"] = slot_profile(t["players"], slots, all_players)


# ---------------------------------------------------------------- finder ----
def _combos(players, sizes, must=None):
    must = set(must or [])
    for n in sizes:
        for combo in itertools.combinations(players, n):
            if must and not must.issubset({p["player_id"] for p in combo}):
                continue
            yield combo


def find_trades(rosters, my_roster_id, ctx, give_ids=None, target_ids=None, max_suggestions=6):
    """Every 1-for-1 up to 2-for-2 that passes every gate, ranked by mutual
    benefit, at most two per opponent and three per player of yours."""
    me = rosters[my_roster_id]

    def tradeable(ps):
        return sorted([p for p in ps if p.get("injury_status") != "IR"], key=lambda p: -p["trade"])[:CANDIDATES_PER_SIDE]
    if give_ids:
        my_pool = [p for p in me["players"] if p["player_id"] in give_ids] + \
                  [p for p in tradeable(me["players"]) if p["player_id"] not in give_ids][:4]
        my_sizes = (len(give_ids),) if len(give_ids) >= 2 else (1, 2)
    else:
        my_pool, my_sizes = tradeable(me["players"]), (1, 2)
    found = []
    for rid, opp in rosters.items():
        if rid == my_roster_id or (target_ids and rid not in target_ids):
            continue
        their_pool = tradeable(opp["players"])
        for give in _combos(my_pool, my_sizes, must=give_ids):
            for get in _combos(their_pool, (1, 2)):
                quick = assess(give, get, me, opp, ctx, full=False)
                if quick and quick["_status"] == "APPROVED":
                    found.append((quick["_score"], rid, give, get))
    if not found:
        # Nothing passes every gate: offer the closest one-tweak deals instead
        # of an empty page, clearly labelled as needing a change.
        for rid, opp in rosters.items():
            if rid == my_roster_id or (target_ids and rid not in target_ids):
                continue
            for give in _combos(my_pool, my_sizes, must=give_ids):
                for get in _combos(tradeable(opp["players"]), (1, 2)):
                    quick = assess(give, get, me, opp, ctx, full=False)
                    if quick and quick["_status"] == "MODIFICATION_REQUIRED":
                        found.append((quick["_score"] - 5, rid, give, get))
    found.sort(key=lambda x: -x[0])
    picked, per_opp, per_player, cores = [], {}, {}, set()
    for _, rid, give, get in found:
        core = (rid, frozenset(p["player_id"] for p in give if p["trade"] >= THROW_IN),
                frozenset(p["player_id"] for p in get if p["trade"] >= THROW_IN))
        if core in cores or per_opp.get(rid, 0) >= 2 or any(per_player.get(p["player_id"], 0) >= 3 for p in give):
            continue
        picked.append({"opponent_roster_id": rid, "opponent_team_name": rosters[rid]["name"],
                       "you_give": list(give), "you_get": list(get),
                       "analysis": assess(give, get, me, rosters[rid], ctx, full=True)})
        cores.add(core)
        per_opp[rid] = per_opp.get(rid, 0) + 1
        for p in give:
            per_player[p["player_id"]] = per_player.get(p["player_id"], 0) + 1
        if len(picked) >= max_suggestions:
            break
    return picked
