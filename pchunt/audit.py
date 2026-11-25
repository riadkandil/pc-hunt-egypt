"""Category audit: compare the final category with the store's own category label (where the store has a specific one).

    python -m pchunt.audit                 # disagreement summary
    python -m pchunt.audit keyboard        # examples involving one category
    python -m pchunt.audit --sample laptop # 40 random products of one category, to eyeball
"""
import random
import sys
from collections import Counter

from . import db
from .classify import category_of, decide, store_category


def main(argv):
    con = db.connect()
    if argv[:1] == ["--sample"]:
        rows = con.execute(f"""SELECT o.title, o.store_cat, o.store_id FROM offers o JOIN stores s ON s.id = o.store_id
                               WHERE {db.ACTIVE} AND o.category = ?""", (argv[1],)).fetchall()
        for r in random.sample(rows, min(40, len(rows))):
            print(f"  {r[0][:90]} | {(r[1] or '')[:40]} | {r[2]}")
        return
    rows = con.execute(f"""SELECT o.title, o.store_cat, o.store_id FROM offers o JOIN stores s ON s.id = o.store_id
                           WHERE {db.ACTIVE}""").fetchall()
    conf, examples = Counter(), {}
    leaf = title_wrong = 0
    for title, sc_txt, sid in rows:
        sc, c = store_category(sc_txt or "")
        if not sc or c != "leaf":
            continue
        leaf += 1
        tc = category_of(title)
        final = decide(tc, (sc, c), title)
        title_wrong += tc != sc
        if final != sc:
            conf[(final, sc)] += 1
            examples.setdefault((final, sc), []).append((title, sc_txt, sid))
    print(f"{len(rows)} live offers; {leaf} carry a specific store category. Title alone disagrees with it on "
          f"{title_wrong} ({100 * title_wrong / max(leaf, 1):.1f} %); final category disagrees on {sum(conf.values())} "
          f"({100 * sum(conf.values()) / max(leaf, 1):.1f} %).")
    focus = argv[0] if argv else None
    for (a, b), n in conf.most_common(40 if not focus else 400):
        if focus and focus not in (a, b):
            continue
        print(f"{n:6}  final={a:12} store={b}")
        for t, sc, sid in examples[(a, b)][:(6 if focus else 2)]:
            print(f"          {t[:85]} | {(sc or '')[:45]} | {sid}")


if __name__ == "__main__":
    main(sys.argv[1:])
