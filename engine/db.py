"""
LOCAL ACCOUNT DATABASE
========================
SQLite (stdlib) — no external DB needed for a local app. Stores accounts,
sessions, email-verification tokens, and each account's settings (which
league is synced, which roster is "mine", scoring preference, etc.).

Email verification: a signup gets a one-time token (24h expiry) mailed to
them via engine/mail.py (Gmail SMTP). If mail isn't configured (no
GMAIL_ADDRESS/GMAIL_APP_PASSWORD in .env), signup still succeeds — the
account just stays unverified until mail is set up and they hit "resend."
There's still no password-reset-via-email flow; change-password requires
the current password.
"""

import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

import bcrypt

from . import crypto

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edgeboard.db")

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
VERIFY_TTL_SECONDS = 24 * 60 * 60         # verification links expire in 24h

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            email_verified INTEGER NOT NULL DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            sleeper_league_id TEXT,
            sleeper_roster_id INTEGER,
            sleeper_team_name TEXT,
            active_team_id INTEGER REFERENCES connected_teams(id) ON DELETE SET NULL,
            espn_league_id TEXT,
            espn_swid TEXT,
            espn_s2 TEXT,
            scoring_preset TEXT DEFAULT '',
            theme TEXT DEFAULT 'high-tech',
            updated_at REAL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS verification_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL DEFAULT 'verify',
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )""")
        # a user can connect more than one team/league; one of them is "active"
        # (drives My Team / Waivers / News) via user_settings.active_team_id
        c.execute("""CREATE TABLE IF NOT EXISTS connected_teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL DEFAULT 'sleeper',
            league_id TEXT NOT NULL,
            league_name TEXT,
            roster_id INTEGER,
            team_name TEXT,
            avatar_url TEXT,
            created_at REAL NOT NULL,
            UNIQUE(user_id, platform, league_id, roster_id)
        )""")

        # ---- migrations for DBs created before a given feature existed ----
        user_cols = {row["name"] for row in c.execute("PRAGMA table_info(users)")}
        if "email_verified" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")

        verify_cols = {row["name"] for row in c.execute("PRAGMA table_info(verification_tokens)")}
        if "purpose" not in verify_cols:
            c.execute("ALTER TABLE verification_tokens ADD COLUMN purpose TEXT NOT NULL DEFAULT 'verify'")

        # OAuth sign-in (Google/Apple): plain columns, not NOT NULL/UNIQUE at
        # the ALTER level (SQLite can't add a constraint that way) — a
        # partial unique index gets the same guarantee for the non-null
        # rows. An OAuth-only account has no password_hash of its own; see
        # create_oauth_user for the empty-string sentinel that avoids
        # widening that column's NOT NULL constraint (which SQLite can't
        # alter without a full table rebuild).
        if "google_id" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
        if "apple_id" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN apple_id TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id) WHERE google_id IS NOT NULL")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_apple_id ON users(apple_id) WHERE apple_id IS NOT NULL")

        settings_cols = {row["name"] for row in c.execute("PRAGMA table_info(user_settings)")}
        if "active_team_id" not in settings_cols:
            c.execute("ALTER TABLE user_settings ADD COLUMN active_team_id INTEGER "
                       "REFERENCES connected_teams(id) ON DELETE SET NULL")

        # one-time backfill: single-team era stored the connection directly on
        # user_settings — migrate any of those rows into connected_teams so
        # multi-team support doesn't lose an existing connection.
        legacy = c.execute(
            "SELECT user_id, sleeper_league_id, sleeper_roster_id, sleeper_team_name "
            "FROM user_settings WHERE sleeper_league_id IS NOT NULL AND sleeper_league_id != '' "
            "AND active_team_id IS NULL"
        ).fetchall()
        for row in legacy:
            cur = c.execute(
                "INSERT OR IGNORE INTO connected_teams "
                "(user_id, platform, league_id, roster_id, team_name, created_at) "
                "VALUES (?, 'sleeper', ?, ?, ?, ?)",
                (row["user_id"], row["sleeper_league_id"], row["sleeper_roster_id"],
                 row["sleeper_team_name"], time.time()),
            )
            new_id = cur.lastrowid or c.execute(
                "SELECT id FROM connected_teams WHERE user_id=? AND league_id=? AND roster_id=?",
                (row["user_id"], row["sleeper_league_id"], row["sleeper_roster_id"]),
            ).fetchone()["id"]
            c.execute("UPDATE user_settings SET active_team_id = ? WHERE user_id = ?", (new_id, row["user_id"]))


# ---------------------------------------------------------------- users ----
class AuthError(Exception):
    pass


def _hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password, hashed):
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _public(user_row):
    return {
        "id": user_row["id"], "username": user_row["username"], "email": user_row["email"],
        "email_verified": bool(user_row["email_verified"]),
    }


def create_user(username, email, password):
    username = (username or "").strip()
    email = (email or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3-20 characters: letters, numbers, underscore only.")
    if not EMAIL_RE.match(email):
        raise AuthError("That doesn't look like a valid email address.")
    if not password or len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")

    with _conn() as c:
        existing = c.execute(
            "SELECT 1 FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
            (username, email),
        ).fetchone()
        if existing:
            raise AuthError("That username or email is already taken.")
        cur = c.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username, email, _hash_password(password), time.time()),
        )
        user_id = cur.lastrowid
        c.execute(
            "INSERT INTO user_settings (user_id, updated_at) VALUES (?, ?)",
            (user_id, time.time()),
        )
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _public(row)


def authenticate(identifier, password):
    identifier = (identifier or "").strip()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
            (identifier, identifier),
        ).fetchone()
    if row and not row["password_hash"]:
        # OAuth-only account (see create_oauth_user's "" sentinel) — never
        # had a password to check, so say so instead of a generic "wrong
        # password" that'd send someone hunting for a password they don't have.
        via = "Google" if row["google_id"] else ("Apple" if row["apple_id"] else "Google/Apple")
        raise AuthError(f"This account signs in with {via} — use that button instead of a password.")
    if not row or not _check_password(password, row["password_hash"]):
        raise AuthError("Incorrect username/email or password.")
    return _public(row)


def _unique_username_from(base):
    base = re.sub(r"[^A-Za-z0-9_]", "", base or "")[:20]
    if len(base) < 3:
        base = (base + "user")[:20].ljust(3, "0")
    with _conn() as c:
        candidate = base
        n = 0
        while c.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (candidate,)).fetchone():
            n += 1
            suffix = str(n)
            candidate = base[: 20 - len(suffix)] + suffix
        return candidate


def find_or_create_oauth_user(provider, provider_id, email, name_hint=None):
    """provider: 'google' | 'apple'. Finds an existing account by that
    provider's id first; failing that, by email (links the provider to an
    existing password account, so either sign-in method works after that);
    failing that, creates a brand-new account.

    Google/Apple already verified the email themselves — an OAuth-created
    account starts pre-verified, no confirmation email needed. It also has
    no password (empty-string sentinel; see the migration note above for
    why that's a sentinel and not a real NULL) until/unless the person
    later sets one from Settings — not built yet, tracked as a gap."""
    email = (email or "").strip().lower()
    if not email:
        raise AuthError("Your Google/Apple account didn't share an email address — can't sign in without one.")
    if not EMAIL_RE.match(email):
        raise AuthError("Google/Apple returned an email address that doesn't look valid.")
    col = "google_id" if provider == "google" else "apple_id"

    with _conn() as c:
        row = c.execute(f"SELECT * FROM users WHERE {col} = ?", (provider_id,)).fetchone()
        if row:
            return _public(row)

        row = c.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if row:
            c.execute(f"UPDATE users SET {col} = ? WHERE id = ?", (provider_id, row["id"]))
            row = c.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return _public(row)

        username = _unique_username_from(name_hint or email.split("@")[0])
        cur = c.execute(
            f"INSERT INTO users (username, email, password_hash, created_at, email_verified, {col}) "
            f"VALUES (?, ?, '', ?, 1, ?)",
            (username, email, time.time(), provider_id),
        )
        user_id = cur.lastrowid
        c.execute("INSERT INTO user_settings (user_id, updated_at) VALUES (?, ?)", (user_id, time.time()))
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _public(row)


def change_password(user_id, current_password, new_password):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not _check_password(current_password, row["password_hash"]):
            raise AuthError("Current password is incorrect.")
        if not new_password or len(new_password) < 8:
            raise AuthError("New password must be at least 8 characters.")
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), user_id))


# ------------------------------------------------------------- sessions ----
def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + SESSION_TTL_SECONDS),
        )
    return token


def get_user_by_session(token):
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ?",
            (token, time.time()),
        ).fetchone()
    return _public(row) if row else None


def delete_session(token):
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --------------------------------------------------------- email verification ----
def create_verification_token(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        # one live token per user per purpose — drop any earlier unused one
        c.execute("DELETE FROM verification_tokens WHERE user_id = ? AND purpose = 'verify'", (user_id,))
        c.execute(
            "INSERT INTO verification_tokens (token, user_id, purpose, created_at, expires_at) VALUES (?, ?, 'verify', ?, ?)",
            (token, user_id, now, now + VERIFY_TTL_SECONDS),
        )
    return token


def consume_verification_token(token):
    """Marks the token's user verified. Returns the public user record, or
    raises AuthError if the token is missing/expired/wrong purpose."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM verification_tokens WHERE token = ? AND purpose = 'verify' AND expires_at > ?",
            (token, time.time()),
        ).fetchone()
        if not row:
            raise AuthError("That verification link is invalid or has expired.")
        c.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (row["user_id"],))
        c.execute("DELETE FROM verification_tokens WHERE token = ?", (token,))
        user = c.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        return _public(user)


# ------------------------------------------------------------ password reset ----
RESET_TTL_SECONDS = 60 * 60  # reset links expire in 1 hour (shorter than verify)


def create_reset_token(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM verification_tokens WHERE user_id = ? AND purpose = 'reset'", (user_id,))
        c.execute(
            "INSERT INTO verification_tokens (token, user_id, purpose, created_at, expires_at) VALUES (?, ?, 'reset', ?, ?)",
            (token, user_id, now, now + RESET_TTL_SECONDS),
        )
    return token


def reset_password(token, new_password):
    """Consumes a password-reset token and sets the new password. Raises
    AuthError if the token is invalid/expired or the password is too weak."""
    if not new_password or len(new_password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM verification_tokens WHERE token = ? AND purpose = 'reset' AND expires_at > ?",
            (token, time.time()),
        ).fetchone()
        if not row:
            raise AuthError("That reset link is invalid or has expired.")
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), row["user_id"]))
        c.execute("DELETE FROM verification_tokens WHERE token = ?", (token,))
        # a successful reset also invalidates every existing session — if
        # someone else had access to the account, this logs them out too
        c.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
        user = c.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        return _public(user)


def get_user_by_email(email):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE lower(email) = lower(?)", ((email or "").strip(),)).fetchone()
    return _public(row) if row else None


# --------------------------------------------------------------- settings ----
# espn_swid/espn_s2 are ESPN session cookies — as sensitive as a login. They're
# encrypted at rest (engine/crypto.py) and NEVER round-tripped to the client;
# get_settings reports only whether each is set, not its value.
PLAIN_SETTINGS_FIELDS = ["espn_league_id", "scoring_preset", "theme"]
SECRET_SETTINGS_FIELDS = ["espn_swid", "espn_s2"]
SETTINGS_FIELDS = PLAIN_SETTINGS_FIELDS + SECRET_SETTINGS_FIELDS


def get_settings(user_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        row = {}
    out = {f: row[f] if row else None for f in PLAIN_SETTINGS_FIELDS}
    out["espn_swid_set"] = bool(row and row["espn_swid"])
    out["espn_s2_set"] = bool(row and row["espn_s2"])
    out["active_team_id"] = row["active_team_id"] if row else None
    return out


def get_espn_secrets(user_id):
    """Decrypted ESPN cookies for actually making a request — internal use
    only, never returned from an API endpoint."""
    with _conn() as c:
        row = c.execute("SELECT espn_swid, espn_s2 FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None, None
    return crypto.decrypt(row["espn_swid"]), crypto.decrypt(row["espn_s2"])


def update_settings(user_id, updates):
    fields = {k: v for k, v in updates.items() if k in SETTINGS_FIELDS}
    if not fields:
        return get_settings(user_id)
    for k in SECRET_SETTINGS_FIELDS:
        if k in fields:
            fields[k] = crypto.encrypt(fields[k]) if fields[k] else None
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as c:
        c.execute(
            f"UPDATE user_settings SET {set_clause}, updated_at = ? WHERE user_id = ?",
            (*fields.values(), time.time(), user_id),
        )
    return get_settings(user_id)


# ---------------------------------------------------------- connected teams ----
def list_connected_teams(user_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM connected_teams WHERE user_id = ? ORDER BY created_at", (user_id,)
        ).fetchall()
        active = c.execute("SELECT active_team_id FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    active_id = active["active_team_id"] if active else None
    return [dict(r, active=(r["id"] == active_id)) for r in rows]


def add_connected_team(user_id, platform, league_id, roster_id, team_name, league_name=None, avatar_url=None):
    """Upsert: reconnecting the same (user, platform, league, roster) just
    refreshes the name/avatar rather than creating a duplicate row."""
    with _conn() as c:
        c.execute(
            "INSERT INTO connected_teams "
            "(user_id, platform, league_id, league_name, roster_id, team_name, avatar_url, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, platform, league_id, roster_id) "
            "DO UPDATE SET team_name = excluded.team_name, league_name = excluded.league_name, "
            "avatar_url = excluded.avatar_url",
            (user_id, platform, league_id, league_name, roster_id, team_name, avatar_url, time.time()),
        )
        team = c.execute(
            "SELECT * FROM connected_teams WHERE user_id=? AND platform=? AND league_id=? AND roster_id=?",
            (user_id, platform, league_id, roster_id),
        ).fetchone()
        # first team a user connects becomes active automatically
        current_active = c.execute("SELECT active_team_id FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        if current_active and current_active["active_team_id"] is None:
            c.execute("UPDATE user_settings SET active_team_id = ? WHERE user_id = ?", (team["id"], user_id))
    return dict(team)


def remove_connected_team(user_id, team_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM connected_teams WHERE id = ? AND user_id = ?", (team_id, user_id)).fetchone()
        if not row:
            raise AuthError("Team not found.")
        # capture this BEFORE deleting — the FK's ON DELETE SET NULL on
        # user_settings.active_team_id fires as part of the DELETE itself
        # (foreign_keys=ON), so checking after would always see NULL already
        active_before = c.execute(
            "SELECT active_team_id FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        was_active = bool(active_before and active_before["active_team_id"] == team_id)

        c.execute("DELETE FROM connected_teams WHERE id = ?", (team_id,))

        if was_active:
            fallback = c.execute(
                "SELECT id FROM connected_teams WHERE user_id = ? ORDER BY created_at LIMIT 1", (user_id,)
            ).fetchone()
            c.execute("UPDATE user_settings SET active_team_id = ? WHERE user_id = ?",
                      (fallback["id"] if fallback else None, user_id))


def set_active_team(user_id, team_id):
    with _conn() as c:
        row = c.execute("SELECT 1 FROM connected_teams WHERE id = ? AND user_id = ?", (team_id, user_id)).fetchone()
        if not row:
            raise AuthError("Team not found.")
        c.execute("UPDATE user_settings SET active_team_id = ? WHERE user_id = ?", (team_id, user_id))


def get_active_team(user_id):
    with _conn() as c:
        row = c.execute(
            "SELECT ct.* FROM user_settings s JOIN connected_teams ct ON ct.id = s.active_team_id "
            "WHERE s.user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


init_db()
