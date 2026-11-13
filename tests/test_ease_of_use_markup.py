"""Batch B ease-of-use changes: bottom nav, friendly api() errors, dialog semantics, no inline handlers."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def block(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


class EaseOfUseMarkup(unittest.TestCase):
    def setUp(self):
        self.html = read("static/index.html")
        self.js = read("static/app.js")

    def test_bottom_nav_has_waivers_not_nfl_games(self):
        nav = block(self.html, 'id="bottom-nav"', "</nav>")
        self.assertIn('data-go="waivers"', nav)
        self.assertIn("<span>Waivers</span>", nav)
        self.assertNotIn('data-go="live"', nav)
        self.assertNotIn("NFL Games</span>", nav)
        # still reachable from the More drawer (the sidebar nav it opens)
        side = block(self.html, 'class="sidebar-nav"', '<div class="sidebar-middle">')
        self.assertIn('data-tab="live"', side)
        self.assertIn('<span class="nav-label">NFL Games</span>', side)

    def test_big_board_sits_below_the_decision_tabs(self):
        side = block(self.html, 'class="sidebar-nav"', '<div class="sidebar-middle">')
        for tab in ("myteam", "startsit", "trade", "waivers"):
            self.assertLess(side.index(f'data-tab="{tab}"'), side.index('data-tab="board"'))

    def test_api_errors_never_show_the_url(self):
        api = block(self.js, "async function api(path, opts)", "\n}\n")
        self.assertNotIn("-> ${", api)
        self.assertIn("Can't reach Lineup Lab", api)
        self.assertIn("err.status = res.status", api)

    def test_modals_get_dialog_semantics_in_one_place(self):
        helper = block(self.js, "function decorateModalRoot(root)", "\n}\n")
        self.assertIn('setAttribute("role", "dialog")', helper)
        self.assertIn('setAttribute("aria-modal", "true")', helper)
        self.assertIn("aria-label", helper)

    def test_no_inline_event_handlers(self):
        for rel in ("static/index.html", "static/app.js"):
            self.assertIsNone(re.search(r"\sonclick\s*=", read(rel)), rel)

    def test_gate_sends_the_platform(self):
        gate = block(self.js, "function renderGateConnectLeague()", "\nasync function main()")
        self.assertIn('data-platform="espn"', gate)
        self.assertIn("platform: connectPlatform", gate)


class LeagueSwitchingFromTheSidebar(unittest.TestCase):
    """Clicking a league in the sidebar must move EVERY league-dependent screen, not just some."""

    def setUp(self):
        self.js = read("static/app.js")
        self.handler = block(self.js, 'row.addEventListener("click", async () => {', "showToast(`Switched to")

    def test_sidebar_lists_every_league_as_a_clickable_keyboard_row(self):
        fn = block(self.js, "function renderSidebarTeams()", "function initPosPills()")
        self.assertIn('class="sidebar-team-row kbd-click', fn)
        self.assertIn('role="button" tabindex="0"', fn)
        self.assertIn("state.teams.map(", fn)                      # one row per connected league, not just the active one

    def test_the_phone_menu_closes_after_picking_a_league(self):
        self.assertGreaterEqual(self.handler.count("closeMobileDrawer()"), 2)   # on a switch and on tapping the current one

    def test_the_big_board_reloads_when_it_was_scored_by_league_rules(self):
        self.assertIn("boardUsedLeagueScoring", self.handler)
        self.assertIn("state.boardLoaded = false", self.handler)
        self.assertIn('if (state.tab === "board") loadBoard()', self.handler)

    def test_the_live_tab_forgets_the_previous_leagues_roster(self):
        self.assertIn("LiveTab.resetRoster()", self.handler)
        live = read("static/live.js")
        self.assertIn("LiveTab.resetRoster = function", live)
        self.assertIn("rosterAt = 0", block(live, "LiveTab.resetRoster = function", "\n"))

    def test_league_chat_follows_the_active_league(self):
        self.assertIn("chatFollowActiveLeague()", self.handler)
        self.assertIn('if (state.tab === "chat") loadChatTab()', self.handler)
        chat = read("static/chat.js")
        fn = block(chat, "function chatFollowActiveLeague()", "function stopChatPolling()")
        self.assertIn("chatState.leagueId = active.league_id", fn)
        self.assertIn("chatLeagues().some(", fn)                   # ESPN leagues have no chat: nothing to follow

    def test_the_screens_that_were_already_refreshed_still_are(self):
        for call in ("loadMyTeam()", "loadWaivers()", "loadNews()", "loadDraftTab()", "loadTradeFinder()", "loadStartSitTab()"):
            self.assertIn(call, self.handler)


if __name__ == "__main__":
    unittest.main()
