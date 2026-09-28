"""engine.role_baseline — the rank-for-rank fallback for players with no
game log of their own (usually rookies): a player who is his team's live RB2
gets that team's real RB2 per-game production from last season.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import unittest

import pandas as pd

from engine.role_baseline import (build_role_rank_baselines, resolve_role_rank_projection,
                                  team_position_rank_baseline)


def _games(player_id, team, position, points):
    return pd.DataFrame({"player_id": player_id, "recent_team": team, "position": position,
                         "week": range(1, len(points) + 1), "fpts_active": points})


WK = pd.concat([
    _games("rb_a", "AAA", "RB", [10.0, 12.0, 14.0]),   # 12.0/g -> AAA RB2
    _games("rb_b", "AAA", "RB", [18.0, 20.0]),         # 19.0/g -> AAA RB1
    _games("rb_c", "AAA", "RB", [30.0]),               # 1 game: below min_games, excluded
    _games("rb_d", "BBB", "RB", [7.0, 9.0]),           #  8.0/g -> BBB RB1
    _games("qb_a", "AAA", "QB", [20.0, 22.0]),         # QBs are never ranked here
])


class RankBaseline(unittest.TestCase):
    def test_ranks_the_teams_own_producers_by_per_game_output(self):
        self.assertEqual(team_position_rank_baseline(WK, "RB")["AAA"], {1: 19.0, 2: 12.0})

    def test_players_under_min_games_are_left_out(self):
        # rb_c's single 30-point game must not become AAA's RB1.
        self.assertNotIn(30.0, team_position_rank_baseline(WK, "RB")["AAA"].values())
        self.assertEqual(team_position_rank_baseline(WK, "RB", min_games=1)["AAA"][1], 30.0)

    def test_teams_are_ranked_separately(self):
        self.assertEqual(team_position_rank_baseline(WK, "RB")["BBB"], {1: 8.0})

    def test_quarterbacks_are_not_part_of_the_fallback(self):
        self.assertEqual(set(build_role_rank_baselines(WK)), {"RB", "WR", "TE"})


class Resolve(unittest.TestCase):
    BASE = build_role_rank_baselines(WK)

    def test_same_rank_gets_that_ranks_real_number(self):
        self.assertEqual(resolve_role_rank_projection("AAA", 2, "RB", self.BASE), 12.0)

    def test_deeper_than_the_real_bench_gets_the_thinnest_real_rank(self):
        self.assertEqual(resolve_role_rank_projection("AAA", 5, "RB", self.BASE), 12.0)

    def test_nothing_real_to_draw_on_returns_none(self):
        self.assertIsNone(resolve_role_rank_projection("AAA", None, "RB", self.BASE))
        self.assertIsNone(resolve_role_rank_projection("ZZZ", 1, "RB", self.BASE))
        self.assertIsNone(resolve_role_rank_projection("AAA", 1, "QB", self.BASE))


if __name__ == "__main__":
    unittest.main()
