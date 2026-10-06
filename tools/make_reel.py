#!/usr/bin/env python3
"""Собирает Reels 1080×1920 из картинок и футажей с музыкой.

Запуск: python3 tools/make_reel.py posts/NN-name/reel.json
Описание ролика (пути относительно файла reel.json):
{
  "output": "reel.mp4",
  "transition": 0.4,                       # длительность перехода, сек
  "segments": [
    {"image": "t1.png", "duration": 3, "bg": "0xe2001a"},       # картинка с лёгким наездом, поля цвета bg
    {"video": "../../library/footage/rhein.mp4", "start": 2, "duration": 3,
     "overlay": "o2.png"}                                       # футаж + прозрачный PNG с текстом (по центру)
  ],
  "music": "../../library/music/lofi-01.mp3",
  "music_start": 0,                         # с какой секунды трека начинать
  "volume": 1.0
}
"""
import json, subprocess, sys, tempfile
from pathlib import Path

W, H, FPS = 1080, 1920, 30
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def run(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def render_segment(seg, base, out):
    d = float(seg["duration"])
    fill = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if "image" in seg:
        # картинка вписывается целиком; поля закрашиваются цветом bg (по умолчанию тёмный фирменный)
        zoom = 0.04 if seg.get("zoom", True) else 0
        bg = seg.get("bg", "0x111214")
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg}")
        vf = (f"{fit},scale=w='trunc({W}*(1+{zoom}*t/{d})/2)*2':h=-2:eval=frame,"
              f"crop={W}:{H},setsar=1,fps={FPS}")
        run(["-loop", "1", "-t", str(d), "-i", str(base / seg["image"]), "-vf", vf, *ENC, "-an", str(out)])
    else:
        inputs = ["-ss", str(seg.get("start", 0)), "-t", str(d), "-i", str(base / seg["video"])]
        if seg.get("overlay"):
            inputs += ["-i", str(base / seg["overlay"])]
            fc = f"[0:v]{fill},setsar=1,fps={FPS}[v];[1:v]scale={W}:-2[o];[v][o]overlay=0:(H-h)/2[out]"
        else:
            fc = f"[0:v]{fill},setsar=1,fps={FPS}[out]"
        run([*inputs, "-filter_complex", fc, "-map", "[out]", *ENC, "-an", str(out)])


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
        durs = [float(s["duration"]) for s in segs]
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
    print(f"готово: {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out} ({total:.1f} с)")


if __name__ == "__main__":
    main(sys.argv[1])
