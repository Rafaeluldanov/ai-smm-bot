"""Тонкий сервис безопасного прогона проекта из SaaS-кабинета с биллингом.

Переиспользует :class:`CrmBotSmmApplicationService` (dry/semi_auto прогон категории),
добавляя учёт units:
- dry-run: только оценка стоимости, БЕЗ списания и без создания постов;
- semi_auto: проверка баланса → прогон (посты уходят на ревью) → списание за
  фактически сгенерированные посты.

Живые публикации НЕ выполняются ни в каком режиме (унаследовано от CRM-прогона).
"""

from sqlalchemy.orm import Session

from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories import project_repository
from app.schemas.saas_onboarding import SaasBotRunResult
from app.services.billing_service import (
    ACTION_COSTS,
    BillingService,
    InsufficientBalanceError,
)
from app.services.crm_bot_smm_application_service import CrmBotSmmApplicationService

_GENERATION_EVENT = "ai_generation"


class SaasBotRunError(Exception):
    """Ошибка запуска прогона (проект/категория не найдены или не совпадают)."""


class SaasBotRunService:
    """Безопасный прогон проекта (dry/semi-auto) с оценкой и списанием units."""

    def __init__(
        self,
        billing_service: BillingService,
        crm_application_service: CrmBotSmmApplicationService,
    ) -> None:
        self._billing = billing_service
        self._crm_app = crm_application_service

    def run_project_dry_preview(
        self, db: Session, account_id: int, project_id: int, category_id: int
    ) -> SaasBotRunResult:
        """Dry-run: оценка стоимости без списания и без создания постов."""
        self._verify_ownership(db, account_id, project_id, category_id)
        preview = self._crm_app.preview_category_run(db, category_id)
        estimated = self._estimate_units(preview.posts_per_week)
        billing = self._billing.get_balance(db, account_id)
        return SaasBotRunResult(
            account_id=account_id,
            project_id=project_id,
            category_id=category_id,
            dry_run=True,
            estimated_units=estimated,
            debited_units=0,
            balance_units=billing.balance_units,
            warnings=["dry-run: посты не создаются, units не списываются."],
            safety=list(preview.safety),
        )

    def run_project_semi_auto(
        self, db: Session, account_id: int, project_id: int, category_id: int
    ) -> SaasBotRunResult:
        """Semi-auto: проверка баланса → прогон → списание за созданные посты.

        Публикаций нет (посты уходят на ревью). Если баланса не хватает на оценку —
        прогон НЕ запускается (:class:`InsufficientBalanceError`).
        """
        self._verify_ownership(db, account_id, project_id, category_id)
        preview = self._crm_app.preview_category_run(db, category_id)
        estimated = self._estimate_units(preview.posts_per_week)

        billing = self._billing.get_balance(db, account_id)
        if billing.balance_units < estimated:
            raise InsufficientBalanceError(estimated, billing.balance_units)

        result = self._crm_app.run_category_semi_auto(db, category_id, dry_run=False)

        # Списываем пропорционально фактически созданным постам (0 постов → 0 units),
        # но не больше зарезервированной оценки.
        actual = min(ACTION_COSTS[_GENERATION_EVENT] * max(0, result.generated_posts), estimated)
        debited = 0
        if actual > 0:
            self._billing.reserve_or_debit(
                db,
                account_id,
                _GENERATION_EVENT,
                actual,
                metadata={"category_id": category_id, "run_id": result.run_id},
                project_id=project_id,
                idempotency_key=f"saas-run-{result.run_id}",
            )
            debited = actual
        balance = self._billing.get_balance(db, account_id).balance_units

        return SaasBotRunResult(
            account_id=account_id,
            project_id=project_id,
            category_id=category_id,
            dry_run=False,
            estimated_units=estimated,
            debited_units=debited,
            balance_units=balance,
            generated_posts=result.generated_posts,
            submitted_for_review=result.submitted_for_review,
            published_publications=result.published_publications,
            warnings=list(result.warnings),
            safety=list(result.safety),
        )

    # --- Внутреннее ---

    @staticmethod
    def _estimate_units(post_count: int) -> int:
        return ACTION_COSTS[_GENERATION_EVENT] * max(1, int(post_count))

    def _verify_ownership(
        self, db: Session, account_id: int, project_id: int, category_id: int
    ) -> None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise SaasBotRunError(f"Проект id={project_id} не найден")
        if project.account_id != account_id:
            raise SaasBotRunError(f"Проект id={project_id} не принадлежит аккаунту id={account_id}")
        category = crm_repo.get_category_by_id(db, category_id)
        if category is None:
            raise SaasBotRunError(f"Категория id={category_id} не найдена")
        if category.project_id != project_id:
            raise SaasBotRunError(f"Категория id={category_id} относится к другому проекту")
