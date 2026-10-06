"""Перекрытия на автобанах вокруг Дюссельдорфа (открытый API Autobahn GmbH, без ключа)."""
import json, math, re, urllib.request
from datetime import datetime

CENTER = (51.2277, 6.7735)
RADIUS_KM = 15
ROADS = ["A3", "A44", "A46", "A52", "A57", "A59"]


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _when(lines, label):
    for l in lines:
        m = re.search(label + r":\s*(\d{2})\.(\d{2})\.(\d{2,4})(?:\s*um\s*(\d{1,2}):(\d{2}))?", l)
        if m:
            d, mo, y, hh, mm = m.groups()
            y = int(y) + (2000 if len(y) == 2 else 0)
            return datetime(y, int(mo), int(d), int(hh or 0), int(mm or 0))
    return None


def closures(report):
    out = []
    for road in ROADS:
        for service in ("closure", "roadworks"):
            try:
                url = f"https://verkehr.autobahn.de/o/autobahn/{road}/services/{service}"
                items = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "tut.dus"}), timeout=30)).get(service, [])
            except Exception as e:
                report.append(f"✗ Autobahn {road}/{service}: {e}"); continue
            for it in items:
                c = it.get("coordinate") or {}
                try:
                    if _km(CENTER, (float(c["lat"]), float(c["long"]))) > RADIUS_KM: continue
                except (KeyError, ValueError, TypeError):
                    continue
                desc = it.get("description") or []
                text = " ".join(desc)
                full = service == "closure" or re.search(r"Vollsperrung|gesperrt", text, re.I)
                if not full: continue
                start, end = _when(desc, "Beginn"), _when(desc, "Ende")
                if not start: continue
                out.append({
                    "title": f"{road}: {it.get('subtitle') or it.get('title', '')}".strip(),
                    "date": start.date().isoformat(), "time": start.strftime("%H:%M"),
                    "end_date": end.date().isoformat() if end else "", "end_time": end.strftime("%H:%M") if end else "",
                    "venue": it.get("title", ""), "address": "", "locality": "Düsseldorf", "price": "", "url": "https://www.autobahn.de/",
                    "category": "важное", "description": re.sub(r"\s+", " ", text)[:240],
                    "source": "Autobahn GmbH", "traffic": True,
                })
    # одно и то же место часто встречается в обоих сервисах
    seen, uniq = set(), []
    for e in out:
        k = (e["title"], e["date"], e["time"])
        if k not in seen:
            seen.add(k); uniq.append(e)
    report.append(f"✓ Autobahn: {len(uniq)} перекрытий в радиусе {RADIUS_KM} км")
    return uniq
