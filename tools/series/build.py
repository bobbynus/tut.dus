#!/usr/bin/env python3
"""Сборка выпуска рубрики из короткого описания.

Запуск: python3 tools/series/build.py posts/s02-cifry-2/issue.json
issue.json:
{
  "title": "Дюссельдорф в цифрах · 2",          # для черновика
  "publish_at": "2026-10-13T19:00:00+02:00",
  "send_at": "...",                             # необязательно: по умолчанию за сутки
  "music_hint": "...",
  "caption": "текст подписи (с хэштегами)",
  "slides": [
    {"bg": "photos/own-….jpg" | null, "tag": "Жители", "h1": "заголовок", "sub": "текст"},
    {"bg": ..., "tag": "...", "big": "658 245", "unit": "", "what": "…", "sub": "…", "src": "источник"},
    {"bg": ..., "tag": "...", "row": [["10", "округов"], ["50", "районов"]], "sub": "…", "src": "…"},
    {"bg": ..., "tag": "...", "h1": "…", "list": [["01", "текст"], …]},
    {"bg": ..., "tag": "...", "h1": "…", "sub": "…", "pill": "Дальше в рубрике: …"}
  ]
}
Фон — путь из library/ (подпись автора берётся из library/backgrounds.json); null — фирменный фон.
Результат: c1.jpg… (1080×1350), caption.txt, post.json со статусом manual (черновик придёт владельцу в Telegram).
"""
import html, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = """
  .slide.v2 { padding: 88px 80px 96px }
  .v2 .big { font: 900 186px/0.92 var(--display); letter-spacing: -.045em; margin: 6px 0 10px; white-space: nowrap }
  .v2 .big em { font-style: normal; color: var(--red) }
  .v2 .what { font: 600 40px/1.25 var(--body); max-width: 900px }
  .v2 .src { margin-top: 30px; font: 400 22px/1.3 var(--body); opacity: .55 }
  .v2 .row { display: flex; gap: 44px; margin-top: 18px; flex-wrap: wrap }
  .v2 .row div { display: flex; flex-direction: column }
  .v2 .row b { font: 900 112px/0.95 var(--display); letter-spacing: -.04em }
  .v2 .row span { font: 500 30px/1.2 var(--body); opacity: .85; margin-top: 8px }
  .slide.v2 > .credit { bottom: 34px }
"""


def esc(s):
    return html.escape(str(s or "")).replace("\n", "<br>")


def credits():
    try:
        items = json.loads((ROOT / "library" / "backgrounds.json").read_text())["items"]
    except Exception:
        return {}
    return {i["file"]: i.get("credit", "") for i in items}


def slide(n, total, s, cred):
    bg = (f'<div class="bg" style="background-image:url(../../library/{s["bg"]})"></div><div class="shade"></div>'
          if s.get("bg") else '<div class="bg brand"></div><div class="shade" style="opacity:.5"></div>')
    size = f' style="font-size:{s["size"]}px"' if s.get("size") else ""
    body = f'<div class="tag">{esc(s.get("tag"))}</div>'
    if s.get("h1"):
        body += f'<h1{size}>{esc(s["h1"])}</h1>'
    if s.get("big"):
        unit = f'<em>{esc(s["unit"])}</em>' if s.get("unit") else ""
        body += f'<div class="big"{size}>{esc(s["big"])}{unit}</div>'
    if s.get("row"):
        body += '<div class="row">' + "".join(f"<div><b>{esc(a)}</b><span>{esc(b)}</span></div>" for a, b in s["row"]) + "</div>"
    if s.get("what"):
        body += f'<p class="what">{esc(s["what"])}</p>'
    if s.get("sub"):
        body += f'<p class="sub">{esc(s["sub"])}</p>'
    if s.get("list"):
        body += '<div class="list">' + "".join(f'<div class="it"><b>{esc(a)}</b><span>{esc(b)}</span></div>' for a, b in s["list"]) + "</div>"
    if s.get("pill"):
        body += f'<div class="pill">{esc(s["pill"])}</div>'
    if s.get("src"):
        body += f'<p class="src">{esc(s["src"])}</p>'
    credit = cred.get(s.get("bg") or "", "")
    return (f'<section class="slide v2" id="c{n}">{bg}\n  <div class="top"><span class="logo">ТУТ<i>.DUS</i></span>'
            f'<span class="page">{n}/{total}</span></div>\n  <div class="low">{body}</div>'
            + (f'<div class="credit">{esc(credit)}</div>' if credit else "") + "</section>")


def build(spec_path):
    spec_path = Path(spec_path).resolve()
    post_dir = spec_path.parent
    spec = json.loads(spec_path.read_text())
    cred = credits()
    slides = spec["slides"]
    page = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{esc(spec["title"])}</title>'
            f'<link rel="stylesheet" href="brand.css"><link rel="stylesheet" href="v2.css"><style>{CSS}</style></head><body>\n'
            + "\n".join(slide(i, len(slides), s, cred) for i, s in enumerate(slides, 1)) + "\n</body></html>")
    tmp = ROOT / "design" / f"_{post_dir.name}.html"
    tmp.write_text(page.replace("../../library/", "../library/"))
    try:
        subprocess.run(["node", "render.cjs", tmp.name, str(post_dir)], cwd=ROOT / "design", check=True)
    finally:
        tmp.unlink(missing_ok=True)
    media = []
    for i in range(1, len(slides) + 1):
        png = post_dir / f"c{i}.png"
        subprocess.run(["convert", str(png), "-quality", "92", str(post_dir / f"c{i}.jpg")], check=True)
        png.unlink()
        media.append(f"c{i}.jpg")
    (post_dir / "texts.json").unlink(missing_ok=True)
    (post_dir / "caption.txt").write_text(spec["caption"].strip() + "\n")
    post = {"type": "carousel", "status": "manual", "title": spec["title"], "publish_at": spec["publish_at"],
            "caption_file": "caption.txt", "media": media,
            "music_hint": spec.get("music_hint", "спокойная инструментальная, без слов — на слайдах много текста")}
    if spec.get("send_at"):
        post["send_at"] = spec["send_at"]
    (post_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n")
    print(f"✓ {post_dir.name}: {len(media)} слайдов, выйдет {spec['publish_at']}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        build(p)
