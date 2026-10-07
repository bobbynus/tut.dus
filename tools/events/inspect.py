#!/usr/bin/env python3
"""Разведка страницы-календаря на JS: откуда она берёт данные.
Печатает скрипты, похожие на API адреса (в HTML и подключённых JS) и контекст вокруг слова-подсказки.
Запуск: inspect.py URL [слово] [доп. URL для просмотра JSON-LD ...]"""
import re, sys, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
API = re.compile(r"""["'`]((?:https?:)?//[^"'`\s]*?(?:api|json|feed|graphql|endpoint|widget|event)[^"'`\s]*)["'`]""", re.I)


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def context(text, word, n=12, width=300):
    for m in list(re.finditer(re.escape(word), text, re.I))[:n]:
        print("  …" + text[max(0, m.start() - width):m.end() + width].replace("\n", " ") + "…\n")


url, word = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
st, html = get(url)
print(f"{st} {len(html)} байт; JSON-LD блоков: {html.count('application/ld+json')}")
scripts = [urllib.parse.urljoin(url, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', html)]
if word:
    print(f"\n== «{word}» в HTML"); context(html, word)
for s in scripts:
    if word and word.lower() not in s.lower():
        continue
    try:
        _, js = get(s)
    except Exception as e:
        print(f"\n== {s}: {e}"); continue
    print(f"\n== {s} ({len(js)} байт)")
    print("\n".join(sorted(set(API.findall(js)))[:80]))
    for w in ("baseUrl", "apiUrl", "/api/", "api_token", "apiToken", "instance"):
        if w in js:
            print(f"-- {w}:"); context(js, w, n=4, width=200)
for extra in sys.argv[3:]:
    st, page = get(extra)
    print(f"\n== {extra}: {st}, JSON-LD: {page.count('application/ld+json')}")
    for blk in re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', page, re.S)[:3]:
        print(blk.strip()[:1500])
