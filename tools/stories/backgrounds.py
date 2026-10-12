#!/usr/bin/env python3
"""Фон для слайда сторис: по смыслу события и без повторов.

Каталог — library/backgrounds.json (файл → темы, подпись автора, exclude). Темы слайда берутся из категории
и слов в названии/площадке. Фото не повторяется 7 дней (журнал data/background-usage.json) и никогда дважды
в одном наборе. Нет подходящего — None: слайд получает фирменный фон.

Проверка: python3 tools/stories/backgrounds.py --test [YYYY-MM-DD]
"""
import json, re, subprocess, sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "library"
USAGE = ROOT / "data" / "background-usage.json"
REPEAT_DAYS = 7

CATEGORY = {
    "концерт": ["concert", "night"], "театр": ["theater", "culture"], "выставка": ["museum", "art"],
    "рынок": ["market", "altstadt"], "фестиваль": ["fair", "altstadt"], "детям": ["kids", "zoo", "park"],
    "спорт": [], "вечеринка": ["night"], "вечер": ["night"], "кино": ["culture", "night"],
    "лекция": ["culture"], "экскурсия": ["altstadt", "city"],
}
WORDS = [
    (r"fortuna|merkur spiel|arena düsseldorf|esprit arena|fußball|football", ["football", "stadium"]),
    (r"\bdeg\b|psd bank dome|eishockey|hockey", ["hockey"]),
    (r"rheinturm", ["rheinturm"]), (r"medienhafen|hafen", ["medienhafen"]),
    (r"rhein|ufer|schiff|\bkd\b|promenade", ["rhein"]), (r"brücke|bridge", ["bridge"]),
    (r"altstadt|burgplatz|marktplatz|bolker|carlsplatz", ["altstadt"]),
    (r"königsallee|\bkö\b|kö-bogen", ["koe"]), (r"hofgarten", ["hofgarten", "park"]),
    (r"nordpark|südpark|volksgarten|park\b|garten", ["park"]), (r"benrath", ["benrath", "castle"]),
    (r"kaiserswerth", ["kaiserswerth"]), (r"oberkassel", ["oberkassel"]), (r"gerresheim", ["gerresheim"]),
    (r"kunstpalast|k20|k21|kunstsammlung|museum|nrw-forum|kit\b|kunsthalle|galerie|ausstellung", ["museum", "art"]),
    (r"tonhalle|klassik|orchester|symphon|philharmon", ["classic", "concert"]),
    (r"oper\b|opernhaus|schauspielhaus|d'haus|theater|kom\(m\)ödchen", ["theater"]),
    (r"messe", ["messe"]), (r"flughafen|airport", ["airport"]), (r"aquazoo|zoo|tier", ["zoo", "kids"]),
    (r"kirmes|riesenrad|rummel", ["kirmes", "fair"]), (r"weihnacht|advent", ["christmas", "market"]),
    (r"trödel|floh|markt", ["market"]), (r"landtag", ["landtag"]), (r"kirche|lambertus|dom\b", ["church"]),
    (r"jazz|konzert|live|band", ["concert", "night"]), (r"party|club|dj", ["night"]),
    (r"japan", ["japan"]), (r"bahn|u-bahn|rheinbahn", ["transport"]),
    # Gemini пишет заголовки по-русски
    (r"фортун|футбол", ["football", "stadium"]), (r"хокке", ["hockey"]), (r"рейнск\w* башн", ["rheinturm"]),
    (r"медиенхафен|гавань", ["medienhafen"]), (r"рейн|набережн|теплоход", ["rhein"]), (r"\bмост", ["bridge"]),
    (r"альтштадт|старый город|старом городе", ["altstadt"]), (r"кё\b|кенигсаллее|кёнигсаллее", ["koe"]),
    (r"хофгартен", ["hofgarten", "park"]), (r"парк|сад\b", ["park"]), (r"бенрат|замок|дворец", ["benrath", "castle"]),
    (r"кайзерсверт", ["kaiserswerth"]), (r"музе|выставк|галере|искусств", ["museum", "art"]),
    (r"тонхалле|симфони|оркестр|классическ", ["classic", "concert"]), (r"опер|театр|спектакл", ["theater"]),
    (r"мессе|ярмарк[аи] messe", ["messe"]), (r"аэропорт", ["airport"]), (r"зоопарк|аквазоо|животн", ["zoo", "kids"]),
    (r"кирмес|колес[оа] обозрени|аттракцион", ["kirmes", "fair"]), (r"рождеств|адвент", ["christmas", "market"]),
    (r"блошин|барахолк|рынок|маркт", ["market"]), (r"ландтаг", ["landtag"]), (r"церк|собор|храм", ["church"]),
    (r"джаз|концерт|рок\b|группа", ["concert", "night"]), (r"вечеринк|клуб|диджей", ["night"]),
]
GENERIC = ["rhein", "rheinturm", "medienhafen", "altstadt", "bridge", "koe", "hofgarten", "city"]


def catalog():
    data = json.loads((LIB / "backgrounds.json").read_text())
    return [it for it in data["items"] if not it.get("exclude") and (LIB / it["file"]).exists()]


def themes(title="", place="", category=""):
    text = f"{title} {place}".lower()
    out = list(CATEGORY.get((category or "").lower(), []))
    for rx, tags in WORDS:
        if re.search(rx, text):
            out = tags + out  # конкретное место важнее категории
    seen = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


def tall(path):
    """Вертикальный или почти квадратный кадр — в сторис почти не обрезается."""
    if str(path).endswith(".mp4"):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    else:
        out = subprocess.run(["identify", "-format", "%w,%h", str(path) + "[0]"], capture_output=True, text=True).stdout
    try:
        w, h = map(int, out.split(",")[:2])
        return h / w >= 0.95
    except ValueError:
        return False


def video_len(path):
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(path)], capture_output=True, text=True).stdout)
    except ValueError:
        return 0.0


class Picker:
    def __init__(self, today):
        self.today = today
        self.items = catalog()
        self.usage = json.loads(USAGE.read_text()) if USAGE.exists() else {}
        self.taken = set()

    def pick(self, wanted, min_video=0.0, allow_video=True):
        """wanted — темы по важности. Возвращает запись каталога или None (тогда фирменный фон)."""
        if not wanted:
            return None
        weight = {t: len(wanted) - i for i, t in enumerate(wanted)}
        fresh_since = (self.today - timedelta(days=REPEAT_DAYS)).isoformat()
        scored = []
        for it in self.items:
            if it["file"] in self.taken:
                continue
            is_video = it["file"].endswith(".mp4")
            if is_video and (not allow_video or video_len(LIB / it["file"]) < min_video):
                continue
            score = sum(weight.get(t, 0) for t in it["tags"])
            if score <= 0:
                continue
            if "_tall" not in it:
                it["_tall"] = tall(LIB / it["file"])
            score += 0.5 if it["_tall"] else 0  # при равном смысле — вертикальный кадр
            last = self.usage.get(it["file"], "")
            scored.append((last < fresh_since, score, last, it))
        if not scored:
            return None
        # сначала давно не использованные, среди них — лучшее совпадение, потом самое давнее
        scored.sort(key=lambda x: (not x[0], -x[1], x[2]))
        best = scored[0][3]
        self.taken.add(best["file"])
        self.usage[best["file"]] = self.today.isoformat()
        return best

    def save(self):
        USAGE.parent.mkdir(exist_ok=True)
        keep = (self.today - timedelta(days=60)).isoformat()
        USAGE.write_text(json.dumps({k: v for k, v in sorted(self.usage.items()) if v >= keep}, indent=1) + "\n")


if __name__ == "__main__" and "--test" in sys.argv:
    sys.path.insert(0, str(ROOT / "tools" / "events"))
    day = date.fromisoformat(sys.argv[-1]) if re.match(r"\d{4}-", sys.argv[-1]) else date.today()
    evs = json.loads((ROOT / "data" / "events.json").read_text())["events"]
    usage = None
    for d in range(3):
        cur = day + timedelta(days=d)
        p = Picker(cur)
        p.usage = usage if usage is not None else {}
        todays = [e for e in evs if e["date"] == cur.isoformat() and not e.get("traffic")][:7]
        print(f"\n== {cur}")
        print("  обложка:", (p.pick(GENERIC) or {}).get("file"))
        for e in todays:
            th = themes(e["title"], e.get("venue", ""), e.get("category", ""))
            got = p.pick(th, min_video=6)
            print(f"  {e['title'][:42]:42} | {','.join(th[:3]):28} → {got['file'] if got else 'фирменный фон'}")
        usage = p.usage
