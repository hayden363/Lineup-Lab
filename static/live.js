// NFL Games tab: a grid of dynamic scorebugs and a full-screen stadium dashboard with three states
// (pre-game, live with a 2D field and play-by-play, post-game recap). Pure builders live on window.LiveTab
// (tested under node); the DOM, polling and animation code only runs in the browser.
(function () {
  "use strict";

  var ALIAS = { WSH: "WAS", JAC: "JAX", LAR: "LA", OAK: "LV", SD: "LAC", STL: "LA", ARZ: "ARI" };
  function key(abbr) { var a = String(abbr || "").toUpperCase(); return ALIAS[a] || a; }
  function esc(x) {
    return String(x == null ? "" : x).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function d1(v) { return v == null ? "—" : Number(v).toFixed(1); }
  function theme(abbr) {
    var t = typeof TeamTheme !== "undefined" ? TeamTheme.get(key(abbr)) : null;
    return t || { primary: "#475569", secondary: "#94a3b8", logo: null, name: abbr };
  }
  function logo(abbr, cls) {
    var t = theme(abbr);
    return t.logo ? '<img class="' + cls + '" src="/api/img?url=' + encodeURIComponent(t.logo) + '" alt="" data-fb-hide="1">' : "";
  }

  // ---------------------------------------------------------------- pure ----
  function sortGames(games) {
    var rank = { in: 0, pre: 1, post: 2 };
    return games.slice().sort(function (a, b) {
      var ra = rank[a.state] == null ? 1 : rank[a.state], rb = rank[b.state] == null ? 1 : rank[b.state];
      if (ra !== rb) return ra - rb;
      return String(a.kickoff || "").localeCompare(String(b.kickoff || ""));
    });
  }

  // Which side just scored: 'home' | 'away' | null. `prev` is "away-home" from the last poll.
  function scoreChange(prev, g) {
    if (prev == null || g.state !== "in") return null;
    var parts = String(prev).split("-"), pa = +parts[0], ph = +parts[1];
    if (g.away.score > pa) return "away";
    if (g.home.score > ph) return "home";
    return null;
  }

  function countdown(ms) {
    if (!isFinite(ms) || ms <= 0) return "Kickoff";
    var s = Math.floor(ms / 1000), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d ? d + "d " + h + "h " + m + "m" : p(h) + ":" + p(m) + ":" + p(sec);
  }

  // SVG x for a yard line (0 to 100 from the left goal line): end zones take 100 units each side of a 1000-wide field.
  function fieldX(yard) { return 100 + yard * 8; }

  function fieldSvg(sit, home, away) {
    var ballX = fieldX(sit.yard_line), ltgX = fieldX(sit.line_to_gain);
    var right = sit.direction === "left-to-right";
    var hc = theme(home), ac = theme(away);
    var grass = "";
    for (var i = 0; i < 10; i++) grass += '<rect x="' + (100 + i * 80) + '" y="0" width="80" height="350" fill="' + (i % 2 ? "#163022" : "#142A1E") + '"/>';
    var marks = "";
    for (var k = 1; k <= 9; k++) {
      var x = fieldX(k * 10), label = k * 10 <= 50 ? k * 10 : 100 - k * 10;
      marks += '<line x1="' + x + '" y1="0" x2="' + x + '" y2="350" stroke="#fff" stroke-opacity=".2" stroke-width="2"/>' +
        '<text x="' + x + '" y="332" fill="#94a3b8" font-size="16" font-family="monospace" text-anchor="middle">' + label + "</text>" +
        '<text x="' + x + '" y="30" fill="#94a3b8" font-size="16" font-family="monospace" text-anchor="middle">' + label + "</text>";
    }
    var hashes = "";
    for (var y = 0; y <= 100; y++) if (y % 5) hashes += '<line x1="' + fieldX(y) + '" y1="118" x2="' + fieldX(y) + '" y2="128" stroke="#fff" stroke-opacity=".18"/><line x1="' + fieldX(y) + '" y1="222" x2="' + fieldX(y) + '" y2="232" stroke="#fff" stroke-opacity=".18"/>';
    var rz = sit.is_red_zone ? '<rect class="fld-rz" x="' + (right ? fieldX(80) : 100) + '" y="0" width="160" height="350" fill="rgba(244,63,94,.16)"/>' : "";
    var dx = right ? 1 : -1, ax = ballX + dx * 36;
    var arrow = '<polygon points="' + ax + ",160 " + (ax + dx * 26) + ",175 " + ax + ',190" fill="#fde047" opacity=".9"/>';
    return '<svg class="fld" viewBox="0 0 1000 350" role="img" aria-label="Ball on the field">' +
      grass +
      '<rect x="0" y="0" width="100" height="350" fill="' + ac.primary + '"/><rect x="900" y="0" width="100" height="350" fill="' + hc.primary + '"/>' +
      '<text x="50" y="175" fill="#fff" font-size="28" font-weight="800" font-family="monospace" text-anchor="middle" transform="rotate(-90 50 175)">' + esc(away) + "</text>" +
      '<text x="950" y="175" fill="#fff" font-size="28" font-weight="800" font-family="monospace" text-anchor="middle" transform="rotate(90 950 175)">' + esc(home) + "</text>" +
      rz + marks + hashes +
      '<line x1="' + ltgX + '" y1="0" x2="' + ltgX + '" y2="350" stroke="#facc15" stroke-width="4" stroke-dasharray="6 4"/>' +
      '<line x1="' + ballX + '" y1="0" x2="' + ballX + '" y2="350" stroke="#38bdf8" stroke-width="4"/>' +
      arrow +
      '<circle class="fld-ball" cx="' + ballX + '" cy="175" r="11" fill="#ea580c" stroke="#fff" stroke-width="2.5"/></svg>';
  }

  function ordinal(n) { return n === 1 ? "1st" : n === 2 ? "2nd" : n === 3 ? "3rd" : n + "th"; }
  function quarter(q) { return q > 4 ? "OT" : ordinal(q) + " Qtr"; }

  function ballLabel(sit, home, away) {
    var own = sit.direction === "left-to-right" ? sit.yard_line : 100 - sit.yard_line;
    return own <= 50 ? sit.possession + " " + own : (sit.possession === home ? away : home) + " " + (100 - own);
  }

  function bannerText(sit, game) {
    var clock = game && game.display_clock ? " • " + game.display_clock + " " + quarter(game.period) : "";
    return ordinal(sit.down) + " & " + sit.distance + " at " + ballLabel(sit, game.home.abbr, game.away.abbr) + clock;
  }

  // "TD Run: Jahmyr Gibbs 14 yds (+7.4 pts)"-style headline for a play, or its plain text.
  function playHeadline(p) {
    var t = String(p.type || "").toLowerCase(), f = p.fantasy || [];
    var lead = f[0];
    if (p.scoring && /rush/.test(t) && lead) return "TD Run: " + lead.name + " " + p.yards + " yds";
    if (p.scoring && /pass|reception/.test(t) && f.length) {
      var rec = f.filter(function (x) { return x.position !== "QB"; })[0] || f[0];
      return "TD Pass: " + rec.name + " " + p.yards + " yds";
    }
    if (/field goal/.test(t) && p.scoring) return "Field Goal" + (p.yards ? " " + p.yards + " yds" : "");
    if (/incompletion|incomplete/.test(t) && p.target) return "Pass Incomplete: Target intended for " + p.target;
    return p.text || p.type || "Play";
  }

  function playRowHtml(p) {
    var f = (p.fantasy || []).map(function (x) {
      var pos = x.points >= 0;
      return '<span class="pbp-pts ' + (x.mine ? "mine" : "") + (pos ? "" : " neg") + '" title="' + esc(x.name) + '">' + (x.mine ? esc(x.name) + " " : "") + (pos ? "+" : "") + x.points.toFixed(1) + " pts</span>";
    }).join("");
    var mineScoring = p.scoring && (p.fantasy || []).some(function (x) { return x.mine; });
    return '<div class="pbp-row' + (p.scoring ? " scoring" : "") + (mineScoring ? " mine" : "") + '"><span class="pbp-clock">' + (p.quarter ? "Q" + esc(p.quarter) + " " : "") + esc(p.clock || "") + "</span>" +
      '<span class="pbp-text">' + esc(playHeadline(p)) + "</span>" + f + "</div>";
  }

  function mineRows(d) {
    var out = [];
    ((d.box && d.box.teams) || []).forEach(function (t) { (t.players || []).forEach(function (p) { if (p.mine) out.push(p); }); });
    return out;
  }

  function mvp(d) {
    var best = null;
    ((d.box && d.box.teams) || []).forEach(function (t) {
      (t.players || []).forEach(function (p) { if (p.fantasy_points != null && (!best || p.fantasy_points > best.fantasy_points)) best = Object.assign({ teamName: t.name, teamAbbr: t.abbr }, p); });
    });
    return best;
  }

  function leaders(d, n) {
    var all = [];
    ((d.box && d.box.teams) || []).forEach(function (t) { (t.players || []).forEach(function (p) { if (p.fantasy_points != null) all.push(Object.assign({ teamAbbr: t.abbr }, p)); }); });
    return all.sort(function (a, b) { return b.fantasy_points - a.fantasy_points; }).slice(0, n);
  }

  // Your players' actual fantasy points in this game against what they were projected for.
  function audit(d) {
    var proj = {};
    (d.projections || []).forEach(function (p) { proj[p.name] = p.proj; });
    var rows = mineRows(d).map(function (p) { return { name: p.name, position: p.position, actual: p.fantasy_points || 0, proj: proj[p.name] == null ? null : proj[p.name] }; });
    var actual = rows.reduce(function (a, r) { return a + r.actual; }, 0);
    var projected = rows.reduce(function (a, r) { return a + (r.proj || 0); }, 0);
    return { rows: rows, actual: Math.round(actual * 10) / 10, projected: Math.round(projected * 10) / 10, delta: Math.round((actual - projected) * 10) / 10 };
  }

  function badgeHtml(g) {
    return g.badge ? '<span class="sb-badge ' + String(g.badge).toLowerCase() + '" title="' + esc(g.network || "Prime time") + '">' + esc(g.badge) + "</span>" : "";
  }

  function statusLine(g) {
    if (g.state === "in") return "Q" + g.period + " · " + (g.display_clock || "");
    return g.status_detail || (g.state === "post" ? "Final" : "");
  }

  // Your players in a game, on the right of the card: his head and projected points before kickoff, his current
  // fantasy points once the game is on or over. `mine` rows: {name, headshot, value, kind: "proj" | "pts", status}.
  function mineHtml(mine) {
    if (!mine || !mine.length) return "";
    var show = mine.slice(0, 4), more = mine.length - show.length;
    var img = function (p) {
      var src = p.headshot ? (typeof proxyImg === "function" ? proxyImg(p.headshot) : p.headshot) : null;
      var fb = typeof initialsAvatarUri === "function" ? initialsAvatarUri(p.name) : "";
      return '<img class="sb-face" src="' + esc(src || fb) + '"' + (fb ? ' data-fb="' + esc(fb) + '"' : "") + ' alt="">';
    };
    return '<div class="sb-mine" aria-label="Your players in this game">' + show.map(function (p) {
      var st = p.status ? '<span class="sb-p-st">' + esc(String(p.status).toUpperCase()) + "</span>" : "";
      return '<div class="sb-p" title="' + esc(p.name) + '">' + img(p) + '<b data-kind="' + esc(p.kind) + '">' + d1(p.value) + "</b><small>" + (p.kind === "pts" ? "pts" : "proj") + "</small>" + st + "</div>";
    }).join("") + (more > 0 ? '<div class="sb-more">+' + more + "</div>" : "") + "</div>";
  }

  function scorebugHtml(g, mineCount, flash, mine) {
    var h = theme(g.home.abbr), a = theme(g.away.abbr);
    var cls = "sb-card" + (g.state === "in" ? " live" : g.state === "post" ? " final" : " pre") + (mineCount ? " has-mine" : "") + (mine && mine.length ? " with-mine" : "");
    var row = function (t, side) {
      return '<div class="sb-team' + (t.winner ? " win" : "") + '">' + logo(t.abbr, "sb-logo") + '<span class="sb-abbr">' + esc(t.abbr) + "</span>" +
        '<span class="sb-score" data-side="' + side + '">' + (g.state === "pre" ? "" : t.score == null ? "–" : t.score) + "</span></div>";
    };
    var sit = g.state === "in" && g.situation ? '<div class="sb-sit' + (g.situation.is_red_zone ? " rz" : "") + '">' + esc(g.situation.text || "") + (g.situation.is_red_zone ? " · RED ZONE" : "") + "</div>" : "";
    return '<button type="button" class="' + cls + '" data-game="' + esc(g.game_id) + '" style="--c1:' + esc(a.primary) + ";--c2:" + esc(h.primary) + ";--s1:" + esc(a.secondary) + ";--s2:" + esc(h.secondary) + '" data-state="' + esc(g.state) + '">' +
      badgeHtml(g) + (g.state === "in" ? '<span class="sb-live"><i></i>LIVE</span>' : "") +
      '<div class="sb-body"><div class="sb-main">' + row(g.away, "away") + row(g.home, "home") +
      '<div class="sb-status">' + esc(statusLine(g)) + (g.network ? ' <span class="sb-net">' + esc(g.network) + "</span>" : "") + "</div>" + sit + "</div>" + mineHtml(mine) + "</div>" +
      (flash ? '<span class="sb-flash ' + flash + '"></span>' : "") + "</button>";
  }

  // The teams (nflverse codes) with a game on right now.
  function liveTeamKeys(list) {
    var out = [];
    (list || []).forEach(function (g) { if (g.state === "in") { out.push(key(g.home.abbr)); out.push(key(g.away.abbr)); } });
    return out;
  }

  function oddsBarHtml(o, g) {
    if (!o) return '<div class="gc-card"><div class="gc-h">Vegas</div><div class="muted">No betting line posted yet.</div></div>';
    var hi = o.home_implied, ai = o.away_implied, tot = (hi || 0) + (ai || 0);
    var split = tot ? Math.round((ai / tot) * 100) : 50;
    return '<div class="gc-card"><div class="gc-h">Vegas</div>' +
      '<div class="gc-odds-line"><b>' + (o.favorite ? esc(o.favorite) + " -" + o.spread : "Pick'em") + "</b><span>O/U <b>" + d1(o.total) + "</b></span></div>" +
      (hi != null ? '<div class="odds-bar"><i style="width:' + split + '%;background:' + esc(theme(g.away.abbr).primary) + '"></i><b style="background:' + esc(theme(g.home.abbr).primary) + '"></b></div>' +
        '<div class="odds-legend"><span>' + esc(g.away.abbr) + " <b>" + d1(ai) + '</b></span><span class="muted">implied totals</span><span>' + esc(g.home.abbr) + " <b>" + d1(hi) + "</b></span></div>" : "") + "</div>";
  }

  function weatherHtml(w) {
    if (!w) return '<div class="gc-card"><div class="gc-h">Weather</div><div class="muted">Not available yet.</div></div>';
    if (w.indoor && w.temp == null) return '<div class="gc-card"><div class="gc-h">Weather</div><div><b>Indoors</b> <span class="muted">roof or dome</span></div></div>';
    return '<div class="gc-card"><div class="gc-h">Weather</div><div class="gc-wx"><b>' + (w.temp == null ? "—" : w.temp + "°F") + "</b><span>" + esc(w.summary || "") + "</span></div>" +
      (w.wind != null ? '<div class="gc-wind' + (w.wind_alert ? " alert" : "") + '">Wind ' + w.wind + " mph" + (w.wind_alert ? " · wind alert: passing and kicking affected" : "") + "</div>" : "") +
      (w.precip ? '<div class="muted">' + w.precip + "% precipitation</div>" : "") + "</div>";
  }

  function injuriesHtml(inj) {
    var teams = Object.keys(inj || {});
    if (!teams.length) return '<div class="muted">No injury report posted.</div>';
    return teams.map(function (t) {
      return '<div class="gc-inj"><div class="gc-inj-team">' + logo(t, "gc-mini") + esc(t) + "</div>" + inj[t].slice(0, 8).map(function (p) {
        return '<div class="gc-inj-row"><span>' + esc(p.name) + ' <small>' + esc(p.position || "") + "</small></span><em class=\"st-" + esc(String(p.status || "").toLowerCase()) + '">' + esc(p.status || "") + (p.detail ? " · " + esc(p.detail) : "") + "</em></div>";
      }).join("") + "</div>";
    }).join("");
  }

  // How he is listed, from the app's shared renderer when it is loaded (BYE, QUESTIONABLE, OUT, IR, PUP...).
  function tagHtml(status, team) {
    if (typeof statusFlagsHtml === "function") return statusFlagsHtml({ injury_status: status, recent_team: team });
    return status ? ' <span class="injury-flag">' + esc(String(status).toUpperCase()) + "</span>" : "";
  }

  function projectionsHtml(list) {
    if (!list || !list.length) return '<div class="muted">None of your players are in this game.</div>';
    return list.map(function (p) {
      return '<div class="gc-proj"><span>' + esc(p.name) + " <small>" + esc(p.position) + " · " + esc(p.team) + (p.is_starter ? " · starting" : " · bench") + "</small>" + tagHtml(p.status, p.team) +
        "</span><b>" + d1(p.proj) + (p.floor != null ? " <small>" + Math.round(p.floor) + "–" + Math.round(p.ceiling) + "</small>" : "") + "</b></div>";
    }).join("");
  }

  function preHtml(d, g) {
    return '<div class="gc-count-wrap"><div class="gc-h">Kickoff in</div><div class="gc-count" id="gc-count" data-kick="' + esc(g.kickoff || "") + '">' + countdown(Date.parse(g.kickoff) - Date.now()) + "</div></div>" +
      '<div class="gc-two">' + weatherHtml(d.weather) + oddsBarHtml(d.odds, g) + "</div>" +
      '<div class="gc-card"><div class="gc-h">Your players in this game</div>' + projectionsHtml(d.projections) + "</div>" +
      '<div class="gc-card"><div class="gc-h">Injury report</div>' + injuriesHtml(d.injuries) + "</div>";
  }

  function liveHtml(d, g, boxHtml) {
    var sit = d.situation;
    var field = sit ? '<div class="fld-wrap' + (sit.is_red_zone ? " rz" : "") + '">' + fieldSvg(sit, g.home.abbr, g.away.abbr) +
      '<div class="fld-bar"><span class="fld-dd">' + esc(bannerText(sit, g)) + "</span>" + (sit.is_red_zone ? '<span class="fld-rzbadge">RED ZONE</span>' : "") + "</div></div>"
      : '<div class="gc-card"><div class="muted">Between drives. The field view returns when the next play is set.</div></div>';
    var wp = d.home_win_pct == null ? "" : '<div class="gc-wp"><span>' + esc(g.away.abbr) + " " + (100 - d.home_win_pct) + '%</span><div class="odds-bar"><i style="width:' + (100 - d.home_win_pct) + "%;background:" + esc(theme(g.away.abbr).primary) + '"></i><b style="background:' + esc(theme(g.home.abbr).primary) + '"></b></div><span>' + d.home_win_pct + "% " + esc(g.home.abbr) + "</span></div>";
    return field + wp + '<div class="gc-two"><div class="gc-card"><div class="gc-h">Play by play</div><div class="pbp" id="gc-pbp">' +
      ((d.plays || []).map(playRowHtml).join("") || '<div class="muted">No plays yet.</div>') + "</div></div>" +
      '<div class="gc-card"><div class="gc-h">Your players</div>' + mineLiveHtml(d) + "</div></div>" + boxHtml;
  }

  function mineLiveHtml(d) {
    var rows = mineRows(d);
    if (!rows.length) return '<div class="muted">None of your players are in this game.</div>';
    return rows.map(function (p) { return '<div class="gc-proj"><span>' + esc(p.name) + " <small>" + esc(p.position) + "</small></span><b>" + d1(p.fantasy_points) + "</b></div>"; }).join("") +
      '<div class="gc-proj total"><span>Total so far</span><b>' + d1(d.box && d.box.mine_points) + "</b></div>";
  }

  function postHtml(d, g, boxHtml) {
    var m = mvp(d), a = audit(d);
    var champ = g.away.winner ? g.away : g.home.winner ? g.home : null;
    var banner = m ? '<div class="gc-mvp"><span class="gc-mvp-tag">Game MVP</span><b>' + esc(m.name) + '</b><span>' + esc(m.position) + " · " + esc(m.teamAbbr) + " · " + d1(m.fantasy_points) + " fantasy pts</span></div>" : "";
    var lead = leaders(d, 5).map(function (p) { return '<div class="gc-proj"><span>' + esc(p.name) + " <small>" + esc(p.position) + " · " + esc(p.teamAbbr) + "</small></span><b>" + d1(p.fantasy_points) + "</b></div>"; }).join("");
    var aud = a.rows.length ? '<div class="gc-audit"><div class="gc-audit-total ' + (a.delta >= 0 ? "up" : "dn") + '"><b>' + d1(a.actual) + '</b><span>pts for your matchup · projected ' + d1(a.projected) + " (" + (a.delta >= 0 ? "+" : "") + d1(a.delta) + ")</span></div>" +
      a.rows.map(function (r) { return '<div class="gc-proj"><span>' + esc(r.name) + " <small>" + esc(r.position) + "</small></span><b>" + d1(r.actual) + (r.proj != null ? ' <small>proj ' + d1(r.proj) + "</small>" : "") + "</b></div>"; }).join("") + "</div>"
      : '<div class="muted">None of your players were in this game.</div>';
    return (champ ? '<div class="gc-final">Final · ' + esc(champ.abbr) + " win</div>" : '<div class="gc-final">Final</div>') + banner +
      '<div class="gc-two"><div class="gc-card"><div class="gc-h">Fantasy impact audit</div>' + aud + '</div><div class="gc-card"><div class="gc-h">Top fantasy scorers</div>' + (lead || '<div class="muted">No stats posted.</div>') + "</div></div>" + boxHtml;
  }

  var LiveTab = { sortGames: sortGames, scoreChange: scoreChange, countdown: countdown, fieldX: fieldX, fieldSvg: fieldSvg, bannerText: bannerText,
    playHeadline: playHeadline, liveTeamKeys: liveTeamKeys, mineHtml: mineHtml, playRowHtml: playRowHtml, scorebugHtml: scorebugHtml, preHtml: preHtml, liveHtml: liveHtml, postHtml: postHtml,
    audit: audit, mvp: mvp, leaders: leaders, oddsBarHtml: oddsBarHtml, weatherHtml: weatherHtml, key: key };
  if (typeof window !== "undefined") window.LiveTab = LiveTab;
  if (typeof module !== "undefined") module.exports = LiveTab;
  if (typeof document === "undefined" || typeof window === "undefined" || !window.document.getElementById) return;

  // -------------------------------------------------------------- browser ----
  var games = [], lastScores = {}, flashes = {}, poll = null, gcTimer = null, gcTick = null, gcGame = null, gcOrigin = null;
  function $(s) { return document.querySelector(s); }
  function reduced() { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }
  function mineCount(g) {
    var m = (typeof state !== "undefined" && state.myTeamAbbrs) || {};
    return (m[key(g.away.abbr)] || 0) + (m[key(g.home.abbr)] || 0);
  }

  var roster = [], boxes = {}, rosterAt = 0;

  // Your roster players in one game, as scorebug rows: projections before kickoff, his points once it is on.
  function mineFor(g) {
    var keys = [key(g.home.abbr), key(g.away.abbr)];
    if (g.state === "pre") {
      return roster.filter(function (p) { return keys.indexOf(key(p.recent_team)) !== -1; })
        .map(function (p) { return { name: p.player_display_name, headshot: p.headshot_url, value: p.PROJ, kind: "proj", status: p.injury_status || null, starter: !!p.is_starter }; })
        .sort(function (a, b) { return (b.starter - a.starter) || ((b.value || 0) - (a.value || 0)); });
    }
    var box = boxes[g.game_id];
    var fromBox = [];
    ((box && box.teams) || []).forEach(function (t) {
      (t.players || []).forEach(function (p) { if (p.mine) fromBox.push({ name: p.name, headshot: p.headshot, value: p.fantasy_points == null ? 0 : p.fantasy_points, kind: "pts", status: null }); });
    });
    if (fromBox.length) return fromBox.sort(function (a, b) { return b.value - a.value; });
    return roster.filter(function (p) { return keys.indexOf(key(p.recent_team)) !== -1; })     // box score not in yet
      .map(function (p) { return { name: p.player_display_name, headshot: p.headshot_url, value: null, kind: "pts", status: p.injury_status || null }; });
  }

  function renderGrid(animate) {
    var grid = $("#live-grid");
    if (!grid) return;
    if (!games.length) { grid.innerHTML = '<div class="empty">No games on the schedule right now.</div>'; return; }
    var sorted = sortGames(games), out = "", last = null;
    var labels = { in: "On now", pre: "Upcoming", post: "Final" };
    sorted.forEach(function (g) {
      if (g.state !== last) { out += '<div class="lv-sec">' + (labels[g.state] || "Games") + "</div>"; last = g.state; }
      out += scorebugHtml(g, mineCount(g), flashes[g.game_id], mineFor(g));
    });
    grid.innerHTML = out;
    grid.classList.toggle("lv-enter", !!animate);
  }

  // The red marker in the sidebar whenever any game is on.
  function updateNavDot() {
    var dot = $("#nav-live-dot");
    if (!dot) return;
    var on = games.some(function (g) { return g.state === "in"; });
    dot.hidden = !on;
    dot.setAttribute("aria-label", on ? "A game is on now" : "");
  }

  // Box scores for the on-now and final games that have one of your players (finals are fetched once).
  async function loadBoxes() {
    var need = games.filter(function (g) { return mineCount(g) && (g.state === "in" || (g.state === "post" && !boxes[g.game_id])); });
    if (!need.length) return;
    var qs = typeof scoringQS === "function" ? scoringQS().replace(/^&/, "") : "";
    await Promise.all(need.map(async function (g) {
      try { boxes[g.game_id] = await api("/api/live-scores/" + encodeURIComponent(g.game_id) + (qs ? "?" + qs : "")); } catch (e) { /* the card keeps its placeholders */ }
    }));
  }

  async function loadRoster() {
    if (typeof state === "undefined" || !state.user || Date.now() - rosterAt < 120000) return;
    rosterAt = Date.now();
    try {
      var d = await api("/api/myteam");
      roster = d.my_team.players || [];
      state.myTeamAbbrs = rosterTeamCounts(d.my_team);
    } catch (e) { /* no league connected: nothing is highlighted */ }
  }

  function bounce(card, side) {
    if (reduced() || !card || !card.animate) return;
    card.animate([{ transform: "scale(1)" }, { transform: "scale(1.04)" }, { transform: "scale(1)" }], { duration: 520, easing: "ease-out" });
    var fl = card.querySelector(".sb-flash");
    if (fl && fl.animate) fl.animate([{ opacity: 0.85 }, { opacity: 0 }], { duration: 1400, easing: "ease-out" });
  }

  async function load(quiet) {
    var grid = $("#live-grid");
    if (!grid) return;
    if (!games.length && !quiet) grid.innerHTML = '<div class="lv-skel">' + '<div class="skel sb-skel"></div>'.repeat(6) + "</div>";
    try {
      await loadRoster();
      var data = await api("/api/live-scores");
      var next = data.games || [];
      var changed = [];
      next.forEach(function (g) {
        var side = scoreChange(lastScores[g.game_id], g);
        lastScores[g.game_id] = g.away.score + "-" + g.home.score;
        if (side) { flashes[g.game_id] = side; changed.push(g.game_id); }
      });
      games = next;
      updateNavDot();
      await loadBoxes();
      renderGrid(!quiet);
      changed.forEach(function (id) {
        bounce(document.querySelector('.sb-card[data-game="' + id + '"]'), flashes[id]);
        setTimeout(function () { delete flashes[id]; var f = document.querySelector('.sb-card[data-game="' + id + '"] .sb-flash'); if (f) f.remove(); }, 1600);
      });
      var live = games.filter(function (g) { return g.state === "in"; }).length;
      var hint = $("#live-hint");
      if (hint) hint.textContent = live ? live + " game" + (live === 1 ? "" : "s") + " live now. Tap one for the full stadium view." : "Every game this week. Tap one for the full stadium view.";
    } catch (e) {
      if (!games.length) grid.innerHTML = '<div class="empty">Couldn\'t load the scoreboard. Try again in a moment.</div>';
    }
  }

  // ------------------------------------------------------------ deep dive ----
  function headerHtml(g) {
    var a = theme(g.away.abbr), h = theme(g.home.abbr);
    var side = function (t, th) { return '<div class="gc-team' + (t.winner ? " win" : "") + '">' + logo(t.abbr, "gc-logo") + '<div class="gc-tname">' + esc(t.name || t.abbr) + '</div><div class="gc-tscore">' + (g.state === "pre" ? "" : t.score == null ? "–" : t.score) + "</div></div>"; };
    return '<div class="gc-head" style="--c1:' + esc(a.primary) + ";--c2:" + esc(h.primary) + '"><button type="button" class="gc-back" id="gc-back" aria-label="Back to all games">‹ All games</button>' +
      badgeHtml(g) + '<div class="gc-scoreline">' + side(g.away, a) + '<div class="gc-mid"><div class="gc-status">' + esc(statusLine(g)) + "</div>" + (g.network ? '<div class="sb-net">' + esc(g.network) + "</div>" : "") + "</div>" + side(g.home, h) + "</div></div>";
  }

  function boxSection(d) {
    return typeof gameBodyHtml === "function" && d.box ? '<div class="gc-card gc-box"><div class="gc-h">Box score</div>' + gameBodyHtml(d.box) + "</div>" : "";
  }

  function renderBody(d) {
    var g = Object.assign({}, gcGame, d.game || {});
    g.home = Object.assign({}, gcGame.home, (d.game || {}).home); g.away = Object.assign({}, gcGame.away, (d.game || {}).away);
    var body = $("#gc-body");
    if (!body) return;
    var box = boxSection(d);
    var scroll = body.scrollTop;
    body.innerHTML = g.state === "pre" ? preHtml(d, g) : g.state === "in" ? liveHtml(d, g, box) : postHtml(d, g, box);
    body.scrollTop = scroll;
    var head = $(".gc-head");
    if (head) head.outerHTML = headerHtml(g);
    clearInterval(gcTick);
    var c = $("#gc-count");
    if (c) gcTick = setInterval(function () { var el = $("#gc-count"); if (!el) return clearInterval(gcTick); el.textContent = countdown(Date.parse(el.dataset.kick) - Date.now()); }, 1000);
  }

  async function refreshGame() {
    if (!gcGame) return;
    try {
      var qs = scoringQS().replace(/^&/, "");
      renderBody(await api("/api/live-scores/" + encodeURIComponent(gcGame.game_id) + "/center" + (qs ? "?" + qs : "")));
    } catch (e) {
      var b = $("#gc-body");
      if (b && !b.querySelector(".gc-card")) b.innerHTML = '<div class="empty">Couldn\'t load this game. Try again in a moment.</div>';
    }
  }

  function openGame(id, origin) {
    var g = games.filter(function (x) { return String(x.game_id) === String(id); })[0];
    var root = $("#gc-root");
    if (!g || !root) return;
    gcGame = g; gcOrigin = origin || null;
    root.innerHTML = '<div class="gc-backdrop"><section class="gc-panel" role="dialog" aria-modal="true" aria-label="Game center">' + headerHtml(g) +
      '<div class="gc-body" id="gc-body"><div class="gc-skel">' + '<div class="skel gc-skel-row"></div>'.repeat(5) + "</div></div></section></div>";
    document.body.classList.add("gc-open");
    var panel = root.querySelector(".gc-panel");
    if (origin && !reduced() && panel.animate) {      // the card grows into the dashboard (and shrinks back on close)
      var a = origin.getBoundingClientRect(), b = panel.getBoundingClientRect();
      panel.animate([{ transformOrigin: "top left", transform: "translate(" + (a.left - b.left) + "px," + (a.top - b.top) + "px) scale(" + a.width / b.width + "," + a.height / b.height + ")", borderRadius: "18px", opacity: 0.4 },
        { transformOrigin: "top left", transform: "none", borderRadius: "0px", opacity: 1 }], { duration: 380, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    clearInterval(gcTimer);
    refreshGame();
    if (g.state === "in") gcTimer = setInterval(function () { if (!document.hidden) refreshGame(); }, 15000);
  }

  function closeGame() {
    var root = $("#gc-root"), panel = root && root.querySelector(".gc-panel");
    clearInterval(gcTimer); clearInterval(gcTick);
    var done = function () { root.innerHTML = ""; document.body.classList.remove("gc-open"); gcGame = null; };
    var origin = gcOrigin && document.body.contains(gcOrigin) ? gcOrigin : null;
    if (panel && origin && !reduced() && panel.animate) {
      var a = origin.getBoundingClientRect(), b = panel.getBoundingClientRect();
      var an = panel.animate([{ transformOrigin: "top left", transform: "none", opacity: 1 },
        { transformOrigin: "top left", transform: "translate(" + (a.left - b.left) + "px," + (a.top - b.top) + "px) scale(" + a.width / b.width + "," + a.height / b.height + ")", opacity: 0.2 }], { duration: 260, easing: "ease-in", fill: "forwards" });
      an.onfinish = done;
      setTimeout(done, 400);
    } else done();
  }

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var card = t.closest(".sb-card[data-game]");
    if (card && card.closest("#live-grid")) { openGame(card.dataset.game, card); return; }
    if (t.closest("#gc-back")) closeGame();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && gcGame) { e.stopPropagation(); closeGame(); } }, true);

  LiveTab.load = load;
  LiveTab.openGame = openGame;
  LiveTab.close = closeGame;
  LiveTab.liveTeams = function () { return liveTeamKeys(games); };
  // A light poll keeps the sidebar marker and Start/Sit's live tags honest on every tab: every 20 s on this tab, a
  // minute elsewhere, never in a hidden tab.
  LiveTab.init = function () {
    clearInterval(poll);
    var n = 0;
    poll = setInterval(function () {
      if (document.hidden || typeof state === "undefined") return;
      n++;
      if (state.tab === "live") load(true);
      else if (state.user !== undefined && n % 3 === 0) refreshDotOnly();
    }, 20000);
    refreshDotOnly();
  };

  async function refreshDotOnly() {
    try { games = (await api("/api/live-scores")).games || []; updateNavDot(); } catch (e) { /* leave the marker as it was */ }
  }
})();
