// Browser-interaction scenarios, driven by the CDP harness (lib/cdp.mjs) against a running stack.
// Each scenario is { name, tags, fn(b, ctx) } where fn throws on failure. `tags` lets the runner pick a
// subset (e.g. skip animation-timing scenarios on a slow CI box). See SCENARIOS.md for the full plan;
// this file implements a high-value core PLUS the two forum-wedge regressions, and grows over time.
//
// ctx = { base, viewport } — base URL and the active viewport name ("desktop" | "mobile").

const uniq = (p) => p + Math.floor(performance.now()) + Math.floor(Math.random() * 1e4);

function assert(cond, msg) { if (!cond) throw new Error(msg); }

// ---- shared app helpers (drive the REAL UI, so they exercise the same code a user hits) ----

// Register + log in a brand-new user through the forms; returns the username. Assumes the stack runs with
// OTP/verify-email OFF (the E2E boot env), so both are one-step.
async function registerAndLogin(b) {
  const u = uniq("e2e"), pw = "Passw0rd!23";
  await b.goto(b.base + "/");
  await b.clearServiceWorkers();
  await b.goto(b.base + "/");
  await b.waitFor("#tab-register");
  await b.click("#tab-register");
  await b.waitFor("#reg-username");
  await b.type("#reg-username", u);
  await b.type("#reg-email", u + "@example.com");
  await b.type("#reg-password", pw);
  await b.submit("#register-form");
  // instant-create returns to the login tab; log in (generous waits — CI-runner boot can be slow)
  await b.waitFor("#login-form", { timeout: 15000 });
  await b.type("#login-username", u);
  await b.type("#login-password", pw);
  await b.submit("#login-form");
  await b.waitFor("#app-view", { timeout: 15000 });
  const inApp = await b.visible("#app-view");
  assert(inApp, "registerAndLogin: never reached the app view");
  return u;
}

async function gotoScreen(b, screen) {
  await b.pageExec(`(() => { const t = document.querySelector('[data-screen="${screen}"]'); if (t) t.click(); return !!t; })()`);
  await b.wait(700);
}

async function createPost(b, title, body, anonymous = false) {
  await gotoScreen(b, "forum");
  await b.waitFor("#forum-form");
  await b.type("#forum-form [name=title]", title);
  await b.type("#forum-form [name=body]", body);
  if (anonymous) await b.pageExec(`(() => { const c = document.querySelector("#forum-form [name=anonymous]"); if (c && !c.checked) c.click(); return true; })()`);
  await b.submit("#forum-form", 1200);
}

// ---- scenarios ----

export const SCENARIOS = [
  // ===== Landing (logged out) =====
  {
    name: "landing: orb demo cycles Ready->Moderate->Rest",
    tags: ["landing", "anim"],
    async fn(b) {
      await b.goto(b.base + "/");
      await b.clearServiceWorkers();
      await b.goto(b.base + "/");
      await b.waitFor("#demo-state");
      const first = await b.text("#demo-state");
      await b.wait(3400);   // one cycle tick (3s) + margin
      const second = await b.text("#demo-state");
      assert(first !== second, `orb state did not cycle (stuck on "${first}")`);
      assert(["Ready", "Moderate", "Rest"].includes(second), `unexpected state "${second}"`);
    },
  },
  {
    name: "landing: 3 steps present, redundant paragraph gone",
    tags: ["landing"],
    async fn(b) {
      await b.goto(b.base + "/");
      const steps = await b.evaluate(`() => document.querySelectorAll(".auth-steps li").length`);
      assert(steps >= 3, `expected 3 how-it-works steps, got ${steps}`);
      const hasParagraph = await b.exists(".hero-sub");
      assert(!hasParagraph, "the redundant value paragraph (.hero-sub) is back");
    },
  },
  {
    name: "landing/mobile: login reachable without scrolling; desktop: 2-col split",
    tags: ["landing", "responsive"],
    async fn(b, ctx) {
      await b.goto(b.base + "/");
      if (ctx.viewport === "mobile") {
        const r = await b.evaluate(`() => { const btn = [...document.querySelectorAll("#login-form button")].pop(); const rr = btn.getBoundingClientRect(); return { bottom: Math.round(rr.bottom), vh: window.innerHeight }; }`);
        assert(r.bottom <= r.vh, `mobile login button below the fold: ${r.bottom} > ${r.vh}`);
        const orbTop = await b.evaluate(`() => Math.round(document.querySelector(".readiness-demo").getBoundingClientRect().top)`);
        assert(orbTop < 160, `orb not near the top on mobile: ${orbTop}`);
      } else {
        const disp = await b.evaluate(`() => getComputedStyle(document.querySelector(".auth-split")).display`);
        assert(disp === "grid", `desktop landing should be a grid split, got ${disp}`);
      }
    },
  },

  // ===== Auth =====
  {
    name: "auth: register + login happy path",
    tags: ["auth"],
    async fn(b) {
      await registerAndLogin(b);
      assert(await b.visible("#app-view"), "not in the app after login");
      const who = await b.text("#who");
      assert(who && who.length > 0, "header greeting is empty after login");
    },
  },
  {
    name: "auth: login with wrong credentials is rejected (no app access)",
    tags: ["auth", "negative"],
    async fn(b) {
      await b.goto(b.base + "/");
      await b.clearServiceWorkers();
      await b.goto(b.base + "/");
      await b.waitFor("#login-form");
      await b.type("#login-username", "nobody_" + uniq("x"));
      await b.type("#login-password", "totally-wrong-xyz");
      await b.submit("#login-form", 1200);
      assert(await b.visible("#auth-view"), "wrong credentials should NOT enter the app");
      const flash = await b.text("#login-flash");
      assert(flash && flash.length > 0, "expected an error flash on wrong login");
    },
  },

  // ===== Forum (incl. the two wedge regressions) =====
  {
    name: "forum: create + open a post shows its detail",
    tags: ["forum"],
    async fn(b) {
      await registerAndLogin(b);
      await createPost(b, "E2E open test", "body text here");
      await b.waitFor("#forum-list .post");
      await b.click("#forum-list .post", 900);
      const shown = await b.evaluate(`() => { const d = document.getElementById("forum-detail"); return d && !d.hidden && d.innerHTML.length > 100; }`);
      assert(shown, "post detail did not render on open");
    },
  },
  // NOTE: no browser media scenario here — deliberately. The picker+submit version fails on headless CI
  // Chrome (script-set files are dropped on form submit), and a fetch-based render variant proved flaky on
  // CI too (timing/post-selection), so we don't chase it pre-demo. The media contract is covered for real,
  // deterministically, by HTTP tests: tests/Integration_Tests/test_media.py (upload→serve EXACT bytes,
  // attach-to-post/DM, foreign blob→not-bound, foreign post→403, bogus→404) and
  // tests/Security_Tests/test_media_limits.py (413/400/401, DM privacy). Frontend render is verified live.
  {
    name: "forum REGRESSION: voting does not wedge the forum (#forum-detail survives)",
    tags: ["forum", "regression"],
    async fn(b) {
      await registerAndLogin(b);
      await createPost(b, "E2E vote A", "aaa");
      await createPost(b, "E2E vote B", "bbb");
      await b.waitFor("#forum-list .post");
      await b.click("#forum-list .post", 900);                        // open post 1
      // upvote it (this calls loadForum, which used to destroy #forum-detail)
      await b.pageExec(`(async () => { const up = [...document.querySelectorAll("#forum-detail .vote-row button")].find(x => /up/i.test(x.textContent)); if (up) up.click(); await new Promise(r=>setTimeout(r,1300)); })()`);
      const detailAlive = await b.exists("#forum-detail");
      assert(detailAlive, "voting destroyed #forum-detail (the wedge)");
      // now open ANOTHER post — must work
      await b.pageExec(`(async () => { const ps = [...document.querySelectorAll("#forum-list .post")]; (ps[1]||ps[0]).click(); await new Promise(r=>setTimeout(r,1000)); })()`);
      const openedSecond = await b.evaluate(`() => { const d = document.getElementById("forum-detail"); return d && !d.hidden && d.innerHTML.length > 100; }`);
      assert(openedSecond, "could not open a post after voting (the wedge)");
    },
  },
  {
    name: "forum REGRESSION: a failed open does not wedge (failOpen recovers)",
    tags: ["forum", "regression"],
    async fn(b) {
      await registerAndLogin(b);
      await createPost(b, "E2E failopen", "ccc");
      await b.waitFor("#forum-list .post");
      // force the detail GET to fail via a one-shot fetch monkeypatch, then tap
      await b.pageExec(`(() => { const real = window.fetch; window.__realFetch = real; window.fetch = (u, o) => (typeof u === "string" && /\\/forum\\/posts\\/[0-9a-f]+$/.test(u) && (!o || (o.method||"GET")==="GET")) ? Promise.reject(new Error("forced")) : real(u, o); return true; })()`);
      await b.click("#forum-list .post", 1200);
      // restore fetch
      await b.pageExec(`(() => { if (window.__realFetch) window.fetch = window.__realFetch; return true; })()`);
      const notWedged = await b.evaluate(`() => { const p = document.querySelector("#forum-list .post"); return !p.classList.contains("open"); }`);
      assert(notWedged, "a failed open left the post stuck open (border) — the wedge");
      // and a subsequent real open works
      await b.click("#forum-list .post", 1000);
      const opensNow = await b.evaluate(`() => { const d = document.getElementById("forum-detail"); return d && !d.hidden && d.innerHTML.length > 100; }`);
      assert(opensNow, "could not open the post after a failed open");
    },
  },
  {
    name: "forum: add a comment appears in the detail",
    tags: ["forum"],
    async fn(b) {
      await registerAndLogin(b);
      await createPost(b, "E2E comment", "ddd");
      await b.waitFor("#forum-list .post");
      await b.click("#forum-list .post", 900);
      await b.waitFor("#comment-form");
      await b.type("#comment-form [name=body]", "a fine comment");
      await b.submit("#comment-form", 1200);
      const hasComment = await b.evaluate(`() => (document.querySelector("#forum-detail .comments") || {}).textContent?.includes("a fine comment") || false`);
      assert(hasComment, "comment did not appear after submit");
    },
  },

  {
    name: "resilience REGRESSION: a dropped request shows an error, not a stuck spinner",
    tags: ["resilience", "regression"],
    async fn(b) {
      await registerAndLogin(b);
      // make the next /dashboard fetch reject (a dropped request on the flaky prod host)
      await b.pageExec(`(() => { const real = window.fetch; window.__realFetch = real;
        window.fetch = (u, o) => (typeof u === "string" && u.indexOf("/dashboard") !== -1) ? Promise.reject(new Error("dropped")) : real(u, o); return true; })()`);
      // trigger a dashboard reload (Refresh) and let it settle
      await b.pageExec(`(() => { const btn = document.getElementById("dashboard-refresh"); if (btn) btn.click(); return true; })()`);
      await b.wait(1200);
      await b.pageExec(`(() => { if (window.__realFetch) window.fetch = window.__realFetch; return true; })()`);
      const dash = await b.text("#dashboard");
      assert(dash && !/loading/i.test(dash), `dashboard stuck on a spinner after a dropped request: "${dash}"`);
      assert(dash && /could not|unavailable|error|try again/i.test(dash), `dropped request showed no error message: "${dash}"`);
    },
  },

  // ===== Profile =====
  {
    name: "profile: change display name updates the header",
    tags: ["profile"],
    async fn(b) {
      await registerAndLogin(b);
      // open the corner menu -> Profile
      await b.pageExec(`(() => { const btn = document.getElementById("user-menu-btn"); if (btn) btn.click(); return true; })()`);
      await b.wait(300);
      await b.pageExec(`(() => { const p = document.querySelector('[data-act="profile"]'); if (p) p.click(); return true; })()`);
      await b.waitFor("#displayname-form");
      const newName = "Renamed" + Math.floor(performance.now() % 10000);
      await b.type("#displayname-input", newName);
      await b.submit("#displayname-form", 1200);
      const who = await b.text("#who");
      assert(who && who.includes(newName), `header did not update to the new name (got "${who}")`);
    },
  },
  {
    name: "profile: theme dark vs light apply different palettes",
    tags: ["profile", "theme"],
    async fn(b) {
      await registerAndLogin(b);
      const bgFor = async (t) => {
        await b.pageExec(`(() => { document.documentElement.setAttribute("data-theme", ${JSON.stringify(t)}); return true; })()`);
        await b.wait(250);
        return b.evaluate(`() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()`);
      };
      const dark = await bgFor("dark");     // force each explicitly -> deterministic regardless of the OS default
      const light = await bgFor("light");
      assert(dark && light && dark !== light, `dark and light --bg should differ (dark=${dark} light=${light})`);
    },
  },
  {
    // Design pass ⑦: the forum reuses the DM generative-avatar system on every author surface.
    name: "forum: posts + comments render generative avatars",
    tags: ["forum", "design"],
    async fn(b) {
      await registerAndLogin(b);
      await createPost(b, uniq("Avatars "), "does everyone get an avatar?");
      await b.waitFor("#forum-list .post");
      const listAv = await b.evaluate(`() => document.querySelectorAll("#forum-list .post .avatar").length`);
      assert(listAv >= 1, "no generative avatar on the forum list byline");
      await b.click("#forum-list .post", 900);
      const detailAv = await b.evaluate(`() => document.querySelectorAll("#forum-detail .by .avatar").length`);
      assert(detailAv >= 1, "no avatar on the open post's author line");
      await b.type("#comment-form [name=body]", "great question");
      await b.submit("#comment-form", 1100);
      const cAv = await b.evaluate(`() => document.querySelectorAll("#forum-detail .comments li .avatar").length`);
      assert(cAv >= 1, "no avatar on the comment row");
    },
  },
  {
    // Design pass ⑧: the profile screen is grouped into exactly 4 cards (You / Preferences / Account / Danger).
    name: "profile: settings are grouped into 4 cards",
    tags: ["profile", "design"],
    async fn(b) {
      await registerAndLogin(b);
      // profile is reached via the corner account menu (not a bottom tab) — same nav as the display-name scenario
      await b.pageExec(`(() => { const btn = document.getElementById("user-menu-btn"); if (btn) btn.click(); return true; })()`);
      await b.wait(300);
      await b.pageExec(`(() => { const p = document.querySelector('[data-act="profile"]'); if (p) p.click(); return true; })()`);
      await b.waitFor("#screen-profile .card");
      const cards = await b.evaluate(`() => document.querySelectorAll("#screen-profile .card").length`);
      assert(cards === 4, `profile should be 4 grouped cards, got ${cards}`);
      // all six section eyebrows must still be present inside those 4 cards
      const eyebrows = await b.evaluate(`() => document.querySelectorAll("#screen-profile .card h2").length`);
      assert(eyebrows === 6, `expected 6 section eyebrows inside the grouped cards, got ${eyebrows}`);
    },
  },
  {
    // iOS-26 / Instagram scroll: header frosts (.scrolled) + the MOBILE tab bar SHRINKS to icon-only
    // (.nav-compact) on scroll-down, and expands back on scroll-up. Mobile-only (pill is display:none on desktop).
    name: "nav: header frosts + tab bar shrinks on scroll-down, expands on scroll-up",
    tags: ["nav", "scroll", "design"],
    async fn(b, ctx) {
      if (ctx.viewport !== "mobile") return;                 // tab-bar shrink is a mobile-only behaviour
      await registerAndLogin(b);
      await b.pageExec(`(async () => { document.body.style.minHeight='3000px'; window.scrollTo(0, 700); await new Promise(r=>setTimeout(r,350)); })()`);
      const down = await b.evaluate(`() => ({s: document.documentElement.classList.contains('scrolled'), h: document.documentElement.classList.contains('nav-compact')})`);
      assert(down.s, "header should gain .scrolled after scrolling down");
      assert(down.h, "the tab bar should shrink (.nav-compact) on scroll-down");
      await b.pageExec(`(async () => { window.scrollTo(0, 120); await new Promise(r=>setTimeout(r,350)); })()`);
      const up = await b.evaluate(`() => document.documentElement.classList.contains('nav-compact')`);
      assert(!up, "the tab bar should expand (.nav-compact removed) on scroll-up");
    },
  },
  {
    // WhatsApp-style: the nav selection capsule SLIDES to the tapped tab (its transform changes per tab).
    name: "nav: selection indicator slides to the tapped tab",
    tags: ["nav", "design"],
    async fn(b, ctx) {
      if (ctx.viewport !== "mobile") return;                 // the sliding pill is the mobile nav
      await registerAndLogin(b);
      await b.pageExec(`(() => { const t = document.querySelector('.tab[data-screen="forum"]'); if (t) t.click(); return true; })()`);
      await b.wait(450);
      const t1 = await b.evaluate(`() => (document.querySelector('.tab-indicator') || {style:{}}).style.transform`);
      await b.pageExec(`(() => { const t = document.querySelector('.tab[data-screen="messages"]'); if (t) t.click(); return true; })()`);
      await b.wait(450);
      const t2 = await b.evaluate(`() => (document.querySelector('.tab-indicator') || {style:{}}).style.transform`);
      assert(t1 && t2 && t1 !== t2, `the selection capsule should slide between tabs (forum=${t1} chat=${t2})`);
    },
  },
];
