# The Daily Drive: history prompt pool (draft for owner review)

Generated from `engine/daily_drive_history_pool.py` on real nflverse data (seasons 2000-2025, drafts 2000-2025). Wording shown is the prompt as it would read on **2026-11-17** (scoped templates rotate their college / team / decade / draft class / round / pick / position by date, and skip any variant that cannot build a valid prompt).

- **179 templates**, all 179 build a valid prompt on real data. 179 built on 2026-11-17 in 5.2s including data load.
- Every rotating scope variant was also run: **818 of 1040 variants pass** (answers 15-50, a tier-6 answer, never fewer than 12); the 222 that fail are listed in the appendix and are never offered (the template falls through to the next scope).
- Answer counts across passing variants: min 12, median 18, max 50 (cap 50); 87 variants sit at 12-14 answers (above the 12 floor, under the 15 target).


## Season marks (25)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 1 | `h_qb_pass_yds` | Name a QB who threw for 4,700+ yards in a season since 2000 | 21 | 2 | Tom Brady | Kurt Warner | 1/1 |
| 2 | `h_qb_pass_td` | Name a QB who threw 36+ touchdown passes in a season since 2000 | 19 | 1 | Tom Brady | Kurt Warner | 1/1 |
| 3 | `h_qb_rush_yds` | Name a QB who ran for 600+ yards in a season since 2000 | 15 | 1 | Russell Wilson | Tim Tebow | 1/1 |
| 4 | `h_qb_rush_td` | Name a QB with 7+ rushing TDs in a season since 2000 | 17 | 1 | Cam Newton | Jaxson Dart | 1/1 |
| 5 | `h_qb_int` | Name a QB who threw 22+ interceptions in a season since 2000 | 20 | 2 | Drew Brees | DeShone Kizer | 1/1 |
| 6 | `h_qb_sacked` | Name a QB who was sacked 55+ times in a season since 2000 | 15 | 1 | Russell Wilson | Sam Howell | 1/1 |
| 7 | `h_rb_rush_yds` | Name a RB who ran for 1,600+ yards in a season since 2000 | 27 | 2 | LaDainian Tomlinson | Alfred Morris | 1/1 |
| 8 | `h_rb_rush_td` | Name a RB with 17+ rushing TDs in a season since 2000 | 15 | 1 | LaDainian Tomlinson | Raheem Mostert | 1/1 |
| 9 | `h_rb_carries` | Name a RB with 350+ carries in a season since 2000 | 21 | 2 | LaDainian Tomlinson | Rudi Johnson | 1/1 |
| 10 | `h_rb_rec` | Name a RB with 80+ catches in a season since 2000 | 20 | 2 | LaDainian Tomlinson | J.D. McKissic | 1/1 |
| 11 | `h_rb_scrim` | Name a RB with 2,200+ yards from scrimmage in a season since 2000 | 16 | 1 | LaDainian Tomlinson | Arian Foster | 1/1 |
| 12 | `h_wr_rec_yds` | Name a WR with 1,600+ receiving yards in a season since 2000 | 17 | 1 | Randy Moss | Josh Gordon | 1/1 |
| 13 | `h_wr_rec` | Name a WR with 115+ catches in a season since 2000 | 21 | 2 | Davante Adams | Michael Thomas | 1/1 |
| 14 | `h_wr_rec_td` | Name a WR with 14+ receiving TDs in a season since 2000 | 21 | 2 | Davante Adams | Braylon Edwards | 1/1 |
| 15 | `h_wr_targets` | Name a WR who was targeted 180+ times in a season since 2000 | 20 | 2 | Reggie Wayne | Michael Thomas | 1/1 |
| 16 | `h_te_rec_yds` | Name a TE with 1,100+ receiving yards in a season since 2000 | 15 | 1 | Tony Gonzalez | Kellen Winslow | 1/1 |
| 17 | `h_te_rec` | Name a TE with 90+ catches in a season since 2000 | 15 | 1 | Tony Gonzalez | Martellus Bennett | 1/1 |
| 18 | `h_te_td` | Name a TE with 11+ receiving TDs in a season since 2000 | 16 | 1 | Travis Kelce | Robert Tonyan | 1/1 |
| 19 | `h_any_td` | Name a player with 20+ rushing and receiving TDs in a season since 2000 | 17 | 1 | LaDainian Tomlinson | Raheem Mostert | 1/1 |
| 20 | `h_sacks` | Name a defender with 18+ sacks in a season since 2000 | 17 | 1 | Jared Allen | Aldon Smith | 1/1 |
| 21 | `h_def_int` | Name a defender with 9+ interceptions in a season since 2000 | 20 | 2 | Champ Bailey | Kwamie Lassiter | 1/1 |
| 22 | `h_def_td` | Name a defender with 3+ defensive TDs in a season since 2000 | 17 | 1 | Charles Woodson | Kyle Brady | 1/1 |
| 23 | `h_k_fg` | Name a kicker who made 36+ field goals in a season since 2000 | 18 | 1 | Nick Folk | Younghoe Koo | 1/1 |
| 24 | `h_k_long` | Name a kicker with a 62+ yard field goal in a season since 2000 | 15 | 1 | Sebastian Janikowski | Brett Maher | 1/1 |
| 25 | `h_p_in20` | Name a punter with 36+ punts inside the 20 in a season since 2000 | 25 | 2 | Andy Lee | Matthew Hayball | 1/1 |

## Decade marks (12)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 26 | `h_dec_qb_yds` | Name a QB who threw for 4,200+ yards in a season of the 2000s | 18 | 1 | Tom Brady | Marc Bulger | 3/3 |
| 27 | `h_dec_qb_td` | Name a QB who threw 34+ touchdown passes in a season of the 2010s | 16 | 1 | Tom Brady | Blake Bortles | 3/3 |
| 28 | `h_dec_qb_rush` | Name a QB who ran for 400+ yards in a season of the 2020s | 19 | 1 | Russell Wilson | Anthony Richardson | 3/3 |
| 29 | `h_dec_rb_yds` | Name a RB who ran for 1,600+ yards in a season of the 2000s | 16 | 1 | LaDainian Tomlinson | Larry Johnson | 3/3 |
| 30 | `h_dec_rb_td` | Name a RB with 15+ rushing TDs in a season of the 2000s | 15 | 1 | LaDainian Tomlinson | LenDale White | 3/3 |
| 31 | `h_dec_rb_rec` | Name a RB with 70+ catches in a season of the 2000s | 15 | 1 | LaDainian Tomlinson | Richie Anderson | 3/3 |
| 32 | `h_dec_wr_yds` | Name a WR with 1,300+ receiving yards in a season of the 2020s | 19 | 1 | Davante Adams | Brandon Aiyuk | 3/3 |
| 33 | `h_dec_wr_rec` | Name a WR with 105+ catches in a season of the 2020s | 16 | 1 | Davante Adams | Diontae Johnson | 3/3 |
| 34 | `h_dec_wr_td` | Name a WR with 10+ receiving TDs in a season of the 2020s | 20 | 2 | Davante Adams | Terry McLaurin | 3/3 |
| 35 | `h_dec_te_yds` | Name a TE with 900+ receiving yards in a season of the 2010s | 17 | 1 | Tony Gonzalez | Jordan Cameron | 3/3 |
| 36 | `h_dec_sacks` | Name a defender with 15+ sacks in a season of the 2010s | 20 | 2 | Aaron Donald | Vic Beasley | 3/3 |
| 37 | `h_dec_int` | Name a defender with 6+ interceptions in a season of the 2020s | 17 | 1 | Tyrann Mathieu | Amani Oruwariye | 3/3 |

## Career totals (15)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 38 | `h_c_qb_yds` | Name a QB with 40,000+ career passing yards counting only seasons since 2000 | 15 | 1 | Tom Brady | Derek Carr | 1/1 |
| 39 | `h_c_qb_td` | Name a QB who has thrown 250+ touchdown passes since 2000 | 18 | 1 | Tom Brady | Derek Carr | 1/1 |
| 40 | `h_c_qb_rush` | Name a QB with 2,000+ career rushing yards since 2000 | 21 | 2 | Aaron Rodgers | Justin Fields | 1/1 |
| 41 | `h_c_rb_yds` | Name a RB with 9,000+ career rushing yards since 2000 | 18 | 1 | LaDainian Tomlinson | Jamal Lewis | 1/1 |
| 42 | `h_c_rb_td` | Name a RB with 60+ career rushing TDs since 2000 | 28 | 2 | LaDainian Tomlinson | Brandon Jacobs | 1/1 |
| 43 | `h_c_rb_rec` | Name a RB with 400+ career catches since 2000 | 15 | 1 | LaDainian Tomlinson | Michael Pittman | 1/1 |
| 44 | `h_c_wr_yds` | Name a WR with 12,000+ career receiving yards since 2000 | 15 | 1 | Larry Fitzgerald | Brandon Marshall | 1/1 |
| 45 | `h_c_wr_rec` | Name a WR with 800+ career catches since 2000 | 21 | 2 | Larry Fitzgerald | Wes Welker | 1/1 |
| 46 | `h_c_wr_td` | Name a WR with 70+ career receiving TDs since 2000 | 22 | 2 | Larry Fitzgerald | Dez Bryant | 1/1 |
| 47 | `h_c_te_yds` | Name a TE with 5,000+ career receiving yards since 2000 | 23 | 2 | Tony Gonzalez | Marcedes Lewis | 1/1 |
| 48 | `h_c_te_td` | Name a TE with 40+ career receiving TDs since 2000 | 19 | 1 | Tony Gonzalez | Marcedes Lewis | 1/1 |
| 49 | `h_c_any_td` | Name a player with 90+ career rushing and receiving TDs since 2000 | 17 | 1 | Larry Fitzgerald | Shaun Alexander | 1/1 |
| 50 | `h_c_sacks` | Name a defender with 110+ career sacks since 2000 | 19 | 1 | Julius Peppers | Dwight Freeney | 1/1 |
| 51 | `h_c_int` | Name a defender with 35+ career interceptions since 2000 | 19 | 1 | Champ Bailey | Dre' Bly | 1/1 |
| 52 | `h_c_k` | Name a kicker with 300+ career field goals since 2000 | 18 | 1 | Adam Vinatieri | Rian Lindell | 1/1 |

## Decade totals (7)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 53 | `h_dt_qb_yds` | Name a QB with 25,000+ passing yards in the 2010s | 15 | 1 | Tom Brady | Ryan Fitzpatrick | 3/3 |
| 54 | `h_dt_qb_td` | Name a QB with 150+ touchdown passes in the 2010s | 18 | 1 | Tom Brady | Andrew Luck | 3/3 |
| 55 | `h_dt_rb_yds` | Name a RB with 6,000+ rushing yards in the 2000s | 18 | 1 | LaDainian Tomlinson | Travis Henry | 3/3 |
| 56 | `h_dt_wr_yds` | Name a WR with 5,000+ receiving yards in the 2020s | 20 | 2 | Davante Adams | Terry McLaurin | 3/3 |
| 57 | `h_dt_te_yds` | Name a TE with 2,000+ receiving yards in the 2020s | 27 | 2 | Travis Kelce | Tyler Conklin | 3/3 |
| 58 | `h_dt_sacks` | Name a defender with 70+ sacks in the 2010s | 18 | 1 | Julius Peppers | Everson Griffen | 3/3 |
| 59 | `h_dt_int` | Name a defender with 25+ interceptions in the 2000s | 22 | 2 | Champ Bailey | Tory James | 3/3 |

## Repeat seasons (9)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 60 | `h_n_wr_1000` | Name a WR with 7+ seasons of 1,000+ receiving yards since 2000 | 20 | 2 | Larry Fitzgerald | Amari Cooper | 1/1 |
| 61 | `h_n_rb_1000` | Name a RB with 5+ seasons of 1,000+ rushing yards since 2000 | 23 | 2 | LaDainian Tomlinson | Jamaal Charles | 1/1 |
| 62 | `h_n_qb_4000` | Name a QB with 4+ seasons of 4,000+ passing yards since 2000 | 19 | 1 | Tom Brady | Andrew Luck | 1/1 |
| 63 | `h_n_qb_30td` | Name a QB with 3+ seasons of 30+ touchdown passes since 2000 | 19 | 1 | Tom Brady | Andrew Luck | 1/1 |
| 64 | `h_n_sack10` | Name a defender with 6+ seasons of 10+ sacks since 2000 | 15 | 1 | Julius Peppers | Danielle Hunter | 1/1 |
| 65 | `h_n_te_700` | Name a TE with 3+ seasons of 700+ receiving yards since 2000 | 25 | 2 | Tony Gonzalez | Jordan Matthews | 1/1 |
| 66 | `h_n_td10` | Name a player with 4+ seasons of 10+ rushing and receiving TDs since 2000 | 35 | 3 | Larry Fitzgerald | Arian Foster | 1/1 |
| 67 | `h_n_rec90` | Name a WR with 4+ seasons of 90+ catches since 2000 | 20 | 2 | Larry Fitzgerald | Michael Thomas | 1/1 |
| 68 | `h_n_int5` | Name a defender with 3+ seasons of 5+ interceptions since 2000 | 29 | 2 | Champ Bailey | J.C. Jackson | 1/1 |

## Big games (19)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 69 | `h_g_qb_yds` | Name a QB who threw for 500+ yards in a game since 2000 | 15 | 1 | Tom Brady | Elvis Grbac | 1/1 |
| 70 | `h_g_qb_td` | Name a QB who threw 5+ touchdown passes in a game of the 2010s | 28 | 2 | Tom Brady | Matt Flynn | 3/3 |
| 71 | `h_g_qb_rush` | Name a QB who ran for 100+ yards in a game since 2000 | 19 | 1 | Russell Wilson | Kevin Hogan | 1/1 |
| 72 | `h_g_rb_yds` | Name a RB who ran for 230+ yards in a game since 2000 | 17 | 1 | LaDainian Tomlinson | Jerome Harrison | 1/1 |
| 73 | `h_g_rb_td` | Name a RB with 4+ rushing and receiving TDs in a game since 2000 | 41 | 4 | LaDainian Tomlinson | Jonas Gray | 1/1 |
| 74 | `h_g_rb_rec` | Name a RB with 130+ receiving yards in a game since 2000 | 22 | 2 | LaDainian Tomlinson | Patrick Cobbs | 1/1 |
| 75 | `h_g_wr_yds` | Name a WR with 250+ receiving yards in a game since 2000 | 15 | 1 | Andre Johnson | Josh Gordon | 1/1 |
| 76 | `h_g_wr_rec` | Name a WR with 15+ catches in a game since 2000 | 16 | 1 | Reggie Wayne | Michael Wilson | 1/1 |
| 77 | `h_g_wr_td` | Name a WR with 3+ receiving TDs in a game of the 2020s | 21 | 2 | Davante Adams | Chase Claypool | 3/3 |
| 78 | `h_g_te_yds` | Name a TE with 160+ receiving yards in a game since 2000 | 19 | 1 | Jason Witten | Ed Dickson | 1/1 |
| 79 | `h_g_ppr` | Name a player with a 50+ PPR point game since 2000 | 31 | 3 | LaDainian Tomlinson | Jahvid Best | 1/1 |
| 80 | `h_g_sacks` | Name a defender with 4+ sacks in a game since 2000 | 48 | 4 | Aaron Donald | Will McDonald IV | 1/1 |
| 81 | `h_ng_qb_400` | Name a QB with 6+ games of 400+ passing yards since 2000 | 16 | 1 | Tom Brady | Ryan Fitzpatrick | 1/1 |
| 82 | `h_ng_qb_5td` | Name a QB with 2+ games of 5+ touchdown passes since 2000 | 21 | 2 | Tom Brady | Jameis Winston | 1/1 |
| 83 | `h_ng_rb_200` | Name a RB with 2+ games of 200+ rushing yards since 2000 | 21 | 2 | LaDainian Tomlinson | Jay Ajayi | 1/1 |
| 84 | `h_ng_wr_200` | Name a WR with 2+ games of 200+ receiving yards since 2000 | 19 | 1 | Reggie Wayne | Josh Gordon | 1/1 |
| 85 | `h_ng_wr_150` | Name a WR with 10+ games of 150+ receiving yards since 2000 | 15 | 1 | Steve Smith | T.Y. Hilton | 1/1 |
| 86 | `h_ng_rb_150` | Name a RB with 8+ games of 150+ rushing yards since 2000 | 18 | 1 | LaDainian Tomlinson | Larry Johnson | 1/1 |
| 87 | `h_ng_sack3` | Name a defender with 6+ games of 3+ sacks since 2000 | 17 | 1 | Julius Peppers | Cameron Wake | 1/1 |

## Rookie seasons (6)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 88 | `h_r_qb_yds` | Name a QB who threw for 3,400+ yards as a rookie (drafted since 2000) | 16 | 1 | Matt Ryan | Mac Jones | 1/1 |
| 89 | `h_r_qb_td` | Name a QB who threw 20+ touchdown passes as a rookie (drafted since 2000) | 18 | 1 | Russell Wilson | Mac Jones | 1/1 |
| 90 | `h_r_rb_yds` | Name a RB who ran for 1,200+ yards as a rookie (drafted since 2000) | 15 | 1 | LaDainian Tomlinson | Steve Slaton | 1/1 |
| 91 | `h_r_wr_yds` | Name a WR with 1,000+ receiving yards as a rookie (drafted since 2000) | 21 | 2 | Anquan Boldin | Michael Clayton | 1/1 |
| 92 | `h_r_sacks` | Name a defender with 10+ sacks as a rookie (drafted since 2000) | 19 | 1 | Julius Peppers | James Pearce Jr. | 1/1 |
| 93 | `h_r_int` | Name a defender with 5+ interceptions as a rookie (drafted since 2000) | 26 | 2 | Ed Reed | Derek Ross | 1/1 |

## Draft pedigree (7)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 94 | `h_p_r1_rb` | Name a first-round pick who ran for 1,400+ yards in a season since 2000 | 18 | 1 | LaDainian Tomlinson | Doug Martin | 1/1 |
| 95 | `h_p_late_rb` | Name a RB drafted in round 4 or later who ran for 1,100+ yards in a season since 2000 | 16 | 1 | Aaron Jones | Jay Ajayi | 1/1 |
| 96 | `h_p_late_qb` | Name a QB drafted in round 3 or later who threw for 3,200+ yards in a season since 2000 | 16 | 1 | Tom Brady | Sam Howell | 1/1 |
| 97 | `h_p_r1_wr` | Name a first-round WR with 1,400+ receiving yards in a season since 2000 | 15 | 1 | Larry Fitzgerald | Odell Beckham Jr. | 1/1 |
| 98 | `h_p_r1_qb` | Name a first-round QB who threw for 4,600+ yards in a season since 2000 | 15 | 1 | Aaron Rodgers | Tua Tagovailoa | 1/1 |
| 99 | `h_p_late_sack` | Name a defender drafted in round 3 or later with 13+ sacks in a season since 2000 | 17 | 1 | Jared Allen | Greg Hardy | 1/1 |
| 100 | `h_p_r2_te` | Name a TE drafted in round 2 or later with 900+ receiving yards in a season since 2000 | 17 | 1 | Jason Witten | Jordan Cameron | 1/1 |

## NFL Draft (21)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 101 | `h_d_first_overall` | Name a #1 overall NFL draft pick since 2000 | 26 | 2 | Matthew Stafford | JaMarcus Russell | 1/1 |
| 102 | `h_d_slot` | Name a player taken with the #3 overall pick since 2000 | 26 | 2 | Matt Ryan | Abdul Carter | 32/32 |
| 103 | `h_d_top5_dec` | Name a top-5 NFL draft pick of the 2020s | 30 | 3 | Joe Burrow | Abdul Carter | 3/3 |
| 104 | `h_d_year_r1` | Name a first-round pick in the 2005 NFL Draft | 32 | 3 | Aaron Rodgers | David Pollack | 26/26 |
| 105 | `h_d_year_pb` | Name a player from the 2000 NFL Draft class who made 2+ Pro Bowls | 16 | 1 | Tom Brady | Brian Jennings | 24/26 |
| 106 | `h_d_hof` | Name a Hall of Famer drafted since 2000 | 19 | 1 | Drew Brees | Devin Hester | 1/1 |
| 107 | `h_d_top10_pos` | Name a linebacker taken in the top 10 of the draft since 2000 | 24 | 2 | Brian Urlacher | Tyree Wilson | 7/8 |
| 108 | `h_d_round` | Name a fifth-round NFL draft pick since 2000 who made 2+ Pro Bowls | 20 | 2 | Tyreek Hill | Matthew Slater | 6/6 |
| 109 | `h_d_late_pos` | Name a defensive back drafted in round 4 or later since 2000 who made a Pro Bowl | 28 | 2 | Richard Sherman | Hanik Milligan | 6/8 |
| 110 | `h_d_r1_pos` | Name a defensive lineman taken in the first round since 2000 who made 5+ Pro Bowls | 20 | 2 | Julius Peppers | Nick Bosa | 7/8 |
| 111 | `h_d_r1_ap` | Name a first-round pick since 2000 who was an All-Pro 4+ times | 19 | 1 | Aaron Rodgers | Cordarrelle Patterson | 1/1 |
| 112 | `h_d_later_ap` | Name a player drafted after the first round since 2000 who was an All-Pro 3+ times | 21 | 2 | Tom Brady | Andy Lee | 1/1 |
| 113 | `h_d_r1_dec_qb` | Name a QB taken in the first round of the 2010s drafts who made a Pro Bowl | 16 | 1 | Cam Newton | Robert Griffin III | 3/3 |
| 114 | `h_d_r1_dec_rb` | Name a running back taken in the first round of the 2000s drafts who made a Pro Bowl | 16 | 1 | LaDainian Tomlinson | Michael Bennett | 2/3 |
| 115 | `h_d_r1_dec_wr` | Name a wide receiver taken in the first round of the 2010s drafts | 34 | 3 | Julio Jones | A.J. Jenkins | 3/3 |
| 116 | `h_d_r12_dec_te` | Name a tight end taken in the first two rounds of the 2010s drafts | 27 | 2 | Rob Gronkowski | Troy Niklas | 3/3 |
| 117 | `h_d_r1_dec_ol` | Name an offensive lineman taken in the first round of the 2010s drafts who made 4+ Pro Bowls | 15 | 1 | Trent Williams | Chris Lindstrom | 2/3 |
| 118 | `h_d_r1_dec_dl` | Name a defensive lineman taken in the first round of the 2000s drafts who made 2+ Pro Bowls | 16 | 1 | Julius Peppers | Albert Haynesworth | 2/3 |
| 119 | `h_d_r1_dec_lb` | Name a linebacker taken in the first round of the 2020s drafts | 17 | 1 | Micah Parsons | Jihaad Campbell | 3/3 |
| 120 | `h_d_r1_dec_db` | Name a defensive back taken in the first round of the 2020s drafts | 28 | 2 | Patrick Surtain II | Lewis Cine | 3/3 |
| 121 | `h_d_late_dec` | Name a player drafted in round 5 or later in the 2000s drafts who made 2+ Pro Bowls | 20 | 2 | Tom Brady | Brian Jennings | 2/3 |

## Draft: colleges (5)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 122 | `h_dc_pb` | Name a player from Oklahoma drafted since 2000 who made 2+ Pro Bowls | 20 | 2 | Trent Williams | Marvin Mims | 14/44 |
| 123 | `h_dc_r1` | Name a first-round pick from USC since 2000 | 27 | 2 | Carson Palmer | R. Jay Soward | 23/44 |
| 124 | `h_dc_def` | Name a defender from South Carolina drafted since 2000 | 47 | 4 | John Abraham | T.J. Brunson | 31/44 |
| 125 | `h_dc_off` | Name an offensive player from Arkansas drafted since 2000 | 40 | 4 | Bobbie Williams | Tyler Wilson | 34/44 |
| 126 | `h_dc_late` | Name a player from West Virginia drafted after round 2 since 2000 | 41 | 4 | Marc Bulger | Shaquille Riddick | 13/44 |

## Draft: teams (5)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 127 | `h_dtm_pb` | Name a player the Panthers drafted since 2000 who made 2+ Pro Bowls | 15 | 1 | Julius Peppers | Jaycee Horn | 32/32 |
| 128 | `h_dtm_r1` | Name a first-round pick of the Cardinals since 2000 | 27 | 2 | Patrick Peterson | Walter Nolen | 32/32 |
| 129 | `h_dtm_r1_pb` | Name a first-round pick of the Jets since 2000 who made a Pro Bowl | 15 | 1 | Darrelle Revis | Jermaine Johnson II | 11/32 |
| 130 | `h_dtm_day2` | Name a player the Lions drafted in rounds 2-4 since 2000 who made a Pro Bowl | 13 | 1 | Darius Slay | Brian Branch | 13/32 |
| 131 | `h_dtm_ap` | Name a player the Ravens drafted since 2000 who was an All-Pro | 16 | 1 | Lamar Jackson | Jordan Stout | 6/32 |

## Draft careers (6)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 132 | `h_dk_qb_yds` | Name a QB drafted since 2000 with 30,000+ career passing yards | 23 | 2 | Tom Brady | Ryan Fitzpatrick | 1/1 |
| 133 | `h_dk_rb_yds` | Name a RB drafted since 2000 with 8,000+ career rushing yards | 19 | 1 | LaDainian Tomlinson | Willis McGahee | 1/1 |
| 134 | `h_dk_wr_yds` | Name a WR drafted since 2000 with 10,000+ career receiving yards | 21 | 2 | Reggie Wayne | Amari Cooper | 1/1 |
| 135 | `h_dk_te_yds` | Name a TE drafted since 2000 with 5,000+ career receiving yards | 20 | 2 | Travis Kelce | Marcedes Lewis | 1/1 |
| 136 | `h_dk_sacks` | Name a player drafted since 2000 with 100+ career sacks | 21 | 2 | Julius Peppers | Elvis Dumervil | 1/1 |
| 137 | `h_dk_int` | Name a player drafted since 2000 with 30+ career interceptions | 26 | 2 | Patrick Peterson | Anthony Henry | 1/1 |

## Playoffs (20)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 138 | `h_po_qb_yds` | Name a QB who threw for 375+ yards in a playoff game since 2000 | 17 | 1 | Tom Brady | Kelly Holcomb | 1/1 |
| 139 | `h_po_qb_td` | Name a QB who threw 4+ touchdown passes in a playoff game since 2000 | 20 | 2 | Tom Brady | Aaron Brooks | 1/1 |
| 140 | `h_po_rb_yds` | Name a RB who ran for 150+ yards in a playoff game since 2000 | 17 | 1 | Derrick Henry | Thomas Rawls | 1/1 |
| 141 | `h_po_wr_yds` | Name a WR with 160+ receiving yards in a playoff game since 2000 | 19 | 1 | Larry Fitzgerald | Chris Hogan | 1/1 |
| 142 | `h_po_te_yds` | Name a TE with 100+ receiving yards in a playoff game since 2000 | 17 | 1 | Travis Kelce | Vance McDonald | 1/1 |
| 143 | `h_po_td_game` | Name a player with 3+ rushing and receiving TDs in a playoff game since 2000 | 23 | 2 | Larry Fitzgerald | Sony Michel | 1/1 |
| 144 | `h_po_sack_game` | Name a defender with 3+ sacks in a playoff game since 2000 | 16 | 1 | Terrell Suggs | Kony Ealy | 1/1 |
| 145 | `h_po_qb_300_n` | Name a QB with 3+ playoff games of 300+ passing yards since 2000 | 16 | 1 | Tom Brady | Kurt Warner | 1/1 |
| 146 | `h_po_rb_100_n` | Name a RB with 2+ playoff games of 100+ rushing yards since 2000 | 25 | 2 | Frank Gore | Sony Michel | 1/1 |
| 147 | `h_po_qb_sum` | Name a QB with 2,500+ career playoff passing yards since 2000 | 16 | 1 | Tom Brady | Kurt Warner | 1/1 |
| 148 | `h_po_rb_sum` | Name a RB with 500+ career playoff rushing yards since 2000 | 23 | 2 | Frank Gore | Isiah Pacheco | 1/1 |
| 149 | `h_po_wr_sum` | Name a WR with 800+ career playoff receiving yards since 2000 | 16 | 1 | Larry Fitzgerald | Deion Branch | 1/1 |
| 150 | `h_po_te_sum` | Name a TE with 300+ career playoff receiving yards since 2000 | 23 | 2 | Jason Witten | Aaron Hernandez | 1/1 |
| 151 | `h_po_td_sum` | Name a player with 8+ career playoff rushing and receiving TDs since 2000 | 20 | 2 | Larry Fitzgerald | Damien Williams | 1/1 |
| 152 | `h_po_sack_sum` | Name a defender with 7+ career playoff sacks since 2000 | 23 | 2 | Michael Strahan | George Karlaftis | 1/1 |
| 153 | `h_po_int_sum` | Name a defender with 3+ career playoff interceptions since 2000 | 44 | 4 | Aeneas Williams | Cobie Durant | 1/1 |
| 154 | `h_po_dec_qb` | Name a QB who threw for 325+ yards in a playoff game of the 2010s | 21 | 2 | Tom Brady | Nick Foles | 3/3 |
| 155 | `h_po_dec_rb` | Name a RB who ran for 120+ yards in a playoff game of the 2010s | 19 | 1 | Derrick Henry | Thomas Rawls | 3/3 |
| 156 | `h_po_dec_wr` | Name a WR with 140+ receiving yards in a playoff game of the 2010s | 22 | 2 | Larry Fitzgerald | Jeff Janis | 3/3 |
| 157 | `h_po_dec_td` | Name a player who scored a rushing or receiving TD in 4+ playoff games of the 2010s | 26 | 2 | Tom Brady | John Kuhn | 3/3 |

## Super Bowls (12)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 158 | `h_sb_qb_played` | Name a QB who threw a pass in a Super Bowl since 2000 | 33 | 3 | Tom Brady | Kenny Pickett | 1/1 |
| 159 | `h_sb_qb_won` | Name a QB who threw a pass in a Super Bowl win since 2000 | 18 | 1 | Tom Brady | Kenny Pickett | 1/1 |
| 160 | `h_sb_qb_lost` | Name a QB who threw a pass in a Super Bowl loss since 2000 | 21 | 2 | Tom Brady | Rex Grossman | 1/1 |
| 161 | `h_sb_qb_yds` | Name a QB who threw for 275+ yards in a Super Bowl since 2000 | 16 | 1 | Tom Brady | Nick Foles | 1/1 |
| 162 | `h_sb_pass_td` | Name a QB who threw a touchdown pass in a Super Bowl since 2000 | 27 | 2 | Tom Brady | Rex Grossman | 1/1 |
| 163 | `h_sb_td_dec` | Name a player who scored a rushing or receiving TD in a Super Bowl of the 2010s | 42 | 4 | Frank Gore | Chris Matthews | 3/3 |
| 164 | `h_sb_rec_yds` | Name a player with 110+ receiving yards in a Super Bowl since 2000 | 16 | 1 | Larry Fitzgerald | Chris Hogan | 1/1 |
| 165 | `h_sb_sack_dec` | Name a defender who sacked the QB in a Super Bowl of the 2000s | 30 | 3 | Dwight Freeney | Jay Alford | 3/3 |
| 166 | `h_sb_int` | Name a defender who intercepted a pass in a Super Bowl win since 2000 | 33 | 3 | Derrick Brooks | Cooper DeJean | 1/1 |
| 167 | `h_sb_k` | Name a kicker who made a field goal in a Super Bowl since 2000 | 27 | 2 | Adam Vinatieri | Jake Moody | 1/1 |
| 168 | `h_sb_rb_champ` | Name a RB who carried the ball 5+ times in a Super Bowl win since 2000 | 35 | 3 | Marshawn Lynch | Bernard Pierce | 1/1 |
| 169 | `h_sb_wr_champ` | Name a receiver (WR, TE or RB) with 60+ receiving yards in a Super Bowl win since 2000 | 36 | 3 | Reggie Wayne | Malcolm Mitchell | 1/1 |

## Team history (10)

| # | key | wording on 2026-11-17 | answers | tier-6 | obvious (tier 1) | rare (tier 6) | variants passing |
|---|-----|------|--------|--------|------|------|------|
| 170 | `h_t_rb` | Name a RB who ran for 400+ yards in a season for the Colts since 2000 | 12 | 1 | Frank Gore | Kenton Keith | 30/32 |
| 171 | `h_t_wr` | Name a WR with 700+ receiving yards in a season for the Saints since 2000 | 16 | 1 | Brandin Cooks | Robert Meachem | 31/32 |
| 172 | `h_t_qb` | Name a QB who threw for 1,000+ yards in a season for the Dolphins since 2000 | 15 | 1 | Ryan Tannehill | Ray Lucas | 16/32 |
| 173 | `h_t_te` | Name a TE with 250+ receiving yards in a season for the Broncos since 2000 | 17 | 1 | Owen Daniels | Matt LaCosse | 22/32 |
| 174 | `h_t_sacks` | Name a defender with 7+ sacks in a season for the Saints since 2000 | 16 | 1 | Cameron Jordan | Bryan Bresee | 32/32 |
| 175 | `h_t_int` | Name a defender with 3+ interceptions in a season for the Lions since 2000 | 25 | 2 | Dre' Bly | Jerry Jacobs | 32/32 |
| 176 | `h_t_td` | Name a player with 8+ rushing and receiving TDs in a season for the Giants since 2000 | 16 | 1 | Tiki Barber | Andre Brown | 32/32 |
| 177 | `h_t_c_rush` | Name a player with 1,000+ rushing yards for the Falcons since 2000 | 15 | 1 | Matt Ryan | Jerious Norwood | 22/32 |
| 178 | `h_t_c_rec` | Name a player with 1,500+ receiving yards for the Texans since 2000 | 13 | 1 | Andre Johnson | Jordan Akins | 32/32 |
| 179 | `h_t_c_sacks` | Name a defender with 15+ sacks for the Chiefs since 2000 | 13 | 1 | Jared Allen | Michael Danna | 30/32 |

## Appendix: scoped templates (variants passing; failing variants are never offered)

- `h_dec_qb_yds`: 3/3 pass, answers 17-20
- `h_dec_qb_td`: 3/3 pass, answers 16-18
- `h_dec_qb_rush`: 3/3 pass, answers 15-19
- `h_dec_rb_yds`: 3/3 pass, answers 16-22
- `h_dec_rb_td`: 3/3 pass, answers 15-19
- `h_dec_rb_rec`: 3/3 pass, answers 15-18
- `h_dec_wr_yds`: 3/3 pass, answers 19-31
- `h_dec_wr_rec`: 3/3 pass, answers 16-22
- `h_dec_wr_td`: 3/3 pass, answers 15-20
- `h_dec_te_yds`: 3/3 pass, answers 15-17
- `h_dec_sacks`: 3/3 pass, answers 17-20
- `h_dec_int`: 3/3 pass, answers 17-26
- `h_dt_qb_yds`: 3/3 pass, answers 15-18
- `h_dt_qb_td`: 3/3 pass, answers 17-20
- `h_dt_rb_yds`: 3/3 pass, answers 17-20
- `h_dt_wr_yds`: 3/3 pass, answers 17-24
- `h_dt_te_yds`: 3/3 pass, answers 24-29
- `h_dt_sacks`: 3/3 pass, answers 15-20
- `h_dt_int`: 3/3 pass, answers 20-25
- `h_g_qb_td`: 3/3 pass, answers 17-28
- `h_g_wr_td`: 3/3 pass, answers 21-47
- `h_d_slot`: 32/32 pass, answers 26-26
- `h_d_top5_dec`: 3/3 pass, answers 30-50
- `h_d_year_r1`: 26/26 pass, answers 31-32
- `h_d_year_pb`: 24/26 pass, answers 15-31; fail: 2024, 2025
- `h_d_top10_pos`: 7/8 pass, answers 15-37; fail: TE
- `h_d_round`: 6/6 pass, answers 15-32
- `h_d_late_pos`: 6/8 pass, answers 12-28; fail: QB, TE
- `h_d_r1_pos`: 7/8 pass, answers 15-20; fail: TE
- `h_d_r1_dec_qb`: 3/3 pass, answers 16-26
- `h_d_r1_dec_rb`: 2/3 pass, answers 16-16; fail: 2020s
- `h_d_r1_dec_wr`: 3/3 pass, answers 32-43
- `h_d_r12_dec_te`: 3/3 pass, answers 17-30
- `h_d_r1_dec_ol`: 2/3 pass, answers 15-18; fail: 2020s
- `h_d_r1_dec_dl`: 2/3 pass, answers 16-23; fail: 2020s
- `h_d_r1_dec_lb`: 3/3 pass, answers 16-17
- `h_d_r1_dec_db`: 3/3 pass, answers 15-28
- `h_d_late_dec`: 2/3 pass, answers 20-49; fail: 2020s
- `h_dc_pb`: 14/44 pass, answers 15-23; fail: Michigan, Florida, Clemson, Auburn, Oregon, Virginia Tech, Stanford, Texas A&M, UCLA, South Carolina, Nebraska, North Carolina, Arkansas, California, Washington, Mississippi, Michigan St., Utah, Pittsburgh, TCU, Louisville, North Carolina St., Arizona St., Mississippi St., Maryland, Kansas St., Missouri, Purdue, Oregon St., West Virginia
- `h_dc_r1`: 23/44 pass, answers 12-35; fail: Virginia Tech, Stanford, UCLA, South Carolina, Nebraska, Arkansas, California, Michigan St., Utah, Pittsburgh, TCU, Louisville, North Carolina St., Arizona St., Mississippi St., Maryland, Kansas St., Missouri, Purdue, Oregon St., West Virginia
- `h_dc_def`: 31/44 pass, answers 18-49; fail: Ohio St., LSU, Georgia, USC, Michigan, Florida, Clemson, Oklahoma, Texas, Miami (FL), Notre Dame, Florida St., Penn St.
- `h_dc_off`: 34/44 pass, answers 15-50; fail: Ohio St., LSU, Georgia, USC, Michigan, Florida, Notre Dame, Florida St., Wisconsin, Oregon
- `h_dc_late`: 13/44 pass, answers 36-50; fail: Alabama, Ohio St., LSU, Georgia, USC, Michigan, Florida, Clemson, Oklahoma, Texas, Miami (FL), Notre Dame, Florida St., Auburn, Penn St., Wisconsin, Oregon, Tennessee, Iowa, Virginia Tech, Stanford, Texas A&M, UCLA, South Carolina, Nebraska, North Carolina, Arkansas, California, Michigan St., Pittsburgh, TCU
- `h_dtm_pb`: 32/32 pass, answers 12-30
- `h_dtm_r1`: 32/32 pass, answers 20-34
- `h_dtm_r1_pb`: 11/32 pass, answers 12-15; fail: ARI, CHI, CIN, CLE, DEN, GB, IND, JAX, KC, LA, LV, MIA, NE, NO, NYG, PHI, PIT, SEA, SF, TB, TEN
- `h_dtm_day2`: 13/32 pass, answers 12-16; fail: ATL, BUF, CAR, CIN, CLE, DEN, IND, JAX, LA, LV, MIA, MIN, NE, NYG, NYJ, SEA, SF, TB, WAS
- `h_dtm_ap`: 6/32 pass, answers 12-16; fail: ARI, ATL, BUF, CHI, CIN, CLE, DEN, DET, GB, HOU, IND, JAX, LA, LAC, LV, MIA, MIN, NO, NYG, NYJ, PHI, PIT, SEA, TB, TEN, WAS
- `h_po_dec_qb`: 3/3 pass, answers 19-21
- `h_po_dec_rb`: 3/3 pass, answers 15-19
- `h_po_dec_wr`: 3/3 pass, answers 17-22
- `h_po_dec_td`: 3/3 pass, answers 19-26
- `h_sb_td_dec`: 3/3 pass, answers 22-42
- `h_sb_sack_dec`: 3/3 pass, answers 24-36
- `h_t_rb`: 30/32 pass, answers 12-19; fail: CIN, JAX
- `h_t_wr`: 31/32 pass, answers 12-18; fail: HOU
- `h_t_qb`: 16/32 pass, answers 12-17; fail: ATL, BAL, CIN, DAL, DET, GB, HOU, JAX, KC, LAC, NE, NO, NYG, PHI, PIT, SEA
- `h_t_te`: 22/32 pass, answers 12-17; fail: ATL, BUF, CAR, CHI, DAL, JAX, KC, PHI, PIT, SF
- `h_t_sacks`: 32/32 pass, answers 15-23
- `h_t_int`: 32/32 pass, answers 15-31
- `h_t_td`: 32/32 pass, answers 15-22
- `h_t_c_rush`: 22/32 pass, answers 12-17; fail: BUF, CAR, IND, JAX, KC, LA, LAC, NYG, NYJ, WAS
- `h_t_c_rec`: 32/32 pass, answers 13-23
- `h_t_c_sacks`: 30/32 pass, answers 12-20; fail: CLE, HOU

## Notes (read before approving)

**Data and seasons.** Regular season and postseason weekly player stats from nflverse `stats_player_week_<year>` for every season 2000 through the last finished season (2025 today; the in-progress 2026 season is never counted so answers do not change week to week). Draft picks from nflverse `draft_picks` for drafts 2000-2025 (the 2026 class has not played a season). Super Bowl winners/losers from the nflverse schedule (`nfl_data_py.import_schedules`). First run downloads 26 weekly files (about 0.5-1.5 s each, roughly 15-25 s total, about 13 s measured) and trims them into `data_cache/daily_drive/hist_week_v1_<year>.parquet` (kept forever, finished seasons never change); later runs read only those caches. If any season file or the draft table cannot be read the whole history pool returns no prompts rather than a pool with a gap.

**Nothing before 2000.** Every data-driven prompt says "since 2000" or names a 2000s / 2010s / 2020s decade or a 2000+ draft class, and the tests assert no template text can render a pre-2000 year and no loader reads a pre-2000 season. Career totals count only seasons since 2000 (a player who started in the 1990s is a valid answer on the strength of his 2000+ numbers alone; the wording "since 2000" says so). Draft-career prompts ("a QB drafted since 2000 with 30,000+ career passing yards") are clean: every season of those careers is 2000 or later. Players drafted before 2000 can be answers to stat prompts (Brett Favre's 2000s seasons, for instance); only the draft prompts are limited to 2000+ drafts. "Rookie" means the season of the draft year, so drafted players only.

**Hall of Fame / All-Pro / Pro Bowl** come only from the draft table's `hof`, `allpro` and `probowls` columns, so undrafted players can never be answers to a flag-based prompt (Kurt Warner-type players simply have no flags there). Stat-based prompts (season marks, career totals, games, playoffs, Super Bowls) do include undrafted players. Only 19 players drafted since 2000 carry the HoF flag, so there is one HoF prompt. The table's `car_av` is empty for 2000+ drafts, so the fame signal uses weighted AV (`w_av`).

**Fame and tiers use the same three-signal path as the current pool** (`dd.pick_threshold` -> `dd._answers_at` -> `fame_scores` -> `rank_and_tier`): career points, Approximate Value, current consensus rank. Because defenders and kickers score ~0 fantasy points, their "career" signal is a frozen 2000+ production score (sacks, interceptions, forced fumbles, defensive TDs, tackles, FG/PAT) so an undrafted star is not buried; AV comes from the whole draft table (1980-2026) so a 1990s draftee with 2000s seasons is not mistaken for an obscure answer. Fame is relative inside each answer set, so a household name can still land in tier 6 when the set is full of bigger names (for example the last tier-6 name in a 4,700-yard list). Tier-6 is always at least the bottom 10% of the set.

**Verification.** I spot-checked real numbers against what I know: Strahan 22.5 sacks (2001), Manning 5,477 yards / 55 TDs (2013), Calvin Johnson 1,964 (2012), LaDainian Tomlinson 28 rushing TDs (2006), Brady 50 TDs (2007), Vinatieri 490 FG since 2000, and nflverse career passing yards for retired QBs drafted since 2000 agree with Pro Football Reference to within about 70 yards over whole careers. nflverse is play-by-play based, so single-season numbers can differ from the official gamebook by a handful of yards (Drew Brees 2011 shows 5,535 against the official 5,476): a player within a few dozen yards of a threshold could be on the wrong side of it. **Unverified:** I did not check every answer of every prompt against an independent source; the answers are exactly what nflverse says.

**Known limits and judgement calls.**
- Defensive stat coverage in the early 2000s: sacks matched official totals in my spot check (Strahan 22.5 in 2001) but I could not independently audit interceptions / forced fumbles / defensive TDs for every early season, and tackle counts looked less certain, so no tackle-based prompt is used.
- Games table keeps only games clearing a floor (for example 100 rushing yards, 250 passing yards); every game template's lowest rung is at or above its floor (a test enforces it).
- Super Bowls are the last postseason week of a season; QB prompts say "threw a pass in" rather than "won/lost/played in" because that is what the data proves (a backup who never threw is not detectable).
- A few answers are people some owners may not want in a game (for example a convicted former player appears in a playoff TE list). The pool does not filter on character; say if you want a name blocklist.
- Team-scoped prompts use low rungs (for example 400+ rushing yards for one team) when a franchise has too few big seasons; they are valid but easy, and a few sit at 12-14 answers.
- Rotating scopes: 64 of the templates rotate college / team / position / round / pick slot / draft class / decade by date. The date picks an order and the first scope that passes is used.
- Timing: the full pool (179 templates) builds in about 1.0-1.5 s once the tables are loaded; loading the cached tables takes about 1-4 s depending on machine load. Resident memory grows by roughly 150-200 MB while building (the tables are about 80 MB; the rest is transient); `history_candidates` releases the tables afterwards unless `keep_context=True`. Worth knowing for the Render Starter instance.
- Not wired in: `day_counts` / `N_FANTASY` / `N_HISTORY` / `HISTORY_ENABLED` untouched.
