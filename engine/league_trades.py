"""
LEAGUE TRADES — what changed hands, who gave and who got
============================================================
Reads Sleeper's transactions feed and turns each completed trade into a
two-sided summary a person can read: for every team, the players and picks it
received and gave up. Pure parsing lives in `parse_trade` so it can be tested
without the network.
"""

from . import sleeper


def parse_trade(tx, team_names, player_name):
    """`tx` is one Sleeper transaction dict. `team_names` is {roster_id: name};
    `player_name(sleeper_id)` returns a display name. Returns None unless it's
    a completed trade. Each side lists what that roster RECEIVED."""
    if tx.get("type") != "trade" or tx.get("status") != "complete":
        return None
    sides = {rid: {"roster_id": rid, "team": team_names.get(rid, f"Team {rid}"), "receives": [], "gives": []}
             for rid in tx.get("roster_ids") or []}
    for pid, rid in (tx.get("adds") or {}).items():
        sides.setdefault(rid, {"roster_id": rid, "team": team_names.get(rid, f"Team {rid}"), "receives": [], "gives": []})
        sides[rid]["receives"].append({"kind": "player", "player_id": pid, "name": player_name(pid)})
    for pid, rid in (tx.get("drops") or {}).items():
        sides.setdefault(rid, {"roster_id": rid, "team": team_names.get(rid, f"Team {rid}"), "receives": [], "gives": []})
        sides[rid]["gives"].append({"kind": "player", "player_id": pid, "name": player_name(pid)})
    for pk in tx.get("draft_picks") or []:
        label = f"{pk.get('season')} round {pk.get('round')} pick"
        new_owner, old_owner = pk.get("owner_id"), pk.get("previous_owner_id")
        if new_owner in sides:
            sides[new_owner]["receives"].append({"kind": "pick", "name": label})
        if old_owner in sides:
            sides[old_owner]["gives"].append({"kind": "pick", "name": label})
    return {"id": tx.get("transaction_id"), "week": tx.get("leg"),
            "at": tx.get("status_updated") or tx.get("created"), "sides": list(sides.values())}


def league_trades(league_id, weeks, force=False):
    """Completed trades across `weeks` (iterable of week numbers), newest
    first. A week Sleeper has no data for is skipped, not fatal."""
    teams = {t["roster_id"]: t["team_name"] for t in sleeper.league_snapshot(league_id)["teams"]}
    players = sleeper.all_players()

    def name(pid):
        p = players.get(pid) or {}
        return p.get("full_name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x) or str(pid)

    out = []
    for w in weeks:
        try:
            txs = sleeper.get_transactions(league_id, w, force=force)
        except Exception:
            continue
        for tx in txs or []:
            t = parse_trade(tx, teams, name)
            if t:
                out.append(t)
    out.sort(key=lambda t: t.get("at") or 0, reverse=True)
    return out


def new_trades(trades, seen_ids):
    """Trades whose id isn't in `seen_ids` — what to flag as 'new' to the user."""
    seen = set(seen_ids or [])
    return [t for t in trades if t["id"] not in seen]
