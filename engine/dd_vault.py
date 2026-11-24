"""THE DAILY DRIVE - the Team Vault (owner idea, 2026-11-23).

A player with a favorite team who gives a rare answer sees one of that team's real plays, redrawn in retro pixels, and it
gets cooler at each level: Chunk Play, Bomb, Highlight Reel TD. The Vault never changes the score.

engine/dd_vault.json is built offline by scripts/dd_vault_build.py from two real sources:
  - nflverse play-by-play (1999 on): exact players, yards, throw depth and side; for 2016 on, all 22 players on the field
  - a hand-verified list of famous plays with a cited source, which is how pre-1999 legends get in
Ranking blends real popularity (Wikipedia pageviews for the play and its players) with how much the play mattered (win
probability swing and playoff stage). A play famous enough to have its own name outranks the rest. A jersey number that
cannot be confirmed stays blank.
"""
import json
import math
import os

from engine import dd_stadium

PATH = os.path.join(os.path.dirname(__file__), "dd_vault.json")
MAX_LEGENDS = 4             # plays per team at the top level
VERY_RARE_SHARE = 0.4       # of the remaining plays, the share at the middle level
PRIVATE = ("views", "score", "impact", "popularity", "source", "named")     # build-time fields the game doesn't need
_CACHE = {}


def popularity(m):
    views = m["views"]
    return int(views["moment"] + sum(views["players"].values()))


def score(m):
    """Popularity on a log scale (a superstar shouldn't drown out everything), lifted by how much the play mattered (0-1)."""
    return round(math.log10(1 + popularity(m)) * (1 + (m.get("impact") or 0)), 4)


def rank_team(moments):
    """Copies of one team's moments with `popularity`, `score` and `tier` set. Named plays (best score first) take the top
    level, or the single best play if the team has none; about 40% of the rest are level 5; the others are level 4."""
    items = [dict(m) for m in moments]
    for m in items:
        m["popularity"], m["score"] = popularity(m), score(m)
    best = sorted(items, key=lambda m: (-m["score"], m["id"]))
    named = [m for m in best if m["named"]]
    legends = named[:MAX_LEGENDS] or best[:1]
    top = {m["id"] for m in legends}
    rest = [m for m in best if m["id"] not in top]
    mid = max(1, round(len(rest) * VERY_RARE_SHARE)) if rest else 0
    for m in legends:
        m["tier"] = 6
    for i, m in enumerate(rest):
        m["tier"] = 5 if i < mid else 4
    return items


def load(path=PATH):
    if path not in _CACHE:
        with open(path, encoding="utf-8") as f:
            _CACHE[path] = json.load(f)
    return _CACHE[path]


def for_team(code, path=PATH):
    """{team, uniforms, moments} for the game. An unknown team or a missing file gives no moments. Never raises."""
    code = (code or "").upper()
    try:
        rows = [m for m in load(path)["moments"] if m["team"] == code]
    except Exception as e:
        print(f"[daily_drive] vault unavailable: {type(e).__name__}: {e}")
        rows = []
    moments = [{k: v for k, v in m.items() if k not in PRIVATE} for m in rows]
    codes = {code} | {m["opp"] for m in moments}
    uniforms = {c: dd_stadium._uniform(c) for c in codes if c in dd_stadium.UNIFORMS}
    return {"team": code, "uniforms": uniforms, "moments": moments}
