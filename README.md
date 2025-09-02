# Civitai Bulk Uploader (Playwright)

Script to bulk-post images to Civitai via browser automation (Playwright). It goes **directly** to `https://civitai.com/posts/create` and never touches legacy URLs.

- One-time login with persisted session (`storage_state.json`)
- Batch uploads; group by subfolders or a flat list
- Titles from folder/file name or auto
- Global tags per post
- Local SHA‑256 dedupe in `uploaded.db`
- Detailed logs and a **debug** mode with timestamps and Playwright trace
- Publish confirmation by URL (`/posts/{id}`) with one automatic retry
- Optional minimized browser window (`--minimized`)

> Supported formats by default: `.png`, `.jpg`, `.jpeg`, `.webp`. You can extend `ALLOWED_EXT` in the script.

---

## Requirements

- Python 3.10+
- Playwright 1.45+ (Chromium)
- Dependencies from `requirements.txt`:
  ```text
  playwright
  Pillow
  tenacity
  ```
- A valid Civitai account

---

## Installation

Windows PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

---

## Quick start

1) **Login** (saves `storage_state.json`):
```powershell
python civitai_bulk_uploader.py --login
```
In the opened window, complete Cloudflare/captcha and sign in. To finish either press **Enter** in the console or simply **close the browser window**.

2) **Smoke test** (1 file per post, detailed log, minimized window):
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by flat --post-size 1 --pause 2-4 --thumb-timeout 45 --publish-timeout 30 --debug --log-file "D:\civitai\debug_log.txt" --minimized
```

---

## Usage

### Basic example
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 20 --title-from folder --pause 4-8 --verbose --minimized
```

### Key flags

- `--dir "<path>"` images root (recursive).
- `--group-by folder|flat` how to split batches:
  - `folder` each subfolder → separate post/series
  - `flat` all files in one stream, chunked
- `--post-size N` max images per post (recommended 5–20)
- `--title-from folder|file|auto` post title source
- `--tags "tag1,tag2"` global tags for all created posts
- `--pause A-B` random per-step pause in seconds to mimic human speed
- `--publish-timeout T` seconds to wait for `/posts/{id}` after clicking Publish; one automatic retry if needed
- `--thumb-timeout T` seconds to wait for thumbnails after upload; falls back to `networkidle` after timeout
- `--dry-run` do everything except pressing Publish
- `--skip-hashes` disable local SHA‑256 dedupe
- `--verbose` concise progress logs
- `--debug` ultra-detailed logs with timestamps (every click/fill/wait), mirrored to console and file
- `--log-file "path.txt"` destination for the debug log (default `debug_log.txt`)
- `--trace` save Playwright trace to `trace.zip` (screenshots, DOM snapshots, sources)
- `--minimized` start Chromium minimized/off-screen (ignored for `--login` because you need to see the window)

### Examples

One file per post, logs and trace:
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by flat --post-size 1 --pause 2-4 --thumb-timeout 45 --publish-timeout 30 --debug --log-file "D:\civitai\debug_log.txt" --trace --minimized
```

Per-folder posts, 10 images each, patient waits:
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 10 --pause 4-8 --thumb-timeout 90 --publish-timeout 240 --verbose --minimized
```

Dry run (no publish):
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 5 --dry-run --verbose
```

Disable dedupe (retesting same files):
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 3 --skip-hashes --debug
```

---

## How it works

- Navigates **only** to `https://civitai.com/posts/create`.
- Fills **Title** ASAP; if the field wasn’t ready, retries after upload.
- Upload strategies:
  1) direct `input[type=file]` set
  2) file chooser fallback (if needed)
- Waits for **thumbnails** up to `--thumb-timeout`; then falls back to `networkidle` to avoid stalling.
- Presses **Publish**, waits for URL to become `/posts/{id}`. If it doesn’t, one automatic retry is attempted.
- Maintains a local DB (`uploaded.db`) of SHA‑256 hashes to avoid reposting identical files (unless `--skip-hashes`).

---

## Logs & debugging

### `--verbose`
Concise progress: discovery count, editor opened, thumbnails ready, publish clicked, confirmation.

### `--debug`
Full protocol with timestamps:
- `GOTO` navigations  
- `CLICK try/ok/err` with selectors and outcomes  
- `FILL` field fills  
- `FILES` file inputs  
- `WAIT` waits (selector, networkidle, pre-publish pause)  
- `DONE upload+wait in Xs`, `DONE publish-phase in Ys` durations

The log is mirrored to console and `--log-file`. Optional `--trace` writes `trace.zip` viewable in Playwright Trace Viewer.

---

## Stability tips

- Don’t overstuff posts. 5–20 images per post is a healthy range.
- If thumbnails take long, reduce `--thumb-timeout` so the script falls back sooner.
- Respect Civitai rules and your local law.
- If Civitai changes DOM, adjust selectors in the `SELECTORS` block.

---

## Known limitations

- Civitai has no official **upload** API at the time of writing; this is UI automation.
- Anti-bot pages/captchas may appear; `--login` requires a visible window.
- Success is confirmed by URL change to `/posts/{id}`; on slow networks you may need a larger `--publish-timeout`.

---

## Customize

- **Extensions**: edit `ALLOWED_EXT`.
- **Selectors**: tweak the `SELECTORS` constants if UI shifts.
- **Pacing**: tune `--pause A-B` for your network/environment.

---

## Security & privacy

- Session cookies persist in `storage_state.json`. Keep it private.
- `--debug` logs include local file paths. Store logs in a safe place or disable detailed logging.

---

## License

Use at your own risk. Make sure you follow Civitai policies and applicable laws.

---

---

# Civitai Bulk Uploader (Playwright) — Русская версия

Скрипт для массовой публикации изображений на Civitai через автоматизацию браузера (Playwright). Переходит **только** на `https://civitai.com/posts/create`, старые URL не используются.

- Авторизация один раз с сохранением сессии (`storage_state.json`)
- Загрузка пачками; группировка по подпапкам или плоским списком
- Заголовки из имён папок/файлов или авто
- Общие теги для всех постов
- Локальная дедупликация по SHA‑256 (`uploaded.db`)
- Подробные логи и режим **debug** с таймштампами и трассировкой
- Подтверждение публикации по URL (`/posts/{id}`) с одной автоповторной попыткой
- Опционально запуск браузера в свёрнутом виде (`--minimized`)

> Поддерживаемые форматы по умолчанию: `.png`, `.jpg`, `.jpeg`, `.webp`. Список расширяется через `ALLOWED_EXT` в коде.

---

## Требования

- Python 3.10+
- Playwright 1.45+ (Chromium)
- Зависимости из `requirements.txt`:
  ```text
  playwright
  Pillow
  tenacity
  ```
- Аккаунт Civitai

---

## Установка

Windows PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

---

## Быстрый старт

1) **Логин** (сохранит `storage_state.json`):
```powershell
python civitai_bulk_uploader.py --login
```
В открывшемся окне пройдите Cloudflare/капчу и войдите. Для завершения нажмите **Enter** в консоли или **закройте окно** браузера.

2) **Пробный запуск** (1 файл на пост, детальный лог, свёрнутое окно):
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by flat --post-size 1 --pause 2-4 --thumb-timeout 45 --publish-timeout 30 --debug --log-file "D:\civitai\debug_log.txt" --minimized
```

---

## Использование

### Базовый пример
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 20 --title-from folder --pause 4-8 --verbose --minimized
```

### Ключевые параметры

- `--dir "<путь>"` корень с изображениями (рекурсивно).
- `--group-by folder|flat` как разбивать партии:
  - `folder` каждая подпапка → отдельный пост/серия
  - `flat` все файлы одной очередью, порциями
- `--post-size N` максимум изображений на пост (рекомендую 5–20)
- `--title-from folder|file|auto` источник заголовка
- `--tags "tag1,tag2"` общие теги для всех постов
- `--pause A-B` случайные паузы между шагами в секундах
- `--publish-timeout T` ожидание смены URL на `/posts/{id}` после Publish; при необходимости одна автопопытка
- `--thumb-timeout T` ожидание появления миниатюр; по таймауту — fallback на `networkidle`
- `--dry-run` выполняет всё, кроме нажатия Publish
- `--skip-hashes` отключить дедуп по SHA‑256
- `--verbose` краткие логи прогресса
- `--debug` детальные логи с таймштампами (каждый клик/заполнение/ожидание), в консоль и файл
- `--log-file "path.txt"` путь к файлу лога для `--debug` (по умолчанию `debug_log.txt`)
- `--trace` сохранить Playwright trace в `trace.zip`
- `--minimized` запуск Chromium свёрнутым/вне экрана (для `--login` игнорируется)

### Примеры

Один файл на пост, логи и трасса:
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by flat --post-size 1 --pause 2-4 --thumb-timeout 45 --publish-timeout 30 --debug --log-file "D:\civitai\debug_log.txt" --trace --minimized
```

Посты по папкам, 10 изображений, спокойные паузы:
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 10 --pause 4-8 --thumb-timeout 90 --publish-timeout 240 --verbose --minimized
```

Черновой прогон без публикации:
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 5 --dry-run --verbose
```

Отключить дедуп (для повторных тестов тех же файлов):
```powershell
python civitai_bulk_uploader.py --dir "D:\civitai	o_upload" --group-by folder --post-size 3 --skip-hashes --debug
```

---

## Как это работает

- Скрипт **переходит только** на `https://civitai.com/posts/create`.
- Пытается заполнить **Title** сразу; при неготовом поле — повторяет попытку после загрузки.
- Стратегии загрузки:
  1) прямая подстановка в `input[type=file]`
  2) при необходимости fallback через file chooser
- Ожидание **миниатюр** до `--thumb-timeout`, дальше — fallback на `networkidle`.
- Жмёт **Publish**, ждёт URL `/posts/{id}`. Если не дождался — одна автопопытка.
- Ведёт локальную БД (`uploaded.db`) с SHA‑256 для избегания повторов (если не указан `--skip-hashes`).

---

## Логи и отладка

### `--verbose`
Коротко: сколько найдено файлов, редактор открыт, миниатюры готовы, Publish, подтверждение.

### `--debug`
Полный протокол с таймштампами:
- `GOTO` переходы  
- `CLICK try/ok/err` селекторы и результат  
- `FILL` заполнение полей  
- `FILES` подстановка путей  
- `WAIT` ожидания (селектор, networkidle, задержка перед публикацией)  
- `DONE upload+wait in Xs`, `DONE publish-phase in Ys` длительности этапов

Лог дублируется в консоль и файл `--log-file`. Опция `--trace` сохраняет `trace.zip` для просмотра в Playwright Trace Viewer.

---

## Советы по стабильности

- Не перегружайте посты. 5–20 изображений на пост — адекватный диапазон.
- Если миниатюры долго «склеиваются», уменьшайте `--thumb-timeout`, чтобы быстрее перейти к fallback.
- Соблюдайте правила Civitai и законы вашей страны.
- При изменении разметки Civitai обновите селекторы в `SELECTORS`.

---

## Ограничения

- Официального API Civitai для **загрузки** пока нет; автоматизация через UI.
- Возможны антибот/капчи; для `--login` нужно видимое окно.
- Успех публикации — по смене URL на `/posts/{id}`; на медленной сети увеличивайте `--publish-timeout`.

---

## Настройка

- **Расширения**: правьте `ALLOWED_EXT`.
- **Селекторы**: корректируйте `SELECTORS` при изменениях UI.
- **Паузы**: подбирайте `--pause A-B` под своё окружение.

---

## Безопасность и приватность

- Сессия хранится в `storage_state.json`. Не делитесь файлом.
- В `--debug` лог пишутся локальные пути к файлам. Храните логи приватно или отключайте подробный режим.

---

## Лицензия

Используйте на свой страх и риск. Следуйте правилам Civitai и применимому законодательству.
