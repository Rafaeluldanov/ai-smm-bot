# AI-SMM-бот

Автоматизированный бот для ведения соцсетей проектов компании. Бот сам выбирает темы
публикаций на основе анализа рынка, SEO, трендов, сезонности и наличия медиа в хранилище,
генерирует тексты под каждую соцсеть, подбирает фото/видео с Яндекс Диска, отправляет на
согласование и публикует.

Продвигаемые проекты:

- **TEEON** ([teeon.ru](https://teeon.ru)) — корпоративная и промо-одежда, мерч: футболки,
  худи, свитшоты, лонгсливы, поло, жилеты, сумки; шелкография, DTF, DTG, вышивка, жаккард.
- **Фабрика сувениров** — сувенирная продукция: шелкография, УФ-печать, тампопечать,
  гравировка, кружки, ручки, текстиль, пакеты, корпоративные подарки.

> Подробная документация — в папке [`Докс/`](./Докс/).

## Технологический стек

Python 3.11+, FastAPI, Pydantic Settings, SQLAlchemy, Alembic, PostgreSQL, Redis,
pytest, ruff, mypy, Docker Compose, Makefile.

## Структура проекта

```
.
├── Докс/            # Проектная документация
├── backend/
│   ├── app/         # FastAPI-приложение (api, core, db, models, schemas,
│   │                #   services, integrations, ai, scheduler, utils)
│   └── tests/       # Тесты
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

## Быстрый старт (локально)

```bash
# 1. Установка зависимостей в виртуальное окружение .venv
make install

# 2. Конфигурация
cp .env.example .env   # при необходимости отредактируйте значения

# 3. Запуск dev-сервера
make run
```

После запуска проверьте здоровье и готовность сервиса:

```bash
# Liveness — сервис жив
curl http://localhost:8000/health
# {"status":"ok","service":"ai-smm-bot"}

# Readiness — окружение, тип БД и настроенные интеграции (без сети)
curl http://localhost:8000/health/readiness
# {"status":"ready","app_env":"local","database":"postgresql",
#  "integrations":{"telegram":false,"vk":false,"yandex_disk":false,"ai":false},"warnings":[]}
```

Быстрая смоук-проверка без сети (поднимает приложение и дёргает health/readiness):

```bash
make smoke
```

Документация API (Swagger): http://localhost:8000/docs

## Запуск через Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Поднимаются три сервиса: PostgreSQL, Redis и backend (FastAPI на порту 8000).

## Команды разработки

| Команда           | Назначение                              |
| ----------------- | --------------------------------------- |
| `make install`                  | Создать `.venv` и установить зависимости          |
| `make run`                      | Запустить dev-сервер FastAPI                      |
| `make db-up`                    | Поднять контейнеры БД и кэша (`db`, `redis`)      |
| `make db-down`                  | Остановить контейнеры БД и кэша                   |
| `make migrate`                  | Применить миграции (`alembic upgrade head`)       |
| `make revision message="..."`   | Создать новую миграцию Alembic                    |
| `make seed-projects`            | Заполнить БД проектами (идемпотентно)             |
| `make sync-media project_slug=teeon` | Синхронизация медиа проекта с Яндекс Диска   |
| `make sync-public-media project_slug=teeon` | Публичная синхронизация (без токена)  |
| `make retag-media project_slug=teeon` | Перетегировать медиа проекта (по данным из БД) |
| `make media-summary project_slug=teeon` | Сводка по тегам медиа проекта               |
| `make enhance-media media_asset_id=1` | Улучшить медиа — создать копию (оригинал не трогается) |
| `make enhance-project-media project_slug=teeon` | Улучшить медиа проекта (копии)        |
| `make media-enhancement-summary project_slug=teeon` | Сводка по улучшенным копиям       |
| `make select-topics project_slug=teeon` | Выбрать темы проекта                         |
| `make content-plan project_slug=teeon` | Недельный контент-план тем                    |
| `make generate-post topic_id=1` | Сгенерировать черновик поста по теме              |
| `make generate-weekly-posts project_slug=teeon` | Сгенерировать посты на неделю        |
| `make review-post post_id=1 action=submit` | Действие согласования поста             |
| `make approve-post post_id=1`   | Одобрить пост                                     |
| `make reject-post post_id=1`    | Отклонить пост                                    |
| `make schedule-post post_id=1`  | Запланировать публикации поста                     |
| `make publish-post post_id=1`   | Опубликовать пост (Telegram/VK)                   |
| `make publish-due`              | Опубликовать созревшие публикации                  |
| `make ingest-analytics post_id=1` | Ввести метрики поста вручную                     |
| `make analytics-report project_slug=teeon` | Отчёт аналитики проекта                |
| `make search-external-images project_slug=teeon query="..."` | Поиск внешних картинок |
| `make convert-external-image candidate_id=1` | Конвертировать кандидата в MediaAsset |
| `make autonomous-run project_slug=teeon` | Автономный прогон pipeline               |
| `make autonomous-dry-run project_slug=teeon` | Сухой автономный прогон             |
| `make autonomous-report run_id=1` | Отчёт по автономному прогону                    |
| `make smoke`                    | Смоук-проверка (health/readiness, без сети)        |
| `make test`                     | Запустить тесты (pytest)                          |
| `make lint`                     | Линтинг (ruff)                                    |
| `make format`                   | Форматирование (ruff)                             |
| `make typecheck`                | Проверка типов (mypy)                             |
| `make check`                    | Полная проверка: ruff + mypy + pytest             |

> Перед переходом к следующему этапу разработки команда `make check` должна проходить успешно.

> Тесты используют SQLite в памяти, поэтому `make check` не зависит от запущенного
> Docker/PostgreSQL.

## Порядок запуска локально

Полная последовательность для запуска с реальной БД (PostgreSQL):

```bash
# 1. Установка зависимостей в виртуальное окружение .venv
make install

# 2. Конфигурация (при необходимости отредактируйте значения)
cp .env.example .env

# 3. Поднять PostgreSQL и Redis в Docker
make db-up

# 4. Применить миграции (создаст таблицы projects, media_assets, topics, posts)
make migrate

# 5. Заполнить БД проектами (TEEON, «Фабрика сувениров»)
make seed-projects

# 6. Запустить dev-сервер
make run
```

## Медиа с Яндекс Диска

Медиа-материалы проектов хранятся на Яндекс Диске и подтягиваются в БД (таблица
`media_assets`) синхронизацией. Для доступа к Диску нужен OAuth-токен в `.env`:

```dotenv
YANDEX_DISK_TOKEN=ваш_OAuth_токен
```

Без токена обычный API работает (например, `GET /media-assets` читает уже
сохранённые записи), а sync-эндпоинты возвращают `503`.

Структура хранилища — `/SMM_BOT/<папка_проекта>/<подпапки>`:

```
/SMM_BOT/
├── 01_TEEON/                # проект teeon
│   ├── 01_Входящие_на_разбор
│   ├── 02_Одобренные_фото
│   ├── 03_Видео
│   ├── 04_Внешние_картинки_из_интернета
│   ├── 05_Использовано_в_постах
│   └── 06_Нужно_переснять
└── 02_Фабрика_сувениров/    # проект fabric-souvenirs
    └── ... (те же подпапки)
```

На **Этапе 2** синхронизация только **читает** Диск (сканируются первые 4 папки:
`01_Входящие_на_разбор`, `02_Одобренные_фото`, `03_Видео`,
`04_Внешние_картинки_из_интернета`) и создаёт/обновляет записи `media_assets` —
сами файлы **не скачиваются**. Повторная синхронизация идемпотентна (бизнес-уникальность
по `yandex_disk_path`, дубликаты не создаются).

Порядок ручной синхронизации (локально):

```bash
# 1. Поднять PostgreSQL и Redis в Docker
make db-up

# 2. Применить миграции
make migrate

# 3. Заполнить БД проектами (TEEON, «Фабрика сувениров»)
make seed-projects

# 4. Синхронизировать медиа проекта с Яндекс Диска
make sync-media project_slug=teeon
```

Скрипт печатает отчёт (`scanned_folders` / `found` / `created` / `updated` /
`skipped` / `errors`). Если `YANDEX_DISK_TOKEN` не задан — выводится понятное сообщение.

## API проектов

Базовый префикс — `/projects`. Все ответы типизированы (`ProjectRead`).
Удаления из БД нет: деактивация выставляет `is_active=false`, но запись сохраняется.

**Правило для `slug`:** разрешены только латиница, цифры, `-` и `_`; значение приводится
к нижнему регистру (`TEEON` → `teeon`); минимальная длина — 2 символа. Пробелы и кириллица
отклоняются с кодом `422`.

```bash
# Список проектов (по умолчанию active_only=true)
curl http://localhost:8000/projects

# Список всех проектов, включая деактивированные
curl "http://localhost:8000/projects?active_only=false"

# Создать проект (201; дубль slug → 409; невалидный slug → 422)
curl -X POST http://localhost:8000/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "TEEON", "slug": "teeon", "website_url": "https://teeon.ru"}'

# Получить проект по slug (404, если не найден)
curl http://localhost:8000/projects/slug/teeon

# Получить проект по id (404, если не найден)
curl http://localhost:8000/projects/1

# Частичное обновление (404, если нет; новый занятый slug → 409)
curl -X PATCH http://localhost:8000/projects/1 \
  -H "Content-Type: application/json" \
  -d '{"name": "TEEON Store"}'

# Деактивировать проект (404, если не найден)
curl -X POST http://localhost:8000/projects/1/deactivate
```

Коды ответов: `201` — проект создан; `404` — проект не найден; `409` — slug уже занят;
`422` — невалидный slug (пробелы, кириллица, недопустимые символы или короче 2 символов).

## API медиа

Базовый префикс — `/media-assets`. Чтение (`GET`) работает без токена; синхронизация
(`POST .../sync/...`) обращается к Яндекс Диску и требует `YANDEX_DISK_TOKEN`.

```bash
# Список медиа (200)
curl http://localhost:8000/media-assets

# С фильтрами по проекту и статусу
curl "http://localhost:8000/media-assets?project_id=1&status=approved"

# Медиа по id (404, если не найдено)
curl http://localhost:8000/media-assets/1

# Синхронизировать медиа проекта по slug (200; 404 — нет проекта;
#   503 — нет/отклонён токен; 400 — неизвестная папка проекта)
curl -X POST http://localhost:8000/media-assets/sync/slug/teeon

# Синхронизировать медиа проекта по id (те же коды ответов)
curl -X POST http://localhost:8000/media-assets/sync/project/1
```

Коды ответов: `200` — успех (чтение или синхронизация); `404` — медиа/проект не найден;
`503` — синхронизация недоступна (`YANDEX_DISK_TOKEN` не задан или отклонён).

#### Публичная папка Яндекс Диска (без токена)

Альтернатива OAuth-токену: медиа можно читать из **публичной папки** SMM. OAuth-токен
не нужен. Файлы **не скачиваются** — сохраняются только метаданные.

```dotenv
# .env
YANDEX_DISK_PUBLIC_MODE=true
YANDEX_DISK_PUBLIC_SMM_URL=https://disk.yandex.ru/d/PYnchGnSLKW3yw
YANDEX_DISK_PUBLIC_ROOT_FOLDER=SMM
```

```bash
# Публичная синхронизация по slug/id (200; 404 — нет проекта; 503 — нет публичной ссылки)
curl -X POST http://localhost:8000/media-assets/sync/public/slug/teeon
curl -X POST http://localhost:8000/media-assets/sync/public/project/1

# CLI
make sync-public-media project_slug=teeon
```

**Правила доступа к папкам:** внутри SMM лежат «Тион» и «Фабрика сувениров».
`teeon` видит **только «Тион»**; `fabric-souvenirs` видит **«Тион» + «Фабрика сувениров»**
(teeon никогда не берёт из «Фабрика сувениров»). Подробности —
[`Докс/18_Публичная_папка_Яндекс_Диска.md`](./Докс/18_Публичная_папка_Яндекс_Диска.md).

### Анализ медиа (Этап 3)

Эндпоинты анализа и тегирования разбирают **имя файла и путь** уже сохранённых записей,
поэтому работают **без `YANDEX_DISK_TOKEN`** — данные берутся из БД, сам Яндекс Диск
не дёргается.

```bash
# Сводка по тегам (частоты products/technologies/details/materials/colors/
#   categories/use_cases/audiences). Без project_id — по всем проектам (200)
curl "http://localhost:8000/media-assets/tags/summary?project_id=1"

# Рекомендации по досъёмке (темы с менее чем 2 одобренными медиа →
#   задачи с папкой 06_Нужно_переснять). 404 — нет проекта
curl "http://localhost:8000/media-assets/shooting-suggestions?project_id=1"

# Проанализировать актив и (по умолчанию) сохранить теги/статус (200; 404 — нет актива)
curl -X POST "http://localhost:8000/media-assets/1/analyze?save=true"

# Перетегировать один актив (200; 404 — нет актива)
curl -X POST http://localhost:8000/media-assets/1/retag

# Перетегировать все медиа проекта по id (200; 404 — нет проекта)
curl -X POST http://localhost:8000/media-assets/retag/project/1

# Перетегировать все медиа проекта по slug (200; 404 — нет проекта)
curl -X POST http://localhost:8000/media-assets/retag/slug/teeon

# Сменить статус актива (200; 404 — нет актива; 422 — неизвестный статус;
#   409 — запрещённый переход)
curl -X PATCH http://localhost:8000/media-assets/1/status \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}'
```

Коды ответов анализа: `200` — успех; `404` — актив/проект не найден; `422` — неизвестный
статус в `PATCH .../status`; `409` — запрещённый переход статуса.

> Подробности словарей терминов и правил тегирования — в
> [`Докс/09_Словарь_медиа_тегов.md`](./Докс/09_Словарь_медиа_тегов.md).

### Улучшение медиа (Media Enhancement)

Бот умеет создавать **улучшенные копии** изображений локально (через Pillow):
авто-контраст, мягкая коррекция яркости/насыщенности, лёгкий sharpen, ресайз и
конвертация в рабочий формат (JPEG по умолчанию), а также баланс белого/denoise
в профиле `product_clean`.

- **Оригиналы НЕ изменяются и НЕ перезаписываются.** Каждое улучшение создаёт
  отдельную копию-вариант (`MediaAssetVariant`) и новый файл в
  `MEDIA_ENHANCEMENT_STORAGE_DIR` (по умолчанию `backend/data/enhanced_media`).
- **Видео пропускаются** (только изображения).
- **Спорные правки** (меняющие реальный цвет/текстуру изделия — баланс белого,
  denoise) помечают копию статусом `needs_review` для ручной проверки.
- **Реальной AI-ретуши нет**: удаление пятен/грязи, выравнивание цвета ткани —
  только интерфейс-заглушка (`app/ai/image_editing.py`), реальный AI не подключён.

Профили: `social_safe` (безопасный, по умолчанию), `product_clean` (сильнее,
с балансом белого/denoise → review), `minimal` (только конвертация/ресайз).

```bash
# Улучшить один медиа-актив (создать копию). 200; 404 — нет актива;
#   409 — уже улучшено (нужен force); 400 — формат/источник не поддержан;
#   503 — загрузчик не настроен
curl -X POST http://localhost:8000/media-enhancements/media/1/enhance \
  -H "Content-Type: application/json" -d '{"profile": "social_safe"}'

# Пакетно улучшить медиа проекта (по умолчанию статус approved). 404 — нет проекта
curl -X POST http://localhost:8000/media-enhancements/project \
  -H "Content-Type: application/json" \
  -d '{"project_slug": "teeon", "status": "approved", "profile": "social_safe"}'

# Список вариантов с фильтрами (media_asset_id / project_id / status / variant_type)
curl "http://localhost:8000/media-enhancements?project_id=1"

# Сводка по статусам и типам вариантов
curl "http://localhost:8000/media-enhancements/summary?project_id=1"

# Сменить статус варианта (created|needs_review|approved|rejected|failed).
#   200; 404 — нет варианта; 422 — неизвестный статус
curl -X PATCH http://localhost:8000/media-enhancements/1/status \
  -H "Content-Type: application/json" -d '{"status": "approved"}'

# CLI
make enhance-media media_asset_id=1
make enhance-project-media project_slug=teeon
make media-enhancement-summary project_slug=teeon
```

> Подробности — [`Докс/19_Улучшение_медиа.md`](./Докс/19_Улучшение_медиа.md).

## Статус

Реализованы **Этапы 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 и 10**.

**Этап 0** — каркас проекта: структура, FastAPI с `/health`, конфигурация,
модели данных, сервисы-заглушки, клиенты интеграций (заглушки), проверки и документация.

**Этап 1** — «Проекты»: миграции Alembic (таблицы `projects`, `media_assets`, `topics`,
`posts`), репозиторий и CRUD проектов, схемы с валидацией `slug`, REST API `/projects`
(список, создание, чтение по id/slug, частичное обновление, деактивация) и идемпотентный
seed проектов (`make seed-projects`).

**Этап 2** — «Яндекс Диск»: клиент REST API Яндекс Диска (OAuth-токен,
рекурсивное чтение файлов), сопоставление проектов и папок хранилища
`/SMM_BOT/<проект>/<подпапки>`, сервис синхронизации медиа (классификация по папкам,
теги по имени файла, идемпотентный upsert по `yandex_disk_path`), миграция `0002`
(индексы `media_assets`), REST API `/media-assets` (список с фильтрами, чтение по id,
синхронизация по id/slug) и скрипт `make sync-media`. На этом этапе медиа только
читаются — файлы не скачиваются.

**Этап 3** — «Анализ медиа»: словари терминов и морфологическое сопоставление
(`media_taxonomy`), расширенное тегирование по имени файла и пути (products,
technologies, details, materials, colors, categories, use_cases, audiences, topics,
seo_keywords, `confidence`, `needs_review`), сервис статусов медиа с правилами переходов
(`new`, `approved`, `approved_video`, `needs_license_review`, `rejected`, `needs_reshoot`,
`used`), сервис анализа (анализ/перетегирование, сводка по тегам, рекомендации по досъёмке),
поддержка папки `06_Нужно_переснять`, REST-эндпоинты анализа и `PATCH .../status`, скрипты
`make retag-media` и `make media-summary`. Анализ и перетегирование работают по данным из БД
и **не требуют** `YANDEX_DISK_TOKEN`. Реальный AI-vision пока не подключён (заложена заглушка).

Telegram, VK, Instagram и AI пока не подключены.

Дальнейшие этапы и задачи — см. [`Докс/02_Этапы_разработки.md`](./Докс/02_Этапы_разработки.md)
и [`Докс/08_Следующие_задачи.md`](./Докс/08_Следующие_задачи.md).


<!-- STAGE4_README_START -->

## Этап 4 — Выбор тем

Реализованы **Этапы 0, 1, 2, 3 и 4**.

### Команды

```bash
make select-topics project_slug=teeon
make content-plan project_slug=teeon
```

### API `/topics`

```bash
curl http://localhost:8000/topics
curl http://localhost:8000/topics/1
```

Выбор тем:

```bash
curl -X POST http://localhost:8000/topics/select/slug/teeon \
  -H "Content-Type: application/json" \
  -d '{
    "business_priorities": {
      "футболки": 100,
      "худи": 80,
      "шелкография": 90
    },
    "weeks": 1,
    "posts_per_week": 3
  }'
```

Недельный план:

```bash
curl -X POST http://localhost:8000/topics/weekly-plan/slug/teeon \
  -H "Content-Type: application/json" \
  -d '{
    "business_priorities": {
      "футболки": 100,
      "худи": 80,
      "шелкография": 90
    },
    "weeks": 1,
    "posts_per_week": 3
  }'
```

Смена статуса темы:

```bash
curl -X PATCH http://localhost:8000/topics/1/status \
  -H "Content-Type: application/json" \
  -d '{"status": "planned"}'
```

Подробная логика описана в:

```text
Докс/10_Логика_выбора_тем.md
```
<!-- STAGE4_README_END -->


<!-- STAGE5_README_START -->

## Этап 5 — Генерация постов

Реализованы **Этапы 0, 1, 2, 3, 4 и 5**.

Выбранная тема превращается в черновик `Post` с текстами под Telegram, VK и Instagram, хэштегами, CTA и SEO-ключами; медиа подбирается из одобренных (`approved`/`approved_video`) или пост помечается `needs_media`. Подбор **в первую очередь берёт собственные медиа компании** (`source_type=internal`, `company_owned`); внешние/`external_reference` — только как fallback. В батче (неделя/автономный прогон) медиа **распределяются между постами**, чтобы не ставить один и тот же актив во все посты. Реальный AI, автопостинг и согласование через Telegram пока не подключены.

### Команды

```bash
make generate-post topic_id=1
make generate-weekly-posts project_slug=teeon
```

### API `/posts`

```bash
# Список постов (фильтры project_id / topic_id / status)
curl "http://localhost:8000/posts?project_id=1&status=draft"

# Пост по id (404, если не найден)
curl http://localhost:8000/posts/1

# Сгенерировать черновик по теме (404 — нет темы). Тело опционально:
#   {"recommended_format": "product"}
curl -X POST http://localhost:8000/posts/generate/topic/1 \
  -H "Content-Type: application/json" -d '{}'

# Сгенерировать посты на неделю (404 — нет проекта)
curl -X POST http://localhost:8000/posts/generate/weekly-plan \
  -H "Content-Type: application/json" \
  -d '{"project_slug": "teeon", "weeks": 1, "posts_per_week": 3}'

# Ручная правка черновика (404, если нет)
curl -X PATCH http://localhost:8000/posts/1 \
  -H "Content-Type: application/json" \
  -d '{"title": "Новый заголовок"}'

# Смена статуса (404 — нет; 422 — неизвестный статус; 409 — запрещённый переход)
curl -X PATCH http://localhost:8000/posts/1/status \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}'
```

Статусы поста: `draft`, `needs_media`, `needs_review`, `approved`, `scheduled`, `published`, `rejected`.

Подробная логика генерации — в:

```text
Докс/11_Генерация_постов.md
```
<!-- STAGE5_README_END -->


<!-- STAGE6_README_START -->

## Этап 6 — Согласование постов

Реализованы **Этапы 0, 1, 2, 3, 4, 5 и 6**.

Человек управляет согласованием черновиков: отправить на ревью, одобрить, отклонить, вернуть на доработку, поправить вручную. Все действия пишутся в журнал `PostReviewAction`. Реальный Telegram Bot API **не** подключён — есть только preview-карточка с кнопками; публикация и автопостинг не выполняются.

### Команды

```bash
make review-post post_id=1 action=submit
make approve-post post_id=1
make reject-post post_id=1
```

### API `/post-reviews`

```bash
# Карточка поста и история действий (404 — поста нет)
curl http://localhost:8000/post-reviews/1/card
curl http://localhost:8000/post-reviews/1/timeline

# Превью карточки для Telegram (без реальной отправки)
curl http://localhost:8000/post-reviews/1/telegram-preview

# Решения (тело PostReviewDecisionRequest; 404 — нет; 409 — переход запрещён)
curl -X POST http://localhost:8000/post-reviews/1/submit \
  -H "Content-Type: application/json" \
  -d '{"actor_name": "Stanislav", "actor_role": "manager"}'
curl -X POST http://localhost:8000/post-reviews/1/approve -H "Content-Type: application/json" -d '{}'
curl -X POST http://localhost:8000/post-reviews/1/reject \
  -H "Content-Type: application/json" -d '{"comment": "Поправьте заголовок"}'
curl -X POST http://localhost:8000/post-reviews/1/request-changes -H "Content-Type: application/json" -d '{}'
curl -X POST http://localhost:8000/post-reviews/1/return-to-draft -H "Content-Type: application/json" -d '{}'

# Ручная правка (404 — нет; 409 — нельзя в текущем статусе)
curl -X PATCH http://localhost:8000/post-reviews/1/edit \
  -H "Content-Type: application/json" -d '{"telegram_text": "Новый текст"}'

# Комментарий без смены статуса
curl -X POST http://localhost:8000/post-reviews/1/comment \
  -H "Content-Type: application/json" -d '{"comment": "Согласуем к пятнице"}'
```

Статусы поста: `draft`, `needs_media`, `needs_review`, `approved`, `scheduled`, `published`, `rejected`.

Подробная логика согласования — в:

```text
Докс/12_Согласование_постов.md
```
<!-- STAGE6_README_END -->


<!-- STAGE7_README_START -->

## Этап 7 — Автопостинг

Реализованы **Этапы 0, 1, 2, 3, 4, 5, 6 и 7**.

Одобренный пост можно запланировать и опубликовать в Telegram и VK через изолированные клиенты. Публикация идемпотентна (один пост — одна публикация на платформу), ошибки фиксируются в публикации и не роняют процесс. Instagram **не** подключён; в тестах реальная сеть не вызывается (fake-клиенты или `httpx.MockTransport`).

**Безопасная live-публикация.** Реальная отправка по умолчанию **выключена**: без флагов `TELEGRAM_LIVE_PUBLISHING_ENABLED` / `VK_LIVE_PUBLISHING_ENABLED` (`.env`, по умолчанию `false`) `publish` возвращает «Live publishing disabled by config» и ничего не отправляет. При включённом флаге Telegram использует `TELEGRAM_BOT_TOKEN` + `TELEGRAM_DEFAULT_CHANNEL_ID`, VK — `VK_ACCESS_TOKEN` + `VK_DEFAULT_GROUP_ID`. Текст берётся из `post.telegram_text` / `post.vk_text`; если у медиа есть **одобренная** улучшенная копия (`MediaAssetVariant`), в запрос кладётся путь к ней (`preferred_media_path`), иначе — метаданные оригинала. Посмотреть payload без отправки: `POST /post-publications/preview/{post_id}` или `python -m app.scripts.publish_post --post-id 1 --dry-run`.

**Фото во VK и групповой токен (v0.1.12).** При живой публикации VK прикрепляет изображение (локальная улучшенная копия или скачивание оригинала из публичной папки Яндекс Диска → `photos.getWallUploadServer` → upload → `photos.saveWallPhoto` → `attachments`). **Групповой токен публикует текст** (`wall.post`), но методы `photos.*` с ним **недоступны** (`VK error 27: group auth`). В этом случае бот делает **text-only fallback**: постит текст без фото и помечает в `raw` `media_upload_skipped: true`, `media_upload_error_code: 27`, `media_warnings`. Видео пока не загружается (тоже text-only + warning). Полноценная загрузка фото через **user-token** — отдельный будущий этап. Токен нигде не логируется и не попадает в `raw`/ошибки.

### Команды

```bash
make schedule-post post_id=1
make publish-post post_id=1
make publish-due
```

### API `/post-publications`

```bash
# Список публикаций (фильтры post_id / project_id / platform / status)
curl "http://localhost:8000/post-publications?post_id=1"

# Публикация по id (404, если нет)
curl http://localhost:8000/post-publications/1

# Запланировать публикации поста (404 — нет поста; 409 — статус не approved/scheduled)
curl -X POST http://localhost:8000/post-publications/schedule/1 \
  -H "Content-Type: application/json" \
  -d '{"platforms": ["telegram", "vk"], "scheduled_at": "2026-06-18T12:00:00"}'

# Опубликовать пост сейчас (частичные сбои видны в published_count/failed_count)
curl -X POST http://localhost:8000/post-publications/publish/1 \
  -H "Content-Type: application/json" -d '{"force": false}'

# Опубликовать все созревшие публикации (планировщик вручную)
curl -X POST http://localhost:8000/post-publications/publish-due \
  -H "Content-Type: application/json" -d '{"now": "2026-06-18T12:00:00"}'

# Dry-run preview: что и куда ушло бы, без отправки (404 — нет поста)
curl -X POST http://localhost:8000/post-publications/preview/1 \
  -H "Content-Type: application/json" -d '{}'

# Ручная правка публикации (target_id/status/error_message)
curl -X PATCH http://localhost:8000/post-publications/1 \
  -H "Content-Type: application/json" -d '{"target_id": "@my_channel"}'
```

Статусы публикации: `pending`, `scheduled`, `publishing`, `published`, `failed`, `skipped`.

> Токены задаются в `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHANNEL_ID`,
> `VK_ACCESS_TOKEN`, `VK_DEFAULT_GROUP_ID`). Без них планирование и API работают,
> а реальная публикация недоступна (понятная ошибка).

Подробная логика автопостинга — в:

```text
Докс/13_Автопостинг.md
```
<!-- STAGE7_README_END -->


<!-- STAGE8_README_START -->

## Этап 8 — Аналитика

Реализованы **Этапы 0, 1, 2, 3, 4, 5, 6, 7 и 8**.

Аналитика хранит снимки метрик публикаций, считает CTR/engagement_rate/performance_score и строит отчёты по постам, темам, кластерам и проекту, а также feedback-сигналы для приоритизации тем. Реальные analytics API соцсетей и Instagram **не** подключены — метрики вводятся вручную или берутся у fake-провайдера.

### Команды

```bash
make ingest-analytics post_id=1
make analytics-report project_slug=teeon
```

### API `/analytics`

```bash
# Список снимков (фильтры post_id / project_id / topic_id / platform)
curl "http://localhost:8000/analytics/snapshots?post_id=1"

# Снимок по id (404, если нет)
curl http://localhost:8000/analytics/snapshots/1

# Ручной ввод метрик по посту (404 — нет поста). CTR/ER считаются автоматически
curl -X POST http://localhost:8000/analytics/snapshots \
  -H "Content-Type: application/json" \
  -d '{"post_id": 1, "platform": "telegram", "impressions": 1000, "reach": 800, "likes": 30, "clicks": 20}'

# Загрузка метрик по публикации (404 — нет публикации; 422 — нет метрик)
curl -X POST http://localhost:8000/analytics/ingest/publication/1 \
  -H "Content-Type: application/json" \
  -d '{"metrics": {"impressions": 1000, "clicks": 30}, "source": "manual"}'

# Метрики у fake-провайдера (без сети)
curl -X POST http://localhost:8000/analytics/fetch/publication/1 \
  -H "Content-Type: application/json" -d '{}'

# Отчёты (404 — нет поста/проекта)
curl http://localhost:8000/analytics/posts/1/performance
curl http://localhost:8000/analytics/projects/1/topics
curl http://localhost:8000/analytics/projects/1/clusters
curl http://localhost:8000/analytics/projects/1/summary
curl http://localhost:8000/analytics/projects/1/feedback
```

Подробная логика аналитики — в:

```text
Докс/14_Аналитика.md
```
<!-- STAGE8_README_END -->


<!-- STAGE9_README_START -->

## Этап 9 — Внешние картинки

Реализованы **Этапы 0, 1, 2, 3, 4, 5, 6, 7, 8 и 9**.

Если у поста/темы нет своего approved-медиа, бот ищет внешние изображения (сток/Creative Commons) под тему/пост, проверяет лицензию и безопасность и может конвертировать одобренного кандидата в `MediaAsset`. Внешнее изображение **никогда** не выдаётся за наш кейс. Реальные стоки и сеть **не** подключены — используется fake-провайдер; файлы не скачиваются.

### Команды

```bash
make search-external-images project_slug=teeon query="шелкография"
make convert-external-image candidate_id=1
```

### API `/external-images`

```bash
# Список кандидатов (фильтры project_id / topic_id / post_id / provider / review_status)
curl "http://localhost:8000/external-images?project_id=1"

# Кандидат по id (404, если нет)
curl http://localhost:8000/external-images/1

# Поиск (404 — нет проекта/темы/поста). Фильтры лицензии/логотипа/безопасности по умолчанию
curl -X POST http://localhost:8000/external-images/search \
  -H "Content-Type: application/json" \
  -d '{"project_slug": "teeon", "query": "шелкография", "limit": 10}'

# Поиск под пост / тему
curl -X POST http://localhost:8000/external-images/search/post/1
curl -X POST http://localhost:8000/external-images/search/topic/1

# Оценка безопасности (can_claim_as_own_case всегда false)
curl http://localhost:8000/external-images/1/safety

# Review (422 — неизвестный статус)
curl -X PATCH http://localhost:8000/external-images/1/review \
  -H "Content-Type: application/json" -d '{"review_status": "approved"}'

# Конвертация в MediaAsset (409 — нельзя: rejected / некоммерческое / небезопасное)
curl -X POST http://localhost:8000/external-images/1/convert-to-media \
  -H "Content-Type: application/json" -d '{"status": "needs_license_review"}'
```

Статусы review: `candidate`, `needs_review`, `approved`, `rejected`, `converted_to_media_asset`.

> Внешнее изображение нельзя выдавать за собственный кейс/портфолио — это правило
> закреплено в политике лицензий и тестах.

Подробная логика — в:

```text
Докс/15_Внешние_картинки.md
```
<!-- STAGE9_README_END -->


<!-- STAGE10_README_START -->

## Этап 10 — Автономный режим

Реализованы **Этапы 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 и 10**.

Автономный прогон связывает все модули в управляемый pipeline: выбор тем → генерация постов → подбор медиа → внешние картинки → согласование → планирование → публикация → аналитика → отчёт. Каждый шаг логируется, действуют safety-guardrails, реальная публикация — только при явном `allow_auto_publish`. В тестах нет реальной сети и AI (fake-провайдеры).

### Режимы

`dry_run` (ничего не создаёт) · `semi_auto` (темы/посты + needs_review) · `auto_generate` · `auto_schedule` (только approved) · `auto_publish` (только при `allow_auto_publish`).

### Команды

```bash
make autonomous-run project_slug=teeon
make autonomous-dry-run project_slug=teeon
make autonomous-report run_id=1
```

### API `/autonomous-runs`

```bash
# Список прогонов (фильтры project_id / status / mode)
curl "http://localhost:8000/autonomous-runs?project_id=1"

# Прогон / шаги / отчёт (404, если нет)
curl http://localhost:8000/autonomous-runs/1
curl http://localhost:8000/autonomous-runs/1/steps
curl http://localhost:8000/autonomous-runs/1/report

# Сухой прогон (ничего не создаёт)
curl -X POST http://localhost:8000/autonomous-runs/dry-run \
  -H "Content-Type: application/json" -d '{"project_slug": "teeon"}'

# Запуск (404 — нет проекта; 422 — режим/настройки). По умолчанию semi_auto
curl -X POST http://localhost:8000/autonomous-runs/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_slug": "teeon",
    "mode": "semi_auto",
    "business_priorities": {"футболки": 100, "худи": 80, "шелкография": 90},
    "weeks": 1,
    "posts_per_week": 3
  }'

# Запуск по slug / id проекта
curl -X POST http://localhost:8000/autonomous-runs/run/slug/teeon \
  -H "Content-Type: application/json" -d '{"mode": "semi_auto"}'
```

Подробная логика автономного режима — в:

```text
Докс/16_Автономный_режим.md
```
<!-- STAGE10_README_END -->


<!-- SEO_VK_README_START -->

## SEO VK-группа TEEON

Системный модуль SEO для VK-группы **TEEON** (и архитектура под вторую группу
«Фабрика сувениров»): SEO-профиль проекта на основе сайта [teeon.ru](https://teeon.ru)
(каталог + нанесения), seed-ядро SEO-запросов Яндекса, выбор релевантной ссылки на
сайт для каждого поста, контент-план и **preview** SEO-заполнения группы.

> ⚠️ Реальные публикации и реальные изменения оформления VK-группы на этом этапе
> **не выполняются**. `VK_LIVE_PUBLISHING_ENABLED` и `VK_GROUP_SETUP_LIVE_ENABLED`
> по умолчанию `false` — всё работает как preview / dry-run.

### Команды

```bash
# Превью SEO-заполнения группы (описание, статус, закреп, услуги, хэштеги, ссылки)
make preview-vk-seo project_slug=teeon
PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_vk_group_seo_setup --project-slug teeon

# SEO-контент-план на 30 дней (тема, SEO-запрос, ссылка на сайт, медиа-тег, CTA)
make seo-content-plan project_slug=teeon days=30
PYTHONPATH=backend .venv/bin/python -m app.scripts.generate_seo_content_plan --project-slug teeon --days 30

# Автономный прогон с пресетом приоритетов из SEO-профиля
PYTHONPATH=backend .venv/bin/python -m app.scripts.autonomous_run \
    --project-slug teeon --use-default-publication-vector --dry-run
```

### API `/seo`

```bash
curl http://localhost:8000/seo/project/teeon/profile
curl http://localhost:8000/seo/project/teeon/vk-group-preview
curl "http://localhost:8000/seo/project/teeon/content-plan?days=30"

# apply: dry_run=true по умолчанию; live → 403 без VK_GROUP_SETUP_LIVE_ENABLED
curl -X POST http://localhost:8000/seo/project/teeon/vk-group-apply \
  -H "Content-Type: application/json" -d '{"dry_run": true}'
```

Подробности — в [`Докс/20_SEO_VK_группа_TEEON.md`](./Докс/20_SEO_VK_группа_TEEON.md).

<!-- SEO_VK_README_END -->


<!-- CRM_BOT_SMM_README_START -->

## CRM Bot SMM Configurator

Слой конфигурации для **внешней CRM**: во вкладке «БОТ СММ» человек заполняет
форму (проект, сайт/темы, ресурсы, ключи, источники контента, категории
продвижения, план публикаций), а бэкенд отдаёт **JSON-схему формы** и REST-API,
которые любая CRM отрисует и вызовет. По данным формы строятся SEO-профиль,
контент-план и безопасный `semi_auto`/`dry-run`.

> ⚠️ Безопасность: **реальные публикации не выполняются**, live VK/Telegram
> выключены, режим `auto_publish` запрещён. Секрет ресурса (`api_key`) хранится
> зашифрованно и **не возвращается** через API — только `api_key_present` и
> `api_key_masked`.

> ♻️ **apply идемпотентен**: `apply?dry_run=false` можно запускать повторно —
> дубли ресурсов/ключей/источников/категорий/планов не создаются, изменённые
> данные обновляются на месте, пустой `api_key` не затирает существующий секрет.

### Команды

```bash
# Схема формы «БОТ СММ» для CRM (без БД)
make crm-form-schema

# Валидация онбординг-пейлоада (без БД)
make crm-onboarding-validate payload_path=backend/examples/crm_bot_smm_onboarding_teeon.json

# Превью онбординга (dry-run, ничего не пишет)
make crm-onboarding-preview payload_path=backend/examples/crm_bot_smm_onboarding_teeon.json

# Применить онбординг (создаёт проект/конфиг/ресурсы/ключи/категории/план; требует БД)
make crm-onboarding-apply payload_path=backend/examples/crm_bot_smm_onboarding_teeon.json

# Контент-план категории на N дней (требует БД)
make crm-category-plan category_id=1 days=30
```

Пример безопасного пейлоада (без реальных токенов):
[`backend/examples/crm_bot_smm_onboarding_teeon.json`](./backend/examples/crm_bot_smm_onboarding_teeon.json).

### API `/crm/bot-smm`

```bash
# Схема формы
curl http://localhost:8000/crm/bot-smm/form-schema

# Черновик онбординга: создать → валидировать → превью → применить
curl -X POST http://localhost:8000/crm/bot-smm/onboarding-drafts \
  -H "Content-Type: application/json" -d '{"payload": { ... }}'
curl -X POST http://localhost:8000/crm/bot-smm/onboarding-drafts/1/validate
curl -X POST http://localhost:8000/crm/bot-smm/onboarding-drafts/1/preview
curl -X POST "http://localhost:8000/crm/bot-smm/onboarding-drafts/1/apply?dry_run=false"

# Конфигурация проекта
curl http://localhost:8000/crm/bot-smm/projects/1/config

# Безопасная проверка ресурса (без сети, без печати секрета)
curl -X POST http://localhost:8000/crm/bot-smm/resources/1/test-connection \
  -H "Content-Type: application/json" -d '{"test_connection": true}'

# Категория: контент-план и безопасные прогоны (публикаций нет)
curl -X POST "http://localhost:8000/crm/bot-smm/categories/1/preview-plan?days=30"
curl -X POST http://localhost:8000/crm/bot-smm/categories/1/run-dry
curl -X POST http://localhost:8000/crm/bot-smm/categories/1/run-semi-auto
```

Подробности — в [`Докс/21_CRM_форма_БОТ_СММ.md`](./Докс/21_CRM_форма_БОТ_СММ.md).

<!-- CRM_BOT_SMM_README_END -->


<!-- MVP_RELEASE_START -->

## Production hardening / MVP-релиз

Все этапы разработки 0–10 завершены. Бэкенд готов к подготовке боевого запуска (MVP). Что добавлено для готовности к запуску:

- **Readiness-проба** `GET /health/readiness` — сообщает окружение (`app_env`), тип БД и какие интеграции настроены; в production добавляет предупреждения о незаданных токенах и о SQLite вместо PostgreSQL. Без сети и обращений к БД.
- **Config helper properties** в `app/config.py`: `is_production`, `is_local`, `database_is_sqlite`, `telegram_configured`, `vk_configured`, `yandex_disk_configured`, `ai_configured`.
- **Смоук-проверка** `make smoke` (`app/scripts/smoke_check.py`) — поднимает приложение in-process и проверяет `/health` + `/health/readiness`, печатает сводку без значений секретов.
- **`.gitignore`/`.env.example`** ужесточены: реальные токены и `.env*` не попадают в репозиторий; шаблон окружения покрывает все настройки.

### Что нужно сделать вручную перед реальным запуском

Это **не** входит в бэкенд-MVP и делается отдельно (см. [`Докс/17_MVP_запуск.md`](./Докс/17_MVP_запуск.md)):

1. Заполнить реальные секреты в `.env` (или в менеджере секретов): `DATABASE_URL` (PostgreSQL), `YANDEX_DISK_TOKEN`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_DEFAULT_CHANNEL_ID`, `VK_ACCESS_TOKEN` + `VK_DEFAULT_GROUP_ID`. Поставить `APP_ENV=production`.
2. Применить миграции на боевой БД: `make migrate` (или `alembic upgrade head`).
3. Включить **живой режим** публикующих клиентов Telegram/VK (сейчас они безопасно отключены и выдают понятную ошибку вместо отправки).
4. Настроить мониторинг/алерты, структурированное логирование и резервное копирование БД.
5. Поднять UI/админку для согласования постов и просмотра прогонов/аналитики.
6. Провести ручное QA на реальном проекте; запускать автономный режим начиная с `dry_run`/`semi_auto`.

Подробный план боевого запуска — в:

```text
Докс/17_MVP_запуск.md
```
<!-- MVP_RELEASE_END -->
