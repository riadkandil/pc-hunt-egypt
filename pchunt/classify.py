"""Product title -> category, brand, specs, family and model key.

category: one of CATEGORIES (None = not a computer product).
specs: dict of filterable values (strings / numbers), keys per category in FACETS.
family: comparable class, e.g. "gpu:RTX 5070" (all cards with that chip) - "compare similar".
model_key: tries to be identical for the same product sold by different stores.
"""
import re
import unicodedata

CATEGORIES = {
    "gpu": "Graphics Cards", "cpu": "Processors", "motherboard": "Motherboards", "ram": "Memory (RAM)",
    "ssd": "SSDs", "hdd": "Hard Drives", "psu": "Power Supplies", "case": "Cases", "cooler": "CPU Coolers",
    "fan": "Case Fans", "thermal": "Thermal Paste & Pads", "monitor": "Monitors", "laptop": "Laptops",
    "desktop": "Desktops & PC Builds", "keyboard": "Keyboards", "mouse": "Mice", "headset": "Headsets & Audio",
    "mousepad": "Mouse Pads", "chair": "Gaming Chairs", "controller": "Controllers", "webcam": "Webcams",
    "microphone": "Microphones", "speaker": "Speakers", "network": "Networking", "ups": "UPS & Power",
    "storage_ext": "External Storage & Flash", "accessory": "PC Accessories & Cables", "printer": "Printers & Ink",
    "software": "Software", "console": "Consoles & Games",
    # not PC parts, kept so every product of every store is searchable
    "phone": "Phones", "tablet": "Tablets", "tv": "TVs", "wearable": "Smart Watches & Wearables",
    "camera": "Cameras & Security", "appliance": "Home & Appliances", "other": "Other",
}
PC_CATEGORIES = [c for c in CATEGORIES if c not in ("phone", "tablet", "tv", "wearable", "camera", "appliance", "other")]

# ---------------------------------------------------------------- the store's own category label -> category
# Matched against each segment of the store's category text (breadcrumb / product type / category list).
STORE_MAP = [
    ("mousepad", r"mouse ?pads?|mousepads?|mouse mats?|desk mats?|ماوس باد"),
    ("accessory", r"laptop (bags?|sleeves?|chargers?|batter(y|ies)|adapters?|stands?|holders?|accessories|screens?|parts?|cooling pads?)|"
                  r"notebook (bags?|accessories)|cables?|adapters?|converters?|hubs?|docking|cooling pads?|gpu (holders?|supports?)"),
    ("ram", r"(laptop|notebook|desktop|pc) (ram|memory)|^(rams?|memory|memories|memory modules?|ram memory|desktop ram)$|رامات|الرامات"),
    ("storage_ext", r"flash( drives?| memory)?|usb (flash|drives?)|memory cards?|sd cards?|external (storage|hard|hdd|ssd|drives?)|portable (ssd|hdd|storage)"),
    ("gpu", r"graphics? cards?|video cards?|^vga$|vga cards?|^gpus?$|كروت ?(ال)?شاشة|كارت شاشة"),
    ("cpu", r"^(processors?|cpus?|cpu processors?|desktop processors?)$|^(intel|amd) (processors?|cpus?)$|المعالجات|معالجات"),
    ("motherboard", r"mother ?boards?|main ?boards?|^mobo$|اللوحات الأم|مازربورد"),
    ("ssd", r"^(internal )?ssds?$|solid state|^m\.?2|nvme|ssd (drives?|nvme|sata)|^ssd"),
    ("hdd", r"(internal )?hard (disks?|drives?)|^hdds?$|surveillance (hdd|drives?)|nas drives?"),
    ("psu", r"power suppl(y|ies)|^psus?$|^power$"),
    ("thermal", r"thermal (paste|compound|pads?)"),
    ("cooler", r"(cpu|liquid|air|water|aio) cool(ers?|ing)|^coolers?$|^cooling$|^coolings?$|liquid"),
    ("fan", r"(case|pc|rgb|argb|cooling) fans?|^fans?$"),
    ("case", r"^(pc |computer |gaming )?cases?$|chassis|pc cases?|computer cases?|cases & towers"),
    ("monitor", r"monitors?|^displays?$|gaming screens?|^screens$|شاشات|الشاشات"),
    ("desktop", r"^(gaming |desktop |custom |ready |prebuilt |pre-built |used |office |home )?(pcs?|desktops?|computers?|"
                r"pc builds?|builds?|bundles?|pc bundles?|workstations?|pc sets?|desktop computers?|towers?)$|"
                r"all[- ]in[- ]ones?|mini pcs?|gaming pcs?$|desktop workstations?$|تجميعات"),
    ("laptop", r"^(gaming |business |used |refurbished )?(laptops?|notebooks?)$|laptops?$|notebooks?$|macbooks?|ultrabooks?|لابتوب"),
    ("keyboard", r"keyboards?|keycaps?|كيبورد|لوحات المفاتيح"),
    ("mouse", r"^(gaming |wireless |wired )?(mouse|mice|mouses)$|gaming mouses?|^mice|ماوس"),
    ("headset", r"headsets?|headphones?|earphones?|ear ?buds|سماعات"),
    ("chair", r"chairs?|كراسي"),
    ("controller", r"controllers?|gamepads?|joysticks?|steering"),
    ("webcam", r"webcams?|web cams?|capture cards?"),
    ("microphone", r"microphones?|^mics?$|مايك"),
    ("speaker", r"speakers?|soundbars?"),
    ("network", r"network(ing)?|routers?|switch(es)?$|access points?|wi-?fi|range extenders?|راوتر"),
    ("ups", r"^ups$|ups & power|uninterruptible"),
    ("printer", r"printers?|ink|toners?|scanners?"),
    ("console", r"consoles?|playstation|xbox|nintendo|video games?|^games$"),
    ("software", r"software|licen[cs]es?|antivirus|operating systems?"),
    ("accessory", r"(mobile|phone|tablet|ipad|tv|camera) (other )?accessor(y|ies)|tv stands?|phone holders?|"
                  r"(mobile|phone|ipad|iphone) cases?|screen protectors?|chargers?"),
    ("appliance", r"^(stand |ceiling |table |desk |wall |tower )?fans?$(?#household fans are filed as Fan)|stand fans?|ceiling fans?"),
    ("phone", r"mobiles?|smart ?phones?|^phones?$|mobile phones?|الموبايل"),
    ("tablet", r"tablets?|ipads?"),
    ("tv", r"\btvs?\b|televisions?|شاشات تلفزيون"),
    ("wearable", r"smart ?watch(es)?|wearables?"),
    ("camera", r"cameras?|cctv|surveillance|security"),
    ("appliance", r"appliances?|kitchen|home|refrigerators?|washing|air condition|personal care"),
]
_STORE_MAP = [(c, re.compile(rx)) for c, rx in STORE_MAP]
BROAD = re.compile(r"^(gaming|accessories|pc accessories|computer accessories|computers?|offers?|sale|new( arrivals?)?|"
                   r"best ?sellers?|hot deals?|pc components|components|hardware|hardware components|electronics|"
                   r"all|products?|shop|store|used|clearance|brands?|uncategori[sz]ed|computers? & laptops?|"
                   r"laptops?, pcs? & accessories|pc & laptops accessories|default)$")


def _segments(store_cat):
    s = norm(store_cat)
    primary = s.split(" | ")[0]                 # shopify: "product type | tags" - tags are too noisy
    return [x.strip() for x in re.split(r"\s*(?:/|>|»|,|;)\s*", primary) if x.strip()]


def store_category(store_cat):
    """(category, confidence) from the store's own labels. confidence "leaf" = a breadcrumb leaf, a product type or a
    single category; "list" = one of several categories the product is filed in (WooCommerce), weaker."""
    s = norm(store_cat or "")
    if not s:
        return None, None
    path = " / " in s.split(" | ")[0] or ">" in s or "»" in s
    segs = [x for x in _segments(s) if not BROAD.match(x) and not x.startswith(("collection:", "__", "brand"))]
    hits = []
    for seg in segs:
        if len(seg) > 60 or re.fullmatch(r"[\d\W]+", seg):
            continue
        if re.search(r"keyboards?", seg) and re.search(r"mouse|mice", seg):
            continue                     # "keyboard & mouse" sections hold both
        cats = [cat for cat, rx in _STORE_MAP if rx.search(seg)]
        if len(set(cats) - {"accessory"}) > 1:
            continue                     # "keyboard & mouse", "hard drives & ssd": ambiguous
        if cats:
            hits.append(cats[0])
    if not hits:
        return None, None
    if path:
        return hits[-1], "leaf"          # deepest breadcrumb segment wins ("PC Accessories / Keyboards")
    if len(set(hits)) == 1:
        return hits[0], ("leaf" if len(segs) <= 1 else "list")
    return None, None                     # filed under contradicting categories


def category_from_store(store_cat):
    return store_category(store_cat)[0]
# Filters shown per category (spec key, label). Order = display order.
FACETS = {
    "gpu": [("chip", "GPU"), ("vram", "VRAM (GB)"), ("chip_maker", "Chip maker"), ("series", "Series")],
    "cpu": [("model", "Model"), ("line", "Line"), ("socket", "Socket"), ("pack", "Box / Tray"), ("igpu", "Graphics")],
    "motherboard": [("chipset", "Chipset"), ("socket", "Socket"), ("form", "Form factor"), ("ddr", "Memory"),
                    ("wifi", "Wi-Fi")],
    "ram": [("ddr", "Type"), ("capacity", "Capacity (GB)"), ("kit", "Kit"), ("speed", "Speed (MHz)"), ("cl", "CL"),
            ("formfactor", "Desktop / Laptop"), ("rgb", "RGB")],
    "ssd": [("capacity", "Capacity (GB)"), ("interface", "Interface"), ("pcie", "PCIe gen"), ("form", "Form factor")],
    "hdd": [("capacity", "Capacity (GB)"), ("rpm", "RPM"), ("use", "Use")],
    "psu": [("watt", "Watts"), ("rating", "80 Plus"), ("modular", "Modular"), ("atx3", "ATX 3.x")],
    "case": [("form", "Form factor"), ("rgb", "RGB")],
    "cooler": [("type", "Type"), ("radiator", "Radiator (mm)"), ("rgb", "RGB")],
    "fan": [("size", "Size (mm)"), ("pack", "Pack"), ("rgb", "RGB")],
    "monitor": [("size", "Size (inch)"), ("resolution", "Resolution"), ("hz", "Refresh (Hz)"), ("panel", "Panel"),
                ("curved", "Curved")],
    "laptop": [("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM (GB)"), ("storage", "Storage (GB)"), ("screen", "Screen")],
    "desktop": [("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM (GB)"), ("storage", "Storage (GB)")],
    "keyboard": [("connection", "Connection"), ("mechanical", "Mechanical")],
    "mouse": [("connection", "Connection")],
    "headset": [("connection", "Connection")],
    "storage_ext": [("capacity", "Capacity (GB)"), ("kind", "Kind")],
    "network": [("kind", "Kind")],
    "ups": [("va", "VA")],
}

BRANDS = [
    "asus", "rog", "msi", "gigabyte", "aorus", "zotac", "pny", "palit", "inno3d", "gainward", "galax", "colorful",
    "sapphire", "powercolor", "xfx", "asrock", "biostar", "intel", "amd", "nvidia", "evga", "afox", "maxsun", "yeston",
    "corsair", "kingston", "g.skill", "gskill", "crucial", "teamgroup", "team group", "t-force", "adata", "xpg", "lexar",
    "samsung", "western digital", "wd", "seagate", "toshiba", "sandisk", "hiksemi", "hikvision", "netac", "kioxia",
    "transcend", "patriot", "silicon power", "apacer", "pioneer", "goodram", "solidigm", "sk hynix", "hp", "dell",
    "lenovo", "acer", "apple", "huawei", "honor", "lg", "benq", "aoc", "viewsonic", "philips", "xiaomi", "redmi",
    "cooler master", "deepcool", "be quiet", "nzxt", "lian li", "thermaltake", "fractal", "phanteks", "montech",
    "arctic", "noctua", "id-cooling", "thermalright", "seasonic", "antec", "fsp", "super flower", "segotep", "gamdias",
    "xigmatek", "darkflash", "1stplayer", "aerocool", "gamemax", "cougar", "silverstone", "jonsbo", "zalman",
    "logitech", "razer", "steelseries", "hyperx", "redragon", "fantech", "havit", "a4tech", "bloody", "marvo", "rapoo",
    "genius", "microsoft", "sony", "jbl", "edifier", "creative", "trust", "attack shark", "ajazz", "aula", "keychron",
    "royal kludge", "tp-link", "tplink", "d-link", "mercusys", "tenda", "ubiquiti", "cisco", "zte", "mikrotik",
    "apc", "eaton", "anker", "ugreen", "baseus", "orico", "thermal grizzly", "gelid", "elgato", "fifine", "boya",
    "t-dagger", "sades", "onikuma", "glorious", "mad catz", "turtle beach", "8bitdo", "playstation", "xbox",
    "nintendo", "titan army", "koorui", "gamepro", "dahua", "uniview", "epson", "canon", "brother", "kaspersky",
    "eset", "pc power", "ocpc", "dragon", "sharkoon", "endorfy", "spirit of gamer", "vertux", "porodo", "msi gaming",
]
_BRAND_FIX = {"rog": "asus", "aorus": "gigabyte", "gskill": "g.skill", "team group": "teamgroup", "t-force": "teamgroup",
              "xpg": "adata", "wd": "western digital", "tplink": "tp-link", "hyperx": "hyperx", "redmi": "xiaomi",
              "msi gaming": "msi", "pc power": "pc power"}
_BRAND_RX = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True))
                       + r")(?![a-z0-9])")

GPU_SERIES = ["rog astral", "rog strix", "astral", "strix", "tuf", "prime", "dual", "proart", "ventus", "shadow",
              "gaming trio", "gaming x", "gaming slim", "inspire", "vanguard", "suprim", "expert", "eagle", "windforce",
              "gaming oc", "aero", "aorus master", "aorus elite", "aorus", "master", "twin edge", "solid", "amp",
              "trinity", "infinity", "twin x2", "x3", "ichill", "gamingpro", "gamerock", "storm x", "jetstream",
              "phoenix", "ghost", "python", "pegasus", "nitro+", "nitro", "pulse", "pure", "hellhound", "red devil",
              "reaper", "fighter", "mercury", "swft", "quicksilver", "challenger", "steel legend", "taichi", "phantom gaming",
              "sakura", "white", "sff", "low profile", "oc", "max", "ice", "verto", "epic-x", "spectral", "vulcan",
              "battle ax", "ex gamer", "1-click oc", "click oc", "jetstream", "gaming"]
_SERIES_RX = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(s) for s in sorted(set(GPU_SERIES), key=len, reverse=True))
                        + r")(?![a-z0-9])")


def norm(s):
    s = (s or "").replace("™", " ").replace("®", " ").replace("©", " ")
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("′′", '"').replace("″", '"').replace("”", '"').replace("“", '"').replace("–", "-").replace("—", "-").replace("×", "x")
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return re.sub(r"\s+", " ", s).strip()


def _has(rx, s):
    return re.search(rx, s) is not None


# ---------------------------------------------------------------- category rules (first match wins)
ACC_WORDS = (r"(cables?|extension cables?|risers?|adapters?|converters?|convert|splitters?|spliter|hubs?|docks?|docking|"
             r"bags?|backpacks?|sleeves?|chargers?|screen protectors?|stands?|holders?|brackets?|sag|cleaning( kit)?|"
             r"covers?|skins?|stickers?|batter(y|ies)(?! life)|keycap pullers?|enclosures?|caddy|kvm|tripods?|light ?bars?|lamps?|"
             r"wrist rests?|card readers?|power banks?|surge protectors?|extension|cooling pads?|laptop coolers?|"
             r"notebook coolers?|extenders?|contact frames?|sealing frames?|backplates?|mounting kits?|\d{2} ?pin|"
             r"replacement (screen|keyboard|battery|fan|hinge)|spare parts?|ports? cover|cases? for|case with keyboard for|"
             r"folio|screen protectors?|tempered glass|glass protector|bags? for|straps?|bands? for|keyboard (covers?|skins?|protectors?)|"
             r"(male|female|type[ -]?c|usb|hdmi|dp|displayport|vga|dvi) (male )?to (vga|hdmi|dp|displayport|dvi|usb|type[ -]?c|rj45|ethernet|lan)|"
             r"iskin|brace|sag holder|gpu support|support bracket|vertical gpu kit|wireview|(silicone?|soft|back|clear|"
             r"leather|printing|phone|mobile|flip) (case|cover)|"
             r"كابل|شاحن|محول|حامل|جراب|وصلة|حافظة|ستاند|لاصقة|اسكرينة)")
ACC_RX = re.compile(r"\b" + ACC_WORDS + r"\b")
FEATURE_CTX = re.compile(r"\b(with|w/|without|no|includes?|including|built-?in|integrated)\b[^,;|]{0,30}$|\+\s*[^,;|]{0,20}$")
# "keyboard for PC & laptop", "fits up to 15.6 inch laptops", "headset for ps5": the device after "for" is not the product
_DEV = (r"(laptops?|notebooks?|pcs?|computers?|macbooks?|desktops?|ps[345]|playstation|xbox|switch|"
        r"iphones?|ipads?|android|tablets?|phones?|mobiles?|consoles?|gaming|mac|windows)")
FOR_RX = re.compile(r"\b(for|compatible with|fits?( up to)?|supports?|works with|designed for)\b[^,;|()]{0,40}?"
                    r"\b" + _DEV + r"\b(\s*(&|and|/|,|or)\s*" + _DEV + r"\b)*")

RULES = [
    ("software", r"\b(windows (10|11) (pro|home)|office 20\d\d|office 365|microsoft 365|antivirus|kaspersky|eset|license key)\b"),
    ("printer", r"\b(printer|toner|ink cartridge|ink bottle|scanner)\b"),
    ("thermal", r"\b(thermal (paste|compound|grease|pad|putty)|thermal ?pads?|liquid metal|kryonaut|hydronaut|mx-?[2-7]\b)"),
    ("keyboard", r"\b(keyboard|keypad|كيبورد)\b.*\b(mouse|ماوس)\b|\b(mouse|ماوس)\b.*\b(keyboard|كيبورد)\b"),   # combos
    ("mousepad", r"\b(mouse ?pad|pad mouse|mousemat|mouse mat|desk ?mat|deskpad|gaming pad|ماوس باد)\b"),
    ("controller", r"\b(controller|gamepad|joystick|steering wheel|racing wheel|dualsense|dualshock|دراع|ذراع تحكم|طارة)\b"),
    ("webcam", r"\b(webcam|web cam|web camera|streamcam|capture card|كاميرا ويب)\b"),
    ("ram", r"\b(sodimm|so-dimm|laptop (memory|ram)|notebook (memory|ram))\b"),
    ("speaker", r"\b(studio monitors?|monitor speakers?)\b"),
    ("laptop", r"\b(laptop|notebook|لابتوب|لاب توب|ماك بوك|ماكبوك|zbook|precision (3|5|7)5\d0|macbook|chromebook|ultrabook|"
               r"vivobook|zenbook|ideapad|thinkpad|thinkbook|legion (5|7|pro|slim)|\bloq\b|yoga (slim|pro|\d)|inspiron|latitude|"
               r"vostro|xps (13|14|15|16)|pavilion|victus|omen (\d|transcend|max)|elitebook|probook|envy x?360|spectre|aspire|"
               r"nitro (v|5|16|lite)|predator helios|swift (go|x|\d)|travelmate|galaxy book|matebook|katana|cyborg|"
               r"thin (gf63|15|a15)|bravo (15|17)|modern (14|15)|prestige (13|14|16)|stealth (14|16|18)|raider|titan (18|gt)|"
               r"vector (16|17)|crosshair (15|16|17)|sword (15|17)|pulse (15|17)|rog (zephyrus|flow)|strix (g|scar) ?1[5-8]|"
               r"tuf (gaming )?(a|f)1[4-8]|expertbook|gaming a1[5-8]|aorus (15|16|17)|g1[5-8] gaming)\b"),
    ("desktop", r"\b(pc build|gaming pc|desktop pc|desktop computer|pc bundle|gaming bundle|bundle|build pc|gaming build|"
                r"gaming desktop(?! (memory|ram))|tower pc|all[- ]in[- ]one (pc|desktop|computer)|aio pc|mini pc|workstation pc|custom pc|pre-?built|gaming rig|"
                r"full pc|assembled pc|pc set|gaming beast|desktop (pc|computer|gaming pc|tower|workstation)|كمبيوتر كامل|"
                r"تجميعة|تجميعه|imac|mac mini|mac studio|mac pro|elitedesk|prodesk|optiplex|thinkcentre|thinkstation|"
                r"workstation|used desktop|pc used|sff pc|\d{2}l desktop)\b"),
    ("monitor", r"(?<!heart rate )(?<!baby )\b(gaming monitor|monitor)\b(?!.*\b(arm|stand|mount|light ?bar|lamp)\b)"),
    ("gpu", r"(كارت|كرت|بطاقة) (شاشة|شاشه|رسوميات)|\bgraphics? card|\bvideo card"),
    ("case", r"\b(case|chassis)\b.*\b(tower|atx|itx|airflow|glass|argb|fans?)\b|\b(mid|full|micro|mini)[- ]?tower\b(?!.*\bcooler\b)"),
    ("motherboard", r"\b(motherboard|mainboard|mobo|مازربورد|ماذربورد|لوحة الام|لوحة أم|لوحه ام)\b|"
                    r"\b(a320|a520|a620|b350|b360|b365|b450|b460|b550|b560|b650e?|b660|b760|b840|b850|b860|h310|h410|h470|h510|"
                    r"h610|h670|h810|x370|x470|x570|x670e?|x870e?|z370|z390|z490|z590|z690|z790|z890|x99|x299|w790|trx50)"
                    r"(m|-m|-i|i|e)?\b(?=.*\b(ddr[45]|wifi|atx|lga|am[45]|gaming|"
                    r"pro|plus|elite|tomahawk|mortar|prime|tuf|aorus|steel|phantom|carbon|edge|ds3h|ud|hdv|-?k|-?p|-?e|-?a)\b)"),
    ("cooler", r"\b(cpu cooler|air cooler|liqu?i?d cool(er|ing)|aio (liquid )?cooler|water cool(er|ing)|aio\b|heatsink|tower cooler|"
               r"cpu fan|ak[46]00|ag[46]00|ls[57]20|le[57]20|hyper 212|masterliquid|kraken|galahad|peerless assassin|"
               r"phantom spirit|liquid freezer|assassin|id-?cooling|frozn|frost commander|aqua elite|مبرد|تبريد مائي)\b"),
    ("cpu", r"\b(ryzen ?[3579]|ryzen threadripper|threadripper|athlon|core ?(i[3579]|ultra ?[3579])|i[3579][- ]\d{4,5}|"
            r"intel ultra ?[3579]|\br[3579] \d{4}|\bci[3579]-\d{4,5}|xeon|pentium|celeron|processor|\bcpu\b|\d{4,5}[kf]{1,2}\b|"
            r"معالج|بروسيسور|بروسيسر)"),
    ("gpu", r"\b(rtx|gtx) ?-?\d{3,4}\b|\bgt ?-?(610|630|640|710|720|730|740|1010|1030)\b|\brtx ?a\d{3,4}\b|\bradeon\b|\brx ?-?\d{3,4}\b|\barc ?[ab]\d{3}\b|"
            r"\bvga\b|\bgpu\b|quadro|geforce|\bgddr[567]x?\b"),
    ("ram", r"\b(ddr[2345]x?|udimm|\bram\b|memory (kit|module)|desktop memory|fury beast|vengeance|trident z|ripjaws|"
            r"lancer|t-create|delta rgb|رامات|رام|ذاكرة)\b"),
    ("storage_ext", r"\b(flash (drive|memory|disk)|usb flash|pen ?drive|memory card|micro ?sd|sd ?card|sdxc|sdhc|"
                    r"external (hard|hdd|ssd|drive)|portable (ssd|hdd|hard|drive)|my passport|t7 shield|\bt7\b|\bt9\b)\b"),
    ("ssd", r"\b(ssd|nvme|solid state|m\.2 ?(2280|ssd|nvme|sata))\b"),
    ("hdd", r"\b(hdd|hard (disk|drive)|\d{4} ?rpm|barracuda|ironwolf|skyhawk|wd (blue|black|purple|red|gold)|surveillance drive|"
            r"nas drive|هارد|قرص صلب)\b"),
    ("psu", r"\b(power supply|\bpsu\b|80 ?\+|80 ?plus|smps|باور سبلاي|باور سبلای|مزود طاقة)\b|"
            r"\b\d{3,4} ?w(att)?\b.*\b(bronze|gold|platinum|titanium|modular)\b|\b(bronze|gold|platinum|titanium)\b.*\b\d{3,4} ?w\b|\bmwe\b"),
    ("fan", r"\b((case|argb|rgb|pwm|cooling|chassis|pc|reverse|silent) fans?|fans? (kit|pack|hub)|(80|92|120|140|200) ?mm fans?|"
            r"\d ?(in ?1|pack|pcs?) fans?|fans? \d ?(in ?1|pack)|مراوح|مروحة كيس)\b"),
    ("monitor", r"\b(display|ultragear|odyssey|ultrawide|مونيتور|شاشة (جيمنج|كمبيوتر|ألعاب|العاب)|شاشة)\b|"
                r"\b\d{2}(\.\d)? ?(\"|inch|''|in\b).*\b(\d{2,3} ?hz|ips|fhd|qhd|uhd|4k)\b"),
    ("case", r"\b(pc case|computer case|gaming case|tower case|mid[- ]?tower|full[- ]?tower|mini[- ]?tower|micro[- ]?atx case|"
             r"matx case|atx case|itx case|chassis|case|كيسة|كيس)\b"),
    ("ups", r"\b(ups|uninterruptible|online ups|line interactive)\b|\b\d{3,4} ?va\b"),
    ("headset", r"\b(headset|headphones?|earbuds?|earphones?|airpods|ear ?buds|سماعة|سماعه|هيدسيت)\b"),
    ("mouse", r"\b(mouse|mice|ماوس|فأرة)\b"),
    ("keyboard", r"\b(keyboard|keypad|keycaps?|كيبورد|لوحة مفاتيح)\b"),
    ("microphone", r"\b(microphone|\bmic\b|condenser|مايك|ميكروفون)\b"),
    ("chair", r"\b(gaming chair|office chair|chair|كرسي)\b"),
    ("speaker", r"\b(speakers?|soundbar|subwoofer|سبيكر|مكبر صوت|مكبرات صوت|نظام صوت|ساوند بار)\b"),
    ("network", r"\b(router|access point|mesh|wi-?fi adapter|wireless adapter|usb adapter wifi|network card|lan card|"
                r"ethernet|network switch|poe|range extender|repeater|powerline|nano usb|wifi card|bluetooth adapter|راوتر)\b"),
    ("console", r"\b(playstation|ps[45] (slim|pro|console|digital)|ps5|ps4|xbox series|nintendo switch|steam deck|rog ally|"
                r"legion go|psn card|gift card|ps5 game|ps4 game|video game)\b"),
    ("fan", r"\b(fans?)\b"),
]
_RULES = [(c, re.compile(rx)) for c, rx in RULES]

# Not PC parts. Checked before the PC rules (phones list "12GB + 512GB", kitchen gear says "food processor").
NONPC_STRONG = [
    ("phone", r"\b(dual sim|esim|\d{1,2} ?gb ?\+ ?\d{2,4} ?gb|snapdragon 8|pixel \d|oneplus|xiaomi \d|redmi|poco [a-z]\d|"
              r"galaxy (z|s\d|a\d|m\d|f\d|c\d|j\d|note)|iphone|smartphone|smart phone|mobile phone|feature phone|nothing phone|"
              r"oppo|realme|vivo|infinix|tecno|nokia|honor (x|magic|\d)|ثنائي الشريحة|شريحتين|جالاكسي|ريدمي|شاومي|شاومى|"
              r"نوفا|موبايل|هاتف|نوكيا|ايفون|آيفون|dimensity|helio g\d+|exynos|cmf phone|"
              r"(honor|oppo|vivo|realme|infinix|tecno|xiaomi|samsung|motorola|zte|huawei)\b.{0,30}\b\d{1,2} ?gb ram\b)\b"),
    ("tablet", r"\b(ipad|matepad|galaxy tab|tab (a|s|m|p)\d+|tab \d+ (gen|pro|plus)|redmi pad|xiaomi pad|xpad|"
               r"tablet|تابلت|ميت باد)\b"),
    ("wearable", r"\b(apple watch|smart ?watch|watch (fit|series|gt|ultra|\d)|fitness band|smart band|smart glasses|"
                 r"galaxy watch|(xiaomi|huawei|amazfit|honor|redmi) watch|watch (s\d|active|band)|ساعة ذكية)\b"),
    ("tv", r"\b(smart tv|led tv|qled tv|oled tv|android tv|google tv|\d{2} ?(inch|\")? (smart |uhd |4k |qled |oled )*tv|"
           r"television|chromecast|apple tv|\d{2,3} ?(\"|inch)?.{0,30}\b(smart|4k|uhd|qled|led|frameless)\b.{0,20}\btv\b|"
           r"\btv-|شاشة تلفزيون|تلفزيون|تليفزيون|سمارت|ريسيفر)\b"),
    ("camera", r"\b(security camera|cctv|dvr|nvr|ip camera|dash ?cam|action camera|gopro|osmo|stabilizer|gimbal|"
               r"fire alarm|كاميرا مراقبة)\b"),
    ("appliance", r"\b(food processor|pressure cooker|refrigerator|fridge|washing machine|air conditioner|microwave|oven|"
                  r"blender|vacuum|cooker|heater|kettle|steam iron|shaver|trimmer|hair dryer|air fryer|toaster|"
                  r"water dispenser|dishwasher|freezer|stove|diffuser|perfume|(stand|ceiling|table|desk|wall|tower|rechargeable) fan|"
                  r"\d{2} ?(\"|inch) fan|fan \d{2} ?(\"|inch)|\d blades|محضر طعام|مفرمة|حلة|زبادي|ماكينة|خلاط|"
                  r"غسالة|ثلاجة|ثلاجه|مكنسة|قطاعة|فرشاة|مكواة|سيشوار|ميكروويف|سخان|غلاية|بوتجاز|فرن|قلاية|تكييف|مكيف|"
                  r"موقد|مروحة سقف|مروحة حامل|دفاية|كشاف|مصباح|لمبة)\b"),
]
_NONPC = [(c, re.compile(rx)) for c, rx in NONPC_STRONG]
COMPONENT_CATS = ("motherboard", "gpu", "cpu", "ram", "ssd", "hdd", "psu", "case", "cooler")
MOBILE_CPU = re.compile(r"\b(i[3579]-?\d{4,5}(h|hx|hs|u|p|g\d)|core (ultra )?[3579] \d{3}[hvu]|ryzen [3579] \d{4}(h|hs|hx|u)|"
                        r"ryzen ai|apple m[1-9]|snapdragon x)\b")
PC_WORDS = re.compile(r"\b(laptop|notebook|monitor|graphics card|rtx \d{4}|keyboard|mouse|ssd)\b")
OTHER_DEVICE = re.compile(r"\b(buds|earbuds|earphones?|headsets?|headphones?|watch|band|speakers?|power ?bank|router|"
                          r"tablet|pad|xpad|tab|سماعة|ساعة)\b")


def _signals(t):
    """How many different PC parts a title names (a bundle / full build names several)."""
    n = 0
    n += bool(gpu_chip(t)[0])
    n += bool(cpu_model(t)[0] or re.search(r"\b(\d{4}x3d|[3-9]\d{3}x|1[2-4]\d{3}k?f?|ultra [579] \d{3}k?f?)\b", t))
    n += bool(_CHIPSET_RX.search(t))
    n += bool(re.search(r"\b\d{1,3} ?gb\b.*\b(ddr[45]|ram)\b|\bkit\b.*\bddr|\d ?x ?\d{1,2} ?gb|\d{1,3} ?gb kit", t))
    n += bool(re.search(r"\b(ssd|nvme)\b", t))
    return n


# whole products whose titles list accessory-like features ("Tempered Glass Mid Tower Case with Riser Cable",
# "27 Inch 165Hz KVM Monitor", "Wi-Fi Range Extender")
WHOLE_PRODUCT = re.compile(r"\b((mid|full|mini|micro|super)[ -]?tower|(pc|computer|gaming|atx|itx) (gaming )?case|chassis)\b(?! (fans?|cables?|stands?|feet|for))"
                           r"|\b\d{2}(\.\d)? ?(inch|\")?.{0,60}\b\d{2,3} ?hz\b.{0,80}\bmonitor\b|\bmonitor\b.{0,60}\b\d{2,3} ?hz\b"
                           r"|\b(range extender|wi-?fi( \d)? (range )?extender|mesh wi-?fi|powerline|media converter)\b")


def _is_accessory(t):
    """An accessory word that names the product itself (not "case with fan hub", "laptop with charger"): only the head
    of the title counts (before the first comma / dash / bracket, where long titles list features)."""
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    if WHOLE_PRODUCT.search(t) and not re.search(r"\b(cases? for|for (pc )?cases?|replacement)\b", t):
        return False
    t = re.split(r"\s[-|–]\s|,|\s\|\s", t, maxsplit=1)[0]
    for m in ACC_RX.finditer(t):
        if not FEATURE_CTX.search(t[:m.start()]):
            return True
    return False


def category_of(title, store_cat=""):
    """Category from the title alone."""
    t = norm(title).replace("cooler master", "coolermaster").replace("be quiet!", "bequiet")
    core = FOR_RX.sub(" ", t)                  # "keyboard for pc & laptop" -> "keyboard"
    acc = _is_accessory(t)                     # on the full title: "case for iphone" is an accessory
    if acc and not re.search(r"\b(rtx|gtx|ryzen|core i\d|ultra [579]|mouse ?pad|desk ?mat|thermal)\b", core):
        return "accessory"                     # "Infinix wall charger", "iPad folio case", "كابل شحن"
    for cat, rx in _NONPC:
        if rx.search(t) and not PC_WORDS.search(t):
            if cat == "phone" and OTHER_DEVICE.search(t):
                continue                       # "Infinix XBUDS", "Xiaomi Watch", "Infinix XPAD"
            return cat
    if re.match(r"(pc |gaming |computer )?(case|chassis|كيسة|كيس)\b", core) or \
            re.search(r"\bcase\b.*\b(without|no|\+|with) ?(power supply|psu)\b", core):
        return "case"
    if MOBILE_CPU.search(core) and re.search(r"\b1[0-8](\.\d)? ?(\"|inch|''|-inch)|\bfhd\b|\b\d{1,2} ?gb\b", core) \
            and not re.search(r"\b(desktop|tower|mini pc|aio|all[- ]in[- ]one|nuc)\b", core) and not acc:
        return "laptop"
    for cat, rx in _RULES:
        if rx.search(core):
            if acc and cat not in ("software", "printer", "thermal", "controller", "webcam", "headset", "speaker",
                                   "microphone", "chair", "console", "network", "ups"):
                # "laptop bag", "vga cable", "ssd enclosure", "monitor stand", "gpu holder"...
                if not (cat in ("laptop", "desktop") and re.search(r"\b(rtx|gtx|ryzen|core|i[3579]|ultra)\b", core)):
                    return "accessory"
            if cat in COMPONENT_CATS and _signals(core) >= 3:
                return "desktop"           # "9700X + B650 + 32GB DDR5 + RTX 5070" style bundle titles
            return cat
    if acc:
        return "accessory"
    return "other"


NON_PC = ("phone", "tablet", "tv", "wearable", "camera", "appliance")
PERIPHERALS = ("keyboard", "mouse", "mousepad", "headset", "speaker", "microphone", "webcam", "controller", "chair")


def decide(title_cat, store, title=""):
    """Combine the title category with the store's own category (store = (category, confidence))."""
    sc, conf = store
    if not sc or sc == title_cat:
        return title_cat
    if title_cat == "other":
        return sc
    if title_cat == "thermal":
        return "thermal"
    if title_cat in PERIPHERALS and sc in PERIPHERALS:
        return title_cat              # shops file mice under "Keyboards", pads under "Mouse"...
    if title_cat == "accessory" and sc == "network" and conf == "leaf":
        return "network"              # USB Wi-Fi adapters, network cables, media converters in a networking section
    if title_cat == "accessory" and sc not in NON_PC:
        return "accessory"            # "GPU support bracket" filed under "Graphic Cards & Accessories"
    if title_cat == "desktop" and sc in COMPONENT_CATS and _signals(norm(title)) >= 3:
        return "desktop"              # bundles filed under one of their parts
    if sc in NON_PC and conf != "leaf" and title_cat not in NON_PC:
        return title_cat              # filed under several categories, one of them "Mobiles"
    if conf == "leaf":
        return sc
    return title_cat


# ---------------------------------------------------------------- spec extractors
def _gb(num, unit):
    v = float(num)
    return int(v * 1024) if unit.lower().startswith("t") else int(v)


def _cap(t, lo=16):
    """largest storage-like capacity mentioned (GB)."""
    caps = [_gb(n, u) for n, u in re.findall(r"(\d+(?:\.\d+)?)\s?(tb|gb)\b", t)]
    caps = [c for c in caps if c >= lo]
    return max(caps) if caps else None


GPU_CHIP = re.compile(r"\b(rtx|gtx|gt(?=\s?-?\s?(?:610|630|640|710|720|730|740|1010|1030)\b))\s?-?\s?(\d{3,4})\s?(ti\s?super|ti|super)?\b|\b(rx)\s?-?\s?(\d{3,4})\s?(xtx|xt|gre)?\b|"
                      r"\barc\s?([ab]\d{3})\b|\brtx\s?(a\d{3,4}|pro \d{4})\b")


def gpu_chip(t):
    m = GPU_CHIP.search(t)
    if not m:
        return None, None
    if m.group(1):
        suf = (m.group(3) or "").replace(" ", "")
        suf = {"ti": " Ti", "super": " Super", "tisuper": " Ti Super"}.get(suf, "")
        return f"{m.group(1).upper()} {m.group(2)}{suf}", "NVIDIA"
    if m.group(4):
        return f"RX {m.group(5)}" + (f" {m.group(6).upper()}" if m.group(6) else ""), "AMD"
    if m.group(7):
        return f"Arc {m.group(7).upper()}", "Intel"
    return f"RTX {m.group(8).upper()}", "NVIDIA"


def cpu_model(t):
    m = re.search(r"(?:core|intel)\s?ultra\s?([3579])(?:\s?-?\s?|(?:\s[a-z]+){1,3}\s(?:-\s)?)(\d{3})([a-z]{0,2})\b", t)
    if m:
        return f"Core Ultra {m.group(1)} {m.group(2)}{m.group(3).upper()}", "Core Ultra", "Intel"
    m = re.search(r"\b(?:core\s?|c)?(i[3579])(?:\s?-?\s?|\s(?:processor|cpu)\s)(\d{4,5})([a-z]{0,2})\b", t)
    if m:
        return f"Core {m.group(1)}-{m.group(2)}{m.group(3).upper()}", f"Core {m.group(1)}", "Intel"
    m = re.search(r"(?:ryzen\s?|\br)([3579])\s?(?:pro\s?)?-?\s?(\d{4})\s?(x3d2?|xt|x|g|ge|gt|f|hs|hx|h|u)?\b", t)
    if m:
        return f"Ryzen {m.group(1)} {m.group(2)}{(m.group(3) or '').upper()}", f"Ryzen {m.group(1)}", "AMD"
    m = re.search(r"threadripper\s?(?:pro\s?)?(\d{4}[a-z]{0,2})", t)
    if m:
        return f"Threadripper {m.group(1).upper()}", "Threadripper", "AMD"
    m = re.search(r"\b(athlon|pentium|celeron|xeon)\s?((?:e[357]|w|silver|gold|platinum|bronze|[a-z])?[\s-]?\d{3,5}[a-z]{0,2}(?:\s?v\d)?)", t)
    if m:
        return f"{m.group(1).title()} {m.group(2).upper().replace(' ', '')}", m.group(1).title(), \
            "AMD" if m.group(1) == "athlon" else "Intel"
    m = re.search(r"\bapple\s?(m[1-9])\s?(pro|max|ultra)?\b|\b(m[1-9])\s?(pro|max)?\s?chip\b", t)
    if m:
        chip = (m.group(1) or m.group(3)).upper() + (f" {(m.group(2) or m.group(4)).title()}" if (m.group(2) or m.group(4)) else "")
        return f"Apple {chip}", "Apple", "Apple"
    m = re.search(r"snapdragon\s?(x\s?(?:elite|plus)?(?:\s?x\d-\d{2}-\d{3})?)", t)
    if m:
        return f"Snapdragon {m.group(1).title()}", "Snapdragon", "Qualcomm"
    return None, None, None


def cpu_socket(model):
    if not model:
        return None
    m = re.match(r"Core Ultra \d (\d)\d\d", model)
    if m:
        return "LGA1851" if m.group(1) == "2" else None
    m = re.match(r"Core i\d-(\d{4,5})", model)
    if m:
        n = m.group(1)
        gen = int(n[:2]) if len(n) == 5 else int(n[0])
        return {12: "LGA1700", 13: "LGA1700", 14: "LGA1700", 10: "LGA1200", 11: "LGA1200"}.get(gen, "LGA1151" if gen in (6, 7, 8, 9) else None)
    m = re.match(r"Ryzen \d (\d)(\d)\d\d(\w*)", model)
    if m:
        series, suf = int(m.group(1)), m.group(3)
        if suf in ("HS", "HX", "H", "U"):
            return None
        if series in (1, 2, 3, 4, 5):
            return "AM4"
        if series in (7, 8, 9):
            return "AM5"
    return None


CHIPSET_SOCKET = {"a320": "AM4", "a520": "AM4", "b350": "AM4", "b450": "AM4", "b550": "AM4", "x370": "AM4", "x470": "AM4",
                  "x570": "AM4", "a620": "AM5", "b650": "AM5", "b650e": "AM5", "b840": "AM5", "b850": "AM5", "x670": "AM5",
                  "x670e": "AM5", "x870": "AM5", "x870e": "AM5", "h610": "LGA1700", "b660": "LGA1700", "h670": "LGA1700",
                  "z690": "LGA1700", "b760": "LGA1700", "z790": "LGA1700", "h810": "LGA1851", "b860": "LGA1851",
                  "z890": "LGA1851", "h410": "LGA1200", "b460": "LGA1200", "h470": "LGA1200", "z490": "LGA1200",
                  "h510": "LGA1200", "b560": "LGA1200", "z590": "LGA1200", "h310": "LGA1151", "b360": "LGA1151",
                  "b365": "LGA1151", "z370": "LGA1151", "z390": "LGA1151", "x299": "LGA2066", "w790": "LGA4677",
                  "trx50": "sTR5", "x99": "LGA2011-3", "h81": "LGA1150", "h61": "LGA1155", "b75": "LGA1155"}
_CHIPSET_RX = re.compile(r"(?<![a-z0-9])(" + "|".join(sorted(CHIPSET_SOCKET, key=len, reverse=True)) + r")(m|-m|-i|i|-e|e)?(?![0-9])")


def _form(t):
    if re.search(r"\be-?atx\b", t):
        return "E-ATX"
    if re.search(r"\b(mini[- ]?itx|itx)\b", t):
        return "Mini-ITX"
    if re.search(r"\b(micro[- ]?atx|m-?atx|matx)\b", t):
        return "Micro-ATX"
    if re.search(r"\batx\b", t):
        return "ATX"
    return None


def _rgb(t):
    return "Yes" if re.search(r"\ba?rgb\b", t) else "No"


def _wireless(t):
    if re.search(r"\b(wireless|bluetooth|2\.4 ?g|tri-?mode|dual[- ]mode|lightspeed|hyperspeed)\b", t):
        return "Wireless"
    return "Wired"


def specs_for(cat, t, brand):
    s = {}
    if cat == "gpu":
        chip, maker = gpu_chip(t)
        if chip:
            s["chip"], s["chip_maker"] = chip, maker
        m = re.search(r"(\d{1,2})\s?g(?:b)?\s?(?:g?ddr\d x?)?(?![a-z0-9])", t) or re.search(r"(\d{1,2}) ?gb", t)
        vr = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,2})\s?g(?:b|d)?\b", t) if int(x) in (2, 3, 4, 6, 8, 10, 11, 12, 16, 20, 24, 32, 48)]
        if vr:
            s["vram"] = vr[0]
        elif m and int(m.group(1)) in (2, 3, 4, 6, 8, 10, 11, 12, 16, 20, 24, 32, 48):
            s["vram"] = int(m.group(1))
        ser = [x for x in dict.fromkeys(_SERIES_RX.findall(t)) if x not in ("gaming", "oc", "white", "max", "ice", "sff")]
        if ser:
            s["series"] = ser[0].title().replace("Rog", "ROG").replace("Tuf", "TUF").replace("Amp", "AMP")
    elif cat == "cpu":
        model, line, maker = cpu_model(t)
        if model:
            s["model"], s["line"] = model, line
            sock = cpu_socket(model)
            if sock:
                s["socket"] = sock
            if maker == "AMD":
                s["igpu"] = "No" if model.endswith("F") or re.search(r"\b[1-5]\d{3}X?\b", model.split()[-1]) and not model.endswith("G") else "Yes"
                if re.search(r" [79]\d{3}", model) and not model.endswith("F"):
                    s["igpu"] = "Yes"
            elif maker == "Intel":
                s["igpu"] = "No" if re.search(r"F$|KF$", model) else "Yes"
        s["pack"] = "Tray" if re.search(r"\b(tray|oem|mpk)\b", t) else "Box" if re.search(r"\b(box|boxed)\b", t) else "Unknown"
    elif cat == "motherboard":
        m = _CHIPSET_RX.search(t)
        if m:
            cs = m.group(1)
            s["chipset"] = cs.upper()
            s["socket"] = CHIPSET_SOCKET[cs]
            suf = (m.group(2) or "").replace("-", "")
            if suf == "m":
                s["form"] = "Micro-ATX"
            elif suf == "i":
                s["form"] = "Mini-ITX"
        s.setdefault("form", _form(t) or "ATX")
        d = re.search(r"\b(ddr[345])\b|\bd([45])\b", t)
        if d:
            s["ddr"] = (d.group(1) or f"ddr{d.group(2)}").upper()
        elif s.get("socket") in ("AM5", "LGA1851"):
            s["ddr"] = "DDR5"
        s["wifi"] = "Yes" if re.search(r"\b(wi-?fi|wifi ?[67]e?|ax|be)\b", t) else "No"
    elif cat == "ram":
        d = re.search(r"\b(ddr[2345])\b", t)
        if d:
            s["ddr"] = d.group(1).upper()
        kit2 = re.search(r"(\d{1,3})\s?gb?\s?\(\s?(\d{1,3})\s?x\s?(\d)\s?\)", t)
        if kit2 and int(kit2.group(2)) * int(kit2.group(3)) == int(kit2.group(1)):
            kit = None
            s["capacity"], s["kit"] = int(kit2.group(1)), f"{kit2.group(3)}x{kit2.group(2)}GB"
        else:
            kit = re.search(r"(\d)\s?x\s?(\d{1,3})\s?gb|(\d{1,3})\s?gb\s?(?:\()?\s?x\s?(\d)\b|(\d{1,3})\s?gb\s?\(\s?(\d)\s?x\s?(\d{1,3})", t)
        if kit:
            if kit.group(1):
                n, size = int(kit.group(1)), int(kit.group(2))
            elif kit.group(3):
                n, size = int(kit.group(4)), int(kit.group(3))
            else:
                n, size = int(kit.group(6)), int(kit.group(7))
            s["capacity"], s["kit"] = n * size, f"{n}x{size}GB"
        elif "capacity" not in s:
            c = re.search(r"(\d{1,3})\s?gb?\b", t)
            if c and int(c.group(1)) in (1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256):
                s["capacity"], s["kit"] = int(c.group(1)), "Single"
        sp = re.search(r"(\d{4})\s?(?:mhz|mt/s|mts)\b", t) or re.search(r"ddr[345]\s?-?\s?(\d{4})\b", t)
        if sp:
            s["speed"] = int(sp.group(1))
        cl = re.search(r"\bc(?:l)?\s?(\d{2})\b", t)
        if cl:
            s["cl"] = int(cl.group(1))
        s["formfactor"] = "Laptop (SODIMM)" if re.search(r"\b(sodimm|so-dimm|laptop|notebook)\b", t) else "Desktop"
        s["rgb"] = _rgb(t)
    elif cat == "ssd":
        c = _cap(t, 60)
        if c:
            s["capacity"] = c
        if re.search(r"\b(nvme|pcie|gen ?[345])\b", t):
            s["interface"] = "NVMe"
        elif re.search(r"\bsata\b|2\.5", t):
            s["interface"] = "SATA"
        g = re.search(r"gen ?([345])|pcie ?([345])\.0", t)
        if g:
            s["pcie"] = f"Gen{g.group(1) or g.group(2)}"
        s["form"] = "M.2" if re.search(r"m\.2|m2\b|2280|nvme", t) else "2.5\"" if re.search(r"2\.5|sata", t) else "Other"
    elif cat == "hdd":
        c = _cap(t, 160)
        if c:
            s["capacity"] = c
        r = re.search(r"(5400|5900|7200|10000|15000)\s?rpm", t)
        if r:
            s["rpm"] = int(r.group(1))
        s["use"] = "NAS" if re.search(r"\b(nas|ironwolf|red)\b", t) else "Surveillance" if re.search(r"\b(surveillance|purple|skyhawk)\b", t) \
            else "Laptop" if re.search(r"2\.5|laptop", t) else "Desktop"
    elif cat == "psu":
        w = [int(x) for x in re.findall(r"\b(\d{3,4})\s?w(?:att)?s?\b", t) if 200 <= int(x) <= 2500]
        if not w:   # model names: MWE Gold 850, P750GM, GE-750, DA1000, B750, V650W
            w = [int(x) for x in re.findall(r"(?<![\d.])(?:[a-z]{1,4}[- ]?)?(\d{3,4})(?:[a-z]{1,3})?\b(?!\s?(?:volt|v\b|mhz|rpm|mm|va))", t)
                 if 300 <= int(x) <= 1650 and int(x) % 50 == 0]
        if w:
            s["watt"] = max(w)
        r = re.search(r"\b(titanium|platinum|gold|silver|bronze)\b", t)
        s["rating"] = r.group(1).title() if r else ("White" if re.search(r"80 ?(\+|plus)", t) else "None")
        s["modular"] = "Full" if re.search(r"\b(full(y)?[- ]?modular)\b", t) else "Semi" if re.search(r"semi[- ]?modular", t) \
            else "Full" if re.search(r"\bmodular\b", t) else "No"
        s["atx3"] = "Yes" if re.search(r"atx ?3\.[01]|pcie ?5(\.[01])?\b|12v-?2x6|12vhpwr", t) else "No"
    elif cat == "case":
        s["form"] = "Full Tower" if re.search(r"full[- ]?tower", t) else "Mini-ITX" if re.search(r"\bitx\b", t) \
            else "Micro-ATX" if re.search(r"micro[- ]?atx|m-?atx|matx|mini[- ]?tower", t) else "Mid Tower"
        s["rgb"] = _rgb(t)
    elif cat == "cooler":
        if re.search(r"\b(liqu?i?d|aio|water)\b", t):
            s["type"] = "Liquid (AIO)"
            r = re.search(r"\b(120|240|280|360|420)\s?(mm)?\b", t) or re.search(r"\b[a-z]{1,3}(240|360|280|120|420)\b", t)
            if r:
                s["radiator"] = int(r.group(1))
        else:
            s["type"] = "Air"
        s["rgb"] = _rgb(t)
    elif cat == "fan":
        r = re.search(r"\b(80|92|120|140|200)\s?mm\b", t)
        if r:
            s["size"] = int(r.group(1))
        p = re.search(r"\b(\d)\s?(?:in ?1|pack|pcs|fans|x)\b", t)
        s["pack"] = int(p.group(1)) if p else 1
        s["rgb"] = _rgb(t)
    elif cat == "monitor":
        z = re.search(r"(\d{2}(?:\.\d)?)\s?(?:\"|″|inch|”|''|in\b|-inch|بوصة|بوصه)", t)
        if z and 15 <= float(z.group(1)) <= 57:
            s["size"] = float(z.group(1))
        else:   # model codes carry the size: GS27FA, M34WQ, G27C4, 27E2G2200, LS27F320
            m = re.search(r"\b(?:[a-z]{1,4})?(2[2-9]|3[0-4]|49)(?=[a-z])[a-z0-9-]{1,10}\b", t)
            if m:
                s["size"] = float(m.group(1))
        if re.search(r"\b(4k|uhd|2160p|3840 ?x ?2160)\b", t):
            s["resolution"] = "4K UHD"
        elif re.search(r"\b(3440 ?x ?1440|uwqhd|wqhd ultrawide)\b", t):
            s["resolution"] = "UWQHD 3440x1440"
        elif re.search(r"\b(qhd|2k|1440p|2560 ?x ?1440|wqhd)\b", t):
            s["resolution"] = "QHD 1440p"
        elif re.search(r"\b(fhd|full hd|1080p|1920 ?x ?1080)\b", t):
            s["resolution"] = "FHD 1080p"
        elif re.search(r"\b(hd|1366 ?x ?768|768p)\b", t):
            s["resolution"] = "HD"
        hz = [int(x) for x in re.findall(r"(\d{2,3})\s?hz", t) if 50 <= int(x) <= 600]
        if hz:
            s["hz"] = max(hz)
        p = re.search(r"\b(qd-?oled|oled|mini ?led|ips|va|tn)\b", t)
        if p:
            s["panel"] = p.group(1).upper().replace("QDOLED", "QD-OLED").replace("MINI LED", "Mini LED").replace("MINILED", "Mini LED")
        s["curved"] = "Yes" if re.search(r"\bcurved\b", t) else "No"
    elif cat in ("laptop", "desktop"):
        model, _, _ = cpu_model(t)
        if model:
            s["cpu"] = model
        chip, _ = gpu_chip(t)
        if chip:
            s["gpu"] = chip
        r = re.search(r"(\d{1,3})\s?gb\s?(?:ram|ddr|lpddr|memory|unified)", t) or re.search(r"\b(4|8|12|16|18|24|32|36|48|64|96|128)\s?gb\b", t)
        if r:
            s["ram"] = int(r.group(1))
        st = re.search(r"(\d+(?:\.\d)?)\s?(tb|gb)\s?(?:m\.2\s?)?(?:nvme\s?|pcie\s?)?(?:ssd|hdd|emmc|storage)", t)
        if st:
            s["storage"] = _gb(st.group(1), st.group(2))
        if cat == "laptop":
            z = re.search(r"(1[0-8](?:\.\d)?)\s?(?:\"|inch|”|''|-inch)", t)
            if z:
                s["screen"] = f'{z.group(1)}"'
    elif cat in ("keyboard", "mouse", "headset"):
        s["connection"] = _wireless(t)
        if cat == "keyboard":
            s["mechanical"] = "Yes" if re.search(r"\b(mechanical|hot-?swap|switch(es)?|gateron|kailh|outemu)\b", t) else "No"
    elif cat == "storage_ext":
        c = _cap(t, 1)
        if c:
            s["capacity"] = c
        s["kind"] = "Flash drive" if re.search(r"flash|pen ?drive|usb (2|3)", t) else "Memory card" if re.search(r"micro ?sd|sd ?card|sdxc|sdhc|memory card", t) \
            else "External SSD" if re.search(r"ssd|t7|t9", t) else "External HDD"
    elif cat == "network":
        s["kind"] = "Router" if re.search(r"router|mesh", t) else "Switch" if re.search(r"switch", t) else "Adapter" if re.search(r"adapter|card|nano|usb", t) \
            else "Access point / extender" if re.search(r"access point|extender|repeater", t) else "Other"
    elif cat == "ups":
        v = re.search(r"(\d{3,5})\s?va\b", t) or re.search(r"(\d(?:\.\d)?)\s?kva", t)
        if v:
            s["va"] = int(float(v.group(1)) * (1000 if "kva" in v.group(0) else 1))
    return s


SERIES_BRAND = [(r"\b(windforce|eagle|aorus|aero oc)\b", "gigabyte"), (r"\b(tuf|rog|strix|astral|prime|proart)\b", "asus"),
                (r"\b(ventus|gaming trio|suprim|shadow [23]x|inspire|vanguard|gaming x)\b", "msi"),
                (r"\b(twin edge|amp|trinity|solid oc)\b", "zotac"), (r"\b(gamingpro|jetstream|gamerock)\b", "palit"),
                (r"\b(ichill|twin x2)\b", "inno3d"), (r"\b(nitro\+|pulse|pure)\b", "sapphire"),
                (r"\b(hellhound|red devil|reaper|fighter)\b", "powercolor"), (r"\b(swft|mercury|quicksilver)\b", "xfx")]


def brand_of(t, vendor, store_name="", cat=None):
    b = _brand_of(t, vendor, store_name)
    if not b and cat == "gpu":
        for rx, name in SERIES_BRAND:
            if re.search(rx, t):
                return name
    return b


def _brand_of(t, vendor, store_name=""):
    v = norm(vendor)
    if v and v not in norm(store_name) and len(v) < 30 and not re.search(r"\d{3,}|default|vendor|store|shop", v):
        m = _BRAND_RX.search(v)
        if m:
            return _BRAND_FIX.get(m.group(1), m.group(1))
    m = _BRAND_RX.search(t)
    if m:
        return _BRAND_FIX.get(m.group(1), m.group(1))
    return v if v and len(v) < 25 and v not in norm(store_name) else ""


STOP = set("""the a an and with for of in to by new original egypt price best gaming graphic graphics card video
desktop processor cpu motherboard ram memory module kit ssd internal solid state drive hard disk power supply
unit pc computer case mid tower monitor inch black white edition version series technology support pcie
pci express gen interface plus""".split())


def _model_tokens(t, brand):
    toks = re.findall(r"[a-z0-9][a-z0-9.+-]*", t)
    out = []
    for x in toks:
        x = x.strip(".-")
        if not x or x in STOP or x == brand or len(x) > 24:
            continue
        if re.search(r"\d", x) and not re.fullmatch(r"\d{4,5}mb/?s?|\d+mbps|\d{1,2}(\.\d)?gbps", x):
            out.append(x)
    return out


def model_key(cat, brand, s, t):
    b = brand or "?"
    if cat == "gpu" and s.get("chip"):
        ser = sorted(set(x for x in _SERIES_RX.findall(t) if x not in ("gaming",)))
        return f"gpu|{b}|{s['chip']}|{s.get('vram', '')}|{' '.join(ser)}"
    if cat == "cpu" and s.get("model"):
        return f"cpu|{s['model']}|{s.get('pack', '')}"
    if cat == "ram" and s.get("capacity"):
        return f"ram|{b}|{s.get('ddr', '')}|{s.get('kit', '')}|{s.get('speed', '')}|{s.get('cl', '')}|{s.get('formfactor', '')}|{s.get('rgb')}"
    toks = sorted(set(_model_tokens(t, b)))
    if not toks:
        # no model number in the title: group only listings with the same distinctive words
        words = [w for w in re.findall(r"[a-z\u0600-\u06ff]{3,}", t) if w not in STOP and w != b and w not in GENERIC]
        return f"{cat}|{b}|~{' '.join(sorted(set(words))[:8]) or t[:80]}"
    if cat == "monitor":
        code = [x for x in toks if re.fullmatch(r"[a-z]*\d+[a-z0-9-]*", x) and len(x) >= 5 and not re.fullmatch(r"\d+hz|\d+(\.\d)?(inch|\")?", x)]
        if code:
            return f"monitor|{b}|{code[0]}"
    return f"{cat}|{b}|{' '.join(toks[:8])}"


GENERIC = set("""wired wireless gaming usb black white red blue grey gray silver original new used open box copy
with and for the rgb led edition english arabic layout keyboard mouse headset""".split())

CONDITION = [("Used", r"\b(used|second ?hand|pre-?owned|مستعمل|استعمال)\b"),
             ("Open box", r"\b(open ?box|opened|كسر زيرو)\b"),
             ("Refurbished", r"\b(refurbished|renewed|refurb)\b")]


def condition_of(t):
    for name, rx in CONDITION:
        if re.search(rx, t):
            return name
    return "New"


def family_of(cat, s):
    k = {"gpu": "chip", "cpu": "model", "motherboard": "chipset", "psu": "watt", "ssd": "capacity", "hdd": "capacity",
         "monitor": "size"}.get(cat)
    if cat == "ram" and s.get("ddr") and s.get("capacity"):
        return f"ram:{s['ddr']} {s['capacity']}GB"
    if k and s.get(k):
        return f"{cat}:{s[k]}"
    return None


def classify(title, store_cat="", vendor="", store_name=""):
    t = norm(title)
    cat = decide(category_of(title), store_category(store_cat), title)
    brand = brand_of(t, vendor, store_name, cat)
    s = specs_for(cat, t, brand)
    cond = condition_of(t)
    s["condition"] = cond
    key = model_key(cat, brand, s, t) + ("" if cond == "New" else f"|{cond}")   # used items compare among themselves
    return {"category": cat, "brand": brand, "specs": s, "family": family_of(cat, s), "model_key": key}
