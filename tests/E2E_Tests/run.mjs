// E2E browser-interaction runner. Boots a system Chrome via CDP (lib/cdp.mjs) against a running stack and
// runs the scenarios (scenarios.mjs) at one or more viewports. Exit code is non-zero if ANY scenario fails
// or ANY scenario triggers an uncaught page exception ("zero console errors" is part of the contract).
//
// Usage:  node tests/E2E_Tests/run.mjs [desktop|mobile|both]   (default: both)
//   env:  E2E_BASE_URL   (default http://localhost:8000)
//         E2E_TAGS       comma-separated tag filter (e.g. "forum,auth"); empty = all
//         E2E_SKIP_TAGS  comma-separated tags to skip (e.g. "anim" on a slow CI box)
//
// The two runs ("desktop" and "mobile") give per-viewport coverage; "both" runs them back-to-back in one
// invocation so a single CI step reports full coverage.

import { Browser, VIEWPORTS } from "./lib/cdp.mjs";
import { SCENARIOS } from "./scenarios.mjs";

const arg = (process.argv[2] || "both").toLowerCase();
const BASE = process.env.E2E_BASE_URL || "http://localhost:8000";
const only = (process.env.E2E_TAGS || "").split(",").map((s) => s.trim()).filter(Boolean);
const skip = (process.env.E2E_SKIP_TAGS || "").split(",").map((s) => s.trim()).filter(Boolean);

const viewportNames = arg === "both" ? ["desktop", "mobile"] : [arg];
for (const v of viewportNames) {
  if (!VIEWPORTS[v]) { console.error(`unknown viewport "${v}" (want desktop|mobile|both)`); process.exit(2); }
}

const pick = SCENARIOS.filter((s) =>
  (only.length === 0 || s.tags.some((t) => only.includes(t))) &&
  !s.tags.some((t) => skip.includes(t)));

async function waitForStack() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(BASE + "/health")).ok) return true; } catch { /* not up */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`stack never became healthy at ${BASE}/health`);
}

let totalFail = 0, totalRun = 0;
await waitForStack();

for (let vi = 0; vi < viewportNames.length; vi++) {
  const vname = viewportNames[vi];
  const b = new Browser({ port: 9500 + vi, userDir: `/tmp/e2e-chrome-${vname}`, viewport: VIEWPORTS[vname] });
  b.base = BASE;
  await b.launch();
  console.log(`\n=== viewport: ${vname} (${VIEWPORTS[vname].width}x${VIEWPORTS[vname].height}) — ${pick.length} scenarios ===`);

  for (const s of pick) {
    totalRun++;
    const before = b.exceptions.length;
    let ok = true, detail = "";
    try {
      await b.send("Network.clearBrowserCookies");        // fresh session per scenario
      await s.fn(b, { base: BASE, viewport: vname });
      const newExc = b.exceptions.slice(before);
      if (newExc.length) { ok = false; detail = "uncaught page exception: " + newExc.join(" | "); }
    } catch (e) {
      ok = false; detail = e && e.message ? e.message : String(e);
    }
    if (!ok) totalFail++;
    console.log(`  ${ok ? "PASS" : "FAIL"}  [${vname}] ${s.name}${ok ? "" : "\n        -> " + detail}`);
  }
  await b.close();
}

console.log(`\n=== E2E summary: ${totalRun - totalFail}/${totalRun} passed across ${viewportNames.join("+")} ===`);
process.exit(totalFail ? 1 : 0);
