#!/usr/bin/env python3
"""Добор фото-фонов с Wikimedia Commons (запускает workflow «Fetch photos»).

Берём только снимки, которые сообщество Commons признало качественными (Quality / Valued / Featured),
большие (длинная сторона ≥ 2400 px) и со свободной лицензией (CC0, CC BY, CC BY-SA — без NC/ND).
Файлы кладутся в library/photos/commons-<тема>-<id>.jpg (≤ 2160 px, без метаданных),
описание — в library/photos/commons-new.json: автор, лицензия, теги. Людей крупным планом
и неудачные кадры отбраковывает человек (или Claude) по контактной таблице, потом записи переносятся
в library/backgrounds.json.

Запуск: fetch_photos.py "тема:запрос[:теги через запятую]" ... [--per 6]
Пример: fetch_photos.py "kunstpalast:Kunstpalast Düsseldorf:museum,art"
"""
import hashlib, html, json, re, subprocess, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "library" / "photos"
UA = {"User-Agent": "tut.dus background fetcher (https://github.com/bobbynus/tut.dus)"}
API = "https://commons.wikimedia.org/w/api.php"
GOOD = ("Quality images", "Valued images", "Featured pictures on Wikimedia Commons")
FREE = re.compile(r"^(CC0|Public domain|PD|CC BY(-SA)? \d)", re.I)
MIN_SIDE = 2400


def api(**params):
    q = urllib.parse.urlencode({"format": "json", **params})
    with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=UA), timeout=60) as r:
        return json.load(r)


def plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def search(query, limit):
    found = {}
    for cat in GOOD:
        res = api(action="query", generator="search", gsrnamespace=6, gsrlimit=40,
                  gsrsearch=f'incategory:"{cat}" {query} filetype:bitmap',
                  prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=2160)
        for p in (res.get("query") or {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata") or {}
            lic = plain((meta.get("LicenseShortName") or {}).get("value"))
            if ii.get("mime") != "image/jpeg" or max(ii.get("width", 0), ii.get("height", 0)) < MIN_SIDE:
                continue
            if not FREE.match(lic) or re.search(r"\b(NC|ND)\b", lic):
                continue
            found.setdefault(p["title"], {"title": p["title"], "thumb": ii.get("thumburl") or ii["url"],
                                          "page": ii.get("descriptionurl"), "license": lic,
                                          "author": plain((meta.get("Artist") or {}).get("value"))[:60] or "неизвестен",
                                          "w": ii["width"], "h": ii["height"]})
        if len(found) >= limit * 3:
            break
    # портретные и близкие к квадрату — первыми: сторис вертикальные
    return sorted(found.values(), key=lambda x: x["w"] / x["h"])[:limit]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--per", type=int, default=6)
    opts = ap.parse_args()
    args, per = opts.specs, opts.per
    new_file = OUT / "commons-new.json"
    new = json.loads(new_file.read_text()) if new_file.exists() else {}
    for spec in args:
        topic, query, *rest = spec.split(":")
        tags = [t.strip() for t in (rest[0] if rest else topic).split(",") if t.strip()]
        items = search(query, per)
        print(f"{topic}: подходящих {len(items)}")
        for it in items:
            name = f"commons-{topic}-{hashlib.md5(it['title'].encode()).hexdigest()[:8]}.jpg"
            if (OUT / name).exists():
                continue
            raw = OUT / (name + ".tmp")
            with urllib.request.urlopen(urllib.request.Request(it["thumb"], headers=UA), timeout=120) as r:
                raw.write_bytes(r.read())
            subprocess.run(["convert", str(raw), "-auto-orient", "-resize", "2160x2160>", "-strip", "-quality", "86",
                            str(OUT / name)], check=True)
            raw.unlink()
            lic = it["license"].replace("Public domain", "PD")
            new[name] = {"tags": tags, "credit": f"Фото: {it['author']} / {lic}", "page": it["page"],
                         "size": f"{it['w']}×{it['h']}"}
            print(f"  + {name}  {it['w']}×{it['h']}  {lic}  {it['author']}")
    new_file.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
