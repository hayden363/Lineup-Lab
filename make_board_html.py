"""
HTML BIG BOARD  (Task 5)
Turns the ranked board into a clean, readable webpage — the first step
toward an actual app UI instead of terminal text. Open the output .html
in any browser.

    python make_board_html.py            # writes big_board.html

Real data flows in automatically when nfl_data_py is installed.
"""

import pandas as pd
from app import build_board, build_matchup_table, load_weekly_with_opp, project_vs


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>Fantasy Big Board</title>
<style>
  body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1116;color:#e8eaed;margin:0;padding:24px}}
  h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#9aa0a6;font-size:13px;margin-bottom:20px}}
  h2{{font-size:16px;margin:28px 0 8px;color:#8ab4f8}}
  table{{border-collapse:collapse;width:100%;margin-bottom:20px;font-size:13px}}
  th,td{{padding:8px 10px;text-align:right;border-bottom:1px solid #23262d}}
  th:first-child,td:first-child{{text-align:left}}
  th{{color:#9aa0a6;font-weight:600;position:sticky;top:0;background:#0f1116}}
  tr:hover{{background:#171a21}}
  .score{{font-weight:700;color:#81c995}}
  .pos{{color:#f28b82}} .neg{{color:#8ab4f8}}
  .rank{{color:#5f6368;width:24px}}
</style></head><body>
<h1>🏈 Fantasy Big Board</h1>
<div class="sub">Your weighted valuation model · SCORE is 0–100 · advanced metrics from play-by-play</div>
{sections}
</body></html>"""


def board_to_html(name, board, cols):
    rows = ""
    for i, (player, r) in enumerate(board.sort_values("SCORE", ascending=False).iterrows(), 1):
        cells = f'<td class="rank">{i}</td><td>{player}</td>'
        for c in cols:
            val = r.get(c, "")
            if isinstance(val, float):
                val = f"{val:.1f}"
            cls = ""
            if c == "SCORE": cls = "score"
            if c == "FORM":
                try: cls = "pos" if float(r[c]) > 0 else "neg"
                except: pass
            cells += f'<td class="{cls}">{val}</td>'
        rows += f"<tr>{cells}</tr>"
    head = '<th class="rank"></th><th>Player</th>' + "".join(f"<th>{c}</th>" for c in cols)
    return f"<h2>{name}</h2><table><tr>{head}</tr>{rows}</table>"


def main(opp=None):
    mwk, _ = load_weekly_with_opp()
    factors, _ = build_matchup_table(mwk)
    sections = ""
    for pos in ["QB","RB"]:
        board = build_board(pos)
        board = project_vs(board, factors, pos, opp)
        cols = ["SCORE","FORM","fpts_per_game"]
        for c in ["pressure_rate","comp_pct_pressure","epa_per_play",
                  "explosive_pass_rate","explosive_run_rate","epa_per_touch"]:
            if c in board.columns: cols.append(c)
        if opp and f"PROJ_vs_{opp}" in board.columns:
            cols.append(f"PROJ_vs_{opp}")
        sections += board_to_html(f"{pos} Rankings", board, cols)

    html = TEMPLATE.format(sections=sections)
    with open("big_board.html", "w") as f:
        f.write(html)
    print("wrote big_board.html — open it in a browser")


if __name__ == "__main__":
    main()
