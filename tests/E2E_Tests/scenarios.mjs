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

// Delete the forum posts this scenario created — matched on the unique marker in their titles — and prove
// none is left. The whole run shares ONE database, so a post left behind changes what every later scenario
// renders; that is how seven scenarios went red at once in #449. Deleting the post takes its comments with
// it (`forum_delete_post`), so comment-creating scenarios need nothing extra.
//
// The assertions are the point. A teardown that silently finds nothing re-creates the leak while looking
// like it ran, so this fails loudly both when it cannot find its own posts and when any survive.
async function cleanupPosts(b, marker, expected = 1) {
  const find = `(list.posts || []).filter((p) => String(p.title).includes(${JSON.stringify(marker)}))`;
  const removed = await b.pageExec(`(async () => {
    const csrf = (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || "";
    const list = await (await fetch("/forum/posts")).json();
    const mine = ${find};
    for (const p of mine) await fetch("/forum/posts/" + p.id, { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
    return mine.length;
  })()`);
  assert(removed >= expected,
    `teardown found ${removed} of its own post(s) but created ${expected} — the rest leak into later scenarios`);
  const left = await b.pageExec(`(async () => {
    const list = await (await fetch("/forum/posts")).json();
    return ${find}.length;
  })()`);
  assert(left === 0, `teardown left ${left} post(s) matching ${JSON.stringify(marker)} in the shared forum`);
}

async function createPost(b, title, body, anonymous = false) {
  await gotoScreen(b, "forum");
  await b.waitFor("#forum-form");
  await b.type("#forum-form [name=title]", title);
  await b.type("#forum-form [name=body]", body);
  if (anonymous) await b.pageExec(`(() => { const c = document.querySelector("#forum-form [name=anonymous]"); if (c && !c.checked) c.click(); return true; })()`);
  await b.submit("#forum-form", 1200);
}

// A SECOND user driven over plain HTTP from the runner (node fetch, own cookie jar) — for cross-user
// scenarios where someone else's action must reach the browser user (votes, DMs). Assumes the E2E boot
// env (OTP/verify OFF), same as registerAndLogin.
async function apiUser(base) {
  const jar = new Map();
  const cookieHeader = () => [...jar.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
  const call = async (path, opts = {}) => {
    const headers = { cookie: cookieHeader(), "X-CSRF-Token": jar.get("csrf_token") || "", ...(opts.body ? { "content-type": "application/json" } : {}), ...opts.headers };
    const r = await fetch(base + path, { ...opts, headers });
    for (const c of r.headers.getSetCookie?.() || []) {
      const [pair] = c.split(";"); const eq = pair.indexOf("=");
      jar.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
    }
    let data = null; try { data = await r.json(); } catch { /* non-JSON */ }
    return { status: r.status, data };
  };
  await call("/health");                                     // seed the csrf cookie
  const u = uniq("e2eapi"), pw = "Passw0rd!23";
  const reg = await call("/register", { method: "POST", body: JSON.stringify({ username: u, password: pw, email: u + "@example.com" }) });
  if (reg.status !== 201) throw new Error(`apiUser register failed: ${reg.status}`);
  const login = await call("/login", { method: "POST", body: JSON.stringify({ username: u, password: pw }) });
  if (login.status !== 200) throw new Error(`apiUser login failed: ${login.status}`);
  return { username: u, call };
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
      const marker = uniq("E2E open ");            // unique, so teardown deletes only this run's row
      await createPost(b, marker, "body text here");
      await b.waitFor("#forum-list .post");
      await b.click("#forum-list .post", 900);
      const shown = await b.evaluate(`() => { const d = document.getElementById("forum-detail"); return d && !d.hidden && d.innerHTML.length > 100; }`);
      assert(shown, "post detail did not render on open");
      await cleanupPosts(b, marker);
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
      const marker = uniq("E2Evote");              // one marker, both posts -> one teardown
      await createPost(b, marker + " A", "aaa");
      await createPost(b, marker + " B", "bbb");
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
      await cleanupPosts(b, marker, 2);            // the vote goes with the post it was cast on
    },
  },
  {
    name: "forum REGRESSION: a failed open does not wedge (failOpen recovers)",
    tags: ["forum", "regression"],
    async fn(b) {
      await registerAndLogin(b);
      const marker = uniq("E2E failopen ");
      await createPost(b, marker, "ccc");
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
      await cleanupPosts(b, marker);
    },
  },
  {
    name: "forum: add a comment appears in the detail",
    tags: ["forum"],
    async fn(b) {
      await registerAndLogin(b);
      const marker = uniq("E2E comment ");
      await createPost(b, marker, "ddd");
      await b.waitFor("#forum-list .post");
      await b.click("#forum-list .post", 900);
      await b.waitFor("#comment-form");
      await b.type("#comment-form [name=body]", "a fine comment");
      await b.submit("#comment-form", 1200);
      const hasComment = await b.evaluate(`() => (document.querySelector("#forum-detail .comments") || {}).textContent?.includes("a fine comment") || false`);
      assert(hasComment, "comment did not appear after submit");
      await cleanupPosts(b, marker);               // deleting the post takes the comment with it
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
    // #342 (second instance): the engagement strip must be CURRENT when the user actually looks at it —
    // another user's vote lands while I'm elsewhere; re-entering Profile re-syncs the strip instead of
    // painting the boot-time snapshot forever.
    name: "profile REGRESSION: engagement strip re-syncs on entry (another user's vote shows)",
    tags: ["profile", "engagement"],
    async fn(b, ctx) {
      await registerAndLogin(b);
      const title = uniq("Engage ");
      await createPost(b, title, "vote bait");
      // First profile visit: strip renders (zeros — nobody voted yet)
      const openProfile = async () => {
        await b.pageExec(`(() => { const btn = document.getElementById("user-menu-btn"); if (btn) btn.click(); return true; })()`);
        await b.wait(300);
        await b.pageExec(`(() => { const p = document.querySelector('[data-act="profile"]'); if (p) p.click(); return true; })()`);
        await b.wait(700);                                   // let the entry re-sync land
      };
      await openProfile();
      await b.waitFor("#engagement-strip");
      const before = await b.text("#engagement-strip");
      assert(before && !/[1-9]/.test(before), `expected an all-zero strip before any votes (got "${before}")`);
      // Leave Profile (strip now cached), then a SECOND user upvotes my post over HTTP
      await gotoScreen(b, "forum");
      const other = await apiUser(ctx.base);
      const posts = await other.call("/forum/posts");
      const mine = (posts.data.posts || []).find((p) => p.title === title);
      assert(mine, "second user could not see the post to vote on");
      const vote = await other.call(`/forum/posts/${mine.id}/vote`, { method: "POST", body: JSON.stringify({ value: 1 }) });
      assert(vote.status === 200, `second user's vote failed: ${vote.status}`);
      // Re-enter Profile: the strip must show the received upvote, not the boot-time zeros
      await openProfile();
      const after = await b.text("#engagement-strip");
      assert(/1/.test(after), `engagement strip still stale after re-entry (got "${after}")`);
      await cleanupPosts(b, title);                // the second user's vote is stored on this post
    },
  },
  {
    // Design pass ⑦: the forum reuses the DM generative-avatar system on every author surface.
    name: "forum: posts + comments render generative avatars",
    tags: ["forum", "design"],
    async fn(b) {
      await registerAndLogin(b);
      const marker = uniq("Avatars ");
      await createPost(b, marker, "does everyone get an avatar?");
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
      await cleanupPosts(b, marker);
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

  // The check-in gate, driven through the real form. Two DIFFERENT requirements are covered here and it is
  // worth being explicit about which is which:
  //
  //   1. VALIDATION — an incomplete or out-of-range check-in must not be saved. Asserted by the outcome
  //      (submit, then read /history back), so any implementation that refuses would pass.
  //   2. ACCESSIBILITY — the button must ANNOUNCE that it is unavailable. aria-disabled is the contract a
  //      screen reader reads; hiding or restyling the button would leave those users with no affordance,
  //      so this one is asserted on the attribute deliberately, not as a proxy for (1).
  //
  // A served-shell test can only prove the validator is PRESENT in the bundle. Replacing validateCheckin's
  // body with `return true` leaves every served-shell assertion green — these steps go red.
  {
    name: "checkin: an incomplete check-in is refused, and the button says so",
    tags: ["checkin"],
    async fn(b) {
      await registerAndLogin(b);                                  // fresh user => history starts empty
      await b.waitFor("#checkin-form");
      const gate = `() => {
        const btn = document.querySelector("#checkin-form button[type=submit]");
        return btn ? btn.getAttribute("aria-disabled") : "no-button";
      }`;
      // The requirement's ground truth: what the server actually stored.
      const savedCount = async () => b.pageExec(`(async () => {
        const r = await fetch("/history", { headers: { "X-CSRF-Token": (document.cookie.match(/csrf_token=([^;]+)/)||[])[1] || "" } });
        const j = await r.json();
        return (j.history || j.items || []).length;
      })()`);

      assert(await savedCount() === 0, "a brand-new user should start with no check-ins");
      assert(await b.evaluate(gate) === "true", "an untouched check-in form must announce Submit as unavailable");

      // (1) EMPTY form — stopped by the FIRST defence: `required` on the two numeric inputs means the
      // browser's own constraint validation rejects the submit before any app code runs. Nothing is saved,
      // and deliberately no app message appears — the browser shows its native bubble instead.
      assert(await b.evaluate(`() => document.querySelector("#checkin-form").checkValidity()`) === false,
        "an empty check-in form should be natively invalid — the required inputs are the first defence");
      await b.pageExec(`(() => { document.querySelector("#checkin-form").requestSubmit(); return true; })()`);
      await b.wait(900);
      assert(await savedCount() === 0, "an empty check-in was SAVED — nothing refused it");

      await b.type("#sleep_hours", "7");
      await b.type("#resting_hr", "55");
      assert(await b.evaluate(gate) === "true",
        "the numbers alone must not open the gate — fatigue/soreness/training_load are still unset");

      // (2) The SECOND defence, and the one that actually matters. Only the two numeric inputs are
      // `required`, so filling them satisfies the browser and the submit now reaches the app. The scales
      // are still unset, so the app itself must refuse it — and tell the user why.
      assert(await b.evaluate(`() => document.querySelector("#checkin-form").checkValidity()`) === true,
        "with both numbers filled the form is natively valid, so the app's own guard is what is under test");
      await b.pageExec(`(() => { document.querySelector("#checkin-form").requestSubmit(); return true; })()`);
      await b.wait(900);
      assert(await savedCount() === 0,
        "a check-in with no fatigue/soreness/training_load was SAVED — the app's own guard did not refuse it");
      const why = await b.text("#checkin-flash");
      assert(why && why.trim().length > 0,
        "the app refused the check-in but told the user nothing about why");

      await b.pageExec(`(() => {
        document.querySelectorAll("#checkin-form .scale").forEach((sc) => {
          const btn = sc.querySelector("button");
          if (btn) btn.click();
        });
        return true;
      })()`);
      await b.wait(150);
      assert(await b.evaluate(gate) === "false", "a fully-filled check-in must announce Submit as available");

      // (3) Below the model's floor (sleep_hours >= 1): the gate shuts AND a submit must still save nothing.
      await b.pageExec(`(() => {
        const el = document.getElementById("sleep_hours");
        el.value = "0";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        return true;
      })()`);
      await b.wait(150);
      assert(await b.evaluate(gate) === "true",
        "sleep_hours below the model's minimum must re-announce Submit as unavailable");
      await b.pageExec(`(() => { document.querySelector("#checkin-form").requestSubmit(); return true; })()`);
      await b.wait(900);
      assert(await savedCount() === 0,
        "a check-in with sleep_hours below the model's minimum was SAVED");

      // No teardown needed: every submit above is expected to be refused, so this scenario stores nothing.
      // If that ever stops being true the assertions fail first, which is the point.
    },
  },

  // Stored XSS, end to end. The requirement (GUIDELINES: defences against injection attacks) is that
  // attacker-supplied content must never execute, while the author's post stays readable. This asserts
  // that OUTCOME, deliberately not the mechanism: escaping, sanitising or stripping would each pass, so
  // the test survives a change of defence and only fails if the app becomes vulnerable.
  //
  // It is reachable because the API returns titles/bodies verbatim — a title posted as
  // `<img src=x onerror=...>` comes back byte-identical — and the SPA renders them via innerHTML, so the
  // client is the only barrier. A served-shell test can grep that escapeHtml appears in the bundle;
  // only a browser can prove the payload does not RUN.
  {
    name: "security: injected markup from another user never executes",
    tags: ["security", "forum"],
    async fn(b) {
      await registerAndLogin(b);
      const payload = `<img src=x onerror="window.__xssFired = true">`;
      const marker = "xss-probe-" + Math.floor(performance.now());

      await createPost(b, `${marker} ${payload}`, `body ${payload}`);
      await gotoScreen(b, "forum");
      await b.waitFor("#forum-list");
      await b.wait(400);

      // The requirement: attacker-supplied content must not run.
      const fired = await b.evaluate(`() => window.__xssFired === true`);
      assert(fired === false, "the injected onerror handler EXECUTED — user content reached the DOM as live markup");

      // ...and must not become a live element that could fire later or leak a request.
      const injected = await b.evaluate(`() => document.querySelectorAll('#forum-list img[src="x"]').length`);
      assert(injected === 0, `the payload became ${injected} live <img> element(s)`);

      // The other half of the requirement: defending must not cost the author their post.
      const shown = await b.evaluate(
        `() => (document.querySelector("#forum-list") || {}).textContent || ""`);
      assert(shown.includes(marker), "the post vanished from the feed — a defence must not drop the content");

      // Teardown — the same helper the other post-creating scenarios use, so the rule can't hold here and
      // drift somewhere else. Leaving a post whose title carries markup is the worst version of the leak:
      // it changes what every later scenario renders.
      await cleanupPosts(b, marker);
    },
  },

  // Account deletion is the one irreversible action in the app, so the confirmation word is the last
  // thing standing between a mis-click and a wiped account. `test_account_and_auth_markup_and_handlers_are_served` greps the
  // served shell for `!== "DELETE"` — which passes just as happily if the comparison is inverted, made
  // case-insensitive, or never wired to the button at all. Only a browser can prove the button is
  // genuinely unusable until the exact word is present.
  //
  // Deliberately never submits: the assertion is about the GATE, and a scenario that actually deleted its
  // user would also destroy the evidence it was testing.
  {
    name: "account: the delete gate stays shut until the exact confirmation word is typed",
    tags: ["profile", "account", "security"],
    async fn(b) {
      await registerAndLogin(b);
      // Profile is deliberately NOT a bottom-nav tab — it lives behind the corner account menu, so
      // gotoScreen() cannot reach it. (That absence is itself an asserted design decision.)
      await b.pageExec(`(() => { const btn = document.getElementById("user-menu-btn"); if (btn) btn.click(); return true; })()`);
      await b.wait(300);
      await b.pageExec(`(() => { const p = document.querySelector('[data-act="profile"]'); if (p) p.click(); return true; })()`);
      await b.waitFor("#delete-reveal");

      // the danger zone starts collapsed — revealing it must not by itself arm anything
      await b.pageExec(`(() => { document.getElementById("delete-reveal").click(); return true; })()`);
      await b.wait(250);
      const btnDisabled = `() => {
        const btn = document.querySelector("#delete-form button[type=submit]");
        return btn ? btn.disabled : "no-button";
      }`;
      assert(await b.evaluate(btnDisabled) === true,
        "the delete button was already usable the moment the form appeared");

      // a password alone must not arm it — the confirmation word is a SEPARATE gate
      await b.type("#delete-password", "Passw0rd!23");
      await b.wait(150);
      assert(await b.evaluate(btnDisabled) === true,
        "the correct password alone armed the delete button — the typed word is meant to be a second gate");

      // near-misses stay shut. Lower-case is the one that matters: the input carries
      // autocapitalize=characters, so a phone may well offer "delete" and a case-insensitive
      // comparison would arm the button on a word the user never deliberately typed.
      for (const near of ["delete", "DELET", "DELETED", " DELETE X"]) {
        await b.pageExec(`(() => {
          const el = document.getElementById("delete-confirm");
          el.value = ${JSON.stringify(near)};
          el.dispatchEvent(new Event("input", { bubbles: true }));
          return true;
        })()`);
        await b.wait(120);
        assert(await b.evaluate(btnDisabled) === true,
          `typing ${JSON.stringify(near)} armed the delete button — only the exact word may open this gate`);
      }

      // ...and the exact word opens it, or the gate would be impossible to pass legitimately
      await b.pageExec(`(() => {
        const el = document.getElementById("delete-confirm");
        el.value = "DELETE";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        return true;
      })()`);
      await b.wait(150);
      assert(await b.evaluate(btnDisabled) === false,
        "the exact confirmation word did NOT arm the button — the gate cannot be passed at all");

      // nothing was submitted, so the account must still be there
      const stillAlive = await b.pageExec(`(async () => (await fetch("/me")).status)()`);
      assert(stillAlive === 200, `the account did not survive a gate-only test (GET /me -> ${stillAlive})`);
    },
  },

  // History's per-entry detail is where a user checks what they actually logged on a given day. The
  // served-shell test greps for `openHistoryDetail` and the modal's ids; that passes even if the modal
  // renders a fixed template, another entry's numbers, or nothing at all.
  //
  // This logs a check-in with deliberately distinctive values and asserts the modal shows THOSE — so it
  // fails if the detail is wired to anything other than the entry that was opened.
  {
    name: "history: opening an entry shows the values that were actually logged",
    tags: ["history", "checkin"],
    async fn(b) {
      await registerAndLogin(b);                                  // fresh user => exactly one entry after this
      await b.waitFor("#checkin-form");

      // distinctive on purpose: 6.5h / 61bpm are unlikely to appear by coincidence in a template
      await b.type("#sleep_hours", "6.5");
      await b.type("#resting_hr", "61");
      const pick = async (field, value) => {
        const ok = await b.pageExec(`(() => {
          const sc = document.querySelector('[data-field="${field}"]');
          if (!sc) return "no-scale";
          const btn = [...sc.querySelectorAll("button")].find((x) => x.textContent.trim() === "${value}");
          if (!btn) return "no-button";
          btn.click();
          return document.getElementById("${field}").value;
        })()`);
        assert(String(ok) === String(value), `could not set ${field} to ${value} (got ${ok})`);
      };
      await pick("fatigue", 7);
      await pick("soreness", 3);
      await pick("training_load", 8);

      await b.pageExec(`(() => { document.querySelector("#checkin-form").requestSubmit(); return true; })()`);
      await b.wait(2500);                                          // the check-in round-trips through the ai container
      const saved = await b.pageExec(`(async () => {
        const r = await fetch("/history", { headers: { "X-CSRF-Token": (document.cookie.match(/csrf_token=([^;]+)/)||[])[1] || "" } });
        return ((await r.json()).history || []).length;
      })()`);
      assert(saved === 1, `expected exactly one stored check-in before opening it, got ${saved}`);

      await gotoScreen(b, "history");
      await b.waitFor("#history");
      const opened = await b.pageExec(`(() => {
        const row = document.querySelector("#history .hrow");
        if (!row) return "no-row";
        row.click();
        return true;
      })()`);
      assert(opened === true, "the stored check-in did not render a row in History");
      await b.wait(600);

      assert(await b.visible("#history-detail"), "clicking a History row did not open its detail");

      // the load-bearing assertion: the modal shows the inputs THIS entry was logged with
      const shown = await b.text("#hdetail-body");
      for (const [label, value] of [["sleep", "6.5"], ["resting hr", "61"], ["fatigue", "7"], ["soreness", "3"], ["training load", "8"]]) {
        assert(shown.includes(value),
          `the detail is missing the ${label} value that was logged (${value}) — body was: ${shown.slice(0, 400)}`);
      }

      // ESC closes it and hands the page back — a modal that traps the user is worse than no modal
      await b.pageExec(`(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); return true; })()`);
      await b.wait(400);
      assert(!(await b.visible("#history-detail")), "ESC did not close the History detail");
      const locked = await b.evaluate(`() => document.documentElement.style.overflow + "|" + document.body.style.overflowY`);
      assert(!/hidden/.test(locked), `the page scroll lock survived the modal closing (${locked})`);

      // No teardown: the only state is one check-in belonging to this scenario's own throwaway user,
      // which no other scenario reads. Nothing is written to the shared forum.
    },
  },

  // Readiness is scored from the LATEST check-in, whenever that was — so the sentence under the orb may
  // not call every score "today's check-in". It did (#450), which contradicted the streak badge two lines
  // above it ("Start a new streak: check in today") and made the front page look like it was serving
  // stale data when only the wording was wrong.
  //
  // The check-in here is real and so is the /dashboard round-trip that scores it; the ONLY thing faked is
  // the page's idea of "now", moved forward 19 days between the two reads. That is the single variable
  // under test, and it cannot be reached any other way — the app deliberately stamps a check-in with the
  // server's clock, so there is no supported route to an entry dated in the past.
  {
    name: "readiness: the card names the day it scored, not always today",
    tags: ["checkin", "dashboard"],
    async fn(b) {
      await registerAndLogin(b);
      await b.waitFor("#checkin-form");
      await b.type("#sleep_hours", "7");
      await b.type("#resting_hr", "58");
      for (const [field, value] of [["fatigue", 4], ["soreness", 3], ["training_load", 5]]) {
        await b.pageExec(`(() => { const sc = document.querySelector('[data-field="${field}"]');
          const btn = [...sc.querySelectorAll("button")].find((x) => x.textContent.trim() === "${value}"); btn.click(); return true; })()`);
      }
      await b.pageExec(`(() => { document.querySelector("#checkin-form").requestSubmit(); return true; })()`);

      // The check-in round-trips through the ai container, and a shared CI runner takes several times
      // longer at it than a local machine — so wait for the card to actually paint rather than for a
      // fixed number of milliseconds. Until it does, `#dashboard` holds the skeleton, whose textContent
      // is "" — which would read as "the card said nothing" instead of "the card is still loading".
      // `[role="img"]` is what makes this a REAL score: the pre-check-in card also draws an orb with a
      // number in it, but that one is the greyed "Example" and is aria-hidden. Matching on the score
      // alone returns that placeholder instantly and the wait does nothing at all.
      const cardText = async (timeout = 25000) => {
        for (let waited = 0; waited < timeout; waited += 400) {
          if (await b.exists('#dashboard .readiness .orb[role="img"]')) return await b.text("#dashboard");
          await b.wait(400);
        }
        return await b.text("#dashboard");                 // timed out: report whatever is there
      };

      const fresh = await cardText();
      assert(/today's check-in/i.test(fresh),
        `a check-in logged moments ago is today's, but the card said: ${JSON.stringify(String(fresh).slice(0, 200))}`);

      // the day this check-in was actually stored, read back from the app and parsed by hand (NOT with the
      // same date API the page formats with, so this is an independent oracle)
      const ts = await b.pageExec(`(async () => {
        const r = await fetch("/history", { headers: { "X-CSRF-Token": (document.cookie.match(/csrf_token=([^;]+)/)||[])[1] || "" } });
        const h = (await r.json()).history || [];
        return h.length ? h[h.length - 1].timestamp : null;
      })()`);
      assert(typeof ts === "string" && ts.length >= 10, `could not read back the stored check-in's timestamp (${ts})`);
      const loggedDay = String(Number(ts.slice(8, 10)));    // "2026-08-08" -> "8"

      // move the page 19 days on — enough that the stored day-of-month can never coincide with the shifted
      // one — and re-run the app's own dashboard load against the unchanged server data
      await b.pageExec(`(() => {
        const Real = Date; window.__RealDate = Real; const SHIFT = 19 * 86400000;
        window.Date = class extends Real {
          constructor(...a) { if (a.length === 0) super(Real.now() + SHIFT); else super(...a); }
          static now() { return Real.now() + SHIFT; }
        };
        return true;
      })()`);
      await b.pageExec(`loadDashboard()`);
      const stale = await cardText();                       // same wait-for-paint, same reason
      await b.pageExec(`(() => { window.Date = window.__RealDate; return true; })()`);

      assert(!/today's check-in/i.test(stale),
        `19 days later the same score was still called today's check-in: ${JSON.stringify(String(stale).slice(0, 220))}`);
      const named = /last check-in \(([^)]+)\)/i.exec(String(stale));
      assert(named,
        `the card stopped claiming today's but never named the day it scored: ${JSON.stringify(String(stale).slice(0, 220))}`);
      // read the day out of the parenthetical ONLY — the rest of the card is full of numbers (the score,
      // the confidence percentages), so a whole-card search would pass on a wrong date by coincidence
      assert(new RegExp(`\\b${loggedDay}\\b`).test(named[1]),
        `the card named "${named[1]}", but the check-in was logged on day ${loggedDay} (${ts})`);

      // No teardown: one check-in on this scenario's own throwaway user, and the clock patch is reverted
      // above — the page is handed back exactly as found.
    },
  },

  // A message arriving must not throw away the thread you are reading. It used to re-render the whole
  // list — measured on the live app, 0 of 21 bubbles survived one incoming message — which silently
  // dropped whatever text the reader had selected, mid-quote.
  //
  // Node identity is the assertion that matters: each bubble is marked before the message arrives, and the
  // marks are counted after. A mark cannot survive innerHTML being replaced, so this fails the moment the
  // thread goes back to being rebuilt, even if the finished screen looks identical.
  {
    name: "messages: an arriving message keeps the thread you are reading",
    tags: ["messages", "realtime"],
    async fn(b) {
      const me = await registerAndLogin(b);
      const peer = await apiUser(b.base);
      for (let i = 1; i <= 6; i++) {                    // /messages caps one sender at 20 a minute
        const r = await peer.call("/messages", { method: "POST", body: JSON.stringify({ to: me, body: `seeded line ${i} — something worth quoting back` }) });
        assert(r.status === 201, `seeding message ${i} failed: ${r.status}`);
      }
      await gotoScreen(b, "messages");
      await b.waitFor("#dm-conversations");
      const opened = await b.pageExec(`(() => { const r = [...document.querySelectorAll("#dm-conversations [data-peer]")]
        .find((x) => x.dataset.peer === ${JSON.stringify(peer.username)}); if (r) r.click(); return !!r; })()`);
      assert(opened === true, "the seeded conversation never appeared in the inbox");
      await b.wait(1400);

      // Wait for the seeded thread to actually render before touching it. A slow runner had the bubbles
      // not yet painted, so the selection ran against bubbles[1] === undefined and threw inside the page
      // rather than failing the assertion below (seen on CI, mobile pass).
      for (let waited = 0; waited < 15000; waited += 400) {
        if (await b.evaluate(`() => document.querySelectorAll("#dm-thread .bubble").length >= 6`)) break;
        await b.wait(400);
      }
      const marked = await b.pageExec(`(() => {
        const bubbles = [...document.querySelectorAll("#dm-thread .bubble")];
        if (bubbles.length < 2) return bubbles.length;                     // let the assertion report it
        bubbles.forEach((el, i) => { el.__kept = i; });
        const r = document.createRange(); r.selectNodeContents(bubbles[1]);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
        return bubbles.length;
      })()`);
      assert(marked >= 6, `expected the seeded thread to be on screen, saw ${marked} bubbles`);
      const selectionBefore = await b.pageExec(`getSelection().toString()`);
      assert(selectionBefore && selectionBefore.includes("seeded line"),
        `could not select text in the thread to begin with (got ${JSON.stringify(selectionBefore)})`);

      await peer.call("/messages", { method: "POST", body: JSON.stringify({ to: me, body: "and one more, arriving while you read" }) });
      // Wait for the message to actually land rather than for a fixed number of milliseconds: delivery goes
      // through the live channel with a 45s poll behind it, and a loaded CI runner is slower than a laptop.
      for (let waited = 0; waited < 30000; waited += 500) {
        if (await b.pageExec(`document.querySelector("#dm-thread").textContent.includes("arriving while you read")`)) break;
        await b.wait(500);
      }

      const after = await b.pageExec(`(() => {
        const bubbles = [...document.querySelectorAll("#dm-thread .bubble")];
        return JSON.stringify({ total: bubbles.length, kept: bubbles.filter((el) => el.__kept !== undefined).length,
          selection: getSelection().toString(), last: bubbles[bubbles.length - 1].textContent });
      })()`);
      const state = JSON.parse(after);
      assert(state.last.includes("arriving while you read"),
        `the new message never reached the open thread: last bubble was ${JSON.stringify(state.last.slice(0, 60))}`);
      assert(state.kept >= marked - 1,
        `the thread was rebuilt around the new message — only ${state.kept} of ${marked} bubbles survived`);
      assert(state.selection === selectionBefore,
        `the reader's selection was destroyed by the arriving message: ${JSON.stringify(selectionBefore)} -> ${JSON.stringify(state.selection)}`);

      // No message state to clean up: both users are this scenario's own throwaway accounts and their
      // messages are private to them. The live stream it opened is closed by the runner, which now does
      // that for every scenario (see run.mjs for what that is and isn't known to fix).
    },
  },

  // The mirror image of the scenario above: an ARRIVING message must leave a scrolled-up reader alone, but a
  // message THEY sent must always bring them to it. Both used to run through one "only re-anchor if already
  // at the bottom" rule, so sending from anywhere else left the new bubble off screen — measured on the
  // running app with a real mouse press on Send: 728px below the fold, and it stayed there.
  //
  // The precondition assertion is what stops this passing vacuously: if the seeded thread doesn't actually
  // overflow the pane there is no "scrolled up" state to test, and the scenario says so instead of passing.
  {
    name: "messages: sending lands you on your own message even if you had scrolled up",
    tags: ["messages"],
    async fn(b) {
      const me = await registerAndLogin(b);
      const peer = await apiUser(b.base);
      const filler = "seeded scrollback line, long enough that eight of these overflow the thread pane. ";
      for (let i = 1; i <= 8; i++) {                    // /messages caps one sender at 20 a minute
        const r = await peer.call("/messages", { method: "POST", body: JSON.stringify({ to: me, body: `[${i}] ${filler.repeat(2)}` }) });
        assert(r.status === 201, `seeding message ${i} failed: ${r.status}`);
      }
      await gotoScreen(b, "messages");
      await b.waitFor("#dm-conversations");
      const opened = await b.pageExec(`(() => { const r = [...document.querySelectorAll("#dm-conversations [data-peer]")]
        .find((x) => x.dataset.peer === ${JSON.stringify(peer.username)}); if (r) r.click(); return !!r; })()`);
      assert(opened === true, "the seeded conversation never appeared in the inbox");
      for (let waited = 0; waited < 15000; waited += 400) {
        if (await b.evaluate(`() => document.querySelectorAll("#dm-thread .bubble").length >= 8`)) break;
        await b.wait(400);
      }

      // How far the newest bubble sits below the visible bottom of the pane — the thing the reader notices.
      const metrics = `(() => { const x = document.querySelector("#dm-thread"), r = x.getBoundingClientRect();
        const bs = [...x.querySelectorAll(".bubble")], lb = bs.length ? bs[bs.length - 1].getBoundingClientRect() : null;
        return JSON.stringify({ fromBottom: Math.round(x.scrollHeight - x.scrollTop - x.clientHeight),
          lastBelowFold: lb ? Math.round(lb.bottom - r.bottom) : null,
          bubbles: bs.length, lastText: bs.length ? bs[bs.length - 1].textContent : "" }); })()`;

      await b.pageExec(`(() => { document.querySelector("#dm-thread").scrollTop = 0; return true; })()`);
      await b.wait(200);
      const before = JSON.parse(await b.pageExec(metrics));
      assert(before.bubbles >= 8, `expected the seeded thread on screen, saw ${before.bubbles} bubbles`);
      assert(before.fromBottom > 100,
        `the seeded thread does not overflow the pane (${before.fromBottom}px from the bottom), so "scrolled up" cannot be tested`);

      const sent = "my own reply, sent from the top of the thread";
      await b.type("#dm-reply", sent);
      await b.submit("#dm-reply-form", 600);
      for (let waited = 0; waited < 30000; waited += 400) {
        if (await b.pageExec(`document.querySelector("#dm-thread").textContent.includes(${JSON.stringify(sent)})`)) break;
        await b.wait(400);
      }
      await b.wait(400);                                 // let the post-send scroll settle before reading it
      const after = JSON.parse(await b.pageExec(metrics));
      assert(after.lastText.includes(sent),
        `the sent message never reached the thread: last bubble was ${JSON.stringify(after.lastText.slice(0, 60))}`);
      assert(after.fromBottom < 40,
        `sending left the reader ${after.fromBottom}px from the bottom (was ${before.fromBottom}px) — their own message is off screen`);
      assert(after.lastBelowFold <= 4,
        `the message just sent sits ${after.lastBelowFold}px below the fold`);

      // Nothing to clean up: both accounts are this scenario's own throwaways and their messages are
      // private to them, exactly as in the arriving-message scenario above.
    },
  },
];
