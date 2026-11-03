#!/usr/bin/env python3
"""Футажи и фото из Immich владельца (workflow «Immich»).

Медиатека личная, а репозиторий публичный, поэтому в два шага:
  scan   — ищет снимки и видео с местом «Düsseldorf» без распознанных людей и собирает таблицу миниатюр
           (immich-out/sheet-*.jpg + candidates.json). Это уходит в artifact на сутки, НЕ в репозиторий.
  import — скачивает только отобранные номера (после просмотра), убирает звук и метаданные,
           кладёт в library/footage|photos/own-imm-*.{mp4,jpg} и добавляет в каталог фонов с темами.
Окружение: IMMICH_URL, IMMICH_API_KEY (секреты). Ключ нигде не печатается.

  immich.py ping
  immich.py scan [--city Düsseldorf] [--limit 150]
  immich.py import <номер:темы,через,запятую> ...      (номера из candidates.json последнего scan)
"""
import hashlib, json, os, subprocess, sys, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "immich-out"
BASE = os.environ.get("IMMICH_URL", "").rstrip("/")
KEY = os.environ.get("IMMICH_API_KEY", "")
DONE = ROOT / "data" / "immich-imported.json"  # хэши уже импортированных (сами id в публичный репозиторий не пишем)


def req(path, body=None, raw=False, timeout=120):
    r = urllib.request.Request(f"{BASE}/api{path}", method="POST" if body is not None else "GET",
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"x-api-key": KEY, "Accept": "application/json" if not raw else "*/*",
                                        "Content-Type": "application/json", "User-Agent": "tut.dus-immich/1.0"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read() if raw else json.load(resp)


def h(asset_id):
    return hashlib.sha256(("tut.dus:" + asset_id).encode()).hexdigest()[:16]


def done():
    return set(json.loads(DONE.read_text())) if DONE.exists() else set()


def diagnose(path):
    """Кто отвечает на запрос: сам Immich или прокси/защита перед ним. Ключ и адрес не печатаются."""
    import urllib.error
    from urllib.parse import urlparse
    u = urlparse(BASE)
    print(f"адрес: схема {u.scheme}, путь в адресе: {'есть (' + u.path + ')' if u.path not in ('', '/') else 'нет'}")
    for with_key in (False, True):
        hdr = {"User-Agent": "tut.dus-immich/1.0", "Accept": "application/json"}
        if with_key: hdr["x-api-key"] = KEY
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + "/api" + path, headers=hdr), timeout=30) as r:
                print(f"{'с ключом' if with_key else 'без ключа'}: {r.status}, server={r.headers.get('server')}")
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace").replace("\n", " ")
            print(f"{'с ключом' if with_key else 'без ключа'}: {e.code}, server={e.headers.get('server')}, "
                  f"cf-ray={'да' if e.headers.get('cf-ray') else 'нет'}, ответ: {body[:200]}")
        except Exception as e:
            print(f"{'с ключом' if with_key else 'без ключа'}: ошибка {type(e).__name__}: {e}")


def ping():
    """Проверяем ровно то, что нужно: поиск (asset.read), миниатюры (asset.view), скачивание (asset.download)."""
    import urllib.error
    diagnose("/server/ping")
    print("сервер:", req("/server/ping"))
    try:
        res = req("/search/metadata", {"city": "Düsseldorf", "page": 1, "size": 1})
        items = res.get("assets", {}).get("items", [])
        print(f"поиск: работает, всего с местом Düsseldorf: {res.get('assets', {}).get('total', '?')}")
    except urllib.error.HTTPError as e:
        print(f"поиск: {e.code} — у ключа нет права asset.read"); return
    if not items:
        print("с местом «Düsseldorf» ничего не нашлось — проверим, как называется город в метаданных"); return
    aid = items[0]["id"]
    for what, path, perm in (("миниатюра", f"/assets/{aid}/thumbnail?size=thumbnail", "asset.view"),
                             ("скачивание", f"/assets/{aid}/original", "asset.download")):
        try:
            req(path, raw=True, timeout=120)
            print(f"{what}: работает")
        except urllib.error.HTTPError as e:
            print(f"{what}: {e.code} — у ключа нет права {perm}")


def search(city, kind, limit):
    items, page = [], 1
    while len(items) < limit and page:
        res = req("/search/metadata", {"city": city, "type": kind, "page": page, "size": 200,
                                       "withExif": True, "withPeople": True, "order": "desc"})
        a = res.get("assets", {})
        items += a.get("items", [])
        page = a.get("nextPage")
        page = int(page) if page else None
    return items


def secs(a):
    """Длительность видео: в разных версиях Immich это строка «ч:мм:сс.ммм» или число (секунды или миллисекунды)."""
    d = a.get("duration")
    if isinstance(d, (int, float)):
        return d / 1000 if d > 10000 else float(d)
    try:
        h_, m, sec = (d or "0:0:0").split(":")
        return int(h_) * 3600 + int(m) * 60 + float(sec)
    except Exception:
        return 0.0


def scan(city="Düsseldorf", limit=60):
    OUT.mkdir(exist_ok=True)
    seen = done()
    cands = []
    for kind in ("VIDEO", "IMAGE"):
        found = search(city, kind, limit * 3)
        ok = [a for a in found if not a.get("people") and h(a["id"]) not in seen and not a.get("isArchived")
              and not a.get("isTrashed")]
        if kind == "VIDEO":  # совсем короткие и очень длинные не берём
            ok = [a for a in ok if 4 <= secs(a) <= 180]
        print(f"{kind}: найдено {len(found)}, без людей и новых {len(ok)}")
        cands += [{"id": a["id"], "type": kind, "date": (a.get("fileCreatedAt") or "")[:10],
                   "dur": round(secs(a)) if kind == "VIDEO" else 0} for a in ok[:limit]]
    thumbs = OUT / "thumbs"; thumbs.mkdir(exist_ok=True)
    no_view = False  # у ключа может не быть права asset.view — тогда миниатюру делаем из оригинала
    for n, c in enumerate(cands, 1):
        c["n"] = n
        out = thumbs / f"{n:03d}.webp"
        try:
            if not no_view:
                out.write_bytes(req(f"/assets/{c['id']}/thumbnail?size=thumbnail", raw=True))
                continue
        except urllib.error.HTTPError as e:
            if e.code != 403:
                print(f"  миниатюра {n}: {e}"); continue
            no_view = True
            print("  нет права asset.view — миниатюры делаю из оригиналов (медленнее)")
        try:
            tmp = OUT / f"_{n}.orig"
            tmp.write_bytes(req(f"/assets/{c['id']}/original", raw=True, timeout=600))
            if c["type"] == "VIDEO":
                subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", "2", "-i", str(tmp),
                                "-frames:v", "1", "-vf", "scale=300:-2", str(out.with_suffix(".jpg"))], check=True)
                out.with_suffix(".jpg").rename(out)
            else:
                subprocess.run(["convert", str(tmp) + "[0]", "-auto-orient", "-thumbnail", "300x300", str(out)], check=True)
            tmp.unlink()
        except Exception as e:
            print(f"  миниатюра {n} из оригинала: {e}")
    # таблицы по 48 штук с номерами (у видео — значок ▶ и длительность)
    for i in range(0, len(cands), 48):
        part = cands[i:i + 48]
        args = []
        for c in part:
            f = thumbs / f"{c['n']:03d}.webp"
            if f.exists():
                label = f"{c['n']} {'▶ %d с' % c['dur'] if c['type'] == 'VIDEO' else ''} {c['date']}"
                args += ["-label", label, str(f)]
        if args:
            subprocess.run(["montage", "-pointsize", "12", *args, "-geometry", "200x200+3+3", "-tile", "8x",
                            str(OUT / f"sheet-{i // 48 + 1}.jpg")], check=True)
    (OUT / "candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=1))
    print(f"кандидатов: {len(cands)}, таблиц: {(len(cands) + 47) // 48}")


def import_(specs, cands_file):
    cands = {c["n"]: c for c in json.loads(Path(cands_file).read_text())}
    seen = done()
    cat_f = ROOT / "library" / "backgrounds.json"
    cat = json.loads(cat_f.read_text())
    for spec in specs:
        n, _, tags = spec.partition(":")
        c = cands[int(n)]
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] or ["city"]
        name = f"own-imm-{h(c['id'])[:10]}"
        tmp = ROOT / f"_{name}.orig"
        tmp.write_bytes(req(f"/assets/{c['id']}/original", raw=True, timeout=600))
        if c["type"] == "VIDEO":
            out = ROOT / "library" / "footage" / f"{name}.mp4"
            # без звука и метаданных, ≤1080 по короткой стороне, не длиннее 30 с — место в репозитории
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), "-t", "30",
                            "-an", "-map_metadata", "-1", "-vf",
                            "scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)'",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(out)], check=True)
            rel = f"footage/{name}.mp4"
        else:
            out = ROOT / "library" / "photos" / f"{name}.jpg"
            subprocess.run(["convert", str(tmp) + "[0]", "-auto-orient", "-resize", "2160x2160>", "-strip",
                            "-quality", "86", str(out)], check=True)
            rel = f"photos/{name}.jpg"
        tmp.unlink()
        cat["items"].append({"file": rel, "tags": tag_list, "credit": ""})
        seen.add(h(c["id"]))
        print(f"+ {rel}  {tag_list}")
    cat_f.write_text(json.dumps(cat, ensure_ascii=False, indent=1))
    DONE.write_text(json.dumps(sorted(seen), indent=0) + "\n")


if __name__ == "__main__":
    if not BASE or not KEY:
        sys.exit("Нет IMMICH_URL / IMMICH_API_KEY")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ping"
    if cmd == "ping":
        ping()
    elif cmd == "scan":
        a = sys.argv[2:]
        scan(a[a.index("--city") + 1] if "--city" in a else "Düsseldorf",
             int(a[a.index("--limit") + 1]) if "--limit" in a else 60)
    elif cmd == "import":
        import_(sys.argv[3:], sys.argv[2])
