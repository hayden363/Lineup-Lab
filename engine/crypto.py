"""
AT-REST ENCRYPTION for sensitive settings (ESPN's espn_s2/SWID cookies).
===========================================================================
Those cookies are equivalent to being logged into the user's real ESPN
account — worth encrypting at rest, not just relying on file permissions.

The key comes from APP_SECRET_KEY in .env if you set one; otherwise a
random key is generated on first run and cached in `.app_secret_key`
(gitignored, local to this machine). Losing that file means previously
encrypted ESPN cookies can't be decrypted — the app treats that the same
as "not configured" and asks you to reconnect rather than crashing.
"""

import os

from cryptography.fernet import Fernet, InvalidToken

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".app_secret_key")


def _load_or_create_key():
    env_key = os.environ.get("APP_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(_KEY_FILE, 0o600)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext):
    if not plaintext:
        return None
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext):
    if not ciphertext:
        return None
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None  # key rotated/lost — treat as unset rather than crash
