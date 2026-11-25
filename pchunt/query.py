"""Search text: the full-text index body, the query language and category intent.

Query language (search box):
    rtx 5070 ti            all words (prefix match: "5070" also finds "5070ti")
    "rog strix"            exact phrase
    -laptop                exclude a word
    ddr5 OR ddr4           either word
    brand:asus  store:sigma  cat:gpu
    price<30000  price>5000  price:5000-9000  <30000
Spacing variants match each other: "rtx5070" = "rtx 5070", "i5-12400f" = "i5 12400f", Arabic letter variants are folded.
"""
import re

from .classify import CATEGORIES, PC_CATEGORIES, category_of, cpu_model, gpu_chip, norm

AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": None})
TOKEN = re.compile(r"[a-z0-9؀-ۿ]+(?:\.[0-9]+)?")


def fold(s):
    return norm(s).translate(AR_FOLD)


def _parts(tok):
    """'rtx5070ti' -> ['rtx', '5070', 'ti'];  '12400f' -> ['12400', 'f']."""
    return [p for p in re.findall(r"[a-z؀-ۿ]+|[0-9]+(?:\.[0-9]+)?", tok) if p]


def index_text(s):
    """Body for the FTS index: every token, its letter/digit parts, and adjacent tokens glued together."""
    toks = TOKEN.findall(fold(s))
    out = list(toks)
    for t in toks:
        ps = _parts(t)
        if len(ps) > 1:
            out += ps
    for a, b in zip(toks, toks[1:]):
        if len(a) <= 8 and len(b) <= 8 and (a[-1].isdigit() != b[0].isdigit()):
            out.append(a + b)               # "rtx 5070" -> "rtx5070"
    return " ".join(out)


def _p(part):
    # numbers match exactly ("32" must not find "3200"), words by prefix ("logi" finds "logitech")
    return f'"{part}"' if part[0].isdigit() else f'"{part}"*'


def _fts_term(tok):
    ps = _parts(tok)
    if len(ps) == 2 and ps[0][0].isdigit() and not ps[1][0].isdigit():
        return f'("{tok}"* OR "{ps[0]} {ps[1]}"*)'   # "2tb" = "2tb" or "2 tb" side by side, never "m.2 ... tb"
    if len(ps) > 1:                          # query "5070ti" -> 5070 AND ti* (also matches "5070 ti")
        return "(" + " AND ".join(_p(p) for p in ps) + f' OR "{tok}"*)'
    return _p(tok)


# spec words inside a category become exact filters: "32gb" in RAM = capacity 32, "850w" in PSUs = watt 850
SPEC_WORDS = {
    "ram": [(r"\b(\d{1,3}) ?gb\b", "capacity", lambda m: m.group(1))],
    "gpu": [(r"\b(\d{1,2}) ?gb?\b", "vram", lambda m: m.group(1))],
    "ssd": [(r"\b(\d+(?:\.\d)?) ?(tb|gb)\b", "capacity",
             lambda m: str(int(float(m.group(1)) * (1024 if m.group(2) == "tb" else 1))))],
    "hdd": [(r"\b(\d+(?:\.\d)?) ?(tb|gb)\b", "capacity",
             lambda m: str(int(float(m.group(1)) * (1024 if m.group(2) == "tb" else 1))))],
    "psu": [(r"\b(\d{3,4}) ?w(att)?s?\b", "watt", lambda m: m.group(1))],
    "monitor": [(r"\b(\d{2}(?:\.\d)?) ?(\"|inch|in|بوصه)\b", "size", lambda m: str(float(m.group(1)))),
                (r"\b(\d{2,3}) ?hz\b", "hz", lambda m: m.group(1))],
}


def spec_filters(q, cat):
    """-> (query without the spec words, {spec key: value}) for the category's spec words."""
    found = {}
    t = fold(q)
    for rx, key, val in SPEC_WORDS.get(cat, []):
        m = re.search(rx, t)
        if m and key not in found:
            found[key] = val(m)
            t = t[:m.start()] + " " + t[m.end():]
    return re.sub(r"\s+", " ", t).strip(), found


def parse(q):
    """-> dict(fts, loose, filters, words). fts = strict FTS5 expression (None when no words), loose = any-word version."""
    filters = {}
    q = fold(q or "")

    def field(m):
        k, v = m.group(1), m.group(2)
        filters.setdefault(k, []).append(v.strip('"'))
        return " "
    q = re.sub(r"\b(brand|store|cat):(\"[^\"]+\"|\S+)", field, q)

    q = re.sub(r"\bprice ?([<>])=? ?([\d,]+)|(?<![\w.])([<>])=? ?([\d,]+)\b|\bprice:([\d,]+)-([\d,]+)",
               lambda m: price_any(m, filters), q)
    words, parts, loose = [], [], []
    for m in re.finditer(r'(-?)"([^"]+)"|(\S+)', q):
        neg, phrase, w = m.group(1), m.group(2), m.group(3)
        if phrase:
            toks = TOKEN.findall(phrase)
            if toks:
                term = '"' + " ".join(toks) + '"'
                parts.append(("NOT " if neg else "") + term)
                if not neg:
                    words += toks
                    loose.append(term)
            continue
        if w == "or" or w == "OR":
            parts.append("OR")
            continue
        neg = w.startswith("-") and len(w) > 1
        toks = TOKEN.findall(w[1:] if neg else w)
        for t in toks:
            term = _fts_term(t)
            parts.append(("NOT " if neg else "") + term)
            if not neg:
                words.append(t)
                loose.append(term)
    # groups of OR-ed terms, AND-ed together; NOT terms appended at the end (FTS5 NOT is binary: "x NOT y")
    groups, nots, join_next = [], [], False
    for p in parts:
        if p == "OR":
            join_next = bool(groups)
            continue
        if p.startswith("NOT "):
            nots.append(p)
            join_next = False
            continue
        if join_next:
            groups[-1].append(p)
        else:
            groups.append([p])
        join_next = False
    fts = " AND ".join(g[0] if len(g) == 1 else "(" + " OR ".join(g) + ")" for g in groups)
    if fts and nots:
        fts += " " + " ".join(nots)
    return {"fts": fts or None, "loose": " OR ".join(loose) or None, "filters": filters, "words": words}


def price_any(m, filters):
    op1, a1, op2, a2, lo, hi = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
    if lo and hi:
        filters["min"], filters["max"] = float(lo.replace(",", "")), float(hi.replace(",", ""))
    else:
        op, a = (op1, a1) if op1 else (op2, a2)
        a = float(a.replace(",", ""))
        filters["max" if op == "<" else "min"] = a
    return " "


# Generic words that only name the kind of product: once the search is inside that category they are dropped from the
# text match, so "graphics card rtx 5070" also finds titles that just say "RTX 5070 Eagle".
CATEGORY_WORDS = {
    "gpu": r"graphics?|cards?|video|vga|gpu|كارت|كرت|بطاقه|شاشه|رسوميات",
    "cpu": r"processors?|cpu|معالج|بروسيسور",
    "motherboard": r"motherboards?|mainboards?|mobo|board|مازربورد|لوحه|الام",
    "ram": r"ram|memory|desktop|رامات|رام|ذاكره",
    "ssd": r"ssd|internal|solid|state|drive",
    "hdd": r"hdd|hard|disk|drive|internal|هارد",
    "psu": r"power|supply|psu|باور|سبلاي",
    "case": r"case|cases|chassis|pc|كيسه|كيس",
    "cooler": r"cpu|coolers?|cooling|مبرد",
    "fan": r"fans?|case|مراوح",
    "monitor": r"monitors?|screen|display|gaming|شاشه|مونيتور",
    "laptop": r"laptops?|notebooks?|لابتوب|لاب|توب",
    "desktop": r"desktop|pc|computer|build|كمبيوتر|تجميعه",
    "keyboard": r"keyboards?|كيبورد",
    "mouse": r"mouse|mice|ماوس",
    "headset": r"headsets?|headphones?|سماعه",
    "mousepad": r"mouse|pad|mousepad",
    "chair": r"chairs?|كرسي",
}


def strip_category_words(q, cat):
    rx = CATEGORY_WORDS.get(cat)
    if not rx:
        return q
    out = re.sub(r"(?<![\w\"-])(" + rx + r")(?![\w\"])", " ", fold(q))
    return re.sub(r"\s+", " ", out).strip()


def intent(q):
    """The category a search clearly asks for ("logitech keyboard" -> keyboard, "rtx 5070" -> gpu), else None."""
    words = parse(q)["words"]
    if not words:
        return None
    t = " ".join(words)
    c = category_of(t)
    if c in PC_CATEGORIES and c not in ("accessory", "other"):
        return c
    if c in CATEGORIES and c not in ("other", "accessory"):
        return c
    if gpu_chip(t)[0]:
        return "gpu"
    if cpu_model(t)[0] or re.search(r"\b(\d{4}x3d|[3-9]\d{3}x|1[2-4]\d{3}k?f?)\b", t):
        return "cpu"
    return None
