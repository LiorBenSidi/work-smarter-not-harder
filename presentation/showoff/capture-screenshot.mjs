// Capture an app screenshot for the gallery poster, by driving the repo's own E2E harness.
//
//   docker compose up -d                                   # stack must be running on :8000
//   node presentation/showoff/capture-screenshot.mjs poster-assets/shot-6-plan.png
//   node presentation/showoff/capture-screenshot.mjs poster-assets/shot-7-profile.png   profile
//   node presentation/showoff/capture-screenshot.mjs poster-assets/shot-8-programme.png programme
//
// Second argument picks the screen: "plan" (default), "profile", or "programme". All three start
// from the same throwaway account and the same saved profile, because the plan cannot render
// without one. "profile" and "programme" are two frames of the SAME screen -- see the geometry
// note at the "programme" branch for why they cannot be one tile.
//
// Real UI, real render, throwaway local account — no fixtures and no hand-made mockups, so what
// lands on the poster is what the app actually produces. Registers a user, fills a profile, files
// a check-in, resolves the split, then frames the plan card and shoots it at the mobile viewport
// the other poster tiles were captured at.
//
// Why a script rather than "take a screenshot by hand": the original poster's mockups had no
// reproducible origin, so when the app gained a feature there was no way to refresh them without
// redoing the whole thing. Re-run this instead.
//
// Set OTP/verify off so registration is one step (this is the E2E boot env):
//   REGISTER_VERIFY_EMAIL=0 OTP_ENABLED=0 SMTP_HOST= SESSION_COOKIE_SECURE=0 RATELIMIT_ENABLED=0 \
//     docker compose up -d --force-recreate web

import { Browser, VIEWPORTS } from "../../tests/E2E_Tests/lib/cdp.mjs";

const BASE = process.env.E2E_BASE_URL || "http://localhost:8000";
const OUT = process.argv[2];
const SCREEN = (process.argv[3] || "plan").toLowerCase();
if (!OUT || !["plan", "profile", "programme"].includes(SCREEN)) {
  console.error("usage: node capture-screenshot.mjs <output.png> [plan|profile|programme]");
  process.exit(1);
}
const uniq = (p) => `${p}${Date.now().toString(36)}`;

const b = new Browser({ port: 9600, userDir: "/tmp/poster-chrome", viewport: VIEWPORTS.mobile });
b.base = BASE;
await b.launch();

// Chrome reuses its profile dir, so clear cookies or a previous run leaves us already signed in
// and the landing page never shows.
const u = uniq("shot"), pw = "Passw0rd!23";
await b.send("Network.clearBrowserCookies");
await b.goto(BASE + "/"); await b.clearServiceWorkers();
await b.send("Network.clearBrowserCookies");
await b.goto(BASE + "/");
await b.waitFor("#tab-register"); await b.click("#tab-register");
await b.waitFor("#reg-username");
await b.type("#reg-username", u);
await b.type("#reg-email", u + "@example.com");
await b.type("#reg-password", pw);
await b.submit("#register-form");
await b.waitFor("#login-form", { timeout: 15000 });
await b.type("#login-username", u);
await b.type("#login-password", pw);
await b.submit("#login-form");
await b.waitFor("#app-view", { timeout: 15000 });
console.log("logged in as", u);

// The plan needs a goal, a training frequency and some equipment; without a saved profile the
// dashboard shows "Set up your profile" and no plan renders at all.
await b.pageExec(`(() => { const p = document.querySelector('[data-act="profile"]'); if (p) p.click(); return true; })()`);
await b.wait(900);
const profiled = await b.pageExec(`(() => {
  const set = (id, v) => { const el = document.getElementById(id); if (!el) return null;
    el.value = v; el.dispatchEvent(new Event("input", {bubbles:true})); el.dispatchEvent(new Event("change", {bubbles:true})); return el.value; };
  const out = {};
  out.age = set("age", "27");
  const g = document.getElementById("gender");
  if (g && g.options.length > 1) { g.selectedIndex = 1; g.dispatchEvent(new Event("change", {bubbles:true})); out.gender = g.value; }
  out.height = set("height", "170");
  out.weight = set("weight", "63");
  out.goal = set("goal", "gain");
  // 6 resolves straight to push/pull/legs — 4 and 5 return split OPTIONS and show a picker instead
  out.freq = set("training_frequency", "6");
  const eq = document.querySelectorAll('#equipment-group input[type=checkbox]');
  eq.forEach(c => { if (!c.checked) c.click(); });
  out.equipment = eq.length;
  // The Advanced-tier weekly programme (#566). Filled with a balanced week so the profile tile
  // shows the section populated, the way an athlete who answered it would see it.
  const PROGRAM = { chest: 12, back: 14, shoulders: 9, biceps: 8, triceps: 8,
                    quads: 12, hamstrings: 10, glutes: 10, calves: 6, core: 8 };
  out.program = 0;
  for (const [mg, sets] of Object.entries(PROGRAM)) {
    const el = document.querySelector('#training-program-group input[data-mg="' + mg + '"]');
    if (el) { el.value = String(sets); el.dispatchEvent(new Event("input", {bubbles:true})); out.program++; }
  }
  const f = document.getElementById("profile-form");
  out.form = !!f;
  if (f) f.requestSubmit();
  return out;
})()`);
console.log("profile ->", JSON.stringify(profiled));
await b.wait(1400);

if (SCREEN === "profile") {
  // Frame the profile card from its top edge, just under the sticky header, so the tile starts on
  // the heading rather than mid-field. No check-in needed: this screen does not depend on one.
  await b.pageExec(`(() => {
    const card = document.querySelector("#screen-profile .card");
    if (!card) return false;
    const hdr = document.querySelector("header, .appbar, .topbar");
    const hh = hdr ? hdr.getBoundingClientRect().height : 0;
    window.scrollTo({ top: card.getBoundingClientRect().top + window.scrollY - hh - 14, behavior: "instant" });
    return true;
  })()`);
  await b.wait(600);
  await b.screenshot(OUT);
  console.log("saved", OUT);
  await b.close();
  process.exit(0);
}

if (SCREEN === "programme") {
  // Why the Advanced-tier programme (#566) gets its OWN tile rather than sharing the profile's.
  //
  // GEOMETRY, measured rather than guessed: the profile card is ~2597 CSS px tall, and the poster
  // crops every tile to aspect-ratio 741/1400 with object-position:top, so only the TOP ~737 CSS px
  // of a capture ever reaches the printed sheet. Card-top through programme-bottom spans ~2223 px --
  // fitting both would need roughly a 0.33x zoom, about 4px type. So one tile cannot carry the
  // profile fields AND the programme at a readable size.
  //
  // Two tiles cost nothing: the grid is four columns, so seven tiles left row two holding three with
  // a gap. Eight fills it -- still two rows, same sheet height.
  // Pick the offset by MEASURING, not by taste: sweep a few back-offs above the programme block and
  // keep the one that lands the most muscle groups on the printed sheet while still showing the
  // section heading. Anchoring on the equipment chips reads nicer but only survives 2 of 10 groups.
  const framed = await b.pageExec(`(() => {
    const grp = document.querySelector("#training-program-group");
    if (!grp) return { ok: false, why: "no #training-program-group" };
    const hdr = document.querySelector("header, .appbar, .topbar");
    const hh = hdr ? hdr.getBoundingClientRect().height : 0;
    const block = grp.closest("fieldset, section") || grp;
    const band = Math.round(window.innerWidth / (741 / 1400));
    const inputs = Array.from(grp.querySelectorAll("input[data-mg]"));
    const heading = Array.from(document.querySelectorAll("#screen-profile *")).find(
      e => /current training programme/i.test(e.textContent || "") && e.children.length === 0);
    let best = null;
    // The header is STICKY and content scrolls under it, so simply landing on the block's top edge
    // leaves the equipment chips peeking out beneath the bar — sliced mid-row, which reads as a
    // mistake. Negative back-offs scroll a little further so the chips clear the bar entirely.
    // A candidate is only acceptable when the section heading is on the sheet AND no equipment chip
    // is visible below the header.
    const chips = Array.from(document.querySelectorAll("#equipment-group *"))
      .filter(e => e.children.length === 0 && (e.textContent || "").trim());
    for (const back of [14, 0, -12, -24, -36]) {
      const y = Math.max(0, block.getBoundingClientRect().top + window.scrollY - hh - back);
      window.scrollTo({ top: y, behavior: "instant" });
      const onSheet = inputs.filter(e => { const r = e.getBoundingClientRect();
        return r.top >= 0 && r.bottom <= band; }).length;
      const hr = heading ? heading.getBoundingClientRect() : null;
      const headOK = !!(hr && hr.top >= 0 && hr.bottom <= band);
      const chipVisible = chips.some(c => { const r = c.getBoundingClientRect();
        return r.bottom > hh + 2 && r.top < band; });
      if (headOK && !chipVisible && (!best || onSheet > best.onSheet)) {
        best = { back, y: Math.round(y), onSheet };
      }
    }
    if (!best) return { ok: false, why: "no offset kept the heading on the sheet" };
    window.scrollTo({ top: best.y, behavior: "instant" });
    return { ok: true, anchoredOn: "programme", chosenBackOff: best.back,
             scrolledTo: best.y, groupsOnSheet: best.onSheet };
  })()`);
  console.log("framing ->", JSON.stringify(framed));
  await b.wait(600);
  // Prove the grid reaches the PRINTED sheet, not merely the viewport. The poster crops each tile to
  // 741/1400 from the top, so the band that survives is the top (viewportWidth / (741/1400)) CSS px --
  // ~737 at 390 wide. Measuring against the viewport instead would pass on inputs the poster throws
  // away, which is the silent mis-frame that put #566 off the sheet in the first place.
  const visible = await b.evaluate(`() => {
    const band = Math.round(window.innerWidth / (741 / 1400));
    const els = Array.from(document.querySelectorAll('#training-program-group input[data-mg]'));
    const onSheet = els.filter(e => { const r = e.getBoundingClientRect();
      return r.top >= 0 && r.bottom <= band; });
    const heading = Array.from(document.querySelectorAll('#screen-profile *')).find(
      e => /current training programme/i.test(e.textContent || "") && e.children.length === 0);
    const hr = heading ? heading.getBoundingClientRect() : null;
    return { posterBandCssPx: band, total: els.length,
             onPrintedSheet: onSheet.length,
             groupsShown: onSheet.map(e => e.getAttribute('data-mg')),
             filled: els.filter(e => e.value !== "").length,
             headingOnSheet: !!(hr && hr.top >= 0 && hr.bottom <= band) };
  }`);
  console.log("programme on the printed sheet:", JSON.stringify(visible));
  if (!visible || visible.onPrintedSheet === 0) {
    console.error("WARNING: no programme input survives the poster crop — reframe before shipping");
  }
  await b.screenshot(OUT);
  console.log("saved", OUT);
  await b.close();
  process.exit(0);
}

// Today is deliberately outside the tab model, so it is reached via #nav-home, not [data-screen].
await b.pageExec(`(() => { const h = document.getElementById("nav-home"); if (h) { h.hidden = false; h.click(); return true; } return false; })()`);
await b.wait(700);
await b.waitFor("#checkin-form", { timeout: 10000 });
await b.type("#sleep_hours", "7");
await b.type("#resting_hr", "55");
await b.pageExec(`(() => { document.querySelectorAll("#checkin-form .scale").forEach(sc => { const btn = sc.querySelector("button"); if (btn) btn.click(); }); return true; })()`);
await b.wait(250);
await b.pageExec(`(() => { document.querySelector("#checkin-form").requestSubmit(); return true; })()`);
await b.wait(3500);

const hasPlan = await b.exists(".plan");
console.log("plan card present:", hasPlan);
if (hasPlan) {
  // a split picker means the frequency was ambiguous — resolve it so the day list renders
  const picked = await b.pageExec(`(() => { const btn = document.querySelector(".plan-pick button"); if (btn) { btn.click(); return true; } return false; })()`);
  if (picked) { await b.wait(2500); }
  // land the card's top edge just under the sticky header, so nothing is clipped mid-line
  await b.pageExec(`(() => {
    const d = document.querySelector(".plan-day"); if (d) d.open = true;
    const p = document.querySelector(".plan"); if (!p) return false;
    const hdr = document.querySelector("header, .appbar, .topbar");
    const hh = hdr ? hdr.getBoundingClientRect().height : 0;
    const y = p.getBoundingClientRect().top + window.scrollY - hh - 14;
    window.scrollTo({ top: y, behavior: "instant" });
    return true;
  })()`);
  await b.wait(700);
  console.log("days:", await b.evaluate(`() => document.querySelectorAll(".plan-day").length`));
  console.log("plan text:", (await b.text(".plan") || "").slice(0, 300).replace(/\s+/g, " "));
} else {
  console.error("WARNING: no .plan card rendered — the shot will not show a plan");
}
await b.screenshot(OUT);
console.log("saved", OUT);
await b.close();
