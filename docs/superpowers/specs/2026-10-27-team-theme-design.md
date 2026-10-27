# Favorite-team theme

Status: design approved in chat (option A: colors + atmosphere + interactions). Awaiting spec review.

## Goal

In Settings the user picks a favorite NFL team and the whole interface becomes a polished, professional
theme of that team. The default (no team) stays exactly as today.

Success looks like:
- Pick a team and every screen visibly re-themes within a second, with a short "kickoff" sweep.
- It still looks like Lineup Lab: same layout, same data, same semantics. Only the identity changes.
- It is readable. Every team palette passes the contrast rules below, checked by a test.
- It is instant and flash-free on reload, works signed-out, and follows the account when signed in.
- Nothing animates for users who prefer reduced motion.

## Non-goals

Per-team fonts, a light mode, sounds, hosting any new image files, team-specific layouts or motifs (option B),
and any change to data, projections or navigation.

## What it builds on

- The look is driven by CSS custom properties on `:root` in `static/style.css` (surfaces, accent, glows,
  borders). Components read only those, so remapping them restyles everything with no markup change.
- `user_settings.theme` already exists (`engine/db.py` `PLAIN_SETTINGS_FIELDS`, `server.py` `SettingsUpdate`) and
  nothing reads it. It will hold the team code, so no migration is needed.
- `TEAM_COLORS` / `teamThemeStyle()` in `static/app.js` tint player cards with one color per team. It stays, and
  reads from the new palette table so the two can never disagree.
- CSP is `script-src 'self'` (no inline script), `img-src 'self' https: data:`. The no-flash boot step must be an
  external file. Team logos are `https` images from `a.espncdn.com`, which is already used by the news cards and is
  on the image proxy's allowlist.

## Design

### 1. Palettes (`static/team-themes.js`, one data table, 32 teams)

The file is `window.TEAM_THEMES = { ...strict JSON... };`: quoted keys, no trailing commas, no computed values, so the
Python tests can `json.loads` the object literal and check it without a JS runtime. `onPrimary` is therefore stored,
and the contrast test proves it is the better of black or white for that primary.

Each team: `code`, `name`, `city`, `division`, and
`primary` (the accent, tuned to read on a dark surface), `secondary`, `deep` (a very dark team-tinted background),
`onPrimary` (text color placed on top of `primary`: black or white, whichever contrasts more), and `logo` (ESPN URL, or null).

Derived variables set on `<html data-team="DET">` by `applyTeam(code)`:

| Variable | From |
|---|---|
| `--accent`, `--accent-dim`, `--accent-glow`, `--brand` | primary |
| `--border-bright` | primary at low alpha |
| `--bg`, `--panel`, `--panel-2`, `--panel-glass` | `deep` blended up in steps, so surfaces carry a faint team tint |
| `--violet`, `--info` | secondary (decorative highlights only) |
| `--tm`, `--tm-rgb` | primary (existing player-card tint) |
| `--on-accent` | computed readable text color for filled buttons and badges |

Semantic colors are never themed: `--pos`, `--neg`, `--avg`, `--tough` keep their meaning (green start, red sit,
amber caution) so a red or green team can't make "sit this player" look like "start him".

### 2. Atmosphere

- A themed hero band at the top of the content area: team logo, city and name in the team's colors, and a slow
  animated gradient with faint yard-line stripes behind it (CSS only, no canvas). It is the same element on every
  tab, kept short so it doesn't push content down on phones (collapses to a slim bar under 560px).
- Page background: a team-tinted radial gradient behind `--bg`, fixed, very low contrast.
- "Kickoff" sweep when a team is picked: a one-time diagonal wipe in primary then secondary across the viewport
  (about 700 ms), then it is gone.

### 3. Interactions

- Cursor-following glow on cards: `pointermove` sets `--mx/--my` on the hovered `.card`-type surface and a
  radial highlight reads them. Throttled with `requestAnimationFrame`; pointer devices only.
- Existing hover-lift gets the team glow (`--shadow-glow` already reads `--accent-glow`).
- Tab changes: a thin team-colored progress/wipe line along the top of the content, reusing the existing tab
  switch hook.
- Loaders and skeleton shimmer pick up the accent automatically.
- All of it is wrapped so `prefers-reduced-motion: reduce` disables animation (static colors and the logo remain).

### 4. Picker (Settings)

A "Favorite team" block, visible to everyone (signed out too), above the account block:
- 32 teams in division groups (AFC/NFC East, North, South, West), each a logo chip with the team abbreviation.
  If a logo fails to load the chip shows the abbreviation on the team color.
- Hover or keyboard focus previews the theme live and restores on leave; click or Enter commits.
- A "Default" chip restores the Lineup Lab look. The picked team is announced to screen readers
  (`aria-pressed`, a polite live region).
- Roving-tabindex arrow-key navigation within the grid.

### 5. Persistence

- `localStorage["eb_team"]` holds the code. It is applied immediately.
- `static/theme-boot.js` is a tiny external script in `<head>` (before the stylesheet paints) that reads it and sets
  `data-team` plus the palette variables synchronously, so there is no flash of the default theme. It also updates
  `<meta name="theme-color">`.
- Signed in: choosing a team also `POST /api/settings {theme: "DET"}`. On load, if the account has a theme and the
  browser has none (new device), the account value is applied and cached. If both exist the most recent choice wins
  (the browser's, since it was set on this device).
- Server validates `theme` against the 32 codes (or empty). Unknown values are rejected with 400, so the field can't
  carry arbitrary text into a stored value that is later put into a `style` attribute.
- Defensive storage: every read and write is wrapped in try/catch (private mode, blocked storage).

### 6. Safety rules

- Palette values only ever come from the static table, never from the user or the server response, so nothing
  user-controlled reaches a `style` attribute or CSS.
- The service worker `SHELL` list gets the two new files; the cache name is bumped so existing installs update.

## Testing

- Unit (Python, `json.loads` of the object literal in `static/team-themes.js`): 32 teams, unique codes, every
  field present, hex valid, every division has 4 teams.
- Contrast test (Python, WCAG formula): for every team, `primary` on `panel` >= 4.5:1 (text accents) and `onPrimary`
  on `primary` >= 4.5:1; `deep` surfaces keep `--text` on `--panel` >= 7:1 and `--muted` on `--panel` >= 4.5:1.
  A team that fails gets its palette adjusted, not the threshold.
- Server: `theme` accepts the 32 codes and empty, rejects anything else; round-trips through get/update.
- Browser (Playwright, contact sheet of all 32 teams on Big Board, My Team, News): no console errors, picker
  hover-preview restores on leave, reload keeps the team with no flash (first computed `--accent` already the team's),
  reduced-motion disables the sweep and hero animation, and the default theme is pixel-identical to today when no
  team is chosen.
- Existing suite stays green.

## Risks and how they're handled

- Dark, low-chroma team colors (black/navy teams): `primary` is the brighter secondary or a lifted tint, never a
  color that fails contrast; the test enforces it.
- Perceived re-brand of a trademarked identity: colors and logos are used as a user-chosen cosmetic theme, logos are
  loaded from ESPN's CDN (not hosted), and the existing "Not affiliated with the NFL" footer stays visible.
- Performance on low-end phones: no canvas or JS animation loop. The cursor glow is pointer-only and rAF-throttled;
  the hero gradient is a CSS transform/opacity animation on a single layer.
- Specificity clashes: theme variables are set on `html[data-team]` so they override `:root` without touching any
  component rule.

## Out of scope for this change

Team-specific motifs (option B), a light theme, sound, and theming the emails.
