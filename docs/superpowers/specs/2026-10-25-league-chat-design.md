# League chat for Lineup Lab — design (approved 2026-10-25)

## Goal
Let users who connected the same league chat with each other inside the app.

## Decisions I defaulted to (change any of them)
- Verification: **Sleeper username must match a roster owner** in that league. ESPN leagues fall back to an **invite code** created by the first verified member.
- Delivery: **polling** every ~5 s while the chat tab is open. No WebSockets (single small Render instance).
- Content: text only, 500-character cap, no images or links auto-expanded.
- Moderation: report, mute a user, delete your own message; a league's first verified member is its moderator and can remove messages.

## Facts I checked
- Users connect leagues by (platform, league_id) via /api/teams/*; no first-class league record exists.
- Sleeper league IDs are public, so "same ID" alone is not proof of membership.
- Schema lives in Supabase migrations (repo holds one), so new tables go in a new migration file.
- Not yet checked: the existing `teams` table columns, which I haven't seen. The plan below assumes they hold platform, league_id, roster_id and user_id.

## Data model (new migration)
- `league_chat_members(user_id, platform, league_id, role, joined_at, muted_until)` — verified membership.
- `league_messages(id, platform, league_id, user_id, body, created_at, deleted_at)` — index on (platform, league_id, id).
- `league_message_reports(message_id, reporter_id, created_at)`.
- `league_invites(code, platform, league_id, created_by, created_at)` for the ESPN fallback.

## API (server.py)
- `POST /api/chat/join` — verify and add the user.
- `GET /api/chat/messages?league=…&after=<id>` — members only.
- `POST /api/chat/messages` — members only, rate-limited (e.g. 10 per minute).
- `POST /api/chat/report`, `POST /api/chat/mute`, `DELETE /api/chat/messages/{id}`.

## UI (static/app.js, index.html, style.css)
New "League chat" tab: message list, input, mute/report menu, empty state explaining verification.

## Safety and risk
- Strangers must never read or post: every read and write checks membership server-side.
- Delete-account must also remove or anonymise the user's messages (existing test_delete_account.py needs extending).
- Chat is user-generated content: needs a report path and terms mention. Do not launch before moderation works.
- Load: polling at 20–100 users is fine; revisit before any viral spike.

## Files touched (roughly 6, so approval needed first)
migrations/ (new), engine/db.py, engine/sleeper.py or similar for owner match, server.py, static/app.js, static/index.html, static/style.css, tests/ (new).

## Tests
Membership gate (member / non-member / muted), rate limit, delete-account cleanup, Sleeper owner match, message ordering with `after`.

## Rollout
Behind a setting, ship to your own league first, then everyone.

## Needs from you
Approve this design (or edit the defaults above), then I write the plan and build it test-first.
