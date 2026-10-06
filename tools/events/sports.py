"""Матчи местных команд: Fortuna (OpenLigaDB), DEG (iCal с официального сайта)."""
import json, re, urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
UA = {"User-Agent": "Mozilla/5.0 (tut.dus events)"}


def _get(url, timeout=40):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "replace")


def fortuna(report):
    today = date.today()
    season = today.year if today.month >= 7 else today.year - 1
    out = []
    for lg in ("bl1", "bl2", "bl3", "dfb"):
        try:
            matches = json.loads(_get(f"https://api.openligadb.de/getmatchdata/{lg}/{season}"))
        except Exception as e:
            report.append(f"✗ OpenLigaDB {lg}: {e}"); continue
        for m in matches:
            t1, t2 = m["team1"]["teamName"], m["team2"]["teamName"]
            if "Düsseldorf" not in t1 + t2 or "Fortuna" not in t1 + t2:
                continue
            home = "Düsseldorf" in t1
            opp = t2 if home else t1
            kick = datetime.fromisoformat(m["matchDateTimeUTC"].replace("Z", "+00:00")).astimezone(TZ)
            comp = {"bl1": "Бундеслига", "bl2": "2. Бундеслига", "bl3": "3. Лига", "dfb": "Кубок Германии"}[lg]
            out.append({
                "title": f"Fortuna — {opp}" if home else f"{opp} — Fortuna",
                "date": kick.date().isoformat(), "time": kick.strftime("%H:%M"), "end_date": "",
                "venue": "Merkur Spiel-Arena" if home else f"на выезде ({m.get('location', {}) and m['location'].get('locationCity') or opp})",
                "address": "", "locality": "Düsseldorf" if home else "",
                "price": "", "url": "https://www.f95.de/", "category": "спорт",
                "description": f"{comp}, {m.get('group', {}).get('groupName', '')}".strip(", "),
                "source": "OpenLigaDB", "team": "Fortuna", "away": not home,
            })
        if out:
            report.append(f"✓ Fortuna ({lg}, сезон {season}): {len(out)} матчей")
            break
    return out


def _ics_events(text):
    text = re.sub(r"\r?\n[ \t]", "", text)  # склейка перенесённых строк
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in block.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                f[k.split(";")[0]] = v.replace("\\,", ",").replace("\\n", " ").strip()
                if k.startswith("DTSTART"): f["DTSTART_RAW"] = k
        yield f


def _ics_dt(raw_key, v):
    if "T" not in v:
        return datetime.strptime(v[:8], "%Y%m%d").replace(tzinfo=TZ)
    dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ) if v.endswith("Z") else dt.replace(tzinfo=TZ)


def deg(report):
    try:
        page = _get("https://www.deg-eishockey.de/saison/spielplan/")
        links = re.findall(r'(?:href|value)="((?:webcal|https?)://[^"]+?\.ics[^"]*|[^"]+?\.ics[^"]*)"', page, re.I)
        links += re.findall(r'(webcal://[^"\s<]+)', page)
        if not links:
            report.append("· DEG: ссылка на iCal не найдена"); return []
        from urllib.parse import urljoin, urlparse
        ics, tried = None, []
        for link in dict.fromkeys(links):
            url = urljoin("https://www.deg-eishockey.de/saison/spielplan/", link.replace("webcal://", "https://").replace("&amp;", "&"))
            if not urlparse(url).netloc:
                continue
            tried.append(url)
            try:
                body = _get(url)
                if "BEGIN:VEVENT" in body:
                    ics = body; break
            except Exception:
                pass
        if not ics:
            report.append(f"✗ DEG: iCal не прочитан ({', '.join(tried[:2]) or links[:2]})"); return []
        out = []
        for f in _ics_events(ics):
            if "DTSTART" not in f: continue
            kick = _ics_dt(f.get("DTSTART_RAW", ""), f["DTSTART"])
            summ, loc = f.get("SUMMARY", ""), f.get("LOCATION", "")
            home = bool(re.search(r"^(Düsseldorfer EG|DEG)\b", summ)) or "PSD Bank Dome" in loc
            out.append({
                "title": summ, "date": kick.date().isoformat(), "time": kick.strftime("%H:%M") if "T" in f["DTSTART"] else "",
                "end_date": "", "venue": loc or ("PSD Bank Dome" if home else "на выезде"),
                "address": "", "locality": "Düsseldorf" if home else "", "price": "",
                "url": "https://www.deg-eishockey.de/", "category": "спорт", "description": "DEL2, хоккей",
                "source": "DEG iCal", "team": "DEG", "away": not home,
            })
        report.append(f"✓ DEG (iCal): {len(out)} матчей")
        return out
    except Exception as e:
        report.append(f"✗ DEG: {e}")
        return []
