"""engine/news.filter_for_players: full-name matching on word boundaries.
No network: feed items are built by hand."""
import unittest

from engine.news import filter_for_players


def item(title, summary=""):
    return {"source": "test", "title": title, "summary": summary, "link": "", "published": "", "image": None}


WILLIAMS = {"player_id": 1, "player_display_name": "Mike Williams"}
ALLEN = {"player_id": 2, "player_display_name": "Josh Allen"}


class FilterForPlayersTests(unittest.TestCase):
    def test_exact_full_name_matches(self):
        out = filter_for_players([item("Mike Williams catches two TDs")], [WILLIAMS])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["matched_players"], [{"player_id": 1, "name": "Mike Williams"}])

    def test_match_is_case_insensitive(self):
        self.assertEqual(len(filter_for_players([item("MIKE WILLIAMS OUT")], [WILLIAMS])), 1)

    def test_longer_name_does_not_match(self):
        self.assertEqual(filter_for_players([item("Mike Williamson signs with Jets")], [WILLIAMS]), [])

    def test_name_inside_a_longer_word_on_the_left_does_not_match(self):
        self.assertEqual(filter_for_players([item("Jimmike Williams note")], [WILLIAMS]), [])

    def test_possessive_and_punctuation_still_match(self):
        items = [item("Josh Allen's ankle is fine"), item("Questionable: Josh Allen."), item("(Josh Allen) practices")]
        self.assertEqual(len(filter_for_players(items, [ALLEN])), 3)

    def test_match_in_summary(self):
        self.assertEqual(len(filter_for_players([item("Bills notes", "Josh Allen threw 40 times")], [ALLEN])), 1)

    def test_player_without_display_name_is_skipped(self):
        players = [{"player_id": 9, "player_display_name": ""}, {"player_id": 8, "player_display_name": None}, ALLEN]
        out = filter_for_players([item("Josh Allen update")], players)
        self.assertEqual(out[0]["matched_players"], [{"player_id": 2, "name": "Josh Allen"}])

    def test_missing_summary_key_does_not_raise(self):
        self.assertEqual(len(filter_for_players([{"title": "Josh Allen update"}], [ALLEN])), 1)

    def test_feed_order_is_preserved(self):
        items = [item("Josh Allen first"), item("nothing"), item("Mike Williams second"), item("Josh Allen third")]
        out = filter_for_players(items, [ALLEN, WILLIAMS])
        self.assertEqual([o["title"] for o in out], ["Josh Allen first", "Mike Williams second", "Josh Allen third"])

    def test_same_name_players_both_attach(self):
        twins = [{"player_id": 2, "player_display_name": "Josh Allen"}, {"player_id": 3, "player_display_name": "Josh Allen"}]
        out = filter_for_players([item("Josh Allen update")], twins)
        self.assertEqual([m["player_id"] for m in out[0]["matched_players"]], [2, 3])


if __name__ == "__main__":
    unittest.main()
