# Privacy Policy — Lineup Lab

**Status: DRAFT.** Written to accurately describe what the application
actually stores and sends today, as a real starting point — not
reviewed by a lawyer, and not sufficient on its own for GDPR/CCPA
compliance if you have EU or California users; that needs real counsel
and, likely, additional user-rights tooling this draft doesn't cover
(e.g., a formal data export/deletion request flow beyond account
deletion). Placeholders below are marked `[ ]`.

Last updated: [date] · Effective date: [date]

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
- **Gmail SMTP** — sends your account-verification and password-reset
  emails. `[ ]` — once this is a real multi-user product rather than a
  personal Gmail relay, this should move to a dedicated transactional
  email provider (SendGrid, Postmark, SES, etc.) with its own DPA, not
  a personal Gmail account.
- **Anthropic (Claude API)** — only the specific news headlines already
  matched to a player you're viewing, only when you view that player,
  solely to generate the optional written summary.

## Your choices

- **Delete your account**: from Settings. `[ ]` — specify exactly what
  this does today (does it hard-delete the row, or just deactivate?) and
  make the answer match reality before this goes live for real users —
  don't promise deletion the code doesn't actually perform.
- **Disconnect a Sleeper or ESPN team**: from Settings, at any time —
  removes the stored league/credential association.
- **Turn off AI summaries**: don't set an `ANTHROPIC_API_KEY` (self-hosted
  today) or, once hosted, `[ ]` add an account-level opt-out toggle.

## Children's privacy

`[ ]` — state a minimum age and, if you might ever have users under 13,
this needs real COPPA-specific review — don't ship without it.

## Changes to this policy

`[ ]` — same as the Terms of Service: define how you'll notify users of
material changes.

## Contact

`[ ]` — a real contact address for privacy questions and data requests.
