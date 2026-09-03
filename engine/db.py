"""
ACCOUNT DATABASE — Postgres (Supabase)
========================================
Real hosted Postgres, not a local file — this is the piece that actually
makes multi-user scaling possible. A SQLite file is one writer, one
process, one disk; this is a real connection-pooled database that many
app instances can share, which is the whole point of moving off it (see
README's scaling notes).

Reads DATABASE_URL from the environment (via .env — see .env.example for
where to get it from your Supabase project's dashboard). Every public
function below keeps the exact same name/signature/return shape it had
as SQLite — every caller in this app (server.py, engine/oauth.py,
engine/espn.py, etc.) needed zero changes for this migration.

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
import time
import uuid
from contextlib import contextmanager

import bcrypt
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import crypto

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars can still be set another way

DATABASE_URL = os.environ.get("DATABASE_URL")

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
VERIFY_TTL_SECONDS = 24 * 60 * 60         # verification links expire in 24h

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A real connection pool, not "open a connection per request" — the
# SQLite version could get away with a fresh connection every call
# because a local file connection is nearly free; a real network
# database is not, and a pool is what lets many app instances (or many
# concurrent requests on one instance) share a small number of actual
# TCP connections instead of each request paying a fresh
# connect+authenticate round trip. min_size=0 so the app can still start
# up (and every non-DB route still work) even before DATABASE_URL is set
# or reachable — the pool just fails at first real use, not at import.
_pool = None
if DATABASE_URL:
    _pool = ConnectionPool(DATABASE_URL, min_size=0, max_size=10, open=False)


def _require_pool():
    if _pool is None:
        raise RuntimeError(
            "DATABASE_URL isn't set — accounts/sessions/settings need a real Postgres "
            "database now (see .env.example for how to get a connection string from "
            "your Supabase project)."
        )
    return _pool


@contextmanager
def _conn():
    pool = _require_pool()
    with pool.connection() as conn:
        conn.row_factory = dict_row
        with conn.cursor() as c:
            yield c
        conn.commit()


def init_db():
    """Schema lives in Supabase migrations (see the project's migration
    history), not runtime DDL here — a hosted multi-instance database
    shouldn't have every app process racing to CREATE TABLE IF NOT
    EXISTS against it on startup. This just verifies the pool can
    actually reach the database, so a misconfigured DATABASE_URL fails
    loudly at startup instead of on the first real request."""
    if _pool is None:
        print("[db] DATABASE_URL not set — accounts/sessions won't work until it is "
              "(see .env.example). Everything else in the app still runs.")
        return
    try:
        _pool.open()
        with _conn() as c:
            c.execute("SELECT 1")
        print("[db] connected to Postgres")
    except Exception as e:
        print(f"[db] couldn't reach the database at startup: {e}")


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
        c.execute(
            "SELECT 1 FROM users WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)",
            (username, email),
        )
        if c.fetchone():
            raise AuthError("That username or email is already taken.")
        c.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, email, _hash_password(password), time.time()),
        )
        user_id = c.fetchone()["id"]
        c.execute(
            "INSERT INTO user_settings (user_id, updated_at) VALUES (%s, %s)",
            (user_id, time.time()),
        )
        c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _public(c.fetchone())


def authenticate(identifier, password):
    identifier = (identifier or "").strip()
    with _conn() as c:
        c.execute(
            "SELECT * FROM users WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)",
            (identifier, identifier),
        )
        row = c.fetchone()
    if row and not row["password_hash"]:
        # OAuth-only account (see find_or_create_oauth_user's "" sentinel) —
        # never had a password to check, so say so instead of a generic
        # "wrong password" that'd send someone hunting for one they don't have.
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
        while True:
            c.execute("SELECT 1 FROM users WHERE lower(username) = lower(%s)", (candidate,))
            if not c.fetchone():
                return candidate
            n += 1
            suffix = str(n)
            candidate = base[: 20 - len(suffix)] + suffix


def find_or_create_oauth_user(provider, provider_id, email, name_hint=None):
    """provider: 'google' | 'apple'. Finds an existing account by that
    provider's id first; failing that, by email (links the provider to an
    existing password account, so either sign-in method works after that);
    failing that, creates a brand-new account.

    Google/Apple already verified the email themselves — an OAuth-created
    account starts pre-verified, no confirmation email needed. It also has
    no password (empty-string sentinel — an OAuth-only account has no
    password of its own until/unless the person later sets one from
    Settings, not built yet, tracked as a gap) until then."""
    email = (email or "").strip().lower()
    if not email:
        raise AuthError("Your Google/Apple account didn't share an email address — can't sign in without one.")
    if not EMAIL_RE.match(email):
        raise AuthError("Google/Apple returned an email address that doesn't look valid.")
    col = "google_id" if provider == "google" else "apple_id"

    with _conn() as c:
        c.execute(f"SELECT * FROM users WHERE {col} = %s", (provider_id,))
        row = c.fetchone()
        if row:
            return _public(row)

        c.execute("SELECT * FROM users WHERE lower(email) = lower(%s)", (email,))
        row = c.fetchone()
        if row:
            c.execute(f"UPDATE users SET {col} = %s WHERE id = %s", (provider_id, row["id"]))
            c.execute("SELECT * FROM users WHERE id = %s", (row["id"],))
            return _public(c.fetchone())

        username = _unique_username_from(name_hint or email.split("@")[0])
        c.execute(
            f"INSERT INTO users (username, email, password_hash, created_at, email_verified, {col}) "
            f"VALUES (%s, %s, '', %s, TRUE, %s) RETURNING id",
            (username, email, time.time(), provider_id),
        )
        user_id = c.fetchone()["id"]
        c.execute("INSERT INTO user_settings (user_id, updated_at) VALUES (%s, %s)", (user_id, time.time()))
        c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _public(c.fetchone())


def change_password(user_id, current_password, new_password):
    with _conn() as c:
        c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = c.fetchone()
        if not row or not _check_password(current_password, row["password_hash"]):
            raise AuthError("Current password is incorrect.")
        if not new_password or len(new_password) < 8:
            raise AuthError("New password must be at least 8 characters.")
        c.execute("UPDATE users SET password_hash = %s WHERE id = %s", (_hash_password(new_password), user_id))


# ------------------------------------------------------------- sessions ----
def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (%s, %s, %s, %s)",
            (token, user_id, now, now + SESSION_TTL_SECONDS),
        )
    return token


def get_user_by_session(token):
    if not token:
        return None
    with _conn() as c:
        c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = %s AND s.expires_at > %s",
            (token, time.time()),
        )
        row = c.fetchone()
    return _public(row) if row else None


def delete_session(token):
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token = %s", (token,))


# --------------------------------------------------------- email verification ----
def create_verification_token(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        # one live token per user per purpose — drop any earlier unused one
        c.execute("DELETE FROM verification_tokens WHERE user_id = %s AND purpose = 'verify'", (user_id,))
        c.execute(
            "INSERT INTO verification_tokens (token, user_id, purpose, created_at, expires_at) "
            "VALUES (%s, %s, 'verify', %s, %s)",
            (token, user_id, now, now + VERIFY_TTL_SECONDS),
        )
    return token


def consume_verification_token(token):
    """Marks the token's user verified. Returns the public user record, or
    raises AuthError if the token is missing/expired/wrong purpose."""
    with _conn() as c:
        c.execute(
            "SELECT * FROM verification_tokens WHERE token = %s AND purpose = 'verify' AND expires_at > %s",
            (token, time.time()),
        )
        row = c.fetchone()
        if not row:
            raise AuthError("That verification link is invalid or has expired.")
        c.execute("UPDATE users SET email_verified = TRUE WHERE id = %s", (row["user_id"],))
        c.execute("DELETE FROM verification_tokens WHERE token = %s", (token,))
        c.execute("SELECT * FROM users WHERE id = %s", (row["user_id"],))
        return _public(c.fetchone())


# ------------------------------------------------------------ password reset ----
RESET_TTL_SECONDS = 60 * 60  # reset links expire in 1 hour (shorter than verify)


def create_reset_token(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM verification_tokens WHERE user_id = %s AND purpose = 'reset'", (user_id,))
        c.execute(
            "INSERT INTO verification_tokens (token, user_id, purpose, created_at, expires_at) "
            "VALUES (%s, %s, 'reset', %s, %s)",
            (token, user_id, now, now + RESET_TTL_SECONDS),
        )
    return token


def reset_password(token, new_password):
    """Consumes a password-reset token and sets the new password. Raises
    AuthError if the token is invalid/expired or the password is too weak."""
    if not new_password or len(new_password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    with _conn() as c:
        c.execute(
            "SELECT * FROM verification_tokens WHERE token = %s AND purpose = 'reset' AND expires_at > %s",
            (token, time.time()),
        )
        row = c.fetchone()
        if not row:
            raise AuthError("That reset link is invalid or has expired.")
        c.execute("UPDATE users SET password_hash = %s WHERE id = %s", (_hash_password(new_password), row["user_id"]))
        c.execute("DELETE FROM verification_tokens WHERE token = %s", (token,))
        # a successful reset also invalidates every existing session — if
        # someone else had access to the account, this logs them out too
        c.execute("DELETE FROM sessions WHERE user_id = %s", (row["user_id"],))
        c.execute("SELECT * FROM users WHERE id = %s", (row["user_id"],))
        return _public(c.fetchone())


def get_user_by_email(email):
    with _conn() as c:
        c.execute("SELECT * FROM users WHERE lower(email) = lower(%s)", ((email or "").strip(),))
        row = c.fetchone()
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
        c.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
        row = c.fetchone()
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
        c.execute("SELECT espn_swid, espn_s2 FROM user_settings WHERE user_id = %s", (user_id,))
        row = c.fetchone()
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
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    with _conn() as c:
        c.execute(
            f"UPDATE user_settings SET {set_clause}, updated_at = %s WHERE user_id = %s",
            (*fields.values(), time.time(), user_id),
        )
    return get_settings(user_id)


# ---------------------------------------------------------- connected teams ----
def list_connected_teams(user_id):
    with _conn() as c:
        c.execute("SELECT * FROM connected_teams WHERE user_id = %s ORDER BY created_at", (user_id,))
        rows = c.fetchall()
        c.execute("SELECT active_team_id FROM user_settings WHERE user_id = %s", (user_id,))
        active = c.fetchone()
    active_id = active["active_team_id"] if active else None
    return [dict(r, active=(r["id"] == active_id)) for r in rows]


def add_connected_team(user_id, platform, league_id, roster_id, team_name, league_name=None, avatar_url=None):
    """Upsert: reconnecting the same (user, platform, league, roster) just
    refreshes the name/avatar rather than creating a duplicate row."""
    with _conn() as c:
        c.execute(
            "INSERT INTO connected_teams "
            "(user_id, platform, league_id, league_name, roster_id, team_name, avatar_url, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, platform, league_id, roster_id) "
            "DO UPDATE SET team_name = EXCLUDED.team_name, league_name = EXCLUDED.league_name, "
            "avatar_url = EXCLUDED.avatar_url",
            (user_id, platform, league_id, league_name, roster_id, team_name, avatar_url, time.time()),
        )
        c.execute(
            "SELECT * FROM connected_teams WHERE user_id=%s AND platform=%s AND league_id=%s AND roster_id=%s",
            (user_id, platform, league_id, roster_id),
        )
        team = c.fetchone()
        # first team a user connects becomes active automatically
        c.execute("SELECT active_team_id FROM user_settings WHERE user_id = %s", (user_id,))
        current_active = c.fetchone()
        if current_active and current_active["active_team_id"] is None:
            c.execute("UPDATE user_settings SET active_team_id = %s WHERE user_id = %s", (team["id"], user_id))
    return dict(team)


def remove_connected_team(user_id, team_id):
    with _conn() as c:
        c.execute("SELECT * FROM connected_teams WHERE id = %s AND user_id = %s", (team_id, user_id))
        row = c.fetchone()
        if not row:
            raise AuthError("Team not found.")
        # capture this BEFORE deleting — the FK's ON DELETE SET NULL on
        # user_settings.active_team_id fires as part of the DELETE itself,
        # so checking after would always see NULL already
        c.execute("SELECT active_team_id FROM user_settings WHERE user_id = %s", (user_id,))
        active_before = c.fetchone()
        was_active = bool(active_before and active_before["active_team_id"] == team_id)

        c.execute("DELETE FROM connected_teams WHERE id = %s", (team_id,))

        if was_active:
            c.execute(
                "SELECT id FROM connected_teams WHERE user_id = %s ORDER BY created_at LIMIT 1", (user_id,)
            )
            fallback = c.fetchone()
            c.execute("UPDATE user_settings SET active_team_id = %s WHERE user_id = %s",
                      (fallback["id"] if fallback else None, user_id))


def set_active_team(user_id, team_id):
    with _conn() as c:
        c.execute("SELECT 1 FROM connected_teams WHERE id = %s AND user_id = %s", (team_id, user_id))
        if not c.fetchone():
            raise AuthError("Team not found.")
        c.execute("UPDATE user_settings SET active_team_id = %s WHERE user_id = %s", (team_id, user_id))


def get_active_team(user_id):
    with _conn() as c:
        c.execute(
            "SELECT ct.* FROM user_settings s JOIN connected_teams ct ON ct.id = s.active_team_id "
            "WHERE s.user_id = %s", (user_id,)
        )
        row = c.fetchone()
    return dict(row) if row else None


# ----------------------------------------------------- track record -------
# "How often has this app's own START call actually been right" — logged
# at the moment a real decision is shown to a signed-in user (see
# server.py's /api/startsit), graded later against real published stats
# (see resolve_predictions, called from refresh_scheduler.py), never
# simulated or backfilled. A week with no resolved rows yet just doesn't
# count toward the record — that's the honest state, not an error.
def log_predictions(user_id, players, kind="startsit", scoring=None):
    """`players`: the full comparison group from one Start/Sit run, each a
    dict with player_id/player_display_name/position/tier/confidence/PROJ/
    season/week already resolved by the caller. One comparison_id ties the
    whole group together so resolution can ask "who in this group actually
    scored the most", not just "was this one player's tier right in
    isolation" (a lone SIT call has nothing to be graded against otherwise).
    Silently no-ops on an empty or single-player group — nothing to compare."""
    if len(players) < 2:
        return
    comparison_id = str(uuid.uuid4())
    now = time.time()
    rows = [
        (
            user_id, comparison_id, kind, p["season"], p["week"], p["player_id"],
            p.get("player_display_name"), p.get("position"), p.get("tier") or "BORDERLINE",
            p.get("confidence"), p.get("PROJ"), Jsonb(scoring) if scoring else None, now,
        )
        for p in players
    ]
    with _conn() as c:
        c.executemany(
            "INSERT INTO predictions (user_id, comparison_id, kind, season, week, player_id, "
            "player_display_name, position, tier, confidence, proj_pts, scoring, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )


def pending_resolution_groups():
    """Distinct (season, week, scoring) combinations with at least one
    still-unresolved prediction — so a caller (see tools.resolve_track_record)
    only has to recompute one real actual-points lookup per distinct group,
    not once per logged row."""
    with _conn() as c:
        c.execute("SELECT DISTINCT season, week, scoring FROM predictions WHERE resolved_at IS NULL")
        return c.fetchall()


def resolve_predictions(season, week, actual_fpts_by_player):
    """Grade every still-unresolved prediction for one real, already-played
    week against `actual_fpts_by_player` (player_id -> real fpts, sourced
    from the same weekly stats the rest of the app scores off of — see
    engine/board.py). Per comparison_id group: the group's real winner is
    whoever actually scored the most of the players that data covers (a
    player with no real stats that week — bye, DNP — is left out of the
    "who won" comparison entirely, not treated as a real 0); every row
    tiered START is correct iff it's tied for that real max. Returns how
    many rows got resolved, so a caller can log/skip silently on 0."""
    with _conn() as c:
        c.execute(
            "SELECT id, comparison_id, player_id, tier FROM predictions "
            "WHERE season = %s AND week = %s AND resolved_at IS NULL",
            (season, week),
        )
        pending = c.fetchall()
        if not pending:
            return 0

        by_group = {}
        for row in pending:
            by_group.setdefault(row["comparison_id"], []).append(row)

        now = time.time()
        resolved = 0
        for group_rows in by_group.values():
            scored = [(r, actual_fpts_by_player[r["player_id"]])
                      for r in group_rows if r["player_id"] in actual_fpts_by_player]
            if len(scored) < 2:
                continue  # not enough of this group actually has real stats yet to call a winner
            group_best = max(pts for _, pts in scored)
            for r, pts in scored:
                was_correct = (r["tier"] == "START") and pts >= group_best - 1e-9
                c.execute(
                    "UPDATE predictions SET resolved_at = %s, actual_pts = %s, was_correct = %s WHERE id = %s",
                    (now, pts, was_correct, r["id"]),
                )
                resolved += 1
        return resolved


def get_track_record(user_id):
    """Real, resolved-only accuracy: of every START call this user's app
    has actually made and that has since been graded against a real
    played week, how many were the group's real top scorer. `pending`
    is how many more calls are logged but still waiting on that week's
    stats — surfaced so the UI can say "N more decisions still pending"
    instead of quietly excluding them, which would read as a smaller
    (and more flattering) sample than what's actually been called."""
    with _conn() as c:
        c.execute(
            "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE was_correct) AS correct "
            "FROM predictions WHERE user_id = %s AND tier = 'START' AND resolved_at IS NOT NULL",
            (user_id,),
        )
        resolved = c.fetchone()
        c.execute(
            "SELECT COUNT(*) AS n FROM predictions "
            "WHERE user_id = %s AND tier = 'START' AND resolved_at IS NULL",
            (user_id,),
        )
        pending = c.fetchone()["n"]
        c.execute(
            "SELECT season, week, player_display_name, position, actual_pts, proj_pts, was_correct "
            "FROM predictions WHERE user_id = %s AND tier = 'START' AND resolved_at IS NOT NULL "
            "ORDER BY resolved_at DESC LIMIT 10",
            (user_id,),
        )
        recent = c.fetchall()
    return {
        "resolved": resolved["n"], "correct": resolved["correct"],
        "accuracy_pct": round(100 * resolved["correct"] / resolved["n"], 1) if resolved["n"] else None,
        "pending": pending, "recent": recent,
    }


init_db()
