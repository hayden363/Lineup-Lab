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

  var gameCache = {};
  function fillGame(code) {
    var el = document.getElementById ? document.getElementById("team-hero") : null;
    var slot = el && el.querySelector ? el.querySelector(".th-info") : null;
    if (!slot || typeof fetch !== "function") return;
    var hit = gameCache[code];
    var paint = function (d) { if (TT().current() === code) slot.innerHTML = gameLineHtml(gameLine(d, new Date()), d); };
    if (hit && Date.now() - hit.at < 600000) { paint(hit.d); return; }
    fetch("/api/team/" + encodeURIComponent(code)).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (d) { gameCache[code] = { at: Date.now(), d: d }; paint(d); }
    }).catch(function () { /* the strip just stays without a game line */ });
  }

  function renderHero() {
    var el = document.getElementById ? document.getElementById("team-hero") : null;
    if (!el) return;
    var t = TT().get(TT().current());
    if (!t) { el.innerHTML = ""; return; }
    el.innerHTML = '<button type="button" class="th-band" data-team-page="' + esc(t.code) + '" aria-label="Open the ' + esc(t.city + " " + t.name) + ' team page">' +
      '<span class="th-art" aria-hidden="true"></span><span class="th-lines" aria-hidden="true"></span>' +
      '<span class="th-body"><img class="th-logo" src="' + esc("/api/img?url=" + encodeURIComponent(t.logo)) + '" alt="" width="28" height="28" data-logo="' + esc(t.code) + '">' +
      '<span class="th-text"><span class="th-city">' + esc(t.city) + '</span><span class="th-name">' + esc(t.name) + '</span></span>' +
      '<span class="th-info"></span><span class="th-go" aria-hidden="true">Team page \u203a</span></span></button>';
    if (!el._tpBound) {
      el._tpBound = true;
      el.addEventListener("error", function (e) { var img = e.target; if (img && img.dataset && img.dataset.logo) swapLogo(img); }, true);   // error does not bubble
    }
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

  window.ThemeFX = { gameLine: gameLine, gameLineHtml: gameLineHtml, renderHero: renderHero, kickoff: kickoff, initGlow: initGlow, tabWipe: tabWipe };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", renderHero);
  else renderHero();
  initGlow();
})();
