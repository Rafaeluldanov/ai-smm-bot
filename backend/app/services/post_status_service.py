"""Статусы поста и безопасные переходы между ними.

Статусы отражают жизненный цикл поста: от черновика до публикации. Переходы
ограничены, чтобы нельзя было, например, опубликовать пост в обход согласования
или вернуть опубликованный пост сразу в черновик. Согласование (Этап 6) и
публикация (Этап 7) будут опираться на эти же правила.

Модуль чистый: без БД, сети и AI — только данные и функции.
"""

# Допустимые статусы поста.
#
# ``changes_requested`` и ``failed`` добавлены в v0.4.0 (review/approval workflow):
# - ``changes_requested`` — клиент в очереди ревью запросил доработку (полуавтомат);
# - ``failed`` — попытка публикации (в т. ч. авто) завершилась ошибкой.
ALLOWED_POST_STATUSES: list[str] = [
    "draft",
    "needs_review",
    "changes_requested",
    "approved",
    "scheduled",
    "published",
    "rejected",
    "needs_media",
    "failed",
]

# Разрешённые переходы: из статуса -> множество статусов.
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"needs_review", "approved", "rejected", "needs_media"},
    "needs_media": {"draft", "needs_review", "rejected"},
    "needs_review": {"approved", "rejected", "draft", "changes_requested"},
    "changes_requested": {"draft", "needs_review", "approved", "rejected"},
    "approved": {"scheduled", "published", "rejected", "draft", "changes_requested", "failed"},
    "scheduled": {"published", "approved", "rejected", "failed"},
    "published": {"approved"},
    "rejected": {"draft"},
    "failed": {"draft", "needs_review", "approved"},
}


class InvalidPostStatusError(Exception):
    """Передан неизвестный статус поста."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Неизвестный статус поста: '{status}'")


class InvalidPostStatusTransitionError(Exception):
    """Переход между статусами поста запрещён."""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Недопустимый переход статуса: '{from_status}' -> '{to_status}'")


def get_allowed_post_statuses() -> list[str]:
    """Вернуть список допустимых статусов поста."""
    return list(ALLOWED_POST_STATUSES)


def can_transition(from_status: str, to_status: str) -> bool:
    """Разрешён ли переход (без выброса исключения)."""
    if from_status not in ALLOWED_POST_STATUSES or to_status not in ALLOWED_POST_STATUSES:
        return False
    return to_status in _TRANSITIONS.get(from_status, set())


def validate_transition(from_status: str, to_status: str) -> None:
    """Проверить переход, бросив понятную ошибку при нарушении.

    Порядок проверок: неизвестный статус → InvalidPostStatusError;
    запрещённый переход → InvalidPostStatusTransitionError.
    """
    if from_status not in ALLOWED_POST_STATUSES:
        raise InvalidPostStatusError(from_status)
    if to_status not in ALLOWED_POST_STATUSES:
        raise InvalidPostStatusError(to_status)
    if to_status not in _TRANSITIONS.get(from_status, set()):
        raise InvalidPostStatusTransitionError(from_status, to_status)
