"""
START/SIT WRITE-UP — Claude explains the engine's numbers
=========================================================
Optional (needs ANTHROPIC_API_KEY, same as the news summaries). Claude gets the
engine's computed facts for each player and writes the diagnostics, floor and
ceiling scenarios, and the pivot rule. It does not pick the player or invent
numbers: the verdict and confidence come from engine/decision.py, and any
metric we don't have (DVOA, route participation, coverage splits) must be
called out as unavailable rather than estimated.
"""

import hashlib
import json
import time

from . import news

MODEL = news.AI_SUMMARY_MODEL
TTL = 60 * 60
_CACHE = {}

SYSTEM = """You are the lead quantitative analyst for a fantasy football start/sit tool. You explain a decision the
platform's model has already made, using only the data you are given.

Rules:
- Use ONLY the numbers in the provided JSON. Never invent stats, ranks, DVOA, route participation, coverage
  (man/zone) splits, pressure numbers or quotes. If a metric isn't in the data, say it isn't available.
- The primary recommendation and confidence are fixed by the model: restate them, don't change them.
- Opportunity over box score: lean on expected points (xFP), snap share, target share, high-value touches,
  game-script work share, Vegas implied total and spread, and the matchup flags.
- Plain English, short sentences, no betting advice.

Return ONLY a JSON object with these keys:
{"diagnostics": [{"player": "<name>", "case": "<2-3 sentences: why he wins or loses this matchup>"}],
 "floor_case": "<2-3 sentences: how low it goes if the game goes wrong, citing p10 numbers>",
 "ceiling_case": "<2-3 sentences: what has to happen for 20+, citing p90 and P(20+)>",
 "final_call": "<1-2 sentences: the default start and the exact situation to pivot>"}"""


def configured():
    return bool(news.ANTHROPIC_API_KEY)


def facts(result):
    """The compact, numbers-only view of a start_sit() result Claude sees."""
    out = {"mode": result.get("mode"), "verdict": result.get("decision"), "players": []}
    for p in result.get("players", []):
        if p.get("error"):
            continue
        d, o = p.get("decision") or {}, p.get("outcomes") or {}
        g = (p.get("environment") or {}).get("game") or {}
        out["players"].append({
            "name": p.get("player_display_name"), "position": p.get("position"), "team": p.get("recent_team"),
            "opponent": d.get("opponent"), "projection": round(p.get("PROJ") or 0, 1),
            "p10": o.get("p10"), "median": o.get("p50"), "p90": o.get("p90"),
            "chance_10_plus_pct": o.get("p_10plus"), "chance_20_plus_pct": o.get("p_20plus"),
            "rating_0_100": d.get("rating"), "rating_parts": d.get("components"),
            "snap_pct_last_game": d.get("snap_pct"), "target_share_pct": d.get("target_share"),
            "high_value_touches_per_game": d.get("hvt_pg"), "xfp_per_game": d.get("xfp_pg"),
            "points_vs_xfp_per_game": d.get("xfp_diff"), "td_share_of_points_pct": d.get("td_share"),
            "work_share_when_leading_vs_trailing": d.get("script_split"),
            "defense_rank_vs_position_1_is_easiest": d.get("defense_rank"),
            "vegas": {"implied_team_total": g.get("implied_total"), "spread_margin_positive_is_favored": g.get("margin"),
                      "game_total": g.get("game_total")},
            "weather": g.get("weather"), "injury_status": p.get("injury_status"),
            "advantages": d.get("flags_good"), "warnings": d.get("flags_bad"),
        })
    return out


def write_up(result):
    """{"diagnostics", "floor_case", "ceiling_case", "final_call"} or None."""
    if not configured():
        return None
    f = facts(result)
    if len(f["players"]) < 2:
        return None
    key = hashlib.sha256(json.dumps(f, sort_keys=True, default=str).encode()).hexdigest()
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=news.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=MODEL, max_tokens=900, system=SYSTEM,
            messages=[{"role": "user", "content": "Data:\n" + json.dumps(f, default=str)}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1])
        out = {k: parsed.get(k) for k in ("diagnostics", "floor_case", "ceiling_case", "final_call")}
    except Exception as e:
        print(f"[startsit-ai] write-up failed: {e}")
        return None
    _CACHE[key] = (time.time(), out)
    return out
