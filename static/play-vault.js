/* The Daily Drive: the Team Vault. On a rare answer, a favorite-team player sees a real play from that team, redrawn in chunky
   retro pixels: a full 11-on-11 with real jersey numbers wherever the record has them (a blank jersey beats a guess). No
   explanation screen: the play runs, one small caption names it, and it goes straight back to the game. Bigger answers get
   slow motion, a louder crowd and an instant replay. Loaded only for players with a favorite team. Never changes the score.
   Any tap skips it. Exposes window.DDVault. */
(function () {
  "use strict";
  var KEY = "dd.vault.seen", LOW_W = 150, PX = 2.55, PY = 3.7;
  var COLOR = { 4: "#b866ff", 5: "#fff04d", 6: "#ffab1a" };
  var PACE = { 4: { hold: 0.55, sparks: 14 }, 5: { hold: 0.8, sparks: 30 }, 6: { hold: 0.65, sparks: 64 } };
  var DIG = ["111101101101111", "010110010010111", "111001111100111", "111001111001111", "101101111001001",
    "111100111001111", "111100111101111", "111001001001001", "111101111101111", "111101111001111"];
  // where each position lines up: [yards from center, yards from the line of scrimmage]
  var OSLOT = { OL: [[0, -0.7], [-3, -0.7], [3, -0.7], [-6, -0.7], [6, -0.7], [-9, -0.8]], TE: [[9.2, -0.8], [-9.2, -0.8], [12, -1]],
    WR: [[-21, -0.4], [21, -0.4], [-15, -1.3], [15, -1.3], [-11.5, -1.6]], RB: [[-3, -6.2], [3, -6.2], [0, -7]], FB: [[0, -3.9], [2, -4]], QB: [[0, -1.7], [5, -5]] };
  var DSLOT = { DL: [[-4.8, 1.4], [-1.6, 1.4], [1.6, 1.4], [4.8, 1.4], [8, 1.4], [-8, 1.4]], LB: [[-6.6, 5], [0, 5.3], [6.6, 5], [-11, 4.4], [11, 4.4]],
    CB: [[-21, 6.2], [21, 6.2], [-15, 6.6], [15, 6.6], [-10, 8]], S: [[-7, 13], [7, 13], [0, 15.5], [-14, 12]] };
  var data = null;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function ease(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function out(t) { t = clamp(t, 0, 1); return 1 - (1 - t) * (1 - t) * (1 - t); }
  function hash(s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function seenGet() { try { return JSON.parse(window.localStorage.getItem(KEY)) || []; } catch (e) { return []; } }
  function seenSet(v) { try { window.localStorage.setItem(KEY, JSON.stringify(v.slice(-400))); } catch (e) { /* private window */ } }
  function div(css, text) { var d = document.createElement("div"); d.style.cssText = css; if (text != null) d.textContent = text; return d; }
  function who(m, role) { for (var i = 0; i < m.players.length; i++) if (m.players[i].role === role) return m.players[i]; return null; }
  function group(pos) {
    var p = String(pos || "").toUpperCase();
    if (/^(C|G|T|OT|OG|OL)$/.test(p)) return "OL";
    if (p === "TE" || p === "WR" || p === "FB" || p === "QB") return p;
    if (p === "RB" || p === "HB") return "RB";
    if (/^(DT|NT|DE|DL)$/.test(p)) return "DL";
    if (/LB$/.test(p)) return "LB";
    if (p === "CB" || p === "DB") return "CB";
    if (/^(FS|SS|S|SAF)$/.test(p)) return "S";
    return null;
  }

  // ------------------------------------------------------------------ the 22 on the field
  function lineUp(rows, slots, side) {
    var used = {}, out2 = [];
    rows.forEach(function (r) {
      var g = group(r[0]) || (side === "o" ? "WR" : "CB"), list = slots[g], i = used[g] || 0;
      used[g] = i + 1;
      var s = list[i % list.length], extra = Math.floor(i / list.length);
      out2.push({ t: side, g: g, n: r[1] == null ? null : r[1], x0: s[0] + extra * 1.6, y0: s[1] - (side === "o" ? extra : -extra) * 1.2, key: null });
    });
    return out2;
  }
  function cast(m) {
    var kind = m.kind, qb = who(m, "qb"), tp = who(m, "target"), lu = m.lineup, o, d, i;
    if (lu && lu.o && lu.o.length === 11 && lu.d && lu.d.length === 11) { o = lineUp(lu.o, OSLOT, "o"); d = lineUp(lu.d, DSLOT, "d"); }
    else {
      var tg = kind === "run" ? "RB" : kind === "fumble" ? "TE" : "WR";
      var base = [["QB", qb && qb.number], ["RB", null], ["TE", null], ["WR", null], ["WR", null], ["WR", null], ["C", null], ["G", null], ["G", null], ["T", null], ["T", null]];
      for (i = 0; i < base.length; i++) if (base[i][0] === tg) { base[i] = [tg, tp && tp.number]; break; }
      o = lineUp(base, OSLOT, "o");
      d = lineUp([["DE"], ["DT"], ["DT"], ["DE"], ["OLB"], ["MLB"], ["OLB"], ["CB"], ["CB"], ["FS"], ["SS"]], DSLOT, "d");
      d.forEach(function (e) { e.n = null; });
    }
    var q = null, t = null, want = tp && tp.number != null ? tp.number : null, tg2 = kind === "run" ? "RB" : kind === "fumble" ? "TE" : "WR";
    o.forEach(function (e) { if (!q && e.g === "QB") q = e; });
    if (want != null) o.forEach(function (e) { if (!t && e.n === want && e !== q) t = e; });
    if (!t) o.forEach(function (e) { if (!t && e.g === tg2) t = e; });
    if (!t) o.forEach(function (e) { if (!t && e !== q && e.g !== "OL") t = e; });
    if (q) { q.key = "qb"; if (qb && qb.number != null) q.n = qb.number; }
    t.key = "target"; if (want != null) t.n = want;
    if (kind === "pass" && m.side && t.x0 * m.side < 0) {       // the target lines up on the side the ball really went
      var sx0 = t.x0, sy0 = t.y0, swap = null;
      o.forEach(function (e) { if (e !== t && Math.abs(e.x0 + sx0) < 0.1 && Math.abs(e.y0 - sy0) < 0.8) swap = e; });
      if (swap) swap.x0 = sx0;
      t.x0 = -sx0;
    }
    return { all: o.concat(d), target: t };
  }

  // ------------------------------------------------------------------ one play, as positions over time
  function plan(m, tEnt) {
    var los = 100 - m.from, sd = m.side || 0, yards = m.yards != null ? m.yards : m.end - los;
    var end = m.td ? Math.max(100.8, m.end || 101) : los + yards, T = { snap: 0.18 };
    var air = m.kind === "pass" ? clamp(m.air != null ? m.air : end - los, -4, Math.max(end - los, 1) + 3) : 0, cy = m.kind === "pass" ? Math.min(109, los + air) : end;
    var x0 = tEnt.x0, y0 = los + tEnt.y0, tx = m.kind === "pass" ? (sd ? sd * clamp(Math.abs(x0) * 0.6, 7, 16) : clamp(x0 * 0.12, -3, 3)) : 1;
    if (m.kind === "pass") { T.go = 0.78; T.hit = T.go + clamp(0.4 + Math.max(air, 0) * 0.014, 0.44, 1.05); T.end = T.hit + clamp(0.5 + Math.max(0, end - cy) * 0.045, 0.55, 2.3); }
    else if (m.kind === "fumble") { T.go = 0.82; T.hit = 1.78; T.end = 2.4; }
    else { T.go = 0.42; T.hit = 0.42; T.end = clamp(1.3 + Math.max(0, end - los) * 0.03, 1.5, 3.4); }
    function qb(t) {
      var u = ease((t - T.snap) / 0.55), r = m.kind === "pass" ? sd * 4 : 0;
      return { x: r * u, y: los - 1.7 - (m.kind === "run" ? 1.2 : 3.6) * u };
    }
    function target(t) {
      if (m.kind === "run") {
        var v = ease((t - T.snap) / (T.end - T.snap)), a = 1 - v, g = sd || -1, sw = clamp((end - los) * 0.3, 4, 20) * g;
        return { x: a * a * a * x0 + 3 * a * a * v * (x0 + sw) + 3 * a * v * v * sw * 0.2 + v * v * v * clamp(sw * 0.1, -3, 3),
          y: a * a * a * y0 + 3 * a * a * v * (los + 0.5) + 3 * a * v * v * (los + (end - los) * 0.4) + v * v * v * end };
      }
      if (t < T.hit) { var u = clamp((t - T.snap) / (T.hit - T.snap), 0, 1); return { x: lerp(x0, m.kind === "fumble" ? 1 : tx, u * u), y: lerp(y0, m.kind === "fumble" ? end : cy, u) }; }
      if (m.kind === "fumble") return { x: 1, y: end };
      var w = clamp((t - T.hit) / Math.max(0.3, T.end - T.hit - 0.18), 0, 1);
      return { x: lerp(tx, tx * 0.72, w), y: lerp(cy, end, m.td && end - cy < 1 ? w : out(w)) };
    }
    function jump(t) { return m.leap ? Math.max(0, Math.sin(clamp((t - T.hit + 0.24) / 0.55, 0, 1) * Math.PI)) * 7 : 0; }
    function ball(t) {
      var q = qb(t), r = target(t), u;
      if (t < T.go) return { x: q.x + 0.5, y: q.y + 0.4, h: 7 };
      if (m.kind === "run" || t >= T.hit) return { x: r.x + 0.5, y: r.y, h: 7 + jump(t) };
      u = (t - T.go) / (T.hit - T.go);
      var q0 = qb(T.go), r1 = target(T.hit);
      if (m.kind === "fumble") return { x: lerp(q0.x, r1.x, u) + Math.sin(u * 13) * 1.2, y: lerp(q0.y, r1.y, out(u)), h: Math.abs(Math.sin(u * Math.PI * 4)) * (1 - u) * 9 };
      return { x: lerp(q0.x, r1.x, u), y: lerp(q0.y, r1.y, u), h: lerp(8, 7 + jump(T.hit), u) + Math.sin(u * Math.PI) * (8 + Math.max(0, r1.y - q0.y) * 0.34) };
    }
    return { T: T, los: los, qb: qb, target: target, ball: ball, jump: jump };
  }

  // ------------------------------------------------------------------ the retro scene
  function makeScene(m, cv, uni) {
    var W = LOW_W, H = Math.max(260, Math.round(W * (cv.clientHeight || 700) / (cv.clientWidth || 380)));
    cv.width = W; cv.height = H;
    var g = cv.getContext("2d"), team = cast(m), pl = plan(m, team.target), T = pl.T, cam = 0, home = uni[m.team], away = uni[m.opp], tier = m.tier, cfg = PACE[tier];
    var sparks = [], cols = [home.jersey, home.trim, home.helmet, "#fff", COLOR[tier]], i;
    for (i = 0; i < cfg.sparks; i++) {
      var a = hash("a" + i) / 4294967295 * Math.PI * 2, s = 30 + (hash("s" + i) % 90);
      sparks.push({ vx: Math.cos(a) * s, vy: Math.sin(a) * s - 34, c: cols[i % cols.length], z: 1 + (hash("z" + i) % 3), life: 0.6 + (hash("l" + i) % 70) / 100 });
    }
    var tile = document.createElement("canvas"), tg, tx, ty;     // the crowd is one small baked tile, so it costs almost nothing to draw
    tile.width = tile.height = 48; tg = tile.getContext("2d"); tg.fillStyle = "#0c1222"; tg.fillRect(0, 0, 48, 48);
    for (tx = 0; tx < 48; tx += 2) for (ty = 0; ty < 48; ty += 3) { var fan = hash(tx + "|" + ty); tg.fillStyle = fan % 3 === 0 ? home.jersey : fan % 3 === 1 ? "#26324a" : "#46546f"; tg.fillRect(tx + (ty % 2), ty, 1, 2); }
    var crowd = g.createPattern(tile, "repeat"), year = String(m.iso_date).slice(0, 4);
    function rc(x, y, w, h, c) { g.fillStyle = c; g.fillRect(Math.round(x), Math.round(y), w, h); }
    function sx(x) { return W / 2 + x * PX; }
    function sy(y) { return H * 0.58 - (y - cam) * PY; }
    function digits(n, x, y, c) {
      var s = String(n), w = s.length * 4 - 1, x0 = Math.round(x - w / 2), k, j, gl;
      g.fillStyle = c;
      for (k = 0; k < s.length; k++) { gl = DIG[+s[k]]; if (!gl) continue; for (j = 0; j < 15; j++) if (gl[j] === "1") g.fillRect(x0 + k * 4 + (j % 3), y + ((j / 3) | 0), 1, 1); }
    }
    function flashes(x0, x1, y0, y1, t) {
      if (x1 <= x0 || y1 <= y0) return;
      var tick = Math.floor(t * 9), k, h;
      for (k = 0; k < 30; k++) { h = hash(tick + ":" + k + ":" + x0); rc(x0 + h % (x1 - x0), y0 + (h >>> 8) % (y1 - y0), 1, 2, "#fff"); }
    }
    function big(s, x, y, c) {
      g.fillStyle = c;
      for (var k = 0; k < s.length; k++) { var gl = DIG[+s[k]]; for (var j = 0; j < 15; j++) if (gl[j] === "1") g.fillRect(x + k * 8 + (j % 3) * 2, y + ((j / 3) | 0) * 2, 2, 2); }
    }
    function stands(t, hot) {
      var bottom = Math.round(sy(110)), y, k;
      if (bottom <= 0) return;
      rc(0, 0, W, bottom, "#070b16");
      for (y = 0; y < bottom; y += 5) rc(0, y, W, 2, "rgba(38,56,98," + (0.08 + 0.3 * y / bottom).toFixed(2) + ")");
      for (k = 0; k < 16; k++) { var st = hash("star" + k); rc(st % W, (st >>> 9) % Math.max(1, bottom - 62), 1, 1, "rgba(255,255,255,.5)"); }
      var deck = Math.max(4, bottom - 54);
      g.fillStyle = crowd; g.fillRect(0, deck, W, Math.max(0, bottom - 6 - deck));
      if (hot) flashes(0, W, deck, bottom - 7, t);
      rc(0, deck - 2, W, 2, home.jersey); rc(0, bottom - 6, W, 5, home.jersey); rc(0, bottom - 6, W, 1, home.trim);
      for (k = 5; k < W; k += 15) rc(k, bottom - 4, 8, 1, "rgba(255,255,255,.5)");
      [14, W - 17].forEach(function (lx) {
        rc(lx, deck - 24, 2, 24, "#39445c"); rc(lx - 5, deck - 31, 12, 7, "#39445c");
        for (var a2 = 0; a2 < 3; a2++) for (var c = 0; c < 2; c++) rc(lx - 4 + a2 * 4, deck - 30 + c * 3, 2, 2, "#fff4c8");
      });
      var bw = 44, bx = Math.round(W / 2 - bw / 2), by = Math.max(2, deck - 25);
      rc(bx - 2, by - 2, bw + 4, 22, "#26324a"); rc(bx, by, bw, 18, "#04060c"); rc(bx, by, bw, 2, home.jersey);
      big(year, bx + 7, by + 5, "#ffd84d"); rc(bx + bw / 2 - 1, by + 18, 3, Math.max(0, deck - by - 18), "#26324a");
    }
    function field(t, hot) {
      var top = cam + H * 0.58 / PY + 2, bot = cam - H * 0.42 / PY - 2, y, k, wide = Math.ceil(53.2 * PX);
      rc(0, 0, W, H, "#0a2c1a");
      stands(t, hot);
      for (y = Math.floor(bot / 5) * 5; y < top; y += 5) {
        if (y < 0 || y >= 100) continue;
        rc(sx(-26.6), sy(y + 5), wide, Math.ceil(5 * PY) + 1, (y / 5) & 1 ? "#1d7a3a" : "#186a32");
        for (k = 0; k < 9; k++) { var h = hash(y + ":" + k); rc(sx(-26 + (h % 520) / 10), sy(y + (h >> 9) % 5), 1, 1, h & 1 ? "#23884a" : "#14592a"); }
        rc(sx(-26.6), sy(y), wide, 1, "rgba(255,255,255,.72)");
        if (y % 10 === 0 && y > 0) { var n = y <= 50 ? y : 100 - y; digits(n, sx(-18), Math.round(sy(y)) + 2, "rgba(255,255,255,.55)"); digits(n, sx(18), Math.round(sy(y)) + 2, "rgba(255,255,255,.55)"); }
      }
      if (top > 100) {
        rc(sx(-26.6), sy(110), wide, Math.ceil(10 * PY), home.jersey);
        g.fillStyle = "rgba(255,255,255,.13)";
        for (k = -40; k < W; k += 11) for (y = 0; y < 34; y++) g.fillRect(k + y, Math.round(sy(110)) + y, 3, 1);
        rc(sx(-26.6), sy(100), wide, 2, "#fff"); rc(sx(-26.6), sy(110), wide, 2, "#fff");
        rc(sx(-3.1), sy(110) - 15, 19, 2, "#ffd84d"); rc(sx(-3.1), sy(110) - 26, 2, 12, "#ffd84d"); rc(sx(-3.1) + 17, sy(110) - 26, 2, 12, "#ffd84d"); rc(sx(0) - 1, sy(110) - 14, 2, 14, "#ffd84d");
      }
      var fieldTop = Math.max(0, Math.round(sy(110)));
      rc(sx(-26.6) - 1, fieldTop, 1, H - fieldTop, "#e9eef2"); rc(sx(26.6), fieldTop, 1, H - fieldTop, "#e9eef2");
      var edge = Math.round(sx(-26.6)) - 2, right = Math.round(sx(26.6)) + 2;
      g.fillStyle = crowd; g.fillRect(0, fieldTop, edge, H - fieldTop); g.fillRect(right, fieldTop, W - right, H - fieldTop);
      if (hot) { flashes(0, edge, fieldTop, H, t); flashes(right, W, fieldTop, H, t + 0.5); }
      rc(sx(-26.6), sy(pl.los), wide, 1, "#4aa8ff");
    }
    function man(e, p, t) {
      var u = e.t === "o" ? home : away, px = Math.round(sx(p.x)), py = Math.round(sy(p.y)), z = e.key === "target" ? Math.round(pl.jump(t)) : 0;
      var running = t > T.snap && (e.g !== "OL" && e.g !== "DL") && (e.key !== "target" || t < T.end - 0.12), run = running ? Math.floor(t * 11 + p.x * 2) & 1 : 0;
      rc(px - 3, py - 1, 8, 2, "rgba(0,0,0,.38)");
      py -= z;
      rc(px - 3, py - 4 - run, 2, 3 + run, u.pants); rc(px + 2, py - 4 - (running ? 1 - run : 0), 2, 3 + (running ? 1 - run : 0), u.pants);
      rc(px - 3, py - 1 - run, 2, 1, "#10131b"); rc(px + 2, py - 1 - (running ? 1 - run : 0), 2, 1, "#10131b");
      rc(px - 4, py - 10, 9, 6, u.jersey); rc(px - 5, py - 10, 1, 3 + run, "#d8a47a"); rc(px + 5, py - 10, 1, 3 + (1 - run), "#d8a47a");
      if (e.n != null) digits(e.n, px + 0.5, py - 10, u.num); else rc(px - 4, py - 10, 9, 1, u.trim);
      rc(px - 2, py - 14, 5, 4, u.helmet); rc(px - 2, py - 12, 5, 1, u.stripe || u.trim); rc(px, py - 14, 1, 4, u.trim);
      if (e.key) rc(px - 5, py + z + 1, 11, 1, COLOR[tier]);
    }
    function place(e, t) {
      if (e.key === "qb") return pl.qb(t);
      if (e.key === "target") return pl.target(t);
      var s = ease((t - T.snap) / 0.5), los = pl.los, pass = m.kind !== "run", dir = e.x0 > 0 ? -1 : 1;
      if (e.t === "o") {
        if (e.g === "OL") return { x: e.x0 + Math.sin(t * 6 + e.x0) * 0.18 * s, y: los + e.y0 + (pass ? -1.2 : 1.3) * s };
        if (e.g === "WR" || (e.g === "TE" && pass)) return { x: e.x0 + dir * 2.4 * ease((t - T.snap - 0.35) / 0.8), y: los + e.y0 + ease((t - T.snap) / 1.4) * (e.g === "WR" ? 14 : 6) };
        return { x: e.x0 * (1 - s * 0.3), y: los + e.y0 + s * 2.6 };
      }
      var b = pl.ball(t), q = pl.qb(t), chase = ease((t - T.hit + 0.5) / 0.9), base, reach = e.g === "DL" ? 0.25 : 0.84;
      if (e.g === "DL") base = { x: e.x0 + (q.x - e.x0) * 0.22 * s, y: los + e.y0 - 1.7 * s };
      else if (e.g === "LB") base = { x: e.x0, y: los + e.y0 + (pass ? 3 : -1.6) * s };
      else base = { x: e.x0 + dir * 1.4 * s, y: los + e.y0 + (pass ? 6 : -1) * s };
      return { x: lerp(base.x, b.x + e.x0 * 0.13, chase * reach), y: lerp(base.y, b.y + e.y0 * 0.12 - 0.5, chase * reach) };
    }
    return {
      T: T,
      draw: function (t, opts) {
        opts = opts || {};
        var b = pl.ball(t), hit = t >= T.hit, age = t - T.hit, k, hot = hit && tier >= 5;
        cam = Math.min(b.y + 1, 98);
        g.setTransform(1, 0, 0, 1, 0, 0);
        var shake = hit && age < 0.26 && tier >= 5 ? Math.round(Math.sin(age * 70) * (tier === 6 ? 2 : 1)) : 0;
        if (opts.zoom) { var fx = Math.round(sx(b.x)), fy = Math.round(sy(b.y) - 6); g.setTransform(2, 0, 0, 2, Math.round(W / 2 - fx * 2), Math.round(H * 0.46 - fy * 2)); }
        else if (shake) g.setTransform(1, 0, 0, 1, shake, 0);
        field(t, hot);
        var list = team.all.map(function (e) { return { e: e, p: place(e, t) }; });
        list.sort(function (x, y) { return y.p.y - x.p.y; });
        list.forEach(function (r) { man(r.e, r.p, t); });
        var bx = Math.round(sx(b.x)), by = Math.round(sy(b.y));
        if (b.h > 8.5) rc(bx - 1, by, 4, 1, "rgba(0,0,0,.42)");
        var fly = Math.round(by - b.h); rc(bx - 2, fly, 5, 3, "#7d421c"); rc(bx - 1, fly, 3, 1, "#a8622e"); rc(bx, fly + 1, 1, 1, "#fff");
        if (hit && age < 1.5 && (m.td || tier >= 5)) {
          var ox = sx(b.x), oy = sy(b.y) - 9;
          sparks.forEach(function (p) { if (age < p.life) rc(ox + p.vx * age, oy + p.vy * age + 62 * age * age, p.z, p.z, p.c); });
        }
        g.setTransform(1, 0, 0, 1, 0, 0);
        if (hit && age < 0.3 && tier >= 5) rc(0, 0, W, H, "rgba(255,255,255," + ((0.3 - age) * (tier === 6 ? 2.2 : 1.2)).toFixed(2) + ")");
        g.fillStyle = "rgba(0,0,0,.13)"; for (k = 0; k < H; k += 2) g.fillRect(0, k, W, 1);
      },
      count: team.all.length
    };
  }

  // ------------------------------------------------------------------ the moment on screen
  function show(m, host, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var finished = false, raf = 0, root;
      function close() {
        if (finished) return; finished = true; cancelAnimationFrame(raf);
        document.removeEventListener("keydown", onKey, true);
        if (root && root.parentNode) root.parentNode.removeChild(root);
        resolve();
      }
      function onKey(e) { if (e.key === "Enter" || e.key === " " || e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } }
      try {
        var cfg = PACE[m.tier], col = COLOR[m.tier], reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        var cond = 'font-family:var(--cond,"Barlow Condensed","Arial Narrow",sans-serif);';
        root = div("position:absolute;inset:0;z-index:40;overflow:hidden;background:#05080f;cursor:pointer;-webkit-tap-highlight-color:transparent");
        root.setAttribute("role", "img"); root.setAttribute("aria-label", m.title + ". " + m.sub + ". Recreation.");
        var cv = document.createElement("canvas"); cv.style.cssText = "position:absolute;inset:0;width:100%;height:100%;image-rendering:pixelated";
        root.appendChild(cv);
        var strip = div("position:absolute;left:10px;right:10px;bottom:14px;padding:6px 11px 7px;background:rgba(5,8,15,.86);border-left:4px solid " + col + ";pointer-events:none");
        strip.appendChild(div(cond + "font-weight:800;font-style:italic;font-size:23px;line-height:1;color:#fff", m.title));
        strip.appendChild(div(cond + "font-weight:700;font-size:15px;line-height:1.1;margin-top:3px;letter-spacing:.03em;color:" + col, m.sub));
        root.appendChild(strip);
        root.appendChild(div(cond + "position:absolute;right:9px;top:9px;padding:1px 6px;background:rgba(0,0,0,.62);color:#c3ccd9;font-weight:700;font-size:11px;letter-spacing:.14em;pointer-events:none", "RECREATION"));
        var badge = div(cond + "position:absolute;left:10px;top:9px;display:none;padding:2px 8px;background:#000;color:#fff;font-weight:800;font-size:13px;letter-spacing:.12em;border-left:3px solid #e5232e;pointer-events:none", "REPLAY");
        root.appendChild(badge);
        host.appendChild(root);
        var scene = makeScene(m, cv, (data && data.uniforms) || opts.uniforms), T = scene.T;
        DDVault.markSeen(m.id);
        root.addEventListener("click", function (e) { e.stopPropagation(); close(); });   // click, not pointerdown: a phone tap can't land on the next screen
        document.addEventListener("keydown", onKey, true);
        if (reduced) { scene.draw(T.end); setTimeout(close, 1500); return; }
        var phase = "play", sim = 0, hold = 0, buzzed = false, last = performance.now();
        var rate = function (t) { return m.tier < 5 ? 1.08 : 1 - (m.tier === 6 ? 0.66 : 0.5) * ease((t - T.hit + 0.34) / 0.14) * (1 - ease((t - T.hit - 0.12) / 0.16)); };
        var frame = function (now) {
          if (finished) return;
          try {
            var dt = Math.min(0.05, (now - last) / 1000); last = now;      // time-based, so a 30fps phone keeps the same pace
            if (phase === "play") {
              sim += dt * rate(sim); scene.draw(Math.min(sim, T.end));
              if (!buzzed && sim >= T.hit) { buzzed = true; if (opts.haptic) opts.haptic(); }
              if (sim >= T.end) { if (m.tier === 6) { phase = "replay"; sim = T.hit - 0.62; badge.style.display = "block"; } else phase = "hold"; }
            } else if (phase === "replay") {
              sim += dt * 0.58; scene.draw(sim, { zoom: true });
              if (sim >= T.hit + 0.36) { phase = "hold"; sim = T.end; badge.style.display = "none"; }
            } else { hold += dt; scene.draw(T.end); if (hold >= cfg.hold) { close(); return; } }
            raf = requestAnimationFrame(frame);
          } catch (err) { close(); }
        };
        raf = requestAnimationFrame(frame);
      } catch (err) { close(); }
    });
  }

  // ------------------------------------------------------------------ the review page: /play?demo=1&team=SF&browse=1
  var TEAMS = "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LA LAC LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split(" ");
  function browse(host) {
    var cond = 'font-family:var(--cond,"Barlow Condensed","Arial Narrow",sans-serif);', box = div("position:absolute;inset:0;z-index:35;overflow-y:auto;background:#070b14;padding:12px 12px 24px;color:#fff");
    var sel = document.createElement("select"); sel.style.cssText = cond + "width:100%;padding:9px;font-size:20px;font-weight:800;background:#161c2b;color:#fff;border:1px solid #2c3650;border-radius:6px";
    sel.setAttribute("aria-label", "Team");
    TEAMS.forEach(function (c) { var o = document.createElement("option"); o.value = o.textContent = c; if (data && c === data.team) o.selected = true; sel.appendChild(o); });
    sel.addEventListener("change", function () { window.location.search = "?demo=1&team=" + sel.value + "&browse=1"; });
    box.appendChild(sel);
    [6, 5, 4].forEach(function (t) {
      var rows = (data ? data.moments : []).filter(function (m) { return m.tier === t; });
      box.appendChild(div(cond + "margin:15px 0 5px;font-weight:800;font-size:15px;letter-spacing:.14em;color:" + COLOR[t], { 6: "HIGHLIGHT REEL", 5: "BOMB", 4: "CHUNK PLAY" }[t] + " · " + rows.length));
      rows.forEach(function (m) {
        var b = document.createElement("button"); b.type = "button"; b.style.cssText = "display:block;width:100%;margin:0 0 5px;padding:8px 10px;text-align:left;background:#121827;color:#fff;border:0;border-left:3px solid " + COLOR[t] + ";cursor:pointer";
        b.appendChild(div(cond + "font-weight:800;font-style:italic;font-size:19px;line-height:1.05", m.title)); b.appendChild(div(cond + "font-weight:600;font-size:14px;color:#aeb8c8;margin-top:2px", m.sub));
        b.addEventListener("click", function () { show(m, host); });
        box.appendChild(b);
      });
    });
    host.appendChild(box);
  }
  function still(m, cv, at) { var sc = makeScene(m, cv, data.uniforms); sc.draw(at === "end" ? sc.T.end : m.kind === "run" ? sc.T.end * 0.62 : sc.T.hit - 0.06); }

  var DDVault = window.DDVault = {
    load: function (url) {
      return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { data = j && j.moments && j.moments.length ? j : null; return data; }).catch(function () { data = null; return null; });
    },
    _set: function (j) { data = j; },
    _cast: function (m) { return cast(m).all; },
    byId: function (id) { return data ? data.moments.filter(function (m) { return m.id === id; })[0] || null : null; },
    list: function () { return data ? data.moments.slice() : []; },
    markSeen: function (id) { var s = seenGet(); if (s.indexOf(id) < 0) { s.push(id); seenSet(s); } },
    pick: function (tier, seed) {                     // an unseen play at this level, else the next level down; replays only once all were seen
      if (!data) return null;
      var pool = [], t;
      for (t = tier; t >= 4; t--) { pool = data.moments.filter(function (m) { return m.tier === t; }); if (pool.length) break; }
      if (!pool.length) return null;
      var seen = seenGet(), fresh = pool.filter(function (m) { return seen.indexOf(m.id) < 0; });
      if (!fresh.length) { var ids = pool.map(function (m) { return m.id; }); seenSet(seen.filter(function (x) { return ids.indexOf(x) < 0; })); fresh = pool; }
      return fresh[hash(seed) % fresh.length];
    },
    show: show,
    browse: browse,
    _still: still
  };
})();
