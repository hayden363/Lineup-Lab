# Lineup Lab: App Store listing (version 1.0)

Paste-ready. Character limits from App Store Connect are in brackets.

## App information
- **Name** [30]: `Lineup Lab: Fantasy Football` (28)
- **Subtitle** [30]: `Start/Sit + Daily NFL Trivia` (28)
- **Bundle ID**: com.haydenjohnstonwoods.lineuplab · **SKU**: `lineuplab-ios-1`
- **Primary category**: Sports · **Secondary**: Games › Trivia
- **Content rights**: does not contain third-party content requiring rights beyond public NFL statistics and the app's own
  analysis (data from nflverse; player headshots from the NFL's public CDN, as on the website).
- **Age rating answers**: no violence, no mature themes, no gambling or simulated gambling, no contests with prizes, no
  user-generated content beyond League Chat (private to a connected league, with report/mute) → expected rating 4+
  (12+ if Apple counts League Chat as unrestricted messaging; answer "Messaging and chat: Yes, private to a league").
- **Price**: Free · **Availability**: United States first (all territories later).

## Version 1.0 text

**Promotional text** [170]
> New every day at midnight ET: The Daily Drive, 7 NFL trivia plays where the rarer your answer, the bigger the play. Then
> let the same data set your fantasy lineup.

**Description** [4000]
> Lineup Lab is two things built on the same real NFL data: a daily football game you'll want to play every morning, and
> a fantasy football lab that sets your lineup.
>
> THE DAILY DRIVE
> Seven NFL trivia plays a day, easiest first. Name a player who fits each prompt. Name the star and pick up a few yards;
> name the guy nobody remembers and it's a 100-yard Highlight Reel TD. Every answer comes from real NFL data.
> • A new drive every day at midnight Eastern
> • Daily streaks and a daily leaderboard
> • Share your drive with friends, spoiler-free
> • Free, and you can play without an account
>
> FANTASY TOOLS FOR YOUR LEAGUE
> Connect your Sleeper or ESPN league in about 30 seconds and Lineup Lab works on your real roster.
> • Start/Sit: who to play this week, with the matchup and weather behind every call
> • Waivers: the pickups that beat your bench
> • Trade analysis: offers that actually raise your playoff odds
> • Live scores for your players during every game
> • Big Board: rest-of-season rankings
> • League Chat with your leaguemates
>
> OUR OWN NUMBERS
> Matchups are graded on what each defense allows to each position, backtested on five seasons of real games, not
> copied from a points-allowed chart.
>
> Lineup Lab is not affiliated with the NFL, Sleeper or ESPN. Fantasy advice only; no betting.

**Keywords** [100]: `fantasy,football,nfl,start sit,waiver,trade,sleeper,espn,trivia,daily,lineup,projections,draft`

**Support URL**: https://lineup-lab-awdv.onrender.com/support
**Marketing URL**: https://lineup-lab-awdv.onrender.com/welcome
**Privacy Policy URL**: https://lineup-lab-awdv.onrender.com/legal/privacy
**Copyright**: `2026 Hayden Finley Johnston Woods`

## App Review information
- **Sign-in required**: yes, for fantasy tools (The Daily Drive works without an account).
- **Demo account**: created on production for Apple (username/password go in App Store Connect only, never in git).
  It has a public Sleeper league connected so every tab has real data.
- **Notes for the reviewer**:
  > Lineup Lab has two parts. The Daily Drive (first tab, also on the welcome screen without signing in) is a free daily
  > NFL trivia game. The fantasy tools (My Team, Start/Sit, News, More) need an account and a connected fantasy league;
  > the demo account already has a public Sleeper league connected.
  > Sign in with Apple, Google and email are all supported. Account deletion: More → Delete account.
  > Push notifications: one optional daily reminder that today's Daily Drive is live, only if not yet played; it can be
  > turned off under More → Notifications.
  > ESPN leagues: private ESPN leagues can be connected by pasting the user's own ESPN cookies (explained in-app); this is
  > read-only and encrypted at rest. The demo account uses a public Sleeper league instead.
  > No gambling: betting lines are only used as an input to projections.

## App Privacy answers ("Data Types")
Data linked to the user, used for **App Functionality** only, **not used for tracking**:
- Contact Info → **Email Address** (account, sign-in, password reset)
- Identifiers → **User ID** (account). The push token is used only to deliver the notifications the user turned on;
  check Apple's current form wording when filling it in.
- User Content → **Gameplay Content** (Daily Drive scores), **Other User Content** (League Chat messages)
- Usage Data: **no** (no analytics SDKs)
- Tracking: **No**

## Screenshots needed
- iPhone 6.9" (1320 × 2868): welcome, Daily Drive in play, Daily Drive results, Start/Sit, My Team
- iPad 13" (2064 × 2752): same five
