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
sys.path.insert(0, str(ROOT / "tools" / "stories"))
WD = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


# подпись списка меняется день ото дня, чтобы сторис не выглядели одинаково
COVER_TAGS = ["Сегодня в городе", "Куда сходить сегодня", "План на день", "Что происходит сегодня", "Дюссельдорф сегодня"]
# первая сторис — приветствие: с читателем здоровается человек, а не табло (docs/voice.md)
HELLO = ["Новая неделя!", "Доброе утро!", "Доброе утро!", "Доброе утро!", "Пятница!", "Суббота!", "Воскресенье!"]
# последняя сторис прощается и зовёт ответить — так появляется разговор
BYE = ["Хорошей недели! Сходите куда-нибудь из списка — ответьте на эту сторис, расскажите, как было.",
       "Хорошего дня! Знаете что-то, чего нет в списке? Ответьте на эту сторис — добавим.",
       "Хорошего дня! А вы куда сегодня? Ответьте на эту сторис.",
       "Хорошего дня! Завтра вечером расскажем про выходные.",
       "Хорошей пятницы! Планы на выходные уже в ленте. А какие у вас? Ответьте на эту сторис.",
       "Хорошей субботы! Нашли в городе что-то классное — пришлите нам, покажем всем.",
       "Хорошего воскресенья! Магазины закрыты, город открыт. Как проводите день? Ответьте на эту сторис."]


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


MARKET = re.compile(r"tr[öo]del|floh|antik|kinder(sachen)?markt|schallplatten|radschläger|fischmarkt|nachtmarkt|moonlight market|mädels", re.I)


def markets_today(today):
    """Барахолки и рынки дня — отдельным слайдом, чтобы в общем списке на 6 строк не терялись
    (8.11.2026 из пяти рынков в сводку попали два, Гросмаркт выпал)."""
    out, seen = [], set()
    for e in sorted(today, key=lambda e: (not e.get("time"), e.get("time") or "")):
        title = html.unescape(e.get("title", ""))
        if not MARKET.search(title) or re.search(r"weihnacht|advent|konzert|jazz|lesung|\bafter\b|party", title, re.I):
            continue
        venue = html.unescape(e.get("venue", ""))
        place = re.sub(r"\s*D(ü|ue)sseldorf(er)?\b[-\s]*", " ", venue).strip(" ,-") or venue
        place = re.sub(r"^(am|an der|auf dem)\s+", "", place)
        key = (re.sub(r"[^a-zäöüß]", "", place.lower())[:12], re.sub(r"[^a-zäöüß]", "", title.lower())[:8])
        if key in seen:
            continue
        seen.add(key)
        name = re.sub(r"(\s+(in|an der|am|@))?\s*@?\s*\bD(ü|ue|Ü|UE)sseldorf\b", "", title, flags=re.I).strip(" -–")
        if re.search(r"ulmenstra(ß|ss)e 275", place, re.I):
            place = "Blumengroßmarkt"
        late = bool(re.search(r"nacht|night|moonlight", title, re.I))
        out.append({"time": e.get("time", ""), "title": short(name, 40), "place": short(place, 30),
                    "when": e.get("time") or ("вечером" if late else "днём")})
    return out


def game_rows(games):
    """Матчи Fortuna/DEG — всегда в списке дня, отдельно от выбора Gemini."""
    rows = []
    for g in games:
        place = g["venue"] if not g.get("away") else "выезд · " + g["venue"].replace("на выезде", "").strip(" ()")
        icon = "⚽" if g["team"] == "Fortuna" else "🏒"
        rows.append({"time": g.get("time", ""), "title": f"{icon} {g['title']}", "place": place.strip(" ·")})
    return rows


PROMPT = """Ты редактор Instagram-аккаунта ТУТ.DUS — «Дюссельдорф на русском» для русскоязычных жителей.
{voice}

Сегодня {day}. Погода: {weather}. Ниже события на сегодня (today) и идущие сейчас выставки/фестивали (ongoing).
Выбери до 6 самых интересных для обычных жителей: разнообразно (концерт, рынок, дети, бесплатное, вечер).
Бесплатные события (price: frei/kostenlos/freier Eintritt/бесплатно), особенно бесплатный вход в музеи, обязательно включай и ставь в highlights;
без деловых выставок, без дублей, без событий не в Дюссельдорфе и соседних городах.
Время, место, цену и то, что именно будет, бери только из данных. Имена, названия групп и площадок оставляй в оригинале.
Верни JSON:
{{"hello": "1–2 короткие фразы от редакции, до 110 символов: по-человечески про сегодняшний день — погода, день недели и что из выбранного под них подходит. Без «доброе утро» (оно уже в заголовке), без перечисления цифр погоды",
  "list": [{{"time": "HH:MM или ''", "title": "по-русски, понятно что это, до 42 символов", "place": "площадка, до 26 символов"}}],
  "highlights": [{{"title": "по-русски, до 34 символов", "text": "1–2 фразы до 115 символов: как сосед советует другу — что там будет и кому зайдёт",
                   "time": "", "place": "", "price": "по-русски: бесплатно / от 15 € / ''", "tag": "концерт|рынок|детям|бесплатно|театр|вечер|выставка|фестиваль|спорт"}}]}}
highlights — {n_hl} лучших из list; первый — то, куда редакция пошла бы сама (на слайде он будет с пометкой «Наш выбор»).{hint}

today: {today}
ongoing: {ongoing}"""


def rank_ongoing(ongoing):
    """Идущих выставок бывает сотни: в выбор отдаём фестивали/рынки и то, что недавно открылось или скоро закроется."""
    def score(e):
        start, end = date.fromisoformat(e["date"]), date.fromisoformat(e.get("end_date") or e["date"])
        big = e.get("big") or e.get("category") in ("фестиваль", "рынок", "детям")
        fresh = (TODAY - start).days <= 7
        closing = (end - TODAY).days <= 7
        return (not big, not (fresh or closing), (end - TODAY).days)
    return sorted(ongoing, key=score)[:25]


def gemini_pick(today, ongoing, weather=None, n_hl=3):
    sys.path.insert(0, str(ROOT / "tools"))
    import gemini
    from voice import VOICE
    slim = lambda evs: [{k: e.get(k, "") for k in ("title", "time", "venue", "price", "category", "description")} for e in evs][:60]
    import insights
    hint = insights.hints()
    if hint:
        print("Статистика:", hint)
    wtext = f"{weather['temp']}, {weather['text']}" if weather else "нет данных — про погоду не пиши"
    prompt = PROMPT.format(voice=VOICE, weather=wtext, n_hl="2" if n_hl == 2 else "2–3",
                           hint=f"\nСтатистика аккаунта: {hint}." if hint else "", day=f"{WD[TODAY.weekday()]}, {TODAY.day} {MONTHS[TODAY.month-1]}",
                           today=json.dumps(slim(today), ensure_ascii=False), ongoing=json.dumps(slim(rank_ongoing(ongoing)), ensure_ascii=False))
    model, out = gemini.call(prompt, kind="copy", temperature=0.7)
    print(f"Gemini: {model}")
    return json.loads(out)


def simple_pick(today, ongoing):
    evs = sorted(today, key=lambda e: e.get("time") or "99")[:6] or rank_ongoing(ongoing)[:4]
    lst = [{"time": e.get("time", ""), "title": short(e["title"], 42), "place": short(e.get("venue", ""), 26)} for e in evs]
    return {"list": lst, "highlights": []}


# фон приветствия подбираем под погоду: в дождь — вечерние огни и вода, в солнце — парки и набережная
# (утром — только дневные кадры: ночные делают приветствие мрачным)
WEATHER_BG = {"rain": ["water", "street"], "sun": ["park", "rhein", "green"], "fog": ["bridge", "rhein"],
              "snow": ["winter", "park"], "storm": ["water"], "cloud": []}


def wline(weather, day):
    sys.path.insert(0, str(ROOT / "tools"))
    from weather import line
    return line(weather, day)


def esc(s):
    return html.escape(str(s or ""))


def fit(s, base, long_at, small):
    return small if len(s or "") > long_at else base


def background(picker, wanted, min_video, avoid=()):
    """Фон слайда по смыслу (tools/stories/backgrounds.py): фото, видео или фирменный.
    Возвращает (html фона, подпись автора, запись о видео или None)."""
    try:
        got = picker.pick(wanted, min_video=min_video, avoid=avoid)
    except Exception as e:  # фон никогда не должен ломать сторис
        print(f"Фон: {e} — фирменный фон")
        got = None
    credit = f'<div class="credit">{esc(got["credit"])}</div>' if got and got.get("credit") else ""
    if not got:
        return '<div class="bg brand"></div>', "", None
    if got["file"].endswith(".mp4"):
        return "", credit, {"video": got["file"]}
    return f'<div class="bg" style="background-image:url(../library/{got["file"]})"></div>', credit, None


def build_html(pick, fairs, notes=(), games=(), picker=None, markets=(), weather=None, n_hl=3):
    """Стиль v2: город на фоне, красный — только акцент. Возвращает (html, {id слайда: видео-фон})."""
    from backgrounds import Picker, GENERIC, themes
    picker = picker or Picker(TODAY)
    videos, credits = {}, {}

    def bg_for(sid, wanted, min_video, avoid=()):
        html_bg, credit, video = background(picker, wanted, min_video, avoid)
        if video:
            videos[sid] = video
        credits[sid] = credit
        return html_bg, (" overlay" if video else "")
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
    # 1) приветствие: погода и фраза от редакции — город виден, текста мало
    weekday_tag = f"{WD[TODAY.weekday()]} · {TODAY.day} {MONTHS[TODAY.month-1]}"
    hello = (pick.get("hello") or "").strip() or wline(weather, TODAY)
    wx = ""
    if weather:
        wx = (f'<div class="wx"><b>{esc(weather["temp"])}</b><span>{esc(weather["text"])}'
              f'<small>прогноз {esc(weather["source"])}</small></span></div>')
    hi_bg, hi_cls = bg_for("d0", WEATHER_BG.get((weather or {}).get("kind"), []) + GENERIC, 6, avoid=("night", "evening"))
    slides = [f'''<section class="slide v2 story{hi_cls}" id="d0">{hi_bg}<div class="shade soft"></div>
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>{TODAY:%d.%m}</span></div>
  <div class="low"><div class="tag">{esc(weekday_tag)}</div><h1 class="hello">{HELLO[TODAY.weekday()]}</h1>
    {wx}<p class="sub say">{esc(hello)}</p><div class="pill">Дальше — план на день</div></div>{credits["d0"]}
</section>''']
    # 2) список дня
    lead = (pick.get("highlights") or [{}])[0]
    cover_bg, cover_cls = bg_for("d1", themes(lead.get("title", ""), lead.get("place", ""), "")[:1] + GENERIC, 7.5)
    slides.append(f'''<section class="slide v2 story{cover_cls}" id="d1">{cover_bg}<div class="shade list-shade"></div>
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>{TODAY:%d.%m}</span></div>
  <div class="low"><div class="tag">{COVER_TAGS[TODAY.toordinal() % len(COVER_TAGS)]}</div><h1>{esc(day_title)}</h1>
    <div class="list">{items}</div>{pills}<!--bye--></div>{credits["d1"]}
</section>''')
    # 3) карточки: первая — «Наш выбор»
    hls = pick.get("highlights", [])[:n_hl]
    for n, h in enumerate(hls, 1):
        sid = f"d{n + 1}"
        title = h.get("title", "")
        meta = "".join(f'<div class="it"><b>{k}</b><span>{esc(v)}</span></div>' for k, v in (
            ("Когда", h.get("time") if h.get("time") not in ("", "00:00") else "весь день"), ("Где", h.get("place")), ("Цена", h.get("price"))) if v)
        hl_bg, hl_cls = bg_for(sid, themes(f"{title} {h.get('text', '')}", h.get("place", ""), h.get("tag", "")), 6)
        tag = h.get("tag") or "событие"
        tag_html = (f'<div class="tag ours">Наш выбор</div><div class="tag">{esc(tag)}</div>' if n == 1
                    else f'<div class="tag">{esc(tag)}</div>')
        slides.append(f'''<section class="slide v2 story{hl_cls}" id="{sid}">{hl_bg}<div class="shade"></div>
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>Сегодня · {n}/{len(hls)}</span></div>
  <div class="low"><div class="tags">{tag_html}</div>
    <h1 style="font-size:{fit(title, 88, 22, 72)}px">{esc(title)}</h1>
    <p class="sub">{esc(h.get("text"))}</p><div class="list">{meta}</div><!--bye--></div>{credits[sid]}
</section>''')
    if len(markets) >= 2:
        n = len(slides)
        rows_m = "".join(
            f'<div class="it"><b>{esc(m.get("when") or "днём")}</b>'
            f'<span>{esc(m["title"])}<small>{esc(m["place"])}</small></span></div>' for m in markets[:7])
        m_bg, m_cls = bg_for(f"d{n}", themes("Trödelmarkt Flohmarkt", "", "рынок") + GENERIC, 6)
        slides.append(f'''<section class="slide v2 story{m_cls}" id="d{n}">{m_bg}<div class="shade list-shade"></div>
  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>{TODAY:%d.%m}</span></div>
  <div class="low"><div class="tag">Барахолки и рынки</div><h1>Где порыться сегодня</h1>
    <div class="list">{rows_m}</div><div class="pill">Время уточняйте у организаторов — бывает, что рынок отменяют из-за погоды</div><!--bye--></div>{credits[f"d{n}"]}
</section>''')
    # прощание — на последней сторис
    slides[-1] = slides[-1].replace("<!--bye-->", f'<p class="bye">{esc(BYE[TODAY.weekday()])}</p>')
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>daily</title>
<link rel="stylesheet" href="brand.css"><link rel="stylesheet" href="v2.css"><style>
  .story.v2 {{ height: 1920px; padding: 240px 80px 340px }}
  .story.v2 h1 {{ font-size: 84px }}
  .v2 .it span {{ display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden }}
  .v2 .pill + .pill {{ margin-top: 14px }}
  /* приветствие: фото города почти без затемнения, темнеет только под текстом */
  .v2 .shade.soft {{ background: linear-gradient(to bottom, rgba(12,13,15,.30) 0%, rgba(12,13,15,.05) 18%, rgba(12,13,15,.10) 42%, rgba(12,13,15,.78) 62%, rgba(12,13,15,.93) 100%) }}
  .story.v2 h1.hello {{ font-size: 112px }}
  .v2 .wx {{ display: flex; align-items: center; gap: 30px; margin: 34px 0 6px }}
  .v2 .wx b {{ font: 900 96px/1 var(--display); letter-spacing: -.04em; white-space: nowrap }}
  .v2 .wx span {{ font: 600 38px/1.2 var(--body) }}
  .v2 .wx small {{ display: block; font: 400 22px/1.3 var(--body); opacity: .55; margin-top: 6px }}
  .v2 .sub.say {{ font-size: 44px; line-height: 1.28; margin: 26px 0 34px }}
  .v2 .tags {{ display: flex; gap: 14px; flex-wrap: wrap }}
  .v2 .tag.ours {{ background: var(--red); color: #fff }}
  .v2 .tag.ours::before {{ background: #fff }}
  .v2 .bye {{ margin-top: 40px; font: 500 32px/1.35 var(--body); opacity: .82 }}
  .v2 .shade.list-shade {{ background: linear-gradient(to bottom, rgba(12,13,15,.55) 0%, rgba(12,13,15,.70) 30%, rgba(12,13,15,.92) 70%, rgba(12,13,15,.97) 100%) }}
</style></head><body>
{chr(10).join(slides)}
</body></html>''', videos


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
        venue = e.get("venue", "")
        same = venue and (venue in e["title"] or e["title"].split(":", 1)[-1].strip() in venue)
        notes.append(f"Внимание{when}: {e['title']}" + (f" ({venue})" if venue and not same else ""))
    if not today and not ongoing and not games and not notes:
        print("На сегодня событий нет — сторис не делаем"); return
    markets = markets_today(today)
    if len(markets) >= 2:  # рынки покажем своим слайдом, а места в общем списке отдадим остальному
        today = [e for e in today if not MARKET.search(e.get("title", ""))]
    n_hl = 2 if len(markets) >= 2 else 3  # сторис не больше шести: приветствие, список, карточки, рынки
    sys.path.insert(0, str(ROOT / "tools"))
    from weather import forecast
    weather = forecast(TODAY)
    print("Погода:", weather)
    try:
        pick = gemini_pick(today, ongoing, weather, n_hl) if (today or ongoing) else {"list": [], "highlights": []}
    except Exception as e:
        print(f"Gemini: {e} — простой отбор"); pick = simple_pick(today, ongoing)
    if len(markets) >= 2:
        pick.setdefault("list", [])[5:] = []
        pick["list"].append({"time": "", "title": f"Барахолки и рынки: {len(markets)}", "place": "список — в сторис дальше"})
    if not pick.get("list") and not games and not notes and len(markets) < 2:
        print("Нечего показать"); return
    from backgrounds import Picker
    picker = Picker(TODAY)
    page, video_bgs = build_html(pick, fairs, notes, games, picker, markets, weather, n_hl)
    (ROOT / "design" / "_daily.html").write_text(page)
    post_dir.mkdir(parents=True, exist_ok=True)
    if video_bgs:  # слайды поверх видео: to_video склеит их с футажом
        (post_dir / "backgrounds.json").write_text(json.dumps(video_bgs, indent=1) + "\n")
    subprocess.run(["node", "render.cjs", "_daily.html", str(post_dir)], cwd=ROOT / "design", check=True)
    (ROOT / "design" / "_daily.html").unlink()
    media = sorted(p.name for p in post_dir.glob("d*.png"))
    publish_at = datetime.combine(TODAY, dtime(8, 0), TZ).isoformat()
    from voice import stamps
    hello = (pick.get("hello") or "").strip() or wline(weather, TODAY)
    lines = [f"{HELLO[TODAY.weekday()]} Сегодня в Дюссельдорфе — {WD[TODAY.weekday()].lower()}, {TODAY.day} {MONTHS[TODAY.month-1]}"]
    if weather:
        lines.append(f"🌡 {weather['temp']}, {weather['text']}")
    if hello:
        lines += ["", hello]
    lines.append("")
    found = stamps(json.dumps(pick, ensure_ascii=False))
    if found:
        print("::warning::штампы в тексте:", ", ".join(found))
    for b in notes:
        lines.append(f"⚠️ {b}")
    if notes: lines.append("")
    rows = game_rows(games) + [x for x in pick["list"] if not (games and re.search(r"Fortuna|DEG|Düsseldorfer EG", x.get("title", "")))]
    rows = [r for r in rows if r.get("place") != "список — в сторис дальше"]  # в Telegram рынки идут списком ниже
    for r in sorted(rows, key=lambda x: x.get("time") if x.get("time") not in ("", "00:00") else "99"):
        t = r.get("time") if r.get("time") not in ("", "00:00") else "весь день"
        lines.append(f"{t} — {r.get('title')}" + (f" ({r['place']})" if r.get("place") else ""))
    for h in pick.get("highlights", [])[:n_hl]:
        if h.get("text"):
            lines += ["", f"▫️ {h['title']}: {h['text']}" + (f" {h['price'].capitalize()}." if h.get("price") else "")]
    if len(markets) >= 2:
        lines += ["", "🧺 Барахолки и рынки:"]
        lines += [f"{m.get('when') or 'днём'} — {m['title']} ({m['place']})" for m in markets]
    lines += ["", "Instagram: instagram.com/tut.dus"]
    (post_dir / "telegram.txt").write_text("\n".join(lines) + "\n")
    (post_dir / "pick.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1))
    (post_dir / "post.json").write_text(json.dumps(
        {"type": "story", "status": "scheduled", "publish_at": publish_at, "media": media, "auto": True},
        ensure_ascii=False, indent=2))
    picker.save()
    print(f"✓ {post_dir.name}: {len(media)} сторис на {publish_at}")
    # к картинкам через API музыку не добавить — делаем из сторис короткие видео с треком
    from to_video import convert
    try:
        convert(post_dir)
    except Exception as e:
        print(f"Видео не собралось ({e}) — останутся картинки")


if __name__ == "__main__":
    main()
