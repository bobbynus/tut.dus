#!/usr/bin/env python3
"""Разведка: какие бесплатные музыкальные библиотеки отдают страницы/API роботу (запуск из GitHub Actions)."""
import re, sys, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
for url in [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]:
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=30)
        body = r.read().decode("utf-8", "replace")
        mp3 = sorted(set(re.findall(r'https?://[^"\'\s<>]+?\.mp3', body)))[:3]
        print(f"\n✓ {r.status} {url}  {len(body)//1024} КБ  mp3-ссылок: {len(set(re.findall(r'https?://[^\"\\s<>]+?\\.mp3', body)))}")
        print("   ", mp3)
        print("   ", re.sub(r"\s+", " ", body[:400]))
        m = re.search(r"\.mp3", body)
        if m:  # как устроена карточка трека
            print("   …", re.sub(r"\s+", " ", body[max(0, m.start() - 2500):m.start() + 1500]))
        for w in ("sort", "Popular", "Trending", "license", "License"):
            for mm in list(re.finditer(w, body))[:2]:
                print(f"   [{w}]", re.sub(r"\s+", " ", body[max(0, mm.start() - 150):mm.start() + 250]))
    except Exception as e:
        print(f"\n✗ {url}\n   {e} {getattr(e, 'read', lambda: b'')()[:300]!r}")
