#!/usr/bin/env python3
"""Утренние сторис «Сегодня в Дюссельдорфе».

Берёт data/events.json, выбирает события на сегодня (Gemini пишет короткие тексты по-русски;
без ключа — простой отбор и оригинальные названия), рисует 1080×1920 и создаёт пост
posts/daily-YYYY-MM-DD/ со статусом scheduled на 08:00 по Берлину.

Пауза: файл AUTOPOST_PAUSED в корне репозитория — сторис не создаются.
"""
import html, json, os, re, subprocess, sys, urllib.request, urllib.error
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
TZ = ZoneInfo("Europe/Berlin")
TODAY = date.fromisoformat(os.environ["DAILY_DATE"]) if os.environ.get("DAILY_DATE") else datetime.now(TZ).date()
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
    today, ongoing, fairs, games = [], [], [], []
    for e in data["events"]:
        try:
            d = date.fromisoformat(e["date"])
            end = date.fromisoformat(e.get("end_date") or e["date"])
        except ValueError:
            continue
        if e.get("team") and d == TODAY:
            games.append(e)
        elif e.get("source") == "Messe Düsseldorf":
            if d <= TODAY <= end: fairs.append(e)
        elif d == TODAY:
            today.append(e)
        elif d < TODAY <= end:
            ongoing.append(e)
    return today, ongoing, fairs, games


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
    from collect import gemini_models  # тот же выбор модели и запасные варианты
    slim = lambda evs: [{k: e.get(k, "") for k in ("title", "time", "venue", "price", "category", "description")} for e in evs][:60]
    prompt = PROMPT.format(day=f"{WD[TODAY.weekday()]}, {TODAY.day} {MONTHS[TODAY.month-1]}",
                           today=json.dumps(slim(today), ensure_ascii=False), ongoing=json.dumps(slim(ongoing), ensure_ascii=False))
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    import time
    last, deadline = None, time.time() + int(os.environ.get("GEMINI_WAIT", "1200"))
    models = gemini_models()[:3]
    while True:  # перегрузки у Gemini обычно короткие — повторяем по кругу до дедлайна
        for model in models:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={KEY}",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
            try:
                resp = json.load(urllib.request.urlopen(req, timeout=180))
                out = "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"])
                pick = json.loads(out)
                print(f"Gemini: {model}")
                return pick
            except Exception as e:
                last = f"{model}: {e}"
        if time.time() > deadline:
            raise RuntimeError(f"Gemini недоступен: {last}")
        print(f"Gemini занят ({last}), повтор через 90 с")
        time.sleep(90)


def simple_pick(today, ongoing):
    evs = sorted(today, key=lambda e: e.get("time") or "99")[:6] or ongoing[:4]
    lst = [{"time": e.get("time", ""), "title": short(e["title"], 42), "place": short(e.get("venue", ""), 26)} for e in evs]
    return {"list": lst, "highlights": []}


def esc(s):
    return html.escape(str(s or ""))


def fit(s, base, long_at, small):
    return small if len(s or "") > long_at else base


def build_html(pick, fairs, notes=(), games=()):
    day_title = f"{WD[TODAY.weekday()]}, {TODAY.day} {MONTHS[TODAY.month-1]}"
    rows = "".join(
        f'<div class="ev"><span class="t">{esc(i.get("time")) if i.get("time") not in ("", "00:00") else "весь день"}</span>'
        f'<span class="n">{esc(i.get("title"))}<small>{esc(i.get("place"))}</small></span></div>'
        for i in sorted(game_rows(games) + [x for x in pick["list"] if not (games and re.search(r"Fortuna|DEG|Düsseldorfer EG", x.get("title", "")))],
                        key=lambda x: x.get("time") if x.get("time") not in ("", "00:00") else "99")[:6])
    banners = list(notes)
    if fairs:
        names = ", ".join(sorted({f["title"] for f in fairs}))[:60]
        banners.append(f"На Messe сегодня {names}: на дорогах к Messe и в U78 будет многолюдно")
    fair = "".join(f'<div class="fair">{esc(b)}</div>' for b in banners[:2])
    slides = [f'''<section class="slide red story" id="d0">
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>{TODAY:%d.%m}</span></div>
  <div class="content">
    <span class="chip">СЕГОДНЯ</span>
    <h1>{esc(day_title)}</h1>
    <div class="evs">{rows}</div>
    {fair}
  </div>
</section>''']
    for n, h in enumerate(pick.get("highlights", [])[:3], 1):
        cls = "ink" if n % 2 else "red"
        title = h.get("title", "")
        meta = " · ".join(x for x in [h.get("time") if h.get("time") != "00:00" else "весь день", h.get("place")] if x)
        slides.append(f'''<section class="slide {cls} story" id="d{n}">
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>Сегодня · {n}/{len(pick["highlights"][:3])}</span></div>
  <div class="content">
    <span class="chip">{esc((h.get("tag") or "событие").upper())}</span>
    <h1 style="font-size:{fit(title, 104, 22, 84)}px">{esc(title)}</h1>
    <p class="lead">{esc(h.get("text"))}</p>
    <div class="meta">{esc(meta)}</div>
    {f'<div class="price">{esc(h.get("price"))}</div>' if h.get("price") else ""}
  </div>
</section>''')
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>daily</title>
<link rel="stylesheet" href="brand.css"><style>
  .story {{ height: 1920px; padding: 260px 88px 380px }}
  .story h1 {{ font-size: 96px; margin-bottom: 8px }}
  .chip {{ display:inline-block; background: var(--white); color: var(--red); font: 700 30px/1 var(--display);
          padding: 16px 24px; border-radius: 99px; align-self: flex-start; margin-bottom: 36px; letter-spacing: .06em }}
  .ink .chip {{ background: var(--red); color: var(--white) }}
  .evs {{ display: grid; gap: 0; margin-top: 48px }}
  .ev {{ display: grid; grid-template-columns: 170px 1fr; gap: 24px; padding: 22px 0; border-top: 2px solid rgba(255,255,255,.3) }}
  .ev .t {{ font: 700 36px/1.2 var(--display) }}
  .ev .n {{ font: 600 38px/1.2 var(--body); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden }}
  .ev .n small {{ display: block; font: 400 30px/1.3 var(--body); opacity: .8; margin-top: 6px }}
  .fair + .fair {{ margin-top: 16px }}
  .fair {{ margin-top: 36px; font: 500 30px/1.35 var(--body); background: rgba(0,0,0,.18); padding: 22px 26px; border-radius: 18px }}
  .meta {{ margin-top: 48px; font: 700 40px/1.3 var(--display) }}
  .price {{ margin-top: 20px; font: 500 36px/1.3 var(--body); opacity: .85 }}
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
    today, ongoing, fairs, games = load_today()
    notes = notices(TODAY)
    if not today and not ongoing and not games and not notes:
        print("На сегодня событий нет — сторис не делаем"); return
    try:
        pick = (gemini_pick(today, ongoing) if KEY else simple_pick(today, ongoing)) if (today or ongoing) else {"list": [], "highlights": []}
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
    (post_dir / "pick.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1))
    (post_dir / "post.json").write_text(json.dumps(
        {"type": "story", "status": "scheduled", "publish_at": publish_at, "media": media, "auto": True},
        ensure_ascii=False, indent=2))
    print(f"✓ {post_dir.name}: {len(media)} сторис на {publish_at}")


if __name__ == "__main__":
    main()
