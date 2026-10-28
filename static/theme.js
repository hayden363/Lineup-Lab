/* Favorite-team theme: the Settings picker and its persistence (this file also gets the hero band and interactions).
   Depends on window.TeamTheme (team-themes.js). The logic is kept apart from the DOM so it can be tested in node.
   State: `committed` is the team the user chose ("" = the default Lineup Lab theme); a hover or focus preview
   changes only what is shown, never what is saved. */
(function () {
  "use strict";
  var KEY = "eb_team";
  var opts = {
    isSignedIn: function () { return false; },
    saveToAccount: function () { return Promise.resolve(); }
  };
  var committed = (window.TeamTheme && window.TeamTheme.current()) || "";
  var host = null;

  function TT() { return window.TeamTheme; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  // Every storage access is guarded: private windows and blocked storage must never break picking a team.
  function stored(op, value) {
    try {
      var s = window.localStorage;
      if (!s) return null;
      if (op === "get") return s.getItem(KEY);
      if (op === "set") s.setItem(KEY, value); else s.removeItem(KEY);
    } catch (e) { /* storage unavailable */ }
    return null;
  }

  function fx(name, arg) {                       // ThemeFX (hero, kickoff) may not be loaded; it is optional
    var f = window.ThemeFX;
    if (f && typeof f[name] === "function") { try { f[name](arg); } catch (e) { /* cosmetic */ } }
  }

  function configure(o) {
    if (!o) return;
    if (typeof o.isSignedIn === "function") opts.isSignedIn = o.isSignedIn;
    if (typeof o.saveToAccount === "function") opts.saveToAccount = o.saveToAccount;
  }

  function init() { committed = TT().current(); }          // adopt whatever the boot script applied

  function announce(text) {
    var live = host && host.querySelector ? host.querySelector(".tp-live") : null;
    if (live) live.textContent = text;
  }

  function refreshPressed() {
    if (!host || !host.querySelectorAll) return;
    host.querySelectorAll(".tp-chip").forEach(function (chip) {
      var code = chip.dataset.team || "";
      var on = code === committed;
      chip.setAttribute("aria-pressed", String(on));
      chip.setAttribute("tabindex", on ? "0" : "-1");
    });
  }

  function choose(code) {
    code = code || "";
    if (code !== "" && !TT().valid(code)) return;
    var changed = code !== committed;
    committed = code;
    TT().apply(code);
    if (code) stored("set", code); else stored("remove");
    if (changed && code) fx("kickoff", code);
    fx("renderHero");
    if (opts.isSignedIn()) {
      try {
        var p = opts.saveToAccount(code || null);
        if (p && typeof p.catch === "function") p.catch(function () { /* the browser copy is still saved */ });
      } catch (e) { /* ditto */ }
    }
    refreshPressed();
    var t = TT().get(code);
    announce(t ? "Favorite team set to " + t.city + " " + t.name : "Favorite team cleared. Using the default theme.");
  }

  function preview(code) {
    if (code === "") TT().clear();
    else if (TT().valid(code)) TT().apply(code);
  }

  function endPreview() { TT().apply(committed); }

  // The account value only fills in a device that has no valid team of its own: the browser's choice always wins.
  function syncFromAccount(accountTheme) {
    if (!TT().valid(accountTheme) || TT().valid(stored("get"))) return;
    committed = accountTheme;
    TT().apply(accountTheme);
    stored("set", accountTheme);
    fx("renderHero");
    refreshPressed();
  }

  function logoUrl(t) { return "/api/img?url=" + encodeURIComponent(t.logo); }

  function chipsHtml(selected) {
    var out = '<div class="tp-grid" role="group" aria-label="Favorite team">';
    out += '<button type="button" class="tp-chip tp-default" data-default="1" aria-pressed="' + String(selected === "") + '" tabindex="' +
      (selected === "" ? "0" : "-1") + '"><span class="tp-abbr">Default</span><span class="tp-sub">Lineup Lab</span></button>';
    var division = null;
    TT().all().forEach(function (t) {
      if (t.division !== division) {
        if (division !== null) out += "</div></div>";
        division = t.division;
        out += '<div class="tp-div"><h4 class="tp-div-h">' + esc(division) + '</h4><div class="tp-row">';
      }
      var on = t.code === selected;
      out += '<button type="button" class="tp-chip" data-team="' + esc(t.code) + '" aria-pressed="' + String(on) + '" tabindex="' + (on ? "0" : "-1") +
        '" title="' + esc(t.city + " " + t.name) + '" aria-label="' + esc(t.city + " " + t.name) + '" style="--c:' + esc(t.primary) + ";--on:" + esc(t.onPrimary) + '">' +
        '<img class="tp-logo" src="' + esc(logoUrl(t)) + '" alt="" loading="lazy" width="36" height="36" data-logo="' + esc(t.code) + '">' +
        '<span class="tp-code">' + esc(t.code) + "</span></button>";
    });
    return out + "</div></div></div>" + '<div class="tp-live" aria-live="polite" role="status"></div>';
  }

  function chipOf(target) { return target && target.closest ? target.closest("[data-team],[data-default]") : null; }
  function codeOf(chip) { return chip.dataset.team || ""; }

  function swapLogo(img) {                        // a logo that will not load becomes the team letters on the team color
    var span = document.createElement("span");
    span.className = "tp-abbr";
    span.textContent = img.dataset.logo;
    if (img.replaceWith) img.replaceWith(span);
  }

  function onKey(e) {
    var keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys) && e.key !== "Home" && e.key !== "End") return;
    var chips = Array.prototype.slice.call(host.querySelectorAll(".tp-chip"));
    var i = chips.indexOf(document.activeElement);
    if (i < 0) return;
    var next = e.key === "Home" ? 0 : e.key === "End" ? chips.length - 1 : (i + keys[e.key] + chips.length) % chips.length;
    e.preventDefault();
    chips[next].focus();
  }

  function bind(el) {
    if (el._tpBound) return;
    el._tpBound = true;
    el.addEventListener("click", function (e) { var c = chipOf(e.target); if (c) choose(codeOf(c)); });
    el.addEventListener("pointerover", function (e) { var c = chipOf(e.target); if (c) preview(codeOf(c)); });
    el.addEventListener("focusin", function (e) { var c = chipOf(e.target); if (c) preview(codeOf(c)); });
    el.addEventListener("pointerleave", endPreview);
    el.addEventListener("focusout", function (e) { if (!e.relatedTarget || !el.contains(e.relatedTarget)) endPreview(); });
    el.addEventListener("keydown", onKey);
    el.addEventListener("error", function (e) { var t = e.target; if (t && t.dataset && t.dataset.logo) swapLogo(t); }, true);   // error events do not bubble
  }

  function render(el) {
    if (!el) return;
    host = el;
    el.innerHTML = '<div class="tp-head"><div class="settings-block-title">Favorite team</div>' +
      '<p class="muted small">Pick your team and the whole app takes on its colors. Saved on this device, and on your account when you are signed in.</p></div>' +
      chipsHtml(committed);
    bind(el);
  }

  window.ThemePicker = { configure: configure, init: init, choose: choose, preview: preview, endPreview: endPreview,
    syncFromAccount: syncFromAccount, render: render, chipsHtml: chipsHtml };
})();


/* ---- atmosphere: the team hero band and the kickoff sweep --------------------------------------------------- */
(function () {
  "use strict";
  var overlay = null;

  function TT() { return window.TeamTheme; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function reduced() { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }

  function swapLogo(img) {                       // same fallback as the picker: the team letters on the team color
    var span = document.createElement("span");
    span.className = "th-abbr";
    span.textContent = img.dataset.logo;
    if (img.replaceWith) img.replaceWith(span);
  }

  // Fills #team-hero for the current team, or empties it for the default theme.
  // ---- the strip's game line: the last result early in the week, the next game from Thursday on ----
  function dateLabel(iso) {
    var d = new Date(String(iso).slice(0, 10) + "T12:00:00");
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  }

  // `d` is /api/team/{code}. Monday to Wednesday the game people are talking about is the one just played; Thursday
  // to Sunday it is the one coming up. With only one of the two available, that one.
  function gameLine(d, now) {
    if (!d) return null;
    var played = (d.games || []).filter(function (g) { return g.result; });
    var last = played[played.length - 1], nxt = d.next_game;
    var dow = (now || new Date()).getDay();
    var wantLast = dow >= 1 && dow <= 3;
    var useLast = last && (wantLast || !nxt);
    if (!useLast && !nxt) return null;
    if (useLast) {
      return { kind: "last", result: last.result, week: last.week,
        text: "Last game \u00b7 Wk " + last.week + " \u00b7 " + last.result + " " + last.team_score + "\u2013" + last.opp_score + " " + (last.home ? "vs" : "@") + " " + last.opponent };
    }
    var line = "";
    if (nxt.spread != null && nxt.spread !== 0) line = " \u00b7 " + (nxt.spread < 0 ? (d.team || "") : nxt.opponent) + " -" + Math.abs(nxt.spread);
    var when = dateLabel(nxt.date);
    return { kind: "next", result: null, week: nxt.week,
      text: "Next game \u00b7 Wk " + nxt.week + (when ? " \u00b7 " + when : "") + " \u00b7 " + (nxt.home ? "vs" : "@") + " " + nxt.opponent + line };
  }

  function gameLineHtml(line, d) {
    if (!line) return "";
    var rec = d && d.record ? '<span class="th-rec">' + esc(d.record.text) + "</span>" : "";
    return rec + '<span class="th-game' + (line.result ? " res-" + String(line.result).toLowerCase() : "") + '">' + esc(line.text) + "</span>";
  }

  // ---- the franchise strip: crest, name + standing, roster synergy and the game-state pill ----
  var ALIAS = { WSH: "WAS", JAC: "JAX", LAR: "LA" };
  function norm(c) { c = String(c || "").toUpperCase(); return ALIAS[c] || c; }
  var DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

  function kickText(iso) {                       // "SUN 1:00 PM" in the viewer's own time zone
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return "";
    var h = d.getHours(), m = d.getMinutes();
    return DAYS[d.getDay()] + " " + (h % 12 || 12) + ":" + (m < 10 ? "0" : "") + m + " " + (h < 12 ? "AM" : "PM");
  }

  function gameFor(code, games) {                // a live game wins when a team somehow appears twice
    var mine = (games || []).filter(function (g) {
      return g && g.home && g.away && (norm(g.home.abbr) === code || norm(g.away.abbr) === code);
    });
    return mine.filter(function (g) { return g.state === "in"; })[0] || mine[0] || null;
  }

  function pillState(code, games, slate, now) {
    code = norm(code);
    var g = gameFor(code, games);
    if (!g) {
      if (slate && slate.byes && slate.week != null && slate.byes[code] === slate.week) return { kind: "bye", text: "BYE WEEK", rz: false };
      return null;
    }
    var home = norm(g.home.abbr) === code, me = home ? g.home : g.away, opp = home ? g.away : g.home;
    var oa = opp.abbr, ms = me.score, os = opp.score;
    if (g.state === "in") {
      var q = g.period > 4 ? "OT" : "Q" + g.period;
      var rz = !!(g.situation && g.situation.is_red_zone && norm(g.situation.possession) === code);
      return { kind: "live", rz: rz, text: code + " " + ms + " - " + os + " " + oa + " • " + q + (g.display_clock ? " " + g.display_clock : "") };
    }
    if (g.state === "post") {
      var res = ms > os ? "W" : ms < os ? "L" : "T";
      return { kind: "post", rz: false, text: "FINAL: " + res + " " + ms + "-" + os };
    }
    var when = kickText(g.kickoff);
    return { kind: "pre", rz: false, text: (home ? "vs " : "@ ") + oa + (when ? " • " + when : "") };
  }

  function streakText(d) {
    var s = d && d.streak;
    return s && s.type === "W" && s.n >= 3 ? s.n + "-Game Win Streak 🔥" : null;
  }

  function subline(d) {
    if (!d) return "";
    var parts = [];
    if (d.record && d.record.text) parts.push(d.record.text);
    if (d.standing && d.standing.text) parts.push(d.standing.text);
    return parts.join(" • ");
  }

  var OUT = { OUT: 1, IR: 1, PUP: 1, SUSPENDED: 1 };
  function synergy(players, code) {
    var r = { total: 0, active: 0 };
    code = norm(code);
    (players || []).forEach(function (p) {
      if (!p || norm(p.recent_team || p.team) !== code) return;
      r.total++;
      if (!p.on_bye && !OUT[String(p.injury_status || "").toUpperCase()]) r.active++;
    });
    return r;
  }

  function isTouchdown(prev, now) { return prev != null && now != null && now - prev >= 6; }

  function synergyHtml(sy) {
    if (!sy) return "";
    if (!sy.total) return '<span class="th-syn-txt">No players on your roster</span>';
    var dots = "";
    for (var i = 0; i < Math.min(sy.total, 8); i++) dots += '<i class="th-dot' + (i < sy.active ? " on" : "") + '"></i>';
    return '<span class="th-dots" aria-hidden="true">' + dots + '</span><span class="th-syn-txt">' + sy.active + " Active on Roster</span>";
  }

  var gameCache = {};
  var live = { games: null, slate: null, roster: null, scores: {}, data: null };

  function heroEl() { return document.getElementById ? document.getElementById("team-hero") : null; }
  function bandEl() { var el = heroEl(); return el && el.querySelector ? el.querySelector(".th-band") : null; }
  function slot(sel) { var el = heroEl(); return el && el.querySelector ? el.querySelector(sel) : null; }

  function paintSub() {
    var el = slot(".th-sub");
    if (!el) return;
    var st = streakText(live.data), base = subline(live.data);
    el.innerHTML = (base ? "<span>" + esc(base) + "</span>" : "") + (st ? '<span class="th-streak">' + esc(st) + "</span>" : "");
  }

  function paintSyn() {
    var el = slot(".th-syn"), code = TT().current();
    if (el && code) el.innerHTML = live.roster ? synergyHtml(synergy(live.roster, code)) : "";
  }

  function paintPill() {
    var code = TT().current(), pill = slot(".th-pill"), band = bandEl();
    var st = code ? pillState(code, live.games, live.slate, new Date()) : null;
    if (pill) {
      pill.textContent = st ? st.text : "";
      pill.className = "th-pill" + (st ? " k-" + st.kind + (st.rz ? " rz" : "") : " hide");
    }
    if (band && band.classList) band.classList.toggle("is-live", !!(st && st.kind === "live"));
  }

  var tdTimer = null;
  function setGames(games) {
    live.games = games || [];
    var code = TT().current(), g = code ? gameFor(code, live.games) : null;
    if (g) {
      var home = norm(g.home.abbr) === code, now = home ? g.home.score : g.away.score;
      var prev = live.scores[g.game_id];
      live.scores[g.game_id] = now;
      var band = bandEl();
      if (g.state === "in" && isTouchdown(prev, now) && band && band.classList && !reduced()) {
        band.classList.add("td-flash");
        if (tdTimer) window.clearTimeout(tdTimer);
        tdTimer = window.setTimeout(function () { tdTimer = null; var b = bandEl(); if (b && b.classList) b.classList.remove("td-flash"); }, 1500);
      }
    }
    paintPill();
  }
  function setSlate(s) { live.slate = s || null; paintPill(); }
  function setRoster(list) { live.roster = list || null; paintSyn(); }

  function fillGame(code) {
    if (typeof fetch !== "function") return;
    var hit = gameCache[code];
    var paint = function (d) { if (TT().current() === code) { live.data = d; paintSub(); paintPill(); paintSyn(); } };
    if (hit && Date.now() - hit.at < 600000) { paint(hit.d); return; }
    fetch("/api/team/" + encodeURIComponent(code) + "?lite=1").then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (d) { gameCache[code] = { at: Date.now(), d: d }; paint(d); }
    }).catch(function () { /* the strip just stays without a subline */ });
  }

  function renderHero() {
    var el = heroEl();
    if (!el) return;
    var t = TT().get(TT().current());
    if (!t) { el.innerHTML = ""; return; }
    live.data = null;
    el.innerHTML = '<button type="button" class="th-band" data-team-page="' + esc(t.code) + '" aria-label="Open the ' + esc(t.city + " " + t.name) + ' team page">' +
      '<span class="th-art" aria-hidden="true"></span><span class="th-lines" aria-hidden="true"></span><span class="th-sheen" aria-hidden="true"></span>' +
      '<span class="th-crest" aria-hidden="true"><span class="th-glow"></span><img class="th-logo" src="' + esc("/api/img?url=" + encodeURIComponent(t.logo)) + '" alt="" width="56" height="56" data-logo="' + esc(t.code) + '"></span>' +
      '<span class="th-title"><span class="th-text"><span class="th-city">' + esc(t.city) + '</span> <span class="th-name">' + esc(t.name) + '</span></span><span class="th-sub"></span></span>' +
      '<span class="th-syn"></span><span class="th-pill hide"></span></button>';
    if (!el._tpBound) {
      el._tpBound = true;
      el.addEventListener("error", function (e) { var img = e.target; if (img && img.dataset && img.dataset.logo) swapLogo(img); }, true);   // error does not bubble
    }
    paintPill(); paintSyn();
    fillGame(t.code);
  }

  function removeOverlay() {
    if (overlay) { if (overlay.remove) overlay.remove(); overlay = null; }
  }

  // One diagonal wipe in the team's two colors, about 0.7 s. Never replays for the default theme or under reduced motion.
  function kickoff(code) {
    var t = TT().get(code);
    if (!t || reduced()) return;
    removeOverlay();
    var el = document.createElement("div");
    el.className = "th-kick";
    el.setAttribute("aria-hidden", "true");
    el.style.setProperty("--k1", t.primary);
    el.style.setProperty("--k2", t.secondary);
    document.body.appendChild(el);
    overlay = el;
    window.setTimeout(function () { if (overlay === el) removeOverlay(); }, 800);   // an older timer never removes a newer overlay
  }

  var SURFACES = ".news-card, .lab-card, .myteam-card, .board-wrap, .tr-card";
  var glowBound = false;

  // A soft team-colored light that follows a mouse over the main card surfaces. Touch and pen never trigger it,
  // and moves are coalesced to one update per frame.
  function initGlow(root) {
    var host = root || document;
    if (glowBound || !host.addEventListener) return;
    glowBound = true;
    var pending = null;
    host.addEventListener("pointermove", function (e) {
      if (e.pointerType !== "mouse" || !TT().current()) return;
      var el = e.target && e.target.closest ? e.target.closest(SURFACES) : null;
      if (!el) return;
      var first = !pending;
      pending = { el: el, x: e.clientX, y: e.clientY };
      if (!first) return;
      window.requestAnimationFrame(function () {
        var p = pending; pending = null;
        var r = p.el.getBoundingClientRect();
        p.el.style.setProperty("--mx", Math.round(p.x - r.left) + "px");
        p.el.style.setProperty("--my", Math.round(p.y - r.top) + "px");
      });
    }, { passive: true });
  }

  var wipe = null;

  // A 350 ms line across the top edge in the team color whenever the tab changes.
  function tabWipe() {
    if (!TT().current() || reduced()) return;
    if (wipe) { if (wipe.remove) wipe.remove(); wipe = null; }
    var el = document.createElement("div");
    el.className = "th-wipe";
    el.setAttribute("aria-hidden", "true");
    document.body.appendChild(el);
    wipe = el;
    window.setTimeout(function () { if (wipe === el) { if (el.remove) el.remove(); wipe = null; } }, 400);
  }

  window.ThemeFX = { gameLine: gameLine, gameLineHtml: gameLineHtml, pillState: pillState, subline: subline, streakText: streakText, synergy: synergy, isTouchdown: isTouchdown,
    setGames: setGames, setSlate: setSlate, setRoster: setRoster, renderHero: renderHero, kickoff: kickoff, initGlow: initGlow, tabWipe: tabWipe };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", renderHero);
  else renderHero();
  initGlow();
})();
