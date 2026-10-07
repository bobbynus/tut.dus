#!/usr/bin/env python3
"""Сторис-картинки → короткие видео с музыкой (через API к картинкам музыку не добавить).

Каждая сторис — 6 секунд, картинка неподвижна (текст читается); музыка идёт непрерывно: вторая сторис
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
    start = 8  # пропускаем тихое вступление
    videos = []
    for n, name in enumerate(spec["media"]):
        if not name.endswith(".png"):
            videos.append(name); continue
        out = name.replace(".png", ".mp4")
        reel = {"output": out, "transition": 0.4,
                "segments": [{"image": name, "duration": SEC}],
                "music": f"../../library/music/{track.name}",
                "music_start": start + n * SEC}
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
