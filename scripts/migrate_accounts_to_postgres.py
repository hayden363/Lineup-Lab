"""
ONE-TIME MIGRATION: local edgeboard.db (SQLite) -> Postgres (Supabase)
=========================================================================
Copies every real row — users, sessions, connected_teams, user_settings,
verification_tokens — from the old local SQLite accounts database into
the new Postgres one, preserving exact IDs so every foreign-key
relationship between them stays intact. Existing sessions keep working;
nobody has to sign in again.

Run once, after DATABASE_URL is set in .env and the schema already
exists on the Postgres side (see engine/db.py / the project's Supabase
migration history):

    source .venv/bin/activate
    python3 scripts/migrate_accounts_to_postgres.py

Safe to re-run: every insert is ON CONFLICT DO NOTHING, so re-running
after a partial run (or after new local signups) just fills in whatever
rows aren't already on the Postgres side, rather than erroring or
duplicating.
"""

import os
import sqlite3
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_PATH = os.path.join(REPO_ROOT, "edgeboard.db")

TABLES = ["users", "connected_teams", "sessions", "user_settings", "verification_tokens"]


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL isn't set in .env — see .env.example for how to get it "
                 "from the Supabase dashboard, then re-run this script.")
    if not os.path.exists(SQLITE_PATH):
        sys.exit(f"No local database found at {SQLITE_PATH} — nothing to migrate "
                 "(a fresh install has no old data; this script isn't needed).")

    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.row_factory = sqlite3.Row

    with psycopg.connect(database_url) as pconn:
        with pconn.cursor() as pc:
            counts = {}

            users = sconn.execute("SELECT * FROM users").fetchall()
            for r in users:
                pc.execute(
                    "INSERT INTO users (id, username, email, password_hash, created_at, "
                    "email_verified, google_id, apple_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (r["id"], r["username"], r["email"], r["password_hash"], r["created_at"],
                     bool(r["email_verified"]), r["google_id"], r["apple_id"]),
                )
            counts["users"] = len(users)

            teams = sconn.execute("SELECT * FROM connected_teams").fetchall()
            for r in teams:
                pc.execute(
                    "INSERT INTO connected_teams (id, user_id, platform, league_id, league_name, "
                    "roster_id, team_name, avatar_url, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (r["id"], r["user_id"], r["platform"], r["league_id"], r["league_name"],
                     r["roster_id"], r["team_name"], r["avatar_url"], r["created_at"]),
                )
            counts["connected_teams"] = len(teams)

            sessions = sconn.execute("SELECT * FROM sessions").fetchall()
            for r in sessions:
                pc.execute(
                    "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (token) DO NOTHING",
                    (r["token"], r["user_id"], r["created_at"], r["expires_at"]),
                )
            counts["sessions"] = len(sessions)

            settings = sconn.execute("SELECT * FROM user_settings").fetchall()
            for r in settings:
                pc.execute(
                    "INSERT INTO user_settings (user_id, sleeper_league_id, sleeper_roster_id, "
                    "sleeper_team_name, espn_league_id, espn_swid, espn_s2, scoring_preset, theme, "
                    "updated_at, active_team_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (user_id) DO NOTHING",
                    (r["user_id"], r["sleeper_league_id"], r["sleeper_roster_id"], r["sleeper_team_name"],
                     r["espn_league_id"], r["espn_swid"], r["espn_s2"], r["scoring_preset"], r["theme"],
                     r["updated_at"], r["active_team_id"]),
                )
            counts["user_settings"] = len(settings)

            tokens = sconn.execute("SELECT * FROM verification_tokens").fetchall()
            for r in tokens:
                pc.execute(
                    "INSERT INTO verification_tokens (token, user_id, purpose, created_at, expires_at) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (token) DO NOTHING",
                    (r["token"], r["user_id"], r["purpose"], r["created_at"], r["expires_at"]),
                )
            counts["verification_tokens"] = len(tokens)

            # bump the identity sequences past the highest migrated id, so
            # the next real signup doesn't collide with a preserved old id
            for table in ("users", "connected_teams"):
                pc.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                )

        pconn.commit()

    sconn.close()
    print("Migrated:")
    for table, n in counts.items():
        print(f"  {table}: {n} rows")


if __name__ == "__main__":
    main()
