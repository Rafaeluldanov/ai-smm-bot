# 44. Botfleet: fingerprint медиа и визуальная дедупликация (v0.4.7)

Слой поверх оценки качества ([43](43_Botfleet_Media_Quality_Scoring.md)): Botfleet находит
визуально похожие и дублирующиеся медиа не только по имени/пути/тегам, но и по **безопасным
локальным fingerprint/hash-признакам** — и группирует их в кластеры дублей с canonical-
ассетом и рекомендациями. Файлы **не удаляются** на этом этапе.

> **Безопасность:** это **не** этап внешнего AI/vision, **не** live-публикаций, **не**
> реальных платежей и **не** внешних API-вызовов. Fingerprint считаются **локально** (Pillow);
> Yandex-скачивание **выключено** по умолчанию (`MEDIA_FINGERPRINTING_USE_YANDEX_DOWNLOAD=
> false`) — сети нет. Fingerprint worker-ом **выключен** по умолчанию
> (`MEDIA_FINGERPRINTING_WORKER_ENABLED=false`), dry-run по умолчанию. Авто-скрытие/удаление
> дублей **выключено** (`MEDIA_DUPLICATE_AUTO_DELETE_ENABLED=false`,
> `MEDIA_DUPLICATE_AUTO_HIDE_ENABLED=false`). Хранятся только хэши/сигнатуры — **без raw
> bytes, без внутренних путей к файлам и без секретов** (имя файла/путь/заголовок хэшируются).

## Термины

- **MediaFingerprintStatus**: `pending · calculated · partial · unavailable · failed`
- **MediaSimilarityType**: `exact_duplicate · near_duplicate · visually_similar · same_series · same_file_name · same_yandex_path · same_tag_signature · heic_jpeg_pair · unknown`
- **MediaDuplicateClusterStatus**: `active · reviewed · ignored · resolved · failed`
- **MediaDuplicateAction**: `keep_canonical · hide_duplicate · retag_duplicate · replace_in_schedule · merge_series · ignore · needs_review`
- **FingerprintSource**: `file_bytes · media_variant · yandex_public · metadata_only · tags_only · unavailable`

## Что такое media fingerprint

`MediaFingerprint` (`media_fingerprint_service`) — набор безопасных локальных признаков медиа:
`file_sha256`, `perceptual_hash`, `average_hash`, `difference_hash`, `color_signature`,
`dimension_signature`, `metadata_signature`, `tag_signature`. Байты берутся из **локального
файла enhanced-варианта** (`output_path`), если он есть и разрешён; иначе — **graceful
fallback** (status `partial`, source `metadata_only`/`tags_only`, без визуального хэша). Сеть
не используется по умолчанию.

## Какие хэши считаются (и как работает perceptual hash)

- **file_sha256** — SHA-256 байтов (точный дубль байтов).
- **average_hash** (8×8): изображение → grayscale → 8×8 → бит `1`, если пиксель ≥ среднего →
  64-битный hex.
- **difference_hash** (dHash 9×8): сравнение соседних по горизонтали пикселей → 64-битный hex.
- **perceptual_hash** = average_hash (MVP; без DCT/embeddings).
- **color_signature** — средний RGB, яркость, aspect ratio, грубые RGB-бакеты.
- **metadata_signature** — расширение, media_kind и **хэши** имени/базового имени/заголовка/
  yandex-пути (сырые значения не хранятся).
- **tag_signature** — нормализованные products/technologies/categories + сводная подпись.

Всё — через Pillow (уже зависимость). При отсутствии Pillow или недекодируемом файле (HEIC без
плагина) визуальные хэши пропускаются → `partial`.

## Как ищутся похожие медиа (`media_similarity_service`)

`compare_fingerprints(left, right)` сравнивает два fingerprint **в пределах одного проекта** и
возвращает `similarity_score ∈ [0..1]`, `similarity_type`, причины, подскоры (visual/tag/
metadata) и `hash_distance` (Hamming):

- одинаковый `file_sha256` → **1.0 exact_duplicate**;
- одинаковый хэш yandex-пути → **1.0 same_yandex_path**;
- Hamming average_hash ≤ 2 → **0.95 near_duplicate**;
- Hamming ≤ `MEDIA_SIMILARITY_NEAR_HASH_DISTANCE` → **0.85 visually_similar**;
- одинаковое базовое имя, разные расширения → **heic_jpeg_pair**;
- одинаковое имя + совпадение тегов → **0.82 near_duplicate**;
- одинаковая подпись тегов → **0.60 same_series** (не дубль без визуального/именного сигнала).

Сильный визуальный сигнал доминирует; иначе — взвешенное смешение
`MEDIA_SIMILARITY_VISUAL_WEIGHT·visual + MEDIA_SIMILARITY_TAG_WEIGHT·tag`.

## Как создаются duplicate clusters

`find_duplicate_clusters` строит пары выше порога (`MEDIA_DUPLICATE_CLUSTER_MIN_SCORE`),
объединяет их **union-find** по `media_asset_id` и создаёт `MediaDuplicateCluster`:
`cluster_type`, `canonical_media_asset_id`, `member_media_asset_ids`, `similarity_score`,
`reasons`, `recommended_actions`. **canonical** выбирается по правилам: approved > выше
media-quality > богаче теги > не использовалось недавно > меньший id.

## Почему нет удаления

Кластеры — только записи с рекомендациями (`keep_canonical`, `hide_duplicate`,
`replace_in_schedule`, `merge_series`, `retag_duplicate`, `needs_review`). Клиент размечает
кластер (`reviewed` / `ignored` / `resolved`); файлы **никогда** не удаляются и не скрываются
автоматически — реальный cleanup-workflow остаётся на будущее.

## Как это влияет на media quality (Часть 8)

`media_quality_service` при наличии сохранённых fingerprint/кластеров уточняет
`uniqueness_score`: точный дубль → 25, почти-дубль → 45, серия → 70, уникальное → 90. Issue-
коды: `duplicate_candidate` (точный/почти), `visually_similar`, `same_series`. Рекомендации:
«оставьте canonical», «выберите другое для разнообразия», «объедините серию / добавьте теги».

## Как auto media selection использует дубли/разнообразие (Часть 9)

`schedule_media_decision_service` **не выбирает почти-одинаковые фото** в одной media_group:
жадно отбрасывает кандидатов, похожих на уже выбранные (по fingerprint/кластеру). Если все
похожи — берёт лучший canonical и предупреждает. В решение и `generation_notes` пишется
`media_diversity_summary`: `diversity_score`, `similar_media_skipped_count`,
`duplicate_cluster_ids`, `selected_similarity_warnings`. Risk-флаги: `duplicate_candidate`,
`low_diversity_media_group`, `similar_media_recently_used`.

## Worker (Часть 10)

При `MEDIA_FINGERPRINTING_WORKER_ENABLED=true` worker считает fingerprint и кластеры дублей
медиатеки проектов; `TickResult` получает `media_fingerprints_previewed/created`,
`duplicate_clusters_previewed/created` + audit `scheduler.worker.media_fingerprint.*` /
`scheduler.worker.duplicate_cluster.*`. Локально, без внешнего AI/сети/live.

## Почему нет внешнего AI

Все fingerprint и сравнения — чистые локальные вычисления (хэши, Hamming-дистанция, сигнатуры)
через Pillow. Никаких vision/embedding API, никакой сети по умолчанию. Image embeddings и
визуальная AI-модель — на будущее, по умолчанию выключены.

## Config-флаги

```
MEDIA_FINGERPRINTING_ENABLED=true               # preview/UI/API/CLI доступны
MEDIA_FINGERPRINTING_WORKER_ENABLED=false       # worker пишет fingerprint (по умолчанию выкл)
MEDIA_FINGERPRINTING_DRY_RUN=true               # dry-run (по умолчанию — без записи)
MEDIA_FINGERPRINTING_MAX_ASSETS_PER_RUN=200
MEDIA_FINGERPRINTING_USE_IMAGE_BYTES=true
MEDIA_FINGERPRINTING_USE_VARIANTS=true
MEDIA_FINGERPRINTING_USE_YANDEX_DOWNLOAD=false   # сеть выключена по умолчанию
MEDIA_FINGERPRINTING_EXTERNAL_AI_ENABLED=false   # внешний AI НЕ используется
MEDIA_SIMILARITY_DEDUP_ENABLED=true
MEDIA_SIMILARITY_EXACT_HASH_THRESHOLD=1.0
MEDIA_SIMILARITY_NEAR_HASH_DISTANCE=6
MEDIA_SIMILARITY_TAG_WEIGHT=0.2
MEDIA_SIMILARITY_VISUAL_WEIGHT=0.8
MEDIA_DUPLICATE_CLUSTER_MIN_SCORE=0.82
MEDIA_DUPLICATE_AUTO_HIDE_ENABLED=false          # авто-скрытие НЕ выполняется
MEDIA_DUPLICATE_AUTO_DELETE_ENABLED=false         # авто-удаление НЕ выполняется
```

## Биллинг

Preview, расчёт fingerprint, preview/построение кластеров — **бесплатны в MVP**
(`media_fingerprint_preview/calculate`, `media_duplicate_preview/calculate` — 0 units; без
внешнего AI). Будущий image-embedding/AI может быть платным, но сейчас выключен. Неуспешный
расчёт не списывает ничего; двойного дебета нет.

## API

- `GET  /media-fingerprints/projects/{id}` — список fingerprint;
- `POST /media-fingerprints/projects/{id}/preview | /calculate` — пачка (dry/write);
- `POST /media-fingerprints/projects/{id}/media-assets/{aid}/preview | /calculate` — один медиа;
- `GET  /media-fingerprints/{fingerprint_id}` — один fingerprint;
- `GET  /media-fingerprints/projects/{id}/duplicates` — кластеры;
- `POST /media-fingerprints/projects/{id}/duplicates/preview | /calculate` — построить (dry/write);
- `POST /media-fingerprints/projects/{id}/duplicates/{cluster_id}/review` — reviewed/ignored/resolved;
- `GET  /media-fingerprints/projects/{id}/dashboard` — сводка.

Все роуты — под tenant-изоляцией (чужой проект/fingerprint/кластер → 404). Секретов, raw bytes
и путей к файлам нет; удаления файлов нет.

## CLI

```bash
make media-fingerprint-preview project_id=1 limit=50
make media-fingerprint-calculate project_id=1 dry_run=false
make media-duplicate-preview project_id=1
make media-duplicate-calculate project_id=1 dry_run=false
make media-duplicate-dashboard project_id=1
```

Dry-run по умолчанию для calculate; секреты/пути не печатаются; файлы не удаляются.

## UI

- `/ui/projects/{id}/media-fingerprints` — «Fingerprint медиа»: сводка по статусам, карточки
  (media_asset_id, статус, источник, префиксы хэшей, подпись тегов, дата расчёта);
- `/ui/projects/{id}/media-duplicates` — «Дубли и похожие медиа»: карточки кластеров (тип,
  canonical, участники, similarity, причины, рекомендованные действия, статус) + «Отметить
  просмотренным»/«Игнорировать» (**без удаления файлов**);
- `/ui/projects/{id}/media-quality` — ссылки на fingerprint/дубли;
- `/ui/projects/{id}/media-decisions/{id}` — карточка «Разнообразие подборки» (diversity_score,
  пропущено похожих, кластеры);
- `/ui/projects/{id}/automation` — блок «Fingerprint и дубли медиа» + флаги;
- `/ui/scheduler` — блок «Fingerprint и дубли медиа в worker» + счётчики.

## Приватность

Сравнение строго per-project — межклиентского смешивания нет. В API/UI/CLI/аудите нет сырых
токенов, raw bytes и внутренних путей к файлам (только хэши/сигнатуры; имя/путь хэшируются).

## Что дальше

Image embeddings (визуальная релевантность/near-dup по содержимому) · визуальная AI-модель
качества · video fingerprinting · авто-ретегирование после одобрения · реальный duplicate
cleanup-workflow (скрытие/архивация с подтверждением).
