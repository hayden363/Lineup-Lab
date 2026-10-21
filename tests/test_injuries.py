"""Live injuries: ESPN feed parsing, overlay on Sleeper's data, return timeline."""

import unittest
from datetime import date
from unittest import mock

import pandas as pd

from engine import injuries as I


def _feed():
    def inj(id_, name, pos, status, fantasy, part=None, detail="Not Specified", rd=None, comment="x"):
        return {"id": id_, "status": status, "shortComment": comment, "date": "2026-10-20T16:10Z",
                "details": {"fantasyStatus": {"abbreviation": fantasy} if fantasy else None, "type": part or "Not Specified",
                            "detail": detail, "side": "Left", "returnDate": rd},
                "athlete": {"displayName": name, "position": {"abbreviation": pos}}}
    return {"injuries": [{"displayName": "Team A", "injuries": [
        inj("1", "Hurt Back", "RB", "Questionable", "QUESTIONABLE", "Hamstring", "Strain", "2026-10-25", "Practiced fully."),
        inj("2", "Done Guy", "WR", "Injured Reserve", "IR", None, rd=None, comment="questionable"),
        inj("3", "Cleared Man", "WR", "Active", None),
        inj("-9", "Not A Player", "RB", "Out", "OUT"),
        inj("4", "Some Lineman", "OT", "Out", "OUT"),
        inj("5", "Kick Er", "PK", "Doubtful", "DOUBTFUL", "Quad"),
    ]}]}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.rows = {r["name"]: r for r in I.parse(_feed())}

    def test_skips_positions_we_do_not_track(self):
        self.assertNotIn("Some Lineman", self.rows)

    def test_status_mapped_to_app_vocabulary(self):
        self.assertEqual(self.rows["Hurt Back"]["status"], "Questionable")
        self.assertEqual(self.rows["Done Guy"]["status"], "IR")
        self.assertEqual(self.rows["Kick Er"]["status"], "Doubtful")
        self.assertEqual(self.rows["Kick Er"]["position"], "K")

    def test_active_means_cleared(self):
        self.assertIsNone(self.rows["Cleared Man"]["status"])

    def test_detail_fields(self):
        r = self.rows["Hurt Back"]
        self.assertEqual((r["body_part"], r["detail"], r["return_date"]), ("Hamstring", "Strain", "2026-10-25"))

    def test_placeholder_comment_is_not_a_report(self):
        self.assertIsNone(self.rows["Done Guy"]["note"])
        self.assertEqual(self.rows["Hurt Back"]["note"], "Practiced fully.")

    def test_unplaceable_negative_ids_have_no_espn_id(self):
        self.assertIsNone(self.rows["Not A Player"]["espn_id"])


def _board():
    return pd.DataFrame({
        "injury_status": ["Out", "Questionable", None, "Doubtful"],
        "injury_body_part": ["Knee", None, None, None],
    }, index=["a", "b", "c", "d"])


def _rec(status, part=None):
    return {"status": status, "body_part": part, "detail": None, "side": None, "return_date": None, "note": None, "updated": None}


class OverlayTests(unittest.TestCase):
    def _run(self, recs):
        with mock.patch.object(I, "snapshot", return_value=recs):
            return I.overlay(_board(), {})

    def test_espn_status_replaces_stale_sleeper(self):
        out = self._run({"a": _rec("Questionable", "Ankle")})
        self.assertEqual(out.loc["a", "injury_status"], "Questionable")
        self.assertEqual(out.loc["a", "injury_body_part"], "Ankle")

    def test_espn_active_clears_an_old_designation(self):
        out = self._run({"a": _rec(None)})
        self.assertTrue(pd.isna(out.loc["a", "injury_status"]))

    def test_unlisted_player_keeps_sleepers_status(self):
        out = self._run({"a": _rec("IR")})
        self.assertEqual(out.loc["d", "injury_status"], "Doubtful")

    def test_new_injury_appears(self):
        out = self._run({"c": _rec("Out", "Hamstring")})
        self.assertEqual(out.loc["c", "injury_status"], "Out")

    def test_input_board_is_not_modified(self):
        b = _board()
        with mock.patch.object(I, "snapshot", return_value={"a": _rec("IR")}):
            I.overlay(b, {})
        self.assertEqual(b.loc["a", "injury_status"], "Out")
        self.assertNotIn("injury_report", b.columns)

    def test_empty_feed_leaves_everything(self):
        out = self._run({})
        self.assertEqual(list(out["injury_status"].fillna("-")), ["Out", "Questionable", "-", "Doubtful"])


class TimelineTests(unittest.TestCase):
    SCHED = pd.DataFrame({
        "game_type": ["REG"] * 4, "week": [7, 8, 9, 10],
        "home_team": ["AAA", "BBB", "AAA", "CCC"], "away_team": ["ZZZ", "AAA", "YYY", "AAA"],
        "gameday": ["2026-10-25", "2026-11-01", "2026-11-08", "2026-11-15"],
        "home_score": [None] * 4,
    })

    def test_counts_games_before_return(self):
        t = I.timeline("2026-11-05", self.SCHED, "AAA", today=date(2026, 10, 21))
        self.assertEqual((t["games_out"], t["return_week"], t["days_out"]), (2, 9, 15))

    def test_back_for_next_game(self):
        t = I.timeline("2026-10-25", self.SCHED, "AAA", today=date(2026, 10, 21))
        self.assertEqual((t["games_out"], t["return_week"]), (0, 7))

    def test_no_date_says_nothing(self):
        t = I.timeline(None, self.SCHED, "AAA")
        self.assertEqual((t["games_out"], t["return_week"], t["days_out"]), (None, None, None))

    def test_bad_date_does_not_crash(self):
        self.assertIsNone(I.timeline("soon", self.SCHED, "AAA")["games_out"])


class ReportTests(unittest.TestCase):
    def test_none_without_a_status(self):
        self.assertIsNone(I.report_for("a", {"injury_status": None}, TimelineTests.SCHED))

    def test_sleeper_only_player_still_gets_a_block(self):
        r = I.report_for("a", {"injury_status": "IR", "injury_body_part": "Knee", "recent_team": "AAA"}, TimelineTests.SCHED)
        self.assertEqual((r["status"], r["body_part"], r["source"]), ("IR", "Knee", "Sleeper"))
        self.assertIn("four games", r["meaning"])
        self.assertIsNone(r["return_date"])

    def test_espn_record_fills_the_block(self):
        rec = {**_rec("Questionable", "Hamstring"), "return_date": "2026-10-25", "note": "Limited."}
        r = I.report_for("a", {"injury_status": "Questionable", "injury_report": rec, "recent_team": "AAA"},
                         TimelineTests.SCHED, today=date(2026, 10, 21))
        self.assertEqual((r["source"], r["return_week"], r["note"]), ("ESPN", 7, "Limited."))


class FailureTests(unittest.TestCase):
    def test_feed_failure_keeps_last_good_copy(self):
        I._CACHE.update(at=0.0, records={"a": _rec("Out")})
        with mock.patch.object(I, "_fetch", side_effect=RuntimeError("down")):
            self.assertEqual(I.snapshot({}, force=True), {"a": _rec("Out")})

    def test_first_call_failure_returns_empty_not_error(self):
        I._CACHE.update(at=0.0, records=None)
        with mock.patch.object(I, "_fetch", side_effect=RuntimeError("down")):
            self.assertEqual(I.snapshot({}, force=True), {})


if __name__ == "__main__":
    unittest.main()
