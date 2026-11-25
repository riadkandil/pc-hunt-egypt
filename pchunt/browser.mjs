// Headless Edge / Chrome driver for shops that build their pages with JavaScript.
// Opens a page like a normal visitor, optionally scrolls / clicks to load more, and prints every JSON response whose URL
// matches `capture` (one JSON line each: {"url", "body"}), then optionally the final DOM ({"dom": "..."}).
//
//   node browser.mjs '{"url": "...", "capture": "products|search", "scrolls": 30, "waitMs": 2500, "dom": false}'
//
// No dependencies: Node >= 22 (global WebSocket + fetch) and the DevTools protocol of an installed browser.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const cfg = JSON.parse(process.argv[2]);
const BROWSERS = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const exe = cfg.browser || BROWSERS.find(existsSync);
const profile = mkdtempSync(join(tmpdir(), "pchunt-browser-"));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = obj => process.stdout.write(JSON.stringify(obj) + "\n");

const proc = spawn(exe, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-extensions", "--mute-audio", "--window-size=1366,900", `--user-data-dir=${profile}`,
  "--remote-debugging-port=0", "about:blank"], { stdio: "ignore" });

let port = null;
for (let i = 0; i < 100 && !port; i++) {
  await sleep(100);
  try { port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { }
}
if (!port) { console.error("browser did not start"); process.exit(2); }
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find(t => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));

let id = 0;
const pending = new Map();
const handlers = [];
ws.addEventListener("message", ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else if (m.method) for (const h of handlers) h(m);
});
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async expr => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

const capture = cfg.capture ? new RegExp(cfg.capture) : null;
const wanted = new Map();
let captured = 0, lastActivity = Date.now();
handlers.push(async m => {
  if (m.method === "Network.responseReceived" && capture && capture.test(m.params.response.url)
      && /json|javascript|text\/plain/.test(m.params.response.mimeType || "")) {
    wanted.set(m.params.requestId, m.params.response.url);
  }
  if (m.method === "Network.loadingFinished" && wanted.has(m.params.requestId)) {
    const url = wanted.get(m.params.requestId);
    wanted.delete(m.params.requestId);
    const r = await send("Network.getResponseBody", { requestId: m.params.requestId });
    if (r.result) {
      const body = r.result.base64Encoded ? Buffer.from(r.result.body, "base64").toString("utf8") : r.result.body;
      captured++; lastActivity = Date.now();
      out({ url, body });
    }
  }
});
await send("Network.enable", { maxResourceBufferSize: 50e6, maxTotalBufferSize: 200e6 });
await send("Page.enable");
if (cfg.headers) await send("Network.setExtraHTTPHeaders", { headers: cfg.headers });
await send("Page.navigate", { url: cfg.url });
await sleep(cfg.waitMs ?? 4000);

// load more: scroll to the bottom until nothing new arrives, and/or click a "load more" control
const deadline = Date.now() + (cfg.maxMs ?? 120000);
let still = 0;
for (let i = 0; i < (cfg.scrolls ?? 0) && Date.now() < deadline; i++) {
  const before = captured;
  const h = await evaluate(`(async () => { window.scrollTo(0, document.body.scrollHeight);
    ${cfg.click ? `const b = [...document.querySelectorAll(${JSON.stringify(cfg.click)})].find(e => e.offsetParent); if (b) b.click();` : ""}
    return document.body.scrollHeight; })()`);
  await sleep(cfg.stepMs ?? 1500);
  if (captured === before && Date.now() - lastActivity > (cfg.idleMs ?? 4000)) { if (++still >= 3) break; } else still = 0;
}
if (cfg.dom) out({ dom: await evaluate("document.documentElement.outerHTML") });
if (cfg.eval) out({ eval: await evaluate(cfg.eval) });
ws.close();
proc.kill();
await sleep(300);
try { rmSync(profile, { recursive: true, force: true }); } catch { }
process.exit(0);
