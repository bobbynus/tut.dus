#!/usr/bin/env python3
"""Учёт футажей: что есть в библиотеке, сколько раз и когда использовалось.

Запуск: python3 tools/footage.py [--days 14]
Свежие (не использованные последние N дней) идут первыми — их и берём в новые ролики.
Записи о использовании пишет make_reel.py в data/footage-usage.json.
"""
import json, subprocess, sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOOTAGE = ROOT / "library" / "footage"
LEDGER = ROOT / "data" / "footage-usage.json"


def duration(f):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                             capture_output=True, text=True).stdout
        return float(out)
    except Exception:
        return 0.0


def usage():
    """{файл: [(дата, пост), ...]}"""
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {}
    used = {}
    for post, rec in ledger.items():
        for c in rec["clips"]:
            used.setdefault(c["file"], []).append((rec["date"], post))
    return used


def report(days=14, probe=True):
    used = usage()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = []
    for f in sorted(FOOTAGE.glob("*.mp4")):
        uses = sorted(used.get(f.name, []))
        last = uses[-1][0] if uses else ""
        rows.append({"file": f.name, "own": f.name.startswith("own-"), "uses": len(uses), "last": last,
                     "fresh": last < cutoff, "sec": duration(f) if probe else 0.0})
    rows.sort(key=lambda r: (not r["fresh"], r["uses"], r["last"], not r["own"]))
    return rows


if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 14
    rows = report(days)
    print(f"{'файл':44} {'сек':>5} {'раз':>4}  последний   ")
    for r in rows:
        mark = "свободен" if r["fresh"] else f"недавно (<{days} дн.)"
        print(f"{r['file']:44} {r['sec']:5.1f} {r['uses']:4}  {r['last'] or '—':10}  {mark}")
    print(f"\nСвободных: {sum(r['fresh'] for r in rows)} из {len(rows)}, своих свободных: {sum(r['fresh'] and r['own'] for r in rows)}")
