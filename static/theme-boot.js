/* Applies the saved favorite team before the stylesheet paints, so a reload never flashes the default theme.
   An external file because the CSP allows no inline script. Any failure (blocked storage, an unknown code) leaves the default theme. */
(function () {
  try {
    var code = window.localStorage && window.localStorage.getItem("eb_team");
    if (code && window.TeamTheme) window.TeamTheme.apply(code);
  } catch (e) { /* storage unavailable: default theme */ }
})();
