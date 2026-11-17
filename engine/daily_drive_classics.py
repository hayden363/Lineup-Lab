"""
THE DAILY DRIVE - hand-curated "classic" NFL knowledge prompts (NOT WIRED IN)
=============================================================================
General NFL knowledge prompts whose answer banks are written and sourced by hand (engine/dd_classics/*.json), for the things
the stats data cannot tell us: Super Bowl history, award winners, stadiums, mascots, franchises, record clubs.

Each bank file is {version, key, cat, text, era ("pre2000" | "2000+" | "all"), group, sources, answers}; every answer is
{id, name, aliases, tier, note, source}. Tiers are EDITORIAL (the answer most fans name first is tier 1, a genuinely obscure
but valid answer is tier 6) and every bank has at least dd.MIN_ANSWERS answers and at least one tier-6 answer.
`aliases` are other accepted spellings (a team's old city, a stadium's old sponsor name); dd.check_answer treats an exact
alias as an exact answer.

classics_candidates(date_str) returns prompt dicts in the same shape as engine.daily_drive_pool.pool_candidates
(id, template, kind="history", text, category, cat, answers, threshold, group), ready for dd.pick_day. The banks are static,
so the date does not change the set; it is accepted so this can be dropped into the same candidate hooks. Fails soft: a
missing or broken file is skipped (and logged), never raised.
"""

import json
import logging
import os

from engine import daily_drive as dd

log = logging.getLogger(__name__)

BANK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dd_classics")
CATEGORY = "NFL history"
ERAS = ("pre2000", "2000+", "all")


def load_banks(bank_dir=None):
    """Every valid bank as a dict, sorted by key. A file that cannot be read or lacks the required fields is skipped."""
    bank_dir = bank_dir or BANK_DIR
    banks = []
    try:
        names = sorted(f for f in os.listdir(bank_dir) if f.endswith(".json"))
    except OSError as e:
        log.warning("dd_classics: cannot list %s: %s", bank_dir, e)
        return []
    for fn in names:
        try:
            with open(os.path.join(bank_dir, fn), encoding="utf-8") as fh:
                b = json.load(fh)
            if not (b.get("key") and b.get("cat") and b.get("text") and b.get("era") in ERAS and isinstance(b.get("answers"), list)):
                raise ValueError("missing key/cat/text/era/answers")
            for a in b["answers"]:
                if not (a.get("id") and a.get("name") and a.get("tier") in dd.TIERS):
                    raise ValueError("bad answer %r" % (a,))
            banks.append(b)
        except Exception as e:  # noqa: BLE001 - one bad file must not take the game down
            log.warning("dd_classics: skipped %s: %s", fn, e)
    return banks


def _answer(a):
    out = {"id": a["id"], "name": a["name"], "tier": a["tier"], "aliases": list(a.get("aliases") or [])}
    for k in dd.ANSWER_EXTRAS:
        out[k] = None
    out["stat_label"] = a.get("note") or None      # shown on the answer card when there is no numeric stat
    return out


def classic_prompt(bank):
    return {"id": "c:" + bank["key"], "template": "c:" + bank["key"], "kind": "history", "text": bank["text"],
            "category": CATEGORY, "cat": bank["cat"], "answers": [_answer(a) for a in bank["answers"]],
            "threshold": None, "group": bank.get("group") or ("c:" + bank["key"]), "era": bank["era"]}


# How hard a hand-written bank plays, by editorial judgement (an answer count says little here: "a team that has won a
# Super Bowl" has 20 answers and is a warm-up). Banks not listed fall back to dd.band_of_count.
CLASSIC_BAND = {
    "nfl-franchise": "easy", "nfl-mascot": "easy", "current-stadium": "easy", "sb-starting-qb-2000": "easy",
    "hof-quarterback": "easy", "sb-winning-teams": "easy", "sb-teams-2000": "easy",
    "sb-mvp-2000": "medium", "sb-winning-qb-2000": "medium", "nfl-mvp-2000": "medium", "first-overall-pick-2000": "medium",
    "career-rushing-10k": "medium", "sb-coach-2000": "medium", "nfl-oroy-2000": "medium", "nfl-opoy-2000": "medium",
    "team-no1-pick-2000": "medium", "sb-city-2000": "medium",
    "career-fg-400": "hard", "career-passing-47k": "hard", "career-receiving-13k": "hard", "career-sacks-100": "hard",
    "nfl-dpoy-2000": "hard", "nfl-droy-2000": "hard", "sb-coach-pre2000": "hard", "sb-mvp-pre2000": "hard",
    "sb-stadium-2000": "hard", "sb-winning-qb-pre2000": "hard", "team-new-stadium-2000": "hard",
}
# a bank that asks the same thing as a stats template shares its group, so a day never has both
SAME_AS = {"sb-starting-qb-2000": "h_sb_qb_played", "first-overall-pick-2000": "h_d_first_overall"}


def classics_candidates(date_str=None, bank_dir=None, banded=False):
    """Prompt dicts for every classic bank that meets the Daily Drive rules (>= MIN_ANSWERS answers, a tier-6 answer).
    `banded` (the easy -> hard days): every bank that is playable (dd.FLOOR answers, every tier), tagged with the band its
    answer count fits; general-knowledge banks count as warm-ups from dd.WARMUP_EASY_MIN answers."""
    try:
        out = []
        for b in load_banks(bank_dir):
            p = classic_prompt(b)
            if banded:
                band = CLASSIC_BAND.get(b["key"]) or dd.band_of_count(len(p["answers"]))
                if band and dd.playable(p["answers"]):
                    out.append({**p, "band": band, "pos_tag": None, "shape": None,
                                "group": SAME_AS.get(b["key"], p["group"])})
                continue
            if len(p["answers"]) >= dd.MIN_ANSWERS and dd.has_hall_of_famer(p["answers"]):
                out.append(p)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("dd_classics: candidates failed: %s", e)
        return []
