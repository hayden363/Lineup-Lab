"""FantasyPros consensus parsing (engine/external_projections.py).

The module's own header says its field names were never checked against a
real response, so these tests pin what the code does with the shapes it
claims to handle, and that anything else yields "no comparison" rather than
a made-up number. requests.get is always mocked: no network, no API key.

FANTASYPROS_API_KEY is read once at import, so tests patch the module
attribute rather than the environment.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import os
import unittest
from unittest import mock

from engine import external_projections as ep


def _response(payload):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def _fetch(payload, position="RB"):
    """Run _fetch_position_projections against a canned payload.
    Returns (table, printed_text, requests.get mock)."""
    out = io.StringIO()
    with mock.patch.object(ep.requests, "get", return_value=_response(payload)) as get, \
            contextlib.redirect_stdout(out):
        table = ep._fetch_position_projections(position, 2026, 5, "PPR")
    return table, out.getvalue(), get


class NormalizeName(unittest.TestCase):
    def test_suffixes_and_punctuation(self):
        cases = {
            "Marvin Harrison Jr.": "marvin harrison",
            "Michael Pittman Jr": "michael pittman",
            "Kenneth Walker III": "kenneth walker",
            "D.J. Moore": "dj moore",
            "Amon-Ra St. Brown": "amonra st brown",
            "  Ja'Marr   Chase ": "jamarr chase",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(ep.normalize_name(raw), want)

    def test_empty_and_none(self):
        self.assertEqual(ep.normalize_name(""), "")
        self.assertEqual(ep.normalize_name(None), "")


class ExtractProjection(unittest.TestCase):
    def test_fpts_wins_over_points(self):
        rec = {"player_name": "A B", "points": 1.0, "fpts": 17.4}
        self.assertEqual(ep._extract_projection(rec), ("A B", 17.4))

    def test_numeric_string_is_accepted(self):
        self.assertEqual(ep._extract_projection({"name": "A B", "fpts": "12.5"}), ("A B", 12.5))

    def test_zero_is_kept_not_skipped(self):
        self.assertEqual(ep._extract_projection({"name": "A B", "fpts": 0}), ("A B", 0.0))

    def test_unparseable_value_falls_through_to_the_next_field(self):
        rec = {"name": "A B", "fpts": "n/a", "points": 9}
        self.assertEqual(ep._extract_projection(rec), ("A B", 9.0))

    def test_none_value_falls_through_to_the_next_field(self):
        rec = {"name": "A B", "fpts": None, "projected_points": 4}
        self.assertEqual(ep._extract_projection(rec), ("A B", 4.0))

    def test_unrecognized_records_give_none(self):
        self.assertIsNone(ep._extract_projection({}))
        self.assertIsNone(ep._extract_projection({"fpts": 10.0}))
        self.assertIsNone(ep._extract_projection({"name": "A B", "rank": 3}))


class FetchPositionProjections(unittest.TestCase):
    RECORDS = [{"player_name": "Kenneth Walker III", "fpts": 14.2},
               {"name": "D.J. Moore", "points": "11"}]
    WANT = {"kenneth walker": 14.2, "dj moore": 11.0}

    def setUp(self):
        p = mock.patch.object(ep, "FANTASYPROS_API_KEY", "test-key")
        p.start()
        self.addCleanup(p.stop)

    def test_bare_list_and_each_known_envelope(self):
        payloads = {"list": self.RECORDS, "players": {"players": self.RECORDS},
                    "data": {"data": self.RECORDS}, "projections": {"projections": self.RECORDS}}
        for label, payload in payloads.items():
            with self.subTest(envelope=label):
                table, _, _ = _fetch(payload)
                self.assertEqual(table, self.WANT)

    def test_request_carries_position_week_scoring_and_key(self):
        _, _, get = _fetch(self.RECORDS, position="WR")
        args, kwargs = get.call_args
        self.assertEqual(args[0], f"{ep.BASE_URL}/2026/projections")
        self.assertEqual(kwargs["params"], {"position": "WR", "week": 5, "scoring": "PPR"})
        self.assertEqual(kwargs["headers"], {"x-api-key": "test-key"})

    def test_unknown_envelope_gives_empty_table_and_says_so(self):
        table, printed, _ = _fetch({"results": self.RECORDS})
        self.assertEqual(table, {})
        self.assertIn("unrecognized FantasyPros response shape", printed)
        self.assertIn("results", printed)

    def test_no_record_parsed_gives_empty_table_and_says_so(self):
        table, printed, _ = _fetch([{"rank": 1}, {"rank": 2}])
        self.assertEqual(table, {})
        self.assertIn("parsed 0/2", printed)

    def test_unparseable_records_are_skipped_not_guessed(self):
        table, _, _ = _fetch([{"rank": 1}, self.RECORDS[0]])
        self.assertEqual(table, {"kenneth walker": 14.2})

    def test_http_failure_gives_empty_table_without_raising(self):
        out = io.StringIO()
        with mock.patch.object(ep.requests, "get", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stdout(out):
            table = ep._fetch_position_projections("RB", 2026, 5, "PPR")
        self.assertEqual(table, {})
        self.assertIn("fetch failed", out.getvalue())

    def test_debug_env_prints_the_raw_payload(self):
        with mock.patch.dict(os.environ, {"FANTASYPROS_DEBUG": "1"}):
            _, printed, _ = _fetch({"results": [{"zzz_field": 1}]})
        self.assertIn("raw payload", printed)
        self.assertIn("zzz_field", printed)

    def test_raw_payload_is_not_printed_without_the_debug_env(self):
        env = {k: v for k, v in os.environ.items() if k != "FANTASYPROS_DEBUG"}
        with mock.patch.dict(os.environ, env, clear=True):
            _, printed, _ = _fetch({"results": [{"zzz_field": 1}]})
        self.assertNotIn("zzz_field", printed)


class ProjectionForPlayer(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(ep._MEM_CACHE, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_unconfigured_returns_none_and_never_calls_out(self):
        with mock.patch.object(ep, "FANTASYPROS_API_KEY", None), \
                mock.patch.object(ep.requests, "get") as get:
            result = ep.projection_for_player("Kenneth Walker III", "RB", 2026, week=5)
        get.assert_not_called()
        self.assertEqual(result, {"configured": False, "source": ep.SOURCE_NAME,
                                  "detail": ep.SOURCE_DETAIL, "proj": None, "week": 5})

    def test_matched_player_is_rounded_to_one_decimal(self):
        payload = [{"player_name": "Kenneth Walker", "fpts": 14.26}]
        with mock.patch.object(ep, "FANTASYPROS_API_KEY", "test-key"), \
                mock.patch.object(ep.requests, "get", return_value=_response(payload)):
            result = ep.projection_for_player("Kenneth Walker III", "RB", 2026, week=5)
        self.assertTrue(result["configured"])
        self.assertEqual(result["proj"], 14.3)

    def test_unmatched_player_has_no_projection(self):
        payload = [{"player_name": "Someone Else", "fpts": 9.0}]
        with mock.patch.object(ep, "FANTASYPROS_API_KEY", "test-key"), \
                mock.patch.object(ep.requests, "get", return_value=_response(payload)):
            result = ep.projection_for_player("Kenneth Walker III", "RB", 2026, week=5)
        self.assertIsNone(result["proj"])

    def test_def_is_requested_as_dst(self):
        with mock.patch.object(ep, "FANTASYPROS_API_KEY", "test-key"), \
                mock.patch.object(ep.requests, "get", return_value=_response([])) as get:
            ep.projection_for_player("Seattle Seahawks", "DEF", 2026, week=5)
        self.assertEqual(get.call_args.kwargs["params"]["position"], "DST")

    def test_unsupported_position_never_calls_out(self):
        with mock.patch.object(ep, "FANTASYPROS_API_KEY", "test-key"), \
                mock.patch.object(ep.requests, "get") as get:
            result = ep.projection_for_player("Some Punter", "P", 2026, week=5)
        get.assert_not_called()
        self.assertIsNone(result["proj"])


if __name__ == "__main__":
    unittest.main()
