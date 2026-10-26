// Capture report figures as PNGs for the README (light and dark), with headless Chrome.
//
//   node scripts/figures.mjs [site_url] [out_dir]
//
// Needs Google Chrome and Node 22+ (built-in WebSocket). Serve the site first (`make serve`).
// Each figure is the <figure> that contains the given chart id, captured at 2x.

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SITE = process.argv[2] || "http://localhost:8765/";
const OUT = process.argv[3] || "docs/img";
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;

// [output name, page path, chart id, season toggle to click first (or null)]
const FIGURES = [
  ["loss-rates", "", "ch-rates", null],
  ["silverstone-gap", "reports/british-grand-prix.html", "ch-rival", null],
  ["silverstone-straights", "reports/british-grand-prix.html", "ch-st-1", null],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp() {
  for (let i = 0; i < 50; i++) {
    try {
      const tabs = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = tabs.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* Chrome still starting */ }
    await sleep(200);
  }
  throw new Error("Chrome did not start");
}

function client(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  };
  const ready = new Promise((r) => (ws.onopen = r));
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const i = ++id;
    pending.set(i, { resolve, reject });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  return { ready, send, close: () => ws.close() };
}

const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, "--hide-scrollbars", "--no-first-run",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "figs-"))}`, "about:blank",
], { stdio: "ignore" });

try {
  const c = client(await cdp());
  await c.ready;
  await c.send("Page.enable");
  await c.send("Runtime.enable");
  await c.send("Emulation.setDeviceMetricsOverride", { width: 1200, height: 900, deviceScaleFactor: 2, mobile: false });
  mkdirSync(OUT, { recursive: true });
  for (const scheme of ["light", "dark"]) {
    await c.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
    let loaded = null;
    for (const [name, path, chart, toggle] of FIGURES) {
      if (loaded !== path) {
        await c.send("Page.navigate", { url: new URL(path, SITE).href });
        await sleep(4000); // fonts, Plotly and every chart
        loaded = path;
      }
      if (toggle) await c.send("Runtime.evaluate", { expression: `document.querySelector(${JSON.stringify(toggle)}).click()` });
      // Sticky bars would cover the figure; take them out of the flow for the capture
      const box = (await c.send("Runtime.evaluate", {
        returnByValue: true,
        expression: `(() => {
          document.querySelectorAll('.masthead, .season-bar').forEach(e => e.style.position = 'static');
          const fig = document.getElementById(${JSON.stringify(chart)}).closest('figure');
          fig.scrollIntoView({ block: 'start' });
          const r = fig.getBoundingClientRect();
          return { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height };
        })()`,
      })).result.value;
      await sleep(600);
      const shot = await c.send("Page.captureScreenshot", {
        format: "png", captureBeyondViewport: true,
        clip: { x: box.x - 8, y: box.y - 8, width: box.w + 16, height: box.h + 16, scale: 1 },
      });
      const file = join(OUT, `${name}-${scheme}.png`);
      writeFileSync(file, Buffer.from(shot.data, "base64"));
      console.log("wrote", file);
    }
  }
  c.close();
} finally {
  chrome.kill();
}
