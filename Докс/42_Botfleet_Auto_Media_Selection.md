# 42. Botfleet: автовыбор медиа в worker-е (v0.4.5)

Слой поверх автовыбора темы ([41](41_Botfleet_Auto_Topic_Selection.md)): для ближайшего
слота расписания worker не просто берёт первое одобренное фото, а сам **выбирает
media strategy и конкретные медиа** — по теме (topic decision), тегам, платформе, learning
profile, A/B winners, прошлым метрикам и доступности media assets — и сохраняет «почему бот
выбрал эти медиа» (:class:`ScheduleMediaDecision`). Пост создаётся только как
draft/needs_review.

> **Безопасность:** это **не** этап live-публикаций, **не** реальных платежей и **не**
> внешних API-вызовов. Решение влияет только на **draft/needs_review**; live-публикаций нет.
> Автовыбор worker-ом **выключен** по умолчанию (`AUTO_MEDIA_SELECTION_WORKER_ENABLED=false`),
> dry-run по умолчанию. Публичные ссылки на медиа **автоматически не создаются**
> (`AUTO_MEDIA_SELECTION_CREATE_PUBLIC_LINKS=false`). Никакие live-флаги публикации/платежей
> это не включает. Секретов и внутренних путей к файлам в ответах/метаданных нет.

## Термины

- **MediaDecisionStatus**: `preview · selected · applied_to_draft · skipped · failed · blocked`
- **MediaDecisionSource**: `topic_decision · learning_profile · media_tags · media_availability · ab_winner · metrics · manual_category · fallback`
- **MediaStrategy**: `text_only · single_image · media_group · carousel_ready · video_later · no_media_available`
- **MediaDecisionRisk**: `no_media · low_confidence · repeated_media · platform_requires_public_url · media_proxy_not_https · heic_conversion_needed · too_many_images · video_not_supported · missing_media_tags · weak_media_match`

## Сигналы (`schedule_media_decision_service._build_context`)

Все сигналы строго **per-project** (без межклиентского обучения):

1. **Topic decision** — `selected_topic` и его теги превращаются в «желаемые теги» и токены темы;
2. **CRM-категория** — `media_tags` категории плана/проекта («желаемые теги»);
3. **Learning profile** — `preferred_media_types` и `high_performing_tags` из
   `ClientLearningService.summarize_learning` (при `AUTO_MEDIA_SELECTION_USE_CLIENT_FEEDBACK`);
4. **A/B winners** — победившая `media_strategy` варианта эксперимента
   (при `AUTO_MEDIA_SELECTION_USE_AB_WINNERS`);
5. **Fatigue** — недавно использованные media asset id (по последним постам и applied-решениям);
6. **Media proxy** — готовность (enabled + https_ready), без сети;
7. **Enhanced-варианты** — id улучшенных вариантов ассетов (для `selected_media_variant_ids`).

## Кандидаты (`build_media_candidates`)

Сканируются media assets проекта со статусом `approved` / `approved_video`. Каждый ассет
скорится; берутся **совпавшие** по тегам/теме (matched), а если совпадений нет — **fallback**
к любым approved. Кандидаты делятся на изображения и видео, сортируются «лучшие первыми».

## Скоринг кандидата (`score_media_candidate`, MVP)

| Компонент | Δ |
|-----------|---|
| точное совпадение media-тега | +25 |
| слово темы в тегах/имени файла | +15 |
| media-тег CRM-категории | +15 |
| высокоэффективный media-тег (обучение) | +15 |
| медиа давно не использовалось | +10 |
| недавно использованное медиа | −20 |
| видео на неподдерживаемой площадке | −30 |
| HEIC (нужна конвертация) | −5 |

Стратегия-уровневые: A/B-winner media_strategy `+15`, поддержка группы и 2+ изображений
`+10`, нет медиа для медиа-плана `−20`, Instagram требует public URL, а HTTPS нет `−25`.

`explain_media_decision` формирует человекочитаемые причины («Медиа выбрано по тегам…»,
«Формат media_group выбран: доступно 4 подходящих изображений», «Instagram требует public
image_url», «Медиа не использовалось недавно», «Есть риск: HEIC нужно конвертировать»).

## Выбор media strategy (`choose_strategy`)

- **Telegram** — `media_group` при 2–10 изображениях; `single_image` при 1; `text_only` без медиа.
- **VK** — `media_group` при 2–5; `single_image` при 1; `text_only` без медиа.
- **Instagram** — `carousel_ready` при 2–10; `single_image` при 1; `no_media_available` без
  изображений; **`needs_public_image_url=true`** при наличии изображений.
- **Website/Blog и прочее** — предпочтителен `single_image`.
- **Только видео** — `video_later` (в live на этом этапе не грузим).
- Число изображений усечено по лимиту платформы (`AUTO_MEDIA_SELECTION_MAX_IMAGES_*`).

`confidence_score ∈ [0..1]` — функция от среднего score выбранных медиа, бонусов за
группу/A-B-winner и штрафа за Instagram-без-HTTPS. Ниже порога
(`AUTO_MEDIA_SELECTION_MIN_CONFIDENCE`) добавляется risk `low_confidence` → пост в ревью.

## Fatigue / reuse penalty

Недавно использованные media asset id (из последних постов и applied-решений в окне
`AUTO_MEDIA_SELECTION_RECENCY_DAYS`) получают штраф новизны (−20). Если **все** выбранные
медиа недавние — risk `repeated_media`. Это предотвращает повтор одних и тех же фото.

## Как A/B winners влияют на медиа

Победившая `media_strategy` из завершённого A/B-эксперимента поднимает соответствующую
стратегию (`+15`) и добавляет сигнал `ab_winner`. Так подтверждённо-эффективный формат
(например, `media_group`) получает приоритет — но только как один из сигналов, не жёстко.

## Как topic decision влияет на медиа

Если для слота уже создано `ScheduleTopicDecision`, его `selected_topic` даёт токены темы и
«желаемые теги» → медиа по теме получают topic-match бонус, а само решение о медиа
связывается с решением о теме (`schedule_topic_decision_id`).

## Instagram public image_url и media proxy

Для Instagram при наличии изображений `needs_public_image_url=true` (Instagram Graph API
требует публичную ссылку). Готовность media proxy (enabled + https_ready) читается **без
сети** и отражается в `media_proxy_ready`; при needs_public без HTTPS — risk
`media_proxy_not_https` и снижение уверенности. **Публичные ссылки автоматически не
создаются** — это остаётся ручным/отдельным шагом (см. [34](34_Botfleet_Media_Proxy_Public_Image_URL.md)).

## Почему live-публикация не выполняется

Сервис/worker/API **не импортируют** `publish_due` и не вызывают клиентов платформ. Решение
только записывает выбор и накладывает `media_asset_ids` / `media_strategy` на **draft**;
публикация остаётся за ревью-воркфлоу и требует явных live-флагов (по умолчанию выключены).

## Интеграция в расписание и worker

- `ScheduleAutomationService.run_due` после решения о теме создаёт решение о медиа (если
  `AUTO_MEDIA_SELECTION_WORKER_ENABLED=true` и не dry-run), накладывает выбранные медиа на
  черновик и пишет в `generation_notes`: `schedule_media_decision_id`,
  `selected_media_asset_ids`, `selected_media_tags`, `selected_media_strategy`,
  `media_decision_confidence`, `media_decision_reasons`, `media_decision_source_signals`,
  `media_decision_risk_flags`, `needs_public_image_url`; сводка — в `ScheduleRun.run_metadata`.
- `SchedulerWorkerService.tick` агрегирует счётчики в `TickResult`:
  `auto_media_selection_enabled/dry_run`, `media_decisions_previewed/created`,
  `low_confidence_media_decisions`, `no_media_decisions` — и пишет audit
  (`scheduler.worker.media_decision.*`). Дубли исключены идемпотентностью прогона расписания.

## Обучение

При одобрении/отклонении поста, созданного из решения, `schedule_media_decision_id` и
выбранная стратегия попадают в метаданные события обучения (`ClientLearningService`), давая
слабый сигнал по выбранным медиа. Межклиентского смешивания нет.

## Config-флаги

```
AUTO_MEDIA_SELECTION_ENABLED=true                 # preview/UI/API/CLI доступны
AUTO_MEDIA_SELECTION_WORKER_ENABLED=false         # worker создаёт решения (по умолчанию выкл)
AUTO_MEDIA_SELECTION_DRY_RUN=true                 # dry-run (по умолчанию — без записи worker-ом)
AUTO_MEDIA_SELECTION_MIN_CONFIDENCE=0.50
AUTO_MEDIA_SELECTION_RECENCY_DAYS=60
AUTO_MEDIA_SELECTION_FATIGUE_WINDOW_DAYS=14
AUTO_MEDIA_SELECTION_MAX_IMAGES_TELEGRAM=10
AUTO_MEDIA_SELECTION_MAX_IMAGES_VK=5
AUTO_MEDIA_SELECTION_MAX_IMAGES_INSTAGRAM=10
AUTO_MEDIA_SELECTION_REQUIRE_MEDIA_FOR_MEDIA_PLANS=false
AUTO_MEDIA_SELECTION_USE_AB_WINNERS=true
AUTO_MEDIA_SELECTION_USE_METRICS=true
AUTO_MEDIA_SELECTION_USE_CLIENT_FEEDBACK=true
AUTO_MEDIA_SELECTION_CREATE_PUBLIC_LINKS=false    # публичные ссылки НЕ создаются автоматически
```

## Биллинг

Preview и создание media-решения — **бесплатны** (`media_decision_preview`,
`media_decision_create`, `media_decision_apply_to_draft` — 0 units). Применение решения к
драфту включено в обычную генерацию draft по расписанию — **без отдельного списания и без
двойного дебета**. Неуспешное решение не списывает ничего. Публичные ссылки (если создаются
вручную) следуют существующим правилам media proxy.

## API

- `GET  /media-decisions/projects/{id}` — список (фильтры `platform_key/decision_status/strategy`);
- `GET  /media-decisions/projects/{id}/dashboard` — сводка;
- `POST /media-decisions/projects/{id}/preview` — предпросмотр (без записи);
- `POST /media-decisions/projects/{id}/create` — создать решение (без поста и live; идемпотентно);
- `GET  /media-decisions/{id}` — одно решение;
- `POST /media-decisions/{id}/apply-dry` — как решение повлияло бы на draft-payload (без записи).

Все роуты — под tenant-изоляцией (чужой проект/решение → 404). Секретов и путей к файлам нет.

## CLI

```bash
make media-decision-preview project_id=1 platform=telegram plan_id=1
make media-decision-create project_id=1 platform=telegram dry_run=false
make media-decision-dashboard project_id=1
```

Dry-run по умолчанию для create; секреты/пути не печатаются; пост не создаётся; live нет.

## UI

- `/ui/projects/{id}/media-decisions` — «Выбор медиа по обучению»: preview/создание + карточки
  решений (стратегия/платформа/медиа/теги/уверенность/источник/риски/причины);
- `/ui/projects/{id}/media-decisions/{id}` — детали: выбранные медиа, альтернативы, причины,
  риски, сигналы, связанный прогон/пост/тема, «влияние на draft»;
- `/ui/projects/{id}/automation` — блок «Автовыбор медиа» + флаги;
- `/ui/scheduler` — блок «Автовыбор медиа в worker» + счётчики последнего тика;
- карточка проекта — «Следующее медиа · почему бот выберет эти фото».

## Приватность

Обучение и подбор медиа строго per-project: A/B winners, метрики, learning profile,
fatigue-история — только своего проекта. Межклиентского смешивания нет. В API/UI/CLI/аудите
нет сырых токенов и внутренних путей к файлам.

## Что дальше

Оценка качества медиа реализована в [43](43_Botfleet_Media_Quality_Scoring.md) (v0.4.6), а
визуальная дедупликация и разнообразие подборки (не выбирать почти-дубли в media_group,
`diversity_score`) — в [44](44_Botfleet_Media_Fingerprints_Dedup.md) (v0.4.7). Скрытые
курированием медиа исключаются из подбора — [45](45_Botfleet_Media_Curation_Workflow.md)
(v0.4.8). Далее: автосоздание публичных ссылок после публичного HTTPS-домена · image
embeddings · полноценная video-стратегия · платформенно-специфичное взвешивание · production
live-auto
аудит.


> **Autopilot-first (v0.5.6):** этот слой скрыт за клиентским автопилотом — клиент подключает Яндекс Диск и календарь, а Botfleet сам всё делает. См. [53_Botfleet_Autopilot_First_Workspace.md](53_Botfleet_Autopilot_First_Workspace.md).