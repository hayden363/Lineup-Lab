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
  // A team-colored badge with its letters, used wherever the real logo cannot load.
  function badgeUri(abbr) {
    var t = theme(abbr);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" rx="18" fill="' + t.primary + '"/><text x="50%" y="54%" font-family="ui-monospace,monospace" font-size="28" font-weight="800" fill="' +
      (t.onPrimary || "#fff") + '" text-anchor="middle" dominant-baseline="middle">' + String(abbr || "").slice(0, 3).toUpperCase() + "</text></svg>";
    return "data:image/svg+xml," + encodeURIComponent(svg);
  }
  function logo(abbr, cls) {
    var t = theme(abbr);
    return '<img class="' + cls + '" src="' + (t.logo ? "/api/img?url=" + encodeURIComponent(t.logo) : badgeUri(abbr)) + '" data-fb="' + badgeUri(abbr) + '" alt="">';
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

  // "Sun, Nov 1, 1:00 PM EST": the kickoff in the viewer's own time zone.
  function kickoffText(g) {
    var d = new Date(g && g.kickoff);
    if (isNaN(d)) return (g && g.status_detail) || "";
    return d.toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  }

  function signed(n) { return n == null ? "" : (n > 0 ? "+" : "") + n; }

  // "DET -3.5 · O/U 48.0" from the betting line.
  function oddsLine(o) {
    if (!o) return "";
    var parts = [];
    if (o.favorite) parts.push(o.favorite + " -" + o.spread);
    else if (o.spread === 0) parts.push("Pick'em");
    if (o.total != null) parts.push("O/U " + d1(o.total));
    return parts.join(" \u00b7 ");
  }

  // Which side covered the spread in a finished game, or null without a line.
  function coverNote(g) {
    var o = g.odds;
    if (g.state !== "post" || !o || !o.favorite || g.home.score == null || g.away.score == null) return "";
    var favHome = key(o.favorite) === key(g.home.abbr);
    var margin = (favHome ? g.home.score - g.away.score : g.away.score - g.home.score);
    if (margin === o.spread) return "Push";
    return (margin > o.spread ? o.favorite : (favHome ? g.away.abbr : g.home.abbr)) + " covered";
  }

  function isFavGame(g, fav) { return !!fav && (key(g.home.abbr) === fav || key(g.away.abbr) === fav); }

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

  function scorebugHtml(g, mineCount, flash, mine, fav) {
    var h = theme(g.home.abbr), a = theme(g.away.abbr), isFav = isFavGame(g, fav);
    var cls = "sb-card" + (g.state === "in" ? " live" : g.state === "post" ? " final" : " pre") + (mineCount ? " has-mine" : "") + (mine && mine.length ? " with-mine" : "") + (isFav ? " sb-fav" : "");
    var row = function (t, side) {
      var mineSide = fav && key(t.abbr) === fav;
      return '<div class="sb-team' + (t.winner ? " win" : "") + (mineSide ? " fav" : "") + '">' + logo(t.abbr, "sb-logo") + '<span class="sb-abbr">' + esc(t.abbr) + "</span>" +
        (t.record ? '<span class="sb-rec">' + esc(t.record) + "</span>" : "") +
        '<span class="sb-score" data-side="' + side + '">' + (g.state === "pre" ? "" : t.score == null ? "–" : t.score) + "</span></div>";
    };
    var sit = g.state === "in" && g.situation ? '<div class="sb-sit' + (g.situation.is_red_zone ? " rz" : "") + '">' + esc(g.situation.text || "") + (g.situation.is_red_zone ? " · RED ZONE" : "") + "</div>" : "";
    var line = oddsLine(g.odds), cover = coverNote(g);
    var when = g.state === "pre" ? kickoffText(g) : statusLine(g);
    var top = '<div class="sb-top"><span class="sb-tl">' + (g.state === "in" ? '<span class="sb-live"><i></i>LIVE</span>' : "") + (isFav ? '<span class="sb-ribbon">\u2605 YOUR TEAM</span>' : "") + "</span>" + badgeHtml(g) + "</div>";
    return '<button type="button" class="' + cls + '" data-game="' + esc(g.game_id) + '" style="--c1:' + esc(a.primary) + ";--c2:" + esc(h.primary) + ";--s1:" + esc(a.secondary) + ";--s2:" + esc(h.secondary) + '" data-state="' + esc(g.state) + '">' +
      (isFav ? '<span class="sb-crest" aria-hidden="true">' + logo(fav, "sb-crest-img") + "</span>" : "") + top +
      '<div class="sb-body"><div class="sb-main">' + row(g.away, "away") + row(g.home, "home") +
      '<div class="sb-status">' + esc(when) + (g.network ? ' <span class="sb-net">' + esc(g.network) + "</span>" : "") + "</div>" + sit +
      (line ? '<div class="sb-line">' + esc(line) + (cover ? ' <b class="sb-cover">' + esc(cover) + "</b>" : "") + "</div>" : "") + "</div>" + mineHtml(mine) + "</div>" +
      (flash ? '<span class="sb-flash ' + flash + '"></span>' : "") + "</button>";
  }

  // Sections of the grid: your team's game first, then what is on, upcoming and final. `filter`: all | fav | mine.
  function gridSections(list, fav, filter, mineFn) {
    var pool = list.slice();
    if (filter === "fav") pool = pool.filter(function (g) { return isFavGame(g, fav); });
    if (filter === "mine") pool = pool.filter(function (g) { return mineFn(g) > 0; });
    var sections = [], favGames = pool.filter(function (g) { return isFavGame(g, fav); }), rest = pool.filter(function (g) { return !isFavGame(g, fav); });
    if (favGames.length) sections.push({ label: "Your team", games: sortGames(favGames), fav: true });
    var labels = { in: "On now", pre: "Upcoming", post: "Final" };
    ["in", "pre", "post"].forEach(function (st) {
      var gs = sortGames(rest.filter(function (g) { return g.state === st; }));
      if (gs.length) sections.push({ label: labels[st], games: gs });
    });
    return sections;
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

  // ---- the game header (every state): both teams with their records, the score or the kickoff time ----
  function headerHtml(g, fav) {
    var a = theme(g.away.abbr), h = theme(g.home.abbr);
    var side = function (t) {
      var mineSide = fav && key(t.abbr) === fav;
      return '<div class="gc-team' + (t.winner ? " win" : "") + (mineSide ? " fav" : "") + '">' + logo(t.abbr, "gc-logo") +
        '<div class="gc-tinfo"><div class="gc-tname">' + esc(t.name || t.abbr) + "</div>" + (t.record ? '<div class="gc-rec">' + esc(t.record) + "</div>" : "") +
        (mineSide ? '<span class="gc-ribbon">\u2605 YOUR TEAM</span>' : "") + '</div><div class="gc-tscore">' + (g.state === "pre" ? "" : t.score == null ? "–" : t.score) + "</div></div>";
    };
    var mid = g.state === "pre"
      ? '<div class="gc-status">KICKOFF</div><div class="gc-when">' + esc(kickoffText(g)) + "</div>"
      : '<div class="gc-status">' + esc(statusLine(g)) + "</div>";
    return '<div class="gc-head' + (isFavGame(g, fav) ? " has-fav" : "") + '" style="--c1:' + esc(a.primary) + ";--c2:" + esc(h.primary) + '"><button type="button" class="gc-back" id="gc-back" aria-label="Back to all games">\u2039 All games</button>' +
      badgeHtml(g) + '<div class="gc-scoreline">' + side(g.away) + '<div class="gc-mid">' + mid + (g.network ? '<div class="sb-net">' + esc(g.network) + "</div>" : "") + "</div>" + side(g.home) + "</div></div>";
  }

  // ---- pre-game dashboard ----
  var COMPARE_ROWS = [["Points per game", "pf_pg", true], ["Points allowed", "pa_pg", false], ["Passing yards", "pass_yds_pg", true], ["Rushing yards", "rush_yds_pg", true]];

  // Tug-of-war bars: each team's share of the pair, in its own color; the better side of each row is bold.
  function compareBarsHtml(m, g) {
    if (!m || !m.home || !m.away) return "";
    var ac = theme(g.away.abbr).primary, hc = theme(g.home.abbr).primary;
    var rows = COMPARE_ROWS.map(function (r) {
      var av = m.away[r[1]], hv = m.home[r[1]];
      if (av == null || hv == null) return "";
      var tot = (av + hv) || 1, aw = Math.round((av / tot) * 100);
      var better = av === hv ? "" : ((av > hv) === r[2] ? "away" : "home");
      return '<div class="cmp-row"><span class="cmp-v' + (better === "away" ? " best" : "") + '">' + d1(av) + '</span><div class="cmp-mid"><div class="cmp-lbl">' + r[0] +
        '</div><div class="cmp-bar"><i style="width:' + aw + "%;background:" + esc(ac) + '"></i><b style="background:' + esc(hc) + '"></b></div></div><span class="cmp-v' + (better === "home" ? " best" : "") + '">' + d1(hv) + "</span></div>";
    }).join("");
    return '<div class="gc-card"><div class="gc-h">Team comparison</div><div class="cmp-head"><span>' + logo(g.away.abbr, "gc-mini") + esc(g.away.abbr) + " " + esc((m.away.record) || "") + "</span><span>" + esc((m.home.record) || "") + " " + esc(g.home.abbr) + logo(g.home.abbr, "gc-mini") + "</span></div>" + (rows || '<div class="muted">No team stats yet.</div>') + "</div>";
  }

  // Last five results as pips plus a small bar chart of points scored.
  function formSideHtml(side, abbr) {
    var rec = (side && side.recent) || [];
    if (!rec.length) return '<div class="form-side"><div class="form-name">' + logo(abbr, "gc-mini") + esc(abbr) + '</div><div class="muted small">No games yet.</div></div>';
    var maxPts = Math.max.apply(null, rec.map(function (r) { return r.team_score || 0; }).concat([1]));
    var color = theme(abbr).primary;
    var bars = rec.map(function (r, i) {
      var hgt = Math.max(4, Math.round(((r.team_score || 0) / maxPts) * 38));
      return '<rect x="' + (i * 22) + '" y="' + (44 - hgt) + '" width="16" height="' + hgt + '" rx="3" fill="' + esc(color) + '" opacity="' + (r.result === "W" ? 1 : 0.45) + '"><title>Wk ' + r.week + ": " + r.team_score + "\u2013" + r.opp_score + "</title></rect>";
    }).join("");
    var pips = rec.map(function (r) {
      return '<span class="form-pip ' + String(r.result).toLowerCase() + '" title="Wk ' + r.week + " " + r.result + " " + r.team_score + "\u2013" + r.opp_score + (r.home ? " vs " : " @ ") + esc(r.opponent) + '">' + esc(r.result) + "</span>";
    }).join("");
    return '<div class="form-side"><div class="form-name">' + logo(abbr, "gc-mini") + esc(abbr) + '</div><div class="form-pips">' + pips + '</div><svg class="form-bars" viewBox="0 0 ' + (rec.length * 22) + ' 48" role="img" aria-label="Points scored, last ' + rec.length + ' games">' + bars + "</svg></div>";
  }

  function formHtml(m, g) {
    if (!m || !m.home || !m.away) return "";
    return '<div class="gc-card"><div class="gc-h">Recent form <span class="muted">last 5 · points scored</span></div><div class="gc-two form-two">' + formSideHtml(m.away, g.away.abbr) + formSideHtml(m.home, g.home.abbr) + "</div></div>";
  }

  function watchHtml(m, g) {
    if (!m || !m.home || !m.away) return "";
    var col = function (side, abbr) {
      var ps = (side.top_players || []).map(function (p) {
        var src = p.headshot_url ? (typeof proxyImg === "function" ? proxyImg(p.headshot_url) : p.headshot_url) : "";
        var fb = typeof initialsAvatarUri === "function" ? initialsAvatarUri(p.name) : "";
        return '<div class="watch-p"><img class="sb-face" src="' + esc(src || fb) + '"' + (fb ? ' data-fb="' + esc(fb) + '"' : "") + ' alt=""><span>' + esc(p.name) + " <small>" + esc(p.position) + '</small></span><b>' + d1(p.ppg) + " <small>ppg</small></b></div>";
      }).join("");
      return '<div><div class="form-name">' + logo(abbr, "gc-mini") + esc(abbr) + "</div>" + (ps || '<div class="muted small">No player data yet.</div>') + "</div>";
    };
    return '<div class="gc-card"><div class="gc-h">Players to watch</div><div class="gc-two">' + col(m.away, g.away.abbr) + col(m.home, g.home.abbr) + "</div></div>";
  }

  // Lineup Lab's own pick, with the market's view when there is a line.
  function predictionHtml(m, g, fav) {
    var p = m && m.prediction;
    var favInGame = isFavGame(g, fav);
    if (!p) return '<div class="gc-card gc-pick"><div class="gc-h">Lineup Lab pick</div><div class="muted">Lineup Lab needs a few games from both teams before it makes a pick (not enough games yet).</div></div>';
    var ac = theme(g.away.abbr).primary, hc = theme(g.home.abbr).primary;
    var winner = p.pick === "home" ? g.home : g.away, wpct = p.pick === "home" ? p.home_win_pct : p.away_win_pct;
    var wname = winner.name || winner.abbr, by = Math.abs(p.margin);
    var mk = "";
    if (p.vs_market) {
      var e = p.vs_market.margin_edge;
      mk = Math.abs(e) < 0.5 ? "Lineup Lab and the market agree on the margin."
        : "Lineup Lab is " + Math.abs(e).toFixed(1) + " pts " + (e > 0 ? "higher" : "lower") + " on " + g.home.abbr + " vs the market.";
    }
    var yours = favInGame ? '<div class="gc-fav">\u2605 Your team: the ' + esc(key(g.home.abbr) === fav ? g.home.name || g.home.abbr : g.away.name || g.away.abbr) + " have a " + (key(g.home.abbr) === fav ? p.home_win_pct : p.away_win_pct) + "% chance</div>" : "";
    return '<div class="gc-card gc-pick' + (favInGame ? " has-fav" : "") + '"><div class="gc-h">Lineup Lab pick</div>' + yours +
      '<div class="pick-score"><div class="pick-side"><span>' + esc(g.away.abbr) + '</span><b>' + d1(p.away_score) + '</b></div><span class="pick-dash">\u2014</span><div class="pick-side"><span>' + esc(g.home.abbr) + "</span><b>" + d1(p.home_score) + "</b></div></div>" +
      '<div class="pick-call">' + esc(wname) + " by " + by.toFixed(1) + " <span>(" + wpct + "% to win)</span></div>" +
      '<div class="pick-bar"><i style="width:' + p.away_win_pct + "%;background:" + esc(ac) + '"></i><b style="background:' + esc(hc) + '"></b></div>' +
      '<div class="odds-legend"><span>' + esc(g.away.abbr) + " <b>" + p.away_win_pct + '%</b></span><span class="muted">win probability</span><span>' + esc(g.home.abbr) + " <b>" + p.home_win_pct + "%</b></span></div>" +
      (mk ? '<div class="pick-mk">' + esc(mk) + "</div>" : "") +
      '<div class="muted small">Built from each team\'s scoring and defense this season' + (p.used_market ? ", blended with the betting line" : "") + ". An estimate, not a guarantee.</div></div>";
  }

  function mlText(v) { return v == null ? "" : (v > 0 ? "+" : "") + v; }

  // Current odds: spread and moneyline for each side, the total and each side's implied score.
  function oddsFullHtml(o, g) {
    if (!o) return '<div class="gc-card"><div class="gc-h">Odds</div><div class="muted">No betting line posted yet.</div></div>';
    var hs = o.favorite ? (key(o.favorite) === key(g.home.abbr) ? -o.spread : o.spread) : 0, as = o.favorite ? -hs : 0;
    var spreadTxt = function (abbr, v) { return esc(abbr) + " " + (o.favorite ? (v < 0 ? "-" + Math.abs(v) : "+" + Math.abs(v)) : "PK"); };
    var hi = o.home_implied, ai = o.away_implied, tot = (hi || 0) + (ai || 0), split = tot ? Math.round((ai / tot) * 100) : 50;
    return '<div class="gc-card gc-odds"><div class="gc-h">Odds <span class="muted">current line</span></div>' +
      '<div class="odds-grid"><div class="odds-team">' + logo(g.away.abbr, "gc-mini") + '<b class="odds-spread">' + spreadTxt(g.away.abbr, as) + '</b><span class="odds-ml">' + esc(mlText(o.away_ml)) + '</span></div>' +
      '<div class="odds-ou"><small>O/U</small><b>' + d1(o.total) + '</b></div>' +
      '<div class="odds-team r"><span class="odds-ml">' + esc(mlText(o.home_ml)) + '</span><b class="odds-spread">' + spreadTxt(g.home.abbr, hs) + "</b>" + logo(g.home.abbr, "gc-mini") + "</div></div>" +
      (hi != null ? '<div class="odds-bar"><i style="width:' + split + "%;background:" + esc(theme(g.away.abbr).primary) + '"></i><b style="background:' + esc(theme(g.home.abbr).primary) + '"></b></div>' +
        '<div class="odds-legend"><span>' + esc(g.away.abbr) + " <b>" + d1(ai) + '</b></span><span class="muted">implied totals</span><span>' + esc(g.home.abbr) + " <b>" + d1(hi) + "</b></span></div>" : "") + "</div>";
  }

  function preHtml(d, g, fav) {
    var m = d.matchup || null;
    return predictionHtml(m, g, fav) +
      '<div class="gc-two">' + oddsFullHtml(d.odds, g) + weatherHtml(d.weather) + "</div>" +
      compareBarsHtml(m, g) + formHtml(m, g) + watchHtml(m, g) +
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

  var LiveTab = { sortGames: sortGames, scoreChange: scoreChange, fieldX: fieldX, fieldSvg: fieldSvg, bannerText: bannerText,
    playHeadline: playHeadline, liveTeamKeys: liveTeamKeys, mineHtml: mineHtml, playRowHtml: playRowHtml, scorebugHtml: scorebugHtml, preHtml: preHtml, headerHtml: headerHtml, gridSections: gridSections, kickoffText: kickoffText, predictionHtml: predictionHtml, oddsFullHtml: oddsFullHtml, compareBarsHtml: compareBarsHtml, coverNote: coverNote, liveHtml: liveHtml, postHtml: postHtml,
    audit: audit, mvp: mvp, leaders: leaders, oddsBarHtml: oddsBarHtml, weatherHtml: weatherHtml, key: key };
  if (typeof window !== "undefined") window.LiveTab = LiveTab;
  if (typeof module !== "undefined") module.exports = LiveTab;
  if (typeof document === "undefined" || typeof window === "undefined" || !window.document.getElementById) return;

  // -------------------------------------------------------------- browser ----
  var games = [], lastScores = {}, flashes = {}, poll = null, gcTimer = null, gcGame = null, gcOrigin = null;
  function $(s) { return document.querySelector(s); }
  function reduced() { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }
  function mineCount(g) {
    var m = (typeof state !== "undefined" && state.myTeamAbbrs) || {};
    return (m[key(g.away.abbr)] || 0) + (m[key(g.home.abbr)] || 0);
  }

  var roster = [], boxes = {}, rosterAt = 0, filter = "all";
  function favKey() { return typeof TeamTheme !== "undefined" && TeamTheme.current() ? key(TeamTheme.current()) : ""; }

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

  function renderFilters() {
    var host = $("#live-filters");
    if (!host) return;
    var fav = favKey(), t = fav && typeof TeamTheme !== "undefined" ? TeamTheme.get(fav) : null;
    var nFav = games.filter(function (g) { return isFavGame(g, fav); }).length, nMine = games.filter(function (g) { return mineCount(g) > 0; }).length;
    var chips = [["all", "All games", games.length]];
    if (t) chips.push(["fav", "\u2605 " + t.name, nFav]);
    if (nMine || (typeof state !== "undefined" && state.user)) chips.push(["mine", "My players", nMine]);
    if (!chips.some(function (c) { return c[0] === filter; })) filter = "all";
    host.innerHTML = chips.map(function (c) { return '<button type="button" class="lv-chip' + (c[0] === filter ? " on" : "") + (c[0] === "fav" ? " fav" : "") + '" data-filter="' + c[0] + '">' + esc(c[1]) + "<b>" + c[2] + "</b></button>"; }).join("");
  }

  function renderGrid(animate) {
    var grid = $("#live-grid");
    if (!grid) return;
    renderFilters();
    if (!games.length) { grid.innerHTML = '<div class="empty">No games on the schedule right now.</div>'; return; }
    var fav = favKey(), out = "";
    var sections = gridSections(games, fav, filter, mineCount);
    if (!sections.length) { grid.innerHTML = '<div class="empty">' + (filter === "mine" ? "None of your players are in a game this week." : "Your team isn't playing this week.") + "</div>"; return; }
    sections.forEach(function (sec) {
      out += '<div class="lv-sec' + (sec.fav ? " fav" : "") + '">' + sec.label + "</div>";
      sec.games.forEach(function (g) { out += scorebugHtml(g, mineCount(g), flashes[g.game_id], mineFor(g), fav); });
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

  function fxCall(name, arg) { try { if (window.ThemeFX) window.ThemeFX[name](arg); } catch (e) { /* the team strip is cosmetic */ } }

  async function loadRoster() {
    if (typeof state === "undefined" || !state.user || Date.now() - rosterAt < 120000) return;
    rosterAt = Date.now();
    try {
      var d = await api("/api/myteam");
      roster = d.my_team.players || [];
      state.myTeamAbbrs = rosterTeamCounts(d.my_team);
      fxCall("setRoster", roster);
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
      fxCall("setGames", games);
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
    body.innerHTML = g.state === "pre" ? preHtml(d, g, favKey()) : g.state === "in" ? liveHtml(d, g, box) : postHtml(d, g, box);
    body.scrollTop = scroll;
    var head = $(".gc-head");
    if (head) head.outerHTML = headerHtml(g, favKey());
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
    root.innerHTML = '<div class="gc-backdrop"><section class="gc-panel" role="dialog" aria-modal="true" aria-label="Game center">' + headerHtml(g, favKey()) +
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
    clearInterval(gcTimer);
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
    var chip = t.closest(".lv-chip[data-filter]");
    if (chip) { filter = chip.dataset.filter; renderGrid(false); return; }
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
    try { games = (await api("/api/live-scores")).games || []; fxCall("setGames", games); updateNavDot(); } catch (e) { /* leave the marker as it was */ }
  }
})();
