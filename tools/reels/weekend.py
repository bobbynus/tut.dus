#!/usr/bin/env python3
"""Рилс «Выходные за 30 секунд»: 4–5 главных событий пятницы–воскресенья на фоне города, с музыкой.

Запускается в среду вечером (workflow «Weekend reel», страхуется из «часов»). Собирает posts/r-weekend-<пятница>/:
reel.mp4, cover.jpg, caption.txt, post.json со статусом manual — бот присылает черновик владельцу,
он публикует в четверг 19:00 из приложения с трендовым звуком. Gemini — 1 запрос в неделю (тексты по-русски);
без него — простой отбор и оригинальные названия.
Окружение: WEEKEND_FRIDAY=YYYY-MM-DD — для какой пятницы (по умолчанию ближайшая), NO_LLM=1 — без нейросети.
"""
import json, os, re, subprocess, sys
from datetime import date, datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
TZ = ZoneInfo("Europe/Berlin")
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools" / "stories"), str(ROOT / "tools" / "events")]
now = datetime.now(TZ).date()
FRI = date.fromisoformat(os.environ["WEEKEND_FRIDAY"]) if os.environ.get("WEEKEND_FRIDAY") else now + timedelta(days=(4 - now.weekday()) % 7 or 7)
DAYS = [FRI, FRI + timedelta(days=1), FRI + timedelta(days=2)]
os.environ.setdefault("DAILY_DATE", FRI.isoformat())  # daily.py берёт отсюда дату для фонов
import daily  # noqa: E402  (esc, short, background)
from backgrounds import Picker, GENERIC, themes  # noqa: E402

WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = daily.MONTHS
GOOD = {"фестиваль": 5, "рынок": 4, "концерт": 3, "детям": 3, "спорт": 3, "театр": 2, "вечеринка": 2, "выставка": 1}


def candidates():
    from collect import keep
    evs = json.loads((ROOT / "data" / "events.json").read_text())["events"]
    out = []
    for e in evs:
        if e.get("traffic") or e.get("category") == "важное" or not keep(e):
            continue
        try:
            d = date.fromisoformat(e["date"]); end = date.fromisoformat(e.get("end_date") or e["date"])
        except ValueError:
            continue
        if not (d <= DAYS[-1] and end >= DAYS[0]):
            continue
        long_run = (end - d).days > 3
        if long_run and not e.get("big") and e.get("category") not in ("фестиваль", "рынок"):
            continue  # многонедельные выставки — не «на выходные»
        score = GOOD.get(e.get("category"), 1) + (4 if e.get("big") else 0) + (3 if e.get("team") else 0)
        score += 2 if re.search(r"frei|kostenlos|бесплат", (e.get("price") or "").lower()) else 0
        out.append((score, e))
    out.sort(key=lambda x: (-x[0], x[1]["date"], x[1].get("time") or "99"))
    seen, picked = set(), []
    for _, e in out:
        key = re.sub(r"\W+", "", e["title"].lower())[:24]
        if key not in seen:
            seen.add(key); picked.append(e)
    return picked[:25]


PROMPT = """Ты редактор Instagram ТУТ.DUS — «Дюссельдорф на русском». Делаем рилс «Выходные за 30 секунд» на {days}.
Из событий ниже выбери 5 самых интересных и разных для обычных жителей (семьи, концерты, рынки, спорт, бесплатное).
Не выдумывай: дни, время, место бери только из данных. Без оценок, которых нет в данных. Названия групп и площадок — в оригинале.
Верни JSON: {{"items": [{{"day": "пт|сб|вс|пт–вс", "time": "HH:MM или ''", "title": "по-русски, до 30 символов",
"text": "одна фраза по-русски, до 70 символов", "place": "площадка, до 24 символов", "tag": "концерт|рынок|детям|бесплатно|спорт|фестиваль|театр|вечер"}}]}}
События: {events}"""


def pick(cands):
    slim = [{k: e.get(k, "") for k in ("title", "date", "end_date", "time", "venue", "price", "category", "description")} for e in cands]
    days = f"{FRI.day}–{DAYS[-1].day} {MONTHS[DAYS[-1].month - 1]}"
    try:
        import gemini
        model, out = gemini.call(PROMPT.format(days=days, events=json.dumps(slim, ensure_ascii=False)), kind="copy", temperature=0.4)
        items = json.loads(out)["items"][:5]
        print(f"Gemini: {model}")
        return items
    except Exception as e:
        print(f"Gemini: {e} — простой отбор")
    res = []
    for e in cands[:5]:
        d = date.fromisoformat(e["date"])
        day = WD[max(d, DAYS[0]).weekday()] if not e.get("end_date") or e["end_date"] == e["date"] else "пт–вс"
        res.append({"day": day, "time": e.get("time", ""), "title": daily.short(e["title"], 30),
                    "text": daily.short(e.get("description", ""), 70), "place": daily.short(e.get("venue", ""), 24),
                    "tag": e.get("category", "")})
    return res


def build(items, post_dir):
    picker = Picker(FRI)
    days = f"{FRI.day}–{DAYS[-1].day} {MONTHS[DAYS[-1].month - 1]}"
    slides, videos = [], {}

    def slide(sid, wanted, body, shade="shade"):
        bg, credit, video = daily.background(picker, wanted, 5)
        if video:
            videos[sid] = video
        cls = " overlay" if video else ""
        return (f'<section class="slide v2 story{cls}" id="{sid}">{bg}<div class="{shade}"></div>'
                f'<div class="top"><span class="logo">ТУТ<i>.DUS</i></span><span>Выходные</span></div>'
                f'<div class="low">{body}</div>{credit}</section>')

    esc = daily.esc
    slides.append(slide("w0", GENERIC, f'<div class="tag">Куда пойти</div><h1 style="font-size:112px">Выходные {esc(days)}</h1>'
                                       f'<p class="sub">{len(items)} идей на пятницу, субботу и воскресенье</p>'))
    for n, it in enumerate(items, 1):
        when = " · ".join(x for x in (it.get("day"), it.get("time")) if x)
        slides.append(slide(f"w{n}", themes(f"{it.get('title', '')} {it.get('text', '')}", it.get("place", ""), it.get("tag", "")),
                            f'<div class="tag">{esc(when)}</div><h1>{esc(it.get("title"))}</h1>'
                            f'<p class="sub">{esc(it.get("text"))}</p><div class="list"><div class="it"><b>Где</b>'
                            f'<span>{esc(it.get("place"))}</span></div></div>'))
    slides.append(slide(f"w{len(items) + 1}", GENERIC,
                        '<div class="tag">Каждый день</div><h1>Сохрани и отправь другу</h1>'
                        '<p class="sub">Что происходит сегодня — каждое утро в сторис. Подробности и ссылки — в Telegram: t.me/tutdus</p>'))
    page = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>weekend</title>'
            '<link rel="stylesheet" href="brand.css"><link rel="stylesheet" href="v2.css"><style>'
            '.story.v2 { height: 1920px; padding: 260px 84px 380px } .story.v2 h1 { font-size: 92px }</style></head><body>'
            + "\n".join(slides) + "</body></html>")
    tmp = ROOT / "design" / "_weekend.html"
    tmp.write_text(page)
    try:
        subprocess.run(["node", "render.cjs", tmp.name, str(post_dir)], cwd=ROOT / "design", check=True)
    finally:
        tmp.unlink(missing_ok=True)
    picker.save()
    return [f"w{i}" for i in range(len(slides))], videos


def main():
    post_dir = ROOT / "posts" / f"r-weekend-{FRI}"
    if (post_dir / "post.json").exists():
        print(f"{post_dir.name} уже есть"); return
    cands = candidates()
    if len(cands) < 3:
        print("На выходные мало событий — рилс не делаем"); return
    items = pick(cands)
    post_dir.mkdir(parents=True, exist_ok=True)
    ids, videos = build(items, post_dir)
    from make_reel import read_seconds
    texts = json.loads((post_dir / "texts.json").read_text())
    segs = []
    for sid in ids:
        # рилс динамичнее сторис: слайд не дольше 7 с (обложка 4 с) — посмотреть ещё раз можно на паузе
        cap = 4.0 if sid == "w0" else 7.0
        sec = min(cap, max(3.5, read_seconds(texts.get(sid, 0))))
        if sid in videos:
            from backgrounds import video_len
            length = video_len(ROOT / "library" / videos[sid]["video"])
            src = min(length, sec / 1.2)
            segs.append({"video": f"../../library/{videos[sid]['video']}", "start": 0, "duration": round(src, 2),
                         "overlay": f"{sid}.png", "slow": round(sec / src, 3)})
        else:
            segs.append({"image": f"{sid}.png", "duration": round(sec, 2), "max": cap})
    (post_dir / "reel.json").write_text(json.dumps({"output": "reel.mp4", "transition": 0.35, "segments": segs,
                                                    "music": "../../library/music/upbeat-sub_clair-background-music-591220.mp3",
                                                    "music_start": 4}, indent=1))
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_reel.py"), str(post_dir / "reel.json")], check=True)
    # обложка — первый кадр; промежуточные PNG не храним
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", "0.5", "-i", str(post_dir / "reel.mp4"),
                    "-frames:v", "1", "-q:v", "3", str(post_dir / "cover.jpg")], check=True)
    for p in post_dir.glob("w*.png"):
        p.unlink()
    days = f"{FRI.day}–{DAYS[-1].day} {MONTHS[DAYS[-1].month - 1]}"
    lines = [f"Выходные {days}: куда пойти в Дюссельдорфе 🗓", ""]
    for it in items:
        when = " ".join(x for x in (it.get("day"), it.get("time")) if x)
        lines.append(f"▫️ {when} — {it.get('title')}" + (f" ({it['place']})" if it.get("place") else ""))
    lines += ["", "Сохрани и отправь тем, с кем пойдёшь 👇", "Что происходит сегодня — каждое утро в сторис.", "",
              "#дюссельдорф #düsseldorf #дюссельдорфафиша #выходные #кудапойти #русскиевдюссельдорфе #жизньвгермании"]
    (post_dir / "caption.txt").write_text("\n".join(lines) + "\n")
    thu = FRI - timedelta(days=1)
    post = {"type": "reel", "status": "manual", "title": f"Выходные {days}", "caption_file": "caption.txt",
            "media": ["reel.mp4"], "cover": "cover.jpg", "share_to_feed": True,
            "publish_at": datetime.combine(thu, dtime(19, 0), TZ).isoformat(),
            "send_at": datetime.combine(thu - timedelta(days=1), dtime(20, 0), TZ).isoformat(),
            "music_hint": "трендовый бодрый звук из Instagram (текста немного — можно со словами)"}
    (post_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n")
    (post_dir / "pick.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"✓ {post_dir.name}: {len(items)} событий, рилс готов")


if __name__ == "__main__":
    main()
