/* The Daily Drive: vanilla JS, no inline script (CSP script-src 'self'). Answers never reach this file until the game
   is over: every typed answer is judged by /api/play/check, and the full tier lists come from /api/play/reveal.
   The visuals (night-field stage, play clock, radar scan, player card, touchdown, drive chart) are all CSS/SVG/canvas;
   prefers-reduced-motion turns off particles, shakes and transitions (see REDUCED and the CSS media query). */
(function () {
  "use strict";
  var PREVIEW_MS = 3000, ANSWER_MS = 25000, SAVE_TTL_MS = 12 * 3600 * 1000, MAX_YARDS = 700, YPX = 5, SCAN_MIN_MS = 450;
  var TIER = {
    6: ["Hall of Famer", 100, "🏆"], 5: ["All-Pro", 85, "🟡"], 4: ["Pro Bowler", 60, "🟣"],
    3: ["Starter", 30, "🔴"], 2: ["Rotation", 15, "🔵"], 1: ["Benchwarmer", 10, "⚪"]
  };
  var TIER_COLOR = { 1: "#b3bccd", 2: "#6fd0ff", 3: "#ff4b55", 4: "#b866ff", 5: "#fff04d", 6: "#ffab1a" };   // grey, light blue, red, purple, yellow, gold
  var TIER_RGB = { 1: "179, 188, 205", 2: "111, 208, 255", 3: "255, 75, 85", 4: "184, 102, 255", 5: "255, 240, 77", 6: "255, 171, 26" };
  var TIER_GRAD = { 1: ["#e3e8f2", "#7d879c"], 2: ["#b6e9ff", "#2f9fe0"], 3: ["#ff8f94", "#c8202f"], 4: ["#dcaaff", "#7d33d6"], 5: ["#fffbb0", "#d8c200"], 6: ["#ffe4a3", "#d27800"] };
  var SACK = "⬛";
  var REDUCEDQ = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var REDUCED = !!(REDUCEDQ && REDUCEDQ.matches);
  if (REDUCEDQ && REDUCEDQ.addEventListener) REDUCEDQ.addEventListener("change", function (e) { REDUCED = e.matches; });
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
  function countUp(el, to, ms, prefix, from) {
    prefix = prefix || ""; from = from || 0;
    if (REDUCED || to === from) { el.textContent = prefix + to; return; }
    var t0 = performance.now();
    (function step(now) {
      var f = Math.min(1, (now - t0) / ms);
      el.textContent = prefix + Math.round(from + (to - from) * (1 - Math.pow(1 - f, 3)));
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
        confetti(90, MIX.concat(GOLDS));
      },
      stop: stop
    };
  })();

  // ---------------------------------------------------------------- the stage: night field, ball, depth gauge (persistent across screens)
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }
  function buildBall() {
    var s = svgEl("svg", { viewBox: "0 0 74 44", "class": "fv-ball", "aria-hidden": "true" });
    var defs = svgEl("defs"), g = svgEl("linearGradient", { id: "ddball", x1: "0", y1: "0", x2: "0", y2: "1" });
    g.appendChild(svgEl("stop", { offset: "0", "stop-color": "#e08a45" })); g.appendChild(svgEl("stop", { offset: "1", "stop-color": "#7a3a14" }));
    defs.appendChild(g); s.appendChild(defs);
    var grp = svgEl("g", { transform: "rotate(-14 37 22)" });
    grp.appendChild(svgEl("ellipse", { cx: 37, cy: 22, rx: 32, ry: 17, fill: "url(#ddball)", stroke: "#2a1206", "stroke-width": 1.5 }));
    grp.appendChild(svgEl("path", { d: "M12 10 Q9 22 12 34 M62 10 Q65 22 62 34", fill: "none", stroke: "#fff", "stroke-width": 2.2, opacity: 0.9 }));
    grp.appendChild(svgEl("path", { d: "M24 22 H50", stroke: "#fff", "stroke-width": 2, "stroke-linecap": "round" }));
    for (var i = 0; i < 5; i++) grp.appendChild(svgEl("path", { d: "M" + (27 + i * 5) + " 18.5 V25.5", stroke: "#fff", "stroke-width": 1.6, "stroke-linecap": "round" }));
    grp.appendChild(svgEl("ellipse", { cx: 34, cy: 13.5, rx: 18, ry: 3.4, fill: "#fff", opacity: 0.16 }));
    s.appendChild(grp);
    return s;
  }
  // Field zones, one per 100 yards (Krillion's depth zones, but on the gridiron)
  var ZONES = [
    ["The Tunnel", "everyone starts here. the crowd hasn't noticed you yet."],
    ["Own Territory", "dirt in your cleats. the long way home."],
    ["Midfield", "no man's land. even the refs lean in."],
    ["Enemy Territory", "their crowd is loud. your answers are louder."],
    ["The Red Zone", "the field shrinks. so does the margin for error."],
    ["The Goal Line", "inches from glory. don't fumble the typing."],
    ["Paydirt", "six points on the board. keep the ball high."]
  ];
  function zoneOf(y) { return ZONES[Math.min(ZONES.length - 1, Math.floor(y / 100))]; }
  function crossedTD(a, b) { return b > a && Math.floor(b / 100) > Math.floor(a / 100); }
  // Yard line for the footer: the drive starts at your own 25, and every 100 yards is a full trip down the field.
  function lineOf(y) {
    var p = (y + 25) % 100;
    return p === 0 ? "GOAL LINE" : p === 50 ? "MIDFIELD" : p < 50 ? "YOUR " + p : "THEIR " + (100 - p);
  }
  var GREEN_RGB = "25, 224, 138";
  function buildField() {
    var lines = h("div", { "class": "fv-lines" });
    lines.appendChild(h("div", { "class": "fv-ez" }, h("b", null, "END ZONE")));
    for (var n = 50; n <= 650; n += 50) {
      ["l", "r"].forEach(function (side) {
        var s = h("span", { "class": "fv-num " + side }, String(n)); s.style.bottom = (n * YPX - 20) + "px"; lines.appendChild(s);
      });
    }
    var turf = h("div", { "class": "fv-turf" }, lines);
    var lights = h("div", { "class": "fv-lights", "aria-hidden": "true" });
    [8, 19, 81, 92].forEach(function (x, i) { var l = h("i", { "class": "fv-lt" }); l.style.left = x + "%"; if (i % 2) l.style.top = "20%"; lights.appendChild(l); });
    var trail = h("div", { "class": "fv-trail" }), ring = h("div", { "class": "fv-ring" }), ring2 = h("div", { "class": "fv-ring b" }), pop = h("div", { "class": "fv-pop" });
    var ballwrap = h("div", { "class": "fv-ballwrap", "aria-hidden": "true" }, h("div", { "class": "fv-shadow" }), trail, h("div", { "class": "fv-bglow" }), ring, ring2, buildBall(), pop);
    var beam = h("div", { "class": "fv-beam", "aria-hidden": "true" });
    // yard markers down the side: 0 at the bottom, 700 (end zone) at the top, a pill per 100 yards
    var gfill = h("div", { "class": "fv-gfill" }), mark = h("div", { "class": "fv-gmark" }), markw = h("div", { "class": "fv-gmw" }, mark);
    markw.style.cssText = "position:absolute;left:0;right:0;top:0;bottom:0;transition:transform 1.25s cubic-bezier(0.2,0.85,0.2,1)";
    var gauge = h("div", { "class": "fv-gauge", role: "img", "aria-label": "Yards gauge, 0 to 700" }, h("div", { "class": "fv-gtrack" }, gfill), markw);
    for (var i = 0; i <= 7; i++) {
      var tk = h("i", { "class": "fv-gtick" }), gl = h("span", { "class": "fv-gl" }, i === 7 ? "700 TD" : String(i * 100));
      tk.style.bottom = gl.style.bottom = (i / 7 * 100) + "%"; tk.style.setProperty("--c", i === 7 ? "#ffab1a" : "#ffffff");
      gauge.appendChild(tk); gauge.appendChild(gl);
    }
    var readNum = h("b", null, "0"), read = h("div", { "class": "fv-read" }, h("small", null, "YARDS"), readNum);
    var zTd = h("div", { "class": "td" }), zName = h("div", { "class": "n" }), zFlav = h("div", { "class": "f" });
    var zone = h("div", { "class": "fv-zone" }, zTd, zName, zFlav);
    var liveTag = h("div", { "class": "fv-live" }, "NIGHT GAME"), foot = h("div", { "class": "fv-foot" }, "YOUR 25");
    var flare = h("div", { "class": "fv-flare", "aria-hidden": "true" }), alert = h("div", { "class": "fv-alert", "aria-hidden": "true" });
    var stamp = h("div", { "class": "fv-stamp", "aria-hidden": "true" }, "SACKED");
    var fv = h("div", { "class": "fv", role: "presentation" },
      h("div", { "class": "fv-sky" }), lights, h("div", { "class": "fv-crowd" }), h("div", { "class": "fv-turf-wrap" }, turf), h("div", { "class": "fv-haze" }),
      flare, alert, beam, ballwrap, h("div", { "class": "fv-hud" }, h("div", { "class": "fv-top" }, read, zone), liveTag), gauge, foot, stamp);
    var cur = 0, advT = 0, flT = 0, footT = 0;
    function showZone(y, cross) {
      var z = zoneOf(y);
      zName.textContent = z[0]; zFlav.textContent = z[1];
      zTd.textContent = "TOUCHDOWN #" + Math.floor(y / 100);
      zone.classList.remove("cross", "zin");
      if (cross) restart(zone, "cross"); else if (zone.getAttribute("data-z") !== z[0] && zone.getAttribute("data-z")) restart(zone, "zin");
      zone.setAttribute("data-z", z[0]);
    }
    showZone(0, false);
    return {
      el: fv,
      yards: function () { return cur; },
      setYards: function (y, animate, rgb) {
        y = Math.max(0, Math.min(MAX_YARDS, y));
        var gain = y - cur, anim = !!animate && !REDUCED, cross = anim && crossedTD(cur, y);
        ballwrap.style.setProperty("--gc", rgb || GREEN_RGB);
        fv.classList.toggle("fv-go", anim); void fv.offsetWidth;
        lines.style.transform = "translate3d(0," + (y * YPX) + "px,0)";
        gfill.style.transition = anim ? "" : "none"; markw.style.transition = anim ? "transform 1.25s cubic-bezier(0.2,0.85,0.2,1)" : "none";
        gfill.style.transform = "scaleY(" + (y / MAX_YARDS) + ")";
        markw.style.transform = "translateY(-" + (y / MAX_YARDS * 100) + "%)";
        gauge.setAttribute("aria-label", "Yards gauge: " + y + " of 700");
        countUp(readNum, y, 1100, "", cur);
        showZone(y, cross || (!REDUCED && crossedTD(cur, y)));
        clearTimeout(footT);
        if (anim) footT = setTimeout(function () { foot.textContent = lineOf(y); }, 1000); else foot.textContent = lineOf(y);
        if (anim && gain > 0) {
          ballwrap.style.setProperty("--g", String(Math.max(0.55, Math.min(2.1, gain / 55))));
          restart(ballwrap, "adv"); clearTimeout(advT); advT = setTimeout(function () { ballwrap.classList.remove("adv"); }, 1400);
          if (cross) restart(read, "pulse");
        }
        cur = y;
      },
      setMode: function (m, tag) { root.setAttribute("data-mode", m); liveTag.textContent = tag || "NIGHT GAME"; },
      flare: function (color, strength, big) {
        flare.style.setProperty("--tc", color); flare.style.setProperty("--ti", String(strength));
        flare.classList.toggle("big", !!big); restart(flare, "on");
        clearTimeout(flT); flT = setTimeout(function () { flare.classList.remove("on"); }, 1700);
      },
      ring: function (double) { restart(ring, "on"); if (double) restart(ring2, "on"); },
      pop: function (text) { pop.textContent = text; restart(pop, "on"); },
      beam: function () { restart(beam, "on"); },
      jolt: function () { restart(fv, "jolt"); },
      stamp: function (text, big) {
        stamp.textContent = text; stamp.classList.toggle("big", !!big); restart(stamp, "on"); setTimeout(function () { stamp.classList.remove("on"); }, 1900);
      },
      sack: function (quiet) {
        if (quiet) return;
        flare.classList.add("red"); this.flare("#ff2846", 1, false); setTimeout(function () { flare.classList.remove("red"); }, 1700);
        this.stamp("SACKED", false);
        restart(ballwrap, "sack"); setTimeout(function () { ballwrap.classList.remove("sack"); }, 600);
      },
      ballPoint: function () { var r = ballwrap.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
    };
  }

  // ---------------------------------------------------------------- today's leaderboard + brand (side column; both optional)
  var lbBox = h("div", { "class": "dd-card dd-lb", style: "display:none" });
  var brandBox = h("div", { "class": "dd-card dd-brandbox" }, h("img", { src: "/icons/icon-192.png", alt: "", width: 44, height: 44 }),
    h("b", null, "Lineup Lab"), h("span", null, "The Daily Drive"), h("span", null, "Know more. Go further."));
  var side = h("div", { "class": "dd-side" }, lbBox, brandBox);
  function boardRow(rank, name, yards, me) {
    return h("div", { "class": "dd-lb-row" + (me ? " me" : "") }, h("span", { "class": "r" }, String(rank)), h("span", null, name), h("span", { "class": "y" }, String(yards)));
  }
  function renderBoard(j) {
    lbBox.textContent = ""; lbBox.appendChild(h("h2", null, "Today's leaderboard"));
    var youRank = j.you && j.you.rank, shown = false;
    j.top.slice(0, 5).forEach(function (r) {
      var me = youRank != null && r.rank === youRank; if (me) shown = true;
      lbBox.appendChild(boardRow(r.rank, me ? "you" : r.name, r.yards, me));
    });
    if (j.you && !shown) lbBox.appendChild(boardRow(j.you.rank, "you", j.you.yards, true));
    lbBox.style.display = "";
  }
  function loadBoard(date) {
    api("/api/play/leaderboard?date=" + encodeURIComponent(date) + "&device_id=" + encodeURIComponent(deviceId())).then(function (j) {
      if (j && j.available && j.top && j.top.length) { renderBoard(j); return; }
      throw new Error("no board");
    }).catch(function () {
      // No leaderboard yet: fall back to today's average, or hide the panel
      fetchStats(date).then(function (st) {
        if (st && st.players) {
          lbBox.textContent = ""; lbBox.appendChild(h("h2", null, "Today's drive"));
          lbBox.appendChild(h("p", { "class": "dd-lb-avg" }, "Average " + avgText(st.average_yards) + " yds across " + st.players + (st.players === 1 ? " player" : " players")));
          lbBox.style.display = "";
        } else lbBox.style.display = "none";
      });
    });
  }

  // ---------------------------------------------------------------- app frame: top slot, persistent field, view slot, side column
  var topSlot = h("div", { "class": "dd-topslot" }), view = h("div", { "class": "dd-view" }), field = buildField();
  root.textContent = ""; root.appendChild(topSlot); root.appendChild(field.el); root.appendChild(view); root.appendChild(side);
  function mount(top) {
    topSlot.textContent = ""; if (top) topSlot.appendChild(top);
    view.textContent = "";
    for (var i = 1; i < arguments.length; i++) if (arguments[i]) view.appendChild(arguments[i]);
  }
  function setStage(mode, yards, animate, tag) {
    root.classList.remove("urgent");
    field.setMode(mode, tag);
    if (yards != null) field.setYards(yards, animate);
  }

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
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
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
  function topBar(extra) {
    return h("div", { "class": "dd-top" }, h("div", { "class": "dd-brand" }, "The Daily ", h("span", null, "Drive")), extra || null);
  }
  var shieldN = 0;
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
    var row = h("div", { "class": "dd-shields" });
    [1, 2, 3, 4, 5, 6].forEach(function (t) { row.appendChild(h("div", { "class": "dd-sh t" + t }, shield(t), h("div", { "class": "nm" }, TIER[t][0]), h("div", { "class": "pt" }, TIER[t][1] + " pts"))); });
    return h("div", { "class": "dd-card dd-tiers" }, h("h2", null, "Rarity tiers (points = yards)"), row);
  }
  function clock() {
    var C = 2 * Math.PI * 46;
    var bg = svgEl("circle", { "class": "bg", cx: 55, cy: 55, r: 46 }), fg = svgEl("circle", { "class": "fg", cx: 55, cy: 55, r: 46, "stroke-dasharray": C, "stroke-dashoffset": 0 });
    var svg = svgEl("svg", { viewBox: "0 0 110 110", "aria-hidden": "true" }); svg.appendChild(bg); svg.appendChild(fg);
    var num = h("b", null, "3");
    var el = h("div", { "class": "dd-clock snap", role: "img", "aria-label": "Play clock" }, svg, num);
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
        el.classList.remove("snap"); el.classList.toggle("low", msLeft <= 5000);
        el.setAttribute("aria-label", "Play clock: " + s + " seconds");
      }
    };
  }
  function pips(tiers, total, cur) {
    var box = h("div", { "class": "dd-pips", "aria-hidden": "true" });
    for (var i = 0; i < total; i++) {
      var cls = i < tiers.length ? (tiers[i] ? "p" + tiers[i] : "sk") : (i === cur ? "cur" : "");
      box.appendChild(h("i", { "class": cls }));
    }
    return box;
  }
  function touchdown(res) {
    var box = h("div", { "class": "dd-td", "aria-hidden": "true" }, h("div", { "class": "fl" }),
      h("div", { "class": "bn" }, h("strong", null, "TOUCHDOWN"), h("span", null, "+" + ((res && res.yards) || 100) + " YARDS · HALL OF FAMER")));
    document.body.appendChild(box);
    field.flare("#ffab1a", 1, true); field.stamp("END ZONE!", true);
    fx.touchdown();
    setTimeout(function () { if (box.parentNode) box.parentNode.removeChild(box); }, REDUCED ? 1800 : 3300);
  }
  // One distinct, escalating effect per tier: grey a quiet gain, light blue a crisp pop, red a hit, purple a burst,
  // yellow a big glowing play (light beam), gold the full-screen touchdown.
  function tierFx(t, res, crossed) {
    var c = TIER_COLOR[t], p = field.ballPoint();
    if (t === 1) field.pop("+" + res.yards);
    else if (t === 2) { field.ring(false); field.flare(c, 0.35, false); field.pop("+" + res.yards); }
    else if (t === 3) { field.ring(true); field.jolt(); field.flare(c, 0.6, false); field.pop("+" + res.yards); }
    else if (t === 4) { field.ring(true); field.flare(c, 0.75, false); fx.sparkle(p.x, p.y, c, 64); field.pop("+" + res.yards); }
    else if (t === 5) { field.beam(); field.ring(true); field.flare(c, 0.95, true); fx.sparkle(p.x, p.y, c, 70); setTimeout(function () { fx.sparkle(p.x, p.y - 60, "#ffffff", 50); }, 260); field.stamp("BIG PLAY", true); }
    else if (t === 6) touchdown(res);
    if (crossed && t !== 6 && !REDUCED) setTimeout(function () { fx.sparkle(p.x, p.y - 30, "#ffab1a", 46); }, 700);
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

  // ---------------------------------------------------------------- one prompt (shared by daily and practice)
  // opts: {date, prompt, index, total, tiers[], used[], resumeAnswerStart, onStart, onDone(result, passed)}
  // result = {tier, yards, name, id, token, team, position, headshot, stat, stat_label}
  function runPrompt(opts) {
    var prompt = opts.prompt, total = opts.total, deadline = 0, done = false, raf = 0, pending = false, warned = false;
    var rg = clock();
    var tag = h("div", { "class": "pr-tag" }, total > 1 ? "Prompt " : "Practice", total > 1 ? h("b", null, (opts.index + 1) + "/" + total) : null);
    var cat = h("div", { "class": "pr-cat" }, prompt.category);
    var text = h("p", { "class": "pr-text", style: "display:none" }, prompt.text);
    var redact = h("div", { "class": "bc-red", "aria-hidden": "true" }, h("i"), h("i"));
    var msg = h("div", { "class": "dd-msg", role: "status" });
    var sugg = h("div", { "class": "dd-sugg" });
    var input = h("input", { "class": "dd-input", type: "text", autocomplete: "off", autocapitalize: "words", autocorrect: "off",
      spellcheck: "false", enterkeyhint: "go", "aria-label": "Your answer", placeholder: "Get set..." });
    var go = h("button", { "class": "dd-btn dd-go", type: "submit" }, "Go");
    var pass = h("button", { "class": "dd-pass", type: "button", onclick: function () { if (!done && !pending && deadline) finish(null, true); } }, "Pass");
    var form = h("form", { "class": "dd-form", onsubmit: function (e) { e.preventDefault(); submit(input.value); } }, rg.el, input, go);
    input.addEventListener("input", function () { input.classList.remove("bad"); });
    var scan = h("div", { "class": "dd-scan", "aria-hidden": "true" }, h("div", { "class": "rad" }, h("div", { "class": "sw" }), h("i", { style: "left:30%;top:28%" }), h("i", { style: "left:66%;top:60%" })), h("p", null, "SCANNING ROSTER"));
    var card = h("div", { "class": "dd-card pr" }, h("div", { "class": "pr-head" }, tag, total > 1 ? pips(opts.tiers || [], total, opts.index) : null), cat, text, redact,
      h("div", { "class": "dd-play" }, form, h("div", { "class": "dd-help" }, h("span", null, "Press Enter to submit"), pass), msg, sugg, scan));
    input.disabled = true; go.disabled = true; pass.disabled = true;
    mount(topBar(h("span", { "class": "dd-chip" }, total > 1 ? "Down " : "Practice ", total > 1 ? h("b", null, (opts.index + 1) + "/" + total) : null)), card, tierLegend());
    setStage(total > 1 ? "play" : "practice", null, false, total > 1 ? "LIVE · PLAY " + (opts.index + 1) : "PRACTICE");
    announce("Prompt " + (opts.index + 1) + ". Category: " + prompt.category + ". Get ready.");

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

  // ---------------------------------------------------------------- result cards
  function playerCard(res, last, next) {
    var t = res.tier, tc = TIER_COLOR[t], team = teamColor(res.team) || tc;
    var card = h("div", { "class": "dd-card pc t" + t });
    card.style.setProperty("--tc", tc); card.style.setProperty("--team", team);
    var yds = h("span", { "class": "n" }, "+0");
    var meta = [];
    if (res.team) meta.push(h("b", null, String(res.team).toUpperCase()));
    if (res.position) meta.push(String(res.position).toUpperCase());
    var sub = h("div", { "class": "pc-sub" }, meta.length ? meta.reduce(function (a, m, i) { if (i) a.push(" · "); a.push(m); return a; }, []) : "Answer accepted");
    var statLabel = res.stat_label ? String(res.stat_label) : "";
    var hasStat = res.stat != null && res.stat !== "";
    card.appendChild(h("div", { "class": "pc-rib" }, h("span", { "class": "pc-shield" }, shield(t), TIER[t][0]), h("b", null, "TIER " + t)));
    card.appendChild(h("div", { "class": "pc-body" }, photo("pc-ph", res), h("div", { "class": "pc-id" }, h("div", { "class": "pc-name" }, res.name), sub)));
    if (hasStat || statLabel) card.appendChild(h("div", { "class": "pc-stat" }, hasStat ? h("b", null, String(res.stat)) : null, statLabel));
    card.appendChild(h("div", { "class": "pc-yds" }, h("div", null, yds, h("span", { "class": "n" }, h("em", null, "yds")))));
    var btn = h("button", { "class": "dd-btn", type: "button", onclick: function () { go(); } }, last ? "See results" : "Next play");
    card.appendChild(h("div", { "class": "pc-foot" }, btn));
    var timer = 0, went = false;
    function go() { if (went) return; went = true; clearTimeout(timer); next(); }
    countUp(yds, res.yards, 800, "+");
    timer = setTimeout(go, t === 6 ? 4600 : 3000);
    announce("Accepted: " + res.name + ", " + TIER[t][0] + ", plus " + res.yards + " yards." + (t === 6 ? " Touchdown!" : ""));
    return card;
  }
  function sackCard(last, next, passed) {
    var card = h("div", { "class": "dd-card pc sacked" + (passed ? " passed" : "") });
    var btn = h("button", { "class": "dd-btn", type: "button", onclick: function () { go(); } }, last ? "See results" : "Next play");
    card.appendChild(h("div", { "class": "pc-rib" }, h("span", null, SACK + " No gain"), h("b", null, "0 YDS")));
    card.appendChild(h("div", { "class": "pc-body" }, h("div", { "class": "pc-name" }, passed ? "PASSED" : "SACKED"),
      h("div", { "class": "pc-sub" }, passed ? "You skipped the play. The ball stays put." : "Time ran out. The ball stays put.")));
    card.appendChild(h("div", { "class": "pc-foot" }, btn));
    var timer = 0, went = false;
    function go() { if (went) return; went = true; clearTimeout(timer); next(); }
    timer = setTimeout(go, 2600);
    announce(passed ? "Passed. No yards." : "Sacked. Time ran out. No yards.");
    return card;
  }
  function resultCard(res, last, next, passed) { return res ? playerCard(res, last, next) : sackCard(last, next, passed); }

  // ---------------------------------------------------------------- daily game
  function startDaily(puzzle, saved) {
    var date = puzzle.date, prompts = puzzle.prompts, total = prompts.length;
    var st = saved || { date: date, startedAt: Date.now(), idx: 0, tiers: [], names: [], ids: [], tokens: [], answerStart: 0 };
    if (!st.tokens) st.tokens = [];
    function persist() { lsSet("dd.saved", st); }
    persist();
    field.setYards(yardsOf(st.tiers), false);

    function step() {
      if (st.idx >= total) { return finishGame(); }
      var resume = st.answerStart && Date.now() < st.answerStart + ANSWER_MS ? st.answerStart : 0;
      if (st.answerStart && !resume) {                           // the real deadline passed while the page was closed
        st.tiers.push(0); st.names.push(""); st.idx++; st.answerStart = 0; persist(); return step();
      }
      runPrompt({
        date: date, prompt: prompts[st.idx], index: st.idx, total: total, tiers: st.tiers.slice(), used: st.ids.slice(),
        resumeAnswerStart: resume,
        onStart: function (ts) { st.answerStart = ts; persist(); },
        onDone: function (res, passed) {
          var before = yardsOf(st.tiers);
          st.tiers.push(res ? res.tier : 0); st.names.push(res ? res.name : ""); if (res) { st.ids.push(res.id); if (res.token) st.tokens.push(res.token); }
          st.idx++; st.answerStart = 0; persist();
          var last = st.idx >= total, after = yardsOf(st.tiers);
          mount(topBar(h("span", { "class": "dd-chip" }, "Play ", h("b", null, st.idx + "/" + total))), resultCard(res, last, step, passed), tierLegend());
          field.setYards(after, true, res ? TIER_RGB[res.tier] : null);
          if (res) tierFx(res.tier, res, crossedTD(before, after)); else field.sack(passed);
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
  function showResults(puzzle, rec) {
    var date = puzzle.date, today = puzzle.today === date;
    var streak = today ? streakNow(date) : 0;
    var text = shareText(date, rec.tiers);
    var copy = h("button", { "class": "dd-btn", type: "button" }, "Copy result");
    copy.addEventListener("click", function () { copyText(text, copy); });
    var num = h("div", { "class": "dd-fin" }, "0");
    var rev = h("div", { "class": "dd-rev" }, h("p", { "class": "dd-small" }, "Loading the answer sheets..."));
    var statsBox = h("div", { "class": "dd-card dd-stats" }, h("h2", null, "How everyone drove"), h("p", { "class": "dd-small" }, "Loading community stats..."));
    var drivesBox = h("div", { "class": "dd-card dd-drives" }, h("h2", null, "Your drives"), h("p", { "class": "dd-small" }, "Loading..."));
    var card = h("div", { "class": "dd-card dd-total" },
      h("h2", null, "Drive chart · " + prettyDate(date)), num, h("div", { "class": "dd-small" }, "yards of " + MAX_YARDS),
      driveChart(rec.tiers), legend(),
      h("div", { "class": "dd-share", "aria-label": "Share card" }, text), copy);
    mount(topBar(streak ? h("span", { "class": "dd-chip" }, "Streak ", h("b", null, streak)) : null), card,
      statsBox, drivesBox,
      h("div", { "class": "dd-card" }, h("h2", null, "Every answer, by tier"), rev),
      h("div", { "class": "dd-row" }, h("button", { "class": "dd-btn alt", type: "button", onclick: practice }, "Practice mode"),
        h("a", { "class": "dd-btn alt dd-link", href: "/" }, "Open Lineup Lab")));
    setStage("result", rec.yards, field.yards() === rec.yards ? false : true, "FINAL");
    countUp(num, rec.yards, 1100);
    announce("Final score: " + rec.yards + " yards of " + MAX_YARDS + ".");
    var label = today ? "Today" : prettyDate(date);
    submitScore(puzzle, rec).then(function (saved) {
      loadBoard(date);
      return (saved && saved.stats ? Promise.resolve(saved.stats) : fetchStats(date));
    }).then(function (st) {
      fillStats(statsBox, st, label, rec.yards);
      return api("/api/play/me").catch(function () { return null; });
    }).then(function (me) { fillDrives(drivesBox, me); })
      .catch(function () { fillStats(statsBox, null, label); fillDrives(drivesBox, null); });
    var jobs = puzzle.prompts.map(function (p, i) {
      return api("/api/play/reveal?date=" + encodeURIComponent(date) + "&prompt_id=" + encodeURIComponent(p.id))
        .then(function (r) { return { r: r, i: i }; });
    });
    Promise.all(jobs).then(function (all) {
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
    }).catch(function () { rev.textContent = "Couldn't load the answer sheets. Reload to try again."; });
  }

  // ---------------------------------------------------------------- practice
  function practice() {
    setStage("practice", 0, false, "PRACTICE");
    mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Finding a prompt...")));
    api("/api/play/practice").then(function (r) {
      runPrompt({
        date: r.date, prompt: r.prompt, index: 0, total: 1, used: [],
        onDone: function (res, passed) {
          var again = h("button", { "class": "dd-btn", type: "button", onclick: practice }, "Another prompt");
          var back = h("button", { "class": "dd-btn alt", type: "button", onclick: boot }, "Back to today's game");
          var out;
          if (res) {
            out = playerCard(res, false, function () {});
            var foot = out.querySelector(".pc-foot"); foot.textContent = "";
            foot.appendChild(h("p", { "class": "dd-small" }, "Practice does not count toward your streak.")); foot.appendChild(again);
            foot.appendChild(h("div", { style: "height:8px" })); foot.appendChild(back);
          } else {
            out = sackCard(false, function () {}, passed);
            var f2 = out.querySelector(".pc-foot"); f2.textContent = "";
            f2.appendChild(h("p", { "class": "dd-small" }, "Practice does not count toward your streak.")); f2.appendChild(again);
            f2.appendChild(h("div", { style: "height:8px" })); f2.appendChild(back);
          }
          mount(topBar(), out);
          field.setYards(res ? res.yards : 0, true, res ? TIER_RGB[res.tier] : null);
          if (res) tierFx(res.tier, res, false); else field.sack(passed);
        }
      });
    }).catch(function (e) { mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Practice isn't available yet: " + e.message),
      h("button", { "class": "dd-btn alt", type: "button", onclick: boot }, "Back"))); });
  }

  // ---------------------------------------------------------------- intro (kickoff)
  function intro(puzzle) {
    var date = puzzle.date;
    var streak = streakNow(puzzle.today);
    var start = h("button", { "class": "dd-btn", type: "button", onclick: function () { startDaily(puzzle, null); } }, "Kickoff");
    var community = h("p", { "class": "dd-small dd-community" });
    setStage("intro", 0, false, "NIGHT GAME");
    mount(topBar(h("span", { "class": "dd-chip" }, "Streak ", h("b", null, streak))),
      h("div", { "class": "dd-card dd-hero" }, h("div", { "class": "k" }, "Lineup Lab · Night game"),
        h("div", { "class": "plate" }, h("h1", null, "The Daily Drive")),
        h("div", null, h("span", { "class": "d" }, longDate(date) + (date === puzzle.today ? " · today" : " · archive")))),
      h("div", { "class": "dd-card" },
        h("div", { "class": "dd-kick" }, "7 plays · 700 yards · 1 answer each"),
        h("p", null, "Type a player who fits. The rarer your answer, the more yards you gain, and every answer is computed from real NFL data. 25 seconds on the play clock, after a 3-second snap count."),
        community, start),
      tierLegend(),
      h("div", { "class": "dd-row" },
        h("button", { "class": "dd-btn alt", type: "button", onclick: practice }, "Practice mode")));
    announce("The Daily Drive. " + longDate(date) + ". Press Kickoff to start.");
    fetchStats(date).then(function (st) {
      if (st && st.players) community.textContent = (date === puzzle.today ? "Today" : prettyDate(date)) + "'s average drive: " + avgText(st.average_yards) +
        " yds across " + st.players + (st.players === 1 ? " player" : " players") + " so far.";
    });
  }

  // ---------------------------------------------------------------- boot
  function boot() {
    setStage("intro", 0, false, "NIGHT GAME");
    mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Loading today's game...")));
    var wanted = (new URLSearchParams(window.location.search)).get("date");
    api("/api/play/daily" + (wanted && /^\d{4}-\d{2}-\d{2}$/.test(wanted) ? "?date=" + wanted : "")).then(function (puzzle) {
      loadBoard(puzzle.date);
      var played = lsGet("dd.played." + puzzle.date);
      if (played) { showResults(puzzle, played); return; }
      var saved = lsGet("dd.saved");
      if (saved && saved.date === puzzle.date && Date.now() - saved.startedAt < SAVE_TTL_MS) { startDaily(puzzle, saved); return; }
      if (saved) lsDel("dd.saved");
      intro(puzzle);
    }).catch(function (e) {
      mount(topBar(), h("div", { "class": "dd-card" }, h("h2", null, "Today's game isn't ready"), h("p", null, e.message),
        h("button", { "class": "dd-btn", type: "button", onclick: boot }, "Try again")));
    });
  }
  boot();
})();
