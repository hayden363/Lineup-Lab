"""My Team rosters stay current: short caches for rosters and lineups, a refresh switch, a refetch when a rostered
player is missing from Sleeper's cached player list, and no silent drops. No network."""
import unittest
from unittest import mock

import pandas as pd

from engine import sleeper, tools


class SleeperFreshnessTests(unittest.TestCase):
    def test_rosters_and_weekly_lineups_refresh_every_minute_not_every_quarter_hour(self):
        self.assertLessEqual(sleeper.ROSTER_TTL, 60)
        with mock.patch.object(sleeper, "_cached_get", return_value=[]) as g:
            sleeper.get_rosters("L1")
            sleeper.get_matchups("L1", 8)
        self.assertEqual([c.args[2] for c in g.call_args_list], [sleeper.ROSTER_TTL, sleeper.ROSTER_TTL])

    def test_force_is_passed_through(self):
        with mock.patch.object(sleeper, "_cached_get", return_value=[]) as g:
            sleeper.get_rosters("L1", force=True)
        self.assertTrue(g.call_args.args[3])

    def test_a_player_missing_from_the_cached_list_triggers_one_refetch(self):
        stale = {"1": {"full_name": "Old Guy", "position": "WR", "team": "DET"}}
        fresh = dict(stale, **{"99": {"full_name": "Jordan Watkins", "position": "WR", "team": "LAR"}})
        calls = []

        def fake_all(force=False):
            calls.append(force)
            return fresh if force else stale
        with mock.patch.object(sleeper, "all_players", side_effect=fake_all), mock.patch.object(sleeper, "_players_cache_age", return_value=7200):
            out = sleeper.resolve_unscored_player("99")
        self.assertEqual(out["player_display_name"], "Jordan Watkins")
        self.assertEqual(calls, [False, True])

    def test_a_fresh_cache_is_not_refetched_for_a_genuinely_unknown_id(self):
        with mock.patch.object(sleeper, "all_players", return_value={}) as ap, mock.patch.object(sleeper, "_players_cache_age", return_value=60):
            self.assertIsNone(sleeper.resolve_unscored_player("nope"))
        self.assertEqual(ap.call_count, 1)

    def test_a_failed_refetch_falls_back_to_unknown(self):
        def fake_all(force=False):
            if force:
                raise RuntimeError("sleeper down")
            return {}
        with mock.patch.object(sleeper, "all_players", side_effect=fake_all), mock.patch.object(sleeper, "_players_cache_age", return_value=7200):
            self.assertIsNone(sleeper.resolve_unscored_player("99"))


class RosterRowsTests(unittest.TestCase):
    def test_an_unresolvable_roster_id_still_gets_a_row_instead_of_vanishing(self):
        bundle = {"season": 2026, "schedule": pd.DataFrame(columns=["week", "home_team", "away_team"]), "wk": pd.DataFrame()}
        rows, total = tools._roster_players(["99"], bundle, lambda pos: None, None, crosswalk={}, starters=[], slot_labels=[],
                                            resolve_unscored=lambda sid: None, week=8)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["player_id"], rows[0]["PROJ"], rows[0]["is_starter"]), ("99", 0.0, False))
        self.assertIn("99", rows[0]["player_display_name"])
        self.assertTrue(rows[0].get("unresolved"))


class RefreshEndpointTests(unittest.TestCase):
    def test_refresh_flag_refetches_the_rosters_and_lineups_first(self):
        from fastapi.testclient import TestClient
        import server
        server.app.dependency_overrides[server.require_user] = lambda: {"id": 1, "username": "t"}
        self.addCleanup(server.app.dependency_overrides.clear)
        with mock.patch.object(server.db, "get_active_team", return_value={"platform": "sleeper", "league_id": "L1", "roster_id": 1}), \
                mock.patch.object(server.tools, "my_team", return_value={"my_team": {"players": []}}), \
                mock.patch.object(server, "_effective_scoring", return_value=None), \
                mock.patch.object(server.sleeper_layer, "get_rosters") as gr, mock.patch.object(server.sleeper_layer, "clear_league_caches") as cc:
            r = TestClient(server.app).get("/api/myteam?refresh=1")
            self.assertEqual(r.status_code, 200)
            cc.assert_called_once_with("L1")
            r2 = TestClient(server.app).get("/api/myteam")
            self.assertEqual(cc.call_count, 1)             # a normal load does not refetch


class RefreshUiTests(unittest.TestCase):
    def test_my_team_has_a_refresh_button_that_passes_refresh_through(self):
        import os
        js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static/app.js")).read()
        self.assertIn('id="mt-refresh"', js)
        self.assertIn('&refresh=1', js)
        self.assertIn("p.unresolved", js)

    def test_espn_leagues_refresh_through_the_espn_cache(self):
        from fastapi.testclient import TestClient
        import server
        server.app.dependency_overrides[server.require_user] = lambda: {"id": 1, "username": "t"}
        self.addCleanup(server.app.dependency_overrides.clear)
        with mock.patch.object(server.db, "get_active_team", return_value={"platform": "espn", "league_id": "9", "roster_id": 1}), \
                mock.patch.object(server.db, "get_espn_secrets", return_value=(None, None)), \
                mock.patch.object(server.tools, "my_team_espn", return_value={"my_team": {"players": []}}), \
                mock.patch.object(server, "_effective_scoring", return_value=None), \
                mock.patch.object(server.espn_layer, "clear_league_cache") as cc:
            self.assertEqual(TestClient(server.app).get("/api/myteam?refresh=1").status_code, 200)
        cc.assert_called_once()


if __name__ == "__main__":
    unittest.main()
