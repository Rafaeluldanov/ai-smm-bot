VENV := .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help install run test lint format typecheck check \
        db-up db-down migrate revision seed-projects sync-media \
        sync-public-media \
        retag-media media-summary select-topics content-plan \
        enhance-media enhance-project-media media-enhancement-summary \
        media-proxy-link media-proxy-cleanup media-proxy-generate media-proxy-check \
        schedule-due-preview schedule-due-run \
        scheduler-tick scheduler-loop scheduler-loop-dry \
        generate-post generate-weekly-posts \
        media-groups media-group-post publish-preview media-platform-preview \
        review-post approve-post reject-post \
        schedule-post publish-post publish-due \
        ingest-analytics analytics-report \
        search-external-images convert-external-image \
        autonomous-run autonomous-dry-run autonomous-report \
        preview-vk-seo seo-content-plan \
        crm-form-schema crm-onboarding-validate crm-onboarding-preview \
        crm-onboarding-apply crm-category-plan \
        saas-form-schema saas-onboarding-preview saas-onboarding-apply \
        saas-teeon-stanislav-preview saas-teeon-stanislav-apply \
        saas-today-calendar-preview saas-today-calendar-apply \
        vk-oauth-env vk-oauth-tunnel-wizard vk-photo-test-preview vk-photo-test-apply \
        local-https-cert vk-oauth-local-https run-https-local \
        vk-oauth-setup-info vk-api-photo-probe vk-api-photo-probe-upload \
        vk-browser-install vk-browser-publish-preview vk-browser-publish-live \
        billing-balance billing-topup \
        prod-check security-readiness backup-db restore-db \
        admin-create-user admin-grant-role audit-export \
        media-curation-review-dashboard media-curation-review-comment \
        media-curation-review-approve media-curation-review-apply \
        notifications-inbox notifications-overdue-scan notifications-workload \
        notification-delivery-preview notification-delivery-send notification-delivery-retry \
        notification-digest-preview notification-digest-generate notification-digest-scheduler \
        notification-safety-dashboard notification-opt-out notification-suppression-clear \
        webhook-subscription-create webhook-subscription-preview \
        email-template-preview email-notification-preview email-test-send \
        telegram-binding-create telegram-binding-verify telegram-notification-preview telegram-test-send \
        telegram-update-simulate telegram-webhook-info telegram-webhook-set telegram-polling-dry \
        yandex-sync-profile yandex-sync-preview yandex-sync-run yandex-sync-worker-tick \
        autopilot-calendar-preview autopilot-calendar-create autopilot-calendar-apply autopilot-calendar-dashboard \
        live-readiness-check live-readiness-platform-check live-readiness-enable live-readiness-effective-gate \
        telegram-live-rollout-dashboard telegram-live-rollout-preview telegram-live-rollout-run-dry telegram-live-rollout-publish-once \
        live-autopilot-monitoring-dashboard live-autopilot-monitoring-health-check live-autopilot-monitoring-incidents live-autopilot-monitoring-pause \
        telegram-runbook-check telegram-runbook-preview telegram-runbook-publish-test \
        onboarding-start onboarding-status onboarding-demo \
        ai-learning-profile ai-learning-analyze ai-learning-recommend \
        strategy-analyze strategy-recommend strategy-apply \
        campaign-create campaign-plan campaign-apply \
        sales-analyze sales-report sales-lead \
        smoke

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Создать виртуальное окружение и установить зависимости
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --seed --python 3.11 $(VENV); \
		$(BIN)/python -m pip install -e ".[dev]"; \
	else \
		python3.11 -m venv $(VENV); \
		$(BIN)/python -m pip install --upgrade pip; \
		$(BIN)/python -m pip install -e ".[dev]"; \
	fi

run: ## Запустить dev-сервер FastAPI
	$(BIN)/uvicorn app.main:app --reload --app-dir backend

db-up: ## Поднять PostgreSQL и Redis (docker compose)
	docker compose up -d db redis

db-down: ## Остановить и удалить контейнеры docker compose
	docker compose down

migrate: ## Применить миграции до последней (alembic upgrade head)
	$(BIN)/alembic upgrade head

revision: ## Создать миграцию автогенерацией: make revision message="..."
	$(BIN)/alembic revision --autogenerate -m "$(message)"

seed-projects: ## Заполнить базовые проекты (TEEON, Фабрика сувениров)
	PYTHONPATH=backend $(BIN)/python -m app.scripts.seed_projects

sync-media: ## Синхронизировать медиа проекта: make sync-media project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.sync_media --project-slug "$(project_slug)"

sync-public-media: ## Публичная синхронизация: make sync-public-media project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.sync_media --project-slug "$(project_slug)" --public

retag-media: ## Перетегировать медиа проекта: make retag-media project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.retag_media --project-slug "$(project_slug)"

media-summary: ## Сводка по тегам проекта: make media-summary project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_summary --project-slug "$(project_slug)"

enhance-media: ## Улучшить медиа (копию): make enhance-media media_asset_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.enhance_media --media-asset-id "$(media_asset_id)"

enhance-project-media: ## Улучшить медиа проекта: make enhance-project-media project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.enhance_project_media --project-slug "$(project_slug)"

media-enhancement-summary: ## Сводка улучшений: make media-enhancement-summary project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_enhancement_summary --project-slug "$(project_slug)"

media-proxy-link: ## Публичная media-ссылка: make media-proxy-link project_id=1 media_asset_id=1 [purpose=instagram]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.create_public_media_link --project-id "$(project_id)" --media-asset-id "$(media_asset_id)" --purpose "$(or $(purpose),instagram)"

media-proxy-cleanup: ## Пометить просроченные ссылки: make media-proxy-cleanup [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_proxy_cleanup --dry-run "$(or $(dry_run),true)"

media-proxy-generate: ## URL доставки: make media-proxy-generate project_id=1 media_asset_id=1 [transform=width_1080] [platform=instagram]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_proxy_generate --project-id "$(project_id)" --media-asset-id "$(media_asset_id)" --transform "$(or $(transform),width_1080)" $(if $(platform),--platform "$(platform)",)

media-proxy-check: ## Готовность media-proxy доставки: make media-proxy-check
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_proxy_check

schedule-due-preview: ## Preview due-задач: make schedule-due-preview account_id=1 project_id=1 platform=telegram [date=today]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.schedule_due_preview --account-id "$(account_id)" --project-id "$(project_id)" --platform "$(platform)" --date "$(or $(date),today)"

schedule-due-run: ## Обработать due-задачи: make schedule-due-run account_id=1 project_id=1 platform=telegram [date=today] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.schedule_due_run --account-id "$(account_id)" --project-id "$(project_id)" --platform "$(platform)" --date "$(or $(date),today)" --dry-run "$(or $(dry_run),true)"

scheduler-tick: ## Один тик scheduler-worker: make scheduler-tick [dry_run=true] [force=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.scheduler_worker_tick --dry-run "$(or $(dry_run),true)" --force "$(or $(force),true)"

scheduler-loop: ## Цикл scheduler-worker: make scheduler-loop [force=false]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.scheduler_worker_loop --force "$(or $(force),false)"

scheduler-loop-dry: ## Безопасный цикл dry-run: make scheduler-loop-dry [force=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.scheduler_worker_loop --dry-run true --force "$(or $(force),true)"

select-topics: ## Выбрать темы проекта: make select-topics project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.select_topics --project-slug "$(project_slug)"

content-plan: ## Недельный контент-план: make content-plan project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.content_plan --project-slug "$(project_slug)"

generate-post: ## Сгенерировать пост по теме: make generate-post topic_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.generate_post --topic-id "$(topic_id)"

generate-weekly-posts: ## Посты на неделю: make generate-weekly-posts project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.generate_weekly_posts --project-slug "$(project_slug)"

media-groups: ## Превью групп медиа: make media-groups project_slug=teeon tag=футболка
	PYTHONPATH=backend $(BIN)/python -m app.scripts.preview_media_groups --project-slug "$(project_slug)" $(if $(tag),--tag "$(tag)",)

media-group-post: ## Пост из группы медиа: make media-group-post project_slug=teeon tag=футболка
	PYTHONPATH=backend $(BIN)/python -m app.scripts.create_media_group_post --project-slug "$(project_slug)" $(if $(tag),--tag "$(tag)",)

publish-preview: ## Dry-run preview поста по платформам: make publish-preview post_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.publish_post --post-id "$(post_id)" --dry-run

media-platform-preview: ## Превью медиа по платформам: make media-platform-preview project_slug=teeon tag=футболка platforms="telegram,vk,instagram,youtube,rutube"
	PYTHONPATH=backend $(BIN)/python -m app.scripts.preview_media_platforms --project-slug "$(project_slug)" $(if $(tag),--tag "$(tag)",) $(if $(platforms),--platforms "$(platforms)",)

review-post: ## Действие согласования: make review-post post_id=1 action=submit
	PYTHONPATH=backend $(BIN)/python -m app.scripts.review_post --post-id "$(post_id)" --action "$(action)"

approve-post: ## Одобрить пост: make approve-post post_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.review_post --post-id "$(post_id)" --action approve

reject-post: ## Отклонить пост: make reject-post post_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.review_post --post-id "$(post_id)" --action reject

schedule-post: ## Запланировать публикации: make schedule-post post_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.schedule_post --post-id "$(post_id)"

publish-post: ## Опубликовать пост: make publish-post post_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.publish_post --post-id "$(post_id)"

publish-due: ## Опубликовать созревшие публикации: make publish-due
	PYTHONPATH=backend $(BIN)/python -m app.scripts.publish_due

ingest-analytics: ## Ввести метрики поста: make ingest-analytics post_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ingest_analytics --post-id "$(post_id)"

metrics-import-preview: ## Превью импорта метрик: make metrics-import-preview project_id=1 [platform=telegram] [source=demo] [depth=standard]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.metrics_import_preview --project-id "$(project_id)" --platform "$(or $(platform),all)" --source "$(or $(source),demo)" --depth "$(or $(depth),standard)"

metrics-import-run: ## Импорт метрик (dry-run по умолчанию): make metrics-import-run project_id=1 [source=demo] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.metrics_import_run --project-id "$(project_id)" --platform "$(or $(platform),all)" --source "$(or $(source),demo)" --depth "$(or $(depth),standard)" --dry-run "$(or $(dry_run),true)"

manual-metrics: ## Ручной ввод метрик публикации (бесплатно): make manual-metrics publication_id=1 views=1000 likes=50
	PYTHONPATH=backend $(BIN)/python -m app.scripts.manual_metrics --publication-id "$(publication_id)" $(if $(views),--views $(views),) $(if $(reach),--reach $(reach),) $(if $(impressions),--impressions $(impressions),) $(if $(likes),--likes $(likes),) $(if $(comments),--comments $(comments),) $(if $(shares),--shares $(shares),) $(if $(saves),--saves $(saves),) $(if $(clicks),--clicks $(clicks),) $(if $(followers_delta),--followers-delta $(followers_delta),)

learning-rebuild: ## Пересчёт обучения по метрикам (dry-run по умолчанию): make learning-rebuild project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.rebuild_learning_from_metrics --project-id "$(project_id)" --platform "$(or $(platform),all)" --depth "$(or $(depth),standard)" --dry-run "$(or $(dry_run),true)"

topic-recommendations: ## Рекомендации тем: make topic-recommendations project_id=1 [platform=telegram] [limit=10]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.topic_recommendations --project-id "$(project_id)" --platform "$(or $(platform),all)" --limit "$(or $(limit),10)"

ab-experiment-preview: ## Превью A/B по теме (без записи): make ab-experiment-preview project_id=1 platform=telegram topic="..."
	PYTHONPATH=backend $(BIN)/python -m app.scripts.create_ab_experiment --project-id "$(project_id)" --platform "$(or $(platform),all)" --topic "$(topic)" --variant-count "$(or $(variant_count),2)" --dry-run true

ab-experiment-create: ## Создать A/B по теме (платно): make ab-experiment-create project_id=1 platform=telegram topic="..." [dry_run=false]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.create_ab_experiment --project-id "$(project_id)" --platform "$(or $(platform),all)" --topic "$(topic)" --variant-count "$(or $(variant_count),2)" --dry-run "$(or $(dry_run),true)"

experiment-score: ## Скоринг эксперимента: make experiment-score experiment_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.score_experiment --experiment-id "$(experiment_id)"

experiment-winner: ## Выбор winner (dry-run по умолчанию): make experiment-winner experiment_id=1 [method=auto] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.choose_experiment_winner --experiment-id "$(experiment_id)" --method "$(or $(method),auto)" --dry-run "$(or $(dry_run),true)"

experiment-suggestions-preview: ## Preview предложений worker-а: make experiment-suggestions-preview project_id=1 [platform=telegram] [limit=10]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.experiment_suggestions_preview --project-id "$(project_id)" --platform "$(or $(platform),all)" $(if $(limit),--limit $(limit),)

experiment-suggestions-generate: ## Генерация предложений (dry-run по умолчанию): make experiment-suggestions-generate project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.experiment_suggestions_generate --project-id "$(project_id)" --platform "$(or $(platform),all)" --dry-run "$(or $(dry_run),true)"

experiment-suggestion-accept: ## Принять предложение: make experiment-suggestion-accept suggestion_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.experiment_suggestion_accept --suggestion-id "$(suggestion_id)"

experiment-suggestion-create: ## Создать A/B из предложения (dry-run по умолчанию): make experiment-suggestion-create suggestion_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.experiment_suggestion_create --suggestion-id "$(suggestion_id)" --dry-run "$(or $(dry_run),true)"

topic-decision-preview: ## Предпросмотр решения автовыбора темы: make topic-decision-preview project_id=1 [platform=telegram] [plan_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.topic_decision_preview --project-id "$(project_id)" --platform "$(or $(platform),all)" $(if $(plan_id),--plan-id $(plan_id),) $(if $(category_id),--category-id $(category_id),)

topic-decision-create: ## Создать решение автовыбора темы (dry-run по умолчанию): make topic-decision-create project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.topic_decision_create --project-id "$(project_id)" --platform "$(or $(platform),all)" $(if $(plan_id),--plan-id $(plan_id),) --dry-run "$(or $(dry_run),true)"

topic-decision-dashboard: ## Сводка решений автовыбора темы: make topic-decision-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.topic_decision_dashboard --project-id "$(project_id)" --platform "$(or $(platform),all)"

media-decision-preview: ## Предпросмотр решения автовыбора медиа: make media-decision-preview project_id=1 [platform=telegram] [plan_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_decision_preview --project-id "$(project_id)" --platform "$(or $(platform),all)" $(if $(plan_id),--plan-id $(plan_id),) $(if $(topic_decision_id),--topic-decision-id $(topic_decision_id),)

media-decision-create: ## Создать решение автовыбора медиа (dry-run по умолчанию): make media-decision-create project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_decision_create --project-id "$(project_id)" --platform "$(or $(platform),all)" $(if $(plan_id),--plan-id $(plan_id),) $(if $(topic_decision_id),--topic-decision-id $(topic_decision_id),) --dry-run "$(or $(dry_run),true)"

media-decision-dashboard: ## Сводка решений автовыбора медиа: make media-decision-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_decision_dashboard --project-id "$(project_id)" --platform "$(or $(platform),all)"

media-quality-preview: ## Предпросмотр оценки качества медиа: make media-quality-preview project_id=1 [platform=telegram] [limit=50]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_quality_preview --project-id "$(project_id)" --platform "$(or $(platform),all)" --limit "$(or $(limit),50)"

media-quality-score: ## Оценить качество медиа (dry-run по умолчанию): make media-quality-score project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_quality_score --project-id "$(project_id)" --platform "$(or $(platform),all)" --limit "$(or $(limit),100)" --dry-run "$(or $(dry_run),true)"

media-quality-dashboard: ## Сводка качества медиа: make media-quality-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_quality_dashboard --project-id "$(project_id)" --platform "$(or $(platform),all)"

media-fingerprint-preview: ## Предпросмотр fingerprint медиа: make media-fingerprint-preview project_id=1 [limit=50]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_fingerprint_preview --project-id "$(project_id)" --limit "$(or $(limit),50)"

media-fingerprint-calculate: ## Рассчитать fingerprint медиа (dry-run по умолчанию): make media-fingerprint-calculate project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_fingerprint_calculate --project-id "$(project_id)" --limit "$(or $(limit),100)" --dry-run "$(or $(dry_run),true)"

media-duplicate-preview: ## Предпросмотр кластеров дублей: make media-duplicate-preview project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_duplicate_preview --project-id "$(project_id)"

media-duplicate-calculate: ## Построить кластеры дублей (dry-run по умолчанию): make media-duplicate-calculate project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_duplicate_calculate --project-id "$(project_id)" --dry-run "$(or $(dry_run),true)"

media-duplicate-dashboard: ## Сводка дублей медиа: make media-duplicate-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_duplicate_dashboard --project-id "$(project_id)"

media-curation-preview: ## Предпросмотр задач курирования: make media-curation-preview project_id=1 [limit=50]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_preview --project-id "$(project_id)" --platform "$(or $(platform),all)" --limit "$(or $(limit),50)"

media-curation-generate: ## Сгенерировать задачи курирования (dry-run по умолчанию): make media-curation-generate project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_generate --project-id "$(project_id)" --platform "$(or $(platform),all)" --dry-run "$(or $(dry_run),true)"

media-curation-apply: ## Применить задачу курирования (dry-run по умолчанию): make media-curation-apply task_id=1 action=approve_tags [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_apply --task-id "$(task_id)" --action "$(or $(action),mark_reviewed)" --dry-run "$(or $(dry_run),true)"

media-curation-dashboard: ## Сводка курирования медиатеки: make media-curation-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_dashboard --project-id "$(project_id)"

media-curation-review-dashboard: ## Сводка доски ревью медиатеки: make media-curation-review-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_review_dashboard --project-id "$(project_id)"

media-curation-review-comment: ## Комментарий к задаче ревью (dry-run по умолчанию): make media-curation-review-comment task_id=1 comment="..." [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_review_comment --task-id "$(task_id)" --comment "$(comment)" --dry-run "$(or $(dry_run),true)"

media-curation-review-approve: ## Одобрить задачу ревью (dry-run по умолчанию): make media-curation-review-approve task_id=1 [comment="..."] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_review_approve --task-id "$(task_id)" $(if $(comment),--comment "$(comment)",) --dry-run "$(or $(dry_run),true)"

media-curation-review-apply: ## Применить одобренную задачу ревью (dry-run по умолчанию): make media-curation-review-apply task_id=1 action=approve_tags [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.media_curation_review_apply --task-id "$(task_id)" --action "$(or $(action),mark_reviewed)" --dry-run "$(or $(dry_run),true)"

notifications-inbox: ## Inbox уведомлений пользователя: make notifications-inbox user_id=1 [status=unread]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notifications_inbox --user-id "$(user_id)" $(if $(status),--status "$(status)",)

notifications-overdue-scan: ## Скан просроченных задач ревью (dry-run по умолчанию): make notifications-overdue-scan project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notifications_overdue_scan $(if $(project_id),--project-id "$(project_id)",) --dry-run "$(or $(dry_run),true)"

notifications-workload: ## Нагрузка ревьюеров проекта: make notifications-workload project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notifications_workload --project-id "$(project_id)"

notification-delivery-preview: ## Предпросмотр доставки: make notification-delivery-preview notification_id=1 [channels=email,telegram]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_delivery_preview --notification-id "$(notification_id)" --channels "$(or $(channels),email)"

notification-delivery-send: ## Доставка (dry-run по умолчанию): make notification-delivery-send notification_id=1 channels=email [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_delivery_send --notification-id "$(notification_id)" --channels "$(or $(channels),email)" --dry-run "$(or $(dry_run),true)"

notification-delivery-retry: ## Повтор доставок (dry-run по умолчанию): make notification-delivery-retry [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_delivery_retry --dry-run "$(or $(dry_run),true)"

notification-digest-preview: ## Предпросмотр дайджеста: make notification-digest-preview user_id=1 [frequency=daily]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_digest_preview --user-id "$(user_id)" --frequency "$(or $(frequency),daily)"

notification-digest-generate: ## Генерация дайджеста (dry-run по умолчанию): make notification-digest-generate user_id=1 [frequency=daily] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_digest_generate --user-id "$(user_id)" --frequency "$(or $(frequency),daily)" --dry-run "$(or $(dry_run),true)"

notification-digest-scheduler: ## Планировщик дайджестов (dry-run по умолчанию): make notification-digest-scheduler [frequency=daily] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_digest_scheduler --frequency "$(or $(frequency),daily)" --dry-run "$(or $(dry_run),true)"

notification-safety-dashboard: ## Сводка безопасности уведомлений: make notification-safety-dashboard user_id=1 [project_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_safety_dashboard --user-id "$(user_id)" $(if $(project_id),--project-id "$(project_id)",)

notification-opt-out: ## Создать отписку (dry-run по умолчанию): make notification-opt-out user_id=1 scope=channel channel=email [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_opt_out --user-id "$(user_id)" --scope "$(or $(scope),global)" $(if $(channel),--channel "$(channel)",) $(if $(project_id),--project-id "$(project_id)",) --dry-run "$(or $(dry_run),true)"

notification-suppression-clear: ## Снять подавление (dry-run по умолчанию): make notification-suppression-clear suppression_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.notification_suppression_clear --suppression-id "$(suppression_id)" --dry-run "$(or $(dry_run),true)"

webhook-subscription-create: ## Создать webhook-подписку (dry-run по умолчанию): make webhook-subscription-create account_id=1 url=https://... [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.webhook_subscription_create --account-id "$(account_id)" --url "$(url)" $(if $(project_id),--project-id "$(project_id)",) --dry-run "$(or $(dry_run),true)"

webhook-subscription-preview: ## Preview доставки webhook (без реального вызова): make webhook-subscription-preview subscription_id=1 [notification_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.webhook_subscription_preview --subscription-id "$(subscription_id)" $(if $(notification_id),--notification-id "$(notification_id)",)

email-template-preview: ## Предпросмотр email-шаблона (sandbox): make email-template-preview template_type=review_assigned [list=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.email_template_preview $(if $(filter true,$(list)),--list,--template-type "$(or $(template_type),system_notice)")

email-notification-preview: ## Предпросмотр email уведомления/дайджеста (sandbox): make email-notification-preview notification_id=1 [show_unsafe_url=false]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.email_notification_preview $(if $(notification_id),--notification-id "$(notification_id)",) $(if $(digest_id),--digest-id "$(digest_id)",) --show-unsafe-url "$(or $(show_unsafe_url),false)"

email-test-send: ## Тестовая отправка email (DRY-RUN only): make email-test-send to=user@example.ru [template_type=system_notice]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.email_test_send --to "$(to)" --template-type "$(or $(template_type),system_notice)"

telegram-binding-create: ## Создать привязку Telegram (token один раз): make telegram-binding-create user_id=1 [project_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_binding_create --user-id "$(user_id)" $(if $(account_id),--account-id "$(account_id)",) $(if $(project_id),--project-id "$(project_id)",)

telegram-binding-verify: ## Верифицировать привязку Telegram (dry/локально): make telegram-binding-verify token=TOKEN chat_id=123456 [username=user]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_binding_verify --token "$(token)" --chat-id "$(chat_id)" $(if $(username),--username "$(username)",) --show-unsafe "$(or $(show_unsafe),false)"

telegram-notification-preview: ## Предпросмотр Telegram-текста (sandbox): make telegram-notification-preview notification_id=1 [digest_id=1] [list=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_notification_preview $(if $(filter true,$(list)),--list,) $(if $(notification_id),--notification-id "$(notification_id)",) $(if $(digest_id),--digest-id "$(digest_id)",)

telegram-test-send: ## Тестовая Telegram-отправка (DRY-RUN only): make telegram-test-send user_id=1 [template_type=system_notice] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_test_send --user-id "$(user_id)" --template-type "$(or $(template_type),system_notice)" --dry-run "$(or $(dry_run),true)"

telegram-update-simulate: ## Симуляция входящего /start апдейта (sandbox): make telegram-update-simulate token=TOKEN chat_id=123456 [username=user]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_update_simulate --token "$(token)" --chat-id "$(chat_id)" $(if $(username),--username "$(username)",) --show-unsafe "$(or $(show_unsafe),false)"

telegram-webhook-info: ## getWebhookInfo (dry-run, sandbox): make telegram-webhook-info [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_webhook_info --dry-run "$(or $(dry_run),true)"

telegram-webhook-set: ## setWebhook (dry-run, sandbox): make telegram-webhook-set url=https://app.example.com/notification-telegram/webhook [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_webhook_set $(if $(url),--url "$(url)",) --dry-run "$(or $(dry_run),true)"

telegram-polling-dry: ## getUpdates (dry-run, sandbox): make telegram-polling-dry [limit=10] [offset=0]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_polling_dry $(if $(limit),--limit "$(limit)",) $(if $(offset),--offset "$(offset)",)

yandex-sync-profile: ## Профиль синхронизации Яндекс Диска: make yandex-sync-profile project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.yandex_sync_profile --project-id "$(project_id)"

yandex-sync-preview: ## Предпросмотр синхронизации (без записи): make yandex-sync-preview project_id=1 [limit=50]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.yandex_sync_preview --project-id "$(project_id)" $(if $(limit),--limit "$(limit)",)

yandex-sync-run: ## Синхронизация (DRY-RUN по умолчанию): make yandex-sync-run project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.yandex_sync_run --project-id "$(project_id)" --dry-run "$(or $(dry_run),true)"

yandex-sync-worker-tick: ## Tick воркера синхронизации (dry-run): make yandex-sync-worker-tick [dry_run=true] [limit=20]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.yandex_sync_worker_tick --dry-run "$(or $(dry_run),true)" $(if $(limit),--limit "$(limit)",)

autopilot-calendar-preview: ## Предпросмотр календаря автопостинга (без записи): make autopilot-calendar-preview project_id=1 [preset=three_per_week] [goal=mixed] [time=10:00]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autopilot_calendar_preview --project-id "$(project_id)" $(if $(preset),--preset "$(preset)",) $(if $(goal),--goal "$(goal)",) $(if $(time),--time "$(time)",) $(if $(platforms),--platforms "$(platforms)",)

autopilot-calendar-create: ## Создать календарь (DRY-RUN по умолчанию): make autopilot-calendar-create project_id=1 [preset=...] [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autopilot_calendar_create --project-id "$(project_id)" $(if $(preset),--preset "$(preset)",) $(if $(goal),--goal "$(goal)",) $(if $(time),--time "$(time)",) $(if $(platforms),--platforms "$(platforms)",) --dry-run "$(or $(dry_run),true)"

autopilot-calendar-apply: ## Применить календарь к автопилоту: make autopilot-calendar-apply project_id=1 calendar_plan_id=3
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autopilot_calendar_apply --project-id "$(project_id)" --calendar-plan-id "$(calendar_plan_id)"

autopilot-calendar-dashboard: ## Дашборд календаря автопостинга: make autopilot-calendar-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autopilot_calendar_dashboard --project-id "$(project_id)"

live-readiness-check: ## Готовность проекта к автопубликации (dry-run): make live-readiness-check project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_readiness_check --project-id "$(project_id)" --dry-run "$(or $(dry_run),true)"

live-readiness-platform-check: ## Готовность площадки: make live-readiness-platform-check project_id=1 platform=telegram [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_readiness_platform_check --project-id "$(project_id)" --platform "$(platform)" --dry-run "$(or $(dry_run),true)"

live-readiness-enable: ## Включить per-project live (dry-run): make live-readiness-enable project_id=1 confirmation=ENABLE_LIVE_AUTOPILOT [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_readiness_enable --project-id "$(project_id)" --confirmation "$(or $(confirmation),ENABLE_LIVE_AUTOPILOT)" --dry-run "$(or $(dry_run),true)"

live-readiness-effective-gate: ## Эффективный live-гейт: make live-readiness-effective-gate project_id=1 platform=telegram
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_readiness_effective_gate --project-id "$(project_id)" --platform "$(platform)"

telegram-live-rollout-dashboard: ## Дашборд Telegram live rollout: make telegram-live-rollout-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_rollout_dashboard --project-id "$(project_id)"

telegram-live-rollout-preview: ## Предпросмотр Telegram live: make telegram-live-rollout-preview project_id=1 [post_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_rollout_preview --project-id "$(project_id)" $(if $(post_id),--post-id "$(post_id)",)

telegram-live-rollout-run-dry: ## Тестовый прогон Telegram (без отправки): make telegram-live-rollout-run-dry project_id=1 [post_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_rollout_run_dry --project-id "$(project_id)" $(if $(post_id),--post-id "$(post_id)",)

telegram-live-rollout-publish-once: ## Live-попытка Telegram (DRY-RUN по умолчанию): make telegram-live-rollout-publish-once project_id=1 post_id=1 confirmation=ENABLE_TELEGRAM_LIVE [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_rollout_publish_once --project-id "$(project_id)" $(if $(post_id),--post-id "$(post_id)",) --confirmation "$(or $(confirmation),ENABLE_TELEGRAM_LIVE)" --dry-run "$(or $(dry_run),true)"

live-autopilot-monitoring-dashboard: ## Дашборд мониторинга автопилота: make live-autopilot-monitoring-dashboard project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_autopilot_monitoring_dashboard --project-id "$(project_id)"

live-autopilot-monitoring-health-check: ## Проверка здоровья автопилота (dry-run): make live-autopilot-monitoring-health-check project_id=1 [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_autopilot_monitoring_health_check --project-id "$(project_id)" --dry-run "$(or $(dry_run),true)"

live-autopilot-monitoring-incidents: ## Инциденты автопилота: make live-autopilot-monitoring-incidents project_id=1 [status=open]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_autopilot_monitoring_incidents --project-id "$(project_id)" $(if $(status),--status "$(status)",)

live-autopilot-monitoring-pause: ## Стоп-кран автопилота: make live-autopilot-monitoring-pause project_id=1 action=pause confirmation=PAUSE_AUTOPILOT
	PYTHONPATH=backend $(BIN)/python -m app.scripts.live_autopilot_monitoring_pause --project-id "$(project_id)" --action "$(or $(action),pause)" --confirmation "$(confirmation)"

telegram-runbook-check: ## Готовность Telegram runbook: make telegram-runbook-check project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_runbook_check --project-id "$(project_id)"

telegram-runbook-preview: ## Предпросмотр тестового поста: make telegram-runbook-preview project_id=1 [post_id=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_runbook_preview --project-id "$(project_id)" $(if $(post_id),--post-id "$(post_id)",)

telegram-runbook-publish-test: ## Production-тест Telegram (DRY-RUN по умолчанию): make telegram-runbook-publish-test project_id=1 confirmation=ENABLE_TELEGRAM_LIVE [dry_run=true]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.telegram_live_runbook_publish_test --project-id "$(project_id)" $(if $(post_id),--post-id "$(post_id)",) --confirmation "$(or $(confirmation),ENABLE_TELEGRAM_LIVE)" --dry-run "$(or $(dry_run),true)"

onboarding-start: ## Старт онбординга клиента: make onboarding-start user_id=1 [company="TEEON"]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.onboarding_start --user-id "$(user_id)" $(if $(company),--company "$(company)",)

onboarding-status: ## Статус онбординга: make onboarding-status session_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.onboarding_status --session-id "$(session_id)"

onboarding-demo: ## Демо онбординга (5 шагов, live OFF): make onboarding-demo user_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.onboarding_demo --user-id "$(user_id)"

ai-learning-profile: ## Профиль AI-обучения: make ai-learning-profile project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ai_learning_profile --project-id "$(project_id)"

ai-learning-analyze: ## Анализ AI-обучения: make ai-learning-analyze project_id=1 [window_days=90]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ai_learning_analyze --project-id "$(project_id)" $(if $(window_days),--window-days "$(window_days)",)

ai-learning-recommend: ## Рекомендации AI-обучения: make ai-learning-recommend project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ai_learning_recommend --project-id "$(project_id)"

strategy-analyze: ## Анализ контент-стратегии: make strategy-analyze project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.content_strategy_analyze --project-id "$(project_id)"

strategy-recommend: ## Рекомендации стратегии: make strategy-recommend project_id=1 [status=generated]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.content_strategy_recommend --project-id "$(project_id)" $(if $(status),--status "$(status)",)

strategy-apply: ## Применить рекомендацию: make strategy-apply project_id=1 rec_id=5 [accept=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.content_strategy_apply --project-id "$(project_id)" --recommendation-id "$(rec_id)" $(if $(accept),--accept,)

campaign-create: ## Создать кампанию: make campaign-create project_id=1 name="..." goal=sales [product="..."]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ai_campaign_create --project-id "$(project_id)" --name "$(name)" --goal "$(goal)" $(if $(product),--product "$(product)",)

campaign-plan: ## Спланировать кампанию: make campaign-plan campaign_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ai_campaign_plan --campaign-id "$(campaign_id)"

campaign-apply: ## Применить кампанию (черновик): make campaign-apply campaign_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.ai_campaign_apply --campaign-id "$(campaign_id)"

sales-analyze: ## Анализ продаж из контента: make sales-analyze project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.sales_intelligence_analyze --project-id "$(project_id)"

sales-report: ## Отчёт продаж из контента: make sales-report project_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.sales_intelligence_report --project-id "$(project_id)"

sales-lead: ## Записать лид/выручку: make sales-lead project_id=1 event=deal_won value=50000 [post_id=12]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.sales_intelligence_lead --project-id "$(project_id)" --event "$(event)" $(if $(value),--value "$(value)",) $(if $(post_id),--post-id "$(post_id)",) $(if $(campaign_id),--campaign-id "$(campaign_id)",)

analytics-report: ## Отчёт аналитики: make analytics-report project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.analytics_report --project-slug "$(project_slug)"

search-external-images: ## Поиск внешних картинок: make search-external-images project_slug=teeon query="..."
	PYTHONPATH=backend $(BIN)/python -m app.scripts.search_external_images --project-slug "$(project_slug)" --query "$(query)"

convert-external-image: ## Конвертировать кандидата: make convert-external-image candidate_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.convert_external_image --candidate-id "$(candidate_id)"

autonomous-run: ## Автономный прогон: make autonomous-run project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autonomous_run --project-slug "$(project_slug)"

autonomous-dry-run: ## Сухой прогон: make autonomous-dry-run project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autonomous_run --project-slug "$(project_slug)" --dry-run

autonomous-report: ## Отчёт прогона: make autonomous-report run_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.autonomous_report --run-id "$(run_id)"

preview-vk-seo: ## Превью SEO-заполнения VK-группы: make preview-vk-seo project_slug=teeon
	PYTHONPATH=backend $(BIN)/python -m app.scripts.preview_vk_group_seo_setup --project-slug "$(project_slug)"

seo-content-plan: ## SEO-контент-план на N дней: make seo-content-plan project_slug=teeon days=30
	PYTHONPATH=backend $(BIN)/python -m app.scripts.generate_seo_content_plan --project-slug "$(project_slug)" --days "$(or $(days),30)"

crm-form-schema: ## Схема формы «БОТ СММ» для CRM: make crm-form-schema
	PYTHONPATH=backend $(BIN)/python -m app.scripts.preview_crm_bot_smm_form

crm-onboarding-validate: ## Валидация онбординга: make crm-onboarding-validate payload_path=...
	PYTHONPATH=backend $(BIN)/python -m app.scripts.validate_crm_onboarding_payload --payload-path "$(payload_path)"

crm-onboarding-preview: ## Превью онбординга (dry-run): make crm-onboarding-preview payload_path=...
	PYTHONPATH=backend $(BIN)/python -m app.scripts.apply_crm_onboarding_payload --payload-path "$(payload_path)" --dry-run true

crm-onboarding-apply: ## Применить онбординг (real): make crm-onboarding-apply payload_path=...
	PYTHONPATH=backend $(BIN)/python -m app.scripts.apply_crm_onboarding_payload --payload-path "$(payload_path)" --dry-run false

crm-category-plan: ## Контент-план категории: make crm-category-plan category_id=1 days=30
	PYTHONPATH=backend $(BIN)/python -m app.scripts.preview_crm_category_plan --category-id "$(category_id)" --days "$(or $(days),30)"

saas-form-schema: ## Схема SaaS-формы онбординга: make saas-form-schema
	PYTHONPATH=backend $(BIN)/python -m app.scripts.preview_saas_onboarding_form

saas-onboarding-preview: ## SaaS онбординг dry-run: make saas-onboarding-preview account_id=1 payload_path=...
	PYTHONPATH=backend $(BIN)/python -m app.scripts.apply_saas_onboarding_payload --account-id "$(account_id)" --payload-path "$(payload_path)" --dry-run true

saas-onboarding-apply: ## SaaS онбординг apply: make saas-onboarding-apply account_id=1 payload_path=...
	PYTHONPATH=backend $(BIN)/python -m app.scripts.apply_saas_onboarding_payload --account-id "$(account_id)" --payload-path "$(payload_path)" --dry-run false

saas-teeon-stanislav-preview: ## TEEON для Станислава (dry-run): make saas-teeon-stanislav-preview
	PYTHONPATH=backend $(BIN)/python -m app.scripts.setup_stanislav_teeon_project --dry-run true

saas-teeon-stanislav-apply: ## TEEON для Станислава (apply): make saas-teeon-stanislav-apply
	PYTHONPATH=backend $(BIN)/python -m app.scripts.setup_stanislav_teeon_project --apply true

saas-today-calendar-preview: ## Календарь на сегодня (dry-run): make saas-today-calendar-preview account_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.create_today_calendar_posts --account-id "$(account_id)" --project-slug teeon --date today --telegram-media-posts "$(or $(telegram),2)" --vk-text-posts "$(or $(vk),1)" --dry-run true

saas-today-calendar-apply: ## Календарь на сегодня (needs_review): make saas-today-calendar-apply account_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.create_today_calendar_posts --account-id "$(account_id)" --project-slug teeon --date today --telegram-media-posts "$(or $(telegram),2)" --vk-text-posts "$(or $(vk),1)" --dry-run false

vk-oauth-env: ## Локально записать VK OAuth в .env (секрет через getpass): make vk-oauth-env
	PYTHONPATH=backend $(BIN)/python -m app.scripts.setup_vk_oauth_env

vk-oauth-tunnel-wizard: ## Dev: HTTPS-туннель (cloudflared) для VK OAuth callback + .env
	PYTHONPATH=backend $(BIN)/python -m app.scripts.dev_vk_oauth_tunnel_wizard

local-https-cert: ## Сгенерировать локальный self-signed HTTPS-сертификат (tmp/certs)
	PYTHONPATH=backend $(BIN)/python -m app.scripts.setup_local_https

vk-oauth-local-https: ## VK OAuth в .env для локального HTTPS (redirect https://localhost:8443)
	PYTHONPATH=backend $(BIN)/python -m app.scripts.setup_vk_oauth_local_https

run-https-local: ## Поднять UI по https://localhost:8443 (нужен make local-https-cert)
	@test -f tmp/certs/localhost-cert.pem || { echo "Нет сертификата — сначала: make local-https-cert"; exit 1; }
	PYTHONPATH=backend $(BIN)/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8443 --ssl-keyfile tmp/certs/localhost-key.pem --ssl-certfile tmp/certs/localhost-cert.pem

vk-photo-test-preview: ## VK photo-тест dry-run: make vk-photo-test-preview account_id=2
	PYTHONPATH=backend $(BIN)/python -m app.scripts.prepare_vk_photo_test --account-id "$(account_id)" --project-slug "$(or $(project_slug),teeon)" --tag "$(or $(tag),футболка)" --dry-run true

vk-photo-test-apply: ## VK photo-тест needs_review: make vk-photo-test-apply account_id=2
	PYTHONPATH=backend $(BIN)/python -m app.scripts.prepare_vk_photo_test --account-id "$(account_id)" --project-slug "$(or $(project_slug),teeon)" --tag "$(or $(tag),футболка)" --dry-run false

vk-oauth-setup-info: ## Показать настройки VK OAuth callback (PUBLIC_APP_URL, VK ID), без секретов
	PYTHONPATH=backend $(BIN)/python -m app.scripts.show_vk_oauth_setup

vk-api-photo-probe: ## VK API: какая стратегия загрузки фото работает (read-only, без wall.post)
	PYTHONPATH=backend $(BIN)/python -m app.scripts.vk_api_photo_probe --strategy "$(or $(strategy),auto)"

vk-api-photo-probe-upload: ## VK API probe с реальной загрузкой тестового фото (без wall.post)
	PYTHONPATH=backend $(BIN)/python -m app.scripts.vk_api_photo_probe --strategy "$(or $(strategy),auto)" --allow-upload true

vk-browser-install: ## Dev: установить Playwright + Chromium (не prod-зависимость)
	$(BIN)/python -m pip install playwright
	$(BIN)/python -m playwright install chromium

vk-browser-publish-preview: ## VK через браузер (dry-run): make vk-browser-publish-preview post_id=44
	PYTHONPATH=backend $(BIN)/python -m app.scripts.vk_browser_publish_post --post-id "$(post_id)" --dry-run true

vk-browser-publish-live: ## VK через браузер (live, ручное подтверждение): make vk-browser-publish-live post_id=44
	PYTHONPATH=backend $(BIN)/python -m app.scripts.vk_browser_publish_post --post-id "$(post_id)" --dry-run false --confirm-live true

billing-balance: ## Баланс аккаунта: make billing-balance account_id=1
	PYTHONPATH=backend $(BIN)/python -m app.scripts.billing_balance --account-id "$(account_id)"

billing-topup: ## Пополнить депозит: make billing-topup account_id=1 units=500
	PYTHONPATH=backend $(BIN)/python -m app.scripts.billing_topup --account-id "$(account_id)" --units "$(units)"

smoke: ## Смоук-проверка: приложение поднимается, health/readiness отвечают
	PYTHONPATH=backend $(BIN)/python -m app.scripts.smoke_check

# --- Production readiness / обслуживание (v0.3.3) ---

prod-check: ## Production-readiness чек-лист (exit 2 при небезопасной конфигурации)
	PYTHONPATH=backend $(BIN)/python -m app.scripts.production_check

security-readiness: ## Проверить /health/security-readiness запущенного сервиса
	curl -s http://127.0.0.1:8000/health/security-readiness

backup-db: ## Бэкап PostgreSQL (pg_dump): make backup-db [dry_run=1]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.backup_db --output-dir backups $(if $(dry_run),--dry-run,)

restore-db: ## Восстановить БД: make restore-db backup_path=... confirm=RESTORE
	PYTHONPATH=backend $(BIN)/python -m app.scripts.restore_db --backup-path "$(backup_path)" --confirm "$(confirm)" --i-understand-data-loss "$(understand)"

admin-create-user: ## Создать пользователя: make admin-create-user email=... password=... [account_name=...]
	PYTHONPATH=backend $(BIN)/python -m app.scripts.admin_create_user --email "$(email)" --password "$(password)" --full-name "$(full_name)" $(if $(account_name),--account-name "$(account_name)",)

admin-grant-role: ## Выдать роль: make admin-grant-role account_id=1 user_id=1 role=admin
	PYTHONPATH=backend $(BIN)/python -m app.scripts.admin_grant_role --account-id "$(account_id)" --user-id "$(user_id)" --role "$(role)"

audit-export: ## Экспорт аудита: make audit-export account_id=1 output=audit.jsonl
	PYTHONPATH=backend $(BIN)/python -m app.scripts.audit_export --account-id "$(account_id)" --output "$(output)"

test: ## Запустить тесты
	$(BIN)/pytest

lint: ## Проверить код линтером ruff
	$(BIN)/ruff check backend

format: ## Отформатировать код ruff
	$(BIN)/ruff format backend

typecheck: ## Проверить типы mypy
	$(BIN)/mypy

check: lint typecheck test ## Полная проверка: ruff + mypy + pytest
