// Render poster.html -> poster.pdf at true A3.
//
//   node presentation/showoff/render-poster.mjs
//
// Why not `chrome --headless --print-to-pdf`: that path lays the page out at Chrome's DEFAULT PAPER
// WIDTH (Letter, 215.9mm) and then emits it onto whatever `@page { size }` asks for. The result is an
// A3-sized sheet carrying a Letter-width layout — 216/297 = 73% of the width used, with a 69mm dead
// column down the right and 44mm dead at the foot. It looks like a CSS bug and is not one: the same
// HTML screenshots correctly at 1123x1588.
//
// `Page.printToPDF` over CDP takes the paper size as an explicit parameter, so the layout viewport and
// the sheet agree. A3 = 297 x 420 mm = 11.69 x 16.54 in.

import { Browser } from "../../tests/E2E_Tests/lib/cdp.mjs";
import { writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "poster.html");
const OUT = process.argv[2] || resolve(HERE, "poster.pdf");

const A3_WIDTH_IN = 297 / 25.4;
const A3_HEIGHT_IN = 420 / 25.4;

const b = new Browser({
  port: 9950,
  userDir: "/tmp/poster-render-chrome",
  viewport: { width: 1123, height: 1588, mobile: false },   // A3 at 96dpi, so layout matches the sheet
});
await b.launch();
await b.goto("file://" + SRC, 2500);

// `send` resolves the whole CDP envelope, so the payload is under `.result` (see how `evaluate`
// reaches through to `r.result.result.value` in lib/cdp.mjs).
const res = await b.send("Page.printToPDF", {
  paperWidth: A3_WIDTH_IN,
  paperHeight: A3_HEIGHT_IN,
  marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0,
  printBackground: true,          // the dark ground and the ambient glows are backgrounds
  preferCSSPageSize: false,        // honour @page; the explicit size above is the fallback
  scale: 1,
});

const data = res?.result?.data;
if (!data) throw new Error("Page.printToPDF returned no data: " + JSON.stringify(res).slice(0, 300));
writeFileSync(OUT, Buffer.from(data, "base64"));
console.log("wrote " + OUT);
await b.close();
