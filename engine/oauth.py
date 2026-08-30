"""
OAUTH SIGN-IN — Google (Apple wired the same way, once you have the
account for it)
======================================================================
Standard server-side OAuth2 authorization-code flow. No SDK, no vendor
library beyond `requests` (already a dependency) and PyJWT for verifying
the ID token's signature against the provider's own public keys — the
same trust model any "Sign in with Google" button uses under the hood.

Credentials come from environment variables (`.env`, same pattern as
Gmail in engine/mail.py):

    GOOGLE_CLIENT_ID=...
    GOOGLE_CLIENT_SECRET=...

How to get them:
  1. https://console.cloud.google.com/apis/credentials
  2. Create an OAuth 2.0 Client ID, type "Web application"
  3. Add an Authorized redirect URI: http://localhost:8420/api/auth/google/callback
     (and your real domain's equivalent if this ever runs somewhere else)
  4. Copy the Client ID and Client Secret into `.env`

If these aren't set, `configured()` reports False and the frontend simply
doesn't show the "Continue with Google" button — same graceful-degrade
pattern as mail.py when Gmail isn't configured.

Apple Sign In follows the identical shape (authorize URL -> code ->
token exchange -> verify id_token against the provider's JWKS -> find-or-
create user) but needs a paid Apple Developer account, a Services ID, and
an ES256 private key — not wired up yet; see APPLE_* below for the
config it would read once it is.
"""

import os
import time

import jwt
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

# Apple — not active until APPLE_CLIENT_ID etc. are set (see module docstring)
APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID")            # the Services ID, e.g. com.you.lineuplab.web
APPLE_TEAM_ID = os.environ.get("APPLE_TEAM_ID")
APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID")
APPLE_PRIVATE_KEY = os.environ.get("APPLE_PRIVATE_KEY")        # contents of the .p8 file
APPLE_AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

_JWKS_CACHE = {}
_JWKS_TTL = 60 * 60  # provider signing keys rotate rarely — an hour is plenty fresh


class OAuthError(Exception):
    pass


def google_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def apple_configured():
    return bool(APPLE_CLIENT_ID and APPLE_TEAM_ID and APPLE_KEY_ID and APPLE_PRIVATE_KEY)


def _get_jwks(url):
    now = time.time()
    cached = _JWKS_CACHE.get(url)
    if cached and (now - cached[0]) < _JWKS_TTL:
        return cached[1]
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    keys = resp.json()["keys"]
    _JWKS_CACHE[url] = (now, keys)
    return keys


def _verify_id_token(id_token, jwks_url, audience, issuers):
    """Decode + verify an OAuth provider's ID token against its own current
    public keys — this is what actually proves the token wasn't forged,
    not just that it's well-formed JSON. Returns the verified claims dict."""
    try:
        keys = _get_jwks(jwks_url)
        unverified_header = jwt.get_unverified_header(id_token)
        kid = unverified_header.get("kid")
        matching = next((k for k in keys if k.get("kid") == kid), None)
        if not matching:
            # keys may have just rotated — one forced refresh, then give up
            _JWKS_CACHE.pop(jwks_url, None)
            keys = _get_jwks(jwks_url)
            matching = next((k for k in keys if k.get("kid") == kid), None)
        if not matching:
            raise OAuthError("Couldn't find a matching signing key — the sign-in token may be invalid.")
        public_key = jwt.PyJWK(matching).key
        claims = jwt.decode(
            id_token, public_key, algorithms=[matching.get("alg", "RS256")],
            audience=audience, issuer=None,  # checked manually below (provider may report either of two issuer forms)
            options={"verify_aud": True, "verify_exp": True, "verify_iss": False},
        )
        if claims.get("iss") not in issuers:
            raise OAuthError("Unexpected token issuer.")
        return claims
    except jwt.PyJWTError as e:
        raise OAuthError(f"Couldn't verify sign-in token: {e}") from e


def google_authorize_url(redirect_uri, state):
    if not google_configured():
        raise OAuthError("Google sign-in isn't configured on this server yet — see engine/oauth.py or .env.example.")
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "access_type": "online", "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def google_exchange_code(code, redirect_uri):
    """code -> verified claims (sub, email, name) for the signed-in Google account."""
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }, timeout=15)
    if resp.status_code != 200:
        raise OAuthError(f"Google rejected the sign-in code: {resp.text[:200]}")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise OAuthError("Google didn't return an ID token.")
    claims = _verify_id_token(id_token, GOOGLE_JWKS_URL, GOOGLE_CLIENT_ID, GOOGLE_ISSUERS)
    return {"provider_id": claims["sub"], "email": claims.get("email"), "name": claims.get("name")}


def apple_authorize_url(redirect_uri, state):
    if not apple_configured():
        raise OAuthError("Apple sign-in isn't configured on this server.")
    from urllib.parse import urlencode
    params = {
        "client_id": APPLE_CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "email name", "state": state, "response_mode": "form_post",
    }
    return f"{APPLE_AUTHORIZE_URL}?{urlencode(params)}"


def _apple_client_secret():
    """Apple doesn't take a static client secret — it takes a short-lived
    JWT you sign yourself with your Apple-issued private key."""
    now = int(time.time())
    payload = {"iss": APPLE_TEAM_ID, "iat": now, "exp": now + 300, "aud": APPLE_ISSUER, "sub": APPLE_CLIENT_ID}
    headers = {"kid": APPLE_KEY_ID}
    return jwt.encode(payload, APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers)


def apple_exchange_code(code, redirect_uri):
    resp = requests.post(APPLE_TOKEN_URL, data={
        "code": code, "client_id": APPLE_CLIENT_ID, "client_secret": _apple_client_secret(),
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }, timeout=15)
    if resp.status_code != 200:
        raise OAuthError(f"Apple rejected the sign-in code: {resp.text[:200]}")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise OAuthError("Apple didn't return an ID token.")
    claims = _verify_id_token(id_token, APPLE_JWKS_URL, APPLE_CLIENT_ID, (APPLE_ISSUER,))
    return {"provider_id": claims["sub"], "email": claims.get("email"), "name": None}
