"""
THE DAILY DRIVE VAULT - builds engine/dd_vault.json
====================================================
Run:  python scripts/dd_vault_build.py <folder with the slim nflverse files>   [--per-team 14]

Sources, all real:
  * engine/dd_vault_legends.json: hand-verified famous plays with a cited source (the only way pre-1999 plays get in)
  * nflverse play-by-play 1999-2025: exact players, yards, throw depth and side
  * nflverse participation + weekly rosters 2016-2025: all 22 players on the field with their positions and numbers
  * nflverse season rosters: cross-checks every jersey number
  * Wikipedia pageviews: how popular the play and its players are

Jersey rules: the play-by-play's own number wins, then the roster for that season and team. A legend's number that the
roster contradicts is blanked and reported. A blank jersey beats a wrong one.
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import dd_stadium, dd_vault  # noqa: E402

LEGENDS = os.path.join(os.path.dirname(dd_vault.PATH), "dd_vault_legends.json")
UA = "LineupLabResearch/1.0 (data analysis script)"
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "LA", "RAI": "LV", "RAM": "LA", "PHO": "ARI"}
STAGE = {"WC": 0.65, "DIV": 0.75, "CONF": 0.88, "SB": 1.0}
ROMAN = [(50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def team(code):
    c = str(code or "").upper()
    return FRANCHISE.get(c, c)


def roman(n):
    out = ""
    for v, s in ROMAN:
        while n >= v:
            out += s
            n -= v
    return out


def season_of(date):
    y, m = int(date[:4]), int(date[5:7])
    return y - 1 if m <= 2 else y


def jersey(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 100 else None


def last_name(name):
    parts = re.sub(r"\b(Jr|Sr|II|III|IV|V)\b\.?", "", str(name or "")).replace(",", " ").split()
    return parts[-1] if parts else ""


# ------------------------------------------------------------------ popularity
class Views:
    """Wikipedia pageviews (last 60 days) in batches of 50 titles, cached on disk so a rebuild is quick and polite."""

    def __init__(self, path):
        self.path = path
        self.got = json.load(open(path)) if os.path.exists(path) else {}

    def _batch(self, titles):
        out, cont = {}, {}
        while True:
            q = {"action": "query", "prop": "pageviews|pageprops", "ppprop": "disambiguation", "pvipdays": 60, "redirects": 1,
                 "titles": "|".join(titles), "format": "json", "formatversion": 2, **cont}
            time.sleep(2.2)
            req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q), headers={"User-Agent": UA})
            for attempt in range(4):
                try:
                    body = json.load(urllib.request.urlopen(req, timeout=30))
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 3:
                        raise
                    time.sleep(min(60, int(e.headers.get("Retry-After") or 20)))
            query = body.get("query", {})
            back = {}                                   # one page can answer several titles (a redirect and its target)
            for r in query.get("normalized", []):
                back.setdefault(r["to"], set()).add(r["from"])
            for r in query.get("redirects", []):
                back.setdefault(r["to"], set()).update(back.get(r["from"], {r["from"]}) | {r["from"]})
            for p in query.get("pages", []):
                if p.get("missing"):
                    continue
                keys = back.get(p["title"], set()) | {p["title"]}
                if (p.get("pageprops") or {}).get("disambiguation") is not None:
                    for k in keys:
                        out[k] = -1
                elif "pageviews" in p:                  # a page can arrive without counts until a later continuation
                    n = sum(v or 0 for v in p["pageviews"].values())
                    for k in keys:
                        out[k] = max(n, out.get(k, 0))
            if "continue" not in body:
                return out
            cont = body["continue"]

    def fetch(self, titles):
        todo = [t for t in dict.fromkeys(titles) if t not in self.got]
        for i in range(0, len(todo), 50):
            part = todo[i:i + 50]
            res = self._batch(part)
            for t in part:
                self.got[t] = res.get(t, res.get(t.replace("_", " "), 0))
            json.dump(self.got, open(self.path, "w"))

    def player(self, name):
        a = self.got.get(f"{name} (American football)", 0)
        return a if a > 0 else max(0, self.got.get(name, 0))


def player_titles(names):
    out = []
    for n in names:
        out += [n, f"{n} (American football)"]
    return out


# ------------------------------------------------------------------ the real play-by-play
def load_plays(folder):
    df = pd.concat([pd.read_pickle(f) for f in sorted(glob.glob(os.path.join(folder, "plays_*.pkl")))], ignore_index=True)
    df["team"], df["opp"] = df.posteam.map(team), df.defteam.map(team)
    stage = {}
    for season, g in df[df.season_type == "POST"].groupby("season"):
        for w, s in zip(sorted(g.week.unique()), ("WC", "DIV", "CONF", "SB")):
            stage[(season, w)] = s
    df["stage"] = [stage.get((s, w)) if t == "POST" else None for s, w, t in zip(df.season, df.week, df.season_type)]
    swing = df.wpa.clip(0, 0.6) / 0.6
    weight = df.stage.map(STAGE).fillna(0.42)
    df["impact"] = (weight * (0.55 + 0.45 * swing)).round(4)
    td = (df.touchdown == 1) & (df.td_team == df.posteam)
    df["scored"] = td
    keep = ((df.play_type == "pass") & df.receiver_player_id.notna()) | ((df.play_type == "run") & df.rusher_player_id.notna())
    return df[keep & (df.yards_gained > 0)].copy()


def rosters(folder):
    r = pd.read_pickle(os.path.join(folder, "rosters.pkl"))
    r["team"] = r.team.map(team)
    r["n"] = r.jersey_number.map(jersey)
    by_id, by_name = {}, {}
    for row in r.itertuples():
        if row.n is None or row.n != row.n:
            continue
        if row.gsis_id:
            by_id[(row.gsis_id, int(row.season))] = int(row.n)
        by_name.setdefault((int(row.season), row.team, str(row.full_name).lower()), set()).add(int(row.n))
    names = {row.gsis_id: row.full_name for row in r.itertuples() if row.gsis_id and row.full_name}
    return by_id, by_name, names


def weekly(folder):
    out = {}
    for f in glob.glob(os.path.join(folder, "week_*.pkl")):
        w = pd.read_pickle(f)
        for row in w.itertuples():
            if row.gsis_id:
                out[(row.gsis_id, int(row.season), int(row.week))] = (row.position, jersey(row.jersey_number))
                out.setdefault((row.gsis_id, int(row.season)), (row.position, jersey(row.jersey_number)))
    return out


def lineups(folder, week):
    out = {}
    for f in glob.glob(os.path.join(folder, "part_*.pkl")):
        p = pd.read_pickle(f)
        p = p[(p.n_offense == 11) & (p.n_defense == 11)]
        for row in p.itertuples():
            out[(row.nflverse_game_id, row.play_id)] = (row.offense_players, row.defense_players)
    return out


def build_lineup(ids, season, wk, week):
    rows = []
    for gid in str(ids).split(";"):
        info = week.get((gid, season, wk)) or week.get((gid, season))
        if not info or not info[0]:
            return None
        rows.append([str(info[0]), info[1]])
    return rows if len(rows) == 11 else None


def desc_number(desc, short):
    m = re.search(r"(\d{1,2})-" + re.escape(str(short)) + r"\b", str(desc or ""))
    return jersey(m.group(1)) if m else None


def side_of(loc):
    return {"left": -1, "right": 1}.get(str(loc), 0)


def game_label(r):
    if r.stage == "SB":
        return f"Super Bowl {roman(int(r.season) - 1965)}"
    if r.stage == "CONF":
        return "AFC Championship" if r.team in AFC else "NFC Championship"
    if r.stage == "DIV":
        return "Divisional Round"
    if r.stage == "WC":
        return "Wild Card"
    return f"Week {int(r.week)}"


AFC = {"BAL", "BUF", "CIN", "CLE", "DEN", "HOU", "IND", "JAX", "KC", "LAC", "LV", "MIA", "NE", "NYJ", "PIT", "TEN"}


def from_row(r, by_id, names, week, lu):
    season, pass_play = int(r.season), r.play_type == "pass"
    tid, tshort = (r.receiver_player_id, r.receiver_player_name) if pass_play else (r.rusher_player_id, r.rusher_player_name)
    players = []
    if pass_play:
        players.append({"name": names.get(r.passer_player_id) or str(r.passer_player_name), "number": desc_number(r.desc, r.passer_player_name) or by_id.get((r.passer_player_id, season)), "role": "qb"})
    players.append({"name": names.get(tid) or str(tshort), "number": desc_number(r.desc, tshort) or by_id.get((tid, season)), "role": "target"})
    frm, yards = int(r.yardline_100), int(r.yards_gained)
    air = None if not pass_play or r.air_yards != r.air_yards else int(r.air_yards)
    end = (max(101, min(108, 100 + max(0, (air or 0) - frm))) if r.scored else 100 - frm + yards)
    t = last_name(players[-1]["name"]).upper()
    title = f"{last_name(players[0]['name']).upper()} TO {t}" if pass_play else f"{t} BREAKS FREE"
    what = f"{yards}-yd TD" if r.scored else f"{yards}-yd {'catch' if pass_play else 'run'}"
    label = game_label(r)
    m = {"id": f"p-{r.game_id}-{int(r.play_id)}", "team": r.team, "opp": r.opp, "title": title, "sub": f"{what} · {label} · {str(r.game_date)[:4]}",
         "iso_date": str(r.game_date), "game": label, "kind": r.play_type, "side": side_of(r.pass_location if pass_play else r.run_location),
         "from": frm, "yards": yards, "end": end, "td": bool(r.scored), "leap": False, "players": players, "named": False, "impact": float(r.impact),
         "source": f"nflverse play-by-play {r.game_id} play {int(r.play_id)}"}
    if air is not None:
        m["air"] = air
    got = lu.get((r.game_id, r.play_id))
    if got:
        o, d = build_lineup(got[0], season, int(r.week), week), build_lineup(got[1], season, int(r.week), week)
        ids = str(got[0]).split(";")
        needed = [tid] + ([r.passer_player_id] if pass_play else [])
        if o and d and all(i in ids for i in needed):           # the play's own record wins for its stars' numbers
            known = {tid: players[-1]["number"]}
            if pass_play:
                known[r.passer_player_id] = players[0]["number"]
            for i, gid in enumerate(ids):
                if known.get(gid) is not None:
                    o[i][1] = known[gid]
            m["lineup"] = {"o": o, "d": d}
    return m


def pick_modern(df, per_team, views, by_id, names, week, lu):
    """The best real plays per team: shortlist by importance, then rank with popularity, with variety (one per game, no player hogging)."""
    out = {}
    short = df[(df.scored) | (df.yards_gained >= 40)].sort_values("impact", ascending=False).groupby("team").head(32)
    ids = set(short.receiver_player_id.dropna()) | set(short.rusher_player_id.dropna()) | set(short.passer_player_id.dropna())
    views.fetch(player_titles([names[i] for i in ids if i in names]))
    for tm, g in short.groupby("team"):
        rows = []
        for r in g.itertuples():
            m = from_row(r, by_id, names, week, lu)
            m["views"] = {"moment": 0, "players": {p["name"]: views.player(p["name"]) for p in m["players"]}}
            rows.append(m)
        rows.sort(key=lambda m: -dd_vault.score(m))
        chosen, games, tally = [], set(), {}
        for m in rows:
            gid, star = m["id"].rsplit("-", 1)[0], m["players"][-1]["name"]
            if gid in games or tally.get(star, 0) >= 3:
                continue
            games.add(gid); tally[star] = tally.get(star, 0) + 1
            chosen.append(m)
            if len(chosen) == per_team:
                break
        out[tm] = chosen
    return out


# ------------------------------------------------------------------ the hand-verified legends
def match_legend(leg, df):
    """The real play-by-play row for a post-1999 legend, or None."""
    if int(leg["date"][:4]) < 1999:
        return None
    rows = df[(df.game_date == leg["date"]) & (df.team == leg["team"]) & ((df.yards_gained - int(leg["yards"])).abs() <= 1)]
    t = last_name(leg["target"]["name"]).lower()
    hits = [r for r in rows.itertuples() if t and t in str(r.receiver_player_name if r.play_type == "pass" else r.rusher_player_name).lower()]
    return hits[0] if len(hits) == 1 else None


def build_legends(raw, df, views, by_id, by_name, names, week, lu, notes):
    out = []
    titles = []
    for x in raw:
        titles += player_titles([p["name"] for p in (x.get("qb"), x.get("target")) if p])
        if "wikipedia.org/wiki/" in x["source"]:
            titles.append(urllib.parse.unquote(x["source"].split("/wiki/")[1].split("#")[0]).replace("_", " "))
    views.fetch(titles)
    for x in raw:
        if x["team"] not in dd_stadium.UNIFORMS or x["opp"] not in dd_stadium.UNIFORMS or x["kind"] not in ("pass", "run", "fumble") or not x.get("target"):
            notes.append(f"dropped (bad fields): {x.get('title')}")
            continue
        season = season_of(x["date"])
        players = []
        for role, p in (("qb", x.get("qb")), ("target", x.get("target"))):
            if not p:
                continue
            n = jersey(p.get("number"))
            have = by_name.get((season, x["team"], p["name"].lower()))
            if n is not None and have and n not in have:
                notes.append(f"number blanked: {x['title']}: {p['name']} listed {n}, roster {season} says {sorted(have)}")
                n = None
            players.append({"name": p["name"], "number": n, "role": role})
        slug = re.sub(r"[^a-z0-9]+", "-", x["title"].lower()).strip("-")
        page = urllib.parse.unquote(x["source"].split("/wiki/")[1].split("#")[0]).replace("_", " ") if "wikipedia.org/wiki/" in x["source"] else None
        moment_views = max(0, views.got.get(page, 0)) if page else 0
        names_line = " to ".join(last_name(p["name"]) for p in players)
        yards = int(x["yards"])
        what = f"{yards}-yd TD" if x["td"] else f"{yards}-yd " + {"pass": "catch", "run": "run", "fumble": "play"}[x["kind"]]
        year = int(x["date"][:4])
        m = {"id": f"l-{x['team'].lower()}-{slug}", "team": x["team"], "opp": x["opp"], "title": x["title"],
             "sub": f"{names_line} · {what} · {x['game']} · {year}", "iso_date": x["date"], "game": x["game"], "kind": x["kind"],
             "side": int(x.get("side") or 0), "from": int(x.get("from") or yards), "yards": yards, "td": bool(x["td"]), "leap": bool(x.get("leap")),
             "players": players, "named": bool(x.get("named")), "source": x["source"], "impact": STAGE["SB"] if "Super Bowl" in x["game"] else STAGE["CONF"] if "Championship" in x["game"] else 0.7,
             "views": {"moment": moment_views, "players": {p["name"]: views.player(p["name"]) for p in players}}}
        m["end"] = max(101, 100 + min(8, int(x.get("depth") or 1))) if m["td"] else 100 - m["from"] + yards
        row = match_legend(x, df)
        if row is not None:                 # a modern legend gets the record's exact numbers, depth, side and all 22 players
            real = from_row(row, by_id, names, week, lu)
            m["from"], m["yards"], m["end"], m["side"] = real["from"], real["yards"], real["end"], real["side"]
            for k in ("air", "lineup"):
                if k in real:
                    m[k] = real[k]
            for p, q in zip(sorted(m["players"], key=lambda z: z["role"]), sorted(real["players"], key=lambda z: z["role"])):
                if q["number"] is not None:
                    if p["number"] not in (None, q["number"]):
                        notes.append(f"number corrected from the record: {x['title']}: {p['name']} {p['number']} -> {q['number']}")
                    p["number"] = q["number"]
            m["pbp"] = real["id"]
        elif year >= 2000:
            notes.append(f"no exact play-by-play match, kept from its source: {x['title']} ({x['date']})")
        out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--per-team", type=int, default=14)
    args = ap.parse_args()
    df = load_plays(args.folder)
    by_id, by_name, names = rosters(args.folder)
    week = weekly(args.folder)
    lu = lineups(args.folder, week)
    views = Views(os.path.join(args.folder, "views.json"))
    notes = []
    legends = build_legends(json.load(open(LEGENDS, encoding="utf-8")), df, views, by_id, by_name, names, week, lu, notes)
    modern = pick_modern(df, args.per_team, views, by_id, names, week, lu)
    out = []
    for tm in sorted(dd_stadium.UNIFORMS):
        mine = [m for m in legends if m["team"] == tm]
        taken = {m.get("pbp") for m in mine}
        seen_ids, unique = set(), []
        for m in mine:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"]); unique.append(m)
            else:
                notes.append(f"duplicate legend skipped: {m['id']}")
        games = {m["iso_date"] for m in unique}
        extra = [m for m in modern.get(tm, []) if m["id"] not in taken and m["iso_date"] not in games]
        ranked = dd_vault.rank_team(unique + extra)
        for m in ranked:
            m.pop("pbp", None)
        out += sorted(ranked, key=lambda m: (-m["tier"], -m["score"]))
    body = {"built": time.strftime("%Y-%m-%d"), "moments": out}
    with open(dd_vault.PATH, "w", encoding="utf-8") as f:
        json.dump(body, f, separators=(",", ":"), ensure_ascii=False)
    full = sum(1 for m in out if m.get("lineup"))
    print(f"{len(out)} moments, {len({m['team'] for m in out})} teams, {sum(1 for m in out if m['iso_date'] < '1999')} before 1999, "
          f"{full} with all 22 real players, file {os.path.getsize(dd_vault.PATH) / 1000:.0f} KB")
    print("per level:", {t: sum(1 for m in out if m["tier"] == t) for t in (6, 5, 4)})
    with open(os.path.join(args.folder, "build_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes))
    print(len(notes), "notes")


if __name__ == "__main__":
    main()
