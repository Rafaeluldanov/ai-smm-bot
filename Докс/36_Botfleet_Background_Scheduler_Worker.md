# 36. Botfleet: фоновый scheduler-worker (v0.3.9)

Фоновый процесс, который сам периодически ищет due-задачи расписаний и создаёт
**draft/needs_review** посты (переиспользуя движок из v0.3.8). **Живой публикации нет.**

> По умолчанию worker **выключен** (`SCHEDULER_WORKER_ENABLED=false`) и в **dry-run**.
> Даже включённый worker НЕ публикует live и не вызывает внешние API платформ.

## 1. Что делает worker

Каждые N секунд worker:

1. захватывает DB-lease (один активный worker);
2. находит активные проекты и их задачи расписаний (`discover_due_targets`);
3. для каждой цели (account, project, platform) вызывает
   `ScheduleAutomationService.run_due_dry` (dry) или `run_due` (create-drafts);
4. создаёт `ScheduleRun` + draft/needs_review + `PostPublication` (pending/scheduled);
5. списывает units только за успех; пишет audit;
6. освобождает lease.

## 2. Чем отличается от publish-due

- **publish-due** (старое) публиковало созревшие публикации на платформы.
- **scheduler-worker** НЕ публикует: только создаёт черновики на ревью. Он **не
  импортирует** `publish_due`, не вызывает `PostPublicationService.publish_due` и live
  клиентов платформ.

## 3. Почему live не выполняется

Worker вызывает только `run_due`/`run_due_dry`, которые создают draft/needs_review и
`PostPublication` в `scheduled` (не `published`). Живая публикация — отдельный будущий
этап (после одобрения).

## 4. Lease (DB-lock)

`SchedulerWorkerLease` (миграция **0021**): `lease_key` (unique), `owner_id`
(host:pid:suffix, без секретов), `status` (active/released/expired), `expires_at`.

- `acquire_lease` — захватить/продлить; занята активной чужой lease → отказ;
- `heartbeat_lease` — продлить свою lease (в течение тика);
- `release_lease` — освободить (только владельцем);
- истёкшую lease (процесс умер) можно перехватить по TTL
  (`SCHEDULER_WORKER_LOCK_TTL_SECONDS`).

Без Redis/Celery на MVP — простой и надёжный DB-lock.

## 5. Idempotency

`run_due` использует ключ `sched-{project}-{plan}-{platform}-{date}-{time}` (unique).
Повторные тики по тому же due-слоту (уже `draft_created`) → skip, без дубля
`ScheduleRun`/`Post` и без повторного списания units.

## 6. Billing

Списание идёт внутри `run_due` (действие `schedule_due_draft_generation`): dry-run 0,
неуспех 0, успех — один раз; нехватка units → `insufficient_balance` (нет поста/списания).

## 7. Dry-run vs create-drafts

- `SCHEDULER_WORKER_DRY_RUN=true` → только preview/log, **без создания постов**;
- `SCHEDULER_WORKER_DRY_RUN=false` + `SCHEDULER_WORKER_CREATE_DRAFTS=true` → создаёт
  draft/needs_review (по-прежнему без live);
- `SCHEDULER_WORKER_CREATE_DRAFTS=false` форсит dry-run.

## 8. Как смотреть результаты

- UI `/ui/scheduler` — статус worker-а, lease, безопасный «Preview tick» / «Run one safe
  tick»;
- UI `/ui/projects/{id}/schedule-runs` — история прогонов (`ScheduleRun`);
- API `/scheduler-worker/status|leases|tick-dry|tick`.

## 9. CLI

```
make scheduler-tick dry_run=true force=true      # один тик (dry)
make scheduler-loop-dry force=true               # цикл dry-run (Ctrl+C — стоп)
make scheduler-loop force=true                   # цикл (dry/create по настройкам)
```
`scheduler_worker_loop` отказывается стартовать, если `SCHEDULER_WORKER_ENABLED=false` и
не передан `--force true`. Ctrl+C — graceful (release lease).

## 10. Production

Worker — **отдельный процесс/контейнер**, не внутри web app. В
`docker-compose.prod.example.yml` есть сервис `scheduler-worker`
(`python -m app.scripts.scheduler_worker_loop`), но по умолчанию выключен. Включение:

1. поднять отдельный контейнер `scheduler-worker`;
2. в `.env.production` осознанно выставить `SCHEDULER_WORKER_ENABLED=true`;
3. решить `SCHEDULER_WORKER_DRY_RUN` (true — только логи; false — создавать черновики);
4. НИКОГДА не включать live-флаги — worker их не использует, но проверьте окружение.

## 11. Риски и checklist

- [ ] worker запускается один раз (lease) — не дублирует черновики;
- [ ] `SCHEDULER_WORKER_ENABLED` включён осознанно;
- [ ] `*_LIVE_PUBLISHING_ENABLED=false` (worker их не трогает, но проверьте);
- [ ] мониторинг lease/тиков (audit `scheduler.worker.*`);
- [ ] бюджет units (worker списывает за создание черновиков).

## 12. Что дальше

- включение cron/контейнера в production;
- workflow одобрения (draft → approved);
- живая публикация после одобрения;
- мониторинг/алерты worker-а.
