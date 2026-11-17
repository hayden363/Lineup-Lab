/* The Daily Drive: vanilla JS, no inline script (CSP script-src 'self'). Answers never reach this file until the game
   is over: every typed answer is judged by /api/play/check, and the full tier lists come from /api/play/reveal.
   The visuals (the full-screen field scene with the quarterback and the six plays lives in play-field.js; HUD, play clock, result moment, touchdown, drive chart) are CSS/SVG/canvas;
   prefers-reduced-motion turns off particles, shakes and transitions (see REDUCED and the CSS media query). */
(function () {
  "use strict";
  var PREVIEW_MS = 3000, ANSWER_MS = 25000, SAVE_TTL_MS = 12 * 3600 * 1000, MAX_YARDS = 700, YPX = 5, SCAN_MIN_MS = 450;
  var TIER = {   // the six plays, lowest to best: [name, yards, share emoji]
    6: ["Highlight Reel TD", 100, "🏈"], 5: ["Bomb", 85, "💣"], 4: ["Chunk Play", 60, "🚀"],
    3: ["Chain Mover", 30, "⛓️"], 2: ["Quick Slant", 15, "⚡"], 1: ["Checkdown", 10, "✅"]
  };
  var TIER_COLOR = { 1: "#b3bccd", 2: "#6fd0ff", 3: "#ff4b55", 4: "#b866ff", 5: "#fff04d", 6: "#ffab1a" };   // grey, light blue, red, purple, yellow, gold
  var TIER_GRAD = { 1: ["#e3e8f2", "#7d879c"], 2: ["#b6e9ff", "#2f9fe0"], 3: ["#ff8f94", "#c8202f"], 4: ["#dcaaff", "#7d33d6"], 5: ["#fffbb0", "#d8c200"], 6: ["#ffe4a3", "#d27800"] };
  var SACK = "❌";
  var REDUCEDQ = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var REDUCED = !!(REDUCEDQ && REDUCEDQ.matches);
  if (REDUCEDQ && REDUCEDQ.addEventListener) REDUCEDQ.addEventListener("change", function (e) { REDUCED = e.matches; });
  // iOS app (user agent "LineupLabApp/<version>"): the native tab bar replaces the top bar; share and haptics go native
  var NATIVE = (window.webkit && window.webkit.messageHandlers) || null;
  if (/LineupLabApp\//.test(navigator.userAgent)) document.documentElement.classList.add("in-app");
  function nativeCall(name, value) {
    try { if (NATIVE && NATIVE[name]) { NATIVE[name].postMessage(value); return true; } } catch (e) { /* not in the app */ }
    return false;
  }
  var root = document.getElementById("app");
  var live = document.getElementById("dd-live");

  // ---------------------------------------------------------------- storage (every access guarded)
  function lsGet(k) { try { var v = window.localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch (e) { return null; } }
  function lsSet(k, v) { try { window.localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked: the game still works */ } }
  function lsDel(k) { try { window.localStorage.removeItem(k); } catch (e) { /* ignore */ } }

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") el.className = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
      else el.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      if (Array.isArray(c)) { c.forEach(function (x) { if (x != null) el.appendChild(typeof x === "string" || typeof x === "number" ? document.createTextNode(String(x)) : x); }); continue; }
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    return el;
  }
  function announce(t) { if (live) live.textContent = t || ""; }
  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || "request failed"); return j; });
    });
  }
  function isoAdd(iso, days) {
    var p = iso.split("-"); var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + days));
    return d.toISOString().slice(0, 10);
  }
  function prettyDate(iso) {
    var p = iso.split("-"); var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  }
  function longDate(iso) {
    var p = iso.split("-"); var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
  }
  function yardsOf(tiers) { return tiers.reduce(function (a, t) { return a + (t ? TIER[t][1] : 0); }, 0); }
  function shareText(date, tiers) {
    return "The Daily Drive · " + prettyDate(date) + " · " + yardsOf(tiers) + " yds\n" +
      tiers.map(function (t) { return t ? TIER[t][2] : SACK; }).join("") + "\nlineup-lab-awdv.onrender.com/play";
  }
  function countUp(el, to, ms, prefix, from, suffix) {
    prefix = prefix || ""; from = from || 0; suffix = suffix || "";
    if (REDUCED || to === from) { el.textContent = prefix + to + suffix; return; }
    var t0 = performance.now();
    (function step(now) {
      var f = Math.min(1, (now - t0) / ms);
      el.textContent = prefix + Math.round(from + (to - from) * (1 - Math.pow(1 - f, 3))) + suffix;
      if (f < 1) requestAnimationFrame(step);
    })(t0);
  }
  function restart(el, cls) { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); }

  // ---------------------------------------------------------------- team + player visuals (all optional fields)
  var TEAM_ALIAS = { WSH: "WAS", LAR: "LA", JAC: "JAX", STL: "LA", SD: "LAC", OAK: "LV" };
  function teamColor(code) {
    var T = window.TEAM_THEMES; if (!code || !T) return "";
    code = String(code).toUpperCase();
    var t = T[code] || T[TEAM_ALIAS[code]];
    return t ? t.primary : "";
  }
  function imgSrc(u) {
    if (!u || typeof u !== "string") return "";
    if (/^data:image\//.test(u)) return u;
    return /^https?:\/\//.test(u) ? "/api/img?url=" + encodeURIComponent(u) : "";
  }
  function initials(name) {
    var p = String(name || "?").replace(/[^A-Za-z\s.'-]/g, "").split(/\s+/).filter(Boolean);
    if (!p.length) return "?";
    return (p[0].charAt(0) + (p.length > 1 ? p[p.length - 1].charAt(0) : "")).toUpperCase();
  }
  // Headshot when the API sends one (through the same-origin image proxy), else a team-colored initials badge.
  function photo(cls, info, tag) {
    var box = h(tag || "div", { "class": cls }), tc = teamColor(info.team);
    if (tc) box.style.setProperty("--tm", tc);
    var ini = h("span", null, initials(info.name));
    box.appendChild(ini);
    var src = imgSrc(info.headshot);
    if (src) {
      var im = h("img", { alt: "", loading: "lazy", decoding: "async", src: src });
      im.addEventListener("load", function () { ini.style.display = "none"; });
      im.addEventListener("error", function () { if (im.parentNode) im.parentNode.removeChild(im); });
      box.appendChild(im);
    }
    return box;
  }

  // ---------------------------------------------------------------- streak
  function streakNow(today) {
    var s = lsGet("dd.streak");
    if (!s) return 0;
    return (s.last === today || s.last === isoAdd(today, -1)) ? s.count : 0;
  }
  function streakBump(today) {
    var s = lsGet("dd.streak") || { last: "", count: 0 };
    if (s.last === today) return s.count;
    s = { last: today, count: s.last === isoAdd(today, -1) ? s.count + 1 : 1 };
    lsSet("dd.streak", s);
    return s.count;
  }

  // ---------------------------------------------------------------- canvas fireworks + confetti (one rAF loop, stopped when idle)
  var fx = (function () {
    var cv = null, ctx = null, parts = [], raf = 0, last = 0, pending = 0, W = 0, H = 0;
    function ensure() {
      if (cv) return;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth; H = window.innerHeight;
      cv = h("canvas", { "class": "dd-fx", "aria-hidden": "true" });
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      ctx = cv.getContext("2d"); if (!ctx) { cv = null; return; }
      ctx.scale(dpr, dpr); document.body.appendChild(cv);
    }
    function stop() { cancelAnimationFrame(raf); raf = 0; if (cv && cv.parentNode) cv.parentNode.removeChild(cv); cv = null; ctx = null; parts = []; }
    function loop(now) {
      var dt = Math.min(0.05, (now - last) / 1000); last = now;
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      var alive = [];
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i];
        p.life -= dt; if (p.life <= 0) continue;
        p.vy += p.g * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.rot += p.vr * dt;
        var a = Math.min(1, p.life / p.max * 1.6);
        ctx.globalAlpha = a; ctx.fillStyle = p.c;
        if (p.kind) { ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillRect(-p.s, -p.s * 0.55, p.s * 2, p.s * 1.1); ctx.restore(); }
        else { ctx.beginPath(); ctx.arc(p.x, p.y, p.s, 0, 6.2832); ctx.fill(); }
        alive.push(p);
      }
      parts = alive;
      if (parts.length || pending) raf = requestAnimationFrame(loop); else stop();
    }
    function kick() { if (!raf) { last = performance.now(); raf = requestAnimationFrame(loop); } }
    function add(p) { if (parts.length < 420) parts.push(p); }
    function burst(x, y, colors, n, speed) {
      ensure(); if (!cv) return;
      for (var i = 0; i < n; i++) {
        var a = Math.random() * 6.2832, v = speed * (0.35 + Math.random() * 0.75), life = 0.8 + Math.random() * 0.7;
        add({ x: x, y: y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, g: 260, life: life, max: life, s: 1.4 + Math.random() * 1.8, c: colors[i % colors.length], kind: 0, rot: 0, vr: 0 });
      }
      kick();
    }
    function confetti(n, colors) {
      ensure(); if (!cv) return;
      for (var i = 0; i < n; i++) {
        var life = 2 + Math.random() * 1.4;
        add({ x: Math.random() * W, y: -10 - Math.random() * 120, vx: (Math.random() - 0.5) * 90, vy: 120 + Math.random() * 160, g: 90, life: life, max: life, s: 3 + Math.random() * 3,
          c: colors[i % colors.length], kind: 1, rot: Math.random() * 6, vr: (Math.random() - 0.5) * 12 });
      }
      kick();
    }
    var GOLDS = ["#ffd36a", "#ffb84d", "#ffffff", "#ff8a3d"], MIX = ["#ffb84d", "#00ceb8", "#bd66ff", "#58a7ff", "#ff5d7a", "#2fd9a0"];
    return {
      sparkle: function (x, y, color, n) { if (!REDUCED) burst(x, y, [color, "#ffffff"], n || 34, 200); },
      touchdown: function () {
        if (REDUCED) return;
        [[0, 0.3, 0.3], [380, 0.72, 0.26], [800, 0.5, 0.2], [1250, 0.22, 0.34]].forEach(function (b) {
          pending++;
          setTimeout(function () { pending--; ensure(); if (cv) burst(window.innerWidth * b[1], window.innerHeight * b[2], GOLDS.concat(MIX), 62, 330); }, b[0]);
        });
        confetti(50, MIX.concat(GOLDS));
      },
      stop: stop
    };
  })();
  // ---------------------------------------------------------------- drive state: where the ball is, the down and the distance (derived from the plays so far, so a resumed game matches)
  // Every 100 yards is a touchdown; the field is 100 yards long, so the ball sits at (yards mod 100) from your own goal line.
  function driveState(tiers) {
    var p = 0, down = 1, dist = 10, td = 0, yards = 0;
    tiers.forEach(function (t) {
      var g = t ? TIER[t][1] : 0; yards += g;
      if (g > 0) {
        if (p + g >= 100) { td++; p = p + g - 100; down = 1; dist = 10; }
        else { p += g; if (g >= dist) { down = 1; dist = 10; } else { dist -= g; down++; } }
      } else down++;
      if (down > 4) { down = 1; dist = 10; }
    });
    return { yards: yards, p: p, down: down, dist: dist, td: td, fd: Math.min(100, p + dist) };
  }
  function posText(p) { return p === 0 ? "OWN GOAL" : p < 50 ? "OWN " + p : p === 50 ? "MIDFIELD" : "OPP " + (100 - p); }
  function downText(ds) { return ["1ST", "2ND", "3RD", "4TH"][ds.down - 1] + " & " + (ds.p + ds.dist >= 100 ? "GOAL" : ds.dist); }
  function crossedTD(a, b) { return b > a && Math.floor(b / 100) > Math.floor(a / 100); }

  // ---------------------------------------------------------------- the stage: field canvas, broadcast HUD, prompt UI, result moment, page scroller (intro/results), side panels
  var field;
  var cv = h("canvas", { "class": "dd-scene", "aria-hidden": "true" });
  try { field = window.DDField.create(cv); } catch (err) {
    field = { resize: function () {}, setNumber: function () {}, setAmbient: function () {}, setScene: function () {}, reset: function () {}, skip: function () { return false; }, playing: function () { return false; },
      play: function (o, done) { setTimeout(done, 50); }, sack: function (o, done) { setTimeout(done, 50); }, ballPoint: function () { return { x: window.innerWidth / 2, y: window.innerHeight / 2 }; }, flash: function () {}, shake: function () {} };
  }
  var hudYards = h("b", null, "0"), hudPos = h("b", null, "OWN GOAL"), hudTd = h("em", null, ""), hudLbl = h("span", { "class": "hud-lbl" }, ""), downChip = h("span", { "class": "dd-down" }, "1ST & 10");
  var pipsBox = h("div", { "class": "dd-pips", "aria-hidden": "true" });
  var hud = h("div", { "class": "dd-hud" },
    h("div", { "class": "sb sb-l" }, h("small", null, "YARDS"), hudYards),
    h("div", { "class": "hud-c" }, pipsBox, hudLbl, downChip),
    h("div", { "class": "sb sb-r" }, h("small", null, "DRIVE"), hudPos, hudTd));
  var promptSlot = h("div", { "class": "dd-prompt" }), resSlot = h("div", { "class": "dd-resslot" }), scroll = h("div", { "class": "dd-scroll" });
  var stage = h("div", { "class": "dd-stage" }, cv, hud, promptSlot, resSlot, scroll);

  // ---------------------------------------------------------------- the Lineup Lab top bar (same brand and buttons as the rest of the site)
  var navStreak = h("span", { "class": "ll-streak" }), navAuth = h("div", { "class": "ll-auth" });
  var nav = h("header", { "class": "ll-nav" },
    h("a", { "class": "ll-brand", href: "/", "aria-label": "Lineup Lab home" }, h("img", { src: "/icons/icon-192.png", alt: "", width: 30, height: 30 }), h("span", null, "Lineup Lab")),
    h("span", { "class": "ll-here", "aria-current": "page" }, "The Daily Drive"),
    h("div", { "class": "ll-right" }, navStreak, navAuth));
  function setNavAuth(signedIn) {      // true: back into the app; false: the same sign-in buttons as the landing page; null: unknown yet
    navAuth.textContent = "";
    if (signedIn === true) navAuth.appendChild(h("a", { "class": "ll-btn", href: "/" }, "Open app"));
    else if (signedIn === false) {
      navAuth.appendChild(h("a", { "class": "ll-btn ghost", href: "/?auth=login" }, "Log in"));
      navAuth.appendChild(h("a", { "class": "ll-btn", href: "/?auth=signup" }, "Start free"));
    }
  }

  // ---------------------------------------------------------------- today's leaderboard + brand (side panels on desktop, a card in the page on phones)
  var lbBoxes = [], lbData = null;
  function lbNew(aside) {
    var box = h("div", { "class": "dd-card dd-lb", style: "display:none" }); box.setAttribute("data-aside", aside ? "1" : "");
    lbBoxes.push(box); lbDraw(box); return box;
  }
  var MEDAL = ["🥇", "🥈", "🥉"];
  function nameHue(n) { var x = 7; for (var i = 0; i < n.length; i++) x = (x * 31 + n.charCodeAt(i)) % 360; return x; }
  function lbAvatar(name, me) {
    var a = h("span", { "class": "av" }, me ? "YOU" : initials(name));
    a.style.setProperty("--hue", String(me ? 152 : nameHue(String(name || ""))));
    return a;
  }
  function boardRow(r, me) {     // ranks 4-10 and the pinned "you" row: rank, badge, name + spoiler-free drive, yards bar
    var bar = h("i", { "class": "bar" }); bar.style.setProperty("--w", Math.min(100, Math.round(r.yards / MAX_YARDS * 100)) + "%");
    return h("div", { "class": "dd-lb-row" + (me ? " me" : "") }, h("span", { "class": "r" }, "#" + r.rank), lbAvatar(r.name, me),
      h("div", { "class": "who" }, h("b", null, me ? "You" : r.name), r.emoji ? h("span", { "class": "em" }, r.emoji) : null),
      h("div", { "class": "y" }, h("b", null, String(r.yards)), h("small", null, "yds"), bar));
  }
  function podium(rows, isMe) {  // the top three, 2nd - 1st - 3rd like a real podium
    var box = h("div", { "class": "dd-pod n" + rows.length });
    [1, 0, 2].forEach(function (k) {
      var r = rows[k]; if (!r) return;
      var me = isMe(r);
      box.appendChild(h("div", { "class": "pod p" + (k + 1) + (me ? " me" : "") },
        h("span", { "class": "medal", "aria-hidden": "true" }, MEDAL[Math.min(2, r.rank - 1)] || MEDAL[2]), lbAvatar(r.name, me),
        h("b", { "class": "nm" }, me ? "You" : r.name), h("span", { "class": "yd" }, r.yards + " yds"),
        r.emoji ? h("span", { "class": "em" }, r.emoji) : null, h("i", { "class": "step" }, "#" + r.rank)));
    });
    return box;
  }
  function lbDraw(box) {
    if (!lbData) { box.style.display = "none"; return; }
    box.textContent = "";
    if (lbData.kind === "avg") {
      box.appendChild(h("h2", null, "Today's drive"));
      box.appendChild(h("p", { "class": "dd-lb-avg" }, "Average " + avgText(lbData.st.average_yards) + " yds across " + lbData.st.players + (lbData.st.players === 1 ? " player" : " players")));
      box.appendChild(h("p", { "class": "dd-small" }, "Sign in and finish today's drive to put your name on the board."));
      box.style.display = ""; return;
    }
    var j = lbData.j, youRank = j.you && j.you.rank, top = j.top.slice(0, 10);
    // tied ranks share a number, so only call a row "you" when no one else holds that rank
    var sameRank = top.filter(function (r) { return r.rank === youRank; }).length;
    var isMe = function (r) { return youRank != null && r.rank === youRank && sameRank === 1; };
    box.appendChild(h("div", { "class": "dd-lb-head" }, h("h2", null, "Today's leaderboard"),
      h("span", { "class": "dd-lb-n" }, j.players + (j.players === 1 ? " player" : " players"))));
    box.appendChild(podium(top.slice(0, 3), isMe));
    var list = h("div", { "class": "dd-lb-list" });
    top.slice(3).forEach(function (r) { list.appendChild(boardRow(r, isMe(r))); });
    if (list.childNodes.length) box.appendChild(list);
    if (j.you && !top.some(isMe)) box.appendChild(h("div", { "class": "dd-lb-you" }, boardRow({ rank: j.you.rank, name: "you", yards: j.you.yards, emoji: j.you.emoji }, true)));
    else if (!j.you) box.appendChild(h("p", { "class": "dd-small dd-lb-foot" }, "Finish today's drive to see where you rank."));
    box.style.display = "";
  }
  function lbRefresh() { lbBoxes = lbBoxes.filter(function (b) { return b.getAttribute("data-aside") || b.isConnected; }); lbBoxes.forEach(lbDraw); }
  function loadBoard(date) {
    api("/api/play/leaderboard?date=" + encodeURIComponent(date) + "&device_id=" + encodeURIComponent(deviceId())).then(function (j) {
      if (j && j.available && j.top && j.top.length) { lbData = { kind: "board", j: j }; lbRefresh(); return; }
      throw new Error("no board");
    }).catch(function () {
      // No leaderboard yet: fall back to today's average, or hide the panel
      fetchStats(date).then(function (st) { lbData = st && st.players ? { kind: "avg", st: st } : null; lbRefresh(); });
    });
  }

  // ---------------------------------------------------------------- the playbook (tier legend): the six plays, lowest to best
  var PLAY_NOTE = { 1: "Short flat to the back", 2: "Sharp cut inside", 3: "Deep dig past the sticks", 4: "Post between the safeties", 5: "Go route, double coverage", 6: "Signature catch for six" };
  var shieldN = 0;
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }
  function shield(t) {
    var id = "ddsh" + (++shieldN), g = TIER_GRAD[t];
    var s = svgEl("svg", { viewBox: "0 0 32 36", "aria-hidden": "true" }), d = svgEl("defs"), lg = svgEl("linearGradient", { id: id, x1: "0", y1: "0", x2: "0", y2: "1" });
    lg.appendChild(svgEl("stop", { offset: "0", "stop-color": g[0] })); lg.appendChild(svgEl("stop", { offset: "1", "stop-color": g[1] }));
    d.appendChild(lg); s.appendChild(d);
    s.appendChild(svgEl("path", { d: "M16 1.5 L29.5 6.5 V17 C29.5 25.5 23.5 31.5 16 34.5 C8.5 31.5 2.5 25.5 2.5 17 V6.5 Z", fill: "url(#" + id + ")", stroke: "rgba(255,255,255,0.55)", "stroke-width": 1.4 }));
    s.appendChild(svgEl("path", { d: "M16 5 L26.5 8.8 V17 C26.5 23.6 22 28.4 16 31 Z", fill: "rgba(255,255,255,0.22)" }));
    return s;
  }
  function tierLegend() {
    var list = h("div", { "class": "dd-plays" });
    [1, 2, 3, 4, 5, 6].forEach(function (t) {
      list.appendChild(h("div", { "class": "dd-pl t" + t }, shield(t), h("div", { "class": "nm" }, h("b", null, TIER[t][0], h("i", { "class": "pe", "aria-hidden": "true" }, TIER[t][2])), h("span", null, PLAY_NOTE[t])), h("div", { "class": "pt" }, "+" + TIER[t][1])));
    });
    return h("div", { "class": "dd-card dd-tiers" }, h("h2", null, "The playbook (yards = rarity)"), list, h("p", { "class": "dd-small dd-sackline" }, SACK + " Wrong answer or out of time: a sack, 0 yards."));
  }
  // desktop side columns: the playbook + your drives on the left, the leaderboard + today's numbers on the right
  var asideMe = h("div", { "class": "dd-card dd-drives dd-side-me" }), asideDay = h("div", { "class": "dd-card dd-day", hidden: "" });
  var asideL = h("aside", { "class": "dd-aside l" }, tierLegend(), asideMe), asideR = h("aside", { "class": "dd-aside r" }, lbNew(true), asideDay);
  function fillDay(st, date, today) {
    asideDay.textContent = "";
    if (!st || !st.players) { asideDay.hidden = true; return; }
    asideDay.hidden = false;
    asideDay.appendChild(h("h2", null, (date === today ? "Today" : prettyDate(date)) + " in numbers"));
    asideDay.appendChild(h("div", { "class": "dd-tiles" }, tile("players", st.players), tile("average", avgText(st.average_yards)), tile("median", avgText(st.median_yards))));
  }
  function loadSides(puzzle) {
    fetchStats(puzzle.date).then(function (st) { fillDay(st, puzzle.date, puzzle.today); });
    api("/api/play/me").catch(function () { return null; }).then(function (me) { fillDrives(asideMe, me); });
  }
  root.textContent = ""; root.appendChild(nav); root.appendChild(asideL); root.appendChild(stage); root.appendChild(asideR);

  // ---------------------------------------------------------------- stage helpers
  function mount(top) {
    scroll.textContent = ""; promptSlot.textContent = ""; resSlot.textContent = ""; scroll.scrollTop = 0;
    if (top) scroll.appendChild(top);
    for (var i = 1; i < arguments.length; i++) if (arguments[i]) scroll.appendChild(arguments[i]);
  }
  function setStage(mode, ambient) {
    root.classList.remove("urgent"); root.setAttribute("data-mode", mode); root.setAttribute("data-phase", "idle");
    field.setAmbient(ambient !== false);
    if (field.setView) field.setView(mode === "play" || mode === "practice" ? 0.575 : mode === "result" ? 0.3 : 0.4, mode === "play" || mode === "practice");
    requestAnimationFrame(function () { field.resize(); });   // the stage is wider on a desktop end screen
  }
  function setPips(tiers, total, cur) {
    pipsBox.textContent = "";
    for (var i = 0; i < total; i++) pipsBox.appendChild(h("i", { "class": i < tiers.length ? (tiers[i] ? "p" + tiers[i] : "sk") : (i === cur ? "cur" : "") }));
  }
  function setHud(ds, o) {
    o = o || {};
    if (o.countFrom != null) { countUp(hudYards, ds.yards, 700, "", o.countFrom); if (!REDUCED && ds.yards !== o.countFrom) restart(hudYards, "pop"); } else hudYards.textContent = String(ds.yards);
    hudPos.textContent = posText(ds.p); hudTd.textContent = ds.td ? "TD " + ds.td : ""; downChip.textContent = downText(ds);
    if (o.label != null) hudLbl.textContent = o.label;
  }
  function fitStage() {   // keep the prompt bar above the on-screen keyboard
    var vv = window.visualViewport; if (!vv) return;
    if (vv.height < window.innerHeight - 100) { stage.style.height = vv.height + "px"; stage.style.bottom = "auto"; stage.style.top = vv.offsetTop + "px"; }
    else { stage.style.height = ""; stage.style.bottom = ""; stage.style.top = ""; }
    field.resize();
  }
  if (window.visualViewport) { window.visualViewport.addEventListener("resize", fitStage); window.visualViewport.addEventListener("scroll", fitStage); }

  // ---------------------------------------------------------------- saved scores + community stats
  // None of this can break the game: every failure collapses to a quiet "stats unavailable".
  var deviceMem = "";
  function deviceId() {
    var d = lsGet("dd.device");
    if (typeof d === "string" && /^[A-Za-z0-9_-]{16,64}$/.test(d)) return d;
    if (deviceMem) return deviceMem;
    var id = "";
    try {
      var a = new Uint8Array(16); window.crypto.getRandomValues(a);
      a.forEach(function (b) { id += ("0" + b.toString(16)).slice(-2); });
    } catch (e) { for (var i = 0; i < 32; i++) id += Math.floor(Math.random() * 16).toString(16); }
    deviceMem = id; lsSet("dd.device", id);
    return id;
  }
  function postJson(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); });
  }
  // Sends only the signed tokens; the server recomputes the yards. Resolves to the response body or null.
  function submitScore(puzzle, rec) {
    if (puzzle.today !== puzzle.date || !rec.tokens || rec.synced) return Promise.resolve(null);
    return postJson("/api/play/score", { date: puzzle.date, device_id: deviceId(), tokens: rec.tokens }).then(function (r) {
      if (r.body && r.body.available) { rec.synced = true; lsSet("dd.played." + puzzle.date, rec); return r.body; }
      if (r.status === 400) { rec.synced = true; lsSet("dd.played." + puzzle.date, rec); }   // stale or rejected: stop retrying
      return null;
    }).catch(function () { return null; });
  }
  function fetchStats(date) {
    return api("/api/play/stats?date=" + encodeURIComponent(date) + "&device_id=" + encodeURIComponent(deviceId()))
      .then(function (j) { return j && j.available ? j : null; }).catch(function () { return null; });
  }
  function avgText(v) { return v == null ? "-" : (Math.round(v) === v ? String(v) : v.toFixed(1)); }
  function histogram(dist, mine) {
    var max = Math.max.apply(null, dist.map(function (b) { return b.count; }).concat([1]));
    var bars = h("div", { "class": "dd-hist", role: "img", "aria-label": "How everyone scored, in 100-yard groups" });
    var labels = h("div", { "class": "dd-hist-x" });
    dist.forEach(function (b) {
      var fill = h("i"), me = mine != null && mine >= b.lo && mine <= b.hi;
      fill.setAttribute("data-h", Math.max(b.count ? 6 : 2, Math.round(b.count / max * 100)));
      bars.appendChild(h("span", { "class": "dd-bar" + (me ? " me" : ""), title: b.lo + "-" + b.hi + " yds: " + b.count + (me ? " (you)" : "") }, fill));
      labels.appendChild(h("span", null, String(b.lo)));
    });
    var go = function () { Array.prototype.forEach.call(bars.querySelectorAll("i"), function (f) { f.style.height = f.getAttribute("data-h") + "%"; }); };
    if (REDUCED) go(); else requestAnimationFrame(function () { requestAnimationFrame(go); });
    return h("div", null, bars, labels);
  }
  function fillStats(box, st, label, mine) {
    box.textContent = "";
    box.appendChild(h("h2", null, "How everyone drove"));
    if (!st) { box.appendChild(h("p", { "class": "dd-small" }, "Stats unavailable right now. Your score is safe on this device.")); return; }
    if (!st.players) { box.appendChild(h("p", { "class": "dd-small" }, "No scores saved yet for " + label + ". You could be the first.")); return; }
    var line = label + ": average " + avgText(st.average_yards) + " yds across " + st.players + (st.players === 1 ? " player" : " players");
    if (st.percentile != null) line += " · you beat " + st.percentile + "%";
    box.appendChild(h("p", { "class": "dd-stat-line" }, line));
    box.appendChild(histogram(st.distribution || [], st.your_yards != null ? st.your_yards : mine));
    box.appendChild(h("p", { "class": "dd-small" }, "Median " + avgText(st.median_yards) + " yds. Bars show how many players finished in each 100-yard group."));
  }
  function sparkline(vals) {
    if (!vals || vals.length < 2) return null;
    var W = 120, H = 32, max = Math.max.apply(null, vals.concat([MAX_YARDS / 2])), n = vals.length;
    var pts = vals.map(function (v, i) { return (i / (n - 1) * (W - 4) + 2).toFixed(1) + "," + (H - 3 - v / max * (H - 6)).toFixed(1); }).join(" ");
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, "class": "dd-spark", role: "img", "aria-label": "Your last " + n + " scores" });
    svg.appendChild(svgEl("polyline", { points: pts, fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    return svg;
  }
  function tile(label, value) { return h("div", { "class": "dd-tile" }, h("b", null, String(value)), h("span", null, label)); }
  function fillDrives(box, me) {
    box.textContent = "";
    if (me && me.signed_in === false) {
      box.appendChild(h("h2", null, "Your drives"));
      box.appendChild(h("p", null, "Sign in to keep your history: past scores, your average, and streaks that follow you to any device."));
      box.appendChild(h("a", { "class": "dd-btn alt dd-link", href: "/?auth=login" }, "Sign in to keep your history"));
      return;
    }
    box.appendChild(h("h2", null, "Your drives"));
    if (!me || me.available === false) { box.appendChild(h("p", { "class": "dd-small" }, "Your history is unavailable right now. Scores you finish are still saved on this device.")); return; }
    if (!me.games) { box.appendChild(h("p", { "class": "dd-small" }, "No saved drives yet. Finish today's game and it lands here.")); return; }
    box.appendChild(h("div", { "class": "dd-tiles" }, tile("played", me.games), tile("average", avgText(me.average_yards)), tile("best", me.best_yards),
      tile("streak · best " + me.longest_streak, me.current_streak)));
    var sp = sparkline(me.spark); if (sp) box.appendChild(h("div", { "class": "dd-spark-wrap" }, h("span", { "class": "dd-small" }, "Last " + me.spark.length + " drives"), sp));
    var list = h("div", { "class": "dd-past" });
    me.history.forEach(function (g, i) {
      var row = h("div", { "class": "dd-past-row" }, h("span", { "class": "d" }, prettyDate(g.date)), h("span", { "class": "e" }, g.emoji), h("b", null, g.yards + " yds"));
      if (i >= 7) row.classList.add("more");
      list.appendChild(row);
    });
    box.appendChild(list);
    if (me.history.length > 7) {
      var btn = h("button", { "class": "dd-btn alt", type: "button" }, "Show all " + me.history.length);
      btn.addEventListener("click", function () { list.classList.add("all"); btn.style.display = "none"; });
      box.appendChild(btn);
    }
  }

  // ---------------------------------------------------------------- shared pieces
  function topBar(extra) {             // page chips (the streak) live in the Lineup Lab top bar now
    navStreak.textContent = ""; if (extra) navStreak.appendChild(extra);
    return null;
  }
  function pageFoot() { return h("div", { "class": "dd-foot" }, h("a", { href: "/" }, "Built by Lineup Lab: real NFL data for your fantasy team")); }
  function clock() {
    var C = 2 * Math.PI * 46;
    var bg = svgEl("circle", { "class": "bg", cx: 55, cy: 55, r: 46 }), fg = svgEl("circle", { "class": "fg", cx: 55, cy: 55, r: 46, "stroke-dasharray": C, "stroke-dashoffset": 0 });
    var svg = svgEl("svg", { viewBox: "0 0 110 110", "aria-hidden": "true" }); svg.appendChild(bg); svg.appendChild(fg);
    var num = h("b", null, "3"), cap = h("i", null, "SNAP");
    var el = h("div", { "class": "dd-clock snap", role: "img", "aria-label": "Play clock" }, svg, num, cap);
    return {
      el: el,
      pre: function (msLeft) {
        fg.setAttribute("stroke-dashoffset", C * (1 - Math.max(0, msLeft) / PREVIEW_MS));
        num.textContent = Math.max(1, Math.ceil(Math.max(0, msLeft) / 1000));
      },
      play: function (msLeft) {
        var s = Math.ceil(Math.max(0, msLeft) / 1000);
        fg.setAttribute("stroke-dashoffset", C * (1 - Math.max(0, msLeft) / ANSWER_MS));
        if (num.textContent !== String(s)) num.textContent = s;
        if (cap.textContent !== "CLOCK") cap.textContent = "CLOCK";
        el.classList.remove("snap"); el.classList.toggle("low", msLeft <= 5000);
        el.setAttribute("aria-label", "Play clock: " + s + " seconds");
      }
    };
  }
  function copyText(text, btn) {
    function done(ok) { btn.textContent = ok ? "Copied" : "Press and hold the card to copy"; setTimeout(function () { btn.textContent = "Copy result"; }, 2000); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallbackCopy(text)); });
    } else done(fallbackCopy(text));
  }
  function fallbackCopy(text) {
    var ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.appendChild(ta);
    ta.select(); var ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta); return ok;
  }
  // Gold full-screen touchdown (also used when a play carries the drive past a 100-yard mark).
  function touchdown(res, n) {
    var box = h("div", { "class": "dd-td", "aria-hidden": "true" }, h("div", { "class": "fl" }),
      h("div", { "class": "bn" }, h("strong", null, "TOUCHDOWN"), h("span", null, (n ? "#" + n + " · " : "") + (res ? TIER[res.tier][0].toUpperCase() + " · +" + res.yards + " YDS" : ""))));
    document.body.appendChild(box);
    field.tdCelebrate && field.tdCelebrate();
    fx.touchdown();
    setTimeout(function () { if (box.parentNode) box.parentNode.removeChild(box); }, REDUCED ? 1800 : 3300);
  }

  // ---------------------------------------------------------------- one prompt (shared by daily and practice)
  // opts: {date, prompt, index, total, tiers[], used[], resumeAnswerStart, state(drive state), onStart, onDone(result, passed)}
  // result = {tier, yards, name, id, token, team, position, headshot, stat, stat_label}
  function runPrompt(opts) {
    var prompt = opts.prompt, total = opts.total, deadline = 0, done = false, raf = 0, pending = false, warned = false;
    var rg = clock();
    var kind = total > 1 ? "PLAY " + (opts.index + 1) + " OF " + total : "PRACTICE";
    var cat = h("div", { "class": "qc-cat" }, prompt.category);
    var text = h("p", { "class": "qc-text", style: "display:none" }, prompt.text);
    var redact = h("div", { "class": "bc-red", "aria-hidden": "true" }, h("i"), h("i"));
    var msg = h("div", { "class": "dd-msg", role: "status" });
    var sugg = h("div", { "class": "dd-sugg" });
    var input = h("input", { "class": "dd-input", type: "text", autocomplete: "off", autocapitalize: "words", autocorrect: "off",
      spellcheck: "false", enterkeyhint: "go", "aria-label": "Your answer", placeholder: "Get set..." });
    var go = h("button", { "class": "dd-btn dd-go", type: "submit" }, "Snap");
    var pass = h("button", { "class": "dd-pass", type: "button", onclick: function () { if (!done && !pending && deadline) finish(null, true); } }, "Pass");
    var form = h("form", { "class": "dd-form", onsubmit: function (e) { e.preventDefault(); submit(input.value); } }, rg.el, input, go);
    input.addEventListener("input", function () { input.classList.remove("bad"); });
    var scan = h("div", { "class": "dd-scan", "aria-hidden": "true" }, h("i"), "Checking the film");
    var card = h("div", { "class": "dd-qcard" }, h("div", { "class": "qc-top" }, cat, h("span", { "class": "qc-kind" }, kind)), redact, text);
    var dock = h("div", { "class": "dd-dock" }, h("div", { "class": "dd-msgrow" }, scan, msg, pass), sugg, form);
    input.disabled = true; go.disabled = true; pass.disabled = true;
    mount(null); promptSlot.appendChild(card); promptSlot.appendChild(dock);
    setStage(total > 1 ? "play" : "practice"); root.setAttribute("data-phase", "answer");
    setPips(opts.tiers || [], total, opts.index); field.setNumber(total > 1 ? opts.index + 1 : 1);
    setHud(opts.state, { label: kind });
    announce("Play " + (opts.index + 1) + ". Category: " + prompt.category + ". Get ready.");

    function begin(answerStart) {
      redact.style.display = "none"; text.style.display = ""; text.classList.add("snap");
      input.disabled = false; go.disabled = false; pass.disabled = false; input.placeholder = "Player name..."; input.focus();
      deadline = answerStart + ANSWER_MS;
      announce(prompt.text);
      if (opts.onStart) opts.onStart(answerStart);
    }
    function finish(res, passed) {
      if (done) return; done = true; cancelAnimationFrame(raf); root.classList.remove("urgent");
      input.disabled = true; go.disabled = true; pass.disabled = true; scan.classList.remove("on");
      opts.onDone(res, !!passed);
    }
    function loop() {
      var now = Date.now();
      if (!deadline) {
        var pl = PREVIEW_MS - (now - t0);
        if (pl <= 0) begin(now); else rg.pre(pl);
      }
      if (deadline) {
        var left = deadline - now;
        rg.play(left);
        root.classList.toggle("urgent", left <= 5000 && left > 0);
        if (left <= 5000 && !warned) { warned = true; announce("Five seconds left"); }
        if (left <= 0 && !pending) { finish(null); return; }      // an answer already in flight still gets judged
      }
      raf = requestAnimationFrame(loop);
    }
    function holdScan(since) {
      var wait = REDUCED ? 0 : Math.max(0, SCAN_MIN_MS - (Date.now() - since));
      return new Promise(function (res) { setTimeout(res, wait); });
    }
    function afterReject() { if (Date.now() > deadline) finish(null); else { go.disabled = false; input.focus(); } }
    function submit(raw) {
      var typed = (raw || "").trim();
      if (!typed || done || pending || !deadline || Date.now() > deadline) return;
      var since = Date.now();
      pending = true; go.disabled = true; msg.textContent = ""; sugg.textContent = ""; input.classList.remove("bad"); scan.classList.add("on");
      api("/api/play/check", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: opts.date, prompt_id: prompt.id, answer: typed, used: opts.used }) })
        .then(function (r) { return holdScan(since).then(function () { return r; }); })
        .then(function (r) {
          pending = false; scan.classList.remove("on");
          if (done) return;
          if (r.ok) {
            finish({ tier: r.tier, yards: r.yards, name: r.canonical, id: r.answer_id, token: r.token || "",
              team: r.team || "", position: r.position || "", headshot: r.headshot || "", stat: r.stat, stat_label: r.stat_label || "" });
            return;
          }
          input.value = ""; input.classList.add("bad");
          msg.textContent = r.reason.charAt(0).toUpperCase() + r.reason.slice(1);
          announce("Not accepted. " + msg.textContent);
          restart(form, "shake");
          (r.suggestions || []).forEach(function (n) {
            sugg.appendChild(h("button", { type: "button", onclick: function () { submit(n); } }, "Did you mean " + n + "?"));
          });
          afterReject();
        })
        .catch(function (e) {
          pending = false; scan.classList.remove("on");
          if (done) { if (window.console) console.error(e); return; }
          msg.textContent = "Couldn't reach the server. Try again."; afterReject();
        });
    }

    // 3-second category preview (the "snap" countdown), then the real 25-second play clock
    var t0 = Date.now();
    if (opts.resumeAnswerStart) begin(opts.resumeAnswerStart);
    raf = requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- the play and the result moment
  // o: {res (or null), passed, before, after (drive states), last, seed, practice, next(), extra(box)}
  // The graded answer runs its designated play on the field (a tap or key skips it), then the full-scene result moment shows with NEXT PLAY.
  function playBanner(t) { return TIER[t][0].toUpperCase() + "!"; }
  function playMoment(o) {
    var res = o.res, t = res ? res.tier : 0, before = o.before, after = o.after, scored = after.td > before.td, settled = false, went = false, timer = 0, variant = 0, tdN = after.td;
    if (res && t === 6) variant = o.variant != null ? o.variant : (window.DDField ? window.DDField.hash(String(o.seed || "x")) % 3 : 0);
    root.setAttribute("data-phase", "anim");
    announce(res ? "Snap. " + res.name + "." : (o.passed ? "Passed." : "Time. Sack."));
    function skip(e) {
      if (e && e.type === "keydown" && e.key !== "Enter" && e.key !== " " && e.key !== "Escape") return;
      if (e && e.type === "keydown") e.preventDefault();
      if (!settled) field.skip();
    }
    stage.addEventListener("pointerdown", skip); document.addEventListener("keydown", skip);
    function landed() {
      if (settled) return; settled = true;
      stage.removeEventListener("pointerdown", skip); document.removeEventListener("keydown", skip);
      nativeCall("haptic", res ? (t >= 5 ? "success" : "light") : "error");   // iOS app: a tap as the play lands
      setHud(after, { countFrom: before.yards });
      showResult();
    }
    function showResult() {
      root.setAttribute("data-phase", "result");
      var tc = res ? TIER_COLOR[t] : "#ff5d7a", sub;
      var big = res ? playBanner(t) : (o.passed ? "PASSED" : "SACKED!");
      var meta = [];
      if (res && res.team) meta.push(String(res.team).toUpperCase());
      if (res && res.position) meta.push(String(res.position).toUpperCase());
      var hasStat = res && res.stat != null && res.stat !== "";
      var noteParts = meta.slice(); if (hasStat) noteParts.push(String(res.stat) + (res.stat_label ? " " + res.stat_label : "")); else if (res && res.stat_label) noteParts.push(String(res.stat_label));
      var btnLabel = o.practice ? "Another prompt" : (o.last ? "See results" : "Next play");
      var btn = h("button", { "class": "dd-btn dd-next", type: "button", onclick: function (e) { e.stopPropagation(); if (o.practice) { fx.stop(); o.next(); } else go(); } }, btnLabel);
      var box = h("div", { "class": "dd-res" + (res ? " t" + t : " sacked") + (scored ? " scored" : ""), style: "--tc:" + tc });
      box.appendChild(h("div", { "class": "rs-play", "data-t": big }, big));
      if (res) {
        box.appendChild(h("div", { "class": "rs-who" }, photo("rs-ph", res), h("div", { "class": "rs-ans" }, "“" + res.name + "”")));
        var ydsEl = h("div", { "class": "rs-yds" }, "+" + res.yards + " YDS"); box.appendChild(ydsEl);
        if (!REDUCED && res.yards > 0) { ydsEl.textContent = "+0 YDS"; setTimeout(function () { countUp(ydsEl, res.yards, 650, "+", 0, " YDS"); }, 400); }
        if (noteParts.length) box.appendChild(h("div", { "class": "rs-note" }, noteParts.join(" · ")));
        if (scored) box.appendChild(h("div", { "class": "rs-td" }, "TOUCHDOWN" + (tdN > 1 ? " #" + tdN : "")));
      } else {
        box.appendChild(h("div", { "class": "rs-ans" }, o.passed ? "You skipped the play." : "Time ran out."));
        box.appendChild(h("div", { "class": "rs-yds" }, "0 YDS"));
        box.appendChild(h("div", { "class": "rs-note" }, "The ball stays put."));
      }
      var acts = h("div", { "class": "rs-actions" });
      if (o.practice) acts.appendChild(h("p", { "class": "dd-small rs-pr" }, "Practice does not count toward your streak."));
      acts.appendChild(btn);
      if (o.practice) acts.appendChild(h("button", { "class": "dd-btn alt dd-back", type: "button", onclick: function (e) { e.stopPropagation(); fx.stop(); boot(); } }, "Back to today's game"));
      box.appendChild(acts);
      resSlot.textContent = ""; resSlot.appendChild(box);
      announce(res ? "Accepted: " + res.name + ", " + TIER[t][0] + ", plus " + res.yards + " yards." + (scored ? " Touchdown!" : "") : (o.passed ? "Passed. No yards." : "Sacked. No yards."));
      if (res && scored) touchdown(res, tdN);
      else if (res && t >= 4 && !REDUCED) { var bp = field.ballPoint(); fx.sparkle(bp.x, bp.y, TIER_COLOR[t], t === 5 ? 56 : 40); }
      if (!o.practice) {
        timer = setTimeout(go, scored ? 5600 : 3600);
        box.addEventListener("click", function () { go(); });
        document.addEventListener("keydown", onKey);
      }
      try { btn.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
    }
    function onKey(e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }
    function go() {
      if (went) return; went = true; clearTimeout(timer); document.removeEventListener("keydown", onKey); fx.stop();
      resSlot.textContent = "";
      if (scored && !o.last) field.reset(after.p, after.fd);
      o.next();
    }
    if (res) field.play({ tier: t, gain: TIER[t][1], p0: before.p, fd0: before.fd, fd1: after.fd, score: scored, variant: variant, seed: o.seed }, landed);
    else field.sack({ p0: before.p, fd0: before.fd, fd1: after.fd }, landed);
  }

  // ---------------------------------------------------------------- daily game
  function startDaily(puzzle, saved) {
    var date = puzzle.date, prompts = puzzle.prompts, total = prompts.length, sceneSet = false;
    var st = saved || { date: date, startedAt: Date.now(), idx: 0, tiers: [], names: [], ids: [], tokens: [], answerStart: 0 };
    if (!st.tokens) st.tokens = [];
    function persist() { lsSet("dd.saved", st); }
    persist();

    function step() {
      if (st.idx >= total) { return finishGame(); }
      var resume = st.answerStart && Date.now() < st.answerStart + ANSWER_MS ? st.answerStart : 0;
      if (st.answerStart && !resume) {                           // the real deadline passed while the page was closed
        st.tiers.push(0); st.names.push(""); st.idx++; st.answerStart = 0; persist(); return step();
      }
      var ds = driveState(st.tiers);
      if (!sceneSet) { sceneSet = true; field.setScene(ds.p, ds.fd, { number: st.idx + 1 }); }
      runPrompt({
        date: date, prompt: prompts[st.idx], index: st.idx, total: total, tiers: st.tiers.slice(), used: st.ids.slice(), state: ds,
        resumeAnswerStart: resume,
        onStart: function (ts) { st.answerStart = ts; persist(); },
        onDone: function (res, passed) {
          var before = driveState(st.tiers), pid = prompts[st.idx].id;
          st.tiers.push(res ? res.tier : 0); st.names.push(res ? res.name : ""); if (res) { st.ids.push(res.id); if (res.token) st.tokens.push(res.token); }
          st.idx++; st.answerStart = 0; persist();
          var last = st.idx >= total, after = driveState(st.tiers);
          setPips(st.tiers, total, st.idx);
          playMoment({ res: res, passed: passed, before: before, after: after, last: last, seed: date + "|" + pid, next: step });
        }
      });
    }

    function finishGame() {
      var today = puzzle.today === date;
      var rec = { tiers: st.tiers, names: st.names, yards: yardsOf(st.tiers), tokens: st.tokens.slice(), synced: false };
      lsSet("dd.played." + date, rec); lsDel("dd.saved");
      if (today) streakBump(date);
      showResults(puzzle, rec);
    }
    step();
  }

  // ---------------------------------------------------------------- results: drive chart + reveal
  // One row per play; each bar starts where the last one ended and is as long as the yards it gained.
  function driveChart(tiers) {
    var W = 360, X0 = 26, X1 = 346, SC = (X1 - X0) / MAX_YARDS, TOP = 16, RH = 25, rows = tiers.length;
    var H = TOP + rows * RH + 22;
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, "class": "dd-chart", role: "img",
      "aria-label": "Drive chart: " + tiers.map(function (t, i) { return "play " + (i + 1) + " " + (t ? TIER[t][0] + " " + TIER[t][1] + " yards" : "sacked"); }).join(", ") });
    svg.appendChild(svgEl("rect", { x: X0, y: TOP - 4, width: X1 - X0, height: rows * RH + 6, rx: 6, fill: "#0b2e28", stroke: "rgba(255,255,255,0.22)" }));
    svg.appendChild(svgEl("rect", { x: X1 - 24, y: TOP - 4, width: 24, height: rows * RH + 6, rx: 6, fill: "rgba(255,194,71,0.3)" }));
    for (var k = 0; k <= 7; k++) {
      var gx = X0 + k * 100 * SC;
      svg.appendChild(svgEl("line", { x1: gx, x2: gx, y1: TOP - 4, y2: TOP + rows * RH + 2, stroke: "rgba(255,255,255,0.22)", "stroke-width": 1 }));
      var lb = svgEl("text", { x: gx, y: TOP + rows * RH + 15, "text-anchor": "middle" }); lb.textContent = k === 7 ? "TD" : String(k * 100); svg.appendChild(lb);
    }
    var cum = 0;
    tiers.forEach(function (t, i) {
      var y = TOP + i * RH + 3, yd = t ? TIER[t][1] : 0, x = X0 + cum * SC, w = yd * SC;
      var rl = svgEl("text", { x: 13, y: y + 13, "text-anchor": "middle" }); rl.textContent = String(i + 1); svg.appendChild(rl);
      if (i) svg.appendChild(svgEl("line", { x1: x, x2: x, y1: y - 7, y2: y + 3, stroke: "rgba(255,255,255,0.4)", "stroke-dasharray": "2 2" }));
      var delay = (i * 0.12) + "s";
      if (t) {
        var r = svgEl("rect", { x: x, y: y, width: w, height: 18, rx: 3, fill: TIER_COLOR[t], "class": "seg" }); r.style.animationDelay = delay; svg.appendChild(r);
        var inside = w >= 34, tx = svgEl("text", { x: inside ? x + w - 4 : x + w + 4, y: y + 13.5, "text-anchor": inside ? "end" : "start", "class": "yd" });
        if (inside) tx.setAttribute("style", "fill:#04141a;font-weight:800");
        tx.textContent = "+" + yd; svg.appendChild(tx);
      } else {
        var s = svgEl("path", { d: "M" + (x - 5) + " " + (y + 2) + " L" + (x + 5) + " " + (y + 16) + " M" + (x + 5) + " " + (y + 2) + " L" + (x - 5) + " " + (y + 16), stroke: "#ff5d7a", "stroke-width": 2.5, "stroke-linecap": "round", "class": "seg" });
        s.style.animationDelay = delay; svg.appendChild(s);
        var st2 = svgEl("text", { x: x + 9, y: y + 13.5, "class": "yd" }); st2.setAttribute("style", "fill:#ff8da1"); st2.textContent = "SACKED"; svg.appendChild(st2);
      }
      cum += yd;
    });
    return svg;
  }
  function legend() {
    var box = h("div", { "class": "dd-legend" });
    [1, 2, 3, 4, 5, 6].forEach(function (t) { var i = h("i"); i.style.setProperty("--c", TIER_COLOR[t]); box.appendChild(h("span", null, i, TIER[t][0])); });
    return box;
  }
  function ansName(a) { return typeof a === "string" ? a : (a && a.name) || ""; }
  function shareResult(text, btn) {   // the iOS app's share sheet, else the phone share sheet, else copy
    if (nativeCall("share", text)) return;
    var coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    if (coarse && navigator.share) { navigator.share({ text: text }).catch(function () { copyText(text, btn); }); return; }
    copyText(text, btn);
  }
  // The end screen (owner 2026-11-17): a Wordle-style top (yards, the 7-play emoji row, Share), then tabs:
  // Leaderboard / Answers / My stats. Two columns on a desktop screen, one on a phone.
  function showResults(puzzle, rec) {
    var date = puzzle.date, today = puzzle.today === date;
    var streak = today ? streakNow(date) : 0;
    var text = shareText(date, rec.tiers);
    var share = h("button", { "class": "dd-btn", type: "button" }, "Share result");
    share.addEventListener("click", function () { shareResult(text, share); });
    var num = h("div", { "class": "dd-fin" }, "0");
    var beat = h("p", { "class": "dd-beat" });
    var emo = h("div", { "class": "dd-emo", role: "img", "aria-label": "Your drive: " + rec.tiers.map(function (t, i) { return "play " + (i + 1) + " " + (t ? TIER[t][0] : "sacked"); }).join(", ") });
    rec.tiers.forEach(function (t, i) {
      var e = h("span", { "class": "e t" + (t || 0), title: (i + 1) + ". " + (t ? TIER[t][0] + " +" + TIER[t][1] : "Sack") }, t ? TIER[t][2] : SACK);
      e.style.animationDelay = (0.25 + i * 0.09) + "s"; emo.appendChild(e);
    });
    var rev = h("div", { "class": "dd-rev" }, h("p", { "class": "dd-small" }, "Loading the answer sheets..."));
    var statsBox = h("div", { "class": "dd-card dd-stats" }, h("h2", null, "How everyone drove"), h("p", { "class": "dd-small" }, "Loading community stats..."));
    var drivesBox = h("div", { "class": "dd-card dd-drives" }, h("h2", null, "Your drives"), h("p", { "class": "dd-small" }, "Loading..."));
    var sum = h("div", { "class": "dd-card dd-sum" },
      h("div", { "class": "dd-kick" }, "The Daily Drive · " + prettyDate(date) + (streak ? " · streak " + streak : "")),
      num, h("div", { "class": "dd-small dd-of" }, "yards of " + MAX_YARDS), emo, beat, share);
    var chart = h("div", { "class": "dd-card dd-total" }, h("h2", null, "Drive chart"), driveChart(rec.tiers), legend());
    var panes = {
      board: h("div", { "class": "dd-pane" }, lbNew(false)),
      answers: h("div", { "class": "dd-pane" }, h("div", { "class": "dd-card" }, h("h2", null, "Every answer, by play"), rev)),
      me: h("div", { "class": "dd-pane" }, statsBox, drivesBox)
    };
    var wide = window.matchMedia && window.matchMedia("(min-width: 1040px)").matches;   // desktop: the chart fills the left column
    if (!wide) panes.me.insertBefore(chart, statsBox);
    var tabs = h("div", { "class": "dd-tabs", role: "tablist" }), btns = {};
    function pick(k) {
      Object.keys(panes).forEach(function (n) { panes[n].hidden = n !== k; btns[n].setAttribute("aria-selected", n === k ? "true" : "false"); });
      lsSet("dd.tab", k);
    }
    [["board", "Leaderboard"], ["answers", "Answers"], ["me", "My stats"]].forEach(function (x) {
      btns[x[0]] = h("button", { type: "button", role: "tab", "class": "dd-tab", onclick: function () { pick(x[0]); } }, x[1]);
      tabs.appendChild(btns[x[0]]);
    });
    var want = lsGet("dd.tab"); pick(panes[want] ? want : "board");
    mount(topBar(streak ? h("span", { "class": "dd-chip" }, "Streak ", h("b", null, streak)) : null),
      h("div", { "class": "dd-results" },
        h("div", { "class": "dd-res-l" }, sum,
          h("div", { "class": "dd-row" }, h("button", { "class": "dd-btn alt", type: "button", onclick: practice }, "Practice mode"),
            h("a", { "class": "dd-btn alt dd-link", href: "/" }, "Open Lineup Lab")), wide ? chart : null),
        h("div", { "class": "dd-res-r" }, tabs, panes.board, panes.answers, panes.me)),
      pageFoot());
    setStage("result", false);
    var fin = driveState(rec.tiers); if (field.state && field.state().los !== fin.p) field.setScene(fin.p, fin.fd);
    countUp(num, rec.yards, 1100);
    announce("Final score: " + rec.yards + " yards of " + MAX_YARDS + ".");
    var label = today ? "Today" : prettyDate(date);
    // Today's answer sheets unlock only after the signed-in player's score is saved, so ask for them after the save.
    var saving = submitScore(puzzle, rec);
    saving.then(function (saved) {
      loadBoard(date);
      return (saved && saved.stats ? Promise.resolve(saved.stats) : fetchStats(date));
    }).then(function (st) {
      fillStats(statsBox, st, label, rec.yards);
      if (st && st.players > 1 && st.percentile != null) beat.textContent = "You beat " + st.percentile + "% of " + st.players + " players · average " + avgText(st.average_yards) + " yds";
      else if (st && st.players) beat.textContent = "Average drive today: " + avgText(st.average_yards) + " yds";
      return api("/api/play/me").catch(function () { return null; });
    }).then(function (me) { fillDrives(drivesBox, me); })
      .catch(function () { fillStats(statsBox, null, label); fillDrives(drivesBox, null); });
    saving.catch(function () { return null; }).then(function () {
      return Promise.all(puzzle.prompts.map(function (p, i) {
        return api("/api/play/reveal?date=" + encodeURIComponent(date) + "&prompt_id=" + encodeURIComponent(p.id))
          .then(function (r) { return { r: r, i: i }; });
      }));
    }).then(function (all) {
      rev.textContent = "";
      all.forEach(function (x) {
        var t = rec.tiers[x.i], mine = rec.names[x.i];
        var d = h("details", null, h("summary", null, h("span", null, x.r.text), h("span", null, t ? TIER[t][2] : SACK)));
        x.r.tiers.forEach(function (tr) {
          if (!tr.answers.length) return;
          d.appendChild(h("h3", null, tr.emoji + " " + tr.tier_name + " (" + tr.yards + " yds)"));
          // tiers[].details (optional) is a parallel list of {name, team, position, headshot, stat, stat_label}
          var list = (tr.details && tr.details.length === tr.answers.length) ? tr.details : tr.answers;
          var rich = list.some(function (a) { return a && typeof a === "object"; });
          var shown = list.slice(0, 12), more = list.length > 12 ? " and " + (list.length - 12) + " more" : "";
          if (rich) {
            var box = h("div", { "class": "dd-ans" });
            shown.forEach(function (a) {
              var nm = ansName(a), o = typeof a === "object" ? a : { name: nm };
              var sub = o.stat != null && o.stat !== "" ? String(o.stat) + (o.stat_label ? " " + o.stat_label : "") : "";
              box.appendChild(h("span", { "class": nm === mine ? "mine" : "" }, photo("", o, "u"), nm, sub ? h("em", null, sub) : null));
            });
            d.appendChild(box);
            if (more) d.appendChild(h("p", { "class": "dd-small" }, more.trim()));
          } else {
            var p = h("p");
            shown.forEach(function (n, k) {
              if (k) p.appendChild(document.createTextNode(", "));
              p.appendChild(n === mine ? h("span", { "class": "mine" }, n) : document.createTextNode(n));
            });
            if (more) p.appendChild(document.createTextNode(more));
            d.appendChild(p);
          }
        });
        rev.appendChild(d);
      });
    }).catch(function (e) {
      var msg = e && e.message && e.message.indexOf("unlock") >= 0 ? e.message : "Couldn't load the answer sheets. Reload to try again.";
      rev.textContent = "";
      rev.appendChild(h("p", { "class": "dd-small" }, msg));
    });
  }

  // ---------------------------------------------------------------- practice
  function practice() {
    setStage("intro"); field.setScene(0, 10, { number: 1 });
    mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Finding a prompt...")));
    api("/api/play/practice").then(function (r) {
      var ds0 = driveState([]);
      runPrompt({
        date: r.date, prompt: r.prompt, index: 0, total: 1, used: [], state: ds0,
        onDone: function (res, passed) {
          playMoment({ res: res, passed: passed, before: ds0, after: driveState(res ? [res.tier] : []), last: false, practice: true, seed: String(r.prompt.id), next: practice });
        }
      });
    }).catch(function (e) { setStage("intro"); mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Practice isn't available yet: " + e.message),
      h("button", { "class": "dd-btn alt", type: "button", onclick: boot }, "Back"))); });
  }

  // ---------------------------------------------------------------- intro (kickoff)
  function intro(puzzle) {
    var date = puzzle.date;
    var streak = streakNow(puzzle.today);
    var start = h("button", { "class": "dd-btn", type: "button", onclick: function () { startDaily(puzzle, null); } }, "Kickoff");
    var community = h("p", { "class": "dd-small dd-community" });
    setStage("intro"); field.setScene(0, 10, { number: 1 });
    mount(topBar(h("span", { "class": "dd-chip" }, "Streak ", h("b", null, streak))),
      h("div", { "class": "dd-hero" }, h("div", { "class": "k" }, "Lineup Lab · Night game"),
        h("div", { "class": "plate" }, h("h1", null, "The Daily Drive")),
        h("div", null, h("span", { "class": "d" }, longDate(date) + (date === puzzle.today ? " · today" : " · archive")))),
      h("div", { "class": "dd-spacer" }),
      h("div", { "class": "dd-card" },
        h("div", { "class": "dd-kick" }, "7 plays · 700 yards · 1 answer each"),
        h("p", null, "Type a player who fits. The rarer your answer, the bigger the play: a Checkdown gains 10 yards, a Highlight Reel TD gains 100. A wrong answer is a sack. Every answer is computed from real NFL data. 25 seconds on the play clock, after a 3-second snap count."),
        community, start),
      h("div", { "class": "dd-row dd-prow" },
        h("button", { "class": "dd-btn alt", type: "button", onclick: practice }, "Practice mode")),
      h("div", { "class": "dd-inpage" }, tierLegend()),
      h("div", { "class": "dd-inpage" }, lbNew(false)),
      pageFoot());
    announce("The Daily Drive. " + longDate(date) + ". Press Kickoff to start.");
    fetchStats(date).then(function (st) {
      if (st && st.players) community.textContent = (date === puzzle.today ? "Today" : prettyDate(date)) + "'s average drive: " + avgText(st.average_yards) +
        " yds across " + st.players + (st.players === 1 ? " player" : " players") + " so far.";
    });
  }

  // ---------------------------------------------------------------- boot
  function boot() {
    fx.stop(); setStage("intro"); field.setScene(0, 10, { number: 1 });
    mount(topBar(), h("div", { "class": "dd-spacer" }), h("div", { "class": "dd-card" }, h("p", null, "Loading today's game...")));
    var wanted = (new URLSearchParams(window.location.search)).get("date");
    api("/api/play/daily" + (wanted && /^\d{4}-\d{2}-\d{2}$/.test(wanted) ? "?date=" + wanted : "")).then(function (puzzle) {
      loadBoard(puzzle.date); loadSides(puzzle);
      var played = lsGet("dd.played." + puzzle.date);
      if (played) { showResults(puzzle, played); return; }
      var saved = lsGet("dd.saved");
      if (saved && saved.date === puzzle.date && Date.now() - saved.startedAt < SAVE_TTL_MS) { startDaily(puzzle, saved); return; }
      if (saved) lsDel("dd.saved");
      intro(puzzle);
    }).catch(function (e) {
      mount(topBar(), h("div", { "class": "dd-spacer" }), h("div", { "class": "dd-card" }, h("h2", null, "Today's game isn't ready"), h("p", null, e.message),
        h("button", { "class": "dd-btn", type: "button", onclick: boot }, "Try again")));
    });
  }

  // ---------------------------------------------------------------- dev hook: /play?demo=1 exposes window.ddDemo to run any play from the console (not in the UI, harmless otherwise)
  //   ddDemo.play(tier 1-6, {variant: 0-2 (tier 6 catch), p: ball yard line 0-99, number: 1-7, seek: seconds to freeze at}); ddDemo.sack({p, seek}); ddDemo.resume(); ddDemo.list
  if (/[?&]demo=1(&|$)/.test(window.location.search)) {
    var demoRun = function (tier, o) {
      o = o || {}; var p0 = o.p != null ? o.p : 25, g = tier ? TIER[tier][1] : 0, np = p0 + g, sc = np >= 100;
      var before = { yards: 0, p: p0, down: 1, dist: 10, td: 0, fd: Math.min(100, p0 + 10) };
      var after = { yards: g, p: sc ? np - 100 : np, down: 1, dist: 10, td: sc ? 1 : 0, fd: Math.min(100, (sc ? np - 100 : np) + 10) };
      fx.stop(); mount(null); setStage("play"); setPips([], 7, 2); setHud(before, { label: "PLAY 3 OF 7" }); field.setScene(p0, before.fd, { number: o.number || 3 });
      var res = tier ? { tier: tier, yards: g, name: "Demo Player", team: "KC", position: "WR", stat: 1234, stat_label: "rec yds" } : null;
      playMoment({ res: res, passed: false, before: before, after: after, last: false, variant: o.variant, seed: "demo", next: function () { root.setAttribute("data-phase", "idle"); } });
      if (o.seek != null && field.seek) field.seek(o.seek);
    };
    window.ddDemo = { play: demoRun, sack: function (o) { demoRun(0, o); }, resume: function () { field.seek && field.seek(null); }, field: field,
      team: function (code) { return loadStadium(code || ""); },
      list: { 1: "Checkdown", 2: "Quick Slant", 3: "Chain Mover", 4: "Chunk Play", 5: "Bomb", "6 (variant 0/1/2)": "Highlight Reel TD" } };
  }

  // ---------------------------------------------------------------- the favorite-team stadium: signed-in players with a favorite team play on
  // their team's field (real starters' numbers, this week's real opponent). Anyone else keeps the Lineup Lab field. Any failure is cosmetic.
  // The demo page previews a team without an account: /play?demo=1&team=SEA (or ddDemo.team("GB")).
  function loadStadium(previewCode) {
    var url;
    if (previewCode != null) url = "/api/play/stadium?preview=1&team=" + encodeURIComponent(previewCode);
    else {
      var code = "";
      try { code = (window.localStorage && window.localStorage.getItem("eb_team")) || ""; } catch (e) { code = ""; }
      url = "/api/play/stadium" + (/^[A-Z]{2,3}$/.test(code) ? "?team=" + code : "");
    }
    return api(url).then(function (r) {
      if (previewCode == null) setNavAuth(r ? !!r.signed_in : null);
      if (field.setTeam && r && (r.signed_in || previewCode != null)) field.setTeam(r.stadium || null);
      return r;
    }).catch(function () { return null; });
  }
  var demoTeam = /[?&]demo=1(&|$)/.test(window.location.search) && /[?&]team=([A-Za-z]{2,3})(&|$)/.exec(window.location.search);
  loadStadium(demoTeam ? demoTeam[1].toUpperCase() : undefined);
  boot();
})();
