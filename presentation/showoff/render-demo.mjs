// Render demo.html's slides to 1920x1080 PNGs — the frames build-demo.sh stitches into demo.mp4.
//
//   node presentation/showoff/render-demo.mjs [outDir]        (default: /tmp/wsnh-demo-frames)
//
// Prints a manifest line per slide — "<file>\t<seconds>" — which build-demo.sh reads to decide how
// long each one is held. Keeping the durations in demo.html (as `data-secs`) rather than in the
// shell script means the clip's pacing lives beside its content, so editing a slide and editing its
// screen time are the same file.
//
// Why not `b.setViewport`: it hardcodes deviceScaleFactor 2 (right for the phone mockups, which want
// retina detail), so a 1920x1080 slide would come out 3840x2160. The gallery rules ask for 1920x1080
// exactly, so the metrics override is sent here directly at scale 1.

import { Browser } from "../../tests/E2E_Tests/lib/cdp.mjs";
import { mkdirSync, rmSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "demo.html");
const OUT = process.argv[2] || "/tmp/wsnh-demo-frames";

const W = 1920, H = 1080;

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const b = new Browser({ port: 9700, userDir: "/tmp/demo-render-chrome",
                        viewport: { width: W, height: H, mobile: false } });
await b.launch();
await b.send("Emulation.setDeviceMetricsOverride",
             { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await b.goto("file://" + SRC, 2500);        // the wait lets the webfont land before the first shot

const slides = await b.evaluate(`() => Array.from(document.querySelectorAll(".slide")).map(
  (s, i) => ({ i, name: s.dataset.name || String(i), secs: Number(s.dataset.secs || 5),
               top: s.offsetTop, h: s.getBoundingClientRect().height }))`);

if (!slides.length) { console.error("no .slide elements found in demo.html"); process.exit(1); }

const bad = slides.filter(s => Math.round(s.h) !== H);
if (bad.length) {
  console.error(`WARNING: ${bad.length} slide(s) are not ${H}px tall — the video will jump:`);
  for (const s of bad) console.error(`   ${s.name}: ${Math.round(s.h)}px`);
}

for (const s of slides) {
  // Position by scrolling rather than hiding siblings: the slides are exactly viewport-sized, so a
  // scroll to offsetTop frames one perfectly and leaves every layout untouched.
  await b.pageExec(`(() => { window.scrollTo({ top: ${s.top}, behavior: "instant" }); return true; })()`);
  await b.wait(160);
  const file = `${OUT}/${s.name}.png`;      // data-name already carries its own ordering prefix
  await b.screenshot(file);
  console.log(`${file}\t${s.secs}`);
}

console.error(`rendered ${slides.length} slides -> ${OUT} ` +
              `(${slides.reduce((a, s) => a + s.secs, 0)}s total)`);
await b.close();
