"""Календарь Visit Düsseldorf (visitduesseldorf.de) через API toubiz — тот же, что грузит виджет на сайте.

Токен публичный: он вшит в HTML страницы календаря, берём его оттуда при каждом сборе
(если сайт его сменит, подхватим автоматически). Один сбор = несколько запросов в день.
"""
import html, json, math, re, urllib.parse, urllib.request
from datetime import date, timedelta

PAGE = "https://www.visitduesseldorf.de/erleben/veranstaltungen/veranstaltungskalender"
API = "https://mein.toubiz.de/api/v1/event"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/130 Safari/537.36", "Accept": "application/json"}
CENTER = (51.2277, 6.7735)
RADIUS_KM = 20
DAYS = 21          # горизонт: три недели вперёд
MAX_PAGES = 15     # по 100 событий
# ежедневные экскурсии и туры — шум для ленты «что сегодня»
SKIP = re.compile(r"führung|fuehrung|rundfahrt|stadtrundgang|hop.on|sightseeing|tour\b|rundgang|escape|workshop für firmen", re.I)
CATS = [("концерт", ["konzert", "musik", "jazz", "oper", "klassik"]), ("театр", ["theater", "kabarett", "comedy", "musical", "tanz", "show"]),
        ("выставка", ["ausstellung", "museum", "kunst"]), ("детям", ["kinder", "familie"]), ("рынок", ["markt", "flohmarkt", "trödel"]),
        ("фестиваль", ["fest", "festival", "brauchtum", "kirmes"]), ("спорт", ["sport"]), ("вечеринка", ["party", "club"]),
        ("кино", ["kino", "film"]), ("лекция", ["vortrag", "lesung", "literatur"])]


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _coords(ev):
    g = ev.get("geocoordinates") or {}
    if isinstance(g, list):
        g = g[0] if g else {}
    try:
        return float(g.get("latitude")), float(g.get("longitude"))
    except (TypeError, ValueError, AttributeError):
        return None


def _category(ev):
    s = f"{(ev.get('category') or {}).get('name', '')} {ev.get('name', '')}".lower()
    for cat, words in CATS:
        if any(w in s for w in words):
            return cat
    return "событие"


def _text(v):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", v or ""))).strip()


def _when(ev, today, horizon):
    """(date, time, end_date) ближайшего проведения в окне или None."""
    ivs = [i for i in ev.get("dateIntervals") or [] if not i.get("canceled")]
    single = [i for i in ivs if i.get("repeatRuleName") in (None, "", "none") and i.get("date")]
    if single and len(single) == len(ivs):
        # разовые даты: берём ближайшую, ещё не закончившуюся
        for i in sorted(single, key=lambda i: i["date"]):
            end = i.get("end") or i["date"]
            if end >= today.isoformat() and i["date"] <= horizon.isoformat():
                return i["date"], (i.get("startAt") or "")[:5], (end if end != i["date"] else "")
        return None
    nxt = (ev.get("nextDate") or "")[:10]
    if not nxt or not (today.isoformat() <= nxt <= horizon.isoformat()):
        return None
    t = next(((i.get("startAt") or "")[:5] for i in ivs if i.get("startAt")), "")
    return nxt, t, ""


def events(report, days=DAYS):
    try:
        token = re.search(r'api-token="([^"]+)"', _get(PAGE)).group(1)
    except Exception as e:
        report.append(f"✗ Visit Düsseldorf (toubiz): токен не найден — {e}")
        return []
    today = date.today()
    horizon = today + timedelta(days=days)
    out, seen, skipped, far, pages = [], set(), 0, 0, 0
    for page in range(1, MAX_PAGES + 1):
        q = urllib.parse.urlencode({
            "api_token": token, "unlicensed": 1, "filter[clientIncludingManaged]": "current",
            "filter[date][after]": today.isoformat(), "filter[date][before]": horizon.isoformat(),
            "sorting[property]": "date", "pagination[pageSize]": 100, "pagination[page]": page})
        try:
            data = json.loads(_get(f"{API}?{q}"))
        except Exception as e:
            report.append(f"✗ Visit Düsseldorf (toubiz), страница {page}: {e}")
            break
        pages = page
        for ev in data.get("payload") or []:
            if ev.get("id") in seen or ev.get("canceled") or ev.get("invisible") or ev.get("trashed"):
                continue
            seen.add(ev.get("id"))
            name = _text(ev.get("name"))
            if SKIP.search(f"{name} {(ev.get('category') or {}).get('name', '')}"):
                skipped += 1
                continue
            c = _coords(ev)
            if c and _km(c, CENTER) > RADIUS_KM:
                far += 1
                continue
            w = _when(ev, today, horizon)
            if not w:
                continue
            out.append({"title": name, "date": w[0], "time": w[1], "end_date": w[2],
                        "venue": _text((ev.get("location") or {}).get("name")), "address": "", "locality": "Düsseldorf",
                        "price": "", "url": ev.get("bookingUrl") or PAGE, "category": _category(ev),
                        "description": _text(ev.get("intro"))[:300], "source": "Visit Düsseldorf"})
        if page >= (data.get("_attributes") or {}).get("pagination", {}).get("lastPage", 1):
            break
    report.append(f"✓ Visit Düsseldorf (toubiz): {len(out)} событий на {days} дн. "
                  f"(страниц {pages}; пропущено экскурсий {skipped}, дальше {RADIUS_KM} км {far})")
    return out


if __name__ == "__main__":
    rep = []
    evs = events(rep)
    print("\n".join(rep))
    from collections import Counter
    print(Counter(e["category"] for e in evs).most_common())
    print(Counter(e["date"] for e in evs).most_common(25))
    for e in evs[:40]:
        print(f"{e['date']} {e['time']:5} {e['end_date']:10} [{e['category']}] {e['title'][:60]} — {e['venue'][:40]}")
