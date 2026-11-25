"""Daily scrape of every enabled store.

    python -m pchunt.scrape                    # all enabled stores
    python -m pchunt.scrape hankerz sigma      # only these
    python -m pchunt.scrape --limit 300        # at most 300 offers per store (quick test)
    python -m pchunt.scrape --workers 12
"""
import argparse
import json
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from . import adapters, db
from .classify import CATEGORIES, classify, norm
from .overrides import DOWN_REASON, OVERRIDES

STORES_JSON = db.ROOT / "stores.json"
MIN_PRICE, MAX_PRICE = 20, 3_000_000      # EGP; placeholder prices (1, 9999999) are dropped
_lock = threading.Lock()


def load_stores():
    out = []
    for s in json.loads(STORES_JSON.read_text(encoding="utf-8")):
        s = {**s, **OVERRIDES.get(s["id"], {})}
        if s.get("platform") == "down" and "enabled" not in OVERRIDES.get(s["id"], {}):
            s["enabled"], s["reason"] = False, DOWN_REASON
        s.setdefault("enabled", True)
        fn = adapters.adapter_for(s)
        s["adapter_name"] = fn.__name__
        out.append(s)
    return out


def prepare(store, raw):
    """classify one store's raw offers (every product is kept; non-PC ones get their own categories)."""
    keep, seen = [], set()
    for r in raw:
        p = r.get("price")
        if not r.get("title") or not p or not (MIN_PRICE <= p <= MAX_PRICE):
            continue
        c = classify(r["title"], r.get("store_cat", ""), r.get("vendor", ""), store["name"])
        ext = str(r.get("ext_id") or r["url"])[:300]
        if ext in seen:
            continue
        seen.add(ext)
        spec_txt = " ".join(str(v) for v in c["specs"].values())
        search = norm(" ".join([r["title"], c["brand"], CATEGORIES[c["category"]], spec_txt, store["name"],
                                r.get("seller") or ""])) + " " + norm(r["title"]).replace(" ", "")
        keep.append({**r, **c, "ext_id": ext, "store_cat": r.get("store_cat") or "", "search": search})
    return keep


STALE_DAYS = 10       # page-by-page stores: an offer stays live this long after its page was last checked


def run_store(store, stamp, day, limit, log):
    t0 = time.time()
    fn = adapters.adapter_for(store)
    rotating = fn.__name__ == "generic"
    pages_done = {}
    if rotating:
        con = db.connect()
        store["_pages"] = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT url, last_fetch, kind FROM pages WHERE store_id=?", (store["id"],))}
        con.close()
        store["_page_cb"] = lambda u, k: pages_done.__setitem__(u, k)
    raw, err = [], None
    n_saved = changed = 0

    def flush():
        nonlocal raw, n_saved, changed
        offers = prepare(store, raw)
        raw = []
        with _lock:
            con = db.connect()
            with con:
                if offers:
                    changed += db.save_offers(con, store["id"], stamp, day, offers)
                if pages_done:
                    con.executemany("INSERT OR REPLACE INTO pages(store_id, url, last_fetch, kind) VALUES(?,?,?,?)",
                                    [(store["id"], u, stamp, k) for u, k in pages_done.items()])
                    gone = [(store["id"], u) for u, k in pages_done.items() if k == -1]
                    con.executemany("UPDATE offers SET gone=1 WHERE store_id=? AND url=?", gone)
                    pages_done.clear()
            con.close()
        n_saved += len(offers)

    try:
        for i, r in enumerate(fn(store, lambda m: log(f"[{store['id']}] {m}"))):
            raw.append(r)
            if rotating and len(raw) >= 500:
                flush()                     # long crawls save as they go
            if limit and i + 1 >= limit:
                break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:500]
        log(f"[{store['id']}] ERROR {err}\n" + traceback.format_exc(limit=3))
    flush()
    dur = time.time() - t0
    ok = n_saved > 0 and (err is None or n_saved > 20)
    fresh = stamp
    if rotating:
        fresh = (datetime.fromisoformat(stamp) - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    with _lock:
        con = db.connect()
        with con:
            con.execute("""UPDATE stores SET last_run=?, status=?, error=?, duration=?,
                           n_offers=CASE WHEN ? THEN ? ELSE n_offers END,
                           last_ok=CASE WHEN ? THEN ? ELSE last_ok END,
                           fresh_from=CASE WHEN ? THEN ? ELSE fresh_from END WHERE id=?""",
                        (stamp, "ok" if ok and not err else "partial" if ok else "error",
                         err or ("" if n_saved else "no offers"), dur, ok, n_saved, ok, stamp, ok, fresh, store["id"]))
        con.close()
    log(f"[{store['id']}] done: {n_saved} offers saved, {changed} price changes, {dur:.0f}s" + (f" ({err})" if err else ""))
    return ok, n_saved


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stores", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--fast", action="store_true", help="skip page-by-page (sitemap) stores")
    ap.add_argument("--slow", action="store_true", help="only page-by-page (sitemap) stores")
    # one thread per store: requests are throttled per host, so stores run side by side without hammering any of them
    ap.add_argument("--workers", type=int, default=64)
    a = ap.parse_args(argv)
    stores = load_stores()
    con = db.connect()
    with con:
        for s in stores:
            db.upsert_store(con, s)
    con.close()
    todo = [s for s in stores if (s["id"] in a.stores if a.stores else s["enabled"])]
    if a.fast:
        todo = [s for s in todo if s["adapter_name"] != "generic"]
    if a.slow:
        todo = [s for s in todo if s["adapter_name"] == "generic"]
    now = datetime.now()
    stamp, day = now.isoformat(timespec="seconds"), now.date().isoformat()
    logdir = db.DATA / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logf = open(logdir / f"{day}.log", "a", encoding="utf-8")

    def log(msg):
        line = f"{datetime.now():%H:%M:%S} {msg}"
        with _lock:
            logf.write(line + "\n")
            logf.flush()
            try:
                print(line, flush=True)
            except UnicodeEncodeError:
                print(line.encode("ascii", "replace").decode(), flush=True)

    log(f"run {stamp}: {len(todo)} stores")
    # slow sitemap crawls first so they overlap with the fast API stores
    todo.sort(key=lambda s: 0 if s["adapter_name"] in ("generic", "listing") else 1)
    ok_n = tot = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(run_store, s, stamp, day, a.limit, log): s for s in todo}
        for f in as_completed(futs):
            ok, n = f.result()
            ok_n += ok
            tot += n
    con = db.connect()
    from . import learn
    learn.apply(con, log)
    log(f"suspicious prices flagged: {db.flag_suspects(con)}")
    db.rebuild_fts(con)
    with con:
        con.execute("INSERT INTO runs(started, finished, stores, ok, offers) VALUES(?,?,?,?,?)",
                    (stamp, datetime.now().isoformat(timespec="seconds"), len(todo), ok_n, tot))
    con.close()
    log(f"run finished: {ok_n}/{len(todo)} stores ok, {tot} offers")
    logf.close()


if __name__ == "__main__":
    main()
