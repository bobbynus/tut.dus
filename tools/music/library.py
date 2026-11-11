#!/usr/bin/env python3
"""Музыка для сторис и рилсов: выбор трека без повторов.

Треки лежат в library/music/ (префикс имени — настроение: calm-, upbeat-, epic-, night-, vocal-).
Описание — library/music.json: источник, автор, лицензия, когда добавлен, популярность у источника.
Журнал использования — data/music-usage.json. Правила:
- один трек не чаще раза в REPEAT_DAYS дней (если свободных нет — самый давно звучавший);
- свежие треки (добавлены недавно) и популярные у источника идут первыми — так музыка «в тренде»;
- если на слайдах много текста — без слов (vocal- не берём).
Запуск: library.py — показать, что свободно.
"""
import json, random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "library" / "music"
CATALOG = ROOT / "library" / "music.json"
LEDGER = ROOT / "data" / "music-usage.json"
REPEAT_DAYS = 10
FRESH_DAYS = 30


def catalog():
    try:
        return json.loads(CATALOG.read_text())
    except Exception:
        return {}


def ledger():
    try:
        return json.loads(LEDGER.read_text())
    except Exception:
        return {}


def last_used(name, used):
    return max((u["date"] for u in used.get(name, [])), default="")


def pick(moods=("calm", "upbeat"), today=None, seed="", words=0):
    """Трек под настроение. words — сколько слов на слайдах (много текста → без вокала)."""
    today = today or date.today()
    cat, used = catalog(), ledger()
    files = [p for p in sorted(DIR.glob("*.mp3")) if p.name.split("-", 1)[0] in moods]
    if words > 40:
        files = [p for p in files if not p.name.startswith("vocal-")] or files
    if not files:
        return None
    cutoff = (today - timedelta(days=REPEAT_DAYS)).isoformat()
    rnd = random.Random(f"{today}{seed}")

    def score(p):
        info = cat.get(p.name, {})
        last = last_used(p.name, used)
        recent = last >= cutoff
        added = info.get("added", "2026-01-01")
        fresh = (today - date.fromisoformat(added)).days <= FRESH_DAYS
        pop = float(info.get("rank", 0.5))  # 0…1, 1 — самый популярный у источника
        return (recent, last if recent else "", -(fresh * 1.0 + pop + rnd.random() * 0.6))
    return min(files, key=score)


def record(name, post, today=None):
    used = ledger()
    used.setdefault(name, []).append({"date": (today or date.today()).isoformat(), "post": post})
    used[name] = used[name][-30:]
    LEDGER.parent.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(used, ensure_ascii=False, indent=1) + "\n")


def credit(name):
    """Подпись для трека, если лицензия требует указать автора (CC BY), иначе пусто."""
    info = catalog().get(name, {})
    return info.get("credit", "") if info.get("attribution") else ""


if __name__ == "__main__":
    used, cat = ledger(), catalog()
    for p in sorted(DIR.glob("*.mp3")):
        info = cat.get(p.name, {})
        print(f"{p.name:60} {info.get('source', '?'):10} добавлен {info.get('added', '?'):10} "
              f"звучал {last_used(p.name, used) or '—'}")
