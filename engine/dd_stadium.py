"""THE DAILY DRIVE - the favorite-team stadium (owner idea, 2026-11-16).

A signed-in player with a favorite team plays on that team's field: their colors on the turf, the end zones and the
crowd, their real starters' jersey numbers (no names), and this week's real opponent on defense in road whites.

Rosters change slowly and the owner asked for this to be cheap, so the numbers are built ONCE, offline, into
engine/dd_stadium.json from data already on disk:
  - offense skill players (RB, 2 WR, TE): the nflverse depth chart (latest snapshot, rank 1-2)
  - defense (4 DL, 2 LB, 2 CB, 2 S) and jersey numbers: Sleeper's player list (depth_chart_order 1)
  - offensive line: Sleeper has no line order, so 5 real active linemen (most experienced first)
  - roof, surface, stadium name and the full regular-season schedule: the nflverse schedule
The QB keeps the question number (owner, 2026-11-16), so the QB's real number is not used on the field.

Rebuild whenever fresher numbers are wanted:
    python -m engine.dd_stadium
"""
import datetime
import json
import os
import time
from collections import Counter

PATH = os.path.join(os.path.dirname(__file__), "dd_stadium.json")
_CACHE = {}

# Home uniforms, stylized: jersey, number, number trim, helmet, helmet stripe ("" = none), pants.
# Road whites for the opponent are derived from the same row (white jersey, numbers in the home jersey color).
UNIFORMS = {
    "ARI": ["#97233F", "#FFFFFF", "#000000", "#F4F4F4", "#97233F", "#FFFFFF"],
    "ATL": ["#101820", "#FFFFFF", "#A71930", "#101820", "#A71930", "#FFFFFF"],
    "BAL": ["#241773", "#FFFFFF", "#9E7C0C", "#101820", "#241773", "#FFFFFF"],
    "BUF": ["#00338D", "#FFFFFF", "#C60C30", "#F4F4F4", "#C60C30", "#FFFFFF"],
    "CAR": ["#101820", "#0085CA", "#FFFFFF", "#BFC0BF", "#0085CA", "#BFC0BF"],
    "CHI": ["#0B162A", "#FFFFFF", "#C83803", "#0B162A", "#C83803", "#FFFFFF"],
    "CIN": ["#101820", "#FFFFFF", "#FB4F14", "#FB4F14", "#101820", "#FFFFFF"],
    "CLE": ["#311D00", "#FFFFFF", "#FF3C00", "#FF3C00", "#311D00", "#FFFFFF"],
    "DAL": ["#041E42", "#FFFFFF", "#869397", "#B0B7BC", "#041E42", "#B0B7BC"],
    "DEN": ["#FB4F14", "#002244", "#FFFFFF", "#002244", "#FB4F14", "#FFFFFF"],
    "DET": ["#0076B6", "#FFFFFF", "#B0B7BC", "#B0B7BC", "#0076B6", "#B0B7BC"],
    "GB":  ["#203731", "#FFFFFF", "#FFB612", "#FFB612", "#203731", "#FFB612"],
    "HOU": ["#03202F", "#FFFFFF", "#A71930", "#03202F", "#A71930", "#FFFFFF"],
    "IND": ["#002C5F", "#FFFFFF", "#A2AAAD", "#F4F4F4", "#002C5F", "#FFFFFF"],
    "JAX": ["#006778", "#FFFFFF", "#D7A22A", "#101820", "#D7A22A", "#FFFFFF"],
    "KC":  ["#E31837", "#FFFFFF", "#FFB81C", "#E31837", "#FFFFFF", "#FFFFFF"],
    "LV":  ["#101820", "#FFFFFF", "#A5ACAF", "#A5ACAF", "#101820", "#A5ACAF"],
    "LAC": ["#0080C6", "#FFFFFF", "#FFC20E", "#F4F4F4", "#FFC20E", "#FFFFFF"],
    "LA":  ["#003594", "#FFFFFF", "#FFD100", "#003594", "#FFD100", "#FFFFFF"],
    "MIA": ["#008E97", "#FFFFFF", "#FC4C02", "#F4F4F4", "#008E97", "#FFFFFF"],
    "MIN": ["#4F2683", "#FFFFFF", "#FFC62F", "#4F2683", "#FFFFFF", "#FFFFFF"],
    "NE":  ["#002244", "#FFFFFF", "#C60C30", "#B0B7BC", "#002244", "#002244"],
    "NO":  ["#101820", "#D3BC8D", "#FFFFFF", "#D3BC8D", "#101820", "#D3BC8D"],
    "NYG": ["#0B2265", "#FFFFFF", "#A71930", "#0B2265", "", "#A5ACAF"],
    "NYJ": ["#125740", "#FFFFFF", "#101820", "#125740", "", "#FFFFFF"],
    "PHI": ["#004C54", "#FFFFFF", "#A5ACAF", "#004C54", "#A5ACAF", "#FFFFFF"],
    "PIT": ["#101820", "#FFB612", "#FFFFFF", "#101820", "#FFB612", "#FFB612"],
    "SF":  ["#AA0000", "#FFFFFF", "#101820", "#B3995D", "#AA0000", "#B3995D"],
    "SEA": ["#002244", "#FFFFFF", "#69BE28", "#1E3A5F", "#69BE28", "#A5ACAF"],
    "TB":  ["#D50A0A", "#FFFFFF", "#34302B", "#34302B", "#D50A0A", "#34302B"],
    "TEN": ["#0C2340", "#FFFFFF", "#4B92DB", "#0C2340", "#4B92DB", "#FFFFFF"],
    "WAS": ["#5A1414", "#FFB612", "#FFFFFF", "#5A1414", "#FFB612", "#FFB612"],
}
TEAMS = sorted(UNIFORMS)
# nflverse codes the app uses -> Sleeper's team codes, where they differ
SLEEPER_CODE = {"LA": "LAR"}

EDGE = ("LDE", "RDE", "LOLB", "ROLB")
INSIDE = ("NT", "LDT", "RDT", "DT")
ILB = ("LILB", "RILB", "MLB", "WLB", "SLB")
OL_POS = ("T", "G", "C", "OL", "OT", "OG")
FALLBACK = {"dl": ("DE", "DT", "NT", "DL"), "lb": ("LB", "ILB", "OLB"), "cb": ("CB",), "s": ("S", "SS", "FS", "DB"),
            "rb": ("RB",), "wr": ("WR",), "te": ("TE",)}


def _norm(name):
    s = "".join(ch for ch in str(name or "").lower() if ch.isalnum() or ch == " ")
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v"))


def _num(p):
    n = p.get("number")
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 99 else None


def _team_numbers(code, dc, players):
    """{rb, wr:[2], te, ol:[5], dl:[4], lb:[2], cb:[2], s:[2], bench:[...]} of real jersey numbers for one team."""
    sc = SLEEPER_CODE.get(code, code)
    mine = [p for p in players if p.get("team") == sc and p.get("active") and _num(p) is not None]
    by_gsis = {p.get("gsis_id"): p for p in mine if p.get("gsis_id")}
    by_name = {_norm(p.get("full_name")): p for p in mine if p.get("full_name")}   # Sleeper often lacks gsis ids
    used = set()

    def take(p):
        if p is None:
            return None
        n = _num(p)
        if n is None or n in used:
            return None
        used.add(n)
        return n

    def from_depth(pos, k):
        rows = dc[(dc["team"] == code) & (dc["pos_abb"] == pos)].sort_values("pos_rank")
        out = []
        for g, name in zip(rows["gsis_id"], rows["player_name"]):
            n = take(by_gsis.get(g) or by_name.get(_norm(name)))
            if n is not None:
                out.append(n)
            if len(out) == k:
                break
        return out

    def from_slots(slots, k):
        out = []
        for slot in slots:
            for p in mine:
                if p.get("depth_chart_position") == slot and p.get("depth_chart_order") == 1:
                    n = take(p)
                    if n is not None:
                        out.append(n)
                        break
            if len(out) == k:
                break
        return out

    def fill(out, group, k):
        for p in sorted(mine, key=lambda p: -(p.get("years_exp") or 0)):
            if len(out) >= k:
                break
            if p.get("position") in FALLBACK[group]:
                n = take(p)
                if n is not None:
                    out.append(n)
        return out

    rb = fill(from_depth("RB", 1), "rb", 1)
    wr = fill(from_depth("WR", 2), "wr", 2)
    te = fill(from_depth("TE", 1), "te", 1)
    ol = []
    for p in sorted([p for p in mine if p.get("position") in OL_POS],
                    key=lambda p: (p.get("depth_chart_position") != "OL", -(p.get("years_exp") or 0), _num(p))):
        n = take(p)
        if n is not None:
            ol.append(n)
        if len(ol) == 5:
            break
    edges = from_slots(EDGE, 2)
    inside = from_slots(INSIDE, 2)
    dl = fill(edges[:1] + inside + edges[1:], "dl", 4)
    if len(edges) >= 2 and len(inside) >= 2:
        dl = [edges[0], inside[0], inside[1], edges[1]]
    lb = fill(from_slots(ILB, 2), "lb", 2)
    if len(lb) < 2:                           # 3-4 fronts: the second edge stays on the line, so take another backer
        lb = fill(lb, "lb", 2)
    cb = fill(from_slots(("LCB", "RCB"), 2), "cb", 2)
    s = fill(from_slots(("FS", "SS"), 2), "s", 2)
    bench = []
    for p in sorted(mine, key=lambda p: _num(p)):
        if len(bench) >= 26:
            break
        if p.get("position") in ("K", "P", "LS"):
            continue
        n = take(p)
        if n is not None:
            bench.append(n)
    return {"rb": rb, "wr": wr, "te": te, "ol": ol, "dl": dl, "lb": lb, "cb": cb, "s": s, "bench": bench}


def _home_venue(code, sched):
    home = sched[(sched["home_team"] == code) & (sched["game_type"] == "REG")]
    roof = Counter(home["roof"].dropna()).most_common(1)
    surf = Counter(home["surface"].dropna()).most_common(1)
    stad = Counter(home["stadium"].dropna()).most_common(1)
    roof = roof[0][0] if roof else "outdoors"
    surf = (surf[0][0] if surf else "grass").strip().lower()
    return {"roof": "dome" if roof in ("dome", "closed") else "open" if roof == "open" else "outdoors",
            "surface": "grass" if surf in ("grass", "") else "turf",
            "stadium": stad[0][0] if stad else ""}


def build(path=PATH, data_dir="data_cache", verbose=True):
    import pandas as pd
    dc = pd.read_parquet(os.path.join(data_dir, "depth_charts_2026.parquet"))
    dc = dc[dc["dt"] == dc["dt"].max()]
    with open(os.path.join(data_dir, "sleeper_all_players.json"), encoding="utf-8") as f:
        players = list(json.load(f).values())
    sched = pd.read_parquet(os.path.join(data_dir, "schedule_2026.parquet"))
    reg = sched[sched["game_type"] == "REG"]
    teams = {}
    for code in TEAMS:
        games = []
        for _, g in reg[(reg["home_team"] == code) | (reg["away_team"] == code)].sort_values("week").iterrows():
            games.append([int(g["week"]), str(g["gameday"]), g["away_team"] if g["home_team"] == code else g["home_team"]])
        dg = reg[((reg["home_team"] == code) | (reg["away_team"] == code)) & (reg["div_game"] == 1)]
        div = sorted({a if h == code else h for h, a in zip(dg["home_team"], dg["away_team"])})
        teams[code] = {**_team_numbers(code, dc, players), **_home_venue(code, sched), "games": games,
                       "rival": div[0] if div else ""}
    body = {"built": time.strftime("%Y-%m-%d"), "depth_chart": str(dc["dt"].max()), "teams": teams}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, separators=(",", ":"), sort_keys=True)
    if verbose:
        short = [c for c, t in teams.items() if len(t["ol"]) < 5 or len(t["dl"]) < 4 or len(t["wr"]) < 2]
        print(f"[stadium] {len(teams)} teams -> {path} ({os.path.getsize(path) / 1e3:.0f} KB); short: {short or 'none'}")
    return body


def load(path=PATH):
    if path not in _CACHE:
        with open(path, encoding="utf-8") as f:
            _CACHE[path] = json.load(f)
    return _CACHE[path]


def opponent(code, today, teams):
    """This week's real opponent (NFL weeks run Tuesday to Monday). A bye week, or no game left, falls back to a
    division rival."""
    start = today - datetime.timedelta(days=(today.weekday() - 1) % 7)       # the Tuesday that opened this week
    end = start + datetime.timedelta(days=6)
    for _wk, day, opp in teams[code]["games"]:
        try:
            d = datetime.date.fromisoformat(day)
        except ValueError:
            continue
        if start <= d <= end and opp in teams:
            return opp
    rival = teams[code].get("rival")
    return rival if rival in teams else next(c for c in TEAMS if c != code)


def _uniform(code):
    j, n, t, h, s, p = UNIFORMS[code]
    return {"jersey": j, "num": n, "trim": t, "helmet": h, "stripe": s, "pants": p}


def stadium(code, today, path=PATH):
    """The field skin for a favorite team, or None for an unknown code or a missing snapshot. Never raises."""
    code = (code or "").upper()
    if code not in UNIFORMS:
        return None
    try:
        teams = load(path)["teams"]
    except Exception as e:
        print(f"[daily_drive] stadium snapshot unavailable: {type(e).__name__}: {e}")
        return None
    if code not in teams:
        return None
    t, opp = teams[code], opponent(code, today, teams)
    o = teams[opp]
    keep = ("rb", "wr", "te", "ol")
    return {
        "home": {"code": code, "uniform": _uniform(code), "numbers": {k: t[k] for k in keep}, "bench": t["bench"],
                 "roof": t["roof"], "surface": t["surface"], "stadium": t["stadium"]},
        "away": {"code": opp, "uniform": _uniform(opp), "numbers": {k: o[k] for k in ("dl", "lb", "cb", "s")},
                 "bench": o["bench"]},
    }


if __name__ == "__main__":
    build()
