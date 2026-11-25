// PC Hunt front end: state lives in the URL hash (#/?q=...&cat=gpu&f_chip=RTX 5070), so every view is shareable.
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const egp = n => n == null ? "-" : Math.round(n).toLocaleString("en-US") + " EGP";
let META = null;
let LAST = null;
let SEQ = 0;            // only the newest search may render (hash changes can overlap)

const SPEC_UNITS = { vram: " GB", capacity: " GB", speed: " MHz", watt: " W", radiator: " mm", size: "", hz: " Hz", rpm: " rpm",
  ram: " GB RAM", storage: " GB", va: " VA", cl: "", pack: "" };
function fmtSpec(k, v) {
  if (v == null || v === "") return "";
  if ((k === "capacity" || k === "storage") && Number(v) >= 1024 && Number(v) % 1024 === 0) return (Number(v) / 1024) + " TB";
  if (k === "size") return v + '"';
  if (k === "cl") return "CL" + v;
  if (k === "pack" && typeof v === "number") return v > 1 ? v + "-pack" : "single";
  return v + (SPEC_UNITS[k] || "");
}

function readState() {
  const h = location.hash.replace(/^#\/?/, "");
  const [route, query = ""] = h.includes("?") ? h.split("?") : [h, ""];
  return { route: route || "", p: new URLSearchParams(query) };
}
function writeState(p, replace = false) {
  for (const [k, v] of [...p.entries()]) if (v === "") p.delete(k);
  const url = "#/?" + p.toString();
  if (replace) history.replaceState(null, "", url); else location.hash = url;
  if (replace) render();
}
function setParam(k, v, { keepPage = false } = {}) {
  const { p } = readState();
  if (v == null || v === "") p.delete(k); else p.set(k, v);
  if (!keepPage) p.delete("page");
  writeState(p);
}
function toggleMulti(k, v, sep) {
  const { p } = readState();
  const cur = (p.get(k) || "").split(sep).filter(Boolean);
  const i = cur.indexOf(v);
  if (i >= 0) cur.splice(i, 1); else cur.push(v);
  if (cur.length) p.set(k, cur.join(sep)); else p.delete(k);
  p.delete("page");
  writeState(p);
}

let LOCAL = null;      // GitHub Pages build: the API runs in the browser (local.js)
async function api(path) {
  if (window.PCHUNT_STATIC) {
    LOCAL ??= await import("./local.js");
    return LOCAL.api(path);
  }
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

// ------------------------------------------------------------------ search view
async function renderSearch(p) {
  $("#q").value = p.get("q") || "";
  $("#pmin").value = p.get("min") || "";
  $("#pmax").value = p.get("max") || "";
  $("#stock").checked = (p.get("stock") ?? "1") === "1";
  $("#deal").checked = p.get("deal") === "1";
  $("#hideSuspect").checked = p.get("suspect") !== "1";
  $("#sort").value = p.get("sort") || (p.get("q") ? "relevance" : "price");
  const view = p.get("view") || "offers";
  for (const b of document.querySelectorAll("#viewSeg button")) b.classList.toggle("on", b.dataset.view === view);
  const qs = new URLSearchParams(p);
  if (!qs.has("stock")) qs.set("stock", "1");
  // home page (no search, no category): lowest prices would be 20 EGP cables, so show the best deals instead
  if (!p.get("sort") && !p.get("q") && !p.get("cat")) { qs.set("sort", "discount"); $("#sort").value = "discount"; }
  $("#grid").innerHTML = `<div class="empty">Loading...</div>`;
  const seq = ++SEQ;
  let d;
  try { d = await api("/api/search?" + qs.toString()); }
  catch (e) { if (seq === SEQ) $("#grid").innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`; return; }
  if (seq !== SEQ) return;
  LAST = d;
  if (d.sort) $("#sort").value = d.sort;
  const cat = p.get("cat") || (d.intent && d.intent.cat) || null;
  renderCats(cat, d.categories);
  renderFacets(p, d, cat);
  renderOpts("#brands", d.brands.map(b => ({ v: b.v, label: b.v, n: b.n })), (p.get("brand") || "").split("|"), v => toggleMulti("brand", v, "|"));
  renderOpts("#storesF", d.stores.map(s => ({ v: s.id, label: s.name, n: s.n })), (p.get("store") || "").split(","), v => toggleMulti("store", v, ","));
  renderOpts("#groups", Object.entries(META.groups).map(([k, label]) => ({ v: k, label })), (p.get("group") || "").split(","), v => toggleMulti("group", v, ","));
  renderChips(p, d);
  const label = cat ? META.labels[cat] : "all categories";
  const pr = d.price.min != null ? ` - ${egp(d.price.min)} to ${egp(d.price.max)}` : "";
  $("#summary").innerHTML = `<b>${d.total.toLocaleString()}</b> ${view === "models" ? "models" : "offers"} in ${esc(label)}${pr}` +
    (d.corrected ? ` <span class="note">Showing results for <b>${esc(d.corrected)}</b></span>` : "") +
    (d.partial ? ` <span class="note">No listing has every word - showing the closest matches.</span>` : "");
  $("#grid").innerHTML = d.items.length ? d.items.map(i => card(i, view)).join("") :
    `<div class="empty">Nothing matches. Remove a filter or change the search.</div>`;
  for (const el of document.querySelectorAll(".card")) el.onclick = () => openOffer(el.dataset.id);
  renderPager(d);
}

function renderCats(active, cats) {
  const list = cats && cats.length ? cats : META.categories;
  const total = list.reduce((a, c) => a + c.n, 0);
  let html = `<button class="${active ? "" : "on"}" data-cat=""><span>All</span><span class="n">${total.toLocaleString()}</span></button>`;
  if (active && !list.find(c => c.id === active)) html += `<button class="on" data-cat="${esc(active)}"><span>${esc(META.labels[active] || active)}</span></button>`;
  const NONPC = ["phone", "tablet", "tv", "wearable", "camera", "appliance", "other"];
  const row = c => `<button class="${c.id === active ? "on" : ""}" data-cat="${esc(c.id)}"><span>${esc(c.label)}</span><span class="n">${c.n.toLocaleString()}</span></button>`;
  html += list.filter(c => !NONPC.includes(c.id)).map(row).join("");
  const rest = list.filter(c => NONPC.includes(c.id));
  if (rest.length) html += `<div class="catsep">Other products</div>` + rest.map(row).join("");
  $("#cats").innerHTML = html;
  for (const b of $("#cats").querySelectorAll("button")) b.onclick = () => {
    const { p } = readState();
    for (const k of [...p.keys()]) if (k.startsWith("f_")) p.delete(k);
    if (b.dataset.cat) p.set("cat", b.dataset.cat); else p.delete("cat");
    p.delete("page");
    writeState(p);
  };
}

function renderFacets(p, d, cat) {
  const box = $("#facets");
  if (!d.facets) { box.innerHTML = ""; return; }
  box.innerHTML = Object.entries(d.facets).filter(([, f]) => f.values.length).map(([k, f]) =>
    `<section class="box"><h3>${esc(f.label)}</h3><div class="opts ${f.values.length > 10 ? "scroll" : ""}" data-facet="${esc(k)}"></div></section>`).join("");
  for (const [k, f] of Object.entries(d.facets)) {
    const el = box.querySelector(`[data-facet="${k}"]`);
    if (!el) continue;
    const sel = (p.get("f_" + k) || "").split("|");
    renderOpts(el, f.values.map(v => ({ v: v.v, label: fmtSpec(k, isNaN(v.v) ? v.v : Number(v.v)), n: v.n })), sel, v => toggleMulti("f_" + k, v, "|"));
  }
}

function renderOpts(target, opts, selected, onToggle) {
  const el = typeof target === "string" ? $(target) : target;
  el.innerHTML = opts.map((o, i) => `<label><input type="checkbox" data-i="${i}" ${selected.includes(String(o.v)) ? "checked" : ""}>` +
    `<span title="${esc(o.label)}">${esc(o.label)}</span>${o.n != null ? `<span class="n">${o.n.toLocaleString()}</span>` : ""}</label>`).join("");
  for (const c of el.querySelectorAll("input")) c.onchange = () => onToggle(String(opts[c.dataset.i].v));
}

function renderChips(p, d) {
  const chips = [];
  const add = (label, fn) => chips.push({ label, fn });
  if (d && d.intent) add(`Searching ${d.intent.label} - search all categories instead`, () => setParam("allcat", "1"));
  if (p.get("q")) add(`"${p.get("q")}"`, () => setParam("q", ""));
  if (p.get("cat")) add(META.labels[p.get("cat")], () => setParam("cat", ""));
  for (const [k, v] of p.entries()) if (k.startsWith("f_")) for (const x of v.split("|")) add(fmtSpec(k.slice(2), isNaN(x) ? x : Number(x)), () => toggleMulti(k, x, "|"));
  for (const b of (p.get("brand") || "").split("|").filter(Boolean)) add(b, () => toggleMulti("brand", b, "|"));
  for (const s of (p.get("store") || "").split(",").filter(Boolean)) add((LAST?.stores.find(x => x.id === s) || { name: s }).name, () => toggleMulti("store", s, ","));
  for (const g of (p.get("group") || "").split(",").filter(Boolean)) add(META.groups[g], () => toggleMulti("group", g, ","));
  if (p.get("min") || p.get("max")) add(`${p.get("min") || 0} - ${p.get("max") || "any"} EGP`, () => { const { p } = readState(); p.delete("min"); p.delete("max"); writeState(p); });
  if (p.get("deal") === "1") add("Discounted", () => setParam("deal", ""));
  const el = $("#chips");
  el.innerHTML = chips.map((c, i) => `<button class="chip" data-i="${i}">${esc(c.label)} &times;</button>`).join("") +
    (chips.length > 1 ? `<button class="chip clear" id="clearAll">Clear all</button>` : "");
  for (const b of el.querySelectorAll(".chip[data-i]")) b.onclick = () => chips[b.dataset.i].fn();
  if ($("#clearAll")) $("#clearAll").onclick = () => { location.hash = "#/"; };
}

function specChips(i) {
  const keys = (META.facets[i.category] || []);
  const order = { gpu: ["chip", "vram", "series"], cpu: ["model", "socket", "pack"], motherboard: ["chipset", "form", "ddr", "wifi"],
    ram: ["ddr", "kit", "speed", "cl"], ssd: ["capacity", "interface", "pcie"], psu: ["watt", "rating", "modular"],
    monitor: ["size", "resolution", "hz", "panel"], laptop: ["cpu", "gpu", "ram", "storage"], desktop: ["cpu", "gpu", "ram", "storage"] }[i.category] || Object.keys(i.specs);
  return order.filter(k => k !== "condition" && i.specs[k] != null && !(k === "wifi" && i.specs[k] === "No")).slice(0, 5)
    .map(k => `<span class="spec">${esc(k === "wifi" ? "Wi-Fi" : fmtSpec(k, i.specs[k]))}</span>`).join("");
}

function card(i, view) {
  const price = view === "models" ? i.best : i.price;
  const disc = i.old_price > i.price ? Math.round((1 - i.price / i.old_price) * 100) : 0;
  const drop = i.prev_price > i.price ? Math.round((1 - i.price / i.prev_price) * 100) : 0;
  let cmp = "";
  if (view === "models") {
    cmp = i.nstores > 1 ? `<div class="cmp">${i.nstores} stores, up to ${egp(i.worst)}</div>` : "";
  } else if (i.model_stores > 1) {
    cmp = i.model_best < i.price - 0.5 ? `<div class="cmp worse">${i.model_stores} stores - cheapest ${egp(i.model_best)}</div>`
      : `<div class="cmp">Cheapest of ${i.model_stores} stores</div>`;
  }
  return `<div class="card" data-id="${i.id}">
    <div class="thumb">${i.image ? `<img loading="lazy" src="${esc(i.image)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'noimg',textContent:'no image'}))">` : `<span class="noimg">no image</span>`}
      ${disc >= 3 ? `<span class="badge">-${disc}%</span>` : ""}${drop >= 2 ? `<span class="badge drop">price down ${drop}%</span>` : ""}${i.specs.condition && i.specs.condition !== "New" ? `<span class="badge cond">${esc(i.specs.condition)}</span>` : ""}${i.suspect ? `<span class="badge warn" title="Far below the usual price for this part - check the listing">check price</span>` : ""}</div>
    <div class="body">
      <div class="title" title="${esc(i.title)}">${esc(i.title)}</div>
      <div class="specs">${specChips(i)}</div>
      <div class="price"><b>${egp(price)}</b>${view !== "models" && i.old_price > i.price ? `<s>${egp(i.old_price)}</s>` : ""}</div>
      ${cmp}
      <div class="meta"><span class="store">${view === "models" ? "best at " : ""}${esc(i.store)}${i.seller && i.seller !== i.store ? ` (${esc(i.seller)})` : ""}</span>${i.in_stock ? "" : `<span class="out">out of stock</span>`}</div>
    </div></div>`;
}

function renderPager(d) {
  const pages = Math.ceil(d.total / d.size);
  const el = $("#pager");
  if (pages <= 1) { el.innerHTML = ""; return; }
  const cur = d.page;
  const nums = new Set([1, pages, cur - 2, cur - 1, cur, cur + 1, cur + 2].filter(n => n >= 1 && n <= pages));
  let html = `<button ${cur === 1 ? "disabled" : ""} data-p="${cur - 1}">&lsaquo;</button>`, prev = 0;
  for (const n of [...nums].sort((a, b) => a - b)) {
    if (n - prev > 1) html += `<span class="muted">...</span>`;
    html += `<button class="${n === cur ? "on" : ""}" data-p="${n}">${n}</button>`;
    prev = n;
  }
  html += `<button ${cur === pages ? "disabled" : ""} data-p="${cur + 1}">&rsaquo;</button>`;
  el.innerHTML = html;
  for (const b of el.querySelectorAll("button[data-p]")) b.onclick = () => { setParam("page", b.dataset.p, { keepPage: true }); scrollTo(0, 0); };
}

// ------------------------------------------------------------------ offer drawer
function chart(points, label) {
  if (!points || points.length < 2) return `<p class="muted">${label}: only ${points?.length || 0} day recorded so far - history builds up with every daily run.</p>`;
  const W = 700, H = 150, P = 34;
  const xs = points.map(p => new Date(p.day).getTime()), ys = points.map(p => p.price);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys) * 0.98, y1 = Math.max(...ys) * 1.02;
  const X = x => P + (x - x0) / (x1 - x0 || 1) * (W - P - 10), Y = y => H - 20 - (y - y0) / (y1 - y0 || 1) * (H - 34);
  const path = points.map((p, i) => `${i ? "L" : "M"}${X(xs[i]).toFixed(1)},${Y(p.price).toFixed(1)}`).join(" ");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>
    ${points.map((p, i) => `<circle cx="${X(xs[i])}" cy="${Y(p.price)}" r="2.5" fill="var(--accent)"><title>${p.day}: ${egp(p.price)}</title></circle>`).join("")}
    <text x="2" y="${Y(Math.max(...ys)) + 4}">${Math.round(Math.max(...ys)).toLocaleString()}</text>
    <text x="2" y="${Y(Math.min(...ys)) + 4}">${Math.round(Math.min(...ys)).toLocaleString()}</text>
    <text x="${P}" y="${H - 4}">${points[0].day}</text><text x="${W - 70}" y="${H - 4}">${points.at(-1).day}</text></svg>`;
}

let SHOW_OUT = false;
async function openOffer(id) {
  CUR_OFFER = id;
  const dr = $("#drawer"), c = $("#drawerCard");
  dr.hidden = false;
  c.innerHTML = `<p class="muted">Loading...</p>`;
  let o;
  try { o = await api("/api/offer?id=" + id + (SHOW_OUT ? "&all=1" : "")); } catch (e) { c.innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const specs = Object.entries(o.specs).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(fmtSpec(k, v))}</dd>`).join("");
  const best = o.same.filter(x => x.in_stock).reduce((a, x) => (a == null || x.price < a ? x.price : a), null);
  const row = x => `<tr class="${x.in_stock && x.price === best && o.same.length > 1 ? "best" : ""}"><td><b>${esc(x.store)}</b>${x.seller && x.seller !== x.store ? `<br><span class="muted">${esc(x.seller)}</span>` : ""}</td>
      <td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a></td>
      <td class="num"><b>${egp(x.price)}</b>${x.old_price > x.price ? `<br><s class="muted">${egp(x.old_price)}</s>` : ""}</td>
      <td>${x.in_stock ? "in stock" : `<span class="out">out</span>`}</td></tr>`;
  c.innerHTML = `<button class="x" data-close>&times;</button>
    <h2>${esc(o.title)}</h2>
    <div class="muted">${esc(META.labels[o.category] || o.category)}${o.brand ? " - " + esc(o.brand) : ""} - seen since ${esc(o.first_seen)}</div>
    <div class="hero"><div class="img">${o.image ? `<img src="${esc(o.image)}" referrerpolicy="no-referrer" alt="">` : `<span class="muted">no image</span>`}</div>
      <div><div class="bigprice">${egp(o.price)}</div>
        ${o.old_price > o.price ? `<div class="muted"><s>${egp(o.old_price)}</s> - ${Math.round((1 - o.price / o.old_price) * 100)}% off</div>` : ""}
        ${o.prev_price ? `<div class="muted">was ${egp(o.prev_price)} before ${esc(o.price_changed)}</div>` : ""}
        <p><b>${esc(o.store)}</b>${o.seller && o.seller !== o.store ? ` - sold by ${esc(o.seller)}` : ""} - ${o.in_stock ? "in stock" : `<span class="out">out of stock</span>`}</p>
        <a class="btn" href="${esc(o.url)}" target="_blank" rel="noopener">Open in store</a>
        <dl class="kv">${specs}</dl></div></div>
    <h4>Same product in ${o.same.length} listing${o.same.length === 1 ? "" : "s"}${o.sold_out_hidden ? ` <button class="linkbtn" id="showOut">+ ${o.sold_out_hidden} sold out</button>` : (SHOW_OUT ? ` <button class="linkbtn" id="hideOut">hide sold out</button>` : "")}</h4>
    <div class="tablewrap"><table><tr><th>Store</th><th>Listing</th><th class="num">Price</th><th>Stock</th></tr>${o.same.map(row).join("")}</table></div>
    <h4>Price history (this listing)</h4>${chart(o.history, "This listing")}
    <h4>Cheapest in-stock price for this model, all stores</h4>${chart(o.model_history, "This model")}
    ${o.similar.length ? `<h4>Similar (${esc(o.family.split(":")[1])}) - cheapest in stock</h4>
      <div class="tablewrap"><table><tr><th>Store</th><th>Listing</th><th class="num">Price</th><th>Stock</th></tr>${o.similar.map(row).join("")}</table></div>` : ""}`;
}
document.addEventListener("click", e => {
  if (e.target.closest("[data-close]")) $("#drawer").hidden = true;
  if (e.target.id === "showOut" || e.target.id === "hideOut") { SHOW_OUT = e.target.id === "showOut"; openOffer(CUR_OFFER); }
});
let CUR_OFFER = null;
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#drawer").hidden = true; });

// ------------------------------------------------------------------ stores view
async function renderStores() {
  const rows = await api("/api/stores");
  const on = rows.filter(r => r.enabled);
  $("#storesSummary").textContent = `${on.length} stores scraped, ${rows.length - on.length} skipped. ` +
    `${rows.reduce((a, r) => a + (r.active || 0), 0).toLocaleString()} PC offers from the latest successful runs.`;
  const t = s => s ? s.replace("T", " ").slice(0, 16) : "-";
  $("#storesTable").innerHTML = `<tr><th>Store</th><th>Type</th><th>Scraper</th><th class="num">Offers</th><th class="num">In stock</th>
    <th>Last good run</th><th>Status</th><th class="num">Time</th><th>Notes</th></tr>` + rows.map(r => `<tr>
    <td><a href="${esc(r.url)}" target="_blank" rel="noopener"><b>${esc(r.name)}</b></a><br><span class="muted">${esc(r.url.replace(/^https?:\/\//, ""))}</span></td>
    <td>${esc(META.groups[r.grp] || r.grp || "")}</td><td>${esc(r.adapter || r.platform)}</td>
    <td class="num"><a href="#/?store=${esc(r.id)}&stock=0">${(r.active || 0).toLocaleString()}</a></td><td class="num">${(r.in_stock || 0).toLocaleString()}</td>
    <td>${t(r.last_ok)}</td>
    <td>${r.enabled ? `<span class="st-${esc(r.status || "")}">${esc(r.status || "not run")}</span>` : `<span class="muted">skipped</span>`}</td>
    <td class="num">${r.duration ? Math.round(r.duration) + " s" : ""}</td>
    <td class="muted">${esc(r.enabled ? (r.error || r.note || "") : r.reason || "")}</td></tr>`).join("");
}

// ------------------------------------------------------------------ wiring
async function render() {
  const { route, p } = readState();
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("on", a.dataset.nav === (route === "stores" ? "stores" : "search"));
  $("#searchView").hidden = route === "stores";
  $("#storesView").hidden = route !== "stores";
  $("#side").classList.remove("open");
  if (route === "stores") return renderStores();
  return renderSearch(p);
}

// a new search starts fresh (category, spec filters, page), keeping only the view toggles
$("#searchForm").onsubmit = e => {
  e.preventDefault();
  const { p } = readState();
  const n = new URLSearchParams();
  for (const k of ["stock", "suspect", "view", "deal"]) if (p.get(k)) n.set(k, p.get(k));
  n.set("q", $("#q").value.trim());
  writeState(n);
};
$("#helpBtn").onclick = () => { $("#help").hidden = !$("#help").hidden; };
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#help").hidden = true; });
$("#sort").onchange = e => setParam("sort", e.target.value);
for (const b of document.querySelectorAll("#viewSeg button")) b.onclick = () => setParam("view", b.dataset.view === "offers" ? "" : b.dataset.view);
$("#stock").onchange = e => setParam("stock", e.target.checked ? "" : "0");
$("#deal").onchange = e => setParam("deal", e.target.checked ? "1" : "");
$("#hideSuspect").onchange = e => setParam("suspect", e.target.checked ? "" : "1");
for (const id of ["pmin", "pmax"]) $("#" + id).onchange = e => setParam(id === "pmin" ? "min" : "max", e.target.value);
$("#filtersBtn").onclick = () => $("#side").classList.toggle("open");
for (const f of document.querySelectorAll(".filter")) f.oninput = () => {
  const term = f.value.toLowerCase();
  for (const l of document.getElementById(f.dataset.for).querySelectorAll("label")) l.hidden = !l.textContent.toLowerCase().includes(term);
};
window.addEventListener("hashchange", render);

META = await api("/api/meta");
const upd = (META.built || META.last_run?.finished || META.last_run?.started || "").slice(0, 10);
$("#foot").innerHTML = `${META.offers.toLocaleString()} listings from ${META.stores} Egyptian stores${upd ? `, updated ${esc(upd)}` : ""}. ` +
  `Prices and stock come from the stores' own sites once a day and may have changed: check the store before buying. ` +
  `Not affiliated with any store. <a href="https://github.com/riadkandil/pc-hunt-egypt" target="_blank" rel="noopener">Source</a>`;
render();
