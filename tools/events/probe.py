#!/usr/bin/env python3
"""Проверяет сайты-кандидаты: есть ли машиночитаемые события (JSON-LD schema.org Event, iCal, RSS)."""
import json, re, sys, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
URLS = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]


def events_in(obj, out):
    if isinstance(obj, list):
        for x in obj: events_in(x, out)
    elif isinstance(obj, dict):
        t = obj.get("@type", "")
        t = " ".join(t) if isinstance(t, list) else str(t)
        if "Event" in t:
            out.append(obj)
        for k in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
            if k in obj: events_in(obj[k], out)


for url in URLS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de,en"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as e:
        print(f"\n✗ {url}\n   ошибка: {e}"); continue
    evs = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try: events_in(json.loads(block.strip()), evs)
        except Exception: pass
    ics = sorted(set(re.findall(r'(?:href|src)="([^"]+(?:\.ics|webcal:[^"]+|ical[^"]*))"', html, re.I)))[:3]
    rss = sorted(set(re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', html, re.I)))[:3]
    print(f"\n{'✓' if evs else '·'} {url}\n   {len(html)//1024} КБ, JSON-LD событий: {len(evs)}, iCal: {ics or '-'}, RSS: {rss or '-'}")
    for e in evs[:4]:
        loc = e.get("location") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        print(f"     – {str(e.get('name'))[:70]} | {e.get('startDate')} | {(loc.get('name') if isinstance(loc, dict) else loc)}")
