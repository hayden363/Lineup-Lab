"""Projected PPG, VORP and the 0-100 PVS are three separate, typed fields and are never swapped or shown in
each other's place. No network or database."""
import unittest
from unittest import mock

import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError

import server
from engine import schemas, tools

# real board values for the two players in the bug report (2026, through week 7)
ARSB = {"player_display_name": "Amon-Ra St. Brown", "position": "WR", "PROJ": 18.0, "VOR": 6.2, "PVS": 72.3}
NABERS = {"player_display_name": "Malik Nabers", "position": "WR", "PROJ": 19.1, "VOR": 7.3, "PVS": 74.3}


class SchemaTests(unittest.TestCase):
    def test_three_separate_fields(self):
        v = schemas.PlayerValue(projected_ppg=17.5, vorp=8.6, pvs_score=91.0)
        self.assertEqual((v.projected_ppg, v.vorp, v.pvs_score), (17.5, 8.6, 91.0))
        self.assertEqual(set(v.model_dump()), {"projected_ppg", "vorp", "pvs_score"})

    def test_strictly_typed_no_coercion(self):
        for bad in ({"projected_ppg": "17.5"}, {"vorp": "8.6"}, {"pvs_score": "91"}):
            with self.assertRaises(ValidationError, msg=bad):
                schemas.PlayerValue(**bad)

    def test_pvs_is_zero_to_one_hundred(self):
        for bad in (-0.1, 100.1, 172.0):
            with self.assertRaises(ValidationError):
                schemas.PlayerValue(pvs_score=bad)
        schemas.PlayerValue(pvs_score=0.0), schemas.PlayerValue(pvs_score=100.0)

    def test_no_extra_fields(self):
        with self.assertRaises(ValidationError):
            schemas.PlayerValue(projected_ppg=17.5, VALUE=57.0)

    def test_vorp_above_the_projection_is_the_swapped_columns_bug_and_is_rejected(self):
        with self.assertRaises(ValidationError):
            schemas.PlayerValue(projected_ppg=8.9, vorp=18.8)             # the reported 8.9 vs 18.8
        schemas.PlayerValue(projected_ppg=18.8, vorp=8.9)                 # the right way round is fine


class ValueFieldsTests(unittest.TestCase):
    def test_each_field_comes_only_from_its_own_column(self):
        f = schemas.value_fields(ARSB)
        self.assertEqual(f, {"projected_ppg": 18.0, "vorp": 6.2, "pvs_score": 72.3})
        # the three numbers are all different here, so any mix-up would show
        self.assertEqual(len({f["projected_ppg"], f["vorp"], f["pvs_score"]}), 3)

    def test_missing_and_nan_become_none_not_zero(self):
        f = schemas.value_fields({"PROJ": float("nan"), "PVS": 55.0})
        self.assertEqual(f, {"projected_ppg": None, "vorp": None, "pvs_score": 55.0})

    def test_an_inconsistent_row_is_dropped_loudly_not_shown_as_fact(self):
        with mock.patch("builtins.print") as log:
            f = schemas.value_fields({"player_display_name": "X", "PROJ": 8.9, "VOR": 18.8, "PVS": 72.0})
        self.assertEqual(f, {"projected_ppg": None, "vorp": None, "pvs_score": None})
        self.assertIn("mixed up", log.call_args[0][0])

    def test_value_is_never_a_vorp_source(self):
        # VALUE is the older 0-100 rescaling of VORP; it must not leak into any of the three fields
        f = schemas.value_fields({"PROJ": 18.0, "VOR": 6.2, "PVS": 72.3, "VALUE": 48.4})
        self.assertNotIn(48.4, f.values())


class ApiPayloadTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server.app.dependency_overrides[server.current_user] = lambda: None
        self.addCleanup(server.app.dependency_overrides.clear)
        board = pd.DataFrame([{**ARSB, "recent_team": "DET", "VALUE": 48.4, "overall_rank": 12, "tier": 2},
                              {**NABERS, "recent_team": "NYG", "VALUE": 57.0, "overall_rank": 10, "tier": 2}],
                             index=["a", "b"])
        board.index.name = "player_id"
        for p in (mock.patch.object(server, "overall_board", return_value=board),
                  mock.patch.object(server, "load_bundle", return_value={"season": 2026, "schedule": None}),
                  mock.patch.object(server, "upcoming_week", return_value=8)):
            p.start(); self.addCleanup(p.stop)

    def test_overall_board_rows_carry_the_three_fields_next_to_the_legacy_keys(self):
        rows = {p["player_display_name"]: p for p in self.client.get("/api/board?pos=ALL").json()["players"]}
        a, n = rows["Amon-Ra St. Brown"], rows["Malik Nabers"]
        self.assertEqual((a["projected_ppg"], a["vorp"], a["pvs_score"]), (18.0, 6.2, 72.3))
        self.assertEqual((n["projected_ppg"], n["vorp"], n["pvs_score"]), (19.1, 7.3, 74.3))
        self.assertEqual((a["PROJ"], a["VOR"], a["PVS"]), (18.0, 6.2, 72.3))   # the existing keys are unchanged

    def test_no_row_puts_vorp_in_the_projection_column(self):
        for p in self.client.get("/api/board?pos=ALL").json()["players"]:
            self.assertGreaterEqual(p["projected_ppg"], p["vorp"])
            self.assertTrue(0 <= p["pvs_score"] <= 100)

    def test_trade_players_name_their_projection_and_pvs(self):
        p = {"player_id": "g1", "name": "Amon-Ra St. Brown", "position": "WR", "value": 18.0, "trade": 72.3, "tier": 2}
        out = tools._public_player(p)
        self.assertEqual((out["projected_ppg"], out["pvs_score"], out["vorp"]), (18.0, 72.3, None))


class InjuryDoesNotTouchValueFields(unittest.TestCase):
    def test_a_questionable_tag_on_a_wednesday_leaves_projection_vorp_and_pvs_as_they_were(self):
        # the board's PROJ/VOR/PVS are rest-of-season numbers: only the weekly projection carries the 0.90
        before = schemas.value_fields(ARSB)
        tagged = schemas.value_fields({**ARSB, "injury_status": "Questionable",
                                       "injury_report": {"note": "did not practice", "updated": "2026-10-21T18:00Z"}})
        self.assertEqual(before, tagged)


if __name__ == "__main__":
    unittest.main()
