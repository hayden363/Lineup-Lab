# Connect-your-league screen redesign — design

Date: 2026-11-17 · Owner: Hayden · Status: approved 2026-11-17 ("approve as long as it works")
Mockups (throwaway): docs/mockups/connect/a.png (desktop), a-phone.png (iPhone). B's ESPN walkthrough is folded into A.

## Why
The connect screen is the first thing a new account sees and it reads as a bare "paste your league URL or ID" box.
People don't know where to find a league link, don't know ESPN leagues must be public, and bounce. The screen should
explain itself, still sell the app (like the launch page), and offer The Daily Drive to anyone not ready to connect.

## Goals
- Sleeper: connect by **username** (no link hunting). Type username → see this season's leagues → tap Connect. When the
  username owns a team in that league, pick it automatically (skip "which team is yours").
- ESPN: a 3-step guide inside the ESPN tab: (1) open your league (button to ESPN Fantasy), (2) make it public
  (exact path `League → Settings → Basic Settings → Make League Viewable to Public`, commissioner only, "not the commish?
  send them this step"), (3) copy the link and paste (show what a link looks like; the number alone works).
  Private league → pointer to Settings (existing espn_s2/SWID flow).
- Yahoo: a "Soon" tab, not selectable.
- Selling side like the launch page: headline, four feature cards (Start/Sit, Waivers, Trades, Live scores), a
  Daily Drive card with a Play button.
- Same place as today: shown after sign-in to anyone with no connected league; "Skip for now" stays.
- Works on desktop, phone browsers and inside the iOS app (in-app mode hides the site chrome already).
- Settings → Connect a league gets the same Sleeper-username option and ESPN guide.

## Non-goals
- Real Yahoo support (needs Yahoo OAuth + a registered Yahoo developer app: separate project).
- Changing sign-up / sign-in or moving the screen before account creation.
- Native iOS changes in this round (see iOS below).

## Anti-goals
- Nothing simulated: league lists come from Sleeper's real API; no fake "your leagues" placeholders.
- Don't break the existing paste-a-link path for either platform (kept as "Paste a league link instead").

## Approaches considered
- **A: split screen (picked).** Selling panel left, connect card right; stacks on phones (connect card first, then
  Daily Drive card, then features). Best balance of selling and doing.
- **B: big platform tiles + walkthrough.** Most hand-holding; its ESPN 3-step guide is reused inside A's ESPN tab.
- **C: 3-step wizard with live preview.** Rejected by owner.

## How (decided)
- Server: new `GET /api/sleeper/user-leagues?username=` → Sleeper `GET /v1/user/{username}` then
  `GET /v1/user/{user_id}/leagues/nfl/{season}` (season from `/state/nfl`). Returns league id, name, team count,
  scoring label, and the user's `user_id`. Rate-limited like other public lookups; short cache; clear errors
  ("No Sleeper user named X", "X has no leagues this season").
- `league_snapshot` exposes each team's `owner_id` so the client can auto-pick the team whose owner is that user_id;
  falls back to the existing "This is me" list when there's no match (e.g. co-owner).
- Client: `renderGateConnectLeague` (static/app.js) rebuilt with the new layout; shared connect-card builder reused by
  Settings. Styles in static/style.css with the existing tokens.
- Daily Drive button: `/play`. Inside the iOS app the web view loads `/play` in that tab (works; a jump to the native
  Daily Drive tab needs the native change below).

## iOS
Inside the app, non-Lineup-Lab links open in an in-app Safari sheet, so "Open Sleeper" / "Open ESPN Fantasy" show the
website, not the native app. Opening the real apps needs a small native change (open those links with
`UIApplication.open` so universal links launch the apps) plus a native tab switch for the Daily Drive button. That ships
in the next app update (1.0.1) after 1.0 clears review; the web changes reach the app immediately.

## Testing
Unit tests for the new endpoint (username found / not found / no leagues, season handling, Sleeper errors) with mocked
HTTP; owner_id in the snapshot; existing connect tests stay green. Browser check at desktop and phone widths and with the
in-app user agent. Full suite run before asking to deploy. Nothing deployed without the owner's yes.

## Left to the builder
Exact copy, spacing and icons within the mockup's direction; caching TTLs; error wording.
