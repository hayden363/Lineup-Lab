# The Daily Drive — build spec (v1)

A Krillion-style daily football trivia game inside Lineup Lab. Source idea: `docs/krillion-source-spec.pdf`
(its answer banks were written from memory and contain errors; do NOT copy facts from it).

Owner decisions (2026-11-16): name **The Daily Drive**; lives **inside Lineup Lab at `/play`**, playable with
no account; prompts are a **mix** of real-data fantasy prompts and history prompts; v1 scores are
**local + share card** (no leaderboard, no new DB table).

## Core rules
- 7 prompts per daily game, identical for everyone, new game at midnight **US Eastern** (America/New_York).
- Per prompt: 3-second category preview, then 25 seconds. One typed answer, no multiple choice.
- Rejected answer: show why ("not in the answer bank" / "already used" ), retry while time remains.
  Timeout with no accepted answer = 0 yards ("Sacked").
- Accepted answer scores its rarity tier. Points = yards. Max 700 yards.

| Tier | Name | Yards | Share emoji |
|---|---|---|---|
| 6 | Hall of Famer | 100 | 🏆 |
| 5 | All-Pro | 85 | 🟣 |
| 4 | Pro Bowler | 60 | 🔵 |
| 3 | Starter | 30 | 🟢 |
| 2 | Rotation | 15 | 🟡 |
| 1 | Benchwarmer | 10 | ⚪ |
| — | Sacked | 0 | 🟥 |

- 100-yard answers get a short "TOUCHDOWN" celebration. A field bar (0 to 700 yards) fills as prompts resolve.
- After the game: per-prompt reveal of the top answers in each tier (spoilers only after you finish), total yards,
  streak, and a spoiler-free share card, e.g.
  `The Daily Drive · Nov 16 · 455 yds` / `🏆🟢🟥🔵🟡🟣🟢` / `lineup-lab-awdv.onrender.com/play`. Copy button.
- One daily attempt (played-today gate). Streak counter. Unfinished game saved in localStorage and expires
  ~12 hours after start while the timer keeps its real deadline (no pausing by reloading).
- Practice mode: unlimited random prompts from past days' generated prompts, not counted for streaks.

## Content: every answer must come from real data
No hand-typed facts. Every prompt's answer set is computed from nflverse data the app already downloads
(`engine/data.py`, `data_cache/`), so it is correct by construction.

**Fantasy prompts (4 per day)** from completed weeks of the current season (`bundle["wk"]` weekly stats,
scored with the app's default PPR via `engine/scoring.py`). Templates, e.g.
- "Name a RB who scored a rushing TD in Week N"
- "Name a WR with 100+ receiving yards in Week N"
- "Name a QB who threw 2+ TD passes in Week N"
- "Name a player who scored 20+ PPR points in Week N"
- "Name a TE who caught a TD this season" (season-to-date sets are fine too)
A template/week combo is used only if its answer set has at least 12 answers.

**History prompts (3 per day)** generated from nflverse historical datasets only (seasonal player stats
1999+, draft picks, schedules), e.g. "Name a player with 1,500+ receiving yards in a season since 1999",
"Name a first-overall pick since 2000", "Name a RB with a 1,800+ rushing-yard season since 1999".
If a dataset isn't available through `engine/data.py`, add a loader in the same cached style
(`data._disk_cached`, nflverse-data GitHub releases). No prompt whose answers can't be computed.

**Rarity (no editors).** Within each prompt's answer set, rank answers by popularity and cut by percentile:
top 20% Benchwarmer, next 20% Rotation, next 20% Starter, next 15% Pro Bowler, next 15% All-Pro, last 10%
Hall of Famer. Popularity:
- fantasy prompts: FantasyPros consensus rank already loaded by `engine/consensus.py` (`overall_lookup`;
  a player the experts don't list counts as least popular), tie-break by season fantasy points;
- history prompts: career PPR fantasy points (more points = more famous).
Store the tier with each answer so later we can switch to "% of players who gave this answer".

**Daily puzzle generation.** Deterministic from the date (seeded RNG) so every player gets the same game
and it can be regenerated: pick 4 fantasy + 3 history prompts, no repeated template on the same day, avoid
reusing an identical prompt within 30 days. Cache each day's puzzle on disk (`data_cache/daily_drive/`).

## Answer checking (server side, so the bank isn't shipped to the browser)
- `GET /api/play/daily?date=YYYY-MM-DD` → date, 7 prompts (id, text, category label, answer count). No answers.
- `POST /api/play/check` `{date, prompt_id, answer, used:[answer ids]}` → `{ok, tier, yards, canonical, answer_id}`
  or `{ok:false, reason, suggestions:[...]}`. Rate limited with the existing `rate_limit` dependency.
- `GET /api/play/reveal?date=…&prompt_id=…` → full tiered answer list; the page calls it only after the game ends.
- `GET /api/play/practice` → one random past prompt.
- Matching: lowercase, strip punctuation and suffixes (Jr, Sr, II, III), collapse spaces; accept full name,
  "F. Last", and last name alone when unique within that prompt's answer set; ambiguous last name →
  `suggestions` ("Did you mean Josh Allen?"). Typos: Levenshtein ≤ 2 (≤1 for names under 6 letters) may
  auto-accept only Benchwarmer–Pro Bowler answers; All-Pro and Hall of Famer need an exact name/alias match
  (otherwise return the suggestion chip). Each answer accepted once per game.
- Future dates are refused; past dates are allowed (archive/practice).

## Page
- `static/play.html`, `static/play.js`, `static/play.css`; routes in `server.py` mirroring `/welcome`,
  `/landing.js`, `/landing.css`. App CSP: `script-src 'self'` — no CDNs, no inline scripts, vanilla JS.
- Uses the app's current look (navy surfaces, teal accent, system sans; tokens from the "Sleeper skin" block
  at the end of `static/style.css` — copy the needed tokens into play.css, don't import style.css).
- Mobile first: 375px wide, input `font-size:16px` (no iOS zoom), input keeps focus between retries, big
  timer ring, works one-handed. Desktop centered column.
- Motion: timer ring, yards count-up, field bar fill, tier badge pop, touchdown burst; all off under
  `prefers-reduced-motion`.
- localStorage wrapped in try/catch everywhere; the game still works if storage is blocked.
- Footer link "Built by Lineup Lab: real NFL data for your fantasy team" → `/`.
- Add a small "Play The Daily Drive" link on the landing page (`static/landing.js` nav or footer) and in the
  app sidebar only if trivial; otherwise leave for review.

## Tests (unittest, existing style)
Puzzle determinism per date; every prompt has ≥12 answers and all six tiers present when the set is large
enough; answer sets match the source data; matching rules (full/last/initial, ambiguity, typo limits by
tier, duplicates); endpoints never leak answers before reveal; future date refused; page served with CSP-safe
script tags (no inline JS).

## Out of scope for v1
Leaderboards, accounts, answer-popularity tiers, themed packs.
