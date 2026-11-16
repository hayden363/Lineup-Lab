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
| 6 | Highlight Reel TD | 100 | 🏆 |
| 5 | Bomb | 85 | 🟣 |
| 4 | Chunk Play | 60 | 🔵 |
| 3 | Chain Mover | 30 | 🟢 |
| 2 | Quick Slant | 15 | 🟡 |
| 1 | Checkdown | 10 | ⚪ |
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

**Season prompts (all 7 per day; owner decision 2026-11-16: "no more random week, just stats from this season,
updated weekly").** Every prompt is about the CURRENT season's regular-season stats through the latest fully
completed week (`engine/daily_drive.eligible_weeks`: every game that week has a score and was played before the
date). Source: nflverse weekly data (`data.load_weekly`, REG only, PPR column `fantasy_points_ppr`). No "in Week N"
prompts; the category label reads "This season · through Week 10". History and draft prompts still exist in code
but are off behind `HISTORY_ENABLED = False` (flip it to get back 4 fantasy + 3 history).

Template families (20, `FANTASY_TEMPLATES`), all phrased "... this season":
- season totals: WR / TE / RB receiving yards, RB rushing yards, QB passing yards, QB passing TDs, WR receptions,
  RB/WR/TE total TDs (rush + rec), PPR points, RB rushing TDs, WR/TE receiving TDs;
- single-game feats: WR receiving-yard game, RB rushing-yard game, QB passing-yard game, PPR-point game,
  rushing/receiving TDs in one game, TE receiving-yard game (answer = anyone whose best game cleared the line);
- mixed: RB catches, WR receiving TDs, QB rushing yards.

**Dynamic thresholds.** Each template owns a ladder of round numbers (yards 300/400/500/600/700/800/1000/1200/1500,
TDs 3/4/5/6/8/10..., PPR 50/75/100/125/150/200..., etc.). `pick_threshold` walks the ladder from the top and takes the
highest rung that still leaves at least `TARGET_MIN` = 15 answers (the band is 15-50; `MIN_ANSWERS` = 12 is the hard
floor and the fallback). The chosen number is printed in the prompt text ("Name a WR with 500+ receiving yards this
season"), so difficulty tracks the season as totals grow.

**Weekly refresh and ids.** A day's puzzle is built from data through the latest completed week at generation time, so
a new week flows in with no manual step. Prompt ids carry the season, through-week and threshold
(`f:wr_rec_yds:2026:w9:t500`): a new week or a new rung means new ids. Cached puzzle files carry `v` (`PUZZLE_VERSION`);
an older shape is regenerated. Tokens (`engine/daily_drive_scores.py`) are looked up in the day's puzzle by prompt id and
answer id, so a game started after a regeneration scores normally (a game straddling a regeneration fails verification
and is refused rather than mis-scored).

**Variety.** Deterministic per date (seeded by the date). 7 distinct templates a day, near-duplicates share a `group`
(WR receiving TDs vs WR/TE receiving TDs; RB receiving yards vs RB catches) and never share a day, and none of
yesterday's templates are used again unless the pool runs dry (replaces the old 30-day id rule).

**Answer extras (for the visuals).** Each bank answer stores `team` (`recent_team`, latest week), `position`,
`headshot` (weekly `headshot_url`, else null), `stat` (the qualifying number, e.g. 742 or 156) and `stat_label` ("rec yds",
"pass TD", "PPR pts", "rush yds in a game", ...). `POST /api/play/check` returns them with an accepted answer;
`GET /api/play/reveal` returns them per answer in each tier's `details` list (parallel to `answers`). Nothing is sent
for unrevealed answers.

**Rarity (no editors).** Within each prompt's answer set, rank answers by popularity and cut by percentile:
top 20% Checkdown, next 20% Quick Slant, next 20% Chain Mover, next 15% Chunk Play, next 15% Bomb, last 10%
Highlight Reel TD. Popularity:
- fantasy (season) prompts: FantasyPros consensus rank already loaded by `engine/consensus.py` (`overall_lookup`;
  a player the experts don't list counts as least popular), tie-break by season PPR points;
- history prompts (off): career PPR fantasy points (more points = more famous).
Store the tier with each answer so later we can switch to "% of players who gave this answer".

**Daily puzzle generation.** Deterministic from the date (seeded RNG) so every player gets the same game
and it can be regenerated: pick 7 season prompts, no repeated template (or near-duplicate group) on the same day and none of
yesterday's templates. Cache each day's puzzle on disk (`data_cache/daily_drive/`).

## Answer checking (server side, so the bank isn't shipped to the browser)
- `GET /api/play/daily?date=YYYY-MM-DD` → date, 7 prompts (id, text, category label, answer count). No answers.
- `POST /api/play/check` `{date, prompt_id, answer, used:[answer ids]}` → `{ok, tier, yards, canonical, answer_id, token, team, position, headshot, stat, stat_label}`
  or `{ok:false, reason, suggestions:[...]}`. Rate limited with the existing `rate_limit` dependency.
- `GET /api/play/reveal?date=…&prompt_id=…` → full tiered answer list (names plus per-answer `details`); the page calls it only after the game ends.
- `GET /api/play/practice` → one random past prompt.
- Matching: lowercase, strip punctuation and suffixes (Jr, Sr, II, III), collapse spaces; accept full name,
  "F. Last", and last name alone when unique within that prompt's answer set; ambiguous last name →
  `suggestions` ("Did you mean Josh Allen?"). Typos: Levenshtein ≤ 2 (≤1 for names under 6 letters) may
  auto-accept only Checkdown–Chunk Play answers; Bomb and Highlight Reel TD need an exact name/alias match
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
