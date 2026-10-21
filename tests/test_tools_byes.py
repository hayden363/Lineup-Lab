import unittest

import pandas as pd

from engine import tools


class TeamOnByeTest(unittest.TestCase):
    def bundle(self):
        rows = [(w, "AAA", "BBB") for w in (1, 3)] + [(2, "CCC", "BBB"), (1, "CCC", "DDD"), (3, "CCC", "DDD")]
        return {"schedule": pd.DataFrame(rows, columns=["week", "home_team", "away_team"])}

    def test_bye_week_only_for_that_team_and_week(self):
        b = self.bundle()
        self.assertTrue(tools._team_on_bye(b, "AAA", 2))
        self.assertFalse(tools._team_on_bye(b, "AAA", 1))
        self.assertFalse(tools._team_on_bye(b, "CCC", 2))

    def test_no_week_or_team_is_never_a_bye(self):
        b = self.bundle()
        self.assertFalse(tools._team_on_bye(b, "AAA", None))
        self.assertFalse(tools._team_on_bye(b, None, 2))


if __name__ == "__main__":
    unittest.main()
