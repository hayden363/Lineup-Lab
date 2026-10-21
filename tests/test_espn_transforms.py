"""Offline pins for the pure transforms in engine/espn.py.

What's pinned: parse_league_id, scoring_from_espn, owner_name, roster_lineup
and build_unscored_resolver, each fed hand-built stand-ins (SimpleNamespace /
dicts) shaped like the espn-api objects they read.

Why: engine/espn.py has never been run against a live ESPN league; its
shapes come from reading espn-api's source. These tests lock the current
behaviour so a refactor can't silently change it, and so the first live
capture has a known baseline to be compared against. No network, no real
espn_api League is ever constructed.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest
from types import SimpleNamespace

from engine import espn


class ParseLeagueId(unittest.TestCase):
    def test_full_url(self):
        url = "https://fantasy.espn.com/football/team?leagueId=1234567&teamId=3"
        self.assertEqual(espn.parse_league_id(url), "1234567")

    def test_too_short_is_none(self):
        self.assertIsNone(espn.parse_league_id("1234"))

    def test_empty_is_none(self):
        self.assertIsNone(espn.parse_league_id(""))

    def test_whitespace_is_stripped(self):
        self.assertEqual(espn.parse_league_id(" 98765 "), "98765")


class ScoringFromEspn(unittest.TestCase):
    def test_maps_known_ids_and_skips_unknown(self):
        league = SimpleNamespace(settings=SimpleNamespace(scoring_format=[
            {"id": 41, "points": 1.0},
            {"id": 999, "points": 5.0},  # not in ESPN_STAT_ID_MAP -> skipped
            {"id": 3, "points": 0.04},
            {"id": 72},                  # no points -> defaults to 0
        ]))
        self.assertEqual(
            espn.scoring_from_espn(league),
            {"reception": 1.0, "pass_yard": 0.04, "fumble_lost": 0},
        )

    def test_reception_stat_53_is_read(self):
        # Real leagues label receptions with id 53; reading only 41 scored
        # every half-PPR or standard league as full PPR.
        half = SimpleNamespace(settings=SimpleNamespace(scoring_format=[{"id": 53, "points": 0.5}]))
        std = SimpleNamespace(settings=SimpleNamespace(scoring_format=[{"id": 53, "points": 0.0}]))
        self.assertEqual(espn.scoring_from_espn(half), {"reception": 0.5})
        self.assertEqual(espn.scoring_from_espn(std), {"reception": 0.0})

    def test_separate_two_point_stats(self):
        league = SimpleNamespace(settings=SimpleNamespace(scoring_format=[
            {"id": 19, "points": 2.0}, {"id": 26, "points": 2.0}, {"id": 44, "points": 2.0}]))
        self.assertEqual(espn.scoring_from_espn(league), {"two_pt": 2.0})


class OwnerName(unittest.TestCase):
    def test_no_owners_is_none(self):
        self.assertIsNone(espn.owner_name(SimpleNamespace(owners=[])))

    def test_falls_back_to_display_name(self):
        team = SimpleNamespace(owners=[{"firstName": "", "lastName": "", "displayName": "dn"}])
        self.assertEqual(espn.owner_name(team), "dn")

    def test_first_and_last_name(self):
        team = SimpleNamespace(owners=[{"firstName": "A", "lastName": "B"}])
        self.assertEqual(espn.owner_name(team), "A B")


def _player(player_id, position, pro_team, slot):
    return SimpleNamespace(
        playerId=player_id, position=position, proTeam=pro_team,
        lineupSlot=slot, name="x",
    )


def _team():
    return SimpleNamespace(roster=[
        _player(1, "QB", None, "QB"),
        _player(-16, "D/ST", "PHI", "D/ST"),
        _player(2, "RB", None, "BE"),
        _player(3, "WR", None, "IR"),
        _player(4, "WR", None, ""),
        _player(-20001, "TQB", "BUF", "OP"),
    ])


class RosterLineup(unittest.TestCase):
    def setUp(self):
        self.raw_ids, self.starters, self.slot_labels = espn.roster_lineup(_team())

    def test_raw_ids_use_team_code_for_dst(self):
        self.assertEqual(self.raw_ids, ["1", "PHI", "2", "3", "4", "-20001"])

    def test_bench_and_ir_are_not_starters(self):
        self.assertEqual(self.starters, ["1", "-20001", "PHI", "4"])

    def test_slot_labels_align_with_starters(self):
        self.assertEqual(self.slot_labels, ["QB", "OP", "D/ST", ""])

    def test_empty_lineup_slot_is_currently_counted_as_starter(self):
        """PINS CURRENT behaviour, not a verified-correct one: BENCH_SLOTS is
        only {"BE", "IR"}, so a player whose lineupSlot is "" lands in
        starters. Whether ESPN ever really sends an empty slot, and whether
        that should count as a starter, is decided by the first live ESPN
        capture -- if it turns out to be a bug, change this test with it."""
        self.assertIn("4", self.starters)
        self.assertIn("", self.slot_labels)


class RosterLineupOrder(unittest.TestCase):
    def test_starters_read_qb_rb_wr_te_flex_dst_k(self):
        team = SimpleNamespace(roster=[
            _player(1, "K", "BUF", "K"), _player(2, "WR", None, "WR"),
            _player(3, "RB", None, "RB/WR/TE"), _player(4, "RB", None, "RB"),
            _player(5, "D/ST", "PHI", "D/ST"), _player(6, "TE", None, "TE"),
            _player(7, "QB", None, "QB"), _player(8, "RB", None, "RB"),
            _player(9, "WR", None, "WR"), _player(10, "WR", None, "BE"),
        ])
        _, starters, labels = espn.roster_lineup(team)
        self.assertEqual(labels, ["QB", "RB", "RB", "WR", "WR", "TE", "RB/WR/TE", "D/ST", "K"])
        self.assertEqual(starters[0], "7")
        self.assertEqual(starters[1:3], ["4", "8"])  # ESPN order kept within a slot


class BuildUnscoredResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = espn.build_unscored_resolver(SimpleNamespace(teams=[_team()]))

    def _row(self, raw_id):
        row = self.resolver(raw_id)
        assert row is not None, f"resolver returned None for {raw_id!r}"
        return row

    def test_dst_position_normalized_to_def(self):
        self.assertEqual(self._row("PHI")["position"], "DEF")

    def test_dst_headshot_is_team_logo(self):
        self.assertEqual(
            self._row("PHI")["headshot_url"],
            "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png",
        )

    def test_team_qb_keeps_position(self):
        self.assertEqual(self._row("-20001")["position"], "TQB")

    def test_team_qb_pseudo_id_has_no_headshot(self):
        self.assertIsNone(self._row("-20001")["headshot_url"])

    def test_real_player_headshot(self):
        self.assertEqual(
            self._row("1")["headshot_url"],
            "https://a.espncdn.com/i/headshots/nfl/players/full/1.png",
        )

    def test_unknown_id_is_none(self):
        self.assertIsNone(self.resolver("unknown"))

    def test_no_depth_chart_order(self):
        self.assertIsNone(self._row("1")["depth_chart_order"])


if __name__ == "__main__":
    unittest.main()
