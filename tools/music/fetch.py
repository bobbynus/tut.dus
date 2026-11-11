#!/usr/bin/env python3
"""Добор свежей бесплатной музыки (workflow «Music», раз в неделю).

Источник — Mixkit (mixkit.co): лицензия Mixkit Free разрешает использовать треки в видео, в том числе
в соцсетях, бесплатно и без указания автора. Страницы настроений Mixkit отсортированы по популярности —
берём самые популярные треки, которых у нас ещё нет: так музыка остаётся «в тренде» среди свободной.

Каждый трек обрезается до 80 секунд (96 кбит/с, ~1 МБ) (сторис и рилсы короче), выравнивается по громкости
и кладётся в library/music/<настроение>-mixkit-<id>.mp3; описание — в library/music.json.
Чтобы репозиторий не рос, в библиотеке держим не больше MAX_TRACKS: лишние — самые давно не звучавшие
старые треки — удаляются из рабочей копии.
Запуск: fetch.py [--per 1]   (--per — сколько новых треков на настроение)
"""
import html, json, re, subprocess, sys, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import library

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
BASE = "https://mixkit.co/free-stock-music/"
# настроение → страницы Mixkit (несуществующие просто пропускаются)
MOODS = {"upbeat": ["mood/upbeat/", "mood/happy/", "pop/"],
         "calm": ["mood/relaxing/", "mood/calm/", "tag/lo-fi/", "mood/chill/"],
         "night": ["jazz/", "mood/dreamy/", "tag/ambient/"],
         "epic": ["cinematic/", "mood/epic/"]}
SKIP = re.compile(r"christmas|xmas|halloween|horror|scary|fright|creepy|spooky|zombie|sad|funeral|wedding", re.I)  # не на каждый день
SEASONAL = re.compile(r"christmas|xmas|holiday|winter|snow|jingle", re.I)
MAX_TRACKS = 30
CLIP = 80   # сторис: до ~68 с музыки подряд, рилс — до 50 с


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def cards(page):
    """[(id, название, автор, жанры)] в порядке страницы (= популярность)."""
    out = []
    for m in re.finditer(r'data-audio-player-item-id-value="(\d+)"(.*?)(?=data-audio-player-item-id-value=|\Z)', page, re.S):
        block = m.group(2)
        title = re.search(r'item-grid-card__title"\s*>\s*(.*?)\s*<', block, re.S)
        author = re.search(r'preview__author"\s*>\s*by\s+(.*?)\s*<', block, re.S)
        genres = re.findall(r'meta-links__link"[^>]*>([^<]+)<', block)
        out.append((m.group(1), html.unescape(title.group(1).strip()) if title else "",
                    html.unescape(author.group(1).strip()) if author else "", genres[:4]))
    return out


def duration(f):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True).stdout
    try:
        return float(out)
    except ValueError:
        return 0.0


def main(per=2):
    cat = library.catalog()
    have = {v.get("source_id") for v in cat.values()}
    month = date.today().month
    added = []
    for mood, pages in MOODS.items():
        candidates = []
        for path in pages:
            try:
                found = cards(get(BASE + path))
            except Exception as e:
                print(f"· {path}: {e}")
                continue
            n = len(found)
            candidates += [(i / max(n, 1), c) for i, c in enumerate(found)]
            print(f"✓ {path}: {n} треков")
        candidates.sort(key=lambda x: x[0])  # первые на странице — самые популярные
        took = 0
        for pos, (tid, title, author, genres) in candidates:
            if took >= per:
                break
            sid = f"mixkit-{tid}"
            if sid in have or SKIP.search(title) or (SEASONAL.search(title) and month not in (11, 12, 1)):
                continue
            have.add(sid)
            name = f"{mood}-{sid}.mp3"
            raw = library.DIR / (name + ".src")
            try:
                with urllib.request.urlopen(urllib.request.Request(f"https://assets.mixkit.co/music/{tid}/{tid}.mp3", headers=UA),
                                            timeout=90) as r:
                    raw.write_bytes(r.read())
                if duration(raw) < 45:  # короткие джинглы не подходят
                    print(f"  · {title}: короче 45 с"); continue
                subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(raw), "-t", str(CLIP),
                                "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={CLIP - 3}:d=3",
                                "-ac", "2", "-b:a", "96k", "-map_metadata", "-1", str(library.DIR / name)], check=True)
            except Exception as e:
                print(f"  ✗ {title}: {e}"); continue
            finally:
                raw.unlink(missing_ok=True)
            cat[name] = {"source": "mixkit", "source_id": sid, "title": title, "author": author, "genres": genres,
                         "license": "Mixkit Free License (без указания автора)", "page": f"https://mixkit.co/free-stock-music/",
                         "rank": round(1 - pos, 2), "added": date.today().isoformat(), "attribution": False}
            added.append(name)
            took += 1
            print(f"  + {name}: {title} — {author} ({', '.join(genres)})")
    prune(cat)
    library.CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=1) + "\n")
    print(f"Новых треков: {len(added)}, всего: {len(list(library.DIR.glob('*.mp3')))}")


def prune(cat):
    files = sorted(library.DIR.glob("*.mp3"))
    if len(files) <= MAX_TRACKS:
        return
    used = library.ledger()
    # удаляем старейшие по «последний раз звучал / добавлен»; свежие (≤ 30 дней) не трогаем
    old = [f for f in files if (date.today() - date.fromisoformat(cat.get(f.name, {}).get("added", "2026-01-01"))).days > 30]
    old.sort(key=lambda f: library.last_used(f.name, used) or cat.get(f.name, {}).get("added", ""))
    for f in old[:len(files) - MAX_TRACKS]:
        f.unlink()
        cat.pop(f.name, None)
        print(f"  − {f.name}: давно в библиотеке, освобождаем место")


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--per") + 1]) if "--per" in sys.argv else 1)
