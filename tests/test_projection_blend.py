import unittest
from datetime import datetime, timedelta

from engine import locks, projection_blend as pb


class AlphaTests(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(pb.alpha(200), 0.70)
        self.assertEqual(pb.alpha(60), 0.50)
        self.assertEqual(pb.alpha(10), 0.35)
        self.assertEqual(pb.alpha(2), 0.25)

    def test_boundaries(self):
        self.assertEqual(pb.alpha(96.01), 0.70)
        self.assertEqual(pb.alpha(96.0), 0.50)   # exactly four days out is the middle band
        self.assertEqual(pb.alpha(24.0), 0.50)
        self.assertEqual(pb.alpha(23.99), 0.35)
        self.assertEqual(pb.alpha(4.0), 0.35)
        self.assertEqual(pb.alpha(3.99), 0.25)
        self.assertEqual(pb.alpha(0.0), 0.25)
        self.assertEqual(pb.alpha(-3.0), 0.25)   # already kicked off

    def test_our_weight_never_rises_as_kickoff_nears(self):
        weights = [pb.alpha(h) for h in range(200, -1, -1)]
        self.assertEqual(weights, sorted(weights, reverse=True))


class BlendTests(unittest.TestCase):
    def test_sunday_leans_on_experts_more_than_tuesday(self):
        tuesday = pb.blend(20.0, 12.0, 120)
        sunday = pb.blend(20.0, 12.0, 2)
        self.assertEqual(tuesday["blended"], 17.6)   # 0.70*20 + 0.30*12
        self.assertEqual(sunday["blended"], 14.0)    # 0.25*20 + 0.75*12
        self.assertLess(sunday["blended"], tuesday["blended"])

    def test_agreement_returns_the_same_number(self):
        self.assertEqual(pb.blend(15.0, 15.0, 30)["blended"], 15.0)

    def test_disagreement_sign_says_who_is_higher(self):
        self.assertEqual(pb.blend(10.0, 14.0, 30)["disagreement"], -4.0)

    def test_missing_inputs_never_invent_a_number(self):
        for args in [(10.0, None, 30), (None, 10.0, 30), (10.0, 12.0, None)]:
            r = pb.blend(*args)
            self.assertIsNone(r["blended"])
            self.assertTrue(r["reason"])


class HoursUntilTests(unittest.TestCase):
    def test_hours(self):
        ko = datetime(2026, 10, 25, 13, 0, tzinfo=locks.ET)
        self.assertEqual(pb.hours_until(ko, ko - timedelta(hours=30)), 30.0)
        self.assertEqual(pb.hours_until(ko, ko + timedelta(hours=1)), -1.0)
        self.assertIsNone(pb.hours_until(None))


if __name__ == "__main__":
    unittest.main()
