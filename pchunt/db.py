"""SQLite storage: stores, current offers, daily price history."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "pchunt.db"
# an offer is live while its store's latest run (or, for page-by-page crawls, the refresh window) has seen it
ACTIVE = "o.gone = 0 AND o.last_seen >= s.fresh_from"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
  id TEXT PRIMARY KEY, name TEXT, url TEXT, grp TEXT, platform TEXT, adapter TEXT,
  enabled INTEGER, reason TEXT, note TEXT,
  last_run TEXT, last_ok TEXT, status TEXT, error TEXT, n_offers INTEGER, duration REAL
);
CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY, store_id TEXT, ext_id TEXT, url TEXT, title TEXT, brand TEXT, category TEXT,
  specs TEXT, family TEXT, model_key TEXT, image TEXT, price REAL, old_price REAL, in_stock INTEGER,
  seller TEXT, store_cat TEXT, vendor TEXT, first_seen TEXT, last_seen TEXT, price_changed TEXT, prev_price REAL,
  search TEXT, UNIQUE(store_id, ext_id)
);
CREATE INDEX IF NOT EXISTS offers_cat ON offers(category, price);
CREATE INDEX IF NOT EXISTS offers_model ON offers(model_key);
CREATE INDEX IF NOT EXISTS offers_family ON offers(family);
CREATE INDEX IF NOT EXISTS offers_store ON offers(store_id, last_seen);
CREATE TABLE IF NOT EXISTS prices (
  offer_id INTEGER, day TEXT, price REAL, in_stock INTEGER, PRIMARY KEY(offer_id, day)
);
CREATE TABLE IF NOT EXISTS pages (
  store_id TEXT, url TEXT, last_fetch TEXT, kind INTEGER, PRIMARY KEY(store_id, url)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, started TEXT, finished TEXT, stores INTEGER, ok INTEGER, offers INTEGER
);
"""


def connect(path=None):
    p = Path(path or DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(offers)")}
    if "suspect" not in cols:
        con.execute("ALTER TABLE offers ADD COLUMN suspect INTEGER DEFAULT 0")
    if "gone" not in cols:
        con.execute("ALTER TABLE offers ADD COLUMN gone INTEGER DEFAULT 0")
    scols = {r[1] for r in con.execute("PRAGMA table_info(stores)")}
    if "fresh_from" not in scols:
        con.execute("ALTER TABLE stores ADD COLUMN fresh_from TEXT")
        con.execute("UPDATE stores SET fresh_from = last_ok")
    con.commit()
    return con


def rebuild_fts(con):
    """Full-text index over every offer's search text (see query.index_text). Rebuilt after each run (a few seconds)."""
    from .query import index_text
    with con:
        con.execute("DROP TABLE IF EXISTS offers_fts")
        con.execute("CREATE VIRTUAL TABLE offers_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2')")
        con.executemany("INSERT INTO offers_fts(rowid, body) VALUES(?, ?)",
                        ((r[0], index_text(r[1] or "")) for r in con.execute("SELECT id, search FROM offers")))
        con.execute("DROP TABLE IF EXISTS offers_vocab")
        con.execute("CREATE VIRTUAL TABLE offers_vocab USING fts5vocab(offers_fts, 'row')")


def flag_suspects(con, min_offers=4):
    """Mark offers priced far below their family's median: placeholder prices (100 EGP cards), rentals, typos.
    GPU chips and CPU models price tightly (< 35 % of the median is suspicious); broad families (27" monitors,
    32 GB DDR4, 1 TB SSDs) mix used / old stock with new, so only < 10 % counts there."""
    rows = con.execute("""SELECT o.id, o.family, o.price FROM offers o JOIN stores s ON s.id = o.store_id
                          WHERE o.family IS NOT NULL AND {ACTIVE}""".format(ACTIVE=ACTIVE)).fetchall()
    fam = {}
    for r in rows:
        fam.setdefault(r["family"], []).append(r["price"])
    med = {}
    for f, ps in fam.items():
        if len(ps) >= min_offers:
            ps = sorted(ps)
            med[f] = ps[len(ps) // 2]
    def ratio(f):
        return 0.35 if f.startswith(("gpu:", "cpu:")) else 0.10
    bad = [(r["id"],) for r in rows if r["family"] in med and r["price"] < ratio(r["family"]) * med[r["family"]]]
    with con:
        con.execute("UPDATE offers SET suspect = 0 WHERE suspect != 0")
        con.executemany("UPDATE offers SET suspect = 1 WHERE id = ?", bad)
    return len(bad)


def upsert_store(con, s):
    con.execute("""INSERT INTO stores(id, name, url, grp, platform, adapter, enabled, reason, note)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, url=excluded.url, grp=excluded.grp,
                   platform=excluded.platform, adapter=excluded.adapter, enabled=excluded.enabled,
                   reason=excluded.reason, note=excluded.note""",
                (s["id"], s["name"], s["url"], s.get("group"), s.get("platform"), s.get("adapter_name"),
                 int(bool(s.get("enabled", True))), s.get("reason"), s.get("note")))


def save_offers(con, store_id, stamp, day, offers):
    """Insert / update one store's offers from a run (stamp = run start ISO time)."""
    cur = con.cursor()
    changed = 0
    for o in offers:
        row = cur.execute("SELECT id, price FROM offers WHERE store_id=? AND ext_id=?", (store_id, o["ext_id"])).fetchone()
        specs = json.dumps(o["specs"], ensure_ascii=False, sort_keys=True)
        if row:
            oid, old = row["id"], row["price"]
            moved = old is not None and abs(old - o["price"]) >= 0.5
            changed += moved
            cur.execute("""UPDATE offers SET url=?, title=?, brand=?, category=?, specs=?, family=?, model_key=?, image=?,
                           price=?, old_price=?, in_stock=?, seller=?, store_cat=?, vendor=?, last_seen=?, search=?, gone=0,
                           prev_price=CASE WHEN ? THEN ? ELSE prev_price END,
                           price_changed=CASE WHEN ? THEN ? ELSE price_changed END
                           WHERE id=?""",
                        (o["url"], o["title"], o["brand"], o["category"], specs, o["family"], o["model_key"], o["image"],
                         o["price"], o["old_price"], int(o["in_stock"]), o.get("seller") or "", o["store_cat"][:300], (o.get("vendor") or "")[:80],
                         stamp, o["search"], moved, old, moved, day, oid))
        else:
            cur.execute("""INSERT INTO offers(store_id, ext_id, url, title, brand, category, specs, family, model_key,
                           image, price, old_price, in_stock, seller, store_cat, vendor, first_seen, last_seen, search)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (store_id, o["ext_id"], o["url"], o["title"], o["brand"], o["category"], specs, o["family"],
                         o["model_key"], o["image"], o["price"], o["old_price"], int(o["in_stock"]),
                         o.get("seller") or "", o["store_cat"][:300], (o.get("vendor") or "")[:80], day, stamp, o["search"]))
            oid = cur.lastrowid
        cur.execute("INSERT OR REPLACE INTO prices(offer_id, day, price, in_stock) VALUES(?,?,?,?)",
                    (oid, day, o["price"], int(o["in_stock"])))
    return changed
