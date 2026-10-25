"""League chat: membership, messages and moderation.

Only verified members of a league read or write its chat. Verification (proving
you own a Sleeper team) lives in verify_sleeper_owner; everything here assumes
the caller has already authenticated the user. Raises ChatError with the HTTP
status the API should return.
"""

import secrets
import time

from . import db

MAX_BODY = 500
PAGE_SIZE = 50
CHALLENGE_TTL = 15 * 60
MAX_MUTE_MINUTES = 7 * 24 * 60


class ChatError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def get_member(user_id, platform, league_id):
    with db._conn() as c:
        c.execute(
            "SELECT role, muted_until, external_id FROM league_chat_members "
            "WHERE user_id = %s AND platform = %s AND league_id = %s",
            (user_id, platform, league_id),
        )
        row = c.fetchone()
    return dict(row) if row else None


def is_member(user_id, platform, league_id):
    return get_member(user_id, platform, league_id) is not None


def _require_member(user_id, platform, league_id):
    member = get_member(user_id, platform, league_id)
    if member is None:
        raise ChatError("Join this league's chat first.", 403)
    return member


def add_member(user_id, platform, league_id, external_id, role="member"):
    """The first member of a league becomes its moderator; nobody can promote
    themselves through `role` (it is ignored after the first member)."""
    with db._conn() as c:
        c.execute(
            "SELECT user_id FROM league_chat_members "
            "WHERE platform = %s AND league_id = %s AND external_id = %s",
            (platform, league_id, external_id),
        )
        taken = c.fetchone()
        if taken and taken["user_id"] != user_id:
            raise ChatError("That Sleeper team is already linked to another Lineup Lab account.", 409)
        c.execute(
            "SELECT 1 FROM league_chat_members WHERE platform = %s AND league_id = %s LIMIT 1",
            (platform, league_id),
        )
        assigned = "member" if c.fetchone() else "moderator"
        c.execute(
            "INSERT INTO league_chat_members (user_id, platform, league_id, external_id, role, joined_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, platform, league_id) DO NOTHING",
            (user_id, platform, league_id, external_id, assigned, time.time()),
        )
        c.execute(
            "SELECT user_id, role, external_id FROM league_chat_members "
            "WHERE user_id = %s AND platform = %s AND league_id = %s",
            (user_id, platform, league_id),
        )
        row = db._fetch_row(c)
    return dict(row)


def create_challenge(user_id, platform, league_id):
    token = "llab-" + secrets.token_hex(4)
    with db._conn() as c:
        c.execute(
            "INSERT INTO league_chat_challenges (user_id, platform, league_id, token, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, platform, league_id, token, time.time()),
        )
    return token


def consume_challenge(user_id, platform, league_id, token):
    """One atomic statement: the token must belong to this user and league, be
    unused and under 15 minutes old. Marks it used and reports whether it was valid."""
    now = time.time()
    with db._conn() as c:
        c.execute(
            "UPDATE league_chat_challenges SET used_at = %s "
            "WHERE user_id = %s AND platform = %s AND league_id = %s AND token = %s "
            "AND used_at IS NULL AND created_at > %s RETURNING id",
            (now, user_id, platform, league_id, token, now - CHALLENGE_TTL),
        )
        return c.fetchone() is not None


def post_message(user_id, platform, league_id, body):
    text = (body or "").strip()
    if not text:
        raise ChatError("Write something first.", 400)
    if len(text) > MAX_BODY:
        raise ChatError(f"Messages are limited to {MAX_BODY} characters.", 400)
    member = _require_member(user_id, platform, league_id)
    if member["muted_until"] and member["muted_until"] > time.time():
        raise ChatError("You're muted in this chat for now.", 403)
    with db._conn() as c:
        c.execute(
            "INSERT INTO league_messages (platform, league_id, user_id, body, created_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id, user_id, body, created_at",
            (platform, league_id, user_id, text, time.time()),
        )
        row = db._fetch_row(c)
    return dict(row)


def list_messages(platform, league_id, after=0, limit=PAGE_SIZE):
    after = max(0, int(after))
    limit = max(1, min(int(limit), PAGE_SIZE))
    with db._conn() as c:
        c.execute(
            "SELECT m.id, m.user_id, u.username, m.body, m.created_at "
            "FROM league_messages m JOIN users u ON u.id = m.user_id "
            "WHERE m.platform = %s AND m.league_id = %s AND m.id > %s AND m.deleted_at IS NULL "
            "ORDER BY m.id LIMIT %s",
            (platform, league_id, after, limit),
        )
        return [dict(r) for r in c.fetchall()]


def _message_row(message_id):
    with db._conn() as c:
        c.execute(
            "SELECT id, user_id, platform, league_id, deleted_at FROM league_messages WHERE id = %s",
            (message_id,),
        )
        row = c.fetchone()
    if row is None:
        raise ChatError("That message doesn't exist.", 404)
    return dict(row)


def delete_message(actor_id, message_id):
    """Soft delete: the row stays for moderation, members stop seeing it."""
    msg = _message_row(message_id)
    if msg["user_id"] != actor_id:
        actor = get_member(actor_id, msg["platform"], msg["league_id"])
        if actor is None or actor["role"] != "moderator":
            raise ChatError("Only the author or a moderator can delete a message.", 403)
    with db._conn() as c:
        c.execute("UPDATE league_messages SET deleted_at = %s WHERE id = %s", (time.time(), message_id))


def report_message(reporter_id, message_id):
    msg = _message_row(message_id)
    _require_member(reporter_id, msg["platform"], msg["league_id"])
    with db._conn() as c:
        c.execute(
            "INSERT INTO league_message_reports (message_id, reporter_id, created_at) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (message_id, reporter_id, time.time()),
        )


def mute_member(actor_id, target_user_id, platform, league_id, minutes):
    actor = _require_member(actor_id, platform, league_id)
    if actor["role"] != "moderator":
        raise ChatError("Only a moderator can mute.", 403)
    if not 1 <= minutes <= MAX_MUTE_MINUTES:
        raise ChatError("Mute for between 1 minute and 7 days.", 400)
    with db._conn() as c:
        c.execute(
            "UPDATE league_chat_members SET muted_until = %s "
            "WHERE user_id = %s AND platform = %s AND league_id = %s",
            (time.time() + minutes * 60, target_user_id, platform, league_id),
        )
