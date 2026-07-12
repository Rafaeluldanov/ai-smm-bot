# 45. Botfleet: воркфлоу очистки и разметки медиатеки (v0.4.8)

Слой поверх качества ([43](43_Botfleet_Media_Quality_Scoring.md)) и визуальной дедупликации
([44](44_Botfleet_Media_Fingerprints_Dedup.md)): Botfleet не только находит слабые/
дублирующиеся медиа, но и даёт клиенту удобный **workflow очистки медиатеки** — проверить
дубли, выбрать canonical, подтвердить теги, скрыть дубль, создать задачи на замену слабых
медиа. Улучшение медиатеки **без удаления файлов**.

> **Безопасность:** это **не** этап удаления медиа, **не** внешнего AI, **не** live-публикаций
> и **не** реальных платежей. Теги применяются **только после подтверждения клиента**
> (`MEDIA_CURATION_AUTO_APPLY_TAGS=false`); дубли скрываются, а не удаляются
> (`MEDIA_CURATION_AUTO_HIDE_DUPLICATES=false`, `MEDIA_CURATION_AUTO_DELETE_ENABLED=false`);
> **файлы никогда не удаляются**. Курирование worker-ом **выключено** по умолчанию
> (`MEDIA_CURATION_WORKER_ENABLED=false`), dry-run по умолчанию. Внешнего AI нет
> (`MEDIA_CURATION_EXTERNAL_AI_ENABLED=false`). В API/UI/CLI нет секретов и внутренних путей.

## Термины

- **MediaCurationTaskType**: `duplicate_review · retag_suggestion · weak_media_review · missing_tags · platform_fit_issue · replace_repeated_media · media_proxy_needed · heic_conversion_needed`
- **MediaCurationTaskStatus**: `proposed · accepted · rejected · applied · ignored · restored · expired · failed`
- **MediaCurationAction**: `approve_tags · reject_tags · mark_duplicate · keep_canonical · hide_from_selection · restore_to_selection · ignore_cluster · request_replacement · mark_reviewed`
- **MediaSelectionVisibility**: `selectable · hidden_duplicate · hidden_weak · hidden_manual · archived · restored`
- **TagSuggestionSource**: `file_name · existing_tags · duplicate_canonical · crm_category · crm_keywords · product_priorities · technology_priorities · learning_profile · high_performing_tags · manual`

## Что такое media curation

`MediaCurationService` собирает **задачи** (`MediaCurationTask`) из трёх источников:
- **кластеры дублей** → `duplicate_review` (canonical + участники + действие keep_canonical);
- **снимки качества** → `weak_media_review` / `heic_conversion_needed` / `media_proxy_needed` /
  `platform_fit_issue`;
- **предложения тегов** (`MediaTagSuggestionService`) → `retag_suggestion` / `missing_tags`.

Каждая задача: тип, причина, предложенное действие, предложенные теги/продукты/технологии,
затронутые медиа, confidence, risk flags, idempotency-ключ (без дублей при повторной генерации),
срок жизни (`MEDIA_CURATION_TASK_EXPIRE_DAYS`).

## Approved retagging (только после подтверждения)

Теги предлагаются **без внешнего AI** — правило-ориентированно из имени файла, существующих
тегов, canonical-медиа дубля, CRM-категории/ключей/приоритетов, learning profile и недавних
media decisions. Бот **только предлагает**; клиент подтверждает (`approve_tags`), и лишь тогда
теги мёржатся в `media_asset.tags` (products/technologies/details), `curation_status=reviewed`,
и пишется audit `media_curation.tags_applied`. Ничего не применяется автоматически.

## Duplicate review

Для кластера дублей задача `duplicate_review` предлагает canonical и действия: `keep_canonical`,
`mark_duplicate` (скрыть не-canonical участников), `ignore_cluster`. Файлы **не удаляются** — у
дубля лишь меняется `selection_visibility` на `hidden_duplicate`.

## Media visibility (без удаления)

`MediaAsset.selection_visibility`: `selectable` (по умолчанию) → `hidden_duplicate` /
`hidden_weak` / `hidden_manual` / `archived`. Скрытые медиа:
- **не участвуют** в auto media selection;
- в media quality получают issue `hidden_from_selection` и сильно сниженный overall/platform_fit;
- **можно вернуть** (`restore_to_selection` → `selectable`). Физический файл не трогается.

## Как курирование улучшает auto media selection (Часть 9)

`schedule_media_decision_service` исключает `hidden_*`/`archived` медиа из подбора и пишет в
решение и `generation_notes` — `media_curation_summary`: `hidden_media_skipped_count`,
`retag_suggestions_available`, `weak_media_warning`. Если селектируемых медиа нет — fallback
`text_only`/`no_media_available`.

## Worker (Часть 10)

При `MEDIA_CURATION_WORKER_ENABLED=true` worker **предлагает** задачи (`generate_curation_tasks`,
dry-run по умолчанию); `TickResult` получает `media_curation_tasks_previewed/created`,
`media_curation_hidden_count`, `media_curation_retag_count` + audit
`scheduler.worker.media_curation.*`. Worker **никогда** не применяет теги, не скрывает и не
удаляет медиа автоматически.

## Почему нет удаления и внешнего AI

Курирование меняет только **теги** (после подтверждения) и **видимость** (hidden/selectable) —
никогда сам файл. Все предложения — локальные правила (словари продуктов/технологий, токены
имени файла, CRM/обучение), без vision/embedding API. Реальный cleanup с бэкапами и
collaborative review — на будущее.

## Config-флаги

```
MEDIA_CURATION_ENABLED=true                 # preview/UI/API/CLI доступны
MEDIA_CURATION_WORKER_ENABLED=false         # worker предлагает задачи (по умолчанию выкл)
MEDIA_CURATION_DRY_RUN=true                 # dry-run (по умолчанию — без записи)
MEDIA_CURATION_AUTO_APPLY_TAGS=false        # теги НЕ применяются автоматически
MEDIA_CURATION_AUTO_HIDE_DUPLICATES=false   # дубли НЕ скрываются автоматически
MEDIA_CURATION_AUTO_DELETE_ENABLED=false    # файлы НЕ удаляются
MEDIA_CURATION_MAX_TASKS_PER_RUN=100
MEDIA_CURATION_MIN_CONFIDENCE=0.55
MEDIA_CURATION_TASK_EXPIRE_DAYS=30
MEDIA_CURATION_USE_FINGERPRINTS=true
MEDIA_CURATION_USE_QUALITY=true
MEDIA_CURATION_USE_LEARNING=true
MEDIA_CURATION_EXTERNAL_AI_ENABLED=false    # внешний AI НЕ используется
```

## Биллинг

Preview, генерация задач и применение (approve_tags/hide/restore) — **бесплатны в MVP**
(`media_curation_preview/generate/apply` — 0 units; без внешнего AI). Будущий AI-ретегинг может
быть платным, но сейчас выключен. Неуспешное применение не списывает ничего; двойного дебета нет.

## Audit

`media_curation.previewed / task_created / task_applied / task_rejected / task_ignored /
media_hidden / media_restored / tags_applied` + `scheduler.worker.media_curation.*`. Метаданные
без секретов и путей (project_id, task_id, media_asset_id, cluster_id, action, suggested_tags,
confidence).

## API

- `GET  /media-curation/projects/{id}` — список задач (фильтры статус/тип/медиа);
- `GET  /media-curation/projects/{id}/dashboard` — сводка;
- `POST /media-curation/projects/{id}/preview` — предпросмотр (без записи);
- `POST /media-curation/projects/{id}/generate` — создать задачи (dry_run true/false);
- `GET  /media-curation/tasks/{task_id}` — одна задача;
- `POST /media-curation/tasks/{task_id}/apply` — approve_tags/mark_duplicate/hide/restore/ignore_cluster/mark_reviewed;
- `POST /media-curation/tasks/{task_id}/reject | /ignore` — отклонить/проигнорировать;
- `POST /media-curation/projects/{id}/media-assets/{aid}/restore` — вернуть медиа в подбор.

**Нет delete-роута** — файлы не удаляются. Tenant-изоляция (чужой проект/задача → 404).

## CLI

```bash
make media-curation-preview project_id=1
make media-curation-generate project_id=1 dry_run=false
make media-curation-apply task_id=1 action=approve_tags dry_run=false
make media-curation-dashboard project_id=1
```

Dry-run по умолчанию для generate/apply; секреты/пути не печатаются; файлы не удаляются.

## UI

- `/ui/projects/{id}/media-curation` — «Очистка и разметка медиатеки»: сводка (активные/дубли/
  ретег/слабые/скрыто/в подборе) + карточки задач с кнопками Approve tags / Mark duplicate /
  Hide / Restore media / Reject / Ignore (**без кнопки удаления**);
- `/ui/projects/{id}/media-curation/tasks/{id}` — детали задачи + действия;
- `/ui/projects/{id}/media-quality`, `/media-duplicates`, `/media-decisions/{id}` — ссылки на
  курирование;
- `/ui/projects/{id}/automation` — блок «Media curation worker» + флаги;
- `/ui/scheduler` — блок «Курирование медиатеки в worker» + счётчики.

## Приватность

Предложения строго per-project (без межклиентского смешивания). В API/UI/CLI/аудите нет сырых
токенов и внутренних путей (только id/теги/статусы).

## Что дальше

Image embeddings · визуальная AI-модель качества · курирование видео · реальный duplicate
cleanup с бэкапами · collaborative review workflow (несколько ревьюеров, история решений).
