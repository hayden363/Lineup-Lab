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
  var NAMES = ["", "CHECKDOWN", "QUICK SLANT", "CHAIN MOVER", "CHUNK PLAY", "BOMB", "HIGHLIGHT REEL TD"];
  var RB = ["#ff3b3b", "#ff9a1f", "#ffe92e", "#37e66a", "#2ec8ff", "#7b61ff", "#d65bff"], CONF = ["#ffd36a", "#ffb84d", "#ffffff", "#ff8a3d", "#fff04d", "#19e08a"];
  var SKINS = ["#f0c8a0", "#c68642", "#8d5524", "#e0ac69", "#a86f45"];
  function rgbOf(hex) { var h = String(hex || "#000").replace("#", ""); if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]; var n = parseInt(h, 16) || 0; return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  function mix(a, b, t) { var x = rgbOf(a), y = rgbOf(b); return "rgb(" + Math.round(lerp(x[0], y[0], t)) + "," + Math.round(lerp(x[1], y[1], t)) + "," + Math.round(lerp(x[2], y[2], t)) + ")"; }
  function luma(hex) { var c = rgbOf(hex); return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255; }
  // The favorite-team skin (setTeam): which formation slot wears which real jersey number.
  var SLOTS = { o: [["ol1", "ol", 0], ["ol2", "ol", 1], ["c", "ol", 2], ["ol4", "ol", 3], ["ol5", "ol", 4], ["te", "te", 0], ["wrL", "wr", 0], ["wrR", "wr", 1], ["rb", "rb", 0]],
    d: [["dl1", "dl", 0], ["dl2", "dl", 1], ["dl3", "dl", 2], ["dl4", "dl", 3], ["lbL", "lb", 0], ["lbR", "lb", 1], ["cbL", "cb", 0], ["cbR", "cb", 1], ["sL", "s", 0], ["sR", "s", 1]] };

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
    { k: "ol1", t: "ol", o: 1, x: -7.2, y: 0, n: 70 }, { k: "ol2", t: "ol", o: 1, x: -3.6, y: 0, n: 64 }, { k: "c", t: "ol", o: 1, x: 0, y: 0, n: 52 },
    { k: "ol4", t: "ol", o: 1, x: 3.6, y: 0, n: 66 }, { k: "ol5", t: "ol", o: 1, x: 7.2, y: 0, n: 76 },
    { k: "te", t: "te", o: 1, x: 11, y: 0, n: 85 }, { k: "wrL", t: "wr", o: 1, x: -15, y: 0, n: 11 }, { k: "wrR", t: "wr", o: 1, x: 15, y: 0, n: 18 },
    { k: "rb", t: "rb", o: 1, x: -4.6, y: -6, n: 28 }, { k: "qb", t: "qb", o: 1, x: 0, y: -5.2, n: 1 },
    { k: "dl1", t: "dl", x: -5.8, y: 2.2, n: 91 }, { k: "dl2", t: "dl", x: -2, y: 2.2, n: 97 }, { k: "dl3", t: "dl", x: 2, y: 2.2, n: 93 }, { k: "dl4", t: "dl", x: 5.8, y: 2, n: 99 },
    { k: "lbL", t: "lb", x: -7, y: 5.8, n: 54 }, { k: "lbR", t: "lb", x: 7, y: 5.8, n: 52 },
    { k: "cbL", t: "cb", x: -15.5, y: 6.5, n: 24 }, { k: "cbR", t: "cb", x: 15.5, y: 6.5, n: 21 },
    { k: "sL", t: "s", x: -8, y: 19, n: 29 }, { k: "sR", t: "s", x: 8, y: 19, n: 31 }
  ];

  // ------------------------------------------------------------------ the plays. spec(): receiver, route, catch, yards after catch, tackler, camera and ball behaviour.
  // g = yards gained on the play (the tackle spot is exactly g past the line of scrimmage), a = air yards (where the catch happens).
  function splitAir(def, g, score) { return clamp(Math.min(def, g * 0.62), 1.2, def); }

  function playSpec(tier, g, variant, rem, score) {
    var s = { tier: tier, color: COLORS[tier], label: NAMES[tier], g: g, score: !!score, throwDur: 0.8, yacDur: 0.5, camDur: 0.6, arc: 50, bscale: 1.3, trail: "none", lead: 0, zoomOut: 0, zoomAt: 1, rch: 1, slowAmt: 0, freeze: 0, replay: false, feet: false, lag: 1.3, cov: {}, sDrop: 5 };
    var a, c;
    if (tier === 1) {                                              // Checkdown: flat route to the back, low fast dart, no trail
      a = splitAir(1.6, g, score); s.rk = "rb"; s.tk = "cbL"; s.throwDur = 0.45; s.yacDur = 0.62; s.camDur = 0.35; s.arc = 9; s.bscale = 1.12; s.rch = 0.35;
      s.route = makePath([[P2(-4, -5), P2(-7.5, -5.4), P2(-10.5, -2.2), P2(-12.6, a)]]);
      s.catchPt = P2(-12.6, a);
      s.yac = makePath([[s.catchPt, P2(-15, a + (g - a) * 0.45), P2(-15.2, a + (g - a) * 0.8), P2(-14.6, g)]]);
      s.end = P2(-14.6, g); s.lag = 0.8; s.cov = { lbL: 0.5 };
    } else if (tier === 2) {                                       // Quick Slant: stem, sharp 45-degree cut inside, line drive, thin white trail, zoom on the catch
      a = splitAir(7, g, score); var st = Math.min(2.6, a * 0.4);
      s.rk = "wrR"; s.tk = "lbR"; s.throwDur = 0.5; s.yacDur = 0.62; s.camDur = 0.55; s.arc = 13; s.bscale = 1.18; s.trail = "thin"; s.zoomAt = 1.22; s.rch = 0.62;
      s.route = makePath([seg(P2(15, 0), P2(15, st)), seg(P2(15, st), P2(15 - (a - st), a))]);
      s.catchPt = P2(15 - (a - st), a);
      s.yac = makePath([[s.catchPt, P2(s.catchPt.x - 1.2, a + (g - a) * 0.4), P2(s.catchPt.x - 2.4, a + (g - a) * 0.75), P2(s.catchPt.x - 3, g)]]);
      s.end = P2(s.catchPt.x - 3, g); s.lag = 1.1;
    } else if (tier === 3) {                                       // Chain Mover: deep dig past the first-down line, medium arc
      a = splitAir(16, g, score); var stem = Math.max(2, a - 1.5);
      s.rk = "wrL"; s.tk = "sL"; s.throwDur = 0.8; s.yacDur = 0.66; s.arc = 58; s.bscale = 1.5; s.lead = 0.2; s.lag = 1.6; s.cov = { sL: 0.2 }; s.zoomAt = 1.14; s.rch = 0.85;
      s.route = makePath([seg(P2(-15, 0), P2(-15, stem)), seg(P2(-15, stem), P2(-4.5, a))]);
      s.catchPt = P2(-4.5, a);
      s.yac = makePath([[s.catchPt, P2(-3, a + (g - a) * 0.4), P2(-1.5, a + (g - a) * 0.75), P2(-0.8, g)]]);
      s.end = P2(-0.8, g);
    } else if (tier === 4) {                                       // Chunk Play: deep post splitting two safeties, high lob, glowing purple trail, camera zooms out mid-throw
      a = splitAir(37, g, score); var stem4 = a * 0.55;
      s.rk = "wrR"; s.tk = "sL"; s.throwDur = 0.95; s.yacDur = 0.9; s.arc = 105; s.bscale = 1.9; s.trail = "glow"; s.zoomOut = 0.08; s.zoomAt = 1.6; s.lead = 0.45; s.slowAmt = 0.3; s.lag = 2.2; s.cov = { sL: 0, sR: 0 }; s.sDrop = 9;
      s.route = makePath([seg(P2(15, 0), P2(14.6, stem4)), seg(P2(14.6, stem4), P2(1.5, a))]);
      s.catchPt = P2(1.5, a);
      s.yac = makePath([[s.catchPt, P2(0.8, a + (g - a) * 0.4), P2(-0.4, a + (g - a) * 0.75), P2(-1.2, g)]]);
      s.end = P2(-1.2, g);
    } else if (tier === 5) {                                       // Bomb: go route against double coverage, huge rainbow, slow-motion catch, screen shake
      a = splitAir(52, g, score);
      s.rk = "wrL"; s.tk = "sL"; s.throwDur = 0.95; s.yacDur = 0.85; s.camDur = 0.55; s.arc = 175; s.bscale = 2.5; s.trail = "rainbow"; s.lead = 0.5; s.lag = 3.2; s.cov = { sL: 0.25 }; s.sDrop = 14; s.zoomOut = 0.08; s.zoomAt = 1.95; s.slowAmt = 0.55; s.freeze = 0.2; s.replay = true;
      s.route = makePath([[P2(-15, 0), P2(-17.5, a * 0.35), P2(-18, a * 0.7), P2(-14, a)]]);
      s.catchPt = P2(-14, a);
      s.yac = makePath([[s.catchPt, P2(-12, a + (g - a) * 0.35), P2(-9, a + (g - a) * 0.7), P2(-6.5, g)]]);
      s.end = P2(-6.5, g);
    } else {                                                       // Highlight Reel TD: three signature catches
      s.score = true; s.variant = variant; s.color = COLORS[6]; s.bscale = 1.9; s.trail = "glow"; s.lead = 0.45; s.arc = 120; s.camDur = 0.55; s.slowAmt = 0.55; s.freeze = 0.24; s.replay = true; s.zoomAt = variant === 1 ? 2.5 : variant === 0 ? 2.25 : 2.0; s.feet = variant === 1;
      if (variant === 0) {                                         // one-handed grab falling backward in the end zone
        a = rem + 3.5; s.rk = "wrR"; s.tk = "cbR"; s.throwDur = 1.0; s.yacDur = 0.7; s.lag = 0.7; s.cov = { cbR: 0.95 };
        s.route = makePath([[P2(15, 0), P2(16.5, a * 0.4), P2(13, a * 0.72), P2(9, a)]]);
        s.catchPt = P2(9, a); s.yac = makePath([seg(s.catchPt, P2(8.6, a - 1.3))]); s.end = P2(8.6, a - 1.3);
      } else if (variant === 1) {                                  // toe-tap in the back corner
        a = rem + 5.5; s.rk = "wrR"; s.tk = "cbR"; s.throwDur = 1.05; s.yacDur = 0.7; s.lag = 0.5; s.cov = { cbR: 0.95 };
        s.route = makePath([[P2(15, 0), P2(19, a * 0.45), P2(23.4, a * 0.75), P2(22.2, a)]]);
        s.catchPt = P2(22.2, a); s.yac = makePath([seg(s.catchPt, P2(22.6, a + 0.5))]); s.end = P2(22.6, a + 0.5);
      } else {                                                     // catch and run: juke, spin, dive for the pylon
        a = clamp(rem * 0.42, 6, 38); var run = Math.max(2, rem - a); s.rk = "wrL"; s.tk = "cbR"; s.throwDur = 0.85; s.yacDur = 0.95 + Math.min(0.4, run * 0.008); s.lag = 1.4; s.cov = { cbR: 0 };
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
    var S = { los: 0, losLine: 0, cam: 0, fd: 10, fdGreen: false, fdPulse: -9, number: 1, zoom: 1, ambient: true, time: 0, flash: null, shake: null, fade: 0, fadeTarget: 0, trail: [], ruler: true, hold: 0, bars: 0, fLow: 0, sackF: 0, cboost: 0, cb0: -9, anyFx: false, ballG: { x: 0, y: 0.3, h: 4, held: null, ang: 0.3, sc: 1, spin: 0, pinS: 0, pinE: 0 } };
    var E = [], EK = {}, P = null, R = null, raf = 0, last = 0, lastDraw = 0, vignette = null, fogG = null, PR = { x: 0, y: 0, s: 1 };
    var bandCv = null, litCv = null, glowCv = null, scanPat = null, sceneC = null, SK = [0, 0, 0, 0, 0, 0, 0, 0, 0], bandH = 0, nextFlash = 0, BP = { x: 0, y: 0, t: 0, vx: 0, vy: 0 };
    var PP = [], SP = [], RG = [], CFL = [], IT = [], PPi = 0, SPi = 0, RGi = 0, CFi = 0, DUST = [], HG = [], i0;
    for (i0 = 0; i0 < 320; i0++) PP.push({ on: 0, x: 0, y: 0, ox: 0, oy: 0, vx: 0, vy: 0, g: 0, life: 0, max: 1, c: "#fff", r: 1, kind: 0, rot: 0 });
    for (i0 = 0; i0 < 300; i0++) SP.push({ on: 0, x: 0, y: 0, px: 0, py: 0, vx: 0, vy: 0, g: 0, life: 0, max: 1, c: "#fff", r: 1, kind: 0, rot: 0, vr: 0 });
    for (i0 = 0; i0 < 14; i0++) RG.push({ on: 0, x: 0, y: 0, c: "#fff", t0: 0, sc: 1 });
    for (i0 = 0; i0 < 12; i0++) CFL.push({ on: 0, x: 0, y: 0, t0: 0 });
    for (i0 = 0; i0 < 24; i0++) IT.push({ y: 0, e: null });
    for (i0 = 0; i0 < 8; i0++) DUST.push("rgba(214,204,176," + (0.42 * i0 / 7).toFixed(2) + ")");
    function helmetGrads(c) {   // helmet shells: highlight, body, dark rim (unit circle; scaled per use)
      HG.length = 0;
      for (var j = 0; j < 2; j++) { var g = ctx.createRadialGradient(-0.35, -0.4, 0.05, 0, 0, 1.05); g.addColorStop(0, c[j][0]); g.addColorStop(0.55, c[j][1]); g.addColorStop(1, c[j][2]); HG.push(g); }
    }
    helmetGrads([["#2fd88f", "#0d8a54", "#06462b"], ["#f3f6fc", "#b4bfd6", "#5f6c8c"]]);
    function shell(hex) { return [mix(hex, "#ffffff", 0.45), hex, mix(hex, "#000000", 0.6)]; }
    var TU = null;     // the favorite-team skin, derived once by setTeam (null = the Lineup Lab default look)
    // Pixel-art players in a modern scene: each player is drawn small on its own sprite canvas, outlined 1px, then
    // blitted up with smoothing off so the pixels stay crisp. The field, lights, ball and effects stay smooth.
    var PIX = false, PXC = null, PXX = null, OLC = null, OLX = null, PXN = 112, PXO = [56, 94];
    var GLY = ["111101101101111", "010110010010111", "111001111100111", "111001111001111", "101101111001001", "111100111001111", "111100111101111", "111001010010010", "111101111101111", "111101111001111"];
    function pixNum(str, cx, cy, fg, bg) {      // 3x5 pixel digits, with a 1px drop outline
      var m = ctx.getTransform(), ax = m.a * cx + m.c * cy + m.e, ay = m.b * cx + m.d * cy + m.f;     // snap to whole sprite pixels, upright
      var n = str.length, x0 = Math.round(ax - (n * 4 - 1) / 2), y0 = Math.round(ay - 2.5), pass, i, j, g;
      ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
      for (pass = 0; pass < 2; pass++) {
        ctx.fillStyle = pass ? fg : bg;
        for (i = 0; i < n; i++) { g = GLY[str.charCodeAt(i) - 48]; if (!g) continue; for (j = 0; j < 15; j++) if (g[j] === "1") ctx.fillRect(x0 + i * 4 + (j % 3) + (pass ? 0 : 1), y0 + ((j / 3) | 0) + (pass ? 0 : 1), 1, 1); }
      }
      ctx.restore();
    }
    function drawPix(e, sx, sy, k) {
      if (!PXC) { PXC = document.createElement("canvas"); PXC.width = PXC.height = PXN; PXX = PXC.getContext("2d"); OLC = document.createElement("canvas"); OLC.width = OLC.height = PXN; OLX = OLC.getContext("2d"); }
      var kp = Math.min(0.8, k), sc = k / kp, ox = PXO[0], oy = PXO[1], main = ctx;
      PXX.setTransform(1, 0, 0, 1, 0, 0); PXX.clearRect(0, 0, PXN, PXN);
      ctx = PXX; PIX = true; try { drawSprite(e, ox, oy, kp); } finally { ctx = main; PIX = false; }
      e.hsx = sx + (e.hsx - ox) * sc; e.hsy = sy + (e.hsy - oy) * sc;          // the ball is pinned to the hand on screen
      OLX.globalCompositeOperation = "source-over"; OLX.clearRect(0, 0, PXN, PXN);
      OLX.drawImage(PXC, -1, 0); OLX.drawImage(PXC, 1, 0); OLX.drawImage(PXC, 0, -1); OLX.drawImage(PXC, 0, 1);
      OLX.globalCompositeOperation = "source-in"; OLX.fillStyle = "#05080f"; OLX.fillRect(0, 0, PXN, PXN);
      OLX.globalCompositeOperation = "source-over"; OLX.drawImage(PXC, 0, 0);
      var wb = e.t === "ol" || e.t === "dl" ? 1.1 : 1, shs = 1 - Math.min(0.5, e.z / 36);                 // ground shadow, snapped to whole pixels
      ctx.fillStyle = "rgba(0,0,0,0.38)"; ctx.fillRect(Math.round(sx - 7 * k * wb * shs), Math.round(sy - 1.6 * k * shs), Math.round(14 * k * wb * shs), Math.max(2, Math.round(3.4 * k * shs)));
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(OLC, Math.round(sx - ox * sc), Math.round(sy - oy * sc), PXN * sc, PXN * sc);
      ctx.imageSmoothingEnabled = true;
    }
    var rnd = rng(7);

    FORM.forEach(function (f, i) {
      var e = { k: f.k, t: f.t, team: f.o ? "o" : "d", n: f.n, ix: f.x, iy: f.y, wx: f.x, wy: f.y, rx: f.x, ry: f.y, px: f.x, py: f.y, z: 0, rot: 0, sxs: 1, sys: 1, arms: "idle", aq: 0, cq: 0, ov: 0, cr: 0, amp: 1, tapL: 0, tapR: 0, lvl: 1, hsx: 0, hsy: 0, run: false, back: !!f.o, vy: 0, phase: i * 1.7, skin: SKINS[i % SKINS.length], bob: i * 0.9 };
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
      bake();
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
        e.z = 0; e.rot = 0; e.sxs = 1; e.sys = 1; idleE(e); e.back = e.team === "o"; e.vy = 0;
      });
      EK.qb.n = qbN();
      var g = S.ballG; g.x = 0; g.y = S.los + 0.3; g.h = 2; g.held = null; g.sc = 1; g.ang = 0.25;
    }
    function qbN() { return TU && TU.qbNum != null ? TU.qbNum : S.number; }   // a team field: the QB's real number; default field: the question number
    function idleE(e) { e.run = false; e.aq = 0; e.cq = 0; e.ov = 0; e.amp = 1; e.tapL = 0; e.tapR = 0; e.lvl = 1; e.cr = e.t === "ol" || e.t === "dl" ? 1 : 0; e.arms = e.k === "qb" ? "hold" : e.cr ? "set" : "idle"; }
    function applyIdlePose(e, t) { idleE(e); e.z = e.team === "o" ? 0.35 * Math.sin(t * 2.1 + e.bob) : 0; }
    function need() { if (!raf && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); } }

    // ---------------------------------------------------------------- building a play
    function buildPlay(o) {
      var rem = 100 - o.p0, tier = o.tier, g = o.gain, score = !!o.score || tier === 6;
      var variant = o.variant == null ? 0 : o.variant;
      if (tier === 6) { variant = rem > 55 ? 2 : variant; g = rem; }
      var sp = playSpec(tier, score && tier !== 6 ? Math.min(g, rem) : g, variant, rem, score);
      sp.L0 = o.p0; sp.L1 = score ? 100 : o.p0 + g; sp.tc = 0.4 + sp.throwDur; sp.ty = sp.tc + sp.yacDur; sp.tEnd = sp.ty + sp.camDur + (score ? 0.2 : 0.1);
      sp.fd0 = o.fd0; sp.fd1 = o.fd1; sp.t = 0; sp.fired = {}; sp.seed = o.seed || 1;
      sp.lead = Math.min(sp.lead * Math.min(sp.catchPt.y, 55), Math.max(0, sp.catchPt.y - 5)); sp.hasFd = false;
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
    var PAIR = { dl1: -7.2, dl2: -3.6, dl3: 3.6, dl4: 7.2 };
    function olY(t) { return -0.5 * sstep(t / 0.45) - 0.9 * sstep((t - 0.5) / 2.2); }
    function resetE(e) { e.rx = e.ix; e.ry = e.iy; e.z = 0; e.rot = 0; e.sxs = 1; e.sys = 1; e.arms = "idle"; e.aq = 0; e.cq = 0; e.run = false; e.ov = 0; e.cr = 0; e.amp = 1; e.tapL = 0; e.tapR = 0; e.lvl = 1; }
    function evalPlay(t) {
      var p = P, tc = p.tc, ty = p.ty, L0 = p.L0, i, e, g = S.ballG, ti = p.tier;
      for (i = 0; i < E.length; i++) resetE(E[i]);
      // the line: offensive tackles set and the front four meet them (engage, shuffle, hold the pocket)
      for (i = 0; i < E.length; i++) {
        e = E[i];
        if (e.t === "ol") { e.ry = e.iy + olY(t); e.arms = "block"; e.aq = sstep((t - 0.08) / 0.4); e.cr = 1 - 0.45 * e.aq; e.rx = e.ix + 0.1 * Math.sin(t * 12 + e.bob) * e.aq; e.ov = 2; e.run = t > 0.05; e.amp = 0.3; }
      }
      // quarterback: drop, wind up, release at t=0.4, follow through
      var q = EK.qb; qbHand(t, QP); q.rx = QP.x; q.ry = QP.y; q.run = t < 0.42; q.ov = 2;
      var tq = (t - 0.24) / 0.3; q.arms = tq > 0 ? "throw" : "hold"; q.aq = tq;
      if (t >= 0.4) { q.rot = -0.1 * Math.sin(clamp((t - 0.4) / 0.5, 0, 1) * PI); q.sxs = 1 - 0.1 * Math.sin(clamp((t - 0.38) / 0.4, 0, 1) * PI); }
      // skill players
      var keys = ["wrL", "wrR", "te", "rb"], rcv = EK[p.rk];
      for (i = 0; i < keys.length; i++) {
        e = EK[keys[i]]; skillPos(keys[i], t, CP); e.rx = CP.x; e.ry = CP.y; e.run = t > 0.12 && t < ty; e.ov = t < tc ? 2 : 0;
        if (e.k === p.rk) {
          e.lvl = p.rch;
          if (t > tc - 0.3 && t < tc + 0.22) { e.arms = "catch"; e.aq = t < tc ? sstep((t - (tc - 0.3)) / 0.24) : 1 - sstep((t - tc) / 0.22); e.cq = t >= tc ? 1 : 0; }
          else if (t >= tc) e.arms = "carry";
        }
      }
      // defenders
      for (i = 0; i < E.length; i++) {
        e = E[i]; if (e.team !== "d") continue;
        defBase(e, t, DP); e.rx = DP.x; e.ry = DP.y; e.run = t > 0.25 && t < ty + 0.1; e.arms = "idle";
        if (e.t === "dl") {
          var en = sstep((t - 0.1) / 0.45); e.rx = lerp(e.ix, PAIR[e.k], en) + 0.16 * Math.sin(t * 13 + e.bob) * en; e.ry = lerp(e.iy, olY(t) + 1.25, en);
          e.run = t > 0.05; e.amp = en < 0.95 ? 1 : 0.3; e.arms = "block"; e.aq = en; e.cr = 1 - 0.45 * en; e.ov = 1;
        }
        if (e.k === p.tk && t > tc) {          // the tackler converges and arrives exactly at the tackle spot at ty
          var from = defBaseAt(e, tc), u = ei2((t - tc) / p.yacDur), tx = p.end.x + (e.ix < p.end.x ? -0.9 : 0.9), tyy = p.score ? p.end.y - 3.2 : p.end.y - 0.35;
          e.rx = lerp(from.x, tx, u); e.ry = lerp(from.y, tyy, u); e.run = true; e.arms = "wrap"; e.aq = u * 0.7;
        }
      }
      rcvPose(t, rcv);
      // tackle: the defender wraps up and drives the carrier down at the exact yard
      if (!p.score && t >= ty) {
        var pr = eo3((t - ty) / 0.3), tk = EK[p.tk], dr = tk.ix < p.end.x ? 1 : -1;
        rcv.sys = 1 - 0.3 * pr; rcv.rot = 0.55 * pr * dr; rcv.run = false; rcv.arms = "carry"; rcv.cq = 1; rcv.z = 1.4 * Math.sin(pr * PI);
        tk.rot = 1.3 * dr * pr; tk.run = false; tk.arms = "wrap"; tk.aq = 1; tk.z = 2.4 * Math.sin(pr * PI); tk.rx = p.end.x + (tk.ix < p.end.x ? -0.9 : 0.9) + 0.8 * pr * dr;
      }
      if (p.score && t >= ty) { rcv.arms = "up"; rcv.aq = 1; rcv.run = false; if (p.tier !== 6 || p.variant === 2 && t > ty + 0.2) rcv.z = Math.max(rcv.z, 3 * Math.abs(Math.sin((t - ty) * 9))); }
      if (p.score && t >= ty) { var tk2 = EK[p.tk], pr2 = eo3((t - ty + 0.1) / 0.3); tk2.rot = 0.9 * pr2; tk2.sys = 1 - 0.3 * pr2; tk2.run = false; tk2.arms = "up"; tk2.aq = 1; }
      for (i = 0; i < E.length; i++) { e = E[i]; e.wx = e.rx; e.wy = L0 + e.ry; }
      ballAt(t, rcv, q);
      // camera: the world pans to a spot ahead of the catch; zoom pulls out a touch during the throw, then pushes in on the receiver
      var catchCam = L0 + p.lead, cam, pu = (t - ty) / p.camDur, relax = t > ty ? 1 - eio3(pu) : 1;
      if (t < 0.4) cam = L0; else if (t < ty) cam = lerp(L0, catchCam, sstep((t - 0.4) / (tc - 0.4 + 0.3))); else cam = catchCam;
      if (t > ty) cam = lerp(catchCam, p.L1, eio3(pu));
      S.cam = cam;
      var fl = clamp((t - 0.4) / (tc - 0.4), 0, 1), zm = 1;
      if (p.zoomOut) zm -= p.zoomOut * sstep((t - 0.3) / 0.35) * (1 - sstep((fl - 0.5) / 0.5));
      if (p.zoomAt > 1) zm += (p.zoomAt - 1) * sstep((fl - 0.35) / 0.65);
      S.zoom = 1 + (zm - 1) * relax;
      S.fLow = p.feet ? sstep((t - tc) / 0.2) * relax : 0;
      S.losLine = t >= ty ? p.L1 : L0;
      // the replay frame: letterbox bars and the INSTANT REPLAY bug around the big catch
      if (p.replay) S.bars = sstep((t - (tc - 0.85)) / 0.4) * (1 - sstep((t - (ty + 0.05)) / 0.4)); else S.bars = 0;
      // first-down line goes green the moment the ball carrier crosses it
      if (!p.fdHit && t >= tc && (L0 + rcv.ry >= S.fd - 0.15 || L0 + p.catchPt.y >= S.fd)) { p.fdHit = true; S.fdGreen = true; S.fdPulse = S.time; if (ti === 3) flash("#3ddc84", 0.22, 0.5); }
      // timed events
      ev(t, tc, "catch", function () {
        var cx = p.catchPt.x, cy = L0 + p.catchPt.y;
        addRing(cx, cy, p.color, ti === 1 ? 0.7 : 1);
        catchFx(ti, cx, cy, p.color);
        if (ti >= 5) shake(ti === 5 ? 7 : 6, 0.55);
        if (ti >= 5) flash(p.color, 0.3, 0.45); else if (ti >= 3) flash(p.color, 0.14, 0.3);
        if (ti >= 4) { S.cboost = 1; S.cb0 = S.time; }
      });
      ev(t, ty, "tackle", function () {
        S.losLine = p.L1;
        if (!p.score) { dust(p.end.x, L0 + p.end.y, 6 + ti * 2); turf(p.end.x, L0 + p.end.y, 4 + ti * 2); if (ti >= 5) shake(3, 0.2); flash("#ffffff", 0.08, 0.2); addRing(p.end.x, L0 + p.end.y, "#ffffff", 0.55); }
        else { burst(p.end.x, L0 + p.end.y, "#ffd36a", 36); flash("#ffab1a", 0.35, 0.6); S.cboost = 1; S.cb0 = S.time; confetti(110); }
      });
      if (ti === 6) {
        ev(t, ty + 0.12, "fw1", function () { firework(0.28, 0.2, "#ffd36a"); });
        ev(t, ty + 0.34, "fw2", function () { firework(0.74, 0.16, "#ff8a3d"); });
        ev(t, ty + 0.56, "fw3", function () { firework(0.5, 0.26, "#ffffff"); confetti(80); });
      }
      if (p.variant === 1 && ti === 6) {          // toe-tap: left foot, then right foot, each leaves a chalk puff
        rcv.tapL = pulse(t, tc + 0.12, 0.12); rcv.tapR = pulse(t, tc + 0.28, 0.12);
        ev(t, tc + 0.16, "tap1", function () { tapSpark(p.catchPt.x - 0.5, L0 + p.catchPt.y); });
        ev(t, tc + 0.32, "tap2", function () { tapSpark(p.catchPt.x + 0.2, L0 + p.catchPt.y); });
      }
      if (p.variant === 0 && ti === 6) ev(t, tc + 0.62, "land", function () { dust(p.end.x, L0 + p.end.y, 9); turf(p.end.x, L0 + p.end.y, 6); });
      if (p.variant === 2 && ti === 6) ev(t, ty - 0.08, "pylon", function () { burst(p.end.x + 1.8, L0 + p.end.y, "#ff8a1f", 18); addRing(p.end.x + 1.8, L0 + p.end.y, "#ffffff", 0.7); });
    }
    function pulse(t, c, w) { var d = Math.abs(t - c) / w; return d >= 1 ? 0 : Math.cos(d * PI / 2); }
    function rcvPose(t, rcv) {
      var p = P, tc = p.tc, ty = p.ty;
      if (p.tier !== 6) return;
      var v = p.variant;
      if (v === 0) {                                // one-handed grab, leaping and falling backward (he turns to face the ball)
        var u = clamp((t - (tc - 0.5)) / 1.25, 0, 1);
        if (t > tc - 0.5) { rcv.ov = 1; rcv.arms = "one"; rcv.aq = sstep((t - (tc - 0.5)) / 0.45); rcv.z = 17 * Math.sin(clamp(u * 1.05, 0, 1) * PI); rcv.rot = -0.3 * eo3(u); rcv.sys = 1 - 0.5 * eo3(clamp((t - tc) / 0.7, 0, 1)); rcv.run = false; rcv.cq = 0; }
        var cb = EK.cbR; if (t > tc - 0.4) { var m = eo3((t - tc + 0.4) / 0.6); cb.ov = 1; cb.z = 9 * Math.sin(clamp(m * 1.2, 0, 1) * PI) * (1 - m * 0.3); cb.rot = 0.35 * m; cb.arms = "up"; cb.aq = 1; cb.run = false; }
      } else if (v === 1) {                         // toe-tap in the back corner: over the shoulder, both hands, two drag steps at the line
        var u2 = clamp((t - (tc - 0.3)) / 0.7, 0, 1);
        if (t > tc - 0.3) { rcv.ov = 2; rcv.rot = 0.2 * Math.sin(u2 * PI * 0.9); rcv.z = 4.5 * Math.sin(clamp((t - tc + 0.3) / 0.4, 0, 1) * PI); rcv.run = false; }
        if (t > tc + 0.5) { rcv.arms = "up"; rcv.aq = 1; rcv.rot = 0.12; rcv.z = 2.5 * Math.abs(Math.sin((t - tc) * 8)); }
        var cb2 = EK.cbR; if (t > tc - 0.25) { cb2.rx = p.catchPt.x + 1.9; cb2.ry = p.catchPt.y - 0.9; cb2.rot = 0.5; cb2.arms = "up"; cb2.aq = 1; cb2.run = false; cb2.ov = 1; }
      } else {                                      // catch and run: juke, spin, dive for the pylon
        if (t > tc) {
          var uu = (t - tc) / p.yacDur;
          rcv.run = uu < 0.86; rcv.arms = "carry"; rcv.cq = 1;
          if (uu > 0.3 && uu < 0.42) rcv.rot = -0.5 * Math.sin((uu - 0.3) / 0.12 * PI);
          if (uu > 0.42 && uu < 0.68) { var sp = (uu - 0.42) / 0.26; rcv.sxs = Math.max(0.12, Math.abs(Math.cos(sp * TAU * 0.5 * 2))) * (Math.cos(sp * TAU) < 0 ? 1 : 1); rcv.z = 3 * Math.sin(sp * PI); rcv.rot = 0.12 * Math.sin(sp * TAU); }
          if (uu >= 0.86) { var d = clamp((uu - 0.86) / 0.14, 0, 1); rcv.sys = 1 - 0.5 * eo3(d); rcv.rot = 0.3 * d; rcv.z = 8 * Math.sin(d * PI); rcv.arms = "up"; rcv.aq = 0.8; rcv.run = false; }
          var lb = EK.lbR; if (uu > 0.28) { var m3 = eo3((uu - 0.28) / 0.25); lb.rx = lerp(lb.rx, rcv.rx - 1.1 + 2 * m3, 0.7 * m3); lb.rot = 1.2 * m3; lb.arms = "wrap"; lb.aq = 1; lb.z = 2 * Math.sin(m3 * PI); lb.run = m3 < 0.5; }
          var cb3 = EK.cbR; if (uu > 0.8) { var m2 = eo3((uu - 0.8) / 0.2); cb3.rot = -1.2 * m2; cb3.arms = "wrap"; cb3.aq = 1; cb3.run = false; cb3.z = 2 * Math.sin(m2 * PI); }
        }
      }
    }
    function ballAt(t, rcv, q) {
      var p = P, tc = p.tc, g = S.ballG, L0 = p.L0, u;
      g.pinS = 0; g.pinE = 0; g.spin = t * 30;
      if (t < 0.28) { u = sstep(t / 0.28); g.x = 0; g.y = L0 + lerp(0.3, q.ry + 0.2, u); g.h = lerp(2, 13, u) + 6 * Math.sin(u * PI); g.held = null; g.sc = 1; }
      else if (t < 0.4) { g.x = q.rx + 0.3; g.y = L0 + q.ry + 0.15; g.h = 13; g.held = "qb"; g.sc = 1; }
      else if (t < tc) {
        u = (t - 0.4) / p.throwDur; var sx0 = q.rx + 0.4, sy0 = L0 + q.ry + 0.2, hC = 12 + 23 * p.rch;
        var fu = eio3(u) * 0.35 + u * 0.65;
        g.x = lerp(sx0, p.catchPt.x, fu); g.y = lerp(sy0, L0 + p.catchPt.y, fu);
        g.h = lerp(14, hC, u) + Math.sin(u * PI) * p.arc; g.sc = 1 + (p.bscale - 1) * Math.sin(u * PI); g.held = null; g.spin = t * 38;
        g.pinS = 1 - clamp(u / 0.1, 0, 1); g.pinE = sstep((u - 0.84) / 0.16);
        if (!p.paused) trailAdd(g.x, g.y, g.h, g.sc);
      } else if (t < p.ty || p.score) { g.held = p.rk; g.sc = 1; g.x = rcv.rx + 0.3; g.y = L0 + rcv.ry + 0.1; g.h = rcv.arms === "up" ? 28 : 12; if (p.score && t >= p.ty) g.h = 26; }
      else { g.held = null; g.x = p.end.x + 0.2; g.y = L0 + p.end.y; g.h = 2.5 * Math.max(0, 1 - (t - p.ty) * 3); g.sc = 1; g.spin = 1.2; }
    }
    function trailAdd(x, wy, h, sc) {
      var tr = S.trail; tr.push({ x: x, y: wy, h: h, sc: sc, t: S.time }); if (tr.length > 26) tr.shift();
    }
    function ev(t, at, name, fn) { var p = P; if (t >= at && !p.fired[name]) { p.fired[name] = 1; fn(); } }

    // ---------------------------------------------------------------- sack: the pocket collapses, the quarterback goes down
    function evalSack(t) {
      var p = P, L0 = p.L0, i, e, q = EK.qb, g = S.ballG;
      for (i = 0; i < E.length; i++) resetE(E[i]);
      var drop = sstep(t / 0.4); q.rx = 0 + 0.5 * Math.sin(t * 5) * sstep((t - 0.5) / 0.4); q.ry = -4.6 - 2.1 * drop - 0.8 * sstep((t - 0.5) / 0.6); q.run = t < 0.42 || (t > 0.5 && t < 1.0); q.arms = "hold"; q.ov = 2;
      var sw = sstep((t - 0.35) / 0.75), hit = clamp((t - 1.05) / 0.5, 0, 1), qx = q.rx, qy = q.ry, col = sstep((t - 0.45) / 0.7);
      var rush = ["dl1", "dl2", "dl3", "dl4", "lbL", "lbR"];
      for (i = 0; i < E.length; i++) {
        e = E[i];
        if (e.t === "ol") { e.ry = e.iy + olY(t) - 1.6 * col; e.rx = lerp(e.ix, e.ix * 0.62, col); e.arms = "block"; e.aq = 1; e.cr = 0.6; e.ov = 2; e.run = t > 0.05 && t < 1.3; e.amp = 0.4; e.rot = 0.18 * col * (e.ix < 0 ? -1 : 1); }
      }
      for (i = 0; i < rush.length; i++) {
        e = EK[rush[i]]; var side = i % 2 ? 1 : -1, tx = qx + (i < 4 ? (i - 1.5) * 0.9 : side * 1.6), ty = qy + 0.7 + (i < 4 ? 0.2 * (i % 2) : 1.4);
        e.rx = lerp(e.ix, tx, eio3(sw)); e.ry = lerp(e.iy, ty, eio3(sw)); e.run = sw < 1; e.arms = sw > 0.55 ? "wrap" : "block"; e.aq = sw; e.ov = 1; e.cr = 0.3 * (1 - sw);
        if (hit > 0) { e.rot = (i % 2 ? 1.0 : -1.0) * eo3(hit) * (i < 4 ? 0.8 : 1); e.run = false; e.arms = "wrap"; e.aq = 1; e.z = 2 * Math.sin(eo3(hit) * PI); }
      }
      var k2 = ["cbL", "cbR", "sL", "sR"]; for (i = 0; i < k2.length; i++) { e = EK[k2[i]]; e.ry = e.iy + 2 * sstep(t / 0.7); }
      var wk = ["wrL", "wrR", "te"]; for (i = 0; i < wk.length; i++) { e = EK[wk[i]]; var d = sstep(t / 1.1); e.ry = e.iy + 9 * d; e.rx = e.ix + (e.ix > 0 ? -2 : 2) * d; e.run = t < 1.2; e.ov = 2; }
      EK.rb.rx = -4; EK.rb.ry = -5; EK.rb.arms = "up"; EK.rb.aq = 1; EK.rb.ov = 2;
      if (hit > 0) { q.rot = -1.25 * eo3(hit); q.sxs = 1; q.sys = 1 - 0.2 * eo3(hit); q.run = false; q.arms = "up"; q.aq = 1; q.z = 3 * Math.sin(eo3(hit) * PI); }
      for (i = 0; i < E.length; i++) { e = E[i]; e.wx = e.rx; e.wy = L0 + e.ry; }
      g.pinS = g.pinE = 0; g.spin = 1; g.held = hit > 0.5 ? null : "qb"; g.x = q.rx + 0.3 + (hit > 0.5 ? 1.0 : 0); g.y = L0 + q.ry + 0.15 - (hit > 0.5 ? 0.5 : 0); g.h = hit > 0.5 ? 2.5 : 13; g.sc = 1;
      S.cam = L0; S.losLine = L0; S.bars = 0; S.fLow = 0;
      var punch = Math.sin(clamp((t - 1.0) / 0.5, 0, 1) * PI); S.zoom = 1 + 0.16 * punch; S.sackF = punch;
      ev(t, 1.05, "hit", function () { flash("#05070c", 0.6, 0.7); dust(q.rx, L0 + q.ry, 12); dust(q.rx + 0.8, L0 + q.ry - 0.4, 6); turf(q.rx, L0 + q.ry, 6); addRing(q.rx, L0 + q.ry, "#ff5d7a", 0.8); p.fz = 0.14; });
    }

    // ---------------------------------------------------------------- effects (pooled: no allocation while a play runs)
    function flash(c, a, dur) { var f = S.flash; if (!f) f = S.flash = { c: c, a: a, t0: 0, dur: dur }; f.c = c; f.a = a; f.t0 = S.time; f.dur = dur; }
    function shake(a, dur) { var s = S.shake; if (!s) s = S.shake = { a: a, t0: 0, dur: dur }; s.a = a; s.t0 = S.time; s.dur = dur; }
    function addRing(x, wy, c, sc) { var r = RG[RGi = (RGi + 1) % RG.length]; r.x = x; r.y = wy; r.c = c; r.t0 = S.time; r.sc = sc || 1; r.on = 1; }
    function pnew() { for (var i = 0; i < PP.length; i++) { PPi = (PPi + 1) % PP.length; if (!PP[PPi].on) return PP[PPi]; } return null; }
    function put(x, wy, vx, vy, g, life, c, r, kind) {
      var p = pnew(); if (!p) return null;
      p.on = 1; p.x = x; p.y = wy; p.ox = 0; p.oy = 0; p.vx = vx; p.vy = vy; p.g = g; p.life = life; p.max = life; p.c = c; p.r = r; p.kind = kind; p.rot = rnd() * TAU; return p;
    }
    function burst(x, wy, c, n) { for (var i = 0; i < n; i++) { var a = rnd() * TAU, v = 20 + rnd() * 70; put(x, wy, Math.cos(a) * v, Math.sin(a) * v * 0.7 - 24, 90, 0.5 + rnd() * 0.5, c, 1 + rnd() * 1.7, 0); } }
    function stars(x, wy, c, n) { for (var i = 0; i < n; i++) { var a = rnd() * TAU, v = 14 + rnd() * 46; put(x, wy, Math.cos(a) * v, Math.sin(a) * v * 0.6 - 18, 20, 0.45 + rnd() * 0.4, c, 2 + rnd() * 2.4, 3); } }
    function dust(x, wy, n) { for (var i = 0; i < n; i++) put(x + (rnd() - 0.5) * 1.5, wy, (rnd() - 0.5) * 44, -8 - rnd() * 24, -10, 0.55 + rnd() * 0.4, "d", 3 + rnd() * 3.5, 1); }
    function turf(x, wy, n) { for (var i = 0; i < n; i++) put(x + (rnd() - 0.5), wy, (rnd() - 0.5) * 70, -26 - rnd() * 40, 150, 0.5 + rnd() * 0.3, i % 3 ? "#1d7a3f" : (TU && !TU.grass ? "#141414" : "#4a2f17"), 1.2 + rnd() * 1.4, 4); }
    function tapSpark(x, wy) { burst(x, wy, "#ffffff", 8); dust(x, wy, 4); put(x, wy, 0, 0, 0, 0.3, "#ffffff", 5, 2); }
    function catchFx(ti, x, wy, col) {
      var n = [0, 6, 12, 22, 38, 60, 90][ti];
      burst(x, wy, col, n); burst(x, wy, "#ffffff", n * 0.35 | 0); stars(x, wy, col, ti >= 5 ? 12 : ti >= 4 ? 8 : ti >= 2 ? 3 : 0);
      if (ti >= 2) put(x, wy, 0, 0, 0, 0.3, col, ti >= 5 ? 44 : 26, 5);
    }
    // screen-space celebration layer: gold confetti and fireworks (above the field, unaffected by camera zoom)
    function snew() { for (var i = 0; i < SP.length; i++) { SPi = (SPi + 1) % SP.length; if (!SP[SPi].on) return SP[SPi]; } return null; }
    function confetti(n) {
      for (var i = 0; i < n; i++) {
        var s = snew(); if (!s) return; var life = 2.2 + rnd() * 1.4;
        s.on = 1; s.kind = 1; s.x = rnd() * W; s.y = -12 - rnd() * 150; s.px = s.x; s.py = s.y; s.vx = (rnd() - 0.5) * 80; s.vy = 90 + rnd() * 140; s.g = 70; s.life = life; s.max = life; s.c = CONF[i % CONF.length]; s.r = 3 + rnd() * 3.5; s.rot = rnd() * TAU; s.vr = (rnd() - 0.5) * 14;
      }
    }
    function firework(fx, fy, col) {
      var x = W * fx, y = H * fy, n = 44;
      for (var i = 0; i < n; i++) {
        var s = snew(); if (!s) return; var a = i / n * TAU + rnd() * 0.2, v = 90 + rnd() * 150, life = 0.9 + rnd() * 0.7;
        s.on = 1; s.kind = 0; s.x = x; s.y = y; s.px = x; s.py = y; s.vx = Math.cos(a) * v; s.vy = Math.sin(a) * v; s.g = 110; s.life = life; s.max = life; s.c = i % 3 ? col : "#ffffff"; s.r = 1.6 + rnd(); s.rot = 0; s.vr = 0;
      }
      var f = snew(); if (f) { f.on = 1; f.kind = 2; f.x = x; f.y = y; f.px = x; f.py = y; f.vx = 0; f.vy = 0; f.g = 0; f.life = 0.35; f.max = 0.35; f.c = col; f.r = 60 * L.u; f.rot = 0; f.vr = 0; }
      flash(col, 0.1, 0.25);
    }
    function clearFx() { var i; for (i = 0; i < PP.length; i++) PP[i].on = 0; for (i = 0; i < SP.length; i++) SP[i].on = 0; for (i = 0; i < RG.length; i++) RG[i].on = 0; }

    // ---------------------------------------------------------------- baked layers (rebuilt on resize only)
    function mk(w, h) { var c = document.createElement("canvas"); c.width = Math.max(1, Math.round(w * dpr)); c.height = Math.max(1, Math.round(h * dpr)); var x = c.getContext("2d"); x.scale(dpr, dpr); return { c: c, x: x }; }
    function bake() {
      var u = L.u, i, j, x, y, r, c;
      // stands + crowd band: its bottom edge (the wall) is blitted at the projected far wall
      bandH = Math.round(H * 0.6); var B = mk(W, bandH), b = B.x, rr = rng(11);
      var sg = b.createLinearGradient(0, 0, 0, bandH); sg.addColorStop(0, "#04060d"); sg.addColorStop(0.6, "#0d1626"); sg.addColorStop(1, "#18243c"); b.fillStyle = sg; b.fillRect(0, 0, W, bandH);
      var rowH = 5.6 * u, wallH = 15 * u;
      for (r = 0, y = bandH - wallH - 4 * u; y > -4; r++, y -= rowH) {
        b.fillStyle = "rgba(0,0,0,0.28)"; b.fillRect(0, y + 3.2 * u, W, 1.2 * u);
        var step = (4.6 + (bandH - y) / bandH * 3.2) * u, ds = 1.8 * u + (bandH - y) / bandH * 1.7 * u;
        for (x = rr() * step; x < W; x += step * (0.85 + rr() * 0.4)) {
          var q = rr(); c = TU ? (q < 0.42 ? TU.crowd[0] : q < 0.6 ? TU.crowd[1] : q < 0.7 ? "120,130,150" : q < 0.8 ? TU.crowd[2] : q < 0.9 ? "255,205,140" : "235,240,255")
            : q < 0.3 ? "70,92,140" : q < 0.5 ? "120,130,150" : q < 0.66 ? "25,224,138" : q < 0.8 ? "255,205,140" : "235,240,255";
          b.fillStyle = "rgba(" + c + "," + (0.22 + rr() * 0.4).toFixed(2) + ")"; b.fillRect(x, y, ds, ds * 1.05);
          b.fillStyle = "rgba(255,226,196," + (0.25 + rr() * 0.3).toFixed(2) + ")"; b.fillRect(x + ds * 0.18, y - ds * 0.62, ds * 0.64, ds * 0.6);
        }
      }
      for (i = 1; i < 6; i++) { b.fillStyle = "rgba(0,0,0,0.3)"; b.fillRect(W * i / 6, 0, 1.4 * u, bandH - wallH); }             // aisle gaps
      var rg = b.createLinearGradient(0, 0, 0, bandH * 0.3); rg.addColorStop(0, "rgba(0,0,0,0.85)"); rg.addColorStop(1, "rgba(0,0,0,0)"); b.fillStyle = rg; b.fillRect(0, 0, W, bandH * 0.3);   // roof overhang
      if (TU && TU.dome) {                     // a closed roof: steel trusses and a ring of fixtures instead of a night sky
        var rh = bandH * 0.34, tg = b.createLinearGradient(0, 0, 0, rh); tg.addColorStop(0, "#0b0f18"); tg.addColorStop(1, "#1c2433"); b.fillStyle = tg; b.fillRect(0, 0, W, rh);
        b.strokeStyle = "rgba(160,175,200,0.22)"; b.lineWidth = 1.2 * u; b.beginPath();
        for (x = -W; x < 2 * W; x += 26 * u) { b.moveTo(x, 0); b.lineTo(x + 18 * u, rh); b.moveTo(x + 18 * u, 0); b.lineTo(x, rh); }
        b.moveTo(0, rh * 0.5); b.lineTo(W, rh * 0.5); b.stroke();
        b.fillStyle = "rgba(0,0,0,0.5)"; b.fillRect(0, rh - 2.5 * u, W, 2.5 * u);
        for (x = 9 * u; x < W; x += 18 * u) { b.fillStyle = "rgba(255,248,230,0.95)"; b.fillRect(x - 3 * u, rh - 5.5 * u, 6 * u, 2.4 * u); }
      }
      var n = 8, bw = W / n; b.font = "800 " + (8.4 * u).toFixed(1) + "px " + FONT; b.textAlign = "center"; b.textBaseline = "middle";
      for (j = 0; j < n; j++) {                                                                                                 // LED ad boards
        var lg = b.createLinearGradient(0, bandH - wallH, 0, bandH);
        if (TU) { lg.addColorStop(0, j % 2 ? TU.o.jersey : "#141a26"); lg.addColorStop(1, j % 2 ? mix(TU.o.jersey, "#000000", 0.4) : "#0b0f18"); }
        else { lg.addColorStop(0, j % 2 ? "#0fa868" : "#16233a"); lg.addColorStop(1, j % 2 ? "#0a6e46" : "#0b1424"); }
        b.fillStyle = lg; b.fillRect(j * bw, bandH - wallH, bw + 1, wallH);
        if (TU) { b.fillStyle = j % 2 ? TU.o.num : TU.accent; b.fillText(j % 4 === 1 ? TU.name : j % 4 === 3 ? TU.city : j % 4 === 0 ? "LINEUP LAB" : "DAILY DRIVE", j * bw + bw / 2, bandH - wallH / 2 + 0.5); }
        else { b.fillStyle = j % 2 ? "rgba(255,255,255,0.9)" : "rgba(25,224,138,0.9)"; b.fillText(j % 2 ? "LINEUP LAB" : "DAILY DRIVE", j * bw + bw / 2, bandH - wallH / 2 + 0.5); }
        b.fillStyle = "rgba(255,255,255,0.16)"; b.fillRect(j * bw, bandH - wallH, bw, 1.2 * u);
      }
      b.fillStyle = "rgba(0,0,0,0.5)"; b.fillRect(0, bandH - 2, W, 2); bandCv = B.c;
      // stadium lights: glow cores and soft beams, additive, screen space
      var Lq = mk(W, H), l = Lq.x; l.globalCompositeOperation = "lighter";
      if (TU && TU.dome) {                     // even indoor light: many soft fixtures, no light towers
        for (i = 0; i < 9; i++) {
          var dx = W * (0.06 + i * 0.11), dy = H * 0.03, dr = Math.min(W, H) * 0.28, dg = l.createRadialGradient(dx, dy, 0, dx, dy, dr);
          dg.addColorStop(0, "rgba(255,246,225,0.34)"); dg.addColorStop(0.3, "rgba(255,240,215,0.08)"); dg.addColorStop(1, "rgba(255,240,215,0)"); l.fillStyle = dg; l.fillRect(0, 0, W, H * 0.7);
        }
      } else
      [[0.08, 0.025], [0.92, 0.025], [0.3, 0.0], [0.7, 0.0]].forEach(function (p, ix) {
        var lx = W * p[0], ly = H * p[1], rd = Math.min(W, H) * (ix < 2 ? 0.5 : 0.32), g = l.createRadialGradient(lx, ly, 0, lx, ly, rd);
        g.addColorStop(0, "rgba(215,235,255," + (ix < 2 ? 0.6 : 0.34) + ")"); g.addColorStop(0.16, "rgba(150,200,255," + (ix < 2 ? 0.2 : 0.1) + ")"); g.addColorStop(1, "rgba(80,140,255,0)"); l.fillStyle = g; l.fillRect(0, 0, W, H * 0.75);
        var bg = l.createLinearGradient(lx, ly, W / 2, H * 0.8); bg.addColorStop(0, "rgba(200,225,255,0.13)"); bg.addColorStop(1, "rgba(200,225,255,0)"); l.fillStyle = bg;
        l.beginPath(); l.moveTo(lx - 7 * u, ly); l.lineTo(lx + 7 * u, ly); l.lineTo(W * (0.5 + (p[0] - 0.5) * 0.15 + 0.22), H * 0.85); l.lineTo(W * (0.5 + (p[0] - 0.5) * 0.15 - 0.22), H * 0.85); l.fill();
      });
      litCv = Lq.c;
      // soft pool of light and a flare sprite (white, tinted by use)
      var G = mk(128, 128), gx = G.x, gg = gx.createRadialGradient(64, 64, 0, 64, 64, 64); gg.addColorStop(0, "rgba(255,255,255,1)"); gg.addColorStop(0.25, "rgba(255,255,255,0.35)"); gg.addColorStop(1, "rgba(255,255,255,0)"); gx.fillStyle = gg; gx.fillRect(0, 0, 128, 128); glowCv = G.c;
      var Sn = mk(4, 4); Sn.x.fillStyle = "rgba(0,0,0,0.5)"; Sn.x.fillRect(0, 0, 4, 1); scanPat = ctx.createPattern(Sn.c, "repeat");
      vignette = ctx.createRadialGradient(W / 2, H * 0.5, Math.min(W, H) * 0.34, W / 2, H * 0.5, Math.max(W, H) * 0.8); vignette.addColorStop(0, "rgba(0,0,0,0)"); vignette.addColorStop(1, "rgba(0,0,0,0.66)");
      fogG = ctx.createLinearGradient(0, 0, 0, H * 0.5); fogG.addColorStop(0, "rgba(6,12,24,0.78)"); fogG.addColorStop(0.55, "rgba(8,18,34,0.3)"); fogG.addColorStop(1, "rgba(8,18,34,0)");
      sceneC = mk(W, H); SK[8] = 0;
    }

    // ---------------------------------------------------------------- the field
    function poly(pts) { ctx.beginPath(); ctx.moveTo(pts[0], pts[1]); for (var i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i], pts[i + 1]); ctx.closePath(); }
    function quad(y0, y1, x0, x1) {
      pj(x0, y0); var ax = PR.x, ay = PR.y; pj(x1, y0); var bx = PR.x, by = PR.y; pj(x1, y1); var cx = PR.x, cy = PR.y; pj(x0, y1);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.lineTo(cx, cy); ctx.lineTo(PR.x, PR.y); ctx.closePath();
    }
    function ftext(txt, x, wy, size, col, alpha, stroke) {
      pj(x, wy); var s = PR.s, px = PR.x, py = PR.y, sz = size * L.pxX * s;
      if (sz < 4 || py < -sz || py > H + sz) return;
      ctx.save(); ctx.translate(px, py); ctx.scale(1, 0.72);
      ctx.font = "800 italic " + sz.toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.globalAlpha = alpha;
      if (stroke) { ctx.lineWidth = sz * 0.07; ctx.strokeStyle = stroke; ctx.lineJoin = "round"; ctx.strokeText(txt, 0, 0); }
      ctx.fillStyle = col; ctx.fillText(txt, 0, 0); ctx.restore();
    }
    function wline(x0, y0, x1, y1) { pj(x0, y0); ctx.moveTo(PR.x, PR.y); pj(x1, y1); ctx.lineTo(PR.x, PR.y); }
    function drawBackdrop() {
      pj(0, 110.5); var wallY = PR.y;
      if (wallY > 0) {
        var top = wallY - bandH;
        if (top > 0) { ctx.fillStyle = "#04060d"; ctx.fillRect(-W, -H, 3 * W, top + H); }
        ctx.drawImage(bandCv, 0, top, W, bandH);
        if (S.zoom !== 1) { ctx.drawImage(bandCv, -W, top, W, bandH); ctx.drawImage(bandCv, W, top, W, bandH); }
        ctx.fillStyle = "rgba(0,0,0,0.3)"; ctx.fillRect(-W, wallY, 3 * W, 3);
      }
    }
    function endZone(y0, y1, base, band) {
      quad(y0, y1, -XS, XS); ctx.fillStyle = base; ctx.fill();
      ctx.save(); quad(y0, y1, -XS, XS); ctx.clip(); ctx.strokeStyle = band; ctx.globalAlpha = 0.2; ctx.lineCap = "butt";
      pj(0, (y0 + y1) / 2); ctx.lineWidth = 3 * L.pxX * PR.s;
      ctx.beginPath(); for (var i = -6; i <= 13; i++) wline(-XS + i * 5.2, y0, -XS + i * 5.2 + 8, y1); ctx.stroke();
      ctx.restore();
    }
    function post(wy) {
      pj(0, wy); var k = ksz(PR.s), x = PR.x, y = PR.y;
      ctx.strokeStyle = "#ffd23a"; ctx.lineCap = "round"; ctx.lineWidth = 1.7 * k;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y - 17 * k); ctx.moveTo(x - 11 * k, y - 22 * k); ctx.lineTo(x + 11 * k, y - 22 * k); ctx.moveTo(x - 11 * k, y - 22 * k); ctx.lineTo(x - 11 * k, y - 50 * k); ctx.moveTo(x + 11 * k, y - 22 * k); ctx.lineTo(x + 11 * k, y - 50 * k); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x, y - 17 * k); ctx.lineTo(x, y - 22 * k); ctx.stroke();
    }
    function drawEmblem() {          // the Lineup Lab logo (football + rising bars + arrow), softly painted at midfield; never team colors
      pj(0, 50); var cx = PR.x, s = PR.s; if (PR.y < -80 || PR.y > H + 80) return;
      pj(0, 44); var y0 = PR.y; pj(0, 56); var y1 = PR.y, rx = 9 * L.pxX * s, ry = Math.abs(y0 - y1) / 2, i;
      ctx.save(); ctx.translate(cx, (y0 + y1) / 2); ctx.scale(rx / 50, ry / 50); ctx.rotate(-0.16); ctx.lineJoin = "round"; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(-47, 0); ctx.quadraticCurveTo(0, -44, 47, 0); ctx.quadraticCurveTo(0, 44, -47, 0); ctx.closePath();
      ctx.globalAlpha = 0.12; ctx.fillStyle = "#04120d"; ctx.fill();
      ctx.globalAlpha = 0.5; ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 3.4; ctx.stroke();
      ctx.lineWidth = 2.6; ctx.beginPath(); ctx.moveTo(-34, -10); ctx.quadraticCurveTo(-30, 0, -34, 10); ctx.moveTo(34, -10); ctx.quadraticCurveTo(30, 0, 34, 10);   // tip stripes
      ctx.moveTo(-12, -15); ctx.lineTo(12, -15); for (i = -9; i <= 9; i += 6) { ctx.moveTo(i, -18.5); ctx.lineTo(i, -11.5); } ctx.stroke();                // laces
      ctx.globalAlpha = 0.45; ctx.fillStyle = ACCENT; ctx.fillRect(-17, 6, 7, 9); ctx.fillRect(-7, 0, 7, 15); ctx.fillRect(3, -6, 7, 21);                     // rising bars
      ctx.strokeStyle = ACCENT; ctx.lineWidth = 2.6; ctx.beginPath(); ctx.moveTo(-20, 3); ctx.lineTo(-8, -4); ctx.lineTo(1, -1); ctx.lineTo(17, -12); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(19.5, -13.8); ctx.lineTo(11, -13.4); ctx.lineTo(16.6, -6.6); ctx.closePath(); ctx.fillStyle = ACCENT; ctx.fill();              // arrowhead
      ctx.restore();
    }
    function drawBench(sd) {        // the team areas: the home bench on the left, the visitors (road whites) on the right
      var u = sd < 0 ? TU.o : TU.d, nums = sd < 0 ? TU.benchH : TU.benchA, Y, i, k, bx, by, idx = 0, coach, row, x0 = sd * (XS + 1.4), x1 = sd * (XS + 8.5);
      ctx.save(); ctx.globalAlpha = sd < 0 ? 0.42 : 0.3; quad(18, 82, Math.min(x0, x1), Math.max(x0, x1)); ctx.fillStyle = sd < 0 ? u.jersey : u.trim; ctx.fill();   // the painted team area
      ctx.globalAlpha = 0.85; ctx.strokeStyle = "#f3d34a"; ctx.lineWidth = 1.4 * L.u; ctx.beginPath(); wline(x0, 18, x0, 82); ctx.stroke();
      ctx.globalAlpha = 0.9; quad(24, 76, Math.min(sd * (XS + 7.2), sd * (XS + 8.2)), Math.max(sd * (XS + 7.2), sd * (XS + 8.2))); ctx.fillStyle = "#0d121c"; ctx.fill(); ctx.restore();   // the bench
      for (row = 1; row >= 0; row--)
      for (Y = 82 - row * 1.3; Y >= 18; Y -= 2.6) {
        idx++; coach = row === 0 && idx % 5 === 0;
        pj(sd * (XS + 3.0 + row * 2.6 + ((idx * 7) % 3) * 0.45), Y); if (PR.y < -40 || PR.y > H + 40) continue;
        k = ksz(PR.s) * 0.9; bx = PR.x; by = PR.y;
        ctx.fillStyle = "rgba(0,0,0,0.32)"; ctx.fillRect(bx - 4 * k, by - 0.5 * k, 8 * k, 1.5 * k);
        ctx.fillStyle = coach ? "#1b2130" : u.pants; ctx.fillRect(bx - 2.6 * k, by - 5.6 * k, 2.2 * k, 5.4 * k); ctx.fillRect(bx + 0.4 * k, by - 5.6 * k, 2.2 * k, 5.4 * k);
        ctx.fillStyle = coach ? u.polo : u.jersey; ctx.fillRect(bx - 3.4 * k, by - 12.6 * k, 6.8 * k, 7.4 * k);
        if (!coach) { ctx.fillStyle = u.trim; ctx.fillRect(bx - 3.4 * k, by - 12.6 * k, 6.8 * k, 0.9 * k); }
        ctx.fillStyle = SKINS[idx % SKINS.length]; ctx.fillRect(bx - 2.3 * k, by - 16.9 * k, 4.6 * k, 4.6 * k);
        if (coach) { ctx.strokeStyle = "#e9edf5"; ctx.lineWidth = 0.7 * k; ctx.beginPath(); ctx.arc(bx, by - 14.6 * k, 2.6 * k, PI * 1.05, PI * 1.95); ctx.stroke(); }
        else if (nums.length && 4.8 * k >= 5) {
          ctx.font = "800 " + (4.8 * k).toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillStyle = u.num; ctx.fillText(String(nums[(idx * 7) % nums.length]), bx, by - 8.9 * k);
        }
      }
      for (Y = -6; Y < 108; Y += 7.5) {            // staff and photographers outside the team areas
        if (Y > 12 && Y < 88) continue;
        pj(sd * (XS + 4 + ((Y * 7) & 3) * 0.6), Y); if (PR.y < -40 || PR.y > H + 40) continue;
        k = ksz(PR.s) * 0.7; bx = PR.x; by = PR.y; ctx.fillStyle = "#2a3346"; ctx.fillRect(bx - 3 * k, by - 12 * k, 6 * k, 11.5 * k);
        ctx.fillStyle = "#d8b08a"; ctx.fillRect(bx - 2.3 * k, by - 16.5 * k, 4.6 * k, 4.6 * k);
      }
    }
    function drawScene() {
      var Y, i, XA = XS + 26;
      ctx.fillStyle = "#04120d"; ctx.fillRect(-W, -H, 3 * W, 3 * H);
      drawBackdrop();
      ctx.drawImage(litCv, 0, 0, W, H);
      // out-of-bounds apron, then the mowed turf (alternating 5-yard stripes + fine mow lines) and the painted end zones
      quad(-44, 125, -XA, XA); ctx.fillStyle = "#082519"; ctx.fill();
      for (Y = -10; Y < 110; Y += 5) {
        if (Y < 0 || Y >= 100) continue;
        quad(Y, Y + 5, -XS, XS); ctx.fillStyle = ((Y / 5) & 1) ? (TU ? TU.turf[0] : "#0f6139") : (TU ? TU.turf[1] : "#0b5130"); ctx.fill();
      }
      ctx.lineCap = "butt"; ctx.strokeStyle = "rgba(255,255,255," + (TU && !TU.grass ? 0.02 : 0.05) + ")"; ctx.lineWidth = 2.6 * L.u; ctx.beginPath();
      for (i = -XS + 1.1; i < XS; i += 2.2) wline(i, 0, i, 100);
      ctx.stroke();
      if (TU) { endZone(-10, 0, TU.ez, TU.ezBand); endZone(100, 110, TU.ez, TU.ezBand); }
      else { endZone(-10, 0, "#0a3d4c", "#19e08a"); endZone(100, 110, "#5a4511", "#ffcf6b"); }
      // light pools (world anchored)
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      var pools = [[-10, S.los + 10, 34, 0.1], [11, S.los + 26, 38, 0.08], [0, S.los + 52, 46, 0.06]];
      for (i = 0; i < 3; i++) { pj(pools[i][0], pools[i][1]); var rr = L.pxX * pools[i][2] * PR.s; ctx.globalAlpha = pools[i][3]; ctx.drawImage(glowCv, PR.x - rr, PR.y - rr * 0.55, rr * 2, rr * 1.1); }
      ctx.restore();
      // paint: yard lines, hashes, numbers, wordmarks
      ctx.strokeStyle = "rgba(255,255,255,0.8)";
      for (Y = 0; Y <= 100; Y += 5) {
        pj(-XS, Y); var lx = PR.x, ly = PR.y, sc = PR.s; pj(XS, Y);
        ctx.lineWidth = (Y === 0 || Y === 100 ? 3.4 : Y % 10 === 0 ? 2.2 : 1.3) * Math.pow(sc, 0.8) * L.u; ctx.globalAlpha = Y === 0 || Y === 100 ? 0.95 : 0.65;
        ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(PR.x, PR.y); ctx.stroke();
      }
      ctx.globalAlpha = 0.5; ctx.lineWidth = 1.1 * L.u; ctx.beginPath();
      for (Y = 1; Y < 100; Y++) { if (Y % 5 === 0) continue; wline(-3.65, Y, -2.55, Y); wline(2.55, Y, 3.65, Y); wline(-XS + 0.85, Y, -XS + 1.95, Y); wline(XS - 1.95, Y, XS - 0.85, Y); }
      ctx.stroke(); ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.92)"; ctx.lineWidth = 3 * L.u; ctx.beginPath();
      wline(-XS, -10, -XS, 110); wline(XS, -10, XS, 110); ctx.stroke();
      ctx.lineWidth = 2.4 * L.u; ctx.beginPath(); wline(-XS, 110, XS, 110); wline(-XS, -10, XS, -10); ctx.stroke();
      for (Y = 10; Y <= 90; Y += 10) { var num = String(Y <= 50 ? Y : 100 - Y); ftext(num, -XS + 11.5, Y, 3.4, "#ffffff", 0.55); ftext(num, XS - 11.5, Y, 3.4, "#ffffff", 0.55); }
      if (TU) {         // painted end zones (city in one, nickname in the other) and the midfield emblem
        ftext(TU.city, 0, -5, TU.citySz, TU.ezText, 0.92, TU.ezStroke); ftext("THE DAILY DRIVE", 0, -8.9, 2.1, TU.ezText, 0.6);
        ftext(TU.name, 0, 105, TU.nameSz, TU.ezText, 0.92, TU.ezStroke); if (TU.stadium) ftext(TU.stadium, 0, 108.6, 1.9, TU.ezText, 0.6);
      } else {
        ftext("LINEUP LAB", 0, -5, 6.6, "#ffffff", 0.62, "rgba(0,40,30,0.7)"); ftext("THE DAILY DRIVE", 0, -8.9, 2.1, "#19e08a", 0.7);
        ftext("LINEUP LAB", 0, 105, 6.6, "#ffe9a8", 0.7, "rgba(60,30,0,0.7)"); ftext("THE DAILY DRIVE", 0, 108.6, 2.1, "#ffffff", 0.55);
      }
      drawEmblem();
      // sideline area: LED boards and the people standing on the apron
      var sd, bx, by, k;
      for (sd = -1; sd <= 1; sd += 2) {
        pj(sd * (XS + 9), -22); var nx = PR.x, ny = PR.y, ns = PR.s; pj(sd * (XS + 9), 118); var fx = PR.x, fy = PR.y, fs = PR.s, nh = 15 * L.u * Math.pow(ns, 0.7), fh = 15 * L.u * Math.pow(fs, 0.7);
        poly([nx, ny, fx, fy, fx, fy - fh, nx, ny - nh]); ctx.fillStyle = "#0a1424"; ctx.fill();
        ctx.strokeStyle = TU ? (sd < 0 ? TU.rail : TU.railAway) : "rgba(25,224,138,0.9)"; ctx.lineWidth = 2 * L.u; ctx.beginPath(); ctx.moveTo(nx, ny - nh); ctx.lineTo(fx, fy - fh); ctx.stroke();
        ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.lineWidth = 1; ctx.beginPath();
        for (Y = -20; Y < 118; Y += 6) { pj(sd * (XS + 9), Y); ctx.moveTo(PR.x, PR.y); ctx.lineTo(PR.x, PR.y - 15 * L.u * Math.pow(PR.s, 0.7)); }
        ctx.stroke();
        if (TU) { drawBench(sd); continue; }
        for (Y = -6; Y < 108; Y += 3.4) {
          pj(sd * (XS + 3.4 + ((Y * 7) & 3) * 0.6), Y); if (PR.y < -40 || PR.y > H + 40) continue;
          k = ksz(PR.s) * 0.72; bx = PR.x; by = PR.y; ctx.fillStyle = "rgba(0,0,0,0.3)"; ctx.fillRect(bx - 4 * k, by - 0.5 * k, 8 * k, 1.5 * k);
          ctx.fillStyle = ((Y * 3) & 3) ? "#223049" : "#19e08a"; ctx.fillRect(bx - 3 * k, by - 12 * k, 6 * k, 11.5 * k); ctx.fillStyle = "#d8b08a"; ctx.fillRect(bx - 2.3 * k, by - 16.5 * k, 4.6 * k, 4.6 * k);
        }
      }
      post(110);
      [[-XS, 0], [XS, 0], [-XS, 100], [XS, 100], [-XS, 110], [XS, 110], [-XS, -10], [XS, -10]].forEach(function (c) { pj(c[0], c[1]); var kk = ksz(PR.s); ctx.fillStyle = "#ff8a1f"; ctx.fillRect(PR.x - 2.5 * kk, PR.y - 9 * kk, 5 * kk, 9 * kk); ctx.fillStyle = "#fff"; ctx.fillRect(PR.x - 2.5 * kk, PR.y - 6 * kk, 5 * kk, 1.6 * kk); });
      // depth fog toward the far end
      ctx.fillStyle = fogG; ctx.fillRect(-W, -H, 3 * W, H * 1.5);
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

    // ---------------------------------------------------------------- players: helmet + facemask, pads, jersey, pants, legs, with run cycle and poses
    var HDS = [0, 0, 0, 0];
    function kfs(a, q, out) {            // piecewise smooth keyframes [[q, x, y], ...]
      var n = a.length, i = 0; if (q <= a[0][0]) { out[0] = a[0][1]; out[1] = a[0][2]; return; }
      while (i < n - 1 && q > a[i + 1][0]) i++;
      if (i >= n - 1) { out[0] = a[n - 1][1]; out[1] = a[n - 1][2]; return; }
      var u = sstep((q - a[i][0]) / (a[i + 1][0] - a[i][0])); out[0] = lerp(a[i][1], a[i + 1][1], u); out[1] = lerp(a[i][2], a[i + 1][2], u);
    }
    var THR = [[0, 2.8, -14.2], [0.35, 7.4, -30.5], [0.47, 3.4, -38.5], [1.0, -2.5, -13], [1.4, 8.2, -10.8]], THL = [[0, -2.6, -14], [0.35, -8.4, -25], [0.6, -6.5, -17], [1.1, -8.2, -10.8]], KO = [0, 0];
    function hands(e) {
      var s = e.run ? Math.sin(e.phase) * e.amp : 0, a = e.arms, q = e.aq, w;
      var lx = -8.2, ly = -10.8 - s * 3.8, rx = 8.2, ry = -10.8 + s * 3.8;
      if (a === "block") { w = clamp(q, 0, 1); lx = lerp(lx, -4.6, w); ly = lerp(ly, -15.2 + s, w); rx = lerp(rx, 4.6, w); ry = lerp(ry, -15.2 - s, w); }
      else if (a === "set") { lx = -5.6; ly = -7; rx = 5.6; ry = -7; }
      else if (a === "hold") { lx = -2.6; ly = -14; rx = 2.8; ry = -14.2; }
      else if (a === "throw") { kfs(THR, q, KO); rx = KO[0]; ry = KO[1]; kfs(THL, q, KO); lx = KO[0]; ly = KO[1]; }
      else if (a === "carry") { rx = 4.8; ry = -12.6; lx = -8; ly = -11.5 - s * 3; }
      else if (a === "catch") {
        w = clamp(q, 0, 1); var bl = e.cq ? -8 : lx, bly = e.cq ? -11.5 - s * 3 : ly, brx = e.cq ? 4.8 : rx, bry = e.cq ? -12.6 : ry, hy = lerp(-12, -36, e.lvl);
        lx = lerp(bl, -3.4, w); ly = lerp(bly, hy, w); rx = lerp(brx, 3.4, w); ry = lerp(bry, hy, w);
      }
      else if (a === "one") { w = clamp(q, 0, 1); rx = lerp(rx, 6.4, w); ry = lerp(ry, -38.5, w); lx = lerp(lx, -10.4, w); ly = lerp(ly, -17, w); }
      else if (a === "up") { w = clamp(q, 0, 1); lx = lerp(lx, -9.6, w); ly = lerp(ly, -33, w); rx = lerp(rx, 9.6, w); ry = lerp(ry, -33, w); }
      else if (a === "wrap") { w = clamp(q, 0, 1); lx = lerp(lx, -3.6, w); ly = lerp(ly, -26, w); rx = lerp(rx, 3.6, w); ry = lerp(ry, -26, w); }
      HDS[0] = lx; HDS[1] = ly; HDS[2] = rx; HDS[3] = ry;
    }
    function limb(sx0, sy0, hx, hy, side, k, sleeve, skin, glove, wb) {
      var ex = (sx0 + hx) / 2 + side * 1.7 * k, ey = (sy0 + hy) / 2 + 1.3 * k;
      ctx.lineCap = "square"; ctx.lineJoin = "miter"; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 5 * k; ctx.beginPath(); ctx.moveTo(sx0, sy0); ctx.lineTo(ex, ey); ctx.lineTo(hx, hy); ctx.stroke();
      ctx.lineCap = "butt"; ctx.strokeStyle = skin; ctx.lineWidth = 3.7 * k; ctx.beginPath(); ctx.moveTo(sx0, sy0); ctx.lineTo(ex, ey); ctx.lineTo(hx, hy); ctx.stroke();   // bare arms
      ctx.strokeStyle = sleeve; ctx.lineWidth = 4.6 * k; ctx.beginPath(); ctx.moveTo(sx0, sy0); ctx.lineTo(lerp(sx0, ex, 0.45), lerp(sy0, ey, 0.45)); ctx.stroke();          // short sleeve
      ctx.fillStyle = "rgba(0,0,0,0.55)"; ctx.fillRect(hx - 2.5 * k, hy - 2.5 * k, 5 * k, 5 * k); ctx.fillStyle = glove; ctx.fillRect(hx - 1.9 * k, hy - 1.9 * k, 3.8 * k, 3.8 * k);
    }
    function leg(sd, lift, spread, hipY, k, wb, pants, sock, front) {
      var hx = sd * 2.4 * wb * k, fx = sd * (2.5 + spread) * wb * k, fy = (-0.7 - lift) * k, hyy = hipY * k;
      var kx = (hx + fx) / 2 + sd * (0.9 + lift * 0.14 + spread * 0.5) * k, ky = (hyy + fy) / 2 - lift * 0.1 * k;
      ctx.lineCap = "square"; ctx.lineJoin = "miter"; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 5.2 * wb * k; ctx.beginPath(); ctx.moveTo(hx, hyy); ctx.lineTo(kx, ky); ctx.lineTo(fx, fy); ctx.stroke();
      ctx.lineCap = "butt"; ctx.strokeStyle = sock; ctx.lineWidth = 3.8 * k; ctx.beginPath(); ctx.moveTo(kx, ky); ctx.lineTo(fx, fy); ctx.stroke();
      ctx.strokeStyle = pants; ctx.lineWidth = 4.9 * wb * k; ctx.beginPath(); ctx.moveTo(hx, hyy); ctx.lineTo(kx, ky + 0.8 * k); ctx.stroke();
      var bw0 = (front ? 5.4 : 4.6) * k; ctx.fillStyle = "#12151e"; ctx.fillRect(fx + sd * 0.3 * k - bw0 / 2, fy - 1 * k, bw0, 2.4 * k);   // block cleat
    }
    function drawSprite(e, sx, sy, k) {
      var off = e.team === "o", qb = e.k === "qb", back = e.back, ty0 = e.t;
      if (qb) k *= 1.14; else if (ty0 === "wr" || ty0 === "rb" || ty0 === "te") k *= 1.06; else if (ty0 === "ol" || ty0 === "dl") k *= 1.04;
      var wb = ty0 === "ol" || ty0 === "dl" ? 1.1 : ty0 === "lb" ? 1.1 : ty0 === "wr" || ty0 === "cb" ? 0.94 : 1;
      var jersey = off ? "#16d27f" : "#eef2f9", trim = off ? "#0a7d4c" : "#9ba7c0", pants = off ? "#eef2f8" : "#303b56", sock = off ? "#16d27f" : "#cfd7e8", num = off ? "#ffffff" : "#16203a", skin = e.skin, glove = off ? "#ffffff" : "#d8e0f0";
      var nstroke = off ? "rgba(0,50,25,0.9)" : "rgba(255,255,255,0.9)", stripe = off ? "#ffffff" : "#33426a";
      if (TU) { var u = off ? TU.o : TU.d; jersey = u.jersey; trim = u.trim; pants = u.pants; sock = u.sock; num = u.num; glove = u.glove; nstroke = u.nstroke; stripe = u.stripe; }
      var ph = e.phase, sw = e.run ? Math.sin(ph) * e.amp : 0, bob = e.run ? -Math.abs(Math.sin(ph)) * 1.1 * k * e.amp : 0, cr = e.cr * 2.6, hipY = -10 + cr;
      // ground shadow
      if (!PIX) { ctx.fillStyle = "rgba(0,0,0,0.4)"; var shs = 1 - Math.min(0.5, e.z / 36); ctx.fillRect(sx - 7.6 * k * wb * shs, sy - 1.6 * k * shs, 15.2 * k * wb * shs, 3.6 * k * shs); }
      ctx.save(); ctx.translate(sx, sy - e.z * k); if (e.rot) ctx.rotate(e.rot); if (e.sxs !== 1 || e.sys !== 1) ctx.scale(e.sxs, e.sys);
      // legs (run cycle: alternating lift, knee drive) + stance spread
      var lL = Math.max(0, sw) * 3.6 + e.tapL * 3, lR = Math.max(0, -sw) * 3.6 + e.tapR * 3, spr = e.cr * 1.9;
      leg(-1, lL, spr, hipY, k, wb, pants, sock, !back); leg(1, lR, spr, hipY, k, wb, pants, sock, !back);
      ctx.translate(0, bob + cr * k); if (e.run) ctx.rotate(Math.sin(ph) * 0.045 * e.amp);
      // arms + gloves (poses: swing, block, hold, throw, catch, carry, wrap, celebrate); from behind they sit behind the torso so the back number shows
      hands(e);
      var ax = 7 * wb * k, ay = -17.9 * k;
      if (back) { limb(-ax, ay, HDS[0] * k, HDS[1] * k, -1, k, jersey, skin, glove, wb); limb(ax, ay, HDS[2] * k, HDS[3] * k, 1, k, jersey, skin, glove, wb); }
      // hips + torso (shoulder pads wider than the waist)
      ctx.fillStyle = pants; ctx.fillRect(-5.8 * wb * k, -11.6 * k, 11.6 * wb * k, 3.4 * k);
      ctx.fillStyle = jersey; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 1.1 * k; ctx.lineJoin = "miter"; ctx.beginPath();
      ctx.rect(-6.8 * wb * k, -19.6 * k, 13.6 * wb * k, 8.8 * k); ctx.fill(); ctx.stroke();                     // boxy torso
      ctx.fillStyle = "rgba(0,0,0,0.16)"; ctx.fillRect(2.2 * wb * k, -18 * k, 3.4 * wb * k, 7.2 * k);
      ctx.fillStyle = trim; ctx.fillRect(-5.6 * wb * k, -11.6 * k, 11.2 * wb * k, 1.1 * k);
      var label = String(e.n), nsz = (qb ? 9.8 : ty0 === "ol" || ty0 === "dl" ? 7.2 : 8) * k, ny = -14.4 * k;
      if (PIX) pixNum(label, 0, ny, num, nstroke);
      else { ctx.font = "800 " + nsz.toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.lineJoin = "round"; ctx.lineWidth = 1.8 * k; ctx.strokeStyle = nstroke; ctx.strokeText(label, 0, ny); ctx.fillStyle = num; ctx.fillText(label, 0, ny); }
      if (!back) { limb(-ax, ay, HDS[0] * k, HDS[1] * k, -1, k, jersey, skin, glove, wb); limb(ax, ay, HDS[2] * k, HDS[3] * k, 1, k, jersey, skin, glove, wb); }
      // hand position on screen (the ball is pinned to it)
      var hxl = HDS[2] * k * e.sxs, hyl = HDS[3] * k * e.sys + (bob + cr * k) * e.sys, cs = e.rot ? Math.cos(e.rot) : 1, sn = e.rot ? Math.sin(e.rot) : 0;
      e.hsx = sx + hxl * cs - hyl * sn; e.hsy = sy - e.z * k + hxl * sn + hyl * cs;
      // shoulder pads
      ctx.fillStyle = jersey; ctx.strokeStyle = "rgba(0,0,0,0.5)"; ctx.lineWidth = 1 * k;
      ctx.fillRect(-ax - 3.8 * k, ay - 2.6 * k, 7.6 * k, 5.4 * k); ctx.strokeRect(-ax - 3.8 * k, ay - 2.6 * k, 7.6 * k, 5.4 * k);   // square shoulder pads
      ctx.fillRect(ax - 3.8 * k, ay - 2.6 * k, 7.6 * k, 5.4 * k); ctx.strokeRect(ax - 3.8 * k, ay - 2.6 * k, 7.6 * k, 5.4 * k);
      ctx.fillStyle = "rgba(255,255,255,0.28)"; ctx.fillRect(-ax - 3 * k, ay - 1.9 * k, 5 * k, 1.2 * k); ctx.fillRect(ax - 3 * k, ay - 1.9 * k, 5 * k, 1.2 * k);
      // neck roll + helmet (a squared-off shell with highlight, stripe, facemask when facing us)
      ctx.fillStyle = skin; ctx.fillRect(-2.5 * k, -22.6 * k, 5 * k, 3.2 * k);                                     // neck
      ctx.fillStyle = "#171b27"; ctx.fillRect(-3.6 * k, -20.4 * k, 7.2 * k, 1.2 * k);                                // collar
      var hy = -26.2 * k, hr = 5.8 * k;
      ctx.save(); ctx.translate(0, hy); ctx.scale(hr, hr * 0.97); ctx.fillStyle = off ? HG[0] : HG[1]; roundRect(-1, -1, 2, 2, 0.3); ctx.fill(); ctx.restore();
      ctx.strokeStyle = "rgba(0,0,0,0.6)"; ctx.lineWidth = 1.1 * k; roundRect(-hr, hy - hr * 0.97, 2 * hr, 1.94 * hr, hr * 0.3); ctx.stroke();
      if (back) {
        if (stripe) { ctx.fillStyle = stripe; ctx.fillRect(-0.9 * k, hy - hr * 0.97, 1.8 * k, hr * 1.45); }
        ctx.fillStyle = "#6c7690"; ctx.fillRect(-hr * 0.93 - 0.9 * k, hy - 0.4 * k, 1.8 * k, 1.8 * k); ctx.fillRect(hr * 0.93 - 0.9 * k, hy - 0.4 * k, 1.8 * k, 1.8 * k);
      } else {
        if (stripe) { ctx.fillStyle = stripe; ctx.fillRect(-0.9 * k, hy - hr * 0.97, 1.8 * k, hr * 0.55); }
        ctx.fillStyle = skin; ctx.fillRect(-hr * 0.74, hy - 2.4 * k, hr * 1.48, hr * 1.2);                              // a real face
        ctx.fillStyle = "#ffffff"; ctx.fillRect(-2.9 * k, hy - 1.1 * k, 2 * k, 1.6 * k); ctx.fillRect(0.9 * k, hy - 1.1 * k, 2 * k, 1.6 * k);   // eyes
        ctx.fillStyle = "#12151e"; ctx.fillRect(-2.1 * k, hy - 0.9 * k, 1.1 * k, 1.3 * k); ctx.fillRect(1.6 * k, hy - 0.9 * k, 1.1 * k, 1.3 * k);
        ctx.fillRect(-3 * k, hy - 2.1 * k, 2.1 * k, 0.6 * k); ctx.fillRect(0.9 * k, hy - 2.1 * k, 2.1 * k, 0.6 * k);                         // brows
        ctx.fillStyle = "#5a2a22"; ctx.fillRect(-1.5 * k, hy + 1.8 * k, 3 * k, 0.8 * k); ctx.fillRect(-2.1 * k, hy + 1.3 * k, 0.7 * k, 0.7 * k); ctx.fillRect(1.4 * k, hy + 1.3 * k, 0.7 * k, 0.7 * k);   // grin
        ctx.strokeStyle = off ? "#dfe7f5" : "#7b88a6"; ctx.lineWidth = 0.85 * k; ctx.beginPath();                    // light cage: just the chin bar
        ctx.moveTo(-hr * 0.8, hy + 1 * k); ctx.lineTo(-hr * 0.72, hy + 4.1 * k); ctx.lineTo(hr * 0.72, hy + 4.1 * k); ctx.lineTo(hr * 0.8, hy + 1 * k); ctx.stroke();
      }
      ctx.fillStyle = "rgba(255,255,255,0.42)"; ctx.fillRect(-hr * 0.7, hy - hr * 0.78, hr * 0.62, hr * 0.26);
      ctx.restore();
    }
    // ---------------------------------------------------------------- the ball: spiral roll, orientation along its path, speed streak, tier trail
    function drawBallSprite(sx, sy, k, ang, spin) {
      var cs = Math.cos(spin), sn = Math.sin(spin);
      ctx.save(); ctx.translate(sx, sy); ctx.rotate(ang); ctx.fillStyle = "#9a5528"; ctx.strokeStyle = "#2a1206"; ctx.lineWidth = 0.9 * k;
      ctx.beginPath(); ctx.ellipse(0, 0, 4.9 * k, 3 * k * (0.78 + 0.22 * Math.abs(cs)), 0, 0, TAU); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "rgba(255,255,255,0.85)"; ctx.fillRect(-3.4 * k, -2.2 * k * Math.abs(cs) - 0.2 * k, 0.8 * k, 4.4 * k * Math.abs(cs) + 0.4 * k); ctx.fillRect(2.6 * k, -2.2 * k * Math.abs(cs) - 0.2 * k, 0.8 * k, 4.4 * k * Math.abs(cs) + 0.4 * k);
      ctx.strokeStyle = cs > -0.1 ? "#fff" : "rgba(255,255,255,0.2)"; ctx.lineWidth = 0.8 * k; var ly = sn * 1.9 * k; ctx.beginPath(); ctx.moveTo(-1.7 * k, ly); ctx.lineTo(1.7 * k, ly);
      for (var i = -1; i <= 1; i++) { ctx.moveTo(i * 1.1 * k, ly - 0.9 * k); ctx.lineTo(i * 1.1 * k, ly + 0.9 * k); } ctx.stroke();
      ctx.restore();
    }
    function drawTrail() {
      var tr = S.trail, P0 = P; if (!tr.length || !P0 || P0.trail === "none") return;
      var kind = P0.trail, col = P0.color, n = tr.length, i, a, b, age, x0, y0, x1, y1, al, wd;
      ctx.save(); ctx.lineCap = "round"; ctx.lineJoin = "round";
      if (kind !== "thin") ctx.globalCompositeOperation = "lighter";
      for (i = 1; i < n; i++) {
        a = tr[i - 1]; b = tr[i]; age = S.time - b.t; if (age > 0.6) continue;
        pj(a.x, a.y); x0 = PR.x; y0 = PR.y - a.h * ksz(PR.s); pj(b.x, b.y); x1 = PR.x; y1 = PR.y - b.h * ksz(PR.s); al = (1 - age / 0.6) * (i / n); wd = L.u * Math.pow(PR.s, 0.5) * (0.4 + 0.6 * i / n);
        if (kind === "glow" || kind === "rainbow") {
          ctx.strokeStyle = kind === "rainbow" ? RB[(i + (S.time * 24 | 0)) % RB.length] : col; ctx.globalAlpha = Math.min(1, al * 0.95); ctx.lineWidth = 13 * wd; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
          ctx.globalAlpha = al * 0.9; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.4 * wd; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
        } else { ctx.strokeStyle = "#fff"; ctx.globalAlpha = al * 0.85; ctx.lineWidth = 1.7 * L.u; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); }
      }
      ctx.restore();
    }
    function drawBall(owner) {
      var g = S.ballG; pj(g.x, g.y); var k = ksz(PR.s), sx = PR.x, sy = PR.y, fl = !owner, hh, bx, by;
      if (fl) { ctx.fillStyle = "rgba(0,0,0," + (0.42 - Math.min(0.25, g.h / 500)).toFixed(2) + ")"; ctx.beginPath(); ctx.ellipse(sx, sy, 5 * k * (1 + g.h / 260), 1.9 * k * (1 + g.h / 400), 0, 0, TAU); ctx.fill(); }
      hh = (owner ? g.h + owner.z : g.h) * k * (owner ? (owner.k === "qb" ? 1.14 : 1.06) : 1);
      bx = sx; by = sy - hh;
      if (owner) { bx = owner.hsx + 0.5 * k; by = owner.hsy - 0.4 * k; if (g.held === "qb" && P && !P.sack) { bx = owner.hsx; by = owner.hsy - 0.6 * k; } }
      else {
        if (g.pinS > 0 && EK.qb.hsx != null) { bx = lerp(bx, EK.qb.hsx, g.pinS); by = lerp(by, EK.qb.hsy, g.pinS); }
        if (g.pinE > 0 && P && EK[P.rk].hsx != null) { var rc = EK[P.rk]; bx = lerp(bx, rc.hsx, g.pinE); by = lerp(by, rc.hsy, g.pinE); }
      }
      // orientation and streak follow the ball's own screen-space velocity
      var dx = bx - BP.x, dy = by - BP.y, dtv = Math.max(0.001, S.time - BP.t);
      if (BP.t > 0 && dtv < 0.2) { BP.vx = lerp(BP.vx, dx / dtv, 0.5); BP.vy = lerp(BP.vy, dy / dtv, 0.5); } else { BP.vx = 0; BP.vy = 0; }
      BP.x = bx; BP.y = by; BP.t = S.time;
      var sp = Math.hypot(BP.vx, BP.vy), ang = fl && sp > 30 ? Math.atan2(BP.vy, BP.vx) : (owner ? -0.5 : 1.0);
      if (fl && sp > 60 && P && P.trail !== "none" && !owner) {
        var ln0 = Math.min(46 * L.u, sp * 0.045), ux = BP.vx / sp, uy = BP.vy / sp;
        ctx.save(); ctx.lineCap = "round"; ctx.globalCompositeOperation = "lighter";
        ctx.strokeStyle = P.trail === "thin" ? "#ffffff" : P.color; ctx.globalAlpha = 0.35; ctx.lineWidth = 5.5 * k; ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx - ux * ln0, by - uy * ln0); ctx.stroke();
        ctx.strokeStyle = "#ffffff"; ctx.globalAlpha = 0.6; ctx.lineWidth = 1.6 * k; ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx - ux * ln0 * 1.2, by - uy * ln0 * 1.2); ctx.stroke(); ctx.restore();
      }
      drawBallSprite(bx, by, k * g.sc * 0.95 * (owner ? 0.9 : 1), ang, g.spin);
    }
    function drawEntities() {
      var n = 0, i, e, g = S.ballG, owner = g.held ? EK[g.held] : null, air = !owner && g.h > 8;
      for (i = 0; i < E.length; i++) { IT[n].y = E[i].wy; IT[n].e = E[i]; n++; }
      if (!air) { IT[n].y = (owner ? owner.wy : g.y) - 0.02; IT[n].e = null; n++; }
      for (i = 1; i < n; i++) { var it = IT[i], j = i - 1; while (j >= 0 && IT[j].y < it.y) { IT[j + 1] = IT[j]; j--; } IT[j + 1] = it; }
      for (i = 0; i < n; i++) {
        e = IT[i].e;
        if (e) { pj(e.wx, e.wy); if (PR.y > -80 && PR.y < H + 120) drawPix(e, PR.x, PR.y, ksz(PR.s)); }
        else drawBall(owner);
      }
      drawTrail();
      if (air) drawBall(null);
    }
    // ---------------------------------------------------------------- fx
    function star(x, y, r) { ctx.beginPath(); ctx.moveTo(x, y - r); ctx.lineTo(x + r * 0.22, y - r * 0.22); ctx.lineTo(x + r, y); ctx.lineTo(x + r * 0.22, y + r * 0.22); ctx.lineTo(x, y + r); ctx.lineTo(x - r * 0.22, y + r * 0.22); ctx.lineTo(x - r, y); ctx.lineTo(x - r * 0.22, y - r * 0.22); ctx.closePath(); ctx.fill(); }
    function drawFx() {
      var tm = S.time, i, r, p, age, k;
      for (i = 0; i < RG.length; i++) {
        r = RG[i]; if (!r.on) continue; age = (tm - r.t0) / 0.5; if (age >= 1) { r.on = 0; continue; }
        pj(r.x, r.y); k = ksz(PR.s); var rad = (6 + 46 * eo3(age)) * k * r.sc;
        ctx.strokeStyle = r.c; ctx.globalAlpha = (1 - age) * 0.95; ctx.lineWidth = (4 * (1 - age) + 1) * L.u; ctx.beginPath(); ctx.ellipse(PR.x, PR.y, rad, rad * 0.42, 0, 0, TAU); ctx.stroke(); ctx.globalAlpha = 1;
      }
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (i = 0; i < PP.length; i++) {
        p = PP[i]; if (!p.on) continue; var a = clamp(p.life / p.max, 0, 1); pj(p.x, p.y); var px = PR.x + p.ox, py = PR.y + p.oy; k = ksz(PR.s);
        if (p.kind === 1) { ctx.globalCompositeOperation = "source-over"; ctx.fillStyle = DUST[(a * 7) | 0]; ctx.beginPath(); ctx.arc(px, py, p.r * k * (1.7 - a * 0.7), 0, TAU); ctx.fill(); ctx.globalCompositeOperation = "lighter"; }
        else if (p.kind === 2) { ctx.strokeStyle = "rgba(255,255,255," + a.toFixed(2) + ")"; ctx.lineWidth = 1.4 * L.u; ctx.beginPath(); ctx.arc(px, py, p.r * k * (2 - a), 0, TAU); ctx.stroke(); }
        else if (p.kind === 3) { ctx.fillStyle = p.c; ctx.globalAlpha = a; star(px, py, p.r * L.u * (0.6 + a)); ctx.globalAlpha = 1; }
        else if (p.kind === 4) { ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = a; ctx.fillStyle = p.c; ctx.fillRect(px - p.r * L.u, py - p.r * L.u, p.r * 2 * L.u, p.r * 1.6 * L.u); ctx.globalAlpha = 1; ctx.globalCompositeOperation = "lighter"; }
        else if (p.kind === 5) { var gr = p.r * k * (1.6 - a * 0.6); ctx.globalAlpha = a; ctx.fillStyle = p.c; ctx.drawImage(glowCv, px - gr, py - gr, gr * 2, gr * 2); ctx.globalAlpha = 1; }
        else { ctx.fillStyle = p.c; ctx.globalAlpha = a; ctx.beginPath(); ctx.arc(px, py, p.r * L.u, 0, TAU); ctx.fill(); ctx.globalAlpha = 1; }
      }
      ctx.restore();
    }
    function drawScreenFx() {
      var i, s, a, any = false;
      for (i = 0; i < SP.length; i++) { if (SP[i].on) { any = true; break; } }
      if (!any) return;
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (i = 0; i < SP.length; i++) {
        s = SP[i]; if (!s.on) continue; a = clamp(s.life / s.max, 0, 1);
        if (s.kind === 0) { ctx.globalAlpha = a; ctx.strokeStyle = s.c; ctx.lineWidth = s.r * L.u; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(s.px, s.py); ctx.lineTo(s.x, s.y); ctx.stroke(); }
        else if (s.kind === 2) { var gr = s.r * (1.6 - a * 0.9); ctx.globalAlpha = a * 0.8; ctx.fillStyle = s.c; ctx.drawImage(glowCv, s.x - gr, s.y - gr, gr * 2, gr * 2); }
        else { var fc = Math.cos(s.rot); ctx.globalAlpha = Math.min(1, a * 1.8); ctx.fillStyle = s.c; ctx.setTransform(dpr * Math.cos(s.rot * 0.5), dpr * Math.sin(s.rot * 0.5), -dpr * Math.sin(s.rot * 0.5) * fc, dpr * fc, dpr * s.x, dpr * s.y); ctx.fillRect(-s.r, -s.r * 0.55, s.r * 2, s.r * 1.1); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); }
      }
      ctx.restore();
    }
    function drawCrowdFlashes() {
      pj(0, 110.5); var wallY = PR.y, i, f, tm = S.time; if (wallY < 6) return;
      var boost = S.cboost > 0 ? Math.max(0, 1 - (tm - S.cb0) / 2.2) : 0;
      if (boost > 0.02) { ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.fillStyle = "rgba(255,226,170," + (0.1 * boost).toFixed(3) + ")"; ctx.fillRect(0, Math.max(0, wallY - bandH), W, Math.min(bandH, wallY) - 14 * L.u); ctx.restore(); }
      if (tm > nextFlash) { nextFlash = tm + (boost > 0.05 ? 0.02 : 0.35 + rnd() * 0.9); f = CFL[CFi = (CFi + 1) % CFL.length]; f.x = rnd() * W; f.y = rnd(); f.t0 = tm; f.on = 1; }
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (i = 0; i < CFL.length; i++) {
        f = CFL[i]; if (!f.on) continue; var a = 1 - (tm - f.t0) / 0.22; if (a <= 0) { f.on = 0; continue; }
        var fy = wallY - 16 * L.u - f.y * Math.min(bandH * 0.8, wallY - 22 * L.u), rr = (7 + a * 9) * L.u; if (fy < 0) continue;
        ctx.globalAlpha = a; ctx.drawImage(glowCv, f.x - rr, fy - rr, rr * 2, rr * 2); ctx.fillStyle = "#fff"; ctx.globalAlpha = a * 0.9; star(f.x, fy, rr * 0.9);
      }
      ctx.restore();
    }
    function drawRuler() {
      if (!S.ruler) return;
      var x = W - 11 * L.u, y0 = H * 0.17, y1 = H * 0.7, pos = clamp(S.losLine, 0, 100), bw = 5 * L.u;
      ctx.save(); ctx.globalAlpha = 1 - S.bars;
      ctx.fillStyle = "rgba(5,8,15,0.58)"; roundRect(x - 13 * L.u, y0 - 18 * L.u, 26 * L.u, (y1 - y0) + 34 * L.u, 8 * L.u); ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.14)"; ctx.fillRect(x - bw / 2, y0, bw, y1 - y0);
      var gy = y1 - (y1 - y0) * pos / 100; ctx.fillStyle = ACCENT; ctx.fillRect(x - bw / 2, gy, bw, y1 - gy);
      ctx.font = "700 " + (8.5 * L.u).toFixed(1) + "px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (var v = 0; v <= 100; v += 10) {
        var ty = y1 - (y1 - y0) * v / 100; ctx.fillStyle = "rgba(255,255,255,0.55)"; ctx.fillRect(x - 5 * L.u, ty - 0.5, 10 * L.u, 1);
        if (v % 20 === 0 && v > 0 && v < 100) { ctx.fillStyle = "rgba(255,255,255,0.75)"; ctx.fillText(String(v), x, ty - 6 * L.u); }
      }
      ctx.fillStyle = "#ffd36a"; ctx.fillText("TD", x, y0 - 8 * L.u); ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.fillText("0", x, y1 + 10 * L.u);
      ctx.translate(x, gy); ctx.rotate(-0.5); ctx.fillStyle = "#9a5528"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1; ctx.beginPath(); ctx.ellipse(0, 0, 7 * L.u, 4.3 * L.u, 0, 0, TAU); ctx.fill(); ctx.stroke();
      ctx.restore();
    }
    // INSTANT REPLAY framing: letterbox bars, scanlines, a replay bug in tier color
    function drawBars() {
      var b = S.bars; if (b < 0.01) return;
      var bh = H * 0.085 * b, u = L.u;
      ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, bh); ctx.fillRect(0, H - bh, W, bh);
      ctx.globalAlpha = 0.4 * b; ctx.fillStyle = scanPat; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 0.5 * b; ctx.fillStyle = vignette; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1;
      if (b > 0.5 && P && P.color) {
        var by = H - bh, x = 14 * u, a = (b - 0.5) * 2, hgt = 22 * u, yy = by - hgt - 10 * u, lab = P.label || "";
        ctx.font = "800 " + (13 * u).toFixed(1) + "px " + FONT; var w1 = ctx.measureText("INSTANT REPLAY").width, w2 = ctx.measureText(lab).width, bw = 28 * u + w1 + 14 * u + w2 + 14 * u;
        ctx.globalAlpha = a; ctx.fillStyle = "rgba(0,0,0,0.82)"; ctx.fillRect(x, yy, bw, hgt); ctx.fillStyle = "#e5232e"; ctx.fillRect(x, yy, 6 * u, hgt); ctx.fillStyle = P.color; ctx.fillRect(x + bw, yy, 6 * u, hgt);
        ctx.fillStyle = "#e5232e"; ctx.beginPath(); ctx.arc(x + 17 * u, yy + hgt / 2, 4 * u * (0.7 + 0.3 * Math.sin(S.time * 9)), 0, TAU); ctx.fill();
        ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillStyle = "#fff"; ctx.fillText("INSTANT REPLAY", x + 28 * u, yy + hgt / 2 + 0.5);
        ctx.fillStyle = P.color; ctx.fillText(lab, x + 42 * u + w1, yy + hgt / 2 + 0.5); ctx.globalAlpha = 1;
      }
    }
    function render() {
      var t = S.time, g = S.ballG, z = S.zoom, sk = S.shake, ox = 0, oy = 0;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (sk) { var age = (t - sk.t0) / sk.dur; if (age >= 1) S.shake = null; else { var m = sk.a * (1 - age) * L.u; ox = (Math.sin(t * 91) + Math.sin(t * 57)) * 0.5 * m; oy = Math.cos(t * 83) * m; } }
      ctx.save();
      if (z !== 1 || ox || oy) {
        // broadcast camera: follow the ball (or the receiver's feet), push in toward screen centre as the zoom grows
        pj(g.x, g.y); var kk = ksz(PR.s), fx = PR.x, fy = PR.y - g.h * kk * (1 - S.fLow), bl = z > 1 ? clamp((z - 1) / 0.5, 0, 1) * 0.9 : 0;
        ctx.translate(fx + (W / 2 - fx) * bl + ox, fy + (H * 0.47 - fy) * bl + oy); ctx.scale(z, z); ctx.translate(-fx, -fy);
        drawScene();
      } else if (sceneUsable()) { ctx.drawImage(sceneC.c, 0, 0, W, H); }
      else drawScene();
      drawCrowdFlashes(); drawEntities(); drawFx();
      ctx.restore();
      ctx.fillStyle = vignette; ctx.fillRect(0, 0, W, H);
      if (S.sackF > 0.01) { ctx.globalAlpha = 0.7 * S.sackF; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
      drawBars(); drawScreenFx(); drawRuler();
      var f = S.flash;
      if (f) { var fa = (t - f.t0) / f.dur; if (fa >= 1) S.flash = null; else { ctx.globalAlpha = f.a * (1 - fa) * (1 - fa); ctx.fillStyle = f.c; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; } }
      if (S.fade > 0.003) { ctx.globalAlpha = S.fade; ctx.fillStyle = "#03050a"; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
    }
    // the static scene (backdrop, turf, paint, markers) is cached while the camera is still
    function sceneUsable() {
      if (S.time - S.fdPulse < 0.8 || !sceneC) return false;
      var K = SK;
      if (K[0] === S.cam && K[1] === S.los && K[2] === S.losLine && K[3] === S.fd && K[4] === (S.fdGreen ? 1 : 0) && K[5] === W && K[6] === H && K[7] === L.ay && K[8] === 1) return true;
      K[0] = S.cam; K[1] = S.los; K[2] = S.losLine; K[3] = S.fd; K[4] = S.fdGreen ? 1 : 0; K[5] = W; K[6] = H; K[7] = L.ay; K[8] = 1;
      var main = ctx; ctx = sceneC.x; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); drawScene(); ctx = main; return true;
    }
    // ---------------------------------------------------------------- the loop
    function movingNow() { return !!(P || R || S.anyFx || S.flash || S.shake || S.bars > 0.01 || S.fade > 0.003 || S.fade !== S.fadeTarget); }
    function playRate(p, dt) {          // slow motion around the big catch, plus a brief freeze frame
      var r = 1;
      if (p.slowAmt) { r = 1 - p.slowAmt * sstep((p.t - (p.tc - 0.35)) / 0.15) * (1 - sstep((p.t - (p.tc + 0.15)) / 0.15)); }
      if (p.freeze && !p.froze && p.t >= p.tc) { p.froze = 1; p.fz = p.freeze; flash("#ffffff", 0.32, 0.3); }
      if (p.fz > 0) { p.fz -= dt; r = 0.04; }
      return r;
    }
    function frame(now) {
      raf = 0; var dt = Math.min(0.05, (now - last) / 1000); last = now;
      var playing = !!P;
      if (!playing && !movingNow() && !S.ambient) { render(); return; }
      if (!playing && !movingNow() && now - lastDraw < 32) { need(); return; }   // ambient shimmer capped near 30fps
      lastDraw = now;
      var dtS = dt, pf = window.__ddPerf ? performance.now() : 0;
      if (P && !P.reduced) dtS = P.paused ? 0 : dt * playRate(P, dt);
      S.time += dtS;
      if (P) stepPlay(dtS);
      stepRest(dtS);
      if (!(P && P.reduced)) updatePrev(dtS);
      render();
      if (pf) window.__ddPerf.push(performance.now() - pf);
      if (P || R || movingNow() || S.ambient) need();
    }
    function stepParts(dt) {
      var i, p, any = false;
      for (i = 0; i < PP.length; i++) { p = PP[i]; if (!p.on) continue; p.life -= dt; if (p.life <= 0) { p.on = 0; continue; } any = true; p.ox += p.vx * dt; p.oy += p.vy * dt; p.vy += p.g * dt; }
      for (i = 0; i < SP.length; i++) {
        p = SP[i]; if (!p.on) continue; p.life -= dt; if (p.life <= 0) { p.on = 0; continue; } any = true;
        p.x += p.vx * dt; p.y += p.vy * dt; p.vy += p.g * dt; p.rot += p.vr * dt;
        if (p.kind === 0) { p.vx *= 1 - 0.9 * dt; p.px = p.x - p.vx * 0.05; p.py = p.y - p.vy * 0.05; }
      }
      for (i = 0; i < RG.length; i++) if (RG[i].on) any = true;
      S.anyFx = any || S.anyFx && S.time - S.cb0 < 2.3;
    }
    function stepRest(dt) {
      var i;
      stepParts(dt);
      if (S.sackF > 0 && !(P && P.sack)) S.sackF = 0;
      if (S.fade !== S.fadeTarget) { var d = S.fadeTarget - S.fade, st = dt / 0.28; S.fade = Math.abs(d) <= st ? S.fadeTarget : S.fade + Math.sign(d) * st; }
      if (R) {
        R.t += dt; var u = eio3(R.t / R.dur);
        E.forEach(function (e, j) {
          var f = R.from[j], tx = e.ix, ty = S.los + e.iy; e.wx = lerp(f.x, tx, u); e.wy = lerp(f.y, ty, u); e.z = f.z * (1 - u); e.rot = f.rot * (1 - u); e.sxs = lerp(f.sxs, 1, u); e.sys = lerp(f.sys, 1, u);
          e.run = u < 0.97 && Math.hypot(tx - f.x, ty - f.y) > 0.8; e.arms = "idle"; e.aq = 0; e.cq = 0; e.ov = 0; e.cr = 0; e.amp = 1; e.tapL = e.tapR = 0;
        });
        S.cam = S.los; S.zoom = 1;
        var g = S.ballG; g.held = null; g.pinS = g.pinE = 0; g.x = lerp(R.bx, 0, u); g.y = lerp(R.by, S.los + 0.3, u); g.h = lerp(R.bh, 2, u);
        if (R.t >= R.dur) { R = null; formation(); }
      } else if (!P) {
        for (i = 0; i < E.length; i++) applyIdlePose(E[i], S.time);
        S.cam = lerp(S.cam, S.los, 0.2); S.zoom = lerp(S.zoom, 1, 0.2); if (Math.abs(S.zoom - 1) < 0.003) S.zoom = 1;
        S.bars = S.bars * 0.8; if (S.bars < 0.01) S.bars = 0;
      }
    }
    function updatePrev(dt) {
      for (var i = 0; i < E.length; i++) {
        var e = E[i]; if (dt > 0) { var v = (e.wy - e.py) / dt; e.vy = lerp(e.vy, v, 0.25); }
        e.px = e.wx; e.py = e.wy;
        if (e.run) e.phase += dt * 15 * (e.amp < 0.6 ? 0.8 : 1);
        if (e.ov) e.back = e.ov === 2; else if (e.run && Math.abs(e.vy) > 1.2) e.back = e.vy > 0; else if (!e.run && !P) e.back = e.team === "o";
      }
    }
    function stepPlay(dt) {
      var p = P;
      if (p.reduced) { p.t += dt; if (!p.fired.sw && p.t >= 0.22) { p.fired.sw = 1; finalState(); } S.fadeTarget = p.t < 0.22 ? 0.65 : 0; if (p.t >= 0.5) endPlay(); return; }
      if (p.paused) { if (p.sack) evalSack(Math.min(p.t, p.tEnd)); else evalPlay(Math.min(p.t, p.tEnd)); return; }
      p.t += dt;
      if (p.sack) evalSack(Math.min(p.t, p.tEnd)); else evalPlay(Math.min(p.t, p.tEnd));
      if (p.t >= p.tEnd) endPlay();
    }
    function finalState() {   // jump to the end of the play
      var p = P; if (!p) return;
      var save = p.fired; p.fired = {}; if (p.sack) evalSack(p.tEnd); else evalPlay(p.tEnd); p.fired = save;
      S.shake = null; S.flash = null; S.bars = 0; S.sackF = 0; p.fz = 0; clearFx();
    }
    function endPlay() {
      var p = P; if (!p) return; var cb = p.done; P = null;
      if (!p.sack) { S.los = p.L1; S.losLine = p.L1; if (p.fd1 != null) { S.fd = p.fd1; if (!p.score) S.fdGreen = false; } }
      S.cam = S.los; S.zoom = 1; S.trail.length = 0; S.fadeTarget = 0; S.bars = 0; S.sackF = 0; S.fLow = 0;
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
      setNumber: function (n) { S.number = n; EK.qb.n = qbN(); need(); },
      setAmbient: function (on) { S.ambient = !!on; need(); },
      setRuler: function (on) { S.ruler = !!on; need(); },
      // Where the line of scrimmage sits on screen (fraction of the height) and whether the yard ruler shows.
      setView: function (ayFrac, ruler) { L.ayF = ayFrac; L.ay = H * ayFrac; S.ruler = !!ruler; need(); },
      // Put the ball on the p-yard line (0 = own goal line, 100 = opponent goal line) with the first-down line at world yard fd.
      setScene: function (p, fd, o) {
        o = o || {}; P = null; R = null; S.los = clamp(p, 0, 100); S.losLine = S.los; S.cam = S.los; S.zoom = 1; S.fd = fd == null ? Math.min(110, S.los + 10) : fd; S.fdGreen = !!o.fdGreen; S.trail.length = 0; clearFx(); S.flash = null; S.shake = null; S.bars = 0; S.sackF = 0; S.fLow = 0; S.anyFx = false;
        if (o.number) { S.number = o.number; } formation(); layout(); need();
      },
      // A drive-ending reset: fade out, jump to the new yard line, fade in.
      reset: function (p, fd) { S.fadeTarget = 1; var self = this; setTimeout(function () { self.setScene(p, fd); S.fade = 1; S.fadeTarget = 0; need(); }, setReduced() ? 120 : 300); need(); },
      // Run the designated play for a graded answer. o: {tier, gain, p0, fd0, fd1, score, variant, seed}. done() fires when it has settled.
      play: function (o, done) {
        this.skip(true); layout();
        var sp = buildPlay(o); sp.done = done; sp.reduced = setReduced(); P = sp; R = null; S.zoom = 1; S.fadeTarget = 0; S.fade = 0; S.bars = 0;
        if (o.fd0 != null) S.fd = o.fd0; S.fdGreen = false; S.losLine = o.p0; S.los = o.p0; S.cam = o.p0; S.trail.length = 0; BP.t = 0;
        if (sp.reduced) { evalPlay(0); S.ballG.h = 2; } else evalPlay(0);
        need(); return sp;
      },
      sack: function (o, done) {
        this.skip(true); layout();
        var sp = { sack: true, tier: 0, L0: o.p0, L1: o.p0, tEnd: 1.9, t: 0, fired: {}, color: "#ff5d7a", label: "SACK", done: done, reduced: setReduced(), fd1: o.fd1 }; P = sp; R = null; S.los = o.p0; S.cam = o.p0; S.zoom = 1; S.fadeTarget = 0; S.fade = 0; S.trail.length = 0; S.bars = 0; BP.t = 0; if (o.fd0 != null) S.fd = o.fd0;
        if (sp.reduced) sp.tEnd = 0.5; evalSack(0); need(); return sp;
      },
      // Finish whatever play is running right now (the player tapped or pressed a key). quiet: do not call the done callback.
      skip: function (quiet) {
        var p = P; if (!p) { if (R) { R.t = R.dur; } return false; }
        if (quiet) { P = null; S.fadeTarget = 0; S.fade = 0; S.bars = 0; S.zoom = 1; clearFx(); return false; }
        finalState(); endPlay(); return true;
      },
      playing: function () { return !!P; },
      // dev only (used by /play?demo=1): freeze the running play at t seconds, or pass null to let it run on.
      seek: function (t) {
        var p = P; if (!p) return; if (t == null) { p.paused = false; need(); return; }
        p.paused = false; p.reduced = false; p.fired = {}; clearFx(); S.trail.length = 0; p.froze = 1; p.fz = 0;
        var base = S.time, ev0 = function (k) { if (p.sack) evalSack(k); else evalPlay(k); };
        for (var k = Math.max(0, t - 0.5); k < t; k += 0.03) { S.time = base - (t - k); ev0(k); stepParts(0.03); }
        S.time = base; p.t = t; p.fired = {}; ev0(t); S.time += 0.12; p.paused = true; need();
      },
      ballPoint: function () { var g = S.ballG; pj(g.x, g.y); var r = canvas.getBoundingClientRect(); return { x: r.left + PR.x, y: r.top + PR.y - g.h * ksz(PR.s) }; },
      flash: flash, shake: shake,
      tdCelebrate: function () { flash("#ffab1a", 0.4, 0.8); },
      // The favorite-team stadium (from /api/play/stadium): {home: {code, uniform, numbers, bench, roof, surface, stadium},
      // away: {code, uniform, numbers, bench}}. null puts the Lineup Lab default field back. The QB wears his real number.
      setTeam: function (sk) {
        var themes = window.TEAM_THEMES || {};
        if (!sk || !sk.home || !sk.away || !sk.home.uniform || !sk.away.uniform) {
          TU = null; helmetGrads([["#2fd88f", "#0d8a54", "#06462b"], ["#f3f6fc", "#b4bfd6", "#5f6c8c"]]);
          FORM.forEach(function (f) { EK[f.k].n = f.n; });
        } else {
          var hu = sk.home.uniform, au = sk.away.uniform, th = themes[sk.home.code] || {}, ta = themes[sk.away.code] || {};
          var city = String(th.city || sk.home.code).toUpperCase(), name = String(th.name || sk.home.code).toUpperCase(), stad = String(sk.home.stadium || "").toUpperCase();
          var awayNum = luma(au.jersey) > 0.8 ? au.trim : au.jersey;
          TU = { code: sk.home.code, city: city, name: name, stadium: stad, citySz: Math.min(6.6, 100 / city.length), nameSz: Math.min(6.6, 100 / name.length),
            dome: sk.home.roof === "dome", grass: sk.home.surface === "grass", accent: th.primary || hu.trim,
            o: { jersey: hu.jersey, trim: hu.trim, pants: hu.pants, sock: hu.jersey, num: hu.num, glove: "#ffffff", nstroke: hu.trim, stripe: hu.stripe, polo: mix(hu.jersey, "#000000", 0.35) },
            d: { jersey: "#f1f3f7", trim: au.jersey, pants: au.pants, sock: au.jersey, num: awayNum, glove: "#e8ecf4", nstroke: "rgba(255,255,255,0.9)", stripe: au.stripe, polo: mix(au.jersey, "#000000", 0.2) },
            ez: hu.jersey, ezBand: hu.trim, ezText: hu.num, ezStroke: mix(hu.jersey, "#000000", 0.55),
            turf: sk.home.surface === "grass" ? ["#17652f", "#11532a"] : ["#0e6a3c", "#0d6238"],
            qbNum: sk.home.numbers && sk.home.numbers.qb && sk.home.numbers.qb[0] != null ? sk.home.numbers.qb[0] : null, crowd: null, rail: th.primary || hu.trim, railAway: ta.primary || au.jersey, benchH: sk.home.bench || [], benchA: sk.away.bench || [] };
          TU.crowd = [mix(hu.jersey, "#ffffff", 0.28), mix(hu.trim, "#ffffff", 0.1), mix(au.jersey, "#ffffff", 0.2)].map(function (c) { return c.slice(4, -1); });
          helmetGrads([shell(hu.helmet), shell(au.helmet)]);
          [["o", sk.home.numbers || {}], ["d", sk.away.numbers || {}]].forEach(function (pair) {
            SLOTS[pair[0]].forEach(function (s) { var arr = pair[1][s[1]], n = arr && arr[s[2]]; EK[s[0]].n = n != null ? n : FORM.filter(function (f) { return f.k === s[0]; })[0].n; });
          });
        }
        EK.qb.n = qbN();
        if (W) bake();
        need();
      },
      team: function () { return TU ? TU.code : ""; },
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
