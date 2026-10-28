// Start/Sit "Your Team" command center: your projected score against this week's opponent with a win-probability
// bar, a lineup status line, one-click lineup solves, and a slide-over to swap any starter for a bench player in place.
// Pure helpers live on window.SSTeam (tested under node); the DOM part only runs in the browser.
(function () {
  "use strict";

  var ELIGIBLE = {
    QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"],
    FLEX: ["RB", "WR", "TE"], WRRB_FLEX: ["RB", "WR"], REC_FLEX: ["WR", "TE"],
    SUPER_FLEX: ["QB", "RB", "WR", "TE"], K: ["K"], DEF: ["DEF"],
    "RB/WR/TE": ["RB", "WR", "TE"], "RB/WR": ["RB", "WR"], "WR/TE": ["WR", "TE"], OP: ["QB", "RB", "WR", "TE"], "D/ST": ["DEF"]
  };

  function eligible(slot, position) {
    var allowed = Object.prototype.hasOwnProperty.call(ELIGIBLE, slot) ? ELIGIBLE[slot] : [slot];
    return allowed.indexOf(position) !== -1;
  }

  function unavailable(p) { return !!p.on_bye || ["Out", "IR", "PUP", "Sus"].indexOf(p.injury_status) !== -1; }
  function starters(players) { return players.filter(function (p) { return p.is_starter; }); }
  function total(players) { return starters(players).reduce(function (a, p) { return a + (+p.PROJ || 0); }, 0); }

  // A team's total is treated as a normal: the starters' spreads (10th to 90th percentile is 2.56 sd wide) add as
  // independent variances. A starter with no range gets a spread of 35% of his projection.
  function variance(players) {
    return starters(players).reduce(function (a, p) {
      var sd = p.floor != null && p.ceiling != null ? (p.ceiling - p.floor) / 2.56 : 0.35 * (+p.PROJ || 0);
      return a + sd * sd;
    }, 0);
  }

  function erf(x) {      // Abramowitz and Stegun 7.1.26
    var s = x < 0 ? -1 : 1; x = Math.abs(x);
    var t = 1 / (1 + 0.3275911 * x);
    var y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }

  // Chance `mine` outscores `opp`, 0 to 100. No opponent means no number.
  function winProb(mine, opp) {
    if (!opp || !opp.length) return null;
    var sd = Math.sqrt(variance(mine) + variance(opp));
    if (!sd) return total(mine) === total(opp) ? 50 : total(mine) > total(opp) ? 100 : 0;
    return Math.round(50 * (1 + erf((total(mine) - total(opp)) / (sd * Math.SQRT2))));
  }

  function status(players) {
    var st = starters(players);
    var ok = st.filter(function (p) { return !unavailable(p); });
    return {
      active: ok.length,
      open: st.length - ok.length,                       // starting slots filled by someone who cannot play this week
      offline: players.filter(unavailable).length        // everyone on the roster on a bye or ruled out
    };
  }

  // Bench players who can take this starter's slot, best projection first, with what the swap does to the total.
  function candidates(players, starterId) {
    var s = players.filter(function (p) { return p.player_id === starterId; })[0];
    if (!s) return [];
    return players.filter(function (p) { return !p.is_starter && !unavailable(p) && eligible(s.slot, p.position); })
      .map(function (p) { return { player: p, delta: Math.round(((+p.PROJ || 0) - (+s.PROJ || 0)) * 10) / 10 }; })
      .sort(function (a, b) { return (+b.player.PROJ || 0) - (+a.player.PROJ || 0); });
  }

  // New roster with the bench player in the starter's slot and the starter on the bench.
  function swap(players, starterId, benchId) {
    var s = players.filter(function (p) { return p.player_id === starterId; })[0];
    var b = players.filter(function (p) { return p.player_id === benchId; })[0];
    if (!s || !b || !s.is_starter || b.is_starter || !eligible(s.slot, b.position)) return players;
    return players.map(function (p) {
      if (p === s) return Object.assign({}, p, { is_starter: false, slot: null });
      if (p === b) return Object.assign({}, p, { is_starter: true, slot: s.slot });
      return p;
    });
  }

  // Re-seat the roster to a solved lineup ([{slot, player_id}]), keeping everyone else on the bench.
  function applyLineup(players, lineup) {
    var slotOf = {};
    lineup.forEach(function (l) { if (l.player_id) slotOf[l.player_id] = l.slot; });
    return players.map(function (p) {
      return slotOf[p.player_id] !== undefined ? Object.assign({}, p, { is_starter: true, slot: slotOf[p.player_id] })
        : Object.assign({}, p, { is_starter: false, slot: null });
    });
  }

  var SSTeam = { eligible: eligible, total: total, variance: variance, winProb: winProb, status: status,
    candidates: candidates, swap: swap, applyLineup: applyLineup, unavailable: unavailable };
  if (typeof window !== "undefined") window.SSTeam = SSTeam;
  if (typeof module !== "undefined") module.exports = SSTeam;
  if (typeof document === "undefined" || typeof window === "undefined" || !window.document.getElementById) return;

  // -------------------------------------------------------------- browser ----
  var model = null;         // {week, league, mine: [players], opp: [players]|null, oppName, myName}
  var drawerFor = null;

  function $(s) { return document.querySelector(s); }
  function esc(x) { return window.esc ? window.esc(x) : String(x == null ? "" : x).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function d1(v) { return v == null ? "—" : Number(v).toFixed(1); }
  function reduced() { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }

  function tween(el, to, ms) {
    var from = parseFloat(el.textContent) || 0;
    if (reduced() || from === to) { el.textContent = d1(to); return; }
    var t0 = performance.now();
    (function step(now) {
      var k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = d1(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  function face(p) { return '<img class="sst-face" ' + headshotAttrs({ headshot_url: p.headshot_url, player_display_name: p.player_display_name }) + ' alt="">'; }

  function flags(p) {
    var f = "";
    if (p.on_bye) f += '<span class="sst-tag bye">BYE</span>';
    else if (p.injury_status) f += '<span class="sst-tag inj">' + esc(p.injury_status) + "</span>";
    if (p.p_play != null && !p.on_bye) f += '<span class="sst-tag q">' + Math.round(p.p_play * 100) + "% to play</span>";
    return f;
  }

  function starterCard(p) {
    var range = p.floor != null && p.ceiling != null ? '<small>' + Math.round(p.floor) + "–" + Math.round(p.ceiling) + "</small>" : "";
    return '<button type="button" class="sst-slot' + (unavailable(p) ? " down" : "") + '" data-pid="' + esc(p.player_id) + '" title="Swap ' + esc(p.player_display_name) + '">' +
      '<span class="sst-slot-label">' + esc(p.slot || p.position) + "</span>" + face(p) +
      '<span class="sst-slot-name">' + esc(p.player_display_name) + flags(p) + "</span>" +
      '<span class="sst-slot-proj"><b>' + d1(p.PROJ) + "</b>" + range + "</span></button>";
  }

  function benchChip(p) {
    return '<div class="sst-bench-chip' + (unavailable(p) ? " down" : "") + '">' + face(p) + "<span>" + esc(p.player_display_name) +
      '<small>' + esc(p.position) + (p.opponent ? " · vs " + esc(p.opponent) : "") + "</small></span><b>" + d1(p.PROJ) + "</b></div>";
  }

  function render(first) {
    var host = $("#ss-hero");
    if (!host) return;
    if (!model) { host.innerHTML = '<div class="sst-load">' + (window.skeletonRows ? window.skeletonRows(3, 2) : "Loading your team…") + "</div>"; return; }
    var mine = model.mine, opp = model.opp, me = total(mine), them = opp ? total(opp) : null;
    var wp = winProb(mine, opp), st = status(mine);
    var bench = mine.filter(function (p) { return !p.is_starter; }).sort(function (a, b) { return (+b.PROJ || 0) - (+a.PROJ || 0); });
    host.innerHTML =
      '<div class="sst-top">' +
        '<div class="sst-side"><div class="sst-label">' + esc(model.myName || "Your team") + '</div><div class="sst-score" id="sst-me">' + d1(first ? 0 : me) + '</div><div class="sst-sub">projected</div></div>' +
        '<div class="sst-mid"><div class="sst-vs">Week ' + esc(model.week) + "</div>" +
          (wp == null ? '<div class="sst-sub">No head-to-head matchup set yet</div>' :
            '<div class="sst-bar" role="img" aria-label="Win probability ' + wp + '%"><i style="width:' + (first ? 50 : wp) + '%" id="sst-bar-fill"></i><span class="sst-bar-me">' + wp + '%</span><span class="sst-bar-opp">' + (100 - wp) + '%</span></div><div class="sst-sub">win probability</div>') +
        "</div>" +
        '<div class="sst-side opp"><div class="sst-label">' + esc(model.oppName || "Opponent") + '</div><div class="sst-score" id="sst-opp">' + (them == null ? "—" : d1(first ? 0 : them)) + '</div><div class="sst-sub">projected</div></div>' +
      "</div>" +
      '<div class="sst-status"><span><b>' + st.active + "</b> active starters</span><span class=\"" + (st.open ? "warn" : "") + '"><b>' + st.open + "</b> open slot" + (st.open === 1 ? "" : "s") + "</span><span class=\"" + (st.offline ? "warn" : "") + '"><b>' + st.offline + "</b> on bye / out</span></div>" +
      '<div class="sst-actions">' +
        '<button type="button" class="primary-btn" data-solve="balanced">Lock optimal lineup</button>' +
        '<button type="button" class="sst-btn" data-solve="upside" title="Underdog mode: favors big weeks">Max ceiling</button>' +
        '<button type="button" class="sst-btn" data-solve="safe" title="Favorite mode: favors fewer duds">Safe floor</button>' +
        '<span class="sst-msg" id="sst-msg" aria-live="polite"></span></div>' +
      '<div class="sst-lineup">' + starters(mine).map(starterCard).join("") + "</div>" +
      (bench.length ? '<div class="sst-bench-head">Bench</div><div class="sst-bench">' + bench.map(benchChip).join("") + "</div>" : "");
    if (first) {          // count up and fill the bar on first paint
      tween($("#sst-me"), me, 700);
      if (them != null) tween($("#sst-opp"), them, 700);
      var fill = $("#sst-bar-fill");
      if (fill) requestAnimationFrame(function () { requestAnimationFrame(function () { fill.style.width = wp + "%"; }); });
    }
  }

  function closeDrawer() {
    drawerFor = null;
    var d = $("#sst-drawer");
    if (d) { d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); }
    var b = $("#sst-scrim");
    if (b) b.classList.remove("open");
  }

  function openDrawer(pid) {
    var s = model.mine.filter(function (p) { return p.player_id === pid; })[0];
    if (!s) return;
    drawerFor = pid;
    var list = candidates(model.mine, pid);
    var host = $("#sst-drawer");
    host.innerHTML =
      '<div class="sst-d-head"><div><div class="sst-label">Swap ' + esc(s.slot || s.position) + '</div><h3>' + esc(s.player_display_name) + '</h3>' +
        '<div class="sst-sub">' + d1(s.PROJ) + ' projected' + (s.opponent ? " · vs " + esc(s.opponent) : "") + '</div></div><button type="button" class="modal-close" id="sst-d-close" aria-label="Close">✕</button></div>' +
      (list.length ? list.map(function (c) {
        var p = c.player, up = c.delta >= 0;
        return '<button type="button" class="sst-cand" data-bench="' + esc(p.player_id) + '">' + face(p) +
          '<span class="sst-cand-main"><b>' + esc(p.player_display_name) + "</b><small>" + esc(p.position) + (p.recent_team ? " · " + esc(p.recent_team) : "") +
          (p.opponent ? " · vs " + esc(p.opponent) : "") + (p.matchup_tag ? ' · <em class="mt-' + esc(p.matchup_tag) + '">' + esc(p.matchup_tag) + " matchup</em>" : "") + "</small>" +
          '<span class="sst-impact ' + (up ? "up" : "dn") + '">' + esc(p.player_display_name) + " (" + (up ? "+" : "") + c.delta.toFixed(1) + " pts) over " + esc(s.player_display_name) + "</span></span>" +
          '<span class="sst-cand-proj">' + d1(p.PROJ) + "</span></button>";
      }).join("") : '<div class="empty">No bench player can play ' + esc(s.slot || s.position) + " this week.</div>");
    host.classList.add("open");
    host.setAttribute("aria-hidden", "false");
    $("#sst-scrim").classList.add("open");
    $("#sst-d-close").focus();
  }

  function doSwap(benchId) {
    var s = drawerFor, before = total(model.mine);
    model.mine = swap(model.mine, s, benchId);
    closeDrawer();
    render(false);
    var me = $("#sst-me");
    if (me) { me.textContent = d1(before); tween(me, total(model.mine), 450); }
    var card = document.querySelector('.sst-slot[data-pid="' + benchId + '"]');
    if (card) card.classList.add("swapped");
    var wp = winProb(model.mine, model.opp), fill = $("#sst-bar-fill");
    if (fill && wp != null) fill.style.width = wp + "%";
  }

  async function solve(mode) {
    var msg = $("#sst-msg");
    document.querySelectorAll("#ss-hero [data-solve]").forEach(function (b) { b.disabled = true; });
    if (msg) msg.textContent = "Solving your lineup…";
    try {
      var qs = scoringQS().replace(/^&/, "");
      var res = await api("/api/startsit/lineup?mode=" + mode + (qs ? "&" + qs : "") + (model.weekParam ? "&week=" + model.weekParam : ""));
      var before = total(model.mine);
      model.mine = applyLineup(model.mine, res.lineup || []);
      render(false);
      var me = $("#sst-me");
      if (me) { me.textContent = d1(before); tween(me, total(model.mine), 450); }
      var m2 = $("#sst-msg");
      if (m2) m2.textContent = (res.changes && res.changes.length ? res.changes.length + " change" + (res.changes.length === 1 ? "" : "s") + " applied" : "Already the best lineup") + " (" + mode + ")";
      document.querySelectorAll(".sst-slot").forEach(function (c) { c.classList.add("swapped"); });
    } catch (e) {
      var m3 = $("#sst-msg");
      if (m3) m3.textContent = "Couldn't solve right now. Try again in a moment.";
      document.querySelectorAll("#ss-hero [data-solve]").forEach(function (b) { b.disabled = false; });
    }
  }

  async function load() {
    var host = $("#ss-hero");
    if (!host) return;
    if (!model) render(false);
    try {
      var qs = scoringQS().replace(/^&/, "");
      var d = await api("/api/myteam" + (qs ? "?" + qs : ""));
      var firstPaint = !model;
      model = { week: d.nfl_week, myName: d.my_team.team_name, mine: d.my_team.players || [],
        opp: d.opponent ? d.opponent.players || [] : null, oppName: d.opponent ? d.opponent.team_name : null, weekParam: null };
      render(firstPaint);
    } catch (e) {
      host.innerHTML = '<div class="empty">Couldn\'t load your team. ' + esc(e.message || "") + "</div>";
    }
  }

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t || !model) return;
    var slot = t.closest(".sst-slot");
    if (slot) { openDrawer(slot.dataset.pid); return; }
    var cand = t.closest(".sst-cand");
    if (cand) { doSwap(cand.dataset.bench); return; }
    if (t.closest("#sst-d-close") || t.closest("#sst-scrim")) { closeDrawer(); return; }
    var btn = t.closest("[data-solve]");
    if (btn) solve(btn.dataset.solve);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && drawerFor) closeDrawer(); });

  SSTeam.load = load;
  SSTeam.reset = function () { model = null; };
})();
