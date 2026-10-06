#!/usr/bin/env python3
"""Утренние сторис «Сегодня в Дюссельдорфе».

Берёт data/events.json, выбирает события на сегодня (Gemini пишет короткие тексты по-русски;
без ключа — простой отбор и оригинальные названия), рисует 1080×1920 и создаёт пост
posts/daily-YYYY-MM-DD/ со статусом scheduled на 08:00 по Берлину.

Пауза: файл AUTOPOST_PAUSED в корне репозитория — сторис не создаются.
"""
import html, json, os, re, subprocess, sys, urllib.request, urllib.error
from datetime import date, datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
TZ = ZoneInfo("Europe/Berlin")
TODAY = date.fromisoformat(os.environ["DAILY_DATE"]) if os.environ.get("DAILY_DATE") else datetime.now(TZ).date() + timedelta(days=1)
KEY = os.environ.get("GEMINI_API_KEY", "")
sys.path.insert(0, str(ROOT / "tools" / "events"))
WD = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def short(s, n):
    s = s or ""
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(" |–-,") + "…"


def load_today():
    from collect import keep
    data = json.loads((ROOT / "data" / "events.json").read_text())
    data["events"] = [e for e in data["events"] if keep(e) or e.get("source") == "Messe Düsseldorf"]
    today, ongoing, fairs, games, important = [], [], [], [], []
    for e in data["events"]:
        try:
            d = date.fromisoformat(e["date"])
            end = date.fromisoformat(e.get("end_date") or e["date"])
        except ValueError:
            continue
        if e.get("team") and d == TODAY:
            games.append(e)
        elif e.get("category") == "важное" and d <= TODAY <= end:
            # долгие стройки на автобанах не повторяем каждый день: только новые и короткие
            if not e.get("traffic") or d >= TODAY - timedelta(days=1) or (end - d).days <= 3:
                important.append(e)
        elif e.get("source") == "Messe Düsseldorf":
            if d <= TODAY <= end: fairs.append(e)
        elif d == TODAY:
            today.append(e)
        elif d < TODAY <= end:
            ongoing.append(e)
    return today, ongoing, fairs, games, important


def game_rows(games):
    """Матчи Fortuna/DEG — всегда в списке дня, отдельно от выбора Gemini."""
    rows = []
    for g in games:
        place = g["venue"] if not g.get("away") else "выезд · " + g["venue"].replace("на выезде", "").strip(" ()")
        icon = "⚽" if g["team"] == "Fortuna" else "🏒"
        rows.append({"time": g.get("time", ""), "title": f"{icon} {g['title']}", "place": place.strip(" ·")})
    return rows


PROMPT = """Ты редактор Instagram-аккаунта ТУТ.DUS — «Дюссельдорф на русском» для русскоязычных жителей.
Сегодня {day}. Ниже события на сегодня (today) и идущие сейчас выставки/фестивали (ongoing).
Выбери до 6 самых интересных для обычных жителей: разнообразно (концерт, рынок, дети, бесплатное, вечер),
без деловых выставок, без дублей, без событий не в Дюссельдорфе и соседних городах.
Не выдумывай факты: время, место и цену бери только из данных; не добавляй оценок и эпитетов («легендарный», «лучший»), которых нет в данных. Имена, названия групп и площадок оставляй в оригинале.
Верни JSON:
{{"list": [{{"time": "HH:MM или ''", "title": "по-русски, до 42 символов", "place": "площадка, до 26 символов"}}],
  "highlights": [{{"title": "по-русски, до 34 символов", "text": "одно предложение по-русски, до 95 символов, почему стоит сходить",
                   "time": "", "place": "", "price": "по-русски: бесплатно / от 15 € / ''", "tag": "концерт|рынок|детям|бесплатно|театр|вечер|выставка|фестиваль|спорт"}}]}}
highlights — 2–3 лучших из list.

today: {today}
ongoing: {ongoing}"""


def gemini_pick(today, ongoing):
    sys.path.insert(0, str(ROOT / "tools"))
    import gemini
    slim = lambda evs: [{k: e.get(k, "") for k in ("title", "time", "venue", "price", "category", "description")} for e in evs][:60]
    prompt = PROMPT.format(day=f"{WD[TODAY.weekday()]}, {TODAY.day} {MONTHS[TODAY.month-1]}",
                           today=json.dumps(slim(today), ensure_ascii=False), ongoing=json.dumps(slim(ongoing), ensure_ascii=False))
    model, out = gemini.call(prompt, kind="copy", temperature=0.4)
    print(f"Gemini: {model}")
    return json.loads(out)


def simple_pick(today, ongoing):
    evs = sorted(today, key=lambda e: e.get("time") or "99")[:6] or ongoing[:4]
    lst = [{"time": e.get("time", ""), "title": short(e["title"], 42), "place": short(e.get("venue", ""), 26)} for e in evs]
    return {"list": lst, "highlights": []}


def esc(s):
    return html.escape(str(s or ""))


def fit(s, base, long_at, small):
    return small if len(s or "") > long_at else base


def photos():
    """Фоны: ваши фото из library/photos (и кадры с Commons, пока своих мало)."""
    d = ROOT / "library" / "photos"
    listed = d / "backgrounds.txt"
    if listed.exists():
        names = [l.strip() for l in listed.read_text().splitlines() if l.strip() and not l.startswith("#") and (d / l.strip()).exists()]
        if names:
            return names
    own = sorted(p.name for p in d.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png") and not p.name.startswith("commons-"))
    return own or sorted(p.name for p in d.glob("commons-*.jpg"))


def build_html(pick, fairs, notes=(), games=()):
    """Стиль v2: город на фоне, красный — только акцент."""
    bgs = photos()
    bg = lambda i: f"../library/photos/{bgs[(TODAY.toordinal() + i) % len(bgs)]}" if bgs else ""
    day_title = f"{WD[TODAY.weekday()]}, {TODAY.day} {MONTHS[TODAY.month-1]}"
    rows = sorted(game_rows(games) + [x for x in pick["list"] if not (games and re.search(r"Fortuna|DEG|Düsseldorfer EG", x.get("title", "")))],
                  key=lambda x: x.get("time") if x.get("time") not in ("", "00:00") else "99")[:6]
    items = "".join(
        f'<div class="it"><b>{esc(i.get("time")) if i.get("time") not in ("", "00:00") else "весь день"}</b>'
        f'<span>{esc(i.get("title"))}<small>{esc(i.get("place"))}</small></span></div>' for i in rows)
    banners = list(notes)
    if fairs:
        names = ", ".join(sorted({f["title"] for f in fairs}))[:60]
        banners.append(f"На Messe сегодня {names}: на дорогах к Messe и в U78 будет многолюдно")
    pills = "".join(f'<div class="pill">{esc(b)}</div>' for b in banners[:3])
    slides = [f'''<section class="slide v2 story" id="d0"><div class="bg" style="background-image:url({bg(0)})"></div><div class="shade list-shade"></div>
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>{TODAY:%d.%m}</span></div>
  <div class="low"><div class="tag">Сегодня в городе</div><h1>{esc(day_title)}</h1>
    <div class="list">{items}</div>{pills}</div>
</section>''']
    hls = pick.get("highlights", [])[:3]
    for n, h in enumerate(hls, 1):
        title = h.get("title", "")
        meta = "".join(f'<div class="it"><b>{k}</b><span>{esc(v)}</span></div>' for k, v in (
            ("Когда", h.get("time") if h.get("time") not in ("", "00:00") else "весь день"), ("Где", h.get("place")), ("Цена", h.get("price"))) if v)
        slides.append(f'''<section class="slide v2 story" id="d{n}"><div class="bg" style="background-image:url({bg(n)})"></div><div class="shade"></div>
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>Сегодня · {n}/{len(hls)}</span></div>
  <div class="low"><div class="tag">{esc(h.get("tag") or "событие")}</div>
    <h1 style="font-size:{fit(title, 88, 22, 72)}px">{esc(title)}</h1>
    <p class="sub">{esc(h.get("text"))}</p><div class="list">{meta}</div></div>
</section>''')
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>daily</title>
<link rel="stylesheet" href="brand.css"><link rel="stylesheet" href="v2.css"><style>
  .story.v2 {{ height: 1920px; padding: 240px 80px 340px }}
  .story.v2 h1 {{ font-size: 84px }}
  .v2 .it span {{ display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden }}
  .v2 .pill + .pill {{ margin-top: 14px }}
  .v2 .shade.list-shade {{ background: linear-gradient(to bottom, rgba(12,13,15,.55) 0%, rgba(12,13,15,.70) 30%, rgba(12,13,15,.92) 70%, rgba(12,13,15,.97) 100%) }}
</style></head><body>
{chr(10).join(slides)}
</body></html>'''


def main():
    if (ROOT / "AUTOPOST_PAUSED").exists():
        print("Автопостинг на паузе (AUTOPOST_PAUSED)"); return
    post_dir = ROOT / "posts" / f"daily-{TODAY:%Y-%m-%d}"
    if (post_dir / "post.json").exists():
        print(f"{post_dir.name} уже есть"); return
    from calendar_de import notices
    today, ongoing, fairs, games, important = load_today()
    notes = notices(TODAY)
    important.sort(key=lambda e: e.get("source") == "Autobahn GmbH")  # сначала полиция и город, потом автобаны
    for e in important[:2]:  # демонстрации, перекрытия — плашкой
        when = f" с {e['time']}" if e.get("time") and e["time"] != "00:00" else ""
        notes.append(f"Внимание{when}: {e['title']}" + (f" ({e['venue']})" if e.get("venue") else ""))
    if not today and not ongoing and not games and not notes:
        print("На сегодня событий нет — сторис не делаем"); return
    try:
        pick = gemini_pick(today, ongoing) if (today or ongoing) else {"list": [], "highlights": []}
    except Exception as e:
        print(f"Gemini: {e} — простой отбор"); pick = simple_pick(today, ongoing)
    if not pick.get("list") and not games and not notes:
        print("Нечего показать"); return
    (ROOT / "design" / "_daily.html").write_text(build_html(pick, fairs, notes, games))
    post_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["node", "render.cjs", "_daily.html", str(post_dir)], cwd=ROOT / "design", check=True)
    (ROOT / "design" / "_daily.html").unlink()
    media = sorted(p.name for p in post_dir.glob("d*.png"))
    publish_at = datetime.combine(TODAY, dtime(8, 0), TZ).isoformat()
    lines = [f"Сегодня в Дюссельдорфе — {WD[TODAY.weekday()].lower()}, {TODAY.day} {MONTHS[TODAY.month-1]}", ""]
    for b in notes:
        lines.append(f"⚠️ {b}")
    if notes: lines.append("")
    rows = game_rows(games) + [x for x in pick["list"] if not (games and re.search(r"Fortuna|DEG|Düsseldorfer EG", x.get("title", "")))]
    for r in sorted(rows, key=lambda x: x.get("time") if x.get("time") not in ("", "00:00") else "99"):
        t = r.get("time") if r.get("time") not in ("", "00:00") else "весь день"
        lines.append(f"{t} — {r.get('title')}" + (f" ({r['place']})" if r.get("place") else ""))
    for h in pick.get("highlights", [])[:3]:
        if h.get("text"):
            lines += ["", f"▫️ {h['title']}: {h['text']}" + (f" {h['price'].capitalize()}." if h.get("price") else "")]
    lines += ["", "Instagram: instagram.com/tut.dus"]
    (post_dir / "telegram.txt").write_text("\n".join(lines) + "\n")
    (post_dir / "pick.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1))
    (post_dir / "post.json").write_text(json.dumps(
        {"type": "story", "status": "scheduled", "publish_at": publish_at, "media": media, "auto": True},
        ensure_ascii=False, indent=2))
    print(f"✓ {post_dir.name}: {len(media)} сторис на {publish_at}")


if __name__ == "__main__":
    main()
