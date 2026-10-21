"""Waiver engine on an ESPN league: rostered players are hidden and Smart Match
scores free agents against the connected team's roster."""

import unittest
from types import SimpleNamespace as NS
from unittest import mock

from engine import waivers
from engine.waivers import cached_pool, load_bundle


def _team(tid, ids, cw_rev):
    roster = [NS(playerId=cw_rev[g], name=g, position="RB", proTeam="X", lineupSlot="BE") for g in ids]
    return NS(team_id=tid, team_name=f"T{tid}", roster=roster, waiver_rank=tid)


class EspnWaiverTests(unittest.TestCase):
    def test_build_reads_espn_league(self):
        bundle = load_bundle()
        pool, _ = cached_pool(None, bundle)
        top = [g for g in pool.sort_values("value", ascending=False).index if g][:24]
        cw = {str(1000 + i): g for i, g in enumerate(top)}
        rev = {g: int(k) for k, g in cw.items()}
        mine, other = top[:12], top[12:24]
        league = NS(teams=[_team(1, mine, rev), _team(2, other, rev)],
                    settings=NS(position_slot_counts={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "BE": 6}))
        slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
        with mock.patch("engine.espn.id_crosswalk", return_value=cw), \
                mock.patch("engine.espn.roster_positions", return_value=slots):
            out = waivers.build(scoring=None, espn={"league": league, "team_id": 1})
        self.assertTrue(out["has_league"])
        self.assertEqual(out["league"]["teams"], 2)
        self.assertFalse(out["league"]["is_faab"])
        listed = {d["player_id"] for d in out["deep_dive"]}
        self.assertFalse(listed & set(top), "rostered players must be hidden")
        self.assertTrue(out["smart_match"], "Smart Match should return adds")
        self.assertTrue(all(s["bids"] is None for s in out["smart_match"]))


if __name__ == "__main__":
    unittest.main()
