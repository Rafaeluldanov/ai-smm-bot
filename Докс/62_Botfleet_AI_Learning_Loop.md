# Botfleet AI Learning Loop (v0.6.5)

Слой **памяти и обучения** Botfleet: система учится на конкретном клиенте, понимает
что у него работает, и подсказывает следующим публикациям. Это **не** новый AI и **не**
новый генератор — это безопасный per-client слой эвристик поверх уже существующей
аналитики и `ClientLearningService`.

## 1. Зачем обучение

Botfleet ведёт соцсети автопилотом. Чтобы качество росло, ему нужна **память** о
конкретном бренде: какие темы заходят, какие форматы сильнее, какой стиль/длина, какое
время и площадки дают лучший отклик, какой CTA работает. AI Learning Loop собирает эти
сигналы, агрегирует их в персональный профиль и превращает в рекомендации.

## 2. Архитектура

```
Публикации + метрики  ─┐
Клиентский фидбэк      ─┤→  AILearningEvent (поток сигналов)
Жизненный цикл поста   ─┘            │
                                     ▼
                          AILearningService.update_client_learning
                                     │  (агрегация по окну 30/60/90 дней)
                                     ▼
                          AILearningProfile («память» бренда)
                            │                │                │
                            ▼                ▼                ▼
                 recommend_next_content  explain_learning  LearningContextBuilder
                 ContentStrategyService                    → PostGenerationService
```

Используется существующая архитектура:
- `AnalyticsService` / `analytics_repository` — метрики постов;
- `ClientLearningService` — источник CTA/тем (reuse, не дублируется);
- `analytics_metrics.calculate_performance_score` — единый 0..100 скоринг;
- `PostGenerationService` — опциональный вход `learning_context` (генератор не переписан).

## 3. Модель данных

`AILearningProfile` (одна строка на проект, `ix_ai_learning_profiles_project` unique):
- `status`: `learning | stable | paused`;
- `learning_score` (0..100), `total_posts_analyzed`, `total_feedback_events`;
- `preferred_topics` / `avoided_topics`, `preferred_formats` / `avoided_formats`,
  `preferred_styles`, `best_publish_times`, `best_platforms`;
- `content_rules`, `media_preferences`, `cta_preferences` (JSON, без секретов);
- `last_learning_at`.

`AILearningEvent` (поток сигналов, per-project):
- `entity_type`: post | topic | format | media | schedule | platform;
- `event_type` (сигналы): impression | like | comment | share | save | click | lead |
  conversion | client_rating | manual_feedback (+ системные: post_created/post_published/post_blocked);
- `value`, `source` (analytics | client | ai | system), `event_metadata` (санитизируется).

Миграция: **`0047_ai_learning_loop`** (down_revision `0046_client_onboarding`).

## 4. Какие данные собираются

- **Аналитика** — `analyze_post_performance` разбирает снапшоты поста в события метрик
  (идемпотентно: без изменения значения дубли не создаются).
- **Клиентский фидбэк** — «Как вам пост?» (🔥 Отлично / 👍 Хорошо / 😐 Нормально /
  👎 Не подходит) или рейтинг 1..5 → `client_rating` / `manual_feedback`.
- **Жизненный цикл поста** — автопилот пишет `post_created` / `post_published` /
  `post_blocked` (fail-safe хук, source=system).

Секреты/токены и полный текст поста **не хранятся** — только идентификаторы и агрегаты.

## 5. Как бот обучается

`update_client_learning` за окно (по умолчанию 90 дней):
1. берёт последний снапшот на (post, platform), считает `performance_score` 0..100;
2. клиентские сигналы (rating/feedback) дают бонус/штраф баллов посту;
3. агрегирует по измерениям: формат, тема, медиа-тип, час публикации, площадка, стиль;
4. сильные (score ≥ 55) → preferred, слабые (score ≤ 25) → avoided;
5. `learning_score` = min(100, 100·(посты + фидбэк)/20); `stable` при ≥ 70;
6. пишет профиль + запись в AuditLog (`ai_learning.profile_updated`).

## 6. Рекомендации

- `recommend_next_content` → темы/форматы/стиль/лучшее время/уверенность;
- `ContentStrategyService.recommend_strategy` → частота/темы/форматы/тон/CTA/медиа-стиль;
- `explain_learning` → «что AI понял» + «что улучшилось» на языке клиента;
- `PostPerformanceLearningService` → `compare_posts` / `detect_winners` / `detect_failures`.

**Рекомендации никогда не применяются автоматически** — стратегию меняет клиент.

## 7. Как меняется генерация постов

`LearningContextBuilder.build_context(project_id)` собирает безопасный контекст
(preferred форматы/тон/темы/запрещённые темы/CTA). Он передаётся в
`PostGenerationService.generate_post_from_topic_object(..., learning_context=...)`
как **опциональный** параметр: при наличии — мягко подсказывает формат/CTA и помечает
`generation_notes.learning_context_applied`. При `None` (все существующие вызовы)
поведение генератора **не меняется**. Сам генератор не переписан.

## 8. API (под project-guard, все требуют авторизации)

- `GET  /projects/{id}/learning` — профиль (что AI понял);
- `POST /projects/{id}/learning/analyze` — запустить анализ + пересчёт;
- `GET  /projects/{id}/learning/recommendations` — next_content + strategy;
- `GET  /projects/{id}/learning/explanation` — объяснение для клиента;
- `POST /projects/{id}/learning/feedback` — клиентский фидбэк по посту;
- `POST /projects/{id}/learning/reset` — сброс агрегатов (история сигналов сохраняется).

UI: `/ui/projects/{id}/ai-learning` — «AI обучение вашего бренда» (существующий
`/ui/projects/{id}/learning` — это отдельный, более ранний экран «Чему бот научился»).

CLI: `make ai-learning-profile|ai-learning-analyze|ai-learning-recommend project_id=1`.

## 9. Feedback loop

Публикация → метрики/фидбэк → события → пересчёт профиля → рекомендации/контекст →
следующая публикация. Цикл замкнут, но безопасно: каждый шаг только читает аналитику и
пишет свой профиль/события.

## 10. Безопасность (жёсткие инварианты, покрыты тестами)

- обучение **НЕ публикует** и **НЕ вызывает** внешние API;
- обучение **НЕ включает** и **НЕ меняет** глобальные `*_LIVE_PUBLISHING_ENABLED`;
- обучение **НЕ меняет стратегию автоматически** (`ai_learning_auto_apply_strategy_enabled`
  по умолчанию `false`) — только рекомендации;
- каждое изменение профиля пишется в **AuditLog**;
- **reset не удаляет** историю сигналов;
- секретов/токенов не хранит (`event_metadata` санитизируется, публичные представления
  метаданные наружу не отдают);
- данные строго per-project — не смешиваются между клиентами;
- обучение **бесплатно** (0 units).

Конфиг: `ai_learning_enabled` (kill-switch, default true),
`ai_learning_auto_apply_strategy_enabled` (default false),
`ai_learning_default_window_days` (90), `ai_learning_min_events_for_stable` (20).
