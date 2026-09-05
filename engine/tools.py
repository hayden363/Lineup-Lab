"""
DECISION TOOLS — start/sit, trade analyzer, waiver wire
==========================================================
The three tools WalterPicks actually sells: "who do I start", "is this
trade good", "who do I add off waivers". All three are thin wrappers
around build_board()/rest_of_season_value() — one ranked, scored,
matchup-aware board is the single source of truth for every decision
surface in the app.
"""

from . import data, db, defense_scoring, kicker_scoring, role_baseline, sleeper
from .board import (POSITIONS, build_board, load_bundle, rest_of_season_value,
                     project_vs)
from .scoring import apply_scoring


def _league_scoring_settings(league_id):
    if not league_id:
        return None
    try:
        return sleeper.get_league(league_id).get("scoring_settings")
    except Exception as e:
        print(f"[tools] couldn't load league scoring settings (using defaults): {e}")
        return None


def _opponent_adjusted_proj(board, gsis_id, pos, bundle, scoring, week=None):
    """PROJ for one player against their own REAL upcoming NFL opponent
    (via data.next_opponent, resolved from their recent_team) rather than
    rest_of_season_value()'s season-long average across every defense.
    That average is the right number for trade/start-sit/waiver tools
    comparing many possible weeks/opponents at once — but "my team, this
    week" has one specific real matchup, and every player showing the
    exact same number regardless of who they actually play is wrong for
    that view. Falls back to the season-average when there's no real
    upcoming opponent to resolve (bye week, end of season, or a team
    missing from the schedule) so a player never just shows a blank."""
    row = board.loc[[gsis_id]]
    recent_team = row["recent_team"].iloc[0] if "recent_team" in row.columns else None
    opp = None
    if recent_team:
        opp, _ = data.next_opponent(bundle["schedule"], recent_team, week)
    if opp:
        return round(float(project_vs(row, pos, opp, bundle=bundle, scoring=scoring)["PROJ"].iloc[0]), 1)
    return round(float(rest_of_season_value(row, pos, bundle=bundle, scoring=scoring).iloc[0]), 1)


def _defense_board(bundle, league_id=None):
    """Real DEF/ST board for this season (see engine/defense_scoring.py) —
    scored with the real league's own Sleeper scoring settings when we
    know them, Sleeper's common defaults otherwise. Cheap enough (one
    small groupby over ~32 teams) to build fresh per request."""
    return defense_scoring.build_defense_board(bundle["pbp"], bundle["schedule"],
                                                 scoring_settings=_league_scoring_settings(league_id))


def _kicker_board(bundle, league_id=None):
    """Real K board for this season (see engine/kicker_scoring.py) — same
    per-request-fresh pattern as _defense_board."""
    return kicker_scoring.build_kicker_board(bundle["pbp"], scoring_settings=_league_scoring_settings(league_id))


def _kicker_team_baseline(bundle, league_id=None):
    """Real per-team kicking baseline (see
    kicker_scoring.build_team_kicker_baseline) — the fallback for a
    kicker with a known current team but no personal game log."""
    return kicker_scoring.build_team_kicker_baseline(bundle["pbp"], scoring_settings=_league_scoring_settings(league_id))


def _role_rank_baselines(bundle, scoring):
    """Real per-team, per-rank RB/WR/TE production (see
    engine/role_baseline.py) — the fallback for a skill-position player
    with a known current team and current depth-chart rank (both live,
    from Sleeper) but no personal game log. Built from the same scoring
    settings the rest of the board uses, so it's on the same points
    scale."""
    wk, _ = apply_scoring(bundle["wk"], scoring)
    return role_baseline.build_role_rank_baselines(wk)


def _role_rank_row(raw_id, unscored, rank_baselines, is_starter, slot):
    """A real PROJ for a skill-position player with no personal game log,
    from his own CURRENT team's real historical same-depth-chart-rank
    production (see engine/role_baseline.py) — or None if there's no
    live depth-chart rank for him, or his team/position has no real
    baseline to draw on. SCORE/FORM/floor/ceiling stay None: this is a
    team+role-level estimate, not a claim about his own skill."""
    if rank_baselines is None or unscored["position"] not in role_baseline.RANK_POSITIONS:
        return None
    proj = role_baseline.resolve_role_rank_projection(
        unscored.get("recent_team"), unscored.get("depth_chart_order"),
        unscored["position"], rank_baselines,
    )
    if proj is None:
        return None
    return {
        "player_id": raw_id, "position": unscored["position"],
        "player_display_name": unscored["player_display_name"],
        "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
        "SCORE": None, "FORM": None, "fpts_per_game": None, "PROJ": round(float(proj), 1),
        "injury_status": None, "is_starter": is_starter, "slot": slot,
    }


def _defense_row(raw_id, unscored, def_board, is_starter, slot):
    """A real SCORE/FORM/PROJ row for a DEF slot, or None if this team
    isn't in the board (shouldn't happen for a real NFL team code, but a
    bad/placeholder id shouldn't crash the roster view)."""
    if def_board is None:
        return None
    row = defense_scoring.resolve_defense_row(raw_id, def_board)
    if row is None:
        return None
    proj = round(row["fpts_per_game"] * (1 + row["FORM"] / 100.0), 1)
    return {
        "player_id": raw_id, "position": "DEF",
        "player_display_name": unscored["player_display_name"],
        "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
        "SCORE": row["SCORE"], "FORM": row["FORM"], "fpts_per_game": row["fpts_per_game"], "PROJ": proj,
        "floor": row["floor"], "ceiling": row["ceiling"], "injury_status": None,
        "is_starter": is_starter, "slot": slot,
    }


def _kicker_row(gsis_id, unscored, k_board, team_baseline, is_starter, slot):
    """A real SCORE/FORM/PROJ row for a K slot, keyed by the gsis_id the
    crosswalk already resolved for this Sleeper id.

    If this specific kicker has never attempted a kick in our data (a
    rookie or a new signing with no personal game log — Sleeper's own
    live roster is the source of truth for who's actually kicking now,
    not our 2024-pinned stat season), fall back to his real CURRENT
    team's own kicking production last season instead of a blank/0 — see
    kicker_scoring.build_team_kicker_baseline for why that's a defensible
    number and not a guess about his own leg. SCORE/FORM stay None in
    that case: PROJ there is a team-level estimate, not a personal
    valuation, and shouldn't be presented as one."""
    if k_board is not None and gsis_id is not None and gsis_id in k_board.index:
        row = k_board.loc[gsis_id].to_dict()
        proj = round(row["fpts_per_game"] * (1 + row["FORM"] / 100.0), 1)
        return {
            "player_id": gsis_id, "position": "K",
            "player_display_name": unscored["player_display_name"],
            "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
            "SCORE": row["SCORE"], "FORM": row["FORM"], "fpts_per_game": row["fpts_per_game"], "PROJ": proj,
            "floor": row["floor"], "ceiling": row["ceiling"], "injury_status": None,
            "is_starter": is_starter, "slot": slot,
        }
    if team_baseline is not None:
        team = defense_scoring.SLEEPER_TO_NFLVERSE_TEAM.get(unscored.get("recent_team"), unscored.get("recent_team"))
        if team in team_baseline.index:
            return {
                "player_id": gsis_id or unscored.get("recent_team"), "position": "K",
                "player_display_name": unscored["player_display_name"],
                "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
                "SCORE": None, "FORM": None, "fpts_per_game": None,
                "PROJ": round(float(team_baseline.loc[team]), 1),
                "injury_status": None, "is_starter": is_starter, "slot": slot,
            }
    return None


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
        # Real upcoming week for this player's team, regardless of whether
        # an explicit opponent override was passed — this is what
        # log_predictions/resolve_predictions grade the eventual call
        # against, so it has to be an actual schedule week, not a guess.
        _, wk_no = data.next_opponent(bundle["schedule"], row.get("recent_team"))
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
            "opponent": opp, "matchup_tag": matchup_tag, "PROJ": proj, "week": wk_no,
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


def resolve_track_record():
    """Grade every logged Start/Sit prediction (see server.py's
    /api/startsit -> db.log_predictions) whose real week has since been
    fully played, against real published stats for that week — never a
    simulated or estimated outcome. Safe to call repeatedly (e.g. once
    per refresh_scheduler tick): a week with nothing pending, or one
    that hasn't fully finished yet, just resolves 0 rows and moves on.

    Only one real-stats lookup per distinct (season, week, scoring)
    combo among what's actually pending, not one per logged player —
    db.pending_resolution_groups() already de-duplicates that."""
    total = 0
    for group in db.pending_resolution_groups():
        season, week, scoring = group["season"], group["week"], group["scoring"]
        bundle = load_bundle(season)
        # current_week = "latest week with a COMPLETED game" — a week is
        # only safe to grade once we've moved on to a later one, so a
        # week still mid-slate (e.g. Monday night not played yet) isn't
        # graded on a partial picture.
        if week >= data.current_week(bundle["schedule"]):
            continue
        wk, _ = apply_scoring(bundle["wk"], scoring)
        actual = wk[wk["week"] == week].groupby("player_id")["fpts_active"].sum().to_dict()
        total += db.resolve_predictions(season, week, actual)
    return total


def trade_analyzer(side_a_ids, side_b_ids, season=None, scoring=None, league_ctx=None):
    """Value comparison (always) plus, when `league_ctx` is supplied, a
    real roster-needs-aware recommendation for each side — not just "who
    gives up more points" but "does this actually help either team's
    actual roster." `league_ctx`, when present, is
    `{"roster_a": <roster_player_list()-shaped dict for side A's full
    CURRENT roster>, "roster_b": <same for side B>, "roster_positions":
    <league's real starting-lineup slots, e.g. Sleeper's
    league["roster_positions"]>}` — both rosters are each side's whole
    team as it stands right now (not just the players in this trade),
    which is what "does this fill a real hole" actually needs to know.
    Missing/None `league_ctx` (no signed-in league context, or a platform
    the needs machinery doesn't support yet — see server.py) just means
    `recommendation` comes back None; the value comparison still works
    exactly as before."""
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

    recommendation = None
    if league_ctx:
        try:
            recommendation = _trade_recommendation(a_players, b_players, a_total, b_total, league_ctx)
        except Exception as e:
            print(f"[trade] couldn't build needs-aware recommendation (value-only): {e}")

    return {
        "season": bundle["season"],
        "side_a": {"players": a_players, "total_value": a_total},
        "side_b": {"players": b_players, "total_value": b_total},
        "diff": diff,
        "verdict": verdict,
        "recommendation": recommendation,
    }


def _roster_players(raw_ids, bundle, get_board, scoring, crosswalk=None, starters=None,
                     slot_labels=None, def_board=None, k_board=None, k_team_baseline=None,
                     rank_baselines=None, resolve_unscored=None, week=None):
    """Real starting lineup (in real slot order — QB/RB/RB/WR/WR/TE/FLEX/
    FLEX/DEF/K, whatever the league actually runs, including multi-FLEX)
    first, then bench sorted by projected value. `starters`/`slot_labels`
    come straight from Sleeper — see sleeper.starters_for_week — not
    reconstructed by us. Only starters count toward the team total; a
    bench player isn't scoring this week, full stop.

    `raw_ids`/`starters` are Sleeper's own (untranslated) player ids;
    `crosswalk` maps them to our gsis player_id for QB/RB/WR/TE board
    lookups. A defense has no crosswalk entry but IS real-scoreable — see
    `_defense_row`/engine/defense_scoring.py — so it gets a real SCORE/
    PROJ, not just a name/photo. A kicker DOES have a crosswalk entry
    (nflverse's weekly player-stats table just never included kickers —
    see engine/kicker_scoring.py) — `_kicker_row` reuses the `gsis_id`
    already resolved below rather than needing its own lookup. Anyone
    truly unpriceable (no qualifying stats in our data — most commonly a
    rookie with no NFL games yet) still gets a real name/team via
    sleeper.resolve_unscored_player, and a PROJ of exactly 0.0 rather than
    a blank — every roster slot shows a number, full stop. SCORE/FORM stay
    None there: those are real per-player valuations, and there's a
    difference between "genuinely projected for zero" (a real answer,
    what 0.0 means here) and "we have no idea," which is what a
    fabricated SCORE would actually be for someone with zero qualifying
    games — SCORE keeps saying so honestly instead of pretending 0.

    `resolve_unscored` defaults to Sleeper's own resolver — pass a
    different one (see engine/espn.py's usage in my_team_espn below) to
    reuse this exact same DEF/K/rookie fallback machinery for a
    non-Sleeper roster source. Every existing caller gets the untouched
    Sleeper behavior by not passing it."""
    crosswalk = crosswalk or {}
    starters = starters or []
    slot_labels = slot_labels or []
    resolve_unscored = resolve_unscored or sleeper.resolve_unscored_player

    def build_row(raw_id, is_starter, slot):
        gsis_id = crosswalk.get(raw_id)
        pos = _position_of(gsis_id, bundle) if gsis_id else None
        if pos is None:
            unscored = resolve_unscored(raw_id)
            if not unscored:
                return None  # genuinely unresolvable — skip rather than show garbage
            if unscored["position"] == "DEF":
                def_row = _defense_row(raw_id, unscored, def_board, is_starter, slot)
                if def_row:
                    return def_row
            elif unscored["position"] == "K":
                k_row = _kicker_row(gsis_id, unscored, k_board, k_team_baseline, is_starter, slot)
                if k_row:
                    return k_row
            elif unscored["position"] in role_baseline.RANK_POSITIONS:
                role_row = _role_rank_row(raw_id, unscored, rank_baselines, is_starter, slot)
                if role_row:
                    return role_row
            return {
                "player_id": raw_id, "position": unscored["position"],
                "player_display_name": unscored["player_display_name"],
                "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
                "SCORE": None, "FORM": None, "fpts_per_game": None, "PROJ": 0.0,
                "injury_status": None, "is_starter": is_starter, "slot": slot,
            }
        board = get_board(pos)
        if gsis_id not in board.index:
            return None
        row = board.loc[gsis_id].to_dict()
        proj = _opponent_adjusted_proj(board, gsis_id, pos, bundle, scoring, week=week)
        return {
            "player_id": gsis_id, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "FORM": row.get("FORM"),
            "fpts_per_game": row.get("fpts_per_game"), "PROJ": proj,
            "injury_status": _clean_num(row.get("injury_status")),
            "is_starter": is_starter, "slot": slot,
        }

    starter_set = set(starters)
    rows, total = [], 0.0
    for raw_id, slot in zip(starters, slot_labels):
        row = build_row(raw_id, True, slot)
        if row:
            rows.append(row)
            total += row["PROJ"]

    bench_rows = [r for r in (build_row(raw_id, False, None) for raw_id in raw_ids if raw_id not in starter_set) if r]
    bench_rows.sort(key=lambda r: -r["PROJ"])
    rows.extend(bench_rows)

    return rows, round(total, 1)


def _team_total(raw_ids, bundle, get_board, scoring, crosswalk=None, starters=None,
                 def_board=None, k_board=None, k_team_baseline=None, rank_baselines=None, week=None):
    """Same 'starters only' rule as _roster_players, for the lighter-weight
    'every other matchup this week' view that doesn't need full rosters."""
    crosswalk = crosswalk or {}
    total = 0.0
    for raw_id in (starters or []):
        gsis_id = crosswalk.get(raw_id)
        pos = _position_of(gsis_id, bundle) if gsis_id else None
        if pos is None:
            if def_board is not None:
                def_row = defense_scoring.resolve_defense_row(raw_id, def_board)
                if def_row:
                    total += def_row["fpts_per_game"] * (1 + def_row["FORM"] / 100.0)
                    continue
            if k_board is not None and gsis_id is not None and gsis_id in k_board.index:
                k_row = k_board.loc[gsis_id]
                total += k_row["fpts_per_game"] * (1 + k_row["FORM"] / 100.0)
                continue
            if k_team_baseline is not None or rank_baselines is not None:
                unscored = sleeper.resolve_unscored_player(raw_id)
                if unscored and unscored["position"] == "K" and k_team_baseline is not None:
                    recent_team = unscored.get("recent_team")
                    team = (defense_scoring.SLEEPER_TO_NFLVERSE_TEAM.get(recent_team, recent_team)
                            if recent_team is not None else None)
                    if team in k_team_baseline.index:
                        total += float(k_team_baseline.loc[team])
                elif unscored and unscored["position"] in role_baseline.RANK_POSITIONS and rank_baselines is not None:
                    proj = role_baseline.resolve_role_rank_projection(
                        unscored.get("recent_team"), unscored.get("depth_chart_order"),
                        unscored["position"], rank_baselines,
                    )
                    if proj is not None:
                        total += float(proj)
            continue
        board = get_board(pos)
        if gsis_id not in board.index:
            continue
        total += _opponent_adjusted_proj(board, gsis_id, pos, bundle, scoring, week=week)
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
    starters/bench split my_team() does.

    Walks the RAW (untranslated) roster + a crosswalk, same as my_team,
    rather than league_snapshot's already gsis-translated player_ids —
    that translation silently drops anyone without a gsis match (every
    DEF/K, plus any real player our id crosswalk just doesn't cover), and
    a trade-builder that quietly can't show your kicker or your actual
    FLEX starter is a real (if not fatal) gap. Falls back to real Sleeper
    name/photo data for anyone we can't price rather than dropping them."""
    snap = sleeper.league_snapshot(league_id)
    team_by_roster = {t["roster_id"]: t for t in snap["teams"]}
    entry = team_by_roster.get(roster_id)
    if entry is None:
        raise ValueError(f"roster_id {roster_id} not found in league {league_id}")

    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)
    crosswalk = sleeper.id_crosswalk()
    raw_ids = sleeper.raw_roster_players(league_id).get(roster_id, [])
    def_board = _defense_board(bundle, league_id)
    k_board = _kicker_board(bundle, league_id)
    k_team_baseline = _kicker_team_baseline(bundle, league_id)
    rank_baselines = _role_rank_baselines(bundle, scoring)

    players = []
    for raw_id in raw_ids:
        gsis_id = crosswalk.get(raw_id)
        pos = _position_of(gsis_id, bundle) if gsis_id else None
        if pos is None:
            unscored = sleeper.resolve_unscored_player(raw_id)
            if not unscored:
                continue
            special_row = None
            if unscored["position"] == "DEF":
                special_row = _defense_row(raw_id, unscored, def_board, is_starter=None, slot=None)
            elif unscored["position"] == "K":
                special_row = _kicker_row(gsis_id, unscored, k_board, k_team_baseline, is_starter=None, slot=None)
            elif unscored["position"] in role_baseline.RANK_POSITIONS:
                special_row = _role_rank_row(raw_id, unscored, rank_baselines, is_starter=None, slot=None)
            if special_row:
                players.append({k: special_row[k] for k in
                                 ("player_id", "position", "player_display_name", "recent_team",
                                  "headshot_url", "SCORE", "PROJ", "injury_status")})
                continue
            players.append({
                "player_id": raw_id, "position": unscored["position"],
                "player_display_name": unscored["player_display_name"],
                "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
                "SCORE": None, "PROJ": 0.0, "injury_status": None,
            })
            continue
        board = get_board(pos)
        if gsis_id not in board.index:
            continue
        row = board.loc[gsis_id].to_dict()
        proj = _opponent_adjusted_proj(board, gsis_id, pos, bundle, scoring)
        players.append({
            "player_id": gsis_id, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "PROJ": proj,
            "injury_status": _clean_num(row.get("injury_status")),
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
    def_board = _defense_board(bundle, league_id)
    k_board = _kicker_board(bundle, league_id)
    k_team_baseline = _kicker_team_baseline(bundle, league_id)
    rank_baselines = _role_rank_baselines(bundle, scoring)
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
                                          crosswalk=crosswalk, starters=starters, slot_labels=slot_labels,
                                          def_board=def_board, k_board=k_board, k_team_baseline=k_team_baseline,
                                          rank_baselines=rank_baselines, week=week)
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
                                       crosswalk=crosswalk, starters=starters_by_roster.get(e["roster_id"], []),
                                       def_board=def_board, k_board=k_board, k_team_baseline=k_team_baseline,
                                       rank_baselines=rank_baselines, week=week),
        } for e in entries]
        league_matchups.append({"matchup_id": pair["matchup_id"], "teams": sides})
    result["league_matchups"] = league_matchups
    return result


def my_team_espn(league_id, team_id, season=None, scoring=None, week=None, year=None, espn_s2=None, swid=None):
    """ESPN equivalent of my_team() — same output shape (my_team/opponent/
    nfl_week/live_week/regular_season_weeks/league_matchups), built from
    ESPN's own per-player roster data (lineup slot IS starter/bench, no
    separate "starters for this week" call needed the way Sleeper needs
    one) instead of Sleeper's. Reuses the exact same _roster_players()
    DEF/K/role-baseline fallback machinery via engine/espn.py's
    roster_lineup()/build_unscored_resolver() adapters.

    `year` is the live ESPN/fantasy season (2026 right now) — a
    different number from `season`, this app's own STATS season (still
    2025 until nflverse publishes 2026 games; see resolve_season in
    engine/data.py). Defaults the same way server.py's /api/espn test
    endpoint does: ask Sleeper's live NFL state, since that's a free,
    already-fetched source of "what year is it really" independent of
    our stats season.

    Known gaps, disclosed rather than silently wrong: DEF/K here score
    with this app's standard defaults, not the league's actual custom
    DEF/K rules (unlike QB/RB/WR/TE, which uses your league's real
    scoring via engine/espn.py's scoring_from_espn — translating ESPN's
    separate DEF/K stat-id scoring isn't built yet). No "every other
    matchup in the league" section yet either (my_team() has one, this
    returns an empty list) — that needs every other team's roster
    resolved too, deferred rather than shipped half-verified."""
    from . import espn as espn_layer

    year = year or espn_layer.resolve_year()
    league = espn_layer.get_league(league_id, year, espn_s2=espn_s2, swid=swid)
    if scoring is None:
        scoring = espn_layer.scoring_from_espn(league)

    team_by_id = {t.team_id: t for t in league.teams}
    my_t = team_by_id.get(team_id)
    if my_t is None:
        raise ValueError(f"team_id {team_id} not found in ESPN league {league_id}")

    week = week or league.current_week
    opp_t = None
    try:
        idx = week - 1
        if 0 <= idx < len(my_t.schedule) and my_t.schedule[idx] is not my_t:
            opp_t = my_t.schedule[idx]
    except Exception:
        opp_t = None

    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)
    def_board = _defense_board(bundle)
    k_board = _kicker_board(bundle)
    k_team_baseline = _kicker_team_baseline(bundle)
    rank_baselines = _role_rank_baselines(bundle, scoring)
    crosswalk = espn_layer.id_crosswalk()
    resolve_unscored = espn_layer.build_unscored_resolver(league)

    def team_card(t):
        raw_ids, starters, slot_labels = espn_layer.roster_lineup(t)
        players, total = _roster_players(raw_ids, bundle, get_board, scoring,
                                          crosswalk=crosswalk, starters=starters, slot_labels=slot_labels,
                                          def_board=def_board, k_board=k_board, k_team_baseline=k_team_baseline,
                                          rank_baselines=rank_baselines, resolve_unscored=resolve_unscored, week=week)
        return {"roster_id": t.team_id, "team_name": t.team_name,
                "avatar_url": t.logo_url or None, "owner": espn_layer.owner_name(t),
                "players": players, "total_proj": total}

    return {
        "season": bundle["season"], "league_id": str(league_id), "league_name": league.settings.name,
        "nfl_week": week, "live_week": league.current_week, "season_type": None,
        "regular_season_weeks": league.settings.reg_season_count,
        "my_team": team_card(my_t),
        "opponent": team_card(opp_t) if opp_t else None,
        "league_matchups": [],  # not built for ESPN yet — see docstring
    }


def league_team_list_espn(league_id, year=None, espn_s2=None, swid=None):
    """ESPN equivalent of league_team_list() — team_id/team_name/avatar
    for every team in an ESPN-connected league, to populate the Trade
    tab's opponent switcher."""
    from . import espn as espn_layer

    year = year or espn_layer.resolve_year()
    league = espn_layer.get_league(league_id, year, espn_s2=espn_s2, swid=swid)
    return [{"roster_id": t.team_id, "team_name": t.team_name, "avatar_url": t.logo_url or None}
            for t in league.teams]


def league_all_player_names_espn(league_id, year=None, espn_s2=None, swid=None):
    """ESPN equivalent of league_all_player_names() — every rostered
    player's real display name, for the League News tab's featured-match
    sort. Unlike the Sleeper version this doesn't need a board lookup:
    ESPN's own roster data already carries a real display name for
    everyone (including DEF/K/rookies our board can't price), and this
    is only used for 'is this headline about someone in my league at
    all,' not a valuation."""
    from . import espn as espn_layer

    year = year or espn_layer.resolve_year()
    league = espn_layer.get_league(league_id, year, espn_s2=espn_s2, swid=swid)
    seen = {}
    for t in league.teams:
        for p in t.roster:
            raw_id = p.proTeam if p.position == "D/ST" else str(p.playerId)
            if raw_id not in seen:
                seen[raw_id] = {"player_id": raw_id, "player_display_name": p.name}
    return list(seen.values())


def roster_player_list_espn(league_id, roster_id, year=None, season=None, scoring=None, espn_s2=None, swid=None):
    """ESPN equivalent of roster_player_list() — one team's full roster,
    real values, for the Trade tab's split-screen builder. Reuses the
    exact same _roster_players() DEF/K/role-baseline fallback machinery
    my_team_espn() uses (via espn.py's roster_lineup()/
    build_unscored_resolver() adapters) rather than a second parallel
    pipeline. Same disclosed gap as my_team_espn: DEF/K score with this
    app's standard defaults, not this league's actual custom DEF/K rules
    (see that function's docstring) — everything else uses the league's
    real scoring."""
    from . import espn as espn_layer

    year = year or espn_layer.resolve_year()
    league = espn_layer.get_league(league_id, year, espn_s2=espn_s2, swid=swid)
    if scoring is None:
        scoring = espn_layer.scoring_from_espn(league)

    team_by_id = {t.team_id: t for t in league.teams}
    team = team_by_id.get(roster_id)
    if team is None:
        raise ValueError(f"team_id {roster_id} not found in ESPN league {league_id}")

    bundle = load_bundle(season)
    get_board = _board_cache(season, scoring)
    def_board = _defense_board(bundle)
    k_board = _kicker_board(bundle)
    k_team_baseline = _kicker_team_baseline(bundle)
    rank_baselines = _role_rank_baselines(bundle, scoring)
    crosswalk = espn_layer.id_crosswalk()
    resolve_unscored = espn_layer.build_unscored_resolver(league)

    raw_ids, _, _ = espn_layer.roster_lineup(team)
    # Every player treated as a "starter" here on purpose — unlike
    # my_team_espn's lineup view, a trade-builder roster browser wants
    # the whole team with no bench distinction, same as roster_player_list's
    # Sleeper behavior.
    rows, _ = _roster_players(raw_ids, bundle, get_board, scoring, crosswalk=crosswalk,
                               starters=raw_ids, slot_labels=[None] * len(raw_ids),
                               def_board=def_board, k_board=k_board, k_team_baseline=k_team_baseline,
                               rank_baselines=rank_baselines, resolve_unscored=resolve_unscored)
    players = [{k: r[k] for k in ("player_id", "position", "player_display_name", "recent_team",
                                    "headshot_url", "SCORE", "PROJ", "injury_status")} for r in rows]
    players.sort(key=lambda p: -(p["PROJ"] or 0))
    return {"roster_id": roster_id, "team_name": team.team_name,
            "avatar_url": team.logo_url or None, "owner": espn_layer.owner_name(team), "players": players}


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


def _team_position_counts(players):
    """Headcount of a roster's real players at each QB/RB/WR/TE slot —
    the same real signal draft_board's need-adjusted best-available
    already scans, applied here to a full CURRENT roster instead of
    picks made so far in a draft. DEF/K/anything else doesn't factor
    into flex-position need scoring — there's exactly one DEF and one K
    slot in almost every league, so 'need' there isn't really a
    graduated thing the way RB/WR/TE depth is."""
    counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
    for p in players:
        pos = p.get("position")
        if pos in counts:
            counts[pos] += 1
    return counts


def _team_needs(roster_players, roster_positions):
    """A real need multiplier per position for one team's CURRENT full
    roster (see _position_needs/_need_multiplier) — 1.25 = a real hole,
    1.0 = adequately filled, 0.82 = already deep. This is the same
    machinery the live draft board's 'need-adjusted best available'
    already uses, just fed a roster instead of draft picks."""
    needs = _position_needs(roster_positions)
    counts = _team_position_counts(roster_players)
    return {pos: _need_multiplier(pos, counts[pos], needs) for pos in counts}


def _fit_score(outgoing, incoming, needs):
    """Positive: what you're receiving matters more to your OWN roster
    right now than what you're giving up does — a real upgrade in team
    construction, not just points. Negative: you're trading away a
    position you're genuinely thin at for one you already have plenty
    of. Only QB/RB/WR/TE count (see _team_position_counts) — a DEF/K
    swap doesn't move a roster's need profile the way a skill-position
    swap does."""
    def total(players):
        return sum(needs.get(p.get("position"), 1.0) for p in players if p.get("position") in needs)
    return round(total(incoming) - total(outgoing), 2)


# (value_delta, fit_score) -> (tier, human-readable reason). Both signals
# matter: a trade can win on raw value and still be a bad idea for a
# roster that's already three-deep at the position it's acquiring, or
# lose on value and still be the right move if it fills a real hole.
_FIT_THRESHOLD = 0.15
_VALUE_THRESHOLD = 1.5


def _side_verdict(value_delta, fit):
    lopsided_value = abs(value_delta) > _VALUE_THRESHOLD
    real_fit = abs(fit) > _FIT_THRESHOLD
    wins_value = value_delta > _VALUE_THRESHOLD
    good_fit = fit > _FIT_THRESHOLD

    if wins_value and good_fit:
        return "great", "Wins on value AND fills a real roster need — an easy yes."
    if wins_value and real_fit and not good_fit:
        return "good_value_bad_fit", "Wins on value, but trades away a position you're thin at for one you're already deep in."
    if wins_value:
        return "good_value", "Wins on value; roster fit is close to a wash either way."
    if (not wins_value) and lopsided_value and good_fit:
        return "worth_it", "Gives up more value, but fills a real hole — worth it if that need outweighs the raw points."
    if lopsided_value and not wins_value and not good_fit:
        return "bad", "Loses on value and doesn't address a real need — hard to recommend."
    if lopsided_value:
        return "bad_value", "Loses on value; roster fit is close to a wash either way."
    if good_fit:
        return "smart", "Fair value, and a smart move for roster construction — addresses a real need."
    if real_fit:
        return "questionable", "Fair value, but you're already deep at what you'd be receiving."
    return "fair", "Roughly fair on both value and roster need."


def _trade_recommendation(a_players, b_players, a_total, b_total, league_ctx):
    """The actual recommendation, not just a number: for each side, does
    what they're receiving address a real hole in THEIR OWN current
    roster, weighed alongside the raw value swing — see _side_verdict."""
    a_valid = [p for p in a_players if "error" not in p]
    b_valid = [p for p in b_players if "error" not in p]

    needs_a = _team_needs(league_ctx["roster_a"]["players"], league_ctx.get("roster_positions"))
    needs_b = _team_needs(league_ctx["roster_b"]["players"], league_ctx.get("roster_positions"))

    # A gives away a_valid, receives b_valid — judged against A's own needs.
    fit_a = _fit_score(a_valid, b_valid, needs_a)
    fit_b = _fit_score(b_valid, a_valid, needs_b)

    net_value_a = round(b_total - a_total, 1)   # value A nets from this trade
    net_value_b = round(a_total - b_total, 1)   # value B nets from this trade

    tier_a, reason_a = _side_verdict(net_value_a, fit_a)
    tier_b, reason_b = _side_verdict(net_value_b, fit_b)

    if abs(net_value_a) <= _VALUE_THRESHOLD:
        value_lean = "Roughly even on value"
    elif net_value_a > 0:
        value_lean = "Leans toward Side A on value"
    else:
        value_lean = "Leans toward Side B on value"

    fit_a_real, fit_b_real = fit_a > _FIT_THRESHOLD, fit_b > _FIT_THRESHOLD
    if fit_a_real and fit_b_real:
        fit_lean = "fills a real need for both sides"
    elif fit_a_real:
        fit_lean = "clearly helps Side A's roster more"
    elif fit_b_real:
        fit_lean = "clearly helps Side B's roster more"
    elif fit_a <= -_FIT_THRESHOLD and fit_b <= -_FIT_THRESHOLD:
        fit_lean = "doesn't really address either side's needs"
    else:
        fit_lean = "roughly a wash on roster fit"

    return {
        "headline": f"{value_lean} — {fit_lean}.",
        "side_a": {"net_value": net_value_a, "fit_score": fit_a, "tier": tier_a, "reason": reason_a, "needs": needs_a},
        "side_b": {"net_value": net_value_b, "fit_score": fit_b, "tier": tier_b, "reason": reason_b, "needs": needs_b},
    }


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
                    "SCORE": row.get("SCORE"),
                    # pandas-stubs 1.5.3.230321 mistypes Series.get(key, default)'s
                    # return as `Dtype` unconditionally — it's actually a scalar
                    # value here, so this is a real pyright false positive.
                    "ADJ_SCORE": round(float(row.get("SCORE", 0)) * mult, 1),  # type: ignore[reportArgumentType]
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
