# 38. Botfleet: Импорт метрик и обратная связь обучения (v0.4.1)

Следующий слой обучения поверх [37](37_Botfleet_Review_Learning_Automation.md): импорт
метрик опубликованных постов, ручной ввод, нормализация метрик разных платформ и пересчёт
профиля обучения на основе реальных/ручных/оценочных данных. Клиент видит, какие посты
сработали лучше, почему, и какие выводы сделал бот.

> **Безопасность:** это **не** этап live-публикаций и **не** реальных платежей. Реальные
> API-метрики платформ по умолчанию **выключены** (feature flag) и в тестах не вызываются;
> demo/manual/estimated работают без сети. Секретов в ответах/логах нет.

## Источники метрик (`MetricSource`)

`internal` · `manual` · `estimated` · `api` · `demo`. Доверие к источнику
(для обучения): **api > manual > internal > estimated > demo**. Каждая метрика всегда
показывается вместе с источником и `confidence_score`.

### Статусы прогона (`MetricImportStatus`)

`preview` · `pending` · `imported` · `partially_imported` · `failed` · `skipped` ·
`no_credentials` · `live_disabled`.

## Нормализация метрик

Платформы называют метрики по-разному — `metrics_normalization_service` приводит их к
единому формату Botfleet (`NormalizedPostMetrics`):

- **Telegram**: `forwards → shares/reposts`; `views → views/impressions` при отсутствии reach.
- **VK**: `reposts → shares/reposts`; `views/impressions/reach` если есть.
- **Instagram**: `impressions/reach/saves/profile_actions/clicks` если есть.

Правила:
- **если метрика неизвестна — `null`, а не `0`**;
- **ER** = вовлечения / база (`reach → impressions → views` fallback), в процентах;
- **CTR** = `clicks / impressions` (требует impressions, иначе `null`);
- `engagement_per_1000`, `actual_engagement_score` (0..100);
- `raw_sanitized` не содержит токенов/секретов;
- `merge_metrics` — при слиянии более доверенный источник не перетирается менее доверенным.

## Адаптеры платформ

`platform_metrics/` — `PlatformMetricsAdapter` (base) + telegram/vk/instagram/demo:

- **demo** — детерминированные (по id + контент-признакам) метрики без сети; `source=demo`,
  стабильны в тестах. **Не реальные показатели.**
- **telegram/vk/instagram** — подготовлены под API, но реальные вызовы выключены:
  при выключенном флаге → `api_disabled`; VK/Instagram без токена → `no_credentials`;
  включённый флаг без реализации → `skipped` (никакой сети).

Feature flags (по умолчанию `false`): `PLATFORM_METRICS_API_ENABLED`,
`TELEGRAM_METRICS_API_ENABLED`, `VK_METRICS_API_ENABLED`, `INSTAGRAM_METRICS_API_ENABLED`.

## Импорт метрик (`metrics_import_service`)

| Метод | Что делает |
|-------|-----------|
| `preview_import` | что было бы импортировано (без записи и без списания) |
| `run_import_dry` | сухой прогон (без записи/биллинга) |
| `run_import` | снимки + события `analytics_imported` + пересчёт профиля; списание — только на успехе |
| `save_manual_metrics` | ручной снимок `source=manual` + сигнал обучения (бесплатно) |
| `rebuild_learning_from_metrics` | пересчёт профиля по метрикам (dry-run бесплатно; запись — 5 units) |
| `build_metrics_dashboard` | сводка для UI (лучший/слабый пост, теги, время, источники) |

Импорт создаёт `PostAnalyticsSnapshot` (ER/CTR хранятся дробью, как во всей аналитике),
затем событие `analytics_imported` (client learning), затем **один** пересчёт профиля в
конце (без O(n²)). Прогон фиксируется в `MetricImportRun` (`idempotency_key` unique).

### API (`/metrics`, tenant-изоляция)

`GET /metrics/projects/{id}/imports` · `POST …/preview` · `POST …/run-dry` ·
`POST …/run` · `POST /metrics/publications/{publication_id}/manual` ·
`POST …/learning/rebuild-preview` · `POST …/learning/rebuild` ·
`GET …/dashboard`. Гарды: `require_project_access` и `require_publication_access`.

## Как метрики влияют на обучение

`analytics_imported` события и снимки пересобирают `ClientLearningProfile`:

- **высокий ER** → `high_performing_tags`, `preferred_media_types`, `best_publish_times`
  (час публикации из `publication.published_at → scheduled_at`);
- **низкий ER** → `low_performing_tags`;
- **высокие saves/shares** → `performance_patterns.useful_content_signals` («полезный» контент);
- вес правки тега масштабируется доверием к источнику (api весит больше demo);
- `performance_patterns`: `avg_engagement_rate`, `best_platform`, `best/worst_post`;
- `confidence_score` растёт с числом событий.

`explain_learning_changes(before, after)` даёт человеко-читаемую сводку «что изменилось
после метрик» для UI.

## Почему demo ≠ реальные метрики

Demo-адаптер генерирует правдоподобные, но **синтетические** значения из id и признаков
контента. Они нужны, чтобы показать работу цикла обучения без внешних API. В UI и API это
явно помечено (`source=demo`, warnings). Реальные показатели появятся только при включении
API-адаптеров (см. ниже).

## Как включить реальные API позже

1. Реализовать сеть в соответствующем `*_metrics_adapter` (VK `stats.getPostReach`,
   Instagram Graph insights и т. п.) через инъектируемый transport (в тестах — MockTransport).
2. Включить флаги `PLATFORM_METRICS_API_ENABLED` + `<platform>_METRICS_API_ENABLED`.
3. Прокинуть креды (user-token / access token + ig_user_id) — секреты не логируются.

## Биллинг

| Действие | units |
|----------|-------|
| preview / dry-run | 0 |
| manual metrics save | 0 |
| demo import | 0 (по умолчанию; `metrics_demo_import_paid=true` — платно) |
| api import | light 5 · standard 10 · deep 20 (за прогон проекта) |
| learning rebuild (запись) | 5 |

Неуспешный/заблокированный импорт units **не** списывает; успешный — ровно один раз
(идемпотентно по `idempotency_key`).

## Приватность

Профиль и метрики строго **per-project**; данные одного клиента не смешиваются с другими и
не уходят в глобальное обучение. Хранятся агрегаты и `raw_sanitized` (без токенов).

## Аудит

`metrics.import.preview/started/completed/failed/blocked`, `metrics.manual.saved`,
`metrics.learning.rebuild.preview`, `metrics.learning.rebuilt`,
`metrics.external_api.disabled`. Без секретов.

## Миграция и модель

`0023_metric_import_runs` (down_revision `0022`, SQLite/PostgreSQL): таблица
`metric_import_runs` (project × platform × source × period, счётчики, `idempotency_key`
unique, `import_metadata` без секретов).

## CLI

```bash
make metrics-import-preview project_id=1 platform=telegram source=demo depth=standard
make metrics-import-run project_id=1 source=demo dry_run=true      # dry-run по умолчанию
make manual-metrics publication_id=1 views=1000 likes=50 comments=3 shares=4
make learning-rebuild project_id=1 dry_run=true
```

## UI

- `/ui/metrics` и `/ui/projects/{id}/metrics` — «Метрики и обучение»: фильтры
  (платформа/источник/глубина/период), сводка (постов с метриками, средний ER/CTR, лучший
  пост/тег/время), кнопки **Preview import / Run demo import / Внести метрики вручную /
  Пересчитать обучение**, таблица постов с источником метрик, форма ручного ввода.
- `/ui/projects/{id}/metrics/import` и `/metrics/manual` — отдельные страницы импорта и
  ручного ввода.
- `/ui/projects/{id}/learning/metrics` — «Как метрики повлияли на обучение»
  (лучшие/слабые темы, CTA, медиа, время, изменения, последние импорты).
- В sidebar добавлен пункт **Метрики**; на страницах ревью/обучения/аналитики — ссылки.

## Что дальше

Реальный VK stats API · реальная стратегия метрик Telegram · Instagram insights ·
A/B-тестирование · цикл оптимизации тем (multi-armed bandit).
