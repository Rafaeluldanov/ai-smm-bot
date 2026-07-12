# 46. Botfleet: collaborative review медиатеки (v0.4.9)

Слой поверх воркфлоу курирования ([45](45_Botfleet_Media_Curation_Workflow.md)): медиатека
курируется не одним человеком, а через **нормальный review workflow** — задачи на проверку,
ответственные, комментарии, история решений, кто что одобрил/отклонил/применил, запрос правок,
статусы задач и **безопасное применение изменений только после подтверждения**.

> **Безопасность:** это **не** этап удаления медиа, **не** live-публикаций, **не** внешнего AI и
> **не** реальных платежей. Изменения (теги/видимость) применяются **только после `approved`**
> (`MEDIA_CURATION_REVIEW_REQUIRE_APPROVAL=true`); авто-применение выключено
> (`MEDIA_CURATION_REVIEW_AUTO_APPLY_AFTER_APPROVAL=false`); уведомления выключены
> (`MEDIA_CURATION_REVIEW_NOTIFY_ENABLED=false`); внешнего AI нет
> (`MEDIA_CURATION_REVIEW_EXTERNAL_AI_ENABLED=false`); **файлы никогда не удаляются**;
> double-apply запрещён. В API/UI/CLI/аудите нет сырых токенов и внутренних путей к файлам.

## Зачем нужно ревью медиатеки

Одиночное курирование не масштабируется на команду: непонятно, кто отвечает за задачу, что уже
обсудили, кто одобрил применение и что именно изменилось. Collaborative review добавляет:
задачи на проверку с ответственным и сроком, комментарии, полную историю решений (timeline) и
жёсткое правило **approve-before-apply** — применить изменения к медиатеке можно только после
явного одобрения.

## Термины

- **MediaCurationReviewStatus**: `proposed · assigned · in_review · changes_requested · approved · rejected · applied · ignored · restored · expired · failed`
- **MediaCurationReviewAction**: `assign · unassign · start_review · comment · request_changes · approve · reject · apply · ignore · restore · expire`
- **MediaCurationPriority**: `low · normal · high · urgent`
- **MediaCurationDecisionType**: `approve_tags · reject_tags · mark_duplicate · keep_canonical · hide_from_selection · restore_to_selection · ignore_cluster · request_replacement · mark_reviewed`
- **Роли участников**: `owner · admin · member · viewer · reviewer` (доступ фактически проверяют
  tenant-гарды проекта; роли — словарь процесса).

`review_status` — **отдельное измерение** от `status` v0.4.8: `status` описывает жизненный цикл
самой задачи курирования, `review_status` — стадию согласования.

## Роли и ответственные

- `assignee_user_id` — ответственный за задачу; `reviewer_user_id` — кто проверяет;
- `priority` (`low|normal|high|urgent`) и `due_at` (срок) — для приоритезации и overdue;
- назначение (`assign`) переводит задачу в `assigned`, старт проверки (`start_review`) — в
  `in_review` и фиксирует reviewer.

## Статусы (жизненный цикл)

```
proposed ──assign──▶ assigned ──start_review──▶ in_review
   │                                   │
   │                                   ├─ request_changes ─▶ changes_requested
   │                                   ├─ approve ─────────▶ approved ──apply──▶ applied
   │                                   └─ reject ──────────▶ rejected
   └─ ignore ─▶ ignored        restore ─▶ restored        overdue(due_at<now)
```

## Комментарии

- пользователь пишет комментарий к задаче; типы: `comment · decision · system · request_changes · approval · rejection`;
- текст **санитизируется** (`sanitize_review_text`): секреты (токены/ключи) и внутренние пути к
  файлам (`disk:/…`, абсолютные пути) не сохраняются;
- лимит на задачу — `MEDIA_CURATION_REVIEW_MAX_COMMENTS_PER_TASK` (по умолчанию 100);
- комментарии видны в UI и попадают в timeline; в MVP физически **не удаляются**;
- каждый комментарий отражается в аудите (`media_curation_review.comment_added`).

## История решений (timeline)

`build_review_timeline` собирает хронологию: системные события (кто предложил/назначил/начал
проверку/одобрил/отклонил/применил/восстановил — из `review_metadata.events`) + комментарии,
отсортированные по времени. Для применённой задачи фиксируются `before_state`/`after_state`
(теги и `selection_visibility` затронутых медиа до/после) и `decision_summary` (действие,
исход, кто применил).

## Approved retagging и duplicate review

- `approve_tags` — подтвердить и добавить предложенные теги (только после `approved`);
- `mark_duplicate` — скрыть дубли (canonical остаётся `selectable`, дубль → `hidden_duplicate`);
- `hide_from_selection` — скрыть слабое медиа из авто-подбора;
- `restore_to_selection` / `restore` — вернуть медиа в подбор (файл не трогаем);
- `keep_canonical` / `ignore_cluster` / `mark_reviewed` — не изменяют медиа.

## Approve-before-apply (гейт согласования)

Правило безопасности реализовано в двух местах:
- `MediaCurationReviewService.apply_approved_task` — если `require_approval` и `review_status !=
  approved`, для изменяющих действий возвращается `requires_approval` (blocked), изменений нет;
- `MediaCurationService.apply_task` (прямой v0.4.8 путь) **тоже** уважает гейт при
  `MEDIA_CURATION_REVIEW_REQUIRE_APPROVAL=true` — прямой apply без approved заблокирован.

Дополнительно: **double-apply запрещён** (повторный apply → `already_applied`), `reject`/`ignore`
ничего не применяют, физического удаления файлов нет.

## Интеграция

- `media_curation quality/selection` видят видимость: скрытые медиа исключаются из авто-подбора
  и учитываются качеством (наследуется из v0.4.8);
- после `approved`/`applied` обновляются теги/видимость и пишется аудит (learning видит
  `curation_status=reviewed`);
- дашборд проекта показывает активные задачи ревью, на одобрении и overdue.

## UI

- `/ui/projects/{id}/media-curation-review` — **доска ревью**: summary-карточки (proposed,
  assigned, in_review, changes_requested, approved, applied, overdue), фильтры (статус,
  приоритет, тип, только overdue) и карточки задач с кнопками **Assign / Start review / Approve /
  Request changes / Reject / Apply approved / Ignore / Restore** (**без кнопки удаления**);
- `/ui/projects/{id}/media-curation-review/tasks/{id}` — **детали задачи**: данные, before/after,
  комментарии (+форма), timeline, действия;
- `/ui/projects/{id}/media-curation` — ссылка на доску ревью;
- `/ui/projects/{id}/automation` — блок «Media curation review» + флаги;
- `/ui/projects/{id}/dashboard` — подсказка «Ревью медиатеки» (активные/на одобрении/overdue).

## CLI

```bash
make media-curation-review-dashboard project_id=1
make media-curation-review-comment task_id=1 comment="Оставить главное фото, дубль скрыть"   # dry-run по умолчанию
make media-curation-review-approve task_id=1 comment="Теги корректные" dry_run=false
make media-curation-review-apply   task_id=1 action=approve_tags dry_run=true
```

Все write-CLI **dry-run по умолчанию** (пишут только при `dry_run=false`); секреты и внутренние
пути не печатаются; удаления нет.

## Флаги конфигурации

| Флаг | По умолчанию | Смысл |
| --- | --- | --- |
| `MEDIA_CURATION_REVIEW_ENABLED` | `true` | Доступен ли workflow ревью |
| `MEDIA_CURATION_REVIEW_REQUIRE_APPROVAL` | `true` | Применять изменения только после `approved` |
| `MEDIA_CURATION_REVIEW_ALLOW_SELF_APPROVAL` | `true` | Может ли ответственный сам одобрять |
| `MEDIA_CURATION_REVIEW_DEFAULT_PRIORITY` | `normal` | Приоритет новой задачи |
| `MEDIA_CURATION_REVIEW_OVERDUE_DAYS` | `7` | Порог просрочки |
| `MEDIA_CURATION_REVIEW_MAX_COMMENTS_PER_TASK` | `100` | Лимит комментариев на задачу |
| `MEDIA_CURATION_REVIEW_NOTIFY_ENABLED` | `false` | Уведомления (пока нет) |
| `MEDIA_CURATION_REVIEW_AUTO_APPLY_AFTER_APPROVAL` | `false` | Авто-apply после approve |
| `MEDIA_CURATION_REVIEW_EXTERNAL_AI_ENABLED` | `false` | Внешний AI (запрещён) |

## Биллинг

Ревью медиатеки — **бесплатно в MVP**: `media_curation_review_comment`,
`media_curation_review_approve`, `media_curation_review_apply` стоят 0 units. Неуспешный apply не
списывает средства. Платной коллаборативной модель может стать позже.

## Аудит

Действия: `media_curation_review.comment_added · assigned · unassigned · started ·
changes_requested · approved · rejected · applied · ignored · restored · overdue`. Метаданные:
`project_id · task_id · media_asset_id · user_id · action · review_status · priority` (без
секретов и внутренних путей).

## Приватность

Строго per-project/account (без межклиентского смешивания). В API/UI/CLI/аудите — только
id/теги/статусы; сырых токенов и внутренних путей к файлам нет.

## Что дальше

- система уведомлений (assignee/reviewer);
- collaborative review с упоминаниями (@mentions);
- SLA/нагрузка ревьюеров (reviewer workload);
- реальный duplicate cleanup с бэкапами;
- визуальные AI-подсказки качества.

> **Продолжение (v0.5.0):** уведомления, упоминания (@mentions), inbox и нагрузка ревьюеров с SLA
> реализованы — assign/comment/mention/approve/reject/apply создают внутренние уведомления. См.
> [47_Botfleet_Notifications_Mentions_Workload.md](47_Botfleet_Notifications_Mentions_Workload.md).
