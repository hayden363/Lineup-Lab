// The team page: a technical, dashboard-style view of one NFL team built from /api/team/{code}. Pure markup builders
// (no DOM access), so they run under node for tests; app.js passes in its own helpers.
(function () {
  "use strict";

  // NFL-average reference marks for the gauges, and the top of each gauge's scale.
  var RATES = [
    ["Points / game", "points_for_pg", 22.5, 40, true],
    ["Allowed / game", "points_against_pg", 22.5, 40, false],
    ["Pass yds / game", "pass_yds_pg", 225, 350, true],
    ["Rush yds / game", "rush_yds_pg", 115, 200, true]
  ];

  function dateLabel(iso) {
    var d = new Date(String(iso).slice(0, 10) + "T12:00:00");
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  }

  // One bar per played game: up for a win, down for a loss, sized by the margin, around a center line.
  function marginChart(games, env) {
    var played = (games || []).filter(function (g) { return g.result; });
    if (!played.length) return "";
    var max = Math.max.apply(null, played.map(function (g) { return Math.abs(g.team_score - g.opp_score); }).concat([7]));
    var w = 28, h = 90, mid = h / 2;
    var bars = played.map(function (g, i) {
      var m = g.team_score - g.opp_score, bh = Math.max(3, Math.round((Math.abs(m) / max) * (mid - 6)));
      var cls = g.result === "W" ? "tpx-w" : g.result === "L" ? "tpx-l" : "tpx-t";
      var y = m >= 0 ? mid - bh : mid;
      return '<rect class="' + cls + '" x="' + (i * w + 4) + '" y="' + y + '" width="20" height="' + bh + '" rx="3"><title>Wk ' + g.week + ": " + g.result + " " + g.team_score + "–" + g.opp_score +
        " " + (g.home ? "vs" : "@") + " " + env.esc(g.opponent) + "</title></rect>" +
        '<text x="' + (i * w + 14) + '" y="' + (h + 12) + '" text-anchor="middle" class="tpx-wk">' + g.week + "</text>";
    }).join("");
    return '<svg class="tpx-chart" style="width:' + Math.max(played.length * 46, 120) + 'px" viewBox="0 0 ' + Math.max(played.length * w, 60) + " " + (h + 16) + '" role="img" aria-label="Margin of victory by week"><line x1="0" x2="' + (played.length * w) + '" y1="' + mid + '" y2="' + mid + '" class="tpx-axis"/>' + bars + "</svg>";
  }

  function gameRow(g, env) {
    var res = g.result, score = res ? g.team_score + "–" + g.opp_score : "—";
    return '<div class="tpx-game ' + (res ? "res-" + res.toLowerCase() : "res-pending") + '"><span class="tpx-gwk">Wk ' + g.week + '</span><span class="tpx-gopp">' + (g.home ? "vs" : "@") + " " + env.esc(g.opponent) +
      '</span><span class="tpx-gscore">' + score + '</span><span class="tpx-gres">' + (res || "·") + "</span></div>";
  }

  function rateTile(label, value, avg, top, higherBetter, env) {
    var pct = value == null ? 0 : Math.max(2, Math.min(100, Math.round((value / top) * 100)));
    var tick = Math.round((avg / top) * 100);
    var good = value == null ? "" : ((value >= avg) === higherBetter ? " good" : " bad");
    return '<div class="tpx-tile"><span class="tpx-k">' + label + '</span><b class="tpx-v">' + (value == null ? "—" : env.d1(value)) + '</b><div class="tpx-gauge"><i class="' + good.trim() + '" style="width:' + pct + '%"></i><span class="tpx-avg" style="left:' + tick + '%" title="NFL average"></span></div></div>';
  }

  function html(d, env) {
    var th = env.theme || {}, n = d.next_game, s = d.stats || {};
    var diff = (d.points_for || 0) - (d.points_against || 0);
    var line = "";
    if (n && n.spread != null && n.spread !== 0) line = " · " + (n.spread < 0 ? d.team : n.opponent) + " -" + Math.abs(n.spread);
    var ribbon = n
      ? '<div class="tpx-next"><span class="tpx-tag">NEXT</span><b>Wk ' + n.week + " · " + env.esc(dateLabel(n.date)) + " · " + (n.home ? "vs" : "@") + " " + env.esc(n.opponent) + "</b>" +
        '<span class="tpx-meta">' + env.esc(line.replace(/^ · /, "")) + (n.total != null ? (line ? " · " : "") + "O/U " + env.d1(n.total) : "") + "</span>" +
        (n.implied_total != null ? '<span class="tpx-meta">Expected score ' + env.d1(n.implied_total) + "–" + env.d1(n.opp_implied_total) + "</span>" : "") + "</div>"
      : '<div class="tpx-next"><span class="tpx-tag">NEXT</span><span class="muted">No upcoming game on the schedule.</span></div>';
    var maxProj = Math.max.apply(null, (d.players || []).map(function (p) { return p.proj || 0; }).concat([1]));
    var players = (d.players || []).map(function (p, i) {
      return '<button type="button" class="tpx-player" data-player="' + env.esc(p.player_id) + '"' + (n ? ' data-opp="' + env.esc(n.opponent) + '"' : "") + '>' +
        '<span class="tpx-rank">' + (i + 1) + '</span><img class="tpx-photo" ' + env.headshotAttrs({ headshot_url: p.headshot_url, player_display_name: p.name }) + ' alt="" loading="lazy">' +
        '<span class="tpx-pname">' + env.esc(p.name) + env.statusFlags(Object.assign({}, p, { recent_team: d.team })) + "<small>" + env.esc(p.position) + "</small></span>" +
        '<span class="tpx-bar"><i style="width:' + Math.round(((p.proj || 0) / maxProj) * 100) + '%"></i></span>' +
        '<span class="tpx-num"><b>' + (p.proj != null ? env.d1(p.proj) : "—") + "</b><small>proj</small></span>" +
        '<span class="tpx-num"><b>' + env.d1(p.ppg) + "</b><small>avg</small></span></button>";
    }).join("");
    var games = (d.games || []).map(function (g) { return gameRow(g, env); }).join("");
    return '<div class="tpx" style="--tc:' + env.esc(th.primary || "#38bdf8") + ";--ts:" + env.esc(th.secondary || "#94a3b8") + '">' +
      '<div class="tpx-hero">' + (d.logo ? '<img class="tpx-logo" src="' + env.proxyImg(d.logo) + '" data-fb-hide="1" alt="">' : "") +
      '<div class="tpx-id"><span class="tpx-city">' + env.esc(String(th.city || "").toUpperCase()) + '</span><h2 class="tpx-name">' + env.esc(String(th.name || d.team).toUpperCase()) + '</h2><span class="tpx-div">' + env.esc(th.division || "") + "</span></div>" +
      '<div class="tpx-rec"><b>' + env.esc(d.record.text) + '</b><span>RECORD</span></div>' +
      '<div class="tpx-pts"><div><b>' + d.points_for + "</b><span>PF</span></div><div><b>" + d.points_against + "</b><span>PA</span></div><div class=\"" + (diff >= 0 ? "pos" : "neg") + '"><b>' + (diff >= 0 ? "+" : "") + diff + "</b><span>DIFF</span></div></div></div>" +
      ribbon +
      '<div class="tpx-tiles">' + RATES.map(function (r) { return rateTile(r[0], s[r[1]], r[2], r[3], r[4], env); }).join("") + "</div>" +
      '<div class="tpx-card"><div class="tpx-h">Season results</div>' + marginChart(d.games, env) + '<div class="tpx-games">' + (games || '<div class="muted">No games yet.</div>') + "</div></div>" +
      '<div class="tpx-card"><div class="tpx-h">Players' + (n ? " · projected for Week " + n.week : "") + '</div><div class="tpx-players">' + (players || '<div class="muted">No player data yet.</div>') + "</div></div></div>";
  }

  var TeamPageUI = { html: html, marginChart: marginChart };
  if (typeof window !== "undefined") window.TeamPageUI = TeamPageUI;
  if (typeof module !== "undefined") module.exports = TeamPageUI;
})();
