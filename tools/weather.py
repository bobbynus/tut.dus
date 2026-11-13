#!/usr/bin/env python3
"""Погода в Дюссельдорфе на день — для утреннего приветствия в сторис.

Источник — Немецкая метеослужба DWD через открытый сервис Bright Sky (без ключа и лимитов по ключу);
запасной — Open-Meteo. Один запрос на сборку, без повторов. Не ответили — приветствие выходит без погоды.
Запуск: weather.py [YYYY-MM-DD]
"""
import json, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta

LAT, LON = 51.2277, 6.7735
UA = {"User-Agent": "tut.dus stories (https://github.com/bobbynus/tut.dus)"}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def _brightsky(day):
    q = urllib.parse.urlencode({"lat": LAT, "lon": LON, "date": day.isoformat(),
                                "last_date": (day + timedelta(days=1)).isoformat(), "tz": "Europe/Berlin"})
    hours = []
    for w in _get(f"https://api.brightsky.dev/weather?{q}").get("weather", []):
        ts = datetime.fromisoformat(w["timestamp"])
        if ts.date() != day or w.get("temperature") is None:
            continue
        hours.append({"h": ts.hour, "t": w["temperature"], "mm": w.get("precipitation") or 0,
                      "gust": w.get("wind_gust_speed") or w.get("wind_speed") or 0, "cloud": w.get("cloud_cover"),
                      "sun": w.get("sunshine") or 0, "cond": w.get("condition") or ""})
    return hours, "DWD"


WMO = {45: "fog", 48: "fog", 71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
       66: "sleet", 67: "sleet", 95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm"}


def _openmeteo(day):
    q = urllib.parse.urlencode({"latitude": LAT, "longitude": LON, "timezone": "Europe/Berlin",
                                "start_date": day.isoformat(), "end_date": day.isoformat(),
                                "hourly": "temperature_2m,precipitation,wind_gusts_10m,cloud_cover,sunshine_duration,weather_code"})
    h = _get(f"https://api.open-meteo.com/v1/forecast?{q}")["hourly"]
    hours = []
    for i, ts in enumerate(h["time"]):
        if h["temperature_2m"][i] is None:
            continue
        hours.append({"h": int(ts[11:13]), "t": h["temperature_2m"][i], "mm": h["precipitation"][i] or 0,
                      "gust": h["wind_gusts_10m"][i] or 0, "cloud": h["cloud_cover"][i],
                      "sun": (h["sunshine_duration"][i] or 0) / 60, "cond": WMO.get(h["weather_code"][i], "")})
    return hours, "Open-Meteo"


def _deg(t):
    t = round(t)
    return f"+{t}" if t > 0 else ("−" + str(-t) if t < 0 else "0")


def summarize(hours, source="DWD"):
    """Часы 7–22: что человеку важно знать утром."""
    day = [x for x in hours if 7 <= x["h"] <= 22]
    if len(day) < 8:
        return None
    tmin, tmax = min(x["t"] for x in day), max(x["t"] for x in day)
    wet = [x for x in day if x["mm"] >= 0.2]
    mm = sum(x["mm"] for x in day)
    parts = [name for name, a, b in (("утром", 7, 11), ("днём", 12, 17), ("вечером", 18, 22))
             if any(a <= x["h"] <= b for x in wet)]
    conds = {x["cond"] for x in day}
    clouds = [x["cloud"] for x in day if x["cloud"] is not None]
    cloud = sum(clouds) / len(clouds) if clouds else 70
    sun_h = sum(x["sun"] for x in day) / 60
    gust = max(x["gust"] for x in day)
    snow = bool(conds & {"snow", "sleet"})
    if "thunderstorm" in conds:
        kind, text = "storm", "гроза"
    elif snow:
        kind, text = "snow", "снег" if "snow" in conds else "мокрый снег"
    elif mm >= 0.5 and wet:
        kind = "rain"
        word = "небольшой дождь" if mm < 2 else "дождь"
        text = f"{word} весь день" if len(parts) == 3 else f"{word} {' и '.join(parts)}"
    elif any(x["cond"] == "fog" and x["h"] <= 10 for x in day):
        kind, text = "fog", "утром туман"
    elif sun_h >= 3 or cloud < 40:
        kind, text = "sun", "солнечно"
    else:
        kind, text = "cloud", "пасмурно" if cloud > 80 else "облачно, местами солнце"
    if kind in ("rain", "storm", "snow") and len(parts) < 3 and parts and kind != "rain":
        text += " " + " и ".join(parts)
    windy = gust >= 50
    if windy:
        text += ", ветрено"
    temp = _deg(tmax) + "°" if round(tmin) == round(tmax) else f"{_deg(tmin)}…{_deg(tmax)}°"
    return {"kind": kind, "temp": temp, "tmin": round(tmin), "tmax": round(tmax), "text": text, "rain_mm": round(mm, 1),
            "rain_parts": parts, "windy": windy, "sun_hours": round(sun_h, 1), "source": source}


def forecast(day):
    """Сводка на день или None. Никогда не бросает исключений."""
    for fetch in (_brightsky, _openmeteo):
        try:
            hours, source = fetch(day)
            got = summarize(hours, source)
            if got:
                return got
        except Exception as e:
            print(f"Погода ({fetch.__name__.strip('_')}): {e}")
    return None


# Фразы от редакции на случай, если нейросеть недоступна (выбор по дате — не повторяются подряд)
LINES = {
    "rain": ["Зонт сегодня — главный аксессуар. Но дома сидеть не обязательно.",
             "Дождь по расписанию — Рейнланд. Берём зонт и всё равно выходим.",
             "Мокро. Зато есть повод зайти туда, где тепло и интересно."],
    "sun": ["Солнце в Дюссельдорфе — событие само по себе. Выходим из дома.",
            "Тот самый день, когда Рейн блестит. Набережная ждёт.",
            "Солнечно — редкий подарок. Не тратьте его на диван."],
    "cloud": ["Небо серое, зато планы яркие.",
              "Обычная рейнская серость. Самое время для кофе и хорошего плана.",
              "Пасмурно, но сухо — для прогулки по городу хватит."],
    "fog": ["С утра туман: Rheinturm играет в прятки.",
            "Туманное утро — город как в кино. К обеду обещают, что найдётся."],
    "snow": ["Снег в Дюссельдорфе! Фотографируйте быстрее, пока не растаял.",
             "Снежно. Шапка, шарф — и город сегодня особенно красивый."],
    "storm": ["Обещают грозу — планы лучше выбирать под крышей.",
              "Гроза в прогнозе. Зонт не спасёт, а вот хороший зал — да."],
}
COLD = ["Холодно. Шарф и перчатки — и можно жить.", "Мороз по рейнским меркам. Одеваемся теплее."]


def line(w, day):
    if not w:
        return ""
    pool = COLD if w["tmax"] <= 2 and w["kind"] in ("cloud", "sun") else LINES[w["kind"]]
    return pool[day.toordinal() % len(pool)]


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    w = forecast(d)
    print(json.dumps(w, ensure_ascii=False, indent=1))
    print(line(w, d))
