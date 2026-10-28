// Lineup Lab — vanilla JS frontend, no build step. Talks to /api/* on the
// same origin (server.py serves both).

const POSITIONS = ["QB", "RB", "WR", "TE"];

const FMT = {
  int: (v) => (v == null ? "—" : Math.round(v).toString()),
  d1: (v) => (v == null ? "—" : Number(v).toFixed(1)),
  d2: (v) => (v == null ? "—" : Number(v).toFixed(2)),
  pct: (v) => (v == null ? "—" : Number(v).toFixed(1) + "%"),
};

// ---- security: every dynamic string that lands in innerHTML goes through
// esc() first (player/team/owner/league names, news text, usernames — all
// of it originates from a third party at some point: Sleeper display names,
// RSS content, etc.) and every clickable URL goes through safeUrl() so a
// "javascript:" href can't sneak in as a team avatar or news link. ----
function esc(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// A same-tag fallback for a player headshot that fails to load (blocked by
// an ad/privacy blocker, a dead CDN link, whatever) — swaps the <img>'s own
// src to a generated initials avatar instead of leaving a blank/broken
// image. Same element, same tag, so every existing sizing/border-radius
// rule for that context keeps applying with zero new CSS.
function initialsAvatarUri(name) {
  const initials = (name || "").trim().split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() || "?";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">`
    + `<rect width="80" height="80" rx="40" fill="#1f6f52"/>`
    + `<text x="50%" y="53%" font-family="ui-monospace,monospace" font-size="30" font-weight="700" `
    + `fill="#eafff4" text-anchor="middle" dominant-baseline="middle">${esc(initials)}</text></svg>`;
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

// data-fb carries the fallback so onerror doesn't need to re-run any JS
// call inline (keeps the CSP-sensitive inline-handler surface trivial: a
// plain attribute swap, no function invocation).
function headshotAttrs(p) {
  return `src="${proxyImg(p.headshot_url)}" data-fb="${initialsAvatarUri(p.player_display_name)}"`;
}

// Every image fallback in this app used to be an inline onerror="..."
// attribute — this app's own CSP header (server.py: script-src 'self',
// no unsafe-inline / unsafe-hashes) silently blocks ALL of those in any
// browser that actually enforces CSP, so a broken image just showed a
// broken-image icon instead of ever falling back. One delegated listener
// in the capture phase (the "error" event doesn't bubble, so capture is
// the only way to catch it from a single top-level listener) replaces
// every one of them, CSP-compliant, driven by data-fb-* attributes set
// where the <img> is built instead of an inline handler.
document.addEventListener("error", (e) => {
  const img = e.target;
  if (img?.tagName !== "IMG") return;
  const d = img.dataset;
  if (d.fb && img.src !== d.fb) { img.src = d.fb; return; }
  if (d.fbEmoji) { img.outerHTML = `<span class="team-emoji">${d.fbEmoji}</span>`; return; }
  if (d.fbHide != null) { img.style.display = "none"; return; }
  if (d.fbRemove != null) { img.remove(); return; }
  if (d.fbNoimageWrap != null) { img.closest(".news-img-wrap")?.classList.add("no-image"); return; }
}, true);

// One delegated listener, real tactile feedback everywhere a button gets
// clicked instead of wiring a ripple onto every button individually —
// same "single top-level listener" shape as the image-fallback one
// above. Skipped under prefers-reduced-motion (the CSS hides the
// element anyway; not spawning it at all avoids even the DOM churn).
const RIPPLE_TARGETS = ".primary-btn, .pill, .nav-item, .week-arrow";
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
if (!prefersReducedMotion) {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(RIPPLE_TARGETS);
    if (!btn || btn.disabled) return;
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 1.4;
    const ripple = document.createElement("span");
    ripple.className = "btn-ripple";
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${e.clientY - rect.top - size / 2}px`;
    btn.appendChild(ripple);
    // animationend alone isn't reliable enough to hang cleanup on — a
    // backgrounded tab or a throttled compositor can delay or skip it
    // entirely, which would otherwise leave orphaned .btn-ripple spans
    // piling up in the DOM for the life of the page. Whichever fires
    // first wins; the leftover is a no-op (remove() on an already-gone
    // node throws nothing).
    ripple.addEventListener("animationend", () => ripple.remove());
    setTimeout(() => ripple.remove(), 650);

    // Primary buttons additionally get the real press-pulse designed in
    // Figma (see style.css's PRIMARY BUTTON PRESS PULSE block — scale
    // spring + glow breathe, real get_motion_context output, not
    // hand-tuned). A toggled class, not :active, since :active only
    // lasts as long as the mouse stays down — too brief for an 800ms
    // release animation on a normal click.
    if (btn.classList.contains("primary-btn")) {
      btn.classList.remove("pulse");
      void btn.offsetWidth; // restart the animation if clicked again mid-animation
      btn.classList.add("pulse");
      setTimeout(() => btn.classList.remove("pulse"), 850);
    }
  });
}

// Keyboard support in one place: Enter/Space activates any clickable
// non-<button> (.kbd-click rows/cards, which also get tabindex="0" where
// they're built), and Escape closes whatever floats on top — a dropdown
// first, then the player/compare/swap modal, then the auth modal.
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target instanceof Element && e.target.matches(".kbd-click, [data-team-page][role='link']")) {
    e.preventDefault();
    e.target.click();
    return;
  }
  if (e.key !== "Escape") return;
  const dd = document.querySelector(".notif-dropdown, .account-dropdown");
  if (dd) { dd.remove(); return; }
  if ($("#modal-root").innerHTML.trim()) { closeModal(); return; }
  if ($("#auth-modal-root").innerHTML.trim()) closeAuthModal();
});

// Which generated Picsart accent art (see static/img/accent-*.png) sits
// behind the player detail modal's header, per position group.
function posAccentClass(pos) {
  if (pos === "QB") return "acc-qb";
  if (pos === "DEF" || pos === "DST") return "acc-def";
  if (pos === "K") return "acc-k";
  return "acc-skill"; // RB / WR / TE
}

function safeUrl(u) {
  if (!u) return "";
  try {
    const parsed = new URL(u, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return esc(parsed.href);
  } catch (e) {}
  return "";
}

// Real photos (player headshots, team avatars, news images) hotlink to
// their real publisher CDNs. Some browsers' ad/privacy blockers flag those
// exact CDN hostnames anyway and silently drop the request — identical to
// a broken image, nothing to debug from here. Route the known ones through
// our own same-origin proxy (see /api/img in server.py) instead; anything
// not on that allowlist just loads directly, unchanged.
const IMG_PROXY_HOSTS = new Set([
  "static.www.nfl.com", "sleepercdn.com", "a.espncdn.com",
  "sportshub.cbsistatic.com", "static.nfl.com",
]);
function proxyImg(u) {
  // Builds from the RAW url, not safeUrl()'s output — safeUrl() HTML-escapes
  // (turns "&" into "&amp;"), and chaining that into encodeURIComponent would
  // bake the literal escaped text into the query value instead of a real
  // "&", corrupting the URL the backend then tries to fetch. esc() is
  // applied once, at the very end, to the finished proxy URL instead.
  if (!u) return "";
  let parsed;
  try { parsed = new URL(u, window.location.origin); } catch (e) { return ""; }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
  // NFL headshot URLs resolve to the full-size original — measured at 3.5MB
  // for one PNG, shown here at 24-84px, so a 60-row board pulled ~200MB
  // through a throttled free-tier server. The CDN resizes on request via the
  // transformation segment of the path; c_limit never upscales. 200px covers
  // the largest display size (84px) at 2x.
  if (parsed.hostname === "static.www.nfl.com" || parsed.hostname === "static.nfl.com") {
    parsed.pathname = parsed.pathname.replace("/image/upload/f_auto,q_auto/", "/image/upload/f_auto,q_auto,w_200,c_limit/");
  }
  if (IMG_PROXY_HOSTS.has(parsed.hostname)) return esc(`/api/img?url=${encodeURIComponent(parsed.href)}`);
  return esc(parsed.href);
}

// ---- signup form helpers: catches the two most common typing mistakes
// (mistyped free-mail domain, weak password) before the request round-trip ----
const COMMON_EMAIL_DOMAINS = [
  "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
  "aol.com", "live.com", "msn.com", "protonmail.com", "comcast.net",
];

function levenshtein(a, b) {
  const m = a.length, n = b.length;
  const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
  for (let j = 0; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      d[i][j] = a[i - 1] === b[j - 1]
        ? d[i - 1][j - 1]
        : 1 + Math.min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1]);
    }
  }
  return d[m][n];
}

// Returns a corrected "user@domain" suggestion if the email's domain looks
// like a near-miss typo of a common provider, else null.
function suggestEmailDomain(email) {
  const at = email.lastIndexOf("@");
  if (at === -1) return null;
  const local = email.slice(0, at);
  const domain = email.slice(at + 1).toLowerCase();
  if (!domain || COMMON_EMAIL_DOMAINS.includes(domain)) return null;
  let best = null, bestDist = Infinity;
  for (const candidate of COMMON_EMAIL_DOMAINS) {
    const dist = levenshtein(domain, candidate);
    if (dist < bestDist) { bestDist = dist; best = candidate; }
  }
  // 1-2 edits on a short domain string is almost always a typo, not intent
  if (best && bestDist > 0 && bestDist <= 2) return `${local}@${best}`;
  return null;
}

// 0-4 strength score from length + character-class variety.
function passwordStrength(pw) {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw)) score++;
  return Math.min(score, 4);
}

// columns shown in the compact board table, per position
const TABLE_COLS = {
  QB: [
    { key: "completion_pct", label: "CMP%", fmt: FMT.pct },
    { key: "td_rate", label: "TD%", fmt: FMT.pct },
    { key: "cpoe", label: "CPOE", fmt: FMT.d1, mobileHide: true },
  ],
  RB: [
    { key: "yards_per_carry", label: "YPC", fmt: FMT.d1 },
    { key: "touches_per_game", label: "TCH/G", fmt: FMT.d1 },
    { key: "target_share", label: "TGT%", fmt: FMT.pct, mobileHide: true },
  ],
  WR: [
    { key: "target_share", label: "TGT%", fmt: FMT.pct },
    { key: "catch_rate", label: "CATCH%", fmt: FMT.pct },
    { key: "avg_separation", label: "SEP", fmt: FMT.d1, mobileHide: true },
  ],
  TE: [
    { key: "target_share", label: "TGT%", fmt: FMT.pct },
    { key: "catch_rate", label: "CATCH%", fmt: FMT.pct },
    { key: "avg_separation", label: "SEP", fmt: FMT.d1, mobileHide: true },
  ],
};

// full metric breakdown shown in the player modal, per position
const DETAIL_METRICS = {
  QB: [
    ["Volume & Efficiency", [
      ["games", "Games", FMT.int], ["volume", "Attempts", FMT.int],
      ["yards_per_attempt", "Yds/Att", FMT.d1], ["completion_pct", "Comp %", FMT.pct],
      ["td_rate", "TD %", FMT.pct], ["int_rate", "INT %", FMT.pct],
      ["sack_rate", "Sack %", FMT.pct], ["rush_yards_per_game", "Rush Yds/G", FMT.d1],
      ["dakota", "DAKOTA", FMT.d1],
    ]],
    ["Advanced (Next Gen Stats + PBP)", [
      ["pressure_rate", "Pressure %", FMT.pct], ["comp_pct_pressure", "Comp % Pressured", FMT.pct],
      ["cpoe", "CPOE", FMT.d1], ["avg_time_to_throw", "Time to Throw", FMT.d2],
      ["aggressiveness", "Aggressiveness", FMT.d1], ["epa_per_play", "EPA/Play", FMT.d2],
      ["explosive_pass_rate", "Explosive %", FMT.pct],
    ]],
  ],
  RB: [
    ["Volume & Efficiency", [
      ["games", "Games", FMT.int], ["volume", "Touches", FMT.int],
      ["yards_per_carry", "Yds/Carry", FMT.d1], ["td_rate", "TD % of Touches", FMT.pct],
      ["touches_per_game", "Touches/G", FMT.d1], ["yards_per_target", "Yds/Target", FMT.d1],
      ["target_share", "Target Share", FMT.pct],
    ]],
    ["Advanced (Next Gen Stats + PBP)", [
      ["rushing_epa_per_carry", "Rush EPA/Carry", FMT.d2], ["explosive_run_rate", "Explosive Run %", FMT.pct],
      ["epa_per_touch", "EPA/Touch", FMT.d2], ["rush_yards_over_expected_per_att", "RYOE/Att", FMT.d1],
      ["rush_efficiency", "Rush Efficiency", FMT.d1], ["pct_stacked_box", "Stacked Box %", FMT.pct],
    ]],
  ],
  WR: [
    ["Volume & Efficiency", [
      ["games", "Games", FMT.int], ["volume", "Targets", FMT.int],
      ["catch_rate", "Catch %", FMT.pct], ["yards_per_target", "Yds/Target", FMT.d1],
      ["td_rate_targets", "TD % of Targets", FMT.pct], ["target_share", "Target Share", FMT.pct],
      ["air_yards_share", "Air Yards Share", FMT.pct], ["wopr", "WOPR", FMT.d1],
      ["yac_per_reception", "YAC/Rec", FMT.d1],
    ]],
    ["Advanced (Next Gen Stats + PBP)", [
      ["avg_separation", "Avg Separation", FMT.d1], ["avg_cushion", "Avg Cushion", FMT.d1],
      ["yac_above_expectation", "YAC Above Exp.", FMT.d1], ["epa_per_target", "EPA/Target", FMT.d2],
      ["explosive_rec_rate", "Explosive %", FMT.pct],
    ]],
  ],
};
DETAIL_METRICS.TE = DETAIL_METRICS.WR;

// -------------------------------------------------------------- state -----
const state = {
  tab: "board",
  pos: "ALL",
  opp: "",
  search: "",
  meta: null,
  user: null,
  settings: null,
  teams: [],                 // connected Sleeper teams (multi-team support)
  leagueScoringDict: null,   // cached scoring dict of the active team's league
  scoring: localStorage.getItem("eb_scoring") || "",   // "" | "half_ppr" | "standard" | "league"
  startsit: [],
  ssMode: "balanced",        // Start/Sit lens: balanced | safe | upside
  ssSwapped: false,          // Start/Sit head-to-head display order (2-player case only)
  tradeA: [],
  tradeB: [],
  tradeTeamA: null,          // {team_name, avatar_url} — for the trade analysis header
  tradeTeamB: null,
  tradeOpponentRosterId: null,
  shopRoster: [],             // my own roster, for the "pick a player to shop" trade finder picker
  shopSelected: new Set(),    // player_ids currently selected to shop
  newsScope: "team",          // "team" | "league" | "opponent"
  notifications: [],          // real, actionable alerts — currently: starters marked OUT/Doubtful
  compareSelected: new Map(), // player_id -> full player row, for the Big Board "Compare" tray (max 4)
};

function saveScoring() { localStorage.setItem("eb_scoring", state.scoring); }
function activeTeam() { return state.teams.find((t) => t.active) || null; }

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `${path} -> ${res.status}`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (e) {}
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return adoptPvs(await res.json());
}

// The score every screen shows is the Player Value Score (PVS): edge over a
// replacement player, comparable across positions (engine/pvs.py). The
// server still sends the old position-relative grade as SCORE; walk the
// response once, keep that as SCORE_POS and let SCORE carry the PVS wherever
// the server attached one (K and D/ST have none and keep their own grade).
function adoptPvs(x) {
  if (Array.isArray(x)) { x.forEach(adoptPvs); return x; }
  if (x && typeof x === "object") {
    if (typeof x.PVS === "number" && !("SCORE_POS" in x)) { x.SCORE_POS = x.SCORE; x.SCORE = x.PVS; }
    for (const k in x) { const v = x[k]; if (v && typeof v === "object") adoptPvs(v); }
  }
  return x;
}

// current scoring as a dict of point values, or null for default (server
// falls back to the signed-in account's saved preference, then full PPR)
function scoringDict() {
  if (state.scoring === "league") return state.leagueScoringDict || null;
  if (state.scoring && state.meta) return state.meta.scoring_presets[state.scoring] || null;
  return null;
}

function scoringQS() {
  const d = scoringDict();
  if (!d) return "";
  return Object.entries(d).map(([k, v]) => `&${k}=${encodeURIComponent(v)}`).join("");
}

// ---------------------------------------------------------------- tabs ----
const TAB_IDS = ["board", "myteam", "draft", "startsit", "trade", "waivers", "news", "chat", "settings"];
// The home/landing tab once the gate clears — My Team, not Big Board.
const DEFAULT_TAB = "myteam";

// One shared indicator bar that slides to whichever sidebar tab is
// active (Settings lives outside .sidebar-nav in its own section, so it
// just gets its own background highlight like before — no bar to slide
// to there). Re-run on anything that can change row positions: a tab
// switch, the sidebar collapsing/expanding, the mobile drawer opening,
// or the window resizing across the mobile breakpoint.
function positionNavIndicator(tab) {
  const indicator = document.getElementById("nav-active-indicator");
  if (!indicator) return;
  const btn = document.querySelector(`.sidebar-nav .nav-item[data-tab="${tab}"]`);
  if (!btn) { indicator.style.opacity = "0"; return; }
  indicator.style.opacity = "1";
  indicator.style.transform = `translateY(${btn.offsetTop + btn.offsetHeight * 0.2}px)`;
  indicator.style.height = `${btn.offsetHeight * 0.6}px`;
}

function switchTab(tab) {
  document.querySelectorAll(".nav-item[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  positionNavIndicator(tab);
  state.tab = tab;
  renderCompareTray();
  TAB_IDS.forEach((t) => { $(`#tab-${t}`).style.display = t === tab ? "" : "none"; });
  const activeSection = $(`#tab-${tab}`);
  activeSection.classList.remove("tab-fade-in");
  void activeSection.offsetWidth; // force reflow so the animation replays every switch
  activeSection.classList.add("tab-fade-in");
  if (typeof ThemeFX !== "undefined") ThemeFX.tabWipe();
  if (tab !== "draft") stopDraftPolling();
  // chat.js is a separate script: if it failed to load, navigation must still work
  if (tab !== "chat" && typeof stopChatPolling === "function") stopChatPolling();
  // The board used to load only after a pill/scoring/search change, so the
  // first visit to Big Board sat on "Loading real NFL data…" forever.
  if (tab === "board" && !state.boardLoaded) loadBoard();
  if (tab === "waivers") loadWaivers();
  if (tab === "myteam") { loadMyTeam(); loadLiveScores(); }
  if (tab === "draft") loadDraftTab();
  if (tab === "startsit") loadStartSitTab();
  if (tab === "news") loadNews();
  if (tab === "chat" && typeof loadChatTab === "function") loadChatTab();
  if (tab === "trade") { loadTradeFinder(); loadTradeAnalyzer(); }
  if (tab === "settings") renderSettingsTab();
  closeMobileDrawer();
  window.scrollTo({ top: 0 });
}

function initTabs() {
  document.querySelectorAll(".nav-item[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
}

// ------------------------------------------------------------- sidebar ----
function closeMobileDrawer() {
  document.body.classList.remove("mobile-drawer-open");
  document.documentElement.classList.remove("mobile-drawer-open");
}

function initSidebar() {
  const collapsed = localStorage.getItem("eb_sidebar_collapsed") === "1";
  document.body.classList.toggle("sidebar-collapsed", collapsed);

  $("#sidebar-toggle").addEventListener("click", () => {
    const isCollapsed = document.body.classList.toggle("sidebar-collapsed");
    localStorage.setItem("eb_sidebar_collapsed", isCollapsed ? "1" : "0");
    document.querySelector(".account-dropdown")?.remove();
    positionNavIndicator(state.tab);
  });

  $("#mobile-menu-btn").addEventListener("click", () => {
    document.body.classList.add("mobile-drawer-open");
    document.documentElement.classList.add("mobile-drawer-open");
    positionNavIndicator(state.tab);
  });
  $("#sidebar-backdrop").addEventListener("click", closeMobileDrawer);
  window.addEventListener("resize", () => positionNavIndicator(state.tab));

  $("#notif-bell").addEventListener("click", toggleNotifDropdown);

  $("#sidebar-add-league").addEventListener("click", () => {
    switchTab("settings");
    setTimeout(() => {
      const input = $("#set-connect-input");
      input?.scrollIntoView({ behavior: "smooth", block: "center" });
      input?.focus();
    }, 150); // after switchTab's own scroll-to-top + tab render
  });
}

// A connected team's league scoring, from whichever platform it lives on.
// ESPN teams used to be fetched from the Sleeper endpoint, which always failed.
async function fetchLeagueScoring(team) {
  if (!team) return null;
  const path = team.platform === "espn" ? "espn" : "sleeper";
  try { return (await api(`/api/${path}/${encodeURIComponent(team.league_id)}`)).scoring || null; } catch (e) { return null; }
}

const platformLabel = (t) => (t.platform === "espn" ? "ESPN" : "Sleeper");

function renderSidebarTeams() {
  const list = $("#sidebar-teams-list");
  if (!state.user) {
    list.innerHTML = `<div class="hint" style="padding:0 4px;">Sign in to connect a league.</div>`;
    return;
  }
  if (!state.teams.length) {
    list.innerHTML = `<div class="hint" style="padding:0 4px;">No leagues connected yet — add one in Settings.</div>`;
    return;
  }
  list.innerHTML = state.teams.map((t) => `
    <div class="sidebar-team-row kbd-click${t.active ? " active" : ""}" data-team-id="${esc(t.id)}" title="${esc(t.team_name)} · ${esc(t.league_name || t.league_id)} (${platformLabel(t)}). Click to switch." role="button" tabindex="0" aria-pressed="${t.active ? "true" : "false"}">
      ${t.avatar_url ? `<img src="${proxyImg(t.avatar_url)}" data-fb-emoji="🏈" alt="">` : `<span class="team-emoji">🏈</span>`}
      <span class="st-name">${esc(t.team_name)}</span>
      <span class="st-plat ${t.platform === "espn" ? "espn" : "sleeper"}">${platformLabel(t)}</span>
    </div>`).join("");
  list.querySelectorAll(".sidebar-team-row").forEach((row) => {
    row.addEventListener("click", async () => {
      if (row.classList.contains("active")) return;
      row.classList.add("switching");
      let res;
      try {
        res = await api(`/api/teams/${row.dataset.teamId}/activate`, { method: "POST" });
      } catch (e) {
        row.classList.remove("switching");
        showToast(e.message || "Couldn't switch leagues.", "error");
        return;
      }
      state.teams = res.teams;
      const active = activeTeam();
      state.leagueScoringDict = null;
      state.shopRoster = [];           // stale roster for the old team — refetch on next Trade/Start-Sit tab visit
      state.shopSelected = new Set();
      state.startsit = [];
      state.tradeA = []; state.tradeB = [];
      state.leagueScoringDict = await fetchLeagueScoring(active);
      if (state.scoring === "league" && !state.leagueScoringDict) { state.scoring = ""; saveScoring(); }
      refreshScoringLeagueOption();
      renderSidebarTeams();
      if (state.tab === "settings") { renderTeamsList(); renderScoringPills(); }
      if (state.tab === "myteam") loadMyTeam();
      if (state.tab === "waivers") loadWaivers();
      if (state.tab === "news") loadNews();
      if (state.tab === "draft") loadDraftTab();
      if (state.tab === "trade") { loadTradeFinder(); loadTradeAnalyzer(); }
      if (state.tab === "startsit") loadStartSitTab();
      showToast(`Switched to "${active ? active.team_name : ""}".`, "success");
    });
  });
}

function initPosPills() {
  const boardPills = $("#pos-pills");
  const waiverPills = $("#waivers-pos-pills");

  const allBtn = el("button", "pill active", "All");
  allBtn.addEventListener("click", () => {
    waiverPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    allBtn.classList.add("active");
    loadWaivers("ALL");
  });
  waiverPills.appendChild(allBtn);

  const boardAll = el("button", "pill" + (state.pos === "ALL" ? " active" : ""), "All");
  boardAll.addEventListener("click", () => {
    state.pos = "ALL";
    boardPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    boardAll.classList.add("active");
    loadBoard();
  });
  boardPills.appendChild(boardAll);

  POSITIONS.forEach((pos) => {
    const b1 = el("button", "pill" + (pos === state.pos ? " active" : ""), pos);
    b1.addEventListener("click", () => {
      state.pos = pos;
      boardPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      b1.classList.add("active");
      loadBoard();
    });
    boardPills.appendChild(b1);

    const b2 = el("button", "pill", pos);
    b2.addEventListener("click", () => {
      waiverPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      b2.classList.add("active");
      loadWaivers(pos);
    });
    waiverPills.appendChild(b2);
  });
}

function initScoringSelect() {
  const sel = $("#scoring-select");
  sel.value = state.scoring;
  refreshScoringLeagueOption();
  // proceedPastGate() calls this after every sign-in; without the guard a
  // sign-out/sign-in cycle stacked a second listener (two board loads per change).
  if (sel.dataset.wired) return;
  sel.dataset.wired = "1";
  sel.addEventListener("change", () => {
    state.scoring = sel.value;
    saveScoring();
    loadBoard();
    if (state.tab === "waivers") loadWaivers();
  });
}

function refreshScoringLeagueOption() {
  const opt = $("#scoring-league-opt");
  opt.style.display = activeTeam() ? "" : "none";
}

// --------------------------------------------------------------- board ----
function scoreCell(score) {
  const pct = Math.max(0, Math.min(100, score));
  // starts at 0 and animates to its real width via animateScoreBars() —
  // a small deliberate-motion touch rather than popping in at full size
  return `<span class="score-bar"><span style="width:0%" data-pct="${pct}"></span></span><span class="score-cell">${FMT.d1(score)}</span>`;
}

function animateScoreBars() {
  const apply = () => {
    document.querySelectorAll(".score-bar > span[data-pct]").forEach((el) => {
      el.style.width = el.dataset.pct + "%";
    });
  };
  // double rAF for a clean paint-then-transition in the normal (visible tab)
  // case, PLUS a setTimeout fallback — rAF is fully paused on a backgrounded
  // tab (confirmed: fires 0 times while document.hidden), so without this a
  // board loaded in a background tab would leave every bar stuck at 0%
  requestAnimationFrame(() => requestAnimationFrame(apply));
  setTimeout(apply, 60);
}

function skeletonRows(n, cols) {
  const extra = `<div class="skel skel-line short" style="margin-left:16px"></div>`.repeat(cols || 2);
  return Array.from({ length: n }).map(() => `
    <div class="skel-row">
      <div class="skel skel-avatar"></div>
      <div class="skel skel-line"></div>
      ${extra}
    </div>`).join("");
}

function formCell(form) {
  if (form == null) return "—";
  const cls = form > 0 ? "form-pos" : form < 0 ? "form-neg" : "";
  const sign = form > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${FMT.d1(form)}%</span>`;
}

// "BYE" when the player's team is off in the week this board is about.
function byeTagHtml(p) {
  if (p.bye_week == null || state.boardWeek == null) return "";
  if (Number(p.bye_week) === Number(state.boardWeek)) return ' <span class="bye-tag" title="Team is on a bye this week">BYE</span>';
  return "";
}

function tierPillHtml(tier) {
  return tier == null ? "—" : `<span class="tier-pill tier-${Math.min(tier, 8)}">T${esc(tier)}</span>`;
}

// How far the experts disagree with us: positive = they rank him higher.
function ecrGapHtml(p) {
  if (p.ecr == null) return '<span class="muted">—</span>';
  const gap = p.ecr_gap;
  const cls = gap > 8 ? "form-pos" : gap < -8 ? "form-neg" : "";
  const arrow = gap > 8 ? "▲" : gap < -8 ? "▼" : "";
  return `${Math.round(p.ecr)} <span class="${cls}" title="Expert consensus rank vs. our rank">${arrow}</span>`;
}

function playerCellHtml(p) {
  // The Big Board table is the app's highest-traffic scanning surface —
  // real injury/gone-dark signals belong here too, not just once you've
  // already clicked into one specific player's modal (statusFlagsHtml
  // was previously wired into 6 other surfaces but missed this one,
  // the actual Big Board row template).
  //
  // rank 1 is a real, already-computed signal (top SCORE for this exact
  // position/scoring/opponent view) — not a fabricated "star" flag — so
  // it's a fair thing to celebrate with a crown. Whichever list handed
  // this player object a `rank` of 1 (Big Board or Waivers, the two
  // callers of this shared template) means the same thing: best of the
  // list you're currently looking at.
  const isTop = p.rank === 1;
  return `<div class="player-cell${isTop ? " player-cell-top" : ""}">
      <img ${headshotAttrs(p)} alt="">
      <div><div class="player-name">${isTop ? '<span class="top-crown" title="Top of this board">👑</span>' : ""}${esc(p.player_display_name) || "—"}${statusFlagsHtml(p)}${byeTagHtml(p)}</div><div class="player-team">${esc(p.recent_team)}${p.position && state.pos === "ALL" ? ` · <span class="pos-chip pos-${esc(p.position)}">${esc(p.position)}</span>` : ""}</div>${p.stat_line ? `<div class="stat-line">${esc(p.stat_line)}</div>` : ""}</div>
    </div>`;
}

function renderBoardHead(cols, showProj) {
  const head = $("#board-head");
  let html = `<th></th><th>Player</th><th title="Player Value Score: edge over a replacement player, comparable across positions">PVS</th><th>FORM</th><th>FPTS/G</th>`;
  cols.forEach((c) => {
    html += `<th${c.mobileHide ? ' class="hide-mobile"' : ""}>${esc(c.label)}</th>`;
  });
  if (showProj) html += `<th>PROJ</th>`;
  head.innerHTML = html;
}

function renderBoardRows(players, cols, showProj) {
  const body = $("#board-body");
  body.innerHTML = "";
  const q = state.search.trim().toLowerCase();
  players
    .filter((p) => !q || (p.player_display_name || "").toLowerCase().includes(q) || (p.recent_team || "").toLowerCase().includes(q))
    .forEach((p) => {
      const tr = el("tr", "kbd-click");
      tr.tabIndex = 0;
      if (p.rank === 1) tr.classList.add("board-row-top");
      const selected = state.compareSelected.has(p.player_id);
      let html = `<td class="rank-cell">${esc(p.rank)}</td>`;
      html += `<td><div class="board-player-row">
          <button type="button" class="cmp-check${selected ? " selected" : ""}" data-pid="${esc(p.player_id)}" aria-pressed="${selected}" aria-label="Compare ${esc(p.player_display_name)}" title="${selected ? "Remove from compare" : "Add to compare"}"><span class="check">${selected ? "✓" : ""}</span></button>
          ${playerCellHtml(p)}
        </div></td>`;
      html += `<td>${scoreCell(p.SCORE)}</td>`;
      html += `<td>${formCell(p.FORM)}</td>`;
      html += `<td>${FMT.d1(p.fpts_per_game)}</td>`;
      cols.forEach((c) => {
        html += `<td${c.mobileHide ? ' class="hide-mobile"' : ""}>${c.fmt(p[c.key])}</td>`;
      });
      if (showProj) html += `<td>${FMT.d1(p.PROJ)}</td>`;
      tr.innerHTML = html;
      // The checkbox is its own click target (stopPropagation) so picking a
      // player to compare doesn't also pop open the player-detail modal —
      // the row itself still does that for every other click, unchanged.
      tr.querySelector(".cmp-check").addEventListener("click", (e) => {
        e.stopPropagation();
        toggleCompare(p, e.currentTarget);
      });
      tr.addEventListener("click", () => openPlayerModal(p.player_id, state.opp));
      body.appendChild(tr);
    });
}

// ------------------------------------------------------- compare tray -----
// Cross-position, whole-universe player comparison — pick any 2-4 players
// off the Big Board (not just your own roster, unlike Start/Sit) and see
// them side by side with the best real number in each category called out.
const CMP_MAX = 4;

function toggleCompare(p, btn) {
  const already = state.compareSelected.has(p.player_id);
  if (!already && state.compareSelected.size >= CMP_MAX) {
    const tray = $("#compare-tray");
    tray.classList.remove("shake"); void tray.offsetWidth; tray.classList.add("shake");
    return;
  }
  if (already) state.compareSelected.delete(p.player_id);
  else state.compareSelected.set(p.player_id, p);
  if (btn) {
    const isSel = state.compareSelected.has(p.player_id);
    btn.classList.toggle("selected", isSel);
    btn.querySelector(".check").textContent = isSel ? "✓" : "";
    btn.setAttribute("aria-pressed", String(isSel));
    btn.title = isSel ? "Remove from compare" : "Add to compare";
  }
  renderCompareTray();
}

function renderCompareTray() {
  const tray = $("#compare-tray");
  const chips = $("#compare-tray-chips");
  const openBtn = $("#compare-open-btn");
  const n = state.compareSelected.size;
  // The tray belongs to the Big Board; it used to float over every other tab.
  if (!n || state.tab !== "board") { tray.style.display = "none"; return; }
  tray.style.display = "";
  chips.innerHTML = [...state.compareSelected.values()].map((p) => `
    <div class="cmp-chip">
      <img ${headshotAttrs(p)} alt="">
      <span>${esc(p.player_display_name)}</span>
      <button type="button" class="chip-x" data-pid="${esc(p.player_id)}" aria-label="Remove ${esc(p.player_display_name)}">✕</button>
    </div>`).join("");
  chips.querySelectorAll(".chip-x").forEach((b) => {
    b.addEventListener("click", () => {
      const pid = b.dataset.pid;
      state.compareSelected.delete(pid);
      // keep the board's own checkbox in sync if that row is on screen
      const boardBtn = document.querySelector(`.cmp-check[data-pid="${CSS.escape(pid)}"]`);
      if (boardBtn) {
        boardBtn.classList.remove("selected");
        boardBtn.querySelector(".check").textContent = "";
        boardBtn.setAttribute("aria-pressed", "false");
      }
      renderCompareTray();
    });
  });
  openBtn.disabled = n < 2;
  openBtn.textContent = n < 2 ? "Compare" : `Compare (${n})`;
}

// One metric row across every selected player — real values only (a
// missing stat renders "—" and is excluded from that row's "who's best"
// call, never treated as a zero). `higherIsBetter` covers every metric
// this app has (SCORE/FORM/FPTS/PROJ/floor/ceiling are all "more is
// better" reads) but is a real parameter, not a hardcoded assumption,
// in case that's ever not true for something added later.
function cmpBestIds(players, key, higherIsBetter = true) {
  const vals = players.map((p) => p[key]).filter((v) => v != null);
  if (vals.length < 2) return new Set(); // nothing to call a "winner" against
  const best = higherIsBetter ? Math.max(...vals) : Math.min(...vals);
  return new Set(players.filter((p) => p[key] === best).map((p) => p.player_id));
}

function cmpRowHtml(label, p, key, opts = {}) {
  const { decimals = 1, suffix = "", signed = false, maxVal = null, isBest = false } = opts;
  const value = p[key];
  if (value == null) {
    return `<div class="cmp-row"><span class="cmp-row-label">${esc(label)}</span><span class="cmp-row-val muted">—</span></div>`;
  }
  const bar = maxVal != null
    ? `<div class="cmp-row-track"><div class="cmp-row-fill${isBest ? " best" : ""}" style="width:${Math.max(4, Math.round((Math.max(0, value) / Math.max(maxVal, 0.1)) * 100))}%"></div></div>`
    : "";
  return `<div class="cmp-row${isBest ? " best" : ""}">
    <span class="cmp-row-label">${esc(label)}${isBest ? ' <span class="cmp-crown">👑</span>' : ""}</span>
    <span class="cmp-row-val" data-target="${value}" data-decimals="${decimals}" data-suffix="${esc(suffix)}" data-signed="${signed ? "1" : "0"}"></span>
    ${bar}
  </div>`;
}

function cmpCardHtml(p, players, isTopOverall, delayMs) {
  const scoreBest = cmpBestIds(players, "SCORE");
  const formBest = cmpBestIds(players, "FORM");
  const fptsBest = cmpBestIds(players, "fpts_per_game");
  const hasProj = players.some((x) => x.PROJ != null);
  const projBest = hasProj ? cmpBestIds(players, "PROJ") : new Set();
  const floorBest = cmpBestIds(players, "floor");
  const ceilBest = cmpBestIds(players, "ceiling");

  const maxOf = (key) => Math.max(0.1, ...players.map((x) => x[key]).filter((v) => v != null));

  let rows = cmpRowHtml("PVS", p, "SCORE", { decimals: 1, maxVal: maxOf("SCORE"), isBest: scoreBest.has(p.player_id) });
  rows += cmpRowHtml("FORM", p, "FORM", { decimals: 1, suffix: "%", signed: true, isBest: formBest.has(p.player_id) });
  rows += cmpRowHtml("FPTS/G", p, "fpts_per_game", { decimals: 1, maxVal: maxOf("fpts_per_game"), isBest: fptsBest.has(p.player_id) });
  if (hasProj) rows += cmpRowHtml("PROJ", p, "PROJ", { decimals: 1, maxVal: maxOf("PROJ"), isBest: projBest.has(p.player_id) });
  rows += cmpRowHtml("Floor", p, "floor", { decimals: 1, maxVal: maxOf("ceiling"), isBest: floorBest.has(p.player_id) });
  rows += cmpRowHtml("Ceiling", p, "ceiling", { decimals: 1, maxVal: maxOf("ceiling"), isBest: ceilBest.has(p.player_id) });

  return `<div class="cmp-card kbd-click ${posAccentClass(p.position)}${isTopOverall ? " cmp-top" : ""}" data-pid="${esc(p.player_id)}" role="button" tabindex="0" style="animation-delay:${delayMs}ms">
    ${isTopOverall ? `<span class="badge-recommended cmp-top-badge">TOP OVERALL</span>` : ""}
    <img ${headshotAttrs(p)} alt="">
    <div class="cmp-name">${esc(p.player_display_name)}${statusFlagsHtml(p)}</div>
    <div class="cmp-meta">${esc(p.position)} · ${esc(p.recent_team)}</div>
    <div class="cmp-rows">${rows}</div>
  </div>`;
}

function openCompareModal() {
  const players = [...state.compareSelected.values()];
  if (players.length < 2) return;

  // Real tally, not a fabricated overall score: count how many of the
  // categories above each player actually won outright, same "best in
  // this row" sets cmpCardHtml computes per-metric. Ties (a shared max)
  // count for every player who hit it, same as the per-row crown.
  const winCounts = new Map(players.map((p) => [p.player_id, 0]));
  [["SCORE", true], ["FORM", true], ["fpts_per_game", true], ["PROJ", true], ["floor", true], ["ceiling", true]].forEach(([key]) => {
    cmpBestIds(players, key).forEach((pid) => winCounts.set(pid, (winCounts.get(pid) || 0) + 1));
  });
  const maxWins = Math.max(...winCounts.values());
  const topId = maxWins > 0 ? [...winCounts.entries()].find(([, n]) => n === maxWins)?.[0] : null;

  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal cmp-modal">
    <div class="modal-header">
      <div><h2>Compare Players</h2><div class="muted">Best real number in each category is highlighted.</div></div>
      <button class="modal-close" aria-label="Close">✕</button>
    </div>
    <div class="cmp-grid">${players.map((p, i) => cmpCardHtml(p, players, p.player_id === topId, i * 80)).join("")}</div>
  </div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeModal();
  });
  root.querySelector(".modal-close").addEventListener("click", closeModal);
  // Reuse the existing player-detail modal for "tell me more" — clicking a
  // compare card swaps modals rather than cramming the full breakdown in here too.
  root.querySelectorAll(".cmp-card[data-pid]").forEach((card) => {
    card.addEventListener("click", () => openPlayerModal(card.dataset.pid, state.opp));
  });

  const countEls = root.querySelectorAll(".cmp-row-val[data-target]");
  countEls.forEach((node) => {
    countUp(node, Number(node.dataset.target), {
      decimals: Number(node.dataset.decimals || 1),
      signed: node.dataset.signed === "1",
      duration: 650,
    });
  });
  setTimeout(() => {
    countEls.forEach((node) => { node.textContent += node.dataset.suffix || ""; });
  }, 680);
}

function initCompareTray() {
  $("#compare-open-btn").addEventListener("click", openCompareModal);
  $("#compare-clear-btn").addEventListener("click", () => {
    document.querySelectorAll(".cmp-check.selected").forEach((btn) => {
      btn.classList.remove("selected");
      btn.querySelector(".check").textContent = "";
      btn.setAttribute("aria-pressed", "false");
    });
    state.compareSelected.clear();
    renderCompareTray();
  });
}

// One list for every position, ranked by value over replacement (VOR) —
// see engine/value.py. PROJ is points per game; VOR is how many of those
// points beat the free replacement at his position.
function renderOverallBoard(data) {
  $("#board-head").innerHTML = `<th></th><th>Player</th><th>Tier</th><th title="Player Value Score: edge over a replacement player, comparable across positions">PVS</th><th>PROJ</th><th>VOR</th><th class="hide-mobile">Experts</th>`;
  const body = $("#board-body");
  body.innerHTML = "";
  const q = state.search.trim().toLowerCase();
  const rr = data.replacement_ranks || {};
  data.players
    .filter((p) => !q || (p.player_display_name || "").toLowerCase().includes(q) || (p.recent_team || "").toLowerCase().includes(q))
    .forEach((p, i) => {
      p.rank = p.overall_rank;
      const tr = el("tr", "kbd-click");
      tr.tabIndex = 0;
      tr.style.setProperty("--i", Math.min(i, 24));
      if (p.rank === 1) tr.classList.add("board-row-top");
      const selected = state.compareSelected.has(p.player_id);
      tr.innerHTML = `<td class="rank-cell">${esc(p.rank)}</td>
        <td><div class="board-player-row">
          <button type="button" class="cmp-check${selected ? " selected" : ""}" data-pid="${esc(p.player_id)}" aria-pressed="${selected}" aria-label="Compare ${esc(p.player_display_name)}" title="${selected ? "Remove from compare" : "Add to compare"}"><span class="check">${selected ? "✓" : ""}</span></button>
          ${playerCellHtml(p)}
        </div></td>
        <td>${tierPillHtml(p.tier)}</td>
        <td>${p.PVS == null ? "—" : scoreCell(p.PVS)}</td>
        <td>${FMT.d1(p.PROJ)}</td>
        <td><span class="vor-cell" title="Points per game above a free replacement ${esc(p.position)}">+${FMT.d1(p.VOR)}</span></td>
        <td class="hide-mobile">${ecrGapHtml(p)}</td>`;
      tr.querySelector(".cmp-check").addEventListener("click", (e) => {
        e.stopPropagation();
        toggleCompare(p, e.currentTarget);
      });
      tr.addEventListener("click", (e) => { rippleAt(tr, e); openPlayerModal(p.player_id, state.opp); });
      body.appendChild(tr);
    });
  $("#board-hint").textContent =
    `Ranked by PVS (Player Value Score, 0–100): how many points per game he gives a lineup over a free replacement at his position (replacement ≈ QB${rr.QB}, RB${rr.RB}, WR${rr.WR}, TE${rr.TE} in a ${data.league?.teams || 12}-team league), plus his usage, ceiling and stability. The expert consensus rank is shown for comparison and no longer moves anyone. That's why an elite tight end can outrank a good quarterback.`;
}

// A short expanding circle where you clicked — pure CSS animation, removed when done.
function rippleAt(node, e) {
  const r = node.getBoundingClientRect();
  const dot = document.createElement("span");
  dot.className = "click-ripple";
  dot.style.left = `${(e.clientX || r.left + r.width / 2) - r.left}px`;
  dot.style.top = `${(e.clientY || r.top + r.height / 2) - r.top}px`;
  node.classList.add("has-ripple");
  node.appendChild(dot);
  setTimeout(() => dot.remove(), 650);
}

async function loadBoard() {
  const loading = $("#board-loading");
  loading.style.display = "";
  loading.innerHTML = skeletonRows(10, 3);
  $("#board-table").style.display = "none";
  try {
    const url = `/api/board?pos=${state.pos}${state.opp ? `&opp=${state.opp}` : ""}${scoringQS()}`;
    const data = await api(url);
    state.boardWeek = data.week;
    state.boardLoaded = true;
    if (state.pos === "ALL") {
      renderOverallBoard(data);
      loading.style.display = "none";
      $("#board-table").style.display = "";
      animateScoreBars();
      return;
    }
    const cols = TABLE_COLS[state.pos] || [];
    renderBoardHead(cols, !!state.opp);
    renderBoardRows(data.players, cols, !!state.opp);
    $("#board-hint").textContent = state.opp
      ? `PROJ = projected points vs ${state.opp} this week — a real, multi-stat matchup read (run D, pass D, pressure), adjusted for recent form and your scoring.`
      : `PVS = 0–100 value over a replacement player: projected edge, usage, ceiling and stability. Pick an opponent above to see matchup-adjusted projections.`;
    loading.style.display = "none";
    $("#board-table").style.display = "";
    animateScoreBars();
  } catch (e) {
    loading.innerHTML = "Couldn't load data — is the server running with a live connection?";
    console.error(e);
  }
}

// -------------------------------------------------------------- modal -----
// Two independent modal roots (player detail, auth/reset-password) can't
// both be meaningfully open at once in normal use, but this stays correct
// either way: background scroll only unlocks once neither has content.
function syncModalScrollLock() {
  const anyOpen = $("#modal-root").innerHTML.trim() !== "" || $("#auth-modal-root").innerHTML.trim() !== "";
  // <html>, not <body>, is the actual scrolling element in standards mode —
  // locking only body leaves the page free to scroll behind the backdrop.
  document.documentElement.classList.toggle("modal-open", anyOpen);
  document.body.classList.toggle("modal-open", anyOpen);
}

function closeModal() {
  clearInterval(gameModalTimer);      // a closed box score must stop polling
  teamModalSeq++;                     // and a team page still loading must not paint into the next modal
  $("#modal-root").innerHTML = "";
  syncModalScrollLock();
}

// Friendly labels for the raw per-week counting-stat columns board.py's
// player_detail() now includes in weekly_log (position-dependent — a QB's
// weekly_log has different keys than a WR's, hence the fallback to the
// raw key itself for anything not in this map).
const WEEKLY_STAT_LABELS = {
  fpts: "Fantasy Points",
  completions: "Completions", attempts: "Attempts", passing_yards: "Passing Yards",
  passing_tds: "Passing TDs", passing_epa: "Passing EPA",
  carries: "Carries", rushing_yards: "Rushing Yards", rushing_tds: "Rushing TDs", rushing_epa: "Rushing EPA",
  targets: "Targets", receptions: "Receptions", receiving_yards: "Receiving Yards",
  receiving_tds: "Receiving TDs", receiving_epa: "Receiving EPA", receiving_air_yards: "Air Yards",
  receiving_yards_after_catch: "YAC", target_share: "Target Share",
};

// Each played week is judged against what he was projected for that week
// (Sleeper's pre-game projection, rescored under this league's settings):
// green = beat it, red = fell short, and a white tick marks the projection.
// Stats Sleeper doesn't project (EPA, air yards, target share...) have no
// projection to judge against, so they show plain bars with his average.
function weeklyChartHtml(weeks, statKey) {
  const vals = weeks.map((w) => w[statKey]).filter((v) => v != null);
  if (!vals.length) return '<span class="muted">No data logged for this stat yet.</span>';
  const projOf = (w) => (w.proj && !w.proj.out && w.proj[statKey] != null ? w.proj[statKey] : null);
  const projs = weeks.map(projOf).filter((v) => v != null);
  const hasProj = projs.length > 0;
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  const maxV = Math.max(1, avg, ...vals.map((v) => Math.max(0, v)), ...projs);
  const decimals = Number.isInteger(avg) && vals.every((v) => Number.isInteger(v)) ? 0 : 1;
  let beat = 0, judged = 0, diffSum = 0;
  const bars = weeks.map((w) => {
    const v = w[statKey];
    if (w.status === "bye") return `<div class="bar bar-bye" title="Week ${esc(w.week)}: BYE"><div class="bar-tag">BYE</div><div class="wk-label">${esc(w.week)}</div></div>`;
    if (w.status === "dnp") return `<div class="bar bar-dnp" title="Week ${esc(w.week)}: did not play (team played ${esc(w.opponent)})"><div class="bar-tag">OUT</div><div class="wk-label">${esc(w.week)}</div></div>`;
    if (v == null) return `<div class="bar" style="height:2%;opacity:.3" title="Week ${esc(w.week)}: no data"><div class="wk-label">${esc(w.week)}</div></div>`;
    const h = Math.max(2, (Math.max(0, v) / maxV) * 100);
    const pr = projOf(w);
    const opp = w.opponent ? ` vs ${w.opponent}` : "";
    let cls = "bar-none", tick = "", title;
    if (pr != null) {
      judged++; diffSum += v - pr;
      cls = v >= pr ? "bar-beat" : "bar-miss";
      if (v >= pr) beat++;
      const tickPct = ((pr / maxV) * 100 / h) * 100;
      tick = `<i class="proj-tick" style="bottom:${tickPct.toFixed(1)}%"></i>`;
      const d = v - pr;
      title = `Week ${w.week}${opp}: ${v.toFixed(decimals)} vs ${pr.toFixed(decimals)} projected (${d >= 0 ? "+" : ""}${d.toFixed(1)})`;
    } else {
      title = `Week ${w.week}${opp}: ${v.toFixed(decimals)}${w.proj && w.proj.out ? " (projected not to play)" : hasProj ? " (no projection)" : ""}`;
    }
    return `<div class="bar ${cls}" style="height:${h.toFixed(1)}%" title="${esc(title)}">${tick}
      <div class="bar-value">${v.toFixed(decimals)}</div>
      <div class="wk-label">${esc(w.week)}</div>
    </div>`;
  }).join("");
  if (!hasProj) {
    const avgPct = Math.max(0, Math.min(100, (avg / maxV) * 100));
    const avgLine = avg > 0 ? `<div class="weeklog-avg-line" style="bottom:${avgPct}%" data-label="Avg ${avg.toFixed(decimals)}"></div>` : "";
    return `<div class="weeklog-note muted small">No weekly projection exists for this stat. The dashed line is his average.</div><div class="weeklog weeklog-plain">${avgLine}${bars}</div>`;
  }
  const avgDiff = judged ? diffSum / judged : 0;
  const verdict = judged
    ? `<div class="weeklog-verdict"><b>Beat his projection in ${beat} of ${judged} games</b><span class="${avgDiff >= 0 ? "pos" : "neg"}">${avgDiff >= 0 ? "+" : ""}${avgDiff.toFixed(1)} per game vs projected</span></div>`
    : "";
  const legend = `<div class="weeklog-legend"><span><i class="lg-beat"></i>Beat projection</span><span><i class="lg-miss"></i>Fell short</span><span><i class="lg-tick"></i>What he was projected</span><span><i class="lg-none"></i>No projection</span><span>Week number under each bar</span></div>`;
  return `${verdict}<div class="weeklog">${bars}</div>${legend}`;
}

async function openPlayerModal(playerId, opp) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal"><div class="loading">Loading…</div></div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeModal();
  });

  // If the loading modal is closed (Escape/backdrop) or replaced by another
  // player before the fetch lands, don't pop it back open.
  const req = String(Date.now() + Math.random());
  root.dataset.req = req;
  const stillWanted = () => root.dataset.req === req && root.innerHTML.trim() !== "";
  let p;
  try {
    const oppQS = opp ? `&opp=${opp}` : "";
    p = await api(`/api/player/${playerId}?${scoringQS().replace(/^&/, "")}${oppQS}`);
  } catch (e) {
    if (stillWanted()) root.querySelector(".modal").innerHTML = `<div class="empty">Couldn't load player.</div>`;
    return;
  }
  if (!stillWanted()) return;

  root.innerHTML = `<div class="modal-backdrop"><div class="modal pcard" style="${teamThemeStyle(p.recent_team)}">${playerCardHtml(p)}</div></div>`;

  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeModal();
  });
  root.querySelector(".modal-close").addEventListener("click", closeModal);
  wirePlayerCard(root, p);

  // Fetched separately from the rest of the modal (real RSS + an optional
  // AI summary can take a moment, especially the AI call) so opening the
  // modal never waits on it.
  loadPlayerNews(playerId, root);
}

// The week-by-week rows for the chart: every week up to the last one that
// has happened, with BYE and missed (did-not-play) weeks kept in so a gap is
// obvious instead of silently skipped. Falls back to the plain played list.
function weeklyRows(p) {
  const all = p.weekly_status;
  if (!all || !all.length) return p.weekly_log || [];
  const lastReal = Math.max(0, ...all.filter((w) => w.status === "played" || w.status === "dnp").map((w) => w.week));
  const through = Math.max(lastReal, Number(state.boardWeek) || 0, 1);
  return all.filter((w) => w.week <= through && (w.status !== "upcoming" || w.week < through));
}

function fmtTotal(v, dec) { return v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: dec || 0 }); }

const TOTAL_LABELS = {
  attempts: "Pass Att", completions: "Comp", passing_yards: "Pass Yds", passing_tds: "Pass TD", interceptions: "INT",
  sacks: "Sacked", carries: "Carries", rushing_yards: "Rush Yds", rushing_tds: "Rush TD", targets: "Targets",
  receptions: "Rec", receiving_yards: "Rec Yds", receiving_tds: "Rec TD", fumbles_lost: "Fumbles Lost",
};

function valueStripHtml(p) {
  if (p.bye_week == null) return "";
  return `<div class="value-strip"><span class="bye-chip">BYE week ${esc(p.bye_week)}</span></div>`;
}

function totalsHtml(p, bare = false) {
  const t = p.totals;
  if (!t) return "";
  const keys = Object.keys(TOTAL_LABELS).filter((k) => t[k] != null && (t[k] !== 0 || ["interceptions", "fumbles_lost"].includes(k)));
  const tiles = keys.map((k) => `<div class="metric-tile"><div class="label">${TOTAL_LABELS[k]}</div><div class="value">${fmtTotal(t[k])}</div></div>`).join("");
  const grid = `<div class="metric-grid stagger-in">${tiles}</div>`;
  return bare ? grid : `<div class="section-label">Season Stats</div>${grid}`;
}

// Next Gen Stats as a scouting report. Skill stats get a letter grade from
// his percentile among same-position peers (A = top 20%, F = bottom 20%),
// colored green to red. Style stats (how he plays, not how well) get no
// grade and no good/bad color: just the word for his style.
const NGS_GRADES = [[80, "A", "g-a"], [60, "B", "g-b"], [40, "C", "g-c"], [20, "D", "g-d"], [0, "F", "g-f"]];
function ngsGrade(pct) { return NGS_GRADES.find(([min]) => pct >= min); }

function ngsHtml(p) {
  const rows = p.ngs || [];
  if (!rows.length) return "";
  const pos = esc(p.position);
  const graded = rows.filter((n) => n.higher_is_better != null && n.percentile != null).sort((a, b) => b.percentile - a.percentile);
  const style = rows.filter((n) => n.higher_is_better == null && n.percentile != null && n.style);
  const val = (n) => fmtTotal(n.value, n.value != null && Math.abs(n.value) >= 100 ? 0 : 1);
  const cards = graded.map((n) => {
    const [, letter, cls] = ngsGrade(n.percentile);
    return `<div class="sr-card ${cls}">
      <div class="sr-grade">${letter}</div>
      <div class="sr-body">
        <div class="sr-name">${esc(n.label)}</div>
        <div class="sr-line"><b>${val(n)}</b> · better than ${n.percentile}% of ${pos}s</div>
        ${n.tip ? `<div class="sr-tip">${esc(n.tip)}</div>` : ""}
      </div>
    </div>`;
  }).join("");
  const styles = style.map((n) => {
    const [lowWord, highWord] = n.style;
    const pct = n.percentile;
    const word = pct >= 67 ? highWord : pct <= 33 ? lowWord : "Typical";
    const where = pct >= 67 ? `higher than ${pct}% of ${pos}s` : pct <= 33 ? `lower than ${100 - pct}% of ${pos}s` : `middle of the pack`;
    return `<div class="sr-style" title="${esc(n.tip || "")}">
      <div class="sr-style-word">${esc(word)}</div>
      <div class="sr-style-stat">${esc(n.label)}: <b>${val(n)}</b></div>
      <div class="sr-style-where">${esc(where)}</div>
    </div>`;
  }).join("");
  const strengths = graded.filter((n) => n.percentile >= 80).slice(0, 2).map((n) => esc(n.label));
  const weak = graded.filter((n) => n.percentile < 40).slice(-2).map((n) => esc(n.label));
  const summary = graded.length
    ? `<div class="sr-summary">${strengths.length ? `<span><em class="pos">Strengths</em> ${strengths.join(", ")}</span>` : ""}${weak.length ? `<span><em class="neg">Weak spots</em> ${weak.join(", ")}</span>` : ""}${!strengths.length && !weak.length ? "<span>No clear strengths or weak spots. Solid across the board.</span>" : ""}</div>`
    : "";
  return `<div class="section-label">Next Gen Stats <span class="muted small">scouting report, graded against other ${pos}s</span></div>
    ${summary}
    ${cards ? `<div class="sr-grid">${cards}</div>` : ""}
    ${styles ? `<div class="sr-sub">Play style <span class="muted small">how he plays, not how well</span></div><div class="sr-styles">${styles}</div>` : ""}`;
}

// ---- Team theme -------------------------------------------------------
// The player card tints itself with the team's accent. The colors come from the one palette table
// (static/team-themes.js), the same one the favorite-team theme uses, so the two can never disagree.
const TEAM_ALIAS = { LAR: "LA", JAC: "JAX", WSH: "WAS", OAK: "LV", SD: "LAC", STL: "LA", ARZ: "ARI", BLT: "BAL", CLV: "CLE", HST: "HOU", SL: "LA" };
function teamThemeStyle(team) {
  const palette = TeamTheme.get(TEAM_ALIAS[team] || team);
  if (!palette) return "";
  const n = parseInt(palette.primary.slice(1), 16);
  return `--tm:${palette.primary};--tm-rgb:${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

// The Settings picker (static/theme.js) saves the choice to the account through the same settings endpoint as everything else.
ThemePicker.configure({
  isSignedIn: () => !!state.user,
  saveToAccount: (code) => api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme: code }) }),
});

// ---- Scouting ---------------------------------------------------------
// The same real Next Gen percentiles as ngsHtml, but as a read, a shape and
// sliders instead of letter grades. All of it is computed from p.ngs.
function scoutTier(pct) {
  return pct >= 90 ? "Elite" : pct >= 70 ? "Strong" : pct >= 40 ? "Average" : pct >= 20 ? "Below avg" : "Weak";
}
// Madden-style letter grade for a percentile vs same-position players.
function scoutGrade(pct) {
  return pct >= 90 ? "A" : pct >= 70 ? "B" : pct >= 40 ? "C" : pct >= 20 ? "D" : "F";
}
// "Beat projection in N of M games (+x / G)" from the weeks that have both a
// real score and a pre-game projection; empty when fewer than 2 qualify.
function beatProjChipHtml(p) {
  const rows = (p.weekly_status || []).filter((w) => w.status === "played" && w.fpts != null
    && w.proj && !w.proj.out && w.proj.fpts != null);
  if (rows.length < 2) return "";
  const beat = rows.filter((w) => w.fpts >= w.proj.fpts).length;
  const per = rows.reduce((a, w) => a + (w.fpts - w.proj.fpts), 0) / rows.length;
  const good = beat * 2 >= rows.length;
  return `<span class="pcd-chip beat ${good ? "up" : "down"}" title="Actual points vs. Sleeper's pre-game projection, rescored for your league">`
    + `${good ? "Beat" : "Missed"} projection in ${beat} of ${rows.length} (${per >= 0 ? "+" : ""}${per.toFixed(1)} / G)</span>`;
}
function scoutHue(pct) { return Math.round(pct * 1.3); } // 0 red -> 130 green
const ordinal = (n) => { const v = n % 100; return n + (["th", "st", "nd", "rd"][(v - 20) % 10] || ["th", "st", "nd", "rd"][v] || "th"); };

// Six traits per position, each a real NGS percentile. `inv` flips a stat
// where a LOW number is the trait (quick release = low time to throw).
const RADAR_WR = [["Separation", "avg_separation"], ["After catch", "avg_yac_above_expectation"], ["YAC", "avg_yac"],
  ["Deep role", "avg_intended_air_yards"], ["Target share", "percent_share_of_intended_air_yards"], ["Hands", "catch_percentage"]];
const RADAR_AXES = {
  QB: [["Accuracy", "completion_percentage_above_expectation"], ["Quick release", "avg_time_to_throw", true], ["Deep game", "avg_intended_air_yards"],
    ["Risk taking", "aggressiveness"], ["Big plays", "max_completed_air_distance"], ["Efficiency", "passer_rating"]],
  RB: [["Creation", "rush_yards_over_expected_per_att"], ["Beats expected", "rush_pct_over_expected"], ["Decisive", "avg_time_to_los", true],
    ["Downhill", "efficiency"], ["Loaded boxes", "percent_attempts_gte_eight_defenders"], ["Yds / carry", "avg_rush_yards"]],
  WR: RADAR_WR, TE: RADAR_WR,
};

function scoutAxes(p) {
  const by = Object.fromEntries((p.ngs || []).filter((n) => n.percentile != null).map((n) => [n.key, n.percentile]));
  return (RADAR_AXES[p.position] || []).filter(([, k]) => by[k] != null).map(([label, k, inv]) => ({ label, pct: inv ? 100 - by[k] : by[k] }));
}

function scoutRadarHtml(axes, team) {
  if (axes.length < 3) return "";
  const c = 160, cy = 118, R = 80, n = axes.length;
  const pt = (i, r) => [c + Math.sin(i * 2 * Math.PI / n) * r, cy - Math.cos(i * 2 * Math.PI / n) * r];
  const ring = (f) => axes.map((_, i) => pt(i, R * f).join(",")).join(" ");
  const poly = axes.map((a, i) => pt(i, R * Math.max(a.pct, 4) / 100).join(",")).join(" ");
  const labels = axes.map((a, i) => {
    const [x, y] = pt(i, R + 20);
    const anchor = x < c - 8 ? "end" : x > c + 8 ? "start" : "middle";
    return `<text class="rd-l" x="${x.toFixed(1)}" y="${(y - 1).toFixed(1)}" text-anchor="${anchor}">${esc(a.label)}</text><text class="rd-n" x="${x.toFixed(1)}" y="${(y + 11).toFixed(1)}" text-anchor="${anchor}">${a.pct}</text>`;
  }).join("");
  return `<svg class="scs-radar" viewBox="0 0 320 236" role="img" aria-label="Player shape: ${axes.map((a) => `${esc(a.label)} ${a.pct}`).join(", ")}">
    ${[.25, .5, .75, 1].map((f) => `<polygon points="${ring(f)}" class="rd-ring${f === .5 ? " avg" : ""}"/>`).join("")}
    ${axes.map((_, i) => `<line x1="${c}" y1="${cy}" x2="${pt(i, R)[0].toFixed(1)}" y2="${pt(i, R)[1].toFixed(1)}" class="rd-ax"/>`).join("")}
    <polygon points="${poly}" class="rd-shape"/>
    ${axes.map((a, i) => { const [x, y] = pt(i, R * Math.max(a.pct, 4) / 100); return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.6" class="rd-dot"/>`; }).join("")}
    ${labels}
  </svg>`;
}

// Archetype headline + one honest sentence, picked by rules on his own
// percentiles (never invented text). Falls back to "Balanced".
function scoutArchetype(p, g) {
  const pos = p.position;
  if (pos === "QB") {
    const ttt = g("avg_time_to_throw"), iay = g("avg_intended_air_yards"), agg = g("aggressiveness"), cpoe = g("completion_percentage_above_expectation");
    if (ttt != null && iay != null && ttt <= 33 && iay <= 33) return ["Quick-game distributor", "Gets the ball out fast and short, and rarely forces it."];
    if (iay != null && agg != null && iay >= 66 && agg >= 66) return ["Gunslinger", "Pushes the ball downfield and throws into tight windows."];
    if (iay != null && iay >= 66) return ["Vertical passer", "Aims deeper than most QBs."];
    if (ttt != null && ttt >= 66) return ["Pocket holder", "Takes his time and lets plays develop."];
    if (cpoe != null && cpoe >= 66) return ["Precision passer", "Completes throws the difficulty says he shouldn't."];
    return ["Balanced passer", "No extreme style: sits near the QB average."];
  }
  if (pos === "RB") {
    const cr = g("rush_yards_over_expected_per_att"), ns = g("efficiency"), tl = g("avg_time_to_los"), box = g("percent_attempts_gte_eight_defenders");
    if (cr != null && cr >= 66) return ["Chunk-play creator", "Gains more than the blocking gives him."];
    if (ns != null && ns >= 66 && (tl == null || tl <= 50)) return ["Downhill runner", "Hits the hole and runs straight ahead."];
    if (tl != null && tl >= 66) return ["Patient zone runner", "Lets blocks develop before he commits."];
    if (box != null && box >= 66) return ["Defense's main focus", "Sees loaded boxes more than most backs."];
    return ["Balanced back", "No extreme style: sits near the RB average."];
  }
  const sep = g("avg_separation"), yx = g("avg_yac_above_expectation"), yac = g("avg_yac"), iay = g("avg_intended_air_yards"), sh = g("percent_share_of_intended_air_yards"), ct = g("catch_percentage");
  if (sh != null && sh >= 66 && (sep == null || sep >= 50)) return ["Alpha target", "The offense runs through him: a big share of the targeted air yards, and he gets open."];
  if (iay != null && iay >= 66) return ["Deep threat", "His targets come downfield."];
  if ((yx != null && yx >= 66) || (yac != null && yac >= 66)) return ["After-catch weapon", "Turns short catches into big gains."];
  if (sep != null && sep >= 66) return ["Separator", "Gets open more cleanly than most."];
  if (ct != null && ct >= 66 && (iay == null || iay <= 40)) return ["Chain mover", "Reliable hands on shorter targets."];
  return [`Balanced ${pos}`, `No extreme style: sits near the ${pos} average.`];
}

function scoutReadHtml(p, axes) {
  const by = Object.fromEntries((p.ngs || []).filter((n) => n.percentile != null).map((n) => [n.key, n.percentile]));
  const g = (k) => (by[k] != null ? by[k] : null);
  const [title, line] = scoutArchetype(p, g);
  const bits = [];
  if (axes.length >= 3) {
    const hi = axes.reduce((a, b) => (b.pct > a.pct ? b : a)), lo = axes.reduce((a, b) => (b.pct < a.pct ? b : a));
    if (hi.pct - lo.pct >= 15) bits.push(`Best trait: <b>${esc(hi.label)}</b> (${ordinal(hi.pct)} percentile). Softest: <b>${esc(lo.label)}</b> (${ordinal(lo.pct)}).`);
  }
  if (p.position === "QB" && g("expected_completion_percentage") >= 66 && g("completion_percentage_above_expectation") != null && g("completion_percentage_above_expectation") < 50) {
    bits.push(`His throws are among the easiest in the league, so a high completion rate is partly the scheme. Adjusted for that, accuracy is ${g("completion_percentage_above_expectation") < 40 ? "below" : "about"} average.`);
  }
  return `<div class="scs-read"><div class="scs-arch">${esc(title)}</div><p class="scs-line">${esc(line)}</p>${bits.map((b) => `<p class="scs-bit">${b}</p>`).join("")}</div>`;
}

// Weekly NGS values as a tiny line plus whether the latest game is up or
// down against his earlier ones.
function scoutTrend(n) {
  const v = (n.weekly || []).map((w) => w.value).filter((x) => x != null);
  if (v.length < 3) return { spark: "", tag: "" };
  const last = v[v.length - 1], prev = v.slice(0, -1), avg = prev.reduce((a, b) => a + b, 0) / prev.length;
  const range = Math.max(...v) - Math.min(...v), d = last - avg;
  const flat = !range || Math.abs(d) < range * 0.15;
  const good = n.higher_is_better === false ? d < 0 : d > 0;
  const cls = flat ? "flat" : n.higher_is_better == null ? "neu" : good ? "up" : "dn";
  const w = 54, h = 18, mn = Math.min(...v);
  const pts = v.map((x, i) => `${(2 + i * (w - 4) / (v.length - 1)).toFixed(1)},${(h - 2 - ((x - mn) / (range || 1)) * (h - 4)).toFixed(1)}`).join(" ");
  return {
    spark: `<svg class="scs-spark ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}"/></svg>`,
    tag: `<span class="scs-trend ${cls}">${flat ? "steady" : d > 0 ? "▲ up lately" : "▼ down lately"}</span>`,
  };
}

// Fantasy floor / average / ceiling from the consistency numbers the app
// already computes.
function fantasyRangeHtml(p) {
  const c = p.consistency;
  if (!c || c.games == null || c.games < 1 || c.best == null || c.worst == null) return "";
  const hi = c.best * 1.12 || 1, pos = (v) => Math.max(0, Math.min(100, (v / hi) * 100));
  const small = c.games < 4 ? `<span class="muted small">only ${c.games} game${c.games === 1 ? "" : "s"} so far</span>` : "";
  return `<div class="pcd-lbl" style="margin-top:20px"><span>Fantasy Range</span>${small}</div>
    <div class="pcd-range">
      <div class="rg-bar" style="left:${pos(c.worst)}%;width:${Math.max(pos(c.best) - pos(c.worst), 2)}%"></div>
      <div class="rg-avg" style="left:${pos(c.mean)}%"><span>Avg ${FMT.d1(c.mean)}</span></div>
      <div class="rg-end lo" style="left:${pos(c.worst)}%"><b>Floor</b> ${FMT.d1(c.worst)}</div>
      <div class="rg-end hi" style="left:${pos(c.best)}%"><b>Ceiling</b> ${FMT.d1(c.best)}</div>
    </div>
    <div class="pcd-rgchips"><span class="scs-chip pos">Boom weeks ${Math.round(c.boom_rate)}%</span><span class="scs-chip ${c.bust_rate ? "neg" : ""}">Bust weeks ${Math.round(c.bust_rate)}%</span><span class="scs-chip">Swing ±${FMT.d1(c.std)}</span></div>`;
}

function careerHtml(p) {
  const h = p.history;
  const name = esc(p.player_display_name || "This player");
  if (!h) return "";
  if (!h.seasons || !h.seasons.length) {
    return `<div class="pcd-lbl" style="margin-top:20px"><span>Career</span></div>
      <div class="muted small">No earlier seasons on file for ${name}. Rookies and new players project from this season and the position average.</div>`;
  }
  const cons = p.consistency || {};
  const rows = [{ label: String(h.seasons[0].season + 1), team: p.recent_team, games: p.games, ppg: p.fpts_per_game, best: cons.best, worst: cons.worst, now: true },
    ...h.seasons.map((x) => ({ label: String(x.season), team: x.team, games: x.games, ppg: x.ppg, best: x.best, worst: x.worst }))];
  const top = Math.max(1, ...rows.map((r) => r.ppg || 0));
  const range = (r) => (r.best != null && r.worst != null ? ` · ${FMT.d1(r.worst)}&ndash;${FMT.d1(r.best)}` : "");
  const lines = rows.map((r) => `<div class="cr-row${r.now ? " now" : ""}">
      <span class="cr-y">${esc(r.label)}${r.now ? "<em>so far</em>" : ""}</span><span class="cr-t">${esc(r.team || "")}</span>
      <div class="cr-bar"><i style="width:${Math.max(3, ((r.ppg || 0) / top) * 100)}%"></i></div>
      <b>${r.ppg == null ? "—" : FMT.d1(r.ppg)}</b><small>${esc(r.games)} g${range(r)}</small></div>`).join("");
  const lean = h.weight != null && h.weight > 0 ? `<span class="scs-chip">Projection leans ~${Math.round(h.weight * 100)}% on history</span>` : "";
  return `<div class="pcd-lbl" style="margin-top:20px"><span>Career · points per game</span><span class="muted small">last ${esc(h.seasons.length)} season${h.seasons.length === 1 ? "" : "s"}</span></div>
    <div class="cr">${lines}</div>
    <div class="pcd-rgchips"><span class="scs-chip pos">Career ${FMT.d1(h.career_ppg)} PPG</span><span class="scs-chip">${esc(h.career_games)} games</span>${lean}</div>
    <div class="muted small" style="margin-top:6px">Newest seasons count most. Rate shown under your league scoring.</div>`;
}

function scoutingSlidersHtml(p) {
  const rows = (p.ngs || []).filter((n) => n.percentile != null);
  if (!rows.length) return "";
  const pos = esc(p.position);
  const val = (n) => fmtTotal(n.value, n.value != null && Math.abs(n.value) >= 100 ? 0 : 1);
  const skill = rows.filter((n) => n.higher_is_better != null).sort((a, b) => b.percentile - a.percentile);
  const style = rows.filter((n) => n.higher_is_better == null && n.style);
  const skillRow = (n, i) => {
    const h = scoutHue(n.percentile), t = scoutTrend(n);
    return `<div class="scs-row" style="--p:${n.percentile};--h:${h};--d:${i * 70}ms" title="${esc(n.tip || "")}">
      <div class="scs-top"><span class="scs-name">${esc(n.label)}</span><span class="scs-val">${t.spark}${val(n)}</span></div>
      <div class="scs-track skill"><i class="scs-fill"></i><b class="scs-orb">${n.percentile}</b></div>
      <div class="scs-sub"><span><b class="scs-grade" style="--h:${h}">${scoutGrade(n.percentile)}</b> <span class="scs-tier">${scoutTier(n.percentile)}</span> ${t.tag}</span><span>better than ${n.percentile}% of ${pos}s</span></div>
    </div>`;
  };
  const styleRow = (n, i) => {
    const [lo, hi] = n.style, t = scoutTrend(n);
    const side = n.percentile >= 60 ? "hi" : n.percentile <= 40 ? "lo" : "mid";
    return `<div class="scs-row sty" style="--p:${n.percentile};--d:${i * 70}ms" title="${esc(n.tip || "")}">
      <div class="scs-top"><span class="scs-name">${esc(n.label)}</span><span class="scs-val">${t.spark}${val(n)}</span></div>
      <div class="scs-track style"><b class="scs-orb">${n.percentile}</b></div>
      <div class="scs-ends"><span class="${side === "lo" ? "on" : ""}">${esc(lo)}</span><span class="${side === "hi" ? "on" : ""}">${esc(hi)}</span></div>
    </div>`;
  };
  const strong = skill.filter((n) => n.percentile >= 70).slice(0, 2);
  const weak = skill.filter((n) => n.percentile < 40).slice(-2);
  const chips = [...strong.map((n) => `<span class="scs-chip pos">${esc(n.label)}</span>`), ...weak.map((n) => `<span class="scs-chip neg">${esc(n.label)}</span>`)].join("");
  const axes = scoutAxes(p), radar = scoutRadarHtml(axes, p.recent_team);
  return `<div class="pcd-lbl"><span>Scouting Report</span><span class="scs-legend">vs other ${pos}s</span></div>
    <div class="scs-hero${radar ? "" : " solo"}">${scoutReadHtml(p, axes)}${radar ? `<div class="scs-shape"><div class="scs-cap">Shape · percentile vs ${pos}s</div>${radar}</div>` : ""}</div>
    ${chips ? `<div class="scs-chips">${chips}</div>` : ""}
    ${skill.length ? `<div class="pcd-sub">How good he is <span class="scs-legend">line = league average</span></div><div class="scs-list">${skill.map(skillRow).join("")}</div>` : ""}
    ${style.length ? `<div class="pcd-sub">How he plays</div><div class="scs-list">${style.map(styleRow).join("")}</div>` : ""}`;
}

// The SCORE/FORM/matchup grid + per-stat gauges + weekly chart — shared
// between the full player modal and the inline expand-in-place panel on
// a Start/Sit card (see startSitCardHtml/toggleSSExpand below), so both
// surfaces show the exact same real breakdown instead of two versions
// drifting apart. Scoped by `.closest(container)` in wirePlayerStatsBody
// rather than a hardcoded id, since more than one of these can be open
// at once (several expanded Start/Sit cards) — an id would collide.
function detailSectionsHtml(p, labelCls = "section-label") {
  // Every percentage-based stat gets a little breakdown bar under its
  // number — a real visual, not just a number, for every stat that has
  // a natural 0–100 scale to plot against.
  return (DETAIL_METRICS[p.position] || []).map(([label, metrics]) => {
    const tiles = metrics.map(([key, mlabel, fmt]) => {
      const raw = p[key];
      const gauge = fmt === FMT.pct && raw != null
        ? `<div class="gauge"><span style="width:${Math.max(0, Math.min(100, raw))}%"></span></div>` : "";
      // "Games" alone reads as "this many games so far" — tag it with the
      // actual season it's counting, since the underlying data source
      // (nflverse) currently tops out at a completed prior season rather
      // than the season that's actually live right now.
      const gLabel = key === "games" && state.meta?.season ? `${mlabel} (${state.meta.season})` : mlabel;
      return `<div class="metric-tile"><div class="label">${esc(gLabel)}</div><div class="value">${fmt(raw)}</div>${gauge}</div>`;
    }).join("");
    return `<div class="${labelCls}">${esc(label)}</div><div class="metric-grid">${tiles}</div>`;
  }).join("");
}

// The "Fantasy Points / Passing Yards / ..." picker above the weekly chart,
// or "" when he only has the one stat to show.
function weeklyStatSelectHtml(p) {
  const statKeys = ["fpts", ...Object.keys((p.weekly_log || [])[0] || {}).filter((k) => !["week", "opponent_team", "fpts"].includes(k))];
  if (statKeys.length < 2) return "";
  const statOptions = statKeys.map((k) => `<option value="${esc(k)}">${esc(WEEKLY_STAT_LABELS[k] || k)}</option>`).join("");
  return `<select class="weeklog-stat-select">${statOptions}</select>`;
}

function playerStatsBodyHtml(p) {
  const sections = detailSectionsHtml(p);
  const weeks = weeklyRows(p);
  const matchupLine = p.matchup_factor != null
    ? `<div class="metric-tile"><div class="label">Matchup vs ${esc(p.matchup_opponent)}</div><div class="value">${p.matchup_factor.toFixed(2)}x</div></div>` : "";

  return `
    <div class="metric-grid">
      <div class="metric-tile"><div class="label">PVS</div><div class="value" style="color:var(--accent)">${FMT.d1(p.SCORE)}</div></div>
      <div class="metric-tile"><div class="label">FORM</div><div class="value">${formCell(p.FORM)}</div></div>
      <div class="metric-tile"><div class="label">FPTS/G</div><div class="value">${FMT.d1(p.fpts_per_game)}</div></div>
      ${matchupLine}
    </div>
    ${valueStripHtml(p)}
    <div class="section-label weeklog-header">
      <span>Weekly Breakdown</span>
      ${weeklyStatSelectHtml(p)}
    </div>
    <div class="weeklog-wrap">${weeks.length ? weeklyChartHtml(weeks, "fpts") : '<span class="muted">No games logged yet.</span>'}</div>
    ${totalsHtml(p)}
    ${projectionCompareSlotHtml()}
    ${sections}
    ${ngsHtml(p)}`;
}

// --------------------------------------------------- player card (modal) ----
// The full-size player card: banner + identity, an action bar, a sticky
// section bar, then Overview / Projection / Weekly / Stats / Scouting / News.
// Every section reuses the same builders the inline Start/Sit panel uses
// (weeklyChartHtml, totalsHtml, detailSectionsHtml, ngsHtml, the projection
// and news slots) so a number never differs between the two surfaces.
const SCORING_LABELS = { "": "PPR", half_ppr: "Half PPR", standard: "Standard", te_premium: "TE Premium", league: "My League" };
const CARD_SECTIONS = [["ov", "Overview"], ["pj", "Projection"], ["st", "Stats"], ["sc", "Scouting"], ["nw", "News"]];

// matchup_factor multiplies his projection against this defense, so 1.00 is
// an average defense. Within 5% either way reads as neutral: a judgment-call
// band, not a fitted threshold.
function matchupTagHtml(f) {
  if (f >= 1.05) return '<span class="pcd-tag soft">Soft</span>';
  if (f <= 0.95) return '<span class="pcd-tag tough">Tough</span>';
  return '<span class="pcd-tag">Neutral</span>';
}

function scoreRingHtml(score) {
  const r = 19, len = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score ?? 0)) / 100;
  return `<svg class="pcd-ring" viewBox="0 0 46 46" aria-hidden="true">
    <circle cx="23" cy="23" r="${r}" class="pcd-ring-bg"/>
    <circle cx="23" cy="23" r="${r}" class="pcd-ring-fg" transform="rotate(-90 23 23)"
      style="--len:${len.toFixed(1)};stroke-dasharray:${len.toFixed(1)};stroke-dashoffset:${(len * (1 - pct)).toFixed(1)}"/>
  </svg>`;
}

// Form is a percent change; the meter fills left (red) or right (green)
// from the middle, full half at 10%.
function formMeterHtml(form) {
  if (form == null) return "";
  const w = Math.min(50, (Math.abs(form) / 10) * 50);
  return `<div class="pcd-meter" aria-hidden="true"><i class="${form < 0 ? "neg" : "pos"}" style="width:${w.toFixed(1)}%"></i></div>`;
}

function agoText(iso) {
  const t = Date.parse(iso || "");
  if (!t) return "";
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 60) return `${m || 1} min ago`;
  if (m < 60 * 24) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} d ago`;
}

// Live injury report (engine/injuries.py): status, what, when he is expected
// back, ESPN's latest note, and what that designation has meant for scoring.
function injuryReportHtml(p) {
  const i = p.injury;
  if (!i) return "";
  const severe = ["Out", "IR", "PUP", "Sus"].includes(i.status);
  const what = [i.body_part, i.detail, i.side].filter(Boolean).map(esc).join(" · ");
  let back = "";
  if (i.return_date) {
    const d = new Date(`${i.return_date}T12:00:00`);
    const when = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    const wk = i.return_week ? ` (Week ${esc(i.return_week)})` : "";
    const out = i.games_out > 0 ? ` · misses about ${esc(i.games_out)} more game${i.games_out === 1 ? "" : "s"}` : i.games_out === 0 ? " · no games missed" : "";
    back = `<div class="inj-row"><span>Expected back</span><b>${esc(when)}${wk}</b><small>${out.replace(/^ · /, "")} · ESPN's estimate</small></div>`;
  } else {
    back = `<div class="inj-row"><span>Expected back</span><b>No date reported</b></div>`;
  }
  const im = i.impact;
  const impact = im ? `<div class="inj-line">Players listed ${esc(im.status)} with a ${esc(String(im.body_part).toLowerCase())} injury have scored about <b>${Math.abs(Math.round(im.median_pct_change * 100))}% ${im.median_pct_change < 0 ? "below" : "above"}</b> their usual (${esc(im.real_sample_size)} past cases). It is already in his projection.</div>` : "";
  const pc = i.play_chance;
  const chance = pc ? `<div class="inj-row"><span>Chance he plays</span><b>${Math.round(pc.p_play * 100)}%</b><small>${esc(pc.basis)}</small></div>` : "";
  const when = agoText(i.updated);
  return `<div class="inj-card${severe ? " severe" : ""}">
    <div class="inj-top"><span class="injury-flag${severe ? "" : " questionable"}">${esc(String(i.status).toUpperCase())}</span><b>Injury report</b>
      <span class="muted small">${esc(i.source)}${when ? ` · updated ${esc(when)}` : ""}</span></div>
    ${what ? `<div class="inj-row"><span>Injury</span><b>${what}</b></div>` : ""}
    ${back}
    ${chance}
    ${i.note ? `<div class="inj-note">${esc(i.note)}</div>` : ""}
    <div class="inj-line muted">${esc(i.meaning || "")}</div>${impact}
  </div>`;
}

function cardKeyTilesHtml(p) {
  const mf = p.matchup_factor;
  const matchup = mf != null
    ? `<div class="pcd-tile"><div class="l">Matchup vs ${esc(p.matchup_opponent)}</div><div class="v">${mf.toFixed(2)}x${matchupTagHtml(mf)}</div><div class="n">vs an average defense</div></div>` : "";
  return `<div class="pcd-keys">
    <div class="pcd-tile"><div class="l">PVS</div><div class="pcd-score"><div class="v" style="color:var(--accent)">${FMT.d1(p.SCORE)}</div>${scoreRingHtml(p.SCORE)}</div><div class="n">out of 100</div></div>
    <div class="pcd-tile"><div class="l">Form</div><div class="v">${formCell(p.FORM)}</div>${formMeterHtml(p.FORM)}</div>
    <div class="pcd-tile"><div class="l">FPTS/G</div><div class="v">${FMT.d1(p.fpts_per_game)}</div><div class="n">Fantasy pts per game</div></div>
    ${matchup}
  </div>`;
}

const CARD_ICONS = {
  compare: '<path d="M5 3v14M15 3v14M2 7h6M12 13h6"/>',
  startsit: '<path d="M6 5l-3 3 3 3M3 8h9M14 12l3 3-3 3M17 15H8"/>',
  trade: '<path d="M13 3l3 3-3 3M16 6H4M7 17l-3-3 3-3M4 14h12"/>',
};
const cardIcon = (k) => `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${CARD_ICONS[k]}</svg>`;

// Overview teaser for the scouting tab: the archetype in one line and a
// jump to the full report.
function scoutGlanceHtml(p) {
  if (!(p.ngs || []).some((n) => n.percentile != null)) return "";
  const by = Object.fromEntries(p.ngs.filter((n) => n.percentile != null).map((n) => [n.key, n.percentile]));
  const [title, line] = scoutArchetype(p, (k) => (by[k] != null ? by[k] : null));
  return `<button type="button" class="pcd-glance" data-go="sc">
    <span class="pg-l">Scouting read</span><span class="pg-t">${esc(title)}</span><span class="pg-s">${esc(line)}</span>
    <span class="pg-go">Full scouting report</span></button>`;
}

// ---- Projection tab: next game in detail, then the weeks after ----------
// Everything comes from /api/player/{id}/ros (engine/ros_projection.py):
// his role baseline, the betting-line and defense multipliers, the 10th /
// 50th / 90th percentile range, and how he has scored so far against easy
// and hard defenses. Past matchups are one season of games, so they are
// small samples and the card says so.
const PJ_TIER = { soft: "Soft", neutral: "Neutral", tough: "Tough" };

// ------------------------------------------------ this week's projection ----
// One number, its honest range, and what moved it (engine/tools.projection_explain).
function explainSlotHtml() {
  return `<div class="wp-slot"><div class="loading small">Working out this week…</div></div>`;
}

function explainRangeHtml(d) {
  const top = Math.max(d.ceiling * 1.1, d.expected * 1.5, 5);
  const at = (v) => Math.max(0, Math.min(100, (v / top) * 100));
  return `<div class="wp-range" role="img" aria-label="Floor ${FMT.d1(d.floor)}, typical ${FMT.d1(d.typical)}, expected ${FMT.d1(d.expected)}, ceiling ${FMT.d1(d.ceiling)} points">
    <i style="left:${at(d.floor)}%;width:${Math.max(at(d.ceiling) - at(d.floor), 2)}%"></i>
    <u class="typ" style="left:${at(d.typical)}%"></u><b class="exp" style="left:${at(d.expected)}%"></b>
    <span class="wp-end lo" style="left:${at(d.floor)}%">${FMT.d1(d.floor)}</span>
    <span class="wp-end hi" style="left:${at(d.ceiling)}%">${FMT.d1(d.ceiling)}</span>
  </div>`;
}

function explainHtml(d) {
  const head = `<div class="wp-head"><span class="wp-title">This week</span><span class="wp-meta">${d.week ? `WK ${esc(d.week)}` : ""}${d.opponent ? ` · ${d.position === "DEF" ? "" : "vs "}${esc(d.opponent)}` : ""}</span></div>`;
  if (d.out) {
    const why = d.out_reason === "bye" ? "is on a bye this week" : `is ${esc(d.injury_status || "out")} and will not play`;
    return `<div class="wp-card">${head}<div class="wp-out">${esc(d.name)} ${why}. He projects to 0 points.</div></div>`;
  }
  const mark = (dir) => (dir === "up" ? "▲" : dir === "down" ? "▼" : "•");
  const drivers = d.drivers.map((x) => `<li class="wp-d ${x.direction}">
      <span class="wp-mark" aria-hidden="true">${mark(x.direction)}</span>
      <div><div class="wp-dl"><b>${esc(x.label)}</b>${x.effect_pct != null && Math.abs(x.effect_pct) >= 1 ? `<span class="wp-eff">${x.effect_pct > 0 ? "+" : ""}${esc(x.effect_pct)}%</span>` : ""}</div>
      <div class="wp-dt">${esc(x.text)}</div>${x.detail ? `<div class="wp-dd">${esc(x.detail)}</div>` : ""}</div></li>`).join("");
  const b = d.backtest;
  return `<div class="wp-card">${head}
    <div class="wp-top">
      <div class="wp-big"><span class="wp-num">${FMT.d1(d.expected)}</span><span class="wp-unit">expected points</span></div>
      <div class="wp-stats"><div><b>${FMT.d1(d.typical)}</b><small>typical week</small></div><div><b>${d.p_10plus}%</b><small>10+ pts</small></div><div><b>${d.p_20plus}%</b><small>20+ pts</small></div></div>
    </div>
    ${explainRangeHtml(d)}
    <div class="wp-legend"><span><i class="k-band"></i>Floor to ceiling (9 in 10 weeks)</span><span><i class="k-typ"></i>Typical</span><span><i class="k-exp"></i>Expected</span></div>
    <div class="wp-why">What moved it</div>
    <ul class="wp-drivers">${drivers}</ul>
    <div class="wp-trust">Weekly scoring is noisy: across ${b.games.toLocaleString()} real games (${esc(b.seasons)}), this method missed by about ${Math.round(b.mae)} points a week on average. The range above is the honest picture; the big number is its average. Built from real NFL data and your league's scoring, nothing simulated or guessed.</div>
  </div>`;
}

async function loadExplain(p, root) {
  const slot = root.querySelector(".wp-slot");
  if (!slot) return;
  try {
    const d = await api(`/api/player/${encodeURIComponent(p.player_id)}/explain?${scoringQS().replace(/^&/, "")}`);
    if (document.body.contains(slot)) slot.outerHTML = explainHtml(d);
  } catch (e) {
    if (document.body.contains(slot)) slot.innerHTML = `<div class="muted small">Couldn't work out this week right now.</div>`;
  }
}

function projSlotHtml() {
  return `<div class="proj-slot"><div class="loading small">Building his next games…</div></div>`;
}

function pjKickoff(g) {
  const k = g.kickoff || {};
  if (!k.day) return "";
  const d = new Date(`${k.day}T12:00:00Z`);
  const day = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
  let time = "";
  if (k.time) {
    const [h, m] = k.time.split(":").map(Number);
    time = ` · ${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"} ET`;
  }
  return day + time;
}

function pjTierLine(g, pos) {
  if (!g.defense_rank) return "no defense data yet";
  const n = g.defense_count || 32, r = g.defense_rank;
  if (g.tier === "soft") return `${ordinal(r)}-softest defense vs ${pos}s`;
  if (g.tier === "tough") return `${ordinal(n - r + 1)}-toughest defense vs ${pos}s`;
  return `mid-pack defense vs ${pos}s`;
}

function pjMult(v) {
  const cls = v > 1.004 ? "up" : v < 0.996 ? "dn" : "flat";
  return `<span class="pj-x ${cls}">&times;${v.toFixed(2)}</span>`;
}

function pjRange(g, top, baseline) {
  const pct = (v) => Math.max(0, Math.min(100, (v / top) * 100));
  return `<div class="pj-range"><i style="left:${pct(g.floor)}%;width:${Math.max(pct(g.ceiling) - pct(g.floor), 2)}%"></i>
    <u style="left:${pct(baseline)}%" title="His usual baseline"></u><b style="left:${pct(g.median)}%"></b></div>
    <div class="pj-nums"><span>Floor <b>${FMT.d1(g.floor)}</b></span><span>Median <b>${FMT.d1(g.median)}</b></span><span>Ceiling <b>${FMT.d1(g.ceiling)}</b></span></div>`;
}

function pjSimilar(g, pos) {
  if (!g.tier) return "";
  const word = PJ_TIER[g.tier].toLowerCase();
  if (g.similar) {
    const n = g.similar.games;
    const cur = g.similar.current ? g.similar.current.games : 0;
    return `Against ${word} defenses he has averaged <b>${FMT.d1(g.similar.avg)}</b> in ${n} game${n === 1 ? "" : "s"} (${cur} this season).`;
  }
  return `He hasn't faced a ${word} defense in the seasons on file.`;
}

function pjWaterfall(g) {
  const st = g.steps;
  const node = (label, v, cls = "") => `<div class="pj-wf-n ${cls}"><span>${label}</span><b>${FMT.d1(v)}</b></div>`;
  const arrow = (label, m) => `<div class="pj-wf-a"><span>${label}</span>${pjMult(m)}</div>`;
  const mates = st.teammates_out > 0
    ? `<div class="pj-wf-a"><span>Teammates out</span><b>+${FMT.d1(st.teammates_out)}</b></div>${node("", st.baseline + st.teammates_out, "mid")}` : "";
  return `<div class="pj-wf">${node("Baseline", st.baseline)}${mates}${arrow("Game", g.m_vegas)}${node("", st.after_environment, "mid")}${arrow("Defense", g.m_defense)}${node("", st.after_defense, "mid")}${arrow("History", g.m_h2h)}${node("Expected", st.final, "end")}</div>`;
}

function pjContingency(g) {
  const c = g.contingency;
  if (!c || (!c.self && !(c.teammates_out || []).length)) return "";
  const pct = (v) => Math.round(v * 100);
  const rows = [];
  if (c.self) {
    rows.push(`<div class="pj-ct-row"><span>If he plays <em>${pct(c.self.p_play)}%</em></span><b>${FMT.d1(c.self.proj_if_plays)}</b><small>${esc(c.self.basis)}</small></div>`);
    rows.push(`<div class="pj-ct-row"><span>If he sits <em>${100 - pct(c.self.p_play)}%</em></span><b>0.0</b><small>his work goes to teammates</small></div>`);
  }
  (c.teammates_out || []).forEach((t) => {
    const more = [t.targets > 0.1 ? `${t.targets.toFixed(1)} more targets` : "", t.carries > 0.1 ? `${t.carries.toFixed(1)} more carries` : ""].filter(Boolean).join(" and ");
    rows.push(`<div class="pj-ct-row"><span>If ${esc(t.name)} sits <em>${esc(t.status)}, ${pct(t.p_out)}% out</em></span><b>${FMT.d1(t.proj_if_out)}</b><small>vs ${FMT.d1(t.proj_if_plays)} if he plays: about ${esc(more)} from the volume teammates have absorbed in past absences</small></div>`);
  });
  return `<div class="pj-ct"><div class="pj-tk">Two ways this game goes</div>${rows.join("")}<div class="muted small">The expected number above already weights each outcome by its chance.</div></div>`;
}

function pjUsageTile(d, pos) {
  const u = d.usage;
  if (!u) return `<div class="pj-tile"><div class="pj-tk">Role lately</div><div class="muted small">Usage data isn't available yet.</div></div>`;
  const rows = [["Snap share", u.snap_pct, "%"], ["Target share", u.target_share, "%"], ["Red-zone + targets / g", u.hvt_pg, ""], ["Expected pts / g", u.xfp_pg, ""]]
    .filter(([, v]) => v && v.recent != null);
  const items = rows.map(([label, v, unit]) => {
    const diff = v.season ? (v.recent - v.season) / v.season : 0;
    const trend = Math.abs(diff) < 0.05 ? "" : diff > 0 ? `<em class="up">&#9650; up</em>` : `<em class="dn">&#9660; down</em>`;
    return `<div class="pj-use"><span>${label}</span><b>${FMT.d1(v.recent)}${unit}</b><small>season ${FMT.d1(v.season)}${unit}</small>${trend}</div>`;
  }).join("");
  return `<div class="pj-tile"><div class="pj-tk">Role · last ${esc(u.games)} games</div>${items || '<div class="muted small">No usage numbers yet.</div>'}</div>`;
}

function pjEnvTile(g) {
  if (!g.has_lines) {
    return `<div class="pj-tile"><div class="pj-tk">Game environment</div><div class="muted small">No betting line is posted for this game yet, so the game environment is neutral (&times;1.00).</div></div>`;
  }
  const spread = g.margin == null ? "—" : g.margin === 0 ? "PK" : `${g.margin > 0 ? "-" : "+"}${Math.abs(g.margin)}`;
  const notes = g.notes || [];
  const indoors = notes.some((n) => /indoors/i.test(n)) || g.roof === "dome" || g.roof === "closed";
  const wx = g.weather ? `<div class="pj-line">${esc(g.weather.label || "Weather")}${g.weather.temp != null ? ` · ${Math.round(g.weather.temp)}°F` : ""}${g.weather.wind != null ? ` · wind ${Math.round(g.weather.wind)} mph` : ""}</div>` : "";
  return `<div class="pj-tile"><div class="pj-tk">Game environment</div>
    <div class="pj-trio"><div><b>${FMT.d1(g.implied_total)}</b><span>team total</span></div><div><b>${esc(spread)}</b><span>${g.margin > 0 ? "favored" : g.margin < 0 ? "underdog" : "spread"}</span></div><div><b>${FMT.d1(g.game_total)}</b><span>game total</span></div></div>
    ${notes.filter((n) => !/^indoors$/i.test(n)).map((n) => `<div class="pj-line">${esc(n)}</div>`).join("")}${wx}${indoors && !g.weather ? `<div class="pj-line muted">Indoors, no weather impact.</div>` : ""}</div>`;
}

function pjMatchupTile(g, pos) {
  const good = (g.flags_good || []).map((t) => `<li class="up">${esc(t)}</li>`).join("");
  const bad = (g.flags_bad || []).map((t) => `<li class="dn">${esc(t)}</li>`).join("");
  return `<div class="pj-tile"><div class="pj-tk">Matchup · ${esc(g.opponent)} defense</div>
    <div class="pj-line"><b class="pj-tag ${g.tier || "neutral"}">${PJ_TIER[g.tier] || "Unknown"}</b> ${esc(pjTierLine(g, pos))} · defense &times;${g.m_defense.toFixed(2)}</div>
    ${good || bad ? `<ul class="pj-flags">${good}${bad}</ul>` : `<div class="muted small">No standout strength or weakness against ${esc(pos)}s.</div>`}</div>`;
}

function pjPastTile(d, g) {
  const by = d.past_by_tier || {}, total = Object.values(by).reduce((a, v) => a + v.games, 0);
  const earlierN = (d.earlier_games || []).length;
  const bars = ["soft", "neutral", "tough"].map((t) => {
    const x = by[t];
    const max = Math.max(1, ...Object.values(by).map((v) => v.avg));
    return `<div class="pj-pt ${t}${g.tier === t ? " now" : ""}"><span>${PJ_TIER[t]}</span><div class="pj-pt-bar"><i style="width:${x ? Math.max(4, (x.avg / max) * 100) : 0}%"></i></div><b>${x ? FMT.d1(x.avg) : "—"}</b><small>${x ? `${x.games} game${x.games === 1 ? "" : "s"}` : "no games"}</small></div>`;
  }).join("");
  const chip = (x, lbl) => `<span class="pj-gc ${x.tier || ""}" title="${esc(lbl)} vs ${esc(x.opponent)}">${esc(lbl)} ${esc(x.opponent)} <b>${FMT.d1(x.points)}</b></span>`;
  const chips = (d.past_games || []).map((x) => chip(x, `W${x.week}`)).join("");
  const older = (d.earlier_games || []).slice().reverse().map((x) => chip(x, `'${String(x.season).slice(2)} W${x.week}`)).join("");
  const prior = g.prior_meeting ? `<div class="pj-line">He already played ${esc(g.opponent)} this season: <b>${FMT.d1(g.prior_meeting.points)}</b> in Week ${esc(g.prior_meeting.week)}.</div>` : "";
  return `<div class="pj-tile wide"><div class="pj-tk">Past matchups · points by defense difficulty</div>
    <div class="pj-pts">${bars}</div>
    <div class="pj-line">${pjSimilar(g, d.position)}${total < 8 ? ` <span class="muted">Small sample: ${total} game${total === 1 ? "" : "s"}.</span>` : ` <span class="muted">${total} games, ${earlierN} from earlier seasons.</span>`}</div>
    ${prior}<div class="pj-gcs">${chips}</div>
    ${older ? `<details class="pj-more"><summary>Earlier seasons (${earlierN} games)</summary><div class="pj-gcs">${older}</div></details>` : ""}</div>`;
}

function pjHistoryTile(d, g) {
  const v = g.vs_opponent, m = g.m_h2h == null ? 1 : g.m_h2h, opp = esc(g.opponent);
  if (!v) {
    return `<div class="pj-tile"><div class="pj-tk">History vs ${opp}</div><div class="pj-line">${pjMult(1)} no earlier games against them</div><div class="muted small">${esc(d.h2h_note || "")}</div></div>`;
  }
  const verdict = v.games < 2 ? "one meeting is too little to adjust"
    : m > 1.004 ? "he has beaten his usual numbers against them" : m < 0.996 ? "he has fallen short of his usual numbers against them" : "about his usual numbers";
  return `<div class="pj-tile"><div class="pj-tk">History vs ${opp}</div>
    <div class="pj-line">${pjMult(m)} ${verdict}</div>
    <div class="pj-line"><b>${esc(v.games)}</b> game${v.games === 1 ? "" : "s"}: avg <b>${FMT.d1(v.avg)}</b> (best ${FMT.d1(v.best)}, worst ${FMT.d1(v.worst)}). Last: <b>${FMT.d1(v.last.points)}</b>, ${esc(v.last.season)} Week ${esc(v.last.week)}.</div>
    <div class="muted small">${esc(d.h2h_note || "")}</div></div>`;
}

function pjHistoryNote(d) {
  const h = d.history;
  if (!h) return "";
  if (!h.seasons || !h.seasons.length) return `<div class="pj-hnote">No earlier seasons on file, so this projection comes from this season and the position average.</div>`;
  const pct = h.weight != null ? Math.round(h.weight * 100) : null;
  return `<div class="pj-hnote">${pct != null ? `About <b>${pct}%</b> of this baseline comes from` : "Built with"} his last ${esc(h.seasons.length)} season${h.seasons.length === 1 ? "" : "s"} (${FMT.d1(h.career_ppg)} PPG over ${esc(h.career_games)} games); the rest is this season. Newest seasons count most.</div>`;
}

function pjHeroHtml(d, p, top) {
  const g = d.games[0];
  const home = g.home === false ? "AWAY" : "HOME";
  const when = [pjKickoff(g), g.roof === "dome" || g.roof === "closed" ? "Indoors" : ""].filter(Boolean).join(" · ");
  return `<div class="pj-hero">
    <div class="pj-hero-top">
      <div><div class="pj-k">Next game · Week ${esc(g.week)}</div>
        <div class="pj-opp">${g.home === false ? "@" : "vs"} ${esc(g.opponent)}<span class="pj-loc">${home}</span></div>
        <div class="pj-when">${esc(when)}</div></div>
      <div class="pj-tier ${g.tier || "neutral"}"><b>${PJ_TIER[g.tier] || "Unknown"} matchup</b><span>${esc(pjTierLine(g, p.position))}</span></div>
    </div>
    <div class="pj-med"><span class="pj-medk">Median outcome</span><b>${FMT.d1(g.median)}</b><span class="pj-medk">pts</span></div>
    ${pjRange(g, top, d.baseline)}
    <div class="pj-legend"><span><i class="g"></i>10th to 90th percentile</span><span><i class="b"></i>median</span><span><i class="u"></i>usual baseline ${FMT.d1(d.baseline)}</span></div>
    ${pjHistoryNote(d)}
    ${pjWaterfall(g)}
  </div>
  <div class="pj-grid">${pjUsageTile(d, p.position)}${pjEnvTile(g)}${pjMatchupTile(g, p.position)}${pjHistoryTile(d, g)}${pjPastTile(d, g)}</div>`;
}

function pjTimelineHtml(d) {
  const cells = d.games.map((g, i) => `<div class="pj-tl-c ${g.tier || "neutral"}${i === 0 ? " now" : ""}" title="Week ${esc(g.week)} ${g.home === false ? "@" : "vs"} ${esc(g.opponent)}: ${esc(PJ_TIER[g.tier] || "Unknown")} matchup, median ${FMT.d1(g.median)}">
    <span class="w">W${esc(g.week)}</span><span class="o">${g.home === false ? "@" : ""}${esc(g.opponent)}</span><span class="m">${FMT.d1(g.median)}</span></div>`).join("");
  return `<div class="pj-tl-wrap"><div class="pj-tl">${cells}</div></div>
    <div class="pj-tl-key"><span class="soft">Soft</span><span class="neutral">Neutral</span><span class="tough">Tough</span><span class="muted">Number = median points</span></div>`;
}

function pjFollowCardHtml(g, d, p, top) {
  const env = g.has_lines
    ? `<span class="pj-chip">${g.margin > 0 ? "Favored by " + g.margin : g.margin < 0 ? "Underdog by " + Math.abs(g.margin) : "Pick'em"}</span><span class="pj-chip">Team total ${FMT.d1(g.implied_total)}</span>`
    : `<span class="pj-chip dim">No betting line yet</span>`;
  const flag = (g.flags_bad && g.flags_bad[0]) ? `<div class="pj-line dn">${esc(g.flags_bad[0])}</div>` : (g.flags_good && g.flags_good[0]) ? `<div class="pj-line up">${esc(g.flags_good[0])}</div>` : "";
  return `<div class="pj-card">
    <div class="pj-card-h"><span class="pj-wk">Wk ${esc(g.week)}</span><span class="pj-copp">${g.home === false ? "@" : "vs"} ${esc(g.opponent)}</span><b class="pj-tag ${g.tier || "neutral"}">${PJ_TIER[g.tier] || "Unknown"}</b><span class="pj-cmed">${FMT.d1(g.median)}<small>median</small></span></div>
    ${pjRange(g, top, d.baseline)}
    <div class="pj-chips">${env}<span class="pj-chip">${esc(pjTierLine(g, p.position))}</span></div>
    <div class="pj-line">${pjSimilar(g, p.position)}</div>${flag}
    <div class="pj-mults">Game ${pjMult(g.m_vegas)} Defense ${pjMult(g.m_defense)} History ${pjMult(g.m_h2h)}</div></div>`;
}

function projPageHtml(d, p) {
  if (!d.games || !d.games.length) {
    return `<div class="ros-empty">${p.bye_week != null ? "No games left on his schedule." : "No upcoming games found."}</div>`;
  }
  const top = Math.max(...d.games.map((g) => g.ceiling)) * 1.06 || 1;
  const first = d.games[0], follow = d.games.slice(1, 4);
  const ratio = d.baseline ? first.proj / d.baseline : 1;
  const advice = ratio >= 1.05 ? "Start with confidence: next week sets up better than his usual."
    : ratio <= 0.85 ? "Tough spot: start him on name value only if your options are worse."
    : "A normal week: nothing here says move him up or down.";
  const smash = d.games.find((g) => g.week === d.smash_week), trap = d.games.find((g) => g.week === d.trap_week);
  const spot = (g) => `Wk ${esc(g.week)} ${g.home === false ? "@" : "vs"} ${esc(g.opponent)}`;
  const take = d.games.length > 1 && smash && trap && smash.week !== trap.week
    ? `<div class="pj-take"><div><span class="k pos">Smash spot</span> ${spot(smash)} · ${FMT.d1(smash.proj)} expected, ${FMT.d1(smash.ceiling)} ceiling</div>
       <div><span class="k neg">Trap spot</span> ${spot(trap)} · ${FMT.d1(trap.proj)} expected, ${FMT.d1(trap.floor)} floor</div></div>` : "";
  const baseNote = d.baseline_xfp != null
    ? `Baseline ${FMT.d1(d.baseline)} pts/game: a model fitted on past seasons that weighs his season average, last 4 games, opportunity (targets and carries) and last year's average, so a fluky touchdown game can't set the number.`
    : `Baseline ${FMT.d1(d.baseline)} pts/game: a model fitted on past seasons that weighs his season average, last 4 games and last year's average. ${p.position === "QB" ? "Passers have no expected-points volume data here." : "He has no expected-points history yet."}`;
  return `<div class="pj-lead"><div><div class="pj-k">Next ${Math.min(4, d.games.length)} game${d.games.length === 1 ? "" : "s"}</div><div class="pj-big">${FMT.d1(d.games.slice(0, 4).reduce((a, g) => a + g.proj, 0))}<small>expected pts</small></div></div><div class="pj-adv">${advice}</div></div>
    <div class="pj-base">${baseNote}</div>
    ${pjContingency(first)}
    ${pjHeroHtml(d, p, top)}
    ${d.games.length > 1 ? `<div class="pcd-sub">The weeks after: matchup difficulty</div>${pjTimelineHtml(d)}
      <div class="pj-follow">${follow.map((g) => pjFollowCardHtml(g, d, p, top)).join("")}</div>${take}` : ""}
    <details class="pj-all"><summary>All ${d.games.length} remaining games</summary>${rosHtml(d)}</details>
    <div class="pj-foot">Built as role baseline &times; betting line (capped &plusmn;10%) &times; opponent defense (capped &plusmn;20%). The weights are judgment calls, not fitted to data. Past matchups are one season, so treat them as context, not a forecast.</div>`;
}

async function loadProjPage(p, root) {
  const slot = root.querySelector(".proj-slot");
  if (!slot) return;
  try {
    const d = await api(`/api/player/${encodeURIComponent(p.player_id)}/ros?${scoringQS().replace(/^&/, "")}`);
    if (!document.body.contains(slot)) return;
    slot.outerHTML = projPageHtml(d, p);
  } catch (e) {
    if (document.body.contains(slot)) slot.innerHTML = `<div class="muted small">Couldn't build his next games right now.</div>`;
  }
}

let lastCardTab = "ov"; // stays on the same tab when you open the next player

// Game-by-game list for the Weekly tab, newest first, from the same rows
// the bar chart uses.
function gameLogHtml(p) {
  const n = (v) => (v == null ? 0 : Math.round(v));
  const line = (w) => {
    if (p.position === "QB") return `${n(w.completions)}/${n(w.attempts)}, ${n(w.passing_yards)} yds, ${n(w.passing_tds)} TD`;
    if (p.position === "RB") return `${n(w.carries)} car, ${n(w.rushing_yards)} yds, ${n(w.rushing_tds)} TD · ${n(w.receptions)} rec, ${n(w.receiving_yards)} yds`;
    return `${n(w.receptions)}/${n(w.targets)} rec, ${n(w.receiving_yards)} yds, ${n(w.receiving_tds)} TD`;
  };
  const rows = weeklyRows(p).filter((w) => w.status === "played" || w.status === "dnp" || w.status === "bye" || (!w.status && w.fpts != null)).slice().reverse();
  if (!rows.length) return "";
  const items = rows.map((w) => {
    const opp = w.opponent || w.opponent_team;
    if (w.status === "bye") return `<div class="gl-row off"><span class="gl-wk">W${esc(w.week)}</span><span class="gl-opp">Bye week</span><span class="gl-line"></span><span class="gl-pts">&mdash;</span></div>`;
    if (w.status === "dnp") return `<div class="gl-row off"><span class="gl-wk">W${esc(w.week)}</span><span class="gl-opp">${w.home === false ? "@" : "vs"} ${esc(opp)}</span><span class="gl-line">Did not play</span><span class="gl-pts">&mdash;</span></div>`;
    return `<div class="gl-row"><span class="gl-wk">W${esc(w.week)}</span><span class="gl-opp">${w.home === false ? "@" : "vs"} ${esc(opp)}</span><span class="gl-line">${line(w)}</span><span class="gl-pts">${FMT.d1(w.fpts)}</span></div>`;
  }).join("");
  return `<div class="pcd-sub">Game log</div><div class="gl-list">${items}</div>`;
}

// The signature delta: average points per game against his pre-game
// projection, big, next to the streak chip.
function deltaCalloutHtml(p) {
  const rows = (p.weekly_status || []).filter((w) => w.status === "played" && w.fpts != null && w.proj && !w.proj.out && w.proj.fpts != null);
  if (rows.length < 2) return "";
  const per = rows.reduce((a, w) => a + (w.fpts - w.proj.fpts), 0) / rows.length;
  return `<div class="pcd-delta ${per >= 0 ? "up" : "dn"}" title="Average points per game vs. the pre-game projection, rescored for your league"><b>${per >= 0 ? "+" : ""}${per.toFixed(1)}</b><span>PPG vs projected</span></div>`;
}

function playerCardHtml(p) {
  const next = p.next_opponent ? `<span class="pcd-chip">Next: ${p.next_is_away ? "@" : "vs"} ${esc(p.next_opponent)} (Wk ${esc(p.next_week)})</span>` : "";
  const bye = p.bye_week != null ? `<span class="pcd-chip bye">BYE week ${esc(p.bye_week)}</span>` : "";
  const ngs = scoutingSlidersHtml(p);
  return `
    <div class="pcd-hd"><button class="modal-close" aria-label="Close">✕</button></div>
    <div class="pcd-id">
      <div class="pcd-av"><img ${headshotAttrs(p)} alt=""></div>
      <div class="pcd-who">
        <h2>${esc(p.player_display_name)}${statusFlagsHtml(p)}</h2>
        <div class="pcd-chips"><span class="pcd-chip">${esc(p.position)}</span><span class="pcd-chip team">${esc(p.recent_team)}</span>${next}${bye}${beatProjChipHtml(p)}</div>
      </div>
      ${deltaCalloutHtml(p)}
    </div>
    <div class="pcd-acts">
      <button type="button" class="pcd-btn pri" data-act="compare">${cardIcon("compare")}Compare</button>
      <button type="button" class="pcd-btn" data-act="startsit">${cardIcon("startsit")}Start / Sit</button>
      <button type="button" class="pcd-btn" data-act="trade" hidden>${cardIcon("trade")}Shop in trades</button>
      <div class="pcd-scoring">Scoring <span>${esc(SCORING_LABELS[state.scoring] || "PPR")}</span></div>
    </div>
    <nav class="pcd-nav" role="tablist" aria-label="Player sections">${CARD_SECTIONS.map(([k, l]) => `<button type="button" role="tab" id="pcd-tab-${k}" data-go="${k}" aria-controls="pcd-pane-${k}" aria-selected="false" tabindex="-1">${l}</button>`).join("")}</nav>
    <div class="pcd-body">
      <section data-sec="ov" id="pcd-pane-ov" role="tabpanel" aria-labelledby="pcd-tab-ov" hidden>
        ${injuryReportHtml(p)}
        ${cardKeyTilesHtml(p)}
        <div class="pcd-lbl pcd-wkhd"><span>Weekly Breakdown</span>${weeklyStatSelectHtml(p)}</div>
        <div class="weeklog-wrap">${weeklyRows(p).length ? weeklyChartHtml(weeklyRows(p), "fpts") : '<span class="muted">No games logged yet.</span>'}</div>
        ${gameLogHtml(p)}
        ${fantasyRangeHtml(p)}
        ${careerHtml(p)}
        ${scoutGlanceHtml(p)}
      </section>
      <section data-sec="pj" id="pcd-pane-pj" role="tabpanel" aria-labelledby="pcd-tab-pj" hidden>${explainSlotHtml()}${projSlotHtml()}<div class="pcd-sub">What the experts say for next game</div>${projectionCompareSlotHtml()}</section>
      <section data-sec="st" id="pcd-pane-st" role="tabpanel" aria-labelledby="pcd-tab-st" hidden>
        <div class="pcd-lbl"><span>Season Stats</span></div>
        ${totalsHtml(p, true)}
        ${detailSectionsHtml(p, "pcd-sub")}
      </section>
      <section data-sec="sc" id="pcd-pane-sc" role="tabpanel" aria-labelledby="pcd-tab-sc" hidden>${ngs || '<div class="pcd-lbl"><span>Scouting Report</span></div><div class="muted small">No Next Gen Stats for this player yet.</div>'}</section>
      <section data-sec="nw" id="pcd-pane-nw" role="tabpanel" aria-labelledby="pcd-tab-nw" hidden>
        <div class="pcd-lbl"><span>Latest News</span></div>
        <div id="player-news-slot" class="player-news-slot"><div class="loading small">Checking for news…</div></div>
      </section>
    </div>`;
}

// Everything the card does after it is on screen: the action bar, the
// section bar (click to jump, scroll to highlight), and the shared stat
// picker + projection loader.
function wirePlayerCard(root, p) {
  const card = root.querySelector(".modal");
  const pid = p.player_id;

  card.querySelector('[data-act="compare"]').addEventListener("click", () => {
    if (!state.compareSelected.has(pid)) {
      if (state.compareSelected.size >= CMP_MAX) { showToast(`Compare holds up to ${CMP_MAX} players. Remove one on the Big Board first.`); return; }
      toggleCompare(p);
    }
    if (state.compareSelected.size >= 2) { openCompareModal(); return; }
    closeModal();
    switchTab("board");
    showToast(`${p.player_display_name} added. Pick one more player to compare.`);
  });

  card.querySelector('[data-act="startsit"]').addEventListener("click", () => {
    if (!state.user || !activeTeam()) { showToast("Connect your team in Settings to use Start / Sit."); return; }
    if (!state.startsit.some((x) => x.player_id === pid)) {
      if (state.startsit.length >= 4) { showToast("Start / Sit holds up to 4 players. Remove one first."); return; }
      state.startsit.push({ player_id: pid, player_display_name: p.player_display_name, position: p.position,
        recent_team: p.recent_team, headshot_url: p.headshot_url, injury_status: p.injury_status, opp: "" });
    }
    closeModal();
    switchTab("startsit");
    renderStartSitChips();
  });

  // Trade shopping works from the user's own roster, so the button only
  // appears for a player they actually have.
  const tradeBtn = card.querySelector('[data-act="trade"]');
  if (state.user && activeTeam()) {
    ensureMyRoster().then((roster) => {
      if (roster.some((x) => x.player_id === pid)) tradeBtn.hidden = false;
    }).catch(() => {});
  }
  tradeBtn.addEventListener("click", () => {
    state.shopSelected = new Set([pid]);
    closeModal();
    switchTab("trade");
    showToast(`${p.player_display_name} selected. Hit "Find trades for selected".`);
  });

  // Real tabs: one pane at a time, header stays put, the pane scrolls.
  const nav = card.querySelector(".pcd-nav");
  const body = card.querySelector(".pcd-body");
  const btns = [...nav.querySelectorAll("[data-go]")];
  const panes = [...card.querySelectorAll("[data-sec]")];
  const showTab = (key, focus) => {
    if (!panes.some((s) => s.dataset.sec === key)) key = "ov";
    lastCardTab = key;
    btns.forEach((b) => {
      const on = b.dataset.go === key;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on) { nav.scrollTo({ left: Math.max(0, b.offsetLeft - 18), behavior: "smooth" }); if (focus) b.focus(); }
    });
    panes.forEach((s) => { s.hidden = s.dataset.sec !== key; });
    body.scrollTop = 0;
  };
  // Any element with data-go (the nav and the Overview teaser) switches tabs.
  card.addEventListener("click", (e) => {
    const go = e.target.closest("[data-go]");
    if (go && card.contains(go)) showTab(go.dataset.go);
  });
  nav.addEventListener("keydown", (e) => {
    const i = btns.findIndex((b) => b.classList.contains("on"));
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (step) { e.preventDefault(); showTab(btns[(i + step + btns.length) % btns.length].dataset.go, true); }
    else if (e.key === "Home") { e.preventDefault(); showTab(btns[0].dataset.go, true); }
    else if (e.key === "End") { e.preventDefault(); showTab(btns[btns.length - 1].dataset.go, true); }
  });
  showTab(lastCardTab);

  loadExplain(p, card);
  loadProjPage(p, card);
  wirePlayerStatsBody(root, p);
}

// Wires the stat-picker inside whatever container just received
// playerStatsBodyHtml() — `container` is the modal root for the full
// modal, or one card's own expand panel for the inline case.
function wirePlayerStatsBody(container, p) {
  const weeks = weeklyRows(p);
  container.querySelector(".weeklog-stat-select")?.addEventListener("change", (e) => {
    container.querySelector(".weeklog-wrap").innerHTML = weeklyChartHtml(weeks, e.target.value);
  });
  loadProjectionCompare(p.player_id, p.matchup_opponent, container);
  loadRosProjection(p.player_id, container);
}

// ------------------------------------------- projection breakdown ----
// Real published FantasyPros consensus next to our own PROJ (see
// engine/external_projections.py for sourcing/matching). Fetched
// separately from the rest of playerStatsBodyHtml — same reasoning as
// loadPlayerNews below: an external call never blocks opening the modal
// — and shared by both the full player modal and a Start/Sit card's
// inline expand, since both render through playerStatsBodyHtml.
//
// The reveal — bars growing in width, staggered, then the delta badge
// popping in on the same spring curve already used for the app's button
// press (CUSTOM_SPRING bounce 0.45, pulled via Figma's get_motion_context
// from the same design file as everything else's motion, not hand-tuned)
// — was designed and keyframed in that Figma file before being ported
// to CSS below (see .pc-fill/.pc-badge.pc-in in style.css).
// ------------------------------------------- rest of season ----
// Game-by-game projection from engine/ros_projection.py: role baseline
// (trailing xFP) x Vegas x defense. Fetched separately, like the compare.
function rosSlotHtml() {
  return `<div class="ros-slot"><div class="loading small">Projecting the rest of the season…</div></div>`;
}

function rosHtml(d) {
  if (!d.games.length) return `<div class="pc-card pc-empty"><div class="muted small">No games left to project.</div></div>`;
  const mult = (v) => (Math.abs(v - 1) < 0.005 ? `<span class="muted">1.00</span>` : `<span class="${v > 1 ? "ros-up" : "ros-dn"}">${v.toFixed(2)}</span>`);
  const rows = d.games.map((g) => {
    const tag = g.week === d.smash_week && d.n_games > 1 ? '<span class="ros-tag up">Smash</span>' : g.week === d.trap_week && d.n_games > 1 ? '<span class="ros-tag dn">Trap</span>' : "";
    const line = g.has_lines ? `${g.margin > 0 ? "-" : "+"}${Math.abs(g.margin)} / ${g.implied_total} ITT` : "no line yet";
    return `<tr title="${esc((g.notes || []).join(" · "))}">
      <td>Wk ${esc(g.week)}</td><td>${g.home === false ? "@" : "vs"} ${esc(g.opponent)} ${tag}</td>
      <td class="ros-line">${esc(line)}</td><td>${g.grade ? `<b class="scs-grade" style="--h:${scoutHue(g.grade === "A" ? 95 : g.grade === "B" ? 75 : g.grade === "C" ? 50 : g.grade === "D" ? 30 : 10)}">${g.grade}</b>` : "—"}</td>
      <td>${mult(g.m_vegas)}</td><td>${mult(g.m_defense)}</td>
      <td>${FMT.d1(g.floor)}</td><td><b>${FMT.d1(g.proj)}</b></td><td>${FMT.d1(g.ceiling)}</td></tr>`;
  }).join("");
  return `<div class="pc-card ros-card">
    <div class="section-label pc-header"><span>Rest of Season</span><span class="pc-wk">${esc(d.n_games)} GAMES · ${FMT.d1(d.total)} PTS</span></div>
    <div class="muted small">Role baseline ${FMT.d1(d.baseline)} per game${d.baseline_xfp != null ? ` (his last 4 games' touches are worth ${FMT.d1(d.baseline_xfp)} expected)` : ""}, then scaled by the game environment and the opponent. Floor and ceiling are the 10th and 90th percentile.</div>
    <div class="ros-scroll"><table class="ros-table"><thead><tr><th>Wk</th><th>Opp</th><th>Spread / ITT</th><th>Matchup</th><th>Vegas ×</th><th>Defense ×</th><th>Floor</th><th>Proj</th><th>Ceiling</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="muted small pc-source-note">Head-to-head history isn't used: it only counts if the same coordinator and coverage scheme are back, and no data here says so. Games a few weeks out often have no betting line yet, so they get no Vegas adjustment. The weights are judgment calls, not fitted to data.</div>
  </div>`;
}

async function loadRosProjection(playerId, container) {
  const slot = container.querySelector(".ros-slot");
  if (!slot || !playerId) return;
  try {
    const d = await api(`/api/player/${encodeURIComponent(playerId)}/ros?${scoringQS().replace(/^&/, "")}`);
    if (document.body.contains(slot)) slot.outerHTML = rosHtml(d);
  } catch (e) {
    if (document.body.contains(slot)) slot.outerHTML = `<div class="pc-card pc-empty"><div class="muted small">Couldn't project the rest of the season right now.</div></div>`;
  }
}

function projectionCompareSlotHtml() {
  return `<div class="pc-slot"><div class="loading small">Checking real consensus…</div></div>`;
}

function projectionCompareHtml(ourProj, consensus, week, blend) {
  const wkTag = week ? `<span class="pc-wk">WK ${esc(week)}</span>` : "";
  if (!consensus.configured) {
    return `<div class="pc-card pc-empty">
      <div class="section-label pc-header"><span>Projection Breakdown</span></div>
      <div class="muted small">Consensus comparison isn't connected yet.</div>
    </div>`;
  }
  if (ourProj == null || consensus.proj == null) {
    return `<div class="pc-card pc-empty">
      <div class="section-label pc-header"><span>Projection Breakdown</span>${wkTag}</div>
      <div class="muted small">No real ${esc(consensus.source)} number for this player${week ? " this week" : ""} yet.</div>
    </div>`;
  }

  const max = Math.max(ourProj, consensus.proj, 0.1);
  const ourPct = Math.max(2, Math.round((ourProj / max) * 100));
  const theirPct = Math.max(2, Math.round((consensus.proj / max) * 100));
  const delta = ourProj - consensus.proj;
  const ahead = delta >= 0;

  return `<div class="pc-card">
    <div class="section-label pc-header"><span>Projection Breakdown</span>${wkTag}</div>
    <div class="pc-row">
      <div class="pc-row-label"><span>Lineup Lab</span><span class="pc-val pc-val-ours">${FMT.d1(ourProj)}</span></div>
      <div class="pc-track"><span class="pc-fill pc-fill-ours" data-pct="${ourPct}"></span></div>
    </div>
    <div class="pc-row">
      <div class="pc-row-label"><span>${esc(consensus.source)}</span><span class="pc-val pc-val-theirs">${FMT.d1(consensus.proj)}</span></div>
      <div class="pc-track"><span class="pc-fill pc-fill-theirs" data-pct="${theirPct}"></span></div>
    </div>
    <div class="pc-badge ${ahead ? "pc-up" : "pc-down"}">${ahead ? "▲" : "▼"} ${Math.abs(delta).toFixed(1)} PTS ${ahead ? "AHEAD OF" : "BEHIND"} CONSENSUS</div>
    ${blend && blend.blended != null ? `<div class="pc-blend small" title="Judgment-call weights, not fitted to data: our model keeps more weight early in the week, the experts more as kickoff nears">Blended ${FMT.d1(blend.blended)} pts · ${Math.round(blend.alpha * 100)}% Lineup Lab / ${Math.round((1 - blend.alpha) * 100)}% experts</div>` : ""}
    <div class="muted small pc-source-note">${esc(consensus.detail)}</div>
  </div>`;
}

async function loadProjectionCompare(playerId, opp, container) {
  const slot = container.querySelector(".pc-slot");
  if (!slot || !playerId) return;
  try {
    const oppQS = opp ? `&opp=${opp}` : "";
    const data = await api(`/api/player/${playerId}/projection-compare?${(scoringQS() + oppQS).replace(/^&/, "")}`);
    if (!document.body.contains(slot)) return; // modal closed/replaced before this resolved
    slot.outerHTML = projectionCompareHtml(data.our_proj, data.consensus, data.consensus?.week, data.blend);
    // Trigger the entrance transitions one frame after insert (same
    // technique as the Trade Analyzer's need-bar-fill: render at the
    // 0-state first so the browser registers it, then flip to the real
    // state so the width/opacity/scale transitions actually animate
    // instead of snapping straight to their end value).
    requestAnimationFrame(() => {
      container.querySelectorAll(".pc-fill[data-pct]").forEach((el) => { el.style.width = el.dataset.pct + "%"; });
      container.querySelector(".pc-badge")?.classList.add("pc-in");
    });
  } catch (e) {
    if (document.body.contains(slot)) {
      slot.outerHTML = `<div class="pc-card pc-empty"><div class="muted small">Couldn't load the projection comparison right now.</div></div>`;
    }
  }
}

function playerNewsCardHtml(it) {
  const img = it.image
    ? `<img class="pn-thumb" src="${safeUrl(it.image)}" alt="" data-fb-remove="1">`
    : "";
  return `<a class="pn-card" href="${safeUrl(it.link)}" target="_blank" rel="noopener noreferrer">
    ${img}
    <div class="pn-body">
      <div class="pn-title">${esc(it.title)}</div>
      <div class="pn-meta">${esc(it.source)}${it.published ? " · " + esc(it.published) : ""}</div>
    </div>
  </a>`;
}

async function loadPlayerNews(playerId, root) {
  const slot = root.querySelector("#player-news-slot");
  if (!slot) return;  // modal was closed/replaced before this resolved
  try {
    const data = await api(`/api/player/${playerId}/news`);
    // root may have been re-rendered (modal closed, another player opened)
    // by the time this async call resolves — re-check before touching the DOM.
    const liveSlot = document.getElementById("player-news-slot");
    if (!liveSlot || !document.body.contains(liveSlot)) return;

    const summaryHtml = data.ai_summary
      ? `<div class="pn-ai-summary"><div class="pn-ai-label">AI SUMMARY</div><p>${esc(data.ai_summary)}</p></div>`
      : "";
    if (!data.items || !data.items.length) {
      liveSlot.innerHTML = summaryHtml || `<div class="muted small">No current news found for this player.</div>`;
      return;
    }
    liveSlot.innerHTML = summaryHtml + `<div class="pn-cards">${data.items.map(playerNewsCardHtml).join("")}</div>`;
  } catch (e) {
    const liveSlot = document.getElementById("player-news-slot");
    if (liveSlot) liveSlot.innerHTML = `<div class="muted small">Couldn't load news right now.</div>`;
  }
}

// ------------------------------------------------------- player picker ----
function initPicker(containerId, onAdd) {
  const container = $(containerId);
  container.innerHTML = `<input type="text" placeholder="Search players to add…" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"><div class="picker-results" style="display:none"></div>`;
  const input = container.querySelector("input");
  const results = container.querySelector(".picker-results");
  let debounce;

  input.addEventListener("input", () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) { results.style.display = "none"; return; }
    debounce = setTimeout(async () => {
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
      results.innerHTML = "";
      if (!data.results.length) {
        results.innerHTML = `<div class="picker-result muted">No players found</div>`;
      }
      data.results.forEach((p) => {
        const row = el("div", "picker-result");
        row.innerHTML = `<img ${headshotAttrs(p)} alt="">
          <span>${esc(p.player_display_name)} <span class="muted">${esc(p.position)} · ${esc(p.recent_team)}</span></span>`;
        row.addEventListener("click", () => {
          onAdd(p);
          input.value = "";
          results.style.display = "none";
        });
        results.appendChild(row);
      });
      results.style.display = "";
    }, 200);
  });

  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) results.style.display = "none";
  });
}

// ------------------------------------------------------------ start/sit ----
// The first player picked lands in the left slot, the second in the right
// one (a real vs-style layout, not just a row of small pills) — later
// picks (3rd/4th, still supported) simply continue filling slots left to
// right in the order they were clicked.
function renderStartSitChips() {
  const row = $("#startsit-chips");
  row.innerHTML = "";
  state.startsit.forEach((p, i) => {
    const slot = el("div", "ss-slot");
    slot.style.animationDelay = `${i * 70}ms`;
    slot.innerHTML = `<button class="ss-slot-x" aria-label="Remove ${esc(p.player_display_name)}">✕</button>
      <img ${headshotAttrs(p)} alt="">
      <div class="ss-slot-name">${esc(p.player_display_name)}${statusFlagsHtml(p)}</div>
      <div class="ss-slot-meta">${esc(p.position)} · ${esc(p.recent_team)}</div>
      <select class="opp-select"><option value="">vs…</option>${state.meta.teams.map((t) => `<option value="${esc(t)}" ${p.opp === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
    slot.querySelector(".opp-select").addEventListener("change", (e) => { p.opp = e.target.value; });
    slot.querySelector(".ss-slot-x").addEventListener("click", () => {
      state.startsit = state.startsit.filter((x) => x.player_id !== p.player_id);
      renderStartSitChips();
      $(`#startsit-roster-picker .shop-chip[data-pid="${p.player_id}"]`)?.classList.remove("selected");
    });
    row.appendChild(slot);
    if (i === 0 && state.startsit.length > 1) {
      const vs = el("div", "ss-slot-vs", "VS");
      row.insertBefore(vs, slot.nextSibling);
    }
  });
  $("#startsit-compare").disabled = state.startsit.length < 2;
}

// Real numbers turned into a sentence — no external AI call, just the same
// SCORE/FORM/matchup data the cards already show, read out as a rationale.
function formTrendPhrase(form) {
  if (form == null) return null;
  if (form >= 15) return "a sharp upward trend over its last several games";
  if (form >= 5) return "an upward trend over its last several games";
  if (form <= -15) return null; // cooling off sharply isn't a reason to START this player
  if (form <= -5) return null;  // trending down isn't a reason to start it either
  return null; // "steady" isn't a reason to prefer one player, so it isn't worth a sentence
}

// The "Start X over Y" sentence, comparing any two players — pulled out
// of what used to be one shared paragraph loop so each player's own card
// can carry its own slice of the analysis, instead of every explanation
// living in one block up top disconnected from the players it's about.
function startSitCompareSentence(top, p) {
  const diff = (top.PROJ - p.PROJ).toFixed(1);
  const bits = [];
  let scoreCaveat = "";
  if (top.SCORE != null && p.SCORE != null && Math.abs(top.SCORE - p.SCORE) >= 3) {
    if (top.SCORE > p.SCORE) {
      bits.push(`a higher PVS (${FMT.d1(top.SCORE)} vs ${FMT.d1(p.SCORE)})`);
    } else {
      // PROJ favors top despite a lower season-long SCORE — worth flagging as
      // an upset call, not silently claiming a "higher SCORE" that isn't true.
      scoreCaveat = ` That's despite a lower season-long PVS (${FMT.d1(top.SCORE)} vs ${FMT.d1(p.SCORE)}) — this week's projection is matchup/form-driven.`;
    }
  }
  const trend = formTrendPhrase(top.FORM);
  if (trend) bits.push(`${esc(trend)} (FORM ${top.FORM >= 0 ? "+" : ""}${FMT.d1(top.FORM)}%)`);
  if (top.matchup_tag && top.opponent) bits.push(`a ${esc(top.matchup_tag).toLowerCase()} matchup vs ${esc(top.opponent)}`);
  const why = bits.length ? ` Backed by ${bits.join(" and ")}.` : "";
  return `Start <strong>${esc(top.player_display_name)}</strong> over <strong>${esc(p.player_display_name)}</strong> — projected for ${FMT.d1(top.PROJ)} pts vs ${FMT.d1(p.PROJ)} (+${diff}).${why}${scoreCaveat}`;
}


function injuryFlagHtml(status, factorDetail) {
  if (!status) return "";
  const mild = status === "Questionable";
  // Real, disclosed reason PROJ moved (see engine/injury_impact.py) —
  // only present where the backend actually attached it (Big Board's
  // opponent view, the player modal; not yet threaded through My
  // Team/Trade/Start-Sit's own row-builders, a real, smaller scope gap
  // rather than a silently partial job). Never shown for a plain flag
  // with no real backing factor.
  const title = factorDetail
    ? ` title="Historically ${factorDetail.median_pct_change >= 0 ? "+" : ""}${Math.round(factorDetail.median_pct_change * 100)}% for ${esc(factorDetail.body_part)} + ${esc(status)} (real median, n=${factorDetail.real_sample_size} games) — already reflected in PROJ"`
    : "";
  return ` <span class="injury-flag${mild ? " questionable" : ""}"${title}>${esc(status.toUpperCase())}</span>`;
}

// Kept as the single call site every player-name render uses (Big
// Board/Waivers, player modal, Start/Sit, My Team, Trade picker) so any
// future status badge only needs wiring in once, here — see git history
// for the "gone dark" badge this used to also render, removed per request.
function statusFlagsHtml(p) {
  const factorDetail = (p.injury_factor != null && p.injury_factor !== 1 && p.injury_sample_n != null)
    ? { median_pct_change: p.injury_factor - 1, body_part: p.injury_body_part, real_sample_size: p.injury_sample_n }
    : null;
  return injuryFlagHtml(p.injury_status, factorDetail);
}

function statChipsHtml(p) {
  const chips = [];
  if (p.snap_pct != null) chips.push(`Snap ${Math.round(p.snap_pct * 100)}%`);
  if (p.redzone_touches != null) chips.push(`RZ touches ${p.redzone_touches}`);
  if (p.SCORE != null) chips.push(`PVS ${FMT.d1(p.SCORE)}`);
  return chips.map((c) => `<span class="ss-stat-chip">${esc(c)}</span>`).join("");
}

// Every card's floor/ceiling bar shares one scale across the whole
// comparison so the bars are actually comparable at a glance, not just
// individually accurate.
// Small conic-gradient confidence ring, real value from the backend's
// own _tier_confidence math (engine/tools.py) — animated in via
// animateSSRings() below, same double-rAF-then-settle technique the
// rest of this app already uses for width-based bars (see
// animateScoreBars/need-bar-fill), just driving a conic-gradient angle
// instead of a width.
function confidenceRingHtml(p, tierClass) {
  if (p.confidence == null) return "";
  const colorVar = tierClass === "tier-start" ? "--accent" : tierClass === "tier-sit" ? "--neg" : tierClass === "tier-borderline" ? "--avg" : "--info";
  return `<div class="ss-ring" data-ring data-value="${p.confidence}" data-color-var="${colorVar}">
    <div class="ss-ring-bg" style="background:conic-gradient(var(${colorVar}) 0deg, var(--border) 0deg)"></div>
    <div class="ss-ring-label"><span class="ss-ring-pct">${p.confidence}%</span><span class="ss-ring-tag">CONF</span></div>
  </div>`;
}

function animateSSRings() {
  const apply = () => {
    document.querySelectorAll(".ss-ring[data-ring]").forEach((el) => {
      const value = parseFloat(el.dataset.value);
      const colorVar = el.dataset.colorVar;
      const bg = el.querySelector(".ss-ring-bg");
      bg.style.background = `conic-gradient(var(${colorVar}) ${value * 3.6}deg, var(--border) 0deg)`;
    });
  };
  requestAnimationFrame(() => requestAnimationFrame(apply));
  setTimeout(apply, 60);
}

function rangeBarHtml(p, scaleMin, scaleMax) {
  const span = Math.max(scaleMax - scaleMin, 0.1);
  const floor = p.floor != null ? p.floor : p.PROJ;
  const ceiling = p.ceiling != null ? p.ceiling : p.PROJ;
  const left = ((floor - scaleMin) / span) * 100;
  const width = Math.max(((ceiling - floor) / span) * 100, 2);
  const markerLeft = Math.min(Math.max(((p.PROJ - scaleMin) / span) * 100, 0), 100);
  return `
    <div class="ss-range-track">
      <div class="ss-range-fill" style="left:${left}%;width:${width}%"></div>
      <div class="ss-range-marker" style="left:${markerLeft}%" title="Projected: ${FMT.d1(p.PROJ)}"></div>
    </div>
    <div class="ss-range-labels" title="25th and 75th percentile of his real game log; the dot is his projection"><span>Low week ${FMT.d1(floor)}</span><span>High week ${FMT.d1(ceiling)}</span></div>`;
}

// The hero card — one per compared player. The per-card "WHY" text this
// used to carry moved into one shared ssNarrativeHtml() card instead
// (see runStartSit): a real 2-bullet summary about the top pick, not N
// separate paragraphs repeating the same comparison from each angle.
// `recommended` (the actual single best pick, not just "tier === START"
// — a comparison can have more than one real START-tier player) gets
// the pulsing glow: a real, ongoing animation, not a one-shot pop, so
// it keeps reading as "this one" while you're looking at the group.
function reasonsHtml(p) {
  if (!p.reasons || !p.reasons.length) return "";
  return `<ul class="ss-reasons">${p.reasons.slice(0, 4).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`;
}

function startSitCardHtml(p, scaleMin, scaleMax, i, recommended, hideRing) {
  const tierClass = "tier-" + (p.tier || "borderline").toLowerCase();
  return `<div class="ss-card ss-hero ${tierClass}${recommended ? " recommended" : ""} ${posAccentClass(p.position)}" data-pid="${esc(p.player_id)}" style="animation-delay:${i * 60}ms">
    ${recommended ? `<div class="ss-rec-badge">Start Recommendation</div>` : ""}
    <div class="ss-card-top">
      <img ${headshotAttrs(p)} alt="">
      <div>
        <div class="ss-name">${esc(p.player_display_name)}${statusFlagsHtml(p)}</div>
        <div class="ss-meta">${esc(p.position)} · ${esc(p.recent_team)}${p.opponent ? " · vs " + esc(p.opponent) + " (" + esc(p.matchup_tag) + ")" : " · rest-of-season blend"}</div>
      </div>
      ${hideRing ? "" : confidenceRingHtml(p, tierClass)}
    </div>
    <div class="ss-proj-row">
      <div class="ss-proj-num">${FMT.d1(p.PROJ)}<span class="ss-proj-lbl">proj pts</span></div>
      <div class="ss-tier-badge ${tierClass}">${esc(p.tier || "—")}</div>
    </div>
    ${rangeBarHtml(p, scaleMin, scaleMax)}
    ${reasonsHtml(p)}
    <div class="ss-stat-chips">${statChipsHtml(p)}</div>
    <button class="ss-expand-toggle" type="button" aria-expanded="false">
      <span>Full player breakdown</span>
      <svg viewBox="0 0 12 8" width="12" height="8"><path d="M1 1.5 6 6.5 11 1.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <div class="ss-expand-panel"></div>
  </div>`;
}

// ---------------------------------------------- shared breakdown panel ----
// One tabbed panel comparing every player in the group side by side per
// real metric, instead of each player's own card repeating its own
// numbers in isolation. Works for 2-4 players (Start/Sit's real range) —
// each row is a small multi-bar chart, one segment per player on a
// shared scale, not a fixed two-sided "vs" layout that would break past
// 2 players.
// Same per-player identity colors as the decision layer above it (SS_COLORS),
// so player 2 is the same color in every Start/Sit chart. This used to be
// accent/neg — painting the second player red, i.e. "bad", for no reason.
const SS_TAB_COLORS = ["#22d3ee", "#a78bfa", "#f472b6", "#e4e4e7"];

function ssMultiBarRowHtml(label, sub, players, valueFn, displayFn, maxOverride) {
  const values = players.map(valueFn);
  const max = maxOverride || Math.max(...values.map((v) => Math.abs(v || 0)), 1);
  const rows = players.map((p, i) => {
    const v = values[i];
    const pct = Math.max(2, Math.min(100, (Math.abs(v || 0) / max) * 100));
    const color = SS_TAB_COLORS[i % SS_TAB_COLORS.length];
    return `<div class="ss-mb-row">
      <span class="ss-mb-name">${esc((p.player_display_name || "").split(" ").slice(-1)[0])}</span>
      <div class="ss-mb-track"><span class="ss-mb-fill" data-pct="${pct}" style="background:${color};box-shadow:0 0 8px -1px ${color};"></span></div>
      <span class="ss-mb-val tabular" style="color:${color}">${esc(displayFn(v, p))}</span>
    </div>`;
  }).join("");
  return `<div class="ss-metric-block">
    <div class="ss-metric-head"><span class="ss-metric-label">${esc(label)}</span>${sub ? `<span class="ss-metric-sub">${esc(sub)}</span>` : ""}</div>
    ${rows}
  </div>`;
}

function ssDivergeRowHtml(p, color, scaleMax) {
  scaleMax = scaleMax || 15;
  const value = p.FORM || 0;
  const clamped = Math.max(-scaleMax, Math.min(scaleMax, value));
  const pct = (Math.abs(clamped) / scaleMax) * 50;
  const positive = clamped >= 0;
  const left = positive ? 50 : 50 - pct;
  return `<div class="ss-mb-row">
    <span class="ss-mb-name">${esc((p.player_display_name || "").split(" ").slice(-1)[0])}</span>
    <div class="ss-diverge-track"><span class="ss-diverge-mid"></span>
      <span class="ss-diverge-fill" data-pct="${pct}" data-left="${left}" style="background:${positive ? "var(--accent)" : "var(--neg)"};box-shadow:0 0 8px -1px ${positive ? "var(--accent-glow)" : "var(--neg-glow)"};"></span>
    </div>
    <span class="ss-mb-val tabular" style="color:${positive ? "var(--accent)" : "var(--neg)"}">${value >= 0 ? "+" : ""}${FMT.d1(value)}%</span>
  </div>`;
}

function ssMatchupRowHtml(p) {
  // Real spectrum, not a fabricated radar: tough .. average .. soft, from
  // the real matchup_tag /api/startsit already computes per opponent
  // (engine/matchup.matchup_tag) — that endpoint only returns the
  // discrete tag, not Big Board's continuous matchup_factor, so the dot
  // position is discrete too (three real stops, not an invented
  // in-between value). No opponent set (the common rest-of-season case)
  // is shown as a real, honest neutral state, not guessed.
  const hasOpp = p.opponent && p.matchup_tag != null;
  const pos = !hasOpp ? 0 : p.matchup_tag === "soft" ? 1 : p.matchup_tag === "tough" ? -1 : 0;
  const pctFromLeft = 50 + pos * 50;
  const tag = hasOpp ? p.matchup_tag : "no matchup set";
  const color = !hasOpp ? "var(--muted)" : p.matchup_tag === "soft" ? "var(--accent)" : p.matchup_tag === "tough" ? "var(--neg)" : "var(--info)";
  return `<div class="ss-mb-row">
    <span class="ss-mb-name">${esc((p.player_display_name || "").split(" ").slice(-1)[0])}</span>
    <div class="ss-spectrum-track">
      <span class="ss-spectrum-mid"></span>
      <span class="ss-spectrum-dot" data-left="${pctFromLeft}" style="background:${color};box-shadow:0 0 8px -1px ${color};"></span>
    </div>
    <span class="ss-mb-val" style="color:${color}">${esc((tag || "").toUpperCase())}</span>
  </div>`;
}

function ssBreakdownPanelHtml(players) {
  const maxProj = Math.max(...players.map((p) => p.ceiling != null ? p.ceiling : p.PROJ), 1);
  const maxRz = Math.max(...players.map((p) => p.redzone_touches || 0), 1);
  const tabs = [
    { key: "overview", label: "Overview", icon: "⚡" },
    { key: "volume", label: "Volume & Usage", icon: "◇" },
    { key: "matchup", label: "Matchup", icon: "◎" },
    { key: "trends", label: "Trends & Availability", icon: "◷" },
  ];
  const tabBtns = tabs.map((t, i) => `<button type="button" class="ss-tab-btn${i === 0 ? " active" : ""}" data-ss-tab="${t.key}"><span>${t.icon}</span>${esc(t.label)}</button>`).join("");

  const overview =
    ssMultiBarRowHtml("Projected Points", "", players, (p) => p.PROJ, (v) => FMT.d1(v), maxProj) +
    ssMultiBarRowHtml("Low week", "25th percentile of his real game log", players, (p) => (p.floor != null ? p.floor : p.PROJ), (v) => FMT.d1(v), maxProj) +
    ssMultiBarRowHtml("High week", "75th percentile of his real game log", players, (p) => (p.ceiling != null ? p.ceiling : p.PROJ), (v) => FMT.d1(v), maxProj);

  const volume =
    ssMultiBarRowHtml("Snap Share", "", players, (p) => (p.snap_pct || 0) * 100, (v) => Math.round(v) + "%", 100) +
    ssMultiBarRowHtml("Red-Zone Touches", "", players, (p) => p.redzone_touches || 0, (v) => Math.round(v), maxRz) +
    ssMultiBarRowHtml("PVS", "value over replacement, 0–100", players, (p) => p.SCORE || 0, (v) => FMT.d1(v), 100);

  const matchup = `<div class="ss-metric-block">
    <div class="ss-metric-head"><span class="ss-metric-label">Matchup Difficulty</span><span class="ss-metric-sub">tough ← average → soft, real per-stat defense factor</span></div>
    ${players.map(ssMatchupRowHtml).join("")}
  </div>`;

  const trends = `<div class="ss-metric-block">
      <div class="ss-metric-head"><span class="ss-metric-label">Recent Form</span><span class="ss-metric-sub">recency-weighted vs. own season average</span></div>
      ${players.map((p) => ssDivergeRowHtml(p)).join("")}
    </div>
    <div class="ss-metric-block">
      <div class="ss-metric-head"><span class="ss-metric-label">Availability</span><span class="ss-metric-sub">weeks since his last logged game (weather is in the head-to-head table above)</span></div>
      ${players.map((p) => {
        const dark = p.weeks_since_played != null && p.weeks_since_played >= 3;
        return `<div class="ss-mb-row">
          <span class="ss-mb-name">${esc((p.player_display_name || "").split(" ").slice(-1)[0])}</span>
          <span class="ss-avail ${dark ? "dark" : "ok"}">${dark ? `Last game Wk ${esc(p.last_active_week)} (${esc(p.weeks_since_played)} wks ago)` : "Active"}</span>
        </div>`;
      }).join("")}
    </div>`;

  return `<div class="ss-breakdown">
    <div class="ss-breakdown-head"><span class="ss-breakdown-title">Side-by-side stats</span> <span class="muted small">each bar is one player, on a shared scale</span></div>
    <div class="ss-tabbar">${tabBtns}</div>
    <div class="ss-tab-body" data-ss-tab-body="overview">${overview}</div>
    <div class="ss-tab-body" data-ss-tab-body="volume" hidden>${volume}</div>
    <div class="ss-tab-body" data-ss-tab-body="matchup" hidden>${matchup}</div>
    <div class="ss-tab-body" data-ss-tab-body="trends" hidden>${trends}</div>
  </div>`;
}

function wireSSBreakdownTabs(container) {
  const btns = container.querySelectorAll(".ss-tab-btn");
  btns.forEach((btn) => btn.addEventListener("click", () => {
    btns.forEach((b) => b.classList.toggle("active", b === btn));
    container.querySelectorAll("[data-ss-tab-body]").forEach((body) => {
      body.hidden = body.dataset.ssTabBody !== btn.dataset.ssTab;
    });
    animateSSBars(container);
  }));
}

function animateSSBars(container) {
  const apply = () => {
    container.querySelectorAll(".ss-mb-fill[data-pct]").forEach((el) => {
      if (el.closest("[hidden]")) return;
      el.style.width = el.dataset.pct + "%";
    });
    container.querySelectorAll(".ss-diverge-fill[data-pct]").forEach((el) => {
      if (el.closest("[hidden]")) return;
      el.style.width = el.dataset.pct + "%";
      el.style.left = el.dataset.left + "%";
    });
    container.querySelectorAll(".ss-spectrum-dot[data-left]").forEach((el) => {
      if (el.closest("[hidden]")) return;
      el.style.left = el.dataset.left + "%";
    });
  };
  requestAnimationFrame(() => requestAnimationFrame(apply));
  setTimeout(apply, 60);
}

// ------------------------------------------------------- narrative card ----
// One real "AI Recommendation Summary" — a crisp couple of bullets about
// the actual top pick, built from the same real comparison sentence
// engine already computes (startSitCompareSentence), not a separate
// invented narrative. Second bullet adds the volume/usage angle that
// sentence doesn't already cover, so it's a genuine second point, not a
// rephrasing of the first.
function ssNarrativeHtml(top, rival, players) {
  if (!rival) return "";
  const bullets = [startSitCompareSentence(top, rival)];
  const snapGap = Math.round(((top.snap_pct || 0) - (rival.snap_pct || 0)) * 100);
  const rzGap = (top.redzone_touches || 0) - (rival.redzone_touches || 0);
  if (Math.abs(snapGap) >= 5 || Math.abs(rzGap) >= 3) {
    const who = snapGap >= 0 ? top : rival;
    const other = snapGap >= 0 ? rival : top;
    bullets.push(`${esc(who.player_display_name)} carries the real usage edge too — ${Math.abs(snapGap)} points more snap share and ${Math.abs(rzGap)} more red-zone touches than ${esc(other.player_display_name)}.`);
  } else {
    bullets.push(`Usage is close between them (snap share within ${Math.abs(snapGap)} points, red-zone touches within ${Math.abs(rzGap)}) — the call comes down to the numbers above, not a lopsided role.`);
  }
  return `<div class="ss-narrative">
    <div class="ss-narrative-head"><span class="ss-narrative-title">Why this call</span><span class="muted small">written from the numbers above, no AI</span></div>
    <ul>${bullets.map((b) => `<li><span class="ss-dot"></span><span>${b}</span></li>`).join("")}</ul>
  </div>`;
}

// Expand-in-place, not a separate modal: click a Start/Sit card and the
// same real breakdown the player modal shows (gauges, weekly graph) opens
// right there, so comparing two players' full stats doesn't mean losing
// the side-by-side view. Fetched once per card and cached on the DOM
// node itself — collapsing and re-expanding doesn't re-fetch.
async function toggleSSExpand(card, playerId, opp) {
  const panel = card.querySelector(".ss-expand-panel");
  const toggle = card.querySelector(".ss-expand-toggle");
  const isOpen = card.classList.toggle("expanded");
  toggle.setAttribute("aria-expanded", String(isOpen));
  if (!isOpen || panel.dataset.loaded) return;

  panel.innerHTML = `<div class="loading small">Loading full breakdown…</div>`;
  try {
    const oppQS = opp ? `&opp=${opp}` : "";
    const p = await api(`/api/player/${playerId}?${scoringQS().replace(/^&/, "")}${oppQS}`);
    panel.innerHTML = `<button type="button" class="ss-fullcard">Open full player card <span aria-hidden="true">&rarr;</span></button>${playerStatsBodyHtml(p)}`;
    panel.querySelector(".ss-fullcard").addEventListener("click", (e) => { e.stopPropagation(); openPlayerModal(playerId, opp); });
    wirePlayerStatsBody(panel, p);
    panel.dataset.loaded = "1";
  } catch (e) {
    panel.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// ------------------------------------------------- start/sit decision ----
// The decision layer from /api/startsit (engine/decision.py): verdict by win
// condition, range-of-outcomes chart, head-to-head table and flags.
// Identity colors for the players being compared. Deliberately no green,
// red or amber: those mean beat/missed/caution everywhere else in the app,
// so a player's own color never reads as a judgment of him.
const SS_COLORS = SS_TAB_COLORS;
const SS_MODE_TEXT = { floor: "protecting a lead", balanced: "a normal week", ceiling: "chasing points" };

function ssDecisionHtml(data, players) {
  const d = data.decision;
  if (!d || players.length < 2 || !players.every((p) => p.outcomes)) {
    return data.summary ? `<div class="ss-summary">${esc(data.summary)}</div>` : "";
  }
  const color = (pid) => SS_COLORS[players.findIndex((p) => p.player_id === pid) % SS_COLORS.length];
  const odds = players.map((p) => `<div class="ssd-odds-row">
      <span class="ssd-dot" style="background:${color(p.player_id)}"></span>
      <span class="ssd-odds-name">${esc(p.player_display_name)}</span>
      <span class="ssd-odds-v"><b>${p.outcomes.p_10plus}%</b> 10+</span>
      <span class="ssd-odds-v"><b>${p.outcomes.p_20plus}%</b> 20+</span>
    </div>`).join("");
  const pickP = players.find((p) => p.player_id === d.pick);
  const overP = players.find((p) => p.player_display_name === d.over_name && p.player_id !== d.pick) || players.find((p) => p.player_id !== d.pick);
  const face = (p, cls) => p ? `<span class="ssd-face ${cls}" style="--c:${color(p.player_id)}"><img ${headshotAttrs(p)} alt=""></span>` : "";
  return `<div class="ssd-card">
    <div class="ssd-top">
      <div class="ssd-faces">${face(pickP, "pick")}${face(overP, "over")}</div>
      <div class="ssd-callbody">
        <div class="ssd-k">The call · ${esc(SS_MODE_TEXT[d.mode] || d.mode)}</div>
        <div class="ssd-pick">Start <span style="color:${color(d.pick)}">${esc(d.pick_name)}</span> <span class="ssd-over">over ${esc(d.over_name)}</span></div>
        <div class="ssd-line">${esc(d.line)}</div>
      </div>
      <div class="ssd-conf ssd-conf-${esc(String(d.confidence || "").toLowerCase().replace(/\s+/g, "-"))}">
        <b>${esc(d.confidence || "")}</b>
        <span>${esc(d.edge || `${d.win_pct}% to outscore ${d.over_name}`)}</span>
      </div>
    </div>
    <div class="ssd-tags"><span class="ssd-tag">${esc(d.archetype)}</span>${d.correlated ? `<span class="ssd-tag" title="Players on the same offence, or facing each other, score together: a quarterback's big game is usually his receivers' too. Measured from 2023-26 games.">Linked scores: shared offence</span>` : ""}</div>
    <div class="ssd-odds"><div class="ssd-k">Win condition odds</div>${odds}</div>
  </div>
  <div class="ssd-grid">
    ${ssRangeChartHtml(data.chart, players, color)}
    ${ssHeadToHeadHtml(players, color)}
  </div>
  ${ssFlagsHtml(players, color)}
  ${state.meta?.ai_writeups ? `<div class="ssd-ai"><button type="button" class="wv-compare" id="ssd-ai-btn">Write me the full breakdown →</button><div id="ssd-ai-out"></div></div>` : ""}`;
}

function ssRangeChartHtml(chart, players, color) {
  if (!chart) return "";
  const W = 640, H = 170, padL = 8, padR = 8, top = 12, base = 132;
  const x = (v) => padL + ((v - chart.lo) / (chart.hi - chart.lo)) * (W - padL - padR);
  const bw = (W - padL - padR) / chart.bins;
  const live = players.filter((p) => !p.outcomes.out);
  const paths = live.map((p) => {
    const c = color(p.player_id);
    const pts = p.outcomes.curve.map((h, i) => `${(padL + bw * (i + 0.5)).toFixed(1)},${(base - h * (base - top)).toFixed(1)}`);
    const d = `M${padL},${base} L${pts.join(" L")} L${W - padR},${base} Z`;
    const mk = [["p10", 0.55], ["p50", 1], ["p90", 0.55]].map(([k, op]) =>
      `<line x1="${x(p.outcomes[k]).toFixed(1)}" x2="${x(p.outcomes[k]).toFixed(1)}" y1="${base}" y2="${base + 8}" stroke="${c}" stroke-width="${k === "p50" ? 3 : 2}" opacity="${op}"/>`).join("");
    return `<path d="${d}" fill="${c}" fill-opacity="0.16" stroke="${c}" stroke-width="2" stroke-linejoin="round"/>${mk}`;
  }).join("");
  const step = chart.hi > 40 ? 10 : 5;
  const ticks = [];
  for (let v = 0; v <= chart.hi; v += step) {
    ticks.push(`<line x1="${x(v)}" x2="${x(v)}" y1="${top}" y2="${base}" stroke="rgba(255,255,255,.05)"/><text x="${x(v)}" y="${base + 24}" text-anchor="middle">${v}</text>`);
  }
  const rows = players.map((p) => `<div class="ssr-row">
      <span class="ssd-dot" style="background:${color(p.player_id)}"></span>
      <span class="ssr-name">${esc(p.player_display_name)}</span>
      ${p.outcomes.out ? `<span class="muted">${p.outcomes.reason === "bye" ? "On a bye: 0 points" : "Ruled out: 0 points"}</span>` : `
      <span class="ssr-v"><em>Floor</em><b>${FMT.d1(p.outcomes.p10)}</b></span>
      <span class="ssr-v"><em>Median</em><b>${FMT.d1(p.outcomes.p50)}</b></span>
      <span class="ssr-v"><em>Ceiling</em><b>${FMT.d1(p.outcomes.p90)}</b></span>`}
    </div>`).join("");
  return `<div class="ssd-panel">
    <div class="ssd-h">Range of outcomes <span class="muted small">fantasy points this week</span></div>
    <div class="ssd-explain">Each shape is every way his week could go: the taller it is at a score, the more likely that score. The ticks under each shape mark his <b>floor</b> (1 bad week in 10 is lower), <b>median</b> (half his weeks beat it) and <b>ceiling</b> (1 big week in 10 is higher).</div>
    <svg class="ssr-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Range of outcomes chart, fantasy points on the horizontal axis">${ticks.join("")}${paths}<line x1="${padL}" x2="${W - padR}" y1="${base}" y2="${base}" stroke="rgba(255,255,255,.18)"/></svg>
    <div class="ssr-legend">${rows}</div>
    <div class="ssd-foot">Built from each player's projection and how much his scoring swings week to week. Checked on 662 player-games this season: 13% landed above the ceiling and 15% below the floor (10% each would be perfect).</div>
  </div>`;
}

function ssHeadToHeadHtml(players, color) {
  const dd = (p) => p.decision || {};
  const game = (p) => (p.environment || {}).game || {};
  const sgn = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}`);
  // Last-4-games value, with the season average shown underneath.
  const rec = (p, k) => (dd(p).recent || {})[k]?.recent ?? null;
  const sea = (p, k, suf) => {
    const x = (dd(p).recent || {})[k];
    return x && x.season != null ? `season ${k === "snap_pct" ? Math.round(x.season) : FMT.d1(x.season)}${suf}` : "";
  };
  const rows = [
    ["Start/Sit rating", (p) => dd(p).rating, (v) => (v == null ? "—" : `${Math.round(v)}/100`), 1],
    ["Projection", (p) => p.PROJ, (v) => FMT.d1(v), 1],
    ["Snap share", (p) => rec(p, "snap_pct"), (v) => (v == null ? "—" : `${Math.round(v)}%`), 1, (p) => sea(p, "snap_pct", "%")],
    ["Target share", (p) => rec(p, "target_share"), (v) => (v == null ? "—" : `${FMT.d1(v)}%`), 1, (p) => sea(p, "target_share", "%")],
    ["High-value touches / game", (p) => rec(p, "hvt_pg"), (v) => (v == null ? "—" : FMT.d1(v)), 1, (p) => sea(p, "hvt_pg", "")],
    ["Expected pts / game (xFP)", (p) => rec(p, "xfp_pg"), (v) => (v == null ? "—" : FMT.d1(v)), 1, (p) => sea(p, "xfp_pg", "")],
    ["Goal-line share (inside the 5)", (p) => dd(p).goal_line_share, (v) => (v == null ? "—" : `${v}%`), 1],
    ["Points vs xFP", (p) => dd(p).xfp_diff, (v) => (v == null ? "—" : sgn(Math.round(v * 10) / 10)), 0],
    ["Team implied total", (p) => game(p).implied_total, (v) => (v == null ? "—" : String(v)), 1],
    ["Spread", (p) => game(p).margin, (v) => (v == null ? "—" : v > 0 ? `Fav by ${v}` : v < 0 ? `Dog by ${-v}` : "Pick'em"), 0],
    ["Defense vs his position", (p) => dd(p).defense_rank, (v) => (v == null ? "—" : `${v}${v === 1 ? "st" : v === 2 ? "nd" : v === 3 ? "rd" : "th"} easiest`), -1],
    ["Work share leading / trailing", (p) => dd(p).script_split, (v) => (v ? `${v.leading}% / ${v.trailing}%` : "—"), 0],
    ["Weather at kickoff", (p) => game(p).weather, (v) => (v ? (v.maybe_closed ? "Roof may be closed" : v.index ? `${v.label}: ${v.reasons.join(", ")}` : `${v.temp}°F, ${v.wind} mph`) : "Indoors / n/a"), 0],
  ];
  const head = players.map((p) => `<th style="color:${color(p.player_id)}">${esc(p.player_display_name)}</th>`).join("");
  const body = rows.map(([label, get, fmt, dir, sub]) => {
    const vals = players.map(get);
    let best = -1;
    if (dir !== 0) {
      const nums = vals.map((v) => (typeof v === "number" ? v : null));
      const ok = nums.filter((v) => v != null);
      if (ok.length >= 2 && new Set(ok).size > 1) {
        const target = dir > 0 ? Math.max(...ok) : Math.min(...ok);
        best = nums.indexOf(target);
      }
    }
    const tag = sub ? ` <small class="ssh-tag">last 4</small>` : "";
    return `<tr><td>${label}${tag}</td>${vals.map((v, i) => {
      const s2 = sub ? sub(players[i]) : "";
      return `<td class="${i === best ? "ssh-win" : ""}">${esc(fmt(v))}${s2 ? `<span class="ssh-sub">${esc(s2)}</span>` : ""}</td>`;
    }).join("")}</tr>`;
  }).join("");
  return `<div class="ssd-panel">
    <div class="ssd-h">Head to head <span class="muted small">green = the edge on that line · usage rows are his last 4 games, season average underneath</span></div>
    <div class="ssh-wrap"><table class="ssh-table"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="ssd-foot">Route participation, DVOA and man/zone coverage splits aren't available from any free source, so they aren't shown.</div>
  </div>`;
}

function ssFlagsHtml(players, color) {
  const cols = players.map((p) => {
    const d = p.decision || {};
    const c = d.components || {};
    const parts = [["role", "Role & xFP", 40], ["matchup", "Matchup", 30], ["script", "Script & total", 20], ["recent", "Form & health", 10]]
      .map(([k, label, w]) => `<div class="ssf-part"><em>${label} <small>${w}%</small></em><s><i style="width:${Math.round(c[k] || 0)}%;background:${color(p.player_id)}"></i></s><b>${Math.round(c[k] || 0)}</b></div>`).join("");
    const good = (d.flags_good || []).map((f) => `<li class="ok">${esc(f)}</li>`).join("");
    const bad = (d.flags_bad || []).map((f) => `<li class="warn">${esc(f)}</li>`).join("");
    return `<div class="ssf-col">
      <div class="ssf-name"><span class="ssd-dot" style="background:${color(p.player_id)}"></span>${esc(p.player_display_name)}<span class="ssf-rating">${Math.round(d.rating || 0)}</span></div>
      <div class="ssf-parts">${parts}</div>
      <ul class="ssf-list">${good}${bad}${!good && !bad ? `<li class="muted">Nothing unusual about this matchup.</li>` : ""}</ul>
    </div>`;
  }).join("");
  return `<div class="ssd-panel">
    <div class="ssd-h">Advantages and warnings <span class="muted small">rating = 40% role + 30% matchup + 20% script + 10% form</span></div>
    <div class="ssf-grid" style="--n:${Math.min(players.length, 4)}">${cols}</div>
  </div>`;
}

async function ssLoadWriteUp(body) {
  const out = $("#ssd-ai-out");
  const btn = $("#ssd-ai-btn");
  btn.disabled = true;
  out.innerHTML = `<div class="loading small">Writing the breakdown…</div>`;
  try {
    const r = await api("/api/startsit/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    out.innerHTML = `<div class="ssd-panel ssd-writeup">
      ${(r.diagnostics || []).map((x) => `<div class="ssw-block"><div class="ssd-k">${esc(x.player)}</div><p>${esc(x.case)}</p></div>`).join("")}
      <div class="ssw-block"><div class="ssd-k">Floor case</div><p>${esc(r.floor_case || "")}</p></div>
      <div class="ssw-block"><div class="ssd-k">Ceiling case</div><p>${esc(r.ceiling_case || "")}</p></div>
      <div class="ssw-block ssw-final"><div class="ssd-k">Final call</div><p>${esc(r.final_call || "")}</p></div>
      <div class="ssd-foot">Written by Claude from the numbers above only.</div>
    </div>`;
    btn.style.display = "none";
  } catch (e) {
    out.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    btn.disabled = false;
  }
}

async function runStartSit() {
  const opponents = {};
  state.startsit.forEach((p) => { if (p.opp) opponents[p.player_id] = p.opp; });
  const body = { player_ids: state.startsit.map((p) => p.player_id), opponents, scoring: scoringDict(), mode: state.ssMode };

  // "locking in" flash on the slot cards themselves before the results
  // land — the animation the compare click is supposed to trigger.
  document.querySelectorAll("#startsit-chips .ss-slot").forEach((slot, i) => {
    slot.classList.remove("confirming");
    void slot.offsetWidth; // restart the animation if clicked more than once
    slot.style.animationDelay = `${i * 90}ms`;
    slot.classList.add("confirming");
  });

  const results = $("#startsit-results");
  results.innerHTML = `<div class="loading">Comparing…</div>`;
  try {
    const data = await api("/api/startsit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const sorted = data.players.slice().sort((a, b) => (b.rank_value ?? b.PROJ ?? -999) - (a.rank_value ?? a.PROJ ?? -999));
    const valid = sorted.filter((p) => !p.error);
    const scaleMin = Math.min(0, ...valid.map((p) => (p.floor != null ? p.floor : p.PROJ)));
    const scaleMax = Math.max(1, ...valid.map((p) => (p.ceiling != null ? p.ceiling : p.PROJ)));

    // When the decision layer is present its pick is THE recommendation:
    // the hero badge, the "why" bullets and the verdict card must agree (they
    // could disagree before — the hero used the lens-ranked first player).
    const decided = data.decision && valid.find((p) => p.player_id === data.decision.pick);
    const top = decided || valid[0];
    const errors = sorted.filter((p) => p.error)
      .map((p) => `<div class="result-card"><span>${esc(p.player_id)}: ${esc(p.error)}</span></div>`).join("");

    // Swap only makes sense as a literal head-to-head — a real 2-player
    // comparison — not a 3-4 player grid, which has no "other side" to
    // swap with. Reorders display only; selection/data are untouched.
    const isHeadToHead = valid.length === 2;
    const heroOrder = isHeadToHead && state.ssSwapped ? [valid[1], valid[0]] : valid;
    // With a decision card on screen its confidence is the one that counts;
    // the hero ring is a different number and only confused the read.
    const heroCards = heroOrder.map((p, i) => startSitCardHtml(p, scaleMin, scaleMax, i, p.player_id === top?.player_id, !!decided)).join("");
    const swapBtn = isHeadToHead
      ? `<button type="button" class="ss-swap-btn" id="ss-swap-btn" title="Swap sides">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M7 4v13M7 17l-3-3M7 17l3-3M17 20V7M17 7l3 3M17 7l-3 3"/>
          </svg>
        </button>` : "";

    const extra = `${valid.length >= 2 ? ssBreakdownPanelHtml(valid) : ""}
      ${top ? ssNarrativeHtml(top, valid.find((x) => x.player_id !== top.player_id), valid) : ""}`;
    results.innerHTML = `
      ${errors}
      ${ssDecisionHtml(data, valid)}
      <div class="ss-hero-row${isHeadToHead ? " head-to-head" : ""}">${heroCards}${swapBtn}</div>
      ${decided ? `<details class="ss-legacy"><summary>More side-by-side stats</summary>${extra}</details>` : extra}
    `;

    results.querySelectorAll(".ss-card").forEach((card) => {
      const p = valid.find((x) => x.player_id === card.dataset.pid);
      // Scoped to the toggle button itself, not the whole card — the
      // expanded panel holds its own interactive bits (the weekly stat
      // picker), and a card-wide click handler would fight clicks
      // inside those instead of just the intended expand/collapse.
      card.querySelector(".ss-expand-toggle").addEventListener("click", () => toggleSSExpand(card, card.dataset.pid, p?.opponent));
    });
    $("#ssd-ai-btn")?.addEventListener("click", () => ssLoadWriteUp(body));
    const breakdown = results.querySelector(".ss-breakdown");
    if (breakdown) wireSSBreakdownTabs(breakdown);
    $("#ss-swap-btn")?.addEventListener("click", (e) => {
      state.ssSwapped = !state.ssSwapped;
      e.currentTarget.classList.add("spin");
      runStartSit();
    });
    animateSSRings();
    if (breakdown) animateSSBars(breakdown);
    // This comparison just logged fresh predictions server-side (see
    // /api/startsit) — refresh so "N pending" reflects them right away,
    // rather than waiting for the next tab visit.
    loadTrackRecord();
  } catch (e) {
    results.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// --------------------------------------------------------- track record ----
// "How often has our own START call actually been right" — real accuracy,
// graded only against real, already-played weeks (see engine/db.py's
// get_track_record). A season with nothing resolved yet just hides the
// strip rather than showing a hollow 0% or a fabricated placeholder.
async function loadTrackRecord() {
  const strip = $("#track-record-strip");
  if (!state.user) { strip.style.display = "none"; return; }
  try {
    const data = await api("/api/track-record");
    if (!data.resolved && !data.pending) { strip.style.display = "none"; return; }
    strip.style.display = "";
    const pctBlock = data.accuracy_pct != null
      ? `<span class="tr-pct" data-target="${data.accuracy_pct}"></span>
         <span class="tr-pct-lbl">of our START calls hit<br>(${data.correct}/${data.resolved} graded)</span>`
      : `<span class="tr-pct muted">—</span><span class="tr-pct-lbl">no graded calls yet this season</span>`;
    const pendingBlock = data.pending
      ? `<span class="tr-pending">${data.pending} more logged, waiting on this week's games</span>` : "";
    strip.innerHTML = `<div class="tr-stat">${pctBlock}</div>${pendingBlock}`;
    const pctNode = strip.querySelector(".tr-pct[data-target]");
    if (pctNode) countUp(pctNode, Number(pctNode.dataset.target), { decimals: 1, duration: 700 });
    setTimeout(() => { if (pctNode) pctNode.textContent += "%"; }, 720);
  } catch (e) {
    strip.style.display = "none";
  }
}

async function renderStartSitPicker() {
  const picker = $("#startsit-roster-picker");
  try {
    await ensureMyRoster();
  } catch (e) { picker.innerHTML = ""; return; }
  picker.innerHTML = state.shopRoster.map((p) => `
    <button type="button" class="shop-chip${state.startsit.some((x) => x.player_id === p.player_id) ? " selected" : ""}" data-pid="${esc(p.player_id)}">
      <img ${headshotAttrs(p)} alt="">
      <span class="pos-badge">${esc(p.position)}</span>
      <span>${esc(p.player_display_name)}</span>
    </button>
  `).join("");
  picker.querySelectorAll(".shop-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const pid = chip.dataset.pid;
      const already = state.startsit.some((x) => x.player_id === pid);
      if (already) {
        state.startsit = state.startsit.filter((x) => x.player_id !== pid);
      } else {
        if (state.startsit.length >= 4) return;
        const p = state.shopRoster.find((x) => x.player_id === pid);
        state.startsit.push({ ...p, opp: "" });
      }
      chip.classList.toggle("selected");
      renderStartSitChips();
    });
  });
}

async function loadStartSitTab() {
  const gate = $("#startsit-gate");
  const body = $("#startsit-body");
  if (!state.user || !activeTeam()) {
    gate.style.display = "";
    body.style.display = "none";
    return;
  }
  gate.style.display = "none";
  body.style.display = "";
  await renderStartSitPicker();
  loadTrackRecord();
  loadStartSitSuggestions();
  renderLineupAdvisor();
}

// ------------------------------------------------ whole-lineup advisor ----
// engine/lineup_advisor.py: the exact best lineup for this week under the
// Safe / Balanced / Upside lens, flex slots included, and what it changes.
const ADVISOR_MODES = [["safe", "Safe", "Protecting a lead: favors fewer duds"], ["balanced", "Balanced", "Highest average points"],
  ["upside", "Upside", "Chasing: favors big weeks"]];

function renderLineupAdvisor(res, loading) {
  const host = $("#ss-lineup-advisor");
  if (!host) return;
  const mode = state.ssMode || "balanced";
  const pills = ADVISOR_MODES.map(([k, l, t]) => `<button type="button" class="pill${k === mode ? " active" : ""}" data-mode="${k}" title="${esc(t)}">${l}</button>`).join("");
  const face = (p) => `<img class="adv-face" ${headshotAttrs({ headshot_url: p.headshot_url, player_display_name: p.name || "" })} alt="">`;
  let out = `<div class="muted small">Solves your whole lineup at once, flex slots included, instead of one pair at a time.</div>`;
  if (loading) out = `<div class="loading small">Solving your lineup…</div>`;
  else if (res && res.error) out = `<div class="form-msg error">${esc(res.error)}</div>`;
  else if (res) {
    const gain = res.best_mode_value - res.current_mode_value;
    const head = res.changes.length
      ? `<b>${res.changes.length} change${res.changes.length === 1 ? "" : "s"}</b> adds <b>${gain.toFixed(1)}</b> ${esc(mode)}-value points (${FMT.d1(res.current_mean)} → ${FMT.d1(res.best_mean)} average) for Week ${esc(res.week)}.`
      : `Your Week ${esc(res.week)} lineup is already the best one for the ${esc(mode)} lens (${FMT.d1(res.best_mean)} average).`;
    const rows = res.changes.map((c) => {
      const add = res.adds.find((p) => p.player_id === c.in) || res.lineup.find((p) => p.player_id === c.in) || {};
      return `<div class="adv-row">${face(add)}<div class="adv-txt"><b>Start ${esc(c.in_name)}</b> at ${esc(c.slot)}${c.out_name ? ` over ${esc(c.out_name)}` : ""}
        <span class="muted small">${c.delta_mean >= 0 ? "+" : ""}${c.delta_mean.toFixed(1)} avg · ${c.delta_mode >= 0 ? "+" : ""}${c.delta_mode.toFixed(1)} ${esc(mode)}</span></div></div>`;
    }).join("");
    const locked = res.locked_slots.length ? `<div class="muted small">Already kicked off, left alone: ${res.locked_slots.map(esc).join(", ")}.</div>` : "";
    const rg = res.range && res.range.best ? (() => {
      const f = (r) => `${FMT.d1(r.p10)}&ndash;${FMT.d1(r.p90)}`;
      const wide = res.range.best.widening;
      return `<div class="adv-range"><span class="k">Range this week</span> Best lineup <b>${f(res.range.best)}</b> (10th&ndash;90th percentile)${res.range.current ? `, your current one <b>${f(res.range.current)}</b>` : ""}.
        ${Math.abs(wide) >= 1 ? `<span class="muted small">Stacked offences make it ${Math.abs(wide).toFixed(1)} points ${wide > 0 ? "wider" : "narrower"} than if every starter were unrelated.</span>` : ""}</div>`;
    })() : "";
    out = `<div class="adv-head">${head}</div>${rows}${rg}${locked}
      <div class="muted small">Ranks lineups by the lens you picked. It is not a win-probability calculation, and Out players and byes count as zero.</div>`;
  }
  host.innerHTML = `<div class="sec-head first"><div><h2>Best lineup, whole roster</h2></div><div class="pill-group adv-modes">${pills}</div></div>
    ${out}<button type="button" class="primary-btn" id="adv-run"${loading ? " disabled" : ""}>Solve my lineup</button>`;
  host.querySelectorAll(".adv-modes .pill").forEach((b) => b.addEventListener("click", () => {
    state.ssMode = b.dataset.mode;
    document.querySelectorAll("#ss-mode [data-mode]").forEach((x) => x.classList.toggle("active", x.dataset.mode === state.ssMode));
    renderLineupAdvisor();
  }));
  $("#adv-run").addEventListener("click", async () => {
    renderLineupAdvisor(null, true);
    try {
      renderLineupAdvisor(await api(`/api/startsit/lineup?mode=${encodeURIComponent(state.ssMode || "balanced")}${scoringQS()}`));
    } catch (e) { renderLineupAdvisor({ error: e.message }); }
  });
}

// ---------------------------------------------- top recommendations ----
// The real top 3 (or fewer — /api/startsit/suggestions never pads to a
// fixed count) start/sit calls on your own actual roster, shown above
// the manual picker/compare tool — see engine.tools.
// start_sit_suggestions_from_roster for how these are found (same-
// position weakest-starter vs strongest-bench, real PROJ gap, most
// actionable first). Each card is a real shortcut into the exact same
// manual compare flow below, not a separate rendering path — clicking
// one loads those two players into the picker and runs the real
// comparison immediately.
function ssSuggestCardHtml(s) {
  const [a, b] = s.players; // a = weakest starter, b = strongest bench (start_sit_suggestions_from_roster's own order)
  if (!a || !b || a.error || b.error) return "";
  const swap = s.gap > 0;
  const verdict = swap
    ? `<span class="ss-suggest-verdict swap">▲ Real upgrade on your bench — +${FMT.d1(s.gap)} pts</span>`
    : `<span class="ss-suggest-verdict hold">Starter confirmed — ahead by ${FMT.d1(Math.abs(s.gap))} pts</span>`;
  const miniRow = (p, tone) => `<div class="ss-suggest-player ${tone}">
    <img ${headshotAttrs(p)} alt="">
    <div><div class="ss-suggest-name">${esc(p.player_display_name)}</div><div class="ss-suggest-proj tabular">${FMT.d1(p.PROJ)} pts</div></div>
  </div>`;
  // Real bug fixed here: both verdicts used to render with the same
  // out(struck-through)/in(highlighted) treatment regardless of which
  // one actually won — so a "Starter confirmed" card still visually
  // read as "cut your starter for this bench guy," the opposite of its
  // own text. The tone now follows the real verdict: swap struck-
  // through/highlights the bench pickup like before; hold instead
  // highlights the CONFIRMED starter and shows the bench player
  // neutrally (compared, not cut — nothing here is actually changing).
  const aTone = swap ? "out" : "confirmed";
  const bTone = swap ? "in" : "compared";
  return `<div class="ss-suggest-card kbd-click${swap ? " swap" : ""}" role="button" tabindex="0" data-starter="${esc(a.player_id)}" data-bench="${esc(b.player_id)}">
    <div class="ss-suggest-pos">${esc(s.position)}</div>
    <div class="ss-suggest-pair">
      ${miniRow(a, aTone)}
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ss-suggest-arrow"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      ${miniRow(b, bTone)}
    </div>
    ${verdict}
  </div>`;
}

async function loadStartSitSuggestions() {
  const wrap = $("#ss-suggestions");
  const list = $("#ss-suggestions-list");
  try {
    const data = await api("/api/startsit/suggestions");
    if (!data.suggestions.length) { wrap.style.display = "none"; return; }
    list.innerHTML = data.suggestions.map(ssSuggestCardHtml).join("");
    list.querySelectorAll(".ss-suggest-card").forEach((card) => {
      card.addEventListener("click", () => loadSuggestionIntoCompare(card.dataset.starter, card.dataset.bench));
    });
    wrap.style.display = "";
  } catch (e) {
    // A real roster with fewer than 2 comparable positions (e.g. a
    // brand-new team with no bench yet) is a normal state, not an
    // error worth surfacing — just don't show the section.
    wrap.style.display = "none";
  }
}

async function loadSuggestionIntoCompare(starterId, benchId) {
  const [starter, bench] = await Promise.all([
    api(`/api/player/${starterId}`), api(`/api/player/${benchId}`),
  ]).catch(() => [null, null]);
  if (!starter || !bench) return;
  const pick = (p) => ({ player_id: p.player_id, player_display_name: p.player_display_name, position: p.position,
    recent_team: p.recent_team, headshot_url: p.headshot_url, injury_status: p.injury_status, opp: "" });
  state.startsit = [pick(starter), pick(bench)];
  renderStartSitChips();
  // keep the roster picker's selected chips in step with the slots
  document.querySelectorAll("#startsit-roster-picker .shop-chip").forEach((c) =>
    c.classList.toggle("selected", state.startsit.some((x) => x.player_id === c.dataset.pid)));
  $(".ss-toolbar")?.scrollIntoView({ behavior: "smooth", block: "start" });
  runStartSit();
}

$("#startsit-gate-btn")?.addEventListener("click", () => switchTab("settings"));

function initStartSit() {
  $("#startsit-compare").addEventListener("click", runStartSit);
  document.querySelectorAll("#ss-mode .ss-mode-btn").forEach((b) => b.addEventListener("click", () => {
    state.ssMode = b.dataset.mode;
    document.querySelectorAll("#ss-mode .ss-mode-btn").forEach((x) => x.classList.toggle("active", x === b));
    if (state.startsit.length >= 2 && $("#startsit-results .ss-card")) runStartSit();
  }));
  initSSScoringToggle();
}

// A real segmented toggle in the tool's own header — not a separate,
// disconnected piece of state: it drives the exact same state.scoring
// the sidebar's #scoring-select does (and keeps that select in sync,
// so the two never disagree), then re-runs the live comparison
// immediately if one's already on screen, so switching formats here
// actually recomputes real PROJ/floor/ceiling rather than just
// changing a label.
function initSSScoringToggle() {
  const bar = $("#ss-scoring-toggle");
  const leagueBtn = $("#ss-scoring-league");
  if (leagueBtn) leagueBtn.style.display = activeTeam() ? "" : "none";
  const sync = () => {
    bar.querySelectorAll("button").forEach((b) => b.classList.toggle("active", (state.scoring || "") === b.dataset.scoring));
  };
  sync();
  bar.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      if ((state.scoring || "") === b.dataset.scoring) return;
      state.scoring = b.dataset.scoring;
      saveScoring();
      const sel = $("#scoring-select");
      if (sel) sel.value = state.scoring;
      sync();
      if (state.tab === "board") loadBoard();
      if (state.startsit.length >= 2 && $("#startsit-results .ss-hero")) runStartSit();
    });
  });
}

// --------------------------------------------------------------- trade ----
function renderTradeChips(side) {
  const listKey = side === "a" ? "tradeA" : "tradeB";
  const row = $(`#trade-${side}-chips`);
  row.innerHTML = "";
  state[listKey].forEach((p) => {
    const chip = el("div", "chip");
    chip.innerHTML = `<img ${headshotAttrs(p)} alt="">
      <span>${esc(p.player_display_name)}</span><button class="chip-x" aria-label="Remove ${esc(p.player_display_name)}">✕</button>`;
    chip.querySelector(".chip-x").addEventListener("click", () => {
      state[listKey] = state[listKey].filter((x) => x.player_id !== p.player_id);
      renderTradeChips(side);
    });
    row.appendChild(chip);
  });
  $("#trade-analyze").disabled = !(state.tradeA.length && state.tradeB.length);
}

// ---- Trade analysis: value + real roster-needs recommendation, animated. ----
const TRADE_TIER_META = {
  great: { label: "Great Trade", css: "tier-great", icon: "🔥" },
  smart: { label: "Smart Move", css: "tier-great", icon: "🎯" },
  good_value: { label: "Good Value", css: "tier-good", icon: "📈" },
  worth_it: { label: "Worth It", css: "tier-good", icon: "✅" },
  fair: { label: "Fair", css: "tier-fair", icon: "⚖️" },
  questionable: { label: "Questionable", css: "tier-questionable", icon: "🤔" },
  good_value_bad_fit: { label: "Mixed Bag", css: "tier-questionable", icon: "🔀" },
  bad_value: { label: "Bad Value", css: "tier-bad", icon: "📉" },
  bad: { label: "Avoid", css: "tier-bad", icon: "⛔" },
};

// Animates a number counting up (or down, for a negative target) from 0 to
// its final value with an ease-out curve — the "cool" reveal for the value
// numbers, not just a static digit appearing.
function countUp(node, target, { decimals = 1, signed = false, duration = 800 } = {}) {
  const start = performance.now();
  const sign = signed && target > 0 ? "+" : "";
  if (prefersReducedMotion) { node.textContent = (target < 0 ? "" : sign) + target.toFixed(decimals); return; }
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const val = target * eased;
    node.textContent = (target < 0 ? "" : sign) + val.toFixed(decimals);
    if (t < 1) requestAnimationFrame(frame);
    else node.textContent = (target < 0 ? "" : sign) + target.toFixed(decimals);
  }
  requestAnimationFrame(frame);
}

// Need multiplier (0.82 deep .. 1.0 set .. 1.25 real need) -> a 20-100%
// bar fill and a red/amber/green urgency class, same idea as the Start/Sit
// tier badges elsewhere in this app.
function needBarPct(mult) {
  const clamped = Math.max(0.82, Math.min(1.25, mult));
  return Math.round(((clamped - 0.82) / (1.25 - 0.82)) * 80 + 20);
}
function needBarClass(mult) {
  if (mult >= 1.25) return "need-high";
  if (mult >= 1.0) return "need-mid";
  return "need-low";
}

function needBarsHtml(needs, touchedPositions) {
  return POSITIONS.map((pos) => {
    const mult = needs?.[pos];
    if (mult == null) return "";
    const touched = touchedPositions.has(pos) ? " touched" : "";
    return `<div class="need-bar${touched}" title="${pos}: ${mult >= 1.25 ? "real need" : mult >= 1.0 ? "adequately filled" : "already deep"}">
      <span class="need-bar-label">${pos}</span>
      <span class="need-bar-track"><span class="need-bar-fill ${needBarClass(mult)}" data-pct="${needBarPct(mult)}"></span></span>
    </div>`;
  }).join("");
}

// A side's give-package can span positions, so there's no one "correct"
// accent — pick a priority order (QB/DEF/K read as the headline decision
// on a side; a pure skill-position side falls back to acc-skill) rather
// than tagging nothing at all. Delegates the actual position->class
// mapping to the same posAccentClass() the player-modal header already uses.
function sideAccentClass(touchedPositions) {
  if (!touchedPositions.size) return "";
  if (touchedPositions.has("QB")) return posAccentClass("QB");
  if (touchedPositions.has("DEF")) return posAccentClass("DEF");
  if (touchedPositions.has("K")) return posAccentClass("K");
  return posAccentClass([...touchedPositions][0]); // any remaining position is RB/WR/TE -> acc-skill anyway
}

function tradeSideCardHtml(sideKey, rec, teamName, touchedPositions, delayMs) {
  const meta = TRADE_TIER_META[rec.tier] || TRADE_TIER_META.fair;
  const label = sideKey === "side_a" ? "Side A" : "Side B";
  const accent = sideAccentClass(touchedPositions);
  return `<div class="tvc ${meta.css}${accent ? ` ${accent}` : ""}" style="animation-delay:${delayMs}ms">
    <div class="tvc-header">
      <span class="tvc-side-label">${esc(label)}${teamName ? ` · ${esc(teamName)}` : ""}</span>
      <span class="trade-tier-badge ${meta.css}"><span class="tvc-icon">${meta.icon}</span>${esc(meta.label)}</span>
    </div>
    <div class="tvc-net">
      <span class="tvc-net-num ${rec.net_value < 0 ? "neg" : "pos"}" data-target="${rec.net_value}"></span>
      <span class="tvc-net-lbl">net value</span>
    </div>
    <div class="tvc-reason">${esc(rec.reason)}</div>
    <div class="tvc-needs-label">Roster needs right now</div>
    <div class="tvc-needs">${needBarsHtml(rec.needs, touchedPositions)}</div>
    <div class="need-legend"><span><i class="need-high"></i>Real need</span><span><i class="need-mid"></i>Filled</span><span><i class="need-low"></i>Already deep</span><span class="muted">outlined = in this trade</span></div>
  </div>`;
}

function tradePlayerCardHtml(p, delayMs) {
  if (p.error) return `<div class="result-card" style="animation-delay:${delayMs}ms"><span>${esc(p.player_id)}: ${esc(p.error)}</span></div>`;
  const accent = posAccentClass(p.position);
  return `<div class="result-card${accent ? ` ${accent}` : ""}" style="animation-delay:${delayMs}ms">
    <img ${headshotAttrs(p)} alt="">
    <div><div class="name">${esc(p.player_display_name)}</div><div class="meta">${esc(p.position)} · ${esc(p.recent_team)} · PVS ${FMT.d1(p.SCORE)}</div></div>
    <div class="proj"><div class="num">${FMT.d1(p.value)}</div><div class="lbl">value</div></div>
  </div>`;
}

// ------------------------------------------------------ trade verdicts ----
// The trade engine's verdict (engine/trade_engine.py), shared by the Trade
// Analyzer and every Trade Finder card.
const TV_STATUS = {
  APPROVED: ["tv-ok", "Realistic"],
  MODIFICATION_REQUIRED: ["tv-warn", "Needs a tweak"],
  VETOED: ["tv-bad", "Dead on arrival"],
};
const TV_GATES = [
  ["tier_break_passed", "Tier break", "A tier-1 player can't be bought with lesser pieces."],
  ["lineup_delta_passed", "Both lineups improve", "They gain 1.5+ starting PPG and you gain 0.5+."],
  ["fairness_passed", "Fairness index", "Within 95-105 is even; 85-94 only with a big need on their side; 106-115 only to land a tier-1 player."],
  ["roster_fit_passed", "Roster fit", "Extra players are covered by cutting bench players, never starters."],
  ["incentive_passed", "Their incentives", "Contenders don't sell studs for depth; only struggling teams sell a tier-1 player for two pieces."],
  ["insult_passed", "Not an insult", "Asking for their best player means sending back at least 85% of his value."],
  ["bye_passed", "Bye-week safe", "The trade can't leave them with an empty starting slot in an upcoming bye week."],
];
const TV_SCRIPTS = [
  ["casual_manager", "Casual manager"], ["quantitative_analyst", "Numbers person"],
  ["skeptical_manager", "Skeptic"], ["desperate_manager", "Desperate team"],
];

function tvFairnessScale(fi) {
  const lo = 70, hi = 130;
  const pos = Math.max(0, Math.min(100, ((fi - lo) / (hi - lo)) * 100));
  const zone = (a, b, cls) => `<i class="${cls}" style="left:${((a - lo) / (hi - lo)) * 100}%;width:${((b - a) / (hi - lo)) * 100}%"></i>`;
  return `<div class="tv-fi">
    <div class="tv-fi-bar">${zone(85, 95, "z-near")}${zone(95, 105, "z-fair")}${zone(105, 115, "z-near")}<b style="left:${pos}%"></b></div>
    <div class="tv-fi-labels"><span>you underpay</span><span>even</span><span>you overpay</span></div>
  </div>`;
}

function tradeVerdictHtml(ev, compact) {
  if (!ev) return "";
  const v = ev.verdict, q = ev.quantitative_breakdown, d = ev.team_impact_diagnostics;
  const [cls, label] = TV_STATUS[v.status] || ["", v.status];
  const gates = TV_GATES.map(([k, name, tip]) => ev.gate_audit[k] === null
    ? `<span class="tv-gate skip" title="Not required for a dead-even trade: it can be fair without moving either lineup.">– ${name} (not required)</span>`
    : `<span class="tv-gate ${ev.gate_audit[k] !== false ? "pass" : "fail"}" title="${esc(tip)}">${ev.gate_audit[k] !== false ? "✓" : "✕"} ${name}</span>`).join("");
  const model = (q.acceptance_model || []).map((m) => `<li><span>${esc(m.factor)}</span><b class="${m.points >= 0 ? "pos" : "neg"}">${m.points > 0 && m !== q.acceptance_model[0] ? "+" : ""}${m.points}</b></li>`).join("");
  const scripts = TV_SCRIPTS.map(([k, name]) => ev.negotiation_scripts?.[k] ? `<div class="tv-script">
      <div class="tv-script-h"><span>${name}</span><button type="button" class="tv-copy" data-copy="${esc(ev.negotiation_scripts[k])}">Copy</button></div>
      <p>${esc(ev.negotiation_scripts[k])}</p></div>` : "").join("");
  const drops = [q.opponent_drop_candidate && `They'd drop ${esc(q.opponent_drop_candidate.name)} (value ${FMT.d1(q.opponent_drop_candidate.value_lost)})`,
    q.user_drop_candidate && `You'd drop ${esc(q.user_drop_candidate.name)} (value ${FMT.d1(q.user_drop_candidate.value_lost)})`].filter(Boolean);
  const head = `<div class="tv-head">
      <div class="tv-grade ${cls}">${esc(v.fairness_grade)}</div>
      <div class="tv-head-main">
        <div><span class="tv-status ${cls}">${label}</span><span class="tv-prob"><b>${v.acceptance_probability_pct}%</b> chance they accept</span></div>
        <div class="tv-summary">${esc(v.summary_reason)}</div>
      </div>
    </div>
    <div class="tv-nums">
      <div><span class="tv-k">Your starting lineup</span><b class="${q.user_starting_delta_ppg.startsWith("-") ? "neg" : "pos"}">${esc(q.user_starting_delta_ppg)}</b><small>PPG</small></div>
      <div><span class="tv-k">Their starting lineup</span><b class="${q.opponent_starting_delta_ppg.startsWith("-") ? "neg" : "pos"}">${esc(q.opponent_starting_delta_ppg)}</b><small>PPG</small></div>
      <div class="tv-fi-cell"><span class="tv-k">Fairness index</span><b>${Math.round(q.fairness_index)}</b>${tvFairnessScale(q.fairness_index)}</div>
    </div>
    <div class="tv-gates">${gates}</div>`;
  const body = `
    <div class="tv-cols">
      <div><div class="tv-k">For you</div><p>${esc(d.user_roster_pros)}</p><p class="muted">${esc(d.user_roster_cons)}</p></div>
      <div><div class="tv-k">${v.status === "APPROVED" ? "Why they'd accept" : "Their side"}</div><p>${esc(d.opponent_rationale)}</p></div>
    </div>
    <div class="tv-cols">
      <div><div class="tv-k">Package math</div><p class="tv-mono">You give ${FMT.d1(q.you_give_effective_value)} · you get ${FMT.d1(q.you_get_effective_value)} (effective chart value)<br>Raw gap ${esc(q.raw_value_gap)} · package-adjusted ${esc(q.package_adjusted_gap)}${drops.length ? `<br>${drops.join("<br>")}` : ""}</p></div>
      <div><div class="tv-k">Acceptance estimate</div><ul class="tv-model">${model}</ul><div class="tv-foot">A transparent estimate from these factors, not a measured rate.</div></div>
    </div>
    ${scripts ? `<div class="tv-k">Send it: pick the message that fits them</div><div class="tv-scripts">${scripts}</div>` : ""}
    ${ev.note ? `<div class="tv-foot">${esc(ev.note)}</div>` : ""}`;
  return compact
    ? `<div class="tv tv-compact">${head}<details class="tv-more"><summary>Full breakdown and messages</summary>${body}</details></div>`
    : `<div class="tv">${head}${body}</div>`;
}

function wireTradeVerdict(root) {
  root.querySelectorAll(".tv-copy").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; }
    catch (e) { b.textContent = "Copy failed"; }
    setTimeout(() => { b.textContent = "Copy"; }, 1500);
  }));
}

function renderTradeAnalysis(data) {
  const results = $("#trade-results");
  const rec = data.recommendation;
  const aTouched = new Set(data.side_a.players.filter((p) => p.position).map((p) => p.position));
  const bTouched = new Set(data.side_b.players.filter((p) => p.position).map((p) => p.position));

  let html = `<div class="trade-analysis">
    ${data.evaluation ? tradeVerdictHtml(data.evaluation, false) : ""}
    <div class="trade-hero"${data.evaluation ? ' style="display:none"' : ""}>
      <div class="trade-hero-value-row">
        <div class="thv-side">
          <div class="thv-label">Side A gives up</div>
          <div class="thv-num" data-target="${data.side_a.total_value}"></div>
        </div>
        <div class="thv-vs">⇄</div>
        <div class="thv-side">
          <div class="thv-label">Side B gives up</div>
          <div class="thv-num" data-target="${data.side_b.total_value}"></div>
        </div>
      </div>
      ${rec ? `<div class="trade-hero-headline">${esc(rec.headline)}</div>` : `<div class="trade-hero-headline muted">Sign in with a connected league to see a needs-aware recommendation, not just point totals.</div>`}
    </div>`;

  if (rec) {
    html += `<div class="trade-verdict-cards">
      ${tradeSideCardHtml("side_a", rec.side_a, state.tradeTeamA?.team_name, aTouched, 80)}
      ${tradeSideCardHtml("side_b", rec.side_b, state.tradeTeamB?.team_name, bTouched, 200)}
    </div>`;
  }

  html += `<div class="trade-players-compare">
    <div class="section-label">Side A gives</div>
    ${data.side_a.players.map((p, i) => tradePlayerCardHtml(p, 340 + i * 60)).join("")}
    <div class="section-label">Side B gives</div>
    ${data.side_b.players.map((p, i) => tradePlayerCardHtml(p, 340 + i * 60)).join("")}
  </div></div>`;

  results.innerHTML = html;
  wireTradeVerdict(results);

  // Kick off the count-up + bar-fill animations now that the nodes exist.
  results.querySelectorAll(".thv-num[data-target]").forEach((node) => countUp(node, Number(node.dataset.target)));
  results.querySelectorAll(".tvc-net-num[data-target]").forEach((node) => countUp(node, Number(node.dataset.target), { signed: true }));
  requestAnimationFrame(() => {
    results.querySelectorAll(".need-bar-fill[data-pct]").forEach((node) => { node.style.width = node.dataset.pct + "%"; });
  });
}

async function runTrade() {
  const body = {
    side_a: state.tradeA.map((p) => p.player_id),
    side_b: state.tradeB.map((p) => p.player_id),
    scoring: scoringDict(),
    opponent_roster_id: state.tradeOpponentRosterId,
  };
  const results = $("#trade-results");
  results.innerHTML = `<div class="trade-analyzing"><div class="trade-scan-bar"></div><span>Analyzing trade — value, then roster fit…</span></div>`;
  try {
    const data = await api("/api/trade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    renderTradeAnalysis(data);
  } catch (e) {
    results.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// Split-screen roster builder: your own roster (fixed) on one side, any
// other team in the league (switchable) on the other — click a player on
// either side to add them to that side's trade package.
function tradeRosterRowHtml(p, selected) {
  return `<div class="trade-roster-row kbd-click${selected ? " selected" : ""}" data-pid="${esc(p.player_id)}" role="button" tabindex="0" aria-pressed="${selected}">
    <img ${headshotAttrs(p)} alt="">
    <div>
      <div class="name">${esc(p.player_display_name)}${statusFlagsHtml(p)}</div>
      <div class="meta">${esc(p.position)} · ${esc(p.recent_team)}</div>
    </div>
    <span class="proj-num">${FMT.d1(p.PROJ)}</span>
    <span class="check">${selected ? "✓" : ""}</span>
  </div>`;
}

function renderTradeRosterList(containerSel, players, side) {
  const listKey = side === "a" ? "tradeA" : "tradeB";
  const container = $(containerSel);
  if (!players.length) { container.innerHTML = `<div class="empty">No players found on this roster.</div>`; return; }
  container.innerHTML = players.map((p) => tradeRosterRowHtml(p, state[listKey].some((x) => x.player_id === p.player_id))).join("");
  container.querySelectorAll(".trade-roster-row").forEach((row) => {
    row.addEventListener("click", () => {
      const pid = row.dataset.pid;
      const p = players.find((x) => x.player_id === pid);
      const already = state[listKey].some((x) => x.player_id === pid);
      if (already) {
        state[listKey] = state[listKey].filter((x) => x.player_id !== pid);
      } else {
        state[listKey].push(p);
      }
      row.classList.toggle("selected");
      row.setAttribute("aria-pressed", String(row.classList.contains("selected")));
      row.querySelector(".check").textContent = row.classList.contains("selected") ? "✓" : "";
      renderTradeChips(side);
    });
  });
}

async function loadTradeSide(side, rosterId) {
  const containerSel = side === "a" ? "#trade-a-roster" : "#trade-b-roster";
  $(containerSel).innerHTML = `<div class="loading">Loading roster…</div>`;
  try {
    const data = await api(`/api/trade/roster?roster_id=${rosterId}`);
    renderTradeRosterList(containerSel, data.players, side);
    const teamInfo = { team_name: data.team_name, avatar_url: data.avatar_url };
    if (side === "a") state.tradeTeamA = teamInfo;
    else { state.tradeTeamB = teamInfo; state.tradeOpponentRosterId = rosterId; }
  } catch (e) {
    $(containerSel).innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function loadTradeAnalyzer() {
  const gate = $("#trade-analyzer-gate");
  const body = $("#trade-analyzer-body");
  if (!state.user || !activeTeam()) {
    gate.style.display = "";
    body.style.display = "none";
    return;
  }
  gate.style.display = "none";
  body.style.display = "";

  try {
    const teamsData = await api("/api/trade/teams");
    const select = $("#trade-opponent-select");
    select.innerHTML = teamsData.teams
      .filter((t) => t.roster_id !== teamsData.my_roster_id)
      .map((t) => `<option value="${esc(t.roster_id)}">${esc(t.team_name)}</option>`).join("");

    await loadTradeSide("a", teamsData.my_roster_id);
    if (select.options.length) {
      await loadTradeSide("b", select.value);
    } else {
      $("#trade-b-roster").innerHTML = `<div class="empty">No other teams found in this league.</div>`;
    }
    select.onchange = () => {
      // a different opponent's roster makes the old selections from the
      // PREVIOUS opponent meaningless as "the trade with this team" — your
      // own side stays put, only side B clears
      state.tradeB = [];
      renderTradeChips("b");
      loadTradeSide("b", select.value);
    };
  } catch (e) {
    $("#trade-a-roster").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    $("#trade-b-roster").innerHTML = "";
  }
}

function initTrade() {
  $("#trade-analyze").addEventListener("click", runTrade);
  $("#trade-analyzer-gate-btn")?.addEventListener("click", () => switchTab("settings"));
}

// ------------------------------------------------------------- waivers ----
// Two tracks from /api/waivers/engine: Smart Match (free agents scored
// against your roster, each paired with the drop it implies) and discovery
// (Sleeper add/drop velocity, handcuffs, a usage deep dive).
let wvTimer = null;

const WV_PARTS = [["urgency", "Need"], ["vorp", "VORP"], ["usage", "Usage"], ["schedule", "Schedule"]];
const WV_BADGE = {
  trap: ["wv-trap", "Waiver trap"],
  breakout: ["wv-breakout", "Breakout signal"],
};

function wvBadgeHtml(p) {
  if (!p.badge) return "";
  const [cls, label] = WV_BADGE[p.badge];
  return `<span class="wv-badge ${cls}" title="${esc(p.badge_reason || "")}">${label}</span>`;
}

function wvPlayer(p) {
  return { ...p, player_display_name: p.name, recent_team: p.team };
}

function wvSigned(v, dec = 1) {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${Number(v).toFixed(dec)}`;
}

function wvCount(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
}

function wvStatusHtml(st, week) {
  if (!st) {
    return `<div class="wv-stat"><span class="wv-k">Waivers for</span><span class="wv-v">Week ${esc(week)}</span></div>
      <div class="wv-stat wv-stat-wide"><span class="wv-k">Your league</span><span class="wv-v small">Sign in and connect a Sleeper league in Settings to see your FAAB, waiver order and picks matched to your roster.</span></div>`;
  }
  const faab = st.is_faab
    ? `<div class="wv-stat"><span class="wv-k">FAAB left</span><span class="wv-v">$${fmtTotal(st.faab_remaining)}<span class="wv-sub">${fmtTotal(st.faab_remaining_pct, 0)}% of $${fmtTotal(st.faab_budget)}</span></span></div>`
    : `<div class="wv-stat"><span class="wv-k">Format</span><span class="wv-v">${esc(st.waiver_type)}<span class="wv-sub">No FAAB budget</span></span></div>`;
  const prio = st.priority != null
    ? `<div class="wv-stat"><span class="wv-k">Waiver priority</span><span class="wv-v">#${esc(st.priority)}<span class="wv-sub">of ${esc(st.teams)} teams</span></span></div>` : "";
  const run = st.next_run
    ? `<div class="wv-stat"><span class="wv-k">Next run</span><span class="wv-v"><span class="wv-live" id="wv-countdown" data-at="${esc(st.next_run)}"></span><span class="wv-sub">${esc(st.next_run_label)}</span></span></div>` : "";
  return `${faab}${prio}${run}<div class="wv-stat"><span class="wv-k">Waivers for</span><span class="wv-v">Week ${esc(week)}<span class="wv-sub">Byes and injuries checked 3 weeks out</span></span></div>`;
}

function wvTick() {
  const elc = document.getElementById("wv-countdown");
  if (!elc) { clearInterval(wvTimer); wvTimer = null; return; }
  const ms = new Date(elc.dataset.at) - new Date();
  if (ms <= 0) { elc.textContent = "Processing"; return; }
  const d = Math.floor(ms / 864e5), h = Math.floor(ms / 36e5) % 24, m = Math.floor(ms / 6e4) % 60;
  elc.textContent = d ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}

function wvNeedsHtml(needs) {
  if (!needs) return "";
  const hot = Object.entries(needs).filter(([, n]) => n.multiplier > 1).sort((a, b) => b[1].multiplier - a[1].multiplier);
  if (!hot.length) return `<div class="wv-need-none">No urgent holes for the next 3 weeks, so these are pure upgrades.</div>`;
  return hot.map(([pos, n]) => `<div class="wv-need ${n.multiplier >= 1.4 ? "hot" : ""}" title="${esc(n.multiplier.toFixed(2))}x need">
      <b>${esc(pos)} need</b><span>${n.reasons.map(esc).join(" · ")}</span>
    </div>`).join("");
}

function wvBidsHtml(bids) {
  if (!bids) return "";
  return `<div class="wv-bids">${bids.map((b) => `<div class="wv-bid${b.recommended ? " rec" : ""}" title="${esc(b.why)}">
      <span class="wv-bid-l">${esc(b.label)}${b.recommended ? " ✓" : ""}</span>
      <span class="wv-bid-v">$${b.dollars[0]}–$${b.dollars[1]}</span>
      <span>${b.pct[0]}–${b.pct[1]}% of budget</span>
      ${b.rivals ? `<span class="muted">${esc(b.rivals_can_cover)} of ${esc(b.rivals)} rivals can cover the top bid</span>` : ""}
    </div>`).join("")}</div>`;
}

function wvSmartCardHtml(s, i) {
  const parts = WV_PARTS.map(([k, label]) => {
    const v = Math.round(s.wps_parts[k]);
    return `<span class="wv-part"><em>${label}<b>${v}</b></em><s><i style="width:${v}%"></i></s></span>`;
  }).join("");
  const drop = s.drop
    ? `<span class="wv-chip-drop"><i>−</i>${esc(s.drop.name)} <span class="muted">${esc(s.drop.position)} · ${FMT.d1(s.drop.ros)}/wk</span></span>`
    : `<span class="wv-chip-drop"><i>○</i><span class="muted">Open roster spot</span></span>`;
  const why = s.need_reasons && s.need_reasons.length ? `<div class="wv-why">${esc(s.need_reasons[0])}</div>` : "";
  const g = s.gain_ros;
  return `<div class="wv-card" data-i="${i}">
    <span class="wv-rank">#${i + 1}</span>
    <div class="wv-card-top">
      <img ${headshotAttrs(wvPlayer(s))} alt="">
      <div class="wv-card-id">
        <div class="wv-name kbd-click" data-pid="${esc(s.player_id)}" role="button" tabindex="0">${esc(s.name)}${statusFlagsHtml(s)}</div>
        <div class="wv-meta"><span class="pos-chip pos-${esc(s.position)}">${esc(s.position)}</span>${esc(s.team)} · next 4 <span class="wv-grade g-${esc(s.schedule.grade.toLowerCase())}">${esc(s.schedule.grade)}</span>${wvBadgeHtml(s)}</div>
      </div>
      <div class="wv-ring" style="--p:${Math.round(s.wps)}" title="Waiver Priority Score: 35% need + 30% value over replacement (VORP) + 25% usage + 10% schedule"><b>${Math.round(s.wps)}</b><span>WPS</span></div>
    </div>
    <div class="wv-gain">
      <span class="wv-gain-n ${g >= 0 ? "pos" : "neg"}">${wvSigned(g)}<small>/wk</small></span>
      <span class="wv-gain-t">to your starting lineup<br><b>${wvSigned(s.gain_next3)}</b> over the next 3 weeks</span>
    </div>
    <div class="wv-swaprow"><span class="wv-k">Drop</span>${drop}</div>
    ${why}
    <div class="wv-parts">${parts}</div>
    ${wvBidsHtml(s.bids)}
    <div class="wv-card-foot"><button class="wv-compare" data-i="${i}">Compare the swap →</button></div>
  </div>`;
}

function wvPlayerCellHtml(p, extras) {
  const isTop = p.rank === 1;
  const q = wvPlayer(p);
  return `<div class="player-cell wv-pcell${isTop ? " player-cell-top" : ""}">
      <img ${headshotAttrs(q)} alt="">
      <div><div class="player-name">${isTop ? '<span class="top-crown" title="Top of this list">👑</span>' : ""}${esc(p.name)}${statusFlagsHtml(p)}${extras || ""}</div>
      <div class="player-team">${esc(p.team || "")} · <span class="pos-chip pos-${esc(p.position)}">${esc(p.position)}</span></div></div>
    </div>`;
}

function wvMoversHtml(movers, hasLeague) {
  if (!movers.length) return `<div class="empty">Sleeper's trending feed is unavailable right now.</div>`;
  const rows = movers.map((m) => {
    const vel = m.velocity == null ? `<span class="wv-velo hot">new today</span>`
      : m.velocity >= 1.5 ? `<span class="wv-velo hot">${m.velocity}x yesterday</span>`
      : m.velocity < 0.8 ? `<span class="wv-velo cool">${m.velocity}x yesterday</span>` : `<span class="wv-velo">${m.velocity}x yesterday</span>`;
    const avail = m.available == null ? "" : m.available ? `<span class="wv-chip ok">Available</span>` : `<span class="wv-chip">Rostered</span>`;
    return `<tr data-pid="${esc(m.player_id)}" tabindex="0" class="kbd-click">
      <td>${wvPlayerCellHtml(m, wvBadgeHtml(m))}</td>
      <td class="tabular"><span class="wv-net">${m.net_24h >= 0 ? "+" : "−"}${wvCount(Math.abs(m.net_24h))}</span></td>
      <td class="tabular muted">+${wvCount(m.adds_24h)} / ${m.drops_24h == null ? "—" : "−" + wvCount(m.drops_24h)}</td>
      <td>${vel}</td><td>${avail}</td></tr>`;
  }).join("");
  return `<div class="hint">Sleeper-wide adds minus drops in the last 24 hours, and today's adds vs the day before. "—" = too few drops to make Sleeper's top-200 list.${hasLeague ? "" : " Connect a league to see who's available in yours."}</div>
    <div class="board-wrap"><table class="wv-table"><thead><tr><th>Player</th><th>Net 24h</th><th>Adds / drops</th><th>Pace</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function wvCuffsHtml(cuffs, hasLeague) {
  if (!cuffs.length) return `<div class="empty">No depth chart data right now.</div>`;
  const rows = cuffs.map((c) => `<tr data-pid="${esc(c.backup_id)}" tabindex="0" class="kbd-click">
      <td><span class="player-name">${esc(c.backup)}</span> <span class="muted small">${esc(c.team)} RB2</span></td>
      <td>${esc(c.starter)}${c.starter_status ? ` <span class="wv-chip warn">${esc(c.starter_status)}</span>` : ""}</td>
      <td class="tabular"><b>${FMT.d1(c.index)}</b> <span class="muted small">pts/wk</span></td>
      <td class="tabular">${c.backup_snap_pct == null ? "—" : fmtTotal(c.backup_snap_pct, 0) + "%"}</td>
      <td>${hasLeague ? (c.available ? `<span class="wv-chip ok">Available</span>` : `<span class="wv-chip">Rostered</span>`) : ""}</td></tr>`).join("");
  return `<div class="hint">Each team's RB2 from the current depth chart, ranked by what the starter's job is worth. Backups whose starter is hurt right now come first.</div>
    <div class="board-wrap"><table class="wv-table"><thead><tr><th>Backup</th><th>Behind</th><th>Job is worth</th><th>Backup snap %</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// The original waiver list (rank, SCORE, FORM, FPTS/G, trending) with the
// usage columns behind a toggle, so the default view stays a quick scan.
const WV_SIMPLE = [["rank", "#"], ["name", "Player"], ["SCORE", "PVS"], ["FORM", "FORM"], ["fpts_pg", "FPTS/G"], ["ros", "ROS pts/wk"]];
const WV_ADV = [["rank", "#"], ["name", "Player"], ["SCORE", "PVS"], ["ros", "ROS pts/wk"], ["snap_pct", "Snap %"],
  ["target_share", "Target %"], ["xfp_pg", "xFP/G"], ["xfp_diff", "Pts vs xFP"], ["hvt_pg", "HVT/G"], ["wopr", "WOPR"], ["sched", "Next 4"]];
const WV_TIPS = {
  SCORE: "Player Value Score, 0-100: how much more he gives a lineup than a freely available replacement at his position. Same number as the Big Board.",
  ros: "Projected fantasy points per week for the rest of the season.",
  snap_pct: "Share of his team's offensive snaps in his most recent game.",
  xfp_pg: "Expected fantasy points per game: what an average player would score on his targets and carries, given their depth and field position (our model, this season's play-by-play).",
  xfp_diff: "Actual points per game minus xFP. Very negative = getting the work but not the points yet (buy low). Very positive = scoring beyond his volume (may cool off).",
  hvt_pg: "High-value touches per game (RBs): red-zone carries plus targets.",
  wopr: "Weighted opportunity rating: 1.5 × target share + 0.7 × air-yards share.",
  sched: "Grade of his next 4 matchups for his position (A = easiest).",
};

function wvTrendHtml(p) {
  return p.trending_adds > 0
    ? `<span class="trend-badge" title="${esc(p.trending_adds)} adds on Sleeper, last 48h">🔥 ${wvCount(p.trending_adds)}</span>` : "";
}

function wvDeepRender() {
  const d = state.wvData;
  if (!d) return;
  const pos = document.querySelector("#waivers-pos-pills .pill.active")?.textContent || "All";
  const adv = $("#wv-advanced")?.checked;
  const cols = adv ? WV_ADV : WV_SIMPLE;
  const sort = state.wvSort || { key: "SCORE", dir: -1 };
  let rows = d.deep_dive.filter((p) => pos === "All" || p.position === pos)
    .slice().sort((a, b) => (b.SCORE ?? -1) - (a.SCORE ?? -1))
    .map((p, i) => ({ ...p, rank: i + 1 }));
  const val = (p, k) => (k === "sched" ? p.schedule.score : k === "name" ? p.name : p[k]);
  if (sort.key !== "SCORE" && sort.key !== "rank") {
    rows = rows.sort((a, b) => {
      const x = val(a, sort.key), y = val(b, sort.key);
      if (x == null) return 1;
      if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * sort.dir;
    });
  } else if (sort.dir === 1) rows.reverse();
  $("#wv-head").innerHTML = cols.map(([k, label]) => `<th data-k="${k}" class="${k === sort.key ? `sorted${sort.dir === 1 ? " asc" : ""}` : ""}" ${WV_TIPS[k] ? `title="${esc(WV_TIPS[k])}"` : ""}>${label}${WV_TIPS[k] && adv ? " ⓘ" : ""}</th>`).join("");
  const n = (v, dec = 1, suf = "") => (v == null ? `<span class="muted">—</span>` : `${Number(v).toFixed(dec)}${suf}`);
  const cell = (p, k) => {
    switch (k) {
      case "rank": return `<td class="rank-cell">${p.rank}</td>`;
      case "name": return `<td>${wvPlayerCellHtml(p, wvTrendHtml(p) + wvBadgeHtml(p))}</td>`;
      case "SCORE": return `<td>${p.SCORE == null ? "—" : scoreCell(p.SCORE)}</td>`;
      case "FORM": return `<td>${formCell(p.FORM)}</td>`;
      case "fpts_pg": return `<td class="tabular">${n(p.fpts_pg)}</td>`;
      case "ros": return `<td class="tabular"><b>${n(p.ros)}</b></td>`;
      case "snap_pct": return `<td class="tabular">${n(p.snap_pct, 0, "%")}</td>`;
      case "target_share": return `<td class="tabular">${n(p.target_share, 1, "%")}</td>`;
      case "xfp_pg": return `<td class="tabular">${n(p.xfp_pg)}</td>`;
      case "xfp_diff": return `<td class="tabular ${p.xfp_diff == null ? "" : p.xfp_diff <= -3 ? "pos" : p.xfp_diff >= 3 ? "neg" : ""}">${p.xfp_diff == null ? n(null) : wvSigned(p.xfp_diff)}</td>`;
      case "hvt_pg": return `<td class="tabular">${n(p.hvt_pg)}</td>`;
      case "wopr": return `<td class="tabular">${n(p.wopr, 2)}</td>`;
      case "sched": return `<td><span class="wv-grade g-${esc(p.schedule.grade.toLowerCase())}">${esc(p.schedule.grade)}</span></td>`;
      default: return "<td></td>";
    }
  };
  const total = rows.length;
  if (!state.wvListAll) rows = rows.slice(0, 25);
  const more = $("#wv-list-more");
  more.style.display = total > 25 ? "" : "none";
  more.textContent = state.wvListAll ? "Show top 25" : `Show all ${total} players`;
  $("#waivers-body").innerHTML = rows.map((p) => `<tr data-pid="${esc(p.player_id)}" tabindex="0" class="kbd-click${p.rank === 1 ? " board-row-top" : ""}">${cols.map(([k]) => cell(p, k)).join("")}</tr>`).join("")
    || `<tr><td colspan="${cols.length}" class="empty">No available players at this position.</td></tr>`;
  wvWireRows($("#waivers-body"));
  animateScoreBars();
}

function wvSwapModal(s) {
  const sw = s.swap;
  const a = sw.add, d = sw.drop;
  const rows = [
    ["Rest-of-season pts/wk", "ros", 1, ""], ["Snap share", "snap_pct", 0, "%"], ["Target share", "target_share", 1, "%"],
    ["Goal-line share", "goal_line_share", 0, "%"], ["xFP per game", "xfp_pg", 1, ""],
    ["Next 4 schedule", "schedule_score", 0, ""], ["Floor (bad week)", "floor", 1, ""], ["Ceiling (big week)", "ceiling", 1, ""],
  ].map(([label, k, dec, suf]) => {
    const x = a?.[k], y = d?.[k];
    const max = Math.max(1, Math.abs(x || 0), Math.abs(y || 0));
    const win = x != null && y != null ? (x > y ? "a" : y > x ? "b" : "") : "";
    const fmt = (v, side) => (v == null ? "—" : k === "schedule_score" ? `${side.schedule_grade} grade` : `${Number(v).toFixed(dec)}${suf}`);
    return `<div class="sw-row">
      <div class="sw-side a ${win === "a" ? "win" : ""}"><span>${fmt(x, a)}</span><i style="width:${x == null ? 0 : (Math.abs(x) / max) * 100}%"></i></div>
      <div class="sw-label">${label}</div>
      <div class="sw-side b ${win === "b" ? "win" : ""}"><i style="width:${y == null ? 0 : (Math.abs(y) / max) * 100}%"></i><span>${fmt(y, d)}</span></div>
    </div>`;
  }).join("");
  const band = (k, label) => `<div class="sw-band"><span class="wv-k">${label}</span><b>${FMT.d1(sw.before[k])} → ${FMT.d1(sw.after[k])}</b><span class="${sw.after[k] - sw.before[k] >= 0 ? "pos" : "neg"}">${wvSigned(sw.after[k] - sw.before[k])}</span></div>`;
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal wv-swap">
    <div class="modal-header"><div><h2>Swap check</h2><div class="muted">Add ${esc(s.name)}${d ? `, drop ${esc(d.name)}` : " into your open spot"}</div></div><button class="modal-close" aria-label="Close">✕</button></div>
    <div class="sw-head"><span class="a">Add: ${esc(a?.name || s.name)}</span><span></span><span class="b">${d ? `Drop: ${esc(d.name)}` : "Open spot"}</span></div>
    ${d ? rows : `<div class="muted">You have an open roster spot, so nobody leaves.</div>`}
    <div class="section-label">Your starting lineup, per week</div>
    <div class="sw-bands">${band("proj", "Projected")}${band("floor", "Floor")}${band("ceiling", "Ceiling")}</div>
    <div class="hint">Starters are picked by rest-of-season projection. Floor and ceiling add up each starter's bad-week and big-week numbers. Playoff odds aren't shown; that needs a full season simulation we don't run yet.</div>
  </div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => { if (e.target.classList.contains("modal-backdrop")) closeModal(); });
  root.querySelector(".modal-close").addEventListener("click", closeModal);
}

function wvWireRows(container) {
  container.querySelectorAll("tr[data-pid], .wv-name[data-pid]").forEach((r) =>
    r.addEventListener("click", () => openPlayerModal(r.dataset.pid)));
}

function wvSmartRender() {
  const d = state.wvData;
  const more = $("#wv-smart-more");
  more.style.display = "none";
  if (!d.has_league) {
    $("#wv-smart").innerHTML = `<div class="empty">Connect your Sleeper or ESPN league in Settings to get free agents scored against your roster, with the player to drop.</div>`;
    return;
  }
  if (!d.smart_match.length) {
    $("#wv-smart").innerHTML = `<div class="empty">No free agent improves your starting lineup right now.</div>`;
    return;
  }
  const shown = state.wvShowAll ? d.smart_match : d.smart_match.slice(0, 3);
  $("#wv-smart").innerHTML = shown.map(wvSmartCardHtml).join("");
  $("#wv-smart").querySelectorAll(".wv-compare").forEach((b) =>
    b.addEventListener("click", () => wvSwapModal(d.smart_match[Number(b.dataset.i)])));
  wvWireRows($("#wv-smart"));
  if (d.smart_match.length > 3) {
    more.style.display = "";
    more.textContent = state.wvShowAll ? "Show top 3 only" : `Show all ${d.smart_match.length} picks`;
  }
}

async function loadWaivers(pos) {
  // A position pill only re-filters the table already on screen.
  if (pos && state.wvData) {
    wvDeepRender();
    return;
  }
  const body = $("#waivers-body");
  body.innerHTML = `<tr><td colspan="6">${skeletonRows(8, 2)}</td></tr>`;
  $("#wv-smart").innerHTML = `<div class="loading">Scoring free agents against your roster…</div>`;
  try {
    const d = await api(`/api/waivers/engine?${scoringQS().replace(/^&/, "")}`);
    state.wvData = d;
    $("#wv-status").innerHTML = wvStatusHtml(d.league, d.week);
    if (!wvTimer && d.league?.next_run) wvTimer = setInterval(wvTick, 30000);
    wvTick();
    $("#wv-note").textContent = d.note || "";
    $("#wv-needs").innerHTML = wvNeedsHtml(d.needs);
    state.wvShowAll = false;
    wvSmartRender();
    $("#wv-movers").innerHTML = wvMoversHtml(d.market_movers, d.has_league);
    $("#wv-cuffs").innerHTML = wvCuffsHtml(d.handcuffs, d.has_league);
    $("#wv-gaps").textContent = `Not shown: ${d.not_available.join("; ")}. xFP is our own model and FAAB bids are our suggestion, not a market consensus.`;
    $("#waivers-hint").textContent = d.has_league
      ? "Ranked by PVS, excluding everyone rostered in your league. 🔥 = adds on Sleeper in the last 48h."
      : "Ranked by PVS. Connect your Sleeper or ESPN league in Settings to hide players who are already rostered.";
    wvDeepRender();
    ["#wv-movers", "#wv-cuffs"].forEach((sel) => wvWireRows($(sel)));
  } catch (e) {
    $("#wv-smart").innerHTML = "";
    body.innerHTML = `<tr><td colspan="6" class="empty">${esc(e.message)}</td></tr>`;
  }
}

function initWaiverControls() {
  document.querySelectorAll(".wv-tab").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll(".wv-tab").forEach((x) => x.classList.toggle("active", x === t));
    $("#wv-movers").style.display = t.dataset.wv === "movers" ? "" : "none";
    $("#wv-cuffs").style.display = t.dataset.wv === "cuffs" ? "" : "none";
  }));
  $("#wv-advanced").addEventListener("change", () => {
    try { localStorage.setItem("wvAdvanced", $("#wv-advanced").checked ? "1" : ""); } catch (e) { /* storage off */ }
    wvDeepRender();
  });
  try { $("#wv-advanced").checked = localStorage.getItem("wvAdvanced") === "1"; } catch (e) { /* storage off */ }
  $("#wv-list-more").addEventListener("click", () => {
    state.wvListAll = !state.wvListAll;
    wvDeepRender();
  });
  $("#wv-smart-more").addEventListener("click", () => {
    state.wvShowAll = !state.wvShowAll;
    wvSmartRender();
  });
  $("#wv-head").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-k]");
    if (!th) return;
    const cur = state.wvSort || { key: "SCORE", dir: -1 };
    state.wvSort = { key: th.dataset.k, dir: cur.key === th.dataset.k ? -cur.dir : th.dataset.k === "name" ? 1 : -1 };
    wvDeepRender();
  });
}

// ------------------------------------------------------ section header ----
// The one section-header pattern every tab uses (icon tile + h2 + a line of
// description), first designed for Waivers. Static headers live in
// index.html with the same markup; this builds the ones rendered from JS.
const SEC_ICONS = {
  matchups: '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="1.4" fill="currentColor"/><circle cx="16" cy="12" r="1.4" fill="currentColor"/><circle cx="10" cy="18" r="1.4" fill="currentColor"/>',
  lineup: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  trades: '<path d="M13 3l3 3-3 3M16 6H4M11 21l-3-3 3-3M8 18h12"/>',
};
function secHeadHtml(icon, title, sub, right) {
  return `<div class="sec-head">
    <span class="sec-head-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${SEC_ICONS[icon] || ""}</svg></span>
    <div><h2>${title}</h2>${sub ? `<p>${sub}</p>` : ""}</div>${right ? `<div class="sec-head-right">${right}</div>` : ""}
  </div>`;
}

// ------------------------------------------------------------- my team ----
// Real starting lineup (real slot labels — QB/RB/RB/WR/WR/TE/FLEX/FLEX/
// DEF/K, whatever this league actually runs) first, bench after — a bench
// player isn't scoring this week, so its projection is muted and excluded
// from the team total (see engine/tools.py _roster_players).
function rosterRowHtml(p, isBench) {
  // DEF/K have no SCORE — this app's stat engine only covers QB/RB/WR/TE
  // (see README) — so there's no player-detail view to open for them.
  const unscored = p.SCORE == null;
  return `<div class="myteam-roster-row${isBench ? " bench" : ""}${unscored ? " unscored" : " kbd-click"}" data-pid="${esc(p.player_id)}" ${unscored ? 'data-unscored="1"' : 'role="button" tabindex="0"'}>
    <img ${headshotAttrs(p)} alt="">
    <span class="pos-badge">${esc(p.slot || p.position)}</span>
    <span>${esc(p.player_display_name)}${p.recent_team ? ` <span class="mt-team" data-team-page="${esc(p.recent_team)}" role="link" tabindex="0" title="Open the ${esc(p.recent_team)} team page">${esc(p.recent_team)}</span>` : ""}${statusFlagsHtml(p)}${p.on_bye ? ' <span class="bye-tag" title="Team is on a bye this week">BYE</span>' : ""}</span>
    <span class="proj-num tabular">${FMT.d1(p.PROJ)}${p.floor != null && p.ceiling != null ? `<small class="proj-range" title="Typical range (10th to 90th percentile)${p.p_play != null ? `; ${Math.round(p.p_play * 100)}% chance to play` : ""}">${FMT.int(p.floor)}–${FMT.int(p.ceiling)}${p.p_play != null ? ` · ${Math.round(p.p_play * 100)}% to play` : ""}</small>` : ""}</span>
  </div>`;
}

function teamCardHtml(team, kind) {
  const starters = team.players.filter((p) => p.is_starter);
  const bench = team.players.filter((p) => !p.is_starter);
  const rows = `
    ${starters.map((p) => rosterRowHtml(p, false)).join("")}
    ${bench.length ? `<div class="section-label">Bench <span class="hint-inline">— doesn't count this week</span></div>` : ""}
    ${bench.map((p) => rosterRowHtml(p, true)).join("")}
  `;
  const avatar = team.avatar_url
    ? `<img class="mt-avatar" src="${proxyImg(team.avatar_url)}" data-fb-emoji="🏈" alt="">`
    : `<span class="team-emoji">🏈</span>`;
  return `<div class="myteam-card${kind === "opponent" ? " opponent" : ""}">
      <div class="mt-label">${kind === "mine" ? "MY TEAM" : "OPPONENT"}</div>
      <div class="mt-name-row">${avatar}<div class="mt-name">${esc(team.team_name)}</div></div>
      <div class="mt-total-lbl">${esc(teamTotalLabel(team))}</div>
      <div class="mt-total tabular">${FMT.d1(team.total_proj)}</div>
      <div style="margin-top:14px">${rows}</div>
    </div>`;
}

// "Projected" until his games are played. Rows the server settled with real
// scores carry final:true, so a finished week reads FINAL and a part-played
// one says it mixes the two.
function teamTotalLabel(team) {
  const starters = (team.players || []).filter((p) => p.is_starter);
  const done = starters.filter((p) => p.final).length;
  if (!starters.length || !done) return "PROJECTED (STARTERS)";
  return done === starters.length ? "FINAL (STARTERS)" : "ACTUAL + PROJECTED (STARTERS)";
}

// A big center "VS" badge between the two team cards, plus who's favored —
// the head-to-head feel of a real matchup page, not just two cards side by side.
function matchupSettled(mine, opp) {
  return [mine, opp].every((t) => teamTotalLabel(t) === "FINAL (STARTERS)");
}

function matchupCenterHtml(mine, opp) {
  if (!opp) return `<div class="matchup-vs-center"><div class="matchup-vs-badge">VS</div></div>`;
  const diff = (mine.total_proj || 0) - (opp.total_proj || 0);
  const favoredName = diff >= 0 ? mine.team_name : opp.team_name;
  // Green only when YOU are projected ahead; an opponent edge is shown
  // plainly (it's not "good"), never in the app's success color.
  const favor = Math.abs(diff) < 0.1
    ? `<span style="color:var(--muted)">Dead even</span>`
    : `<span class="matchup-favor-lbl">${matchupSettled(mine, opp) ? "Final margin" : "Projected edge"}</span><span class="${diff >= 0 ? "" : "is-opp"}">${esc(favoredName)} +${FMT.d1(Math.abs(diff))}</span>`;
  return `<div class="matchup-vs-center">
    <div class="matchup-vs-badge">VS</div>
    <div class="matchup-favor">${favor}</div>
  </div>`;
}

// Split bar showing each side's share of the combined projected total —
// a quick "who's ahead, by how much" read at a glance.
function matchupBarHtml(mine, opp) {
  const mv = Math.max(mine.total_proj || 0, 0), ov = Math.max(opp.total_proj || 0, 0);
  const sum = mv + ov;
  const minePct = sum > 0 ? (mv / sum) * 100 : 50;
  return `<div class="matchup-bar-wrap">
    <div class="matchup-bar-labels"><span class="mine">${esc(mine.team_name)} · ${minePct.toFixed(0)}%</span><span class="matchup-bar-cap">share of combined projected points</span><span>${(100 - minePct).toFixed(0)}% · ${esc(opp.team_name)}</span></div>
    <div class="matchup-bar" role="img" aria-label="${esc(mine.team_name)} ${minePct.toFixed(0)} percent of combined projected points">
      <div class="matchup-bar-fill mine" style="width:${minePct.toFixed(1)}%"></div>
      <div class="matchup-bar-fill theirs" style="width:${(100 - minePct).toFixed(1)}%"></div>
    </div>
  </div>`;
}

function leagueMatchupsHtml(matchups, myRosterId) {
  if (!matchups || !matchups.length) return "";
  const rows = matchups.map((m) => {
    const sides = m.teams.map((t) => `
      <div class="lm-side${t.roster_id === myRosterId ? " me" : ""}">
        ${t.avatar_url ? `<img src="${proxyImg(t.avatar_url)}" data-fb-hide="1" alt="">` : ""}
        <span class="lm-name">${esc(t.team_name)}</span>
        <span class="lm-proj">${FMT.d1(t.total_proj)}</span>
      </div>`).join(`<span class="lm-vs">vs</span>`);
    return `<div class="lm-row">${sides}</div>`;
  }).join("");
  return `${secHeadHtml("matchups", "League matchups this week", "Every head-to-head in your league, projected from each team's starters.")}<div class="league-matchups">${rows}</div>`;
}

function renderMyTeamWeekSelector(data) {
  const total = data.regular_season_weeks || 14;
  const select = $("#myteam-week-select");
  select.innerHTML = Array.from({ length: total }, (_, i) => i + 1)
    .map((w) => `<option value="${w}" ${w === data.nfl_week ? "selected" : ""}>Week ${w}</option>`).join("");
  select.onchange = () => loadMyTeam(parseInt(select.value, 10));

  const prev = $("#myteam-week-prev"), next = $("#myteam-week-next");
  prev.disabled = data.nfl_week <= 1;
  prev.onclick = () => loadMyTeam(data.nfl_week - 1);
  next.disabled = data.nfl_week >= total;
  next.onclick = () => loadMyTeam(data.nfl_week + 1);

  const liveBtn = $("#myteam-week-live");
  const onLiveWeek = data.live_week && data.live_week === data.nfl_week;
  if (data.live_week && !onLiveWeek && data.live_week <= total) {
    liveBtn.style.display = "";
    liveBtn.onclick = () => loadMyTeam(data.live_week);
  } else {
    liveBtn.style.display = "none";
  }
  $("#myteam-week-controls").style.display = "flex";
}

async function loadMyTeam(week) {
  const gate = $("#myteam-gate");
  const content = $("#myteam-content");
  gate.style.display = "none";
  content.style.display = "none";
  $("#myteam-week-controls").style.display = "none";

  if (!state.user) {
    gate.style.display = "";
    gate.querySelector(".gate-sub").textContent = "Sign in, then connect Sleeper and pick your roster in Settings.";
    return;
  }

  content.innerHTML = `<div class="loading">Loading your team…</div>`;
  content.style.display = "";
  try {
    const weekQS = week ? `&week=${week}` : "";
    const data = await api(`/api/myteam?${(scoringQS() + weekQS).replace(/^&/, "")}`);
    renderMyTeamWeekSelector(data);
    state.notifications = computeInjuryNotifications(data.my_team);
    state.myTeamAbbrs = rosterTeamCounts(data.my_team);
    markLiveScoreCards();
    renderNotifBell();
    const onLiveWeek = data.live_week && data.live_week === data.nfl_week;
    let html = `<div class="hint">Week ${esc(data.nfl_week)}${onLiveWeek ? " · in progress" : ""} · ${esc(data.league_name)}</div>`;
    html += `<div class="myteam-summary">
      ${teamCardHtml(data.my_team, "mine")}
      ${matchupCenterHtml(data.my_team, data.opponent)}
      ${data.opponent ? teamCardHtml(data.opponent, "opponent")
        : `<div class="myteam-card opponent"><div class="mt-label">OPPONENT</div><div class="mt-name muted">No head-to-head matchup set for week ${esc(data.nfl_week)} yet.</div></div>`}
    </div>`;
    if (data.opponent) html += matchupBarHtml(data.my_team, data.opponent);
    html += leagueMatchupsHtml(data.league_matchups, data.my_team.roster_id);
    html += `<div id="trades-panel"></div>`;
    content.innerHTML = html;
    countUpTotals(content, `${data.nfl_week}|${data.my_team.roster_id}`);
    loadTradesPanel();
    content.querySelectorAll(".myteam-roster-row:not(.unscored)").forEach((row) => {
      row.addEventListener("click", (e) => { if (!e.target.closest("[data-team-page]")) openPlayerModal(row.dataset.pid); });
    });
  } catch (e) {
    content.style.display = "none";
    gate.style.display = "";
    gate.querySelector(".gate-sub").textContent = e.message || "Connect a league in Settings first.";
  }
}

// The two team totals count up from zero the first time a week is shown; background refreshes and week-arrow
// returns to a week already seen stay still. Skipped under reduced motion.
const countedWeeks = new Set();
function countUpTotals(root, key) {
  if (prefersReducedMotion || countedWeeks.has(key)) return;
  countedWeeks.add(key);
  root.querySelectorAll(".mt-total").forEach((el) => {
    const to = parseFloat(el.textContent);
    if (!isFinite(to) || to <= 0) return;
    const t0 = performance.now(), ms = 700;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      el.textContent = (to * (1 - Math.pow(1 - k, 3))).toFixed(1);
      if (k < 1) requestAnimationFrame(tick); else el.textContent = to.toFixed(1);
    };
    requestAnimationFrame(tick);
  });
}

// ------------------------------------------------------------ league trades ----
async function loadTradesPanel() {
  const host = $("#trades-panel");
  if (!host) return;
  let seen = [];
  try { seen = JSON.parse(localStorage.getItem("seenTrades") || "[]"); } catch (e) { /* storage unavailable */ }
  try {
    const { trades } = await api(`/api/league/trades?seen=${encodeURIComponent(seen.join(","))}`);
    const head = secHeadHtml("trades", "League trades", "Every completed trade in your league, newest first.");
    if (!trades.length) { host.innerHTML = `${head}<div class="hint">No trades in your league yet.</div>`; return; }
    const side = (s) => `<div class="tr-side"><div class="tr-team">${esc(s.team)} <span class="muted small">gets</span></div>${s.receives.map((x) => `<div class="tr-item ${x.kind}">${esc(x.name)}</div>`).join("") || `<div class="muted small">nothing</div>`}</div>`;
    host.innerHTML = head +
      trades.slice(0, 10).map((t) => `<div class="tr-card${t.is_new ? " is-new" : ""}"><div class="tr-head">${t.week != null ? `Week ${esc(t.week)}` : esc(t.at ? new Date(t.at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—")}${t.is_new ? ` <span class="lk lk-open">NEW</span>` : ""}${t.status ? ` <span class="lk">${esc(t.status)}</span>` : ""}${t.votes ? ` <span class="muted small">${esc(t.votes.approved)} approve · ${esc(t.votes.vetoed)} veto</span>` : ""}</div><div class="tr-sides">${t.sides.map(side).join("")}</div></div>`).join("");
    try { localStorage.setItem("seenTrades", JSON.stringify(trades.map((t) => t.id))); } catch (e) { /* storage unavailable */ }
  } catch (e) {
    host.innerHTML = `${secHeadHtml("trades", "League trades", "")}<div class="hint">${esc(e.message)}</div>`;
  }
}

$("#myteam-gate-btn")?.addEventListener("click", () => switchTab("settings"));

// ---------------------------------------------------------------- draft ----
let draftPollHandle = null;
let draftTeamNames = {};   // roster_id -> team_name, for the active league

function stopDraftPolling() {
  if (draftPollHandle) { clearInterval(draftPollHandle); draftPollHandle = null; }
}

function needBadge(mult) {
  if (mult >= 1.2) return `<span class="need-badge need">NEED</span>`;
  if (mult <= 0.9) return `<span class="need-badge deep">DEEP</span>`;
  return "";
}

function runBadge(mult) {
  return mult > 1 ? `<span class="need-badge run" title="This position is going off the board fast (4+ of the last 8 picks)">RUN</span>` : "";
}

function renderDraftBoard(d) {
  const content = $("#draft-content");
  const onClockName = d.on_the_clock_roster_id != null ? (draftTeamNames[d.on_the_clock_roster_id] || `Roster #${d.on_the_clock_roster_id}`) : "—";
  const isMe = d.on_the_clock_roster_id === d.my_roster_id;

  let html = "";

  // A finished draft has nothing live to track — say so plainly instead of
  // showing a "COMPLETE" status bar next to best-available "advice" for
  // picks that already happened, possibly seasons ago.
  if (d.is_complete) {
    html += `<div class="draft-complete-banner">
      <span class="draft-complete-icon">🏁</span>
      <div>
        <div class="draft-complete-title">${esc(d.season || "This")} Draft — Complete</div>
        <div class="draft-complete-sub">${esc(d.total_picks)} picks across ${esc(d.rounds)} rounds, ${esc(d.teams)} teams. Nothing live to track — here's the recap.</div>
      </div>
    </div>`;
  } else {
    html += `<div class="draft-status-bar${isMe ? " on-the-clock" : ""}">
      <div class="draft-status-item"><div class="lbl">STATUS</div><div class="val">${esc(d.status).toUpperCase()}</div></div>
      <div class="draft-status-item"><div class="lbl">PICK</div><div class="val">${d.current_pick_no} / ${d.total_picks}</div></div>
      <div class="draft-status-item"><div class="lbl">ON THE CLOCK</div><div class="val${isMe ? " you" : ""}">${isMe ? "YOU" : esc(onClockName)}</div></div>
      ${d.picks_until_mine != null ? `<div class="draft-status-item"><div class="lbl">PICKS UNTIL YOURS</div><div class="val">${esc(d.picks_until_mine)}</div></div>` : ""}
    </div>`;
    if (!d.supported_format) {
      html += `<div class="hint">This draft type (${esc(d.draft_type)}) isn't fully supported yet — showing what we can, but recommendations assume a standard snake draft.</div>`;
    }
  }

  const picksFeed = [...d.picks_made].reverse().slice(0, 40).map((p) => `
    <div class="picks-feed-row">
      <span class="pick-no">#${esc(p.pick_no)}</span>
      <span class="pos-badge">${esc(p.position || "?")}</span>
      <span>${esc(p.player_display_name) || "—"}</span>
      <span class="muted" style="margin-left:auto">${esc(p.team || "")}</span>
    </div>`).join("") || `<div class="empty">No picks yet.</div>`;

  if (d.is_complete) {
    const recap = (d.my_picks_recap || []).map((p) => `
      <div class="picks-feed-row">
        <span class="pick-no">R${esc(p.round)}</span>
        <span class="pos-badge">${esc(p.position || "?")}</span>
        <span>${esc(p.player_display_name) || "—"}</span>
        <span class="muted" style="margin-left:auto">Pick #${esc(p.pick_no)}</span>
      </div>`).join("") || `<div class="empty">No picks found for your team in this draft.</div>`;
    html += `<div class="draft-columns">
      <div><div class="section-label">All Picks</div><div class="picks-feed">${picksFeed}</div></div>
      <div><div class="section-label">Your Draft Recap</div><div class="picks-feed">${recap}</div></div>
    </div>`;
  } else {
    const available = d.best_available.map((p, i) => `
      <div class="myteam-roster-row" data-pid="${esc(p.player_id)}">
        <span class="rank-cell">${i + 1}</span>
        <img ${headshotAttrs(p)} alt="">
        <span class="pos-badge">${esc(p.position)}</span>
        <span>${esc(p.player_display_name)}${needBadge(p.need_multiplier)}${runBadge(p.run_multiplier)}</span>
        <span class="proj-num">${FMT.d1(p.ADJ_SCORE)}</span>
      </div>`).join("");
    html += `<div class="draft-columns">
      <div><div class="section-label">Recent Picks</div><div class="picks-feed">${picksFeed}</div></div>
      <div><div class="section-label">Best Available (need-adjusted)</div><div class="board-wrap" style="padding:4px 12px;max-height:480px;overflow-y:auto;">${available}</div></div>
    </div>`;
  }

  const listScroll = content.querySelector(".board-wrap")?.scrollTop || 0;     // the 6 s refresh must not snap the list back to the top
  content.innerHTML = html;
  const list = content.querySelector(".board-wrap");
  if (list && listScroll) list.scrollTop = listScroll;
  content.querySelectorAll(".myteam-roster-row").forEach((row) => {
    row.addEventListener("click", () => openPlayerModal(row.dataset.pid));
  });
}

async function loadDraftBoard(draftId) {
  const content = $("#draft-content");
  content.style.display = "";
  content.innerHTML = `<div class="loading">Loading draft…</div>`;
  try {
    const d = await api(`/api/draft/${draftId}?${scoringQS().replace(/^&/, "")}`);
    renderDraftBoard(d);
    stopDraftPolling();
    if (!d.is_complete) {
      draftPollHandle = setInterval(async () => {
        if (document.hidden) return;                 // no point polling a background tab
        try { renderDraftBoard(await api(`/api/draft/${draftId}?${scoringQS().replace(/^&/, "")}`)); }
        catch (e) { stopDraftPolling(); }
      }, 6000);
    }
  } catch (e) {
    content.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function loadDraftTab() {
  const gate = $("#draft-gate");
  const picker = $("#draft-picker");
  const content = $("#draft-content");
  gate.style.display = "none"; picker.style.display = "none"; content.style.display = "none";

  if (!state.user || !activeTeam()) {
    gate.style.display = "";
    return;
  }

  if (activeTeam().platform === "espn") {
    gate.style.display = "";
    gate.querySelector(".gate-sub").textContent = "Live draft tracking reads Sleeper's draft feed, and ESPN has no public one. Switch to a Sleeper league in the sidebar to use the Draft Board.";
    return;
  }

  try {
    const snap = await api(`/api/sleeper/${activeTeam().league_id}`);
    draftTeamNames = {};
    snap.teams.forEach((t) => { draftTeamNames[t.roster_id] = t.team_name; });

    const data = await api("/api/myteam/drafts");
    if (!data.drafts.length) {
      picker.style.display = "";
      picker.innerHTML = `<div class="hint">No drafts found for this league yet.</div>`;
      return;
    }
    if (data.drafts.length === 1) {
      loadDraftBoard(data.drafts[0].draft_id);
      return;
    }
    picker.style.display = "";
    picker.innerHTML = `<div class="hint">This league has multiple drafts — pick one:</div>
      <div class="draft-picker-list">${data.drafts.map((d) => `
        <button class="pill" data-draft="${esc(d.draft_id)}">${esc(d.season)} · ${esc(d.status)}</button>
      `).join("")}</div>`;
    picker.querySelectorAll("button[data-draft]").forEach((b) => {
      b.addEventListener("click", () => { picker.style.display = "none"; loadDraftBoard(b.dataset.draft); });
    });
  } catch (e) {
    gate.style.display = "";
    gate.querySelector(".gate-sub").textContent = e.message;
  }
}

$("#draft-gate-btn")?.addEventListener("click", () => switchTab("settings"));

// --------------------------------------------------------- trade finder ----
// Player-driven only: nothing gets scanned until you pick your own player(s)
// to shop above and hit "Find trades for selected". The need-driven "system
// picks what to shop" mode still exists server-side (harmless to keep) but
// the UI never triggers it on its own anymore.
function playerChipsHtml(players) {
  return players.map((p) => `
    <div class="ts-player">
      <img ${headshotAttrs(p)} alt="">
      <span>${esc(p.player_display_name)}</span>
    </div>`).join("");
}

// Purely presentational: the backend doesn't hand back a tier for a
// suggestion (just a real value_diff), so bucket it here the same way
// needBarClass() buckets a real need multiplier — a percentage of what
// you're giving up, not a fixed points cutoff, since "give" value scale
// varies a lot by player tier. Reuses the exact tier CSS/icons the Trade
// Analyzer already defines (.trade-tier-badge.tier-*) for visual parity.
function tradeReasonsHtml(s) {
  const r = s.reasons;
  if (!r || (!r.you.length && !r.them.length)) return "";
  const list = (title, items) => items.length ? `<div class="tr-why"><div class="tr-why-t">${esc(title)}</div><ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  return `<div class="tr-reasons">${list("Why you'd do it", r.you)}${list(`Why ${s.opponent_team_name} might`, r.them)}</div>`;
}

function tradeFinderTier(pctDiff) {
  if (pctDiff >= 15) return { css: "tier-great", label: "Great Value", icon: "🔥" };
  if (pctDiff >= 5) return { css: "tier-good", label: "Good Value", icon: "📈" };
  if (pctDiff >= -5) return { css: "tier-fair", label: "Fair Trade", icon: "⚖️" };
  if (pctDiff >= -20) return { css: "tier-questionable", label: "Slight Overpay", icon: "🤔" };
  return { css: "tier-bad", label: "Overpay", icon: "📉" };
}

async function loadTradeFinder(giveIds) {
  const block = $("#trade-finder-block");
  if (!state.user || !activeTeam()) { block.style.display = "none"; return; }
  block.style.display = "";
  await renderShopPicker();

  const results = $("#trade-finder-results");
  const clearBtn = $("#shop-clear-btn");
  const shopping = giveIds && giveIds.length;
  clearBtn.style.display = shopping ? "" : "none";

  if (!shopping && !giveIds?.scan) {
    results.innerHTML = `<div class="hint">Pick one or two of your own players above and hit "Find trades for selected", or let us scan every roster for the best deals for your team.</div>
      <button class="primary-btn" id="tf-scan-btn">Find my best trades</button>`;
    $("#tf-scan-btn").addEventListener("click", () => loadTradeFinder(Object.assign([], { scan: true })));
    return;
  }

  // Same scan-bar treatment as the Trade Analyzer's "Analyzing trade…" state
  // — this used to be a bare loading string, at a visibly lower visual tier
  // than the rest of the Trade tab.
  results.innerHTML = `<div class="trade-analyzing"><div class="trade-scan-bar"></div><span>Scanning the league for realistic trades…</span></div>`;
  try {
    const giveQS = giveIds.map((id) => `&give=${encodeURIComponent(id)}`).join("");
    // NOT `scoringQS().replace("&","?")` — that's a no-op when scoringQS()
    // is empty (the common default-scoring case), leaving giveQS glued
    // straight onto the path with no "?" at all: "/api/trade-finder&give=…"
    // is a literal 404 to the router, not a query string — exactly the
    // "trade finder always says Not Found" bug. A literal "?" plus
    // stripping one leading "&" is well-formed either way.
    const data = await api(`/api/trade-finder?${(scoringQS() + giveQS).replace(/^&/, "")}`);
    if (!data.suggestions.length) {
      results.innerHTML = `<div class="empty tf-empty">No fair trade turns up for that pick right now. Try a different player or pair.</div>`;
      return;
    }
    renderTradeFinderResults(results, data.suggestions);
  } catch (e) {
    results.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

function renderTradeFinderResults(results, suggestions, showAll) {
  const fair = suggestions.filter((s) => s.kind === "fair").length;
  const realistic = suggestions.filter((s) => s.analysis?.verdict?.status === "APPROVED").length;
  const LIMIT = 25;
  const shown = showAll ? suggestions : suggestions.slice(0, LIMIT);
  let html = realistic
    ? `<div class="tf-summary">
        <span class="tf-summary-count" data-target="${realistic}"></span>
        <span class="tf-summary-lbl">trade${realistic === 1 ? "" : "s"} found</span>
        <span class="tf-summary-best">${fair ? `${fair} dead-even on the trade chart (listed first, even if they don't help a lineup), then the best trades for both teams` : "every one passes all five checks below"}</span>
      </div>`
    : `<div class="tf-summary"><span class="tf-summary-lbl">No trade passes every check right now. These are the closest; each says what to change.</span></div>`;
  html += shown.map((s, i) => `
      <div class="trade-suggestion tf-clickable${i === 0 && realistic ? " best-value" : ""}" data-idx="${i}" tabindex="0" role="button" aria-label="Open trade details" style="animation-delay:${Math.min(i, 8) * 70}ms">
        <div class="ts-opp"><span>vs ${esc(s.opponent_team_name)}</span>${s.kind === "fair" ? `<span class="badge-fair">DEAD EVEN</span>` : ""}${i === 0 && realistic ? `<span class="badge-recommended">TOP PICK</span>` : ""}</div>
        <div class="ts-swap">
          <div class="ts-side">${playerChipsHtml(s.you_give)}</div>
          <div class="ts-swap-icon">⇄</div>
          <div class="ts-side">${playerChipsHtml(s.you_get)}</div>
        </div>
        ${tradeVerdictHtml(s.analysis, true)}
        <div class="ts-footer">
          <span class="tf-open-hint">Tap for the full trade breakdown</span>
          <button class="pill" data-give='${esc(JSON.stringify(s.you_give))}' data-get='${esc(JSON.stringify(s.you_get))}'>Load into builder</button>
        </div>
      </div>`).join("");
  if (!showAll && suggestions.length > LIMIT) html += `<button class="pill tf-more" id="tf-more">Show all ${suggestions.length} trades</button>`;
  results.innerHTML = html;
  $("#tf-more")?.addEventListener("click", () => renderTradeFinderResults(results, suggestions, true));
  wireTradeVerdict(results);
  const countEl = results.querySelector(".tf-summary-count[data-target]");
  if (countEl) countUp(countEl, Number(countEl.dataset.target), { decimals: 0, duration: 500 });
  results.querySelectorAll("button[data-give]").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      loadTradeIntoBuilder(JSON.parse(b.dataset.give), JSON.parse(b.dataset.get));
    });
  });
  results.querySelectorAll(".tf-clickable").forEach((card) => {
    const open = () => openTradeDetail(shown[Number(card.dataset.idx)]);
    card.addEventListener("click", (e) => { if (!e.target.closest("button, summary, details, a")) open(); });
    card.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === card) { e.preventDefault(); open(); } });
  });
}

function loadTradeIntoBuilder(give, get) {
  state.tradeA = give;
  state.tradeB = get;
  renderTradeChips("a"); renderTradeChips("b");
  window.scrollTo({ top: document.querySelector(".trade-columns").offsetTop - 80, behavior: "smooth" });
}

function tdPlayerRowHtml(p) {
  const tierN = p.tier;
  const flags = [p.injury_status && `<span class="injury-flag questionable">${esc(p.injury_status)}</span>`, p.bye && `<span class="muted small">Bye wk ${esc(p.bye)}</span>`].filter(Boolean).join(" ");
  return `<div class="td-player">
    <img ${headshotAttrs(p)} alt="">
    <div class="td-pinfo"><div class="name">${esc(p.player_display_name || p.name)}</div>
      <div class="meta">${esc(p.position)} · ${esc(p.recent_team)}${tierN ? ` · Tier ${esc(tierN)}` : ""} ${flags}</div></div>
    <div class="td-pnums"><div><b>${p.trade != null ? FMT.d1(p.trade) : "—"}</b><small>chart value</small></div>
      <div><b>${p.value != null ? FMT.d1(p.value) : "—"}</b><small>proj PPG</small></div></div>
  </div>`;
}

function openTradeDetail(s) {
  if (!s) return;
  const a = s.analysis, c = a?.context || {};
  const total = (ps) => ps.reduce((t, p) => t + (p.trade || 0), 0);
  const benched = (list) => list?.length ? list.map((x) => `${esc(x.name)} (${FMT.d1(x.proj_ppg)} PPG)`).join(", ") : "nobody";
  const tags = (arr) => (arr && arr.length ? arr.map(esc).join(", ") : "none");
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal tdetail">
    <div class="modal-header"><div><h2>Trade with ${esc(s.opponent_team_name)}</h2>
      <div class="muted">${s.kind === "fair" ? "Dead even on the trade chart" : "Helps both lineups"} · everything the engine checked</div></div>
      <button class="modal-close" aria-label="Close">✕</button></div>
    <div class="td-sides">
      <div class="td-side"><div class="section-label">You give <span class="muted">· ${FMT.d1(total(s.you_give))} chart value</span></div>${s.you_give.map(tdPlayerRowHtml).join("")}</div>
      <div class="td-side"><div class="section-label">You get <span class="muted">· ${FMT.d1(total(s.you_get))} chart value</span></div>${s.you_get.map(tdPlayerRowHtml).join("")}</div>
    </div>
    ${a ? tradeVerdictHtml(a, false) : ""}
    ${a ? `<div class="td-ctx">
      <div class="section-label">Lineup moves</div>
      <p><b>You:</b> ${benched(c.user_starter_replaced)} would lose a starting spot.<br><b>${esc(s.opponent_team_name)}:</b> ${benched(c.opponent_starter_replaced)} would lose a starting spot.</p>
      <div class="section-label">Both teams</div>
      <p><b>You</b> (${esc(c.user_record || "no record yet")}): needs ${tags(c.user_weaknesses)}; strong at ${tags(c.user_strengths)}.<br>
      <b>${esc(s.opponent_team_name)}</b> (${esc(c.opponent_record || "no record yet")}${c.opponent_archetype ? `, ${esc(c.opponent_archetype)}` : ""}): needs ${tags(c.opponent_weaknesses)}; strong at ${tags(c.opponent_strengths)}.</p>
    </div>` : ""}
    <div class="td-actions"><button class="primary-btn" id="td-load">Load into builder</button><button class="pill" id="td-close">Close</button></div>
  </div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => { if (e.target.classList.contains("modal-backdrop")) closeModal(); });
  root.querySelector(".modal-close").addEventListener("click", closeModal);
  $("#td-close").addEventListener("click", closeModal);
  $("#td-load").addEventListener("click", () => { closeModal(); loadTradeIntoBuilder(s.you_give, s.you_get); });
  wireTradeVerdict(root);
}

// Shared "my own roster" cache — both the Trade Finder's shop picker and
// the Start/Sit picker draw from the same synced roster, one fetch covers both.
async function ensureMyRoster() {
  if (!state.shopRoster.length) {
    const data = await api(`/api/myteam?${scoringQS().replace(/^&/, "")}`);
    state.shopRoster = data.my_team.players;
  }
  return state.shopRoster;
}

async function renderShopPicker() {
  const picker = $("#shop-roster-picker");
  try {
    await ensureMyRoster();
  } catch (e) { picker.innerHTML = ""; return; }
  // Trade Finder's backend (engine/tools.py trade_finder) can only value
  // a QB/RB/WR/TE that's actually in the scored board — DEF/K (which
  // never get a personal SCORE, see _defense_row/_kicker_row) and any
  // currently-unscored fallback player throw a hard ValueError if
  // selected as something to shop, surfacing as "trade finder doesn't
  // work" with no clue why. Filtering them out of the picker here fixes
  // the actual bug (offering a selection the backend can't handle) —
  // the fuller fix, giving DEF/K real shoppable trade values, is a
  // separate, bigger backend feature, not this bug's fault line.
  const shoppable = state.shopRoster.filter((p) => POSITIONS.includes(p.position) && p.SCORE != null);
  picker.innerHTML = shoppable.map((p) => `
    <button type="button" class="shop-chip${state.shopSelected.has(p.player_id) ? " selected" : ""}" data-pid="${esc(p.player_id)}">
      <img ${headshotAttrs(p)} alt="">
      <span class="pos-badge">${esc(p.position)}</span>
      <span>${esc(p.player_display_name)}</span>
    </button>
  `).join("");
  picker.querySelectorAll(".shop-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const pid = chip.dataset.pid;
      if (state.shopSelected.has(pid)) state.shopSelected.delete(pid);
      else {
        if (state.shopSelected.size >= 2) { showToast("Shop one or two players at a time."); return; }
        state.shopSelected.add(pid);
      }
      chip.classList.toggle("selected");
      $("#shop-find-btn").disabled = state.shopSelected.size === 0;
    });
  });
  $("#shop-find-btn").disabled = state.shopSelected.size === 0;
}

function initTradeFinder() {
  $("#shop-find-btn").addEventListener("click", () => loadTradeFinder([...state.shopSelected]));
  $("#shop-clear-btn").addEventListener("click", () => {
    state.shopSelected.clear();
    loadTradeFinder();
  });
}

// ---------------------------------------------------------------- news ----
// -------------------------------------------------------- live scores ----
// Real in-game NFL scores (see /api/live-scores + engine/live_scores.py)
// — free, public, no key. Lives on My Team since that's the home tab;
// polls on a short interval only while that tab is actually the one
// showing, so it isn't hammering ESPN's endpoint from a background tab.
// ESPN and nflverse spell a few teams differently (TEAM_ALIAS, above); fold
// both to one key so a roster team lines up with a scoreboard team.
const teamKey = (t) => { const a = String(t || "").toUpperCase(); return TEAM_ALIAS[a] || a; };

// {team: how many of your players are on it}, from a My Team card.
function rosterTeamCounts(team) {
  const out = {};
  ((team && team.players) || []).forEach((p) => {
    const k = teamKey(p.recent_team);
    if (k) out[k] = (out[k] || 0) + 1;
  });
  return out;
}

function myPlayersInGame(g) {
  const m = state.myTeamAbbrs || {};
  return (m[teamKey(g.away.abbr)] || 0) + (m[teamKey(g.home.abbr)] || 0);
}

function liveScoreCardHtml(g) {
  const isLive = g.state === "in";
  const isFinal = g.state === "post";
  const scoreLine = g.state === "pre"
    ? `<span class="muted">vs</span>`
    : `${g.away.score}–${g.home.score}`;
  const mine = myPlayersInGame(g);
  return `<button type="button" class="live-score-card${isLive ? " live" : ""}${isFinal ? " final" : ""}${mine ? " has-mine" : ""}${g.flash ? " score-flash" : ""}" data-game="${esc(g.game_id)}" title="Open box score">
    ${isLive ? `<span class="live-dot"></span>` : ""}
    <div class="lsc-teams">
      <span class="${g.away.winner ? "lsc-winner" : ""}">${esc(g.away.abbr)}</span>
      <span class="lsc-score">${scoreLine}</span>
      <span class="${g.home.winner ? "lsc-winner" : ""}">${esc(g.home.abbr)}</span>
    </div>
    <div class="lsc-status">${esc(isLive ? `Q${g.period} · ${g.display_clock}` : g.status_detail)}</div>
    ${mine ? `<div class="lsc-mine">★ ${mine} of yours</div>` : ""}
  </button>`;
}

// Re-flag the strip's cards once My Team's roster is known (the strip can
// finish loading before the roster does).
function markLiveScoreCards() {
  const strip = $("#live-scores-strip");
  if (!strip || !state.liveGames) return;
  strip.innerHTML = state.liveGames.map(liveScoreCardHtml).join("");
}

async function loadLiveScores() {
  const strip = $("#live-scores-strip");
  if (!strip) return;
  try {
    const data = await api("/api/live-scores");
    const games = data.games || [];
    if (!games.length) { strip.style.display = "none"; return; }
    const before = new Map((state.liveGames || []).map((g) => [String(g.game_id), `${g.away.score}-${g.home.score}`]));
    games.forEach((g) => { const b = before.get(String(g.game_id)); g.flash = b != null && g.state === "in" && b !== `${g.away.score}-${g.home.score}`; });
    state.liveGames = games;
    strip.innerHTML = games.map(liveScoreCardHtml).join("");
    if (games.some((g) => g.flash)) setTimeout(() => { games.forEach((g) => { g.flash = false; }); strip.querySelectorAll(".score-flash").forEach((c) => c.classList.remove("score-flash")); }, 2200);
    strip.style.display = "flex";
  } catch (e) {
    // a scoreboard hiccup shouldn't be loud — just leave whatever was
    // showing (or stay hidden if this was the first load)
  }
}

const GB_GROUPS = [["QB", "Quarterbacks"], ["RB", "Running backs"], ["WR", "Wide receivers"], ["TE", "Tight ends"], ["K", "Kickers"]];
const GB_GROUP_OF = { QB: "QB", RB: "RB", FB: "RB", WR: "WR", TE: "TE", K: "K", PK: "K" };

function gamePlayerHtml(p, team) {
  const pts = p.fantasy_points == null ? "" : `<b class="gb-pts">${FMT.d1(p.fantasy_points)}</b>`;
  const fb = initialsAvatarUri(p.name);
  const photo = p.headshot ? `<img class="gb-photo" src="${proxyImg(p.headshot)}" data-fb="${fb}" alt="" loading="lazy">` : `<img class="gb-photo" src="${fb}" alt="">`;
  const logo = team && team.logo ? `<img class="gb-tlogo" src="${proxyImg(team.logo)}" data-fb-hide="1" alt="">` : "";
  return `<div class="gb-player${p.mine ? " mine" : ""}">
    ${photo}
    <div class="gb-main">
      <div class="gb-head"><span class="gb-name">${p.mine ? '<span class="gb-star" title="On your team">★</span> ' : ""}${esc(p.name)}</span>${pts}</div>
      <div class="gb-sub">${logo}<span>${esc(p.position || "")} · ${esc(p.team || (team && team.abbr) || "")}</span></div>
      ${(p.lines || []).map((l) => `<div class="gb-line"><span class="gb-lbl">${esc(l.label)}</span>${esc(l.text)}</div>`).join("")}
    </div>
  </div>`;
}

function gameTeamHtml(t) {
  const groups = GB_GROUPS.map(([code, label]) => [label, (t.players || []).filter((p) => GB_GROUP_OF[p.position] === code)]).filter(([, ps]) => ps.length);
  const rest = (t.players || []).filter((p) => !GB_GROUP_OF[p.position]);
  const logo = t.logo ? `<img class="gb-teamlogo" src="${proxyImg(t.logo)}" data-fb-hide="1" alt="">` : "";
  return `<div class="gb-team">
    <button type="button" class="gb-team-head" data-team-page="${esc(t.abbr)}">${logo}<span>${esc(t.name || t.abbr)}</span><span class="gb-go" aria-hidden="true">›</span></button>
    ${groups.map(([label, ps]) => `<div class="gb-group">${esc(label)}</div>${ps.map((p) => gamePlayerHtml(p, t)).join("")}`).join("") || `<div class="muted">No stats yet.</div>`}
    ${rest.length ? `<details class="gb-rest"><summary>Defense &amp; other (${rest.length})</summary>${rest.map((p) => gamePlayerHtml(p, t)).join("")}</details>` : ""}
  </div>`;
}

function gameBodyHtml(box) {
  const teams = box.teams || [];
  if (!teams.length) return `<div class="empty">No box score yet. It appears once the game kicks off.</div>`;
  const mineLine = box.mine_count
    ? `<div class="gb-mine-summary">Your players in this game: <b>${box.mine_count}</b> · <b>${FMT.d1(box.mine_points)}</b> fantasy pts</div>`
    : "";
  return mineLine + `<div class="gb-teams">${teams.map(gameTeamHtml).join("")}</div>`;
}

// ---- team page: record, next game outlook, weekly results, stats and a roster of clickable player profiles ----
function teamGameRowHtml(g) {
  const res = g.result;
  const score = res ? `${g.team_score}–${g.opp_score}` : "—";
  return `<div class="tp-game ${res ? "res-" + res.toLowerCase() : "res-pending"}">
    <span class="tp-wk">Wk ${g.week}</span>
    <span class="tp-opp">${g.home ? "vs" : "@"} ${esc(g.opponent)}</span>
    <span class="tp-score">${score}</span>
    <span class="tp-res">${res || "·"}</span>
  </div>`;
}

function teamPageHtml(d) {
  const th = TeamTheme.get(d.team) || {};
  const n = d.next_game;
  const when = (iso) => { const t = new Date(iso + "T12:00:00"); return isNaN(t) ? iso : t.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }); };
  const fav = n && n.spread != null ? (n.spread < 0 ? `${esc(d.team)} favored by ${Math.abs(n.spread)}` : n.spread > 0 ? `${esc(n.opponent)} favored by ${n.spread}` : "Pick'em") : "";
  const outlook = n ? `<div class="tp-next">
      <div class="tp-next-title">Next game · Week ${n.week} · ${esc(when(n.date))}</div>
      <div class="tp-next-main">${n.home ? "vs" : "@"} <b>${esc(n.opponent)}</b></div>
      ${n.implied_total != null ? `<div class="tp-next-meta">${fav ? fav + " · " : ""}Expected score ${FMT.d1(n.implied_total)}–${FMT.d1(n.opp_implied_total)} (total ${FMT.d1(n.total)})</div>` : ""}
    </div>` : `<div class="tp-next"><div class="tp-next-title">Next game</div><div class="muted">No upcoming game on the schedule.</div></div>`;
  const s = d.stats || {};
  const stat = (label, v) => `<div class="tp-stat"><b>${v == null ? "–" : FMT.d1(v)}</b><span>${label}</span></div>`;
  const players = (d.players || []).map((p) => `<button type="button" class="tp-player" data-player="${esc(p.player_id)}"${n ? ` data-opp="${esc(n.opponent)}"` : ""}>
      <img class="tp-photo" ${headshotAttrs({ headshot_url: p.headshot_url, player_display_name: p.name })} alt="" loading="lazy">
      <span class="tp-pname">${esc(p.name)}<small>${esc(p.position)}${p.injury_status ? ` · ${esc(p.injury_status)}` : ""}</small></span>
      <span class="tp-pnum"><b>${p.proj != null ? FMT.d1(p.proj) : "–"}</b><small>proj</small></span>
      <span class="tp-pnum"><b>${FMT.d1(p.ppg)}</b><small>avg</small></span>
    </button>`).join("");
  return `<div class="tp-head">
      ${d.logo ? `<img class="tp-logo" src="${proxyImg(d.logo)}" data-fb-hide="1" alt="">` : ""}
      <div><h2>${esc(th.city || "")} ${esc(th.name || d.team)}</h2>
        <div class="muted">${esc(th.division || "")} · <b>${esc(d.record.text)}</b> · ${d.points_for} PF / ${d.points_against} PA</div></div>
    </div>
    ${outlook}
    <div class="tp-stats">${stat("Points / game", s.points_for_pg)}${stat("Allowed / game", s.points_against_pg)}${stat("Pass yds / game", s.pass_yds_pg)}${stat("Rush yds / game", s.rush_yds_pg)}</div>
    <div class="section-label">Weekly results</div>
    <div class="tp-games">${(d.games || []).map(teamGameRowHtml).join("") || `<div class="muted">No games yet.</div>`}</div>
    <div class="section-label">Players${n ? ` · projected for Week ${n.week}` : ""}</div>
    <div class="tp-players">${players || `<div class="muted">No player data yet.</div>`}</div>`;
}

async function openTeamModal(code) {
  const seq = ++teamModalSeq;
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal tp-modal"><div class="modal-header"><div></div><button class="modal-close" aria-label="Close">✕</button></div>
    <div id="tp-body">${skeletonRows(6, 2)}</div></div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeModal();
    const pl = e.target.closest(".tp-player");
    if (pl) openPlayerModal(pl.dataset.player, pl.dataset.opp);
  });
  root.querySelector(".modal-close").addEventListener("click", closeModal);
  try {
    const qs = scoringQS().replace(/^&/, "");
    const d = await api(`/api/team/${encodeURIComponent(code)}${qs ? "?" + qs : ""}`);
    const body = $("#tp-body");
    if (body && seq === teamModalSeq) body.innerHTML = teamPageHtml(d);
  } catch (e) {
    const body = $("#tp-body");
    if (body && seq === teamModalSeq) body.innerHTML = `<div class="empty">Couldn't load this team. Try again in a moment.</div>`;
  }
}

// one delegated listener: the theme pill and any team name/logo marked data-team-page open the team page
document.addEventListener("click", (e) => {
  const el = e.target.closest ? e.target.closest("[data-team-page]") : null;
  if (el && el.dataset.teamPage) openTeamModal(el.dataset.teamPage);
});

var gameModalTimer = null;
var teamModalSeq = 0;

async function openGameModal(gameId) {
  const g = (state.liveGames || []).find((x) => String(x.game_id) === String(gameId));
  if (!g) return;
  const root = $("#modal-root");
  const live = g.state === "in";
  const score = g.state === "pre" ? "vs" : `${g.away.score}–${g.home.score}`;
  root.innerHTML = `<div class="modal-backdrop"><div class="modal gb-modal">
    <div class="modal-header"><div><h2>${esc(g.away.abbr)} ${score} ${esc(g.home.abbr)}</h2>
      <div class="muted" id="gb-status">${esc(live ? `Q${g.period} · ${g.display_clock}` : g.status_detail)}</div></div>
      <button class="modal-close" aria-label="Close">✕</button></div>
    <div id="gb-body">${skeletonRows(8, 2)}</div>
  </div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => { if (e.target.classList.contains("modal-backdrop")) closeModal(); });
  root.querySelector(".modal-close").addEventListener("click", closeModal);

  clearInterval(gameModalTimer);
  const refresh = async () => {
    const body = $("#gb-body");
    if (!body) { clearInterval(gameModalTimer); return; }   // modal was closed
    try {
      const qs = scoringQS().replace(/^&/, "");
      body.innerHTML = gameBodyHtml(await api(`/api/live-scores/${encodeURIComponent(gameId)}${qs ? "?" + qs : ""}`));
    } catch (e) {
      if (!body.querySelector(".gb-teams")) body.innerHTML = `<div class="empty">Couldn't load this box score. Try again in a moment.</div>`;
    }
  };
  await refresh();
  if (live) gameModalTimer = setInterval(refresh, 20000);
}

function initLiveScores() {
  const strip = $("#live-scores-strip");
  if (strip) strip.addEventListener("click", (e) => {
    const card = e.target.closest(".live-score-card[data-game]");
    if (card) openGameModal(card.dataset.game);
  });
  loadLiveScores();
  setInterval(() => {
    if (state.tab === "myteam" && document.visibilityState === "visible") loadLiveScores();
  }, 20000);
}

function initNews() {
  $("#news-scope-tabs").querySelectorAll("button[data-scope]").forEach((b) => {
    b.addEventListener("click", () => {
      if (state.newsScope === b.dataset.scope) return;
      state.newsScope = b.dataset.scope;
      $("#news-scope-tabs").querySelectorAll("button[data-scope]").forEach((x) => x.classList.toggle("active", x === b));
      loadNews();
    });
  });
}

// Real publisher photos (RSS enclosure, or the article's own og:image —
// see engine/news.py) — a headline whose image fails to load just drops
// back to a text-only card instead of showing a broken image.
function newsTagsHtml(it) {
  if (it.match_kind === "team") {
    return `<div class="news-matched"><span class="tag soft team">Team news</span>${(it.matched_teams || []).map((t) => `<span class="tag soft">${esc(t)}</span>`).join("")}</div>`;
  }
  return it.matched_players && it.matched_players.length
    ? `<div class="news-matched">${it.matched_players.map((m) => `<span class="tag soft">${esc(m.name)}</span>`).join("")}</div>` : "";
}

function newsCardHtml(it, featured, i) {
  // The story's own photo when we have it; until then (or when the feed has none) the headshot of the player it
  // is about, else his team's logo, so every card has a picture on first paint.
  const src = it.image || it.fallback_image;
  const isFallback = !it.image && !!it.fallback_image;
  return `<a class="news-card${featured ? " featured" : ""}" href="${safeUrl(it.link)}" target="_blank" rel="noopener noreferrer" style="animation-delay:${Math.min(i, 8) * 50}ms">
    <div class="news-img-wrap${src ? "" : " no-image"}${isFallback ? " is-fallback" : ""}">
      ${src ? `<img src="${proxyImg(src)}" alt="" loading="lazy" data-fb-noimage-wrap="1">` : ""}
      ${featured ? `<span class="news-badge">FEATURED</span>` : ""}
    </div>
    <div class="news-body">
      <div class="news-meta"><span>${esc(it.source)}</span><span>·</span><span>${esc(it.published)}</span></div>
      ${newsTagsHtml(it)}
      <div class="news-title">${esc(it.title)}</div>
      <div class="news-summary">${esc(it.summary)}</div>
    </div>
  </a>`;
}

function renderNews(data, scope) {
  const list = $("#news-list");
  const src = (data.sources || []).join(", ");
  if (data.requires_team) {
    $("#news-hint").textContent = `Sign in and connect a Sleeper team to see ${scope === "opponent" ? "opponent" : "your team's"} news.`;
    list.innerHTML = `<div class="empty">Connect a league in Settings to unlock this tab.</div>`;
    return;
  }
  if (scope === "favorite") {
    const t = TeamTheme.get(data.team);
    $("#news-hint").textContent = `Every headline about the ${t ? t.city + " " + t.name : "team"}${src ? ` (${src})` : ""}.`;
    if (!data.items.length) { list.innerHTML = `<div class="empty">No headlines about the ${esc(t ? t.name : "team")} right now. Check back later.</div>`; return; }
  } else if (scope === "team") {
    $("#news-hint").textContent = `${data.team_name ? `"${data.team_name}"` : "Your roster"}: stories naming your players, then news about their teams${src ? ` (${src})` : ""}.`;
  } else if (scope === "opponent") {
    $("#news-hint").textContent = data.team_name ? `This week's opponent, "${data.team_name}"${src ? ` (${src})` : ""}.` : "This week's opponent.";
  } else {
    $("#news-hint").textContent = `Every headline from ${src || "the NFL feeds"}; ones about someone in your league come first.`;
  }
  if (data.message) { list.innerHTML = `<div class="empty">${esc(data.message)}</div>`; return; }
  if (!data.items.length) {
    list.innerHTML = `<div class="empty">No headlines about your players or their teams right now. Check back later.</div>`;
    return;
  }
  // The big FEATURED slot is for a story's own photo; a stand-in headshot or logo would just be blown up.
  list.innerHTML = data.items.map((it, i) => newsCardHtml(it, i === 0 && it.match_kind !== "team" && !!it.image, i)).join("");
}

// Last answer per tab, kept for a few minutes so switching tabs (or coming back) paints at once while a
// fresh copy loads behind it.
const NEWS_CLIENT_TTL = 5 * 60 * 1000;

// The favorite-team tab: shown (labelled with the team's name) only while a team theme is chosen. First time News opens
// with a team set it becomes the selected tab; choosing the default theme again drops back to My Team.
function syncNewsFavTab() {
  const btn = $("#news-fav-tab");
  const t = TeamTheme.get(TeamTheme.current());
  if (btn) { btn.hidden = !t; if (t) btn.textContent = t.name; }
  if (t && !state.newsFavSeen) { state.newsFavSeen = true; state.newsScope = "favorite"; }
  if (!t && state.newsScope === "favorite") state.newsScope = "team";
  $("#news-scope-tabs").querySelectorAll("button[data-scope]").forEach((x) => x.classList.toggle("active", x.dataset.scope === state.newsScope));
}

async function loadNews() {
  const list = $("#news-list");
  syncNewsFavTab();
  const scope = state.newsScope;
  const fav = TeamTheme.current();
  // keyed by who is looking and at which team, so a sign-out or a league switch never shows someone else's stories
  const t = (typeof activeTeam === "function" && activeTeam()) || {};
  const key = `${state.user ? state.user.id : 0}|${t.league_id || ""}|${t.roster_id || ""}|${scope}|${scope === "favorite" ? fav : ""}`;
  state.newsCache = state.newsCache || {};
  const cached = state.newsCache[key] && Date.now() - state.newsCache[key].at < NEWS_CLIENT_TTL ? state.newsCache[key] : null;
  if (cached) renderNews(cached.data, scope);
  else list.innerHTML = Array.from({ length: 6 }, () => `<div class="news-card news-skel" aria-hidden="true"><div class="skel news-skel-img"></div><div class="news-body"><div class="skel skel-line short"></div><div class="skel skel-line" style="max-width:none"></div><div class="skel skel-line" style="max-width:70%"></div></div></div>`).join("");
  try {
    const data = await api(`/api/news?scope=${scope}${scope === "favorite" ? "&team=" + encodeURIComponent(fav) : ""}`);
    state.newsCache[key] = { at: Date.now(), data };
    if (state.newsScope === scope) renderNews(data, scope);     // the user may have switched tabs meanwhile
    // Photos are looked up in the background after the first download (engine/news.py), so on a cold server
    // some cards still carry a stand-in headshot/logo. Look again once, a few seconds later, to swap in the real photos.
    state.newsPhotoRetry = state.newsPhotoRetry || {};
    const items = data.items || [];
    if (items.filter((x) => !x.image).length >= Math.max(3, items.length * 0.2) && !state.newsPhotoRetry[key]) {
      state.newsPhotoRetry[key] = true;
      setTimeout(() => { if (state.tab === "news" && state.newsScope === scope) loadNews(); }, 6000);
    }
  } catch (e) {
    if (!cached && state.newsScope === scope) list.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// ------------------------------------------------------------- account ----
function renderAccountButton() {
  const btn = $("#account-btn");
  const initial = state.user ? state.user.username.slice(0, 1).toUpperCase() : "👤";
  btn.innerHTML = `<span class="profile-avatar">${esc(initial)}</span>
    <span class="profile-name">${esc(state.user ? state.user.username : "Sign In")}</span>
    ${state.user ? '<span class="profile-chevron">⋯</span>' : ""}`;
  btn.onclick = () => (state.user ? toggleAccountDropdown() : openAuthModal("login"));
}

// ------------------------------------------------------- notifications ----
// Real, actionable alerts only — right now that's "a starter in your
// current lineup is marked OUT or Doubtful" (Questionable is normal
// noise every week and isn't worth interrupting anyone for).
function computeInjuryNotifications(myTeam) {
  if (!myTeam?.players) return [];
  return myTeam.players
    .filter((p) => p.is_starter && p.injury_status && p.injury_status !== "Questionable")
    .map((p) => ({ player_id: p.player_id, name: p.player_display_name, status: p.injury_status, slot: p.slot || p.position }));
}

function renderNotifBell() {
  const bell = $("#notif-bell");
  const badge = $("#notif-badge");
  const n = state.notifications.length;
  bell.style.display = state.user && n > 0 ? "flex" : "none";
  badge.style.display = n > 0 ? "flex" : "none";
  badge.textContent = n > 9 ? "9+" : String(n);
}

function toggleNotifDropdown() {
  const existing = document.querySelector(".notif-dropdown");
  if (existing) { existing.remove(); return; }
  const bell = $("#notif-bell");
  const rect = bell.getBoundingClientRect();
  const dd = el("div", "notif-dropdown");
  dd.style.top = `${rect.bottom + 8}px`;
  dd.style.left = `${rect.left}px`;
  dd.innerHTML = `<div class="ad-header">Lineup Alerts</div>` + (state.notifications.length
    ? state.notifications.map((n) => `<button data-pid="${esc(n.player_id)}">
        <span class="injury-flag">${esc(n.status.toUpperCase())}</span> ${esc(n.slot)} ${esc(n.name)} is in your starting lineup this week.
      </button>`).join("")
    : `<div class="hint" style="padding:12px 14px">All clear — no starter alerts.</div>`);
  dd.querySelectorAll("button[data-pid]").forEach((b) => b.addEventListener("click", () => { dd.remove(); openPlayerModal(b.dataset.pid); }));
  document.body.appendChild(dd);
  setTimeout(() => document.addEventListener("click", function closeOnce(e) {
    if (!dd.contains(e.target) && !e.target.closest("#notif-bell")) { dd.remove(); document.removeEventListener("click", closeOnce); }
  }), 0);
}

function toggleAccountDropdown() {
  const existing = document.querySelector(".account-dropdown");
  if (existing) { existing.remove(); return; }
  const dd = el("div", "account-dropdown");
  dd.innerHTML = `
    <div class="ad-header"><div class="ad-username">${esc(state.user.username)}</div><div class="ad-email">${esc(state.user.email)}</div></div>
    <button data-go="settings">Settings</button>
    <button data-go="myteam">My Team</button>
    <button id="ad-signout">Sign Out</button>`;
  dd.querySelectorAll("button[data-go]").forEach((b) => b.addEventListener("click", () => { dd.remove(); switchTab(b.dataset.go); }));
  dd.querySelector("#ad-signout").addEventListener("click", doSignOut);
  document.body.appendChild(dd);
  setTimeout(() => document.addEventListener("click", function closeOnce(e) {
    if (!dd.contains(e.target) && e.target.id !== "account-btn") { dd.remove(); document.removeEventListener("click", closeOnce); }
  }), 0);
}

async function doSignOut() {
  await api("/api/auth/logout", { method: "POST" });
  state.user = null; state.settings = null; state.teams = []; state.leagueScoringDict = null;
  state.shopRoster = []; state.shopSelected = new Set(); state.startsit = [];
  state.tradeA = []; state.tradeB = [];
  state.notifications = [];
  document.querySelector(".account-dropdown")?.remove();
  document.querySelector(".notif-dropdown")?.remove();
  renderNotifBell();
  renderAccountButton();
  refreshScoringLeagueOption();
  renderSidebarTeams();
  switchTab(DEFAULT_TAB);
  await proceedPastGate(); // sign-in is mandatory — this brings the gate right back
}

function closeAuthModal() { $("#auth-modal-root").innerHTML = ""; syncModalScrollLock(); }

// The visual (image/tagline/trust points) side of the split-screen auth
// experience — shared between the closable modal and the full-screen
// mandatory gate, just wrapped differently by each caller.
function authVisualPanelHtml(headline, subcopy) {
  return `
    <div class="auth-visual-brand">
      <img src="/icons/icon-192.png" alt="">
      <span>Lineup Lab</span>
    </div>
    <div class="auth-visual-copy">
      <h3>${esc(headline)}</h3>
      <p>${esc(subcopy)}</p>
    </div>
    <ul class="auth-visual-points">
      <li><span class="auth-visual-dot"></span>Real Next Gen Stats, not paid grades</li>
      <li><span class="auth-visual-dot"></span>Synced to your real Sleeper league</li>
      <li><span class="auth-visual-dot"></span>Bcrypt + encrypted at rest</li>
    </ul>`;
}

// The form side (tabs, sign-in/create-account form, Google button) — same
// markup and same wiring (validation, submit) regardless of whether it's
// rendered inside the closable modal or the full-screen mandatory gate.
// `onSuccess` is what runs after a real signed-in user comes back — the
// modal closes and re-renders the current tab; the gate moves on to the
// league-sync step or reveals the app.
// True only inside the iOS/Android shell (mobile/ — Capacitor injects window.Capacitor
// into the remote page). Google blocks its sign-in inside an embedded web view
// (disallowed_useragent), so the Google button is web-only for now.
const IS_NATIVE_APP = !!(window.Capacitor && typeof window.Capacitor.isNativePlatform === "function"
  && window.Capacitor.isNativePlatform());

// Light tap feedback from the native Haptics plugin; a no-op on the web.
function nativeHaptic(style = "LIGHT") {
  try { window.Capacitor?.Plugins?.Haptics?.impact({ style }); } catch (_) { /* haptics are cosmetic */ }
}
if (IS_NATIVE_APP) {
  document.addEventListener("click", (e) => {
    if (e.target instanceof Element && e.target.closest("button, .pill, .tab-btn, [role=tab], a.oauth-btn")) nativeHaptic();
  }, { passive: true });
}

function authPanelHtml(mode) {
  return `
    <div class="auth-tabs">
      <button class="auth-tab-btn ${mode === "login" ? "active" : ""}" data-mode="login">Sign In</button>
      <button class="auth-tab-btn ${mode === "signup" ? "active" : ""}" data-mode="signup">Create Account</button>
    </div>
    <div id="auth-form-area"></div>
    ${state.meta?.oauth_google && !IS_NATIVE_APP ? `
      <div class="auth-divider"><span>or</span></div>
      <a class="oauth-btn google" href="/api/auth/google/start">
        <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
          <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/>
          <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"/>
          <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z"/>
          <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.59-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"/>
        </svg>
        Continue with Google
      </a>` : ""}`;
}

function wireAuthPanel(container, mode, onSuccess) {
  const renderForm = (m) => {
    const area = $("#auth-form-area");
    if (m === "login") {
      area.innerHTML = `<div class="form-grid">
        <input type="text" id="auth-identifier" placeholder="Username or email">
        <input type="password" id="auth-password" placeholder="Password">
        <button class="primary-btn" id="auth-submit">Sign In</button>
        <button class="link-btn" id="auth-forgot" type="button">Forgot password?</button>
        <div class="form-msg" id="auth-msg"></div>
      </div>`;
      $("#auth-submit").addEventListener("click", async () => {
        const msg = $("#auth-msg");
        msg.className = "form-msg"; msg.textContent = "";
        try {
          const user = await api("/api/auth/login", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ identifier: $("#auth-identifier").value, password: $("#auth-password").value }),
          });
          await onSuccess(user);
        } catch (e) { msg.className = "form-msg error"; msg.textContent = e.message; }
      });
      $("#auth-forgot").addEventListener("click", () => renderForgotForm());
    } else {
      area.innerHTML = `<div class="form-grid signup-form">
        <div class="field">
          <input type="text" id="auth-username" placeholder="Username (3-20 chars, letters/numbers/_)" autocomplete="username">
          <div class="field-hint" id="hint-username"></div>
        </div>
        <div class="field">
          <input type="email" id="auth-email" placeholder="Email" autocomplete="email">
          <div class="field-hint" id="hint-email"></div>
        </div>
        <div class="field">
          <input type="password" id="auth-password" placeholder="Password (8+ characters)" autocomplete="new-password">
          <div class="pw-strength" id="pw-strength"><div class="pw-strength-bar" id="pw-strength-bar"></div></div>
          <div class="field-hint" id="hint-password"></div>
        </div>
        <label class="terms-row">
          <input type="checkbox" id="auth-terms">
          <span>I agree to the Terms of Service and Privacy Policy</span>
        </label>
        <button class="primary-btn" id="auth-submit" disabled>Create Account</button>
        <div class="form-msg" id="auth-msg"></div>
      </div>`;

      const uField = $("#auth-username"), eField = $("#auth-email"), pField = $("#auth-password");
      const termsBox = $("#auth-terms"), submitBtn = $("#auth-submit");
      const uHint = $("#hint-username"), eHint = $("#hint-email"), pHint = $("#hint-password");
      const pwBar = $("#pw-strength-bar");
      const valid = { username: false, email: false, password: false };

      const setHint = (hintEl, fieldEl, text, ok) => {
        hintEl.textContent = text || "";
        hintEl.className = "field-hint" + (text ? (ok ? " ok" : " error") : "");
        fieldEl.classList.toggle("invalid", !!text && !ok);
        fieldEl.classList.toggle("valid", ok === true && !text);
      };

      const checkUsername = () => {
        const v = uField.value.trim();
        if (!v) { setHint(uHint, uField, "", false); valid.username = false; }
        else if (!/^[a-zA-Z0-9_]{3,20}$/.test(v)) {
          setHint(uHint, uField, "3-20 characters: letters, numbers, underscore only.", false);
          valid.username = false;
        } else { setHint(uHint, uField, "", true); uField.classList.add("valid"); valid.username = true; }
        updateSubmit();
      };

      const checkEmail = () => {
        const v = eField.value.trim();
        if (!v) { setHint(eHint, eField, "", false); valid.email = false; updateSubmit(); return; }
        const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
        if (!emailOk) {
          setHint(eHint, eField, "That doesn't look like a valid email address.", false);
          valid.email = false; updateSubmit(); return;
        }
        const suggestion = suggestEmailDomain(v);
        if (suggestion) {
          eHint.innerHTML = `Did you mean <button type="button" class="link-btn hint-fix" id="email-fix">${esc(suggestion)}</button>?`;
          eHint.className = "field-hint error";
          eField.classList.add("invalid"); eField.classList.remove("valid");
          $("#email-fix").addEventListener("click", () => { eField.value = suggestion; checkEmail(); });
          valid.email = true; // typo is a soft warning, not a hard block
        } else {
          setHint(eHint, eField, "", true); eField.classList.add("valid");
          valid.email = true;
        }
        updateSubmit();
      };

      const checkPassword = () => {
        const v = pField.value;
        const score = passwordStrength(v);
        pwBar.className = "pw-strength-bar" + (v ? ` s${score}` : "");
        pwBar.style.width = v ? `${(score + 1) * 20}%` : "0%";
        if (!v) { setHint(pHint, pField, "", false); valid.password = false; }
        else if (v.length < 8) {
          setHint(pHint, pField, "At least 8 characters.", false);
          valid.password = false;
        } else {
          const labels = ["Weak", "Weak", "Fair", "Good", "Strong"];
          setHint(pHint, pField, labels[score], true);
          pHint.classList.add("strength-label");
          valid.password = true;
        }
        updateSubmit();
      };

      const updateSubmit = () => {
        submitBtn.disabled = !(valid.username && valid.email && valid.password && termsBox.checked);
      };

      uField.addEventListener("input", checkUsername);
      eField.addEventListener("input", checkEmail);
      pField.addEventListener("input", checkPassword);
      termsBox.addEventListener("change", updateSubmit);

      submitBtn.addEventListener("click", async () => {
        const msg = $("#auth-msg");
        msg.className = "form-msg"; msg.textContent = "";
        submitBtn.classList.add("loading");
        submitBtn.disabled = true;
        try {
          const user = await api("/api/auth/signup", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              username: uField.value.trim(), email: eField.value.trim(), password: pField.value,
            }),
          });
          submitBtn.classList.remove("loading");
          await onSuccess(user);
          showToast(user.verification_email === "sent"
            ? "Welcome to Lineup Lab — check your email to verify your account. If it's not in your inbox, look in spam or junk."
            : "Welcome to Lineup Lab! We couldn't send your verification email just now — you can resend it from your account settings.",
            user.verification_email === "sent" ? "success" : "error");
        } catch (e) {
          submitBtn.classList.remove("loading");
          submitBtn.disabled = false;
          msg.className = "form-msg error"; msg.textContent = e.message;
          // shake whichever wrapper actually has that class defined (the
          // modal does; the full-screen gate doesn't need it, and a
          // missing target here would just no-op harmlessly)
          const shakeTarget = container.querySelector(".modal") || container;
          shakeTarget.classList.remove("shake"); void shakeTarget.offsetWidth; shakeTarget.classList.add("shake");
        }
      });
    }
  };

  const renderForgotForm = () => {
    const area = $("#auth-form-area");
    area.innerHTML = `<div class="form-grid">
      <div class="hint" style="margin:0 0 4px">Enter your account email — if it matches an account, a reset link is sent to it. The email may land in your spam or junk folder.</div>
      <input type="email" id="forgot-email" placeholder="Email">
      <button class="primary-btn" id="forgot-submit">Send Reset Link</button>
      <button class="link-btn" id="forgot-back" type="button">Back to sign in</button>
      <div class="form-msg" id="auth-msg"></div>
    </div>`;
    $("#forgot-submit").addEventListener("click", async () => {
      const msg = $("#auth-msg");
      msg.className = "form-msg"; msg.textContent = "";
      try {
        const res = await api("/api/auth/forgot-password", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: $("#forgot-email").value }),
        });
        msg.className = "form-msg success"; msg.textContent = res.message;
      } catch (e) { msg.className = "form-msg error"; msg.textContent = e.message; }
    });
    $("#forgot-back").addEventListener("click", () => renderForm("login"));
  };

  renderForm(mode);

  container.querySelectorAll(".auth-tab-btn").forEach((b) => b.addEventListener("click", () => {
    container.querySelectorAll(".auth-tab-btn").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    renderForm(b.dataset.mode);
  }));
}

function openAuthModal(mode) {
  const root = $("#auth-modal-root");
  root.innerHTML = `<div class="modal-backdrop auth-modal"><div class="modal auth-modal-shell">
    <button class="modal-close auth-modal-close" aria-label="Close">✕</button>
    <div class="auth-visual-panel">${authVisualPanelHtml("Real data. Real edge.",
      "No mock projections, no paid grading service — every number here comes from real NFL stats, real Next Gen Stats, and your real Sleeper league.")}</div>
    <div class="auth-form-panel">
      <div class="modal-header"><h2>Account</h2></div>
      ${authPanelHtml(mode)}
    </div>
  </div></div>`;
  syncModalScrollLock();
  wireAuthPanel(root, mode, onAuthSuccess);
  root.querySelector(".modal-close").addEventListener("click", closeAuthModal);
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeAuthModal();
  });
}

function openResetPasswordModal(token) {
  const root = $("#auth-modal-root");
  root.innerHTML = `<div class="modal-backdrop auth-modal"><div class="modal">
    <div class="modal-header"><h2>Reset Password</h2><button class="modal-close" aria-label="Close">✕</button></div>
    <div class="form-grid">
      <input type="password" id="reset-new-password" placeholder="New password (8+ characters)">
      <button class="primary-btn" id="reset-submit">Set New Password</button>
      <div class="form-msg" id="reset-msg"></div>
    </div>
  </div></div>`;
  syncModalScrollLock();
  $("#reset-submit").addEventListener("click", async () => {
    const msg = $("#reset-msg");
    msg.className = "form-msg"; msg.textContent = "";
    try {
      const user = await api("/api/auth/reset-password", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: $("#reset-new-password").value }),
      });
      await onAuthSuccess(user);
      showToast("Password updated — you're signed in.", "success");
    } catch (e) { msg.className = "form-msg error"; msg.textContent = e.message; }
  });
  root.querySelector(".modal-close").addEventListener("click", closeAuthModal);
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeAuthModal();
  });
}

async function onAuthSuccess(user) {
  state.user = user;
  closeAuthModal();
  renderAccountButton();
  await loadSettingsIntoState();
  if (state.tab === "settings") renderSettingsTab();
  if (state.tab === "myteam") loadMyTeam();
  if (state.tab === "news") loadNews();
}

async function loadSettingsIntoState() {
  if (!state.user) { state.settings = null; state.teams = []; state.leagueScoringDict = null; refreshScoringLeagueOption(); return; }
  try {
    state.settings = await api("/api/settings");
    ThemePicker.syncFromAccount(state.settings.theme);     // a new device picks up the account's team; a device with one keeps it
    const teamsRes = await api("/api/teams");
    state.teams = teamsRes.teams;
    const active = activeTeam();
    if (active) {
      state.leagueScoringDict = await fetchLeagueScoring(active);
    } else {
      state.leagueScoringDict = null;
    }
  } catch (e) { state.settings = null; state.teams = []; }
  refreshScoringLeagueOption();
  renderSidebarTeams();
}

// -------------------------------------------------------------- settings ----
function renderVerifyStatus() {
  const statusEl = $("#set-verify-status");
  const btn = $("#set-verify-resend");
  const msg = $("#verify-msg");
  msg.textContent = "";

  if (state.user.email_verified) {
    statusEl.innerHTML = `<span style="color:var(--accent)">✓ Email verified</span>`;
    btn.style.display = "none";
    return;
  }

  statusEl.innerHTML = `<span style="color:var(--avg)">Not verified</span>`;
  if (state.meta && state.meta.mail_configured) {
    btn.style.display = "";
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Sending…";
      try {
        await api("/api/auth/resend-verification", { method: "POST" });
        msg.className = "form-msg success"; msg.textContent = "Verification email sent — check your inbox, and your spam or junk folder if it's not there.";
      } catch (e) {
        msg.className = "form-msg error"; msg.textContent = e.message;
      } finally {
        btn.disabled = false; btn.textContent = "Resend Email";
      }
    };
  } else {
    btn.style.display = "none";
    msg.textContent = "Email sending isn't configured on this server yet (see .env.example).";
  }
}

// ---------------------------------------------------------------- toast ----
function showToast(text, kind) {
  const root = $("#toast-root");
  const t = el("div", `toast ${kind}`);
  t.innerHTML = `<span>${esc(text)}</span><button type="button" aria-label="Dismiss">✕</button>`;

  const AUTO_DISMISS_MS = 5000;
  let timer;
  const dismiss = () => {
    t.classList.add("leaving");
    // Don't gate actual removal on animationend firing — a near-zero
    // animation duration (prefers-reduced-motion, or some automated/headless
    // environments) can skip the event entirely, which would otherwise
    // leave the toast stuck in the DOM forever. The CSS transition still
    // plays for anyone with motion enabled; this timeout is just the
    // guaranteed backstop.
    setTimeout(() => t.remove(), 220);
  };
  const arm = () => { timer = setTimeout(dismiss, AUTO_DISMISS_MS); };
  const disarm = () => clearTimeout(timer);

  t.querySelector("button").addEventListener("click", () => { disarm(); dismiss(); });
  t.addEventListener("mouseenter", disarm);
  t.addEventListener("mouseleave", arm);
  arm();

  root.appendChild(t);
}

function handleUrlRedirects() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("verified")) {
    const ok = params.get("verified") === "1";
    showToast(ok ? "Email verified — you're all set." : "That verification link is invalid or expired.", ok ? "success" : "error");
    params.delete("verified");
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? `?${params}` : ""));
  }
  if (params.has("reset_token")) {
    const token = params.get("reset_token");
    params.delete("reset_token");
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? `?${params}` : ""));
    openResetPasswordModal(token);
  }
  if (params.has("oauth")) {
    showToast("Signed in.", "success");
    params.delete("oauth");
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? `?${params}` : ""));
  }
  if (params.has("oauth_error")) {
    showToast("Sign-in didn't go through — try again.", "error");
    params.delete("oauth_error");
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? `?${params}` : ""));
  }
}

function renderSettingsTab() {
  ThemePicker.render($("#team-picker"));
  const out = $("#settings-logged-out");
  const inArea = $("#settings-logged-in");
  if (!state.user) {
    out.style.display = ""; inArea.style.display = "none";
    $("#settings-signin-btn").onclick = () => openAuthModal("signup");
    return;
  }
  out.style.display = "none"; inArea.style.display = "";

  $("#set-username").textContent = state.user.username;
  $("#set-email").textContent = state.user.email;
  renderVerifyStatus();

  $("#settings-signout").onclick = doSignOut;
  $("#settings-open-draft").onclick = () => switchTab("draft");

  $("#cp-submit").onclick = async () => {
    const msg = $("#cp-msg");
    msg.className = "form-msg"; msg.textContent = "";
    try {
      await api("/api/auth/change-password", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: $("#cp-current").value, new_password: $("#cp-new").value }),
      });
      msg.className = "form-msg success"; msg.textContent = "Password updated.";
      $("#cp-current").value = ""; $("#cp-new").value = "";
    } catch (e) { msg.className = "form-msg error"; msg.textContent = e.message; }
  };

  // OAuth-only accounts have no password; the server only asks for one when it exists.
  $("#del-password").style.display = state.user.has_password === false ? "none" : "";
  $("#del-submit").onclick = async () => {
    const msg = $("#del-msg");
    msg.className = "form-msg"; msg.textContent = "";
    if (!confirm("Permanently delete your Lineup Lab account? This can't be undone.")) return;
    try {
      await api("/api/auth/delete-account", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: $("#del-password").value, confirm: $("#del-confirm").value }),
      });
      $("#del-password").value = ""; $("#del-confirm").value = "";
      await doSignOut();
      showToast("Your account has been deleted.", "success");
    } catch (e) { msg.className = "form-msg error"; msg.textContent = e.message; }
  };

  renderTeamsList();

  $("#set-espn-swid").value = "";
  $("#set-espn-s2").value = "";
  $("#set-espn-swid").placeholder = state.settings.espn_swid_set ? "•••••••• (already set — leave blank to keep)" : "SWID cookie (private leagues only)";
  $("#set-espn-s2").placeholder = state.settings.espn_s2_set ? "•••••••• (already set — leave blank to keep)" : "espn_s2 cookie (private leagues only)";
  $("#set-espn-save").onclick = async () => {
    const updates = {};
    if ($("#set-espn-swid").value) updates.espn_swid = $("#set-espn-swid").value;
    if ($("#set-espn-s2").value) updates.espn_s2 = $("#set-espn-s2").value;
    state.settings = await api("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(updates),
    });
    $("#set-espn-swid").value = ""; $("#set-espn-s2").value = "";
    $("#set-espn-swid").placeholder = state.settings.espn_swid_set ? "•••••••• (already set — leave blank to keep)" : "SWID cookie (private leagues only)";
    $("#set-espn-s2").placeholder = state.settings.espn_s2_set ? "•••••••• (already set — leave blank to keep)" : "espn_s2 cookie (private leagues only)";
  };

  renderScoringPills();

  $("#settings-season-info").textContent = state.meta ? `Currently serving ${state.meta.season} season data (auto-upgrades the moment a newer season is published).` : "";
  $("#settings-refresh").onclick = async () => {
    const msg = $("#refresh-msg");
    msg.textContent = "Refreshing…";
    try {
      await api("/api/refresh", { method: "POST" });
      msg.className = "form-msg success"; msg.textContent = "Data refreshed.";
      loadBoard();
    } catch (e) { msg.className = "form-msg error"; msg.textContent = e.message; }
  };
}

// ---- multi-team switcher: list connected teams as cards, plus a
// "connect another league" flow that accepts a pasted URL or bare ID ----
function renderTeamsList() {
  const list = $("#set-teams-list");
  if (!state.teams.length) {
    list.innerHTML = `<div class="hint">No leagues connected yet.</div>`;
  } else {
    list.innerHTML = state.teams.map((t) => `
      <div class="team-card${t.active ? " active" : ""}" data-team-id="${esc(t.id)}">
        ${t.avatar_url ? `<img src="${proxyImg(t.avatar_url)}" data-fb-hide="1" alt="">` : `<div class="team-card-noavatar">🏈</div>`}
        <div class="team-card-info">
          <div class="team-card-name">${esc(t.team_name)}</div>
          <div class="team-card-league">${esc(t.league_name || t.league_id)}</div>
        </div>
        ${t.active ? `<span class="tag soft">ACTIVE</span>` : `<button class="pill" data-activate="${esc(t.id)}">Switch</button>`}
        <button class="chip-x" data-remove="${esc(t.id)}" title="Remove" aria-label="Remove ${esc(t.team_name)}">✕</button>
      </div>`).join("");

    list.querySelectorAll("button[data-activate]").forEach((b) => b.addEventListener("click", async () => {
      const res = await api(`/api/teams/${b.dataset.activate}/activate`, { method: "POST" });
      state.teams = res.teams;
      const active = activeTeam();
      state.leagueScoringDict = await fetchLeagueScoring(active);
      refreshScoringLeagueOption();
      renderTeamsList();
      renderScoringPills();
      showToast(`Switched to "${active ? active.team_name : ""}".`, "success");
    }));
    list.querySelectorAll("button[data-remove]").forEach((b) => b.addEventListener("click", async () => {
      const res = await api(`/api/teams/${b.dataset.remove}`, { method: "DELETE" });
      state.teams = res.teams;
      const active = activeTeam();
      state.leagueScoringDict = null;
      state.leagueScoringDict = await fetchLeagueScoring(active);
      refreshScoringLeagueOption();
      renderTeamsList();
      renderScoringPills();
    }));
  }

  const connectArea = $("#set-connect-results");
  connectArea.innerHTML = "";
  $("#set-connect-input").value = "";

  let connectPlatform = "sleeper";
  $("#set-connect-platform").querySelectorAll(".pill").forEach((p) => {
    p.classList.toggle("active", p.dataset.platform === connectPlatform);
    p.onclick = () => {
      connectPlatform = p.dataset.platform;
      $("#set-connect-platform").querySelectorAll(".pill").forEach((x) => x.classList.toggle("active", x === p));
      $("#set-connect-input").placeholder = connectPlatform === "espn"
        ? "Paste ESPN league URL or ID" : "Paste Sleeper league URL or ID";
      $("#set-espn-disclaimer").style.display = connectPlatform === "espn" ? "" : "none";
      $("#set-espn-public-note").style.display = connectPlatform === "espn" ? "" : "none";
      connectArea.innerHTML = "";
    };
  });

  $("#set-connect-btn").onclick = async () => {
    const raw = $("#set-connect-input").value.trim();
    if (!raw) return;
    const btn = $("#set-connect-btn");
    btn.disabled = true; btn.textContent = "Loading…";
    connectArea.innerHTML = "";
    try {
      const snap = await api("/api/teams/lookup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league_id_or_url: raw, platform: connectPlatform }),
      });
      connectArea.innerHTML = `<div class="hint">Which team is yours in "${esc(snap.league_name)}"?</div>` +
        snap.teams.map((t) => `<div class="league-team-row">
            <span>${t.avatar_url ? `<img class="inline-avatar" src="${proxyImg(t.avatar_url)}" data-fb-hide="1" alt="">` : ""}
              ${esc(t.team_name)}${t.owner ? " (" + esc(t.owner) + ")" : ""} — ${esc(t.player_ids.length)} rostered</span>
            <button class="pill" data-roster="${esc(t.roster_id)}" data-name="${esc(t.team_name)}" data-avatar="${safeUrl(t.avatar_url)}">This is me</button>
          </div>`).join("");
      connectArea.querySelectorAll("button[data-roster]").forEach((b) => {
        b.addEventListener("click", async () => {
          const team = await api("/api/teams", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              league_id: snap.league_id, league_name: snap.league_name,
              roster_id: parseInt(b.dataset.roster, 10), team_name: b.dataset.name, avatar_url: b.dataset.avatar || null,
              platform: connectPlatform,
            }),
          });
          const teamsRes = await api("/api/teams");
          state.teams = teamsRes.teams;
          state.leagueScoringDict = snap.scoring;
          refreshScoringLeagueOption();
          renderTeamsList();
          renderScoringPills();
          showToast(`Connected "${team.team_name}".`, "success");
        });
      });
    } catch (e) {
      connectArea.innerHTML = `<div class="form-msg error">${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "Connect";
    }
  };
}

function renderScoringPills() {
  const group = $("#set-scoring-pills");
  const options = [["", "PPR"], ["half_ppr", "Half PPR"], ["standard", "Standard"], ["te_premium", "TE Premium"]];
  if (activeTeam()) options.push(["league", "My League"]);
  group.innerHTML = "";
  options.forEach(([val, label]) => {
    const b = el("button", "pill" + (state.scoring === val ? " active" : ""), esc(label));
    b.addEventListener("click", async () => {
      state.scoring = val;
      saveScoring();
      group.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      b.classList.add("active");
      $("#scoring-select").value = val;
      if (val !== "league") {
        await api("/api/settings", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scoring_preset: val }),
        });
      }
      loadBoard();
    });
    group.appendChild(b);
  });
}

// --------------------------------------------------------------- init -----
function initSearch() {
  let debounce;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.search = e.target.value;
      loadBoard();
    }, 150);
  });
}

async function initMeta() {
  const meta = await api("/api/meta");
  state.meta = meta;
  // The "which season is stats data actually from" explanation (it's the
  // most recent one with games actually played, which can lag a newer
  // live league season) used to show as a sidebar badge — removed from
  // there, but the same real explanation is still surfaced in Settings
  // (see renderSettingsTab's #settings-season-info) for anyone who wants
  // to know exactly what's powering the numbers.
  const oppSelect = $("#opp-select");
  meta.teams.forEach((t) => {
    const opt = el("option");
    opt.value = t;
    opt.textContent = t;
    oppSelect.appendChild(opt);
  });
  oppSelect.addEventListener("change", () => {
    state.opp = oppSelect.value;
    loadBoard();
  });
}

// -------------------------------------------------------------- gate -----
// Sign-in is mandatory: nothing behind it renders until there's a real
// signed-in user. A signed-in user with no connected league gets one more
// full-screen step (skippable) before the app itself appears.
//
// Both functions below also clear .auth-pending (see index.html's
// #boot-veil / style.css) — real bug found in a redesign pass: main()
// awaits two sequential API calls (/api/meta, then /api/auth/me) before
// either of these ever runs, and #gate-root itself starts display:none,
// so there was a real window on every load where the full sidebar + tab
// shell sat there visible and clickable by default, for signed-in and
// signed-out visitors alike, before this function ever got a chance to
// decide which state should actually show.
function showGate() {
  document.documentElement.classList.remove("auth-pending");
  document.body.classList.remove("auth-pending");
  $("#gate-root").style.display = "flex";
  document.documentElement.classList.add("gate-locked");
  document.body.classList.add("gate-locked");
}
function hideGate() {
  document.documentElement.classList.remove("auth-pending");
  document.body.classList.remove("auth-pending");
  $("#gate-root").style.display = "none";
  document.documentElement.classList.remove("gate-locked");
  document.body.classList.remove("gate-locked");
}

function renderGateAuth(mode) {
  showGate();
  $("#gate-headline").textContent = "Real data. Real edge.";
  $("#gate-subcopy").textContent = "No mock projections, no paid grading service — every number here comes from real NFL stats, real Next Gen Stats, and your real Sleeper league.";
  const panel = $("#gate-panel");
  panel.innerHTML = `<div class="gate-form-wrap">
    <div class="gate-mobile-brand"><img src="/icons/icon-192.png" alt=""><span>Lineup Lab</span></div>
    <div class="modal-header"><h2>Welcome</h2></div>
    ${authPanelHtml(mode)}
  </div>`;
  wireAuthPanel(panel, mode, onGateAuthSuccess);
}

async function onGateAuthSuccess(user) {
  state.user = user;
  renderAccountButton();
  await loadSettingsIntoState();
  await proceedPastGate();
}

// The single decision point: signed out -> auth step; signed in with no
// league -> connect step; signed in with a league -> reveal the app.
// Every gate success path (password login, signup, Google, connect a
// league, or skipping that step) funnels back through here.
async function proceedPastGate() {
  if (!state.user) { renderGateAuth("login"); return; }
  if (!state.teams.length) { renderGateConnectLeague(); return; }
  hideGate();
  initScoringSelect();
  switchTab(DEFAULT_TAB);
}

function renderGateConnectLeague() {
  showGate();
  $("#gate-headline").textContent = "Sync your league";
  $("#gate-subcopy").textContent = "Paste your Sleeper league's URL (or just its ID) and pick which team is yours — My Team, Waivers, Trade, and News all follow it from here.";
  const panel = $("#gate-panel");
  panel.innerHTML = `<div class="gate-form-wrap">
    <div class="gate-mobile-brand"><img src="/icons/icon-192.png" alt=""><span>Lineup Lab</span></div>
    <div class="modal-header"><h2>Connect Your League</h2></div>
    <div class="form-grid">
      <input type="text" id="gate-connect-input" placeholder="Paste Sleeper league URL or ID" autocomplete="off">
      <button class="primary-btn" id="gate-connect-btn">Connect</button>
    </div>
    <div id="gate-connect-results"></div>
    <button class="link-btn" id="gate-skip-league" type="button">Skip for now</button>
  </div>`;

  const resultsArea = $("#gate-connect-results");
  $("#gate-connect-btn").addEventListener("click", async () => {
    const raw = $("#gate-connect-input").value.trim();
    if (!raw) return;
    const btn = $("#gate-connect-btn");
    btn.disabled = true; btn.textContent = "Loading…";
    resultsArea.innerHTML = "";
    try {
      const snap = await api("/api/teams/lookup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league_id_or_url: raw }),
      });
      resultsArea.innerHTML = `<div class="hint">Which team is yours in "${esc(snap.league_name)}"?</div>` +
        snap.teams.map((t) => `<div class="league-team-row">
            <span>${t.avatar_url ? `<img class="inline-avatar" src="${proxyImg(t.avatar_url)}" data-fb-hide="1" alt="">` : ""}
              ${esc(t.team_name)}${t.owner ? " (" + esc(t.owner) + ")" : ""} — ${esc(t.player_ids.length)} rostered</span>
            <button class="pill" data-roster="${esc(t.roster_id)}" data-name="${esc(t.team_name)}" data-avatar="${safeUrl(t.avatar_url)}">This is me</button>
          </div>`).join("");
      resultsArea.querySelectorAll("button[data-roster]").forEach((b) => {
        b.addEventListener("click", async () => {
          const team = await api("/api/teams", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              league_id: snap.league_id, league_name: snap.league_name,
              roster_id: parseInt(b.dataset.roster, 10), team_name: b.dataset.name, avatar_url: b.dataset.avatar || null,
            }),
          });
          const teamsRes = await api("/api/teams");
          state.teams = teamsRes.teams;
          state.leagueScoringDict = snap.scoring;
          showToast(`Connected "${team.team_name}".`, "success");
          await proceedPastGate();
        });
      });
    } catch (e) {
      resultsArea.innerHTML = `<div class="form-msg error">${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "Connect";
    }
  });
  $("#gate-skip-league").addEventListener("click", async () => {
    hideGate();
    initScoringSelect();
    switchTab(DEFAULT_TAB);
  });
}

async function main() {
  // A password-reset link lands here already carrying its own modal (via
  // handleUrlRedirects below) — don't stack the mandatory gate on top of
  // that flow, whatever the current sign-in state happens to be.
  const cameViaResetLink = new URLSearchParams(window.location.search).has("reset_token");

  // Safety net for the new .auth-pending boot veil (see index.html/
  // style.css): every REAL path below reaches showGate()/hideGate(),
  // which clear it immediately once the actual sign-in state is known —
  // but if anything in between throws (a real network failure on
  // initMeta(), say), this `finally` guarantees the veil still comes down
  // instead of leaving the page stuck on "Loading Lineup Lab…" forever
  // with no way out. Worse-looking (whatever was underneath, un-gated)
  // beats a permanently frozen spinner.
  try {
    handleUrlRedirects();
    initSidebar();
    initTabs();
    initPosPills();
    initWaiverControls();
    initSearch();
    initStartSit();
    initTrade();
    initTradeFinder();
    initCompareTray();
    initNews();
    initLiveScores();
    await initMeta();

    try {
      state.user = await api("/api/auth/me");
    } catch (e) {
      state.user = null;
    }
    renderAccountButton();
    await loadSettingsIntoState();

    if (cameViaResetLink) {
      // Same reasoning as showGate()/hideGate() — this branch is real
      // "reveal the app" too, just without the gate on top of it.
      document.documentElement.classList.remove("auth-pending");
      document.body.classList.remove("auth-pending");
      initScoringSelect();
      switchTab(DEFAULT_TAB);
      return;
    }
    await proceedPastGate();
  } finally {
    document.documentElement.classList.remove("auth-pending");
    document.body.classList.remove("auth-pending");
  }
}

main();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

// ---------------------------------------------------------- count-up ----
// Headline numbers (My Team's projected total, a Start/Sit card's proj)
// animate up from 0 the moment they land in the DOM, instead of just
// appearing — self-contained, so it works regardless of which function
// rendered the element and needs no changes to those render functions.
const COUNTUP_SELECTOR = ".mt-total, .ss-proj-num, .trade-verdict .big";

function animateCountUp(el) {
  if (el.dataset.counted) return;
  // Only the element's own leading text node gets touched — a sibling
  // label element (e.g. .ss-proj-num's "proj pts" <span>) has to survive
  // untouched. Reading/writing el.textContent here (the original
  // approach) flattens the whole element, silently deleting any child
  // element and its spacing along with it — found for real on the
  // Start/Sit cards ("19.4proj pts", no gap) once actually rendered
  // in-browser, not caught by testing the HTML string in isolation.
  const textNode = Array.prototype.find.call(el.childNodes, (n) => n.nodeType === 3 && n.textContent.trim());
  if (!textNode) return;
  const raw = textNode.textContent;
  const match = raw.match(/-?[\d,]+\.?\d*/);
  if (!match) return;
  const target = parseFloat(match[0].replace(/,/g, ""));
  if (!isFinite(target)) return;
  el.dataset.counted = "1";
  const decimals = (match[0].split(".")[1] || "").length;
  const prefix = raw.slice(0, match.index);
  const suffix = raw.slice(match.index + match[0].length);
  const dur = 650;
  const start = performance.now();
  (function frame(now) {
    const t = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    textNode.textContent = prefix + (target * eased).toFixed(decimals) + suffix;
    if (t < 1) requestAnimationFrame(frame);
  })(start);
}

if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  new MutationObserver((muts) => {
    for (const m of muts) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.matches?.(COUNTUP_SELECTOR)) animateCountUp(node);
        node.querySelectorAll?.(COUNTUP_SELECTOR).forEach(animateCountUp);
      }
    }
  }).observe(document.getElementById("app"), { childList: true, subtree: true });
}
