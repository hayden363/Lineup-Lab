# Lineup Lab — iOS app (Capacitor)

A thin native iPhone shell around the live web app (`https://lineup-lab-awdv.onrender.com`).
Same server, same Supabase accounts, same data as the website — a web deploy updates
the app instantly, no App Store release needed (only native changes need one).

What's native: app icon, launch screen, status bar, haptic taps (`@capacitor/haptics`),
share sheet and in-app browser plugins installed (`@capacitor/share`, `@capacitor/browser`),
an offline screen when there's no connection. Google sign-in is hidden inside the app
(Google blocks it in embedded web views); email + password works the same as on the web.

## One-time setup (you)
1. Install **Xcode** from the Mac App Store (free, ~12 GB), open it once and accept the license.
2. Join the **Apple Developer Program** ($99/yr): https://developer.apple.com/programs/enroll/
   (approval can take up to 48 h). Needed for TestFlight and the App Store.
3. In a terminal: `cd mobile && npm install && npx cap sync ios && npx cap open ios`

## Run on your iPhone / simulator
In Xcode: select the **App** target → *Signing & Capabilities* → tick *Automatically manage
signing* and pick your Team. Change the bundle identifier if you want
(currently `com.kirbycove.lineuplab`; it must match `appId` in `capacitor.config.json` and
the App Store Connect record). Pick a simulator or your plugged-in iPhone and press ▶.

## Ship to the App Store
1. App Store Connect → *My Apps* → **+** → New App (name "Lineup Lab", bundle ID above, SKU any).
2. Fill the listing from `APP_STORE_LISTING.md`.
3. Xcode → set the device to *Any iOS Device (arm64)* → **Product ▸ Archive** → *Distribute App*
   → *App Store Connect*. Test it first through TestFlight.
4. Add screenshots (see the listing file), a **demo account** in App Review notes, submit for review.

## Changing things
- App URL / name / colors: `capacitor.config.json`, then `npx cap sync ios`.
- Bump `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` in Xcode for every upload.
- Not done yet (needs the paid developer account): push notifications (APNs key) and native
  Sign in with Apple. Apple requires Sign in with Apple only if the app offers other
  social logins — it doesn't today, since Google is hidden in-app.
