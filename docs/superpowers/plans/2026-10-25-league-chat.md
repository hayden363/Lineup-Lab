# League Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verified members of the same Sleeper league can chat with each other in a new League chat tab.

**Architecture:** New Supabase tables hold members, messages, reports and verification challenges. `engine/chat.py` owns chat logic (membership, posting, moderation, Sleeper ownership check) on top of `engine/db.py`'s `_conn()`; `server.py` exposes thin `/api/chat/*` routes; the UI polls every 5 s while the tab is open.

**Tech Stack:** FastAPI, psycopg (Postgres/Supabase), vanilla JS in `static/app.js`, `unittest` with the mocked-cursor pattern from `tests/test_delete_account.py`.

**Spec:** `docs/superpowers/specs/2026-10-25-league-chat-design.md`

## Deviations from the approved spec (need your OK)
1. **Verification is a team-name challenge, not a username match.** `connected_teams` accepts any `roster_id` and Sleeper has no login, so a typed username proves nothing. Instead the app gives the user a one-time token; they put it in their Sleeper team name; we re-read `engine/sleeper.get_users(league_id, force=True)` and match `metadata.team_name`. The matched Sleeper `user_id` is stored, and one Sleeper user maps to one Lineup Lab account per league.
2. **ESPN is out of v1.** The spec's invite-code fallback is dropped; ESPN leagues see "League chat is Sleeper-only for now". Reason: no ownership proof for ESPN is designed yet, and an invite code relies on people keeping it secret.
3. **Deleted accounts cascade-delete their messages** (FK `ON DELETE CASCADE`, same as every other users table), instead of anonymising.

## Global Constraints
- Message body: 1–500 characters after trimming, text only, rendered with `textContent` (never `innerHTML`).
- Post limit: 10 messages per 60 seconds per user. Poll endpoint: 30 per 60 seconds per user.
- Every read and write checks membership server-side; non-members get 403, never an empty list.
- Page size: at most 50 messages per poll, ordered by ascending `id`.
- Schema changes go in a new file under `migrations/` named like `20261025000000_league_chat.sql`; no runtime DDL (see `engine/db.py` `init_db`).
- Tests run with `.venv/bin/python -m unittest discover -s tests -t . -v`. No network in tests; mock `db._conn` and Sleeper calls.

## Review Focus
- A non-member (or a user who never confirmed) requests messages or posts: expect 403, nothing leaked.
- A muted user posts: expect 403 with a clear message, and unmute when `muted_until` passes.
- Empty, whitespace-only or 501-character body: expect 400, nothing stored.
- `after` is missing, negative or non-numeric: expect it treated as 0 / rejected with 400, never a 500.
- Message body containing `<script>` or HTML: expect it displayed as literal text.
- Two Lineup Lab accounts try to verify as the same Sleeper user in one league: expect the second to be refused.
- Challenge token reused, expired (15 min) or belonging to another user: expect refusal.
- A deleted message: expect it to disappear for members, with the row kept for moderation.

---

### Task 1: Migration and chat data layer

**Files:**
- Create: `migrations/20261025000000_league_chat.sql`
- Create: `engine/chat.py`
- Test: `tests/test_league_chat_db.py`

**Interfaces:**
- Consumes: `engine.db._conn()` (context manager yielding a cursor with `dict_row`), `db._fetch_row`.
- Produces (all in `engine/chat.py`):
  - `class ChatError(Exception)` with `status: int`
  - `is_member(user_id: int, platform: str, league_id: str) -> bool`
  - `get_member(user_id, platform, league_id) -> Optional[dict]` (keys: `role`, `muted_until`, `external_id`)
  - `add_member(user_id, platform, league_id, external_id: str, role: str) -> dict` (raises `ChatError(409)` if `external_id` already belongs to another user in that league)
  - `create_challenge(user_id, platform, league_id) -> str` (token, `llab-` + 8 random chars)
  - `consume_challenge(user_id, platform, league_id, token) -> bool` (valid only if matching, unused, under 15 minutes old, same user)
  - `post_message(user_id, platform, league_id, body: str) -> dict`
  - `list_messages(platform, league_id, after: int = 0, limit: int = 50) -> list[dict]` (excludes `deleted_at` rows)
  - `delete_message(actor_id, message_id) -> None` (author or league moderator only)
  - `report_message(reporter_id, message_id) -> None`
  - `mute_member(actor_id, target_user_id, platform, league_id, minutes: int) -> None` (moderator only)

- [ ] **Step 1: Write failing tests** in `tests/test_league_chat_db.py` using `FakeCursor`/`patched_conn` from `tests/test_delete_account.py` style: `test_post_message_rejects_blank_and_501_chars` (raises `ChatError` status 400, no INSERT executed), `test_post_message_rejects_muted_member` (403), `test_add_member_conflicts_on_same_external_id` (409), `test_consume_challenge_rejects_expired_and_wrong_user`, `test_list_messages_excludes_deleted_and_caps_at_50`, `test_delete_message_requires_author_or_moderator`, `test_migration_cascades_on_user_delete` (reads the SQL file; asserts every `REFERENCES users` / `public.users` clause contains `ON DELETE CASCADE`).
- [ ] **Step 2: Run** `.venv/bin/python -m unittest tests.test_league_chat_db -v` — expect FAIL (module missing).
- [ ] **Step 3: Write the migration** with tables `league_chat_members` (PK `(user_id, platform, league_id)`, plus `UNIQUE (platform, league_id, external_id)`, `role text`, `muted_until double precision`, `joined_at`), `league_messages` (`id bigserial`, index on `(platform, league_id, id)`, `deleted_at`), `league_message_reports`, `league_chat_challenges`. Use the column-type style of `migrations/20260928000000_add_activation_events.sql` (it uses `public.` and `user_id` FK; copy its FK form).
- [ ] **Step 4: Implement `engine/chat.py`** with the signatures above; use `db._conn()` and parameterised SQL only; the first member of a league gets `role='moderator'`.
- [ ] **Step 5: Run tests** — expect PASS.
- [ ] **Step 6: Commit** `feat: league chat tables and data layer`.

### Task 2: Sleeper ownership check

**Files:**
- Modify: `engine/chat.py`
- Test: `tests/test_league_chat_verify.py`

**Interfaces:**
- Consumes: `engine.sleeper.get_users(league_id, force=True) -> list[dict]` (each has `user_id`, `display_name`, `metadata.team_name`), Task 1's `consume_challenge`, `add_member`.
- Produces: `verify_sleeper_owner(user_id: int, league_id: str, token: str) -> str` returns the matched Sleeper `user_id`; raises `ChatError(400)` if no Sleeper user's `metadata.team_name` contains the token, or `ChatError(400)` if the token is invalid/expired.

- [ ] **Step 1: Write failing tests**: `test_verify_matches_token_in_team_name` (mock `sleeper.get_users`; asserts returned id and that `force=True` was used), `test_verify_fails_when_token_absent`, `test_verify_fails_for_expired_token`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** `verify_sleeper_owner`; token match is case-insensitive substring on `team_name`; consume the challenge only on success.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: verify Sleeper league ownership by team-name token`.

### Task 3: API routes

**Files:**
- Modify: `server.py` (add routes near the connected-teams routes, ~line 1200; add `user_rate_limit` beside `rate_limit`, ~line 171)
- Test: `tests/test_league_chat_api.py`

**Interfaces:**
- Consumes: Task 1 and 2 functions; `require_user` dependency.
- Produces routes (all `require_user`, league key = `platform`+`league_id` in the body or query):
  - `POST /api/chat/challenge` → `{token, expires_in}` (Sleeper only; other platforms 400 "League chat is Sleeper-only for now")
  - `POST /api/chat/join` body `{platform, league_id, token}` → `{member: {...}}`
  - `GET /api/chat/messages?platform=&league_id=&after=` → `{messages: [...]}`
  - `POST /api/chat/messages` body `{platform, league_id, body}`
  - `DELETE /api/chat/messages/{id}`, `POST /api/chat/report` body `{message_id}`, `POST /api/chat/mute` body `{platform, league_id, user_id, minutes}`
  - `user_rate_limit(key_prefix: str, limit: int, window_seconds: int)` keyed by `user["id"]`, returning 429 like `rate_limit`.

- [ ] **Step 1: Write failing tests** with `TestClient` and mocked `chat.*`: `test_messages_403_for_non_member`, `test_post_403_for_non_member`, `test_post_429_after_10_per_minute`, `test_after_param_garbage_is_400_not_500`, `test_espn_platform_rejected_for_challenge`, `test_unauthenticated_gets_401`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement routes** as thin wrappers; map `ChatError` to `HTTPException(e.status, str(e))`; clamp `after` to an int `>= 0`.
- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: league chat API`.

### Task 4: Chat tab UI

**Files:**
- Modify: `static/index.html`, `static/app.js`, `static/style.css`
- Test: `tests/test_league_chat_ui.py` (static checks, same style as other front-end tests in `tests/` if any; otherwise string assertions on the files)

**Interfaces:**
- Consumes: Task 3 routes; `GET /api/teams` for the user's connected Sleeper leagues.
- Produces: a "League chat" tab with (a) a verify panel showing the token and the steps ("put this in your Sleeper team name, then press Verify"), (b) a message list and input, (c) a per-message menu with Report, Delete (own or moderator) and Mute (moderator).

- [ ] **Step 1: Write failing tests**: `test_chat_rendering_never_uses_innerhtml` (search the chat section of `app.js` for `innerHTML` assignments with message bodies; expect none), `test_chat_poll_interval_is_5s`, `test_polling_stops_when_tab_hidden`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** the tab; render bodies with `textContent`; poll `GET /api/chat/messages` with the last seen id every 5000 ms only while the tab is visible; show the Sleeper-only message for ESPN leagues.
- [ ] **Step 4: Run tests** — expect PASS; then open the app locally (`run.sh`) and send a message between two test accounts to see it work.
- [ ] **Step 5: Commit** `feat: league chat tab`.

### Task 5: Full-suite check and docs

**Files:**
- Modify: `README.md` (one short section on league chat and the Sleeper-only limit)
- Test: existing suite

- [ ] **Step 1:** Run `.venv/bin/python -m unittest discover -s tests -t . -v`; expect all green (previously 648 passing on Oct 22; new tests add to that).
- [ ] **Step 2:** Add the README section.
- [ ] **Step 3: Commit** `docs: league chat`.
- [ ] **Step 4:** Apply the migration to Supabase only after your explicit approval, since it changes the live database. Deploy only on your explicit yes.

## Self-review notes
- Spec coverage: members, messages, reports, delete, mute, polling, 500-char cap, rate limit, cascade delete, moderator role, Sleeper verification: all have a task. Deviations 1-3 listed above.
- Types: `ChatError.status`, `external_id` (Sleeper `user_id` as text) and `after` (int) are used identically across tasks.
- Proportion: plan is intentionally signatures and test names; no function bodies.
