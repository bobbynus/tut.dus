#!/usr/bin/env python3
"""Статистика Instagram: что заходит, а что нет — чтобы контент становился лучше сам.

Раз в день (перед сборкой сторис на завтра) собирает охват/сохранения/репосты постов за 30 дней
и сторис за последние сутки (у сторис статистика живёт 24 ч, потом пропадает) в data/insights.json.
Пишет короткую сводку data/insights.md и отдаёт подсказку для отбора событий (hints()):
какие темы сторис удерживают зрителя лучше. Ошибки API (например, нет права на статистику)
не ломают сборку — просто печатаются.
Окружение: IG_ACCESS_TOKEN. Запуск: insights.py
"""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://graph.instagram.com/v23.0"
DATA = ROOT / "data" / "insights.json"
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
METRICS = {"story": "reach,replies,shares",
           "reel": "reach,views,saved,shares,total_interactions",
           "carousel": "reach,saved,shares,total_interactions",
           "image": "reach,saved,shares,total_interactions"}


def get(path, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode(errors="replace")[:200]) from None


def metrics(media_id, kind):
    out = {}
    for m in get(f"{media_id}/insights", metric=METRICS[kind]).get("data", []):
        out[m["name"]] = (m.get("values") or [{}])[0].get("value", m.get("total_value", {}).get("value"))
    if kind == "story":  # пролистали вперёд / вышли / вернулись назад — отдельным запросом
        try:
            for m in get(f"{media_id}/insights", metric="navigation", breakdown="story_navigation_action_type").get("data", []):
                for b in (m.get("total_value", {}).get("breakdowns") or [{}])[0].get("results", []):
                    out[b["dimension_values"][0].lower()] = b["value"]
        except Exception:
            pass
    return out


def collect():
    data = json.loads(DATA.read_text()) if DATA.exists() else {}
    now = datetime.now(timezone.utc)
    ok = failed = 0
    for pub in sorted(ROOT.glob("posts/*/published.json")):
        post_dir = pub.parent
        spec = json.loads((post_dir / "post.json").read_text())
        info = json.loads(pub.read_text())
        when = datetime.fromisoformat(info["published_at"].replace("Z", "+00:00").replace("+0000", "+00:00"))
        kind = spec["type"]
        age = now - when
        if kind == "story" and age > timedelta(hours=23) or age > timedelta(days=30):
            continue  # у сторис статистика пропадает через сутки; старые посты уже не меняются
        ids = info.get("media_ids") or [info.get("media_id")]
        rec = {"type": kind, "published_at": info["published_at"], "title": spec.get("title", post_dir.name),
               "checked_at": now.isoformat(timespec="minutes"), "items": []}
        try:
            for mid in ids:
                rec["items"].append({"id": mid, **metrics(mid, kind)})
            if kind == "story" and (post_dir / "pick.json").exists():
                pick = json.loads((post_dir / "pick.json").read_text())
                rec["tags"] = [h.get("tag", "") for h in pick.get("highlights", [])[:3]]
            data[post_dir.name] = rec
            ok += 1
        except Exception as e:
            failed += 1
            print(f"✗ {post_dir.name}: {e}")
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"Статистика: обновлено {ok}, ошибок {failed}")
    report(data)


def story_hold(rec):
    """Доля зрителей первой сторис, дошедших до последней (0…1)."""
    reach = [i.get("reach") or 0 for i in rec["items"]]
    return reach[-1] / reach[0] if len(reach) > 1 and reach[0] else None


def report(data):
    lines = [f"# Что заходит (обновлено {datetime.now():%d.%m.%Y})", ""]
    posts = [(k, v) for k, v in data.items() if v["type"] != "story" and v["items"]]
    posts.sort(key=lambda kv: -(kv[1]["items"][0].get("reach") or 0))
    if posts:
        lines += ["## Посты и рилсы (охват / сохранения / репосты)", ""]
        for k, v in posts[:15]:
            i = v["items"][0]
            lines.append(f"- {v['published_at'][:10]} {v['title']}: {i.get('reach', '—')} / {i.get('saved', '—')} / {i.get('shares', '—')}"
                         + (f", просмотров {i['views']}" if i.get("views") else ""))
    stories = sorted(((k, v) for k, v in data.items() if v["type"] == "story" and v["items"]), key=lambda kv: kv[0])[-14:]
    if stories:
        lines += ["", "## Утренние сторис (охват первой → последней)", ""]
        for k, v in stories:
            reach = [str(i.get("reach", "—")) for i in v["items"]]
            lines.append(f"- {k[6:]}: {' → '.join(reach)}  темы: {', '.join(v.get('tags', [])) or '—'}")
    hint = hints(data)
    if hint:
        lines += ["", f"Подсказка для отбора: {hint}"]
    (ROOT / "data" / "insights.md").write_text("\n".join(lines) + "\n")


def hints(data=None):
    """Какие темы главных событий лучше удерживают зрителя сторис (нужно ≥ 10 дней данных)."""
    if data is None:
        data = json.loads(DATA.read_text()) if DATA.exists() else {}
    by_tag, days = {}, 0
    for v in data.values():
        if v["type"] != "story" or story_hold(v) is None:
            continue
        days += 1
        for t in v.get("tags", []):
            by_tag.setdefault(t, []).append(story_hold(v))
    if days < 10:
        return ""
    avg = sorted(((sum(x) / len(x), t) for t, x in by_tag.items() if len(x) >= 3 and t), reverse=True)
    if len(avg) < 3:
        return ""
    return (f"по статистике лучше досматривают темы: {', '.join(t for _, t in avg[:3])}; "
            f"хуже — {avg[-1][1]} (учитывай, но разнообразие важнее)")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Нет IG_ACCESS_TOKEN")
    collect()
