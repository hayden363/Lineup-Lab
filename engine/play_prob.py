"""
Chance a player listed Questionable or Doubtful actually plays.

Base rates come from engine/play_prob_factors.json, measured by
engine/play_prob_tuner.py on real nflverse injury reports and snap counts
(2016-2024). Practice participation moves the rate a lot (a Questionable WR who
practiced fully played about 82% of the time, one who did not practice about
46%), but no live feed carries it, so it is read from the wording of ESPN's
latest injury note when that note is recent. With no usable note the rate is the
position's overall rate for the status.

Out, IR, PUP and Sus are not handled here: they are a known zero.
"""
import json
import os
import re
from datetime import date, datetime

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "play_prob_factors.json")
try:
    with open(_PATH) as f:
        _F = json.load(f)["factors"]
except (OSError, ValueError) as e:
    print(f"[play_prob] couldn't read {_PATH} (no play-chance adjustment): {e}")
    _F = {}

NOTE_MAX_AGE_DAYS = 4
_RULED_OUT = re.compile(r"expected to miss|ruled out|will not play|won't play|unlikely to (play|suit)|not expected to play|sidelined", re.I)
_DNP = re.compile(r"non-?participant|did not practice|didn't practice|\bDNP\b|sat out (of )?practice|not practicing", re.I)
_LIMITED = re.compile(r"limited (participant|in practice|practice)|limited participation|\bLP\b|practiced in a limited", re.I)
_FULL = re.compile(r"full (participant|practice|participation)|practiced fully|practiced in full|expected to play|optimistic|should be (ok|fine|good)|will play|no limitations", re.I)
_PAST_GAME = re.compile(r"(won't|will not|didn't|did not) return|return(ed)? to (the|sunday|monday|thursday|saturday)", re.I)


def practice_from_note(note, updated=None, today=None):
    """'dnp' / 'limited' / 'full' / 'out' / None, from recent injury-note wording."""
    if not note or _PAST_GAME.search(note):
        return None
    if updated:
        try:
            when = datetime.fromisoformat(str(updated).replace("Z", "+00:00")).date()
            if ((today or date.today()) - when).days > NOTE_MAX_AGE_DAYS:
                return None
        except ValueError:
            return None
    if _RULED_OUT.search(note):
        return "out"
    for label, rx in (("dnp", _DNP), ("limited", _LIMITED), ("full", _FULL)):
        if rx.search(note):
            return label
    return None


def _rate(position, status, practice):
    for key in (f"{position}|{status}|{practice}", f"{position}|{status}", f"{status}|{practice}", status):
        if practice is None and key.endswith("|None"):
            continue
        hit = _F.get(key)
        if hit:
            return hit, key
    return None, None


def play_probability(position, status, report=None, today=None):
    """{"p_play", "n", "practice", "basis"} for a Questionable/Doubtful player,
    else None. `report` is the ESPN injury dict (note, updated) when we have it."""
    if status not in ("Questionable", "Doubtful"):
        return None
    report = report if isinstance(report, dict) else {}
    practice = practice_from_note(report.get("note"), report.get("updated"), today)
    if practice == "out":
        return {"p_play": 0.05, "n": None, "practice": "out",
                "basis": "his latest report says he is expected to miss the game"}
    hit, key = _rate(position, status, practice)
    if not hit:
        return None
    seen = {"dnp": "did not practice", "limited": "were limited in practice", "full": "practiced fully"}.get(practice)
    who = f"{position}s listed {status}" + (f" who {seen}" if seen else "")
    return {"p_play": hit["p_play"], "n": hit["n"], "practice": practice,
            "basis": f"{round(hit['p_play'] * 100)}% of {who} played ({hit['n']} past cases)"}
