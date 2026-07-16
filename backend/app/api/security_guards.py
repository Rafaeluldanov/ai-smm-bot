"""HTTP-гарды tenant-изоляции для FastAPI-роутов (аккаунт/проект/счёт/платформа).

Двухуровневая модель (безопасная и обратно совместимая):
- **Аутентифицированный** запрос — доступ проверяется строго: пользователь должен быть
  владельцем/участником аккаунта ресурса, иначе **404** (существование чужих ресурсов не
  раскрывается). Роли owner/admin требуются для изменения billing-профиля и т. п.
- **Анонимный** запрос — допускается только вне production (dev/local), где сохраняется
  back-compat для существующих тестов и локальной разработки. В production (или при
  ``security_require_auth=true``) анонимный доступ к защищённым роутам → **401**.

Секреты здесь не участвуют — гарды только сверяют владение. Вебхуки провайдеров НЕ
используют эти гарды (проверяются подписью/идемпотентностью, не токеном пользователя).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_optional_user
from app.config import Settings, get_settings
from app.models.account import Account
from app.models.user import User
from app.repositories import (
    account_repository,
    content_experiment_repository,
    crm_bot_smm_repository,
    experiment_suggestion_repository,
    media_curation_repository,
    media_duplicate_cluster_repository,
    media_fingerprint_repository,
    media_quality_repository,
    payment_repository,
    post_publication_repository,
    post_repository,
    project_repository,
    schedule_media_decision_repository,
    schedule_topic_decision_repository,
)
from app.services import saas_security_service as security

DbSession = Annotated[Session, Depends(get_db)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
_AUTH_REQUIRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация"
)


def _auth_required(settings: Settings) -> bool:
    """Требовать ли авторизацию на защищённых роутах (prod — всегда)."""
    return settings.is_production or settings.security_require_auth


def _account_role(db: Session, user: User, account: Account) -> str | None:
    if account.owner_user_id == user.id:
        return "owner"
    membership = account_repository.get_membership(db, account.id, user.id)
    return membership.role if membership is not None else None


def _guard_account(
    db: Session, settings: Settings, user: User | None, account_id: int, *, need_admin: bool = False
) -> None:
    """Проверить доступ к аккаунту (или права owner/admin) с учётом двух уровней."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return  # dev/local анонимно — back-compat
    account = account_repository.get_account_by_id(db, account_id)
    if account is None or not security.user_can_access_account(db, user, account_id):
        raise _NOT_FOUND
    if account.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт неактивен")
    if need_admin and _account_role(db, user, account) not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права владельца или администратора аккаунта",
        )


def _guard_project(db: Session, settings: Settings, user: User | None, project_id: int) -> None:
    """Проверить доступ к проекту (в т. ч. legacy-проекты без account_id)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return  # dev/local анонимно — back-compat
    project = project_repository.get_project_by_id(db, project_id)
    if project is None:
        raise _NOT_FOUND
    if project.account_id is None:
        # Legacy/seed-проект: в production скрываем, в dev — доступен.
        if settings.is_production and settings.security_hide_legacy_projects_in_prod:
            raise _NOT_FOUND
        return
    if not security.user_can_access_account(db, user, project.account_id):
        raise _NOT_FOUND


# --- Публичные guard-зависимости (используются в маршрутах) --- #


def require_account_member(
    account_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к аккаунту только участнику/владельцу (или dev-анонимно)."""
    _guard_account(db, settings, user, account_id)


def require_account_owner_or_admin(
    account_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: только owner/admin аккаунта (billing-профиль, опасные действия)."""
    _guard_account(db, settings, user, account_id, need_admin=True)


def require_project_access(
    project_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к проекту только участнику его аккаунта (или dev-анонимно)."""
    _guard_project(db, settings, user, project_id)


def require_project_platform_access(
    project_id: int, platform: str, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард платформенного воркспейса: доступ к проекту (платформа — из его конфига)."""
    _guard_project(db, settings, user, project_id)


def require_invoice_access(
    invoice_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: счёт принадлежит аккаунту текущего пользователя."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    invoice = payment_repository.get_invoice(db, invoice_id)
    if invoice is None or not security.user_can_access_account(db, user, invoice.account_id):
        raise _NOT_FOUND


def require_post_access(
    post_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к посту (через проект → аккаунт) для аналитики."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    post = post_repository.get_post_by_id(db, post_id)
    if post is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, post.project_id)


def require_publication_access(
    publication_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к публикации (через пост → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    publication = post_publication_repository.get_publication_by_id(db, publication_id)
    if publication is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, publication.project_id)


def require_campaign_access(
    campaign_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к AI-кампании (через кампанию → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import ai_campaign_repository

    campaign = ai_campaign_repository.get_campaign(db, campaign_id)
    if campaign is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, campaign.project_id)


def require_action_access(
    action_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к бизнес-действию Executive Layer (через действие → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import business_os_repository

    action = business_os_repository.get_action(db, action_id)
    if action is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, action.project_id)


def require_ai_decision_access(
    decision_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к AI-решению Decision Engine (через решение → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import decision_repository

    decision = decision_repository.get_decision(db, decision_id)
    if decision is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, decision.project_id)


def require_decision_scenario_access(
    scenario_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к сценарию решения (через сценарий → решение → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import decision_repository

    scenario = decision_repository.get_scenario(db, scenario_id)
    if scenario is None:
        raise _NOT_FOUND
    decision = decision_repository.get_decision(db, scenario.decision_id)
    if decision is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, decision.project_id)


def require_simulation_access(
    simulation_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к стратегической симуляции (через симуляцию → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import strategy_simulation_repository

    simulation = strategy_simulation_repository.get_simulation(db, simulation_id)
    if simulation is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, simulation.project_id)


def require_forecast_access(
    forecast_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к прогнозу бизнеса (через прогноз → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import business_forecast_repository

    forecast = business_forecast_repository.get_forecast(db, forecast_id)
    if forecast is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, forecast.project_id)


def require_goal_access(
    goal_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к бизнес-цели Business Planner (через цель → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import business_planner_repository

    goal = business_planner_repository.get_goal(db, goal_id)
    if goal is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, goal.project_id)


def require_plan_access(
    plan_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к стратегическому плану (через план → цель → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import business_planner_repository

    plan = business_planner_repository.get_plan(db, plan_id)
    if plan is None:
        raise _NOT_FOUND
    goal = business_planner_repository.get_goal(db, plan.goal_id)
    if goal is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, goal.project_id)


def require_execution_plan_access(
    execution_plan_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к плану исполнения (через план → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import execution_repository

    plan = execution_repository.get_execution_plan(db, execution_plan_id)
    if plan is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, plan.project_id)


def require_execution_task_access(
    task_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к задаче исполнения (через задачу → цель → план → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import execution_repository

    task = execution_repository.get_task(db, task_id)
    if task is None:
        raise _NOT_FOUND
    objective = execution_repository.get_objective(db, task.objective_id)
    if objective is None:
        raise _NOT_FOUND
    plan = execution_repository.get_execution_plan(db, objective.execution_plan_id)
    if plan is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, plan.project_id)


def require_performance_snapshot_access(
    snapshot_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к снимку эффективности (через снимок → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import performance_repository

    snapshot = performance_repository.get_snapshot(db, snapshot_id)
    if snapshot is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, snapshot.project_id)


def require_improvement_access(
    improvement_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к улучшению Continuous Improvement (через улучшение → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import continuous_improvement_repository

    improvement = continuous_improvement_repository.get_improvement(db, improvement_id)
    if improvement is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, improvement.project_id)


def require_operations_risk_access(
    risk_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к операционному риску (через риск → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import operations_repository

    risk = operations_repository.get_risk(db, risk_id)
    if risk is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, risk.project_id)


def require_operations_recommendation_access(
    recommendation_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к операционной рекомендации (через рекомендацию → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import operations_repository

    recommendation = operations_repository.get_recommendation(db, recommendation_id)
    if recommendation is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, recommendation.project_id)


def require_workflow_access(
    workflow_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к бизнес-процессу Workflow Manager (через процесс → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import workflow_repository

    workflow = workflow_repository.get_workflow(db, workflow_id)
    if workflow is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, workflow.project_id)


def require_workflow_step_access(
    step_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к этапу процесса (через этап → процесс → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import workflow_repository

    step = workflow_repository.get_step(db, step_id)
    if step is None:
        raise _NOT_FOUND
    workflow = workflow_repository.get_workflow(db, step.workflow_id)
    if workflow is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, workflow.project_id)


def require_workflow_blocker_access(
    blocker_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к блокеру процесса (через блокер → процесс → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import workflow_repository

    blocker = workflow_repository.get_blocker(db, blocker_id)
    if blocker is None:
        raise _NOT_FOUND
    workflow = workflow_repository.get_workflow(db, blocker.workflow_id)
    if workflow is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, workflow.project_id)


def require_task_access(
    task_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к задаче владельца Chief of Staff (через задачу → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import chief_of_staff_repository

    task = chief_of_staff_repository.get_task(db, task_id)
    if task is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, task.project_id)


def require_decision_access(
    decision_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к решению владельца Chief of Staff (через решение → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import chief_of_staff_repository

    decision = chief_of_staff_repository.get_decision(db, decision_id)
    if decision is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, decision.project_id)


def require_live_attempt_access(
    attempt_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к попытке live-публикации (через её проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import live_publish_attempt_repository

    attempt = live_publish_attempt_repository.get_attempt_by_id(db, attempt_id)
    if attempt is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, attempt.project_id)


def require_live_incident_access(
    incident_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к инциденту автопилота (через его проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import live_autopilot_monitoring_repository

    incident = live_autopilot_monitoring_repository.get_incident_by_id(db, incident_id)
    if incident is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, incident.project_id)


def require_media_proxy_token_access(
    token_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к токену media-proxy (через его проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    from app.repositories import media_proxy_repository

    token = media_proxy_repository.get_token_by_id(db, token_id)
    if token is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, token.project_id)


def require_experiment_access(
    experiment_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к эксперименту (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    experiment = content_experiment_repository.get_experiment_by_id(db, experiment_id)
    if experiment is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, experiment.project_id)


def require_variant_access(
    variant_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к варианту эксперимента (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    variant = content_experiment_repository.get_variant_by_id(db, variant_id)
    if variant is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, variant.project_id)


def require_suggestion_access(
    suggestion_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к предложению эксперимента (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    suggestion = experiment_suggestion_repository.get_by_id(db, suggestion_id)
    if suggestion is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, suggestion.project_id)


def require_topic_decision_access(
    decision_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к решению о теме (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    decision = schedule_topic_decision_repository.get_by_id(db, decision_id)
    if decision is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, decision.project_id)


def require_media_decision_access(
    decision_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к решению о медиа (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    decision = schedule_media_decision_repository.get_by_id(db, decision_id)
    if decision is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, decision.project_id)


def require_media_quality_access(
    snapshot_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к снимку качества медиа (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    snapshot = media_quality_repository.get_by_id(db, snapshot_id)
    if snapshot is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, snapshot.project_id)


def require_media_fingerprint_access(
    fingerprint_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к fingerprint медиа (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    fingerprint = media_fingerprint_repository.get_by_id(db, fingerprint_id)
    if fingerprint is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, fingerprint.project_id)


def require_media_cluster_access(
    cluster_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к кластеру дублей медиа (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    cluster = media_duplicate_cluster_repository.get_by_id(db, cluster_id)
    if cluster is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, cluster.project_id)


def require_media_curation_task_access(
    task_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к задаче курирования (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    task = media_curation_repository.get_task_by_id(db, task_id)
    if task is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, task.project_id)


def require_vk_resource_access(
    resource_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: VK-ресурс принадлежит проекту/аккаунту пользователя (status/check)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    resource = crm_bot_smm_repository.get_resource_by_id(db, resource_id)
    if resource is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, resource.project_id)


def guard_account_in_body(
    db: Session, settings: Settings, user: User | None, account_id: int
) -> None:
    """In-route гард для роутов с account_id в теле запроса (onboarding/analytics run)."""
    _guard_account(db, settings, user, account_id)


def guard_project_in_body(
    db: Session, settings: Settings, user: User | None, project_id: int
) -> None:
    """In-route гард для роутов с project_id в теле запроса."""
    _guard_project(db, settings, user, project_id)
