"""
THE DAILY DRIVE - saved scores, signed answer tokens, community stats
=====================================================================
Pure functions (no DB, no network) so the integrity and the math are unit-testable; engine/db.py does the storage.

INTEGRITY. The browser never tells the server a score. /api/play/check hands back, for every accepted answer, a short
HMAC token over (date, prompt_id, answer_id, tier). /api/play/score receives only those tokens; the server verifies
each one, keeps one per prompt, looks the tier up again in the puzzle, and recomputes the yards itself. A made-up
token fails the HMAC; a real token for another day fails (the date is inside the MAC); a lower-tier token can't be
upgraded (the tier is inside the MAC and is re-checked against the puzzle).

The MAC key is derived from the app's existing secret (APP_SECRET_KEY, else the key engine/crypto.py already
generates and keeps in .app_secret_key), so there is no new environment variable. If no key can be read at all,
signing returns None and scoring is switched off (the game itself still plays).
"""

import base64
import datetime as dt
import hashlib
import hmac
import os
import re
import statistics

from engine import daily_drive as dd

N_PROMPTS = dd.N_FANTASY + dd.N_HISTORY
MAX_YARDS = 100 * N_PROMPTS                      # 700
SACK = "\U0001F7E5"
_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


# ------------------------------------------------------------------------------------------------ signing
def _key():
    """Derived HMAC key, or None when no app secret is readable. Domain-separated from the Fernet use of the secret."""
    try:
        raw = os.environ.get("APP_SECRET_KEY")
        if raw:
            raw = raw.encode("utf-8")
        else:
            from engine import crypto
            raw = crypto._load_or_create_key()
        return hashlib.sha256(b"daily-drive-score-v1|" + raw).digest()
    except Exception:
        return None


def enabled():
    """True when a signing secret is readable (otherwise scoring is switched off and the game still plays)."""
    return _key() is not None


def _b64(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(key, date_str, payload):
    return hmac.new(key, f"{date_str}|{payload}".encode("utf-8"), hashlib.sha256).digest()[:16]


def sign_token(date_str, prompt_id, answer_id, tier, key=None):
    """Token for one accepted answer: base64(prompt_id|answer_id|tier) + "." + 128-bit truncated HMAC. None if no key."""
    key = key or _key()
    if not key:
        return None
    payload = f"{prompt_id}|{answer_id}|{int(tier)}"
    return _b64(payload.encode("utf-8")) + "." + _b64(_mac(key, date_str, payload))


def verify_token(date_str, token, key=None):
    """(prompt_id, answer_id, tier) if the token is genuine for this date, else None. Constant-time compare."""
    key = key or _key()
    if not key or not isinstance(token, str) or token.count(".") != 1 or len(token) > 400:
        return None
    try:
        left, right = token.split(".")
        payload = _unb64(left).decode("utf-8")
        given = _unb64(right)
        parts = payload.split("|")
        if len(parts) < 3:
            return None
        tier = int(parts[-1])
        answer_id = parts[-2]
        prompt_id = "|".join(parts[:-2])
    except Exception:
        return None
    if not hmac.compare_digest(_mac(key, date_str, payload), given) or tier not in dd.TIERS:
        return None
    return prompt_id, answer_id, tier


def score_from_tokens(date_str, tokens, prompts, key=None):
    """Server-side scoring. `prompts` = the day's puzzle prompts in order. Returns (yards, tiers) with one tier per
    prompt (0 = no accepted answer), or raises ValueError('...') when any token is forged, stale or inconsistent.
    The yards come from the puzzle's own answer bank, never from anything the browser said."""
    by_id = {p["id"]: i for i, p in enumerate(prompts)}
    tiers = [0] * len(prompts)
    for tok in tokens or []:
        v = verify_token(date_str, tok, key)
        if v is None:
            raise ValueError("invalid score token")
        prompt_id, answer_id, tier = v
        i = by_id.get(prompt_id)
        if i is None:
            raise ValueError("invalid score token")
        match = next((a for a in prompts[i]["answers"] if a["id"] == answer_id), None)
        if match is None or match["tier"] != tier:
            raise ValueError("invalid score token")
        if not tiers[i]:                                  # one answer counts per prompt: the first token wins
            tiers[i] = tier
    return yards_of(tiers), tiers


def yards_of(tiers):
    return sum(dd.TIERS[t][1] for t in tiers if t)


def emoji_row(tiers):
    return "".join(dd.TIERS[t][2] if t else SACK for t in tiers)


def device_hash(device_id):
    """sha256 hex of the page's random device id, or None when it isn't a plausible id."""
    if not isinstance(device_id, str) or not _DEVICE_RE.match(device_id):
        return None
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ stats math
BUCKETS = [(0, 99), (100, 199), (200, 299), (300, 399), (400, 499), (500, 599), (600, 700)]


def distribution(yards_list):
    out = [{"lo": lo, "hi": hi, "count": 0} for lo, hi in BUCKETS]
    for y in yards_list:
        for b in out:
            if y <= b["hi"] or b is out[-1]:
                b["count"] += 1
                break
    return out


def percentile_beaten(yards_list, mine):
    """% of the OTHER players you scored strictly more than. `yards_list` includes your own score. None when you
    are the only player (nobody to compare with)."""
    n = len(yards_list)
    if n < 2:
        return None
    below = sum(1 for y in yards_list if y < mine)
    return int(round(100.0 * below / (n - 1)))


def day_stats(yards_list, mine=None):
    n = len(yards_list)
    out = {"players": n, "average_yards": None, "median_yards": None, "distribution": distribution(yards_list)}
    if n:
        out["average_yards"] = round(sum(yards_list) / n, 1)
        out["median_yards"] = round(float(statistics.median(yards_list)), 1)
    if mine is not None:
        out["your_yards"] = mine
        out["percentile"] = percentile_beaten(yards_list, mine)
    return out


def streaks(dates, today):
    """(current, longest) consecutive-day streaks from ISO date strings. A streak that ended yesterday is still
    'current' (today's game just isn't played yet); older than that is broken."""
    days = sorted({dt.date.fromisoformat(d) for d in dates})
    if not days:
        return 0, 0
    longest = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        longest = max(longest, run)
    t = dt.date.fromisoformat(today)
    last = days[-1]
    if (t - last).days > 1:
        return 0, longest
    cur = 1
    for a, b in zip(reversed(days[:-1]), reversed(days)):
        if (b - a).days == 1:
            cur += 1
        else:
            break
    return cur, longest


def my_history(rows, today, recent=60, spark=14):
    """rows = [{date: iso, yards, tiers}] in any order -> the /me payload body."""
    rows = sorted(rows, key=lambda r: r["date"], reverse=True)
    games = len(rows)
    cur, longest = streaks([r["date"] for r in rows], today)
    ys = [r["yards"] for r in rows]
    return {
        "games": games,
        "average_yards": round(sum(ys) / games, 1) if games else None,
        "best_yards": max(ys) if ys else None,
        "current_streak": cur, "longest_streak": longest,
        "history": [{"date": r["date"], "yards": r["yards"], "tiers": r["tiers"], "emoji": emoji_row(r["tiers"])}
                    for r in rows[:recent]],
        "spark": [r["yards"] for r in reversed(rows[:spark])],
    }
