"""Репозиторий контент-экспериментов и их вариантов (v0.4.2).

Секретов в metadata нет (обеспечивает сервисный слой). Изоляция project/account —
на API/сервисном слое. Все выборки фильтруют по ``project_id``.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content_experiment import ContentExperiment
from app.models.content_experiment_variant import ContentExperimentVariant

# --- Эксперименты ---


def create_experiment(db: Session, **fields: Any) -> ContentExperiment:
    """Создать эксперимент."""
    experiment = ContentExperiment(**fields)
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return experiment


def get_experiment_by_id(db: Session, experiment_id: int) -> ContentExperiment | None:
    """Эксперимент по id (или None)."""
    return db.get(ContentExperiment, experiment_id)


def list_experiments_for_project(
    db: Session,
    project_id: int,
    platform_key: str | None = None,
    status: str | None = None,
    experiment_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ContentExperiment]:
    """Эксперименты проекта (свежие первыми) с фильтрами."""
    stmt = select(ContentExperiment).where(ContentExperiment.project_id == project_id)
    if platform_key is not None:
        stmt = stmt.where(ContentExperiment.platform_key == platform_key)
    if status is not None:
        stmt = stmt.where(ContentExperiment.status == status)
    if experiment_type is not None:
        stmt = stmt.where(ContentExperiment.experiment_type == experiment_type)
    stmt = stmt.order_by(ContentExperiment.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def update_experiment(
    db: Session, experiment: ContentExperiment, **fields: Any
) -> ContentExperiment:
    """Обновить поля эксперимента."""
    for field, value in fields.items():
        setattr(experiment, field, value)
    db.commit()
    db.refresh(experiment)
    return experiment


def complete_experiment(
    db: Session,
    experiment: ContentExperiment,
    winner_variant_id: int | None,
    confidence_score: float,
    completed_at: Any,
    learning_profile_version: int | None = None,
) -> ContentExperiment:
    """Отметить эксперимент завершённым с winner."""
    return update_experiment(
        db,
        experiment,
        status="completed",
        winner_variant_id=winner_variant_id,
        confidence_score=confidence_score,
        completed_at=completed_at,
        learning_profile_version=learning_profile_version,
    )


def cancel_experiment(db: Session, experiment: ContentExperiment) -> ContentExperiment:
    """Отменить эксперимент."""
    return update_experiment(db, experiment, status="canceled")


def get_experiment_for_post(db: Session, post_id: int) -> ContentExperiment | None:
    """Эксперимент, к которому относится пост (через вариант)."""
    variant = get_variant_for_post(db, post_id)
    if variant is None:
        return None
    return get_experiment_by_id(db, variant.experiment_id)


def list_active_experiments(db: Session, project_id: int) -> list[ContentExperiment]:
    """Активные эксперименты проекта (active / waiting_metrics)."""
    stmt = (
        select(ContentExperiment)
        .where(
            ContentExperiment.project_id == project_id,
            ContentExperiment.status.in_(("active", "waiting_metrics")),
        )
        .order_by(ContentExperiment.id.desc())
    )
    return list(db.scalars(stmt).all())


# --- Варианты ---


def create_variant(db: Session, **fields: Any) -> ContentExperimentVariant:
    """Создать вариант эксперимента."""
    variant = ContentExperimentVariant(**fields)
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


def get_variant_by_id(db: Session, variant_id: int) -> ContentExperimentVariant | None:
    """Вариант по id (или None)."""
    return db.get(ContentExperimentVariant, variant_id)


def list_variants_for_experiment(db: Session, experiment_id: int) -> list[ContentExperimentVariant]:
    """Варианты эксперимента (по variant_key A→B→C)."""
    stmt = (
        select(ContentExperimentVariant)
        .where(ContentExperimentVariant.experiment_id == experiment_id)
        .order_by(ContentExperimentVariant.variant_key, ContentExperimentVariant.id)
    )
    return list(db.scalars(stmt).all())


def update_variant(
    db: Session, variant: ContentExperimentVariant, **fields: Any
) -> ContentExperimentVariant:
    """Обновить поля варианта."""
    for field, value in fields.items():
        setattr(variant, field, value)
    db.commit()
    db.refresh(variant)
    return variant


def mark_winner(
    db: Session, variant: ContentExperimentVariant, winner_reason: str
) -> ContentExperimentVariant:
    """Отметить вариант победителем."""
    return update_variant(db, variant, is_winner=True, status="winner", winner_reason=winner_reason)


def list_winners_for_project(
    db: Session, project_id: int, limit: int = 50
) -> list[ContentExperimentVariant]:
    """Варианты-победители проекта (свежие первыми)."""
    stmt = (
        select(ContentExperimentVariant)
        .where(
            ContentExperimentVariant.project_id == project_id,
            ContentExperimentVariant.is_winner.is_(True),
        )
        .order_by(ContentExperimentVariant.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_variant_for_post(db: Session, post_id: int) -> ContentExperimentVariant | None:
    """Вариант, связанный с постом (или None)."""
    stmt = (
        select(ContentExperimentVariant)
        .where(ContentExperimentVariant.post_id == post_id)
        .order_by(ContentExperimentVariant.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_variant_for_publication(
    db: Session, publication_id: int
) -> ContentExperimentVariant | None:
    """Вариант, связанный с публикацией (или None)."""
    stmt = (
        select(ContentExperimentVariant)
        .where(ContentExperimentVariant.publication_id == publication_id)
        .order_by(ContentExperimentVariant.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()
