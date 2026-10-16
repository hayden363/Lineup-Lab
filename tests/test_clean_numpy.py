"""server._clean and engine.tools._clean_num must turn numpy scalars into plain
Python values. A numpy.int64 injury_sample_n (any rostered player who is
Questionable/Doubtful with a known body part) made FastAPI's encoder raise, so
/api/myteam and /api/trade/roster returned 500 and no players loaded."""
import unittest

import numpy as np
from fastapi.encoders import jsonable_encoder

import server
from engine.tools import _clean_num


class CleanNumpyTests(unittest.TestCase):
    def test_numpy_int64_becomes_int_and_encodes(self):
        out = server._clean({"players": [{"injury_sample_n": np.int64(150), "injury_factor": np.float64(0.7345)}]})
        p = out["players"][0]
        self.assertIs(type(p["injury_sample_n"]), int)
        self.assertEqual(p["injury_sample_n"], 150)
        self.assertIs(type(p["injury_factor"]), float)
        jsonable_encoder(out)   # raised TypeError before the fix

    def test_numpy_nan_and_inf_become_none(self):
        self.assertIsNone(server._clean(np.float64("nan")))
        self.assertIsNone(server._clean(np.float64("inf")))

    def test_numpy_bool_becomes_bool(self):
        self.assertIs(server._clean(np.bool_(True)), True)

    def test_tuples_are_walked(self):
        out = server._clean({"pair": (np.int64(3), float("nan"))})
        self.assertEqual(out["pair"], [3, None])

    def test_plain_values_unchanged(self):
        data = {"a": 1, "b": 2.5, "c": "x", "d": None, "e": [True]}
        self.assertEqual(server._clean(data), data)

    def test_clean_num_unwraps_numpy(self):
        self.assertIs(type(_clean_num(np.int64(7))), int)
        self.assertIsNone(_clean_num(np.float64("nan")))
        self.assertIsNone(_clean_num(None))
        self.assertEqual(_clean_num(np.float64(1.5)), 1.5)


if __name__ == "__main__":
    unittest.main()
