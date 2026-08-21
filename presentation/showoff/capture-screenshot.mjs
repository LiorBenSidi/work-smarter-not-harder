// Capture an app screenshot for the gallery poster, by driving the repo's own E2E harness.
//
//   docker compose up -d                                   # stack must be running on :8000
//   node presentation/showoff/capture-screenshot.mjs poster-assets/shot-6-plan.png
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
if (!OUT) {
  console.error("usage: node capture-screenshot.mjs <output.png>");
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
  const f = document.getElementById("profile-form");
  out.form = !!f;
  if (f) f.requestSubmit();
  return out;
})()`);
console.log("profile ->", JSON.stringify(profiled));
await b.wait(1400);

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
