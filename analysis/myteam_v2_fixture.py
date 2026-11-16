"""Fixture data for eyeballing the My Team screen without a signed-in DB: writes analysis/myteam-v2-shots/fixture.json with
the /api/myteam body plus /api/myteam/live bodies for pre / in-game / final, shaped like the real API. Live bodies are built
by the real engine (myteam_live.compose + win_prob) from made-up players, points and clocks. Screenshots only, not data."""
import json
import sys
import time

sys.path.insert(0, ".")
from engine import myteam_live as ml, win_prob

NOW = time.time()
ROSTER = {
    "me": [("QB", "Jared Goff", "DET", 21.4), ("RB", "Saquon Barkley", "PHI", 17.9), ("RB", "Bijan Robinson", "ATL", 16.2),
           ("WR", "Puka Nacua", "LA", 15.8), ("WR", "Amon-Ra St. Brown", "DET", 15.1), ("TE", "Trey McBride", "ARI", 11.7),
           ("FLEX", "Jaylen Waddle", "MIA", 12.3), ("DEF", "Denver Broncos", "DEN", 8.4), ("K", "Brandon Aubrey", "DAL", 8.9)],
    "opp": [("QB", "Josh Allen", "BUF", 23.0), ("RB", "Derrick Henry", "BAL", 16.4), ("RB", "Jahmyr Gibbs", "DET", 15.5),
            ("WR", "Ja'Marr Chase", "CIN", 17.6), ("WR", "CeeDee Lamb", "DAL", 14.3), ("TE", "Brock Bowers", "LV", 12.9),
            ("FLEX", "DK Metcalf", "PIT", 11.0), ("DEF", "Houston Texans", "HOU", 7.6), ("K", "Harrison Butker", "KC", 8.2)],
}
BENCH = [("RB", "Rhamondre Stevenson", "NE", 7.4), ("WR", "Rashee Rice", "KC", 9.8)]


def team(key, rid, name, bench):
    players = []
    for i, (slot, nm, tm, proj) in enumerate(ROSTER[key] + (BENCH if bench else [])):
        pos = "DEF" if slot == "DEF" else ("K" if slot == "K" else (slot if slot != "FLEX" else "WR"))
        players.append({"player_id": f"{key}{i}", "player_display_name": nm, "position": pos, "slot": slot, "recent_team": tm,
                        "is_starter": i < len(ROSTER[key]), "PROJ": proj, "SCORE": None if pos in ("K", "DEF") else 60.0,
                        "floor": round(proj * .55), "ceiling": round(proj * 1.6), "p_play": 0.97, "headshot_url": None})
    tot = round(sum(p["PROJ"] for p in players if p["is_starter"]), 1)
    return {"roster_id": rid, "team_name": name, "avatar_url": None, "total_proj": tot, "players": players}


def myteam():
    mine, opp = team("me", 1, "Bye Week Bandits", True), team("opp", 2, "Waiver Wire Warriors", True)
    d = {"nfl_week": 11, "live_week": 11, "regular_season_weeks": 14, "league_name": "Dynasty Degenerates", "my_team": mine, "opponent": opp,
         "league_matchups": [{"teams": [{"roster_id": 1, "team_name": mine["team_name"], "total_proj": mine["total_proj"], "avatar_url": None},
                                        {"roster_id": 2, "team_name": opp["team_name"], "total_proj": opp["total_proj"], "avatar_url": None}]}]}
    d["win_prob"] = win_prob.pregame_win_prob(mine, opp)
    return d


def game(home, away, state, period=0, clock=None, hs=0, as_=0, kick=0):
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + kick))
    return {"game_id": home + away, "week": 11, "kickoff": iso, "state": state, "period": period, "display_clock": clock,
            "status_detail": "", "home": {"abbr": home, "score": hs}, "away": {"abbr": away, "score": as_}}


def live(data, scenario):
    teams = {"DET": "GB", "PHI": "WSH", "ATL": "NO", "LA": "SEA", "ARI": "SF", "MIA": "NYJ", "DEN": "LV", "DAL": "NYG", "BUF": "NE", "BAL": "CLE",
             "CIN": "TB", "PIT": "CHI", "HOU": "TEN", "KC": "IND"}
    games = []
    for h, a in teams.items():
        if scenario == "pre":
            games.append(game(h, a, "pre", kick=4 * 3600))
        elif scenario == "final":
            games.append(game(h, a, "post", period=4, clock="0:00", hs=24, as_=17))
        elif h in ("DET", "PHI", "ATL"):
            games.append(game(h, a, "post", period=4, clock="0:00", hs=27, as_=20))
        elif h in ("LA", "ARI", "MIA", "BUF"):
            games.append(game(h, a, "in", period=3, clock="8:41", hs=17, as_=13))
        else:
            games.append(game(h, a, "pre", kick=3 * 3600))
    pts = {1: {}, 2: {}}
    rid = {"me": 1, "opp": 2}
    for key in ("me", "opp"):
        for i, (slot, nm, tm, proj) in enumerate(ROSTER[key]):
            f = {"final": 1.18, "pre": 0}.get(scenario, 0.6 if tm in ("LA", "ARI", "MIA", "BUF") else (1.1 if tm in ("DET", "PHI", "ATL") else 0))
            if scenario == "in" and key == "opp" and tm in ("BUF", "DAL"):
                f = 0.4 if tm == "BUF" else 0
            if f:
                pts[rid[key]][f"{key}{i}"] = round(proj * f * (0.8 + 0.07 * ((i * 7) % 5)), 2)
    base = {"week": 11, "live_week": 11, "platform": "sleeper",
            "my_team": {"roster_id": 1, "starters": [], "bench": []}, "opponent": {"roster_id": 2, "starters": []}}
    inner = ml.make_base({"nfl_week": 11, "live_week": 11, "my_team": data["my_team"], "opponent": data["opponent"]}, {}, "sleeper")
    return ml.compose(inner, games, {"source": "sleeper", "by_roster": pts}, now=NOW)


if __name__ == "__main__":
    d = myteam()
    out = {"myteam": d, "live": {s: live(d, s) for s in ("pre", "in", "final")}}
    with open("analysis/myteam-v2-shots/fixture.json", "w") as f:
        json.dump(out, f)
    for s, l in out["live"].items():
        print(s, l["win_prob"], l["my_team"]["points_total"], l["my_team"]["live_proj_total"], l["opponent"]["points_total"], l["opponent"]["live_proj_total"])
    print("pregame", d["win_prob"])
