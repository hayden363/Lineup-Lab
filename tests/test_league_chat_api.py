"""League chat HTTP routes (/api/chat/*).

Auth is overridden and the data layer is mocked where the route, not the layer,
is under test; the membership gate is exercised against the real engine/chat
functions with only get_member patched. No network, no database.

    .venv/bin/python -m unittest tests.test_league_chat_api -v
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import chat

USER = {"id": 7, "username": "sam", "email": "sam@example.com", "email_verified": True}
MEMBER = {"role": "member", "muted_until": None, "external_id": "111"}
LEAGUE = {"platform": "sleeper", "league_id": "1392639173193633792"}


class ChatApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.addCleanup(server.app.dependency_overrides.clear)
        server._RATE_BUCKETS.clear()
        self.addCleanup(server._RATE_BUCKETS.clear)

    def sign_in(self):
        server.app.dependency_overrides[server.require_user] = lambda: USER

    def test_every_route_requires_sign_in(self):
        for method, path in [
            ("post", "/api/chat/challenge"), ("post", "/api/chat/join"),
            ("get", "/api/chat/messages?platform=sleeper&league_id=L1"), ("post", "/api/chat/messages"),
            ("delete", "/api/chat/messages/1"), ("post", "/api/chat/report"), ("post", "/api/chat/mute"),
        ]:
            r = getattr(self.client, method)(path)
            self.assertEqual(r.status_code, 401, f"{method} {path}")

    def test_messages_are_403_for_a_non_member_and_never_read(self):
        self.sign_in()
        with mock.patch.object(chat, "get_member", return_value=None), \
                mock.patch.object(chat, "list_messages") as listing:
            r = self.client.get("/api/chat/messages", params=LEAGUE)
        self.assertEqual(r.status_code, 403)
        listing.assert_not_called()

    def test_posting_is_403_for_a_non_member_and_nothing_is_stored(self):
        self.sign_in()
        with mock.patch.object(chat, "get_member", return_value=None), \
                mock.patch.object(chat.db, "_conn") as conn:
            r = self.client.post("/api/chat/messages", json={**LEAGUE, "body": "hi"})
        self.assertEqual(r.status_code, 403)
        conn.assert_not_called()

    def test_member_reads_messages_with_their_role(self):
        self.sign_in()
        with mock.patch.object(chat, "get_member", return_value=MEMBER), \
                mock.patch.object(chat, "list_messages", return_value=[{"id": 4, "body": "yo"}]) as listing:
            r = self.client.get("/api/chat/messages", params={**LEAGUE, "after": "3"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"messages": [{"id": 4, "body": "yo"}], "role": "member"})
        listing.assert_called_once_with("sleeper", "1392639173193633792", after=3)

    def test_garbage_after_is_a_400_not_a_500(self):
        self.sign_in()
        with mock.patch.object(chat, "get_member", return_value=MEMBER), \
                mock.patch.object(chat, "list_messages") as listing:
            r = self.client.get("/api/chat/messages", params={**LEAGUE, "after": "abc"})
        self.assertEqual(r.status_code, 400)
        listing.assert_not_called()

    def test_negative_after_is_treated_as_zero(self):
        self.sign_in()
        with mock.patch.object(chat, "get_member", return_value=MEMBER), \
                mock.patch.object(chat, "list_messages", return_value=[]) as listing:
            r = self.client.get("/api/chat/messages", params={**LEAGUE, "after": "-9"})
        self.assertEqual(r.status_code, 200)
        listing.assert_called_once_with("sleeper", "1392639173193633792", after=0)

    def test_the_eleventh_post_in_a_minute_is_429(self):
        self.sign_in()
        with mock.patch.object(chat, "post_message", return_value={"id": 1}):
            codes = [self.client.post("/api/chat/messages", json={**LEAGUE, "body": "hi"}).status_code
                     for _ in range(11)]
        self.assertEqual(codes, [200] * 10 + [429])

    def test_the_post_limit_is_per_user_not_per_address(self):
        with mock.patch.object(chat, "post_message", return_value={"id": 1}):
            for user_id in (7, 8):
                server.app.dependency_overrides[server.require_user] = lambda uid=user_id: {**USER, "id": uid}
                for _ in range(10):
                    self.assertEqual(self.client.post("/api/chat/messages", json={**LEAGUE, "body": "hi"}).status_code, 200)

    def test_chat_layer_errors_keep_their_status_and_message(self):
        self.sign_in()
        with mock.patch.object(chat, "post_message", side_effect=chat.ChatError("You're muted in this chat for now.", 403)):
            r = self.client.post("/api/chat/messages", json={**LEAGUE, "body": "hi"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("muted", r.json()["detail"])

    def test_challenge_is_sleeper_only(self):
        self.sign_in()
        with mock.patch.object(chat, "create_challenge") as create:
            r = self.client.post("/api/chat/challenge", json={"platform": "espn", "league_id": "9"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Sleeper", r.json()["detail"])
        create.assert_not_called()

    def test_challenge_returns_a_token_and_its_lifetime(self):
        self.sign_in()
        with mock.patch.object(chat, "create_challenge", return_value="llab-ab12cd34") as create:
            r = self.client.post("/api/chat/challenge", json=LEAGUE)
        self.assertEqual(r.json(), {"token": "llab-ab12cd34", "expires_in": 900})
        create.assert_called_once_with(7, "sleeper", "1392639173193633792")

    def test_join_verifies_ownership_before_adding_the_member(self):
        self.sign_in()
        calls = []
        proof = {"external_id": "111", "is_commissioner": False}
        with mock.patch.object(chat, "verify_sleeper_owner", side_effect=lambda *a: calls.append("verify") or proof), \
                mock.patch.object(chat, "add_member", side_effect=lambda *a: calls.append("add") or {"role": "member"}) as add:
            r = self.client.post("/api/chat/join", json={**LEAGUE, "token": "llab-ab12cd34"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(calls, ["verify", "add"])
        add.assert_called_once_with(7, "sleeper", "1392639173193633792", "111", "member")
        self.assertEqual(r.json(), {"member": {"role": "member"}})

    def test_only_the_leagues_commissioner_is_made_a_moderator(self):
        self.sign_in()
        proof = {"external_id": "444", "is_commissioner": True}
        with mock.patch.object(chat, "verify_sleeper_owner", return_value=proof), \
                mock.patch.object(chat, "add_member", return_value={"role": "moderator"}) as add:
            self.client.post("/api/chat/join", json={**LEAGUE, "token": "llab-0c0ffee0"})
        add.assert_called_once_with(7, "sleeper", "1392639173193633792", "444", "moderator")

    def test_a_role_in_the_request_body_is_ignored(self):
        self.sign_in()
        proof = {"external_id": "111", "is_commissioner": False}
        with mock.patch.object(chat, "verify_sleeper_owner", return_value=proof), \
                mock.patch.object(chat, "add_member", return_value={"role": "member"}) as add:
            self.client.post("/api/chat/join", json={**LEAGUE, "token": "llab-ab12cd34", "role": "moderator"})
        add.assert_called_once_with(7, "sleeper", "1392639173193633792", "111", "member")

    def test_league_ids_that_are_not_plain_numbers_never_reach_sleeper(self):
        self.sign_in()
        for bad in ("../../x", "1/2", "12 34", "", "9" * 40, "abc"):
            server._RATE_BUCKETS.clear()  # six bad ids would otherwise trip the 5-per-10-minutes challenge limit
            with mock.patch.object(chat, "create_challenge") as create, \
                    mock.patch.object(chat, "verify_sleeper_owner") as verify:
                a = self.client.post("/api/chat/challenge", json={"platform": "sleeper", "league_id": bad})
                b = self.client.post("/api/chat/join", json={"platform": "sleeper", "league_id": bad, "token": "llab-ab12cd34"})
            self.assertEqual((a.status_code, b.status_code), (400, 400), bad)
            create.assert_not_called()
            verify.assert_not_called()

    def test_a_failed_verification_adds_nobody(self):
        self.sign_in()
        with mock.patch.object(chat, "verify_sleeper_owner", side_effect=chat.ChatError("nope", 400)), \
                mock.patch.object(chat, "add_member") as add:
            r = self.client.post("/api/chat/join", json={**LEAGUE, "token": "llab-ffffffff"})
        self.assertEqual(r.status_code, 400)
        add.assert_not_called()

    def test_delete_report_and_mute_pass_the_signed_in_user_through(self):
        self.sign_in()
        with mock.patch.object(chat, "delete_message") as delete, \
                mock.patch.object(chat, "report_message") as report, \
                mock.patch.object(chat, "mute_member") as mute:
            self.assertEqual(self.client.delete("/api/chat/messages/5").status_code, 200)
            self.assertEqual(self.client.post("/api/chat/report", json={"message_id": 5}).status_code, 200)
            self.assertEqual(self.client.post("/api/chat/mute", json={**LEAGUE, "user_id": 8, "minutes": 30}).status_code, 200)
        delete.assert_called_once_with(7, 5)
        report.assert_called_once_with(7, 5)
        mute.assert_called_once_with(7, 8, "sleeper", "1392639173193633792", 30)

    def test_deleting_a_missing_message_is_404(self):
        self.sign_in()
        with mock.patch.object(chat, "delete_message", side_effect=chat.ChatError("That message doesn't exist.", 404)):
            self.assertEqual(self.client.delete("/api/chat/messages/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
