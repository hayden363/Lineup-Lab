/* The Daily Drive: vanilla JS, no inline script (CSP script-src 'self'). Answers never reach this file until the game
   is over: every typed answer is judged by /api/play/check, and the full tier lists come from /api/play/reveal. */
(function () {
  "use strict";
  var PREVIEW_MS = 3000, ANSWER_MS = 25000, SAVE_TTL_MS = 12 * 3600 * 1000, MAX_YARDS = 700;
  var TIER = {
    6: ["Hall of Famer", 100, "🏆"], 5: ["All-Pro", 85, "🟣"], 4: ["Pro Bowler", 60, "🔵"],
    3: ["Starter", 30, "🟢"], 2: ["Rotation", 15, "🟡"], 1: ["Benchwarmer", 10, "⚪"]
  };
  var SACK = "🟥";
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var root = document.getElementById("app");

  // ---------------------------------------------------------------- storage (every access guarded)
  function lsGet(k) { try { var v = window.localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch (e) { return null; } }
  function lsSet(k, v) { try { window.localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked: the game still works */ } }
  function lsDel(k) { try { window.localStorage.removeItem(k); } catch (e) { /* ignore */ } }

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") el.className = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
      else el.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      if (Array.isArray(c)) { c.forEach(function (x) { el.appendChild(x); }); continue; }
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    return el;
  }
  function mount() { root.textContent = ""; for (var i = 0; i < arguments.length; i++) if (arguments[i]) root.appendChild(arguments[i]); }
  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || "request failed"); return j; });
    });
  }
  function isoAdd(iso, days) {
    var p = iso.split("-"); var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + days));
    return d.toISOString().slice(0, 10);
  }
  function prettyDate(iso) {
    var p = iso.split("-"); var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  }
  function yardsOf(tiers) { return tiers.reduce(function (a, t) { return a + (t ? TIER[t][1] : 0); }, 0); }
  function shareText(date, tiers) {
    return "The Daily Drive · " + prettyDate(date) + " · " + yardsOf(tiers) + " yds\n" +
      tiers.map(function (t) { return t ? TIER[t][2] : SACK; }).join("") + "\nlineup-lab-awdv.onrender.com/play";
  }
  function countUp(el, to, ms, prefix) {
    prefix = prefix || "";
    if (REDUCED || !to) { el.textContent = prefix + to; return; }
    var t0 = performance.now();
    (function step(now) {
      var f = Math.min(1, (now - t0) / ms);
      el.textContent = prefix + Math.round(to * (1 - Math.pow(1 - f, 3)));
      if (f < 1) requestAnimationFrame(step);
    })(t0);
  }

  // ---------------------------------------------------------------- streak
  function streakNow(today) {
    var s = lsGet("dd.streak");
    if (!s) return 0;
    return (s.last === today || s.last === isoAdd(today, -1)) ? s.count : 0;
  }
  function streakBump(today) {
    var s = lsGet("dd.streak") || { last: "", count: 0 };
    if (s.last === today) return s.count;
    s = { last: today, count: s.last === isoAdd(today, -1) ? s.count + 1 : 1 };
    lsSet("dd.streak", s);
    return s.count;
  }

  // ---------------------------------------------------------------- shared pieces
  function topBar(extra) {
    return h("div", { "class": "dd-top" },
      h("div", { "class": "dd-brand" }, "The Daily ", h("span", null, "Drive")), extra || null);
  }
  function fieldBar(yards) {
    var bar = h("i");
    requestAnimationFrame(function () { requestAnimationFrame(function () { bar.style.width = Math.min(100, yards / MAX_YARDS * 100) + "%"; }); });
    return h("div", null, h("div", { "class": "dd-field", role: "img", "aria-label": yards + " of " + MAX_YARDS + " yards" }, bar),
      h("div", { "class": "dd-field-meta" }, h("span", null, "0"), h("b", null, yards + " yds"), h("span", null, MAX_YARDS)));
  }
  function ring() {
    var C = 2 * Math.PI * 62;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 140 140");
    var bg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    var fg2 = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    [[bg, "bg"], [fg2, "fg"]].forEach(function (p) {
      p[0].setAttribute("class", p[1]); p[0].setAttribute("cx", 70); p[0].setAttribute("cy", 70); p[0].setAttribute("r", 62);
    });
    fg2.setAttribute("stroke-dasharray", C); fg2.setAttribute("stroke-dashoffset", 0);
    svg.appendChild(bg); svg.appendChild(fg2);
    var num = h("b", null, "25");
    var el = h("div", { "class": "dd-ring" }, svg, num);
    return {
      el: el,
      set: function (msLeft) {
        fg2.setAttribute("stroke-dashoffset", C * (1 - Math.max(0, msLeft) / ANSWER_MS));
        num.textContent = Math.ceil(Math.max(0, msLeft) / 1000);
        el.classList.toggle("low", msLeft <= 5000);
      }
    };
  }
  function touchdown() {
    var box = h("div", { "class": "dd-td", "aria-hidden": "true" }, h("strong", null, "TOUCHDOWN"));
    if (!REDUCED) {
      var colors = ["#ffb84d", "#00ceb8", "#bd66ff", "#58a7ff", "#ff5d7a", "#2fd9a0"];
      for (var i = 0; i < 36; i++) {
        var a = Math.random() * Math.PI * 2, r = 120 + Math.random() * 190, p = h("i");
        p.style.background = colors[i % colors.length];
        p.style.setProperty("--dx", Math.cos(a) * r + "px"); p.style.setProperty("--dy", Math.sin(a) * r + "px");
        box.appendChild(p);
      }
    }
    document.body.appendChild(box);
    setTimeout(function () { if (box.parentNode) box.parentNode.removeChild(box); }, 1900);
  }
  function copyText(text, btn) {
    function done(ok) { btn.textContent = ok ? "Copied" : "Press and hold the card to copy"; setTimeout(function () { btn.textContent = "Copy result"; }, 2000); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallbackCopy(text)); });
    } else done(fallbackCopy(text));
  }
  function fallbackCopy(text) {
    var ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.appendChild(ta);
    ta.select(); var ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta); return ok;
  }

  // ---------------------------------------------------------------- one prompt (shared by daily and practice)
  // opts: {date, prompt, index, total, yardsSoFar, used[], startedAt, onDone(result)}  result = {tier, name, id}
  function runPrompt(opts) {
    var prompt = opts.prompt, deadline = 0, done = false, raf = 0, previewT = 0, timers = [];
    var rg = ring();
    var cat = h("div", { "class": "dd-cat" }, prompt.category);
    var text = h("div", { "class": "dd-prompt hidden" }, prompt.text);
    var msg = h("div", { "class": "dd-msg" });
    var sugg = h("div", { "class": "dd-sugg" });
    var input = h("input", { "class": "dd-input", type: "text", autocomplete: "off", autocapitalize: "words", autocorrect: "off",
      spellcheck: "false", enterkeyhint: "go", "aria-label": "Your answer", placeholder: "Type a player's name" });
    var go = h("button", { "class": "dd-btn dd-go", type: "submit" }, "Go");
    var form = h("form", { "class": "dd-form", onsubmit: function (e) { e.preventDefault(); submit(input.value); } }, input, go);
    var pre = h("div", { "class": "dd-pre" }, h("div", { "class": "dd-small" }, "Get ready"), h("div", { "class": "big" }, "3"));
    var play = h("div", { style: "display:none" }, h("div", { "class": "dd-clock" }, rg.el), form, msg, sugg);
    var card = h("div", { "class": "dd-card" }, cat, text, pre, play);
    var counter = h("span", { "class": "dd-chip" }, "Prompt ", h("b", null, (opts.index + 1) + "/" + opts.total));
    input.disabled = true; go.disabled = true;

    mount(topBar(counter), opts.field === false ? null : fieldBar(opts.yardsSoFar || 0), card);

    function begin(answerStart) {
      pre.style.display = "none"; play.style.display = ""; text.classList.remove("hidden");
      input.disabled = false; go.disabled = false; input.focus();
      deadline = answerStart + ANSWER_MS;
      if (opts.onStart) opts.onStart(answerStart);
      (function tick() {
        var left = deadline - Date.now();
        rg.set(left);
        if (left <= 0) { finish(null); return; }
        raf = requestAnimationFrame(tick);
      })();
    }
    function finish(res) {
      if (done) return; done = true; cancelAnimationFrame(raf); clearTimeout(previewT);
      input.disabled = true; go.disabled = true;
      opts.onDone(res);
    }
    function submit(raw) {
      var typed = (raw || "").trim();
      if (!typed || done) return;
      var sentAt = Date.now();
      go.disabled = true; msg.textContent = ""; sugg.textContent = "";
      api("/api/play/check", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: opts.date, prompt_id: prompt.id, answer: typed, used: opts.used }) })
        .then(function (r) {
          if (done) return;
          if (r.ok) {
            if (sentAt > deadline) return;                 // answered after the buzzer: the timeout already won
            finish({ tier: r.tier, yards: r.yards, name: r.canonical, id: r.answer_id });
            return;
          }
          go.disabled = false; input.value = ""; input.focus();
          msg.textContent = r.reason.charAt(0).toUpperCase() + r.reason.slice(1);
          form.classList.remove("shake"); void form.offsetWidth; form.classList.add("shake");
          (r.suggestions || []).forEach(function (n) {
            sugg.appendChild(h("button", { type: "button", onclick: function () { submit(n); } }, "Did you mean " + n + "?"));
          });
        })
        .catch(function () { if (done) return; go.disabled = false; msg.textContent = "Couldn't reach the server. Try again."; input.focus(); });
    }

    // 3-second category preview, then the real 25-second clock
    var resumeStart = opts.resumeAnswerStart;
    if (resumeStart) { begin(resumeStart); return; }
    var big = pre.querySelector(".big"), n = 3;
    var t0 = Date.now();
    (function countdown() {
      var left = PREVIEW_MS - (Date.now() - t0);
      n = Math.max(1, Math.ceil(left / 1000)); big.textContent = n;
      if (left <= 0) { begin(Date.now()); return; }
      previewT = setTimeout(countdown, 100);
    })();
  }

  function resultCard(res, last, next) {
    var t = res ? res.tier : 0;
    var badge = h("div", { "class": "dd-badge t" + t + (REDUCED ? "" : " pop") }, t ? TIER[t][2] + " " + TIER[t][0] : SACK + " Sacked");
    var yds = h("div", { "class": "dd-yds" }, "+0");
    var who = h("div", { "class": "dd-who" }, res ? res.name : "Time ran out");
    var btn = h("button", { "class": "dd-btn", type: "button", onclick: function () { go(); } }, last ? "See results" : "Next prompt");
    var timer = 0, went = false;
    function go() { if (went) return; went = true; clearTimeout(timer); next(); }
    countUp(yds, res ? res.yards : 0, 700, "+");
    yds.appendChild(h("span", { "class": "dd-small" }, " yds"));
    if (t === 6) touchdown();
    timer = setTimeout(go, t === 6 ? 3200 : 2200);
    return h("div", { "class": "dd-card dd-res" }, badge, yds, who, btn);
  }

  // ---------------------------------------------------------------- daily game
  function startDaily(puzzle, saved) {
    var date = puzzle.date, prompts = puzzle.prompts, total = prompts.length;
    var st = saved || { date: date, startedAt: Date.now(), idx: 0, tiers: [], names: [], ids: [], answerStart: 0 };
    function persist() { lsSet("dd.saved", st); }
    persist();

    function step() {
      if (st.idx >= total) { return finishGame(); }
      var resume = st.answerStart && Date.now() < st.answerStart + ANSWER_MS ? st.answerStart : 0;
      if (st.answerStart && !resume) {                           // the real deadline passed while the page was closed
        st.tiers.push(0); st.names.push(""); st.idx++; st.answerStart = 0; persist(); return step();
      }
      runPrompt({
        date: date, prompt: prompts[st.idx], index: st.idx, total: total, yardsSoFar: yardsOf(st.tiers), used: st.ids.slice(),
        resumeAnswerStart: resume,
        onStart: function (ts) { st.answerStart = ts; persist(); },
        onDone: function (res) {
          st.tiers.push(res ? res.tier : 0); st.names.push(res ? res.name : ""); if (res) st.ids.push(res.id);
          st.idx++; st.answerStart = 0; persist();
          var last = st.idx >= total;
          mount(topBar(h("span", { "class": "dd-chip" }, "Prompt ", h("b", null, st.idx + "/" + total))),
            fieldBar(yardsOf(st.tiers)), resultCard(res, last, step));
        }
      });
    }

    function finishGame() {
      var today = puzzle.today === date;
      var rec = { tiers: st.tiers, names: st.names, yards: yardsOf(st.tiers) };
      lsSet("dd.played." + date, rec); lsDel("dd.saved");
      if (today) streakBump(date);
      showResults(puzzle, rec);
    }
    step();
  }

  // ---------------------------------------------------------------- results + reveal
  function showResults(puzzle, rec) {
    var date = puzzle.date, today = puzzle.today === date;
    var streak = today ? streakNow(date) : 0;
    var text = shareText(date, rec.tiers);
    var copy = h("button", { "class": "dd-btn", type: "button" }, "Copy result");
    copy.addEventListener("click", function () { copyText(text, copy); });
    var num = h("div", { "class": "num" }, "0");
    var rev = h("div", { "class": "dd-rev" }, h("p", { "class": "dd-small" }, "Loading the answer sheets..."));
    var card = h("div", { "class": "dd-card dd-total" },
      h("div", { "class": "dd-small" }, "Final score"), num, h("div", { "class": "dd-small" }, "yards of " + MAX_YARDS),
      h("div", { "class": "dd-share", "aria-label": "Share card" }, text), copy);
    mount(topBar(streak ? h("span", { "class": "dd-chip" }, "Streak ", h("b", null, streak)) : null), fieldBar(rec.yards), card,
      h("div", { "class": "dd-card" }, h("h2", null, "Every answer, by tier"), rev),
      h("div", { "class": "dd-row" }, h("button", { "class": "dd-btn alt", type: "button", onclick: practice }, "Practice mode"),
        h("a", { "class": "dd-btn alt", href: "/", style: "text-decoration:none;text-align:center;display:block" }, "Open Lineup Lab")));
    countUp(num, rec.yards, 1100);
    var jobs = puzzle.prompts.map(function (p, i) {
      return api("/api/play/reveal?date=" + encodeURIComponent(date) + "&prompt_id=" + encodeURIComponent(p.id))
        .then(function (r) { return { r: r, i: i }; });
    });
    Promise.all(jobs).then(function (all) {
      rev.textContent = "";
      all.forEach(function (x) {
        var t = rec.tiers[x.i], mine = rec.names[x.i];
        var d = h("details", null, h("summary", null, h("span", null, x.r.text), h("span", null, t ? TIER[t][2] : SACK)));
        x.r.tiers.forEach(function (tr) {
          if (!tr.answers.length) return;
          d.appendChild(h("h3", null, tr.emoji + " " + tr.tier_name + " (" + tr.yards + " yds)"));
          var p = h("p");
          tr.answers.slice(0, 12).forEach(function (n, k) {
            if (k) p.appendChild(document.createTextNode(", "));
            p.appendChild(n === mine ? h("span", { "class": "mine" }, n) : document.createTextNode(n));
          });
          if (tr.answers.length > 12) p.appendChild(document.createTextNode(" and " + (tr.answers.length - 12) + " more"));
          d.appendChild(p);
        });
        rev.appendChild(d);
      });
    }).catch(function () { rev.textContent = "Couldn't load the answer sheets. Reload to try again."; });
  }

  // ---------------------------------------------------------------- practice
  function practice() {
    mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Finding a prompt...")));
    api("/api/play/practice").then(function (r) {
      runPrompt({
        date: r.date, prompt: r.prompt, index: 0, total: 1, field: false, used: [],
        onDone: function (res) {
          var again = h("button", { "class": "dd-btn", type: "button", onclick: practice }, "Another prompt");
          var out = h("div", { "class": "dd-card dd-res" },
            h("div", { "class": "dd-badge t" + (res ? res.tier : 0) }, res ? TIER[res.tier][2] + " " + TIER[res.tier][0] : SACK + " Sacked"),
            h("div", { "class": "dd-who" }, res ? res.name + " (+" + res.yards + " yds)" : "Time ran out"),
            h("p", { "class": "dd-small" }, "Practice does not count toward your streak."), again,
            h("div", { style: "height:8px" }), h("button", { "class": "dd-btn alt", type: "button", onclick: boot }, "Back to today's game"));
          mount(topBar(), out);
          if (res && res.tier === 6) touchdown();
        }
      });
    }).catch(function (e) { mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Practice isn't available yet: " + e.message),
      h("button", { "class": "dd-btn alt", type: "button", onclick: boot }, "Back"))); });
  }

  // ---------------------------------------------------------------- intro
  function intro(puzzle) {
    var date = puzzle.date;
    var streak = streakNow(puzzle.today);
    var start = h("button", { "class": "dd-btn", type: "button", onclick: function () { startDaily(puzzle, null); } }, "Start today's drive");
    var rows = [];
    [6, 5, 4, 3, 2, 1].forEach(function (t) { rows.push(h("span", null, TIER[t][2] + " " + TIER[t][0])); rows.push(h("span", null, TIER[t][1] + " yds")); });
    mount(topBar(h("span", { "class": "dd-chip" }, "Streak ", h("b", null, streak))),
      h("div", { "class": "dd-card" },
        h("div", { "class": "dd-cat" }, prettyDate(date) + (date === puzzle.today ? " · today" : " · archive")),
        h("h1", null, "Seven prompts. One answer each."),
        h("p", null, "Type a player who fits. Rarer answers earn more yards, and every answer is computed from real NFL data. You get 25 seconds per prompt, after a 3-second preview."),
        h("div", { "class": "dd-tiers" }, rows), start),
      h("div", { "class": "dd-row" },
        h("button", { "class": "dd-btn alt", type: "button", onclick: practice }, "Practice mode")));
  }

  // ---------------------------------------------------------------- boot
  function boot() {
    mount(topBar(), h("div", { "class": "dd-card" }, h("p", null, "Loading today's game...")));
    var wanted = (new URLSearchParams(window.location.search)).get("date");
    api("/api/play/daily" + (wanted && /^\d{4}-\d{2}-\d{2}$/.test(wanted) ? "?date=" + wanted : "")).then(function (puzzle) {
      var played = lsGet("dd.played." + puzzle.date);
      if (played) { showResults(puzzle, played); return; }
      var saved = lsGet("dd.saved");
      if (saved && saved.date === puzzle.date && Date.now() - saved.startedAt < SAVE_TTL_MS) { startDaily(puzzle, saved); return; }
      if (saved) lsDel("dd.saved");
      intro(puzzle);
    }).catch(function (e) {
      mount(topBar(), h("div", { "class": "dd-card" }, h("h2", null, "Today's game isn't ready"), h("p", null, e.message),
        h("button", { "class": "dd-btn", type: "button", onclick: boot }, "Try again")));
    });
  }
  boot();
})();
