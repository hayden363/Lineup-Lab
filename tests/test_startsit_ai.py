"""Tests for engine/startsit_ai.py: the numbers-only facts() view and the cached write_up().

The Anthropic client is faked (injected into sys.modules), so nothing touches the network.

    .venv/bin/python -m unittest tests.test_startsit_ai -v
"""
import json
import sys
import types
import unittest
from unittest import mock

from engine import news, startsit_ai


def player(name="A Player", **over):
    p = {
        "player_display_name": name, "position": "WR", "recent_team": "KC", "PROJ": 14.349,
        "decision": {"opponent": "LV", "rating": 71, "components": {"opp": 10}, "snap_pct": 88, "target_share": 24.5,
                     "hvt_pg": 6.1, "xfp_pg": 12.0, "xfp_diff": 1.2, "recent": "up", "goal_line_share": 30,
                     "td_share": 20, "script_split": {"lead": 1, "trail": 2}, "defense_rank": 5,
                     "flags_good": ["target hog"], "flags_bad": ["tough corner"]},
        "outcomes": {"p10": 4.0, "p50": 13.0, "p90": 24.0, "p_10plus": 70, "p_20plus": 15},
        "environment": {"game": {"implied_total": 26.5, "margin": 3.5, "game_total": 48.5, "weather": "dome"}},
        "injury_status": "Q",
    }
    p.update(over)
    return p


def result(*players, **over):
    r = {"mode": "start_sit", "decision": {"pick": "A Player", "confidence": "high"}, "players": list(players)}
    r.update(over)
    return r


class Facts(unittest.TestCase):
    def test_error_players_are_dropped(self):
        f = startsit_ai.facts(result(player("Ok"), {"player_display_name": "Bad", "error": "not found"}))
        self.assertEqual([p["name"] for p in f["players"]], ["Ok"])

    def test_top_level_carries_mode_and_the_models_verdict(self):
        f = startsit_ai.facts(result(player()))
        self.assertEqual(f["mode"], "start_sit")
        self.assertEqual(f["verdict"], {"pick": "A Player", "confidence": "high"})

    def test_full_player_maps_every_field(self):
        p = startsit_ai.facts(result(player()))["players"][0]
        self.assertEqual((p["name"], p["position"], p["team"], p["opponent"]), ("A Player", "WR", "KC", "LV"))
        self.assertEqual((p["p10"], p["median"], p["p90"]), (4.0, 13.0, 24.0))
        self.assertEqual((p["chance_10_plus_pct"], p["chance_20_plus_pct"]), (70, 15))
        self.assertEqual(p["vegas"], {"implied_team_total": 26.5, "spread_margin_positive_is_favored": 3.5, "game_total": 48.5})
        self.assertEqual(p["weather"], "dome")
        self.assertEqual((p["advantages"], p["warnings"]), (["target hog"], ["tough corner"]))
        self.assertEqual(p["injury_status"], "Q")

    def test_projection_is_rounded_to_one_decimal(self):
        self.assertEqual(startsit_ai.facts(result(player(PROJ=14.349)))["players"][0]["projection"], 14.3)
        self.assertEqual(startsit_ai.facts(result(player(PROJ=14.36)))["players"][0]["projection"], 14.4)

    def test_missing_projection_is_zero(self):
        self.assertEqual(startsit_ai.facts(result(player(PROJ=None)))["players"][0]["projection"], 0)

    def test_sparse_player_gives_none_not_a_crash(self):
        f = startsit_ai.facts(result({"player_display_name": "Sparse"}))["players"][0]
        self.assertEqual(f["name"], "Sparse")
        for k in ("p10", "median", "p90", "opponent", "rating_0_100", "weather", "injury_status"):
            self.assertIsNone(f[k], k)
        self.assertEqual(f["vegas"], {"implied_team_total": None, "spread_margin_positive_is_favored": None, "game_total": None})

    def test_none_valued_nested_blocks_are_tolerated(self):
        f = startsit_ai.facts(result(player(decision=None, outcomes=None, environment={"game": None})))["players"][0]
        self.assertIsNone(f["median"])
        self.assertIsNone(f["vegas"]["game_total"])

    def test_empty_result(self):
        self.assertEqual(startsit_ai.facts({})["players"], [])


class FakeAnthropic:
    """Stands in for the `anthropic` module; counts calls and returns canned text."""
    def __init__(self, text):
        self.text, self.calls = text, []
        outer = self

        class Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                if isinstance(outer.text, Exception):
                    raise outer.text
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=outer.text)])

        class Client:
            def __init__(self, api_key=None):
                outer.api_key = api_key
                self.messages = Messages()

        self.module = types.SimpleNamespace(Anthropic=Client)


GOOD = json.dumps({"diagnostics": [{"player": "A", "case": "x"}], "floor_case": "f", "ceiling_case": "c",
                   "final_call": "go", "extra": "dropped"})


class WriteUp(unittest.TestCase):
    def setUp(self):
        startsit_ai._CACHE.clear()
        self.addCleanup(startsit_ai._CACHE.clear)
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)
        self.key = mock.patch.object(news, "ANTHROPIC_API_KEY", "sk-test")
        self.key.start()

    def fake(self, text=GOOD):
        fa = FakeAnthropic(text)
        p = mock.patch.dict(sys.modules, {"anthropic": fa.module})
        p.start()
        self.addCleanup(p.stop)
        return fa

    def res(self):
        return result(player("A"), player("B"))

    def test_unconfigured_returns_none_without_calling_the_api(self):
        fa = self.fake()
        with mock.patch.object(news, "ANTHROPIC_API_KEY", ""):
            self.assertFalse(startsit_ai.configured())
            self.assertIsNone(startsit_ai.write_up(self.res()))
        self.assertEqual(fa.calls, [])

    def test_fewer_than_two_players_returns_none_without_calling_the_api(self):
        fa = self.fake()
        self.assertIsNone(startsit_ai.write_up(result(player("A"))))
        self.assertIsNone(startsit_ai.write_up(result(player("A"), {"player_display_name": "B", "error": "x"})))
        self.assertEqual(fa.calls, [])

    def test_returns_only_the_four_expected_keys(self):
        fa = self.fake()
        out = startsit_ai.write_up(self.res())
        self.assertEqual(set(out), {"diagnostics", "floor_case", "ceiling_case", "final_call"})
        self.assertEqual(out["final_call"], "go")
        self.assertEqual(fa.api_key, "sk-test")

    def test_sends_the_facts_not_the_raw_result(self):
        fa = self.fake()
        startsit_ai.write_up(self.res())
        kw = fa.calls[0]
        self.assertEqual(kw["system"], startsit_ai.SYSTEM)
        self.assertEqual(kw["model"], startsit_ai.MODEL)
        sent = json.loads(kw["messages"][0]["content"].split("Data:\n", 1)[1])
        self.assertEqual([p["name"] for p in sent["players"]], ["A", "B"])
        self.assertNotIn("player_display_name", json.dumps(sent))

    def test_tolerates_prose_around_the_json(self):
        self.fake("Sure! Here you go:\n" + GOOD + "\nHope that helps.")
        self.assertEqual(startsit_ai.write_up(self.res())["floor_case"], "f")

    def test_second_identical_call_is_served_from_cache(self):
        fa = self.fake()
        first = startsit_ai.write_up(self.res())
        second = startsit_ai.write_up(self.res())
        self.assertEqual(len(fa.calls), 1)
        self.assertIs(first, second)

    def test_different_data_misses_the_cache(self):
        fa = self.fake()
        startsit_ai.write_up(self.res())
        startsit_ai.write_up(result(player("A"), player("B", PROJ=20)))
        self.assertEqual(len(fa.calls), 2)

    def test_cache_expires_after_the_ttl(self):
        fa = self.fake()
        with mock.patch.object(startsit_ai.time, "time", return_value=1000.0):
            startsit_ai.write_up(self.res())
        with mock.patch.object(startsit_ai.time, "time", return_value=1000.0 + startsit_ai.TTL - 1):
            startsit_ai.write_up(self.res())
        self.assertEqual(len(fa.calls), 1)
        with mock.patch.object(startsit_ai.time, "time", return_value=1000.0 + startsit_ai.TTL):
            startsit_ai.write_up(self.res())
        self.assertEqual(len(fa.calls), 2)

    def test_malformed_json_returns_none_and_is_not_cached(self):
        fa = self.fake("this is not json at all")
        self.assertIsNone(startsit_ai.write_up(self.res()))
        self.assertEqual(startsit_ai._CACHE, {})
        fa.text = GOOD                                    # a retry gets a fresh call and succeeds
        self.assertIsNotNone(startsit_ai.write_up(self.res()))
        self.assertEqual(len(fa.calls), 2)

    def test_api_error_returns_none_and_is_not_cached(self):
        self.fake(RuntimeError("overloaded"))
        self.assertIsNone(startsit_ai.write_up(self.res()))
        self.assertEqual(startsit_ai._CACHE, {})


if __name__ == "__main__":
    unittest.main()
