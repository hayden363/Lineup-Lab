import unittest

import server


class ESPNErrorMessageTests(unittest.TestCase):
    def test_private_league_says_make_public(self):
        class ESPNAccessDenied(Exception):
            pass
        msg = server._espn_error_message(ESPNAccessDenied("League 1 cannot be accessed"))
        self.assertIn("isn't public", msg)
        self.assertIn("Make League Viewable to Public", msg)

    def test_missing_league_points_at_id(self):
        class ESPNInvalidLeague(Exception):
            pass
        self.assertIn("league ID", server._espn_error_message(ESPNInvalidLeague("x")))

    def test_unknown_error_still_mentions_public(self):
        self.assertIn("public", server._espn_error_message(RuntimeError("boom")))


if __name__ == "__main__":
    unittest.main()
