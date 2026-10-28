"""'Find a trade' for a player you want: the finder is told who to land, says who owns him, and the route passes it through."""
import unittest
from unittest import mock

from engine import tools, trade_engine


def P(pid, name="X"):
    return {"player_id": pid, "name": name, "position": "WR", "value": 10, "trade": 50, "injury_status": None, "headshot_url": None,
            "recent_team": "DET", "usage": None, "bye": None}


ROSTERS = {1: {"name": "Me", "players": [P("mine1")]}, 2: {"name": "Rivals", "players": [P("amon", "Amon-Ra St. Brown")]}}
SETUP = ({"season": 2026}, ROSTERS, {"slots": [], "profile": "standard", "teams": 12})


class RunFinderTests(unittest.TestCase):
    def run_it(self, want, found=()):
        with mock.patch.object(trade_engine, "find_trades", return_value=list(found)) as ft:
            out = tools._run_trade_finder(SETUP, "L1", 1, None, None, 6, want_player_ids=want)
        return out, ft

    def test_want_ids_reach_the_engine_and_the_owner_is_reported(self):
        out, ft = self.run_it(["amon"])
        self.assertEqual(ft.call_args.kwargs["want_ids"], ["amon"])
        self.assertEqual(out["target"], {"player_id": "amon", "owner_roster_id": 2, "owner_team_name": "Rivals", "on_my_roster": False, "on_a_roster": True})

    def test_a_free_agent_is_reported_as_not_on_any_roster(self):
        out, _ = self.run_it(["free"])
        self.assertEqual((out["target"]["on_a_roster"], out["target"]["owner_roster_id"]), (False, None))

    def test_your_own_player_is_flagged(self):
        out, _ = self.run_it(["mine1"])
        self.assertTrue(out["target"]["on_my_roster"])

    def test_no_want_ids_keeps_the_old_shape(self):
        out, ft = self.run_it(None)
        self.assertIsNone(ft.call_args.kwargs["want_ids"])
        self.assertNotIn("target", out)


class RouteTests(unittest.TestCase):
    def test_want_is_passed_to_the_finder(self):
        from fastapi.testclient import TestClient
        import server
        server.app.dependency_overrides[server.require_user] = lambda: {"id": 1, "username": "t"}
        self.addCleanup(server.app.dependency_overrides.clear)
        with mock.patch.object(server.db, "get_active_team", return_value={"platform": "sleeper", "league_id": "L1", "roster_id": 1}), \
                mock.patch.object(server, "_effective_scoring", return_value=None), \
                mock.patch.object(server.tools, "trade_finder", return_value={"suggestions": []}) as tf:
            r = TestClient(server.app).get("/api/trade-finder?want=amon")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(tf.call_args.kwargs["want_player_ids"], ["amon"])


if __name__ == "__main__":
    unittest.main()


class FrontEndWiringTests(unittest.TestCase):
    def js(self):
        import os
        return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static/app.js")).read()

    def test_the_player_card_has_a_find_a_trade_button_that_opens_the_trade_tab_in_acquire_mode(self):
        js = self.js()
        self.assertIn('data-act="findtrade"', js)
        self.assertIn("Find a trade", js)
        self.assertIn("state.tradeWant = { player_id: pid", js)
        self.assertIn('switchTab("trade")', js[js.index('findBtn.addEventListener'):][:300])

    def test_the_button_is_hidden_for_your_own_players(self):
        js = self.js()
        self.assertIn("findBtn.hidden = roster.some((x) => x.player_id === pid)", js)

    def test_the_trade_tab_asks_the_finder_to_land_him_and_explains_an_empty_result(self):
        js = self.js()
        body = js[js.index("async function runAcquire"):][:2600]
        self.assertIn("&want=", body)
        self.assertIn("isn't on a roster in your league", body)
        self.assertIn("already on your team", body)
        self.assertIn("state.tradeWant = null", js[js.index("async function loadTradeFinder"):][:700])
