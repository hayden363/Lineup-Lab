// The Sleeper-style skin's small bits of script: color every position chip by position, and run the phone's bottom
// tab bar. Pure helpers are exported for tests; the DOM wiring only runs in the browser.
(function () {
  "use strict";

  var CHIPS = ".pos-badge, .pos-chip, .sst-slot-label, .th-pos";

  // The color family a position label belongs to: QB, RB, WR, TE, K, DEF, or FLEX for any flex-type slot.
  function posOf(text) {
    if (text == null) return null;
    var t = String(text).trim().toUpperCase().replace(/\s+/g, "");
    if (!t) return null;
    if (t === "QB" || t === "RB" || t === "WR" || t === "TE") return t;
    if (t === "K" || t === "PK") return "K";
    if (t === "DEF" || t === "DST" || t === "D/ST") return "DEF";
    if (/FLEX|^OP$|^SUPER|^(RB|WR|TE)\//.test(t)) return "FLEX";
    return null;
  }

  // Tag every position chip under `root` with data-pos (once). Returns how many it newly tagged.
  function decorate(root) {
    var n = 0;
    Array.prototype.forEach.call(root.querySelectorAll(CHIPS), function (el) {
      if (el.dataset.pos) return;
      var p = posOf(el.textContent);
      if (p) { el.dataset.pos = p; n++; }
    });
    return n;
  }

  var Skin = { posOf: posOf, decorate: decorate };
  if (typeof window !== "undefined") window.Skin = Skin;
  if (typeof module !== "undefined") module.exports = Skin;
  if (typeof document === "undefined" || typeof window === "undefined" || !window.document.getElementById) return;

  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; decorate(document); });
  }

  function syncBottomNav() {
    var active = document.querySelector(".sidebar-nav .nav-item.active");
    var tab = active ? active.getAttribute("data-tab") : "";
    document.querySelectorAll("#bottom-nav [data-go]").forEach(function (b) { b.classList.toggle("on", b.dataset.go === tab); });
    var more = document.getElementById("bn-more");
    if (more) more.classList.toggle("on", !!tab && !document.querySelector('#bottom-nav [data-go="' + tab + '"]'));
    var src = document.getElementById("nav-live-dot"), dst = document.getElementById("bn-live-dot");
    if (src && dst) dst.hidden = src.hidden;
  }

  function init() {
    decorate(document);
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    var nav = document.getElementById("bottom-nav");
    if (!nav) return;
    nav.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest("[data-go]") : null;
      if (b) {
        var target = document.querySelector('.sidebar-nav .nav-item[data-tab="' + b.dataset.go + '"]');
        if (target) target.click();
        return;
      }
      if (e.target.closest && e.target.closest("#bn-more")) {
        var menu = document.getElementById("mobile-menu-btn");
        if (menu) menu.click();
      }
    });
    var side = document.querySelector(".sidebar-nav");
    if (side) new MutationObserver(syncBottomNav).observe(side, { attributes: true, subtree: true, attributeFilter: ["class"] });
    var dot = document.getElementById("nav-live-dot");
    if (dot) new MutationObserver(syncBottomNav).observe(dot, { attributes: true, attributeFilter: ["hidden"] });
    syncBottomNav();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
