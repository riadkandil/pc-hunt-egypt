"""Store scrapers. Every adapter yields raw offers:

    {"ext_id", "url", "title", "vendor", "store_cat", "price", "old_price", "in_stock", "image", "sku"}

price / old_price are EGP floats (old_price = price before discount, or None).
"""
import html as htmllib
import json
import time
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

from . import net

MAX_PAGES = 400


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("٬", "").replace("،", "")
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _clean(s):
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- Shopify
def shopify(store, log):
    base = store["url"]
    seen = set()
    for page in range(1, MAX_PAGES):
        j = net.get_json(f"{base}/products.json?limit=250&page={page}")
        prods = j.get("products") or []
        if not prods:
            break
        new = 0
        for p in prods:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            new += 1
            img = (p.get("images") or [{}])[0].get("src") if p.get("images") else None
            # "product type | tags": the type is the store's category, tags are only a weak hint
            cat = f'{p.get("product_type") or ""} | {", ".join(p.get("tags") or [])[:250]}'
            variants = p.get("variants") or []
            multi = len(variants) > 1
            for v in variants:
                price = _num(v.get("price"))
                old = _num(v.get("compare_at_price"))
                title = p["title"]
                vt = v.get("title") or ""
                if multi and vt and vt.lower() != "default title":
                    title = f"{title} - {vt}"
                yield {
                    "ext_id": str(v["id"]) if multi else str(p["id"]),
                    "url": f"{base}/products/{p['handle']}" + (f"?variant={v['id']}" if multi else ""),
                    "title": _clean(title), "vendor": p.get("vendor") or "", "store_cat": cat,
                    "price": price, "old_price": old if old and price and old > price else None,
                    "in_stock": bool(v.get("available")), "image": img, "sku": v.get("sku") or "",
                }
        if new == 0:          # some themes ignore page= and loop forever
            break
        log(f"shopify page {page}: {len(prods)}")


# ---------------------------------------------------------------- WooCommerce Store API
def woocommerce(store, log):
    base = store["url"]
    api = store.get("api") or "/wp-json/wc/store/v1/products"
    sep = "&" if "?" in api else "?"
    total_pages = None
    for page in range(1, MAX_PAGES):
        url = f"{base}{api}{sep}per_page=100&page={page}"
        final, body, headers = net.fetch(url, headers={"Accept": "application/json"})
        if total_pages is None and headers.get("X-WP-TotalPages"):
            total_pages = int(headers["X-WP-TotalPages"])
        try:
            prods = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            break
        if not isinstance(prods, list) or not prods:
            break
        for p in prods:
            pr = p.get("prices") or {}
            div = 10 ** int(pr.get("currency_minor_unit") or 0)
            price = _num(pr.get("price"))
            if (price is None or price == 0) and pr.get("price_range"):
                price = _num(pr["price_range"].get("min_amount"))
            price = price / div if price else None
            reg = _num(pr.get("regular_price"))
            reg = reg / div if reg else None
            cats = ", ".join(c.get("name", "") for c in p.get("categories") or [])
            brands = ", ".join(b.get("name", "") for b in p.get("brands") or []) if isinstance(p.get("brands"), list) else ""
            yield {
                "ext_id": str(p.get("id")), "url": p.get("permalink") or "",
                "title": _clean(p.get("name")), "vendor": _clean(brands), "store_cat": _clean(cats),
                "price": price, "old_price": reg if reg and price and reg > price else None,
                "in_stock": bool(p.get("is_in_stock")) and p.get("is_purchasable", True) is not False,
                "image": ((p.get("images") or [{}])[0] or {}).get("src"), "sku": p.get("sku") or "",
            }
        log(f"woocommerce page {page}/{total_pages}: {len(prods)}")
        if total_pages and page >= total_pages:
            break


# ---------------------------------------------------------------- Magento 2 GraphQL
MAGENTO_Q = """query($p:Int){products(filter:{price:{from:"1"}},pageSize:100,currentPage:$p){
 total_count page_info{total_pages}
 items{ sku name url_key url_suffix stock_status small_image{url} categories{name}
  price_range{minimum_price{final_price{value} regular_price{value}}} } } }"""


def magento(store, log):
    base = store["url"]
    pages = None
    for page in range(1, MAX_PAGES):
        j = net.post_json(base + "/graphql", {"query": MAGENTO_Q, "variables": {"p": page}})
        data = (j.get("data") or {}).get("products") or {}
        pages = pages or (data.get("page_info") or {}).get("total_pages") or 1
        for it in data.get("items") or []:
            mp = (it.get("price_range") or {}).get("minimum_price") or {}
            price = _num((mp.get("final_price") or {}).get("value"))
            reg = _num((mp.get("regular_price") or {}).get("value"))
            yield {
                "ext_id": it.get("sku"), "url": f"{base}/{it.get('url_key')}{it.get('url_suffix') or '.html'}",
                "title": _clean(it.get("name")), "vendor": "",
                "store_cat": ", ".join(c.get("name") or "" for c in it.get("categories") or [])[:300],
                "price": price, "old_price": reg if reg and price and reg > price else None,
                "in_stock": it.get("stock_status") == "IN_STOCK",
                "image": (it.get("small_image") or {}).get("url"), "sku": it.get("sku") or "",
            }
        log(f"magento page {page}/{pages}")
        if page >= pages:
            break


# ---------------------------------------------------------------- generic: sitemap + product page data
PRODUCT_URL = re.compile(r"/(product|products|p|item|shop)/|route=product/product|product_id=|/\d{3,}[-/]|\.html$", re.I)
SKIP_URL = re.compile(r"/(category|categories|collections?|brand|brands|blog|tag|page|pages|news|cart|account)/"
                      r"|\.(jpg|png|webp|pdf)$", re.I)


def _sitemap_urls(url, depth=0, out=None, seen=None):
    out = [] if out is None else out
    seen = set() if seen is None else seen
    if url in seen or depth > 3 or len(seen) > 300:
        return out
    seen.add(url)
    try:
        _, body, _ = net.fetch(url, retries=1)
    except Exception:
        return out
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        import gzip
        body = gzip.decompress(body)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    tag = root.tag.split("}")[-1]
    locs = [e.text.strip() for e in root.iter() if e.tag.split("}")[-1] == "loc" and e.text]
    if tag == "sitemapindex":
        # product sitemaps first; skip obvious non-product ones
        locs.sort(key=lambda u: 0 if "product" in u.lower() else 1)
        for loc in locs:
            if re.search(r"(post|page|categor|tag|author|blog|brand|news|image)[-_s]*\d*\.xml", loc.lower()) \
                    and "product" not in loc.lower():
                continue
            _sitemap_urls(loc, depth + 1, out, seen)
    else:
        out.extend(locs)
    return out


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _avail(v):
    if v is None:
        return None
    s = str(v).lower()
    if any(k in s for k in ("outofstock", "out of stock", "soldout", "sold out", "discontinued")):
        return False
    if any(k in s for k in ("instock", "in stock", "limitedavailability", "preorder", "onlineonly")):
        return True
    return None


# sold-out markers on the product itself (button / stock label), English + Arabic
OUT_RX = re.compile(r'class="[^"]*(?:stock|availability|btn|button|badge|label|status)[^"]*"[^>]*>\s*(?:<[^>]+>\s*){0,3}'
                    r'(?:out of stock|sold out|نفذت الكمية|نفدت الكمية|نفد من المخزون|غير متوفر|غير متاح|unavailable)\s*<', re.I)


def parse_product_page(url, html):
    """Extract one offer from a product page: JSON-LD Product, then og/meta tags, then Next/Nuxt JSON."""
    title = price = old = image = sku = brand = None
    stock = None
    cat = ""
    crumbs = []
    for blob in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(blob.strip().rstrip(";"))
        except ValueError:
            try:
                data = json.loads(re.sub(r"[\x00-\x1f]", " ", blob.strip()))
            except ValueError:
                continue
        for d in _walk(data):
            t = d.get("@type")
            t = " ".join(t) if isinstance(t, list) else str(t or "")
            if "BreadcrumbList" in t and not crumbs:
                names = []
                for it in d.get("itemListElement") or []:
                    if isinstance(it, dict):
                        nm = it.get("name") or (it.get("item") or {}).get("name") if isinstance(it.get("item"), dict) else it.get("name")
                        if nm:
                            names.append(_clean(str(nm)))
                crumbs = names
            if "Product" in t and not title:
                title = d.get("name")
                img = d.get("image")
                image = (img[0] if isinstance(img, list) and img else img)
                if isinstance(image, dict):
                    image = image.get("url")
                sku = d.get("sku") or d.get("mpn")
                b = d.get("brand")
                brand = b.get("name") if isinstance(b, dict) else b
                cat = d.get("category") or ""
                offers = d.get("offers")
                offers = offers if isinstance(offers, list) else [offers] if offers else []
                for o in offers:
                    if not isinstance(o, dict):
                        continue
                    p = _num(o.get("price") or o.get("lowPrice"))
                    if p is None and isinstance(o.get("priceSpecification"), dict):
                        p = _num(o["priceSpecification"].get("price"))
                    if p and (price is None or p < price):
                        price = p
                        stock = _avail(o.get("availability"))
    def meta(prop):
        m = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\']%s["\'][^>]*content=["\']([^"\']*)' % re.escape(prop), html, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name|itemprop)=["\']%s["\']' % re.escape(prop), html, re.I)
        return htmllib.unescape(m.group(1)) if m else None
    if not title:
        title = meta("og:title")
    if price is None:
        price = _num(meta("product:price:amount") or meta("og:price:amount") or meta("price"))
        if stock is None:
            stock = _avail(meta("product:availability") or meta("og:availability") or meta("availability"))
    if price is None:
        m = re.search(r'itemprop=["\']price["\'][^>]*content=["\']([\d.,]+)', html)
        price = _num(m.group(1)) if m else None
    if price is None:
        # Next.js / Nuxt payloads: the first object with a name and a price
        for blob in re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S):
            try:
                data = json.loads(blob)
            except ValueError:
                continue
            for d in _walk(data):
                nm = d.get("name") or d.get("title")
                pv = d.get("price") or d.get("final_price") or d.get("sale_price")
                if isinstance(nm, str) and _num(pv) and len(nm) > 8:
                    title = title or nm
                    price = _num(d.get("sale_price") or d.get("final_price") or pv)
                    reg = _num(d.get("regular_price") or d.get("old_price") or d.get("compare_at_price"))
                    old = reg if reg and reg > price else None
                    q = d.get("quantity", d.get("stock", d.get("in_stock")))
                    if isinstance(q, bool):
                        stock = q
                    elif isinstance(q, (int, float)):
                        stock = q > 0
                    break
            break
    if old is None:
        o = _num(meta("product:original_price:amount") or meta("og:original_price:amount"))
        old = o if o and price and o > price else None
    if not title or not price:
        return None
    if not crumbs:
        nav = re.search(r'<(?:nav|ol|ul|div)[^>]+class="[^"]*breadcrumb[^"]*"[^>]*>(.*?)</(?:nav|ol|ul|div)>', html, re.S | re.I)
        if nav:
            crumbs = [_clean(x) for x in re.findall(r"<a[^>]*>(.*?)</a>", nav.group(1), re.S)]
    crumbs = [c for c in crumbs if c and c.lower() not in ("home", "الرئيسية", "shop", "المتجر") and c != _clean(title)]
    if crumbs:
        cat = " / ".join(crumbs[-4:])
    if stock is None and OUT_RX.search(html):     # only when the structured data says nothing
        stock = False
    if image and image.startswith("//"):
        image = "https:" + image
    return {"ext_id": sku or url, "url": url, "title": _clean(title), "vendor": _clean(brand or ""),
            "store_cat": _clean(cat if isinstance(cat, str) else ""), "price": price, "old_price": old,
            "in_stock": True if stock is None else stock, "image": urljoin(url, image) if image else None,
            "sku": sku or ""}


def product_urls(store, log):
    base = store["url"]
    sm = store.get("sitemap") or "/sitemap.xml"
    urls = _sitemap_urls(base + sm)
    host = urlparse(base).netloc.replace("www.", "")
    urls = [u for u in dict.fromkeys(urls) if host in urlparse(u).netloc and not SKIP_URL.search(u)]
    if store.get("url_filter"):
        rx = re.compile(store["url_filter"], re.I)
        urls = [u for u in urls if rx.search(u)]
    prod = [u for u in urls if PRODUCT_URL.search(u)]
    log(f"sitemap: {len(urls)} urls, {len(prod)} look like products")
    return prod if len(prod) >= 0.2 * len(urls) and prod else urls


def generic(store, log):
    """Every product page from the sitemap. Pages are remembered (store["_pages"]: url -> (last_fetch, kind)), so each
    run fetches new URLs first, then the least recently checked products, until the store's time budget runs out;
    big catalogues are fully refreshed over a few runs. Results per page go to store["_page_cb"](url, kind)
    (kind 1 = product, 0 = no product data, -1 = gone)."""
    import random
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta
    urls = product_urls(store, log)
    known = store.get("_pages") or {}
    cb = store.get("_page_cb") or (lambda u, k: None)
    current = set(urls)
    for u, (_, kind) in known.items():           # products that left the sitemap are gone
        if kind == 1 and u not in current:
            cb(u, -1)
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()
    new = [u for u in urls if u not in known]
    random.Random(7).shuffle(new)                # category pages often come first: shuffle for a fair sample
    prods = sorted((u for u in urls if known.get(u, (None, None))[1] == 1), key=lambda u: known[u][0] or "")
    rest = [u for u in urls if known.get(u, (None, None))[1] in (0, -1) and (known[u][0] or "") < month_ago]
    todo = new + prods + rest
    if not todo:
        return
    conns = store.get("conns", 2)
    for h in {urlparse(store["url"]).netloc, urlparse(todo[0]).netloc}:
        net.set_conns(h, conns)
    deadline = time.time() + store.get("time_budget", 4 * 3600)
    log(f"generic: {len(new)} new, {len(prods)} known products, {len(rest)} rechecks; {conns} connections")
    has_known = any(k == 1 for _, k in known.values())

    def one(u):
        if time.time() > deadline:
            return u, None, "late"
        try:
            final, page = net.text(u, retries=1)
        except net.HttpError as e:
            return u, None, e.code
        except Exception:
            return u, None, "err"
        return u, parse_product_page(final, page), 200

    hits = blocked = done = 0
    with ThreadPoolExecutor(conns) as ex:
        for i in range(0, len(todo), 40):
            chunk = todo[i:i + 40]
            for u, rec, status in ex.map(one, chunk):
                if status == "late":
                    continue
                done += 1
                if status in (404, 410):
                    cb(u, -1)
                elif status in (403, 429):
                    blocked += 1
                elif rec:
                    hits += 1
                    cb(u, 1)
                    rec["ext_id"] = u
                    yield rec
                elif status == 200:
                    cb(u, 0)
            if not has_known and done >= 150 and hits == 0:
                log("no product data on the first 150 pages: giving up")
                return
            if blocked >= 20 and hits == 0:
                log("blocked (HTTP 403/429): giving up")
                return
            if time.time() > deadline:
                log(f"time budget used: {done}/{len(todo)} pages this run")
                return
            if (i // 40) % 10 == 0:
                log(f"generic {done}/{len(todo)} pages, {hits} products")


# ---------------------------------------------------------------- listing pages with embedded JSON (Next.js RSC etc.)
def page_json_blobs(html):
    """All JSON payloads embedded in a page: Next.js app-router flight data, __NEXT_DATA__, JSON-LD."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    if chunks:
        try:
            txt = "".join(json.loads('"' + c + '"') for c in chunks)
        except ValueError:
            txt = ""
        # flight rows look like  `3f:[...]` / `12:{...}`; pull out every top-level JSON value
        for m in re.finditer(r'(?:^|\n)[0-9a-f]+:(?=[\[{])', txt):
            start = m.end()
            obj, end = _scan_json(txt, start)
            if obj is not None:
                yield obj
    for blob in re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S):
        try:
            yield json.loads(blob)
        except ValueError:
            pass
    for blob in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            yield json.loads(blob.strip())
        except ValueError:
            pass


def _scan_json(txt, start):
    try:
        return json.JSONDecoder().raw_decode(txt, start)
    except ValueError:
        return None, start


def _price_of(v):
    """price may be a number, a string or a dict like {final_price, base_price} / {current, base}."""
    if isinstance(v, dict):
        cur = next((_num(v[k]) for k in ("final_price", "current", "sale_price", "special", "amount", "price", "value", "min")
                    if k in v and _num(v[k])), None)
        base = next((_num(v[k]) for k in ("base_price", "base", "regular_price", "old_price", "original") if k in v and _num(v[k])), None)
        return cur, base
    return _num(v), None


def json_products(blobs):
    """Product-like dicts inside JSON values: a name plus a price, and some id/slug."""
    found = {}
    for blob in blobs:
        for d in _walk(blob):
            name = d.get("name") or d.get("title")
            if not isinstance(name, str) or len(name) < 6 or "price" not in d:
                continue
            key = d.get("slug") or d.get("id") or d.get("variant_id") or d.get("sku") or d.get("product_id") or name
            if not isinstance(key, (str, int)):
                continue
            price, base = _price_of(d.get("price"))
            if not price:
                continue
            found[str(key)] = (d, price, base)
    return list(found.values())


def listing_items(html):
    return json_products(page_json_blobs(html))


def listing_offer(d, price, old, cfg, base):
    """One offer from a product dict found in a listing's JSON."""
    slug = d.get(cfg.get("slug_key", "slug")) or d.get("id")
    stock = next((d[k] for k in ("is_in_stock", "is_stock", "in_stock", "available") if k in d), None)
    if isinstance(d.get("stock_status"), str):
        stock = d["stock_status"].lower() in ("in_stock", "instock")
    brand = d.get("brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    img = d.get("thumbnail") or d.get("image") or d.get("thumbnail_url")
    img = img.get("url") if isinstance(img, dict) else img
    if img and cfg.get("image_prefix") and not str(img).startswith("http"):
        img = cfg["image_prefix"] + img
    cats = d.get("categories") or d.get("category") or ""
    if isinstance(cats, dict):
        if "name" in cats:          # {"name": leaf, "parent_category": {...}}
            parent = cats.get("parent_category") or cats.get("parent") or {}
            cats = " / ".join(x for x in [parent.get("name", "") if isinstance(parent, dict) else "", cats["name"]] if x)
        else:                       # {"l1": {...}, "l2": {...}, "l3": {...}}
            cats = " / ".join(str(v.get("name", "")) for v in cats.values() if isinstance(v, dict))
    elif isinstance(cats, list):
        cats = ", ".join(c.get("name", "") if isinstance(c, dict) else str(c) for c in cats)
    seller = d.get("seller_name") or d.get("store_name")
    return {"ext_id": str(d.get("id") or slug), "url": urljoin(base + "/", cfg["item_url"].format(slug=slug, id=d.get("id"))),
            "title": _clean(d.get("name") or d.get("title")), "vendor": _clean(brand or ""),
            "store_cat": _clean(str(cats)), "price": price, "old_price": old if old and old > price else None,
            "in_stock": True if stock is None else bool(stock), "image": img, "sku": d.get("sku") or "",
            "seller": seller or ""}


def sigma_pages():
    """Sigma's search stops after ~1000 results, so walk its leaf categories (public category API)."""
    from urllib.parse import quote
    _, body, _ = net.fetch("https://api.sigma-computer.com/api/stores/v1/categories",
                           headers={"Accept": "application/json", "X-Store-Id": "9d96d97b-d53e-4a6a-a393-68c388b31d9e"})
    out = []

    def walk(cs):
        for c in cs:
            if c.get("subcategories"):
                walk(c["subcategories"])
            else:
                out.append(c["id"])
    walk(json.loads(body)["data"])
    return ["/en/search?filters=" + quote(json.dumps({"category_id": [cid]}, separators=(",", ":"))) for cid in out]


def listing(store, log):
    base = store["url"]
    cfg = store["listing"]
    pages_from = cfg.get("pages") or []
    if cfg.get("pages_fn") == "sigma":
        pages_from = sigma_pages() + pages_from
    if cfg.get("from_sitemap"):
        rx = re.compile(cfg["from_sitemap"])
        pages_from = sorted(u for u in dict.fromkeys(_sitemap_urls(base + (store.get("sitemap") or "/sitemap.xml")))
                            if rx.search(u))
        log(f"listing: {len(pages_from)} category pages")
    seen = set()
    for lp in pages_from:
        lp = urljoin(base + "/", lp)
        lp_seen = set()
        sep = "&" if "?" in lp else "?"
        if cfg.get("queries"):     # no working pagination: one request per query variant (e.g. sort orders)
            urls = [f"{lp}{sep}{q}" if q else lp for q in cfg["queries"]]
        else:
            urls = (lp if page == 1 and not cfg.get("always_page") else f"{lp}{sep}{cfg.get('page_param', 'page')}={page}"
                    for page in range(1, cfg.get("max_pages", 300)))
        for url in urls:
            try:
                _, html = net.text(url, retries=1)
            except Exception as e:
                log(f"listing {url}: {e}")
                break
            items = listing_items(html)
            new = 0
            for d, price, old in items:
                slug = d.get(cfg.get("slug_key", "slug")) or d.get("id")
                ident = str(d.get("id") or slug)
                if ident not in lp_seen:
                    lp_seen.add(ident)
                    new += 1          # new for this listing page set (drives pagination)
                if ident in seen:
                    continue
                seen.add(ident)
                yield listing_offer(d, price, old, cfg, base)
            if not cfg.get("queries") and (not items or new == 0):
                break
        log(f"listing {lp}: {len(seen)} so far")


# ---------------------------------------------------------------- WooCommerce shop pages (Store API closed)
def _woo_cards(html):
    parts = re.split(r'<(?:li|div)[^>]+class="[^"]*\btype-product\b', html)[1:]
    for chunk in parts:
        head = chunk[:400]
        chunk = chunk[:6000]
        m = re.search(r'href="(https?://[^"]+)"', chunk)
        t = re.search(r'class="[^"]*(?:woocommerce-loop-product__title|product-title|product-name|name)[^"]*"[^>]*>(?:\s*<a[^>]*>)?(.*?)</', chunk, re.S) \
            or re.search(r'<h[23][^>]*>(?:\s*<a[^>]*>)?(.*?)</', chunk, re.S)
        pm = re.search(r'<span class="price">(.*?)</span>\s*(?:</span>|<)', chunk, re.S) or re.search(r'class="price"[^>]*>(.*?)</span></span>', chunk, re.S)
        if not (m and t and pm):
            continue
        ptxt = pm.group(1)
        old = re.search(r'<del.*?>(.*?)</del>', ptxt, re.S)
        new = re.search(r'<ins.*?>(.*?)</ins>', ptxt, re.S)
        amounts = [_num(a) for a in re.findall(r'<bdi>(.*?)</bdi>', ptxt, re.S)] or [_num(_clean(ptxt))]
        price = _num(_clean(new.group(1))) if new else (amounts[0] if amounts else None)
        oldp = _num(_clean(old.group(1))) if old else None
        img = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', chunk)
        pid = re.search(r'post-(\d+)', head)
        yield {"ext_id": pid.group(1) if pid else m.group(1), "url": m.group(1), "title": _clean(t.group(1)),
               "vendor": "", "store_cat": " ".join(re.findall(r'product_cat-([a-z0-9-]+)', head))[:200],
               "price": price, "old_price": oldp if oldp and price and oldp > price else None,
               "in_stock": "outofstock" not in head, "image": img.group(1) if img else None, "sku": ""}


def woo_html(store, log):
    base = store["url"]
    shop = store.get("shop_path", "/shop/")
    seen = set()
    for page in range(1, MAX_PAGES):
        url = base + shop if page == 1 else f"{base}{shop.rstrip('/')}/page/{page}/"
        try:
            _, html = net.text(url, retries=1)
        except net.HttpError as e:
            if e.code == 404:
                break
            raise
        cards = list(_woo_cards(html))
        new = [c for c in cards if c["ext_id"] not in seen]
        if not new:
            break
        for c in new:
            seen.add(c["ext_id"])
            yield c
        if page % 10 == 0:
            log(f"woo_html page {page}: {len(seen)}")


# ---------------------------------------------------------------- shop-specific JSON APIs (found by watching their pages)
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def egs(store, log):
    """Egypt Game Store: the site's own search API; "%" matches every product and every digital card."""
    api = "https://api.egyptgamestore.com/api/products/search?search=%25&page={page}"
    for kind, path in (("products", "product"), ("cards", "card")):
        last = None
        page = 1
        while last is None or page <= last:
            j = net.get_json(api.format(page=page))
            block = (j.get("data") or {}).get(kind) or {}
            last = block.get("last_page") or 1
            for it in block.get(kind) or block.get("data") or []:
                price = _num(it.get("price"))
                disc = _num(it.get("price_after_discount"))
                cur = disc if disc and price and disc < price else price
                yield {"ext_id": f"{kind}-{it['id']}", "url": f"https://egyptgamestore.com/{path}/{it['id']}/{_slug(it.get('name'))}",
                       "title": _clean(it.get("name")), "vendor": "", "store_cat": "Gift Cards" if kind == "cards" else "",
                       "price": cur, "old_price": price if cur and price and price > cur else None,
                       "in_stock": (it.get("stock") or 0) > 0 or bool(it.get("is_preorder")),
                       "image": it.get("main_image") or it.get("img"), "sku": it.get("sku") or ""}
            if page % 20 == 0:
                log(f"egs {kind} page {page}/{last}")
            page += 1


def strapi(store, log):
    """Strapi shops (HQ Store): /api/products?populate=*, page by page; product URLs come from the sitemap."""
    base = store["url"]
    urls = {}
    for u in _sitemap_urls(base + "/sitemap.xml"):
        m = re.search(r"pid_([a-z0-9]+)", u)
        if m:
            urls[m.group(1)] = u
    page, count = 1, None
    while count is None or page <= count:
        j = net.get_json(f"{base}/api/products?populate=*&pagination[pageSize]=100&pagination[page]={page}")
        count = ((j.get("meta") or {}).get("pagination") or {}).get("pageCount") or 1
        for it in j.get("data") or []:
            price, orig = _num(it.get("price")), _num(it.get("originalPrice"))
            img = (it.get("image") or [{}])[0] if isinstance(it.get("image"), list) else it.get("image") or {}
            img = img.get("url") if isinstance(img, dict) else None
            cat = it.get("category") or {}
            brand = it.get("brand") or {}
            yield {"ext_id": it.get("documentId") or str(it.get("id")),
                   "url": urls.get(it.get("documentId")) or f"{base}/products/{_slug(it.get('name'))}-pid_{it.get('documentId')}",
                   "title": _clean(it.get("name")), "vendor": brand.get("name", "") if isinstance(brand, dict) else "",
                   "store_cat": cat.get("name", "") if isinstance(cat, dict) else "", "price": price,
                   "old_price": orig if orig and price and orig > price else None,
                   "in_stock": bool(it.get("inStock")) or (it.get("stock") or 0) > 0,
                   "image": urljoin(base + "/", img) if img else None, "sku": ""}
        page += 1


def delta(store, log):
    """Delta Computer (Nuxt shop): api.delta-computer.net/api/products, 100 per page."""
    page, total = 1, None
    while total is None or (page - 1) * 100 < total:
        j = net.get_json(f"https://api.delta-computer.net/api/products?per_page=100&page={page}")
        total = ((j.get("paginate") or {}).get("total")) or 0
        items = j.get("data") or []
        if not items:
            break
        for it in items:
            price = _num(it.get("price"))
            disc = _num(it.get("discounted_price")) if it.get("is_discounted") else None
            cur = disc if disc and price and disc < price else price
            img = it.get("image") or {}
            brand = it.get("brand") or {}
            yield {"ext_id": str(it.get("id")), "url": f"https://delta-computer.net/products/{it.get('slug')}",
                   "title": _clean(it.get("name")), "vendor": brand.get("name", "") if isinstance(brand, dict) else "",
                   "store_cat": "", "price": cur, "old_price": price if cur and price and price > cur else None,
                   "in_stock": (it.get("stock") or 0) > 0,
                   "image": (img.get("full_path_small") or img.get("full_path")) if isinstance(img, dict) else None,
                   "sku": ""}
        page += 1


def puzzle(store, log):
    """Puzzle Technology: its search API ("%" = everything), 100 at a time."""
    start, total = 0, None
    while total is None or start < total:
        j = net.get_json(f"https://puzzle-technology.com/api/search?name=%25&start={start}&end={start + 100}&filters=[]")
        total = j.get("num_products") or 0
        items = j.get("products") or []
        if not items:
            break
        for it in items:
            yield {"ext_id": str(it.get("id")), "url": f"https://puzzle-technology.com/product/{it.get('slug')}",
                   "title": _clean(it.get("title") or it.get("name")), "vendor": "", "store_cat": "",
                   "price": _num(it.get("price")), "old_price": None, "in_stock": (it.get("stock") or 0) > 0,
                   "image": it.get("img1"), "sku": it.get("sku") or ""}
        start += 100


# ---------------------------------------------------------------- product cards in plain HTML listing pages
CARD_LAYOUTS = {
    "prestashop": {"split": r'<article[^>]+class="[^"]*product-miniature',
                   "link": r'product-title"?[^>]*>\s*<a href="([^"#]+)[^"]*"[^>]*>(.*?)</a>',
                   "price": r'<span class="price"[^>]*>(.*?)</span>', "old": r'class="regular-price"[^>]*>(.*?)</span>',
                   "id": r'data-id-product="(\d+)"', "out": r"out-of-stock|product-unavailable|out_of_stock"},
    "odoo": {"split": r'<(?:div|td|form)[^>]+class="[^"]*\boe_product(?:_cart)?\b',
             "link": r'itemprop="name"[^>]*href="([^"?]+)[^"]*"[^>]*content="([^"]+)"',
             "price": r'oe_currency_value">([^<]+)', "id": r'data-product-template-id="(\d+)"',
             "out": r"out of stock|out-of-stock|غير متوفر"},
}


def html_cards(store, log):
    """Category / shop pages whose product cards are plain HTML (PrestaShop, Odoo)."""
    base = store["url"]
    cfg = store["cards"]
    lay = {**CARD_LAYOUTS[cfg["layout"]], **cfg.get("layout_override", {})}
    seen = set()
    for page in range(1, cfg.get("max_pages", 1000)):
        try:
            _, html = net.text(base + cfg["page_url"].format(page=page), retries=1)
        except net.HttpError as e:
            if e.code == 404:
                break
            raise
        new = 0
        for card in re.split(lay["split"], html)[1:]:
            card = card[:8000]
            m = re.search(lay["link"], card, re.S)
            if not m:
                continue
            url, title = urljoin(base + "/", htmllib.unescape(m.group(1))), _clean(m.group(2))
            mid = re.search(lay["id"], card)
            ident = mid.group(1) if mid else url
            if ident in seen:
                continue
            prices = [p for p in (_num(_clean(x)) for x in re.findall(lay["price"], card, re.S)) if p]
            if not prices:
                continue
            old = None
            if lay.get("old"):
                o = re.search(lay["old"], card, re.S)
                old = _num(_clean(o.group(1))) if o else None
            price = min(prices)
            if not old and len(prices) > 1 and max(prices) > price:
                old = max(prices)
            seen.add(ident)
            new += 1
            img = re.search(r'<img[^>]+(?:data-src|data-full-size-image-url|src)="([^"]+)"', card)
            yield {"ext_id": ident, "url": url, "title": title, "vendor": "", "store_cat": "", "price": price,
                   "old_price": old if old and old > price else None,
                   "in_stock": not re.search(lay["out"], card, re.I),
                   "image": urljoin(base + "/", img.group(1)) if img else None, "sku": ""}
        if not new:
            break
        if page % 10 == 0:
            log(f"cards page {page}: {len(seen)}")


# ---------------------------------------------------------------- JavaScript shops: headless Edge (browser.mjs)
BROWSER_JS = __import__("pathlib").Path(__file__).with_name("browser.mjs")
_browser_slots = __import__("threading").BoundedSemaphore(3)      # at most 3 headless browsers at once


def browser_capture(cfg, timeout=900):
    """Run browser.mjs on one page; returns (captured JSON bodies, final DOM or "")."""
    import subprocess
    with _browser_slots:
        p = subprocess.run(["node", str(BROWSER_JS), json.dumps(cfg)], capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    bodies, dom = [], ""
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "dom" in d:
            dom = d["dom"] or ""
        elif "body" in d:
            try:
                bodies.append(json.loads(d["body"]))
            except ValueError:
                pass
    return bodies, dom


def browser_listing(store, log):
    """Category pages that load more products while scrolling (B.TECH): the browser scrolls to the end, the page's
    own product requests are captured, plus the first server-rendered batch from the DOM."""
    base = store["url"]
    cfg = store["listing"]
    pages = list(cfg.get("pages") or [])
    if cfg.get("from_sitemap"):
        rx = re.compile(cfg["from_sitemap"])
        found = [u for u in dict.fromkeys(_sitemap_urls(base + (store.get("sitemap") or "/sitemap.xml"))) if rx.search(u)]
        if cfg.get("rewrite"):
            found = [re.sub(cfg["rewrite"][0], cfg["rewrite"][1], u) for u in found]
        found = list(dict.fromkeys(found))
        if cfg.get("leaves_only"):     # a parent category lists the same products as its children
            found = [u for u in found if not any(o != u and o.startswith(u.rstrip("/") + "/") for o in found)]
        pages += found
    log(f"browser listing: {len(pages)} category pages")
    seen = set()
    for i, lp in enumerate(pages):
        url = urljoin(base + "/", lp)
        try:
            bodies, dom = browser_capture({"url": url, "capture": cfg["capture"], "scrolls": cfg.get("scrolls", 400),
                                           "maxMs": cfg.get("max_ms", 600000), "dom": True, "waitMs": 5000})
        except Exception as e:
            log(f"browser {url}: {e}")
            continue
        items = json_products(bodies) + (listing_items(dom) if dom else [])
        new = 0
        for d, price, old in items:
            o = listing_offer(d, price, old, cfg, base)
            if o["ext_id"] in seen:
                continue
            seen.add(o["ext_id"])
            new += 1
            yield o
        if i % 10 == 0:
            log(f"browser listing {i + 1}/{len(pages)}: {len(seen)} products")


ADAPTERS = {"shopify": shopify, "woocommerce": woocommerce, "magento": magento, "listing": listing,
            "browser_listing": browser_listing, "egs": egs, "strapi": strapi, "delta": delta, "puzzle": puzzle, "html_cards": html_cards,
            "woo_html": woo_html}


def adapter_for(store):
    return ADAPTERS.get(store.get("adapter") or store["platform"], generic)
