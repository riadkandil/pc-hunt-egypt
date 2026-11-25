"""Static copy of the website for GitHub Pages: the front end plus the live offers as JSON files; the search runs in the
browser (static/local.js answers the same /api/* calls as server.py).

    python -X utf8 -m pchunt.export_site [out_dir]        # default: site/

Files (data/):
    meta.json          categories, labels, facets, totals, last run
    stores.json        the Stores page
    offers-in-<n>.json   every live in-stock offer, PART_ROWS per file (loaded first, in parallel; part 0 has "sold")
    offers-out-<n>.json  live sold-out offers (loaded only when "In stock only" is off or a drawer asks for them)
                         meta.json "parts" = {"in": count, "out": count}
    hist/<n>.json      price history of offers whose price or stock changed, n = id % HIST_SHARDS
Offer rows are arrays (see COLS); urls / images drop a per-store prefix (stores.json "up" / "ip").
"""
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .classify import CATEGORIES, FACETS, PC_CATEGORIES
from .server import GROUPS, NUMERIC, meta, stores

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
HIST_SHARDS = 64
PART_ROWS = 40000      # rows per offers file (~12 MB): GitHub refuses files over 100 MB, Raneen alone may add 170k offers
COLS = ["id", "s", "title", "brand", "cat", "specs", "family", "model_key", "url", "image", "price", "old_price",
        "seller", "first_seen", "price_changed", "prev_price", "suspect"]


def _prefix(values):
    """The '/'-ended prefix that saves the most characters over these strings."""
    cnt = Counter()
    for v in values:
        i = 0
        while True:
            i = v.find("/", i + 1)
            if i < 0:
                break
            cnt[v[:i + 1]] += 1
    if not cnt:
        return ""
    best = max(cnt.items(), key=lambda kv: (len(kv[0]) - 1) * kv[1])
    return best[0] if best[1] >= max(3, len(values) // 5) else ""


def _num(x):
    if x is None:
        return 0
    return int(x) if float(x).is_integer() else round(float(x), 2)


def _dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return path.stat().st_size


def export(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    con = db.connect()
    rows = con.execute(f"""SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id
                           WHERE {db.ACTIVE} ORDER BY o.id""").fetchall()
    st = stores(con)
    sid = {s["id"]: i for i, s in enumerate(st)}
    by_store = defaultdict(list)
    for r in rows:
        by_store[r["store_id"]].append(r)
    for s in st:
        rs = by_store.get(s["id"], [])
        s["up"] = _prefix([r["url"] for r in rs])
        s["ip"] = _prefix([r["image"] or "" for r in rs if r["image"]])
    pre = {s["id"]: (s["up"], s["ip"]) for s in st}
    cat_ix = {c: i for i, c in enumerate(CATEGORIES)}

    def row(r):
        up, ip = pre[r["store_id"]]
        url, img = r["url"], r["image"] or ""
        specs = json.loads(r["specs"] or "{}")
        return [r["id"], sid[r["store_id"]], r["title"], r["brand"] or "", cat_ix.get(r["category"], cat_ix["other"]),
                specs or 0, r["family"] or "", r["model_key"] or "",
                url[len(up):] if up and url.startswith(up) else url, img[len(ip):] if ip and img.startswith(ip) else img,
                _num(r["price"]), _num(r["old_price"]), r["seller"] or "", r["first_seen"] or "",
                r["price_changed"] or "", _num(r["prev_price"]), r["suspect"] or 0]

    ins = [row(r) for r in rows if r["in_stock"]]
    outs = [row(r) for r in rows if not r["in_stock"]]
    # sold-out listings per model, so the drawer can say "+ n sold out" before offers-out.json is loaded
    sold = Counter(r["model_key"] for r in rows if not r["in_stock"] and r["model_key"])
    in_keys = {r["model_key"] for r in rows if r["in_stock"]}
    sizes, parts = {}, {}
    for kind, rs in (("in", ins), ("out", outs)):
        chunks = [rs[i:i + PART_ROWS] for i in range(0, len(rs), PART_ROWS)] or [[]]
        parts[kind] = len(chunks)
        for n, chunk in enumerate(chunks):
            obj = {"cols": COLS, "rows": chunk}
            if kind == "in" and n == 0:
                obj["sold"] = {k: c for k, c in sold.items() if k in in_keys}
            name = f"offers-{kind}-{n}.json"
            sizes[name] = _dump(out / "data" / name, obj)
    # price history: only offers whose price or stock ever changed (others: one point = today's price)
    hist = defaultdict(dict)
    live = {r["id"] for r in rows}
    cur, pts = None, []

    def flush():
        if cur in live:
            ch = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if (a[1], a[2]) != (p[1], p[2])]
            if len(ch) > 1:
                if ch[-1] is not pts[-1]:
                    ch.append(pts[-1])
                hist[cur % HIST_SHARDS][cur] = ch
    for oid, day, price, stock in con.execute("SELECT offer_id, day, price, in_stock FROM prices ORDER BY offer_id, day"):
        if oid != cur:
            if pts:
                flush()
            cur, pts = oid, []
        pts.append([day, _num(price), stock])
    if pts:
        flush()
    for n in range(HIST_SHARDS):
        _dump(out / f"data/hist/{n}.json", hist.get(n, {}))
    m = meta(con)
    m.update({"cats": list(CATEGORIES), "pc": PC_CATEGORIES, "numeric": sorted(NUMERIC), "groups": GROUPS,
              "facet_labels": {k: v for k, v in FACETS.items()}, "hist_shards": HIST_SHARDS,
              "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "sizes": sizes, "parts": parts, "in_stock": len(ins), "sold_out": len(outs)})
    _dump(out / "data/meta.json", m)
    _dump(out / "data/stores.json", st)
    con.close()
    for f in STATIC.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    html = (out / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--static-->", '<script>window.PCHUNT_STATIC = true;</script>')
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("")
    (out / "404.html").write_text(html, encoding="utf-8")
    return {"in_stock": len(ins), "sold_out": len(outs), "files": sizes}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site"
    info = export(out)
    print(f"site -> {out}: {info['in_stock']} in stock, {info['sold_out']} sold out, "
          + ", ".join(f"{k} {v / 1e6:.1f} MB" for k, v in info["files"].items()))


if __name__ == "__main__":
    main()
