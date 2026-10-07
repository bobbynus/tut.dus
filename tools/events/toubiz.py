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


def _start_time(ev, day):
    for i in ev.get("dateIntervals") or []:
        if i.get("startAt") and (i.get("date") or "") <= day <= (i.get("end") or "9999"):
            return i["startAt"][:5]
    return next(((i.get("startAt") or "")[:5] for i in ev.get("dateIntervals") or [] if i.get("startAt")), "")


def _fetch_day(token, day, report):
    """Все события, которые проходят в этот день (API сам разворачивает повторы)."""
    items, page = [], 1
    while page <= MAX_PAGES:
        q = urllib.parse.urlencode({
            "api_token": token, "unlicensed": 1, "filter[clientIncludingManaged]": "current",
            "filter[date][after]": day, "filter[date][before]": day,
            "pagination[pageSize]": 100, "pagination[page]": page})
        data = json.loads(_get(f"{API}?{q}"))
        items += data.get("payload") or []
        if page >= (data.get("_attributes") or {}).get("pagination", {}).get("lastPage", 1):
            break
        page += 1
    return items


def events(report, days=DAYS):
    try:
        token = re.search(r'api-token="([^"]+)"', _get(PAGE)).group(1)
    except Exception as e:
        report.append(f"✗ Visit Düsseldorf (toubiz): токен не найден — {e}")
        return []
    today = date.today()
    seen_days, info, skipped, far, failed = {}, {}, set(), set(), 0
    for n in range(days + 1):
        day = (today + timedelta(days=n)).isoformat()
        try:
            items = _fetch_day(token, day, report)
        except Exception as e:
            failed += 1
            continue
        for ev in items:
            eid = ev.get("id")
            if not eid or ev.get("canceled") or ev.get("trashed"):
                continue
            if eid not in info:
                name = _text(ev.get("name"))
                c = _coords(ev)
                if SKIP.search(f"{name} {(ev.get('category') or {}).get('name', '')}"):
                    skipped.add(eid)
                elif c and _km(c, CENTER) > RADIUS_KM:
                    far.add(eid)
                info[eid] = ev
            if eid not in skipped and eid not in far:
                seen_days.setdefault(eid, []).append(day)
    out = []
    for eid, ds in seen_days.items():
        ev = info[eid]
        base = {"title": _text(ev.get("name")), "venue": _text((ev.get("location") or {}).get("name")), "address": "",
                "locality": "Düsseldorf", "price": "", "url": ev.get("bookingUrl") or PAGE, "category": _category(ev),
                "description": _text(ev.get("intro"))[:300], "source": "Visit Düsseldorf"}
        ds = sorted(set(ds))
        if len(ds) >= 4:
            # идёт много дней (выставка, даже с выходными по понедельникам) — одна запись с периодом;
            # конец берём из расписания события, а не из нашего окна в 3 недели
            ends = [i.get("end") for i in ev.get("dateIntervals") or [] if i.get("end")]
            end = max([ds[-1]] + [e for e in ends if e >= ds[-1]])
            out.append({**base, "date": ds[0], "time": "", "end_date": end})
        else:
            for d in ds[:6]:  # повторяющиеся (спектакль по пятницам) — отдельными датами
                out.append({**base, "date": d, "time": _start_time(ev, d), "end_date": ""})
    report.append(f"{'✓' if not failed else '⚠'} Visit Düsseldorf (toubiz): {len(seen_days)} событий, {len(out)} записей на {days} дн. "
                  f"(пропущено экскурсий {len(skipped)}, дальше {RADIUS_KM} км {len(far)}"
                  f"{f', не загрузилось дней: {failed}' if failed else ''})")
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
