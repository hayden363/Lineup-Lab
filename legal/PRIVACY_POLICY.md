# Privacy Policy — Lineup Lab

Last updated: 2026-10-18 · Effective date: 2026-10-18

## What we collect, and why

| Data | Why we have it | How it's stored |
|---|---|---|
| Username, email, password | Your account | Password is bcrypt-hashed — we never see or store it in plain text, and can't recover it for you, only reset it |
| Session token | Keeps you signed in | Random token in an `httponly` cookie; the token itself, not your password, is what's stored server-side |
| Sleeper league ID(s) you connect | Sync your real roster/matchups | Plain — this is public information on Sleeper's own platform, not a secret |
| ESPN `espn_s2` / `SWID` cookies, if you connect an ESPN league | Read your ESPN league on your behalf (see Terms of Service, Section 5) | Encrypted at rest; never sent back to your browser or shown to anyone after you save it, including you — only "connected: yes/no" is ever displayed |
| Your league scoring preference, connected-team selection | Personalizes SCORE/PROJ to your actual league | Plain, tied to your account |
| Player news article text (headlines/snippets) you view | Sent to Anthropic's API to generate the optional AI summary on a player's page, only when you view that page | Not stored by Lineup Lab beyond a short-lived cache to avoid re-summarizing the same headlines repeatedly; see Anthropic's own privacy policy for how they handle a request once sent |

## What we don't do

- No ad trackers, no third-party analytics pixels, no selling or renting
  your data to anyone.
- No plaintext logging of passwords, session tokens, or ESPN
  credentials — verified directly in the codebase, not just asserted
  here; see the Security section of the project README.
- We don't post, message, or take any action on your behalf on Sleeper,
  ESPN, or anywhere else — every third-party integration is read-only.

## Third parties this app talks to, and why

- **Sleeper** — league/roster data, public API, no login required.
- **ESPN** — only if you explicitly connect an ESPN league; see Terms of
  Service Section 5 for the full disclosure.
- **nflverse / GitHub** — public statistical data.
- **ESPN/CBS RSS** — public news headlines.
- **Google** — only if you use "Continue with Google" to sign in; we
  receive your name/email/a stable ID from Google, nothing else.
- **Gmail (Google)** — sends your account-verification and password-reset
  emails from lineuplabfootball@gmail.com. Your email address and the
  message pass through Google's mail servers to reach you.
- **Render and Supabase** — host the app and its database (accounts,
  settings, connected leagues).
- **Anthropic (Claude API)** — only the specific news headlines already
  matched to a player you're viewing, only when you view that player,
  solely to generate the optional written summary.

## Your choices

- **Delete your account**: Settings → Delete account (in the website and
  the iPhone app). This permanently deletes your account row and, with it,
  everything tied to it: sessions, settings, connected leagues and
  stored ESPN credentials, prediction history, and verification/reset
  tokens. It happens immediately and can't be undone. Ordinary server
  logs (which don't contain your password or tokens) age out on the
  hosting provider's normal schedule.
- **Disconnect a Sleeper or ESPN team**: from Settings, at any time —
  removes the stored league/credential association.
- **AI summaries**: they're generated only when you open a player's page,
  from public news headlines — nothing about you or your account is sent.
  If you'd rather not use them, simply don't open that section; there's no
  account-level toggle yet.

## Children's privacy

Lineup Lab is not directed at children under 13, and you must be at least
13 to create an account. We don't knowingly collect personal information
from anyone under 13; if you believe a child has given us any, email us
and we'll delete it.

## Changes to this policy

If we change this policy in a material way, we'll update the date above and,
for significant changes, tell you in the app or by email.

## Contact

Questions, access or deletion requests: **lineuplabfootball@gmail.com**
