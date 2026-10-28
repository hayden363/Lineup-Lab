"""
DECISION TOOLS — start/sit, trade analyzer, waiver wire
==========================================================
The three tools WalterPicks actually sells: "who do I start", "is this
trade good", "who do I add off waivers". All three are thin wrappers
around build_board()/rest_of_season_value() — one ranked, scored,
matchup-aware board is the single source of truth for every decision
surface in the app.
"""

import time

import numpy as np
import pandas as pd

from . import lineup as lineup_layer
from . import profile
from . import context, correlation, data, db, decision, kdef_model, schemas, play_prob, draft_runs, history, trade_engine, locks, trade_reasons, defense_scoring, kicker_scoring, role_baseline, sleeper, waivers, weather
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


class _Actuals:
    """What actually happened in games already played in one NFL week, so a
    completed (or part-completed) week shows real points instead of a
    projection of a game that is over. A team's game counts as final only when
    the schedule has its score AND the weekly stats table has that team's
    players for the week (the stats lag the schedule by a day or so), so a
    just-finished game keeps its projection until the stats arrive."""

    def __init__(self, bundle, scoring, week, league_id=None):
        self.week = int(week)
        sched = bundle["schedule"]
        s = sched[(sched["week"] == self.week) & sched["home_score"].notna()]
        if "game_type" in s.columns:
            s = s[s["game_type"] == "REG"]
        played = set(s["home_team"]) | set(s["away_team"])
        wk = bundle["wk"]
        in_stats = set(wk.loc[wk["week"] == self.week, "recent_team"])
        self.final_teams = played & in_stats
        self._skill = {}
        if self.final_teams:
            scored, _ = apply_scoring(wk[wk["week"] == self.week], scoring)
            self._skill = scored.groupby("player_id")["fpts_active"].sum().to_dict()
        self._defense, self._kicker = {}, {}
        league = _league_scoring_settings(league_id)
        if self.final_teams:
            try:
                d = defense_scoring.build_defense_weekly(bundle["pbp"], sched)
                d = d[d["week"] == self.week]
                pts = defense_scoring.score_defense_weekly(d, defense_scoring.def_scoring_from_sleeper(league))
                self._defense = dict(zip(d["defteam"], pts))
            except Exception as e:
                print(f"[tools] actual defense scores unavailable: {e}")
            try:
                k = kicker_scoring.build_kicker_weekly(bundle["pbp"])
                k = k[k["week"] == self.week]
                pts = kicker_scoring.score_kicker_weekly(k, kicker_scoring.k_scoring_from_sleeper(league))
                self._kicker = dict(zip(k["player_id"], pts))
            except Exception as e:
                print(f"[tools] actual kicker scores unavailable: {e}")

    def any(self):
        return bool(self.final_teams)

    def skill(self, gsis_id, team):
        if team not in self.final_teams:
            return None
        return round(float(self._skill.get(gsis_id, 0.0)), 1)

    def defense(self, raw_team):
        team = defense_scoring.to_nflverse_team(raw_team)
        if team not in self.final_teams or team not in self._defense:
            return None
        return round(float(self._defense[team]), 1)

    def kicker(self, gsis_id, team=None):
        if gsis_id in self._kicker:
            return round(float(self._kicker[gsis_id]), 1)
        if team and defense_scoring.to_nflverse_team(team) in self.final_teams:
            return 0.0       # his team played and he never attempted a kick
        return None

    def points(self, row):
        """Actual points for a roster row, or None while his game is unplayed."""
        pos, pid = row.get("position"), row.get("player_id")
        if pos == "DEF":
            return self.defense(pid)
        if pos == "K":
            return self.kicker(pid, row.get("recent_team"))
        team = defense_scoring.to_nflverse_team(row.get("recent_team"))
        return self.skill(pid, team) if pos in ("QB", "RB", "WR", "TE") else None


def _team_on_bye(bundle, team, week):
    """True when `team` has its bye in the explicitly requested NFL `week`: it
    plays no game, so every player on it scores 0, not a next-game projection."""
    if week is None or not team:
        return False
    byes = bundle.get("_bye_weeks")
    if byes is None:
        byes = bundle["_bye_weeks"] = profile.bye_weeks(bundle["schedule"])
    return byes.get(team) == int(week)


def _head_to_head(gsis_id, opp, scoring, bundle, baseline):
    """({"factor", "meetings", "avg", "season_avg"}) for his own record against `opp` over the last two seasons and
    this one (engine/history.h2h_factor), or None with no usable history. The factor is small by design: see the
    note on H2H_SHRINK in engine/history.py."""
    season, wk = bundle.get("season"), bundle.get("wk")
    if not opp or not gsis_id or season is None or not history.available():
        return None
    games = history.player_games(gsis_id, scoring, season)
    mine = wk[wk["player_id"] == gsis_id] if wk is not None else []
    if len(mine):
        scored, _ = apply_scoring(mine, scoring)
        games = games + [{"season": season, "week": int(r.week), "opponent": r.opponent_team, "points": float(r.fpts_active)}
                         for r in scored.itertuples(index=False) if isinstance(getattr(r, "opponent_team", None), str)]
    meet = history.versus(games, opp, current=season)
    if not meet:
        return None
    return {"factor": history.h2h_factor(games, opp, baseline, current=season), "meetings": meet["games"], "avg": meet["avg"]}


def _opponent_adjusted_proj_full(board, gsis_id, pos, bundle, scoring, week=None, info=None):
    """Same real computation as _opponent_adjusted_proj below, also
    returning the real injury-factor disclosure detail behind PROJ (None,
    None when there isn't any — no live Questionable/Doubtful match, or
    the rest_of_season_value fallback path, which bakes the real factor
    into PROJ either way but doesn't return per-row detail — see
    engine/board.py). Split out so every OTHER existing caller of
    _opponent_adjusted_proj (team totals, the Projection Breakdown
    endpoint) keeps getting a bare float and doesn't have to change."""
    row = board.loc[[gsis_id]]
    recent_team = row["recent_team"].iloc[0] if "recent_team" in row.columns else None
    opp, game_week = None, None
    if recent_team:
        if _team_on_bye(bundle, recent_team, week):
            return 0.0, (None, None)
        opp, game_week = data.next_opponent(bundle["schedule"], recent_team, week)
    if opp:
        projected = project_vs(row, pos, opp, bundle=bundle, scoring=scoring)
        proj = float(projected["PROJ"].iloc[0])
        h2h = _head_to_head(gsis_id, opp, scoring, bundle, proj)
        if info is not None:       # out-param: the opponent and matchup read, for rows that want to show them
            info.update({"opponent": opp,
                         "matchup_tag": projected["matchup_tag"].iloc[0] if "matchup_tag" in projected.columns else None,
                         "matchup_factor": _clean_num(projected["matchup_factor"].iloc[0]) if "matchup_factor" in projected.columns else None})
        # The market view of his game (implied team total, script, roof), the same factor Start/Sit and the player
        # page apply, so My Team shows the number they do.
        env_f = 1.0
        if game_week and bundle.get("schedule") is not None:
            ctx = context.game_context(bundle["schedule"], recent_team, game_week)
            env_f, _ = context.environment_factor(pos, ctx, _clean_num(row["target_share"].iloc[0]) if "target_share" in row.columns else None)
        proj = round(proj * env_f * (h2h["factor"] if h2h else 1.0), 1)
        detail = (_clean_num(projected["injury_factor"].iloc[0]), _clean_num(projected["injury_sample_n"].iloc[0]))
    else:
        proj = round(float(rest_of_season_value(row, pos, bundle=bundle, scoring=scoring).iloc[0]), 1)
        detail = (None, None)
    # The number above is his score if he plays. A player who won't play scores
    # nothing, and one listed Questionable/Doubtful plays only some of the time
    # (the same chance Start/Sit uses), so a team total can't count him in full.
    status = row["injury_status"].iloc[0] if "injury_status" in row.columns else None
    if status in decision.WONT_PLAY:
        return 0.0, detail
    report = row["injury_report"].iloc[0] if "injury_report" in row.columns else None
    pp = play_prob.play_probability(pos, status, report)
    if pp:
        proj = round(proj * pp["p_play"], 1)
    return proj, detail


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
    return _opponent_adjusted_proj_full(board, gsis_id, pos, bundle, scoring, week=week)[0]


def real_proj_for_player(player_id, position, bundle=None, scoring=None, week=None, season=None):
    """Public wrapper around _opponent_adjusted_proj for one player, for
    callers outside this module (currently: server.py's Projection
    Breakdown endpoint) that want the exact same real PROJ number My Team
    already shows — not a second, differently-computed projection for
    the same player. Returns None if the player has no real games logged
    this season at all (a genuinely real "nothing to show" case, not the
    same early-season ranked-list gap the min_games=0 fallback below
    covers for someone with a real, if sparse, sample)."""
    bundle = bundle or load_bundle(season)
    board = build_board(position, season=season, scoring=scoring)
    if player_id not in board.index:
        # Same real early-season gap as My Team/Start-Sit/Trade — you
        # asked about this exact player by id, so the ranked-list bar
        # (build_board's default min_games=2) has no business hiding them.
        board = build_board(position, season=season, min_games=0, scoring=scoring)
        if player_id not in board.index:
            return None
    return _opponent_adjusted_proj(board, player_id, position, bundle, scoring, week=week)


def _row_rate(row):
    """A K or DEF board row's projection rate: the history-blended `rate` when
    the board has one, else the plain season average."""
    r = row.get("rate") if hasattr(row, "get") else None
    return float(r) if r is not None and r == r else float(row["fpts_per_game"])


def _defense_board(bundle, league_id=None):
    """Real DEF/ST board for this season (see engine/defense_scoring.py) —
    scored with the real league's own Sleeper scoring settings when we
    know them, Sleeper's common defaults otherwise. Cheap enough (one
    small groupby over ~32 teams) to build fresh per request."""
    return defense_scoring.build_defense_board(bundle["pbp"], bundle["schedule"],
                                                 scoring_settings=_league_scoring_settings(league_id),
                                                 season=bundle.get("season"))


def _offense_fragility(bundle, league_id=None):
    """Real defense-vs-offense matchup factor for every real NFL offense
    (see engine/defense_scoring.build_offense_fragility) — the mirror of
    _defense_board, so a DEF/ST slot's PROJ can vary by who it's actually
    facing instead of always showing the same season-average number.
    Same cheap-enough-to-build-fresh-per-request pattern."""
    return defense_scoring.build_offense_fragility(bundle["pbp"], bundle["schedule"],
                                                     scoring_settings=_league_scoring_settings(league_id))


def _defense_opponent(bundle, team_code, week=None):
    """A DEF/ST slot's own real next opponent OFFENSE — the team code its
    board is keyed by (nflverse, via SLEEPER_TO_NFLVERSE_TEAM) is a
    defense; this resolves who THAT defense actually plays, the same
    data.next_opponent() lookup _opponent_adjusted_proj uses for skill
    positions."""
    nflverse_code = defense_scoring.SLEEPER_TO_NFLVERSE_TEAM.get(team_code, team_code)
    opp, _ = data.next_opponent(bundle["schedule"], nflverse_code, week)
    return opp


def _kicker_board(bundle, league_id=None):
    """Real K board for this season (see engine/kicker_scoring.py) — same
    per-request-fresh pattern as _defense_board."""
    return kicker_scoring.build_kicker_board(bundle["pbp"], scoring_settings=_league_scoring_settings(league_id),
                                             season=bundle.get("season"))


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


def _pool_rate(board):
    """League-wide average projection rate of a K or DEF board: the 'pool' kdef_model scales against."""
    col = "rate" if "rate" in board.columns else "fpts_per_game"
    m = board[col].mean()
    return float(m) if m == m else 0.0


def _defense_proj(row, def_board, bundle, team_code, week=None):
    """PROJ for a DEF/ST: shrunk rate adjusted by the betting market's implied total for the offense
    it faces (engine/kdef_model.py). Falls back to neutral when there's no schedule/line."""
    ctx = None
    if bundle is not None:
        ctx = kdef_model.game_context(bundle["schedule"], defense_scoring.to_nflverse_team(team_code), week)
    return kdef_model.defense_projection(_row_rate(row), _pool_rate(def_board), (ctx or {}).get("itt_opp"))


def _kicker_proj(rate, k_pool, bundle, team_code, week=None):
    """PROJ for a kicker: shrunk rate adjusted by his offense's implied total and a roof
    (engine/kdef_model.py). Neutral when there's no schedule/line."""
    ctx = None
    if bundle is not None and team_code:
        ctx = kdef_model.game_context(bundle["schedule"], defense_scoring.to_nflverse_team(team_code), week)
    return kdef_model.kicker_projection(rate, k_pool, (ctx or {}).get("itt"), (ctx or {}).get("indoor"))


def _defense_row(raw_id, unscored, def_board, is_starter, slot, bundle=None, fragility=None, week=None):
    """A real SCORE/FORM/PROJ row for a DEF slot, or None if this team
    isn't in the board (shouldn't happen for a real NFL team code, but a
    bad/placeholder id shouldn't crash the roster view). PROJ is adjusted
    by the real offense this defense is actually about to face (see
    engine/defense_scoring.build_offense_fragility) when bundle/fragility
    are given — falls back to the unadjusted FORM-only number (the old
    behavior) when they're not, or when there's no real next opponent to
    resolve yet (see _opponent_adjusted_proj's docstring on why that's
    currently the common case)."""
    if def_board is None:
        return None
    row = defense_scoring.resolve_defense_row(raw_id, def_board)
    if row is None:
        return None
    proj = _defense_proj(row, def_board, bundle, raw_id, week)
    return {
        "player_id": raw_id, "position": "DEF",
        "player_display_name": unscored["player_display_name"],
        "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
        "SCORE": row["SCORE"], "FORM": row["FORM"], "fpts_per_game": row["fpts_per_game"], "PROJ": proj,
        "floor": row["floor"], "ceiling": row["ceiling"], "injury_status": None,
        "is_starter": is_starter, "slot": slot,
    }


def _kicker_row(gsis_id, unscored, k_board, team_baseline, is_starter, slot, bundle=None, week=None):
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
        proj = _kicker_proj(_row_rate(row), _pool_rate(k_board), bundle, unscored.get("recent_team"), week)
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
                "PROJ": _kicker_proj(float(team_baseline.loc[team]), float(team_baseline.mean()), bundle,
                                     unscored.get("recent_team"), week),
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
    if hasattr(v, "item") and type(v).__module__ == "numpy":
        v = v.item()   # numpy.int64 etc. aren't JSON-serializable
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
    rv = lambda r: r.get("rank_value", r["PROJ"]) or 0  # the lens (safe/upside) picks the order
    ranked = sorted(valid, key=rv, reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    for r in ranked:
        is_top = r is top
        reference = second if is_top else top
        if reference is None:
            r["tier"], r["confidence"] = "START", 60
            continue
        top_val = max(rv(top), 0.1)
        gap_pct = (rv(r) - rv(reference)) / top_val if not is_top else 0.0

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


def start_sit(player_ids, opponents=None, season=None, scoring=None, mode="balanced", keep_samples=False):
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
    # A team on bye in this week's slate isn't playing, whatever its next game is.
    slate_week = waivers.target_week(bundle["schedule"])
    byes = profile.bye_weeks(bundle["schedule"])
    weather.prefetch(bundle["schedule"], slate_week)
    for pid in player_ids:
        pos = _position_of(pid, bundle)
        if pos is None:
            results.append({"player_id": pid, "error": "player not found"})
            continue
        board = get_board(pos)
        if pid not in board.index:
            # Same real early-season gap fixed in _roster_players/
            # _team_total/roster_player_list — a specific player you're
            # deliberately comparing (clicked in from your own roster, or
            # searched by name) shouldn't show "not enough data" just for
            # not yet clearing the RANKED-LIST bar; that bar exists to
            # keep strangers' one-game flukes off a top-N list, not to
            # hide a player you already asked about by id.
            raw_board = build_board(pos, season=bundle["season"], min_games=0, scoring=scoring)
            if pid not in raw_board.index:
                results.append({"player_id": pid, "error": "not enough data this season"})
                continue
            board = raw_board
        row = board.loc[pid].to_dict()
        # Real upcoming week for this player's team, regardless of whether
        # an explicit opponent override was passed — this is what
        # log_predictions/resolve_predictions grade the eventual call
        # against, so it has to be an actual schedule week, not a guess.
        # With no override, the projection is against that real next opponent.
        next_opp, wk_no = data.next_opponent(bundle["schedule"], row.get("recent_team"))
        opp = opponents.get(pid) or next_opp
        on_bye = not opponents.get(pid) and byes.get(row.get("recent_team")) == slate_week
        if opp:
            projected = project_vs(board.loc[[pid]], pos, opp, bundle=bundle, scoring=scoring)
            proj = float(projected["PROJ"].iloc[0])
            matchup_tag = projected["matchup_tag"].iloc[0]
            matchup_factor = _clean_num(projected["matchup_factor"].iloc[0])
            # Only project_vs's per-opponent path computes these (see
            # engine/board.py) — rest_of_season_value already bakes the
            # real injury factor into PROJ either way, it just doesn't
            # return the per-row "why" detail alongside a bare number.
            injury_factor = _clean_num(projected["injury_factor"].iloc[0])
            injury_sample_n = _clean_num(projected["injury_sample_n"].iloc[0])
        else:
            proj = float(rest_of_season_value(board.loc[[pid]], pos, bundle=bundle, scoring=scoring).iloc[0])
            matchup_tag = None
            matchup_factor = None
            injury_factor = None
            injury_sample_n = None
        # Game environment + usage trend (engine/context.py): a capped
        # multiplier from the betting-market view of this game, applied to
        # the projection and its floor/ceiling alike.
        ctx = context.game_context(bundle["schedule"], row.get("recent_team"), wk_no) if wk_no else None
        env_f, env_notes = context.environment_factor(pos, ctx, _clean_num(row.get("target_share")))
        h2h = _head_to_head(pid, opp, scoring, bundle, proj) if opp and not on_bye else None
        h2h_f = h2h["factor"] if h2h else 1.0
        base_proj = proj
        proj = proj * env_f * h2h_f
        floor_v, ceil_v = _clean_num(row.get("floor")), _clean_num(row.get("ceiling"))
        floor_v = floor_v * env_f * h2h_f if floor_v is not None else None
        ceil_v = ceil_v * env_f * h2h_f if ceil_v is not None else None
        # A player on a bye or ruled out scores nothing this week. His next-game number is kept for reference, but
        # the PROJ every ranking and sentence reads is zero, so a bye can never look like the best option.
        next_proj = proj
        if on_bye or _clean_num(row.get("injury_status")) in decision.WONT_PLAY:
            proj, floor_v, ceil_v = 0.0, 0.0, 0.0
        usage = context.usage_trend(bundle["wk"], pid, pos)
        spread = (ceil_v - floor_v) if (floor_v is not None and ceil_v is not None) else None
        results.append({
            "base_proj": base_proj, "environment": {"factor": env_f, "notes": env_notes, "game": ctx},
            "head_to_head": h2h,
            "usage": usage, "cv": (spread / proj if spread is not None and proj else None),
            "player_id": pid, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "PVS": row.get("PVS"), "FORM": row.get("FORM"), "fpts_per_game": row.get("fpts_per_game"),
            "opponent": None if on_bye else opp, "matchup_tag": matchup_tag, "matchup_factor": matchup_factor, "PROJ": proj,
            "next_game_proj": next_proj if proj == 0.0 and next_proj else None,
            "week": slate_week if on_bye else wk_no, "on_bye": on_bye,
            "floor": floor_v, "ceiling": ceil_v,
            "snap_pct": _clean_num(row.get("snap_pct")), "redzone_touches": _clean_num(row.get("redzone_touches")),
            "injury_status": _clean_num(row.get("injury_status")),
            "injury_body_part": _clean_num(row.get("injury_body_part")),
            "injury_factor": injury_factor, "injury_sample_n": injury_sample_n,
            # "Gone dark" signal (engine/board.py) — exactly the kind of
            # thing a real Start/Sit call needs to know: comparing two
            # players' PROJ without surfacing that one of them hasn't
            # actually played in 11 weeks is a real gap, not a cosmetic one.
            "weeks_since_played": _clean_num(row.get("weeks_since_played")),
            "last_active_week": _clean_num(row.get("last_active_week")),
        })

    if mode not in ("balanced", "safe", "upside"):
        mode = "balanced"
    valid = [r for r in results if "error" not in r]
    for r in valid:
        r["rank_value"] = context.rank_value(r["PROJ"], r["floor"], r["ceiling"], mode)
        r["reasons"] = context.build_reasons(r)
    chart = None
    try:
        chart = _attach_decisions(valid, bundle, get_board, scoring, mode)
    except Exception as e:
        print(f"[startsit] decision layer skipped: {e}")
    _apply_recommendation_tiers(valid)
    summary = None
    if valid:
        best = max(valid, key=lambda r: r["rank_value"])
        for r in results:
            r["recommended"] = ("error" not in r) and (r["player_id"] == best["player_id"])
        summary = context.comparison_reason(best, [r for r in valid if r is not best], mode)
    call = None
    if chart and len(valid) >= 2:
        call = decision.verdict(valid, mode)
        if call:
            for r in results:
                r["recommended"] = ("error" not in r) and (r["player_id"] == call["pick"])
    if call and chart:
        call["correlated"] = bool(chart.get("correlated"))
    if not keep_samples:
        for r in valid:
            r.get("outcomes", {}).pop("_samples", None)
    return {"season": bundle["season"], "mode": mode, "summary": summary, "players": results,
            "decision": call, "chart": chart}


def _attach_decisions(valid, bundle, get_board, scoring, mode):
    """Outcome range, rating and flags on each start_sit row (engine/decision.py).
    Re-ranks rows by the chosen win condition. Returns the shared chart axis
    and each player's density curve."""
    from .scoring import ScoringSettings
    pool, _ = waivers.cached_pool(scoring, bundle)
    snaps = waivers.weekly_snaps(bundle["season"])
    pbp = bundle["pbp"]
    xfp_wk = waivers.xfp_by_player(pbp, scoring)
    goal_line = waivers.goal_line_share(pbp)
    rz = pbp[(pbp["play_type"] == "run") & pbp["rusher_player_id"].notna() & (pbp["yardline_100"].fillna(100) <= 20)]
    rz_by = rz.groupby(["rusher_player_id", "week"]).size()
    factors = bundle["defense_factors"]
    s = ScoringSettings.from_dict(scoring) if scoring else ScoringSettings.from_preset("ppr")
    wk = bundle["wk"]
    for r in valid:
        pid, pos = r["player_id"], r["position"]
        b = get_board(pos)
        q = b[(b["games"] >= 3) & (b["fpts_per_game"] >= 5)]["cv"].dropna()
        pos_cv = float(q.median()) if len(q) else 0.55
        row = b.loc[pid] if pid in b.index else None
        games = int(row["games"]) if row is not None else 0
        career = history.weighted_career(pos, scoring, bundle["season"], pid) if history.available() else None
        hist_h = float(career["h"]) if career else 0.0
        cv_all = history.blend_cv(None if row is None else row.get("cv"), games,
                                  career["cv"] if career else None, hist_h)
        cv = decision.shrunk_cv(cv_all, games + hist_h, pos_cv)
        seed = int("".join(ch for ch in pid if ch.isdigit()) or 0) % (2 ** 32)
        pp = play_prob.play_probability(pos, r.get("injury_status"), r.get("injury_report"))
        r["play_chance"] = pp
        r["outcomes"] = decision.outcomes(r["PROJ"], cv, seed, pp["p_play"] if pp else 1.0)
        if r.get("injury_status") in decision.WONT_PLAY:
            r["outcomes"] = decision.ruled_out()
        if r.get("on_bye"):
            r["outcomes"] = decision.ruled_out()
            r["outcomes"]["reason"] = "bye"
        ctx = (r.get("environment") or {}).get("game")
        opp = r.get("opponent") or (ctx or {}).get("opponent")
        split = decision.script_split(bundle["pbp"], pid, r.get("recent_team"),
                                      weeks=set(wk.loc[wk["player_id"] == pid, "week"].astype(int)))
        mrank = decision.defense_rank(pos, opp, factors) if opp else (None, None)
        prow = pool.loc[pid] if pid in pool.index else None
        usage_pct = float(prow["usage_score"]) if prow is not None else None
        xfp = None
        if prow is not None and pd.notna(prow.get("xfp_pg")):
            xfp = {"xfp_pg": float(prow["xfp_pg"]), "diff": float(prow["xfp_diff"])}
        g = wk[wk["player_id"] == pid]
        td_pts = ((g["rushing_tds"].fillna(0) * s.rush_td + g["receiving_tds"].fillna(0) * s.rec_td).sum()
                  + (g["passing_tds"].fillna(0) * s.pass_td).sum())
        tot = g["fantasy_points_ppr"].sum() if scoring is None else None
        if tot is None:
            from .scoring import compute_fantasy_points
            tot = compute_fantasy_points(g, s).sum() if len(g) else 0
        td_share = (100 * td_pts / tot) if tot and tot > 0 and len(g) >= 3 else None
        sw = sorted((snaps.get(pid) or {}).items())
        snap_trend = decision.snap_trend([v for _, v in sw])
        mine_x = xfp_wk[xfp_wk["player_id"] == pid]
        recent = decision.recent_usage(
            pid, pos, wk, snaps.get(pid) or {}, dict(zip(mine_x["week"].astype(int), mine_x["xfp"])),
            {int(w): int(n) for (_, w), n in rz_by[rz_by.index.get_level_values(0) == pid].items()})
        rate, comps = decision.rating(r, usage_pct, ctx, split, mrank, recent)
        if r["outcomes"].get("out"):   # on a bye or ruled out: he scores 0, so the rating must not read as a start
            rate = 0.0
        mg, mb = decision.matchup_flags(pos, opp, factors) if opp else ([], [])
        pg, pb = decision.player_flags(r, ctx, split, xfp, td_share, snap_trend)
        if r.get("on_bye"):
            pb = ["On a bye this week: he scores 0"] + list(pb)
        def _f(v, nd=1):
            return None if v is None or pd.isna(v) else round(float(v), nd)
        r["decision"] = {
            "rating": rate, "components": comps, "flags_good": mg + pg, "flags_bad": mb + pb,
            "script_split": split, "defense_rank": mrank[0], "defense_count": mrank[1], "opponent": opp,
            "xfp_pg": xfp["xfp_pg"] if xfp else None, "xfp_diff": xfp["diff"] if xfp else None,
            "snap_pct": _f(prow.get("snap_pct") * 100 if prow is not None and pd.notna(prow.get("snap_pct")) and prow.get("snap_pct") <= 1 else (prow.get("snap_pct") if prow is not None else None), 0),
            "target_share": _f(prow.get("target_share")) if prow is not None else None,
            "hvt_pg": _f(prow.get("hvt_pg")) if prow is not None else None,
            "td_share": _f(td_share, 0), "snap_trend": _f(snap_trend, 0),
            "recent": recent, "goal_line_share": round(goal_line.get(pid, 0.0) * 100),
        }
        r["rank_value"] = decision.mode_value(r["outcomes"], mode)
    # Players on one offence (or facing each other) move together: rearrange the
    # draws so head-to-head odds and lineup totals see that (engine/correlation.py).
    seed = int("".join(ch for ch in "".join(sorted(r["player_id"] for r in valid)) if ch.isdigit()) or 0) % (2 ** 32)
    try:
        correlated = correlation.apply(valid, wk, seed)
    except Exception as e:
        print(f"[startsit] correlation skipped: {e}")
        correlated = False
    lo = 0.0
    hi = max(30.0, max(float(np.percentile(r["outcomes"]["_samples"], 97)) for r in valid))
    for r in valid:
        r["outcomes"]["curve"] = decision.curve(r["outcomes"]["_samples"], lo, hi)
    return {"lo": lo, "hi": round(hi, 1), "bins": 40, "correlated": correlated}


# Every lineup-slot label that takes more than one of RB/WR/TE and no QB
# (superflex is a different question): FLEX, WRRB_FLEX, REC_FLEX, RB/WR/TE...
FLEX_SLOT_LABELS = frozenset(s for s, allowed in lineup_layer.ELIGIBLE.items()
                             if len(allowed) > 1 and "QB" not in allowed)


def start_sit_suggestions_from_roster(roster_players, season=None, scoring=None, limit=3):
    """The N most actionable real start/sit calls sitting on your own
    current roster right now — `roster_players` is my_team()'s or
    my_team_espn()'s `["my_team"]["players"]` list (same shape either
    way, so this works for both platforms without caring which one).

    For each real position where you have both a starter and a bench
    option, compares your weakest real starter's PROJ against your
    strongest real bench alternative AT THE SAME POSITION — a same-
    position swap is always a real, valid move regardless of which
    specific slot (dedicated or FLEX) the starter happens to occupy.

    Separately, ALSO runs one real FLEX-specific comparison: whoever's
    actually sitting in a FLEX slot right now vs. the single best real
    bench option across all of RB/WR/TE (not just the FLEX starter's own
    position) — a FLEX slot has no same-position constraint, so this is
    the one real place a genuine cross-position comparison is valid.
    A dedicated RB/WR/TE slot still never gets compared against a
    different position's bench player — swapping a dedicated RB slot for
    a bench WR isn't a real, valid move without a lineup-optimizer-level
    rebalance this app doesn't do.

    Ranked by the real PROJ gap: a positive gap (bench beats starter) is
    a genuine "you might want to swap this" call, sorted most-actionable
    first; if every starter already correctly beats their bench, the
    smallest (least negative) gaps sort first instead — still the real
    calls most worth a second look, not a made-up filler set.

    Each returned suggestion re-runs the exact real start_sit() compare
    for that starter/bench pair (not a stripped-down roster row) — same
    floor/ceiling/snap/matchup/tier/confidence shape the manual compare
    tool already returns, so the frontend renders it with the exact same
    real components, no separate/duplicated code path."""
    # Nobody weighs starting a player on a bye or ruled out, so neither can be one side of a "closest call".
    # (A starter on a bye needs replacing, which the Start/Sit lineup panel flags on its own.)
    roster_players = [p for p in roster_players
                      if not p.get("on_bye") and not p.get("unresolved") and p.get("injury_status") not in decision.WONT_PLAY]
    by_pos = {}
    for p in roster_players:
        if p.get("position"):
            by_pos.setdefault(p["position"], []).append(p)

    candidates = []
    for pos, group in by_pos.items():
        starters = [p for p in group if p.get("is_starter") and p.get("PROJ") is not None]
        bench = [p for p in group if not p.get("is_starter") and p.get("PROJ") is not None]
        if not starters or not bench:
            continue
        weakest_starter = min(starters, key=lambda p: p["PROJ"])
        best_bench = max(bench, key=lambda p: p["PROJ"])
        gap = round(best_bench["PROJ"] - weakest_starter["PROJ"], 1)
        candidates.append((pos, weakest_starter, best_bench, gap))

    # Any RB/WR/TE flex label, not just Sleeper's "FLEX": Sleeper also has
    # WRRB_FLEX/REC_FLEX and an ESPN team's flex slot arrives as "RB/WR/TE"
    # (or "RB/WR", "WR/TE"), which this used to skip entirely. The bench
    # option must be legal in that starter's own slot.
    flex_starters = [p for p in roster_players
                     if p.get("is_starter") and p.get("slot") in FLEX_SLOT_LABELS and p.get("PROJ") is not None]
    if flex_starters:
        weakest_flex = min(flex_starters, key=lambda p: p["PROJ"])
        flex_bench = [p for p in roster_players
                      if not p.get("is_starter") and p.get("PROJ") is not None
                      and lineup_layer.eligible(weakest_flex["slot"], p.get("position"))]
        if flex_bench:
            best_flex_bench = max(flex_bench, key=lambda p: p["PROJ"])
            gap = round(best_flex_bench["PROJ"] - weakest_flex["PROJ"], 1)
            candidates.append(("FLEX", weakest_flex, best_flex_bench, gap))

    candidates.sort(key=lambda c: -c[3])

    suggestions = []
    for pos, starter, bench, gap in candidates[:limit]:
        cmp = start_sit([starter["player_id"], bench["player_id"]], season=season, scoring=scoring)
        suggestions.append({"position": pos, "gap": gap, "players": cmp["players"]})
    return suggestions


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
                # This is the exact original real-world case that started
                # this whole fix: a trade offered right after a fresh
                # season starts, with real, established starters still
                # showing "not enough data" purely from the ranked-list
                # bar, not because there's no real signal at all. Same
                # min_games=0 fallback as My Team/Start-Sit/Trade picker.
                raw_board = build_board(pos, season=bundle["season"], min_games=0, scoring=scoring)
                if pid not in raw_board.index:
                    players.append({"player_id": pid, "error": "not enough data this season"})
                    continue
                board = raw_board
            row = board.loc[pid].to_dict()
            value = float(rest_of_season_value(board.loc[[pid]], pos, bundle=bundle, scoring=scoring).iloc[0])
            total += value
            players.append({
                "player_id": pid, "position": pos,
                "player_display_name": row.get("player_display_name"),
                "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
                "SCORE": row.get("SCORE"), "PVS": row.get("PVS"), "value": round(value, 1),
                "injury_status": _clean_num(row.get("injury_status")),
                "injury_body_part": _clean_num(row.get("injury_body_part")),
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


def _row_range(row, proj, pos, status, report, pid, pos_cv=0.55):
    """{floor, ceiling, p_play} for a My Team row: the 10th/90th percentile of his score around `proj` (the same
    outcome model Start/Sit uses), and the chance he plays when he's Questionable/Doubtful. `proj` already includes
    the play chance, so it is divided back out to get his score if he plays. {} for someone ruled out or at zero."""
    if status in decision.WONT_PLAY or not proj or proj <= 0:
        return {}
    pp = play_prob.play_probability(pos, status, report)
    p_play = pp["p_play"] if pp else 1.0
    cv = decision.shrunk_cv(row.get("cv"), row.get("games"), pos_cv)
    seed = int("".join(ch for ch in str(pid) if ch.isdigit()) or 0) % (2 ** 32)
    o = decision.outcomes(proj / p_play if p_play else proj, cv, seed, p_play)
    return {"floor": o["p10"], "ceiling": o["p90"], "p_play": round(p_play, 2) if pp else None}


def _roster_players(raw_ids, bundle, get_board, scoring, crosswalk=None, starters=None,
                     slot_labels=None, def_board=None, k_board=None, k_team_baseline=None,
                     rank_baselines=None, resolve_unscored=None, week=None, fragility=None, actuals=None):
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
                # Sleeper has no record of him (even after a refresh): keep a row so the roster count is right and
                # the owner can see a slot is unrecognised, rather than a player silently vanishing.
                return {"player_id": raw_id, "position": "?", "player_display_name": f"Unknown player ({raw_id})",
                        "recent_team": None, "headshot_url": None, "SCORE": None, "FORM": None, "fpts_per_game": None,
                        "PROJ": 0.0, "injury_status": None, "injury_body_part": None, "injury_factor": None,
                        "injury_sample_n": None, "is_starter": is_starter, "slot": slot, "unresolved": True}
            if unscored["position"] == "DEF":
                def_row = _defense_row(raw_id, unscored, def_board, is_starter, slot,
                                        bundle=bundle, fragility=fragility, week=week)
                if def_row:
                    return def_row
            elif unscored["position"] == "K":
                k_row = _kicker_row(gsis_id, unscored, k_board, k_team_baseline, is_starter, slot,
                                        bundle=bundle, week=week)
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
                "injury_status": None, "injury_body_part": None, "injury_factor": None, "injury_sample_n": None,
                "is_starter": is_starter, "slot": slot,
            }
        board = get_board(pos)
        if gsis_id not in board.index:
            # Doesn't clear this position's RANKED-LIST bar (build_board's
            # default min_games=2 — real early in a season, before almost
            # anyone has 2 games yet). That bar exists so a fluky 1-game
            # sample doesn't look like a ranked #1 among strangers on Big
            # Board/Waivers — it has no business making an established
            # player on YOUR OWN roster vanish. min_games isn't part of
            # build_board's cache key (see its docstring), so asking for
            # the same position/season/scoring at min_games=0 reuses the
            # already-computed board — this costs nothing extra.
            raw_board = build_board(pos, season=bundle["season"], min_games=0, scoring=scoring)
            if gsis_id not in raw_board.index:
                return None  # genuinely no real games logged this season at all
            board = raw_board
        row = board.loc[gsis_id].to_dict()
        match_info = {}
        proj, (injury_factor, injury_sample_n) = _opponent_adjusted_proj_full(board, gsis_id, pos, bundle, scoring, week=week, info=match_info)
        return {
            **match_info,
            "player_id": gsis_id, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "PVS": row.get("PVS"), "FORM": row.get("FORM"),
            "fpts_per_game": row.get("fpts_per_game"), "PROJ": proj,
            **_row_range(row, proj, pos, row.get("injury_status"), row.get("injury_report"), gsis_id),
            "injury_status": _clean_num(row.get("injury_status")),
            "injury_body_part": _clean_num(row.get("injury_body_part")),
            "injury_factor": injury_factor, "injury_sample_n": injury_sample_n,
            "is_starter": is_starter, "slot": slot,
            # Same "gone dark" signal as start_sit() above — My Team is
            # the surface where this matters most: a started player who
            # hasn't actually played in weeks is exactly the kind of thing
            # that should be visible without having to click into them.
            "weeks_since_played": _clean_num(row.get("weeks_since_played")),
            "last_active_week": _clean_num(row.get("last_active_week")),
            "on_bye": _team_on_bye(bundle, row.get("recent_team"), week),
        }

    def settle(row):
        """Swap in the real score once his game has been played."""
        if row is None or actuals is None:
            return row
        pts = actuals.points(row)
        if pts is None:
            return row
        return {**{k: v for k, v in row.items() if k not in ("floor", "ceiling", "p_play")}, "PROJ": pts, "final": True}

    starter_set = set(starters)
    rows, total = [], 0.0
    for raw_id, slot in zip(starters, slot_labels):
        row = settle(build_row(raw_id, True, slot))
        if row:
            rows.append(row)
            total += row["PROJ"]

    bench_rows = [r for r in (settle(build_row(raw_id, False, None)) for raw_id in raw_ids if raw_id not in starter_set) if r]
    bench_rows.sort(key=lambda r: -r["PROJ"])
    rows.extend(bench_rows)

    return rows, round(total, 1)


def _team_total(raw_ids, bundle, get_board, scoring, crosswalk=None, starters=None,
                 def_board=None, k_board=None, k_team_baseline=None, rank_baselines=None, week=None,
                 fragility=None, actuals=None):
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
                    done = actuals.defense(raw_id) if actuals else None
                    if done is not None:
                        total += done
                        continue
                    total += _defense_proj(def_row, def_board, bundle, raw_id, week)
                    continue
            if k_board is not None and gsis_id is not None and gsis_id in k_board.index:
                k_row = k_board.loc[gsis_id]
                done = actuals.kicker(gsis_id) if actuals else None
                if done is not None:
                    total += done
                    continue
                total += _kicker_proj(_row_rate(k_row), _pool_rate(k_board), bundle,
                                      (sleeper.resolve_unscored_player(raw_id) or {}).get("recent_team"), week)
                continue
            if k_team_baseline is not None or rank_baselines is not None:
                unscored = sleeper.resolve_unscored_player(raw_id)
                if unscored and unscored["position"] == "K" and k_team_baseline is not None:
                    recent_team = unscored.get("recent_team")
                    team = (defense_scoring.SLEEPER_TO_NFLVERSE_TEAM.get(recent_team, recent_team)
                            if recent_team is not None else None)
                    if team in k_team_baseline.index:
                        total += _kicker_proj(float(k_team_baseline.loc[team]), float(k_team_baseline.mean()),
                                              bundle, recent_team, week)
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
            # Same real early-season gap as _roster_players.build_row
            # above — don't let a starter silently contribute 0 to the
            # team total just because they haven't cleared build_board's
            # ranked-list min_games bar yet this season.
            raw_board = build_board(pos, season=bundle["season"], min_games=0, scoring=scoring)
            if gsis_id not in raw_board.index:
                continue
            board = raw_board
        done = actuals.skill(gsis_id, board.loc[gsis_id].get("recent_team")) if actuals else None
        total += done if done is not None else _opponent_adjusted_proj(board, gsis_id, pos, bundle, scoring, week=week)
    return round(total, 1)


def league_all_player_names(league_id, season=None, scoring=None):
    """Every rostered player across the whole league, name-only — a cheap
    lookup (no valuation) for 'is this headline about someone in my league
    at all', which is what the League News tab's featured sort needs.

    Reads the name straight off the real weekly stats table rather than
    requiring board membership — a real, if early-season-thin, name
    shouldn't be gated by build_board's ranked-list min_games/min_volume
    bar, which exists to keep a one-game fluke off a top-N list, not to
    decide who's a real enough person to match a headline against."""
    snap = sleeper.league_snapshot(league_id)
    bundle = load_bundle(season)
    cols = [c for c in ("player_display_name", "recent_team", "headshot_url") if c in bundle["wk"].columns]
    last = bundle["wk"].sort_values("week").groupby("player_id")[cols].last()
    names, teams = last["player_display_name"].to_dict(), last["recent_team"].to_dict()
    shots = last["headshot_url"].to_dict() if "headshot_url" in last.columns else {}
    seen = {}
    for team in snap["teams"]:
        for pid in team["player_ids"]:
            if pid in seen:
                continue
            name = names.get(pid)
            if name:
                seen[pid] = {"player_id": pid, "player_display_name": name, "recent_team": teams.get(pid),
                             "headshot_url": shots.get(pid)}
    return list(seen.values())


_NEWS_ROSTER_CACHE = {}
NEWS_ROSTER_TTL = 60


def team_profile(code, scoring=None, season=None, projected=10, lite=False):
    """engine/team_page.build on the live data, plus next-game projections (matchup-adjusted, the same numbers
    Start/Sit shows) for the team's `projected` best fantasy players."""
    from . import team_page
    bundle = load_bundle(season)
    page = team_page.build(code, bundle["schedule"], bundle["wk"])
    if page is None:
        return None
    if lite:                   # the header strip needs only the record and the games
        return page
    nxt = page["next_game"]
    try:                       # how every player is listed (Questionable, Out, IR, PUP...), not just the projected few
        listed = sleeper.live_injury_statuses()
        for p in page["players"]:
            p["injury_status"] = listed.get(p["player_id"])
    except Exception as e:
        print(f"[team] injury statuses for {code} unavailable: {e}")
    top = page["players"][:projected]
    if nxt and top:
        try:
            res = start_sit([p["player_id"] for p in top], opponents={p["player_id"]: nxt["opponent"] for p in top},
                            season=season, scoring=scoring)
            proj = {r["player_id"]: r for r in res.get("players", []) if not r.get("error")}
            for p in top:
                r = proj.get(p["player_id"])
                if r:
                    p["proj"] = None if r.get("on_bye") or (r.get("outcomes") or {}).get("out") else round(float(r["PROJ"]), 1)
                    p["injury_status"] = r.get("injury_status")
        except Exception as e:
            print(f"[team] projections for {code} unavailable: {e}")
    return page


def matchup_profile(home_abbr, away_abbr, market=None, season=None):
    """Both teams side by side for the game dashboard: record, scoring and allowed per game, passing and rushing
    yards, the last results, their best fantasy players, and Lineup Lab's own pick (engine/game_predict.py)."""
    from . import game_predict, team_page
    bundle = load_bundle(season)

    def side(abbr):
        page = team_page.build(abbr, bundle["schedule"], bundle["wk"])
        if page is None:
            return None
        st = page["stats"]
        played = [g for g in page["games"] if g["result"]][-5:]
        return {"abbr": abbr, "record": page["record"]["text"], "games": st["games"], "pf_pg": st["points_for_pg"],
                "pa_pg": st["points_against_pg"], "pass_yds_pg": st["pass_yds_pg"], "rush_yds_pg": st["rush_yds_pg"],
                "recent": [{"week": g["week"], "opponent": g["opponent"], "home": g["home"], "result": g["result"],
                            "team_score": g["team_score"], "opp_score": g["opp_score"]} for g in played],
                "top_players": [{k: p.get(k) for k in ("player_id", "name", "position", "ppg", "headshot_url")} for p in page["players"][:4]]}
    h, a = side(home_abbr), side(away_abbr)
    if h is None or a is None:
        return None
    pred = game_predict.predict({"games": h["games"], "pf_pg": h["pf_pg"], "pa_pg": h["pa_pg"]} if h["games"] else None,
                                {"games": a["games"], "pf_pg": a["pf_pg"], "pa_pg": a["pa_pg"]} if a["games"] else None, market)
    return {"home": h, "away": a, "prediction": pred}


def team_player_roster(team, season=None):
    """Names, teams and headshots of the players whose latest game was with NFL `team`: lets the favorite-team
    news tab say which player a story is about."""
    wk = load_bundle(season)["wk"]
    cols = [c for c in ("player_display_name", "recent_team", "headshot_url") if c in wk.columns]
    last = wk.sort_values("week").groupby("player_id")[cols].last()
    last = last[last["recent_team"] == team]
    return [{"player_id": pid, "player_display_name": r["player_display_name"], "recent_team": r["recent_team"],
             "headshot_url": r["headshot_url"] if "headshot_url" in last.columns else None}
            for pid, r in last.iterrows()]


def news_rosters(league_id, roster_id, week=None, season=None):
    """My roster and this week's head-to-head opponent's, as just names and NFL teams: all the
    news filter needs. my_team() answers the same question but also projects every player and
    runs the matchup pipeline, which the Team and Opponent news tabs paid for on every tab
    switch. Same week and opponent rules as my_team(); cached briefly per (league, roster, week)."""
    key = (league_id, roster_id, week)
    hit = _NEWS_ROSTER_CACHE.get(key)
    if hit and time.time() - hit[0] < NEWS_ROSTER_TTL:
        return hit[1]
    snap = sleeper.league_snapshot(league_id)
    by_roster = {t["roster_id"]: t for t in snap["teams"]}
    mine = by_roster.get(roster_id)
    if mine is None:
        raise ValueError(f"roster_id {roster_id} not found in league {league_id}")
    state = sleeper.get_nfl_state()
    if week is None:
        week = state.get("week") if state.get("season_type") in ("regular", "post") and state.get("week") else 1
    opp = None
    try:
        for pair in sleeper.matchups_for_week(league_id, week):
            if roster_id in pair["roster_ids"]:
                others = [r for r in pair["roster_ids"] if r != roster_id]
                opp = by_roster.get(others[0]) if others else None
                break
    except Exception:
        opp = None
    wk = load_bundle(season)["wk"]
    cols = [c for c in ("player_display_name", "recent_team", "headshot_url") if c in wk.columns]
    last = wk.sort_values("week").groupby("player_id")[cols].last()

    def card(t):
        return {"team_name": t["team_name"],
                "players": [{"player_id": pid, "player_display_name": last.at[pid, "player_display_name"],
                             "recent_team": last.at[pid, "recent_team"],
                             "headshot_url": last.at[pid, "headshot_url"] if "headshot_url" in last.columns else None}
                            for pid in t["player_ids"] if pid in last.index]}
    out = {"nfl_week": week, "my_team": card(mine), "opponent": card(opp) if opp else None}
    _NEWS_ROSTER_CACHE[key] = (time.time(), out)
    return out


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
    fragility = _offense_fragility(bundle, league_id)
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
                special_row = _defense_row(raw_id, unscored, def_board, is_starter=None, slot=None,
                                            bundle=bundle, fragility=fragility)
            elif unscored["position"] == "K":
                special_row = _kicker_row(gsis_id, unscored, k_board, k_team_baseline, is_starter=None, slot=None,
                                           bundle=bundle)
            elif unscored["position"] in role_baseline.RANK_POSITIONS:
                special_row = _role_rank_row(raw_id, unscored, rank_baselines, is_starter=None, slot=None)
            if special_row:
                # .get(), not special_row[k]: DEF/K/role-rank rows don't
                # carry injury_body_part/injury_factor/injury_sample_n at
                # all (no board row to source them from) — bracket access
                # here would KeyError on exactly those real rosters, the
                # same real bug already caught once for weeks_since_played
                # on this exact class of fallback row.
                players.append({k: special_row.get(k) for k in
                                 ("player_id", "position", "player_display_name", "recent_team",
                                  "headshot_url", "SCORE", "PVS", "PROJ", "injury_status",
                                  "injury_body_part", "injury_factor", "injury_sample_n")})
                continue
            players.append({
                "player_id": raw_id, "position": unscored["position"],
                "player_display_name": unscored["player_display_name"],
                "recent_team": unscored["recent_team"], "headshot_url": unscored.get("headshot_url"),
                "SCORE": None, "PROJ": 0.0, "injury_status": None,
                "injury_body_part": None, "injury_factor": None, "injury_sample_n": None,
            })
            continue
        board = get_board(pos)
        if gsis_id not in board.index:
            # Same real early-season gap fixed in _roster_players/
            # _team_total (see their comments for the full story — an
            # established starter with a real, if sparse, sample was
            # silently vanishing before clearing build_board's ranked-list
            # min_games bar) — this fifth allowlist had the identical
            # `continue`/`return None` shape and had never gotten the same
            # fix, so a real starter could vanish from the Trade tab's own
            # roster picker too.
            raw_board = build_board(pos, season=bundle["season"], min_games=0, scoring=scoring)
            if gsis_id not in raw_board.index:
                continue  # genuinely no real games logged this season at all
            board = raw_board
        row = board.loc[gsis_id].to_dict()
        proj, (injury_factor, injury_sample_n) = _opponent_adjusted_proj_full(board, gsis_id, pos, bundle, scoring)
        players.append({
            "player_id": gsis_id, "position": pos,
            "player_display_name": row.get("player_display_name"),
            "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
            "SCORE": row.get("SCORE"), "PVS": row.get("PVS"), "PROJ": proj,
            "injury_status": _clean_num(row.get("injury_status")),
            "injury_body_part": _clean_num(row.get("injury_body_part")),
            "injury_factor": injury_factor, "injury_sample_n": injury_sample_n,
            # Same "gone dark" signal as start_sit()/_roster_players() —
            # a fourth allowlist that had the same gap (see this app's
            # memory notes on why this needs adding deliberately in each
            # one): the Trade tab's roster picker is exactly where you'd
            # want to know a player you're about to offer/request hasn't
            # actually played in months.
            "weeks_since_played": _clean_num(row.get("weeks_since_played")),
            "last_active_week": _clean_num(row.get("last_active_week")),
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
    weather.prefetch(bundle["schedule"], week)       # every game's forecast at once, so the per-player lookups are instant

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
    fragility = _offense_fragility(bundle, league_id)
    k_board = _kicker_board(bundle, league_id)
    k_team_baseline = _kicker_team_baseline(bundle, league_id)
    rank_baselines = _role_rank_baselines(bundle, scoring)
    actuals = _Actuals(bundle, scoring, week, league_id)
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
                                          rank_baselines=rank_baselines, week=week, fragility=fragility,
                                          actuals=actuals)
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
                                       rank_baselines=rank_baselines, week=week, fragility=fragility,
                                       actuals=actuals),
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
    weather.prefetch(bundle["schedule"], week)
    def_board = _defense_board(bundle)
    fragility = _offense_fragility(bundle)
    k_board = _kicker_board(bundle)
    k_team_baseline = _kicker_team_baseline(bundle)
    rank_baselines = _role_rank_baselines(bundle, scoring)
    crosswalk = espn_layer.id_crosswalk()
    resolve_unscored = espn_layer.build_unscored_resolver(league)
    actuals = _Actuals(bundle, scoring, week)

    def team_card(t):
        raw_ids, starters, slot_labels = espn_layer.roster_lineup(t)
        players, total = _roster_players(raw_ids, bundle, get_board, scoring,
                                          crosswalk=crosswalk, starters=starters, slot_labels=slot_labels,
                                          def_board=def_board, k_board=k_board, k_team_baseline=k_team_baseline,
                                          rank_baselines=rank_baselines, resolve_unscored=resolve_unscored, week=week,
                                          fragility=fragility, actuals=actuals)
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
    fragility = _offense_fragility(bundle)
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
                               rank_baselines=rank_baselines, resolve_unscored=resolve_unscored,
                               fragility=fragility)
    # .get(), not r[k]: DEF/K/role-rank-fallback rows (_defense_row/
    # _kicker_row/_role_rank_row) don't carry weeks_since_played/
    # last_active_week at all (no board row to source them from) —
    # bracket access here would KeyError on exactly those real rosters.
    players = [{k: r.get(k) for k in ("player_id", "position", "player_display_name", "recent_team",
                                       "headshot_url", "SCORE", "PVS", "PROJ", "injury_status",
                                       "injury_body_part", "injury_factor", "injury_sample_n",
                                       "weeks_since_played", "last_active_week")} for r in rows]
    players.sort(key=lambda p: -(p["PROJ"] or 0))
    return {"roster_id": roster_id, "team_name": team.team_name,
            "avatar_url": team.logo_url or None, "owner": espn_layer.owner_name(team), "players": players}


# Superflex slot labels. Any of QB/RB/WR/TE may legally start there, but in
# practice managers start a quarterback, so each one counts as a full extra QB
# need — without this a superflex league reads as needing exactly one QB and
# every QB trade gets undervalued. Neither label is confirmed by Sleeper's
# published API docs or by the real leagues cached in data_cache/ (all standard
# 1-QB): "SUPER_FLEX" is the commonly used Sleeper value and "OP" is ESPN's
# lineup label. A label outside this set still falls through to ignored, same
# as before, so a wrong guess here costs nothing.
SUPERFLEX_SLOTS = {"SUPER_FLEX", "OP"}

# ESPN's flex labels (espn_api POSITION_MAP; see espn.roster_positions).
# "RB/WR/TE" is an ordinary FLEX. The two-position ones split their one
# slot evenly between the two positions allowed in it.
# "TQB" (team QB) is deliberately NOT counted as a QB need: that slot
# holds a whole team's QB unit, which the roster carries as position
# "TQB", not "QB" — so counting it would make every TQB league look one
# quarterback short and push individual-QB trades that can't fill it.
FLEX_SLOTS = {"FLEX", "RB/WR/TE"}
HALF_FLEX_SLOTS = {"RB/WR": ("RB", "WR"), "WR/TE": ("WR", "TE")}


def _position_needs(roster_positions):
    """Starting-slot requirements per position, with FLEX spread evenly
    across RB/WR/TE (a simplification — real flex value skews RB/WR over
    TE, but this is a reasonable v1), ESPN's two-position flexes split
    between their two positions, and superflex counted as a QB."""
    base = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}
    flex = 0
    for slot in roster_positions or []:
        if slot in base:
            base[slot] += 1
        elif slot in FLEX_SLOTS:
            flex += 1
        elif slot in HALF_FLEX_SLOTS:
            for pos in HALF_FLEX_SLOTS[slot]:
                base[pos] += 0.5
        elif slot in SUPERFLEX_SLOTS:
            base["QB"] += 1
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
    if lopsided_value and not wins_value and real_fit and not good_fit:
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
    runs = []
    if is_complete:
        my_picks_recap = sorted(
            [p for p in picks_made if p["roster_id"] == my_roster_id],
            key=lambda p: p["pick_no"] or 0,
        )
    else:
        bundle = load_bundle(season)
        runs = draft_runs.run_positions(sorted(picks_made, key=lambda p: p["pick_no"] or 0))
        for pos in POSITIONS:
            board = build_board(pos, season=season, scoring=scoring)
            board = board[~board.index.isin(drafted_gsis)]
            mult = _need_multiplier(pos, my_filled.get(pos, 0), needs) if my_roster_id is not None else 1.0
            run_mult = draft_runs.RUN_MULTIPLIER if pos in runs else 1.0
            for pid, row in board.head(40).iterrows():
                best_available.append({
                    "player_id": pid, "position": pos,
                    "player_display_name": row.get("player_display_name"),
                    "recent_team": row.get("recent_team"), "headshot_url": row.get("headshot_url"),
                    "SCORE": row.get("SCORE"), "PVS": row.get("PVS"),
                    # pandas-stubs 1.5.3.230321 mistypes Series.get(key, default)'s
                    # return as `Dtype` unconditionally — it's actually a scalar
                    # value here, so this is a real pyright false positive.
                    "ADJ_SCORE": round(float(row.get("SCORE", 0)) * mult * run_mult, 1),  # type: ignore[reportArgumentType]
                    "fpts_per_game": row.get("fpts_per_game"), "need_multiplier": mult,
                    "run_multiplier": run_mult,
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
        "position_runs": runs,
        "supported_format": draft.get("type") == "snake",
    }


def _next_unplayed_week(schedule):
    """First regular-season week with a game still to play, or None."""
    s = schedule[schedule["game_type"] == "REG"] if "game_type" in schedule.columns else schedule
    if "home_score" in s.columns:
        s = s[s["home_score"].isna()]
    return int(s["week"].min()) if len(s) else None


def _league_pvs(scoring, shape):
    """{player_id: PVS} for this league's team count, slots and scoring, so the
    trade value moves with the format (superflex, deep benches, custom points).
    None if the board can't be built; trade_values then falls back to its own
    scale rather than failing the whole analyzer."""
    try:
        from .board import overall_board
        league = {"teams": shape["teams"], "slots": shape["slots"]}
        return overall_board(scoring=scoring, league=league)["PVS"].to_dict()
    except Exception as e:
        print(f"[trade] league PVS unavailable, using fallback values: {e}")
        return None


def _trade_setup(league_id, scoring=None, season=None):
    """Everything the trade engine needs for one Sleeper league: valued
    rosters (with records, weaknesses, usage, byes) and the league context."""
    snap = sleeper.league_snapshot(league_id)
    if scoring is None:
        scoring = snap["scoring"]
    league = sleeper.get_league(league_id)
    roster_positions = league.get("roster_positions") or []
    bundle = load_bundle(season)
    pool, _ = waivers.cached_pool(scoring, bundle)
    raw = sleeper.get_rosters(league_id)
    cw = sleeper.id_crosswalk()
    rostered = {cw.get(str(x)) for r in raw for x in (r.get("players") or [])} - {None}
    shape = trade_engine.league_shape(roster_positions, len(raw))
    values = trade_engine.trade_values(pool, shape, rostered, pvs_by_id=_league_pvs(scoring, shape))

    def _f(v, scale=1.0):
        return None if v is None or pd.isna(v) else round(float(v) * scale, 1)
    usage = {pid: {"xfp_pg": _f(r.get("xfp_pg")), "target_share": _f(r.get("target_share")), "hvt_pg": _f(r.get("hvt_pg"))}
             for pid, r in pool.iterrows()}
    byes = profile.bye_weeks(bundle["schedule"])
    rosters = trade_engine.build_rosters(league_id, pool, values, cw, usage=usage, byes=byes)
    slots = [s for s in roster_positions if s in lineup_layer.ELIGIBLE and s not in ("K", "DEF", "D/ST")]
    trade_engine.annotate(rosters, slots)
    ctx = {"slots": slots, "profile": trade_engine.depth_profile(shape), "teams": shape["teams"],
           "starters": shape["starters"], "week": _next_unplayed_week(bundle["schedule"])}
    return bundle, rosters, ctx


def _public_player(p):
    out = {k: p.get(k) for k in ("player_id", "name", "player_display_name", "position", "recent_team",
                                 "headshot_url", "value", "trade", "tier", "injury_status", "bye")}
    # `value` is projected points per game and `trade` is the 0-100 PVS-based trade value; say so by name
    out.update(schemas.value_fields({"player_display_name": out["name"], "PROJ": p.get("value"), "PVS": p.get("trade")}))
    return out


def _trade_setup_espn(league_id, scoring=None, season=None, year=None, espn_s2=None, swid=None):
    """_trade_setup() for an ESPN league: the same valued rosters, records and
    league context, read from ESPN. Scoring defaults to the league's own."""
    from . import espn as espn_layer

    year = year or espn_layer.resolve_year()
    league = espn_layer.get_league(league_id, year, espn_s2=espn_s2, swid=swid)
    if scoring is None:
        scoring = espn_layer.scoring_from_espn(league)
    roster_positions = espn_layer.roster_positions(league)
    bundle = load_bundle(season)
    pool, _ = waivers.cached_pool(scoring, bundle)
    cw = espn_layer.id_crosswalk()
    rostered = {cw.get(str(p.playerId)) for t in league.teams for p in t.roster} - {None}
    shape = trade_engine.league_shape(roster_positions, len(league.teams))
    values = trade_engine.trade_values(pool, shape, rostered, pvs_by_id=_league_pvs(scoring, shape))

    def _f(v, scale=1.0):
        return None if v is None or pd.isna(v) else round(float(v) * scale, 1)
    usage = {pid: {"xfp_pg": _f(r.get("xfp_pg")), "target_share": _f(r.get("target_share")), "hvt_pg": _f(r.get("hvt_pg"))}
             for pid, r in pool.iterrows()}
    byes = profile.bye_weeks(bundle["schedule"])
    rosters = trade_engine.build_rosters_espn(league, pool, values, cw, usage=usage, byes=byes)
    slots = [s for s in roster_positions if s in lineup_layer.ELIGIBLE and s not in ("K", "DEF", "D/ST")]
    trade_engine.annotate(rosters, slots)
    ctx = {"slots": slots, "profile": trade_engine.depth_profile(shape), "teams": shape["teams"],
           "starters": shape["starters"], "week": _next_unplayed_week(bundle["schedule"])}
    return bundle, rosters, ctx


def _run_trade_finder(setup, league_id, my_roster_id, target_roster_id, give_player_ids, max_suggestions, want_player_ids=None):
    bundle, rosters, ctx = setup
    if my_roster_id not in rosters:
        raise ValueError(f"roster_id {my_roster_id} not found in league {league_id}")
    mine_ids = {p["player_id"] for p in rosters[my_roster_id]["players"]}
    if give_player_ids:
        missing = [pid for pid in give_player_ids if pid not in mine_ids]
        if missing:
            raise ValueError(f"Player(s) not on your roster or not scoreable this season: {', '.join(missing)}")
        if len(give_player_ids) > 2:
            raise ValueError("Pick one or two players to shop at a time.")
    found = trade_engine.find_trades(rosters, my_roster_id, ctx, give_ids=list(give_player_ids or []) or None,
                                     target_ids={target_roster_id} if target_roster_id else None,
                                     max_suggestions=max_suggestions, want_ids=list(want_player_ids) if want_player_ids else None)
    out = []
    for f in found:
        a = f["analysis"]
        out.append({
            "opponent_roster_id": f["opponent_roster_id"], "opponent_team_name": f["opponent_team_name"], "kind": f.get("kind"),
            "you_give": [_public_player(p) for p in f["you_give"]], "you_get": [_public_player(p) for p in f["you_get"]],
            "value_diff": a["_my_dsl"], "my_gain": a["_my_dsl"], "their_gain": a["_opp_dsl"],
            "fills_need": max(f["you_get"], key=lambda p: p["trade"])["position"],
            "analysis": {k: v for k, v in a.items() if not k.startswith("_")},
        })
    result = {"season": bundle["season"], "my_roster_id": my_roster_id, "suggestions": out}
    if want_player_ids:        # who owns the player being pursued, so the page can say so when there is nothing to offer
        pid = list(want_player_ids)[0]
        owner = next(((rid, t) for rid, t in rosters.items() if any(p["player_id"] == pid for p in t["players"])), None)
        result["target"] = {"player_id": pid, "owner_roster_id": owner[0] if owner else None,
                            "owner_team_name": owner[1]["name"] if owner else None,
                            "on_my_roster": bool(owner and owner[0] == my_roster_id), "on_a_roster": owner is not None}
    return result


def trade_finder(league_id, my_roster_id, target_roster_id=None, give_player_ids=None,
                  season=None, scoring=None, max_suggestions=6, want_player_ids=None):
    """Trades that pass every gate in engine/trade_engine.py (tier break,
    both starting lineups, roster fit, records, fairness index), ranked by
    mutual benefit. Need-driven by default; with `give_player_ids` (one or
    two of yours) every suggestion includes them."""
    return _run_trade_finder(_trade_setup(league_id, scoring, season), league_id, my_roster_id,
                             target_roster_id, give_player_ids, max_suggestions, want_player_ids)


def trade_finder_espn(league_id, my_roster_id, target_roster_id=None, give_player_ids=None, season=None,
                      scoring=None, max_suggestions=6, year=None, espn_s2=None, swid=None, want_player_ids=None):
    """trade_finder() for an ESPN league. Kickers and defenses are not traded
    here (the engine values QB/RB/WR/TE), same as for Sleeper."""
    return _run_trade_finder(_trade_setup_espn(league_id, scoring, season, year, espn_s2, swid), league_id,
                             my_roster_id, target_roster_id, give_player_ids, max_suggestions, want_player_ids)


def evaluate_trade(league_id, my_roster_id, opponent_roster_id, give_ids, get_ids, scoring=None, season=None):
    """The full trade-engine verdict for a trade you built by hand."""
    _, rosters, ctx = _trade_setup(league_id, scoring, season)
    me, opp = rosters.get(my_roster_id), rosters.get(opponent_roster_id)
    if not me or not opp:
        raise ValueError("couldn't read one of the rosters from Sleeper")
    by_me = {p["player_id"]: p for p in me["players"]}
    by_opp = {p["player_id"]: p for p in opp["players"]}
    give = [by_me[i] for i in give_ids if i in by_me]
    get = [by_opp[i] for i in get_ids if i in by_opp]
    skipped = [i for i in give_ids if i not in by_me] + [i for i in get_ids if i not in by_opp]
    if not give or not get:
        return None
    a = trade_engine.assess(give, get, me, opp, ctx, full=True)
    out = {k: v for k, v in a.items() if not k.startswith("_")}
    if skipped:
        out["note"] = "Kickers, defenses and players we can't value yet were left out of this verdict."
    return out


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


# Out-of-sample error of the projection formula, measured by scripts/backtest_projection.py on
# every QB/RB/WR/TE game from 2016-2024 (each prediction uses only earlier games).
BACKTEST = {"mae": 5.15, "games": 32004, "seasons": "2016-2024"}


def projection_explain(player_id, scoring=None, season=None):
    """One player's projection for the coming week, laid out plainly: the expected
    number, the typical and the floor-to-ceiling range, and each thing that moved it
    with real numbers. None when he can't be found."""
    from . import ros_projection

    res = start_sit([player_id], scoring=scoring, season=season)
    p = res["players"][0] if res.get("players") else None
    if not p or p.get("error"):
        return None
    ros = ros_projection.player_ros(player_id, scoring=scoring, season=season) or {}
    o = p["outcomes"]
    out = {"player_id": player_id, "name": p.get("player_display_name"), "position": p["position"],
           "team": p.get("recent_team"), "week": p.get("week"), "opponent": p.get("opponent"),
           "on_bye": bool(p.get("on_bye")), "out": bool(o.get("out")), "out_reason": o.get("reason"),
           "injury_status": p.get("injury_status"), "backtest": BACKTEST, "drivers": []}
    if out["out"]:
        return out
    out.update({"expected": o["mean"], "typical": o["p50"], "floor": o["p10"], "ceiling": o["p90"],
                "p_10plus": o["p_10plus"], "p_20plus": o["p_20plus"], "p_play": o.get("p_play", 1.0)})

    def pct(f):
        return None if f is None else round((f - 1) * 100)

    def add(label, text, effect=None, detail=None):
        direction = "flat" if effect is None or abs(effect) < 2 else "up" if effect > 0 else "down"
        out["drivers"].append({"label": label, "text": text, "effect_pct": effect, "direction": direction, "detail": detail})

    games = len([g for g in ros.get("past_games", [])])
    ppg = p.get("fpts_per_game")
    hist = ros.get("history") or {}
    if ppg is not None:
        detail = None
        if hist.get("career_ppg") is not None and hist.get("weight"):
            detail = (f"Blended with his last {hist['lookback']} seasons ({hist['career_ppg']:.1f} a game over {hist['career_games']} games), "
                      f"which makes up {round(hist['weight'] * 100)}% of the starting rate.")
        add("Season scoring", f"{ppg:.1f} points a game over {games or p.get('games') or '?'} games", None, detail)
    if p.get("FORM") not in (None, 0):
        add("Recent form", f"Last few games {'above' if p['FORM'] > 0 else 'below'} his season pace", round(p["FORM"]),
            "Recent games count more, but a hot or cold streak only moves the number partway: past seasons show weekly scoring regresses fast.")
    xfp = (ros.get("usage") or {}).get("xfp_pg") or {}
    if xfp.get("recent") is not None and ppg is not None:
        gap = ppg - xfp["recent"]
        if gap >= 3:
            add("Usage vs results", f"Scoring {gap:.1f} a game more than his touches usually produce ({xfp['recent']:.1f} expected)", None,
                "Yards and touchdowns above his workload tend to even out. His rest-of-season baseline weights usage at 70%, so it sits below his scoring.")
        elif gap <= -3:
            add("Usage vs results", f"Scoring {abs(gap):.1f} a game less than his touches usually produce ({xfp['recent']:.1f} expected)", None,
                "His workload says better days are coming. His rest-of-season baseline weights usage at 70%, so it sits above his scoring.")
        else:
            add("Usage vs results", f"Scoring in line with his touches ({xfp['recent']:.1f} expected a game)")
    if p.get("usage") and p["usage"].get("label") in ("rising", "falling"):
        u = p["usage"]
        add("Role trend", f"{u['metric'].capitalize()} {u['label']}: {u['recent_avg']:g} a game lately vs {u['earlier_avg']:g} earlier", None)
    if p.get("opponent") and p.get("matchup_factor") is not None:
        add("Matchup", f"vs {p['opponent']}: {p.get('matchup_tag') or 'average'} defense for his position", pct(p["matchup_factor"]))
    env = p.get("environment") or {}
    if env.get("factor") not in (None, 1.0) or env.get("notes"):
        add("Game environment", "; ".join(env.get("notes") or []) or "Betting lines", pct(env.get("factor")),
            "Capped at 10% either way.")
    pc = p.get("play_chance")
    if pc:
        add("Health", f"Listed {p.get('injury_status')}: {round(pc['p_play'] * 100)}% chance he plays", round((pc["p_play"] - 1) * 100), pc.get("basis"))
    elif p.get("injury_status"):
        add("Health", f"Listed {p['injury_status']}", None)
    return out
