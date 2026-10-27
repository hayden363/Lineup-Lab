// Browser check for the favorite-team theme. Usage: node scripts/check_team_themes.js [baseUrl] [outPng]
// Needs a running app (uvicorn server:app) and Playwright.
const { chromium } = require("playwright");
const BASE = process.argv[2] || "http://127.0.0.1:8000";
const OUT = process.argv[3] || "team-themes-contact.png";
let failed = 0;
const check = (ok, msg) => { console.log((ok ? "PASS " : "FAIL ") + msg); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  const newPage = async () => {
    const p = await ctx.newPage();
    p.on("pageerror", (e) => errors.push(String(e)));
    p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::/.test(m.text())) errors.push(m.text()); });
    return p;
  };
  const page = await newPage();
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  const codes = await page.evaluate(() => TeamTheme.all().map((t) => t.code));
  check(codes.length === 32, "32 teams in the palette table");

  // default theme: no attribute, empty hero
  await page.evaluate(() => localStorage.removeItem("eb_team")); await page.reload({ waitUntil: "domcontentloaded" });
  check(await page.evaluate(() => !document.documentElement.hasAttribute("data-team") && document.getElementById("team-hero").children.length === 0), "default theme has no data-team and an empty hero");

  // every team: first computed accent equals the primary right after load (no flash), screenshots
  const shots = [];
  for (const code of codes) {
    await page.evaluate((c) => localStorage.setItem("eb_team", c), code);
    await page.reload({ waitUntil: "domcontentloaded" });
    const r = await page.evaluate((c) => ({ accent: document.documentElement.style.getPropertyValue("--accent").trim().toLowerCase(), want: TeamTheme.get(c).primary.toLowerCase(), team: document.documentElement.dataset.team }), code);
    check(r.team === code && r.accent === r.want, `${code}: accent applied at load (${r.accent})`);
    shots.push(await page.screenshot({ clip: { x: 0, y: 0, width: 640, height: 400 } }));
  }
  check(errors.length === 0, `no console errors across all teams${errors.length ? ": " + errors[0] : ""}`);

  // contact sheet
  const sheet = await ctx.newPage();
  await sheet.setContent(`<body style="margin:0;background:#111;display:grid;grid-template-columns:repeat(8,1fr);gap:4px">${shots.map((b) => `<img style="width:100%" src="data:image/png;base64,${b.toString("base64")}">`).join("")}</body>`);
  await sheet.setViewportSize({ width: 2400, height: 900 });
  await sheet.screenshot({ path: OUT, fullPage: true });
  console.log("contact sheet: " + OUT);

  // picker: hover preview then leave restores; choose persists across reload
  await page.evaluate(() => localStorage.setItem("eb_team", "GB")); await page.reload({ waitUntil: "domcontentloaded" });
  // signed out, the login gate covers the app; hide it so the picker underneath can be driven
  await page.addStyleTag({ content: "#gate-root { display: none !important; }" });
  await page.evaluate(() => document.querySelector('.nav-item[data-tab="settings"]').click());
  await page.waitForSelector('#team-picker [data-team="DET"]', { state: "visible" });
  await page.hover('#team-picker [data-team="DET"]');
  check(await page.evaluate(() => document.documentElement.dataset.team) === "DET", "hover previews the team");
  await page.mouse.move(5, 5);
  check(await page.evaluate(() => document.documentElement.dataset.team) === "GB", "leaving the chip restores the saved team");
  await page.click('#team-picker [data-team="DET"]');
  await page.reload({ waitUntil: "domcontentloaded" });
  check(await page.evaluate(() => document.documentElement.dataset.team) === "DET", "chosen team survives a reload");

  // reduced motion removes the sweep
  const rm = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
  const rp = await rm.newPage();
  await rp.goto(BASE, { waitUntil: "domcontentloaded" });
  await rp.evaluate(() => { localStorage.setItem("eb_team", "DET"); });
  await rp.reload({ waitUntil: "domcontentloaded" });
  await rp.evaluate(() => ThemeFX.kickoff("DET"));
  check(await rp.evaluate(() => !document.querySelector(".th-kick")), "reduced motion: no kickoff sweep");
  await rm.close();

  // mobile: no horizontal scroll with a team and the picker open
  const mob = await browser.newContext({ viewport: { width: 360, height: 740 } });
  const mp = await mob.newPage();
  await mp.goto(BASE, { waitUntil: "domcontentloaded" });
  await mp.evaluate(() => localStorage.setItem("eb_team", "KC")); await mp.reload({ waitUntil: "domcontentloaded" });
  await mp.addStyleTag({ content: "#gate-root { display: none !important; }" });
  await mp.evaluate(() => (document.querySelector('.nav-item[data-tab="settings"]') || {}).click && document.querySelector('.nav-item[data-tab="settings"]').click());
  check(await mp.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "360px: no horizontal scroll with a team set and picker open");
  await mob.close();

  await browser.close();
  console.log(failed ? `${failed} check(s) failed` : "all checks passed");
  process.exit(failed ? 1 : 0);
})();
