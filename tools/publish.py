#!/usr/bin/env python3
"""Публикует в Instagram посты, у которых подошло время.

Каждый пост — папка posts/NN-name/ с файлом post.json:
{
  "type": "carousel" | "image" | "reel" | "story",
  "status": "scheduled" | "draft",
  "publish_at": "2026-10-06T19:00:00+02:00",
  "caption_file": "caption.txt",
  "media": ["s1.png", "s2.png"],      # reel — один файл; story — по сторис на файл
  "cover": "cover.png",               # необязательно, обложка reel
  "share_to_feed": true               # reel: показывать в ленте
}
После публикации рядом появляется published.json — повторно пост не выйдет.

Окружение: IG_ACCESS_TOKEN, IG_USER_ID, GITHUB_REPOSITORY, GITHUB_SHA.
DRY_RUN=1 — только проверить файлы и ссылки, ничего не публиковать.
POST=NN-name — обработать только этот пост (и игнорировать publish_at).
"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

API = "https://graph.instagram.com/v23.0"
ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
USER = os.environ.get("IG_USER_ID", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "bobbynus/tut.dus")
SHA = os.environ.get("GITHUB_SHA", "main")
DRY = os.environ.get("DRY_RUN") == "1"
ONLY = os.environ.get("POST", "").strip()
VIDEO_EXT = {".mp4", ".mov"}


def call(method, path, **params):
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    req = urllib.request.Request(url + ("?" + data.decode() if method == "GET" else ""),
                                 data=None if method == "GET" else data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path}: {e.code} {body}") from None


def public_url(post_dir, name):
    rel = (post_dir / name).relative_to(ROOT).as_posix()
    return f"https://raw.githubusercontent.com/{REPO}/{SHA}/{urllib.parse.quote(rel)}"


def check_url(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"{url}: HTTP {r.status}")


def wait_ready(container_id, label):
    for _ in range(60):  # до 10 минут
        st = call("GET", container_id, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{label}: контейнер {code}: {st.get('status')}")
        time.sleep(10)
    raise RuntimeError(f"{label}: видео не обработалось за 10 минут")


def media_params(post_dir, name):
    url = public_url(post_dir, name)
    if Path(name).suffix.lower() in VIDEO_EXT:
        return {"video_url": url}, True
    return {"image_url": url}, False


def publish(post_dir, spec):
    kind = spec["type"]
    caption = (post_dir / spec["caption_file"]).read_text().strip() if spec.get("caption_file") else ""
    media = spec["media"]

    if kind == "carousel":
        if not 2 <= len(media) <= 10:
            raise RuntimeError("в карусели должно быть от 2 до 10 файлов")
        children = []
        for name in media:
            p, is_video = media_params(post_dir, name)
            if is_video:
                p["media_type"] = "VIDEO"
            cid = call("POST", f"{USER}/media", is_carousel_item="true", **p)["id"]
            if is_video:
                wait_ready(cid, name)
            children.append(cid)
        container = call("POST", f"{USER}/media", media_type="CAROUSEL",
                         children=",".join(children), caption=caption)["id"]
    elif kind == "image":
        p, _ = media_params(post_dir, media[0])
        container = call("POST", f"{USER}/media", caption=caption, **p)["id"]
    elif kind == "reel":
        p = {"video_url": public_url(post_dir, media[0]), "media_type": "REELS", "caption": caption,
             "share_to_feed": "true" if spec.get("share_to_feed", True) else "false"}
        if spec.get("cover"):
            p["cover_url"] = public_url(post_dir, spec["cover"])
        container = call("POST", f"{USER}/media", **p)["id"]
    elif kind == "story":
        # несколько файлов — несколько сторис подряд, в указанном порядке
        ids = []
        for name in media:
            p, _ = media_params(post_dir, name)
            cid = call("POST", f"{USER}/media", media_type="STORIES", **p)["id"]
            wait_ready(cid, name)
            ids.append(call("POST", f"{USER}/media_publish", creation_id=cid)["id"])
        return {"media_ids": ids, "published_at": datetime.now(timezone.utc).isoformat()}
    else:
        raise RuntimeError(f"неизвестный тип поста: {kind}")

    wait_ready(container, post_dir.name)
    media_id = call("POST", f"{USER}/media_publish", creation_id=container)["id"]
    info = call("GET", media_id, fields="permalink,timestamp")
    return {"media_id": media_id, "permalink": info.get("permalink"),
            "published_at": info.get("timestamp") or datetime.now(timezone.utc).isoformat()}


def telegram_mirror(post_dir, spec):
    """Тот же пост в Telegram-канал. Для сторис — альбом и текстовая сводка (telegram.txt)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import telegram
    if not telegram.enabled() or (post_dir / "telegram.json").exists():
        return None
    text_file = post_dir / ("telegram.txt" if (post_dir / "telegram.txt").exists() else spec.get("caption_file", ""))
    caption = text_file.read_text().strip() if spec.get("caption_file") or text_file.name == "telegram.txt" else ""
    urls = [public_url(post_dir, n) for n in spec["media"]]
    ids = telegram.publish(spec["type"], urls, caption)
    (post_dir / "telegram.json").write_text(json.dumps({"message_ids": ids, "published_at": datetime.now(timezone.utc).isoformat()}) + "\n")
    return ids


def main():
    if not DRY and not (TOKEN and USER):
        sys.exit("Нет IG_ACCESS_TOKEN / IG_USER_ID")
    now = datetime.now(timezone.utc)
    failed = False
    for spec_file in sorted(ROOT.glob("posts/*/post.json")):
        post_dir = spec_file.parent
        if ONLY and post_dir.name != ONLY:
            continue
        spec = json.loads(spec_file.read_text())
        if (post_dir / "published.json").exists():
            pub = json.loads((post_dir / "published.json").read_text())
            age = now - datetime.fromisoformat(pub["published_at"].replace("Z", "+00:00").replace("+0000", "+00:00"))
            if not DRY and age.total_seconds() < 86400:
                try:
                    if telegram_mirror(post_dir, spec): print(f"✓ {post_dir.name}: Telegram (догнали)")
                except Exception as e:
                    failed = True; print(f"✗ {post_dir.name}: Telegram: {e}")
            continue
        if not ONLY:
            if spec.get("status") != "scheduled":
                continue
            if datetime.fromisoformat(spec["publish_at"]) > now:
                print(f"· {post_dir.name}: ждёт {spec['publish_at']}")
                continue
        try:
            files = list(spec["media"]) + ([spec["cover"]] if spec.get("cover") else [])
            for name in files:
                if not (post_dir / name).exists():
                    raise RuntimeError(f"нет файла {name}")
            if DRY:
                for name in files:
                    check_url(public_url(post_dir, name))
                print(f"✓ {post_dir.name}: {spec['type']}, {len(spec['media'])} файл(ов), ссылки открываются (проверка)")
                continue
            result = publish(post_dir, spec)
            (post_dir / "published.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(f"✓ {post_dir.name}: опубликован {result.get('permalink') or ', '.join(result.get('media_ids', []))}")
            try:
                if telegram_mirror(post_dir, spec): print(f"✓ {post_dir.name}: Telegram")
            except Exception as e:  # Telegram не должен ломать Instagram
                failed = True; print(f"✗ {post_dir.name}: Telegram: {e}")
        except Exception as e:  # продолжаем с остальными постами
            failed = True
            print(f"✗ {post_dir.name}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
