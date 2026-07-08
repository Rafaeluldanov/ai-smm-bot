VENV := .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help install run test lint format typecheck check \
        db-up db-down migrate revision seed-projects sync-media \
        sync-public-media \
        retag-media media-summary select-topics content-plan \
        enhance-media enhance-project-media media-enhancement-summary \
        generate-post generate-weekly-posts \
        media-groups media-group-post \
        review-post approve-post reject-post \
        schedule-post publish-post publish-due \
        ingest-analytics analytics-report \
        search-external-images convert-external-image \
        autonomous-run autonomous-dry-run autonomous-report \
        preview-vk-seo seo-content-plan \
        crm-form-schema crm-onboarding-validate crm-onboarding-preview \
        crm-onboarding-apply crm-category-plan \
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

smoke: ## Смоук-проверка: приложение поднимается, health/readiness отвечают
	PYTHONPATH=backend $(BIN)/python -m app.scripts.smoke_check

test: ## Запустить тесты
	$(BIN)/pytest

lint: ## Проверить код линтером ruff
	$(BIN)/ruff check backend

format: ## Отформатировать код ruff
	$(BIN)/ruff format backend

typecheck: ## Проверить типы mypy
	$(BIN)/mypy

check: lint typecheck test ## Полная проверка: ruff + mypy + pytest
