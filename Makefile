VENV := .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help install run test lint format typecheck check \
        db-up db-down migrate revision seed-projects sync-media \
        sync-public-media \
        retag-media media-summary select-topics content-plan \
        enhance-media enhance-project-media media-enhancement-summary \
        media-proxy-link media-proxy-cleanup \
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
