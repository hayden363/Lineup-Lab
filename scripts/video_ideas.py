#!/usr/bin/env python3
"""Draft short-video ideas from Lineup Lab's own public waiver-engine data.

Reads /api/waivers/engine (no login needed: market movers, handcuffs, deep dive)
and writes a markdown file of ready-to-record video drafts, each built from a
real number the app produced this week. It makes no video and posts nothing —
a human reviews the drafts and records them.

    python3 scripts/video_ideas.py                       # print to the terminal
    python3 scripts/video_ideas.py --out ideas.md        # save to a file
    python3 scripts/video_ideas.py --base http://localhost:8000

Standard library only. Player names are text-only on purpose (no headshots, no
NFL footage or logos); wording says "projection" and never promises results.
"""
import argparse
import json
import sys
import urllib.request

DEFAULT_BASE = "https://lineup-lab-awdv.onrender.com"
LINK = "link in bio"


def fetch(base):
    req = urllib.request.Request(f"{base.rstrip('/')}/api/waivers/engine",
                                 headers={"User-Agent": "lineup-lab-video-ideas"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def num(x, nd=1):
    return "n/a" if x is None else f"{x:.{nd}f}"


def waiver_idea(p, week):
    stats = [f"model rest-of-season value {num(p.get('ros'))}"]
    if p.get("snap_pct") is not None:
        stats.append(f"{num(p['snap_pct'], 0)}% of snaps")
    if p.get("target_share") is not None:
        stats.append(f"{num(p['target_share'])}% target share")
    return {
        "title": f"Waiver pick: {p['name']}",
        "hook": f"My model's top waiver pickup for week {week} is {p['name']}.",
        "on_screen": f"{p['name']} · {p['position']} · {p['team']}",
        "script": (f"Lineup Lab ranks {p['name']} first among available {p['position']}s this week. "
                   f"{', '.join(stats).capitalize()}. It's a projection, not a promise."),
        "demo": "Screen-record the Waivers tab, Market Movers list, tap the player.",
        "cta": f"Free tool, {LINK}.",
    }


def handcuff_idea(h):
    return {
        "title": f"Handcuff alert: {h['backup']}",
        "hook": f"{h['starter']} is {h['starter_status']}. Here's who to grab.",
        "on_screen": f"{h['team']} · {h['starter']} ({h['starter_status']}) → {h['backup']}",
        "script": (f"{h['starter']} is listed {h['starter_status']}. His backup {h['backup']} "
                   f"played {num(h.get('backup_snap_pct'), 0)}% of snaps last time out and is "
                   f"{'still on waivers' if h.get('available') else 'already rostered in some leagues'}. "
                   "Check the status before kickoff."),
        "demo": "Screen-record the Handcuffs list, highlight the starter and backup rows.",
        "cta": f"Free tool, {LINK}.",
    }


def regression_idea(p, hot):
    d = p["xfp_diff"]
    return {
        "title": f"{'Hot' if hot else 'Due'}: {p['name']}",
        "hook": (f"{p['name']} is scoring {abs(d):.1f} points per game "
                 f"{'above' if hot else 'below'} what his usage says he should."),
        "on_screen": f"{p['name']} · actual vs expected: {d:+.1f} pts/game",
        "script": (f"Usage predicts about {num(p.get('xfp_pg'))} points a game for {p['name']}. "
                   f"He's {'over' if hot else 'under'}performing that by {abs(d):.1f}. "
                   f"{'That tends to cool off.' if hot else 'That can bounce back.'} "
                   "Tendencies, not guarantees."),
        "demo": "Screen-record the player card, show expected vs actual points.",
        "cta": f"See your own players, {LINK}.",
    }


def render(ideas, week, season):
    out = [f"# Lineup Lab video drafts — {season} week {week}", "",
           "Drafts only. Review each before recording. Numbers come from the live app; "
           "keep the 'projection, not a promise' wording.", ""]
    for i, d in enumerate(ideas, 1):
        out += [f"## {i}. {d['title']}",
                f"- **Hook (first 2s):** {d['hook']}",
                f"- **On-screen text:** {d['on_screen']}",
                f"- **Voiceover:** {d['script']}",
                f"- **Screen to record:** {d['demo']}",
                f"- **CTA:** {d['cta']}", ""]
    out += ["---", "Checklist: no NFL footage or logos · no headshots · commercial-library music "
            "or none · show a miss as well as a win sometimes · tag as AI-generated if any "
            "part is AI."]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=DEFAULT_BASE, help="app base URL")
    ap.add_argument("--out", help="write markdown here instead of printing")
    args = ap.parse_args()

    try:
        data = fetch(args.base)
    except Exception as e:
        sys.exit(f"couldn't reach {args.base}: {e}")

    week, season = data.get("week"), data.get("season")
    ideas = []

    movers = [p for p in data.get("market_movers") or [] if p.get("SCORE") is not None]
    if movers:
        ideas.append(waiver_idea(max(movers, key=lambda p: p["SCORE"]), week))

    live = [h for h in data.get("handcuffs") or [] if h.get("live") and h.get("available")]
    for h in live[:2]:
        ideas.append(handcuff_idea(h))

    diffs = [p for p in data.get("deep_dive") or [] if p.get("xfp_diff") is not None]
    if diffs:
        ideas.append(regression_idea(max(diffs, key=lambda p: p["xfp_diff"]), hot=True))
        ideas.append(regression_idea(min(diffs, key=lambda p: p["xfp_diff"]), hot=False))

    if not ideas:
        sys.exit("the app returned no usable waiver data this week")

    text = render(ideas, week, season)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {len(ideas)} drafts to {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
