"""
DAILY DRIVE MISSED GUESSES — what players typed that the answer bank rejected
==============================================================================
Run:  python scripts/dd_misses.py [YYYY-MM-DD] [--min 2]     (default: today US Eastern; needs DATABASE_URL)

For each prompt, the most common rejected guesses with a verdict, so you can spot:
  - a missing nickname / spelling   -> add it to engine/daily_drive_nicknames.py
  - a real player who should count  -> the answer bank has a gap (check the data)
  - a real player who doesn't fit   -> fine; the game already explains why
Verdicts come from the same code the game uses (check_answer + explain_miss), against the day's frozen puzzle.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import daily_drive as dd  # noqa: E402
from engine import daily_drive_history_snapshot as snap  # noqa: E402
from engine import db  # noqa: E402


def verdict(prompt, guess):
    names = {dd.norm_name(a["name"]): a["name"] for a in prompt["answers"]}
    near = sorted(names, key=lambda n: dd.levenshtein(guess, n))[:1]
    why = snap.explain_miss(prompt, guess)
    if why:
        return why
    if near and dd.levenshtein(guess, near[0]) <= 3:
        return f"close to {names[near[0]]}: nickname or spelling to add?"
    return "unknown name"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=dd.today_et().isoformat())
    ap.add_argument("--min", type=int, default=1, help="only guesses typed at least this many times")
    args = ap.parse_args()
    if not db.DATABASE_URL:
        sys.exit("DATABASE_URL is not set")
    puzzle = db.get_drive_puzzle(args.date)
    if not puzzle:
        sys.exit(f"no frozen puzzle for {args.date}")
    by_id = {p["id"]: p for p in puzzle["prompts"]}
    misses = [m for m in db.drive_misses(args.date) if m["n"] >= args.min]
    print(f"The Daily Drive {args.date}: {len(misses)} distinct missed guesses")
    for p in puzzle["prompts"]:
        rows = [m for m in misses if m["prompt_id"] == p["id"]]
        if not rows:
            continue
        print(f"\n{p['text']}")
        for m in rows[:25]:
            print(f"  {m['n']:>4}x  {m['guess']:<28} {verdict(p, m['guess'])}")
    stray = [m for m in misses if m["prompt_id"] not in by_id]
    if stray:
        print(f"\n({len(stray)} guesses for prompts not in the frozen puzzle)")


if __name__ == "__main__":
    main()
