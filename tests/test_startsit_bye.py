"""A player whose team is on bye this week scores 0 in Start/Sit."""

import unittest

from engine import profile, tools, waivers


class ByeStartSitTests(unittest.TestCase):
    def test_bye_player_is_ruled_out_and_never_picked(self):
        bundle = waivers.load_bundle()
        slate = waivers.target_week(bundle["schedule"])
        byes = profile.bye_weeks(bundle["schedule"])
        bye_teams = {t for t, w in byes.items() if w == slate}
        if not bye_teams:
            self.skipTest("no team is on bye in this week's slate")
        pool, _ = waivers.cached_pool(None, bundle)
        qbs = pool[(pool["position"] == "QB") & pool["injury_status"].isna()]
        on_bye = qbs[qbs["recent_team"].isin(bye_teams)].sort_values("value", ascending=False)
        playing = qbs[~qbs["recent_team"].isin(bye_teams)].sort_values("value")
        if on_bye.empty or playing.empty:
            self.skipTest("no healthy QB on a bye team")
        res = tools.start_sit([on_bye.index[0], playing.index[len(playing) // 2]])
        byp = next(p for p in res["players"] if p["player_id"] == on_bye.index[0])
        self.assertTrue(byp["on_bye"])
        self.assertTrue(byp["outcomes"]["out"])
        self.assertEqual(byp["outcomes"]["reason"], "bye")
        self.assertEqual(byp["decision"]["rating"], 0.0)   # a bye must not read as a strong start
        self.assertEqual(byp["week"], slate)
        self.assertIsNone(byp["opponent"])
        self.assertNotEqual(res["decision"]["pick"], on_bye.index[0])


if __name__ == "__main__":
    unittest.main()
