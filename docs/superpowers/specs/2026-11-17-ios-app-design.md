# Lineup Lab for iPhone and iPad — design

Date: 2026-11-17 · Owner: Hayden · Status: approved 2026-11-17 (owner: "go"); building

## Goal
Lineup Lab on the App Store as soon as possible, for iPhone and iPad, without rebuilding the product. The app shows the
live web app inside native screens and adds native features that make it a real app (and pass Apple's review).

## Decisions already made (owner)
- Native Swift shell + native extras (not Capacitor, not a rewrite).
- iPhone and iPad in version 1.
- Apple Developer Program membership is active.

## What the app is
A SwiftUI app with a native tab bar. Each tab is a `WKWebView` showing a page of https://lineup-lab-awdv.onrender.com.
All tabs share one cookie store, so signing in once signs in everywhere. Web changes reach the app instantly; only native
changes need a new App Store build.

Tabs (iPhone bottom bar; iPad sidebar via `TabView` sidebar style):
1. **The Daily Drive** → `/play` (first: it is the daily habit and the way in)
2. **My Team** → `/?tab=myteam`
3. **Start/Sit** → `/?tab=startsit`
4. **News** → `/?tab=news`
5. **More** (native list): NFL Games, Waivers, Trade, Big Board, League Chat, Settings, Privacy, Terms, Support, Sign out,
   Delete account

When the page is loaded inside the app, the web hides its own sidebar and top bar (the native tab bar replaces them).
The app identifies itself with a user-agent suffix `LineupLabApp/<version>`; the web adds `body.in-app` and honours
`?tab=`.

## Native features (why it is more than a website)
| Feature | How | Server work |
|---|---|---|
| **Sign in with Apple** (required by Guideline 4.8 because Google sign-in is offered) | `AuthenticationServices`; the app sends Apple's identity token to the server | `POST /api/auth/apple`: verify the token against Apple's public keys (PyJWT + cryptography, already installed), find or create the user, start a session; the app puts the session cookie into the web views |
| **Google sign-in** | Google blocks sign-in inside embedded web views, so the app opens it in `ASWebAuthenticationSession` | `/api/auth/google/start?app=1` ends with a redirect to `lineuplab://auth?code=…` (one-time, 60-second code); `POST /api/auth/app-exchange` turns the code into a session |
| **Push notifications** | APNs; the app registers its device token after the user allows it | `POST /api/push/register`; a sender using an APNs auth key (.p8). Version 1 sends **Daily Drive is live** (once a day at 11am ET, only if not played, can be turned off). **Lineup-alert pushes move to 1.1**: the bell's alerts are computed in the browser from each user's roster, so a server push needs a roster job first |
| **Native share** | Daily Drive results open the iOS share sheet (`window.webkit.messageHandlers.share`) | none |
| **Haptics** | a tap on each Daily Drive play result | none |
| **Offline screen** | a native "you're offline, try again" view instead of a browser error | none |

## App Store requirements and how each is met
- **Account deletion in the app** (5.1.1(v)): already exists (`/api/auth/delete-account`, works for Google-only accounts);
  More → Delete account opens it. Sign in with Apple accounts must also be deletable (same endpoint, no password).
- **Privacy policy / terms**: already live at `/legal/privacy` and `/legal/terms`.
- **Support URL**: new `/support` page (contact email, FAQ).
- **Privacy labels**: email address, user ID, fantasy league IDs, usage data; no tracking, no ads.
- **Age rating**: 4+ style content, no gambling (fantasy advice and a trivia game; betting lines are only an input).
- **Icon**: `static/icons/source2.png` (1024×1024, no transparency).
- **Screenshots**: captured from the simulator: iPhone 6.9" and iPad 13".
- **Reviewer account**: a test account on production with a connected sample league, given to Apple in the review notes
  (owner approves creating it).

## Build and tooling
- `ios/` folder in the repo: `project.yml` (XcodeGen) + Swift sources. XcodeGen generates the Xcode project, so the project
  file is never hand-edited.
- Needs on this Mac: **Xcode** (owner installs from the Mac App Store), **XcodeGen** (one binary from its official GitHub
  release; owner approves the download).
- Bundle ID `com.haydenjohnstonwoods.lineuplab` (com.lineuplab.app was taken), display name **Lineup Lab**, iOS 17+.
- Signing: automatic signing with the owner's team, done in Xcode after the owner signs in.

## Steps
1. Web: `in-app` mode (`LineupLabApp` user agent → hide sidebar/top bar, `?tab=`), `/support` page.
2. Server: Sign in with Apple, Google app hand-off, push registration + sender, Daily Drive reminder job. Tests.
3. iOS app: tabs, shared cookies, sign-in screens, push registration, share/haptics bridge, offline view, iPad sidebar.
4. Run in the simulator (iPhone + iPad), fix, capture screenshots.
5. App Store Connect (owner present): create the app record, APNs key, privacy answers, metadata, reviewer account.
6. Archive and upload a build → TestFlight → owner tries it on his phone → submit for review.

Nothing is pushed to the live site and nothing is submitted to Apple without the owner's yes at that step.

## Out of scope for version 1
Home-screen widgets, Apple Watch, in-app purchases (plans are still a waitlist), offline data.

## Risks
- **Review rejection under 4.2 (minimum functionality)**: mitigated by native tabs, Sign in with Apple, push, share; if
  rejected, a home-screen widget (Daily Drive streak) is the next native feature.
- **ESPN cookie entry** (users paste ESPN cookies to connect private leagues) may draw reviewer questions: the review notes
  explain it; the reviewer account uses a public Sleeper league.
- **Render cold starts** make the first launch slow: the native launch screen shows while the first page loads.
