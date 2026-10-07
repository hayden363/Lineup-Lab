"""At-rest encryption of the ESPN espn_s2/SWID cookies (engine/crypto.py).

Those cookies are a login to a real ESPN account, so two things are pinned
here: what is stored is never the plaintext, and a token the current key
can't open comes back as None ("reconnect ESPN") instead of raising.

engine.crypto builds its Fernet at import time and, with no APP_SECRET_KEY
and no key file, writes .app_secret_key into the repo root. APP_SECRET_KEY is
set below, before the import, so importing this module never creates that
file; every test then swaps in its own throwaway Fernet, so the real key is
never used, read or printed.

    .venv/bin/python -m unittest discover -s tests -t . -v
"""

import os
import unittest
from unittest import mock

from cryptography.fernet import Fernet

os.environ.setdefault("APP_SECRET_KEY", Fernet.generate_key().decode())

from engine import crypto  # noqa: E402  (must follow the env var above)

COOKIE = "AEB%2Fnot-a-real-espn_s2-cookie%3D%3D"


class CryptoRoundTrip(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(crypto, "_fernet", Fernet(Fernet.generate_key()))
        p.start()
        self.addCleanup(p.stop)

    def test_round_trip_returns_the_original(self):
        self.assertEqual(crypto.decrypt(crypto.encrypt(COOKIE)), COOKIE)

    def test_round_trip_keeps_non_ascii(self):
        self.assertEqual(crypto.decrypt(crypto.encrypt("{SWID-é-✓}")), "{SWID-é-✓}")

    def test_ciphertext_is_a_str_that_hides_the_plaintext(self):
        token = crypto.encrypt(COOKIE)
        assert isinstance(token, str)
        self.assertNotEqual(token, COOKIE)
        self.assertNotIn(COOKIE, token)

    def test_empty_and_none_encrypt_to_none(self):
        self.assertIsNone(crypto.encrypt(""))
        self.assertIsNone(crypto.encrypt(None))

    def test_empty_and_none_decrypt_to_none(self):
        self.assertIsNone(crypto.decrypt(""))
        self.assertIsNone(crypto.decrypt(None))

    def test_token_from_a_different_key_decrypts_to_none(self):
        # the documented "lost key = reconnect" contract: no exception
        foreign = Fernet(Fernet.generate_key()).encrypt(COOKIE.encode()).decode()
        self.assertIsNone(crypto.decrypt(foreign))

    def test_garbage_decrypts_to_none(self):
        self.assertIsNone(crypto.decrypt("not-a-fernet-token"))


if __name__ == "__main__":
    unittest.main()
