"""Wiring checks for the UI polish pass (static/app.js, style.css, index.html). The behaviors are exercised in a real browser
by scripts/check_polish.js; these keep each piece from silently disappearing."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


JS, CSS, HTML = read("static/app.js"), read("static/style.css"), read("static/index.html")


def body_of(name):
    i = JS.index(name)
    return JS[i:i + 1500]


class PolishTests(unittest.TestCase):
    def test_closing_a_modal_stops_the_box_score_timer_and_cancels_pending_team_loads(self):
        b = body_of("function closeModal()")
        self.assertIn("clearInterval(gameModalTimer)", b)
        self.assertIn("teamModalSeq++", b)

    def test_a_stale_team_response_cannot_paint_into_a_newer_modal(self):
        b = JS[JS.index("async function openTeamModal"):]
        b = b[:b.index("document.addEventListener")]
        self.assertGreaterEqual(b.count("seq === teamModalSeq"), 2)

    def test_draft_polling_pauses_in_a_hidden_tab_and_keeps_the_list_scroll(self):
        self.assertIn("if (document.hidden) return;", JS)
        self.assertIn("listScroll", JS)

    def test_team_links_work_from_the_keyboard(self):
        self.assertIn("[data-team-page][role='link']", JS)

    def test_loading_states_are_skeletons_not_plain_text(self):
        for gone in ("Loading headlines…", "Loading box score…", "Loading team…"):
            self.assertNotIn(gone, JS)
        self.assertIn("news-skel", JS)
        self.assertIn(".news-skel", CSS)

    def test_score_changes_flash_and_the_flag_clears(self):
        live = read("static/live.js")
        self.assertIn("scoreChange(lastScores", live)
        self.assertIn("delete flashes[id]", live)
        self.assertIn("sb-flash", CSS)

    def test_totals_count_up_once_per_week_and_not_under_reduced_motion(self):
        b = body_of("function countUpTotals")
        self.assertIn("prefersReducedMotion", b)
        self.assertIn("countedWeeks.has(key)", b)

    def test_roster_rows_stagger_in_and_reduced_motion_turns_it_off(self):
        self.assertIn(".myteam-roster-row:nth-child(3)", CSS)
        self.assertTrue(re.search(r"prefers-reduced-motion: reduce\) \{\s*\.myteam-roster-row", CSS))

    def test_toasts_are_announced_to_screen_readers(self):
        self.assertIn('id="toast-root" role="status" aria-live="polite"', HTML)


if __name__ == "__main__":
    unittest.main()
