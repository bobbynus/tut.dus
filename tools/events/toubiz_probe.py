#!/usr/bin/env python3
"""Разведка API toubiz (календарь visitduesseldorf.de). Токен — публичный, из HTML страницы."""
import re, sys, urllib.request

UA = {"User-Agent": "Mozilla/5.0 Chrome/126", "Accept": "application/json"}
PAGE = "https://www.visitduesseldorf.de/erleben/veranstaltungen/veranstaltungskalender"


def get(url, n=700):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:n]
    except Exception as e:
        return 0, str(e)


_, html = get(PAGE)
token = re.search(r'api-token="([^"]+)"', html).group(1)
print("token найден:", token[:12] + "…")
_, loader = get("https://widget.toubiz.de/js/stable/widget.js")
print("loader:", loader)
bundle = re.search(r"https?://[^\"'\s]+\.js", loader) or re.search(r"(?<=\")\./(widget\.module\.js)", loader)
if bundle and not bundle.group(0).startswith("http"):
    bundle = re.match(r"(.*)", "https://widget.toubiz.de/js/stable/widget.module.js")
if bundle:
    st, js = get(bundle.group(0))
    print("bundle", bundle.group(0), st, len(js))
    for m in sorted(set(re.findall(r"""["'`](/api/[^"'`\s]{0,80})["'`]""", js)))[:80]:
        print("  ", m)
    imports = sorted(set(re.findall(r"""["'](\./[\w.-]+\.js)["']""", js)))
    print("imports:", imports[:40])
    for imp in imports[:25]:
        st2, js2 = get("https://widget.toubiz.de/js/stable/" + imp[2:])
        if "filter" in js2 or "api/v1" in js2:
            print("  chunk с API:", imp, len(js2))
            js += js2
    print("всего JS:", len(js))
    for m in sorted(set(re.findall(r"""["'`](/?api/v1/[^"'`\s]{0,80})["'`]""", js)))[:80]:
        print("  ", m)
    for w in ("clientIncludingManaged", "excludeTag", "filter[", "fromDate", "dateFrom", "startDate", "within"):
        for m in list(re.finditer(re.escape(w), js))[:2]:
            print(f"-- {w}: …{js[max(0, m.start()-250):m.end()+250]}…".replace("\n", " "))
B = "https://mein.toubiz.de"
import json
st, body = get(f"{B}/api/v1/event?limit=1&api_token={token}")
ev = json.loads(body)["payload"][0]
print("\nКЛЮЧИ события:", sorted(ev))
for k in ("dates", "dateIntervals", "location", "address", "client", "category", "tags", "url", "name", "title"):
    if k in ev:
        print(f"{k}: {json.dumps(ev[k], ensure_ascii=False)[:600]}")
for path in sys.argv[1:] or [
    "/api/v1/event?limit=3", "/api/v1/event-date?limit=3", "/api/v1/eventDate?limit=3",
    "/api/v2/event?limit=3", "/api/v1/article?filter[type]=event&limit=3",
]:
    sep = "&" if "?" in path else "?"
    st, body = get(f"{B}{path}{sep}api_token={token}")
    print(f"\n### {path} → {st}\n{body[:900]}")
