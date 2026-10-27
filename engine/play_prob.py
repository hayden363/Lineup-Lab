"""
Chance a player listed Questionable or Doubtful plays, used to scale his WEEKLY projection.

The policy (set by the product owner, not fitted):
    Out, IR, PUP, Sus   weekly projection 0 (handled by the callers: a known zero)
    Doubtful            projection x 0.25
    Questionable        projection x 0.90, unless he did NOT practice on the FRIDAY (the final
                        report of the week), then x 0.60
Routine practice maintenance never halves a projection: a Wednesday or Thursday
non-participant who is merely listed Questionable stays at x 0.90.

For reference only, engine/play_prob_factors.json holds the measured rates (nflverse injury
reports and snap counts, 2016-2024: Questionable overall played 70% of the time, a Questionable
WR who did not practice about 46%). They are returned as `p_history` but do not drive the
number. The 0.90 is therefore generous on average, by design.

Practice participation is not in any live feed: it is read from the wording of ESPN's latest
injury note when that note is recent, and "Friday" is the day that note was posted (Eastern time).
A note that says he is expected to miss the GAME still counts as ruled out (0.05); one that says he
is expected to miss PRACTICE does not.
"""
import json
import os
import re
from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:   # no tz database: fall back to UTC for the weekday check
    _ET = None

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "play_prob_factors.json")
try:
    with open(_PATH) as f:
        _F = json.load(f)["factors"]
except (OSError, ValueError) as e:
    print(f"[play_prob] couldn't read {_PATH} (no play-chance adjustment): {e}")
    _F = {}

NOTE_MAX_AGE_DAYS = 4
DOUBTFUL_P = 0.25
QUESTIONABLE_P = 0.90
QUESTIONABLE_FRIDAY_DNP_P = 0.60
OUT_NOTE_P = 0.05
FRIDAY = 4
_RULED_OUT = re.compile(r"expected to miss|ruled out|will not play|won't play|unlikely to (play|suit)|not expected to play|sidelined", re.I)
_DNP = re.compile(r"non-?participant|did not practice|didn't practice|\bDNP\b|sat out (of )?practice|not practicing", re.I)
_LIMITED = re.compile(r"limited (participant|in practice|practice)|limited participation|\bLP\b|practiced in a limited", re.I)
_FULL = re.compile(r"full (participant|practice|participation)|practiced fully|practiced in full|expected to play|optimistic|should be (ok|fine|good)|will play|no limitations", re.I)
_PAST_GAME = re.compile(r"(won't|will not|didn't|did not) return|return(ed)? to (the|sunday|monday|thursday|saturday)", re.I)


def _ruled_out(note):
    """True when the note says he will miss the GAME. "Expected to miss practice" is routine."""
    for m in _RULED_OUT.finditer(note):
        if not re.search(r"\bpractice", note[m.end():m.end() + 40], re.I):
            return True
    return False


def _posted_on_friday(updated):
    """True when the note's timestamp falls on a Friday in Eastern time."""
    try:
        when = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is not None and _ET is not None:
        when = when.astimezone(_ET)
    return when.weekday() == FRIDAY


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
    if _ruled_out(note):
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
    """{"p_play", "n", "practice", "p_history", "basis"} for a Questionable/Doubtful player, else None.
    `p_play` is the weekly-projection multiplier from the policy in the module docstring;
    `p_history` is the measured rate for reference. `report` is the ESPN injury dict (note, updated)."""
    if status not in ("Questionable", "Doubtful"):
        return None
    report = report if isinstance(report, dict) else {}
    practice = practice_from_note(report.get("note"), report.get("updated"), today)
    hit, _ = _rate(position, status, practice)
    hist = {"n": hit["n"], "p_history": hit["p_play"]} if hit else {"n": None, "p_history": None}
    if practice == "out":
        return {"p_play": OUT_NOTE_P, "practice": "out", **hist,
                "basis": "his latest report says he is expected to miss the game"}
    if status == "Doubtful":
        return {"p_play": DOUBTFUL_P, "practice": practice, **hist,
                "basis": f"listed Doubtful: projection x{DOUBTFUL_P:g}"}
    if practice == "dnp" and _posted_on_friday(report.get("updated")):
        return {"p_play": QUESTIONABLE_FRIDAY_DNP_P, "practice": practice, **hist,
                "basis": f"listed Questionable and did not practice Friday: projection x{QUESTIONABLE_FRIDAY_DNP_P:g}"}
    return {"p_play": QUESTIONABLE_P, "practice": practice, **hist,
            "basis": f"listed Questionable: projection x{QUESTIONABLE_P:g}"}
