"""
SECURITY HELPERS — the pieces of account and request safety that do not need a database
=======================================================================================
  public_base_url     the origin used in emails and OAuth redirects. Never taken blindly from the Host header: a
                      forged Host on "forgot password" would otherwise mail the victim a reset link to the attacker's site.
  same_origin         the Origin/Referer check for state-changing requests (defence in depth on top of SameSite=Lax).
  AccountThrottle     failed-login counter per account, so credential stuffing spread over many IPs still stops.
  check_password      length and common-password rules (bcrypt only reads the first 72 bytes).
  hash_token          sessions and one-time links are stored as a SHA-256 of the token, so a database leak is not a
                      list of live logins.
  audit               one structured line per security event, never with passwords, tokens or emails.
"""

import hashlib
import os
import re
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://lineup-lab-awdv.onrender.com"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "testserver"}


def _origin_of(url):
    p = urlparse(url or "")
    return f"{p.scheme}://{p.netloc}".lower() if p.scheme and p.netloc else ""


def _host_is_ours(host):
    host = (host or "").split(":")[0].lower()
    return host in _LOCAL_HOSTS or host.endswith(".onrender.com")


def public_base_url(request_base_url):
    """Configured origin first (PUBLIC_BASE_URL, then Render's own RENDER_EXTERNAL_URL); otherwise the request's own
    origin, but only for localhost and *.onrender.com; any other Host header falls back to the default."""
    for key in ("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        configured = _origin_of(os.environ.get(key, ""))
        if configured:
            return configured
    origin = _origin_of(str(request_base_url))
    if origin and _host_is_ours(urlparse(origin).netloc):
        return origin
    return DEFAULT_BASE_URL


def same_origin(headers, host):
    """True when a state-changing request came from this site. A request with neither Origin nor Referer (curl, a
    mobile app) is allowed: it is not a browser being driven by another page, and it carries no cookie to ride."""
    src = headers.get("origin") or headers.get("referer")
    if not src:
        return True
    got = urlparse(src).netloc.lower()
    return bool(got) and got == (host or "").lower()


class AccountThrottle:
    """`limit` failures per `window` seconds per key; a success clears the key."""

    def __init__(self, limit=8, window=15 * 60):
        self.limit, self.window = limit, window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key, now):
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:
            self._hits.pop(key, None)
        return q

    def blocked(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            return len(self._trim(key, now)) >= self.limit

    def fail(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._trim(key, now)
            self._hits[key].append(now)

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)

    def size(self):
        return len(self._hits)


COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwertyui", "qwerty123",
    "iloveyou", "11111111", "00000000", "abc12345", "letmein1", "football", "football1", "fantasy1",
    "admin123", "welcome1", "monkey123", "dragon123", "sunshine1", "princess1", "passw0rd", "trustno1",
}
MAX_PASSWORD_BYTES = 72


def check_password(password, username="", email=""):
    """Returns an error message, or None when the password is acceptable."""
    if not password or len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "Password must be at most 72 bytes (about 72 characters)."
    low = password.lower()
    if low in COMMON_PASSWORDS or len(set(low)) < 3:
        return "That password is too easy to guess. Pick something less common."
    ident = {(username or "").lower(), (email or "").lower().split("@")[0]} - {""}
    if low in ident:
        return "Your password can't be the same as your username or email."
    return None


def hash_token(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


_SAFE = re.compile(r"[^A-Za-z0-9_.:\-/ =]")


def audit(event, **fields):
    """[security] event=login_failed ip=... user_id=... — values are stripped to a safe character set, so a hostile
    username can never forge extra log fields."""
    parts = [f"event={_SAFE.sub('', str(event))}"]
    for k, v in fields.items():
        if v is not None:
            parts.append(f"{k}={_SAFE.sub('', str(v))[:64].replace(' ', '_')}")
    print("[security] " + " ".join(parts))
