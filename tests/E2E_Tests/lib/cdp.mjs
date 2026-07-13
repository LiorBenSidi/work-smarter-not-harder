// Dependency-free browser-automation driver over the Chrome DevTools Protocol.
//
// Why not Playwright/Puppeteer: those are extra dependencies (a browser download + a package). This uses
// ONLY Node's built-ins (global fetch + WebSocket, available since Node 21) to drive a system-installed
// Chrome over CDP. GitHub's ubuntu runners ship google-chrome; locally we use the macOS app. Same code.
//
// It exposes a small, honest surface for E2E interaction tests: navigate, evaluate JS in the page, click
// real elements, type into inputs, submit forms, screenshot, and read computed layout — plus it collects
// every uncaught page exception so a scenario can assert "zero console errors".

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname } from "node:path";

// Resolve a Chrome/Chromium binary: explicit override, then the usual macOS + Linux locations.
function chromeBinary() {
  const candidates = [
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
  ].filter(Boolean);
  return candidates.find((p) => existsSync(p)) || candidates[0];
}

export class Browser {
  constructor({ port = 9500, userDir = "/tmp/e2e-chrome", viewport = { width: 1280, height: 900, mobile: false } } = {}) {
    this.port = port; this.userDir = userDir; this.viewport = viewport;
    this._id = 0; this._pending = new Map(); this.exceptions = [];
  }

  async launch() {
    const bin = chromeBinary();
    this._proc = spawn(bin, [
      "--headless=new", `--remote-debugging-port=${this.port}`, `--user-data-dir=${this.userDir}`,
      "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
      "--no-sandbox", "--disable-dev-shm-usage",   // required on CI runners; harmless locally
    ], { stdio: "ignore" });

    let target;
    for (let i = 0; i < 80; i++) {
      try {
        const list = await (await fetch(`http://127.0.0.1:${this.port}/json`)).json();
        target = list.find((t) => t.type === "page");
        if (target) break;
      } catch { /* chrome not up yet */ }
      await sleep(250);
    }
    if (!target) throw new Error("Chrome DevTools target never appeared");

    this._ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((res, rej) => { this._ws.onopen = res; this._ws.onerror = rej; });
    this._ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this._pending.has(m.id)) { this._pending.get(m.id)(m); this._pending.delete(m.id); }
      if (m.method === "Runtime.exceptionThrown") {
        const d = m.params.exceptionDetails;
        this.exceptions.push(d?.exception?.description || d?.text || JSON.stringify(d));
      }
    };
    await this.send("Runtime.enable");
    await this.send("Page.enable");
    await this.send("Network.enable");
    await this.send("Network.setCacheDisabled", { cacheDisabled: true });   // never a stale SW/HTTP shell
    await this.setViewport(this.viewport);
    return this;
  }

  send(method, params = {}) {
    return new Promise((res) => { const id = ++this._id; this._pending.set(id, res); this._ws.send(JSON.stringify({ id, method, params })); });
  }

  async setViewport({ width, height, mobile }) {
    this.viewport = { width, height, mobile };
    await this.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 2, mobile: !!mobile });
  }

  // Run an expression IN THE PAGE via the CDP `Runtime.evaluate` protocol method (NOT JavaScript's eval()):
  // the string is sent over the DevTools socket to Chrome and evaluated in the page context, exactly as
  // typing it in the DevTools console would. It only ever carries our own test expressions against our own
  // app — no untrusted input. `evaluate` takes an arrow FUNCTION string and INVOKES it, returning its value
  // (async arrows are awaited); `pageExec` runs a raw already-invoked expression/IIFE.
  async evaluate(expr, awaitPromise = true) {
    const r = await this.send("Runtime.evaluate", { expression: `(${expr})()`, awaitPromise, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error("evaluate threw: " + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
    return r.result?.result?.value;
  }
  async pageExec(expr, awaitPromise = true) {
    const r = await this.send("Runtime.evaluate", { expression: expr, awaitPromise, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error("pageExec threw: " + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
    return r.result?.result?.value;
  }

  async goto(url, settleMs = 1400) { await this.send("Page.navigate", { url }); await sleep(settleMs); }
  wait(ms) { return sleep(ms); }

  // Clear any registered service worker + caches so we always render the fresh shell (SW updates lazily).
  async clearServiceWorkers() {
    await this.pageExec(`(async()=>{if(navigator.serviceWorker){const rs=await navigator.serviceWorker.getRegistrations();await Promise.all(rs.map(r=>r.unregister()));}if(window.caches){const ks=await caches.keys();await Promise.all(ks.map(k=>caches.delete(k)));}return true;})()`);
  }

  // Poll until the selector exists (and is visible unless {visible:false}); throws on timeout.
  async waitFor(selector, { timeout = 5000, visible = true } = {}) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const ok = await this.evaluate(`() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; if (${!visible}) return true; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; }`);
      if (ok) return true;
      await sleep(80);
    }
    throw new Error(`waitFor timeout: ${selector}`);
  }

  async click(selector, settleMs = 400) {
    const found = await this.evaluate(`() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true; }`);
    if (!found) throw new Error(`click: selector not found: ${selector}`);
    await sleep(settleMs);
  }

  // Set an input's value the way a user would (fires input+change) then optionally submit its form.
  async type(selector, value) {
    const ok = await this.pageExec(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event("input",{bubbles:true})); el.dispatchEvent(new Event("change",{bubbles:true})); return true; })()`);
    if (!ok) throw new Error(`type: selector not found: ${selector}`);
  }

  async submit(formSelector, settleMs = 900) {
    const ok = await this.pageExec(`(() => { const f = document.querySelector(${JSON.stringify(formSelector)}); if (!f) return false; f.requestSubmit ? f.requestSubmit() : f.dispatchEvent(new Event("submit",{cancelable:true,bubbles:true})); return true; })()`);
    if (!ok) throw new Error(`submit: form not found: ${formSelector}`);
    await sleep(settleMs);
  }

  // Set a real file on a <input type=file>. Browsers block setting input.files from page JS, so we resolve
  // the element to a CDP RemoteObject and hand DevTools the absolute path directly (the genuine upload path).
  async setFileInput(selector, filePath) {
    const r = await this.send("Runtime.evaluate", { expression: `document.querySelector(${JSON.stringify(selector)})`, returnByValue: false });
    const objectId = r.result?.result?.objectId;
    if (!objectId) throw new Error("file input not found: " + selector);
    await this.send("DOM.enable");
    await this.send("DOM.setFileInputFiles", { files: [filePath], objectId });
    await this.pageExec(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (el) el.dispatchEvent(new Event("change",{bubbles:true})); return true; })()`);
    return true;
  }
  async text(selector) { return this.evaluate(`() => { const el = document.querySelector(${JSON.stringify(selector)}); return el ? el.textContent.trim() : null; }`); }
  async visible(selector) { return this.evaluate(`() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.hidden && getComputedStyle(el).visibility !== "hidden" && getComputedStyle(el).display !== "none"; }`); }
  async exists(selector) { return this.evaluate(`() => !!document.querySelector(${JSON.stringify(selector)})`); }
  async rect(selector) { return this.evaluate(`() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null; const r = el.getBoundingClientRect(); return {top:Math.round(r.top),bottom:Math.round(r.bottom),left:Math.round(r.left),width:Math.round(r.width),height:Math.round(r.height)}; }`); }

  async screenshot(path) {
    const r = await this.send("Page.captureScreenshot", { format: "png" });
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, Buffer.from(r.result.data, "base64"));
  }

  async close() { try { this._ws && this._ws.close(); } catch { /* ignore */ } if (this._proc) this._proc.kill("SIGKILL"); }
}

// Viewport presets used across the suite.
export const VIEWPORTS = {
  desktop: { width: 1280, height: 900, mobile: false },
  mobile: { width: 390, height: 844, mobile: true },
};
