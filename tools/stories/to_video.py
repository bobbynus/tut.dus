#!/usr/bin/env python3
"""Сторис-картинки → короткие видео с музыкой (через API к картинкам музыку не добавить).

Каждая сторис — от 6 до 15 секунд по объёму текста, картинка неподвижна; музыка идёт непрерывно: вторая сторис
продолжает трек с 6-й секунды и т. д. Использование: to_video.py posts/<папка> [трек]
Исходные PNG после конвертации удаляются: слайды одноразовые, храним только видео.
"""
import json, random, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEC = 6


def pick_track(prefixes=("calm-", "upbeat-")):
    tracks = sorted(p for p in (ROOT / "library" / "music").glob("*.mp3") if p.name.startswith(prefixes))
    return random.Random(Path.cwd().name).choice(tracks) if tracks else None


def convert(post_dir, track=None):
    post_dir = Path(post_dir)
    spec = json.loads((post_dir / "post.json").read_text())
    track = Path(track) if track else pick_track()
    if not track:
        print("Нет треков в library/music — оставляю картинки"); return
    sys.path.insert(0, str(ROOT / "tools"))
    from make_reel import read_seconds
    try:
        texts = json.loads((post_dir / "texts.json").read_text())
    except Exception:
        texts = {}
    from backgrounds import video_len
    try:
        video_bgs = json.loads((post_dir / "backgrounds.json").read_text())
    except Exception:
        video_bgs = {}
    start = 8.0  # пропускаем тихое вступление; дальше музыка идёт непрерывно через все сторис
    videos = []
    for n, name in enumerate(spec["media"]):
        if not name.endswith(".png"):
            videos.append(name); continue
        out = name.replace(".png", ".mp4")
        sec = max(SEC, read_seconds(texts.get(Path(name).stem, 0)))  # много текста — сторис дольше
        seg = {"image": name, "duration": sec}
        video = video_bgs.get(Path(name).stem)
        if video:  # фон — футаж: слайд накладывается сверху, видео идёт чуть медленнее
            length = video_len(ROOT / "library" / video["video"])
            src = min(length, sec / 1.25)
            seg = {"video": f"../../library/{video['video']}", "start": 0, "duration": round(src, 2),
                   "overlay": name, "slow": round(sec / src, 3)}
        reel = {"output": out, "transition": 0.4,
                "segments": [seg],
                "music": f"../../library/music/{track.name}",
                "music_start": start}
        start += sec
        cfg = post_dir / f"_{n}.json"
        cfg.write_text(json.dumps(reel))
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_reel.py"), str(cfg)], check=True)
        cfg.unlink()
        (post_dir / name).unlink()  # слайд одноразовый: в репозитории храним только видео
        videos.append(out)
    spec["media"] = videos
    spec["music"] = track.name
    (post_dir / "post.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    print(f"✓ {post_dir.name}: {len(videos)} видео-сторис, трек {track.name}")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
