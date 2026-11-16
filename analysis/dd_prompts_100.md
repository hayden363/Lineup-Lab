# The Daily Drive: 100-prompt pool for owner review

Data: 2026 season through Week 10, scope variants as of 2026-11-16. Tier numbers: 1 = 10 yds (most obvious) ... 6 = 100 yds (rarest).
Every prompt below passed the real tiering path (dd.pick_threshold): at least 12 answers (target 15+), at least one tier-6 answer.
Scoped prompts rotate by date; all variants were also run. `*` = fragile early in a season (see fragility section).

| # | Prompt (today's threshold) | Answers | Tier-6 | Obvious (tier 1) | Rare (tier 6) |
|---|---|---|---|---|---|
| | **Season totals** | | | | |
| 1 | Name a WR with 600+ receiving yards | 17 | 1 | CeeDee Lamb | Tetairoa McMillan |
| 2 | Name a TE with 300+ receiving yards | 19 | 1 | Travis Kelce | Michael Mayer |
| 3 | Name a RB with 500+ rushing yards | 19 | 1 | Christian McCaffrey | Braelon Allen |
| 4 | Name a QB with 2,000+ passing yards | 17 | 1 | Aaron Rodgers | Deshaun Watson |
| 5 | Name a QB who has thrown 12+ touchdown passes | 16 | 1 | Aaron Rodgers | Geno Smith |
| 6 | Name a RB with 20+ catches | 22 | 2 | Christian McCaffrey | RJ Harvey |
| 7 | Name a WR or TE with 5+ receiving TDs | 18 | 1 | Stefon Diggs | Mike Gesicki |
| 8 | Name a player with 6+ touchdowns (rushing + receiving) | 28 | 2 | Josh Allen | Pat Freiermuth |
| 9 | Name a player with 175+ PPR fantasy points | 20 | 2 | Kirk Cousins | Drake Maye |
| 10 | Name a player who has been targeted 70+ times | 19 | 1 | CeeDee Lamb | Michael Wilson |
| 11 | Name a RB with 125+ carries | 18 | 1 | Derrick Henry | Braelon Allen |
| 12 | Name a player with 800+ scrimmage yards (rushing + receiving) | 19 | 1 | Christian McCaffrey | Chuba Hubbard |
| 13 | Name a WR with 150+ yards after the catch | 28 | 2 | CeeDee Lamb | Malik Washington |
| | **One-game feats** | | | | |
| 14 | Name a WR with a 150+ yard receiving game | 15 | 1 | Davante Adams | Tetairoa McMillan |
| 15 | Name a TE with an 80+ yard receiving game | 18 | 1 | Travis Kelce | Darnell Washington |
| 16 | Name a RB with an 110+ yard rushing game | 17 | 1 | Derrick Henry | Kenny Gainwell |
| 17 | Name a QB with a 325+ yard passing game | 16 | 1 | Matthew Stafford | Sam Darnold |
| 18 | Name a player with a 35+ PPR point game | 25 | 2 | Davante Adams | Tyler Allgeier |
| 19 | Name a QB who threw 3+ touchdown passes in one game | 27 | 2 | Aaron Rodgers | Drew Lock |
| 20 | Name a player with 11+ catches in one game | 16 | 1 | CeeDee Lamb | Michael Wilson |
| 21 | Name a QB with 40+ rushing yards in one game | 18 | 1 | Josh Allen | Jalon Daniels |
| 22 | Name a RB with 55+ receiving yards in one game | 23 | 2 | Christian McCaffrey | Dylan Sampson |
| | **Same-game combos** | | | | |
| 23 | Name a RB who ran for 100+ yards AND scored in the same game* | 23 | 2 | Derrick Henry | Emmett Johnson |
| 24 | Name a WR with 100+ receiving yards AND a TD in the same game | 30 | 3 | Davante Adams | Kayshon Boutte |
| 25 | Name a QB who threw a TD AND ran for a TD in the same game | 19 | 1 | Kirk Cousins | Tyler Huntley |
| 26 | Name a RB with 50+ rushing AND 50+ receiving yards in the same game* | 12 | 1 | Christian McCaffrey | Emmett Johnson |
| 27 | Name a player with a rushing TD AND a receiving TD in the same game* | 16 | 1 | Christian McCaffrey | Emanuel Wilson |
| 28 | Name a QB with 300+ passing yards AND 3+ TD passes in the same game* | 15 | 1 | Matthew Stafford | Sam Darnold |
| 29 | Name a WR with 8+ catches AND 100+ yards in the same game* | 22 | 2 | Davante Adams | KC Concepcion |
| 30 | Name a TE with a TD AND 5+ catches in the same game* | 23 | 2 | Travis Kelce | Colby Parkinson |
| | **Repeat performers** | | | | |
| 31 | Name a WR with 2+ games of 100+ receiving yards | 19 | 1 | Davante Adams | Tre Tucker |
| 32 | Name a RB with 1+ games of 100+ rushing yards* | 24 | 2 | Derrick Henry | Emmett Johnson |
| 33 | Name a player who has scored in 5+ games (rushing/receiving TD) | 28 | 2 | Josh Allen | Pat Freiermuth |
| 34 | Name a player with 5+ games of 20+ PPR points | 17 | 1 | Kirk Cousins | C.J. Stroud |
| 35 | Name a QB with 1+ games of 300+ passing yards* | 22 | 2 | Matthew Stafford | Sam Darnold |
| 36 | Name a player with 2+ multi-TD games (2+ rushing/receiving TDs) | 22 | 2 | Davante Adams | Tony Pollard |
| | **Streaks** | | | | |
| 37 | Name a player who has scored in 3+ straight games | 30 | 3 | Josh Allen | Keon Coleman |
| 38 | Name a WR with 75+ receiving yards in 2+ straight games* | 25 | 2 | Davante Adams | DeMario Douglas |
| 39 | Name a RB with 60+ rushing yards in 2+ straight games | 26 | 2 | Christian McCaffrey | Kaelon Black |
| | **Efficiency** | | | | |
| 40 | Name a RB averaging 4+ yards per carry (min 60 carries) | 26 | 2 | Christian McCaffrey | Kaelon Black |
| 41 | Name a WR averaging 8.5+ yards per target (min 40 targets) | 18 | 1 | Davante Adams | DeMario Douglas |
| 42 | Name a QB completing 64%+ of his passes (min 180 attempts) | 15 | 1 | Matthew Stafford | Deshaun Watson |
| 43 | Name a QB averaging 7+ yards per attempt (min 180 attempts) | 19 | 1 | Matthew Stafford | Sam Darnold |
| 44 | Name a WR averaging 13+ yards per catch (min 25 catches) | 20 | 2 | Davante Adams | Tre Tucker |
| 45 | Name a QB throwing a TD on 4.5%+ of his attempts (min 180 attempts) | 16 | 1 | Aaron Rodgers | Sam Darnold |
| 46 | Name a QB with an interception rate under 2.5% (min 180 attempts) | 17 | 1 | Aaron Rodgers | Cam Ward |
| 47 | Name a WR with a 25%+ target share (min 7 games played) | 15 | 1 | CeeDee Lamb | Michael Wilson |
| | **Scoped to a conference** | | | | |
| 48 | Name an AFC player with 3+ rushing TDs | 17 | 1 | Josh Allen | Chris Rodriguez Jr. |
| 49 | Name an AFC WR with 400+ receiving yards* | 16 | 1 | Ja'Marr Chase | DeMario Douglas |
| 50 | Name an AFC RB with 300+ rushing yards | 16 | 1 | Derrick Henry | J.K. Dobbins |
| 51 | Name an NFC QB with 6+ touchdown passes | 15 | 1 | Matthew Stafford | Drew Lock |
| 52 | Name an NFC TE with 2+ receiving TDs* | 17 | 1 | George Kittle | Teagan Quitoriano |
| | **Scoped to a division** | | | | |
| 53 | Name a NFC East player with 1+ receiving TDs* | 23 | 2 | Stefon Diggs | Darius Cooper |
| 54 | Name a NFC East player with a 20+ PPR point game* | 16 | 1 | Dak Prescott | Jaxson Dart |
| | **Scoped to a college conference** | | | | |
| 55 | Name an ACC alum with 2+ rushing or receiving TDs | 18 | 1 | Christian McCaffrey | Davis Allen |
| | **Game context** | | | | |
| 56 | Name a player who scored against a division rival, 3+ times | 23 | 2 | Josh Allen | Brian Robinson |
| 57 | Name a WR with 110+ receiving yards in a game against a division rival | 17 | 1 | Mike Evans | Tyquan Thornton |
| 58 | Name a player who scored in a primetime game, 3+ times | 17 | 1 | Davante Adams | Brian Robinson |
| 59 | Name a RB with a 100+ yard rushing game on the road | 19 | 1 | Derrick Henry | Emmett Johnson |
| 60 | Name a player who scored in a dome or closed-roof game, 3+ times | 33 | 3 | Davante Adams | Brian Robinson |
| 61 | Name a player with 25+ PPR points in an overtime game | 22 | 2 | Matthew Stafford | Cam Ward |
| 62 | Name a player who scored in a one-score loss (8 points or fewer), 2+ times | 38 | 3 | Davante Adams | Kimani Vidal |
| 63 | Name a player with 25+ PPR points in a loss | 37 | 3 | Matthew Stafford | Mason Taylor |
| 64 | Name a player who scored in an upset win (his team was the underdog), 2+ times | 27 | 2 | Mike Evans | MarShawn Lloyd |
| 65 | Name a player who scored in a shootout (60+ combined points), 3+ times | 23 | 2 | Josh Allen | Noah Fant |
| | **Last week** | | | | |
| 66 | Name a player with 25+ PPR points last week | 18 | 1 | Patrick Mahomes | Emmett Johnson |
| 67 | Name a RB with 1+ rushing TDs last week | 15 | 1 | Christian McCaffrey | Seth McGowan |
| 68 | Name a WR with 70+ receiving yards last week | 20 | 2 | Stefon Diggs | Konata Mumpfield |
| 69 | Name a RB with 60+ rushing yards last week | 15 | 1 | Christian McCaffrey | Ronnie Rivers |
| 70 | Name a QB with 200+ passing yards last week | 18 | 1 | Matthew Stafford | Kyle McCord |
| | **Last three weeks** | | | | |
| 71 | Name a player with 3+ TDs over the last three weeks | 15 | 1 | Josh Allen | Emmett Johnson |
| 72 | Name a player with 60+ PPR points over the last three weeks | 15 | 1 | Josh Allen | Emmett Johnson |
| 73 | Name a WR with 175+ receiving yards over the last three weeks | 17 | 1 | CeeDee Lamb | DeMario Douglas |
| 74 | Name a RB with 150+ rushing yards over the last three weeks | 20 | 2 | Jonathan Taylor | Emmett Johnson |
| | **Rookies** | | | | |
| 75 | Name a rookie with 2+ rushing or receiving TDs | 15 | 1 | Denzel Boston | Nate Boerkircher |
| 76 | Name a rookie WR with 100+ receiving yards | 15 | 1 | Denzel Boston | Barion Brown |
| 77 | Name a rookie with a 12+ PPR point game | 22 | 2 | Denzel Boston | Kevin Coleman Jr. |
| 78 | Name a rookie with 200+ scrimmage yards (rushing + receiving) | 18 | 1 | Denzel Boston | Seth McGowan |
| 79 | Name a rookie with 10+ catches | 22 | 2 | Denzel Boston | Josh Cuevas |
| | **Defense** | | | | |
| 80 | Name a defender with 6+ sacks | 17 | 1 | Jeffery Simmons | Quinnen Williams |
| 81 | Name a defender with 3+ interceptions | 17 | 1 | Travis Hunter | Rasul Douglas |
| 82 | Name a defender with 70+ tackles | 26 | 2 | Jeremy Chinn | Demetrius Knight Jr. |
| 83 | Name a defender who has forced 2+ fumbles | 43 | 4 | Andrew Van Ginkel | Tyson Campbell |
| 84 | Name a defender with 8+ passes defended | 30 | 3 | Keisean Nixon | Riley Moss |
| 85 | Name a defender with 14+ tackles in one game | 20 | 2 | Dane Belton | Kevin Winston Jr. |
| | **Kicking** | | | | |
| 86 | Name a kicker with 16+ field goals made | 17 | 1 | Jason Sanders | Jason Myers |
| 87 | Name a kicker with a 56+ yard field goal | 22 | 2 | Chris Boswell | Will Reichard |
| 88 | Name a kicker with 3+ field goals from 50 or more yards | 22 | 2 | Jason Sanders | Tyler Bass |
| 89 | Name a punter with 15+ punts downed inside the 20 | 15 | 1 | Jack Fox | Michael Dickson |
| | **Odd angles** | | | | |
| 90 | Name a QB who has been sacked 15+ times | 22 | 2 | Aaron Rodgers | Daniel Jones |
| 91 | Name a QB who has thrown 6+ interceptions | 17 | 1 | Aaron Rodgers | Malik Willis |
| 92 | Name a player who has lost 2+ fumbles | 30 | 3 | Baker Mayfield | Chimere Dike |
| 93 | Name a WR with 4+ rushing attempts | 15 | 1 | DJ Moore | Isaiah Williams |
| 94 | Name a QB who has rushed for 1+ touchdowns | 28 | 2 | Kirk Cousins | Tyler Huntley |
| 95 | Name a QB with 20+ rushing attempts | 26 | 2 | Kirk Cousins | Malik Willis |
| 96 | Name a player whose best and worst PPR weeks are 30+ points apart (min 6 games) | 16 | 1 | Davante Adams | Emmett Johnson |
| | **Fantasy finishes** | | | | |
| 97 | Name a WR who has finished a week as a top-12 WR in PPR scoring 3+ times | 16 | 1 | Davante Adams | Tre Tucker |
| 98 | Name a RB who has finished a week as a top-12 RB in PPR scoring 3+ times | 20 | 2 | Christian McCaffrey | Rhamondre Stevenson |
| 99 | Name a TE who has finished a week as a top-6 TE in PPR scoring 1+ times | 30 | 3 | Travis Kelce | Davis Allen |
| 100 | Name a QB who has finished a week as a top-6 QB in PPR scoring 2+ times | 15 | 1 | Matthew Stafford | Geno Smith |

## Fragile early in a season (2025 replayed at Weeks 3, 5, 8)

The ladder walks down to its lowest rung when counts are thin, and the game already needs 3 finished weeks. These prompts still return nothing at one of the early weeks (the day picker just skips them, others fill in):

- `combo_rb_100_td`: early-season gaps at wk 3
- `combo_rb_5050`: early-season gaps at wk 3,5
- `combo_rush_rec_td`: early-season gaps at wk 3,5,8
- `combo_qb_300_3td`: early-season gaps at wk 3,5,8
- `combo_wr_8_100`: early-season gaps at wk 3
- `combo_te_td_5`: early-season gaps at wk 3
- `n_rb_100`: early-season gaps at wk 3
- `n_qb_300`: early-season gaps at wk 3
- `s_wr_100`: early-season gaps at wk 3
- `sc_div_rec_td`: early-season gaps at wk 3
- `sc_conf_wr_yds`: early-season gaps at wk 3
- `sc_div_ppr_game`: early-season gaps at wk 3
- `sc_conf_te_td`: early-season gaps at wk 3
- `w_rb_td` (RB rushing TD last week) is also thin on a single-week window: it returned nothing for 2025 Week 12.

## Judgement calls for the owner

- Team-scoped prompts ("Name a Chiefs player with a TD") were tried and cut: with 12 answers needed, only 4 of 32 teams pass for scorers and 28 of 32 for "has a catch" (and none before Week 5). Division and conference scopes (rotating by date) replace them. All 8 divisions pass for receiving TDs and for a big PPR game; all 4 college conferences pass.
- The college-scoped prompt (`sc_col_td`) use the player's college from the draft table and TODAY's conference membership (Texas and Oklahoma count as SEC, USC/UCLA/Oregon/Washington as Big Ten). Players who went undrafted have no college on file, so they are never answers. This is player background, not a stat: owner may want it cut.
- Rookies are "players drafted in this season's draft" (draft table, `season == this season`). Undrafted rookies are not counted (the draft table shows 61 drafted rookies at QB/RB/WR/TE vs 79 in the Sleeper-style rookie file, which the app does not load).
- Defense and kicking prompts exist because the weekly table has real sacks, interceptions, tackles, forced fumbles, passes defended, FG distance buckets, punts inside 20. Fame for defenders comes only from career Approximate Value (no fantasy/consensus signal), so tiers there are rougher.
- Prompts that need a count of 1 (combos, "scored against a division rival") show "{n}+ times" in the text only when the ladder climbs above 1.
- The day picker has no category balance; every prompt carries `cat` so a later change can ask for a spread across categories.

## What the data ruled out

- Weather (cold, wind, rain): `temp` and `wind` in the schedule are filled for only 45 of 272 games.
- Age, jersey number, height: the Sleeper player list has them but the app trims it to 8 fields, and the nflverse weekly table has none.
- "Firsts" (first career TD, first 100-yard game): needs history, which the owner rule excludes. Only within-season firsts are computable and add little.
- Draft round/pick and years-in-the-league prompts: draft trivia, excluded by rule.
- Team-name answers: tiering has no popularity signal for teams, and 12+ answers per prompt would need a different path.
- Red-zone/goal-line usage, snap share, pressure/blitz, deep-ball and drop rates: not in the weekly table (some live in play-by-play, NGS, PFR or FTN files but were not loaded or verified here).
- Opponent-defense quality ("against a top-5 pass defense"): not computed; "against a team over .500" was cut for being too broad.
- Per-team standings use only games already played; the schedule's `spread_line` marks "underdog" and is complete for played games.
