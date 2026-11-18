# Connect-League Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare "paste your league URL" gate with mockup A: Sleeper connect-by-username, an ESPN 3-step guide, a Yahoo "Soon" tab, a launch-page-style selling side and a Daily Drive button, on desktop, phones and inside the iOS app.

**Architecture:** One new server endpoint wraps Sleeper's public user→leagues API. One new front-end file (`static/connect.js`) builds the connect card and is mounted twice: in the post-sign-in gate (`renderGateConnectLeague`) and in Settings. The gate's left panel gets connect-mode copy; on phones the card is followed by a Daily Drive card and feature list inside the panel.

**Tech Stack:** FastAPI (Python 3.9), `requests`, vanilla JS, `static/style.css` tokens, `unittest` + FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-11-17-connect-league-redesign-design.md` (mockups: `docs/mockups/connect/a.png`, `a-phone.png`)

## Global Constraints

- Real data only: league lists come from Sleeper's API; no placeholder leagues.
- The existing paste-a-link path (`POST /api/teams/lookup`) keeps working for both platforms.
- Yahoo is shown as "Soon" and is not selectable.
- ESPN step 2 copy names the exact path `League → Settings → Basic Settings` and the toggle `Make League Viewable to Public` (commissioner only).
- Placement unchanged: shown after sign-in when `state.teams` is empty; "Skip for now" stays.
- No native iOS changes this round. Links to Sleeper/ESPN are plain `https` links (the app opens them in its Safari sheet).
- Test command: `~/Desktop/fantasy-app/.venv/bin/python -W ignore -m unittest discover -s tests -t .`
- Nothing is pushed or deployed without the owner's yes.

## Review Focus

1. **Username typed loosely** (`  @HXS_Football `): trim, drop a leading `@`, lowercase before calling Sleeper. Test in Task 1.
2. **League link pasted into the username box** (a `sleeper.com/leagues/...` URL or an all-digits ID): route to the existing link lookup instead of a username search. Test in Task 2 (string check) and manual check in Task 4.
3. **New season with no leagues yet:** when the current `league_season` returns no leagues, fall back to `previous_season` and say which season is shown. Test in Task 1.
4. **Sleeper down or slow:** timeout/HTTP error → 502 with "Sleeper didn't answer. Try again in a minute.", never a 500 stack. Test in Task 1.
5. **League already connected:** leagues already in `state.teams` show "Connected" (disabled) instead of Connect. Manual check in Task 4.

---

### Task 1: Sleeper user-leagues lookup (server)

**Files:**
- Modify: `engine/sleeper.py` (new functions after `get_nfl_state`; `league_snapshot` team dicts)
- Modify: `server.py` (new endpoint next to `/api/teams/lookup`, ~line 1376; new rate limiter next to `play_rate_limit`)
- Test: `tests/test_connect_league.py` (new)

**Interfaces:**
- Produces: `sleeper.normalize_username(raw: str) -> str`
- Produces: `sleeper.user_leagues(username: str) -> dict` returning
  `{"user_id": str, "username": str, "display_name": str, "season": str, "leagues": [{"league_id": str, "name": str, "total_rosters": int, "scoring_label": "PPR"|"Half PPR"|"Standard", "avatar_url": str|None}]}`;
  raises `LookupError` when the user doesn't exist; lets `requests` errors propagate.
- Produces: `league_snapshot(...)["teams"][i]` gains `"owner_id": str|None` and `"co_owner_ids": list[str]`.
- Produces: `GET /api/sleeper/user-leagues?username=` → the dict above; 400 empty username; 404 `No Sleeper user named "<name>".`; 502 `Sleeper didn't answer. Try again in a minute.`

- [ ] **Step 1: Write the failing tests** in `tests/test_connect_league.py` (mock `engine.sleeper.requests.get`, `get_nfl_state`, and for the snapshot `get_league/get_rosters/get_users/id_crosswalk`):

```python
def test_normalize_username(self):
    self.assertEqual(sleeper.normalize_username("  @HXS_Football "), "hxs_football")

def test_user_leagues_maps_fields(self):
    # /user/hxs -> {"user_id":"u1","username":"hxs","display_name":"HXS"}
    # /user/u1/leagues/nfl/2026 -> [{"league_id":"L1","name":"Dynasty","total_rosters":12,"avatar":None,"scoring_settings":{"rec":1}}]
    out = sleeper.user_leagues("HXS")
    self.assertEqual(out["user_id"], "u1"); self.assertEqual(out["season"], "2026")
    self.assertEqual(out["leagues"][0], {"league_id": "L1", "name": "Dynasty", "total_rosters": 12,
                                         "scoring_label": "PPR", "avatar_url": None})

def test_scoring_labels(self):  # rec 0.5 -> "Half PPR", rec 0 / missing -> "Standard"

def test_unknown_user_raises_lookuperror(self):  # Sleeper returns JSON null for /user/<name>

def test_falls_back_to_previous_season_when_empty(self):
    # state {"league_season":"2027","previous_season":"2026"}; 2027 -> [], 2026 -> [one league]
    self.assertEqual(sleeper.user_leagues("hxs")["season"], "2026")

def test_snapshot_exposes_owner_ids(self):
    # roster {"roster_id":1,"owner_id":"u1","co_owners":["u2"],"players":[]}
    t = sleeper.league_snapshot("L1")["teams"][0]
    self.assertEqual((t["owner_id"], t["co_owner_ids"]), ("u1", ["u2"]))

def test_endpoint_statuses(self):
    c = TestClient(server.app); server._RATE_BUCKETS.clear()
    # user_leagues patched: ok -> 200 body passthrough; LookupError -> 404 with 'No Sleeper user named "zz".';
    # requests.Timeout -> 502 "Sleeper didn't answer. Try again in a minute."; username="" -> 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/Desktop/fantasy-app/.venv/bin/python -W ignore -m unittest tests.test_connect_league -v`
Expected: FAIL (`AttributeError: module 'engine.sleeper' has no attribute 'normalize_username'`)

- [ ] **Step 3: Implement** in `engine/sleeper.py`: `normalize_username`, `user_leagues` (plain `requests.get(..., timeout=10)` + `raise_for_status()`, no disk cache, since these are per-person lookups; season from `get_nfl_state()["league_season"]`, fallback `previous_season`; scoring label from `scoring_settings["rec"]`: 1→PPR, 0.5→Half PPR, else Standard; `avatar_url()` for the league avatar). Add `owner_id`/`co_owner_ids` to the snapshot team dict. In `server.py`: `sleeper_lookup_rate_limit = rate_limit("sleeper_lookup", limit=30, window_seconds=60)` and `@app.get("/api/sleeper/user-leagues", dependencies=[Depends(sleeper_lookup_rate_limit)])` mapping errors to the statuses above (return via `_clean`).

- [ ] **Step 4: Run to verify they pass**

Run: same command. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sleeper.py server.py tests/test_connect_league.py
git commit -m "feat: Sleeper connect-by-username lookup endpoint"
```

### Task 2: Shared connect card (`static/connect.js`) + Settings uses it

**Files:**
- Create: `static/connect.js`
- Modify: `static/index.html` (add `<script src="/connect.js"></script>` before `/app.js` at ~line 551; replace the Settings connect markup at ~lines 417–433, i.e. `#set-connect-platform` through `#set-connect-results`, with `<div id="set-connect-card"></div>`)
- Modify: `static/app.js` (Settings connect block ~lines 5671–5720 replaced by one `mountConnectCard` call)
- Modify: `static/style.css` (`.cc-*` styles, existing tokens)
- Test: `tests/test_connect_league.py` (static-file checks)

**Interfaces:**
- Consumes: `GET /api/sleeper/user-leagues`, `POST /api/teams/lookup`, `POST /api/teams`, `GET /api/teams`; globals from app.js used only at call time: `api`, `esc`, `proxyImg`, `safeUrl`, `showToast`, `state`.
- Produces: `window.mountConnectCard(container: HTMLElement, opts: {onConnected: (team) => Promise<void>|void, onPrivateEspn: () => void}) -> void`

Card behavior (mockup A right side / `a-phone.png`):
- Tabs: Sleeper (default), ESPN, Yahoo (`SOON`, disabled).
- **Sleeper:** label "Your Sleeper username", input, "Find my leagues" button. Hint: "In the Sleeper app: tap your profile photo; your username is under your name." plus an "Open Sleeper ↗" link to `https://sleeper.com/`. Results: a "Your <season> leagues" list, each row showing name, `<n> teams · <scoring_label>`, and a Connect button. A league already in `state.teams` (same `league_id`) shows a disabled "Connected". Zero leagues: `"<username> has no NFL leagues for <season> on Sleeper."`. If the input is all digits or contains `sleeper.com`/`sleeper.app`, skip the username search and run the link lookup.
- **Connect (Sleeper):** `POST /api/teams/lookup` with the league_id, then pick the team whose `owner_id` or `co_owner_ids` matches the lookup's `user_id` and `POST /api/teams` straight away. With no match, show the existing "Which team is yours?" list with "This is me" buttons.
- "Paste a league link instead" toggles the existing link input, which works for whichever platform tab is active.
- **ESPN:** three numbered steps.
  1. "Open your league in ESPN Fantasy", with "Open ESPN Fantasy ↗" linking to `https://fantasy.espn.com/football/`.
  2. "Make sure the league is public": "Commissioner only: `League → Settings → Basic Settings`, turn on **Make League Viewable to Public**. Not the commissioner? Send them this step."
  3. "Copy the league link and paste it here", showing the example `fantasy.espn.com/football/league?leagueId=8423117` and "The number alone works too.", with an input and a Connect button using the existing lookup.
  Below the steps: "Private league? Set it up in Settings" calls `opts.onPrivateEspn`. The existing ESPN disclaimer text stays under the ESPN tab.

- [ ] **Step 1: Write failing static checks** (read files like `test_ios_app_server._r`):

```python
def test_connect_card_wired(self):
    js = _r("static/connect.js"); html = _r("static/index.html")
    for s in ["/api/sleeper/user-leagues", "Make League Viewable to Public", "League → Settings → Basic Settings",
              "https://fantasy.espn.com/football/", "https://sleeper.com/", "SOON", "co_owner_ids", "mountConnectCard"]:
        self.assertIn(s, js)
    self.assertLess(html.index('src="/connect.js"'), html.index('src="/app.js"'))
    self.assertIn('id="set-connect-card"', html)
```

- [ ] **Step 2: Run to verify it fails.** Run: `... -m unittest tests.test_connect_league -v`. Expected: FAIL (no `static/connect.js`).
- [ ] **Step 3: Implement** `connect.js`, the Settings mount (`onConnected`: refresh `state.teams`, `renderTeamsList()`, `showToast`; `onPrivateEspn`: scroll to the ESPN cookie fields), styles.
- [ ] **Step 4: Run the full suite.** Run: the Global Constraints test command. Expected: OK (existing skips only).
- [ ] **Step 5: Commit** `git add static/connect.js static/index.html static/app.js static/style.css tests/test_connect_league.py && git commit -m "feat: shared connect card (Sleeper username, ESPN guide) in Settings"`

### Task 3: Gate layout (selling side, Daily Drive, phone stack)

**Files:**
- Modify: `static/app.js` `renderGateConnectLeague` (~line 5888) and the auth-gate reset (~line 5835)
- Modify: `static/style.css` (`.gate-fullscreen.connect-mode` rules)
- Test: `tests/test_connect_league.py`

**Interfaces:**
- Consumes: `mountConnectCard` (Task 2), `proceedPastGate(true)`, `leaveGateFor`, `goToLeagueConnect`, `switchTab(DEFAULT_TAB)`.

Copy (from mockup A):
- Left headline: "Connect your league." + accent "Get this week's answers."
- Subcopy: "Takes about 30 seconds. We only read your league; we never post or change anything."
- Feature cards:
  - "Start/Sit for your roster": "Who to play, with the matchup and weather behind every call."
  - "Waivers that beat your bench": "Pickups ranked against the players you already have."
  - "Trades that raise your odds": "See if an offer helps your playoff chances before you accept."
  - "Live scores, every game": "Your players' points as they happen on Sunday."
- Daily Drive card: tag "Not ready yet?", title "Play today's Daily Drive", line "7 NFL trivia plays. No league needed.", button "Play now" linking to `/play`, with `static/img/daily-drive-cover.webp` as the image.
- Panel title: "Where's your league?" with sub "Pick your app and we'll find it."

- [ ] **Step 1: Write failing static checks:** `renderGateConnectLeague` source contains `"Where's your league?"`, `"Get this week's answers."`, `'href="/play"'`, `mountConnectCard(` and `connect-mode`; the auth gate removes `connect-mode` (string `classList.remove("connect-mode")` present).
- [ ] **Step 2: Run to verify it fails.** Run the module tests. Expected: FAIL.
- [ ] **Step 3: Implement:**
  - On entry, add `connect-mode` to `#gate-root`.
  - Fill `#gate-headline`, `#gate-subcopy` and `#gate-points` (feature cards + Daily Drive card) for the desktop left panel.
  - In `#gate-panel`, render the title, `mountConnectCard`, and a phone-only block (Daily Drive card, then a compact feature list) shown below 820px. The left panel already hides below 820px.
  - Keep "Skip for now".
  - The auth gate (`renderGateAuth`) removes `connect-mode` and restores the default points markup.
  - `onConnected` calls `proceedPastGate(true)`; `onPrivateEspn` calls `leaveGateFor(goToLeagueConnect)`.
- [ ] **Step 4: Run the full suite.** Expected: OK.
- [ ] **Step 5: Commit** `git commit -am "feat: connect gate redesign (selling side, Daily Drive, phone layout)"`

### Task 4: Verify in a browser (desktop, phone, in-app)

**Files:** none (fixes go back into Tasks 2–3 files)

- [ ] **Step 1:** Run the local server and open the gate signed in with no teams, using a local test account from the project's seed/fixtures.
- [ ] **Step 2:** At 1440×900, check that the layout matches `a.png`.
  - Search a real public Sleeper username (owner supplies one, or use a league-member username from a public league ID already in the tests).
  - Leagues list; Connect auto-picks or falls back to the "This is me" list.
  - The ESPN tab shows the 3 steps; Yahoo can't be selected.
  - Daily Drive opens `/play`.
- [ ] **Step 3:** At 390×844, and at 390×844 with the user agent suffix `LineupLabApp/1.0`, check the stack order: card, then Daily Drive card, then features. No horizontal scroll; site chrome hidden in-app.
- [ ] **Step 4:** Check Review Focus items 2 and 5 by hand: paste a league URL into the username box, and try a league that's already connected.
- [ ] **Step 5:** Send the owner screenshots. Ask for a yes before pushing or deploying.
