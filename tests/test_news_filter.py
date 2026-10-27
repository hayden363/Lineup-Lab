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


def P(pid, name, team=None):
    return {"player_id": pid, "player_display_name": name, "recent_team": team}


class NameVariantTests(unittest.TestCase):
    """A headline rarely spells a name exactly as the stats table does."""

    def check(self, name, headline, expect=True):
        out = filter_for_players([item(headline)], [P(1, name)])
        self.assertEqual(len(out), 1 if expect else 0, f"{name!r} vs {headline!r}")

    def test_suffix_is_dropped_either_way(self):
        self.check("Kenneth Walker III", "Kenneth Walker rushes for 120 yards")
        self.check("Michael Penix Jr.", "Michael Penix throws two TDs")
        self.check("Kenneth Walker", "Kenneth Walker III is questionable")        # headline carries the suffix

    def test_curly_apostrophe_and_dropped_apostrophe(self):
        self.check("Ja'Marr Chase", "Ja’Marr Chase returns to practice")
        self.check("Ja'Marr Chase", "JaMarr Chase returns to practice")
        self.check("D'Andre Swift", "D’Andre Swift gets 20 carries")

    def test_hyphen_period_and_initials(self):
        self.check("Amon-Ra St. Brown", "Amon-Ra St Brown catches 11 passes")
        self.check("Amon-Ra St. Brown", "Amon Ra St. Brown leads the Lions")
        self.check("C.J. Stroud", "CJ Stroud shines in Week 5")
        self.check("Jaxon Smith-Njigba", "Jaxon Smith Njigba goes off")

    def test_still_no_substring_false_positives(self):
        self.check("Mike Williams", "Mike Williamson signs with Jets", expect=False)
        self.check("Josh Allen", "Josh Allender is a local coach", expect=False)

    def test_possessive_after_a_suffixed_name(self):
        self.check("Kenneth Walker III", "Kenneth Walker's carries are rising")


class SurnameAndTeamTests(unittest.TestCase):
    WALKER = P(1, "Kenneth Walker III", "SEA")
    LAMB = P(2, "CeeDee Lamb", "DAL")

    def test_surname_plus_own_team_matches(self):
        out = filter_for_players([item("Seahawks: Walker out for Sunday")], [self.WALKER])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["match_kind"], "surname")
        self.assertEqual(out[0]["matched_players"], [{"player_id": 1, "name": "Kenneth Walker III"}])

    def test_surname_alone_is_not_enough(self):
        self.assertEqual(filter_for_players([item("Walker cleared for Sunday")], [self.WALKER]), [])

    def test_surname_with_a_different_team_is_not_a_match(self):
        self.assertEqual(filter_for_players([item("Packers: Walker (another player) is out")], [self.WALKER]), [])

    def test_player_without_a_known_team_gets_name_matching_only(self):
        self.assertEqual(filter_for_players([item("Seahawks: Walker out")], [P(1, "Kenneth Walker III")]), [])

    def test_two_roster_players_sharing_a_surname_on_one_team_disable_surname_matching(self):
        twins = [P(1, "Tyler Johnson", "TB"), P(2, "Calvin Johnson", "TB")]
        self.assertEqual(filter_for_players([item("Buccaneers: Johnson is out")], twins), [])
        self.assertEqual(len(filter_for_players([item("Buccaneers: Tyler Johnson is out")], twins)), 1)

    def test_team_aliases_and_city_names(self):
        for team, text in (("WSH", "Commanders: Hill listed"), ("LAR", "Rams note on Hill"), ("JAC", "Jaguars: Hill out"),
                           ("GB", "Green Bay: Hill hurt"), ("NE", "Pats: Hill is back")):
            out = filter_for_players([item(text)], [P(1, "Taysom Hill", team)])
            self.assertEqual(len(out), 1, text)

    def test_short_surnames_are_ignored(self):
        # under four letters ("Ray", "Lee", "Fox") is too common a word to match on its own, even with the team
        self.assertEqual(filter_for_players([item("Lions: Ray injured")], [P(1, "Jerome Ray", "DET")]), [])
        self.assertEqual(len(filter_for_players([item("Lions: Hall injured")], [P(1, "Bij Hall", "DET")])), 1)


class RankingTests(unittest.TestCase):
    def test_name_beats_surname_and_title_beats_body(self):
        walker, lamb = P(1, "Kenneth Walker III", "SEA"), P(2, "CeeDee Lamb", "DAL")
        items = [
            {**item("Seahawks: Walker out"), "ts": 300},                          # surname, newest
            {**item("Weekly notes", "CeeDee Lamb had a quiet game"), "ts": 200},  # name in summary
            {**item("CeeDee Lamb scores twice"), "ts": 100},                      # name in title, oldest
        ]
        out = filter_for_players(items, [walker, lamb])
        self.assertEqual([o["title"] for o in out], ["CeeDee Lamb scores twice", "Weekly notes", "Seahawks: Walker out"])
        self.assertEqual([o["match_kind"] for o in out], ["name", "name", "surname"])

    def test_newest_first_within_the_same_strength(self):
        a = {**item("Josh Allen old"), "ts": 100}
        b = {**item("Josh Allen new"), "ts": 900}
        out = filter_for_players([a, b], [ALLEN])
        self.assertEqual([o["title"] for o in out], ["Josh Allen new", "Josh Allen old"])


class TeamNewsTests(unittest.TestCase):
    def test_team_news_is_opt_in_ranked_last_and_capped(self):
        players = [P(1, "CeeDee Lamb", "DAL")]
        items = [item(f"Cowboys notebook {i}") for i in range(15)] + [item("CeeDee Lamb scores")]
        self.assertEqual(len(filter_for_players(items, players)), 1)
        out = filter_for_players(items, players, include_team_news=True)
        self.assertEqual(out[0]["match_kind"], "name")
        self.assertEqual(len(out), 1 + 10)                                  # TEAM_NEWS_CAP
        self.assertTrue(all(o["match_kind"] == "team" and o["matched_teams"] == ["DAL"] for o in out[1:]))
        self.assertEqual(out[1]["matched_players"], [])

    def test_a_player_match_is_not_duplicated_as_team_news(self):
        out = filter_for_players([item("Cowboys: CeeDee Lamb scores")], [P(1, "CeeDee Lamb", "DAL")], include_team_news=True)
        self.assertEqual([o["match_kind"] for o in out], ["name"])

    def test_nothing_from_other_teams(self):
        out = filter_for_players([item("Packers beat the Bears")], [P(1, "CeeDee Lamb", "DAL")], include_team_news=True)
        self.assertEqual(out, [])
