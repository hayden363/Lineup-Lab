"""Daily Drive upgrade (2026-11-18): a frozen puzzle per day, answer rarity after the game, the missed-guess log with
friendlier reasons, a stricter typo rule, and the league leaderboard."""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from engine import daily_drive as dd
from engine import daily_drive_history_snapshot as snap
from engine import daily_drive_scores as ds
from tests.test_daily_drive import _pool


class UnitTests(unittest.TestCase):
    def test_rarity_rounds_and_never_shows_zero_for_a_pick(self):
        self.assertEqual(ds.rarity(1, 300), {"n": 1, "players": 300, "pct": 1})
        self.assertEqual(ds.rarity(30, 200)["pct"], 15)
        self.assertEqual(ds.rarity(0, 10)["pct"], 0)
        self.assertIsNone(ds.rarity(0, 0)["pct"])

    def test_picks_from_tokens_first_per_prompt(self):
        with mock.patch.dict(os.environ, {"APP_SECRET_KEY": "k"}):
            p = [{"id": "p1"}, {"id": "p2"}]
            toks = [ds.sign_token("2026-11-18", "p1", "a1", 2), ds.sign_token("2026-11-18", "p1", "a9", 3),
                    ds.sign_token("2026-11-18", "p2", "b1", 1), "junk.tok"]
            self.assertEqual(ds.picks_from_tokens("2026-11-18", toks, p), [("p1", "a1"), ("p2", "b1")])

    def test_typo_keeps_first_letter_for_full_names(self):
        ans = [{"id": "x", "name": "A.J. Brown", "tier": 2}, {"id": "y", "name": "Patrick Mahomes", "tier": 2}]
        self.assertFalse(dd.check_answer(ans, "St. Brown")["ok"])
        self.assertEqual(dd.check_answer(ans, "Patrik Mahomes")["answer"]["id"], "y")   # real typos still forgiven


class ExplainMissTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = snap.load(snap.PATH_BANDED)

    def prompt(self, tpl, scope, pick=min):
        qs = self.body["prompts"][tpl][scope]
        return snap._unpack(pick(qs, key=lambda q: q["threshold"]), self.body["heads"])

    def test_other_decade(self):
        p = self.prompt("h_d_r1_dec_wr", "2010s")
        self.assertEqual(snap.explain_miss(p, "Jalen Reagor"), "Jalen Reagor fits the 2020s (since 2020) version, not this one.")

    def test_close_uses_real_stat(self):
        p = self.prompt("h_dec_qb_yds", "2010s", pick=max)
        self.assertEqual(snap.explain_miss(p, "Andy Dalton"), "Close: Andy Dalton's best is 4,293 pass yds.")

    def test_unknown_name_keeps_default(self):
        self.assertIsNone(snap.explain_miss(self.prompt("h_d_r1_dec_wr", "2010s"), "Zzz Nobody"))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        s = server
        self.c = TestClient(s.app)
        self.today = dd.today_et().isoformat()
        self.prompts = dd.pick_day(self.today, _pool())
        s._PLAY_MEM.clear(); s._RATE_BUCKETS.clear(); s._PLAY_STATS_CACHE.clear()
        self.addCleanup(s._PLAY_MEM.clear)
        self.saved = {}
        self.picks = {}
        self.user = None
        patches = [mock.patch.dict(os.environ, {"APP_SECRET_KEY": "t"}),
                   mock.patch.object(s.daily_drive, "get_puzzle", lambda d, cache: {"date": d, "prompts": self.prompts}),
                   mock.patch.object(s.db, "DATABASE_URL", "postgres://test"),
                   mock.patch.object(s.db, "get_drive_puzzle", return_value=None),
                   mock.patch.object(s.db, "save_drive_puzzle", side_effect=lambda d, p: p),
                   mock.patch.object(s.db, "save_drive_score", side_effect=self._save),
                   mock.patch.object(s.db, "drive_my_day", side_effect=lambda d, u=None, h=None: self.saved.get(h or u)),
                   mock.patch.object(s.db, "drive_day_yards", side_effect=lambda d: [r["yards"] for r in self.saved.values()]),
                   mock.patch.object(s.db, "add_drive_picks", side_effect=self._add),
                   mock.patch.object(s.db, "drive_pick_counts", side_effect=lambda d: self.picks),
                   mock.patch.object(s, "current_user", side_effect=lambda req: self.user)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def _save(self, d, yards, tiers, user_id=None, device_hash=None, now=None):
        k = device_hash or user_id
        if k in self.saved:
            return self.saved[k], False
        self.saved[k] = {"date": d, "yards": yards, "tiers": list(tiers)}
        return self.saved[k], True

    def _add(self, d, picks):
        for pid, aid in picks:
            self.picks.setdefault(pid, {})[aid] = self.picks.get(pid, {}).get(aid, 0) + 1

    def _token(self, i, a):
        p = self.prompts[i]
        return self.c.post("/api/play/check", json={"prompt_id": p["id"], "answer": p["answers"][a]["name"], "used": []}).json()["token"]

    def test_puzzle_is_frozen_and_reused(self):
        stored = {"date": self.today, "prompts": list(reversed(self.prompts))}
        with mock.patch.object(server.db, "get_drive_puzzle", return_value=stored):
            ids = [p["id"] for p in self.c.get("/api/play/daily").json()["prompts"]]
        self.assertEqual(ids, [p["id"] for p in stored["prompts"]])

    def test_new_puzzle_gets_stored(self):
        with mock.patch.object(server.db, "save_drive_puzzle", side_effect=lambda d, p: p) as save:
            self.c.get("/api/play/daily")
        self.assertEqual(save.call_args[0][0], self.today)

    def test_db_down_still_serves_the_game(self):
        with mock.patch.object(server.db, "get_drive_puzzle", side_effect=RuntimeError("down")), \
             mock.patch.object(server.db, "save_drive_puzzle", side_effect=RuntimeError("down")):
            self.assertEqual(len(self.c.get("/api/play/daily").json()["prompts"]), len(self.prompts))

    def test_score_counts_picks_once_and_returns_rarity(self):
        toks = [self._token(0, 0), self._token(1, 2)]
        r = self.c.post("/api/play/score", json={"date": self.today, "device_id": "d" * 24, "tokens": toks}).json()
        self.assertEqual(r["rarity"][0], {"n": 1, "players": 1, "pct": 100})
        self.assertIsNone(r["rarity"][2])                                    # a sack has no rarity
        again = self.c.post("/api/play/score", json={"date": self.today, "device_id": "d" * 24, "tokens": toks}).json()
        self.assertFalse(again["saved"])
        self.assertEqual(self.picks[self.prompts[0]["id"]][self.prompts[0]["answers"][0]["id"]], 1)

    def test_miss_is_logged_and_explained(self):
        p = self.prompts[0]
        with mock.patch.object(server, "_log_miss") as log, \
             mock.patch.object(server.dd_history_snapshot, "explain_miss", return_value="Close: X's best is 9 yds."):
            r = self.c.post("/api/play/check", json={"prompt_id": p["id"], "answer": "Zzz Nobody", "used": []}).json()
        self.assertEqual(r["reason"], "Close: X's best is 9 yds.")
        self.assertEqual(log.call_args[0][1:], (p["id"], "Zzz Nobody"))

    def test_log_miss_normalizes(self):
        with mock.patch.object(server, "_MISS_POOL") as pool, mock.patch.object(server.db, "log_drive_miss") as log:
            pool.submit.side_effect = lambda fn: fn()
            server._log_miss("2026-11-18", "p1", "  Ja'Marr  CHASE!! ")
            server._log_miss("2026-11-18", "p1", "x")                       # too short: not stored
        log.assert_called_once_with("2026-11-18", "p1", "jamarr chase")

    def test_reveal_has_rarity(self):
        p = self.prompts[0]
        self.picks = {p["id"]: {p["answers"][0]["id"]: 1}}
        self.saved = {"a": {"yards": 10, "tiers": [1]}, "b": {"yards": 0, "tiers": [0]}}
        y = (dd.dt.date.fromisoformat(self.today) - dd.dt.timedelta(days=1)).isoformat()
        r = self.c.get("/api/play/reveal", params={"prompt_id": p["id"], "date": y}).json()
        det = {d["id"]: d for tr in r["tiers"] for d in tr["details"]}
        self.assertEqual(det[p["answers"][0]["id"]]["pct"], 50)

    def test_league_board(self):
        self.user = {"id": 7}
        board = [{"league_id": "L1", "league_name": "Dynasty", "platform": "sleeper",
                  "players": [{"user_id": 9, "name": "pal", "yards": 300, "tiers": [6, 0]},
                              {"user_id": 7, "name": "me", "yards": 100, "tiers": [1, 1]}]}]
        with mock.patch.object(server.db, "drive_league_board", return_value=board), \
             mock.patch.object(server.chat_layer, "get_member", return_value={"role": "member"}):
            r = self.c.get("/api/play/league-board").json()
        lg = r["leagues"][0]
        self.assertTrue(lg["chat"])
        self.assertEqual([(p["rank"], p["me"]) for p in lg["players"]], [(1, False), (2, True)])
        self.assertNotIn("user_id", lg["players"][0])
        self.user = None
        self.assertEqual(self.c.get("/api/play/league-board").json(), {"signed_in": False, "leagues": []})


if __name__ == "__main__":
    unittest.main()
