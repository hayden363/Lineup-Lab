"""
DECISION TOOLS — start/sit, trade analyzer, waiver wire
==========================================================
The three tools WalterPicks actually sells: "who do I start", "is this
trade good", "who do I add off waivers". All three are thin wrappers
around build_board()/rest_of_season_value() — one ranked, scored,
matchup-aware board is the single source of truth for every decision
surface in the app.
"""

from . import data, sleeper
from .board import (POSITIONS, build_board, load_bundle, rest_of_season_value,
                     project_vs)


def _position_of(player_id, bundle):
    prow = bundle["wk"][bundle["wk"]["player_id"] == player_id]
    if prow.empty:
        return None
    pos = prow.iloc[-1]["position"]
    return pos if pos in POSITIONS else None


def _board_cache(season, scoring):
    """One build_board() call per position per request, memoized locally
    so start/sit and trade tools (which may reference several players at
    the same position) don't rebuild the same board repeatedly."""
    cache = {}

    def get(position):
        if position not in cache:
            cache[position] = build_board(position, season=season, scoring=scoring)
        return cache[position]

    return get


def _clean_num(v):
    """NaN isn't valid JSON — normalize pandas' NaN/NaT to None before a
    dict full of these values leaves this module."""
    return None if (v is None or (isinstance(v, float) and (v != v))) else v


def _tier_confidence(top, other):
    """0-100: how confident the tier call between `top` (the best PROJ)
    and `other` is, from the REAL spread already on the board — each
    player's own floor-to-ceiling range (see build_board). A gap between
    them bigger than their combined uncertainty is a confident call; a gap
    swallowed by that uncertainty is a coin flip. Not a black-box model
    score — you can recompute this by hand from the two numbers shown."""
    gap = (top["PROJ"] or 0) - (other["PROJ"] or 0)
    top_spread = max((top.get("ceiling") or 0) - (top.get("floor") or 0), 0)
    other_spread = max((other.get("ceiling") or 0) - (other.get("floor") or 0), 0)
    spread = top_spread + other_spread
    if spread <= 0:
        return 60
    overlap_ratio = max(0.0, min(1.0, 1 - gap / spread))
    return int(round(min(97, max(50, 95 - overlap_ratio * 40))))


def _apply_recommendation_tiers(valid):
    """START / FLEX / BORDERLINE / SIT for every player in the comparison
    (not just a single winner), each with a confidence % — relative to the
    best-projected player, adjusted for a real injury designation (an
    "Out" tag overrides the projection math; a real designation on the
    field beats a model every time)."""
    if not valid:
        return
    ranked = sorted(valid, key=lambda r: r["PROJ"] or 0, reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    for r in ranked:
        is_top = r is top
        reference = second if is_top else top
        if reference is None:
            r["tier"], r["confidence"] = "START", 60
            continue
        top_val = max((top["PROJ"] or 0), 0.1)
        gap_pct = (r["PROJ"] - reference["PROJ"]) / top_val if not is_top else 0.0

        if r.get("injury_status") == "Out":
            tier = "SIT"
        elif is_top:
            tier = "START"
        elif gap_pct > -0.08:
            tier = "FLEX"
        elif gap_pct > -0.22:
            tier = "BORDERLINE"
        else:
            tier = "SIT"
        if r.get("injury_status") == "Doubtful" and tier in ("START", "FLEX"):
            tier = "BORDERLINE"

        # confidence always compares top against the OTHER player in the
        # pair (itself, when r is top and reference is #2) — not against
        # `reference`, which for a non-top r is top itself and would
        # compare top to top (zero gap, meaningless).
        confidence = _tier_confidence(top, second) if is_top else _tier_confidence(top, r)
        if r.get("injury_status") == "Out":
            confidence = max(confidence, 90)  # a real "Out" tag isn't a close call
        r["tier"] = tier
        r["confidence"] = confidence


def start_sit(player_ids, opponents=None, season=None, scoring=None):
    """Compare 2+ players. `opponents`: optional {player_id: opp_abbr} for
    matchup-adjusted projections; players without one use a rest-of-season
    blended projection instead.

    Every player gets a real signal set beyond the projection itself:
    floor/ceiling (actual spread of their own game log this season), snap
    share and red-zone touches (real opportunity/usage), and current
    injury designation — plus a START/FLEX/BORDERLINE/SIT tier with a
    confidence % computed from those same numbers (see
    _apply_recommendation_tiers), not a separate black-box score."""
    opponents = opponents or {}
    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)

    results = []
    for pid in player_ids:
        pos = _position_of(pid, bundle)
        if pos is None:
            results.append({"player_id": pid, "error": "player not found"})
            continue
        board = get_board(pos)
        if pid not in board.index:
            results.append({"player_id": pid, "error": "not enough data this season"})
            continue
        row = board.loc[pid].to_dict()
        opp = opponents.get(pid)
        if opp:
            projected = project_vs(board.loc[[pid]], pos, opp, bundle=bundle, scoring=scoring)
            proj = float(projected["PROJ"].iloc[0])
            matchup_tag = projected["matchup_tag"].iloc[0]
        else:
            proj = float(rest_of_season_value(board.loc[[pid]], pos, bundle=bundle, scoring=scoring).iloc[0])
            matchup_tag = None
        results.append({
            "player_id": pid, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "FORM": row.get("FORM"), "fpts_per_game": row.get("fpts_per_game"),
            "opponent": opp, "matchup_tag": matchup_tag, "PROJ": proj,
            "floor": _clean_num(row.get("floor")), "ceiling": _clean_num(row.get("ceiling")),
            "snap_pct": _clean_num(row.get("snap_pct")), "redzone_touches": _clean_num(row.get("redzone_touches")),
            "injury_status": _clean_num(row.get("injury_status")),
        })

    valid = [r for r in results if "error" not in r]
    _apply_recommendation_tiers(valid)
    if valid:
        best = max(valid, key=lambda r: r["PROJ"])
        for r in results:
            r["recommended"] = ("error" not in r) and (r["player_id"] == best["player_id"])
    return {"season": bundle["season"], "players": results}


def trade_analyzer(side_a_ids, side_b_ids, season=None, scoring=None):
    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)

    def side_value(ids):
        players, total = [], 0.0
        for pid in ids:
            pos = _position_of(pid, bundle)
            if pos is None:
                players.append({"player_id": pid, "error": "player not found"})
                continue
            board = get_board(pos)
            if pid not in board.index:
                players.append({"player_id": pid, "error": "not enough data this season"})
                continue
            row = board.loc[pid].to_dict()
            value = float(rest_of_season_value(board.loc[[pid]], pos, bundle=bundle, scoring=scoring).iloc[0])
            total += value
            players.append({
                "player_id": pid, "position": pos,
                "player_display_name": row.get("player_display_name"),
                "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
                "SCORE": row.get("SCORE"), "value": round(value, 1),
            })
        return players, round(total, 1)

    a_players, a_total = side_value(side_a_ids)
    b_players, b_total = side_value(side_b_ids)

    diff = round(a_total - b_total, 1)
    if abs(diff) < 1.5:
        verdict = "fair"
    elif diff > 0:
        verdict = "side_a"
    else:
        verdict = "side_b"

    return {
        "season": bundle["season"],
        "side_a": {"players": a_players, "total_value": a_total},
        "side_b": {"players": b_players, "total_value": b_total},
        "diff": diff,
        "verdict": verdict,
    }


def _roster_players(raw_ids, bundle, get_board, scoring, crosswalk=None, starters=None, slot_labels=None):
    """Real starting lineup (in real slot order — QB/RB/RB/WR/WR/TE/FLEX/
    FLEX/DEF/K, whatever the league actually runs, including multi-FLEX)
    first, then bench sorted by projected value. `starters`/`slot_labels`
    come straight from Sleeper — see sleeper.starters_for_week — not
    reconstructed by us. Only starters count toward the team total; a
    bench player isn't scoring this week, full stop.

    `raw_ids`/`starters` are Sleeper's own (untranslated) player ids;
    `crosswalk` maps them to our gsis player_id for QB/RB/WR/TE board
    lookups. A defense or kicker has no crosswalk entry — those get a real
    name/team via sleeper.resolve_unscored_player instead of a SCORE/PROJ,
    rather than silently vanishing from the lineup."""
    crosswalk = crosswalk or {}
    starters = starters or []
    slot_labels = slot_labels or []

    def build_row(raw_id, is_starter, slot):
        gsis_id = crosswalk.get(raw_id)
        pos = _position_of(gsis_id, bundle) if gsis_id else None
        if pos is None:
            unscored = sleeper.resolve_unscored_player(raw_id)
            if not unscored:
                return None  # genuinely unresolvable — skip rather than show garbage
            return {
                "player_id": raw_id, "position": unscored["position"],
                "player_display_name": unscored["player_display_name"],
                "recent_team": unscored["recent_team"], "headshot_url": None,
                "SCORE": None, "FORM": None, "fpts_per_game": None, "PROJ": None,
                "is_starter": is_starter, "slot": slot,
            }
        board = get_board(pos)
        if gsis_id not in board.index:
            return None
        row = board.loc[gsis_id].to_dict()
        proj = round(float(rest_of_season_value(board.loc[[gsis_id]], pos, bundle=bundle, scoring=scoring).iloc[0]), 1)
        return {
            "player_id": gsis_id, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "FORM": row.get("FORM"),
            "fpts_per_game": row.get("fpts_per_game"), "PROJ": proj,
            "is_starter": is_starter, "slot": slot,
        }

    starter_set = set(starters)
    rows, total = [], 0.0
    for raw_id, slot in zip(starters, slot_labels):
        row = build_row(raw_id, True, slot)
        if row:
            rows.append(row)
            if row["PROJ"] is not None:
                total += row["PROJ"]

    bench_rows = [r for r in (build_row(raw_id, False, None) for raw_id in raw_ids if raw_id not in starter_set) if r]
    bench_rows.sort(key=lambda r: -(r["PROJ"] if r["PROJ"] is not None else -1))
    rows.extend(bench_rows)

    return rows, round(total, 1)


def _team_total(raw_ids, bundle, get_board, scoring, crosswalk=None, starters=None):
    """Same 'starters only' rule as _roster_players, for the lighter-weight
    'every other matchup this week' view that doesn't need full rosters."""
    crosswalk = crosswalk or {}
    total = 0.0
    for raw_id in (starters or []):
        gsis_id = crosswalk.get(raw_id)
        pos = _position_of(gsis_id, bundle) if gsis_id else None
        if pos is None:
            continue
        board = get_board(pos)
        if gsis_id not in board.index:
            continue
        total += float(rest_of_season_value(board.loc[[gsis_id]], pos, bundle=bundle, scoring=scoring).iloc[0])
    return round(total, 1)


def league_all_player_names(league_id, season=None, scoring=None):
    """Every rostered player across the whole league, name-only — a cheap
    lookup (no valuation) for 'is this headline about someone in my league
    at all', which is what the League News tab's featured sort needs."""
    snap = sleeper.league_snapshot(league_id)
    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)
    seen = {}
    for team in snap["teams"]:
        for pid in team["player_ids"]:
            if pid in seen:
                continue
            pos = _position_of(pid, bundle)
            if pos is None:
                continue
            board = get_board(pos)
            if pid not in board.index:
                continue
            seen[pid] = {"player_id": pid, "player_display_name": board.loc[pid, "player_display_name"]}
    return list(seen.values())


def league_team_list(league_id):
    """roster_id/team_name/avatar for every team in the league — just
    enough to populate a team switcher, no player-level work."""
    snap = sleeper.league_snapshot(league_id)
    return [{"roster_id": t["roster_id"], "team_name": t["team_name"],
              "avatar_url": t.get("avatar_url") or t.get("owner_avatar_url")} for t in snap["teams"]]


def roster_player_list(league_id, roster_id, season=None, scoring=None):
    """Every player on one specific roster, full display info (name/
    position/headshot/value) — for browsing a team's roster to build a
    trade from (Trade tab's your-side / opponent-side panels), not the
    starters/bench split my_team() does. `league_snapshot`'s player_ids
    are already gsis-translated, so this resolves them directly rather
    than through the raw-sleeper-id + crosswalk path _roster_players uses
    for my_team (which needs the crosswalk to also catch DEF/K)."""
    snap = sleeper.league_snapshot(league_id)
    team_by_roster = {t["roster_id"]: t for t in snap["teams"]}
    entry = team_by_roster.get(roster_id)
    if entry is None:
        raise ValueError(f"roster_id {roster_id} not found in league {league_id}")

    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)

    players = []
    for pid in entry["player_ids"]:
        pos = _position_of(pid, bundle)
        if pos is None:
            continue
        board = get_board(pos)
        if pid not in board.index:
            continue
        row = board.loc[pid].to_dict()
        proj = float(rest_of_season_value(board.loc[[pid]], pos, bundle=bundle, scoring=scoring).iloc[0])
        players.append({
            "player_id": pid, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "PROJ": round(proj, 1),
        })
    players.sort(key=lambda p: -p["PROJ"])
    return {"roster_id": roster_id, "team_name": entry["team_name"],
            "avatar_url": entry.get("avatar_url") or entry.get("owner_avatar_url"),
            "owner": entry.get("owner"), "players": players}


def my_team(league_id, roster_id, season=None, scoring=None, week=None):
    """Sync a Sleeper league: lay out my roster and (if the league has a
    real head-to-head matchup set for the requested week) my opponent's,
    each with our own SCORE/FORM/PROJ for every player — plus, from the
    same real schedule data, every other matchup in the league that week.

    A league's full-season schedule (every week's pairings) is normally
    generated up front, well before the games are played — so `week` can
    be any week of the regular season, not just whatever week it is right
    now in the real NFL. Defaults to the live current week."""
    snap = sleeper.league_snapshot(league_id)
    if scoring is None:
        scoring = snap["scoring"]

    team_by_roster = {t["roster_id"]: t for t in snap["teams"]}
    my_entry = team_by_roster.get(roster_id)
    if my_entry is None:
        raise ValueError(f"roster_id {roster_id} not found in league {league_id}")

    nfl_state = sleeper.get_nfl_state()
    season_type = nfl_state.get("season_type")
    live_week = nfl_state.get("week")

    league = sleeper.get_league(league_id)
    playoff_start = (league.get("settings") or {}).get("playoff_week_start")
    regular_season_weeks = (playoff_start - 1) if playoff_start else 14

    if week is not None:
        # explicit week requested — always try it, regardless of what the
        # real NFL calendar is doing right now (the schedule may already
        # exist even in the preseason, once a league has drafted)
        requested_week = week
    else:
        # default to the live week during the season; before it starts,
        # default to week 1 so "my team" still shows something meaningful
        requested_week = live_week if season_type in ("regular", "post") and live_week else 1

    pairings = []
    try:
        pairings = sleeper.matchups_for_week(league_id, requested_week)
    except Exception:
        pairings = []
    week = requested_week

    opp_entry = None
    for pair in pairings:
        if roster_id in pair["roster_ids"]:
            others = [r for r in pair["roster_ids"] if r != roster_id]
            if others:
                opp_entry = team_by_roster.get(others[0])
            break

    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)

    # Real starting lineup, real slots (including a real double-FLEX league,
    # or DEF/K, or whatever your league actually runs) — from Sleeper's own
    # data, not reconstructed. Week-specific starters first; a week far
    # enough out that Sleeper has no matchup data for it yet falls back to
    # the roster's current saved lineup.
    roster_positions = league.get("roster_positions") or []
    slot_labels = [s for s in roster_positions if s != "BN"]
    crosswalk = sleeper.id_crosswalk()
    raw_rosters = sleeper.raw_roster_players(league_id)
    try:
        starters_by_roster = sleeper.starters_for_week(league_id, week)
    except Exception:
        starters_by_roster = {}
    if not any(starters_by_roster.values()):
        try:
            starters_by_roster = sleeper.roster_level_starters(league_id)
        except Exception:
            starters_by_roster = {}

    def team_card(entry):
        raw_ids = raw_rosters.get(entry["roster_id"], entry["player_ids"])
        starters = starters_by_roster.get(entry["roster_id"], [])
        players, total = _roster_players(raw_ids, bundle, get_board, scoring,
                                          crosswalk=crosswalk, starters=starters, slot_labels=slot_labels)
        return {"roster_id": entry["roster_id"], "team_name": entry["team_name"],
                "avatar_url": entry.get("avatar_url") or entry.get("owner_avatar_url"),
                "owner": entry.get("owner"), "players": players, "total_proj": total}

    result = {
        "season": bundle["season"], "league_id": league_id, "league_name": snap["league_name"],
        "nfl_week": week, "live_week": live_week, "season_type": season_type,
        "regular_season_weeks": regular_season_weeks,
        "my_team": team_card(my_entry),
        "opponent": team_card(opp_entry) if opp_entry else None,
    }

    # every other matchup this week, from the same real schedule data —
    # lighter weight than my_team/opponent (totals only, no per-player rows)
    league_matchups = []
    for pair in pairings:
        entries = [team_by_roster[r] for r in pair["roster_ids"] if r in team_by_roster]
        if not entries:
            continue
        sides = [{
            "roster_id": e["roster_id"], "team_name": e["team_name"],
            "avatar_url": e.get("avatar_url") or e.get("owner_avatar_url"),
            "total_proj": _team_total(raw_rosters.get(e["roster_id"], e["player_ids"]), bundle, get_board, scoring,
                                       crosswalk=crosswalk, starters=starters_by_roster.get(e["roster_id"], [])),
        } for e in entries]
        league_matchups.append({"matchup_id": pair["matchup_id"], "teams": sides})
    result["league_matchups"] = league_matchups
    return result


def _position_needs(roster_positions):
    """Starting-slot requirements per position, with FLEX spread evenly
    across RB/WR/TE (a simplification — real flex value skews RB/WR over
    TE, but this is a reasonable v1)."""
    base = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}
    flex = 0
    for slot in roster_positions or []:
        if slot in base:
            base[slot] += 1
        elif slot == "FLEX":
            flex += 1
    for pos in ("RB", "WR", "TE"):
        base[pos] += flex / 3
    return base


def _need_multiplier(position, filled_count, needs):
    need = needs.get(position, 1.0)
    if filled_count < need:
        return 1.25   # still need a starter here
    if filled_count < need * 1.75:
        return 1.0    # reasonably filled
    return 0.82        # already deep here — nudge toward other needs


def draft_board(draft_id, my_roster_id=None, season=None, scoring=None, best_available_limit=60):
    """Live snake-draft board: picks made so far (from Sleeper directly —
    no stats lookup needed, the pick's own metadata has name/position/team),
    who's on the clock, how many picks until yours, and a need-adjusted
    'best available' ranking across all positions.

    Rookies and stat-less players won't show a SCORE — this app doesn't
    fabricate a value for a player with no real NFL production yet. That's
    a real gap for rookie-heavy drafts; a dedicated rookie model (built off
    real draft capital, not guesswork) is the fix, tracked separately."""
    draft = sleeper.get_draft(draft_id)
    if not draft:
        raise ValueError(f"draft {draft_id} not found")
    picks_raw = sleeper.get_draft_picks(draft_id)
    pick_order = sleeper.build_pick_order(draft)
    crosswalk = sleeper.id_crosswalk()

    league_id = draft.get("league_id")
    roster_positions = []
    if league_id:
        try:
            league = sleeper.get_league(league_id)
            roster_positions = league.get("roster_positions") or []
        except Exception:
            pass
    needs = _position_needs(roster_positions)

    picks_made = []
    drafted_gsis = set()
    my_filled = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
    for p in picks_raw:
        meta = p.get("metadata") or {}
        gsis = crosswalk.get(str(p.get("player_id")))
        if gsis:
            drafted_gsis.add(gsis)
        pos = meta.get("position")
        if p.get("roster_id") == my_roster_id and pos in my_filled:
            my_filled[pos] += 1
        picks_made.append({
            "pick_no": p.get("pick_no"), "round": p.get("round"), "roster_id": p.get("roster_id"),
            "player_id": gsis, "player_display_name": f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip(),
            "position": pos, "team": meta.get("team"),
        })

    total_picks = len(pick_order)
    current_pick_no = len(picks_raw) + 1
    on_the_clock = pick_order[current_pick_no - 1]["roster_id"] if current_pick_no <= total_picks else None
    is_complete = current_pick_no > total_picks

    my_upcoming = [p["pick_no"] for p in pick_order if p["roster_id"] == my_roster_id and p["pick_no"] >= current_pick_no]
    picks_until_mine = (my_upcoming[0] - current_pick_no) if my_upcoming else None

    # A finished draft has nothing left to recommend — "best available" would
    # just be noise dressed up as advice for a pick that already happened, so
    # skip that (real) compute entirely and hand back your own actual picks
    # instead: a genuine recap, not a stale live-draft UI pretending to still
    # be useful.
    best_available = []
    my_picks_recap = []
    if is_complete:
        my_picks_recap = sorted(
            [p for p in picks_made if p["roster_id"] == my_roster_id],
            key=lambda p: p["pick_no"] or 0,
        )
    else:
        bundle = load_bundle(season)
        for pos in POSITIONS:
            board = build_board(pos, season=season, scoring=scoring)
            board = board[~board.index.isin(drafted_gsis)]
            mult = _need_multiplier(pos, my_filled.get(pos, 0), needs) if my_roster_id is not None else 1.0
            for pid, row in board.head(40).iterrows():
                best_available.append({
                    "player_id": pid, "position": pos,
                    "player_display_name": row.get("player_display_name"),
                    "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
                    "SCORE": row.get("SCORE"), "ADJ_SCORE": round(float(row.get("SCORE", 0)) * mult, 1),
                    "fpts_per_game": row.get("fpts_per_game"), "need_multiplier": mult,
                })
        best_available.sort(key=lambda r: r["ADJ_SCORE"], reverse=True)

    return {
        "draft_id": draft_id, "league_id": league_id, "status": draft.get("status"),
        "season": draft.get("season"),
        "draft_type": draft.get("type"), "rounds": draft.get("settings", {}).get("rounds"),
        "teams": draft.get("settings", {}).get("teams"),
        "total_picks": total_picks, "current_pick_no": current_pick_no, "is_complete": is_complete,
        "on_the_clock_roster_id": on_the_clock,
        "my_roster_id": my_roster_id, "my_filled_positions": my_filled, "my_picks_recap": my_picks_recap,
        "picks_until_mine": picks_until_mine, "my_next_pick_no": my_upcoming[0] if my_upcoming else None,
        "picks_made": picks_made,
        "best_available": best_available[:best_available_limit],
        "supported_format": draft.get("type") == "snake",
    }


def trade_finder(league_id, my_roster_id, target_roster_id=None, give_player_ids=None,
                  season=None, scoring=None, max_suggestions=5):
    """Scan (one or every) other roster for a realistic trade.

    Two modes:
      - Need-driven (default, `give_player_ids` omitted): the system picks
        what you'd give from your deepest position to fill your weakest
        need — scans for opportunities you haven't thought to look for.
      - Player-driven (`give_player_ids` set): you pick which of your own
        player(s) to shop; the system searches every other roster for the
        best realistic return for that specific player or package.

    Both modes are built on the same rest-of-season values as the Trade
    Analyzer, not a separate guess, and reject anything too lopsided to be
    a realistic offer (>35% value gap)."""
    snap = sleeper.league_snapshot(league_id)
    if scoring is None:
        scoring = snap["scoring"]
    team_by_roster = {t["roster_id"]: t for t in snap["teams"]}
    my_team = team_by_roster.get(my_roster_id)
    if my_team is None:
        raise ValueError(f"roster_id {my_roster_id} not found in league {league_id}")

    league = sleeper.get_league(league_id)
    needs = _position_needs(league.get("roster_positions") or [])

    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)

    def roster_by_position(player_ids):
        out = {"QB": [], "RB": [], "WR": [], "TE": []}
        for pid in player_ids:
            pos = _position_of(pid, bundle)
            if pos not in out:
                continue
            board = get_board(pos)
            if pid not in board.index:
                continue
            row = board.loc[pid].to_dict()
            value = float(rest_of_season_value(board.loc[[pid]], pos, bundle=bundle, scoring=scoring).iloc[0])
            out[pos].append({"player_id": pid, "position": pos, "value": value,
                              "player_display_name": row.get("player_display_name"),
                              "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url")})
        return out

    my_by_pos = roster_by_position(my_team["player_ids"])
    my_filled = {pos: len(players) for pos, players in my_by_pos.items()}
    my_weak_positions = sorted(needs.keys(), key=lambda p: my_filled.get(p, 0) - needs.get(p, 0))
    # my best surplus: positions where I'm deepest relative to need (what I can afford to trade from)
    my_strong_positions = sorted(needs.keys(), key=lambda p: my_filled.get(p, 0) - needs.get(p, 0), reverse=True)

    targets = [target_roster_id] if target_roster_id else [r for r in team_by_roster if r != my_roster_id]
    suggestions = []

    if give_player_ids:
        # Player-driven: you chose what to shop, we search every other roster for the best return.
        my_players_flat = {p["player_id"]: p for players in my_by_pos.values() for p in players}
        missing = [pid for pid in give_player_ids if pid not in my_players_flat]
        if missing:
            raise ValueError(f"Player(s) not on your roster or not scoreable this season: {', '.join(missing)}")
        give_players = [my_players_flat[pid] for pid in give_player_ids]
        if not give_players:
            raise ValueError("No valid players selected to shop.")
        give_value = sum(p["value"] for p in give_players)

        for opp_id in targets:
            opp_team = team_by_roster.get(opp_id)
            if not opp_team:
                continue
            opp_by_pos = roster_by_position(opp_team["player_ids"])
            opp_candidates = []
            for pos, players in opp_by_pos.items():
                for candidate in players:
                    diff = abs(candidate["value"] - give_value)
                    if diff > max(candidate["value"], give_value, 1) * 0.35:
                        continue  # too lopsided to be realistic
                    opp_candidates.append({
                        "opponent_roster_id": opp_id, "opponent_team_name": opp_team["team_name"],
                        "you_give": give_players, "you_get": [candidate],
                        "value_diff": round(candidate["value"] - give_value, 1),
                        "fills_need": pos if pos in my_weak_positions else None,
                    })
            opp_candidates.sort(key=lambda s: (s["fills_need"] is None, -s["value_diff"]))
            suggestions.extend(opp_candidates[:2])  # best couple of fits per team, not every match

        suggestions.sort(key=lambda s: (s["fills_need"] is None, -s["value_diff"]))
    else:
        # Need-driven: the original "scan for opportunities" behavior.
        for opp_id in targets:
            opp_team = team_by_roster.get(opp_id)
            if not opp_team:
                continue
            opp_by_pos = roster_by_position(opp_team["player_ids"])
            # they give: their best player at one of my weak positions
            # I give: my best surplus player at one of their weak positions, similar value
            for weak_pos in my_weak_positions:
                gets = sorted(opp_by_pos.get(weak_pos, []), key=lambda p: -p["value"])
                if not gets:
                    continue
                get_player = gets[0]
                for give_pos in my_strong_positions:
                    if give_pos == weak_pos and len(my_by_pos.get(give_pos, [])) <= int(needs.get(give_pos, 1)):
                        continue  # don't suggest trading from a position I also need
                    gives = sorted(my_by_pos.get(give_pos, []), key=lambda p: abs(p["value"] - get_player["value"]))
                    if not gives:
                        continue
                    give_player = gives[0]
                    diff = abs(give_player["value"] - get_player["value"])
                    if diff > max(get_player["value"], give_player["value"]) * 0.35:
                        continue  # too lopsided to be realistic
                    suggestions.append({
                        "opponent_roster_id": opp_id, "opponent_team_name": opp_team["team_name"],
                        "you_give": [give_player], "you_get": [get_player],
                        "value_diff": round(get_player["value"] - give_player["value"], 1),
                        "fills_need": weak_pos,
                    })
                    break  # one suggestion per (opponent, weak position)

        suggestions.sort(key=lambda s: -s["value_diff"])

    return {"season": bundle["season"], "my_roster_id": my_roster_id, "suggestions": suggestions[:max_suggestions]}


def waiver_wire(positions=None, rostered_ids=None, season=None, scoring=None, limit=15, trending=True):
    """Top available (not-rostered) players by SCORE, per position.
    `rostered_ids`: player_ids to exclude — pass a synced league's roster,
    or leave empty to just see the position's full ranked board.
    `trending`: attach Sleeper's real platform-wide add-count from the last
    48h (trending_adds) — actual usage data, not something we're inferring."""
    positions = positions or list(POSITIONS)
    rostered_ids = set(rostered_ids or [])
    bundle = load_bundle(season)

    trending_counts = {}
    if trending:
        try:
            trending_counts = sleeper.trending_gsis_counts("add", lookback_hours=48, limit=200)
        except Exception as e:
            print(f"[waivers] couldn't fetch trending data: {e}")

    out = {}
    for pos in positions:
        board = build_board(pos, season=season, scoring=scoring)
        board = board[~board.index.isin(rostered_ids)]
        board = board.head(limit).reset_index()
        board.insert(0, "rank", range(1, len(board) + 1))
        board["trending_adds"] = board["player_id"].map(trending_counts).fillna(0).astype(int)
        out[pos] = board.to_dict(orient="records")  # kept in SCORE order; trending is a badge, not a re-sort
    return {"season": bundle["season"], "available": out}
