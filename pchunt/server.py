"""PC Hunt web app: search, filter and compare every scraped offer.

    python -m pchunt.server            # http://127.0.0.1:8790
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db
from . import query
from .classify import CATEGORIES, FACETS, PC_CATEGORIES, norm

STATIC = Path(__file__).resolve().parent / "static"
PORT = 8790
GROUPS = {"A": "PC hardware specialists", "B": "Computer & laptop stores", "C": "Electronics chains & retailers",
          "D": "Marketplaces", "E": "Gaming stores", "F": "Server & enterprise"}
NUMERIC = {"vram", "capacity", "speed", "cl", "watt", "radiator", "size", "hz", "rpm", "ram", "storage", "va", "pack"}
ACTIVE = db.ACTIVE
SORTS = {
    "price": "o.price ASC", "-price": "o.price DESC",
    "discount": "CASE WHEN o.old_price > o.price THEN (o.old_price - o.price) / o.old_price ELSE 0 END DESC, o.price",
    "new": "o.first_seen DESC, o.price", "drop": "CASE WHEN o.prev_price > o.price THEN (o.prev_price - o.price) / o.prev_price ELSE 0 END DESC, o.price",
}


def one(qs, k, default=None):
    v = qs.get(k)
    return v[0] if v and v[0] != "" else default


FROM = "FROM offers o JOIN stores s ON s.id = o.store_id"


def build_where(qs, skip=None):
    """(FROM clause, WHERE clause, params) for the query string; `skip` leaves one facet out (for its own counts).
    The search box goes through the full-text index (query.parse); qs["_fts"] can override its expression."""
    parsed = qs.get("_parsed") or query.parse(one(qs, "q", ""))
    frm, jp = FROM, []
    fts = qs.get("_fts", parsed["fts"])
    if fts:
        # CROSS JOIN pins the order: one full-text match, then offers looked up by rowid (else SQLite re-runs the
        # match for every offer row)
        frm = ("FROM (SELECT rowid AS fid, rank FROM offers_fts WHERE offers_fts MATCH ?) f "
               "CROSS JOIN offers o ON o.id = f.fid JOIN stores s ON s.id = o.store_id")
        jp.append(fts)
    w, p = [ACTIVE], []
    flt = parsed["filters"]
    for b in flt.get("brand", []):
        w.append("o.brand LIKE ?")
        p.append(f"%{b}%")
    for st in flt.get("store", []):
        w.append("(o.store_id LIKE ? OR s.name LIKE ?)")
        p += [f"%{st}%", f"%{st}%"]
    cat = one(qs, "cat") or (flt.get("cat") or [None])[0]
    if cat:
        w.append("o.category = ?")
        p.append(cat)
    if skip != "store" and one(qs, "store"):
        ids = one(qs, "store").split(",")
        w.append(f"o.store_id IN ({','.join('?' * len(ids))})")
        p += ids
    if one(qs, "group"):
        gs = one(qs, "group").split(",")
        w.append(f"s.grp IN ({','.join('?' * len(gs))})")
        p += gs
    if skip != "brand" and one(qs, "brand"):
        bs = one(qs, "brand").split("|")
        w.append(f"o.brand IN ({','.join('?' * len(bs))})")
        p += bs
    lo = one(qs, "min") or flt.get("min")
    hi = one(qs, "max") or flt.get("max")
    if lo:
        w.append("o.price >= ?")
        p.append(float(lo))
    if hi:
        w.append("o.price <= ?")
        p.append(float(hi))
    if one(qs, "stock", "1") == "1":
        w.append("o.in_stock = 1")
    if one(qs, "deal") == "1":
        w.append("o.old_price > o.price")
    if one(qs, "suspect", "0") != "1":
        w.append("o.suspect = 0")
    if one(qs, "pc") == "1":
        w.append(f"o.category IN ({','.join('?' * len(PC_CATEGORIES))})")
        p += PC_CATEGORIES
    for k, vals in qs.items():
        if not k.startswith("f_") or k[2:] == skip or not vals or not vals[0]:
            continue
        key = re.sub(r"[^a-z0-9_]", "", k[2:])
        vs = vals[0].split("|")
        w.append(f"CAST(json_extract(o.specs, '$.{key}') AS TEXT) IN ({','.join('?' * len(vs))})")
        p += vs
    return frm, " AND ".join(w), jp + p


def offer_dict(r, extra=()):
    d = {k: r[k] for k in ("id", "store_id", "url", "title", "brand", "category", "family", "model_key", "image",
                           "price", "old_price", "in_stock", "seller", "first_seen", "last_seen", "price_changed",
                           "prev_price", "suspect")}
    d["specs"] = json.loads(r["specs"] or "{}")
    d["store"] = r["store_name"]
    for k in extra:
        d[k] = r[k]
    return d


def correct(con, q):
    """Fix misspelt words against the words that occur in listings ("keybaord" -> "keyboard")."""
    import difflib
    words = query.parse(q)["words"]
    fixes = {}
    try:
        for w in words:
            if len(w) < 4 or w.isdigit():
                continue
            own = con.execute("SELECT doc FROM offers_vocab WHERE term = ?", (w,)).fetchone()
            own = own[0] if own else 0
            if own >= 5 or (not own and con.execute(
                    "SELECT 1 FROM offers_vocab WHERE term > ? AND term < ? LIMIT 1", (w, w + "￿")).fetchone()):
                continue                       # common word, or the start of one
            cands = con.execute("SELECT term, doc FROM offers_vocab WHERE term >= ? AND term < ? AND length(term) BETWEEN ? AND ?",
                                (w[0], w[0] + "￿", len(w) - 2, len(w) + 2)).fetchall()
            # a rare word (a store's own typo counts) next to a much more common near-identical one
            best = max(((difflib.SequenceMatcher(None, w, t).ratio() + min(d, 500) / 5000, t) for t, d in cands
                        if t != w and d >= 10 * (own + 1) and difflib.SequenceMatcher(None, w, t).ratio() >= 0.75), default=None)
            if best:
                fixes[w] = best[1]
    except Exception:
        return q, {}
    if not fixes:
        return q, {}
    folded = query.fold(q)
    for w, t in fixes.items():
        folded = re.sub(rf"(?<![\w]){re.escape(w)}(?![\w])", t, folded)
    return folded, fixes


def search(con, qs):
    qs = dict(qs)
    q = one(qs, "q", "")
    q, fixes = correct(con, q) if q else (q, {})
    parsed = query.parse(q)
    # category intent: "logitech keyboard" searches Keyboards (laptops that mention a keyboard stay out)
    intent = None
    if q and not one(qs, "cat") and not parsed["filters"].get("cat") and one(qs, "allcat") != "1":
        intent = query.intent(q)
        if intent:
            qs["cat"] = [intent]
            rest = query.strip_category_words(q, intent)
            rest, specs = query.spec_filters(rest, intent)
            for k, v in specs.items():             # "32gb" -> capacity 32 (exact), unless the user set that filter
                qs.setdefault("f_" + k, [v])
            parsed = query.parse(rest)             # the category filter replaces the generic words
    qs["_parsed"] = parsed
    partial = False
    frm, where, params = build_where(qs)
    total = con.execute(f"SELECT COUNT(*) {frm} WHERE {where}", params).fetchone()[0]
    if total == 0 and intent:                 # nothing in the guessed category: search everything
        qs.pop("cat")
        intent = None
        parsed = query.parse(q)
        qs["_parsed"] = parsed
        frm, where, params = build_where(qs)
        total = con.execute(f"SELECT COUNT(*) {frm} WHERE {where}", params).fetchone()[0]
    if total == 0 and parsed["fts"] and parsed["loose"] and parsed["loose"] != parsed["fts"]:
        qs["_fts"] = parsed["loose"]          # no exact match: any of the words, best matches first
        partial = True
        frm, where, params = build_where(qs)
        total = con.execute(f"SELECT COUNT(*) {frm} WHERE {where}", params).fetchone()[0]
    has_rank = bool(qs.get("_fts", parsed["fts"]))
    # every listing matches all the words: cheapest first; partial matches: best match first
    # inside a category every listing matches: cheapest first; free text / partial matches: best match first
    sort_key = one(qs, "sort") or ("price" if (one(qs, "cat") or not has_rank) and not partial else "relevance")
    if sort_key == "relevance" and not has_rank:
        sort_key = "price"
    sort = "f.rank, o.in_stock DESC, o.price" if sort_key == "relevance" else SORTS.get(sort_key, SORTS["price"])
    page = max(1, int(one(qs, "page", "1")))
    size = min(200, int(one(qs, "size", "48")))
    view = one(qs, "view", "offers")
    if view == "models":
        rank_col = ", f.rank AS rank" if has_rank else ", 0 AS rank"
        # one row per model: its cheapest listing (row_number) + price range / store count over the group
        inner = f"""WITH f0 AS (SELECT o.*, s.name AS store_name{rank_col} {frm} WHERE {where}),
                    g AS (SELECT model_key, MIN(price) AS best, MAX(price) AS worst, COUNT(DISTINCT store_id) AS nstores,
                          COUNT(*) AS noffers, MIN(rank) AS mrank FROM f0 GROUP BY model_key),
                    r AS (SELECT f0.*, ROW_NUMBER() OVER (PARTITION BY model_key ORDER BY price, in_stock DESC) AS rn FROM f0)
                    SELECT r.*, g.best, g.worst, g.nstores, g.noffers, g.mrank FROM r JOIN g USING (model_key) WHERE r.rn = 1"""
        total = con.execute(f"SELECT COUNT(*) FROM ({inner})", params).fetchone()[0]
        msort = "mrank, best" if sort_key == "relevance" else sort.replace("o.price", "best").replace("o.", "")
        rows = con.execute(f"SELECT * FROM ({inner}) ORDER BY {msort} LIMIT ? OFFSET ?",
                           params + [size, (page - 1) * size]).fetchall()
        items = [offer_dict(r, ("best", "worst", "nstores", "noffers")) for r in rows]
    else:
        rows = con.execute(f"SELECT o.*, s.name AS store_name {frm} WHERE {where} ORDER BY {sort} LIMIT ? OFFSET ?",
                           params + [size, (page - 1) * size]).fetchall()
        items = [offer_dict(r) for r in rows]
        # how many other stores sell the same model (cheaper?)
        keys = list({i["model_key"] for i in items if i["model_key"]})
        if keys:
            stats = {r[0]: (r[1], r[2]) for r in con.execute(
                f"""SELECT o.model_key, COUNT(DISTINCT o.store_id), MIN(o.price) {FROM}
                    WHERE {ACTIVE} AND o.in_stock = 1 AND o.suspect = 0 AND o.model_key IN ({','.join('?' * len(keys))}) GROUP BY o.model_key""", keys)}
            for i in items:
                n, best = stats.get(i["model_key"], (0, None))
                i["model_stores"], i["model_best"] = n, best

    facets = {}
    cat = one(qs, "cat") or (parsed["filters"].get("cat") or [None])[0]
    for key, label in [("condition", "Condition")] + FACETS.get(cat, []):
        f2, w, p = build_where(qs, skip=key)
        rows = con.execute(f"""SELECT CAST(json_extract(o.specs, '$.{key}') AS TEXT) v, COUNT(*) n {f2}
                               WHERE {w} AND v IS NOT NULL GROUP BY v""", p).fetchall()
        vals = [{"v": r["v"], "n": r["n"]} for r in rows]
        if key in NUMERIC:
            vals.sort(key=lambda x: float(x["v"]) if re.fullmatch(r"[\d.]+", x["v"]) else 0)
        else:
            vals.sort(key=lambda x: -x["n"])
        facets[key] = {"label": label, "values": vals[:60]}
    f2, w, p = build_where(qs, skip="brand")
    brands = [{"v": r[0], "n": r[1]} for r in con.execute(
        f"SELECT o.brand, COUNT(*) n {f2} WHERE {w} AND o.brand != '' GROUP BY o.brand ORDER BY n DESC LIMIT 80", p)]
    f2, w, p = build_where(qs, skip="store")
    stores = [{"id": r[0], "name": r[1], "n": r[2]} for r in con.execute(
        f"SELECT o.store_id, s.name, COUNT(*) n {f2} WHERE {w} GROUP BY o.store_id ORDER BY n DESC", p)]
    # category counts for the current search, ignoring the category itself and its spec filters
    qs2 = {k: v for k, v in qs.items() if k != "cat" and not k.startswith("f_")}
    f2, w, p = build_where(qs2)
    cats = [{"id": r[0], "label": CATEGORIES.get(r[0], r[0]), "n": r[1]} for r in con.execute(
        f"SELECT o.category, COUNT(*) n {f2} WHERE {w} GROUP BY o.category ORDER BY n DESC", p)]
    pr = con.execute(f"SELECT MIN(o.price), MAX(o.price) {frm} WHERE {where}", params).fetchone()
    return {"total": total, "page": page, "size": size, "items": items, "facets": facets, "brands": brands,
            "stores": stores, "categories": cats, "price": {"min": pr[0], "max": pr[1]}, "sort": sort_key,
            "intent": {"cat": intent, "label": CATEGORIES.get(intent)} if intent else None, "partial": partial,
            "corrected": q if fixes else None,
            "auto_specs": {k[2:]: v[0] for k, v in qs.items() if k.startswith("f_")} if intent else {},
            "parsed": {"filters": parsed["filters"], "words": parsed["words"]}}


def offer(con, oid, include_out=False):
    frm = "FROM offers o JOIN stores s ON s.id = o.store_id"
    r = con.execute(f"SELECT o.*, s.name AS store_name, s.last_ok {frm} WHERE o.id = ?", (oid,)).fetchone()
    if not r:
        return None
    d = offer_dict(r)
    d["history"] = [dict(x) for x in con.execute("SELECT day, price, in_stock FROM prices WHERE offer_id=? ORDER BY day", (oid,))]
    stock = "" if include_out else " AND o.in_stock = 1"
    same = [offer_dict(x) for x in con.execute(
        f"SELECT o.*, s.name AS store_name {frm} WHERE {ACTIVE} AND o.model_key = ? ORDER BY o.in_stock DESC, o.price", (r["model_key"],))]
    d["same"] = [x for x in same if include_out or x["in_stock"] or x["id"] == oid]
    d["sold_out_hidden"] = len(same) - len(d["same"])
    d["similar"] = []
    if r["family"]:
        d["similar"] = [offer_dict(x) for x in con.execute(
            f"""SELECT o.*, s.name AS store_name {frm} WHERE {ACTIVE} AND o.in_stock = 1 AND o.suspect = 0 AND o.family = ?
                AND o.model_key != ? ORDER BY o.price LIMIT 24""", (r["family"], r["model_key"]))]
    # model history: cheapest in-stock price per day over every store selling this model
    d["model_history"] = [dict(x) for x in con.execute(
        """SELECT p.day, MIN(p.price) price FROM prices p JOIN offers o ON o.id = p.offer_id
           WHERE o.model_key = ? AND p.in_stock = 1 GROUP BY p.day ORDER BY p.day""", (r["model_key"],))]
    return d


def meta(con):
    frm = "FROM offers o JOIN stores s ON s.id = o.store_id"
    cats = [{"id": r[0], "label": CATEGORIES.get(r[0], r[0]), "n": r[1]} for r in con.execute(
        f"SELECT o.category, COUNT(*) n {frm} WHERE {ACTIVE} AND o.in_stock = 1 GROUP BY o.category ORDER BY n DESC")]
    run = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    totals = con.execute(f"SELECT COUNT(*), COUNT(DISTINCT o.store_id) {frm} WHERE {ACTIVE}").fetchone()
    return {"categories": cats, "labels": CATEGORIES, "groups": GROUPS, "offers": totals[0], "stores": totals[1],
            "last_run": dict(run) if run else None, "facets": {k: [x[1] for x in v] for k, v in FACETS.items()}}


def stores(con):
    rows = con.execute(f"""SELECT s.*, (SELECT COUNT(*) FROM offers o WHERE o.store_id = s.id AND {ACTIVE}) AS active,
                          (SELECT COUNT(*) FROM offers o WHERE o.store_id = s.id AND {ACTIVE} AND o.in_stock = 1) AS in_stock,
                          (SELECT COUNT(*) FROM pages p WHERE p.store_id = s.id AND p.kind = 1) AS pages_known
                          FROM stores s ORDER BY s.enabled DESC, active DESC""").fetchall()
    return [dict(r) for r in rows]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path.startswith("/api/"):
                con = db.connect()
                try:
                    if u.path == "/api/search":
                        return self.send(200, search(con, qs))
                    if u.path == "/api/offer":
                        d = offer(con, int(one(qs, "id", "0")), one(qs, "all") == "1")
                        return self.send(200 if d else 404, d or {"error": "not found"})
                    if u.path == "/api/meta":
                        return self.send(200, meta(con))
                    if u.path == "/api/stores":
                        return self.send(200, stores(con))
                finally:
                    con.close()
                return self.send(404, {"error": "unknown endpoint"})
            path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = (STATIC / path).resolve()
            if STATIC not in f.parents and f != STATIC or not f.is_file():
                f = STATIC / "index.html"
            ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
                     ".png": "image/png", ".ico": "image/x-icon"}.get(f.suffix, "application/octet-stream")
            self.send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        except Exception as e:  # noqa
            self.send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PC Hunt on http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
