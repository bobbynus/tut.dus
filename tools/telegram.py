"""Зеркало постов в Telegram-канал через Bot API.

Секреты: TG_BOT_TOKEN (от @BotFather), TG_CHANNEL (@имя_канала). Бот — админ канала с правом публикации.
Telegram сам скачивает картинки и видео по публичным ссылкам (репозиторий публичный).
"""
import json, os, re, urllib.parse, urllib.request, urllib.error

TOKEN = os.environ.get("TG_BOT_TOKEN", "")
CHANNEL = os.environ.get("TG_CHANNEL", "")


def enabled():
    return bool(TOKEN and CHANNEL)


def api(method, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                                   for k, v in params.items()}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        res = json.loads(e.read().decode() or "{}")
    if not res.get("ok"):
        raise RuntimeError(f"Telegram {method}: {res.get('description', res)}")
    return res["result"]


def clean_caption(text):
    """Хэштеги в Telegram не нужны — убираем строки, состоящие из хэштегов."""
    lines = [l for l in text.splitlines() if not re.fullmatch(r"\s*(#\S+\s*)+", l)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def publish(kind, urls, caption=""):
    """kind: carousel | image | reel | story. Возвращает id сообщений."""
    caption = clean_caption(caption)
    short = caption if len(caption) <= 1024 else ""  # лимит подписи к медиа — 1024 символа
    ids = []
    is_video = lambda u: u.lower().split("?")[0].endswith((".mp4", ".mov"))
    if kind == "reel" or (len(urls) == 1 and is_video(urls[0])):
        ids.append(api("sendVideo", chat_id=CHANNEL, video=urls[0], caption=short, supports_streaming="true")["message_id"])
    elif len(urls) == 1:
        ids.append(api("sendPhoto", chat_id=CHANNEL, photo=urls[0], caption=short)["message_id"])
    else:
        media = [{"type": "video" if is_video(u) else "photo", "media": u} for u in urls[:10]]
        if short:
            media[0]["caption"] = short
        ids += [m["message_id"] for m in api("sendMediaGroup", chat_id=CHANNEL, media=media)]
    if caption and not short:
        ids.append(api("sendMessage", chat_id=CHANNEL, text=caption[:4096], disable_web_page_preview="true")["message_id"])
    return ids


# ---------- Личка владельца: черновики постов, которые он публикует сам (с музыкой из приложения) ----------
# chat id храним в репозитории в зашифрованном виде: расшифровать может только тот, у кого есть токен бота.
from pathlib import Path
import hashlib, html as _html

OWNER_FILE = Path(__file__).resolve().parents[1] / "data" / "telegram-owner.json"


def _xor(data: bytes) -> bytes:
    key = hashlib.sha256(("tut.dus-owner:" + TOKEN).encode()).digest()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def owner_chat():
    """chat id владельца. Если ещё не знаем — ищем /start в личке бота (Telegram хранит сообщения сутки)."""
    if not TOKEN:
        return None
    if OWNER_FILE.exists():
        return int(_xor(bytes.fromhex(json.loads(OWNER_FILE.read_text())["chat"])).decode())
    for upd in api("getUpdates", allowed_updates=["message"]):
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and (msg.get("text") or "").startswith("/start"):
            OWNER_FILE.parent.mkdir(exist_ok=True)
            OWNER_FILE.write_text(json.dumps({"chat": _xor(str(chat["id"]).encode()).hex()}) + "\n")
            api("sendMessage", chat_id=chat["id"], text="Готово! Сюда будут приходить черновики постов ТУТ.DUS: "
                "картинки, подпись и подсказка, какую музыку поставить.")
            return chat["id"]
    return None


def send_draft(chat, urls, caption, header):
    """Черновик в личку: пояснение, файлы без сжатия (документами) и подпись, которую удобно скопировать."""
    ids = [api("sendMessage", chat_id=chat, text=header, parse_mode="HTML")["message_id"]]
    for i in range(0, len(urls), 10):
        media = [{"type": "document", "media": u} for u in urls[i:i + 10]]
        ids += [m["message_id"] for m in api("sendMediaGroup", chat_id=chat, media=media)]
    ids.append(api("sendMessage", chat_id=chat, parse_mode="HTML",
                   text="Подпись — кнопка «Копировать» в углу блока:\n<pre>" + _html.escape(caption[:3900]) + "</pre>")["message_id"])
    return ids
