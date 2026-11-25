"""Detect the e-commerce platform of every store and write stores.json.

    python -m pchunt.detect            # all stores from ../egypt_pc_component_stores.csv
    python -m pchunt.detect hankerz.com.eg static-eg.com   # only these (merged into stores.json)
"""
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import net

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "egypt_pc_component_stores.csv"
OUT = ROOT / "stores.json"
SKIP_GROUPS = {"G", "H"}             # classifieds, price-comparison sites
SKIP_SITES = {"amazon.eg", "jumia.com.eg", "noon.com/egypt-en", "carrefouregypt.com", "eshop.vodafone.com.eg"}


def probe_json(url):
    try:
        return net.get_json(url, retries=0, timeout=20)
    except Exception:
        return None


def detect(site):
    base = "https://" + site.strip("/")
    info = {"url": base, "platform": "unknown", "note": ""}
    try:
        final, html = net.text(base + "/", retries=1, timeout=25)
    except Exception as e:
        info["platform"] = "down"
        info["note"] = str(e)[:200]
        return info
    m = re.match(r"(https?://[^/]+)", final)
    if m:
        info["url"] = base = m.group(1)
    low = html.lower()

    if "cdn.shopify.com" in low or "shopify.theme" in low or "myshopify.com" in low:
        j = probe_json(base + "/products.json?limit=1")
        if j and "products" in j:
            info["platform"] = "shopify"
            return info
        info["note"] = "shopify markers but products.json failed"
    if "wp-content" in low or "woocommerce" in low or "wp-json" in low:
        for path in ("/wp-json/wc/store/v1/products?per_page=1", "/wp-json/wc/store/products?per_page=1",
                     "/?rest_route=/wc/store/v1/products&per_page=1"):
            j = probe_json(base + path)
            if isinstance(j, list):
                info["platform"] = "woocommerce"
                info["api"] = path.split("?")[0] if not path.startswith("/?") else "/?rest_route=/wc/store/v1/products"
                return info
        info["note"] = (info["note"] + " wordpress, store api closed").strip()
    if "magento" in low or "mage/cookies" in low or "/static/version" in low or "requirejs-config" in low:
        try:
            j = net.post_json(base + "/graphql", {"query": "{storeConfig{base_currency_code}}"}, retries=0, timeout=20)
            if j.get("data"):
                info["platform"] = "magento"
                return info
        except Exception:
            pass
        info["note"] = (info["note"] + " magento, graphql closed").strip()
    if "salla" in low and "cdn.salla" in low:
        info["platform"] = "salla"
    elif "expandcart" in low:
        info["platform"] = "expandcart"
    elif "route=product/product" in low or "catalog/view/theme" in low or "route=common/home" in low:
        info["platform"] = "opencart"
    elif "youcan" in low:
        info["platform"] = "youcan"
    elif "__next_data__" in low or "/_next/static" in low:
        info["platform"] = "nextjs"
    elif "nuxt" in low:
        info["platform"] = "nuxt"
    elif info["platform"] == "unknown" and ("wp-content" in low):
        info["platform"] = "wordpress"
    elif info["platform"] == "unknown" and "magento" in low:
        info["platform"] = "magento-closed"
    info["jsonld_product"] = '"@type":"product"' in low.replace(" ", "") or '"@type": "product"' in low
    # sitemap presence for the generic crawler
    for sm in ("/sitemap.xml", "/sitemap_index.xml", "/product-sitemap.xml"):
        try:
            _, body = net.text(base + sm, retries=0, timeout=20)
            if "<urlset" in body or "<sitemapindex" in body:
                info["sitemap"] = sm
                break
        except Exception:
            continue
    return info


def load_csv():
    rows = []
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            site = r["website"].strip()
            if not site or site.startswith("(") or r["group"] in SKIP_GROUPS or site in SKIP_SITES:
                continue
            rows.append({"id": (r["qarenly_slug"] or re.sub(r"\W+", "-", r["name"].lower())).replace("_", "-"),
                         "name": r["name"], "site": site, "group": r["group"]})
    return rows


def main(argv):
    rows = load_csv()
    if argv:
        rows = [r for r in rows if r["site"] in argv or r["id"] in argv]
    old = {}
    if OUT.exists():
        old = {s["id"]: s for s in json.loads(OUT.read_text(encoding="utf-8"))}

    def one(r):
        d = detect(r["site"])
        print(f'{r["id"]:22} {d["platform"]:12} {d.get("sitemap", ""):18} {d["note"][:60]}', flush=True)
        return {**r, **d, "enabled": d["platform"] not in ("down",)}

    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(one, rows))
    for s in res:
        prev = old.get(s["id"], {})
        if "enabled" in prev and prev.get("manual"):
            s["enabled"] = prev["enabled"]
        old[s["id"]] = {**prev, **s}
    OUT.write_text(json.dumps(sorted(old.values(), key=lambda s: s["id"]), indent=1, ensure_ascii=False),
                   encoding="utf-8")
    counts = {}
    for s in old.values():
        counts[s["platform"]] = counts.get(s["platform"], 0) + 1
    print(counts)


if __name__ == "__main__":
    main(sys.argv[1:])
