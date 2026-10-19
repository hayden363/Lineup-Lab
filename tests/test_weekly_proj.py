import unittest
from unittest import mock

from engine import weekly_proj, profile
from engine.scoring import ScoringSettings


class PointsTest(unittest.TestCase):
    def test_ppr_and_half_ppr_from_stat_line(self):
        line = {"rec": 5, "rec_yd": 60, "rec_td": 1}
        self.assertEqual(weekly_proj.points(line, ScoringSettings.from_preset("ppr")), 17.0)
        self.assertEqual(weekly_proj.points(line, ScoringSettings.from_preset("half_ppr")), 14.5)

    def test_projected_out_is_not_a_projection(self):
        self.assertEqual(weekly_proj.projected_line({"gp": 0, "rec": 4}, None), {"out": True})
        self.assertEqual(weekly_proj.projected_line({"rec": 0}, None), {"out": True})

    def test_stat_names_mapped_to_ours(self):
        out = weekly_proj.projected_line({"rec_tgt": 8, "rec": 5.4, "rec_yd": 70.2}, ScoringSettings())
        self.assertEqual(out["targets"], 8)
        self.assertEqual(out["receptions"], 5.4)
        self.assertEqual(out["fpts"], 12.4)


class PlayerProjectionsTest(unittest.TestCase):
    def test_matches_by_crosswalk_and_skips_missing_weeks(self):
        rows = {1: [{"player_id": "99", "stats": {"rec": 6, "rec_yd": 80}}],
                2: [{"player_id": "12", "stats": {"rec": 9}}]}
        with mock.patch.object(weekly_proj.sleeper, "id_crosswalk", return_value={"99": "00-1", "12": "00-2"}), \
             mock.patch.object(weekly_proj, "_week_rows", side_effect=lambda s, w, p: rows[w]):
            out = weekly_proj.player_projections("00-1", "WR", 2026, [1, 2], None)
        self.assertEqual(list(out), [1])
        self.assertEqual(out[1]["fpts"], 14.0)

    def test_fetch_failure_drops_week_only(self):
        def boom(s, w, p):
            if w == 2:
                raise RuntimeError("down")
            return [{"player_id": "99", "stats": {"rec": 1}}]
        with mock.patch.object(weekly_proj.sleeper, "id_crosswalk", return_value={"99": "00-1"}), \
             mock.patch.object(weekly_proj, "_week_rows", side_effect=boom):
            out = weekly_proj.player_projections("00-1", "WR", 2026, [1, 2], None)
        self.assertEqual(list(out), [1])

    def test_attach_only_on_played_weeks(self):
        rows = [{"week": 1, "status": "played"}, {"week": 2, "status": "bye"}]
        weekly_proj.attach(rows, {1: {"fpts": 10}, 2: {"fpts": 5}})
        self.assertEqual(rows[0]["proj"], {"fpts": 10})
        self.assertNotIn("proj", rows[1])


class StyleWordsTest(unittest.TestCase):
    def test_style_stats_get_words_skill_stats_do_not(self):
        self.assertEqual(profile._style_words("passing", "aggressiveness"), ["Plays it safe", "Gunslinger"])
        self.assertEqual(profile._style_words("receiving", "avg_intended_air_yards"), ["Short targets", "Deep threat"])
        self.assertEqual(profile._style_words("passing", "avg_intended_air_yards"), ["Short and quick", "Pushes it deep"])

    def test_every_style_stat_has_words(self):
        for kind, specs in profile.NGS_SPECS.items():
            for col, _, higher in specs:
                if higher is None:
                    self.assertIsNotNone(profile._style_words(kind, col), f"{kind}/{col}")


if __name__ == "__main__":
    unittest.main()
