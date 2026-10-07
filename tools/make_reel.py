#!/usr/bin/env python3
"""Собирает Reels 1080×1920 из картинок и футажей с музыкой.

Запуск: python3 tools/make_reel.py posts/NN-name/reel.json
Описание ролика (пути относительно файла reel.json):
{
  "output": "reel.mp4",
  "transition": 0.4,                       # длительность перехода, сек
  "segments": [
    {"image": "t1.png", "duration": 3, "bg": "0xe2001a"},       # неподвижная картинка, поля цвета bg ("zoom": true — наезд)
    {"video": "../../library/footage/rhein.mp4", "start": 2, "duration": 3,
     "overlay": "o2.png"}                                       # футаж + прозрачный PNG с текстом (по центру)
  ],
  "music": "../../library/music/lofi-01.mp3",
  "music_start": 0,                         # с какой секунды трека начинать
  "volume": 1.0
}
Какие футажи куда ушли, записывается в data/footage-usage.json (см. tools/footage.py).
"""
import json, subprocess, sys, tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOOTAGE = ROOT / "library" / "footage"
LEDGER = ROOT / "data" / "footage-usage.json"

W, H, FPS = 1080, 1920, 30
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def run(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


READ_WPS = 2.5        # слов в секунду: спокойное чтение с телефона
MAX_SLOW = 2.0        # футаж под текстом замедляем не больше чем вдвое


def read_seconds(words):
    """Сколько держать кадр с текстом, чтобы его успели прочитать с первого раза."""
    return 0.0 if not words else min(15.0, 2.5 + words / READ_WPS)


def plan(seg, base):
    """Длительность сегмента с учётом объёма текста (texts.json пишет render.cjs) и замедление футажа."""
    d = float(seg["duration"])
    try:
        texts = json.loads((base / "texts.json").read_text())
    except Exception:
        texts = {}
    layer = seg.get("image") if "image" in seg else seg.get("overlay")
    need = read_seconds(texts.get(Path(layer).stem, 0)) if layer else 0.0
    if "image" in seg:
        return max(d, need), 1.0
    slow = seg.get("slow") or (min(need / d, MAX_SLOW) if need > d else 1.0)
    return d * slow, slow


def render_segment(seg, base, out):
    d, slow = plan(seg, base)
    fill = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if "image" in seg:
        # картинка вписывается целиком; поля закрашиваются цветом bg (по умолчанию тёмный фирменный)
        zoom = 0.04 if seg.get("zoom", False) else 0  # по умолчанию статично: текст должен читаться
        bg = seg.get("bg", "0x111214")
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg}")
        if zoom:
            vf = (f"{fit},scale=w='trunc({W}*(1+{zoom}*t/{d})/2)*2':h=-2:eval=frame,"
                  f"crop={W}:{H},setsar=1,fps={FPS}")
        else:
            vf = f"{fit},setsar=1,fps={FPS}"
        run(["-loop", "1", "-t", str(d), "-i", str(base / seg["image"]), "-vf", vf, *ENC, "-an", str(out)])
    else:
        # берём из футажа исходный кусок и растягиваем его, если тексту нужно больше времени
        inputs = ["-ss", str(seg.get("start", 0)), "-t", str(float(seg["duration"])), "-i", str(base / seg["video"])]
        stretch = f"setpts={slow:.3f}*PTS," if slow > 1.001 else ""
        if seg.get("overlay"):
            inputs += ["-i", str(base / seg["overlay"])]
            fc = f"[0:v]{stretch}{fill},setsar=1,fps={FPS}[v];[1:v]scale={W}:-2[o];[v][o]overlay=0:(H-h)/2[out]"
        else:
            fc = f"[0:v]{stretch}{fill},setsar=1,fps={FPS}[out]"
        run([*inputs, "-filter_complex", fc, "-map", "[out]", *ENC, "-an", str(out)])


def record_usage(segs, base):
    """Учёт футажей: для каждого поста — какие фрагменты и когда. Пересборка поста перезаписывает его запись."""
    clips = []
    for seg in segs:
        if "video" not in seg:
            continue
        f = (base / seg["video"]).resolve()
        if f.parent == FOOTAGE:
            clips.append({"file": f.name, "start": seg.get("start", 0), "duration": seg["duration"]})
    if not clips or not base.is_relative_to(ROOT):
        return
    try:
        when = json.loads((base / "post.json").read_text())["publish_at"][:10]
    except Exception:
        when = date.today().isoformat()
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {}
    ledger[str(base.relative_to(ROOT))] = {"date": when, "clips": clips}
    LEDGER.write_text(json.dumps(dict(sorted(ledger.items())), ensure_ascii=False, indent=1) + "\n")


def main(spec_path):
    spec_path = Path(spec_path).resolve()
    base = spec_path.parent
    spec = json.loads(spec_path.read_text())
    segs = spec["segments"]
    t = float(spec.get("transition", 0.4))
    out = base / spec.get("output", "reel.mp4")

    with tempfile.TemporaryDirectory() as tmp:
        clips = []
        for i, seg in enumerate(segs):
            clip = Path(tmp) / f"{i:02d}.mp4"
            render_segment(seg, base, clip)
            clips.append(clip)

        # склейка с переходами xfade
        durs = [plan(s, base)[0] for s in segs]
        total = sum(durs) - t * (len(segs) - 1)
        args = []
        for c in clips:
            args += ["-i", str(c)]
        if len(clips) == 1:
            vchain, vlabel = "[0:v]null[v]", "[v]"
        else:
            parts, prev, offset = [], "[0:v]", 0.0
            for i in range(1, len(clips)):
                offset += durs[i - 1] - t
                label = f"[x{i}]"
                parts.append(f"{prev}[{i}:v]xfade=transition=fade:duration={t}:offset={offset:.3f}{label}")
                prev = label
            vchain, vlabel = ";".join(parts), prev

        if spec.get("music"):
            args += ["-ss", str(spec.get("music_start", 0)), "-i", str(base / spec["music"])]
            a = len(clips)
            achain = (f"[{a}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={spec.get('volume', 1.0)},"
                      f"afade=t=in:d=0.5,afade=t=out:st={max(total - 1.2, 0):.3f}:d=1.2,"
                      f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
            fc = f"{vchain};{achain}"
            maps = ["-map", vlabel, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        else:
            fc, maps = vchain, ["-map", vlabel]
        run([*args, "-filter_complex", fc, *maps, *ENC, "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)])
    record_usage(segs, base)
    print(f"готово: {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out} ({total:.1f} с)")


if __name__ == "__main__":
    main(sys.argv[1])
