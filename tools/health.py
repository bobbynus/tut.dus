#!/usr/bin/env python3
"""Ежедневная проверка «нужно ли внимание человека». Проблема → issue в репозитории
с упоминанием владельца (GitHub присылает письмо на почту). Проблема ушла → issue закрывается.

Проверяет: объём репозитория, токен Instagram (работает ли, давно ли продлевался),
вышли ли запланированные посты, готовы ли утренние сторис, свежесть сбора событий,
жив ли Clock, хватает ли свежих своих футажей.
Окружение: GITHUB_TOKEN, GITHUB_REPOSITORY, IG_ACCESS_TOKEN. DRY_RUN=1 — только печать.
"""
import json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import footage

REPO = os.environ.get("GITHUB_REPOSITORY", "bobbynus/tut.dus")
OWNER = REPO.split("/")[0]
GH = f"https://api.github.com/repos/{REPO}"
LABEL = "внимание"
DRY = os.environ.get("DRY_RUN") == "1"
BERLIN = ZoneInfo("Europe/Berlin")
now = datetime.now(BERLIN)

SIZE_WARN_MB = 700          # GitHub советует до 1 ГБ
TOKEN_WARN_DAYS = 45        # токен Instagram живёт 60 дней
TOKEN_FIRST = "2026-10-06"  # когда токен был выдан (до первого продления)
LATE_MIN = 45               # насколько пост может опоздать
FRESH_OWN_MIN = 2           # меньше свободных своих футажей — просим новые


def gh(path, method="GET", body=None):
    req = urllib.request.Request(GH + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "null")


# ---- проверки: каждая возвращает None (всё хорошо) или (заголовок, текст) ----

def check_repo_size():
    mb = gh("")["size"] / 1024
    if mb >= SIZE_WARN_MB:
        return ("Репозиторий приближается к лимиту объёма",
                f"Размер репозитория: **{mb:.0f} МБ** (GitHub советует держать до 1 ГБ).\n\n"
                "Пора почистить историю от старых опубликованных медиа (вариант 3 из обсуждения) "
                "— напишите Claude, он подготовит чистку.")


def check_ig_token():
    token = os.environ.get("IG_ACCESS_TOKEN", "")
    url = "https://graph.instagram.com/v23.0/me?" + urllib.parse.urlencode({"fields": "username", "access_token": token})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            json.loads(r.read())
    except Exception as e:
        detail = e.read().decode()[:300] if hasattr(e, "read") else str(e)
        return ("Токен Instagram не работает — публикации остановлены",
                f"Instagram API отвечает ошибкой:\n```\n{detail}\n```\n"
                "Нужно выпустить новый токен (workflow **Instagram token**) и обновить секрет `IG_ACCESS_TOKEN`.")
    f = ROOT / "data" / "ig-token.json"
    last = json.loads(f.read_text())["refreshed_at"][:10] if f.exists() else TOKEN_FIRST
    age = (date.today() - date.fromisoformat(last)).days
    if age >= TOKEN_WARN_DAYS:
        return ("Токен Instagram скоро истечёт",
                f"Токен последний раз продлевался **{last}** ({age} дн. назад), живёт 60 дней.\n\n"
                "Автопродление (workflow **Instagram token — refresh**) не срабатывает. Чаще всего не задан "
                "секрет `GH_PAT` (токен GitHub с правом записи секретов). Добавьте его и запустите workflow вручную.")


def check_refresh_runs():
    runs = gh("/actions/workflows/ig-refresh.yml/runs?per_page=1").get("workflow_runs", [])
    if runs and runs[0]["conclusion"] == "failure":
        return ("Не удалось продлить токен Instagram",
                f"Последний запуск продления упал: {runs[0]['html_url']}\n\n"
                "Скорее всего, не задан секрет `GH_PAT`. Без продления токен истечёт через 60 дней после выдачи.")


def check_overdue_posts():
    late = []
    for spec_f in sorted((ROOT / "posts").glob("*/post.json")):
        spec = json.loads(spec_f.read_text())
        if spec.get("status") != "scheduled" or (spec_f.parent / "published.json").exists():
            continue
        due = datetime.fromisoformat(spec["publish_at"])
        if now - due > timedelta(minutes=LATE_MIN):
            late.append(f"- `{spec_f.parent.name}` — должен был выйти {due:%d.%m %H:%M}")
    if late:
        return ("Посты не вышли вовремя",
                "Эти посты запланированы, но не опубликованы:\n" + "\n".join(late) +
                "\n\nСмотрите логи workflow **Clock**. Claude может опубликовать вручную.")


def check_today_stories():
    if (ROOT / "AUTOPOST_PAUSED").exists() or now.hour < 9:
        return
    if not (ROOT / "posts" / f"daily-{now.date()}" / "post.json").exists():
        return ("Утренние сторис на сегодня не подготовлены",
                f"Нет папки `posts/daily-{now.date()}`. Смотрите логи workflow **Daily stories**.")


def check_events_fresh():
    try:
        gen = json.loads((ROOT / "data" / "events.json").read_text())["generated_at"][:10]
    except Exception:
        gen = "2000-01-01"
    if (now.date() - date.fromisoformat(gen)).days >= 2:
        return ("Сбор событий не работает",
                f"Последний сбор событий: **{gen}**. Смотрите логи workflow **Events collect** "
                "(возможно, исчерпан лимит Gemini или сломался источник).")


def check_clock():
    runs = gh("/actions/workflows/clock.yml/runs?per_page=5").get("workflow_runs", [])
    if not any(r["status"] in ("in_progress", "queued", "waiting", "requested") for r in runs):
        return ("Clock остановлен — публикации по расписанию не идут",
                "Нет активного запуска workflow **Clock**. Запустите его вручную: Actions → Clock → Run workflow.")


def check_footage():
    rows = footage.report(probe=False)
    fresh = sum(r["fresh"] and r["own"] for r in rows)
    if fresh < FRESH_OWN_MIN:
        return ("Нужны свежие футажи",
                f"Своих футажей, не использованных последние 14 дней: **{fresh}**. "
                "Загрузите новые видео в `library/inbox/` — звук и метаданные удалятся автоматически.")


CHECKS = [check_repo_size, check_ig_token, check_refresh_runs, check_overdue_posts,
          check_today_stories, check_events_fresh, check_clock, check_footage]


def main():
    problems, failed = {}, []
    for check in CHECKS:
        try:
            res = check()
        except Exception as e:
            failed.append(f"{check.__name__}: {e}")
            continue
        status = "✗ " + res[0] if res else "✓"
        print(f"{check.__name__:22} {status}")
        if res:
            problems[res[0]] = res[1]
    if os.environ.get("HEALTH_TEST") == "true":
        problems["Проверка уведомлений ТУТ.DUS"] = ("Это тестовое письмо: так будут приходить напоминания, когда нужно "
                                                    "ваше внимание. Issue закроется сам при следующей проверке.")
    if DRY:
        return
    open_issues = gh(f"/issues?state=open&labels={urllib.parse.quote(LABEL)}&per_page=100")
    open_by_title = {i["title"]: i for i in open_issues}
    for title, body in problems.items():
        if title not in open_by_title:
            gh("/issues", "POST", {"title": title, "labels": [LABEL],
                                   "body": f"@{OWNER} {body}\n\n_Проверка {now:%d.%m.%Y %H:%M}. "
                                           "Issue закроется сам, когда проблема уйдёт._"})
            print("issue открыт:", title)
    checked_ok = not failed  # если какая-то проверка не смогла выполниться, ничего не закрываем
    for title, issue in open_by_title.items():
        if title not in problems and checked_ok:
            gh(f"/issues/{issue['number']}/comments", "POST", {"body": "Проблема больше не наблюдается — закрываю."})
            gh(f"/issues/{issue['number']}", "PATCH", {"state": "closed", "state_reason": "completed"})
            print("issue закрыт:", title)
    for f in failed:
        print("::warning::проверка не выполнена:", f)
    (ROOT / "data" / "health.json").write_text(json.dumps(
        {"checked_at": now.isoformat(timespec="minutes"), "problems": list(problems)}, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
