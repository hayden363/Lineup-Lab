/* The 32-team palette table for the favorite-team theme (docs/superpowers/specs/2026-10-27-team-theme-design.md).
   Strict JSON on purpose (quoted keys, no trailing commas) so the Python tests can json.loads the literal.
   primary = the accent, tuned to read on a dark surface; deep = a very dark tint of the team hue;
   onPrimary = black or white, whichever contrasts more with primary (a test proves it). */
window.TEAM_THEMES = {
  "BUF": {"code": "BUF", "name": "Bills", "city": "Buffalo", "division": "AFC East", "primary": "#5088EA", "secondary": "#E0344F", "deep": "#070b14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"},
  "MIA": {"code": "MIA", "name": "Dolphins", "city": "Miami", "division": "AFC East", "primary": "#1CB5BA", "secondary": "#FF7A33", "deep": "#06100f", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png"},
  "NE": {"code": "NE", "name": "Patriots", "city": "New England", "division": "AFC East", "primary": "#E45B71", "secondary": "#B6BEC4", "deep": "#090c14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png"},
  "NYJ": {"code": "NYJ", "name": "Jets", "city": "New York", "division": "AFC East", "primary": "#2FA676", "secondary": "#D8E4DD", "deep": "#06100c", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyj.png"},
  "BAL": {"code": "BAL", "name": "Ravens", "city": "Baltimore", "division": "AFC North", "primary": "#9D75E1", "secondary": "#D4AF37", "deep": "#0d0a14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/bal.png"},
  "CIN": {"code": "CIN", "name": "Bengals", "city": "Cincinnati", "division": "AFC North", "primary": "#FB5A1F", "secondary": "#E6E6E6", "deep": "#120a06", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cin.png"},
  "CLE": {"code": "CLE", "name": "Browns", "city": "Cleveland", "division": "AFC North", "primary": "#FF6A33", "secondary": "#B07A60", "deep": "#120b07", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cle.png"},
  "PIT": {"code": "PIT", "name": "Steelers", "city": "Pittsburgh", "division": "AFC North", "primary": "#FFB612", "secondary": "#A5ACAF", "deep": "#0b0b09", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/pit.png"},
  "HOU": {"code": "HOU", "name": "Texans", "city": "Houston", "division": "AFC South", "primary": "#E65C6F", "secondary": "#5B8FD6", "deep": "#0a0c14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"},
  "IND": {"code": "IND", "name": "Colts", "city": "Indianapolis", "division": "AFC South", "primary": "#4F86E6", "secondary": "#C9D0D6", "deep": "#070a14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png"},
  "JAX": {"code": "JAX", "name": "Jaguars", "city": "Jacksonville", "division": "AFC South", "primary": "#1AAFC0", "secondary": "#D7A22A", "deep": "#061012", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/jax.png"},
  "TEN": {"code": "TEN", "name": "Titans", "city": "Tennessee", "division": "AFC South", "primary": "#4B92DB", "secondary": "#E4413E", "deep": "#070c14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ten.png"},
  "DEN": {"code": "DEN", "name": "Broncos", "city": "Denver", "division": "AFC West", "primary": "#F26B2A", "secondary": "#4F7FDC", "deep": "#120a06", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/den.png"},
  "KC": {"code": "KC", "name": "Chiefs", "city": "Kansas City", "division": "AFC West", "primary": "#EB5267", "secondary": "#FFB81C", "deep": "#12060a", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"},
  "LV": {"code": "LV", "name": "Raiders", "city": "Las Vegas", "division": "AFC West", "primary": "#A5ACAF", "secondary": "#7C858A", "deep": "#0a0a0a", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lv.png"},
  "LAC": {"code": "LAC", "name": "Chargers", "city": "Los Angeles", "division": "AFC West", "primary": "#1E9BE8", "secondary": "#FFC20E", "deep": "#060d14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lac.png"},
  "DAL": {"code": "DAL", "name": "Cowboys", "city": "Dallas", "division": "NFC East", "primary": "#5586E6", "secondary": "#A5ACAF", "deep": "#070a12", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png"},
  "NYG": {"code": "NYG", "name": "Giants", "city": "New York", "division": "NFC East", "primary": "#5A86E2", "secondary": "#D23B52", "deep": "#070b14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyg.png"},
  "PHI": {"code": "PHI", "name": "Eagles", "city": "Philadelphia", "division": "NFC East", "primary": "#1FA58F", "secondary": "#A5ACAF", "deep": "#06100e", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png"},
  "WAS": {"code": "WAS", "name": "Commanders", "city": "Washington", "division": "NFC East", "primary": "#D96570", "secondary": "#FFB612", "deep": "#12080a", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png"},
  "CHI": {"code": "CHI", "name": "Bears", "city": "Chicago", "division": "NFC North", "primary": "#E8602C", "secondary": "#5A86DA", "deep": "#080b13", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/chi.png"},
  "DET": {"code": "DET", "name": "Lions", "city": "Detroit", "division": "NFC North", "primary": "#1B9BE0", "secondary": "#A5ACAF", "deep": "#060d14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png"},
  "GB": {"code": "GB", "name": "Packers", "city": "Green Bay", "division": "NFC North", "primary": "#FFB612", "secondary": "#3FA567", "deep": "#06100a", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/gb.png"},
  "MIN": {"code": "MIN", "name": "Vikings", "city": "Minnesota", "division": "NFC North", "primary": "#9B72E0", "secondary": "#FFC62F", "deep": "#0c0814", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/min.png"},
  "ATL": {"code": "ATL", "name": "Falcons", "city": "Atlanta", "division": "NFC South", "primary": "#E95458", "secondary": "#A5ACAF", "deep": "#12070a", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/atl.png"},
  "CAR": {"code": "CAR", "name": "Panthers", "city": "Carolina", "division": "NFC South", "primary": "#1B9BD8", "secondary": "#A5ACAF", "deep": "#060c12", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png"},
  "NO": {"code": "NO", "name": "Saints", "city": "New Orleans", "division": "NFC South", "primary": "#D8BE82", "secondary": "#8C8C8C", "deep": "#0d0b07", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/no.png"},
  "TB": {"code": "TB", "name": "Buccaneers", "city": "Tampa Bay", "division": "NFC South", "primary": "#EA544E", "secondary": "#FF8A2A", "deep": "#120807", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/tb.png"},
  "ARI": {"code": "ARI", "name": "Cardinals", "city": "Arizona", "division": "NFC West", "primary": "#EA5360", "secondary": "#C9C9C9", "deep": "#120709", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png"},
  "LA": {"code": "LA", "name": "Rams", "city": "Los Angeles", "division": "NFC West", "primary": "#4F86F0", "secondary": "#FFD100", "deep": "#070b14", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png"},
  "SF": {"code": "SF", "name": "49ers", "city": "San Francisco", "division": "NFC West", "primary": "#E35C60", "secondary": "#C5A15A", "deep": "#120708", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"},
  "SEA": {"code": "SEA", "name": "Seahawks", "city": "Seattle", "division": "NFC West", "primary": "#6CC24A", "secondary": "#5B8DEF", "deep": "#060f0b", "onPrimary": "#000000", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sea.png"}
};

/* ---- the engine: turns a palette into CSS variables on <html data-team="..."> ---------------------------------
   Semantic colors (--pos, --neg, --avg, --tough, --soft) are never touched, so start/sit meaning survives any team.
   Everything comes from the table above: nothing user-controlled ever reaches a style attribute. */
(function () {
  var T = window.TEAM_THEMES || {};
  var DIVISIONS = ["AFC East", "AFC North", "AFC South", "AFC West", "NFC East", "NFC North", "NFC South", "NFC West"];
  var VAR_KEYS = ["--accent", "--accent-dim", "--accent-glow", "--brand", "--border-bright", "--bg", "--panel", "--panel-2",
    "--panel-glass", "--violet", "--info", "--violet-glow", "--info-glow", "--tm", "--tm-rgb", "--on-accent", "--team-secondary"];
  var root = document.documentElement;
  var meta = document.querySelector('meta[name="theme-color"]');
  var defaultThemeColor = meta ? meta.content : null;
  var current = "";

  function rgb(hex) { return [1, 3, 5].map(function (i) { return parseInt(hex.slice(i, i + 2), 16); }); }
  function hex(c) { return "#" + c.map(function (v) { var s = Math.round(v).toString(16); return s.length < 2 ? "0" + s : s; }).join(""); }
  function mix(a, toward, f) {                       // a moved f of the way toward `toward`
    var x = rgb(a), y = rgb(toward);
    return hex(x.map(function (v, i) { return v * (1 - f) + y[i] * f; }));
  }
  function rgba(a, alpha) { var c = rgb(a); return "rgba(" + c[0] + ", " + c[1] + ", " + c[2] + ", " + alpha + ")"; }

  function valid(code) { return typeof code === "string" && Object.prototype.hasOwnProperty.call(T, code); }
  function get(code) { return valid(code) ? T[code] : null; }

  function vars(code) {
    var p = get(code);
    if (!p) return {};
    var dim = mix(p.primary, "#000000", 0.18);
    var panel = mix(p.deep, "#ffffff", 0.07);
    var c = rgb(p.primary);
    return {
      "--accent": p.primary, "--accent-dim": dim, "--accent-glow": rgba(p.primary, 0.38), "--brand": dim,
      "--border-bright": rgba(p.primary, 0.28),
      "--bg": p.deep, "--panel": panel, "--panel-2": mix(p.deep, "#ffffff", 0.11), "--panel-glass": rgba(panel, 0.68),
      "--violet": p.secondary, "--info": p.secondary, "--violet-glow": rgba(p.secondary, 0.38), "--info-glow": rgba(p.secondary, 0.38),
      "--tm": p.primary, "--tm-rgb": c.join(","), "--on-accent": p.onPrimary, "--team-secondary": p.secondary
    };
  }

  function clear() {
    VAR_KEYS.forEach(function (k) { root.style.removeProperty(k); });
    root.removeAttribute("data-team");
    if (meta && defaultThemeColor !== null) meta.setAttribute("content", defaultThemeColor);
    current = "";
  }

  // Applies a team, or the default theme for anything that isn't one of the 32 codes. Returns whether a team is applied.
  function apply(code) {
    clear();
    if (!valid(code)) return false;
    var v = vars(code);
    Object.keys(v).forEach(function (k) { root.style.setProperty(k, v[k]); });
    root.setAttribute("data-team", code);
    if (meta) meta.setAttribute("content", T[code].deep);
    current = code;
    return true;
  }

  function all() {
    return Object.keys(T).map(function (k) { return T[k]; }).sort(function (a, b) {
      return DIVISIONS.indexOf(a.division) - DIVISIONS.indexOf(b.division) || (a.city + a.name < b.city + b.name ? -1 : 1);
    });
  }

  window.TeamTheme = { valid: valid, get: get, vars: vars, apply: apply, clear: clear, current: function () { return current; }, all: all };
})();
