"""Sleeper ownership check for league chat (engine/chat.verify_sleeper_owner).

A user proves they own a Sleeper team by putting their one-time token in the
team name; we re-read the league's users (force refresh) and look for it.
Sleeper and the challenge table are mocked — no network.

    .venv/bin/python -m unittest tests.test_league_chat_verify -v
"""

import unittest
from unittest import mock

import requests

from engine import chat

USERS = [
    {"user_id": "111", "display_name": "Sam", "metadata": {"team_name": "Sam's Squad llab-ab12cd34"}},
    {"user_id": "222", "display_name": "Pat", "metadata": {"team_name": "Pat's Team"}},
    {"user_id": "333", "display_name": "NoMeta", "metadata": None},
    {"user_id": "444", "display_name": "Commish", "is_owner": True, "metadata": {"team_name": "The Boss llab-0c0ffee0"}},
    {"user_id": "555", "display_name": "Odd", "metadata": {"team_name": 12345}},
]


class VerifySleeperOwner(unittest.TestCase):
    def verify(self, token, consume=True, users=USERS):
        with mock.patch.object(chat.sleeper_layer, "get_users", return_value=users) as get_users, \
                mock.patch.object(chat, "consume_challenge", return_value=consume) as consume_mock:
            try:
                result = chat.verify_sleeper_owner(7, "L1", token)
            except chat.ChatError as e:
                return e, get_users, consume_mock
            return result, get_users, consume_mock

    def test_matches_the_token_in_a_team_name_and_forces_a_fresh_read(self):
        result, get_users, consume = self.verify("llab-ab12cd34")
        self.assertEqual(result, {"external_id": "111", "is_commissioner": False})
        get_users.assert_called_once_with("L1", force=True)
        consume.assert_called_once_with(7, "sleeper", "L1", "llab-ab12cd34")

    def test_token_match_ignores_case(self):
        result, _, _ = self.verify("LLAB-AB12CD34")
        self.assertEqual(result["external_id"], "111")

    def test_fails_when_no_team_name_has_the_token_and_burns_nothing(self):
        result, _, consume = self.verify("llab-ffffffff")
        self.assertIsInstance(result, chat.ChatError)
        self.assertEqual(result.status, 400)
        consume.assert_not_called()

    def test_fails_for_an_expired_or_foreign_token_even_if_it_is_in_a_team_name(self):
        result, _, _ = self.verify("llab-ab12cd34", consume=False)
        self.assertIsInstance(result, chat.ChatError)
        self.assertEqual(result.status, 400)

    def test_users_without_metadata_do_not_crash_the_scan(self):
        result, _, _ = self.verify("llab-ab12cd34", users=[USERS[2], USERS[0]])
        self.assertEqual(result["external_id"], "111")

    def test_a_non_string_team_name_does_not_crash_the_scan(self):
        result, _, _ = self.verify("llab-ab12cd34", users=[USERS[4], USERS[0]])
        self.assertEqual(result["external_id"], "111")

    def test_the_leagues_commissioner_is_flagged(self):
        result, _, _ = self.verify("llab-0c0ffee0")
        self.assertEqual(result, {"external_id": "444", "is_commissioner": True})

    def test_a_sleeper_outage_or_unknown_league_is_a_502_not_a_500(self):
        for failure in (requests.ConnectionError("down"), requests.HTTPError("404"), requests.Timeout()):
            with mock.patch.object(chat.sleeper_layer, "get_users", side_effect=failure), \
                    mock.patch.object(chat, "consume_challenge") as consume:
                with self.assertRaises(chat.ChatError) as ctx:
                    chat.verify_sleeper_owner(7, "L1", "llab-ab12cd34")
                self.assertEqual(ctx.exception.status, 502)
                consume.assert_not_called()

    def test_a_missing_users_payload_is_a_502(self):
        with mock.patch.object(chat.sleeper_layer, "get_users", return_value=None):
            with self.assertRaises(chat.ChatError) as ctx:
                chat.verify_sleeper_owner(7, "L1", "llab-ab12cd34")
        self.assertEqual(ctx.exception.status, 502)

    def test_a_blank_token_never_matches_a_team(self):
        result, _, _ = self.verify("  ")
        self.assertIsInstance(result, chat.ChatError)
        self.assertEqual(result.status, 400)


if __name__ == "__main__":
    unittest.main()
