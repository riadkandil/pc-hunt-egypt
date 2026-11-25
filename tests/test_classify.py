import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pchunt.classify import classify  # noqa: E402

CASES = [
    # title, category, expected spec subset, brand
    ("Asus Dual GeForce RTX 5060 NVIDIA OC Graphic Card - DUAL-RTX5060-O8G", "gpu", {"chip": "RTX 5060"}, "asus"),
    ("ASUS TUF Gaming RTX 5070 Ti 16GB GDDR7 OC Edition", "gpu", {"chip": "RTX 5070 Ti", "vram": 16, "series": "TUF"}, "asus"),
    ("Sapphire PULSE AMD Radeon RX 9070 XT 16GB GDDR6", "gpu", {"chip": "RX 9070 XT", "vram": 16}, "sapphire"),
    ("Gigabyte GeForce RTX 4060 Ti EAGLE OC 8G", "gpu", {"chip": "RTX 4060 Ti", "vram": 8}, "gigabyte"),
    ("Intel Arc B580 Limited Edition 12GB", "gpu", {"chip": "Arc B580", "vram": 12}, "intel"),
    ("AMD Ryzen 7 7800X3D 8-Core Processor Box", "cpu", {"model": "Ryzen 7 7800X3D", "socket": "AM5", "pack": "Box"}, "amd"),
    ("Intel Core i5-12400F Processor 18M Cache tray", "cpu", {"model": "Core i5-12400F", "socket": "LGA1700", "pack": "Tray", "igpu": "No"}, "intel"),
    ("Intel® Core™ Ultra 7 265K Desktop Processor", "cpu", {"model": "Core Ultra 7 265K", "socket": "LGA1851"}, "intel"),
    ("AMD Ryzen 5 5600 6-Core AM4", "cpu", {"model": "Ryzen 5 5600", "socket": "AM4"}, "amd"),
    ("GIGABYTE B650M AORUS ELITE AX DDR5", "motherboard", {"chipset": "B650", "socket": "AM5", "form": "Micro-ATX", "wifi": "Yes"}, "gigabyte"),
    ("ASUS Prime B760-PLUS D4, an Intel® B760 LGA 1700 ATX motherboard", "motherboard", {"chipset": "B760", "ddr": "DDR4", "form": "ATX"}, "asus"),
    ("MSI MAG X870 TOMAHAWK WIFI", "motherboard", {"chipset": "X870", "socket": "AM5"}, "msi"),
    ("Kingston FURY Beast 32GB (2x16GB) DDR5 6000MHz CL30 RGB", "ram", {"ddr": "DDR5", "capacity": 32, "kit": "2x16GB", "speed": 6000, "cl": 30, "rgb": "Yes"}, "kingston"),
    ("Corsair Vengeance LPX 16GB DDR4 3200MHz", "ram", {"capacity": 16, "speed": 3200, "formfactor": "Desktop"}, "corsair"),
    ("Crucial 8GB DDR4 3200 SODIMM Laptop Memory", "ram", {"capacity": 8, "formfactor": "Laptop (SODIMM)"}, "crucial"),
    ("Samsung 990 EVO Plus 1TB NVMe M.2 SSD PCIe Gen 4", "ssd", {"capacity": 1024, "interface": "NVMe", "pcie": "Gen4"}, "samsung"),
    ("Lexar NM790 M.2 2280 PCIe Gen 4×4 NVMe SSD Internal 2TB", "ssd", {"capacity": 2048, "interface": "NVMe"}, "lexar"),
    ("Kingston A400 480GB 2.5 SATA SSD", "ssd", {"capacity": 480, "interface": "SATA", "form": "2.5\""}, "kingston"),
    ("Seagate BarraCuda 2TB 7200 RPM HDD", "hdd", {"capacity": 2048, "rpm": 7200}, "seagate"),
    ("MSI MAG A850GL PCIE5 850W 80 Plus Gold Fully Modular Power Supply", "psu", {"watt": 850, "rating": "Gold", "modular": "Full", "atx3": "Yes"}, "msi"),
    ("Cooler Master MWE 650 Bronze V2 650W", "psu", {"watt": 650, "rating": "Bronze"}, "cooler master"),
    ("Cooler Master TD500 MAX ATX Mid-Tower Case", "case", {"form": "Mid Tower"}, "cooler master"),
    ("DeepCool AK620 CPU Cooler", "cooler", {"type": "Air"}, "deepcool"),
    ("LIqud cooler Gammaxx l240 Argb", "cooler", {"type": "Liquid (AIO)", "radiator": 240, "rgb": "Yes"}, ""),
    ("Arctic MX-4 Thermal Paste 4g", "thermal", {}, "arctic"),
    ("Thermal Grizzly Hydronaut 1g Thermal Paste", "thermal", {}, "thermal grizzly"),
    ("Dell SE2725HG 27 Inch Full HD IPS Gaming Monitor 200Hz 1ms", "monitor", {"size": 27.0, "resolution": "FHD 1080p", "hz": 200, "panel": "IPS"}, "dell"),
    ("LG UltraGear 27GQ50F 27\" FHD VA 165Hz", "monitor", {"size": 27.0, "hz": 165, "panel": "VA"}, "lg"),
    ("Lenovo LOQ 15IRX9 Laptop i7-13650HX RTX 4060 16GB 1TB SSD 15.6\"", "laptop", {"gpu": "RTX 4060", "ram": 16, "storage": 1024}, "lenovo"),
    ("HUAWEI MateBook D15 With Ryzen 7 5700U, 8GB RAM", "laptop", {"cpu": "Ryzen 7 5700U", "ram": 8}, "huawei"),
    ("Gaming PC Build Ryzen 5 5500 GTX 1660 Super 16GB DDR4", "desktop", {"cpu": "Ryzen 5 5500", "gpu": "GTX 1660 Super", "ram": 16}, None),
    ("9700x tray mpk gigabyte b650 gaming x ax v2 am5 lexar thor oc 32gb kit 2x16gb 6000mhz gigabyte rtx 5070 windforce oc sff 12gb", "desktop", {}, None),
    ("Logitech G PRO X Gaming Headset (2nd Generation)", "headset", {}, "logitech"),
    ("T-DAGGER ARENA TGK321 Wired Gaming Keyboard RGB", "keyboard", {"connection": "Wired"}, "t-dagger"),
    ("Logitech G502 X Lightspeed Wireless Gaming Mouse", "mouse", {"connection": "Wireless"}, "logitech"),
    ("Razer Gigantus V2 Gaming Mouse Pad", "mousepad", {}, "razer"),
    ("HDMI to VGA Cable 1.5m", "accessory", {}, None),
    ("Laptop Bag 15.6 inch", "accessory", {}, None),
    ("SanDisk Ultra 64GB USB 3.0 Flash Drive", "storage_ext", {"capacity": 64, "kind": "Flash drive"}, "sandisk"),
    ("TP-Link Archer AX55 AX3000 Wi-Fi 6 Router", "network", {"kind": "Router"}, "tp-link"),
    ("Galanz 97L Mini Bar Refrigerator BC-103F", "appliance", {}, None),
    ("BOSCH MultiTalent 3 Plus Food processor, 900 Watt, 2.3L - MCM3PM386", "appliance", {}, None),
    ("Xiaomi 17 Dual SIM 5G - 12GB + 512GB / Venture Green", "phone", {}, None),
    ("سامسونج جالاكسي A37 ثنائي الشريحة 8 جيجابايت رام 5G", "phone", {}, None),
    ("Acer Nitro VG271 27 Inches Full HD IPS Monitor with AMD Radeon FREESYNC Technology, 144Hz", "monitor", {"hz": 144}, "acer"),
    ("AOC Q27G4Z 27″ 2K QHD Fast IPS 260Hz Gaming Monitor", "monitor", {"size": 27.0, "resolution": "QHD 1440p", "hz": 260}, "aoc"),
    ("آسوس TUF شاشة ألعاب 23.8 بوصة، FHD LED، معدل تحديث 120Hz، موديل VA249HG", "monitor", {"size": 23.8, "hz": 120}, None),
    ("AMD Ryzen 3 3200G 4M Cache 4-Core Socket AM4 65W AMD Radeon Graphics TRAY", "cpu", {"model": "Ryzen 3 3200G", "socket": "AM4"}, "amd"),
    ("Intel Xeon E5-2660 v3 Processor", "cpu", {"model": "Xeon E5-2660V3"}, "intel"),
    ("Intel Ultra 5 225F", "cpu", {"model": "Core Ultra 5 225F", "socket": "LGA1851"}, "intel"),
    ("Intel® Core™ i5 processor 14400F 20M Cache, up to 4.70 GHz", "cpu", {"model": "Core i5-14400F"}, "intel"),
    ("Cooler Master MWE Gold 850 V2 Fully Modular Power Supply", "psu", {"watt": 850, "rating": "Gold"}, "cooler master"),
    ("GIGABYTE P750GM 80+GOLD FULLY MODULAR", "psu", {"watt": 750}, "gigabyte"),
    ("Asus Prime Gold Power Supply 240 Volt , White - 90YE00U0B0NA00", "psu", {"rating": "Gold"}, "asus"),
    ("TeamGroup ELITE 16G DDR5 5600MHz CL46 Desktop Memory", "ram", {"capacity": 16, "speed": 5600, "cl": 46}, "teamgroup"),
    ("Trident Z5 NEO RGB 64G (32×2) DDR5 Up to 6000MT/s", "ram", {"capacity": 64, "kit": "2x32GB", "speed": 6000}, None),
    ("iSkin Keyboard For MacBook Pro 13.3,15.4,17 Russian (US)", "accessory", {}, None),
    ("2B (CV144) Type C to VGA Cable – 1.8M – Black", "accessory", {}, None),
    ("upHere G276CF Graphics Card GPU Brace Support (Sag Holder/Holster)", "accessory", {}, None),
    ("Pad Mouse Gaming Big 30*70", "mousepad", {}, None),
    ("Honor AM16 Earphone (Heart Rate Monitor)", "headset", {}, None),
    ("3D Micky Mouse Pattern Printing Case For iPhone 6", "accessory", {}, None),
    ("A4Tech KRS83 USB Keyboard For PC & Laptop", "keyboard", {}, "a4tech"),
    ("Infinix Wall Charger 33W", "accessory", {}, None),
    ("Infinix XPAD 30 Pro 4G, 8GB RAM, 256GB, 11-Inch Display - Gray", "tablet", {}, None),
    ("Honor 400 Lite 5G - 8GB Ram - 256GB - VELVET GREY", "phone", {}, None),
    ("REDRAGON H730 - USB Wired Gaming Headset 53mm Drivers", "headset", {}, "redragon"),
    ("Corsair Vengeance RGB PRO 16GB (2x8GB) 3600MHz CL18 DDR4 DRAM Desktop Gaming Memory Kit", "ram", {"capacity": 16}, "corsair"),
    ("XPG LEVANTE II 360 ALL-IN-ONE CPU LIQUID COOLER", "cooler", {"type": "Liquid (AIO)"}, None),
    ("HP Victus 15 Intel Core i5 12450H, NVIDIA GeForce RTX 3050 4gb, 8GB RAM, 512GB SSD, Full HD", "laptop", {"gpu": "RTX 3050"}, "hp"),
    ("Dell G15 5510 Gaming Laptop - Intel Core i5-10500H 8GB RAM, 512GB SSD, Nvidia GTX1650, 15.6 inch", "laptop", {}, "dell"),
    ("PC Used Desktop HP EliteDesk 705 G3 (AMD A12/8870 - 8G DDR4 - No Hard - AMD Radeon R7 - DVD)", "desktop", {}, "hp"),
    ("نوكيا 125 - أسود", "phone", {}, None),
]


class ClassifyTest(unittest.TestCase):
    def test_cases(self):
        bad = []
        for title, cat, sub, brand in CASES:
            r = classify(title)
            got = r and r["category"]
            if got != cat:
                bad.append(f"{title!r}: category {got} != {cat}")
                continue
            if r is None:
                continue
            for k, v in (sub or {}).items():
                if r["specs"].get(k) != v:
                    bad.append(f"{title!r}: {k}={r['specs'].get(k)!r} != {v!r}  ({r['specs']})")
            if brand is not None and r["brand"] != brand:
                bad.append(f"{title!r}: brand {r['brand']!r} != {brand!r}")
        self.assertFalse(bad, "\n" + "\n".join(bad))

    def test_same_model_same_key(self):
        a = classify("ASUS TUF Gaming GeForce RTX 5070 Ti 16GB GDDR7 OC Edition Graphics Card")
        b = classify("ASUS TUF-RTX5070TI-O16G-GAMING TUF Gaming RTX 5070 Ti OC 16GB")
        self.assertEqual(a["family"], b["family"])
        c = classify("AMD Ryzen 7 7800X3D Box")
        d = classify("Ryzen 7 7800X3D 8-Core 16-Thread Desktop Processor - Box")
        self.assertEqual(c["model_key"], d["model_key"])


if __name__ == "__main__":
    unittest.main()


class SearchTest(unittest.TestCase):
    def test_query_parse(self):
        from pchunt import query
        r = query.parse('brand:asus "rog strix" -laptop price<8000 ddr5 OR ddr4')
        self.assertEqual(r["filters"]["brand"], ["asus"])
        self.assertEqual(r["filters"]["max"], 8000.0)
        self.assertIn('"rog strix"', r["fts"])
        self.assertIn('NOT "laptop"*', r["fts"])
        self.assertEqual(query.intent("logitech keyboard"), "keyboard")
        self.assertEqual(query.intent("rtx 5070"), "gpu")
        self.assertEqual(query.intent("7800x3d"), "cpu")
        self.assertEqual(query.strip_category_words("graphics card rtx 5070", "gpu"), "rtx 5070")
        self.assertIn("rtx5070", query.index_text("RTX 5070"))
        self.assertIn("5070", query.index_text("RTX5070"))

    def test_more_titles(self):
        for title, store, cat in [("KINBAS GT700 Silent Gaming Mouse, 7 buttons", "", "mouse"),
                                  ("Manhattan VGA and USB to HDMI Converter", "", "accessory"),
                                  ("MSI GeForce GT 1030 2GD4 LP OC", "", "gpu"),
                                  ("Logitech M90 Wired USB Mouse Black", "Accessories, Keyboard & Mouse", "mouse"),
                                  ("Logitech MK270 Wireless Keyboard and Mouse Combo", "Keyboard & Mouse", "keyboard"),
                                  ("REDRAGON M724 Wired Gaming Mouse", "Keyboards", "mouse"),
                                  ("Cooler Master TD500 Max Bundle", "Case", "case"),
                                  ("COUGAR MX350 Tempered glass Mid Tower Case", "Cases", "case"),
                                  ("HYTE Y70 Modern Aesthetic Included Luxury PCIE 4.0 Riser Cable Black Mid Tower Case", "", "case"),
                                  ("Corsair iCUE 5000T RGB Tempered Glass Mid-Tower ATX PC Case - White", "", "case"),
                                  ("MSI MAG 274UPF E2 27 Inch 160Hz 1Ms UHD Rapid IPS KVM Switch VESA DisplayHDR 400 Monitor", "", "monitor"),
                                  ("TP-Link TL-WA850RE 300Mbps Wi-Fi Range Extender, White", "", "network"),
                                  ("Riser Cable PCIe 4.0 for PC Case", "Cases", "accessory"),
                                  ("Fantech ProMount MBD1 Dual Arm 13-32 Inch Black Monitor Bracket", "Monitors", "accessory"),
                                  ("Splitter HDMI 4K 4 Port Zero", "Monitors", "accessory")]:
            self.assertEqual(classify(title, store)["category"], cat, title)
