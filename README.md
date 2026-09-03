# 🏈 Lineup Lab

A from-scratch fantasy football valuation app — a full local web app (installable
on your phone as a PWA), with real accounts, real multi-team league sync, and
real security hardening, not just scripts. Built on **free, legal NFL data**
(nflverse / nfl_data_py), including real **Next Gen Stats** player-tracking
data (separation, cushion, completion % above expectation, rush yards over
expected) as the free, legal stand-in for paid grading services like PFF.

**No PFF data is used anywhere.** PFF grades are a paid, proprietary product;
scraping or redistributing them would violate their terms of service. Instead,
the "advanced metrics" layer leans on the NFL's own public Next Gen Stats feed
— the same category of signal, computed transparently, that's actually yours
to own and extend.

## Run it

```bash
./run.sh
```

First run sets up a virtualenv and installs dependencies; every run after
that just starts the server. Then open **http://localhost:8420** —
on your phone, open that URL (same Wi-Fi) and use "Add to Home Screen" to
install it as an app. That's the whole mobile story: there's no separate
native app to build or App Store submission — it's the same responsive PWA,
served by the same process, reachable from any device on your network.

Manual setup, if you'd rather:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8420
```

## What it does

| Layer | File(s) | What it gives you |
|---|---|---|
| Data layer | [engine/data.py](engine/data.py) | Pulls + disk-caches weekly stats, play-by-play, Next Gen Stats, and schedules from nflverse. Auto-detects the latest season that's actually published. |
| Base metrics + SCORE | [engine/metrics.py](engine/metrics.py) | Per-position (QB/RB/WR/TE) efficiency + volume metrics → a 0–100 weighted SCORE. Filters out small-sample noise (mop-up duty, one-target games). Weights start hand-picked but can be replaced with ones **learned from real multi-season history** — see [weight_tuner.py](weight_tuner.py) below. |
| Advanced metrics | [engine/advanced.py](engine/advanced.py) | Real Next Gen Stats (separation, cushion, CPOE, time to throw, rush yards over expected) + play-by-play EPA/explosive-play rate — your PFF-grade proxy, for free. |
| Defensive matchup engine | [engine/defense.py](engine/defense.py) | A real, **multi-stat** defensive profile per team (run defense, pass defense, pressure, plus **defense-side Next Gen Stats** — coverage separation allowed, YAC-over-expectation allowed, CPOE allowed, rush yards over expected allowed — attributed to the right defense via the schedule, since NGS itself has no opponent column), each mapped to the specific SCORE metric it actually predicts. A run-stuffing defense hurts a between-the-tackles runner more than a receiving back; a blanket "points allowed" number can't tell you that. |
| Custom scoring | [engine/scoring.py](engine/scoring.py) | Recomputes fantasy points from raw counting stats using YOUR point values (PPR/Half-PPR/Standard presets, or fully custom) instead of trusting a fixed column. SCORE stays scoring-agnostic on purpose; FPTS/FORM/PROJ/trade value all respect it. |
| Accounts | [engine/db.py](engine/db.py) | Real local accounts — SQLite, bcrypt-hashed passwords, session cookies, email verification, password reset. |
| OAuth sign-in | [engine/oauth.py](engine/oauth.py) | "Continue with Google" — real server-side OAuth2, ID token verified against Google's own public keys (not just decoded and trusted). Signing in with the same email as an existing password account links them. Apple Sign In is built the same way but inactive until you have a paid Apple Developer account for it — see that file. |
| At-rest encryption | [engine/crypto.py](engine/crypto.py) | Fernet symmetric encryption for ESPN cookies — the one genuinely sensitive thing this app stores. |
| Outbound mail | [engine/mail.py](engine/mail.py) | Verification + password-reset emails via Gmail SMTP (an App Password you configure — see Security below). |
| League sync | [engine/sleeper.py](engine/sleeper.py), [engine/espn.py](engine/espn.py) | Sleeper: real, public, read-only sync (no login) — scoring settings, rosters, avatars, real head-to-head weekly matchups, platform-wide trending add/drop counts, via a free nflverse ID crosswalk. ESPN: real sync too — public leagues signed out, private leagues via your own encrypted `espn_s2`/`SWID` — wired into the same connect-team flow as Sleeper, not yet into the decision tools (see Roadmap). |
| DEF/ST + Kicker scoring | [engine/defense_scoring.py](engine/defense_scoring.py), [engine/kicker_scoring.py](engine/kicker_scoring.py) | Real, fully scored DEF/ST and K positions — same SCORE/FORM/PROJ/floor-ceiling treatment as skill positions, each with its own model. |
| Stat-less-player fallback | [engine/role_baseline.py](engine/role_baseline.py) | A real PROJ for a skill player with no personal game log yet (a rookie, a new signing) — off his own current team's real same-depth-chart-rank production, not a guess about his own talent. |
| News | [engine/news.py](engine/news.py) | Real ESPN/CBS NFL RSS headlines, filtered to your roster + this week's opponent's roster (full-name matching only — see the code comment on why). Optional: a short AI-written per-player summary (`ai_summary_for_player`), grounded only in those same real matched headlines — via the Claude API, behind `ANTHROPIC_API_KEY`. |
| Live scores | [engine/live_scores.py](engine/live_scores.py) | Real in-game NFL scores (ESPN's public scoreboard feed) — score, quarter, clock, game state, 20s server-side cache. |
| Decision tools | [engine/tools.py](engine/tools.py) | My Team (roster + real opponent for ANY week of the schedule, not just the live one, + full league matchup slate, all projected), start/sit, **trade analyzer with a real needs-aware recommendation** (not just a point total — for each side, whether what they'd receive fills an actual hole in their CURRENT roster vs. what they'd give up, using the same need-multiplier machinery the draft board's best-available already uses; a per-side tier + reason + live QB/RB/WR/TE need bars, Sleeper leagues only for now), **trade finder** (scans the league for realistic trades that fill your real positional needs), **live draft board** (Sleeper snake drafts — on-the-clock, need-adjusted best-available, real pick-order math), and waiver wire (auto-synced, trending badges) — all built on the same scored board. |
| Board builder | [engine/board.py](engine/board.py) | Combines all of the above into a ranked, matchup-projected big board, a player search, or a single player's full detail record. |
| Weekly-refresh automation | [engine/refresh_scheduler.py](engine/refresh_scheduler.py) | An in-process background task — no separate cron job — that force-refreshes the board on a timer (`REFRESH_INTERVAL_HOURS`, default 24) so it's never stale and a newly published season is picked up without a restart. |
| API | [server.py](server.py) | FastAPI JSON API (see below) that also serves the frontend, plus the security middleware/rate-limiting described below. |
| Frontend | [static/](static/) | Vanilla JS/HTML/CSS (no build step) — a collapsible left sidebar nav (icon rail ↔ full, mobile drawer) across Big Board, My Team (with a week selector — browse any week's real matchup), Draft, Start/Sit, Trade, Waivers, News, and Settings. Full design system: soft glass cards, layered shadows, micro-interactions, entrance animations, skeleton loaders — all in one installable PWA. |

## API

Every read endpoint accepts optional scoring overrides: `?scoring=half_ppr` /
`?scoring=standard` (default: signed-in account's saved preference, else full
PPR), or individual point values (`&reception=0.5&pass_td=6&...`).

- `GET /api/meta` — season, positions, teams, weight config, scoring presets
- `GET /api/board?pos=WR&opp=DAL&min_games=2` — ranked board, optionally matchup-projected (real multi-stat defensive read)
- `GET /api/player/{player_id}?opp=DAL` — full metric breakdown + weekly log + matchup factor
- `GET /api/player/{player_id}/news` — real matched headlines for one player + an optional AI-written summary of them (behind `ANTHROPIC_API_KEY`)
- `GET /api/search?q=...` — player search across all positions
- `GET /api/live-scores` — real in-game scores for the current week, public, no sign-in
- `POST /api/startsit`, `POST /api/trade`, `GET /api/waivers` — the three decision tools (waivers auto-syncs to your active league, with real Sleeper trending-add counts)
- `GET /api/myteam?week=N` — your synced roster + that week's real opponent (any week of the schedule, defaults to the live one) + every other real matchup in the league, all projected (requires sign-in + a connected team)
- `GET /api/trade-finder?target_roster_id=N` — realistic trade suggestions that fill your real needs
- `GET /api/myteam/drafts`, `GET /api/draft/{draft_id}?roster_id=N` — find and load a live/completed Sleeper snake draft board
- `GET /api/news` — real NFL headlines, personalized when signed in with a connected team
- `POST /api/auth/signup` `/login` `/logout` `/change-password` `/forgot-password` `/reset-password`, `GET /api/auth/me` — accounts
- `GET /api/auth/google/start`, `GET /api/auth/google/callback` — "Continue with Google" (only appears in the UI once `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are set — see `.env.example`)
- `GET`/`POST /api/settings` — ESPN fields, scoring preference (per account)
- `GET /api/teams`, `POST /api/teams`, `POST /api/teams/{id}/activate`, `DELETE /api/teams/{id}` — connect/switch/remove multiple Sleeper teams
- `POST /api/teams/lookup` — paste a Sleeper OR ESPN league URL/ID (`platform: "sleeper" | "espn"`), get back its teams to pick from
- `GET /api/sleeper/{league_id}` — sync a public Sleeper league's scoring + rosters + avatars
- `GET /api/espn/{league_id}?year=N` — sync an ESPN league (public works signed out; a private one needs your own `espn_s2`/`SWID` from Settings) — a verification/test endpoint for now, see Roadmap
- `POST /api/refresh` — force-refetch all data, bypassing the disk cache and re-checking for a newly published season (also runs automatically every `REFRESH_INTERVAL_HOURS`, default 24 — see [engine/refresh_scheduler.py](engine/refresh_scheduler.py))

## Data freshness — what's actually live vs. a snapshot

Every field in this app comes from a real source, but not every real source
updates on the same clock. This is the honest ledger — audited directly
against each source, not assumed — so "is this live" has one answer to
check instead of a guess per feature.

**Genuinely live** (Sleeper's API, refetched on Sleeper's own cadence —
seconds to about a day depending on the endpoint, see `PLAYERS_TTL` etc. in
`engine/sleeper.py`):
- Roster composition, league scoring settings, matchup pairings, trending
  adds/drops, team/owner names and avatars, live/completed draft state.
- **Injury status** — `engine/sleeper.live_injury_statuses()`. This used to
  come from nflverse's season-pinned injury report instead, which was
  **actively wrong**, not just old — e.g. it had Jalen Hurts tagged "Out"
  when Sleeper's live data said no designation at all. Fixed; every
  injury flag in the app (Start/Sit, My Team, Trade) now reads this.
- Current team affiliation for ANY player, including one our stat engine
  can't price (`sleeper.resolve_unscored_player`) — this is also what
  drives the DEF/K "team baseline" fallback in `engine/defense_scoring.py`
  / `engine/kicker_scoring.py`, and the real-status retirement filter
  (`sleeper.inactive_gsis_ids`).

**A real season snapshot, not live, but now current as of the actual
most recent completed NFL season** (nflverse — free, legal — `season:
2025` is what the app resolves to as of this writing; `data.resolve_season()`
finds it automatically):
- Weekly box-score stats, play-by-play, Next Gen Stats, schedule, injury
  reports, and snap counts — everything `engine/data.py` loads with a
  `season` argument.
- Everything downstream of those: SCORE, FORM, floor/ceiling, PROJ, the
  matchup engine, DEF/ST and kicker scoring — real, honestly computed,
  from the most recent season that's actually finished and published.
- One partial exception: `data.load_player_status()` (Active/Retired) is
  cached under a fixed `"live"` key, not the season, so it refreshes on
  its own 6-hour cache TTL independent of the stats — current-ish, not
  instantaneous, and only a binary status flag, not stats.

**This section previously said the app was capped at 2024 — that was
true when written, and the diagnosis was real, but the fix turned out to
be available sooner than "wait for nflverse to publish 2025."** nflverse
had already published a full 2025 season; they'd just renamed the
weekly-stats release tag from `player_stats` to `stats_player` (last real
update to the old tag: 2025-05-06), and `nfl_data_py` 0.3.3 — the latest
version on PyPI as of this writing — still hardcodes the dead old URL in
`import_weekly_data()`, so it silently 404'd for any season the old tag
never got, and this app's own season-resolution fallback correctly
treated that failure as "no newer season exists yet." It didn't — the
probe was just asking the wrong address. `engine/data.py` now fetches the
new tag directly (`_fetch_stats_player_week`), verified column-for-column
against the old tag for a season both cover (2024): every value the app
actually uses matched exactly, with a few renamed columns aliased back
(`team`→`recent_team`, `passing_interceptions`→`interceptions`,
`sacks_suffered`→`sacks`). One real, disclosed loss: `dakota` (nflverse's
own QB EPA+CPOE composite, one of `QB_WEIGHTS`) isn't in the new tag under
any name checked — `engine/metrics.py` already degrades that gracefully
(neutral instead of a crash) rather than needing a workaround. If a
future `nfl_data_py` release restores `import_weekly_data()` for the new
tag, this whole direct-fetch layer can come back out — it's a narrowly
scoped bypass of one dead URL, not a rewrite of how the app gets its data.

**What this means for a specific player with no real current-season game
log** — most commonly a true rookie a few games into their first season,
or a kicker who's never gotten an active roster spot — see
`engine/kicker_scoring.py`'s team-baseline fallback,
`engine/role_baseline.py`'s depth-chart-rank fallback, and
`engine/tools.py`'s `_roster_players` docstring: real per-game history is
the only thing SCORE/FORM/floor/ceiling are willing to be built from, so
those stay `None` rather than fabricated for a genuinely stat-less
player. PROJ still shows a real number where one exists one level up (a
kicker's own team's real production, or a skill player's own team's
real same-depth-chart-rank production, computed the same honest way),
and `0.0` — not a blank — everywhere no real number exists at all yet,
so no roster slot is silently empty. A player who picks up real games
this season stops needing any of this the moment they qualify — nothing
special to flip, the board just prices them for real once there's real
data to price them from.

**No live odds/props, no live weather, no live betting-market signal** —
none of that is wired in anywhere; the Player Prop Evaluator roadmap item
would need a paid odds API and is explicitly kept separate from valuation.

## Accounts, multi-team sync, and email

Signup/login/logout/change-password/forgot-password/reset-password all work
for real: usernames and emails are unique and validated, passwords are
bcrypt-hashed, sessions are real server-side tokens in an httponly cookie.

**Multiple teams.** Connect as many Sleeper teams as you actually play in —
paste a league URL or its bare numeric ID in Settings, pick which roster is
yours, and it's added to your account. Switch which one is "active" any
time; My Team, Waivers, and News all follow whichever team is active. Each
connection is stored per-account (`connected_teams` table), so it's there
whichever device you sign in from.

**Email — what's real and whose address it is.** Verification and
password-reset emails work for real, sent via Gmail's SMTP relay. Setup:

```bash
cp .env.example .env   # then edit .env yourself — see the file for the two lines
```

You'll need a Gmail **App Password** (not your normal password) — instructions
are in `.env.example` and `engine/mail.py`. Important clarification: the
`GMAIL_ADDRESS` you configure is **your own** Gmail account (or any address
you control) — Lineup Lab sends through it, the same way any app sends mail
through an account someone owns. There is no "Claude-owned" inbox this could
send from instead, and no way for Claude to receive or reply to email — an AI
assistant doesn't have a persistent inbox to check, in this conversation or
any other. Every email this app sends goes out under an address you control,
and only you receive replies to it.

If `.env` isn't set up, signup/forgot-password still work fine — accounts
just stay unverified / reset links don't go out until mail is configured.

**ESPN league sync** has its settings fields ready (league ID, `espn_s2`,
`SWID` — encrypted at rest, see Security) but isn't wired to live roster
data yet — see Roadmap. The Settings page explains exactly what each field
is for and which are optional.

## Security

This is a LAN-local dev app (not deployed behind TLS), so some of this is
about doing right by data at rest and by anyone else on your network more
than defending against the open internet. What's actually implemented:

- **Passwords**: bcrypt-hashed, never stored or logged in plaintext.
- **Sessions**: cryptographically random tokens (`secrets.token_urlsafe`),
  `httponly` + `SameSite=Lax` cookies (blocks classic cross-site POST CSRF),
  `Secure` auto-enabled if this ever sits behind HTTPS.
  A password reset also invalidates every other existing session for that account.
- **Rate limiting**: login/signup/resend-verification/forgot-password are
  capped per IP (e.g. 10 login attempts / 5 min) — see `rate_limit()` in `server.py`.
- **Account enumeration**: `forgot-password` always returns the same generic
  response whether or not the email exists.
- **ESPN cookies encrypted at rest**: Fernet symmetric encryption
  (`engine/crypto.py`), keyed by `APP_SECRET_KEY` (`.env`) or an
  auto-generated local key file (`.app_secret_key`, gitignored). `GET
  /api/settings` never echoes the decrypted value back — only whether it's set.
- **XSS**: every dynamic string the frontend renders (player/team/owner/league
  names from Sleeper, RSS headlines, your own username/email) is HTML-escaped
  before insertion; every clickable/loadable URL is protocol-checked
  (`http`/`https` only) before use — see `esc()`/`safeUrl()` in `static/app.js`.
- **SQL injection**: parameterized queries everywhere in `engine/db.py`; the
  one dynamic column list (`update_settings`) is built from a fixed
  whitelist, never from raw input.
- **Response headers**: `X-Content-Type-Options: nosniff`, `X-Frame-Options:
  DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, a `Content-Security-Policy`
  restricting scripts/styles/connections to same-origin (no external
  dependencies to allow), and `Permissions-Policy` disabling camera/mic/geo.
- **CORS**: none — this process serves its own frontend, same-origin only,
  so there's no cross-origin API surface to protect.
- **No password-reset-required-question, no plaintext credential logging,
  no secrets in error messages** returned to the client.

**Known, disclosed limitations, not overlooked:**
- No TLS termination — if you expose this beyond your own LAN, put it behind
  a reverse proxy or tunnel (Caddy, Tailscale, ngrok) that terminates HTTPS.
- Signup allows account enumeration via the "username already taken" message
  (a UX trade-off — full prevention needs an email-confirmation-gated signup
  flow, which felt like overkill for a personal app).
- The in-memory rate limiter resets on restart and doesn't share state across
  multiple server processes — fine for one local instance, not for a
  horizontally-scaled deployment.

## Weight tuning on real data

`engine/metrics.py`'s `WEIGHTS` start hand-picked, but don't have to stay
that way. `weight_tuner.py` regresses one real season's per-position
metrics against the *same players'* real fantasy points/game the
**following** season — "did this metric actually predict next year's
production," not just describe this year's box score after the fact
(regressing a rate stat against the same season's total it's partly
built from would be closer to circular reasoning than genuine
prediction). It reaches back several real historical seasons on its own,
independent of the live app's current season.

```bash
python weight_tuner.py              # dry run — prints learned vs current weights
python weight_tuner.py --write      # saves data_cache/learned_weights.json
```

`engine/metrics.py` picks up `learned_weights.json` automatically on
import — restart the server after `--write` for it to take effect. It's
a **partial** override: any position or metric the tuner didn't touch
keeps its hand-picked default, so it's safe to run for only the
positions/metrics you trust the sample size for. Nothing is applied
until you explicitly run it with `--write` — a fresh checkout scores
with the hand-picked defaults exactly as before.

## Development — type checking

[Pyright](https://microsoft.github.io/pyright/) is set up for static type
checking, both as an editor LSP and from the command line.

```bash
pip install -r requirements-dev.txt   # installs requirements.txt + pyright
pyright .                              # or just `pyright` — picks up pyrightconfig.json
```

`pyrightconfig.json` points it at `.venv` so it resolves the real installed
packages (FastAPI, pandas, etc.) instead of guessing. In VS Code, installing
the recommended **Pylance** extension (prompted automatically via
`.vscode/extensions.json` when you open the folder — it bundles Pyright as
its language server) gets you the same checking live as you type, using the
interpreter/settings already configured in `.vscode/settings.json`.

## Legacy prototype scripts

`valuation_engine.py`, `advanced_metrics.py`, `matchup.py`, and
`make_board_html.py` are the original single-file prototypes this app grew
out of (QB/RB only, terminal output, one blanket matchup number instead of
`engine/defense.py`'s multi-stat model). They still run standalone but are
fully superseded by the `engine/` package, which the web app actually uses.
`weight_tuner.py` used to be one of these — it's since been rewritten to
run for real against the `engine/` package and real multi-season history
(see above), not a superseded prototype anymore.

## Roadmap

**Done, not just planned:** live Sleeper snake-draft board, trade finder,
multi-week My Team schedule browsing, multi-team account support, "Continue
with Google" sign-in, the full sidebar/design overhaul, snap share +
injury status availability signals (`engine/board.py`'s `injury_status` /
`snap_pct` / `redzone_touches`, surfaced as chips + an injury flag on
Start/Sit), floor/median/ceiling range-of-outcomes on Start/Sit (each
player's own real 25th/75th-percentile game log this season, shown as a
range bar with the PROJ number marked inside it — see `build_board`'s
`floor`/`ceiling` columns and `startSitCardHtml` in `static/app.js`),
weight tuning from real multi-season history (see above), defense-side
Next Gen Stats in the matchup engine (`engine/defense.py`'s
`build_ngs_defense_profile` — see the table above), real live in-game
scores (`engine/live_scores.py`, ESPN's public scoreboard feed), an
AI-written per-player news summary grounded in real matched headlines
(`engine/news.py`'s `ai_summary_for_player`, behind `ANTHROPIC_API_KEY`),
DEF/ST and Kicker as fully scored positions with their own models
(`engine/defense_scoring.py`, `engine/kicker_scoring.py`), a role-baseline
fallback projection for stat-less skill players off their own team's
real depth-chart-rank production (`engine/role_baseline.py`), **real ESPN
league sync** (`engine/espn.py` — public leagues work signed out, private
leagues via encrypted `espn_s2`/`SWID`; wired into the same connect-team
flow as Sleeper, `POST /api/teams/lookup` with `platform: "espn"`),
weekly-refresh automation (`engine/refresh_scheduler.py` — an in-process
background task, no separate cron job, that force-refreshes the board on
a timer so it's never more than `REFRESH_INTERVAL_HOURS` stale and a
newly published season gets picked up without a restart; default 24h,
see `.env.example`), and **ESPN wired into the decision tools** — My
Team, Waivers, Trade (opponent switcher + roster browser), and League
News all sync a connected ESPN team exactly like a Sleeper one now
(`tools.my_team_espn`/`league_team_list_espn`/`roster_player_list_espn`/
`league_all_player_names_espn` in `engine/tools.py`, dispatched by
`connected_teams.platform` in `server.py`) — with one disclosed gap: DEF/K
score with this app's standard defaults rather than an ESPN league's
actual custom DEF/K rules, since translating ESPN's separate stat-id
scoring for those two positions isn't built. **Caveat carried over from
`engine/espn.py`'s own docstring: this has not yet been exercised against
a real live ESPN league** (no test league was available while building
it) — the shapes come from reading the `espn-api` package's source, not
a verified response; treat the first real connection attempt as the
actual test. What's left:

1. **Player Prop Evaluator** — approved (needs a paid odds-data API, e.g.
   The Odds API — you'd sign up and drop the key in `.env`, same pattern as
   Gmail). Not started yet. This is explicitly a sports-betting feature, kept
   separate from the fantasy-value engine, with "not gambling advice" framing
   throughout once built.
2. **Yahoo Fantasy league sync** — real, current OAuth2 API confirmed to
   exist; needs you to register a free app in Yahoo's developer portal and
   hand over a client ID/secret (like the Gmail setup). Not started.
3. **ESPN Trade Finder auto-suggest** — the one decision tool still
   Sleeper-only (needs every other roster's positional needs scanned the
   way `tools.trade_finder` does, which ESPN's league object exposes
   differently); Trade's manual roster browser already works for ESPN in
   the meantime, and `/api/trade-finder` returns a clear "not built yet"
   error for an ESPN-active team rather than a confusing Sleeper-side one.
4. **CBS Sports sync** — deprioritized. A real API exists but is deprecated
   and gated behind already having a CBS league — not a foundation worth
   building on now.
5. **Underdog Fantasy sync** — declined. No public API exists; the only way
   in is scraping their private endpoints, which violates their ToS.
6. **Rookie rankings** — no real prior-season stats to score a rookie on by
   definition; needs a dedicated model (draft capital, college production)
   instead of reusing the veteran SCORE pipeline. Discussed, not yet built.
7. **Live draft support beyond standard snake** — Dynasty/Auction/Keeper/
   Superflex/Best Ball each need a genuinely different ranking model, not
   just a relabeled snake board; deliberately scoped out of the v1 draft tool.
8. **"Continue with Apple"** — built the same way as Google (`engine/oauth.py`
   is provider-agnostic), just not activated: needs a paid Apple Developer
   Program account ($99/yr), a Services ID, and an ES256 signing key. Set
   `APPLE_CLIENT_ID`/`APPLE_TEAM_ID`/`APPLE_KEY_ID`/`APPLE_PRIVATE_KEY` once
   you have them and it works the same way Google does.

## Honest status

This is a real, working local app — not a mockup. Every piece described above
was tested end-to-end against live data: real Sleeper league sync (including
switching between two connected teams), real RSS news, real signup/login/
password-reset, real matchup math, real rate limiting (verified a login
actually gets 429'd after 10 attempts), real trending-add data from Sleeper.

**On "gather all 2025 NFL data"**: this note originally said the season
resolver was stuck on 2024 because nflverse hadn't published 2025 yet —
that diagnosis turned out to be wrong in a specific, now-fixed way. See
"Data freshness" above: nflverse *had* published 2025, under a renamed
release tag `nfl_data_py` doesn't know about yet; `engine/data.py` now
fetches that tag directly, and the season resolver correctly serves
**2025**. Live NFL *news* (the News tab) was never affected by any of
this — that's pulled fresh from ESPN/CBS RSS regardless of which stats
season is active.
