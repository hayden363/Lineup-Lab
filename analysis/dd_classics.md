# Daily Drive classics: curated NFL knowledge prompts

28 hand-built prompts in `engine/dd_classics/*.json` (loader: `engine/daily_drive_classics.py`). Not wired into the day mix.
Pre-2000 prompts: 4 of 28 (rule: at most ~10). Tiers are editorial: each bank is written most-popular-first and cut with the same percentile rule as the data pools (20/20/20/15/15/10), except the franchise bank where tiers are set by hand.

| # | Prompt | Answers | Tier-6 examples | Era |
|---|---|---|---|---|
| 1 | Name a kicker with 400 or more career field goals made (`career-fg-400`) | 15 | John Carney | all |
| 2 | Name a quarterback with 47,000 or more career passing yards (`career-passing-47k`) | 15 | Fran Tarkenton | all |
| 3 | Name a player with 13,000 or more career receiving yards (`career-receiving-13k`) | 21 | Andre Reed, Henry Ellard | all |
| 4 | Name a player with 10,000 or more career rushing yards (`career-rushing-10k`) | 32 | Ricky Watters, Thomas Jones, Ottis Anderson | all |
| 5 | Name a player with 100 or more official career sacks (`career-sacks-100`) | 46 | Greg Townsend, Trace Armstrong, Jim Jeffcoat, William Fuller | all |
| 6 | Name a current NFL stadium (`current-stadium`) | 30 | EverBank Stadium, Northwest Stadium, Paycor Stadium | all |
| 7 | Name a player drafted No. 1 overall in the NFL Draft since 2000 (`first-overall-pick-2000`) | 27 | Eric Fisher, Courtney Brown | 2000+ |
| 8 | Name a Pro Football Hall of Fame quarterback (`hof-quarterback`) | 34 | Benny Friedman, Jimmy Conzelman, Paddy Driscoll | pre2000 |
| 9 | Name a player who has won AP Defensive Player of the Year since the 2000 season (`nfl-dpoy-2000`) | 20 | Stephon Gilmore, Bob Sanders | 2000+ |
| 10 | Name a player who has won AP Defensive Rookie of the Year since the 2000 season (`nfl-droy-2000`) | 26 | Carson Schwesinger, Kendrell Bell | 2000+ |
| 11 | Name an NFL franchise (`nfl-franchise`) | 66 | Dayton Triangles, Akron Pros, Rock Island Independents, Hammond Pros | all |
| 12 | Name an NFL team mascot (`nfl-mascot`) | 33 | Boom, Taima, Brownie the Elf | all |
| 13 | Name a player who has won AP NFL MVP since the 2000 season (`nfl-mvp-2000`) | 16 | Steve McNair | 2000+ |
| 14 | Name a player who has won AP Offensive Player of the Year since the 2000 season (`nfl-opoy-2000`) | 22 | Jamal Lewis, Priest Holmes | 2000+ |
| 15 | Name a player who has won AP Offensive Rookie of the Year since the 2000 season (`nfl-oroy-2000`) | 26 | Anthony Thomas, Mike Anderson | 2000+ |
| 16 | Name a city that has hosted a Super Bowl since the 2000 season (`sb-city-2000`) | 16 | Jacksonville | 2000+ |
| 17 | Name a head coach who has won a Super Bowl since the 2000 season (`sb-coach-2000`) | 18 | Brian Billick | 2000+ |
| 18 | Name a head coach who won a Super Bowl before the 2000 season (`sb-coach-pre2000`) | 19 | Don McCafferty | pre2000 |
| 19 | Name a Super Bowl MVP since the 2000 season (`sb-mvp-2000`) | 19 | Dexter Jackson | 2000+ |
| 20 | Name a Super Bowl MVP from before the 2000 season (`sb-mvp-pre2000`) | 31 | Desmond Howard, Chuck Howley, Jake Scott | pre2000 |
| 21 | Name a stadium that has hosted a Super Bowl since the 2000 season (`sb-stadium-2000`) | 16 | EverBank Stadium | 2000+ |
| 22 | Name a quarterback who has started a Super Bowl since the 2000 season (`sb-starting-qb-2000`) | 30 | Rex Grossman, Brad Johnson, Trent Dilfer | 2000+ |
| 23 | Name a team that has played in a Super Bowl since the 2000 season (`sb-teams-2000`) | 20 | Arizona Cardinals, Las Vegas Raiders | 2000+ |
| 24 | Name a quarterback who has won a Super Bowl since the 2000 season (`sb-winning-qb-2000`) | 15 | Trent Dilfer | 2000+ |
| 25 | Name a quarterback who won a Super Bowl before the 2000 season (`sb-winning-qb-pre2000`) | 21 | Joe Theismann, Jeff Hostetler | pre2000 |
| 26 | Name a team that has won a Super Bowl (`sb-winning-teams`) | 20 | Tampa Bay Buccaneers, New York Jets | all |
| 27 | Name a team whose current home stadium opened in 2000 or later (`team-new-stadium-2000`) | 20 | Cincinnati Bengals, Buffalo Bills | 2000+ |
| 28 | Name a team that has made the No. 1 overall pick in the NFL Draft since 2000 (`team-no1-pick-2000`) | 18 | Miami Dolphins | 2000+ |

## Judgement calls

- **Franchise prompt (`nfl-franchise`)**: 32 current teams are tiers 1-4, eight per tier, most storied first (Cowboys, Patriots, Packers, Chiefs, Steelers, 49ers, Eagles, Bears = tier 1; Bengals, Falcons, Panthers, Cardinals, Titans, Jaguars, Texans, Commanders = tier 4). 34 defunct NFL franchises are tiers 5-6 (tier 5: Canton Bulldogs, Boston Yanks, Brooklyn Dodgers, Duluth Eskimos, Pottsville Maroons, Providence Steam Roller, Frankford Yellow Jackets). No "name a defunct franchise" prompt exists.
- **Relocated / renamed names are aliases of the current franchise, not separate answers** (Oakland Raiders, St. Louis Rams, Houston Oilers, Baltimore Colts, Decatur/Chicago Staleys, Portsmouth Spartans, Washington Redskins / Football Team, ...). Typing one scores the current team once. Reason: one franchise = one answer, no double-dipping.
- **Defunct teams that collide with a current team's last word were left out** so a bare "Panthers", "Lions", "Cowboys", "Buccaneers" stays unambiguous: Detroit Panthers, Brooklyn Lions, Kansas City Cowboys, Los Angeles Buccaneers, and the 1950 Baltimore Colts / 1952 Dallas Texans / 1921 New York Giants. "Dallas Texans" is deliberately not an alias of the Chiefs for the same reason. Shared words among defunct teams (Maroons, Bulldogs, Pros) ask "which one?".
- **"Since the 2000 season"** means Super Bowl XXXV (Jan 2001) onward. XXXIV (Jan 2000, 1999 season) is on the pre-2000 side, so Kurt Warner / Dick Vermeil / Rams appear in the pre-2000 prompts, and Warner also in the since-2000 "started a Super Bowl" prompt (XXXVI, XLIII).
- **Super Bowl V**: Unitas is credited as the winning QB (starter, per Wikipedia and the Hall of Fame list). ESPN credits Earl Morrall; sources disagree, so Morrall is not an answer.
- **Stadium names**: banks accept the sponsor names a fan might use (Heinz Field, Reliant, FedExField, Cowboys Stadium, ...) as aliases. Houston's stadium is listed as NRG Stadium with "Reliant Stadium" as an alias because sources disagree on the 2026 name. The Bills' new Highmark Stadium (opened 2026) is used; old names are aliases.
- **Awards** are the AP awards (MVP, DPOY, OPOY, OROY, DROY) through the 2025 season, checked against AP News (Feb 2026) and Wikipedia/PFR/NFL.com. Co-winners (2003 MVP: Manning and McNair) are both answers.
- **Record-club prompts use thresholds chosen to stay stable**: nobody can drop out and active players near the line are avoided (47,000 passing yards excludes Wilson/Cousins, whose totals differ between sources; 400 field goals; 13,000 receiving yards; 100 official (1982+) sacks; 10,000 rushing yards). Answers whose numbers are in the `note` are rounded as "130+" where the exact figure moves with active players.
- **Hall of Fame QB**: pre-modern passers the Hall lists as QB with two sources (Baugh, Luckman, Herber, Friedman, Conzelman, Driscoll) are in; Dutch Clark and Ace Parker are on the Hall's own list but had only that one source, so they are out.
- **Mascots**: only names confirmed by two sources (Wikipedia list + sportmascots.com / whiteclouds). Teams with no official mascot (Packers, Giants, Jets, Chargers) have no entry.
- A "who has won X since 2000" bank may use the owner's `group` field to avoid two near-duplicates on one day: `sb-qb` (winning QBs + starting QBs), `sb-venue` (stadiums + cities), `no1` (No. 1 pick players + teams), `stadiums`, `records-*`.

## Alias change to the engine

`engine/daily_drive.check_answer` now honors an optional `aliases` list on any answer. An exact (normalized) alias counts as an exact answer, which means it is accepted at any tier (so tier-5/6 answers don't need the typo path); an alias shared by two answers asks "which one?"; aliases also take part in the typo check (tier 1-4 auto-accepts, tier 5-6 only suggests). Answers without `aliases` behave exactly as before (the whole of `tests.test_daily_drive` still passes).

## Verification

Every bank cites two or more sources (listed per prompt in the JSON `sources`, and the primary URL on each answer). Perplexity search (`perplexity_search`, the `ask` tool was credit-blocked) and Wikipedia fetches were used; Pro Football Reference pages were read through the search results (direct fetch returns 403). Primary pairs: Super Bowl lists = Wikipedia + CBS Sports/NFL Records/Pro Football Hall of Fame; awards = AP News (Feb 6, 2026) + Wikipedia/PFR/FootballDB/NFL.com; draft = Wikipedia + ESPN + DraftHistory; stats = PFR + Wikipedia/Hall of Fame/StatMuse; franchises = Pro Football Hall of Fame franchise histories + Wikipedia + jt-sw.com; stadiums = Wikipedia + sportsfoundation.org + Wikipedia home-stadium chronology; mascots = Wikipedia + sportmascots.com + whiteclouds.

## Dropped / not included (could not be confirmed with two sources)

- Ravens' extra mascots (Rise, Conquer, Edgar, Allen), Chiefs' Warpaint, Lions' Theo, Eagles' Air Swoop: single-source or conflicting.
- Dutch Clark and Ace Parker (Hall of Fame QBs): single source.
- Earl Morrall as a Super Bowl V winning QB: sources disagree.
- Considered and not built: owners / current head coaches (change too often), Pro Bowl lists, 5,000-yard seasons and 2,000-yard rushers (fewer than 12 answers).
- Not independently re-derived: exact career totals shown in answer notes (they are display-only; membership of each club was checked against the threshold).
