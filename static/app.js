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
  return `src="${proxyImg(p.headshot_url)}" data-fb="${initialsAvatarUri(p.player_display_name)}" onerror="this.onerror=null;this.src=this.dataset.fb"`;
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
  pos: "QB",
  opp: "",
  search: "",
  meta: null,
  user: null,
  settings: null,
  teams: [],                 // connected Sleeper teams (multi-team support)
  leagueScoringDict: null,   // cached scoring dict of the active team's league
  scoring: localStorage.getItem("eb_scoring") || "",   // "" | "half_ppr" | "standard" | "league"
  startsit: [],
  tradeA: [],
  tradeB: [],
  shopRoster: [],             // my own roster, for the "pick a player to shop" trade finder picker
  shopSelected: new Set(),    // player_ids currently selected to shop
  newsScope: "team",          // "team" | "league" | "opponent"
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
  return res.json();
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
const TAB_IDS = ["board", "myteam", "draft", "startsit", "trade", "waivers", "news", "settings"];

function switchTab(tab) {
  document.querySelectorAll(".nav-item[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  state.tab = tab;
  TAB_IDS.forEach((t) => { $(`#tab-${t}`).style.display = t === tab ? "" : "none"; });
  const activeSection = $(`#tab-${tab}`);
  activeSection.classList.remove("tab-fade-in");
  void activeSection.offsetWidth; // force reflow so the animation replays every switch
  activeSection.classList.add("tab-fade-in");
  if (tab !== "draft") stopDraftPolling();
  if (tab === "waivers") loadWaivers();
  if (tab === "myteam") loadMyTeam();
  if (tab === "draft") loadDraftTab();
  if (tab === "startsit") loadStartSitTab();
  if (tab === "news") loadNews();
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
  });

  $("#mobile-menu-btn").addEventListener("click", () => {
    document.body.classList.add("mobile-drawer-open");
    document.documentElement.classList.add("mobile-drawer-open");
  });
  $("#sidebar-backdrop").addEventListener("click", closeMobileDrawer);

  $("#sidebar-add-league").addEventListener("click", () => {
    switchTab("settings");
    setTimeout(() => {
      const input = $("#set-connect-input");
      input?.scrollIntoView({ behavior: "smooth", block: "center" });
      input?.focus();
    }, 150); // after switchTab's own scroll-to-top + tab render
  });
}

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
    <div class="sidebar-team-row${t.active ? " active" : ""}" data-team-id="${esc(t.id)}" title="${esc(t.team_name)}">
      ${t.avatar_url ? `<img src="${proxyImg(t.avatar_url)}" onerror="this.outerHTML='<span class=&quot;team-emoji&quot;>🏈</span>'" alt="">` : `<span class="team-emoji">🏈</span>`}
      <span class="st-name">${esc(t.team_name)}</span>
    </div>`).join("");
  list.querySelectorAll(".sidebar-team-row").forEach((row) => {
    row.addEventListener("click", async () => {
      if (row.classList.contains("active")) return;
      const res = await api(`/api/teams/${row.dataset.teamId}/activate`, { method: "POST" });
      state.teams = res.teams;
      const active = activeTeam();
      state.leagueScoringDict = null;
      state.shopRoster = [];           // stale roster for the old team — refetch on next Trade/Start-Sit tab visit
      state.shopSelected = new Set();
      state.startsit = [];
      state.tradeA = []; state.tradeB = [];
      if (active) {
        try { state.leagueScoringDict = (await api(`/api/sleeper/${active.league_id}`)).scoring; } catch (e) {}
      }
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
  POSITIONS.forEach((pos) => {
    const b1 = el("button", "pill" + (pos === state.pos ? " active" : ""), pos);
    b1.addEventListener("click", () => {
      state.pos = pos;
      boardPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      b1.classList.add("active");
      loadBoard();
    });
    boardPills.appendChild(b1);

    const b2 = el("button", "pill" + (pos === "QB" ? " active" : ""), pos);
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

function playerCellHtml(p) {
  return `<div class="player-cell">
      <img ${headshotAttrs(p)} alt="">
      <div><div class="player-name">${esc(p.player_display_name) || "—"}</div><div class="player-team">${esc(p.recent_team)}</div></div>
    </div>`;
}

function renderBoardHead(cols, showProj) {
  const head = $("#board-head");
  let html = `<th></th><th>Player</th><th>SCORE</th><th>FORM</th><th>FPTS/G</th>`;
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
      const tr = el("tr");
      let html = `<td class="rank-cell">${esc(p.rank)}</td>`;
      html += `<td>${playerCellHtml(p)}</td>`;
      html += `<td>${scoreCell(p.SCORE)}</td>`;
      html += `<td>${formCell(p.FORM)}</td>`;
      html += `<td>${FMT.d1(p.fpts_per_game)}</td>`;
      cols.forEach((c) => {
        html += `<td${c.mobileHide ? ' class="hide-mobile"' : ""}>${c.fmt(p[c.key])}</td>`;
      });
      if (showProj) html += `<td>${FMT.d1(p.PROJ)}</td>`;
      tr.innerHTML = html;
      tr.addEventListener("click", () => openPlayerModal(p.player_id, state.opp));
      body.appendChild(tr);
    });
}

async function loadBoard() {
  const loading = $("#board-loading");
  loading.style.display = "";
  loading.innerHTML = skeletonRows(10, 3);
  $("#board-table").style.display = "none";
  try {
    const url = `/api/board?pos=${state.pos}${state.opp ? `&opp=${state.opp}` : ""}${scoringQS()}`;
    const data = await api(url);
    const cols = TABLE_COLS[state.pos] || [];
    renderBoardHead(cols, !!state.opp);
    renderBoardRows(data.players, cols, !!state.opp);
    $("#board-hint").textContent = state.opp
      ? `PROJ = projected points vs ${state.opp} this week — a real, multi-stat matchup read (run D, pass D, pressure), adjusted for recent form and your scoring.`
      : `SCORE = weighted 0–100 value from real stats + Next Gen Stats. Pick an opponent above to see matchup-adjusted projections.`;
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
  $("#modal-root").innerHTML = "";
  syncModalScrollLock();
}

async function openPlayerModal(playerId, opp) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal"><div class="loading">Loading…</div></div></div>`;
  syncModalScrollLock();
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeModal();
  });

  let p;
  try {
    const oppQS = opp ? `&opp=${opp}` : "";
    p = await api(`/api/player/${playerId}?${scoringQS().replace(/^&/, "")}${oppQS}`);
  } catch (e) {
    root.querySelector(".modal").innerHTML = `<div class="empty">Couldn't load player.</div>`;
    return;
  }

  const sections = (DETAIL_METRICS[p.position] || []).map(([label, metrics]) => {
    const tiles = metrics.map(([key, mlabel, fmt]) => `
      <div class="metric-tile"><div class="label">${esc(mlabel)}</div><div class="value">${fmt(p[key])}</div></div>
    `).join("");
    return `<div class="section-label">${esc(label)}</div><div class="metric-grid">${tiles}</div>`;
  }).join("");

  const weeks = p.weekly_log || [];
  const maxFp = Math.max(1, ...weeks.map((w) => w.fpts || 0));
  const bars = weeks.map((w) => {
    const h = Math.max(2, Math.round((Math.max(0, w.fpts) / maxFp) * 100));
    return `<div class="bar" style="height:${h}%"><div class="wk-label">${esc(w.week)}</div></div>`;
  }).join("");

  const nextOpp = p.next_opponent ? `Next: vs ${esc(p.next_opponent)} (Wk ${esc(p.next_week)})` : "";
  const matchupLine = p.matchup_factor != null
    ? `<div class="metric-tile"><div class="label">Matchup vs ${esc(p.matchup_opponent)}</div><div class="value">${p.matchup_factor.toFixed(2)}x</div></div>` : "";

  root.innerHTML = `<div class="modal-backdrop"><div class="modal">
    <div class="modal-header">
      <img ${headshotAttrs(p)} alt="">
      <div>
        <h2>${esc(p.player_display_name)}</h2>
        <div class="muted">${esc(p.position)} · ${esc(p.recent_team)} ${nextOpp ? "· " + nextOpp : ""}</div>
      </div>
      <button class="modal-close">✕</button>
    </div>
    <div class="metric-grid">
      <div class="metric-tile"><div class="label">SCORE</div><div class="value" style="color:var(--accent)">${FMT.d1(p.SCORE)}</div></div>
      <div class="metric-tile"><div class="label">FORM</div><div class="value">${formCell(p.FORM)}</div></div>
      <div class="metric-tile"><div class="label">FPTS/G</div><div class="value">${FMT.d1(p.fpts_per_game)}</div></div>
      ${matchupLine}
    </div>
    ${sections}
    <div class="section-label">Weekly Fantasy Points</div>
    <div class="weeklog">${bars || '<span class="muted">No games logged yet.</span>'}</div>
  </div></div>`;

  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) closeModal();
  });
  root.querySelector(".modal-close").addEventListener("click", closeModal);
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
function renderStartSitChips() {
  const row = $("#startsit-chips");
  row.innerHTML = "";
  state.startsit.forEach((p) => {
    const chip = el("div", "chip");
    chip.innerHTML = `<img ${headshotAttrs(p)} alt="">
      <span>${esc(p.player_display_name)}</span>
      <select class="opp-select"><option value="">vs…</option>${state.meta.teams.map((t) => `<option value="${esc(t)}" ${p.opp === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <button class="chip-x">✕</button>`;
    chip.querySelector(".opp-select").addEventListener("change", (e) => { p.opp = e.target.value; });
    chip.querySelector(".chip-x").addEventListener("click", () => {
      state.startsit = state.startsit.filter((x) => x.player_id !== p.player_id);
      renderStartSitChips();
      $(`#startsit-roster-picker .shop-chip[data-pid="${p.player_id}"]`)?.classList.remove("selected");
    });
    row.appendChild(chip);
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

function startSitRationaleHtml(players) {
  const valid = players.filter((p) => !p.error && p.PROJ != null).sort((a, b) => b.PROJ - a.PROJ);
  if (valid.length < 2) return "";
  const top = valid[0];
  const paras = valid.slice(1).map((p) => {
    const diff = (top.PROJ - p.PROJ).toFixed(1);
    const bits = [];
    let scoreCaveat = "";
    if (top.SCORE != null && p.SCORE != null && Math.abs(top.SCORE - p.SCORE) >= 3) {
      if (top.SCORE > p.SCORE) {
        bits.push(`a higher SCORE (${FMT.d1(top.SCORE)} vs ${FMT.d1(p.SCORE)})`);
      } else {
        // PROJ favors top despite a lower season-long SCORE — worth flagging as
        // an upset call, not silently claiming a "higher SCORE" that isn't true.
        scoreCaveat = ` That's despite a lower season-long SCORE (${FMT.d1(top.SCORE)} vs ${FMT.d1(p.SCORE)}) — this week's projection is matchup/form-driven.`;
      }
    }
    const trend = formTrendPhrase(top.FORM);
    if (trend) bits.push(`${esc(trend)} (FORM ${top.FORM >= 0 ? "+" : ""}${FMT.d1(top.FORM)}%)`);
    if (top.matchup_tag && top.opponent) bits.push(`a ${esc(top.matchup_tag).toLowerCase()} matchup vs ${esc(top.opponent)}`);
    const why = bits.length ? ` Backed by ${bits.join(" and ")}.` : "";
    return `<p>Start <strong>${esc(top.player_display_name)}</strong> over <strong>${esc(p.player_display_name)}</strong> — projected for ${FMT.d1(top.PROJ)} pts vs ${FMT.d1(p.PROJ)} (+${diff}).${why}${scoreCaveat}</p>`;
  });
  return `<div class="ss-rationale"><div class="ss-rationale-label">WHY</div>${paras.join("")}</div>`;
}

function injuryFlagHtml(status) {
  if (!status) return "";
  const mild = status === "Questionable";
  return ` <span class="injury-flag${mild ? " questionable" : ""}">${esc(status.toUpperCase())}</span>`;
}

function statChipsHtml(p) {
  const chips = [];
  if (p.snap_pct != null) chips.push(`Snap ${Math.round(p.snap_pct * 100)}%`);
  if (p.redzone_touches != null) chips.push(`RZ touches ${p.redzone_touches}`);
  if (p.SCORE != null) chips.push(`SCORE ${FMT.d1(p.SCORE)}`);
  return chips.map((c) => `<span class="ss-stat-chip">${esc(c)}</span>`).join("");
}

// Every card's floor/ceiling bar shares one scale across the whole
// comparison so the bars are actually comparable at a glance, not just
// individually accurate.
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
    <div class="ss-range-labels"><span>Floor ${FMT.d1(floor)}</span><span>Ceiling ${FMT.d1(ceiling)}</span></div>`;
}

function startSitCardHtml(p, scaleMin, scaleMax, i) {
  const tierClass = "tier-" + (p.tier || "borderline").toLowerCase();
  return `<div class="ss-card ${tierClass}" data-pid="${esc(p.player_id)}" style="animation-delay:${i * 60}ms">
    <div class="ss-card-top">
      <img ${headshotAttrs(p)} alt="">
      <div>
        <div class="ss-name">${esc(p.player_display_name)}${injuryFlagHtml(p.injury_status)}</div>
        <div class="ss-meta">${esc(p.position)} · ${esc(p.recent_team)}${p.opponent ? " · vs " + esc(p.opponent) + " (" + esc(p.matchup_tag) + ")" : " · rest-of-season blend"}</div>
      </div>
      <div class="ss-tier-badge ${tierClass}">${esc(p.tier || "—")}</div>
    </div>
    <div class="ss-proj-row">
      <div class="ss-proj-num">${FMT.d1(p.PROJ)}<span class="ss-proj-lbl">proj pts</span></div>
      <div class="ss-confidence">${p.confidence != null ? p.confidence + "% confidence" : ""}</div>
    </div>
    ${rangeBarHtml(p, scaleMin, scaleMax)}
    <div class="ss-stat-chips">${statChipsHtml(p)}</div>
  </div>`;
}

async function runStartSit() {
  const opponents = {};
  state.startsit.forEach((p) => { if (p.opp) opponents[p.player_id] = p.opp; });
  const body = { player_ids: state.startsit.map((p) => p.player_id), opponents, scoring: scoringDict() };
  const results = $("#startsit-results");
  results.innerHTML = `<div class="loading">Comparing…</div>`;
  try {
    const data = await api("/api/startsit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const sorted = data.players.slice().sort((a, b) => (b.PROJ || -999) - (a.PROJ || -999));
    const valid = sorted.filter((p) => !p.error);
    const scaleMin = Math.min(0, ...valid.map((p) => (p.floor != null ? p.floor : p.PROJ)));
    const scaleMax = Math.max(1, ...valid.map((p) => (p.ceiling != null ? p.ceiling : p.PROJ)));

    results.innerHTML = startSitRationaleHtml(sorted);
    let i = 0;
    sorted.forEach((p) => {
      if (p.error) {
        results.insertAdjacentHTML("beforeend", `<div class="result-card"><span>${esc(p.player_id)}: ${esc(p.error)}</span></div>`);
        return;
      }
      results.insertAdjacentHTML("beforeend", startSitCardHtml(p, scaleMin, scaleMax, i++));
    });
    results.querySelectorAll(".ss-card").forEach((card) => {
      const p = valid.find((x) => x.player_id === card.dataset.pid);
      card.addEventListener("click", () => openPlayerModal(card.dataset.pid, p?.opponent));
    });
  } catch (e) {
    results.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
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
}

$("#startsit-gate-btn")?.addEventListener("click", () => switchTab("settings"));

function initStartSit() {
  $("#startsit-compare").addEventListener("click", runStartSit);
}

// --------------------------------------------------------------- trade ----
function renderTradeChips(side) {
  const listKey = side === "a" ? "tradeA" : "tradeB";
  const row = $(`#trade-${side}-chips`);
  row.innerHTML = "";
  state[listKey].forEach((p) => {
    const chip = el("div", "chip");
    chip.innerHTML = `<img ${headshotAttrs(p)} alt="">
      <span>${esc(p.player_display_name)}</span><button class="chip-x">✕</button>`;
    chip.querySelector(".chip-x").addEventListener("click", () => {
      state[listKey] = state[listKey].filter((x) => x.player_id !== p.player_id);
      renderTradeChips(side);
    });
    row.appendChild(chip);
  });
  $("#trade-analyze").disabled = !(state.tradeA.length && state.tradeB.length);
}

async function runTrade() {
  const body = {
    side_a: state.tradeA.map((p) => p.player_id),
    side_b: state.tradeB.map((p) => p.player_id),
    scoring: scoringDict(),
  };
  const results = $("#trade-results");
  results.innerHTML = `<div class="loading">Analyzing…</div>`;
  try {
    const data = await api("/api/trade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const verdictText = data.verdict === "fair" ? "Roughly Fair" : data.verdict === "side_a" ? "Side A gives up more" : "Side B gives up more";
    let html = `<div class="trade-verdict"><div class="big">${esc(verdictText)}</div>
      <div class="muted">Side A: ${data.side_a.total_value} pts · Side B: ${data.side_b.total_value} pts · Diff: ${data.diff > 0 ? "+" : ""}${data.diff}</div></div>`;
    ["side_a", "side_b"].forEach((sideKey) => {
      html += `<div class="section-label">${sideKey === "side_a" ? "Side A" : "Side B"}</div>`;
      data[sideKey].players.forEach((p) => {
        if (p.error) { html += `<div class="result-card"><span>${esc(p.player_id)}: ${esc(p.error)}</span></div>`; return; }
        html += `<div class="result-card">
          <img ${headshotAttrs(p)} alt="">
          <div><div class="name">${esc(p.player_display_name)}</div><div class="meta">${esc(p.position)} · ${esc(p.recent_team)} · SCORE ${FMT.d1(p.SCORE)}</div></div>
          <div class="proj"><div class="num">${FMT.d1(p.value)}</div><div class="lbl">value</div></div>
        </div>`;
      });
    });
    results.innerHTML = html;
  } catch (e) {
    results.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// Split-screen roster builder: your own roster (fixed) on one side, any
// other team in the league (switchable) on the other — click a player on
// either side to add them to that side's trade package.
function tradeRosterRowHtml(p, selected) {
  return `<div class="trade-roster-row${selected ? " selected" : ""}" data-pid="${esc(p.player_id)}">
    <img ${headshotAttrs(p)} alt="">
    <div>
      <div class="name">${esc(p.player_display_name)}</div>
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
    body.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

function initTrade() {
  $("#trade-analyze").addEventListener("click", runTrade);
  $("#trade-analyzer-gate-btn")?.addEventListener("click", () => switchTab("settings"));
}

// ------------------------------------------------------------- waivers ----
async function loadWaivers(pos) {
  pos = pos || document.querySelector("#waivers-pos-pills .pill.active")?.textContent || "QB";
  const body = $("#waivers-body");
  body.innerHTML = `<tr><td colspan="5">${skeletonRows(8, 2)}</td></tr>`;

  try {
    const data = await api(`/api/waivers?pos=${pos}${scoringQS()}`);
    $("#waivers-hint").textContent = data.league
      ? `Excluding everyone rostered in "${data.league.league_name}" (${data.league.team_name}) — synced to your account. 🔥 = trending adds on Sleeper, last 48h.`
      : `Not excluding any rostered players — sign in and connect your Sleeper league in Settings to see who's actually available.`;
    body.innerHTML = "";
    (data.available[pos] || []).forEach((p) => {
      const tr = el("tr");
      const trending = p.trending_adds > 0
        ? `<span class="trend-badge" title="${esc(p.trending_adds)} adds on Sleeper, last 48h">🔥 ${p.trending_adds >= 1000 ? (p.trending_adds / 1000).toFixed(1) + "k" : p.trending_adds}</span>` : "";
      tr.innerHTML = `<td class="rank-cell">${esc(p.rank)}</td><td>${playerCellHtml(p)}${trending}</td>
        <td>${scoreCell(p.SCORE)}</td><td>${formCell(p.FORM)}</td><td>${FMT.d1(p.fpts_per_game)}</td>`;
      tr.addEventListener("click", () => openPlayerModal(p.player_id));
      body.appendChild(tr);
    });
    if (!(data.available[pos] || []).length) {
      body.innerHTML = `<tr><td colspan="5" class="empty">No qualifying players.</td></tr>`;
    }
    animateScoreBars();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="5" class="empty">${esc(e.message)}</td></tr>`;
  }
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
  return `<div class="myteam-roster-row${isBench ? " bench" : ""}${unscored ? " unscored" : ""}" data-pid="${esc(p.player_id)}" ${unscored ? 'data-unscored="1"' : ""}>
    <img ${headshotAttrs(p)} alt="">
    <span class="pos-badge">${esc(p.slot || p.position)}</span>
    <span>${esc(p.player_display_name)}</span>
    <span class="proj-num">${FMT.d1(p.PROJ)}</span>
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
    ? `<img class="mt-avatar" src="${proxyImg(team.avatar_url)}" onerror="this.outerHTML='<span class=&quot;team-emoji&quot;>🏈</span>'" alt="">`
    : `<span class="team-emoji">🏈</span>`;
  return `<div class="myteam-card${kind === "opponent" ? " opponent" : ""}">
      <div class="mt-label">${kind === "mine" ? "MY TEAM" : "OPPONENT"}</div>
      <div class="mt-name-row">${avatar}<div class="mt-name">${esc(team.team_name)}</div></div>
      <div class="mt-total-lbl">PROJECTED (STARTERS)</div>
      <div class="mt-total">${FMT.d1(team.total_proj)}</div>
      <div style="margin-top:14px">${rows}</div>
    </div>`;
}

// A big center "VS" badge between the two team cards, plus who's favored —
// the head-to-head feel of a real matchup page, not just two cards side by side.
function matchupCenterHtml(mine, opp) {
  if (!opp) return `<div class="matchup-vs-center"><div class="matchup-vs-badge">VS</div></div>`;
  const diff = (mine.total_proj || 0) - (opp.total_proj || 0);
  const favoredName = diff >= 0 ? mine.team_name : opp.team_name;
  const favor = Math.abs(diff) < 0.1
    ? `<span style="color:var(--muted)">Dead even</span>`
    : `${esc(favoredName)} +${FMT.d1(Math.abs(diff))}`;
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
    <div class="matchup-bar">
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
        ${t.avatar_url ? `<img src="${proxyImg(t.avatar_url)}" onerror="this.style.display='none'" alt="">` : ""}
        <span class="lm-name">${esc(t.team_name)}</span>
        <span class="lm-proj">${FMT.d1(t.total_proj)}</span>
      </div>`).join(`<span class="lm-vs">vs</span>`);
    return `<div class="lm-row">${sides}</div>`;
  }).join("");
  return `<div class="section-label">League Matchups This Week</div><div class="league-matchups">${rows}</div>`;
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
    content.innerHTML = html;
    content.querySelectorAll(".myteam-roster-row:not(.unscored)").forEach((row) => {
      row.addEventListener("click", () => openPlayerModal(row.dataset.pid));
    });
  } catch (e) {
    content.style.display = "none";
    gate.style.display = "";
    gate.querySelector(".gate-sub").textContent = e.message || "Connect a league in Settings first.";
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
        <span>${esc(p.player_display_name)}${needBadge(p.need_multiplier)}</span>
        <span class="proj-num">${FMT.d1(p.ADJ_SCORE)}</span>
      </div>`).join("");
    html += `<div class="draft-columns">
      <div><div class="section-label">Recent Picks</div><div class="picks-feed">${picksFeed}</div></div>
      <div><div class="section-label">Best Available (need-adjusted)</div><div class="board-wrap" style="padding:4px 12px;max-height:480px;overflow-y:auto;">${available}</div></div>
    </div>`;
  }

  content.innerHTML = html;
  content.querySelectorAll(".myteam-roster-row").forEach((row) => {
    row.addEventListener("click", () => openPlayerModal(row.dataset.pid));
  });
}

async function loadDraftBoard(draftId) {
  const content = $("#draft-content");
  content.style.display = "";
  content.innerHTML = `<div class="loading">Loading draft…</div>`;
  try {
    const d = await api(`/api/draft/${draftId}${scoringQS().replace("&", "?")}`);
    renderDraftBoard(d);
    stopDraftPolling();
    if (!d.is_complete) {
      draftPollHandle = setInterval(async () => {
        try { renderDraftBoard(await api(`/api/draft/${draftId}${scoringQS().replace("&", "?")}`)); }
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

async function loadTradeFinder(giveIds) {
  const block = $("#trade-finder-block");
  if (!state.user || !activeTeam()) { block.style.display = "none"; return; }
  block.style.display = "";
  await renderShopPicker();

  const results = $("#trade-finder-results");
  const clearBtn = $("#shop-clear-btn");
  const shopping = giveIds && giveIds.length;
  clearBtn.style.display = shopping ? "" : "none";

  if (!shopping) {
    results.innerHTML = `<div class="hint">Pick one or more of your own players above, then hit "Find trades for selected" — we'll scan the whole league for realistic returns.</div>`;
    return;
  }

  results.innerHTML = `<div class="loading">Scanning the league for realistic trades…</div>`;
  try {
    const giveQS = giveIds.map((id) => `&give=${encodeURIComponent(id)}`).join("");
    const data = await api(`/api/trade-finder${scoringQS().replace("&", "?")}${giveQS}`);
    if (!data.suggestions.length) {
      results.innerHTML = `<div class="hint">No realistic offers found for that player right now — try a different pick, or check back as values update.</div>`;
      return;
    }
    results.innerHTML = data.suggestions.map((s, i) => `
      <div class="trade-suggestion" style="animation-delay:${i * 55}ms">
        <div class="ts-opp">vs ${esc(s.opponent_team_name)}${s.fills_need ? ` · fills your ${esc(s.fills_need)} need` : ""}</div>
        <div class="ts-swap">
          <div class="ts-side">${playerChipsHtml(s.you_give)}</div>
          <div class="ts-swap-icon">⇄</div>
          <div class="ts-side">${playerChipsHtml(s.you_get)}</div>
        </div>
        <div class="ts-footer">
          <span class="ts-diff ${s.value_diff >= 0 ? "pos" : "neg"}">${s.value_diff >= 0 ? "+" : ""}${s.value_diff} pts</span>
          <button class="pill" data-give='${esc(JSON.stringify(s.you_give))}' data-get='${esc(JSON.stringify(s.you_get))}'>Load into builder</button>
        </div>
      </div>
    `).join("");
    results.querySelectorAll("button[data-give]").forEach((b) => {
      b.addEventListener("click", () => {
        // dataset getters already HTML-decode attribute entities, so these are plain JSON strings
        state.tradeA = JSON.parse(b.dataset.give);
        state.tradeB = JSON.parse(b.dataset.get);
        renderTradeChips("a"); renderTradeChips("b");
        window.scrollTo({ top: document.querySelector(".trade-columns").offsetTop - 80, behavior: "smooth" });
      });
    });
  } catch (e) {
    results.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// Shared "my own roster" cache — both the Trade Finder's shop picker and
// the Start/Sit picker draw from the same synced roster, one fetch covers both.
async function ensureMyRoster() {
  if (!state.shopRoster.length) {
    const data = await api(`/api/myteam${scoringQS().replace("&", "?")}`);
    state.shopRoster = data.my_team.players;
  }
  return state.shopRoster;
}

async function renderShopPicker() {
  const picker = $("#shop-roster-picker");
  try {
    await ensureMyRoster();
  } catch (e) { picker.innerHTML = ""; return; }
  picker.innerHTML = state.shopRoster.map((p) => `
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
      else state.shopSelected.add(pid);
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
function newsCardHtml(it, featured, i) {
  return `<a class="news-card${featured ? " featured" : ""}" href="${safeUrl(it.link)}" target="_blank" rel="noopener noreferrer" style="animation-delay:${Math.min(i, 8) * 50}ms">
    <div class="news-img-wrap${it.image ? "" : " no-image"}">
      ${it.image ? `<img src="${proxyImg(it.image)}" alt="" loading="lazy" onerror="this.closest('.news-img-wrap').classList.add('no-image')">` : ""}
      ${featured ? `<span class="news-badge">FEATURED</span>` : ""}
    </div>
    <div class="news-body">
      <div class="news-meta"><span>${esc(it.source)}</span><span>·</span><span>${esc(it.published)}</span></div>
      ${it.matched_players && it.matched_players.length ? `<div class="news-matched">${it.matched_players.map((m) => `<span class="tag soft">${esc(m.name)}</span>`).join("")}</div>` : ""}
      <div class="news-title">${esc(it.title)}</div>
      <div class="news-summary">${esc(it.summary)}</div>
    </div>
  </a>`;
}

async function loadNews() {
  const list = $("#news-list");
  const scope = state.newsScope;
  list.innerHTML = `<div class="loading">Loading headlines…</div>`;
  try {
    const data = await api(`/api/news?scope=${scope}`);
    if (data.requires_team) {
      $("#news-hint").textContent = `Sign in and connect a Sleeper team to see ${scope === "opponent" ? "opponent" : "your team's"} news.`;
      list.innerHTML = `<div class="empty">Connect a league in Settings to unlock this tab.</div>`;
      return;
    }
    if (scope === "team") {
      $("#news-hint").textContent = data.team_name ? `Filtered to "${data.team_name}".` : `Filtered to your roster.`;
    } else if (scope === "opponent") {
      $("#news-hint").textContent = data.team_name ? `Filtered to this week's opponent, "${data.team_name}".` : "This week's opponent.";
    } else {
      $("#news-hint").textContent = `Every real NFL headline from ESPN & CBS Sports RSS — ones about someone in your league are surfaced first.`;
    }
    if (data.message) {
      list.innerHTML = `<div class="empty">${esc(data.message)}</div>`;
      return;
    }
    if (!data.items.length) {
      list.innerHTML = `<div class="empty">No matching headlines right now — check back later.</div>`;
      return;
    }
    list.innerHTML = data.items.map((it, i) => newsCardHtml(it, i === 0, i)).join("");
  } catch (e) {
    list.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
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
  document.querySelector(".account-dropdown")?.remove();
  renderAccountButton();
  refreshScoringLeagueOption();
  renderSidebarTeams();
  switchTab("board");
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
function authPanelHtml(mode) {
  return `
    <div class="auth-tabs">
      <button class="auth-tab-btn ${mode === "login" ? "active" : ""}" data-mode="login">Sign In</button>
      <button class="auth-tab-btn ${mode === "signup" ? "active" : ""}" data-mode="signup">Create Account</button>
    </div>
    <div id="auth-form-area"></div>
    ${state.meta?.oauth_google ? `
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
          showToast("Welcome to Lineup Lab — check your email to verify your account.", "success");
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
      <div class="hint" style="margin:0 0 4px">Enter your account email — if it matches an account, a reset link is sent to it.</div>
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
    <div class="modal-header"><h2>Reset Password</h2><button class="modal-close">✕</button></div>
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
    const teamsRes = await api("/api/teams");
    state.teams = teamsRes.teams;
    const active = activeTeam();
    if (active) {
      try {
        const snap = await api(`/api/sleeper/${active.league_id}`);
        state.leagueScoringDict = snap.scoring;
      } catch (e) { state.leagueScoringDict = null; }
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
        msg.className = "form-msg success"; msg.textContent = "Verification email sent — check your inbox.";
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
  t.innerHTML = `<span>${esc(text)}</span><button>✕</button>`;

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

  renderTeamsList();

  $("#set-espn-league").value = state.settings.espn_league_id || "";
  $("#set-espn-swid").value = "";
  $("#set-espn-s2").value = "";
  $("#set-espn-swid").placeholder = state.settings.espn_swid_set ? "•••••••• (already set — leave blank to keep)" : "SWID cookie (private leagues only)";
  $("#set-espn-s2").placeholder = state.settings.espn_s2_set ? "•••••••• (already set — leave blank to keep)" : "espn_s2 cookie (private leagues only)";
  $("#set-espn-save").onclick = async () => {
    const updates = { espn_league_id: $("#set-espn-league").value };
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
        ${t.avatar_url ? `<img src="${proxyImg(t.avatar_url)}" onerror="this.style.display='none'" alt="">` : `<div class="team-card-noavatar">🏈</div>`}
        <div class="team-card-info">
          <div class="team-card-name">${esc(t.team_name)}</div>
          <div class="team-card-league">${esc(t.league_name || t.league_id)}</div>
        </div>
        ${t.active ? `<span class="tag soft">ACTIVE</span>` : `<button class="pill" data-activate="${esc(t.id)}">Switch</button>`}
        <button class="chip-x" data-remove="${esc(t.id)}" title="Remove">✕</button>
      </div>`).join("");

    list.querySelectorAll("button[data-activate]").forEach((b) => b.addEventListener("click", async () => {
      const res = await api(`/api/teams/${b.dataset.activate}/activate`, { method: "POST" });
      state.teams = res.teams;
      const active = activeTeam();
      if (active) {
        try { state.leagueScoringDict = (await api(`/api/sleeper/${active.league_id}`)).scoring; } catch (e) { state.leagueScoringDict = null; }
      }
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
      if (active) {
        try { state.leagueScoringDict = (await api(`/api/sleeper/${active.league_id}`)).scoring; } catch (e) {}
      }
      refreshScoringLeagueOption();
      renderTeamsList();
      renderScoringPills();
    }));
  }

  const connectArea = $("#set-connect-results");
  connectArea.innerHTML = "";
  $("#set-connect-input").value = "";

  $("#set-connect-btn").onclick = async () => {
    const raw = $("#set-connect-input").value.trim();
    if (!raw) return;
    const btn = $("#set-connect-btn");
    btn.disabled = true; btn.textContent = "Loading…";
    connectArea.innerHTML = "";
    try {
      const snap = await api("/api/teams/lookup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league_id_or_url: raw }),
      });
      connectArea.innerHTML = `<div class="hint">Which team is yours in "${esc(snap.league_name)}"?</div>` +
        snap.teams.map((t) => `<div class="league-team-row">
            <span>${t.avatar_url ? `<img class="inline-avatar" src="${proxyImg(t.avatar_url)}" onerror="this.style.display='none'" alt="">` : ""}
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
  const options = [["", "PPR"], ["half_ppr", "Half PPR"], ["standard", "Standard"]];
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
      if (val === "" || val === "half_ppr" || val === "standard") {
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
  $("#season-badge").textContent = `${meta.season} SZN`;
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
function showGate() {
  $("#gate-root").style.display = "flex";
  document.documentElement.classList.add("gate-locked");
  document.body.classList.add("gate-locked");
}
function hideGate() {
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
  await loadBoard();
}

function renderGateConnectLeague() {
  showGate();
  $("#gate-headline").textContent = "Sync your league";
  $("#gate-subcopy").textContent = "Paste your Sleeper league's URL (or just its ID) and pick which team is yours — My Team, Waivers, Trade, and News all follow it from here.";
  const panel = $("#gate-panel");
  panel.innerHTML = `<div class="gate-form-wrap">
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
            <span>${t.avatar_url ? `<img class="inline-avatar" src="${proxyImg(t.avatar_url)}" onerror="this.style.display='none'" alt="">` : ""}
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
    await loadBoard();
  });
}

async function main() {
  // A password-reset link lands here already carrying its own modal (via
  // handleUrlRedirects below) — don't stack the mandatory gate on top of
  // that flow, whatever the current sign-in state happens to be.
  const cameViaResetLink = new URLSearchParams(window.location.search).has("reset_token");

  handleUrlRedirects();
  initSidebar();
  initTabs();
  initPosPills();
  initSearch();
  initStartSit();
  initTrade();
  initTradeFinder();
  initNews();
  await initMeta();

  try {
    state.user = await api("/api/auth/me");
  } catch (e) {
    state.user = null;
  }
  renderAccountButton();
  await loadSettingsIntoState();

  if (cameViaResetLink) {
    initScoringSelect();
    await loadBoard();
    return;
  }
  await proceedPastGate();
}

main();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
