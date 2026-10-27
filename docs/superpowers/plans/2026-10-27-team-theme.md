# Favorite-Team Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pick a favorite NFL team in Settings and the whole interface takes on a polished, interactive theme of that team.

**Architecture:** One static palette table plus a small derivation engine (`static/team-themes.js`) sets CSS variables on `html[data-team]`, which remaps the existing design tokens. A tiny external boot script applies the saved team before first paint. A separate `static/theme.js` owns the picker, the hero band, the kickoff sweep and the cursor-glow/tab-wipe interactions. The choice is kept in `localStorage` and synced to the existing `user_settings.theme` field.

**Tech Stack:** Vanilla JS and CSS (no build step), FastAPI/pydantic, pytest. Node (already installed) runs the JS engine inside pytest. Playwright (pre-installed in the sandbox, not a repo dependency) for the browser check.

**Spec:** `docs/superpowers/specs/2026-10-27-team-theme-design.md`

## Global Constraints

- Default look (no team chosen) must be unchanged: no variable is set, no element is rendered.
- Semantic variables are never themed: `--pos`, `--neg`, `--avg`, `--tough`, `--soft`.
- Palette values come only from the static table: never from user input or a server response.
- CSP is `script-src 'self'` (no inline script) and `img-src 'self' https: data:`: all new JS is an external file, logos are `https`.
- `localStorage` key is `eb_team`; the account field is `theme`; the value is a team code from the 32-team table, or empty.
- Every storage read/write is wrapped in try/catch.
- Everything animated is disabled under `prefers-reduced-motion: reduce`.
- Contrast: `primary` on derived `--panel` >= 4.5:1; `onPrimary` on `primary` >= 4.5:1; `--text` on `--panel` >= 7:1; `--muted` on `--panel` >= 4.5:1.
- Existing suite stays green.

## Review Focus

1. A saved team code that isn't in the table (renamed, removed, hand-edited) must fall back to the default theme without an error. (Task 2)
2. Storage blocked or throwing (private window, disabled storage): picking a team must still apply for the session and never throw. (Task 4)
3. A team whose color is close to a semantic color (Chiefs/Cardinals red, Packers/Seahawks green): the semantic variables must stay untouched under every team so start/sit meaning survives. (Task 2)
4. Rapid hover across picker chips: the preview must always restore the committed team on leave, and a click must commit exactly the clicked team. (Task 4)
5. A logo that fails to load (ESPN CDN blocked, offline): the chip and the hero fall back to the team abbreviation on the team color, with no broken-image icon. (Task 4, Task 5)

---

## File Structure

| File | Responsibility |
|---|---|
| `static/team-themes.js` (create) | `window.TEAM_THEMES` (32-team JSON table) and `window.TeamTheme` engine: `get`, `vars`, `apply`, `clear`, `current`, `valid` |
| `static/theme-boot.js` (create) | 10-line synchronous loader: read `eb_team`, call `TeamTheme.apply`. Loaded in `<head>` |
| `static/theme.js` (create) | picker, account sync, hero band, kickoff sweep, cursor glow, tab wipe |
| `static/style.css` (modify) | appended theme block: hero, backdrop, sweep, glow, picker, wipe, reduced-motion |
| `static/index.html` (modify) | head scripts, hero mount, picker mount, body script |
| `static/app.js` (modify) | `teamThemeStyle()` reads the table; settings load/tab-switch hooks into `theme.js` |
| `static/sw.js` (modify) | new files in `SHELL`, cache name bumped |
| `server.py` (modify) | `SettingsUpdate.theme` validated against the 32 codes |
| `tests/test_team_themes.py` (create) | palette validity, node-run engine tests, contrast |
| `tests/test_theme_setting.py` (create) | server validation and round-trip |
| `scripts/check_team_themes.js` (create) | manual Playwright contact sheet and behavior check |

---

### Task 1: Palette table

**Files:**
- Create: `static/team-themes.js` (table only in this task)
- Test: `tests/test_team_themes.py`

**Interfaces:**
- Produces: `window.TEAM_THEMES = { "<CODE>": { code, name, city, division, primary, secondary, deep, onPrimary, logo }, ... }` written as strict JSON (quoted keys, no trailing commas) so Python can `json.loads` the literal. `division` is e.g. `"NFC North"`. `logo` is `https://a.espncdn.com/i/teamlogos/nfl/500/<espn>.png` with ESPN's codes (`lar` for LA, `wsh` for WAS), same as `engine/news.py team_logo`.
- Test helper (in the test file): `load_themes() -> dict` extracting the object literal between `window.TEAM_THEMES =` and the closing `};`.

- [ ] **Step 1: Write the failing tests** in `tests/test_team_themes.py`: `test_32_teams_with_unique_codes`, `test_every_field_present_and_hex_valid` (`primary/secondary/deep/onPrimary` match `^#[0-9a-fA-F]{6}$`), `test_each_division_has_four_teams` (8 divisions), `test_codes_match_the_news_team_table` (same 32 codes as `engine.news._TEAMS`), `test_logo_urls_follow_the_news_logo_helper` (equals `engine.news.team_logo(code)`), `test_on_primary_is_the_higher_contrast_of_black_or_white` (WCAG relative luminance; helper `contrast(a, b) -> float` in the test file).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_team_themes.py -q`. Expected: FAIL (file missing).
- [ ] **Step 3: Create the table** for all 32 teams. `primary` is the accent tuned for a dark surface (start from the existing `TEAM_COLORS` in `static/app.js`, lift navy/black teams to their brighter color); `deep` is a very dark tint of the team hue (L about 5-7%); `onPrimary` is `#000000` or `#ffffff`, whichever contrasts more.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `static/team-themes.js tests/test_team_themes.py` as "Team palette table".

---

### Task 2: Derivation engine and boot

**Files:**
- Modify: `static/team-themes.js` (append the engine)
- Create: `static/theme-boot.js`
- Modify: `static/index.html` (two `<script>` tags in `<head>`, before the stylesheet link: `team-themes.js` then `theme-boot.js`), `static/sw.js`, `static/style.css` (primary buttons and badges use `var(--on-accent, <current color>)`)
- Test: `tests/test_team_themes.py` (node-driven)

**Interfaces:**
- Produces on `window.TeamTheme`: `valid(code) -> boolean`; `get(code) -> palette | null`; `vars(code) -> {"--accent": "#...", ...} | {}` (pure, no DOM; `{}` for an unknown code); `apply(code) -> boolean` (sets `data-team` and the vars on `document.documentElement`, updates `meta[name=theme-color]`; for an invalid/empty code it clears them and returns false); `clear()`; `current() -> code | ""`; `all() -> palette[]` in division order.
- `vars()` keys (exact): `--accent`, `--accent-dim` (primary mixed 18% toward black), `--accent-glow` (`rgba(primary, .38)`), `--brand` (= accent-dim), `--border-bright` (`rgba(primary, .28)`), `--bg` (= deep), `--panel` (deep mixed 7% toward white), `--panel-2` (11%), `--panel-glass` (`rgba(panel, .68)`), `--violet` and `--info` (secondary), `--violet-glow` and `--info-glow` (`rgba(secondary, .38)`), `--tm`, `--tm-rgb` (`"r,g,b"`), `--on-accent` (= onPrimary), `--team-secondary`.
- Test helper: `engine_vars() -> {code: vars}` runs `node` over `team-themes.js` in a `vm` context with a stub `window`/`document` and prints JSON; tests `pytest.skip` if `node` is not on PATH.

- [ ] **Step 1: Write the failing tests**: `test_unknown_or_empty_code_gives_no_vars_and_no_error` (`vars("XYZ")`, `vars("")`, `vars(null)` are `{}`; `apply("XYZ")` returns false), `test_semantic_variables_are_never_themed` (no team's `vars` contains `--pos`, `--neg`, `--avg`, `--tough`, `--soft`), `test_every_team_vars_has_the_exact_key_set`, and the four contrast tests from Global Constraints over `engine_vars()` for all 32 teams (message names the team and the ratio).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the engine in `static/team-themes.js` per the Interfaces block, with `mix(hex, toward, fraction)` and `rgba(hex, alpha)` helpers. `theme-boot.js`: in try/catch, read `localStorage.getItem("eb_team")` and call `TeamTheme.apply`.
- [ ] **Step 4: Fix palettes** (never thresholds) until all contrast tests pass; re-run. Expected: PASS.
- [ ] **Step 5: Wire** `index.html`, `sw.js` (add the three new files and `/style.css` stays; bump the cache name), and the `--on-accent` fallbacks in `style.css`. Run `node --check` on all three JS files and the full suite. Expected: PASS, default look unchanged (no `data-team` attribute without a saved team).
- [ ] **Step 6: Commit** "Team theme engine and boot".

---

### Task 3: Server validation

**Files:**
- Modify: `server.py` (`SettingsUpdate.theme`)
- Test: `tests/test_theme_setting.py`

**Interfaces:**
- Consumes: the 32 codes. The server must not import the JS: it uses `engine.news._TEAMS` keys as the source of truth (Task 1's test already proves the JS table matches it).
- Produces: `POST /api/settings {"theme": "DET"}` stores `DET`; `""` or `null` clears; anything else returns 422/400 and stores nothing.

- [ ] **Step 1: Write the failing tests** (`TestClient`, `server.db` patched, `require_user` overridden): `test_valid_code_is_stored` (`db.update_settings` called with `{"theme": "DET"}`), `test_empty_clears`, `test_lowercase_is_normalised_to_upper`, `test_unknown_code_is_rejected_and_nothing_is_stored`, `test_markup_and_overlong_values_are_rejected` (`"<img onerror=x>"`, `"DET; background:red"`, a 5000-character string), `test_get_settings_returns_the_theme`.
- [ ] **Step 2: Run** `pytest tests/test_theme_setting.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** a pydantic `validator("theme", pre=True)` on `SettingsUpdate` (uppercase, strip, allow empty/None, else must be in the code set).
- [ ] **Step 4: Run** it plus the full suite. Expected: PASS.
- [ ] **Step 5: Commit** "Validate the theme setting".

---

### Task 4: Picker and persistence

**Files:**
- Create: `static/theme.js` (picker and sync part)
- Modify: `static/index.html` (picker mount `#team-picker` as the first block in `#tab-settings`, outside `#settings-logged-in`, plus the body script tag), `static/app.js` (`loadSettingsIntoState` calls `ThemePicker.syncFromAccount(settings.theme)`; `teamThemeStyle` builds from `TeamTheme.get`; delete the duplicated `TEAM_COLORS`/`TEAM_ALIAS` use of colors only), `static/style.css` (picker styles)
- Test: `tests/test_team_themes.py` (node-driven, DOM stub) and the browser script in Task 7

**Interfaces:**
- Consumes: `TeamTheme.apply/clear/valid/get/all/current`, `POST /api/settings`.
- Produces on `window.ThemePicker`: `choose(code) -> void` (apply, `localStorage` write, account `POST` when `state.user`, live-region announcement, kickoff sweep hook `ThemeFX.kickoff(code)` if present); `preview(code)`; `endPreview()` (restores `TeamTheme.current()`); `syncFromAccount(accountTheme)` (applies the account value only when the browser has none; a browser value always wins); `render(host)`.
- Chip markup: `<button type="button" aria-pressed>` with the logo `<img>` (`onerror` swaps to the abbreviation span on the team primary), grouped under division headings, plus a "Default" chip.

- [ ] **Step 1: Write the failing tests** (node, DOM stub): `test_choose_applies_stores_and_posts_when_signed_in`, `test_signed_out_choose_never_posts`, `test_blocked_storage_still_applies_and_does_not_throw` (storage getter/setter throws), `test_sync_from_account_only_when_browser_has_none`, `test_browser_choice_beats_account_value`, `test_unknown_account_theme_is_ignored`, `test_preview_then_end_preview_restores_committed_team` (committed `DET`, preview `GB`, `KC`, `SEA` in a row, end, expect `DET`), `test_default_chip_clears_everything`, `test_logo_error_swaps_to_abbreviation`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `static/theme.js` picker (event delegation on the grid; `pointerenter`/`focus` preview, `pointerleave`/`blur` end preview, click/Enter commit; roving tabindex with arrow keys; a polite `aria-live` node).
- [ ] **Step 4: Wire** the mount, script tag, `app.js` hooks and picker CSS; remove the now-duplicate color table in `app.js`. Run the full suite. Expected: PASS.
- [ ] **Step 5: Commit** "Favorite-team picker with persistence".

---

### Task 5: Atmosphere

**Files:**
- Modify: `static/theme.js` (`ThemeFX`: hero + kickoff), `static/index.html` (`<div id="team-hero">` at the top of the content area), `static/style.css`
- Test: node (DOM stub) plus the Task 7 browser check

**Interfaces:**
- Produces: `window.ThemeFX.renderHero()` (fills `#team-hero` for the current team, or empties it for default), `ThemeFX.kickoff(code)` (one-time 700 ms diagonal wipe overlay in primary then secondary, removes itself). `ThemePicker.choose` and boot both call `renderHero`.
- Hero: logo (abbreviation fallback), city in small caps, team name large in `--accent`, a slow gradient layer and faint yard-line stripes (CSS only, one animated layer using `transform`/`opacity`). Under 560px it collapses to a slim bar (logo + name, no gradient animation). Page backdrop: fixed team-tinted radial gradient on `html[data-team] body::before`.

- [ ] **Step 1: Write the failing tests**: `test_hero_is_empty_without_a_team`, `test_hero_shows_logo_city_and_name_for_a_team`, `test_hero_logo_error_falls_back_to_the_abbreviation`, `test_kickoff_removes_its_overlay_and_is_skipped_for_reduced_motion` (stub `matchMedia`), `test_kickoff_called_twice_leaves_one_overlay_at_most`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `renderHero`, `kickoff` and the CSS (`@media (prefers-reduced-motion: reduce)` removes the gradient animation and skips the sweep).
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit** "Team hero band and kickoff sweep".

---

### Task 6: Interactions

**Files:**
- Modify: `static/theme.js` (`ThemeFX.glow`, `ThemeFX.tabWipe`), `static/app.js` (call `ThemeFX.tabWipe()` from the existing tab-switch function), `static/style.css`
- Test: node (DOM stub)

**Interfaces:**
- Produces: `ThemeFX.initGlow(root=document)` (one delegated `pointermove` listener; for the nearest `.news-card, .lab-card, .myteam-card, .board-wrap, .tr-card` sets `--mx`/`--my` in px relative to it, via `requestAnimationFrame`; does nothing for `pointerType !== "mouse"`), `ThemeFX.tabWipe()` (restarts a 350 ms top-edge line animation in the accent; no-op without a team or under reduced motion).
- CSS: the glow is `radial-gradient(240px circle at var(--mx) var(--my), rgba(var(--tm-rgb), .14), transparent)` as a `::after` on those surfaces, only under `html[data-team]`.

- [ ] **Step 1: Write the failing tests**: `test_glow_sets_position_vars_for_mouse_only`, `test_glow_is_throttled_to_one_frame` (3 moves, 1 rAF callback), `test_glow_ignores_elements_outside_themed_surfaces`, `test_tab_wipe_is_a_noop_without_a_team_and_under_reduced_motion`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** both functions, the CSS and the `app.js` call.
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit** "Cursor glow and tab wipe".

---

### Task 7: Browser verification and docs

**Files:**
- Create: `scripts/check_team_themes.js`
- Modify: `README.md` (one paragraph under the frontend row)

**Interfaces:**
- Consumes: a running app (`uvicorn server:app`), Playwright from the environment.
- Produces: a contact sheet PNG of all 32 teams on Big Board, My Team (mocked) and News, and a pass/fail line per behavior.

- [ ] **Step 1: Write** the script: for each team set `eb_team`, reload, assert first computed `--accent` equals the team primary (no flash), screenshot; assert zero console errors across all 32; picker hover-preview then leave restores; reload keeps the team; reduced-motion (`emulateMedia`) removes the sweep and hero animation; default theme (no `eb_team`) has no `data-team` and an empty `#team-hero`; a 360x740 viewport has no horizontal scroll with a team set and the picker open.
- [ ] **Step 2: Run** it against the running app. Expected: every line passes. Fix what it finds (in the owning task's files), re-run.
- [ ] **Step 3: Document** the feature in `README.md`, run the full suite, confirm the branch is clean.
- [ ] **Step 4: Commit** "Team theme browser check and docs".

---

## Self-Review

- **Spec coverage:** palettes (T1); derived variables and semantic exclusions (T2); no-flash boot and `theme-color` (T2); server validation (T3); picker, hover-preview, keyboard, announcements, localStorage plus account sync with browser-wins precedence (T4); hero, backdrop, kickoff, logo fallback, mobile collapse (T5); glow, tab wipe, reduced motion (T5, T6); service worker (T2); contrast and 32-team tests (T1, T2); browser contact sheet (T7). No gaps found.
- **Type consistency:** `TeamTheme` (`valid`, `get`, `vars`, `apply`, `clear`, `current`, `all`), `ThemePicker` (`choose`, `preview`, `endPreview`, `syncFromAccount`, `render`) and `ThemeFX` (`renderHero`, `kickoff`, `initGlow`, `tabWipe`) are used by those exact names in every task. `eb_team` and `theme` are the only storage names.
- **Review Focus:** each of the five lines has its test (T2: unknown code, semantic vars; T4: blocked storage, rapid hover, logo error; T5: hero logo error).
- **Proportion:** the plan is about 2x the spec, with signatures, test names and exact values and no function bodies.
