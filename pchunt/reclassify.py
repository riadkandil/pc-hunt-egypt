"""Re-run the classifier over every stored offer (after editing classify.py). No network.

    python -m pchunt.reclassify
"""
import json

from . import db
from .classify import CATEGORIES, classify, norm


def main():
    con = db.connect()
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM stores")}
    rows = con.execute("SELECT id, store_id, title, store_cat, vendor, seller FROM offers").fetchall()
    # classify first, write afterwards in one short transaction (a scrape may be writing at the same time)
    upd = []
    for r in rows:
        c = classify(r["title"], r["store_cat"] or "", r["vendor"] or "", names.get(r["store_id"], ""))
        spec_txt = " ".join(str(v) for v in c["specs"].values())
        search = norm(" ".join([r["title"], c["brand"], CATEGORIES[c["category"]], spec_txt,
                                names.get(r["store_id"], ""), r["seller"] or ""])) + " " + norm(r["title"]).replace(" ", "")
        upd.append((c["category"], c["brand"], json.dumps(c["specs"], ensure_ascii=False, sort_keys=True),
                    c["family"], c["model_key"], search, r["id"]))
    with con:
        con.executemany("UPDATE offers SET category=?, brand=?, specs=?, family=?, model_key=?, search=? WHERE id=?", upd)
    n = len(upd)
    from . import learn
    learn.apply(con)
    print(f"reclassified {n}, suspicious prices {db.flag_suspects(con)}")
    db.rebuild_fts(con)


if __name__ == "__main__":
    main()
