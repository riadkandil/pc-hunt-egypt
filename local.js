// PC Hunt API in the browser, for the static (GitHub Pages) build: answers the same /api/* calls as pchunt/server.py
// from the JSON files written by pchunt/export_site.py. The full-text search mirrors the SQLite FTS5 index:
// same index text (query.index_text), same query language (query.parse), bm25-style ranking.
const DATA = "data/";
let META = null, STORES = null, SIDX = null;
let OFFERS = [];             // offer objects; position = doc number in the text index
const BYID = new Map();
let SOLD = {};               // model_key -> sold-out listings (before the offers-out parts are loaded)
let OUT_LOADED = false, OUT_PROMISE = null, IN_PROMISE = null;
let IDX = null;              // text index, rebuilt when offers are added
const HIST = new Map();      // shard -> {id: [[day, price, stock], ...]}

const json = async url => { const r = await fetch(url); if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); };
const W = "[\\p{L}\\p{N}_]";
const rx = (s, f = "") => new RegExp(s, "u" + f);

// ------------------------------------------------------------------ text (classify.norm, query.fold / index_text)
const AR_FOLD = { "أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": "" };
function norm(s) {
  s = String(s || "").replace(/[™®©]/g, " ").normalize("NFKC").toLowerCase();
  s = s.replace(/′′|″|”|“/g, '"').replace(/[–—]/g, "-").replace(/×/g, "x").replace(/[٠-٩]/g, d => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  return s.replace(/\s+/g, " ").trim();
}
const fold = s => norm(s).replace(/[أإآةىؤئـ]/g, c => AR_FOLD[c]).replace(/\p{M}/gu, "");
const TOKEN = /[a-z0-9؀-ۿ]+(?:\.[0-9]+)?/g;
const parts = tok => tok.match(/[a-z؀-ۿ]+|[0-9]+(?:\.[0-9]+)?/g) || [];
const isDigit = c => c >= "0" && c <= "9";
function indexText(s) {
  const toks = fold(s).match(TOKEN) || [];
  const out = [...toks];
  for (const t of toks) { const ps = parts(t); if (ps.length > 1) out.push(...ps); }
  for (let i = 0; i + 1 < toks.length; i++) {
    const a = toks[i], b = toks[i + 1];
    if (a.length <= 8 && b.length <= 8 && isDigit(a.at(-1)) !== isDigit(b[0])) out.push(a + b);
  }
  return out.join(" ");
}
// FTS5 unicode61 splits the index text on anything that is not a letter or a digit ("m.2" -> m, 2)
const ftsTokens = s => s.split(/[^\p{L}\p{N}]+/u).filter(Boolean);

// ------------------------------------------------------------------ loading
function addRows(data) {
  const C = Object.fromEntries(data.cols.map((c, i) => [c, i]));
  for (const r of data.rows) {
    const st = STORES[r[C.s]];
    const o = {
      id: r[C.id], store_id: st.id, store: st.name, grp: st.grp, title: r[C.title], brand: r[C.brand],
      category: META.cats[r[C.cat]], specs: r[C.specs] || {}, family: r[C.family] || null, model_key: r[C.model_key],
      url: st.up + r[C.url], image: r[C.image] ? st.ip + r[C.image] : "", price: r[C.price], old_price: r[C.old_price] || null,
      in_stock: data.out ? 0 : 1, seller: r[C.seller], first_seen: r[C.first_seen], price_changed: r[C.price_changed] || null,
      prev_price: r[C.prev_price] || null, suspect: r[C.suspect],
    };
    if (BYID.has(o.id)) continue;
    o._d = OFFERS.length;          // doc number in the text index
    BYID.set(o.id, o);
    OFFERS.push(o);
  }
  IDX = null;
}

async function loadIn() {
  META = await json(DATA + "meta.json");
  STORES = await json(DATA + "stores.json");
  SIDX = Object.fromEntries(STORES.map(s => [s.id, s]));
  const parts = await loadParts("in");
  SOLD = parts[0].sold || {};
  parts.forEach(addRows);
  // build the text index while the visitor looks at the first page (about a second)
  setTimeout(() => (window.requestIdleCallback || setTimeout)(() => index(), { timeout: 4000 }), 300);
}
const ready = () => (IN_PROMISE ??= loadIn());
function loadOut() {
  return OUT_PROMISE ??= loadParts("out").then(ps => { ps.forEach(d => { d.out = true; addRows(d); }); OUT_LOADED = true; });
}
// offers-<kind>-<n>.json, fetched in parallel, kept in order (doc numbers stay stable)
const loadParts = kind => Promise.all(Array.from({ length: (META.parts || {})[kind] || 1 },
                                                 (_, n) => json(`${DATA}offers-${kind}-${n}.json`)));

// ------------------------------------------------------------------ text index
function buildIndex() {
  const post = new Map();
  const N = OFFERS.length, len = new Uint16Array(N);
  let total = 0;
  OFFERS.forEach((o, i) => {
    const toks = ftsTokens(indexText(searchText(o)));
    len[i] = Math.min(toks.length, 65535);
    total += toks.length;
    for (const t of new Set(toks)) {
      let a = post.get(t);
      if (!a) post.set(t, a = []);
      a.push(i);
    }
  });
  const vocab = [...post.keys()].sort();
  IDX = { post, vocab, len, avg: total / Math.max(1, N), N };
  return IDX;
}
const index = () => IDX || buildIndex();
function searchText(o) {
  const spec = Object.values(o.specs).join(" ");
  return [o.title, o.brand, META.labels[o.category] || "", spec, o.store, o.seller || ""].join(" ");
}
function lowerBound(arr, x) { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < x) lo = m + 1; else hi = m; } return lo; }
function prefixTerms(p) {
  const v = index().vocab, out = [];
  for (let i = lowerBound(v, p); i < v.length && v[i].startsWith(p); i++) out.push(v[i]);
  return out;
}
const df = t => index().post.get(t)?.length || 0;

// a query term -> doc mask. Leaf = {t: token, pre: prefix?}; phrase = {ph: [leaf...]}; {and: [...]}; {or: [...]}
function leafMask(l) {
  const { post, N } = index();
  const m = new Uint8Array(N);
  for (const t of l.pre ? prefixTerms(l.t) : [l.t]) for (const d of post.get(t) || []) m[d] = 1;
  return m;
}
function phraseHit(doc, ph) {
  const toks = ftsTokens(indexText(searchText(OFFERS[doc])));
  for (let i = 0; i + ph.length <= toks.length; i++) {
    let ok = true;
    for (let j = 0; j < ph.length && ok; j++) ok = ph[j].pre ? toks[i + j].startsWith(ph[j].t) : toks[i + j] === ph[j].t;
    if (ok) return true;
  }
  return false;
}
function evalTerm(term, leaves) {
  const N = index().N;
  if (term.t != null) { const m = leafMask(term); leaves?.push({ m, n: count(m) }); return m; }
  if (term.ph) {
    const ms = term.ph.map(l => leafMask(l));
    const m = new Uint8Array(N);
    for (let d = 0; d < N; d++) if (ms.every(x => x[d]) && phraseHit(d, term.ph)) m[d] = 1;
    leaves?.push({ m, n: count(m) });
    return m;
  }
  const ms = (term.and || term.or).map(x => evalTerm(x, leaves));
  const m = new Uint8Array(N);
  if (term.and) { for (let d = 0; d < N; d++) m[d] = ms.every(x => x[d]) ? 1 : 0; }
  else { for (let d = 0; d < N; d++) m[d] = ms.some(x => x[d]) ? 1 : 0; }
  return m;
}
const count = m => { let n = 0; for (const x of m) n += x; return n; };

// one quoted FTS string ("2tb"* / "2 tb"* / "rog strix") -> leaf or phrase
function ftsString(s, pre) {
  const ts = ftsTokens(s);
  if (!ts.length) return null;
  if (ts.length === 1) return { t: ts[0], pre };
  return { ph: ts.map((t, i) => ({ t, pre: pre && i === ts.length - 1 })) };
}
const _p = part => ftsString(part, !isDigit(part[0]));       // numbers exact, words by prefix
function ftsTerm(tok) {
  const ps = parts(tok);
  if (ps.length === 2 && isDigit(ps[0][0]) && !isDigit(ps[1][0])) return { or: [ftsString(tok, true), ftsString(ps[0] + " " + ps[1], true)].filter(Boolean) };
  if (ps.length > 1) return { or: [{ and: ps.map(_p).filter(Boolean) }, ftsString(tok, true)].filter(Boolean) };
  return _p(tok);
}

// ------------------------------------------------------------------ query language (query.parse)
export function parse(q) {
  const filters = {};
  q = fold(q || "");
  q = q.replace(/\b(brand|store|cat):("[^"]+"|\S+)/g, (_, k, v) => { (filters[k] ??= []).push(v.replace(/^"|"$/g, "")); return " "; });
  q = q.replace(/\bprice ?([<>])=? ?([\d,]+)|(?<![\w.])([<>])=? ?([\d,]+)\b|\bprice:([\d,]+)-([\d,]+)/g, (m, op1, a1, op2, a2, lo, hi) => {
    const n = x => parseFloat(x.replace(/,/g, ""));
    if (lo && hi) { filters.min = n(lo); filters.max = n(hi); }
    else { const op = op1 || op2, a = n(a1 || a2); filters[op === "<" ? "max" : "min"] = a; }
    return " ";
  });
  const words = [], ps = [], loose = [];
  for (const m of q.matchAll(/(-?)"([^"]+)"|(\S+)/g)) {
    const [, negQ, phrase, w] = m;
    if (phrase) {
      const toks = phrase.match(TOKEN) || [];
      if (toks.length) {
        const term = ftsString(toks.join(" "), false);
        if (term) { ps.push(negQ ? { not: term } : term); if (!negQ) { words.push(...toks); loose.push(term); } }
      }
      continue;
    }
    if (w === "or") { ps.push("OR"); continue; }
    const neg = w.startsWith("-") && w.length > 1;
    for (const t of (neg ? w.slice(1) : w).match(TOKEN) || []) {
      const term = ftsTerm(t);
      if (!term) continue;
      ps.push(neg ? { not: term } : term);
      if (!neg) { words.push(t); loose.push(term); }
    }
  }
  const groups = [], nots = [];
  let joinNext = false;
  for (const p of ps) {
    if (p === "OR") { joinNext = groups.length > 0; continue; }
    if (p.not) { nots.push(p.not); joinNext = false; continue; }
    if (joinNext) groups.at(-1).push(p); else groups.push([p]);
    joinNext = false;
  }
  const fts = groups.length ? { and: groups.map(g => g.length === 1 ? g[0] : { or: g }), nots } : null;
  return { fts, loose: loose.length ? { or: loose, nots: [] } : null, filters, words };
}

// ------------------------------------------------------------------ category intent (query.intent, simplified)
const B0 = `(?<!${W})`, B1 = `(?!${W})`;
const word = s => rx(`${B0}(?:${s})${B1}`);
const ACC = word("cables?|adapters?|converters?|hubs?|docks?|docking|chargers?|splitters?|extensions?|bags?|backpacks?|sleeves?|" +
  "covers?|skins?|stickers?|holders?|stands?|mounts?|brackets?|screen protectors?|kabel|وصله|وصلة|شاحن|شنطه|حامل|جراب");
const INTENTS = [
  ["mousepad", "mouse ?pads?|mousepads?|desk ?mats?|ماوس باد"],
  [null, "combo|keyboard (?:and|&|\\+) mouse|mouse (?:and|&|\\+) keyboard"],
  ["laptop", "laptops?|notebooks?|macbook|لابتوب|لاب توب"],
  ["desktop", "desktops?|gaming pc|pc build|pc builds|all in one pc|تجميعه|تجميعة"],
  ["monitor", "monitors?|مونيتور|مونيتر|شاشه كمبيوتر|\\d{2}(?:\\.\\d)? ?(?:inch|بوصه) \\d{2,3} ?hz|\\d{3} ?hz"],
  ["gpu", "graphics cards?|graphic cards?|video cards?|vga cards?|gpu|كارت شاشه|كرت شاشه"],
  ["motherboard", "motherboards?|mainboards?|mobo|مازربورد|ماذربورد|بورده"],
  ["cooler", "cpu coolers?|air coolers?|liquid coolers?|aio|water cooling|مبرد"],
  ["psu", "power supply|power supplies|psu|باور سبلاي|باور|\\d{3,4} ?w(?:att)? (?:80 ?plus )?(?:bronze|gold|platinum|titanium)"],
  ["ram", "ram|rams|memory|ddr[345]l?|رامات|رام|ذاكره"],
  ["ssd", "ssd|ssds|nvme|m\\.2 ssd"],
  ["hdd", "hdd|hard drives?|hard disks?|هارد"],
  ["thermal", "thermal paste|thermal pads?|معجون"],
  ["case", "pc cases?|cases?|chassis|كيسه|كيس"],
  ["fan", "case fans?|fans?|مراوح|مروحه"],
  ["keyboard", "keyboards?|كيبورد"],
  ["mouse", "mouse|mice|ماوس"],
  ["headset", "headsets?|headphones?|earphones?|earbuds|سماعه|سماعات"],
  ["speaker", "speakers?|soundbar|سبيكر"],
  ["webcam", "webcams?|web cam"],
  ["microphone", "microphones?|mic|ميكروفون|مايك"],
  ["chair", "chairs?|كرسي"],
  ["controller", "controllers?|gamepads?|joysticks?|دراع"],
  ["network", "routers?|access points?|network switch|wifi adapter|mesh wifi|راوتر"],
  ["ups", "ups"],
  ["printer", "printers?|ink|toner|طابعه"],
  ["console", "ps5|ps4|playstation|xbox|nintendo switch"],
  ["phone", "iphone|phones?|smartphones?|mobile phones?|موبايل"],
  ["tablet", "ipad|tablets?|تابلت"],
  ["tv", "tv|tvs|television|تلفزيون|شاشه تلفزيون"],
  ["wearable", "smart ?watch(?:es)?|smart band|ساعه ذكيه"],
  ["storage_ext", "flash drives?|flash memory|usb flash|external hard|external ssd|memory cards?|micro ?sd|فلاشه"],
].map(([c, s]) => [c, word(s)]);
const GPU_CHIP = /\b(rtx|gtx|rx|arc)\s?-?\s?([ab]?\d{3,4})\b/;
const CPU_CHIP = /\b(i[3579]\s?-?\s?\d{4,5}[a-z]{0,2}|ryzen\s?[3579]\s?\d{4}[a-z0-9]{0,3}|r[3579]\s?\d{4}[a-z0-9]{0,3}|\d{4}x3d|[3-9]\d{3}x|1[2-4]\d{3}k?f?|core ultra\s?[3579]\s?\d{3}[a-z]{0,2}|ultra [3579] \d{3}[a-z]{0,2})\b/;
export function intent(q) {
  const words = parse(q).words;
  if (!words.length) return null;
  const t = words.join(" ");
  if (ACC.test(t)) return null;
  for (const [c, r] of INTENTS) if (r.test(t)) return c;
  if (GPU_CHIP.test(t)) return "gpu";
  if (CPU_CHIP.test(t)) return "cpu";
  return null;
}
const CATEGORY_WORDS = {
  gpu: "graphics?|cards?|video|vga|gpu|كارت|كرت|بطاقه|شاشه|رسوميات", cpu: "processors?|cpu|معالج|بروسيسور",
  motherboard: "motherboards?|mainboards?|mobo|board|مازربورد|لوحه|الام", ram: "ram|rams|memory|desktop|رامات|رام|ذاكره",
  ssd: "ssd|ssds|internal|solid|state|drive", hdd: "hdd|hard|disk|drive|internal|هارد", psu: "power|supply|supplies|psu|باور|سبلاي",
  case: "case|cases|chassis|pc|كيسه|كيس", cooler: "cpu|coolers?|cooling|مبرد", fan: "fans?|case|مراوح|مروحه",
  monitor: "monitors?|screen|display|gaming|شاشه|مونيتور", laptop: "laptops?|notebooks?|لابتوب|لاب|توب",
  desktop: "desktops?|pc|computer|build|كمبيوتر|تجميعه", keyboard: "keyboards?|كيبورد", mouse: "mouse|mice|ماوس",
  headset: "headsets?|headphones?|سماعه|سماعات", mousepad: "mouse|pads?|mousepads?", chair: "chairs?|كرسي",
};
function stripCategoryWords(q, cat) {
  const r = CATEGORY_WORDS[cat];
  if (!r) return q;
  return fold(q).replace(rx(`(?<![\\p{L}\\p{N}_"-])(?:${r})(?![\\p{L}\\p{N}_"])`, "g"), " ").replace(/\s+/g, " ").trim();
}
const gbOrTb = m => String(Math.round(parseFloat(m[1]) * (m[2] === "tb" ? 1024 : 1)));
const SPEC_WORDS = {
  ram: [[/\b(\d{1,3}) ?gb\b/, "capacity", m => m[1]]],
  gpu: [[/\b(\d{1,2}) ?gb?\b/, "vram", m => m[1]]],
  ssd: [[/\b(\d+(?:\.\d)?) ?(tb|gb)\b/, "capacity", gbOrTb]],
  hdd: [[/\b(\d+(?:\.\d)?) ?(tb|gb)\b/, "capacity", gbOrTb]],
  psu: [[/\b(\d{3,4}) ?w(?:att)?s?\b/, "watt", m => m[1]]],
  monitor: [[rx(`\\b(\\d{2}(?:\\.\\d)?) ?("|inch|in|بوصه)${B1}`), "size", m => String(parseFloat(m[1]))],
            [/\b(\d{2,3}) ?hz\b/, "hz", m => m[1]]],
};
function specFilters(q, cat) {
  const found = {};
  let t = fold(q);
  for (const [r, key, val] of SPEC_WORDS[cat] || []) {
    const m = t.match(r);
    if (m && !(key in found)) { found[key] = val(m); t = t.slice(0, m.index) + " " + t.slice(m.index + m[0].length); }
  }
  return [t.replace(/\s+/g, " ").trim(), found];
}

// ------------------------------------------------------------------ spelling (server.correct)
function ratio(a, b) {         // like difflib.SequenceMatcher.ratio (via the longest common subsequence)
  const n = a.length, m = b.length, dp = Array(m + 1).fill(0);
  for (let i = 1; i <= n; i++) {
    let prev = 0;
    for (let j = 1; j <= m; j++) {
      const tmp = dp[j];
      dp[j] = a[i - 1] === b[j - 1] ? prev + 1 : Math.max(dp[j], dp[j - 1]);
      prev = tmp;
    }
  }
  return 2 * dp[m] / (n + m);
}
function correct(q) {
  const fixes = {};
  for (const w of parse(q).words) {
    if (w.length < 4 || /^\d+$/.test(w)) continue;
    const own = df(w);
    if (own >= 5 || (!own && prefixTerms(w).length)) continue;
    const v = index().vocab;
    let best = null;
    for (let i = lowerBound(v, w[0]); i < v.length && v[i][0] === w[0]; i++) {
      const t = v[i];
      if (t === w || Math.abs(t.length - w.length) > 2) continue;
      const d = df(t);
      if (d < 10 * (own + 1)) continue;
      const r = ratio(w, t);
      if (r < 0.75) continue;
      const s = r + Math.min(d, 500) / 5000;
      if (!best || s > best[0]) best = [s, t];
    }
    if (best) fixes[w] = best[1];
  }
  if (!Object.keys(fixes).length) return [q, {}];
  let f = fold(q);
  for (const [w, t] of Object.entries(fixes)) f = f.replace(rx(`(?<!${W})${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!${W})`, "g"), t);
  return [f, fixes];
}

// ------------------------------------------------------------------ search (server.search)
const one = (qs, k, d = null) => { const v = qs[k]; return v != null && v !== "" ? v : d; };

// docs matching the text expression (null = every doc) and their scores
function textMatch(expr) {
  if (!expr) return null;
  const { len, avg, N } = index();
  const leaves = [];
  const m = evalTerm(expr.and ? { and: expr.and } : { or: expr.or }, leaves);
  for (const nt of expr.nots || []) { const x = evalTerm(nt); for (let d = 0; d < N; d++) if (x[d]) m[d] = 0; }
  const docs = [], score = new Map();
  const k1 = 1.2, b = 0.75;
  for (let d = 0; d < N; d++) {
    if (!m[d]) continue;
    let s = 0;
    for (const l of leaves) if (l.m[d]) {
      const idf = Math.log((N - l.n + 0.5) / (l.n + 0.5) + 1);
      s += idf * (k1 + 1) / (1 + k1 * (1 - b + b * len[d] / avg));
    }
    docs.push(d);
    score.set(d, s);
  }
  return { docs, score };
}

function makeFilter(qs, parsed, skip) {
  const flt = parsed.filters, tests = [];
  for (const b of flt.brand || []) tests.push(o => (o.brand || "").includes(b));
  for (const st of flt.store || []) tests.push(o => o.store_id.includes(st) || o.store.toLowerCase().includes(st));
  const cat = one(qs, "cat") || (flt.cat || [])[0];
  if (cat) tests.push(o => o.category === cat);
  if (skip !== "store" && one(qs, "store")) { const s = new Set(one(qs, "store").split(",")); tests.push(o => s.has(o.store_id)); }
  if (one(qs, "group")) { const g = new Set(one(qs, "group").split(",")); tests.push(o => g.has(o.grp)); }
  if (skip !== "brand" && one(qs, "brand")) { const b = new Set(one(qs, "brand").split("|")); tests.push(o => b.has(o.brand)); }
  const lo = one(qs, "min") ?? flt.min, hi = one(qs, "max") ?? flt.max;
  if (lo != null) tests.push(o => o.price >= +lo);
  if (hi != null) tests.push(o => o.price <= +hi);
  if (one(qs, "stock", "1") === "1") tests.push(o => o.in_stock);
  if (one(qs, "deal") === "1") tests.push(o => o.old_price > o.price);
  if (one(qs, "suspect", "0") !== "1") tests.push(o => !o.suspect);
  if (one(qs, "pc") === "1") { const pc = new Set(META.pc); tests.push(o => pc.has(o.category)); }
  for (const [k, v] of Object.entries(qs)) {
    if (!k.startsWith("f_") || k.slice(2) === skip || !v) continue;
    const key = k.slice(2), vs = new Set(String(v).split("|"));
    tests.push(o => o.specs[key] != null && vs.has(String(o.specs[key])));
  }
  return o => tests.every(t => t(o));
}

const disc = (a, b) => (a > b ? (a - b) / a : 0);
const SORTS = {
  price: (a, b) => a.price - b.price, "-price": (a, b) => b.price - a.price,
  discount: (a, b) => disc(b.old_price, b.price) - disc(a.old_price, a.price) || a.price - b.price,
  new: (a, b) => (b.first_seen > a.first_seen) - (b.first_seen < a.first_seen) || a.price - b.price,
  drop: (a, b) => disc(b.prev_price, b.price) - disc(a.prev_price, a.price) || a.price - b.price,
};

let MODEL_STATS = null;      // model_key -> [stores, cheapest] over in-stock, non-suspect offers
function modelStats() {
  if (MODEL_STATS) return MODEL_STATS;
  const m = new Map();
  for (const o of OFFERS) {
    if (!o.in_stock || o.suspect || !o.model_key) continue;
    let s = m.get(o.model_key);
    if (!s) m.set(o.model_key, s = { stores: new Set(), best: Infinity });
    s.stores.add(o.store_id);
    if (o.price < s.best) s.best = o.price;
  }
  return MODEL_STATS = m;
}
const pub = o => { const { grp, _d, ...rest } = o; return rest; };

async function search(input) {
  await ready();
  let qs = { ...input };
  if (one(qs, "stock", "1") !== "1") await loadOut();
  let q = one(qs, "q", "");
  let fixes = {};
  if (q) [q, fixes] = correct(q);
  let parsed = parse(q), it = null;
  const canGuess = q && !one(qs, "cat") && !parsed.filters.cat && one(qs, "allcat") !== "1";
  const useIntent = c => {
    it = c;
    qs.cat = c;
    const [rest, specs] = specFilters(stripCategoryWords(q, c), c);
    for (const [k, v] of Object.entries(specs)) if (qs["f_" + k] == null) qs["f_" + k] = v;
    parsed = parse(rest);
  };
  if (canGuess && intent(q)) useIntent(intent(q));
  let expr = parsed.fts, partial = false;
  let tm = textMatch(expr);
  const base = () => tm ? tm.docs.map(d => OFFERS[d]) : OFFERS;
  let pool = base(), f = makeFilter(qs, parsed), hits = pool.filter(f);
  if (canGuess && !it && hits.length >= 8) {
    // no rule named a category: if most matching listings are one kind of PC product, open that category
    // ("corsair vengeance" -> RAM, "i7 14700k" -> CPUs)
    const c = new Map();
    for (const o of hits) c.set(o.category, (c.get(o.category) || 0) + 1);
    const [top, n] = [...c].sort((a, b) => b[1] - a[1])[0];
    if (n >= 0.6 * hits.length && !["accessory", "other"].includes(top)) {
      useIntent(top);
      expr = parsed.fts; tm = textMatch(expr);
      pool = base(); f = makeFilter(qs, parsed); hits = pool.filter(f);
    }
  }
  if (!hits.length && it) {                 // nothing in the guessed category: search everything
    delete qs.cat;
    for (const k of Object.keys(qs)) if (k.startsWith("f_") && !(k in input)) delete qs[k];
    it = null;
    parsed = parse(q); expr = parsed.fts; tm = textMatch(expr);
    pool = base(); f = makeFilter(qs, parsed); hits = pool.filter(f);
  }
  if (!hits.length && parsed.fts && parsed.loose && parsed.words.length > 1) {
    expr = parsed.loose; partial = true;    // no exact match: any of the words, best matches first
    tm = textMatch(expr);
    pool = base(); hits = pool.filter(f);
  }
  const hasRank = !!tm;
  const score = o => tm.score.get(o._d) || 0;
  let sortKey = one(qs, "sort") || ((one(qs, "cat") || !hasRank) && !partial ? "price" : "relevance");
  if (sortKey === "relevance" && !hasRank) sortKey = "price";
  const cmp = sortKey === "relevance" ? (a, b) => score(b) - score(a) || b.in_stock - a.in_stock || a.price - b.price : (SORTS[sortKey] || SORTS.price);
  const page = Math.max(1, parseInt(one(qs, "page", "1"))), size = Math.min(200, parseInt(one(qs, "size", "48")));
  const view = one(qs, "view", "offers");
  let items, total;
  if (view === "models") {
    const g = new Map();
    for (const o of hits) { const k = o.model_key; let x = g.get(k); if (!x) g.set(k, x = []); x.push(o); }
    const models = [...g.values()].map(list => {
      list.sort((a, b) => a.price - b.price || b.in_stock - a.in_stock);
      const r = list[0];
      return { ...pub(r), best: r.price, worst: list.at(-1).price, nstores: new Set(list.map(x => x.store_id)).size,
        noffers: list.length, _s: hasRank ? Math.max(...list.map(score)) : 0, _r: r };
    });
    total = models.length;
    models.sort(sortKey === "relevance" ? (a, b) => b._s - a._s || a.best - b.best : (a, b) => cmp(a._r, b._r));
    items = models.slice((page - 1) * size, page * size).map(({ _s, _r, ...m }) => m);
  } else {
    total = hits.length;
    items = [...hits].sort(cmp).slice((page - 1) * size, page * size).map(pub);
    const ms = modelStats();
    for (const i of items) { const s = ms.get(i.model_key); i.model_stores = s ? s.stores.size : 0; i.model_best = s ? s.best : null; }
  }

  const counts = (list, key) => { const c = new Map(); for (const o of list) { const v = key(o); if (v != null && v !== "") c.set(v, (c.get(v) || 0) + 1); } return c; };
  const facets = {};
  const cat = one(qs, "cat") || (parsed.filters.cat || [])[0];
  for (const [key, label] of [["condition", "Condition"], ...(META.facet_labels[cat] || [])]) {
    const f2 = makeFilter(qs, parsed, key);
    let vals = [...counts(pool.filter(f2), o => o.specs[key] != null ? String(o.specs[key]) : null)].map(([v, n]) => ({ v, n }));
    if (META.numeric.includes(key)) vals.sort((a, b) => (/^[\d.]+$/.test(a.v) ? +a.v : 0) - (/^[\d.]+$/.test(b.v) ? +b.v : 0));
    else vals.sort((a, b) => b.n - a.n);
    facets[key] = { label, values: vals.slice(0, 60) };
  }
  const brands = [...counts(pool.filter(makeFilter(qs, parsed, "brand")), o => o.brand)].sort((a, b) => b[1] - a[1]).slice(0, 80).map(([v, n]) => ({ v, n }));
  const stores = [...counts(pool.filter(makeFilter(qs, parsed, "store")), o => o.store_id)].sort((a, b) => b[1] - a[1])
    .map(([id, n]) => ({ id, name: SIDX[id]?.name || id, n }));
  const qs2 = Object.fromEntries(Object.entries(qs).filter(([k]) => k !== "cat" && !k.startsWith("f_")));
  const cats = [...counts(pool.filter(makeFilter(qs2, parsed)), o => o.category)].sort((a, b) => b[1] - a[1])
    .map(([id, n]) => ({ id, label: META.labels[id] || id, n }));
  let pmin = null, pmax = null;
  for (const o of hits) { if (pmin == null || o.price < pmin) pmin = o.price; if (pmax == null || o.price > pmax) pmax = o.price; }
  return {
    total, page, size, items, facets, brands, stores, categories: cats, price: { min: pmin, max: pmax }, sort: sortKey,
    intent: it ? { cat: it, label: META.labels[it] } : null, partial, corrected: Object.keys(fixes).length ? q : null,
    auto_specs: it ? Object.fromEntries(Object.entries(qs).filter(([k]) => k.startsWith("f_")).map(([k, v]) => [k.slice(2), v])) : {},
    parsed: { filters: parsed.filters, words: parsed.words },
  };
}

// ------------------------------------------------------------------ offer drawer (server.offer)
async function history(ids) {
  const out = {};
  const shards = [...new Set(ids.map(id => id % META.hist_shards))];
  await Promise.all(shards.map(async n => { if (!HIST.has(n)) HIST.set(n, await json(`${DATA}hist/${n}.json`).catch(() => ({}))); }));
  for (const id of ids) out[id] = HIST.get(id % META.hist_shards)[id] || null;
  return out;
}
async function offer(id, all) {
  await ready();
  if (all) await loadOut();
  let o = BYID.get(id);
  if (!o && !OUT_LOADED) { await loadOut(); o = BYID.get(id); }
  if (!o) throw new Error("not found");
  const same = OFFERS.filter(x => x.model_key === o.model_key).sort((a, b) => b.in_stock - a.in_stock || a.price - b.price);
  const shown = same.filter(x => all || x.in_stock || x.id === o.id);
  const outCount = OUT_LOADED ? same.length - shown.length : (SOLD[o.model_key] || 0) - (o.in_stock ? 0 : 1);
  const H = await history(same.map(x => x.id));
  const today = META.last_run?.started?.slice(0, 10) || o.first_seen;
  const pts = x => (H[x.id] || [[x.first_seen || today, x.price, x.in_stock]]).map(([day, price, in_stock]) => ({ day, price, in_stock }));
  const byDay = new Map();
  for (const x of same) for (const p of pts(x)) if (p.in_stock && (!byDay.has(p.day) || p.price < byDay.get(p.day))) byDay.set(p.day, p.price);
  const similar = o.family ? OFFERS.filter(x => x.family === o.family && x.model_key !== o.model_key && x.in_stock && !x.suspect)
    .sort((a, b) => a.price - b.price).slice(0, 24).map(pub) : [];
  return {
    ...pub(o), history: pts(o), same: shown.map(pub), sold_out_hidden: Math.max(0, outCount), similar,
    model_history: [...byDay].sort((a, b) => (a[0] > b[0]) - (a[0] < b[0])).map(([day, price]) => ({ day, price })),
  };
}

// ------------------------------------------------------------------ entry point
export async function api(path) {
  const u = new URL(path, "http://x");
  const qs = Object.fromEntries(u.searchParams);
  if (u.pathname === "/api/meta") { await ready(); return META; }
  if (u.pathname === "/api/stores") { await ready(); return STORES; }
  if (u.pathname === "/api/search") return search(qs);
  if (u.pathname === "/api/offer") return offer(parseInt(qs.id), qs.all === "1");
  throw new Error("unknown endpoint " + u.pathname);
}
