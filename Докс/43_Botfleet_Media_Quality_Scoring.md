# 43. Botfleet: оценка качества медиа и дедупликация (v0.4.6)

Слой поверх автовыбора медиа ([42](42_Botfleet_Auto_Media_Selection.md)): Botfleet не просто
подбирает медиа по тегам, а **оценивает каждое медиа** по пяти измерениям, выявляет проблемы
и повторы, определяет платформенную пригодность — и сохраняет снимок
(:class:`MediaQualitySnapshot`). Оценка **правило-ориентированная**.

> **Безопасность:** это **не** этап live-публикаций, **не** реальных платежей и **не**
> внешнего AI. Оценка влияет только на подбор медиа для **draft/needs_review**; live-
> публикаций нет. Оценка worker-ом **выключена** по умолчанию
> (`MEDIA_QUALITY_SCORING_WORKER_ENABLED=false`), dry-run по умолчанию. Внешний AI и
> авто-ретегирование **выключены** (`MEDIA_QUALITY_EXTERNAL_AI_ENABLED=false`,
> `MEDIA_QUALITY_AUTO_RETAGS_ENABLED=false`). Секретов и внутренних путей к файлам в
> ответах/метаданных нет.

## Термины

- **MediaQualityStatus**: `pending · scored · needs_tags · weak · good · excellent · duplicate · unsupported · failed`
- **MediaQualityIssue**: `too_small · too_large · unsupported_format · heic_conversion_needed · video_not_supported · recently_used · duplicate_candidate · weak_topic_match · missing_tags · missing_product_tags · missing_technology_tags · instagram_public_url_required · media_proxy_not_ready · internal_path_only`
- **MediaQualitySignalSource**: `metadata · tags · usage_history · metrics · ab_winner · manual_feedback · estimated`

## Пять измерений (`media_quality_service`)

Каждый балл ∈ `[0..100]`:

1. **quality** — формат (JPEG/PNG ↑, HEIC ↓, видео/неизвестное ↓), статус (approved ↑),
   метаданные (title/description), число тегов, наличие enhanced-варианта, размеры (если
   известны из варианта: слишком маленькое/большое → штраф);
2. **relevance** — пересечение тегов с media_tags категории/темы, слова темы в тегах/имени,
   наличие product/technology/category-тегов;
3. **freshness** — не использовалось = 92; использовалось недавно = штраф (60 → 45 → …);
4. **uniqueness** — дубликаты штрафуются; уникальный файл/путь/подпись тегов = высоко;
5. **platform_fit** — пригодность к платформе (см. ниже).

**overall** = взвешенная сумма: `quality 30% · relevance 25% · freshness 20% · uniqueness 15%
· platform_fit 10%`.

**Статус** выводится из overall и проблем: `unsupported` (плохой формат) → `duplicate` →
`needs_tags` (нет тегов) → `excellent` (≥ `MIN_EXCELLENT`) → `good` (≥ `MIN_GOOD`) → `weak`.

## Как определяются проблемы (issues)

Правило-ориентированно из признаков: HEIC → `heic_conversion_needed`; видео →
`video_not_supported`; неизвестный формат → `unsupported_format`; нет тегов → `missing_tags`
/ `missing_product_tags` / `missing_technology_tags`; недавнее использование →
`recently_used`; кандидат-дубль → `duplicate_candidate`; низкая релевантность →
`weak_topic_match`; Instagram → `instagram_public_url_required` (+ `media_proxy_not_ready` /
`internal_path_only`); размеры вне диапазона → `too_small` / `too_large`.

`recommend_actions` формирует человекочитаемые рекомендации («Добавьте product-тег»,
«Конвертируйте HEIC в JPEG», «Не используйте это медиа повторно», «Для Instagram подготовьте
public image_url», «Слабое совпадение с темой — замените»). `recommend_tags` подсказывает,
какие группы тегов добавить (product / technology / category).

## Как определяется duplicate (без image embeddings)

`find_duplicate_candidates` (MVP, при `MEDIA_QUALITY_DEDUP_ENABLED`): совпадение по
нормализованному **имени файла**, **yandex_disk_path**, **заголовку** или **подписи тегов**
(отсортированное множество всех тегов). Тяжёлых image embeddings на этом этапе нет —
дубликаты ищутся по метаданным. Первый кандидат сохраняется как
`duplicate_of_media_asset_id`.

## Как freshness предотвращает повторы

`recent_usage_count` считается по applied-решениям о медиа
(`schedule_media_decision_repository.count_recent_media_usage`) и `last_used_at` в окне
`MEDIA_QUALITY_RECENCY_DAYS`. Ненулевой счётчик даёт `recently_used` и снижает freshness — так
повторное использование одних и тех же фото деприоритизируется.

## Платформенная пригодность (platform_fit)

- **Telegram** — изображение 90; HEIC 70 (нужна конвертация); видео 25 (planned/limited).
- **VK** — изображение 85; HEIC 65; видео 25.
- **Instagram** — требует public HTTPS image_url: с yandex-путём 80 (или 60 без готового
  media proxy), без публичного источника 40 (`internal_path_only`); видео 20.
- **Website/Blog** — single image предпочтительнее (85).
- **Планируемые/неизвестные** — нейтрально 50 (preview only).

## Влияние на auto media selection (Часть 6)

При подборе кандидатов `schedule_media_decision_service.build_media_candidates` подмешивает
overall-качество (снимок → быстрый dry-run без скана дублей) в ранг ассета — **сильные медиа
поднимаются**. В решение и `generation_notes` пишется `media_quality_summary`:
`selected_media_scores`, `average_selected_score`, `weak_selected_count`,
`duplicate_warning_count`, `common_issues`, `media_quality_snapshot_ids`. Risk-флаги:
`weak_media_quality` (средний балл ниже `MIN_GOOD`) и `repeated_media` (повтор/дубль). Слабое
медиа всё ещё может быть использовано при отсутствии альтернатив — но с предупреждением. Пост
остаётся draft/needs_review.

## Worker (Часть 7)

`SchedulerWorkerService` при `MEDIA_QUALITY_SCORING_WORKER_ENABLED=true` оценивает медиатеку
проектов из targets (`score_project_media`), пишет снимки (если не dry-run) и агрегирует в
`TickResult`: `media_quality_scoring_enabled/dry_run`, `media_quality_assets_scanned`,
`media_quality_snapshots_created`, `media_quality_weak_count`,
`media_quality_duplicate_count` + audit `scheduler.worker.media_quality.*`. Live-публикаций
нет; внешнего AI нет.

## Почему нет live-публикации и внешнего AI

Сервис/worker/API/CLI **не импортируют** `publish_due` и не вызывают клиентов платформ или
внешние AI/HTTP. Оценка — чистая функция от метаданных медиа (формат/теги/статус/размеры/
история использования). Глубокая AI-оценка возможна в будущем, но по умолчанию выключена.

## Config-флаги

```
MEDIA_QUALITY_SCORING_ENABLED=true              # preview/UI/API/CLI доступны
MEDIA_QUALITY_SCORING_WORKER_ENABLED=false      # worker пишет снимки (по умолчанию выкл)
MEDIA_QUALITY_SCORING_DRY_RUN=true              # dry-run (по умолчанию — без записи worker-ом)
MEDIA_QUALITY_MIN_GOOD_SCORE=70
MEDIA_QUALITY_MIN_EXCELLENT_SCORE=85
MEDIA_QUALITY_RECENCY_DAYS=60
MEDIA_QUALITY_FATIGUE_WINDOW_DAYS=14
MEDIA_QUALITY_MAX_SNAPSHOTS_PER_ASSET=20
MEDIA_QUALITY_DEDUP_ENABLED=true
MEDIA_QUALITY_PLATFORM_WEIGHTING_ENABLED=true
MEDIA_QUALITY_AUTO_RETAGS_ENABLED=false         # авто-ретегирование НЕ выполняется
MEDIA_QUALITY_EXTERNAL_AI_ENABLED=false         # внешний AI НЕ используется
```

## Биллинг

Preview, оценка и дашборд — **бесплатны в MVP** (`media_quality_preview`,
`media_quality_score`, `media_quality_dashboard` — 0 units; без внешнего AI). Глубокая
AI-оценка в будущем может быть платной, но сейчас выключена. Неуспешная оценка не списывает
ничего; двойного дебета нет.

## API

- `GET  /media-quality/projects/{id}` — список снимков (фильтры `platform_key/status/min_score`);
- `GET  /media-quality/projects/{id}/dashboard` — сводка;
- `POST /media-quality/projects/{id}/score-preview` — предпросмотр пачки (без записи);
- `POST /media-quality/projects/{id}/score` — оценить пачку (пишет снимки);
- `POST /media-quality/projects/{id}/media-assets/{aid}/score-preview` — одно медиа (без записи);
- `POST /media-quality/projects/{id}/media-assets/{aid}/score` — одно медиа (пишет снимок);
- `GET  /media-quality/{snapshot_id}` — один снимок.

Все роуты — под tenant-изоляцией (чужой проект/снимок → 404). Секретов и путей к файлам нет.

## CLI

```bash
make media-quality-preview project_id=1 platform=telegram limit=50
make media-quality-score project_id=1 platform=telegram dry_run=false
make media-quality-dashboard project_id=1
```

Dry-run по умолчанию для score; секреты/пути не печатаются; live/внешнего AI нет.

## UI

- `/ui/projects/{id}/media-quality` — «Качество медиа»: фильтры (платформа/статус/мин. балл),
  сводка (всего/оценено/excellent/good/weak/дубли/средний балл), частые проблемы, карточки
  медиа (5 баллов + проблемы + рекомендации);
- `/ui/projects/{id}/media-decisions/{id}` — карточка «Качество выбранных медиа» (средний
  балл, слабые, повторы, частые проблемы);
- `/ui/projects/{id}/automation` — блок «Оценка качества медиа» + флаги;
- `/ui/scheduler` — блок «Media quality scoring in worker» + счётчики последнего тика.

## Приватность

Оценка строго per-project: usage-история, метрики, learning — только своего проекта.
Межклиентского смешивания нет. В API/UI/CLI/аудите нет сырых токенов и внутренних путей к
файлам (в снимке — только `media_asset_id`, баллы, проблемы, рекомендации).

## Что дальше

Image embeddings (визуальная релевантность/дубли) · визуальная AI-модель качества · оценка
видео · авто-ретегирование после одобрения · платформенно-специфичная оптимизация медиа ·
production live-auto аудит.
