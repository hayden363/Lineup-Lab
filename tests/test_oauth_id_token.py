"""engine/oauth._verify_id_token against tokens signed with a locally generated
RSA key. No network and no secrets: _get_jwks is patched to return our JWK."""
import json
import time
import unittest
from unittest import mock

import jwt
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa

from engine import oauth
from engine.oauth import OAuthError, _verify_id_token

JWKS_URL = "https://example.test/jwks"
AUD = "client-123"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(private_key, kid, alg="RS256"):
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "alg": alg, "use": "sig"})
    return jwk


def claims(**over):
    now = int(time.time())
    c = {"iss": "https://accounts.google.com", "aud": AUD, "sub": "user-1", "iat": now, "exp": now + 600}
    c.update(over)
    return c


class VerifyIdTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = make_key()
        cls.other_key = make_key()
        cls.jwk = jwk_for(cls.key, "k1")

    def setUp(self):
        oauth._JWKS_CACHE.clear()
        patcher = mock.patch.object(oauth, "_get_jwks", return_value=[self.jwk])
        self.get_jwks = patcher.start()
        self.addCleanup(patcher.stop)

    def sign(self, payload, key=None, kid="k1", alg="RS256"):
        return jwt.encode(payload, key or self.key, algorithm=alg, headers={"kid": kid})

    def verify(self, token):
        return _verify_id_token(token, JWKS_URL, AUD, ISSUERS)

    def test_valid_token_returns_claims(self):
        self.assertEqual(self.verify(self.sign(claims()))["sub"], "user-1")

    def test_second_issuer_form_is_accepted(self):
        self.assertEqual(self.verify(self.sign(claims(iss="accounts.google.com")))["sub"], "user-1")

    def test_wrong_audience_is_rejected(self):
        with self.assertRaises(OAuthError):
            self.verify(self.sign(claims(aud="someone-else")))

    def test_expired_token_is_rejected(self):
        with self.assertRaises(OAuthError):
            self.verify(self.sign(claims(exp=int(time.time()) - 60)))

    def test_wrong_issuer_is_rejected(self):
        with self.assertRaisesRegex(OAuthError, "Unexpected token issuer"):
            self.verify(self.sign(claims(iss="https://evil.example")))

    def test_missing_issuer_is_rejected(self):
        c = claims()
        del c["iss"]
        with self.assertRaisesRegex(OAuthError, "Unexpected token issuer"):
            self.verify(self.sign(c))

    def test_token_signed_by_a_different_key_with_same_kid_is_rejected(self):
        with self.assertRaises(OAuthError):
            self.verify(self.sign(claims(), key=self.other_key))

    def test_unknown_kid_refreshes_once_then_rejects(self):
        with self.assertRaisesRegex(OAuthError, "matching signing key"):
            self.verify(self.sign(claims(), kid="rotated-away"))
        self.assertEqual(self.get_jwks.call_count, 2)

    def test_unknown_kid_found_after_refresh_is_accepted(self):
        new_jwk = jwk_for(self.other_key, "k2")
        self.get_jwks.side_effect = [[self.jwk], [self.jwk, new_jwk]]
        self.assertEqual(self.verify(self.sign(claims(), key=self.other_key, kid="k2"))["sub"], "user-1")

    def test_alg_none_token_is_rejected(self):
        token = jwt.encode(claims(), "", algorithm="none", headers={"kid": "k1"})
        with self.assertRaises(OAuthError):
            self.verify(token)

    def test_hs256_signed_with_the_public_key_is_rejected(self):
        # Algorithm confusion: an attacker HMAC-signs with the (public) RSA key bytes.
        from cryptography.hazmat.primitives import serialization
        pem = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        import base64, hashlib, hmac
        def b64(b):
            return base64.urlsafe_b64encode(b).rstrip(b"=")
        header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
        body = b64(json.dumps(claims()).encode())
        sig = b64(hmac.new(pem, header + b"." + body, hashlib.sha256).digest())
        with self.assertRaises(OAuthError):
            self.verify((header + b"." + body + b"." + sig).decode())

    def test_garbage_token_is_rejected(self):
        with self.assertRaises(OAuthError):
            self.verify("not-a-jwt")


if __name__ == "__main__":
    unittest.main()
