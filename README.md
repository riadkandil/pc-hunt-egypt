# PC Hunt Egypt

Scrapes every product of every Egyptian online store on the list once a day (PC parts first, but phones, TVs and
appliances are kept too), sorts each product into a category with its specs, keeps a daily price history, and serves a
search site to find the cheapest offer for anything.

**Live site: https://riadkandil.github.io/pc-hunt-egypt/** (GitHub Pages, updated after each daily scrape)

## Run

| What | Command (from `egypt_pc_stores/`) |
|---|---|
| Website | `python serve.py` then open http://127.0.0.1:8790 |
| Scrape now (all stores) | `python -X utf8 -m pchunt.scrape` |
| Only the fast API stores (~15 min) / only the page-by-page ones | `... -m pchunt.scrape --fast` / `--slow` |
| Some stores | `python -X utf8 -m pchunt.scrape sigma hankerz` |
| Re-detect store platforms | `python -X utf8 -m pchunt.detect` (rewrites `stores.json`) |
| After editing `classify.py` (no network) | `python -X utf8 -m pchunt.reclassify` |
| Category audit (vs the stores' own categories) | `python -X utf8 -m pchunt.audit [category]`, `--sample <category>` |
| Tests | `python -m unittest discover -s tests` |
| Static site (GitHub Pages copy) into `site/` | `python -X utf8 -m pchunt.export_site` |
| Export + publish to GitHub Pages | `python -X utf8 -m pchunt.publish` (force-pushes `site/` as the only commit of `gh-pages`) |
| Daily schedule | `install_schedule.ps1` registers the Windows task **PC Hunt daily scrape** (06:00, runs later if the PC was off). Remove: `Unregister-ScheduledTask -TaskName "PC Hunt daily scrape" -Confirm:$false` |

Logs: `data/logs/<date>.log`. Database: `data/pchunt.db` (SQLite). Python stdlib only; the browser scraper uses
Node (>= 22) and the installed Microsoft Edge (or Chrome) in headless mode.

## Scrapers (`pchunt/adapters.py`, per-store settings in `pchunt/overrides.py`)

| Scraper | Stores | How |
|---|---|---|
| `shopify` | ~27 | `/products.json`, 250 products per request |
| `woocommerce` | ~40 | public Store API `/wp-json/wc/store/v1/products`, 100 per request |
| `magento` | El Araby | GraphQL |
| `listing` | Sigma, Zar3 | product lists embedded in the pages' Next.js data (Sigma: every leaf category, its search stops at ~1000) |
| `browser_listing` | B.TECH | headless Edge (`pchunt/browser.mjs`) scrolls every category to the end and keeps the product data the page itself loads |
| `egs`, `puzzle`, `delta`, `strapi` | Egypt Game Store, Puzzle, Delta Computer, HQ Store | the shops' own JSON APIs (found by watching their pages in the browser) |
| `html_cards` | Compuscience (PrestaShop), Quality (Odoo) | product cards in plain listing pages |
| `generic` | ~20 (2B, Raya, Raneen, Egypt Laptop, Games World, ...) | sitemap -> every product page (JSON-LD, breadcrumbs, meta tags). Pages are remembered: each run fetches new products first, then the least recently checked, within a 4 h budget, so big catalogues (Raneen ~190k pages) are fully refreshed over a few days; products gone from the sitemap or answering 404 are dropped |

Politeness: requests to one site are spaced (0.6 s, 2 connections for page-by-page crawls, slowed down on HTTP 429).
When python.exe cannot connect to a site but curl.exe can (seen on this PC), the request goes through curl.

Skipped (shown with the reason on the Stores page): sites that refuse automated requests or show a bot check
(Ultratech, Hatly, El Ghazawy, Egytech, Brothers, Gamma, Era Tablet, Next Mart) and East Asia (broken TLS certificate);
these blocks are not worked around. Amazon, Jumia and noon are not scraped.

## Categories and specs (`pchunt/classify.py`, `pchunt/learn.py`)

1. The store's own category (breadcrumb, Shopify product type, WooCommerce category) when it is specific.
2. Title rules in English and Arabic: "for PC & laptop" phrases are ignored, accessory words only count in the head
   of the title, phones / tablets / TVs / watches / appliances get their own categories, bundles that name several parts
   are PC builds, real chipset and GPU chip names only.
3. Where both exist they are combined (`decide`): accessories and bundles keep the title's answer, peripherals filed in
   a mixed "keyboard & mouse" section keep the title's answer, otherwise a specific store category wins.
4. Titles that are bare model names ("Lian Li O11 Dynamic") learn their category from the same words in labelled
   listings (Naive Bayes, 95 % confidence, never into laptops / PCs / monitors / CPUs / GPUs / motherboards).

Audit (live data): the final category disagrees with a specific store category on about 2 % of listings, mostly where
the title is more precise (cables and holders filed under the device). Specs per category: GPU chip / VRAM / series,
CPU model / socket / box-tray, chipset / form factor / DDR, RAM kit / speed / CL, SSD capacity / NVMe / PCIe gen,
PSU watts / 80 Plus / modular, monitor size / resolution / Hz / panel, laptop and PC CPU / GPU / RAM / storage, and a
Condition (New / Used / Open box / Refurbished) for everything.

## Static site (`pchunt/export_site.py`, `pchunt/static/local.js`, `pchunt/publish.py`)

GitHub Pages only serves files, so the export writes the live offers as JSON (`data/offers-in-<n>.json` in stock, loaded
first; `data/offers-out-<n>.json` sold out, loaded on demand; 40,000 offers per file, since GitHub refuses files over
100 MB; price history in `data/hist/`) next to the same front end.
`local.js` answers the `/api/*` calls in the browser: the same index text and query language as the FTS5 index, a
bm25-style ranking, filters, facets, spelling fixes and "best price per model". Category intent uses a word list plus a
fallback (most matches in one PC category -> open it). The daily task (`daily_scrape.cmd`) publishes after scraping.

## Search (`pchunt/query.py`, `pchunt/server.py`)

SQLite FTS5 index rebuilt after each run. In the search box:

| Type | Meaning |
|---|---|
| `rtx 5070 ti` | all words; spacing does not matter (`rtx5070ti`, `i5-12400f` = `i5 12400f`); numbers match exactly |
| `"rog strix"` | exact phrase |
| `-laptop` | leave out |
| `ddr5 OR ddr4` | either |
| `brand:asus` `store:sigma` `cat:gpu` | brand / store / category |
| `price<30000` `price:5000-9000` | price range |

A search that names a kind of product opens in that category and turns spec words into filters ("32gb ddr5" = RAM,
32 GB; "850w gold" = power supplies, 850 W; "27 inch 165hz" = monitors). Misspellings are corrected against the
words in the listings ("corsiar vengance" -> "corsair vengeance"). No exact match -> closest matches. Sold-out listings
and suspicious prices (far below the usual price for that chip / model) are hidden unless you ask for them.
