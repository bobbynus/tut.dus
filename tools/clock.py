#!/usr/bin/env python3
"""Что пора запустить сейчас (для «часов»). Печатает имена workflow через пробел.

- events-collect.yml — если сегодня (по Берлину) ещё не было сбора и уже после 10:00
- daily-stories.yml  — если после 20:00 нет сторис на завтра
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
now = datetime.now(ZoneInfo("Europe/Berlin"))
todo = []
try:
    gen = json.loads((ROOT / "data" / "events.json").read_text())["generated_at"][:10]
except Exception:
    gen = ""
if now.hour >= 10 and gen != now.date().isoformat():
    todo.append("events-collect.yml")
tomorrow = (now + timedelta(days=1)).date()
if now.hour >= 20 and not (ROOT / "posts" / f"daily-{tomorrow}" / "post.json").exists() and not (ROOT / "AUTOPOST_PAUSED").exists():
    todo.append("daily-stories.yml")
print(" ".join(todo))
