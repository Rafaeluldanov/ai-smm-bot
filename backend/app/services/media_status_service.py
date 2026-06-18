"""Сервис статусов медиа и безопасных переходов между ними.

Статусы отражают жизненный цикл медиафайла: от обнаружения до использования
в посте. Переходы ограничены, чтобы нельзя было, например, сразу пометить
непроверенную внешнюю картинку как использованную.
"""

from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.repositories import media_asset_repository
from app.repositories.media_asset_repository import MediaAssetNotFoundError

# Допустимые статусы медиа.
ALLOWED_STATUSES: list[str] = [
    "new",
    "approved",
    "approved_video",
    "needs_license_review",
    "rejected",
    "needs_reshoot",
    "used",
]

# Разрешённые переходы: из статуса -> множество статусов.
_TRANSITIONS: dict[str, set[str]] = {
    "new": {"approved", "approved_video", "needs_license_review", "rejected", "needs_reshoot"},
    "approved": {"used", "rejected", "needs_reshoot"},
    "approved_video": {"used", "rejected", "needs_reshoot"},
    "needs_license_review": {"approved", "rejected"},
    "needs_reshoot": {"approved", "rejected"},
    "used": {"approved", "approved_video"},
    "rejected": {"approved", "needs_reshoot"},
}


class InvalidMediaStatusError(Exception):
    """Передан неизвестный статус медиа."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Неизвестный статус медиа: '{status}'")


class InvalidMediaStatusTransitionError(Exception):
    """Переход между статусами запрещён."""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Недопустимый переход статуса: '{from_status}' -> '{to_status}'")


class MediaStatusService:
    """Правила статусов и переходов медиа."""

    def get_allowed_statuses(self) -> list[str]:
        """Вернуть список допустимых статусов."""
        return list(ALLOWED_STATUSES)

    def can_transition(self, from_status: str, to_status: str) -> bool:
        """Разрешён ли переход (без выброса исключения)."""
        if from_status not in ALLOWED_STATUSES or to_status not in ALLOWED_STATUSES:
            return False
        return to_status in _TRANSITIONS.get(from_status, set())

    def validate_transition(self, from_status: str, to_status: str) -> None:
        """Проверить переход, бросив понятную ошибку при нарушении."""
        if from_status not in ALLOWED_STATUSES:
            raise InvalidMediaStatusError(from_status)
        if to_status not in ALLOWED_STATUSES:
            raise InvalidMediaStatusError(to_status)
        if to_status not in _TRANSITIONS.get(from_status, set()):
            raise InvalidMediaStatusTransitionError(from_status, to_status)

    def update_media_status(self, db: Session, media_asset_id: int, new_status: str) -> MediaAsset:
        """Сменить статус медиа с проверкой допустимости перехода.

        Порядок проверок: неизвестный статус → InvalidMediaStatusError;
        нет актива → MediaAssetNotFoundError; запрещённый переход →
        InvalidMediaStatusTransitionError.
        """
        if new_status not in ALLOWED_STATUSES:
            raise InvalidMediaStatusError(new_status)

        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None:
            raise MediaAssetNotFoundError(media_asset_id)

        self.validate_transition(asset.status, new_status)
        return media_asset_repository.update_media_asset_status(db, asset, new_status)
