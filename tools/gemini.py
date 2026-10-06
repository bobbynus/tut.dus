"""Вызовы Gemini с жёстким учётом бесплатных лимитов.

Лимит обнуляется в полночь по тихоокеанскому времени (~09:00 по Берлину). Учёт ведётся
в data/gemini-usage.json (коммитится вместе с данными). Никаких циклов повторов:
каждая модель пробуется не больше одного раза за вызов, и только пока не исчерпан наш потолок.
"""
import json, os, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "gemini-usage.json"
KEY = os.environ.get("GEMINI_API_KEY", "")

# Наш потолок в день — заметно ниже лимитов Google (Flash 20, Flash Lite 500).
CAPS = {"gemini-3.5-flash": 6, "gemini-3.5-flash-lite": 120}
PREFS = {
    "extract": ["gemini-3.5-flash-lite"],                    # разбор страниц
    "copy": ["gemini-3.5-flash", "gemini-3.5-flash-lite"],   # тексты сторис
}


def pacific_day():
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _load():
    try:
        data = json.loads(LEDGER.read_text())
    except Exception:
        data = {}
    return data if data.get("day") == pacific_day() else {"day": pacific_day(), "calls": {}}


def usage():
    return _load()["calls"]


def call(prompt, kind="extract", temperature=0.1):
    """Возвращает (model, text). Бросает RuntimeError, если все модели недоступны или потолок исчерпан."""
    if os.environ.get("NO_LLM") == "1":
        raise RuntimeError("NO_LLM=1 — нейросеть отключена для этого запуска")
    if not KEY:
        raise RuntimeError("GEMINI_API_KEY не задан")
    ledger, errors = _load(), []
    for model in PREFS[kind]:
        used = ledger["calls"].get(model, 0)
        if used >= CAPS[model]:
            errors.append(f"{model}: дневной потолок {CAPS[model]} исчерпан"); continue
        ledger["calls"][model] = used + 1  # считаем и неудачные: Google их тоже считает
        LEDGER.parent.mkdir(exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, indent=1) + "\n")
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={KEY}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=300))
            return model, "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"])
        except urllib.error.HTTPError as e:
            errors.append(f"{model}: HTTP {e.code}")
        except Exception as e:
            errors.append(f"{model}: {e}")
    raise RuntimeError("; ".join(errors))
