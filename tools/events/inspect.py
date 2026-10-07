#!/usr/bin/env python3
"""Разведка страницы-календаря на JS: откуда она берёт данные.
Печатает скрипты, iframe, похожие на API адреса (в HTML и в подключённых JS).
Запуск: inspect.py URL"""
import re, sys, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
API = re.compile(r"""["'`](https?://[^"'`\s]*?(?:api|json|feed|graphql|destination|meta|widget|event|veranstalt|search|infomax|imx|tomas|deskline|outdooractive)[^"'`\s]*)["'`]""", re.I)
REL = re.compile(r"""["'`](/[^"'`\s]*?(?:api|json|feed|graphql|event|veranstalt|search)[^"'`\s]*)["'`]""", re.I)


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


url = sys.argv[1]
st, html = get(url)
print(f"{st} {len(html)} байт; JSON-LD блоков: {html.count('application/ld+json')}")
scripts = [urllib.parse.urljoin(url, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', html)]
print("\n== scripts"); print("\n".join(scripts))
print("\n== iframes"); print("\n".join(re.findall(r'<iframe[^>]+src="([^"]+)"', html)))
print("\n== data-атрибуты с url"); print("\n".join(sorted(set(re.findall(r'data-[\w-]*(?:url|src|api|endpoint)[\w-]*="([^"]+)"', html)))[:40]))
print("\n== API в HTML"); print("\n".join(sorted(set(API.findall(html) + REL.findall(html)))[:60]))
for s in scripts:
    try:
        _, js = get(s)
    except Exception as e:
        print(f"\n== {s}: {e}"); continue
    hits = sorted(set(API.findall(js) + REL.findall(js)))
    if hits:
        print(f"\n== API в {s} ({len(js)} байт)"); print("\n".join(hits[:60]))
