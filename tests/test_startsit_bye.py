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
        self.assertEqual(byp["PROJ"], 0.0)                 # not his next game's number
        self.assertGreater(byp["next_game_proj"], 0)
        self.assertIn("vs 0.0 for " + byp["player_display_name"], res["summary"] or "")   # the write-up compares against his real 0


class SuggestionsSkipUnavailablePlayers(unittest.TestCase):
    """A player on a bye or ruled out is never one side of a "closest call": nobody weighs starting him."""

    def row(self, pid, pos, proj, starter, slot=None, **kw):
        return dict({"player_id": pid, "position": pos, "PROJ": proj, "is_starter": starter, "slot": slot or pos,
                     "player_display_name": pid}, **kw)

    def run_suggestions(self, roster):
        from unittest import mock
        seen = []

        def fake_start_sit(ids, **kw):
            seen.append(tuple(ids))
            return {"players": [{"player_id": i} for i in ids]}
        with mock.patch.object(tools, "start_sit", side_effect=fake_start_sit):
            out = tools.start_sit_suggestions_from_roster(roster)
        return out, seen

    def test_a_starter_on_a_bye_is_not_compared_with_a_bench_player(self):
        roster = [self.row("cmc", "RB", 0.0, True, on_bye=True), self.row("sadiq", "RB", 9.0, False),
                  self.row("rb2", "RB", 12.0, True), self.row("rb3", "RB", 8.0, False)]
        out, seen = self.run_suggestions(roster)
        self.assertEqual(seen, [("rb2", "sadiq")])                  # the bye RB is on neither side
        self.assertFalse(any("cmc" in pair for pair in seen))

    def test_a_ruled_out_or_ir_player_is_never_suggested(self):
        roster = [self.row("a", "WR", 14.0, True), self.row("b", "WR", 15.0, False, injury_status="Out"),
                  self.row("c", "WR", 16.0, False, injury_status="IR"), self.row("d", "WR", 9.0, False)]
        _, seen = self.run_suggestions(roster)
        flat = {x for pair in seen for x in pair}
        self.assertFalse({"b", "c"} & flat)

    def test_bench_player_on_a_bye_is_not_offered_for_the_flex(self):
        roster = [self.row("a", "WR", 14.0, True), self.row("flex", "RB", 6.0, True, slot="FLEX"),
                  self.row("byewr", "WR", 20.0, False, on_bye=True), self.row("ok", "WR", 9.0, False)]
        _, seen = self.run_suggestions(roster)
        self.assertFalse(any("byewr" in pair for pair in seen))


if __name__ == "__main__":
    unittest.main()
