# Terms of Service — Lineup Lab

**Status: DRAFT.** This was written to accurately describe what the
application actually does, as a real starting point for a real ToS —
it has not been reviewed by a lawyer and should be before it governs any
real user's account, especially once the app accepts signups beyond
personal/household use. Placeholders below are marked `[ ]`.

Last updated: [date] · Effective date: [date] · Governing law: [state/country]

## 1. What Lineup Lab is

Lineup Lab is a fantasy football decision-support tool. It computes
player valuations, matchup projections, and lineup recommendations from
free, public NFL statistical data (see Section 4), and lets you connect
your own fantasy leagues (currently Sleeper and, optionally, ESPN) so
those numbers reflect your actual roster.

Lineup Lab is **not affiliated with, endorsed by, or sponsored by** the
NFL, any NFL team, Sleeper, ESPN, Yahoo, PFF (Pro Football Focus), or
WalterFootball. All team names, logos, and player likenesses belong to
their respective owners and are used only to identify the real players
and teams the statistics describe.

## 2. Not gambling or financial advice

Nothing in Lineup Lab — SCORE, PROJ, FORM, trade grades, start/sit
recommendations, or any AI-written summary — is betting advice, gambling
advice, or financial advice. Any future feature involving betting odds
or props (see the public roadmap) will carry this same disclaimer
throughout, not just here.

## 3. Accounts

- You must provide accurate information at signup and are responsible
  for keeping your login credentials confidential.
- You must be old enough to use fantasy sports products under the laws
  of your jurisdiction. `[ ]` — pick and state a minimum age.
- You may delete your account at any time from Settings; see the
  Privacy Policy for what deletion actually does to your data.
- We may suspend or terminate an account for abuse of the service
  (e.g., attempting to circumvent rate limits, automated scraping of
  Lineup Lab itself, or credential stuffing against the login endpoint).

## 4. Data sources and their own terms

Lineup Lab pulls from several outside sources. Your use of Lineup Lab
does not grant you any rights to those sources beyond what they
themselves grant:

- **nflverse** (play-by-play, weekly stats, Next Gen Stats, schedules) —
  licensed [CC-BY-4.0](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md),
  free for reuse including commercial use, with attribution — which
  Lineup Lab displays on every page.
- **Sleeper** — read-only access to public league data via Sleeper's own
  API, used only to sync leagues you are actually a member of.
- **ESPN Fantasy** (optional) — see Section 5, a separate and more
  explicit disclosure given the different nature of this integration.
- **ESPN / CBS Sports news** — real headlines via public RSS syndication,
  linked back to the original source.
- **Anthropic (Claude API)** — powers the optional AI-written player news
  summary; governed by Anthropic's own usage policies.

## 5. ESPN league sync — read this before connecting an ESPN league

ESPN does not offer or support a public, documented API for third-party
fantasy applications. Lineup Lab's ESPN integration works by using
**your own** ESPN session credentials (`espn_s2` and `SWID`, obtained
from your own logged-in ESPN session) to read data from a league you are
already a member of — the same data your own browser can already see.
This is **not an official ESPN integration, is not endorsed by ESPN, and
may stop working at any time** without notice if ESPN changes their
systems. By connecting an ESPN league you acknowledge:

- This feature is provided on a best-effort basis and may break, be
  rate-limited, or be removed without notice.
- Your ESPN credentials are encrypted at rest and used only to fetch
  your own league's data on your behalf, never logged in plaintext, and
  never shown back to you or anyone else once saved.
- You can disconnect an ESPN team at any time from Settings, which
  deletes the stored credentials.
- Lineup Lab does not control ESPN's own terms of service, and your use
  of ESPN's platform remains governed by ESPN's own terms, separately
  from these.

## 6. Disclaimer of warranties

Lineup Lab is provided "as is." Player valuations and projections are
computed from real historical data using the methodology described in
the project's own documentation — they are estimates, not guarantees,
and past statistical performance does not predict future results.
`[ ]` — standard "AS IS, NO WARRANTIES OF ANY KIND" boilerplate belongs
here in the final version; keep the plain-English explanation above it.

## 7. Limitation of liability

`[ ]` — standard limitation-of-liability clause, scoped by counsel to
your actual jurisdiction and business structure.

## 8. Changes to these terms

`[ ]` — how you'll notify users of material changes (e.g., email, in-app
notice) and what happens to a user who doesn't accept them.

## 9. Contact

`[ ]` — a real support/legal contact address once one exists.
