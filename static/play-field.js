/* The Daily Drive: the field scene. One full-bleed canvas, viewed from behind the offense looking downfield, with the
   quarterback, his receivers and the defense drawn in code. A graded answer runs a designated play on it (see PLAYS and
   buildPlay): snap and dropback, throw with a fake-3D arc, catch and yards after the catch, tackle at exactly the yards earned,
   camera pan back to the new line of scrimmage. Exposes window.DDField.create(canvas). One requestAnimationFrame loop, only
   running while something moves; prefers-reduced-motion swaps every animation for a short fade. No dependencies. */
(function () {
  "use strict";
  var PI = Math.PI, TAU = PI * 2;
  var ACCENT = "#19e08a";
  var FONT = '"Barlow Condensed","Roboto Condensed","Arial Narrow","Helvetica Neue",Arial,sans-serif';
  var XS = 26.65, Z0 = 70;          // half field width (yards); perspective depth constant
  var COLORS = { 1: "#b3bccd", 2: "#6fd0ff", 3: "#ff4b55", 4: "#b866ff", 5: "#fff04d", 6: "#ffab1a" };
  var SKINS = ["#f0c8a0", "#c68642", "#8d5524", "#e0ac69", "#a86f45"];

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function sstep(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function eio3(t) { t = clamp(t, 0, 1); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function eo3(t) { t = clamp(t, 0, 1); return 1 - Math.pow(1 - t, 3); }
  function ei2(t) { t = clamp(t, 0, 1); return t * t; }
  function rng(seed) {
    var a = seed >>> 0;
    return function () { a = (a + 0x6D2B79F5) | 0; var t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function hashStr(s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

  // ------------------------------------------------------------------ routes: piecewise cubic beziers in (x, y) = (yards right of center, yards past the line of scrimmage)
  function P2(x, y) { return { x: x, y: y }; }
  function cub(a, b, c, d, u) {
    var v = 1 - u, A = v * v * v, B = 3 * v * v * u, C = 3 * v * u * u, D = u * u * u;
    return { x: A * a.x + B * b.x + C * c.x + D * d.x, y: A * a.y + B * b.y + C * c.y + D * d.y };
  }
  function seg(a, d) { return [a, P2(lerp(a.x, d.x, 1 / 3), lerp(a.y, d.y, 1 / 3)), P2(lerp(a.x, d.x, 2 / 3), lerp(a.y, d.y, 2 / 3)), d]; }
  function makePath(segs) {
    var lens = [], tot = 0, i, k;
    for (i = 0; i < segs.length; i++) {
      var s = segs[i], len = 0, pr = s[0];
      for (k = 1; k <= 10; k++) { var q = cub(s[0], s[1], s[2], s[3], k / 10); len += Math.hypot(q.x - pr.x, q.y - pr.y); pr = q; }
      lens.push(len); tot += len;
    }
    return function (u) {
      u = clamp(u, 0, 1); var want = u * tot, acc = 0;
      for (var j = 0; j < segs.length; j++) {
        if (want <= acc + lens[j] || j === segs.length - 1) return cub(segs[j][0], segs[j][1], segs[j][2], segs[j][3], lens[j] ? clamp((want - acc) / lens[j], 0, 1) : 1);
        acc += lens[j];
      }
    };
  }

  // ------------------------------------------------------------------ formation (x right of center, y past the line of scrimmage, in yards)
  var FORM = [
    { k: "ol1", t: "ol", o: 1, x: -5, y: 0, n: 70 }, { k: "ol2", t: "ol", o: 1, x: -2.5, y: 0, n: 64 }, { k: "c", t: "ol", o: 1, x: 0, y: 0, n: 52 },
    { k: "ol4", t: "ol", o: 1, x: 2.5, y: 0, n: 66 }, { k: "ol5", t: "ol", o: 1, x: 5, y: 0, n: 76 },
    { k: "te", t: "te", o: 1, x: 8, y: 0, n: 85 }, { k: "wrL", t: "wr", o: 1, x: -15, y: 0, n: 11 }, { k: "wrR", t: "wr", o: 1, x: 15, y: 0, n: 18 },
    { k: "rb", t: "rb", o: 1, x: -4, y: -5, n: 28 }, { k: "qb", t: "qb", o: 1, x: 0, y: -4.6, n: 1 },
    { k: "dl1", t: "dl", x: -4, y: 1.8, n: 91 }, { k: "dl2", t: "dl", x: -1.4, y: 1.8, n: 97 }, { k: "dl3", t: "dl", x: 1.4, y: 1.8, n: 93 }, { k: "dl4", t: "dl", x: 4, y: 1.8, n: 99 },
    { k: "lbL", t: "lb", x: -5.5, y: 5, n: 54 }, { k: "lbR", t: "lb", x: 5.5, y: 5, n: 52 },
    { k: "cbL", t: "cb", x: -15.5, y: 6.5, n: 24 }, { k: "cbR", t: "cb", x: 15.5, y: 6.5, n: 21 },
    { k: "sL", t: "s", x: -8, y: 19, n: 29 }, { k: "sR", t: "s", x: 8, y: 19, n: 31 }
  ];

  // ------------------------------------------------------------------ the plays. spec(): receiver, route, catch, yards after catch, tackler, camera and ball behaviour.
  // g = yards gained on the play (the tackle spot is exactly g past the line of scrimmage), a = air yards (where the catch happens).
  function splitAir(def, g, score) { return clamp(Math.min(def, g * 0.62), 1.2, def); }

  function playSpec(tier, g, variant, rem, score) {
    var s = { tier: tier, color: COLORS[tier], g: g, score: !!score, throwDur: 0.8, yacDur: 0.5, camDur: 0.6, arc: 50, bscale: 1.3, trail: "none", lead: 0, zoomOut: 0, zoomIn: 0, slow: null, shake: 0, lag: 1.3, cov: {}, sDrop: 5, thud: 0 };
    var a, c;
    if (tier === 1) {                                              // Checkdown: flat route to the back, low fast dart, no trail
      a = splitAir(1.6, g, score); s.rk = "rb"; s.tk = "cbL"; s.throwDur = 0.45; s.yacDur = 0.62; s.camDur = 0.35; s.arc = 9; s.bscale = 1.12; s.thud = 2.2;
      s.route = makePath([[P2(-4, -5), P2(-7.5, -5.4), P2(-10.5, -2.2), P2(-12.6, a)]]);
      s.catchPt = P2(-12.6, a);
      s.yac = makePath([[s.catchPt, P2(-15, a + (g - a) * 0.45), P2(-15.2, a + (g - a) * 0.8), P2(-14.6, g)]]);
      s.end = P2(-14.6, g); s.lag = 0.8; s.cov = { lbL: 0.5 };
    } else if (tier === 2) {                                       // Quick Slant: stem, sharp 45-degree cut inside, line drive, thin white trail, zoom on the catch
      a = splitAir(7, g, score); var st = Math.min(2.6, a * 0.4);
      s.rk = "wrR"; s.tk = "lbR"; s.throwDur = 0.5; s.yacDur = 0.62; s.camDur = 0.55; s.arc = 13; s.bscale = 1.18; s.trail = "thin"; s.zoomIn = 0.075;
      s.route = makePath([seg(P2(15, 0), P2(15, st)), seg(P2(15, st), P2(15 - (a - st), a))]);
      s.catchPt = P2(15 - (a - st), a);
      s.yac = makePath([[s.catchPt, P2(s.catchPt.x - 1.2, a + (g - a) * 0.4), P2(s.catchPt.x - 2.4, a + (g - a) * 0.75), P2(s.catchPt.x - 3, g)]]);
      s.end = P2(s.catchPt.x - 3, g); s.lag = 1.1; s.thud = 1.2;
    } else if (tier === 3) {                                       // Chain Mover: deep dig past the first-down line, medium arc
      a = splitAir(16, g, score); var stem = Math.max(2, a - 1.5);
      s.rk = "wrL"; s.tk = "sL"; s.throwDur = 0.8; s.yacDur = 0.66; s.arc = 58; s.bscale = 1.5; s.lead = 0.12; s.lag = 1.6; s.cov = { sL: 0.2 }; s.thud = 3;
      s.route = makePath([seg(P2(-15, 0), P2(-15, stem)), seg(P2(-15, stem), P2(-4.5, a))]);
      s.catchPt = P2(-4.5, a);
      s.yac = makePath([[s.catchPt, P2(-3, a + (g - a) * 0.4), P2(-1.5, a + (g - a) * 0.75), P2(-0.8, g)]]);
      s.end = P2(-0.8, g);
    } else if (tier === 4) {                                       // Chunk Play: deep post splitting two safeties, high lob, glowing purple trail, camera zooms out mid-throw
      a = splitAir(37, g, score); var stem4 = a * 0.55;
      s.rk = "wrR"; s.tk = "sL"; s.throwDur = 0.95; s.yacDur = 0.9; s.arc = 105; s.bscale = 1.9; s.trail = "glow"; s.zoomOut = 0.16; s.lead = 0.22; s.lag = 2.2; s.cov = { sL: 0, sR: 0 }; s.sDrop = 9; s.thud = 3.5;
      s.route = makePath([seg(P2(15, 0), P2(14.6, stem4)), seg(P2(14.6, stem4), P2(1.5, a))]);
      s.catchPt = P2(1.5, a);
      s.yac = makePath([[s.catchPt, P2(0.8, a + (g - a) * 0.4), P2(-0.4, a + (g - a) * 0.75), P2(-1.2, g)]]);
      s.end = P2(-1.2, g);
    } else if (tier === 5) {                                       // Bomb: go route against double coverage, huge rainbow, slow-motion catch, screen shake
      a = splitAir(52, g, score);
      s.rk = "wrL"; s.tk = "sL"; s.throwDur = 1.15; s.yacDur = 1.0; s.camDur = 0.7; s.arc = 175; s.bscale = 2.5; s.trail = "glow"; s.lead = 0.3; s.lag = 3.2; s.cov = { sL: 0.25 }; s.sDrop = 14; s.shake = 7; s.zoomOut = 0.06;
      s.slow = [0.3, 0.7];
      s.route = makePath([[P2(-15, 0), P2(-17.5, a * 0.35), P2(-18, a * 0.7), P2(-14, a)]]);
      s.catchPt = P2(-14, a);
      s.yac = makePath([[s.catchPt, P2(-12, a + (g - a) * 0.35), P2(-9, a + (g - a) * 0.7), P2(-6.5, g)]]);
      s.end = P2(-6.5, g);
    } else {                                                       // Highlight Reel TD: three signature catches
      s.score = true; s.variant = variant; s.color = COLORS[6]; s.bscale = 1.9; s.trail = "glow"; s.lead = 0.28; s.arc = 120; s.camDur = 0.7;
      if (variant === 0) {                                         // one-handed grab falling backward in the end zone
        a = rem + 3.5; s.rk = "wrR"; s.tk = "cbR"; s.throwDur = 1.0; s.yacDur = 0.7; s.lag = 0.7; s.cov = { cbR: 0.95 };
        s.route = makePath([[P2(15, 0), P2(16.5, a * 0.4), P2(13, a * 0.72), P2(9, a)]]);
        s.catchPt = P2(9, a); s.yac = makePath([seg(s.catchPt, P2(8.6, a - 1.3))]); s.end = P2(8.6, a - 1.3);
      } else if (variant === 1) {                                  // toe-tap in the back corner
        a = rem + 5.5; s.rk = "wrR"; s.tk = "cbR"; s.throwDur = 1.05; s.yacDur = 0.7; s.lag = 0.5; s.cov = { cbR: 0.95 };
        s.route = makePath([[P2(15, 0), P2(19, a * 0.45), P2(23.4, a * 0.75), P2(22.2, a)]]);
        s.catchPt = P2(22.2, a); s.yac = makePath([seg(s.catchPt, P2(22.6, a + 0.5))]); s.end = P2(22.6, a + 0.5);
      } else {                                                     // catch and run: juke, spin, dive for the pylon
        a = clamp(rem * 0.42, 6, 38); var run = Math.max(2, rem - a); s.rk = "wrL"; s.tk = "cbR"; s.throwDur = 0.85; s.yacDur = 1.15 + Math.min(0.5, run * 0.009); s.lag = 1.4; s.cov = { cbR: 0 };
        s.route = makePath([[P2(-15, 0), P2(-10, a * 0.35), P2(-6, a * 0.8), P2(-2, a)]]);
        s.catchPt = P2(-2, a);
        s.yac = makePath([[s.catchPt, P2(-6.5, a + run * 0.14), P2(11, a + run * 0.3), P2(14, a + run * 0.52)], [P2(14, a + run * 0.52), P2(18, a + run * 0.7), P2(23, a + run * 0.88), P2(24.6, rem + 0.4)]]);
        s.end = P2(24.6, rem + 0.4);
      }
      s.g = rem; s.score = true;
    }
    s.air = a; s.endY = s.end.y;
    return s;
  }

  // ------------------------------------------------------------------ the field
  function create(canvas, options) {
    options = options || {};
    var reducedQ = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    var ctx = canvas.getContext("2d");
    var W = 0, H = 0, dpr = 1, L = { u: 1, cx: 0, ay: 0, pxX: 7, ppy: 8, ayF: 0.575 };
    var S = { los: 0, losLine: 0, cam: 0, fd: 10, fdGreen: false, fdPulse: -9, number: 1, zoom: 1, ambient: true, time: 0, flash: null, shake: null, ring: [], parts: [], fade: 0, fadeTarget: 0, trail: [], ruler: true, hold: 0, ballG: { x: 0, y: 0.3, h: 4, held: null, ang: 0.3, sc: 1 } };
    var E = [], EK = {}, P = null, R = null, raf = 0, last = 0, lastDraw = 0, crowd = [], vignette = null, PR = { x: 0, y: 0, s: 1 };
    var rnd = rng(7);

    FORM.forEach(function (f, i) {
      var e = { k: f.k, t: f.t, team: f.o ? "o" : "d", n: f.n, ix: f.x, iy: f.y, wx: f.x, wy: f.y, rx: f.x, ry: f.y, px: f.x, py: f.y, z: 0, rot: 0, sxs: 1, sys: 1, arms: "idle", run: false, back: !!f.o, vy: 0, phase: i * 1.7, skin: SKINS[i % SKINS.length], bob: i * 0.9 };
      E.push(e); EK[f.k] = e;
    });

    // ---------------------------------------------------------------- layout + projection
    function layout() {
      var r = canvas.getBoundingClientRect(), w = Math.max(160, Math.round(r.width)), h = Math.max(200, Math.round(r.height));
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (w === W && h === H && canvas.width === Math.round(w * dpr)) return;
      W = w; H = h; canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      L.u = clamp(Math.min(W / 390, H / 800), 0.8, 1.3); L.cx = W / 2; L.ay = H * L.ayF;
      L.pxX = Math.min(W * 0.98 / (2 * XS), 8 * L.u); L.ppy = 8.2 * L.u;
      var rr = rng(11); crowd = [];
      var n = Math.round(W * H / 2600);
      for (var i = 0; i < n; i++) crowd.push({ x: rr() * W, y: rr(), c: rr() < 0.45 ? "255,220,170" : rr() < 0.5 ? "140,190,255" : "255,255,255", a: 0.18 + rr() * 0.5, f: rr() < 0.16 ? 1 + rr() * 2 : 0, p: rr() * 6 });
      vignette = ctx.createRadialGradient(W / 2, H * 0.5, Math.min(W, H) * 0.35, W / 2, H * 0.5, Math.max(W, H) * 0.78);
      vignette.addColorStop(0, "rgba(0,0,0,0)"); vignette.addColorStop(1, "rgba(0,0,0,0.62)");
      need();
    }
    function pj(x, wy) {
      var z = Math.max(12, Z0 + wy - S.cam), s = Z0 / z;
      PR.s = s; PR.x = L.cx + x * L.pxX * s; PR.y = L.ay - L.ppy * Z0 * Math.log(z / Z0);
      return PR;
    }
    function ksz(s) { return L.u * Math.pow(s, 0.6) * 1.42; }

    // ---------------------------------------------------------------- formation + states
    function formation() {
      E.forEach(function (e) {
        e.wx = e.ix; e.wy = S.los + e.iy; e.px = e.wx; e.py = e.wy;
        e.z = 0; e.rot = 0; e.sxs = 1; e.sys = 1; e.arms = "idle"; e.run = false; e.back = e.team === "o"; e.vy = 0;
      });
      EK.qb.n = S.number;
      var g = S.ballG; g.x = 0; g.y = S.los + 0.3; g.h = 2; g.held = null; g.sc = 1; g.ang = 0.25;
    }
    function applyIdlePose(e, t) {
      e.z = e.team === "o" ? 0.35 * Math.sin(t * 2.1 + e.bob) : 0; e.arms = e.k === "qb" ? "hold" : "idle";
      if (e.t === "ol" || e.t === "dl") e.arms = "idle";
    }
    function need() { if (!raf && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); } }

    // ---------------------------------------------------------------- building a play
    function buildPlay(o) {
      var rem = 100 - o.p0, tier = o.tier, g = o.gain, score = !!o.score || tier === 6;
      var variant = o.variant == null ? 0 : o.variant;
      if (tier === 6) { variant = rem > 55 ? 2 : variant; g = rem; }
      var sp = playSpec(tier, score && tier !== 6 ? Math.min(g, rem) : g, variant, rem, score);
      sp.L0 = o.p0; sp.L1 = score ? 100 : o.p0 + g; sp.tc = 0.4 + sp.throwDur; sp.ty = sp.tc + sp.yacDur; sp.tEnd = sp.ty + sp.camDur + (score ? 0.25 : 0.1);
      sp.fd0 = o.fd0; sp.fd1 = o.fd1; sp.t = 0; sp.fired = {}; sp.seed = o.seed || 1;
      sp.lead = sp.lead * Math.min(sp.catchPt.y, 55); sp.hasFd = false;
      return sp;
    }
    function skillPos(key, t, out) {
      var p = P, e = EK[key], x, y;
      if (key === p.rk) {
        if (t <= p.tc) { var u = clamp(t / p.tc, 0, 1); u = lerp(u, sstep(u), 0.35); var q = p.route(u); x = q.x; y = q.y; }
        else if (t < p.ty) { var q2 = p.yac(clamp((t - p.tc) / p.yacDur, 0, 1) * 0 + (p.slowYac ? eo3((t - p.tc) / p.yacDur) : lerp((t - p.tc) / p.yacDur, eo3((t - p.tc) / p.yacDur), 0.45))); x = q2.x; y = q2.y; }
        else { x = p.end.x; y = p.end.y; }
      } else if (e.t === "wr") {
        var d = sstep(t / (p.ty + 0.3)); x = e.ix + (e.ix > 0 ? -2.5 : 2.5) * d; y = e.iy + 13 * d;
      } else if (e.t === "te") { var d2 = sstep(t / (p.ty + 0.3)); x = e.ix - 1.2 * d2; y = e.iy + 5.5 * d2; }
      else if (e.t === "rb") { var d3 = sstep(t / 1.0); x = e.ix - 1.5 * d3; y = e.iy + 2.2 * d3; }
      else { x = e.ix; y = e.iy; }
      out.x = x; out.y = y; return out;
    }
    var T1 = { x: 0, y: 0 }, T2 = { x: 0, y: 0 }, T3 = { x: 0, y: 0 };
    function defBase(e, t, out) {
      var p = P, tc = p.tc, ty = p.ty, x = e.ix, y = e.iy, tt = Math.min(t, ty);
      var cp = skillPos(p.rk, tt, T1), cx = cp.x, cy = cp.y;
      if (e.t === "dl") { var r = 0.5 * sstep((t - 0.25) / 1.1); x = lerp(x, x * 0.4, r); y = lerp(y, -0.3, r); }
      else if (e.t === "lb") {
        var k = p.cov[e.k] != null ? p.cov[e.k] : 0.3;
        y += 3.2 * sstep(t / 0.8); x = lerp(x, x * 0.4 + cx * 0.3, k * sstep(t / tc));
        if (t > tc) { var u = ei2((t - tc) / p.yacDur); var b0 = {}; var tmp = defBaseAt(e, tc); x = lerp(tmp.x, cx - (e.ix < cx ? 1.2 : -1.2), 0.8 * u); y = lerp(tmp.y, cy - 1.6, 0.8 * u); }
      } else if (e.t === "cb") {
        var tgt = skillPos(e.ix < 0 ? "wrL" : "wrR", tt, T2), cov = sstep(t / 0.45) * (p.cov[e.k] != null ? p.cov[e.k] : 0.92);
        var lag = p.lag, tx = tgt.x + (e.ix < 0 ? -0.5 : 0.5), ty2 = tgt.y - lag;
        x = lerp(x, tx, cov); y = lerp(y, ty2, cov);
        if (t > tc && e.k !== p.tk) { var u2 = ei2((t - tc) / p.yacDur); var tmp2 = defBaseAt(e, tc); x = lerp(tmp2.x, cx, 0.8 * u2); y = lerp(tmp2.y, cy - 2, 0.8 * u2); }
      } else if (e.t === "s") {
        var kk = p.cov[e.k] != null ? p.cov[e.k] : 0.4;
        y += p.sDrop * sstep(t / 0.7); x = lerp(x, x * 0.3 + p.catchPt.x * 0.7, kk * sstep(t / tc));
        if (t > tc && e.k !== p.tk) { var u3 = ei2((t - tc) / p.yacDur); var tmp3 = defBaseAt(e, tc); x = lerp(tmp3.x, cx, 0.85 * u3); y = lerp(tmp3.y, cy - 2.5, 0.85 * u3); }
      }
      out.x = x; out.y = y; return out;
    }
    var T4 = { x: 0, y: 0 };
    function defBaseAt(e, t) {   // position before the catch only (never recurses past it)
      var save = P.tcLock; P.tcLock = true; var out = defBasePre(e, t, T4); P.tcLock = save; return out;
    }
    function defBasePre(e, t, out) {
      var p = P, tc = p.tc, x = e.ix, y = e.iy, cp = skillPos(p.rk, Math.min(t, tc), T3), cx = cp.x, cy = cp.y;
      if (e.t === "dl") { var r = 0.5 * sstep((t - 0.25) / 1.1); x = lerp(x, x * 0.4, r); y = lerp(y, -0.3, r); }
      else if (e.t === "lb") { var k = p.cov[e.k] != null ? p.cov[e.k] : 0.3; y += 3.2 * sstep(t / 0.8); x = lerp(x, x * 0.4 + cx * 0.3, k * sstep(t / tc)); }
      else if (e.t === "cb") {
        var tgt = skillPos(e.ix < 0 ? "wrL" : "wrR", Math.min(t, tc), {}), cov = sstep(t / 0.45) * (p.cov[e.k] != null ? p.cov[e.k] : 0.92);
        x = lerp(x, tgt.x + (e.ix < 0 ? -0.5 : 0.5), cov); y = lerp(y, tgt.y - p.lag, cov);
      } else if (e.t === "s") { var kk = p.cov[e.k] != null ? p.cov[e.k] : 0.4; y += p.sDrop * sstep(t / 0.7); x = lerp(x, x * 0.3 + p.catchPt.x * 0.7, kk * sstep(t / tc)); }
      out.x = x; out.y = y; return out;
    }

    function qbHand(t, out) {   // quarterback position at time t (dropback 0-0.4 then hold)
      var d = sstep(t / 0.4); out.x = 0; out.y = -4.6 - 2.1 * d; return out;
    }

    // ---------------------------------------------------------------- evaluating a play at time t
    var QP = { x: 0, y: 0 }, CP = { x: 0, y: 0 }, DP = { x: 0, y: 0 };
    function evalPlay(t) {
      var p = P, tc = p.tc, ty = p.ty, L0 = p.L0, i, e, g = S.ballG;
      for (i = 0; i < E.length; i++) { e = E[i]; e.rx = e.ix; e.ry = e.iy; e.z = 0; e.rot = 0; e.sxs = 1; e.sys = 1; e.arms = "idle"; e.run = false; }
      // offensive line sets back
      for (i = 0; i < E.length; i++) { e = E[i]; if (e.t === "ol") { e.ry = e.iy - 0.7 * sstep(t / 0.5); e.arms = "idle"; } }
      // quarterback
      var q = EK.qb; qbHand(t, QP); q.rx = QP.x; q.ry = QP.y; q.run = t < 0.42; q.arms = t < 0.4 ? "hold" : (t < tc ? "throw" : "idle");
      if (t >= 0.4 && t < 0.4 + 0.5) { q.rot = -0.12 * Math.sin(clamp((t - 0.4) / 0.5, 0, 1) * PI); }
      // skill players
      var keys = ["wrL", "wrR", "te", "rb"], rcv = EK[p.rk];
      for (i = 0; i < keys.length; i++) {
        e = EK[keys[i]]; skillPos(keys[i], t, CP); e.rx = CP.x; e.ry = CP.y; e.run = t > 0.12 && t < ty; e.arms = e.k === p.rk && t > tc - 0.25 && t < tc + 0.18 ? "catch" : (e.k === p.rk && t >= tc ? "carry" : "run");
      }
      // defenders
      for (i = 0; i < E.length; i++) {
        e = E[i]; if (e.team !== "d") continue;
        defBase(e, t, DP); e.rx = DP.x; e.ry = DP.y; e.run = t > 0.25 && t < ty + 0.1; e.arms = "idle";
        if (e.k === p.tk && t > tc) {          // the tackler converges and arrives exactly at the tackle spot at ty
          var from = defBaseAt(e, tc), u = ei2((t - tc) / p.yacDur), tx = p.end.x + (e.ix < p.end.x ? -0.9 : 0.9), tyy = p.score ? p.end.y - 3.2 : p.end.y - 0.35;
          e.rx = lerp(from.x, tx, u); e.ry = lerp(from.y, tyy, u); e.run = true; e.arms = "up";
        }
      }
      // receiver specifics (poses for the highlight-reel catches, tackles and celebrations)
      rcvPose(t, rcv);
      // tackle: carrier and tackler go down at ty
      if (!p.score && t >= ty) {
        var pr = eo3((t - ty) / 0.28), tk = EK[p.tk];
        rcv.sys = 1 - 0.55 * pr; rcv.rot = 0.5 * pr; rcv.run = false; rcv.arms = "up";
        tk.sys = 1 - 0.5 * pr; tk.rot = -0.6 * pr; tk.run = false; tk.arms = "up"; tk.rx = p.end.x + (tk.ix < p.end.x ? -0.9 : 0.9) + 0.35 * pr * (tk.ix < p.end.x ? 1 : -1);
      }
      if (p.score && t >= ty) { rcv.arms = "up"; rcv.run = false; if (p.variant !== 2 && p.variant != null || p.tier !== 6) { rcv.z = Math.max(rcv.z, 3 * Math.abs(Math.sin((t - ty) * 9))); } }
      if (p.score && t >= ty) { var tk2 = EK[p.tk]; var pr2 = eo3((t - ty + 0.1) / 0.3); tk2.sys = 1 - 0.55 * pr2; tk2.rot = 0.7 * pr2; tk2.run = false; }
      for (i = 0; i < E.length; i++) { e = E[i]; e.wx = e.rx; e.wy = L0 + e.ry; }
      // the ball
      ballAt(t, rcv, q);
      // camera + line markers
      var catchCam = L0 + p.lead, cam;
      if (t < 0.4) cam = L0; else if (t < ty) cam = lerp(L0, catchCam, sstep((t - 0.4) / (tc - 0.4 + 0.3))); else cam = catchCam;
      var pu = (t - ty) / p.camDur;
      if (t > ty) cam = lerp(catchCam, p.L1, eio3(pu));
      S.cam = cam;
      var zm = 1;
      if (p.zoomOut) zm -= p.zoomOut * sstep((t - 0.4) / (tc - 0.4)) * (t > ty ? 1 - eio3(pu) : 1);
      if (p.zoomIn) zm += p.zoomIn * sstep((t - (tc - 0.12)) / 0.25) * (t > ty ? 1 - eio3(pu) : 1);
      S.zoom = zm;
      S.losLine = t >= ty ? p.L1 : L0;
      // first-down line goes green the moment the ball carrier crosses it
      if (!p.fdHit && t >= tc && (L0 + rcv.ry >= S.fd - 0.15 || L0 + p.catchPt.y >= S.fd)) { p.fdHit = true; S.fdGreen = true; S.fdPulse = S.time; if (p.tier === 3) flash("#3ddc84", 0.22, 0.5); }
      // timed events
      ev(t, tc, "catch", function () {
        var cpt = { x: p.catchPt.x, y: L0 + p.catchPt.y };
        addRing(cpt.x, cpt.y, p.color, p.tier === 1 ? 0.7 : 1);
        burst(cpt.x, cpt.y, p.color, p.tier >= 4 ? 22 : 10);
        if (p.thud) shake(p.thud, 0.18); if (p.shake) shake(p.shake, 0.55);
        if (p.tier >= 5) flash(p.color, 0.3, 0.45); else if (p.tier >= 3) flash(p.color, 0.14, 0.3);
      });
      ev(t, ty, "tackle", function () {
        S.losLine = p.L1;
        if (!p.score) { dust(p.end.x, L0 + p.end.y, 7); shake(2.4, 0.2); flash("#ffffff", 0.08, 0.2); addRing(p.end.x, L0 + p.end.y, "#ffffff", 0.55); }
        else { burst(p.end.x, L0 + p.end.y, "#ffd36a", 30); flash("#ffab1a", 0.35, 0.6); }
      });
      if (p.variant === 1 && p.tier === 6) {      // toe-tap: two quick taps right after the catch
        ev(t, tc + 0.16, "tap1", function () { tapSpark(p.catchPt.x - 0.5, L0 + p.catchPt.y); });
        ev(t, tc + 0.3, "tap2", function () { tapSpark(p.catchPt.x + 0.2, L0 + p.catchPt.y); });
      }
    }
    function rcvPose(t, rcv) {
      var p = P, tc = p.tc, ty = p.ty;
      if (p.tier !== 6) return;
      var v = p.variant;
      if (v === 0) {                                // one-handed grab, falling backward
        var u = clamp((t - (tc - 0.2)) / 0.85, 0, 1);
        if (t > tc - 0.2) { rcv.arms = "one"; rcv.z = 15 * Math.sin(clamp(u * 1.15, 0, 1) * PI); rcv.rot = -0.95 * eo3(u); rcv.sys = 1 - 0.22 * eo3(u); rcv.run = false; }
        if (t > tc + 0.55) { var pr = eo3((t - tc - 0.55) / 0.2); rcv.sys = 0.78 - 0.3 * pr; rcv.rot = -1.1; rcv.arms = "one"; }
        var cb = EK.cbR; if (t > tc - 0.1) { cb.rot = 0.5 * eo3((t - tc + 0.1) / 0.5); cb.sys = 1 - 0.4 * eo3((t - tc + 0.1) / 0.5); cb.arms = "up"; cb.run = false; }
      } else if (v === 1) {                         // toe-tap in the back corner
        var u2 = clamp((t - (tc - 0.2)) / 0.5, 0, 1);
        if (t > tc - 0.2) { rcv.arms = "one"; rcv.rot = 0.32 * Math.sin(u2 * PI * 0.8 + 0.2); rcv.z = 7 * Math.sin(clamp(u2 * 1.2, 0, 1) * PI); rcv.run = false; }
        if (t > tc + 0.5) { rcv.arms = "up"; rcv.rot = 0; rcv.z = 2.5 * Math.abs(Math.sin((t - tc) * 8)); }
        var cb2 = EK.cbR; if (t > tc - 0.25) { cb2.rx = p.catchPt.x + 1.9; cb2.ry = p.catchPt.y - 0.9; cb2.rot = 0.45; cb2.arms = "up"; cb2.run = false; }
      } else {                                      // catch and run: juke, spin, dive for the pylon
        if (t > tc) {
          var uu = (t - tc) / p.yacDur;
          rcv.run = uu < 0.86;
          if (uu > 0.3 && uu < 0.4) rcv.rot = -0.55 * Math.sin((uu - 0.3) / 0.1 * PI);
          if (uu > 0.4 && uu < 0.66) { var sp = (uu - 0.4) / 0.26; rcv.sxs = Math.cos(sp * TAU * 1.0 + 0.0) * 0.9 + (Math.abs(Math.cos(sp * TAU)) < 0.15 ? 0.15 : 0); rcv.z = 3; rcv.arms = "carry"; }
          if (uu >= 0.86) { var d = clamp((uu - 0.86) / 0.14, 0, 1); rcv.sys = 1 - 0.55 * eo3(d); rcv.rot = 0.15; rcv.z = 7 * Math.sin(d * PI); rcv.arms = "up"; rcv.run = false; }
          var lb = EK.lbR; if (uu > 0.28) { var m = eo3((uu - 0.28) / 0.25); lb.rx = lerp(lb.rx, rcv.rx - 1.1 + 2 * m, 0.7 * m); lb.rot = 0.9 * m; lb.sys = 1 - 0.55 * m; lb.run = m < 0.5; }
          var cb3 = EK.cbR; if (uu > 0.8) { var m2 = eo3((uu - 0.8) / 0.2); cb3.rot = -0.9 * m2; cb3.sys = 1 - 0.5 * m2; cb3.arms = "up"; cb3.run = false; }
        }
      }
    }
    function ballAt(t, rcv, q) {
      var p = P, tc = p.tc, g = S.ballG, L0 = p.L0, u, k = 1;
      var qy = q.ry;
      if (t < 0.28) { u = sstep(t / 0.28); g.x = 0; g.y = L0 + lerp(0.3, q.ry + 0.2, u); g.h = lerp(2, 13, u) + 6 * Math.sin(u * PI); g.held = null; g.sc = 1; g.ang = 0.4 + u * 4; }
      else if (t < 0.4) { g.x = q.rx + 0.3; g.y = L0 + q.ry + 0.15; g.h = 13; g.held = "qb"; g.sc = 1; g.ang = 0.3; }
      else if (t < tc) {
        u = (t - 0.4) / p.throwDur; var sx0 = q.rx + 0.4, sy0 = L0 + q.ry + 0.2;
        var fu = eio3(u) * 0.35 + u * 0.65;
        g.x = lerp(sx0, p.catchPt.x, fu); g.y = lerp(sy0, L0 + p.catchPt.y, fu);
        g.h = lerp(14, 15, u) + Math.sin(u * PI) * p.arc; g.sc = 1 + (p.bscale - 1) * Math.sin(u * PI); g.held = null; g.ang = Math.atan2(-(Math.cos(u * PI) * p.arc * 0.02), 1) + u * 9;
        if (!p.paused) trailAdd(g.x, g.y, g.h, g.sc);
      } else if (t < p.ty || p.score) { g.held = p.rk; g.sc = 1; g.x = rcv.rx + 0.3; g.y = L0 + rcv.ry + 0.1; g.h = rcv.arms === "up" ? 28 : 12; g.ang = 0.2; if (p.score && t >= p.ty) { g.h = 26; } }
      else { g.held = null; g.x = p.end.x + 0.2; g.y = L0 + p.end.y; g.h = 2.5 * Math.max(0, 1 - (t - p.ty) * 3); g.sc = 1; g.ang = 1.2; }
      if (g.held && t > 0.4 && t < tc + 0.01) { g.held = null; }
    }
    function trailAdd(x, wy, h, sc) {
      var tr = S.trail; tr.push({ x: x, y: wy, h: h, sc: sc, t: S.time }); if (tr.length > 22) tr.shift();
    }
    function ev(t, at, name, fn) { var p = P; if (t >= at && !p.fired[name]) { p.fired[name] = 1; fn(); } }

    // ---------------------------------------------------------------- sack
    function evalSack(t) {
      var p = P, L0 = p.L0, i, e, q = EK.qb, g = S.ballG;
      for (i = 0; i < E.length; i++) { e = E[i]; e.rx = e.ix; e.ry = e.iy; e.z = 0; e.rot = 0; e.sxs = 1; e.sys = 1; e.arms = "idle"; e.run = false; }
      var drop = sstep(t / 0.4); q.rx = 0; q.ry = -4.6 - 2.1 * drop; q.run = t < 0.42; q.arms = "hold";
      var sw = sstep((t - 0.35) / 0.8), hit = clamp((t - 1.05) / 0.5, 0, 1), qx = q.rx, qy = q.ry;
      var rush = ["dl1", "dl2", "dl3", "dl4", "lbL", "lbR"];
      for (i = 0; i < E.length; i++) { e = E[i]; if (e.t === "ol") { e.ry = e.iy - 0.7 * sstep(t / 0.5) - 1.2 * sstep((t - 0.6) / 0.6); e.rx = e.ix * (1 + 0.15 * sstep((t - 0.6) / 0.6)); } }
      for (i = 0; i < rush.length; i++) {
        e = EK[rush[i]]; var side = i % 2 ? 1 : -1, tx = qx + (i < 4 ? (i - 1.5) * 0.9 : side * 1.6), ty = qy + 0.7 + (i < 4 ? 0.2 * (i % 2) : 1.4);
        e.rx = lerp(e.ix, tx, eio3(sw)); e.ry = lerp(e.iy, ty, eio3(sw)); e.run = sw < 1; e.arms = sw > 0.6 ? "up" : "idle";
        if (hit > 0) { e.rot = (i % 2 ? 0.7 : -0.7) * eo3(hit); e.sys = 1 - 0.5 * eo3(hit); e.run = false; }
      }
      var k2 = ["cbL", "cbR", "sL", "sR"]; for (i = 0; i < k2.length; i++) { e = EK[k2[i]]; e.ry = e.iy + 2 * sstep(t / 0.7); }
      var wk = ["wrL", "wrR", "te"]; for (i = 0; i < wk.length; i++) { e = EK[wk[i]]; var d = sstep(t / 1.1); e.ry = e.iy + 9 * d; e.rx = e.ix + (e.ix > 0 ? -2 : 2) * d; e.run = t < 1.2; }
      EK.rb.rx = -4; EK.rb.ry = -5; EK.rb.arms = "up";
      if (hit > 0) { q.sys = 1 - 0.55 * eo3(hit); q.rot = -0.5 * eo3(hit); q.run = false; q.arms = "up"; q.z = 0; }
      for (i = 0; i < E.length; i++) { e = E[i]; e.wx = e.rx; e.wy = L0 + e.ry; }
      g.held = hit > 0.8 ? null : "qb"; g.x = q.rx + 0.3 + (hit > 0.8 ? 0.7 : 0); g.y = L0 + q.ry + 0.15 - (hit > 0.8 ? 0.4 : 0); g.h = hit > 0.8 ? 2.5 : 13; g.sc = 1; g.ang = hit > 0.8 ? 1.0 : 0.3;
      S.cam = L0; S.zoom = 1; S.losLine = L0;
      ev(t, 1.05, "hit", function () { shake(4.5, 0.35); flash("#05070c", 0.55, 0.7); dust(q.rx, L0 + q.ry, 9); });
    }

    // ---------------------------------------------------------------- effects
    function flash(c, a, dur) { S.flash = { c: c, a: a, t0: S.time, dur: dur }; }
    function shake(a, dur) { S.shake = { a: a, t0: S.time, dur: dur }; }
    function addRing(x, wy, c, sc) { S.ring.push({ x: x, y: wy, c: c, t0: S.time, sc: sc || 1 }); }
    function burst(x, wy, c, n) {
      for (var i = 0; i < n; i++) { var a = rnd() * TAU, v = 20 + rnd() * 60; S.parts.push({ x: x, y: wy, ox: 0, oy: 0, vx: Math.cos(a) * v, vy: Math.sin(a) * v * 0.7 - 20, g: 90, life: 0.5 + rnd() * 0.4, max: 0.9, c: c, r: 1 + rnd() * 1.6, kind: 0 }); }
    }
    function dust(x, wy, n) { for (var i = 0; i < n; i++) { S.parts.push({ x: x + (rnd() - 0.5) * 1.5, y: wy, ox: 0, oy: 0, vx: (rnd() - 0.5) * 40, vy: -8 - rnd() * 22, g: -10, life: 0.5 + rnd() * 0.35, max: 0.85, c: "210,200,170", r: 3 + rnd() * 3, kind: 1 }); } }
    function tapSpark(x, wy) { burst(x, wy, "#ffffff", 7); S.parts.push({ x: x, y: wy, ox: 0, oy: 0, vx: 0, vy: 0, g: 0, life: 0.3, max: 0.3, c: "#ffffff", r: 5, kind: 2 }); }

    // ---------------------------------------------------------------- drawing
    function poly(pts) { ctx.beginPath(); ctx.moveTo(pts[0], pts[1]); for (var i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i], pts[i + 1]); ctx.closePath(); }
    function quad(y0, y1, x0, x1) {
      pj(x0, y0); var ax = PR.x, ay = PR.y; pj(x1, y0); var bx = PR.x, by = PR.y; pj(x1, y1); var cx = PR.x, cy = PR.y; pj(x0, y1);
      poly([ax, ay, bx, by, cx, cy, PR.x, PR.y]);
    }
    function ftext(txt, x, wy, size, col, alpha, rot) {
      pj(x, wy); var s = PR.s, px = PR.x, py = PR.y; var sz = size * L.pxX * s;
      if (sz < 4) return;
      ctx.save(); ctx.translate(px, py); ctx.scale(1, 0.72); if (rot) ctx.rotate(rot);
      ctx.font = "800 " + sz.toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.globalAlpha = alpha; ctx.fillStyle = col; ctx.fillText(txt, 0, 0); ctx.restore();
    }
    function drawBackdrop() {
      var g = ctx.createLinearGradient(0, 0, 0, H * 0.45); g.addColorStop(0, "#03050a"); g.addColorStop(1, "#0b1320");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      // stands above the far wall
      pj(0, 110.5); var wallY = PR.y; pj(0, 120); var topY = Math.max(0, Math.min(PR.y, wallY - 20 * L.u));
      var sg = ctx.createLinearGradient(0, 0, 0, wallY); sg.addColorStop(0, "#070b14"); sg.addColorStop(1, "#131c2c"); ctx.fillStyle = sg; ctx.fillRect(0, 0, W, Math.max(0, wallY));
      var tm = S.time;
      for (var i = 0; i < crowd.length; i++) {
        var c = crowd[i], y = c.y * wallY; if (y > wallY - 2) continue;
        var a = c.a * (c.f ? 0.45 + 0.55 * Math.max(0, Math.sin(tm * c.f + c.p)) : 1);
        ctx.fillStyle = "rgba(" + c.c + "," + a.toFixed(2) + ")"; ctx.fillRect(c.x, y, 1.7 * L.u, 1.7 * L.u);
      }
      // ad boards on the wall
      var bh = 7 * L.u, n = 9, w = W / n;
      for (var j = 0; j < n; j++) { ctx.fillStyle = j % 2 ? "rgba(25,224,138,0.5)" : "rgba(20,30,48,0.95)"; ctx.fillRect(j * w, wallY - bh, w + 1, bh); }
      ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fillRect(0, wallY, W, 2);
    }
    function drawLights() {
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      [[0.1, 0.03], [0.9, 0.03]].forEach(function (p, i) {
        var x = W * p[0], y = H * p[1], r = Math.min(W, H) * 0.5;
        var g = ctx.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, "rgba(200,230,255,0.55)"); g.addColorStop(0.15, "rgba(150,200,255,0.18)"); g.addColorStop(1, "rgba(80,140,255,0)");
        ctx.fillStyle = g; ctx.fillRect(0, 0, W, H * 0.7);
        ctx.globalAlpha = 0.07; ctx.fillStyle = "#cfe6ff"; ctx.beginPath(); ctx.moveTo(x - 6, y); ctx.lineTo(x + 6, y); ctx.lineTo(W * (i ? 0.2 : 0.8), H * 0.85); ctx.lineTo(W * (i ? -0.1 : 0.5), H * 0.85); ctx.fill(); ctx.globalAlpha = 1;
      });
      ctx.restore();
    }
    function drawField() {
      var Y, shade = 0;
      // out of bounds
      ctx.fillStyle = "#061510"; pj(0, -12); ctx.fillRect(0, 0, W, H);
      drawBackdrop(); drawLights();
      // grass stripes + end zones
      for (Y = -10; Y < 110; Y += 5) {
        var ez = Y < 0 || Y >= 100;
        quad(Y, Y + 5, -XS, XS);
        if (Y < 0) ctx.fillStyle = "#0c3b44"; else if (Y >= 100) ctx.fillStyle = "#4a3a12"; else ctx.fillStyle = ((Y / 5) & 1) ? "#0f5a35" : "#0c4a2c";
        ctx.fill();
      }
      // light pool around the line of scrimmage
      pj(0, S.los + 6); var gp = ctx.createRadialGradient(PR.x, PR.y, 0, PR.x, PR.y, L.pxX * 36);
      gp.addColorStop(0, "rgba(255,255,240,0.13)"); gp.addColorStop(1, "rgba(255,255,240,0)"); ctx.fillStyle = gp; ctx.fillRect(0, 0, W, H);
      // end zone art
      ftext("LINEUP", 0, -4.6, 5.2, "#19e08a", 0.5); ftext("LAB", 0, -8, 3.2, "#ffffff", 0.2);
      var pulse = 0.5 + 0.2 * Math.sin(S.time * 2.4);
      ftext("LINEUP LAB", 0, 105, 4.6, "#ffcf6b", pulse + 0.1); ftext("END ZONE", 0, 108.3, 2.6, "#ffffff", 0.25);
      // yard lines, sidelines, hashes
      ctx.lineCap = "butt"; ctx.strokeStyle = "rgba(255,255,255,0.8)";
      for (Y = 0; Y <= 100; Y += 5) {
        pj(-XS, Y); var lx = PR.x, ly = PR.y, sc = PR.s; pj(XS, Y);
        ctx.lineWidth = (Y === 0 || Y === 100 ? 3.4 : Y % 10 === 0 ? 2.2 : 1.3) * Math.pow(sc, 0.8) * L.u; ctx.globalAlpha = Y === 0 || Y === 100 ? 0.95 : 0.65;
        ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(PR.x, PR.y); ctx.stroke();
      }
      ctx.globalAlpha = 0.55; ctx.lineWidth = 1.1 * L.u;
      ctx.beginPath();
      for (Y = 1; Y < 100; Y++) {
        if (Y % 5 === 0) continue;
        [-3.1, 3.1, -XS + 1.4, XS - 1.4].forEach(function (hx) { pj(hx - 0.55, Y); ctx.moveTo(PR.x, PR.y); pj(hx + 0.55, Y); ctx.lineTo(PR.x, PR.y); });
      }
      ctx.stroke(); ctx.globalAlpha = 1;
      // sidelines + end lines
      ctx.strokeStyle = "rgba(255,255,255,0.9)"; ctx.lineWidth = 3 * L.u;
      [-XS, XS].forEach(function (x) { pj(x, -10); ctx.beginPath(); ctx.moveTo(PR.x, PR.y); pj(x, 110); ctx.lineTo(PR.x, PR.y); ctx.stroke(); });
      ctx.lineWidth = 2.4 * L.u; pj(-XS, 110); ctx.beginPath(); ctx.moveTo(PR.x, PR.y); pj(XS, 110); ctx.lineTo(PR.x, PR.y); ctx.stroke();
      // yard numbers
      for (Y = 10; Y <= 90; Y += 10) { var num = String(Y <= 50 ? Y : 100 - Y); ftext(num, -XS + 11.5, Y, 3.4, "#ffffff", 0.55); ftext(num, XS - 11.5, Y, 3.4, "#ffffff", 0.55); }
      // pylons
      [[-XS, 0], [XS, 0], [-XS, 100], [XS, 100]].forEach(function (c) { pj(c[0], c[1]); var k = ksz(PR.s); ctx.fillStyle = "#ff8a1f"; ctx.fillRect(PR.x - 2.5 * k, PR.y - 9 * k, 5 * k, 9 * k); ctx.fillStyle = "#fff"; ctx.fillRect(PR.x - 2.5 * k, PR.y - 6 * k, 5 * k, 1.6 * k); });
      // line of scrimmage (blue) and first-down line (yellow, green once crossed)
      drawMarker(S.losLine, "#3da5ff", 1, false);
      var pa = 1 + 0.8 * Math.max(0, 1 - (S.time - S.fdPulse) / 0.7);
      drawMarker(S.fd, S.fdGreen ? "#2cf29a" : "#ffd60a", pa, true);
    }
    function drawMarker(wy, col, pw, dashed) {
      if (wy < -10 || wy > 110) return;
      pj(-XS, wy); var ax = PR.x, ay = PR.y, sc = PR.s; pj(XS, wy);
      ctx.save(); ctx.strokeStyle = col; ctx.lineCap = "round";
      ctx.globalAlpha = 0.28 * pw; ctx.lineWidth = 9 * Math.pow(sc, 0.8) * L.u * pw; ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(PR.x, PR.y); ctx.stroke();
      ctx.globalAlpha = 1; ctx.lineWidth = 3.2 * Math.pow(sc, 0.8) * L.u * Math.min(1.8, pw); if (dashed) ctx.setLineDash([14 * sc * L.u, 6 * sc * L.u]);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(PR.x, PR.y); ctx.stroke(); ctx.restore();
    }
    function roundRect(x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
    function ln(x0, y0, x1, y1, col, w) { ctx.strokeStyle = col; ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); }
    function drawSprite(e, sx, sy, k) {
      var off = e.team === "o", qb = e.k === "qb", back = e.back;
      if (qb) k *= 1.28; else if (e.t === "wr" || e.t === "rb" || e.t === "te") k *= 1.06;
      var jersey = off ? "#19e08a" : "#f3f6fb", pants = off ? "#e8eef7" : "#39435c", helm = off ? (qb ? "#0b8f57" : "#0e7a4a") : "#c8d2e6", num = off ? "#ffffff" : "#16203a", skin = e.skin;
      // ground shadow
      ctx.fillStyle = "rgba(0,0,0,0.38)"; ctx.beginPath(); ctx.ellipse(sx, sy + 0.4 * k, 7.4 * k * (1 + (e.z > 4 ? 0 : 0)), 2.5 * k, 0, 0, TAU); ctx.fill();
      ctx.save(); ctx.translate(sx, sy - e.z * k); if (e.rot) ctx.rotate(e.rot); if (e.sxs !== 1 || e.sys !== 1) ctx.scale(e.sxs, e.sys);
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      var ph = e.run ? e.phase : 0, sw = e.run ? Math.sin(ph) : 0;
      var fl = -0.6 * k - Math.max(0, sw) * 2.6 * k, fr = -0.6 * k - Math.max(0, -sw) * 2.6 * k;
      ln(-2.5 * k, -9.5 * k, -2.5 * k, fl, "rgba(0,0,0,0.5)", 4.7 * k); ln(2.5 * k, -9.5 * k, 2.5 * k, fr, "rgba(0,0,0,0.5)", 4.7 * k);
      ln(-2.5 * k, -9.5 * k, -2.5 * k, fl, pants, 3.7 * k); ln(2.5 * k, -9.5 * k, 2.5 * k, fr, pants, 3.7 * k);
      ln(-2.5 * k, fl + 0.4 * k, -2.5 * k, fl, "#1b2030", 4 * k); ln(2.5 * k, fr + 0.4 * k, 2.5 * k, fr, "#1b2030", 4 * k);
      // arms (behind the torso when seen from the back, in front when facing us)
      var arm = e.arms, ax = 6.6 * k, sy0 = -17.4 * k, lw = 3 * k, sa = e.run ? Math.sin(ph) * 3.2 * k : 0, lx, ly, rx, ry;
      lx = -7.6 * k; ly = -10.5 * k - sa; rx = 7.6 * k; ry = -10.5 * k + sa;
      if (arm === "up") { lx = -8.2 * k; ly = -28 * k; rx = 8.2 * k; ry = -28 * k; }
      else if (arm === "one") { lx = -6.5 * k; ly = -13 * k; rx = 7.8 * k; ry = -29 * k; }
      else if (arm === "catch") { lx = -4.8 * k; ly = -25 * k; rx = 4.8 * k; ry = -25 * k; }
      else if (arm === "carry") { lx = -3.2 * k; ly = -13.5 * k; rx = 6.8 * k; ry = -11 * k + sa; }
      else if (arm === "throw") { lx = -3 * k; ly = -16 * k; rx = 6.2 * k; ry = -27.5 * k; }
      else if (arm === "hold") { lx = -3.4 * k; ly = -14.2 * k; rx = 3.4 * k; ry = -14.2 * k; }
      var armPair = function () {
        ln(-ax, sy0, lx, ly, "rgba(0,0,0,0.5)", lw + 1.2 * k); ln(ax, sy0, rx, ry, "rgba(0,0,0,0.5)", lw + 1.2 * k);
        ln(-ax, sy0, lx, ly, skin, lw); ln(ax, sy0, rx, ry, skin, lw);
        ln(-ax, sy0, lerp(-ax, lx, 0.38), lerp(sy0, ly, 0.38), jersey, lw + 0.8 * k); ln(ax, sy0, lerp(ax, rx, 0.38), lerp(sy0, ry, 0.38), jersey, lw + 0.8 * k);
      };
      if (!back) armPair();
      // torso
      ctx.fillStyle = jersey; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 1.1 * k;
      roundRect(-6 * k, -19.6 * k, 12 * k, 11.4 * k, 3 * k); ctx.fill(); ctx.stroke();
      ctx.fillStyle = off ? "#0fa868" : "#dfe5f1"; ctx.beginPath(); ctx.ellipse(0, -19 * k, 7.2 * k, 2.8 * k, 0, 0, TAU); ctx.fill();
      ctx.fillStyle = pants; ctx.fillRect(-5.6 * k, -9.6 * k, 11.2 * k, 1.8 * k);
      // number
      ctx.font = "800 " + ((qb ? 9.6 : 7.4) * k).toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      var ty = qb ? -13.9 * k : -13.6 * k, label = String(e.n); ctx.lineWidth = 1.7 * k; ctx.strokeStyle = off ? "rgba(0,50,25,0.9)" : "rgba(255,255,255,0.9)"; ctx.strokeText(label, 0, ty); ctx.fillStyle = num; ctx.fillText(label, 0, ty);
      if (back) armPair();
      // head
      ctx.fillStyle = helm; ctx.beginPath(); ctx.arc(0, -24.6 * k, 5.6 * k, 0, TAU); ctx.fill(); ctx.lineWidth = 1.1 * k; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.stroke();
      if (back) { ln(0, -30 * k, 0, -26.3 * k, off ? "#ffffff" : "#5a6684", 1.5 * k); ctx.fillStyle = "rgba(255,255,255,0.22)"; ctx.beginPath(); ctx.ellipse(-1.6 * k, -26.8 * k, 1.9 * k, 1.2 * k, -0.5, 0, TAU); ctx.fill(); }
      else {
        ctx.fillStyle = skin; ctx.beginPath(); ctx.ellipse(0, -23.6 * k, 3.7 * k, 3 * k, 0, 0, TAU); ctx.fill();
        ctx.fillStyle = "#1b2030"; ctx.fillRect(-2.2 * k, -24.6 * k, 1.1 * k, 1.4 * k); ctx.fillRect(1.1 * k, -24.6 * k, 1.1 * k, 1.4 * k);
        ctx.strokeStyle = off ? "#e8eef7" : "#6c7894"; ctx.lineWidth = 1 * k; ctx.beginPath(); ctx.moveTo(-3.9 * k, -25.2 * k); ctx.lineTo(-3.9 * k, -21.6 * k); ctx.lineTo(3.9 * k, -21.6 * k); ctx.lineTo(3.9 * k, -25.2 * k); ctx.moveTo(-3.9 * k, -23.4 * k); ctx.lineTo(3.9 * k, -23.4 * k); ctx.stroke();
      }
      ctx.restore();
    }
    function drawBallSprite(sx, sy, k, ang) {
      ctx.save(); ctx.translate(sx, sy); ctx.rotate(ang); ctx.fillStyle = "#9a5528"; ctx.strokeStyle = "#2a1206"; ctx.lineWidth = 0.9 * k;
      ctx.beginPath(); ctx.ellipse(0, 0, 4.8 * k, 3 * k, 0, 0, TAU); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 0.8 * k; ctx.beginPath(); ctx.moveTo(-1.6 * k, 0); ctx.lineTo(1.6 * k, 0); for (var i = -1; i <= 1; i++) { ctx.moveTo(i * 1.1 * k, -1 * k); ctx.lineTo(i * 1.1 * k, 1 * k); } ctx.stroke();
      ctx.restore();
    }
    function drawTrail() {
      var tr = S.trail, P0 = P; if (!tr.length || !P0 || P0.trail === "none") return;
      var kind = P0.trail, col = P0.color, n = tr.length;
      ctx.save(); ctx.lineCap = "round"; ctx.lineJoin = "round";
      if (kind === "glow") ctx.globalCompositeOperation = "lighter";
      for (var i = 1; i < n; i++) {
        var a = tr[i - 1], b = tr[i], age = S.time - b.t; if (age > 0.55) continue;
        pj(a.x, a.y); var x0 = PR.x, y0 = PR.y - a.h * ksz(PR.s); pj(b.x, b.y); var x1 = PR.x, y1 = PR.y - b.h * ksz(PR.s), al = (1 - age / 0.55) * (i / n);
        if (kind === "glow") { ctx.strokeStyle = col; ctx.globalAlpha = Math.min(1, al * 0.95); ctx.lineWidth = 12 * L.u * Math.pow(PR.s, 0.5); ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.globalAlpha = al * 0.9; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.2 * L.u; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); }
        else { ctx.strokeStyle = "#fff"; ctx.globalAlpha = al * 0.85; ctx.lineWidth = 1.6 * L.u; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); }
      }
      ctx.restore();
    }
    function drawEntities() {
      var items = [], i, e;
      for (i = 0; i < E.length; i++) { e = E[i]; items.push({ y: e.wy, e: e }); }
      var g = S.ballG, owner = g.held ? EK[g.held] : null, air = !owner && g.h > 8;
      if (!air) items.push({ y: (owner ? owner.wy : g.y) - 0.02, b: 1 });
      items.sort(function (a, b) { return b.y - a.y; });
      for (i = 0; i < items.length; i++) {
        var it = items[i];
        if (it.e) { pj(it.e.wx, it.e.wy); drawSprite(it.e, PR.x, PR.y, ksz(PR.s)); }
        else drawBall(owner);
      }
      drawTrail();
      if (air) drawBall(null);
    }
    function drawBall(owner) {
      var g = S.ballG; pj(g.x, g.y); var k = ksz(PR.s), sx = PR.x, sy = PR.y;
      if (!owner) { ctx.fillStyle = "rgba(0,0,0," + (0.42 - Math.min(0.25, g.h / 500)).toFixed(2) + ")"; ctx.beginPath(); ctx.ellipse(sx, sy, 5 * k * (1 + g.h / 260), 1.9 * k * (1 + g.h / 400), 0, 0, TAU); ctx.fill(); }
      var hh = (owner ? g.h + owner.z : g.h) * k * (owner ? (owner.k === "qb" ? 1.28 : 1.06) : 1);
      drawBallSprite(sx, sy - hh, k * g.sc * 0.95, g.ang);
    }
    function drawFx() {
      var tm = S.time, i;
      for (i = S.ring.length - 1; i >= 0; i--) {
        var r = S.ring[i], age = (tm - r.t0) / 0.5; if (age >= 1) { S.ring.splice(i, 1); continue; }
        pj(r.x, r.y); var k = ksz(PR.s), rad = (6 + 46 * eo3(age)) * k * r.sc;
        ctx.strokeStyle = r.c; ctx.globalAlpha = (1 - age) * 0.95; ctx.lineWidth = (4 * (1 - age) + 1) * L.u;
        ctx.beginPath(); ctx.ellipse(PR.x, PR.y, rad, rad * 0.42, 0, 0, TAU); ctx.stroke(); ctx.globalAlpha = 1;
      }
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (i = 0; i < S.parts.length; i++) {
        var p = S.parts[i], a = clamp(p.life / p.max, 0, 1); pj(p.x, p.y); var px = PR.x + p.ox, py = PR.y + p.oy, k2 = ksz(PR.s);
        if (p.kind === 1) { ctx.globalCompositeOperation = "source-over"; ctx.fillStyle = "rgba(" + p.c + "," + (a * 0.4).toFixed(2) + ")"; ctx.beginPath(); ctx.arc(px, py, p.r * k2 * (1.6 - a * 0.6), 0, TAU); ctx.fill(); ctx.globalCompositeOperation = "lighter"; }
        else if (p.kind === 2) { ctx.strokeStyle = "rgba(255,255,255," + a.toFixed(2) + ")"; ctx.lineWidth = 1.4 * L.u; ctx.beginPath(); ctx.arc(px, py, p.r * k2 * (2 - a), 0, TAU); ctx.stroke(); }
        else { ctx.fillStyle = p.c; ctx.globalAlpha = a; ctx.beginPath(); ctx.arc(px, py, p.r * L.u, 0, TAU); ctx.fill(); ctx.globalAlpha = 1; }
      }
      ctx.restore();
    }
    function drawRuler() {
      if (!S.ruler) return;
      var x = W - 11 * L.u, y0 = H * 0.17, y1 = H * 0.7, pos = clamp(S.cam, 0, 100) * 0 + clamp(S.losLine, 0, 100), bw = 5 * L.u;
      ctx.save();
      ctx.fillStyle = "rgba(5,8,15,0.58)"; roundRect(x - 13 * L.u, y0 - 18 * L.u, 26 * L.u, (y1 - y0) + 34 * L.u, 8 * L.u); ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.14)"; ctx.fillRect(x - bw / 2, y0, bw, y1 - y0);
      var gy = y1 - (y1 - y0) * pos / 100; ctx.fillStyle = ACCENT; ctx.fillRect(x - bw / 2, gy, bw, y1 - gy);
      ctx.font = "700 " + (8.5 * L.u).toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (var v = 0; v <= 100; v += 10) {
        var ty = y1 - (y1 - y0) * v / 100; ctx.fillStyle = "rgba(255,255,255,0.55)"; ctx.fillRect(x - 5 * L.u, ty - 0.5, 10 * L.u, 1);
        if (v % 20 === 0 && v > 0 && v < 100) { ctx.fillStyle = "rgba(255,255,255,0.75)"; ctx.fillText(String(v), x, ty - 6 * L.u); }
      }
      ctx.fillStyle = "#ffd36a"; ctx.fillText("TD", x, y0 - 8 * L.u); ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.fillText("0", x, y1 + 10 * L.u);
      // ball marker
      ctx.translate(x, gy); ctx.rotate(-0.5); ctx.fillStyle = "#9a5528"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1; ctx.beginPath(); ctx.ellipse(0, 0, 7 * L.u, 4.3 * L.u, 0, 0, TAU); ctx.fill(); ctx.stroke();
      ctx.restore();
    }
    function render() {
      var t = S.time;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
      ctx.save();
      // camera: zoom about the line-of-scrimmage anchor, plus shake
      var sk = S.shake, ox = 0, oy = 0;
      if (sk) { var age = (t - sk.t0) / sk.dur; if (age >= 1) S.shake = null; else { var m = sk.a * (1 - age) * L.u; ox = (Math.sin(t * 91) + Math.sin(t * 57)) * 0.5 * m; oy = Math.cos(t * 83) * m; } }
      ctx.translate(L.cx + ox, L.ay + oy); ctx.scale(S.zoom, S.zoom); ctx.translate(-L.cx, -L.ay);
      drawField(); drawEntities(); drawFx();
      ctx.restore();
      // vignette, flash, fade
      if (vignette) { ctx.fillStyle = vignette; ctx.fillRect(0, 0, W, H); }
      drawRuler();
      var f = S.flash;
      if (f) { var fa = (t - f.t0) / f.dur; if (fa >= 1) S.flash = null; else { ctx.globalAlpha = f.a * (1 - fa) * (1 - fa); ctx.fillStyle = f.c; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; } }
      if (S.fade > 0.003) { ctx.globalAlpha = S.fade; ctx.fillStyle = "#03050a"; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
    }

    // ---------------------------------------------------------------- the loop
    function movingNow() { return !!(P || R || S.parts.length || S.ring.length || S.flash || S.shake || S.fade > 0.003 || S.fade !== S.fadeTarget); }
    function frame(now) {
      raf = 0; var dt = Math.min(0.05, (now - last) / 1000); last = now;
      var playing = !!P;
      if (!playing && !movingNow() && !S.ambient) { render(); return; }
      if (!playing && !movingNow() && now - lastDraw < 32) { need(); return; }   // ambient shimmer capped near 30fps
      lastDraw = now; if (!(P && P.paused)) S.time += dt;
      if (P) stepPlay(dt);
      stepRest(dt);
      if (!(P && P.reduced)) updatePrev(dt);
      render();
      if (P || R || movingNow() || S.ambient) need();
    }
    function stepRest(dt) {
      var i, p;
      for (i = S.parts.length - 1; i >= 0; i--) { p = S.parts[i]; p.life -= dt; if (p.life <= 0) { S.parts.splice(i, 1); continue; } p.ox += p.vx * dt; p.oy += p.vy * dt; p.vy += p.g * dt; }
      if (S.fade !== S.fadeTarget) { var d = S.fadeTarget - S.fade, st = dt / 0.28; S.fade = Math.abs(d) <= st ? S.fadeTarget : S.fade + Math.sign(d) * st; }
      if (R) {
        R.t += dt; var u = eio3(R.t / R.dur);
        E.forEach(function (e, j) {
          var f = R.from[j], tx = e.ix, ty = S.los + e.iy; e.wx = lerp(f.x, tx, u); e.wy = lerp(f.y, ty, u); e.z = f.z * (1 - u); e.rot = f.rot * (1 - u); e.sxs = lerp(f.sxs, 1, u); e.sys = lerp(f.sys, 1, u);
          e.run = u < 0.97 && Math.hypot(tx - f.x, ty - f.y) > 0.8; e.arms = "idle";
        });
        S.cam = S.los; S.zoom = 1;
        var g = S.ballG; g.held = null; g.x = lerp(R.bx, 0, u); g.y = lerp(R.by, S.los + 0.3, u); g.h = lerp(R.bh, 2, u);
        if (R.t >= R.dur) { R = null; formation(); }
      } else if (!P) {
        for (i = 0; i < E.length; i++) applyIdlePose(E[i], S.time);
        S.cam = lerp(S.cam, S.los, 0.2); S.zoom = lerp(S.zoom, 1, 0.2);
      }
    }
    function updatePrev(dt) {
      for (var i = 0; i < E.length; i++) {
        var e = E[i]; if (dt > 0) { var v = (e.wy - e.py) / dt; e.vy = lerp(e.vy, v, 0.25); }
        e.px = e.wx; e.py = e.wy;
        if (e.run) e.phase += dt * 15;
        if (e.run && Math.abs(e.vy) > 1.2) e.back = e.vy > 0; else if (!e.run && !P) e.back = e.team === "o";
      }
    }
    function stepPlay(dt) {
      var p = P;
      if (p.reduced) { p.t += dt; if (!p.fired.sw && p.t >= 0.22) { p.fired.sw = 1; finalState(); } S.fadeTarget = p.t < 0.22 ? 0.65 : 0; if (p.t >= 0.5) endPlay(); return; }
      if (p.paused) { if (p.sack) evalSack(Math.min(p.t, p.tEnd)); else evalPlay(Math.min(p.t, p.tEnd)); return; }
      var rate = 1;
      if (p.slow && p.t > p.tc - p.slow[0] && p.t < p.tc + p.slow[1] - 0.2) rate = 0.5;
      p.t += dt * rate;
      if (p.sack) evalSack(Math.min(p.t, p.tEnd)); else evalPlay(Math.min(p.t, p.tEnd));
      if (p.t >= p.tEnd) endPlay();
    }
    function finalState() {   // jump to the end of the play
      var p = P; if (!p) return;
      var save = p.fired; p.fired = {}; if (p.sack) evalSack(p.tEnd); else evalPlay(p.tEnd); p.fired = save;
      S.shake = null; S.flash = null; S.ring.length = 0;
    }
    function endPlay() {
      var p = P; if (!p) return; var cb = p.done; P = null;
      if (!p.sack) { S.los = p.L1; S.losLine = p.L1; if (p.fd1 != null) { S.fd = p.fd1; if (!p.score) S.fdGreen = false; } }
      S.cam = S.los; S.zoom = 1; S.trail.length = 0; S.fadeTarget = 0;
      var g = S.ballG;
      R = { t: -0.45, dur: 0.95, from: E.map(function (e) { return { x: e.wx, y: e.wy, z: e.z, rot: e.rot, sxs: e.sxs, sys: e.sys }; }), bx: g.x, by: g.y, bh: g.h };
      if (p.score) R.t = -1.1;
      if (cb) cb();
      need();
    }

    // ---------------------------------------------------------------- public API
    function setReduced() { return !!(reducedQ && reducedQ.matches); }
    var api = {
      resize: layout,
      setNumber: function (n) { S.number = n; EK.qb.n = n; need(); },
      setAmbient: function (on) { S.ambient = !!on; need(); },
      setRuler: function (on) { S.ruler = !!on; need(); },
      // Where the line of scrimmage sits on screen (fraction of the height) and whether the yard ruler shows.
      setView: function (ayFrac, ruler) { L.ayF = ayFrac; L.ay = H * ayFrac; S.ruler = !!ruler; need(); },
      // Put the ball on the p-yard line (0 = own goal line, 100 = opponent goal line) with the first-down line at world yard fd.
      setScene: function (p, fd, o) {
        o = o || {}; P = null; R = null; S.los = clamp(p, 0, 100); S.losLine = S.los; S.cam = S.los; S.zoom = 1; S.fd = fd == null ? Math.min(110, S.los + 10) : fd; S.fdGreen = !!o.fdGreen; S.trail.length = 0; S.ring.length = 0; S.parts.length = 0; S.flash = null; S.shake = null;
        if (o.number) { S.number = o.number; } formation(); layout(); need();
      },
      // A drive-ending reset: fade out, jump to the new yard line, fade in.
      reset: function (p, fd) { S.fadeTarget = 1; var self = this; setTimeout(function () { self.setScene(p, fd); S.fade = 1; S.fadeTarget = 0; need(); }, setReduced() ? 120 : 300); need(); },
      // Run the designated play for a graded answer. o: {tier, gain, p0, fd0, fd1, score, variant, seed}. done() fires when it has settled.
      play: function (o, done) {
        this.skip(true); layout();
        var sp = buildPlay(o); sp.done = done; sp.reduced = setReduced(); P = sp; R = null; S.zoom = 1; S.fadeTarget = 0; S.fade = 0;
        if (o.fd0 != null) S.fd = o.fd0; S.fdGreen = false; S.losLine = o.p0; S.los = o.p0; S.cam = o.p0; S.trail.length = 0;
        if (sp.reduced) { evalPlay(0); S.ballG.h = 2; } else evalPlay(0);
        need(); return sp;
      },
      sack: function (o, done) {
        this.skip(true); layout();
        var sp = { sack: true, tier: 0, L0: o.p0, L1: o.p0, tEnd: 1.9, t: 0, fired: {}, color: "#ff5d7a", done: done, reduced: setReduced(), fd1: o.fd1 }; P = sp; R = null; S.los = o.p0; S.cam = o.p0; S.zoom = 1; S.fadeTarget = 0; S.fade = 0; S.trail.length = 0; if (o.fd0 != null) S.fd = o.fd0;
        if (sp.reduced) sp.tEnd = 0.5; evalSack(0); need(); return sp;
      },
      // Finish whatever play is running right now (the player tapped or pressed a key). quiet: do not call the done callback.
      skip: function (quiet) {
        var p = P; if (!p) { if (R) { R.t = R.dur; } return false; }
        if (quiet) { P = null; S.fadeTarget = 0; S.fade = 0; return false; }
        finalState(); endPlay(); return true;
      },
      playing: function () { return !!P; },
      // dev only (used by /play?demo=1): freeze the running play at t seconds, or pass null to let it run on.
      seek: function (t) {
        var p = P; if (!p) return; if (t == null) { p.paused = false; need(); return; }
        p.paused = false; p.reduced = false; p.fired = {}; S.ring.length = 0; S.parts.length = 0; S.trail.length = 0;
        var base = S.time, ev0 = function (k) { if (p.sack) evalSack(k); else evalPlay(k); };
        for (var k = Math.max(0, t - 0.5); k < t; k += 0.03) { S.time = base - (t - k); ev0(k); }
        S.time = base; p.t = t; p.fired = {}; ev0(t); S.time += 0.12; p.paused = true; need();
      },
      ballPoint: function () { var g = S.ballG; pj(g.x, g.y); var r = canvas.getBoundingClientRect(); return { x: r.left + PR.x, y: r.top + PR.y - g.h * ksz(PR.s) }; },
      flash: flash, shake: shake,
      tdCelebrate: function () { flash("#ffab1a", 0.4, 0.8); shake(5, 0.5); },
      state: function () { return { los: S.los, fd: S.fd, number: S.number, playing: !!P, tier: P ? P.tier : 0, t: P ? P.t : 0 }; }
    };
    window.addEventListener("resize", layout);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) need(); else if (raf) { cancelAnimationFrame(raf); raf = 0; } });
    if (typeof ResizeObserver !== "undefined") { try { new ResizeObserver(layout).observe(canvas); } catch (e) { /* fall back to window resize */ } }
    formation(); layout(); need();
    return api;
  }

  window.DDField = { create: create, hash: hashStr, colors: COLORS };
})();
