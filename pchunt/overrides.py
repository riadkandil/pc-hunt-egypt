"""Hand-made per-store settings, merged over the detected ones in stores.json.

adapter: shopify | woocommerce | magento | listing | woo_html | generic (sitemap + product pages)
enabled False + reason: the store is skipped (shown on the Stores page with the reason).
"""

BTECH_CATS = [f"/en/c/laptop-pc/pc-components/{c}" for c in
              ("graphics-cards", "power-supplies", "processors", "motherboards", "ram", "cases",
               "internal-storage", "network-cards")] + [
    "/en/c/laptop-pc/laptops", "/en/c/laptop-pc/pcs", "/en/c/laptop-pc/monitors",
    "/en/c/laptop-pc/external-storage-flash-drives/external-ssd-hdd",
    "/en/c/laptop-pc/laptop-pc-accessories/keyboards", "/en/c/laptop-pc/laptop-pc-accessories/mouse",
    "/en/c/laptop-pc/laptop-pc-accessories/web-cams", "/en/c/laptop-pc/laptop-pc-accessories/pc-speakers",
    "/en/c/gaming-area/gaming-accessories/gaming-headphones", "/en/c/gaming-area/gaming-accessories/gaming-chairs",
    "/en/c/gaming-area/gaming-accessories/gaming-mouses", "/en/c/gaming-area/gaming-accessories/gaming-keyboards",
    "/en/c/gaming-area/gaming-accessories/controllers"]

OVERRIDES = {
    # site search stops at ~1000 results: walk every leaf category, then the plain search for anything uncategorised
    "sigma": {"adapter": "listing", "listing": {"pages_fn": "sigma", "pages": ["/en/search"], "item_url": "/en/item?id={slug}",
                                                "max_pages": 200}},
    # B.TECH renders 20 products per category in the page and loads the rest while scrolling, from an API that needs
    # the page's own token: headless Edge scrolls every leaf category to the end and keeps the page's responses.
    "btech": {"adapter": "browser_listing", "listing": {
        "from_sitemap": r"btech\.com/ar/c/", "rewrite": [r"/ar/c/", "/en/c/"], "leaves_only": True,
        "item_url": "/en/p/{slug}", "image_prefix": "https://media.btech.com/catalogs/",
        "capture": r"discovery/api/v1/products/search", "scrolls": 600, "max_ms": 900000}},
    "zar3store": {"adapter": "listing", "listing": {"pages": ["/"], "item_url": "/store/product/{id}", "max_pages": 2}},
    "elnour-tech": {"adapter": "generic"},
    "hq-store": {"adapter": "strapi", "enabled": True},
    "ultratech": {"enabled": False, "reason": "blocks automated access to every page except the home page (HTTP 403)"},
    "egyptgamestore": {"adapter": "egs", "enabled": True},
    "puzzle-technology": {"adapter": "puzzle", "enabled": True},
    "delta-computer": {"adapter": "delta", "enabled": True},
    "hatly": {"enabled": False, "reason": "answers automated requests with a bot-check page (not worked around)"},
    "quality-egypt": {"adapter": "html_cards", "enabled": True, "cards": {"layout": "odoo", "page_url": "/shop/page/{page}",
                      "layout_override": {"split": r'class="[^"]*\btp-product-item\b'}}},
    "compuscience": {"adapter": "html_cards", "enabled": True, "cards": {"layout": "prestashop", "page_url": "/en/2-home?page={page}"}},
    "elghazawy": {"enabled": False, "reason": "answers automated requests with a bot-check page (not worked around)"},
}
DOWN_REASON = "refuses automated requests (HTTP 403 / bot check) or has a broken TLS certificate; not worked around"
