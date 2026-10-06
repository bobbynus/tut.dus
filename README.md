# ТУТ.DUS

Instagram о Дюссельдорфе на русском: что происходит сегодня, куда пойти, к кому обратиться.
Схема названия «ТУТ + код города» (DUS, CGN, BER) позволяет расширяться на другие города.

## Структура

| Папка | Что там |
|---|---|
| `design/` | Бренд (`brand.css`), HTML-шаблоны слайдов, рендер в PNG |
| `posts/NN-name/` | Готовые слайды и текст каждого поста |
| `profile/` | Оформление профиля: описание, аватар, обложки «Актуального», ответы в директ |

## Как собрать слайды

```bash
cd design
npm install                                   # шрифты Unbounded и Golos Text
node render.cjs 01-intro.html ../posts/01-intro
```

Холст 1080×1350 (4:5), аватар 1080×1080.

## Публикация

Публикует GitHub Actions, токены лежат в секретах репозитория.

1. Пост — папка `posts/NN-name/` со слайдами или видео, `caption.txt` и `post.json`
   (формат описан в начале `tools/publish.py`).
2. `"status": "scheduled"` и время в `publish_at` → workflow **Publish** (запускается каждые 15 минут)
   опубликует пост и положит рядом `published.json` со ссылкой.
3. `"status": "draft"` — пост не публикуется.

Ручной запуск: Actions → Publish → Run workflow (можно указать папку поста и режим проверки).

## Reels с футажами и музыкой

```bash
python3 tools/make_reel.py posts/NN-name/reel.json
```

Футажи и музыка лежат в `library/` (см. `library/README.md`). Стоковые футажи скачивает workflow
**Fetch footage** (нужен секрет `PEXELS_API_KEY`).

## Workflows

| Workflow | Что делает |
|---|---|
| Publish | Публикует посты по расписанию |
| Fetch footage | Скачивает вертикальные футажи с Pexels |
| Instagram API check | Проверяет, что токен рабочий |
| Instagram token — get / refresh | Получает токен и продлевает его 1-го и 15-го числа |
