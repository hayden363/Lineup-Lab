import unittest
import pandas as pd
from engine import board as B


def mk(rows):
    return pd.DataFrame(rows, columns=["games", "fpts_per_game"])


class ShrinkTests(unittest.TestCase):
    def test_small_sample_pulled_toward_pool(self):
        b = mk([(5, 30.0)] + [(8, 15.0)] * 30)
        r = B.shrunk_rate(b, "RB")
        self.assertLess(r.iloc[0], 30.0)
        self.assertGreater(r.iloc[0], 15.0)

    def test_full_season_barely_moves(self):
        b = mk([(16, 30.0)] + [(16, 15.0)] * 30)
        self.assertGreater(B.shrunk_rate(b, "RB").iloc[0], 27.0)

    def test_more_games_means_less_shrink(self):
        a = B.shrunk_rate(mk([(4, 30.0)] + [(8, 15.0)] * 30), "RB").iloc[0]
        c = B.shrunk_rate(mk([(12, 30.0)] + [(8, 15.0)] * 30), "RB").iloc[0]
        self.assertGreater(c, a)

    def test_projection_uses_rate_column(self):
        b = pd.DataFrame({"fpts_per_game": [30.0], "rate": [20.0]})
        self.assertEqual(B._rate(b).iloc[0], 20.0)


if __name__ == "__main__":
    unittest.main()
