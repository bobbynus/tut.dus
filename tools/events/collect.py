#!/usr/bin/env python3
"""Собирает события Дюссельдорфа в data/events.json и data/events.md.

1. Для каждого источника из sources.json ищет разметку schema.org Event (JSON-LD).
2. Страницы без разметки (llm=true) разбирает Gemini, если задан GEMINI_API_KEY.
3. Фильтрует по городу и датам, убирает дубли.
Без ключа Gemini работают только источники с разметкой.
"""
import html as htmllib, json, os, re, sys, time, unicodedata, urllib.request, urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((Path(__file__).parent / "sources.json").read_text())
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
TODAY = date.today()
HORIZON = TODAY + timedelta(days=CFG.get("days_ahead", 60))
LOCALITIES = CFG["localities"]
report = []
OTHER_CITIES = (r"\b(köln|koeln|cologne|essen|dortmund|bonn|duisburg|wuppertal|krefeld|bochum|mönchengladbach|aachen|"
                r"oberhausen|kleve|solingen|remscheid|leverkusen|mülheim|gelsenkirchen|moers|viersen|hagen|"
                r"bergisch|klingenhalle|obex)\b")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de,en;q=0.8"})
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")


# ---------- JSON-LD ----------
def walk_events(obj, out):
    if isinstance(obj, list):
        for x in obj: walk_events(x, out)
    elif isinstance(obj, dict):
        t = obj.get("@type", "")
        t = " ".join(t) if isinstance(t, list) else str(t)
        if re.search(r"Event\b", t) and "startDate" in obj:
            out.append(obj)
        for k in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
            if k in obj: walk_events(obj[k], out)


def text(v):
    if isinstance(v, list): v = v[0] if v else ""
    if isinstance(v, dict): v = v.get("name") or v.get("@id") or ""
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", str(v or ""))).strip()


def from_jsonld(e, source):
    loc = e.get("location") or {}
    if isinstance(loc, list): loc = loc[0] if loc else {}
    addr = loc.get("address", "") if isinstance(loc, dict) else ""
    if isinstance(addr, dict):
        locality = addr.get("addressLocality", "")
        addr = ", ".join(x for x in [addr.get("streetAddress", ""), addr.get("postalCode", ""), locality] if x)
    else:
        locality = ""
    offers = e.get("offers") or {}
    if isinstance(offers, list): offers = offers[0] if offers else {}
    price = offers.get("price") or offers.get("lowPrice") if isinstance(offers, dict) else None
    t = e.get("@type", "")
    t = " ".join(t) if isinstance(t, list) else str(t)
    start, end = str(e.get("startDate", "")), str(e.get("endDate", ""))
    return {
        "title": text(e.get("name")),
        "date": start[:10], "time": start[11:16] if len(start) > 10 else "",
        "end_date": end[:10] if end else "",
        "venue": text(loc.get("name")) if isinstance(loc, dict) else text(loc),
        "address": text(addr), "locality": locality,
        "price": str(price) if price not in (None, "") else "",
        "url": text(e.get("url")),
        "category": source.get("category") or guess_category(t, text(e.get("name"))),
        "description": text(e.get("description"))[:300],
        "source": source["name"],
    }


def guess_category(schema_type, title):
    s = f"{schema_type} {title}".lower()
    for cat, words in [("рынок", ["trödel", "floh", "markt", "market"]), ("детям", ["kinder", "kids", "familie"]),
                       ("концерт", ["music", "konzert", "concert", "live", "band", "jazz"]),
                       ("театр", ["theater", "theatre", "comedy", "kabarett", "musical"]),
                       ("выставка", ["exhibition", "ausstellung", "messe"]), ("фестиваль", ["festival", "fest"]),
                       ("спорт", ["sport", "fortuna", "deg ", "lauf", "marathon"]), ("вечеринка", ["party", "club", "dj"])]:
        if any(w in s for w in words): return cat
    return "событие"


# ---------- Очистка HTML для нейросети ----------
def clean_page(raw, is_rss=False, rss_items=6):
    if is_rss:
        items = re.findall(r"<item>(.*?)</item>", raw, re.S)[:rss_items]
        parts = []
        for it in items:
            title = re.search(r"<title>(.*?)</title>", it, re.S)
            body = re.search(r"<content:encoded>(.*?)</content:encoded>", it, re.S) or re.search(r"<description>(.*?)</description>", it, re.S)
            link = re.search(r"<link>(.*?)</link>", it, re.S)
            parts.append(f"## {text(title.group(1) if title else '')}\n{link.group(1) if link else ''}\n"
                         + clean_page(re.sub(r"<!\[CDATA\[|\]\]>", "", body.group(1) if body else "")))
        return "\n\n".join(parts)
    raw = re.sub(r"(?is)<(script|style|noscript|svg|iframe|head|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r'(?is)<a [^>]*href="([^"#][^"]*)"[^>]*>(.*?)</a>', lambda m: f" {m.group(2)} [{m.group(1)}] ", raw)
    raw = re.sub(r"(?i)<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", raw)
    raw = htmllib.unescape(re.sub(r"<[^>]+>", " ", raw))
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


# ---------- Gemini ----------
PROMPT = """Ниже тексты страниц с афишами событий в Дюссельдорфе и окрестностях. Сегодня {today}.
Извлеки ВСЕ конкретные события с датами от {today} до горизонта, указанного в заголовке каждого источника (по умолчанию {horizon}). Следуй указаниям под заголовком, если они есть.
Повторяющиеся (например, рынок каждую субботу) разверни в отдельные даты.
Не выдумывай: если поля нет в тексте, оставь пустую строку. Ссылку бери из текста (в квадратных скобках), относительные ссылки дополни доменом источника.
Верни JSON-массив объектов с полями:
title, date (YYYY-MM-DD), time (HH:MM или ""), end_date (YYYY-MM-DD или ""), venue, address, locality (город),
price (как в тексте, "frei"/"kostenlos" если бесплатно), url, category (одно из: концерт, театр, выставка, рынок, фестиваль, детям, вечеринка, спорт, экскурсия, важное, событие; «важное» — демонстрации, перекрытия, забастовки),
description (1 предложение по-немецки или по-английски, как в источнике), source (имя источника из заголовка === ... ===, только имя до первого «|»).

{pages}"""


def gemini_extract(batch):
    import time
    def head(s):
        hz = TODAY + timedelta(days=s.get("horizon_days", CFG.get("days_ahead", 60)))
        return f"=== {s['name']} | {s['url']} | горизонт до {hz} ===" + (f"\nУказание: {s['hint']}" if s.get("hint") else "")
    pages = "\n\n".join(f"{head(s)}\n{t[:45000]}" for s, t in batch)
    sys.path.insert(0, str(ROOT / "tools"))
    import gemini
    model, out = gemini.call(PROMPT.format(today=TODAY, horizon=HORIZON, pages=pages), kind="extract")
    items = json.loads(out)
    if isinstance(items, dict): items = items.get("events", [])
    by_name = {s["name"]: s for s, _ in batch}
    for it in items:
        src = by_name.get(it.get("source", "").split("|")[0].strip())
        if not src: continue
        it["source"] = src["name"]
        if src.get("category") and not it.get("category"): it["category"] = src["category"]
        if src.get("horizon_days"): it["horizon_days"] = src["horizon_days"]
        if src.get("big"): it["big"] = True
    return model, items


# ---------- Фильтры и дубли ----------
def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9а-я]+", "", "".join(c for c in s if not unicodedata.combining(c)))


def keep(ev):
    try:
        d = date.fromisoformat(ev.get("date", ""))
    except ValueError:
        return False
    end = ev.get("end_date") or ev["date"]
    try:
        end_d = date.fromisoformat(end)
    except ValueError:
        end_d = d
    horizon = TODAY + timedelta(days=ev["horizon_days"]) if ev.get("horizon_days") else HORIZON
    if end_d < TODAY or d > horizon or not ev.get("title"):
        return False
    if ev.get("traffic"):
        return True
    if ev.get("team"):  # матчи наших команд показываем и на выезде
        return True
    place = f"{ev.get('locality','')} {ev.get('address','')} {ev.get('venue','')}".lower()
    known_city = re.search(OTHER_CITIES, place)
    return not (known_city and not any(l in place for l in LOCALITIES))


def merge(events):
    best = {}
    for ev in events:
        k = ("match:" + ev["team"] + ev["date"]) if ev.get("team") else norm(ev["title"])[:32] + ev["date"]
        cur = best.get(k)
        better = sum(bool(v) for v in ev.values()) > sum(bool(v) for v in (cur or {}).values())
        if cur and cur.get("team") and cur.get("source") in ("OpenLigaDB", "DEG iCal"):
            better = False  # официальные данные не заменяем извлечёнными
        if not cur or better:
            if cur: ev.setdefault("also_in", []).append(cur["source"])
            best[k] = ev
        else:
            cur.setdefault("also_in", []).append(ev["source"])
    return sorted(best.values(), key=lambda e: (e["date"], e.get("time") or "99"))


def main():
    events, llm_batch = [], []
    for src in CFG["sources"]:
        try:
            raw = fetch(src["url"])
        except Exception as e:
            report.append(f"✗ {src['name']}: {e}"); continue
        found = []
        if not src.get("rss"):
            for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw, re.S | re.I):
                try: walk_events(json.loads(block.strip()), found)
                except Exception: pass
        if found:
            evs = [from_jsonld(e, src) for e in found]
            events += evs
            report.append(f"✓ {src['name']}: {len(evs)} (разметка)")
        elif src.get("llm"):
            llm_batch.append((src, clean_page(raw, src.get("rss"), src.get("rss_items", 6))))
            report.append(f"… {src['name']}: в очередь нейросети")
        else:
            report.append(f"· {src['name']}: событий не найдено")

    try:
        previous = json.loads((ROOT / "data" / "events.json").read_text())["events"]
    except Exception:
        previous = []
    if llm_batch:
        # по 7 страниц за запрос: ~4 запроса к Flash Lite в день
        for i in range(0, len(llm_batch), 7):
            chunk = llm_batch[i:i + 7]
            try:
                model, items = gemini_extract(chunk)
                events += items
                report.append(f"✓ Gemini ({model}): {len(items)} событий из {', '.join(s['name'] for s, _ in chunk)}")
            except Exception as e:
                names = {s["name"] for s, _ in chunk}
                kept = [e2 for e2 in previous if e2.get("source") in names]
                events += kept
                report.append(f"✗ Gemini: {e} — оставлены прошлые данные ({len(kept)} событий)")

    for a in json.loads((Path(__file__).parent / "annual.json").read_text())["events"]:
        events.append({**{k: "" for k in ("time", "end_date", "address", "locality", "price", "url", "description")},
                       **a, "big": True, "horizon_days": 400})
    report.append("✓ Ежегодные события (annual.json)")
    from traffic import closures
    events += closures(report)
    from toubiz import events as visit_duesseldorf
    events += visit_duesseldorf(report)
    from sports import fortuna, deg, tidy_deg, tidy_fortuna
    deg_ical = deg(report)
    if deg_ical:  # официальный календарь точнее — версию Gemini отбрасываем
        events = [e for e in events if e.get("source") != "DEG (расписание)"]
    events = tidy_fortuna(tidy_deg(events)) + fortuna(report) + deg_ical

    if GEMINI_KEY:  # список моделей не расходует лимит запросов
        try:
            ms = json.load(urllib.request.urlopen(f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}&pageSize=200", timeout=30))
            names = sorted(m["name"].split("/", 1)[1] for m in ms.get("models", []) if "flash" in m["name"])
            report.append("· Доступные модели Flash: " + ", ".join(names))
        except Exception as e:
            report.append(f"· Список моделей: {e}")

    total = len(events)
    events = merge([e for e in events if keep(e)])
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    (out / "events.json").write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="minutes"), "count": len(events), "events": events},
        ensure_ascii=False, indent=1) + "\n")

    days = {}
    for e in events: days.setdefault(e["date"], []).append(e)
    wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    md = [f"# События Дюссельдорфа\n\nСобрано {datetime.now():%d.%m.%Y %H:%M}: {len(events)} событий "
          f"(из {total} найденных до фильтра и удаления дублей).\n"]
    for d, evs in days.items():
        dd = date.fromisoformat(d)
        md.append(f"\n## {wd[dd.weekday()]} {dd:%d.%m}\n")
        for e in evs:
            bits = [e.get("time"), e.get("venue"), e.get("price") and f"💶 {e['price']}", e.get("category")]
            md.append(f"- **{e['title']}** — " + " · ".join(b for b in bits if b) + (f" — [ссылка]({e['url']})" if e.get("url") else ""))
    md.append("\n## Источники\n\n" + "\n".join(f"- {r}" for r in report))
    (out / "events.md").write_text("\n".join(md) + "\n")
    print("\n".join(report))
    print(f"Итого: {len(events)} событий")


if __name__ == "__main__":
    main()
