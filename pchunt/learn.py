"""Learn categories from the stores that label their products, and apply them to titles the rules cannot place.

Many titles are bare model names ("Lian Li O11 Dynamic Mini", "KZ ZS10 Pro", "MCHOSE Ace 68 v2") that say nothing
about the kind of product, but other stores sell the same names under a category. A multinomial Naive Bayes over title
words (trained on every live offer the rules or the store placed) fills in the "other" ones when it is confident.

    python -m pchunt.learn          # runs after every scrape and reclassify too
"""
import json
import math
import re
from collections import Counter, defaultdict

from . import db
from .classify import condition_of, family_of, model_key, norm, specs_for

MIN_PROB = 0.95          # posterior needed to move an offer out of "other"
SKIP = {"other"}
# a wrong guess into these would pollute the most-used filters (a gym bag among laptops): rules / stores only
NO_LEARN = {"laptop", "desktop", "monitor", "tv", "cpu", "gpu", "motherboard"}


def tokens(title, brand=""):
    t = norm(title)
    words = [w for w in re.findall(r"[a-z0-9؀-ۿ][a-z0-9؀-ۿ.+-]*", t) if len(w) > 1]
    feats = set(words)
    feats.update(f"{a}_{b}" for a, b in zip(words, words[1:]))      # "o11 dynamic", "ace 68"
    if brand:
        feats.add("brand:" + brand)
    return feats


def train(rows):
    doc_count = Counter()
    word_count = defaultdict(Counter)
    vocab = set()
    for title, brand, cat in rows:
        f = tokens(title, brand)
        doc_count[cat] += 1
        word_count[cat].update(f)
        vocab.update(f)
    totals = {c: sum(wc.values()) for c, wc in word_count.items()}
    return doc_count, word_count, totals, len(vocab)


def predict(model, title, brand=""):
    doc_count, word_count, totals, v = model
    n = sum(doc_count.values())
    f = [x for x in tokens(title, brand) if any(x in word_count[c] for c in doc_count)]
    if len(f) < 2:
        return None, 0.0
    scores = {}
    for c, dc in doc_count.items():
        lp = math.log(dc / n)
        wc, tot = word_count[c], totals[c] + v
        for x in f:
            lp += math.log((wc.get(x, 0) + 1) / tot)
        scores[c] = lp
    best = max(scores, key=scores.get)
    m = scores[best]
    z = sum(math.exp(s - m) for s in scores.values())
    return best, 1.0 / z


def apply(con=None, log=print):
    con = con or db.connect()
    live = con.execute(f"""SELECT o.id, o.title, o.brand, o.category FROM offers o JOIN stores s ON s.id = o.store_id
                           WHERE {db.ACTIVE}""").fetchall()
    model = train([(r["title"], r["brand"] or "", r["category"]) for r in live if r["category"] not in SKIP])
    moved = 0
    with con:
        for r in live:
            if r["category"] != "other":
                continue
            cat, p = predict(model, r["title"], r["brand"] or "")
            if cat and p >= MIN_PROB and cat not in NO_LEARN:
                t = norm(r["title"])
                s = specs_for(cat, t, r["brand"] or "")
                s["condition"] = condition_of(t)
                con.execute("UPDATE offers SET category=?, specs=?, family=?, model_key=? WHERE id=?",
                            (cat, json.dumps(s, ensure_ascii=False, sort_keys=True), family_of(cat, s),
                             model_key(cat, r["brand"] or "", s, t), r["id"]))
                moved += 1
    log(f"learned categories for {moved} of {sum(r['category'] == 'other' for r in live)} 'other' offers")
    return moved


if __name__ == "__main__":
    apply()
