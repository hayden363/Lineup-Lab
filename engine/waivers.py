"""
WAIVER ENGINE — who fills my hole, and who is the best talent out there
=======================================================================
Two tracks over the same pool of free agents:

  * Smart Match: every free agent scored against YOUR roster (Waiver Priority
    Score), paired with the bench player you'd drop, and the net change to
    your starting lineup.
  * Discovery: platform-wide add/drop velocity, a usage deep dive, trap and
    breakout flags, and a handcuff index.

Waiver Priority Score (0-100):
    WPS = 0.35 * positional urgency + 0.30 * VORP
        + 0.25 * usage quality      + 0.10 * schedule
    VORP = his rest-of-season points/game minus the replacement-level player at
    his position (the first player a league of this shape leaves unrostered).
    The lineup gain from adding him still decides which move is worth showing
    and who to drop; it is shown next to the score but is not weighted in it.

Every input is real data or computed from it:
  * rosters, FAAB budget and spend, waiver priority, waiver day   Sleeper league
  * add/drop counts over 24h and 48h                              Sleeper trending
  * snap share                                                    nflverse snap counts
  * targets, carries, target share, WOPR                          nflverse weekly
  * red-zone / goal-line work, expected fantasy points (xFP)      nflverse play-by-play
  * backups behind each starter                                   nflverse depth charts
  * matchups                                                      engine/defense.py

Not available, so not shown as numbers: route participation (no public 2026
source), roster % / claim share (Sleeper doesn't publish it), playoff odds.
xFP is our own model (league-average points for each kind of opportunity this
season), and FAAB bid tiers are our suggestion, not a market consensus.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import data, injuries, lineup as lineup_layer, optimizer, profile, sleeper, value as value_layer
from .board import POSITIONS, build_board, load_bundle, matchup_multiplier, rest_of_season_value
from .scoring import ScoringSettings, apply_scoring

ET = ZoneInfo("America/New_York")
WAIVER_TYPES = {0: "Rolling waivers", 1: "Reverse standings", 2: "FAAB"}
# Sleeper's waiver_day_of_week: 0 = Monday. Checked against a real league set
# to 2: all 30 of its processed claims this season cleared Wednesday ~3 AM ET.
WAIVER_HOUR_ET = 3
UNAVAILABLE_NOW = {"Out", "IR", "PUP", "Sus", "NA"}
UNAVAILABLE_LONG = {"IR", "PUP", "Sus", "NA"}
WEIGHTS = {"urgency": 0.35, "vorp": 0.30, "usage": 0.25, "schedule": 0.10}
VORP_FULL_SCORE = 15.0  # +15 pts/game over replacement = a full 100 on the VORP input (8 saturated for every top add)
GAIN_FULL_SCORE = 5.0   # +5 pts/week to your starting lineup = a full 100 on the gain input
TRAP_SNAP_PCT = 35      # a big week on fewer snaps than this is a trap
TRAP_MIN_POINTS = 12
WINDOW = 3              # weeks of byes/injuries the urgency check looks ahead
FAAB_TIERS = [("floor", "Floor", 2, 5, "Speculative depth add; unlikely to be contested."),
              ("market", "Market", 12, 18, "Competitive add in a 10-12 team league."),
              ("aggressive", "Desperation", 25, 45, "Starter-level role or you're desperate at the spot; 45% and up if rivals are flush.")]


# ------------------------------------------------------------ league status ----
def next_waiver_run(settings, now=None):
    """Aware datetime (ET) of the next waiver processing, or None if the league
    doesn't run waivers on a schedule."""
    now = (now or dt.datetime.now(ET)).astimezone(ET)
    if settings.get("daily_waivers"):
        hour = int(settings.get("daily_waivers_hour") or WAIVER_HOUR_ET)
        run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        return run if run > now else run + dt.timedelta(days=1)
    day = settings.get("waiver_day_of_week")
    if day is None:
        return None
    run = now.replace(hour=WAIVER_HOUR_ET, minute=0, second=0, microsecond=0)
    run += dt.timedelta(days=(int(day) - now.weekday()) % 7)
    return run if run > now else run + dt.timedelta(days=7)


def league_status(league, rosters, my_roster_id, now=None):
    s = league.get("settings") or {}
    wtype = s.get("waiver_type")
    mine = next((r for r in rosters if r.get("roster_id") == my_roster_id), {}) or {}
    ms = mine.get("settings") or {}
    out = {"waiver_type": WAIVER_TYPES.get(wtype, "Waivers"), "is_faab": wtype == 2,
           "priority": ms.get("waiver_position"), "teams": len(rosters)}
    if wtype == 2:
        budget = float(s.get("waiver_budget") or 100)
        used = float(ms.get("waiver_budget_used") or 0)
        out.update(faab_budget=budget, faab_used=used, faab_remaining=max(0.0, budget - used),
                   faab_remaining_pct=round(100 * max(0.0, budget - used) / budget, 1) if budget else 0.0)
        # What every OTHER team still has to bid: a bid only wins against rivals
        # who can't outspend it.
        out["rivals_remaining"] = sorted(
            (max(0.0, budget - float((r.get("settings") or {}).get("waiver_budget_used") or 0))
             for r in rosters if r.get("roster_id") != my_roster_id), reverse=True)
    run = next_waiver_run(s, now)
    if run:
        out["next_run"] = run.isoformat()
        out["next_run_label"] = run.strftime("%a %b %-d, %-I %p ET")
    return out


def target_week(schedule):
    """The week waivers are for: the first week with most games still unplayed."""
    s = schedule[schedule["game_type"] == "REG"] if "game_type" in schedule.columns else schedule
    for wk in sorted(s["week"].unique()):
        games = s[s["week"] == wk]
        if games["home_score"].notna().sum() < len(games) / 2:
            return int(wk)
    return int(s["week"].max())


# ---------------------------------------------------------------- usage ----
def _points_settings(scoring):
    return scoring if isinstance(scoring, ScoringSettings) else ScoringSettings.from_dict(scoring or {}) \
        if scoring else ScoringSettings.from_preset("ppr")


def xfp_by_player(pbp, scoring=None):
    """Expected fantasy points per player per week: every target and carry is
    worth the league-average fantasy points of that kind of opportunity this
    season (targets by air-yard depth and field zone, carries by field zone).
    Passing isn't modeled, so QBs get rushing xFP only and show no xFP."""
    s = _points_settings(scoring)
    p = pbp[pbp["week"].notna()]
    zone_bins = [0, 5, 10, 20, 50, 100]
    tg = p[(p["play_type"] == "pass") & p["receiver_player_id"].notna() & p["air_yards"].notna()].copy()
    tg["pts"] = (tg["complete_pass"].fillna(0) * (s.reception + tg["yards_gained"].fillna(0) * s.rec_yard)
                 + tg["pass_touchdown"].fillna(0) * s.rec_td)
    tg["depth"] = pd.cut(tg["air_yards"], [-100, 0, 5, 10, 20, 100], labels=False)
    tg["zone"] = pd.cut(tg["yardline_100"], zone_bins, labels=False, include_lowest=True)
    tg["xfp"] = tg.groupby(["depth", "zone"])["pts"].transform("mean")
    ru = p[(p["play_type"] == "run") & p["rusher_player_id"].notna()].copy()
    ru["pts"] = ru["yards_gained"].fillna(0) * s.rush_yard + ru["rush_touchdown"].fillna(0) * s.rush_td
    ru["zone"] = pd.cut(ru["yardline_100"], [0, 2, 5, 10, 20, 50, 100], labels=False, include_lowest=True)
    ru["xfp"] = ru.groupby("zone")["pts"].transform("mean")
    rows = pd.concat([
        tg.rename(columns={"receiver_player_id": "player_id"})[["player_id", "week", "xfp"]],
        ru.rename(columns={"rusher_player_id": "player_id"})[["player_id", "week", "xfp"]],
    ])
    return rows.groupby(["player_id", "week"])["xfp"].sum().reset_index()


def goal_line_share(pbp):
    """Share of his team's carries + targets inside the 5-yard line."""
    p = pbp[pbp["yardline_100"].fillna(100) <= 5]
    car = p[(p["play_type"] == "run") & p["rusher_player_id"].notna()][["posteam", "rusher_player_id"]] \
        .rename(columns={"rusher_player_id": "player_id"})
    tgt = p[(p["play_type"] == "pass") & p["receiver_player_id"].notna()][["posteam", "receiver_player_id"]] \
        .rename(columns={"receiver_player_id": "player_id"})
    opp = pd.concat([car, tgt])
    if opp.empty:
        return {}
    team_tot = opp.groupby("posteam").size()
    mine = opp.groupby(["player_id", "posteam"]).size().reset_index(name="n")
    mine["share"] = mine["n"] / mine["posteam"].map(team_tot)
    return mine.groupby("player_id")["share"].max().round(3).to_dict()


def weekly_snaps(season):
    """{gsis_id: {week: offense snap %}} (0-100)."""
    try:
        snaps = data.load_snap_counts(season)
        cw = data.load_pfr_crosswalk()
    except Exception as e:
        print(f"[waivers] snap counts unavailable: {e}")
        return {}
    pfr = dict(zip(cw["pfr_id"], cw["gsis_id"]))
    out = {}
    for r in snaps[["pfr_player_id", "week", "offense_pct"]].itertuples(index=False):
        g = pfr.get(r.pfr_player_id)
        if g and pd.notna(r.offense_pct):
            out.setdefault(g, {})[int(r.week)] = round(float(r.offense_pct) * (100 if r.offense_pct <= 1 else 1), 1)
    return out


def weekly_usage(wk_scored):
    """Per player per week: fpts, opportunities (targets + carries), TD points."""
    w = wk_scored
    td = (w.get("rushing_tds", 0).fillna(0) + w.get("receiving_tds", 0).fillna(0)) * 6
    return pd.DataFrame({"player_id": w["player_id"], "week": w["week"], "fpts": w["fpts_active"],
                         "opp": w["targets"].fillna(0) + w["carries"].fillna(0),
                         "targets": w["targets"].fillna(0), "td_pts": td})


def flag(weeks, snaps):
    """'trap', 'breakout' or None from his game log (list of week dicts with
    fpts/opp/td_pts, oldest first) and {week: snap %}.
      trap      big box score off little work: 12+ points on under 35% of
                snaps, or 12+ points (and 1.5x his usual) on <= 5 opportunities,
                mostly from TDs
      breakout  work jumped 30%+ (opportunities or snaps) in his last game
                while the box score stayed ordinary
    """
    if not weeks:
        return None, None
    last, prior = weeks[-1], weeks[:-1]
    snap_last = snaps.get(last["week"])
    prior_fpts = np.mean([w["fpts"] for w in prior]) if prior else None
    low_snaps = snap_last is not None and snap_last < TRAP_SNAP_PCT
    td_fluke = (last["opp"] <= 5 and (prior_fpts is None or last["fpts"] >= 1.5 * prior_fpts)
                and last["td_pts"] >= 0.5 * last["fpts"])
    if last["fpts"] >= TRAP_MIN_POINTS and (low_snaps or td_fluke):
        work = f"{int(last['opp'])} touches/targets" + (f", {snap_last:.0f}% of snaps" if snap_last is not None else "")
        return "trap", f"{last['fpts']:.1f} pts in week {last['week']} on {work}; {last['td_pts']:.0f} of it from TDs"
    if len(prior) >= 2:
        p_opp = np.mean([w["opp"] for w in prior])
        p_snap = [snaps[w["week"]] for w in prior if w["week"] in snaps]
        opp_jump = p_opp > 0 and last["opp"] >= 1.3 * p_opp and last["opp"] >= 8
        snap_jump = (snap_last is not None and p_snap and snap_last >= 50
                     and snap_last >= 1.3 * np.mean(p_snap) and snap_last - np.mean(p_snap) >= 10)
        if (opp_jump or snap_jump) and last["fpts"] <= 1.1 * prior_fpts:
            bits = []
            if opp_jump:
                bits.append(f"{int(last['opp'])} touches/targets (was {p_opp:.1f})")
            if snap_jump:
                bits.append(f"{snap_last:.0f}% of snaps (was {np.mean(p_snap):.0f}%)")
            return "breakout", f"Week {last['week']}: " + ", ".join(bits) + f", only {last['fpts']:.1f} pts so far"
    return None, None


# --------------------------------------------------------------- schedule ----
GRADES = [(80, "A"), (60, "B"), (40, "C"), (20, "D"), (0, "F")]


def grade(score):
    return next(g for floor, g in GRADES if score >= floor)


def schedule_outlook(position, team, week, bundle, n=4):
    """Next n games' matchup multipliers -> 0-100 (1.10 easy = 100, 0.90 hard = 0)."""
    sched = profile.team_schedule(bundle["schedule"], team) if team else {}
    games = [(w, sched[w]["opponent"]) for w in range(week, week + n) if w in sched]
    if not games:
        return {"score": 50.0, "grade": "C", "opponents": []}
    mults = [matchup_multiplier(position, opp, bundle) for _, opp in games]
    score = float(np.clip((np.mean(mults) - 0.90) / 0.20 * 100, 0, 100))
    return {"score": round(score, 1), "grade": grade(score),
            "opponents": [{"week": w, "opponent": o, "factor": round(m, 3)} for (w, o), m in zip(games, mults)]}


# ---------------------------------------------------------------- lineups ----
def lineup_total(slots, players):
    """Best starting-lineup sum over QB/RB/WR/TE/flex slots (exact, see
    engine/optimizer.py). `players`: list of {player_id, position, value}."""
    return optimizer.best_assignment(slots, players, lineup_layer.eligible)[0]


def scoring_slots(roster_positions):
    return [s for s in roster_positions or [] if s in lineup_layer.ELIGIBLE and s not in ("K", "DEF", "D/ST")]


def week_value(p, week, byes):
    """A player's value in one specific week: 0 on his bye or while he can't play."""
    status = p.get("injury_status")
    if byes.get(p.get("team")) == week:
        return 0.0
    if status in UNAVAILABLE_LONG or (p.get("week0") == week and status in UNAVAILABLE_NOW):
        return 0.0
    return p["value"]


def needs(my_players, slots, league_rosters, week, byes):
    """{position: {multiplier, score 0-100, reasons}} for my roster.
    Urgency: a week in the next WINDOW where I can't fill my starting slots at
    a position (bye/injury) -> 1.5 this week, 1.3 next, 1.15 the week after.
    Imbalance: my weakest starter at a position vs the league median of the
    same rank -> up to 1.5 when mine is far behind."""
    out = {}
    dedicated = {pos: slots.count(pos) for pos in POSITIONS}
    for pos in POSITIONS:
        mult, reasons = 1.0, []
        for i, wk in enumerate(range(week, week + WINDOW)):
            healthy = [p for p in my_players if p["position"] == pos and week_value(p, wk, byes) > 0]
            flex_need = sum(1 for s in slots if s not in POSITIONS and lineup_layer.eligible(s, pos))
            flex_pool = [p for p in my_players if p["position"] in ("RB", "WR", "TE") and week_value(p, wk, byes) > 0]
            flex_dedicated = sum(dedicated[x] for x in ("RB", "WR", "TE"))
            short_pos = len(healthy) < dedicated[pos]
            short_flex = pos in ("RB", "WR", "TE") and flex_need and len(flex_pool) < flex_dedicated + flex_need
            if short_pos or short_flex:
                m = (1.5, 1.3, 1.15)[i]
                if m > mult:
                    mult = m
                why = "byes/injuries" if any(byes.get(p.get("team")) == wk for p in my_players if p["position"] == pos) else "injuries"
                reasons.append(f"Week {wk}: only {len(healthy)} healthy {pos}{'s' if len(healthy) != 1 else ''} "
                               f"for {dedicated[pos]} {pos} slot{'s' if dedicated[pos] != 1 else ''}"
                               + (" plus flex" if short_flex and not short_pos else "") + f" ({why})")
                break
        k = dedicated[pos]
        if k and league_rosters:
            def kth(players):
                vals = sorted((p["value"] for p in players if p["position"] == pos), reverse=True)
                return vals[k - 1] if len(vals) >= k else 0.0
            mine = kth(my_players)
            median = float(np.median([kth(r) for r in league_rosters]))
            if median > 0 and mine < 0.85 * median:
                m = min(1.5, 1.0 + (1 - mine / median))
                if m > mult:
                    mult = m
                reasons.append(f"Your {pos}{k} projects {mine:.1f} pts/wk; the league median {pos}{k} is {median:.1f}")
        out[pos] = {"multiplier": round(mult, 2), "score": round((mult - 1.0) / 0.5 * 100, 1), "reasons": reasons}
    return out


def handcuffs_on(players, depth):
    """player_ids on this roster who are the direct backup to a starter on the same roster."""
    mine = {p["player_id"] for p in players}
    out = set()
    for team, chart in depth.items():
        rb = chart.get("RB", [])
        if len(rb) >= 2 and rb[0] in mine and rb[1] in mine:
            out.add(rb[1])
    return out


def best_swap(add, my_players, slots, roster_full, protected, byes, week):
    """(drop player or None, ROS gain/wk, next-3-weeks gain/wk) for adding `add`."""
    base = lineup_total(slots, my_players)

    def window(players):
        return np.mean([lineup_total(slots, [{**p, "value": week_value(p, w, byes)} for p in players])
                        for w in range(week, week + WINDOW)])

    base_w = window(my_players)
    if not roster_full:
        after = my_players + [add]
        return None, lineup_total(slots, after) - base, window(after) - base_w
    choices = []
    for cand in my_players:
        if cand["player_id"] in protected or cand.get("position") not in POSITIONS:
            continue
        after = [p for p in my_players if p["player_id"] != cand["player_id"]] + [add]
        choices.append((lineup_total(slots, after) - base, cand, after))
    if not choices:
        return None, None, None
    gain, drop, after = max(choices, key=lambda c: (round(c[0], 2), -c[1]["value"]))
    return drop, gain, window(after) - base_w


def bid_tiers(wps, need_mult, status):
    """Our three FAAB bid ranges with one recommended (FAAB leagues only).
    When rival balances are known, each tier also says how many rivals can
    afford its top bid, so a bid that every rival can cover reads as
    contested instead of safe."""
    if not status.get("is_faab"):
        return None
    rec = "aggressive" if wps >= 80 or (need_mult >= 1.5 and wps >= 65) else "market" if wps >= 60 else "floor"
    budget, left = status["faab_budget"], status["faab_remaining"]
    rivals = status.get("rivals_remaining") or []
    tiers = []
    for key, label, lo, hi, why in FAAB_TIERS:
        top = round(budget * hi / 100)
        tier = {"key": key, "label": label, "pct": [lo, hi], "why": why,
                "dollars": [min(left, round(budget * lo / 100)), min(left, top)],
                "recommended": key == rec}
        if rivals:
            tier["rivals_can_cover"] = sum(1 for r in rivals if r >= top)
            tier["rivals"] = len(rivals)
        tiers.append(tier)
    return tiers


# ---------------------------------------------------------------- the pool ----
def depth_by_team():
    """{team: {"RB": [gsis ids by depth], ...}} from the newest depth-chart snapshot."""
    try:
        dc = data.load_depth_charts()
    except Exception as e:
        print(f"[waivers] depth charts unavailable: {e}")
        return {}
    dc = dc[dc["pos_abb"].isin(["QB", "RB", "WR", "TE"]) & dc["gsis_id"].notna()]
    if dc.empty:
        return {}
    dc = dc[dc["dt"] == dc.groupby("team")["dt"].transform("max")]
    out = {}
    for (team, pos), g in dc.sort_values("pos_rank").groupby(["team", "pos_abb"]):
        ids = list(dict.fromkeys(g["gsis_id"]))
        out.setdefault(team, {})[pos] = ids
    return out


_POOL_CACHE = {}
POOL_TTL = 10 * 60


def cached_pool(scoring, bundle):
    """player_pool + usage_score, reused for 10 minutes per (season, scoring)."""
    import time
    key = (bundle["season"], None if scoring is None else tuple(sorted(dict(scoring).items())))
    hit = _POOL_CACHE.get(key)
    if hit and time.time() - hit[0] < POOL_TTL:
        return hit[1], hit[2]
    pool, logs = player_pool(scoring, bundle)
    pool["usage_score"] = usage_scores(pool)
    _POOL_CACHE.clear()
    _POOL_CACHE[key] = (time.time(), pool, logs)
    return pool, logs


def player_pool(scoring, bundle):
    """Every QB/RB/WR/TE with a game this season, with ROS value and usage."""
    frames = []
    for pos in POSITIONS:
        b = build_board(pos, season=bundle["season"], min_games=1, scoring=scoring).copy()
        b["value"] = rest_of_season_value(b, pos, bundle=bundle)
        frames.append(b)
    pool = pd.concat(frames)
    wk_scored, _ = apply_scoring(bundle["wk"], scoring)
    usage = weekly_usage(wk_scored[wk_scored["player_id"].isin(pool.index)])
    xfp = xfp_by_player(bundle["pbp"], scoring)
    usage = usage.merge(xfp, on=["player_id", "week"], how="left")
    usage["xfp"] = usage["xfp"].fillna(0)
    g = usage.groupby("player_id")
    pool["xfp_pg"] = g["xfp"].mean().round(1)
    pool["opp_pg"] = g["opp"].mean().round(1)
    pool["actual_pg"] = g["fpts"].mean().round(1)
    pool["xfp_diff"] = (pool["actual_pg"] - pool["xfp_pg"]).round(1)
    pool.loc[pool["position"] == "QB", ["xfp_pg", "xfp_diff"]] = np.nan
    gl = goal_line_share(bundle["pbp"])
    pool["goal_line_share"] = pool.index.map(lambda i: gl.get(i, 0.0))
    pool["hvt_pg"] = ((pool["redzone_touches"].fillna(0) + pool["targets"].fillna(0)) / pool["games"]).round(1)
    pool.loc[~pool["position"].isin(["RB"]), "hvt_pg"] = np.nan
    logs = {pid: grp.sort_values("week").to_dict("records") for pid, grp in usage.groupby("player_id")}
    return pool, logs


def replacement_levels(pool, roster_positions, teams):
    """{position: projected points/game of the first player this league shape
    leaves unrostered}: rank (teams x starters at the position + 1) by value.
    The baseline VORP is measured against (engine/value.replacement_ranks)."""
    from . import trade_engine
    if roster_positions:
        shape = trade_engine.league_shape(roster_positions, teams)
        ranks = value_layer.replacement_ranks({"teams": shape["teams"], "slots": shape["slots"]})
    else:
        ranks = value_layer.replacement_ranks(None)
    out = {}
    for pos in POSITIONS:
        vals = pool.loc[pool["position"] == pos, "value"].sort_values(ascending=False)
        out[pos] = float(vals.iloc[min(ranks[pos], len(vals)) - 1]) if len(vals) else 0.0
    return out


def usage_scores(pool):
    """0-100 usage quality: mean percentile within position of the volume signals
    that fit the position."""
    cols = {"QB": ["opp_pg", "snap_pct"], "RB": ["snap_pct", "opp_pg", "hvt_pg", "xfp_pg"],
            "WR": ["snap_pct", "target_share", "wopr", "xfp_pg"], "TE": ["snap_pct", "target_share", "wopr", "xfp_pg"]}
    out = pd.Series(50.0, index=pool.index)
    for pos, cs in cols.items():
        sub = pool[pool["position"] == pos]
        if sub.empty:
            continue
        pct = [sub[c].rank(pct=True) * 100 for c in cs if c in sub.columns and sub[c].notna().any()]
        if pct:
            out.loc[sub.index] = pd.concat(pct, axis=1).mean(axis=1).fillna(0).round(1)
    return out


def _num(v, nd=1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else round(float(v), nd)


def _band(r, key):
    v, avg, ros = r.get(key), r.get("fpts_per_game"), r.get("value")
    if v is None or pd.isna(v) or not avg or pd.isna(avg) or ros is None or pd.isna(ros):
        return v
    return float(v) * float(ros) / float(avg)


def player_card(pid, r, sched, badge, extra=None):
    snap = r.get("snap_pct")
    return {
        "player_id": pid, "name": r["player_display_name"], "position": r["position"], "team": r["recent_team"],
        "headshot_url": r.get("headshot_url"), "injury_status": r.get("injury_status") if isinstance(r.get("injury_status"), str) else None,
        "ros": _num(r["value"]), "fpts_pg": _num(r["fpts_per_game"]), "games": int(r["games"]),
        "SCORE": _num(r.get("SCORE")), "PVS": _num(r.get("PVS")), "FORM": _num(r.get("FORM")),
        "snap_pct": _num(snap * 100 if snap is not None and not pd.isna(snap) and snap <= 1 else snap),
        "target_share": _num(r.get("target_share")),   # board stores these as percents
        "wopr": _num(r.get("wopr") / 100 if _num(r.get("wopr")) is not None else None, 2), "xfp_pg": _num(r.get("xfp_pg")), "xfp_diff": _num(r.get("xfp_diff")),
        "hvt_pg": _num(r.get("hvt_pg")), "goal_line_share": _num((r.get("goal_line_share") or 0) * 100),
        # floor/ceiling come from his raw per-game average; scale them onto
        # the projection so a bad week never reads above the projection.
        "floor": _num(_band(r, "floor")), "ceiling": _num(_band(r, "ceiling")), "bye_week": _num(r.get("bye_week"), 0),
        "schedule": sched, "badge": badge[0], "badge_reason": badge[1], **(extra or {}),
    }


def espn_status(league, my_team_id):
    """League status from an ESPN league: waiver priority and team count.
    espn-api exposes no FAAB budget, so ESPN leagues get no bid ranges."""
    mine = next((t for t in league.teams if t.team_id == my_team_id), None)
    return {"waiver_type": "Waivers", "is_faab": False, "teams": len(league.teams),
            "priority": getattr(mine, "waiver_rank", None) or None}


def build(league_id=None, my_roster_id=None, scoring=None, now=None, limit=10, espn=None):
    """`espn` = {"league": espn_api League, "team_id": int} reads rosters and
    settings from ESPN instead of Sleeper."""
    bundle = load_bundle()
    schedule = bundle["schedule"]
    week = target_week(schedule)
    byes = profile.bye_weeks(schedule)
    pool, logs = cached_pool(scoring, bundle)
    pool = pool.copy()
    snaps = weekly_snaps(bundle["season"])
    depth = depth_by_team()

    rostered, status, my_players, slots, league_rosters, roster_full = set(), None, [], [], [], False
    mine_raw = {}
    roster_positions, n_teams = None, 0

    def as_players(ids):
        out = []
        for g in ids:
            if g and g in pool.index:
                row = pool.loc[g]
                out.append({"player_id": g, "position": row["position"], "team": row["recent_team"],
                            "value": float(row["value"]), "name": row["player_display_name"],
                            "injury_status": row.get("injury_status") if isinstance(row.get("injury_status"), str) else None,
                            "week0": week})
        return out

    if espn:
        from . import espn as espn_layer
        eleague, cw = espn["league"], espn_layer.id_crosswalk()
        roster_positions = espn_layer.roster_positions(eleague)
        n_teams = len(eleague.teams)
        status = espn_status(eleague, espn["team_id"])
        slots = scoring_slots(roster_positions)
        for t in eleague.teams:
            ids = [cw.get(str(p.playerId)) for p in t.roster]
            rostered |= set(ids)
            ps = as_players([g for p, g in zip(t.roster, ids) if p.lineupSlot != "IR"])
            if t.team_id == espn["team_id"]:
                my_players = ps
            league_rosters.append(ps)
        counts = getattr(eleague.settings, "position_slot_counts", None) or {}
        cap = sum(n for k, n in counts.items() if k != "IR")
        mine_t = next((t for t in eleague.teams if t.team_id == espn["team_id"]), None)
        roster_full = bool(mine_t and cap and len([p for p in mine_t.roster if p.lineupSlot != "IR"]) >= cap)
        rostered.discard(None)
    elif league_id and my_roster_id is not None:
        league = sleeper.get_league(league_id)
        rosters = sleeper.get_rosters(league_id)
        roster_positions, n_teams = league.get("roster_positions"), len(rosters)
        status = league_status(league, rosters, my_roster_id, now)
        slots = scoring_slots(roster_positions)
        cw = sleeper.id_crosswalk()
        for r in rosters:
            rostered |= {cw.get(str(x)) for x in (r.get("players") or [])}
            ps = as_players([cw.get(str(raw)) for raw in r.get("players") or []])
            if r.get("roster_id") == my_roster_id:
                my_players = ps
                mine_raw = r
            league_rosters.append(ps)
        active = len(mine_raw.get("players") or []) - len(mine_raw.get("reserve") or []) - len(mine_raw.get("taxi") or [])
        roster_full = active >= len([s_ for s_ in league.get("roster_positions") or [] if s_ not in ("IR", "TAXI")])
        rostered.discard(None)

    avail = pool[~pool.index.isin(rostered) & ~pool.index.isin(bundle["retired_ids"])]
    sched_cache = {}

    def sched_for(pid, r):
        key = (r["position"], r["recent_team"])
        if key not in sched_cache:
            sched_cache[key] = schedule_outlook(r["position"], r["recent_team"], week, bundle)
        return sched_cache[key]

    def badge_for(pid):
        return flag(logs.get(pid, []), snaps.get(pid, {}))

    # ---- Smart Match
    smart = []
    need = None
    if my_players:
        need = needs(my_players, slots, [r for r in league_rosters if r is not my_players], week, byes)
        protected = handcuffs_on(my_players, depth)
        # IR/PUP/suspended players can't help a lineup soon; they stay in the
        # deep dive (flagged) but aren't Smart Match adds.
        repl_level = replacement_levels(pool, roster_positions, n_teams)
        healthy = avail[~avail["injury_status"].isin(UNAVAILABLE_LONG)
                        & ~avail.apply(lambda r: injuries.out_long(r, schedule), axis=1)]
        candidates = healthy.sort_values("value", ascending=False).head(120)
        for pid, r in candidates.iterrows():
            add = {"player_id": pid, "position": r["position"], "team": r["recent_team"], "value": float(r["value"]),
                   "injury_status": r.get("injury_status") if isinstance(r.get("injury_status"), str) else None,
                   "week0": week}
            drop, gain, gain3 = best_swap(add, my_players, slots, roster_full, protected, byes, week)
            if gain is None:
                continue
            sched = sched_for(pid, r)
            n = need[r["position"]]
            vorp = float(r["value"]) - repl_level.get(r["position"], 0.0)
            parts = {"urgency": n["score"], "vorp": float(np.clip(vorp / VORP_FULL_SCORE * 100, 0, 100)),
                     "usage": float(r["usage_score"]), "schedule": sched["score"]}
            wps = sum(WEIGHTS[k] * v for k, v in parts.items())
            smart.append({**player_card(pid, r, sched, badge_for(pid)), "wps": round(wps, 1),
                          "wps_parts": {k: round(v, 1) for k, v in parts.items()},
                          "vorp": round(vorp, 1),
                          "gain_ros": round(gain, 1), "gain_next3": round(gain3, 1),
                          "need_reasons": n["reasons"], "need_multiplier": n["multiplier"],
                          "drop": None if drop is None else {"player_id": drop["player_id"], "name": drop["name"],
                                                              "position": drop["position"], "team": drop["team"],
                                                              "ros": round(drop["value"], 1)},
                          "bids": bid_tiers(wps, n["multiplier"], status)})
        # Only moves that actually help: +0.3/wk rest of season, or +1/wk
        # over the next 3 weeks (covering a bye or injury).
        smart = [s for s in smart if s["gain_ros"] >= 0.3 or s["gain_next3"] >= 1.0]
        smart.sort(key=lambda s: -s["wps"])
        smart = smart[:limit]
        for s in smart:
            s["swap"] = swap_detail(s, pool, my_players, slots, sched_for, byes, week)

    # ---- Market movers
    movers = market_movers(pool, rostered, sched_for, badge_for, bool(my_players))

    # ---- The ranked list (+ usage columns) and handcuffs
    # Ranked by SCORE like the original waiver list. Top 20 per position, so filtering to one position in the table still
    # leaves a real list (QBs would otherwise crowd out everything else).
    try:
        trend48 = sleeper.trending_gsis_counts("add", lookback_hours=48, limit=200)
    except Exception:
        trend48 = {}
    # 2+ games, same bar as the original list: one big game shouldn't top it.
    top = avail[avail["games"] >= 2].sort_values("PVS" if "PVS" in avail.columns else "SCORE", ascending=False, na_position="last").groupby("position", group_keys=False).head(20)
    deep = [player_card(pid, r, sched_for(pid, r), badge_for(pid),
                        {"usage_score": _num(r["usage_score"]), "trending_adds": int(trend48.get(pid, 0))})
            for pid, r in top.iterrows()]
    cuffs = handcuff_index(depth, pool, rostered)

    return {"season": bundle["season"], "week": week, "league": status,
            "needs": need, "smart_match": smart, "market_movers": movers, "deep_dive": deep,
            "handcuffs": cuffs, "has_league": bool(my_players),
            "weights": WEIGHTS, "not_available": ["Route participation (no public 2026 data)",
                                                  "Roster % and claim share (Sleeper doesn't publish them)",
                                                  "Playoff odds"]}


def swap_detail(s, pool, my_players, slots, sched_for, byes, week):
    """Side-by-side add vs drop, and the lineup before/after."""
    drop = s.get("drop")
    def side(pid):
        if pid is None or pid not in pool.index:
            return None
        r = pool.loc[pid]
        c = player_card(pid, r, sched_for(pid, r), (None, None))
        return {k: c[k] for k in ("player_id", "name", "position", "team", "ros", "snap_pct", "target_share",
                                   "goal_line_share", "floor", "ceiling", "xfp_pg")} | {"schedule_score": c["schedule"]["score"],
                                                                                    "schedule_grade": c["schedule"]["grade"]}
    def lineup_band(players):
        # starters chosen by value; floor/ceiling summed over those starters
        order = sorted(slots, key=lambda x: len(lineup_layer.ELIGIBLE.get(x, {x})))
        used, proj, lo, hi = set(), 0.0, 0.0, 0.0
        for slot in order:
            cand = [p for p in players if p["player_id"] not in used and lineup_layer.eligible(slot, p["position"])]
            if cand:
                b = max(cand, key=lambda p: p["value"])
                used.add(b["player_id"])
                r = pool.loc[b["player_id"]]
                proj += b["value"]
                f, c = _band(r, "floor"), _band(r, "ceiling")
                lo += float(f) if f is not None and pd.notna(f) else b["value"]
                hi += float(c) if c is not None and pd.notna(c) else b["value"]
        return {"proj": round(proj, 1), "floor": round(lo, 1), "ceiling": round(hi, 1)}
    add = {"player_id": s["player_id"], "position": s["position"], "team": s["team"], "value": s["ros"]}
    after = [p for p in my_players if not drop or p["player_id"] != drop["player_id"]] + [add]
    return {"add": side(s["player_id"]), "drop": side(drop["player_id"]) if drop else None,
            "before": lineup_band(my_players), "after": lineup_band(after)}


def market_movers(pool, rostered, sched_for, badge_for, has_league, limit=15):
    """Sleeper's platform-wide adds/drops: 24h net and day-over-day velocity."""
    try:
        add24 = sleeper.trending_gsis_counts("add", lookback_hours=24, limit=200)
        add48 = sleeper.trending_gsis_counts("add", lookback_hours=48, limit=200)
        drop24 = sleeper.trending_gsis_counts("drop", lookback_hours=24, limit=200)
    except Exception as e:
        print(f"[waivers] trending unavailable: {e}")
        return []
    out = []
    for pid in set(add24) | set(drop24):
        if pid not in pool.index:
            continue
        # A player outside Sleeper's top-200 list for a kind has an unknown
        # count there, not zero; drops stay None and net is adds minus known drops.
        a, d = add24.get(pid, 0), drop24.get(pid)
        prev = max(0, add48.get(pid, a) - a)
        r = pool.loc[pid]
        out.append(player_card(pid, r, sched_for(pid, r), badge_for(pid), {
            "adds_24h": a, "drops_24h": d, "net_24h": a - (d or 0), "adds_prev_24h": prev,
            "velocity": round(a / prev, 1) if prev else None,
            "available": (pid not in rostered) if has_league else None}))
    out.sort(key=lambda m: -m["net_24h"])
    return out[:limit]


def handcuff_index(depth, pool, rostered, limit=20):
    """Each team's RB2, ranked by what the RB1 role is worth (the starter's ROS
    pts/week), with the backup's current snap share and whether the starter is
    banged up right now."""
    out = []
    for team, chart in depth.items():
        rb = [p for p in chart.get("RB", []) if p in pool.index]
        if len(rb) < 2:
            continue
        starter, backup = pool.loc[rb[0]], pool.loc[rb[1]]
        if backup["value"] > starter["value"] or backup.get("injury_status") in UNAVAILABLE_LONG:
            # The depth chart lists the lead back second while he's hurt;
            # he isn't anyone's handcuff.
            continue
        st_status = starter.get("injury_status") if isinstance(starter.get("injury_status"), str) else None
        out.append({"team": team, "backup_id": rb[1], "backup": backup["player_display_name"],
                    "backup_ros": _num(backup["value"]), "backup_snap_pct": _num(backup.get("snap_pct") * 100 if pd.notna(backup.get("snap_pct")) and backup.get("snap_pct") <= 1 else backup.get("snap_pct")),
                    "starter": starter["player_display_name"], "starter_ros": _num(starter["value"]),
                    "starter_status": st_status, "live": st_status in UNAVAILABLE_NOW | {"Questionable", "Doubtful"},
                    "available": rb[1] not in rostered, "index": _num(starter["value"])})
    out.sort(key=lambda c: (-int(c["live"]), -(c["index"] or 0)))
    return out[:limit]
