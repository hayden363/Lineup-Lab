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
| Base metrics + SCORE | [engine/metrics.py](engine/metrics.py) | Per-position (QB/RB/WR/TE) efficiency + volume metrics → a 0–100 weighted SCORE. Filters out small-sample noise (mop-up duty, one-target games). |
| Advanced metrics | [engine/advanced.py](engine/advanced.py) | Real Next Gen Stats (separation, cushion, CPOE, time to throw, rush yards over expected) + play-by-play EPA/explosive-play rate — your PFF-grade proxy, for free. |
| Defensive matchup engine | [engine/defense.py](engine/defense.py) | A real, **multi-stat** defensive profile per team (run defense, pass defense, pressure — ~15 categories from play-by-play), each mapped to the specific SCORE metric it actually predicts. A run-stuffing defense hurts a between-the-tackles runner more than a receiving back; a blanket "points allowed" number can't tell you that. |
| Custom scoring | [engine/scoring.py](engine/scoring.py) | Recomputes fantasy points from raw counting stats using YOUR point values (PPR/Half-PPR/Standard presets, or fully custom) instead of trusting a fixed column. SCORE stays scoring-agnostic on purpose; FPTS/FORM/PROJ/trade value all respect it. |
| Accounts | [engine/db.py](engine/db.py) | Real local accounts — SQLite, bcrypt-hashed passwords, session cookies, email verification, password reset. |
| OAuth sign-in | [engine/oauth.py](engine/oauth.py) | "Continue with Google" — real server-side OAuth2, ID token verified against Google's own public keys (not just decoded and trusted). Signing in with the same email as an existing password account links them. Apple Sign In is built the same way but inactive until you have a paid Apple Developer account for it — see that file. |
| At-rest encryption | [engine/crypto.py](engine/crypto.py) | Fernet symmetric encryption for ESPN cookies — the one genuinely sensitive thing this app stores. |
| Outbound mail | [engine/mail.py](engine/mail.py) | Verification + password-reset emails via Gmail SMTP (an App Password you configure — see Security below). |
| League sync | [engine/sleeper.py](engine/sleeper.py) | Real, public, read-only Sleeper league sync (no login) — scoring settings, rosters, avatars, real head-to-head weekly matchups, and platform-wide trending add/drop counts, via a free nflverse ID crosswalk. |
| News | [engine/news.py](engine/news.py) | Real ESPN/CBS NFL RSS headlines, filtered to your roster + this week's opponent's roster (full-name matching only — see the code comment on why). |
| Decision tools | [engine/tools.py](engine/tools.py) | My Team (roster + real opponent for ANY week of the schedule, not just the live one, + full league matchup slate, all projected), start/sit, trade analyzer, **trade finder** (scans the league for realistic trades that fill your real positional needs), **live draft board** (Sleeper snake drafts — on-the-clock, need-adjusted best-available, real pick-order math), and waiver wire (auto-synced, trending badges) — all built on the same scored board. |
| Board builder | [engine/board.py](engine/board.py) | Combines all of the above into a ranked, matchup-projected big board, a player search, or a single player's full detail record. |
| API | [server.py](server.py) | FastAPI JSON API (see below) that also serves the frontend, plus the security middleware/rate-limiting described below. |
| Frontend | [static/](static/) | Vanilla JS/HTML/CSS (no build step) — a collapsible left sidebar nav (icon rail ↔ full, mobile drawer) across Big Board, My Team (with a week selector — browse any week's real matchup), Draft, Start/Sit, Trade, Waivers, News, and Settings. Full design system: soft glass cards, layered shadows, micro-interactions, entrance animations, skeleton loaders — all in one installable PWA. |

## API

Every read endpoint accepts optional scoring overrides: `?scoring=half_ppr` /
`?scoring=standard` (default: signed-in account's saved preference, else full
PPR), or individual point values (`&reception=0.5&pass_td=6&...`).

- `GET /api/meta` — season, positions, teams, weight config, scoring presets
- `GET /api/board?pos=WR&opp=DAL&min_games=2` — ranked board, optionally matchup-projected (real multi-stat defensive read)
- `GET /api/player/{player_id}?opp=DAL` — full metric breakdown + weekly log + matchup factor
- `GET /api/search?q=...` — player search across all positions
- `POST /api/startsit`, `POST /api/trade`, `GET /api/waivers` — the three decision tools (waivers auto-syncs to your active league, with real Sleeper trending-add counts)
- `GET /api/myteam?week=N` — your synced roster + that week's real opponent (any week of the schedule, defaults to the live one) + every other real matchup in the league, all projected (requires sign-in + a connected team)
- `GET /api/trade-finder?target_roster_id=N` — realistic trade suggestions that fill your real needs
- `GET /api/myteam/drafts`, `GET /api/draft/{draft_id}?roster_id=N` — find and load a live/completed Sleeper snake draft board
- `GET /api/news` — real NFL headlines, personalized when signed in with a connected team
- `POST /api/auth/signup` `/login` `/logout` `/change-password` `/forgot-password` `/reset-password`, `GET /api/auth/me` — accounts
- `GET /api/auth/google/start`, `GET /api/auth/google/callback` — "Continue with Google" (only appears in the UI once `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are set — see `.env.example`)
- `GET`/`POST /api/settings` — ESPN fields, scoring preference (per account)
- `GET /api/teams`, `POST /api/teams`, `POST /api/teams/{id}/activate`, `DELETE /api/teams/{id}` — connect/switch/remove multiple Sleeper teams
- `POST /api/teams/lookup` — paste a Sleeper league URL or bare ID, get back its teams to pick from
- `GET /api/sleeper/{league_id}` — sync a public Sleeper league's scoring + rosters + avatars
- `POST /api/refresh` — force-refetch all data, bypassing the disk cache

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

## Legacy prototype scripts

`valuation_engine.py`, `advanced_metrics.py`, `matchup.py`, `weight_tuner.py`,
and `make_board_html.py` are the original single-file prototypes this app grew
out of (QB/RB only, terminal output, one blanket matchup number instead of
`engine/defense.py`'s multi-stat model). They still run standalone but are
fully superseded by the `engine/` package, which the web app actually uses.
`weight_tuner.py`'s regression approach is the natural next step for tuning
`engine/metrics.py`'s `WEIGHTS` on real historical results instead of
hand-picked numbers.

## Roadmap

**Done, not just planned:** live Sleeper snake-draft board, trade finder,
multi-week My Team schedule browsing, multi-team account support, "Continue
with Google" sign-in, the full sidebar/design overhaul. What's left:

1. **Weight tuning on real data** — feed several seasons of `engine/board.py`
   output into a regression (like `weight_tuner.py`, extended to WR/TE) to
   replace hand-picked weights with learned ones.
2. **Next Gen Stats in the matchup engine** — `engine/defense.py` is
   deliberately built from play-by-play (run D, pass D, pressure) first;
   folding in defense-side NGS (e.g. coverage separation allowed) is the
   planned next layer, not skipped by accident.
3. **Snap share + injury status** — `nfl_data_py.import_snap_counts` /
   `import_injuries` are free too; wire them in as availability signals.
4. **Player Prop Evaluator** — approved (needs a paid odds-data API, e.g.
   The Odds API — you'd sign up and drop the key in `.env`, same pattern as
   Gmail). Not started yet. This is explicitly a sports-betting feature, kept
   separate from the fantasy-value engine, with "not gambling advice" framing
   throughout once built.
5. **Yahoo Fantasy league sync** — real, current OAuth2 API confirmed to
   exist; needs you to register a free app in Yahoo's developer portal and
   hand over a client ID/secret (like the Gmail setup). Not started.
6. **ESPN league sync** — settings fields exist and are encrypted at rest;
   the live roster fetch (ESPN's fantasy API) is the remaining work.
7. **CBS Sports sync** — deprioritized. A real API exists but is deprecated
   and gated behind already having a CBS league — not a foundation worth
   building on now.
8. **Underdog Fantasy sync** — declined. No public API exists; the only way
   in is scraping their private endpoints, which violates their ToS.
9. **Rookie rankings + start/sit range-of-outcomes** (floor/median/ceiling
   instead of one number) — discussed, not yet built.
10. **Live draft support beyond standard snake** — Dynasty/Auction/Keeper/
    Superflex/Best Ball each need a genuinely different ranking model, not
    just a relabeled snake board; deliberately scoped out of the v1 draft tool.
11. **Weekly-refresh automation** — a scheduled task that calls `/api/refresh`
    during the season so the board updates itself.
12. **"Continue with Apple"** — built the same way as Google (`engine/oauth.py`
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

**On "gather all 2025 NFL data"**: the season resolver currently serves
**2024** — as of this build, nflverse (the free, legal source everything here
is built on) hasn't tagged a 2025 season release yet, checked directly
against their GitHub releases, not assumed. There is no real 2025 season
stat data to pull from anywhere free and legal right now, regardless of the
calendar date — the app won't fabricate or approximate one. It'll switch to
2025 automatically the moment nflverse publishes it, no code changes needed.
This does mean "this week's real matchup" in My Team can look mismatched
against a live 2026 Sleeper league until then; the roster sync and points
math are still real, just running on the most recent season with real stats
behind it. Live NFL *news* (the News tab) is unaffected — that's pulled
fresh from ESPN/CBS RSS regardless of which stats season is active.
