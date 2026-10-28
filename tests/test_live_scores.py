"""engine.live_scores: ESPN scoreboard parsing and the 20 s cache.

What is pinned:
  * _team_info reads the score only when it is a whole number.
  * _parse_event returns None for any structurally broken event (missing or
    null competitions, status, status type, competitors) instead of raising.
  * live_scoreboard caches for TTL_SECONDS, refetches on force=True, serves
    the last good games after a failure, and one malformed event never blanks
    the rest of the scoreboard.

ESPN's feed is undocumented; whether it ever really sends a null status,
status type or competitor is NOT verified. These cases are a robustness
guard, not a fix for an observed outage.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from unittest import mock

from engine import live_scores
from engine.live_scores import _parse_event, _team_info, live_scoreboard


def _competitor(home_away, abbr, score="0", winner=False):
    return {
        "homeAway": home_away,
        "score": score,
        "winner": winner,
        "team": {"abbreviation": abbr, "shortDisplayName": abbr.title()},
    }


def _event(event_id="1", state="in", competitors=None):
    return {
        "id": event_id,
        "date": "2026-10-18T17:00Z",
        "week": {"number": 6},
        "competitions": [{
            "status": {
                "period": 3,
                "displayClock": "10:42",
                "type": {"state": state, "shortDetail": "10:42 - 3rd", "completed": state == "post"},
            },
            "competitors": competitors if competitors is not None else [
                _competitor("home", "KC", "21"), _competitor("away", "BUF", "17"),
            ],
        }],
    }


def _response(payload):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


class TeamInfo(unittest.TestCase):
    def test_string_score(self):
        self.assertEqual(_team_info({"score": "14"})["score"], 14)

    def test_int_score(self):
        self.assertEqual(_team_info({"score": 14})["score"], 14)

    def test_empty_score_is_none(self):
        self.assertIsNone(_team_info({"score": ""})["score"])

    def test_negative_score_is_none(self):
        self.assertIsNone(_team_info({"score": "-1"})["score"])


class ParseEvent(unittest.TestCase):
    def test_full_event(self):
        g = _parse_event(_event(state="post"))
        self.assertEqual(g["game_id"], "1")
        self.assertEqual(g["week"], 6)
        self.assertEqual(g["state"], "post")
        self.assertEqual(g["period"], 3)
        self.assertTrue(g["completed"])
        self.assertEqual(g["home"]["abbr"], "KC")
        self.assertEqual(g["home"]["score"], 21)
        self.assertEqual(g["away"]["abbr"], "BUF")

    def test_competitors_null(self):
        e = _event()
        e["competitions"][0]["competitors"] = None
        self.assertIsNone(_parse_event(e))

    def test_competitions_empty(self):
        e = _event()
        e["competitions"] = []
        self.assertIsNone(_parse_event(e))

    def test_competitions_missing(self):
        e = _event()
        del e["competitions"]
        self.assertIsNone(_parse_event(e))

    def test_no_home_or_no_away(self):
        self.assertIsNone(_parse_event(_event(competitors=[_competitor("home", "KC")])))
        self.assertIsNone(_parse_event(_event(competitors=[_competitor("away", "BUF")])))

    def test_status_null(self):
        e = _event()
        e["competitions"][0]["status"] = None
        g = _parse_event(e)  # must not raise
        self.assertIsNotNone(g)  # a null status degrades to a pre-game card, teams intact
        self.assertEqual(g["state"], "pre")

    def test_status_type_null(self):
        e = _event()
        e["competitions"][0]["status"]["type"] = None
        g = _parse_event(e)
        self.assertIsNotNone(g)
        self.assertEqual(g["state"], "pre")

    def test_null_competitor_entry(self):
        e = _event(competitors=[None, _competitor("away", "BUF")])
        self.assertIsNone(_parse_event(e))


class Scoreboard(unittest.TestCase):
    def setUp(self):
        live_scores._CACHE.update({"at": 0, "games": []})

    def test_second_call_within_ttl_uses_cache(self):
        with mock.patch("engine.live_scores.requests.get", return_value=_response({"events": [_event()]})) as get:
            first = live_scoreboard()
            second = live_scoreboard()
        self.assertEqual(get.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)

    def test_force_refetches(self):
        with mock.patch("engine.live_scores.requests.get", return_value=_response({"events": [_event()]})) as get:
            live_scoreboard()
            live_scoreboard(force=True)
        self.assertEqual(get.call_count, 2)

    def test_failure_after_good_fetch_returns_last_good(self):
        with mock.patch("engine.live_scores.requests.get", return_value=_response({"events": [_event()]})):
            good = live_scoreboard()
        with mock.patch("engine.live_scores.requests.get", side_effect=RuntimeError("boom")):
            after = live_scoreboard(force=True)
        self.assertEqual(after, good)
        self.assertEqual(len(after), 1)

    def test_first_call_failure_returns_empty(self):
        with mock.patch("engine.live_scores.requests.get", side_effect=RuntimeError("boom")):
            self.assertEqual(live_scoreboard(), [])

    def test_failure_stamps_cache_so_next_call_does_not_refetch(self):
        with mock.patch("engine.live_scores.requests.get", side_effect=RuntimeError("boom")) as get:
            live_scoreboard()
            live_scoreboard()
        self.assertEqual(get.call_count, 1)

    def test_one_malformed_event_keeps_the_good_games(self):
        bad = _event(event_id="bad")
        bad["competitions"][0]["status"] = None
        bad["competitions"][0]["competitors"] = [None, None]
        events = [_event("a"), bad, _event("b")]
        with mock.patch("engine.live_scores.requests.get", return_value=_response({"events": events})):
            games = live_scoreboard()
        self.assertEqual([g["game_id"] for g in games], ["a", "b"])


class EnrichedEventTests(unittest.TestCase):
    def _rich(self):
        e = _event(state="in")
        e["date"] = "2026-11-02T01:20Z"                      # Sunday 8:20 pm ET
        for c in e["competitions"][0]["competitors"]:
            c["team"]["id"] = "12" if c["homeAway"] == "home" else "4"
        comp = e["competitions"][0]
        comp["broadcasts"] = [{"market": "national", "names": ["NBC"]}]
        comp["odds"] = [{"details": "KC -2.5", "overUnder": 47.5}]
        comp["situation"] = {"down": 2, "distance": 4, "possession": "12", "possessionText": "KC 38",
                             "downDistanceText": "2nd & 4 at KC 38", "isRedZone": False}
        comp["venue"] = {"indoor": False}
        e["weather"] = {"displayValue": "Clear", "temperature": 55}
        return e

    def test_prime_time_badge_network_odds_and_weather_come_through(self):
        g = _parse_event(self._rich())
        self.assertEqual((g["badge"], g["network"]), ("SNF", "NBC"))
        self.assertEqual((g["odds"]["favorite"], g["odds"]["spread"], g["odds"]["total"]), ("KC", 2.5, 47.5))
        self.assertEqual((g["weather"]["temp"], g["weather"]["indoor"]), (55, False))

    def test_live_situation_is_placed_on_the_field(self):
        g = _parse_event(self._rich())
        self.assertEqual((g["situation"]["possession"], g["situation"]["down"], g["situation"]["direction"]),
                         ("KC", 2, "right-to-left"))          # KC is the home team
        self.assertEqual(g["situation"]["yard_line"], 62)

    def test_plain_events_still_parse_with_empty_extras(self):
        g = _parse_event(_event())
        self.assertEqual((g["badge"], g["network"], g["odds"], g["situation"]), (None, None, None, None))


if __name__ == "__main__":
    unittest.main()
