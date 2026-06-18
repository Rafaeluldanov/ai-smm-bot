"""Safety-guardrails автономного режима (Этап 10).

Определяет, что разрешено автоматизировать в каждом режиме, и проверяет, можно ли
авто-одобрить/запланировать/опубликовать конкретный пост. Главные принципы:
человек по умолчанию в контуре (require_human_review), внешние стоки и посты без
медиа не уходят в авто-одобрение/публикацию, реальные публикации требуют явного
``allow_auto_publish``.

Чистый сервис: без сети и AI.
"""

from app.models.media_asset import MediaAsset
from app.models.post import Post
from app.schemas.autonomous import (
    AutonomousModeSettings,
    AutonomousRunRequest,
    AutonomousSafetyReport,
)

ALLOWED_MODES: list[str] = [
    "dry_run",
    "semi_auto",
    "auto_generate",
    "auto_schedule",
    "auto_publish",
]

# Потолок возможностей режима: (approve, schedule, publish).
_MODE_CAPS: dict[str, tuple[bool, bool, bool]] = {
    "dry_run": (False, False, False),
    "semi_auto": (False, False, False),
    "auto_generate": (True, False, False),
    "auto_schedule": (True, True, False),
    "auto_publish": (True, True, True),
}

# Статусы поста, из которых пост можно авто-одобрить.
_APPROVABLE_FROM: set[str] = {"draft", "needs_review"}
# Лицензии внешних стоков, требующие ручной проверки перед одобрением.
_BLOCKED_LICENSES: set[str] = {"external_needs_review", "needs_review", "needs_license_review"}


class AutonomousSafetyService:
    """Правила безопасности автономного прогона."""

    def get_mode_settings(
        self, mode: str, settings: AutonomousModeSettings | None
    ) -> AutonomousModeSettings:
        """Вывести эффективные настройки: возможности режима ∩ явные настройки."""
        base = settings.model_copy() if settings is not None else AutonomousModeSettings()
        approve_cap, schedule_cap, publish_cap = _MODE_CAPS.get(mode, (False, False, False))

        require_human_review = base.require_human_review
        if mode in {"dry_run", "semi_auto"}:
            require_human_review = True

        effective = base.model_copy()
        effective.dry_run = base.dry_run or mode == "dry_run"
        effective.require_human_review = require_human_review
        effective.allow_auto_approve = (
            approve_cap and base.allow_auto_approve and not require_human_review
        )
        effective.allow_auto_schedule = schedule_cap and base.allow_auto_schedule
        effective.allow_auto_publish = publish_cap and base.allow_auto_publish
        return effective

    def validate_request(self, request: AutonomousRunRequest) -> AutonomousSafetyReport:
        """Проверить запрос и вернуть эффективные настройки."""
        errors: list[str] = []
        warnings: list[str] = []

        if request.mode not in ALLOWED_MODES:
            errors.append(f"Неизвестный режим: '{request.mode}'")
        if request.weeks < 1:
            errors.append("weeks должен быть >= 1")
        if request.posts_per_week < 1:
            errors.append("posts_per_week должен быть >= 1")
        if request.project_id is None and not request.project_slug:
            errors.append("Нужен project_id или project_slug")

        effective = self.get_mode_settings(
            request.mode if request.mode in ALLOWED_MODES else "semi_auto", request.settings
        )
        if effective.allow_auto_publish:
            warnings.append("Включена авто-публикация — посты будут опубликованы без ручного ревью")

        return AutonomousSafetyReport(
            allowed=not errors, warnings=warnings, errors=errors, effective_settings=effective
        )

    def can_auto_approve(
        self, post: Post, media_asset: MediaAsset | None = None
    ) -> tuple[bool, list[str]]:
        """Можно ли авто-одобрить пост (и почему нет)."""
        reasons: list[str] = []
        if post.status == "needs_media":
            reasons.append("Пост без медиа (needs_media) нельзя авто-одобрять")
        elif post.status not in _APPROVABLE_FROM:
            reasons.append(f"Статус '{post.status}' не допускает авто-одобрение")
        if media_asset is not None and media_asset.source_type == "external_stock":
            license_type = media_asset.license_type or ""
            if license_type in _BLOCKED_LICENSES or media_asset.status == "needs_license_review":
                reasons.append("Внешний сток требует ручной проверки лицензии")
        return (len(reasons) == 0), reasons

    def can_auto_schedule(self, post: Post) -> tuple[bool, list[str]]:
        """Можно ли авто-запланировать пост (только approved)."""
        reasons: list[str] = []
        if post.status == "needs_media":
            reasons.append("Пост без медиа (needs_media) нельзя планировать")
        elif post.status != "approved":
            reasons.append(f"Планировать можно только approved-посты (текущий: '{post.status}')")
        return (len(reasons) == 0), reasons

    def can_auto_publish(self, post: Post) -> tuple[bool, list[str]]:
        """Можно ли авто-опубликовать пост (approved/scheduled)."""
        reasons: list[str] = []
        if post.status not in {"approved", "scheduled"}:
            reasons.append(
                f"Публиковать можно только approved/scheduled (текущий: '{post.status}')"
            )
        return (len(reasons) == 0), reasons
