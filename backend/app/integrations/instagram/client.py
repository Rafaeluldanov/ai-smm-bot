"""Клиент Instagram: заглушка + безопасный adapter-скелет публикации.

``InstagramPublishingClient`` реализует протокол ``PublishingClient`` и участвует в
dry-run/preview через ``PostPublicationService`` (какие медиа ушли бы: фото/carousel/
reels — по capability-слою). LIVE-публикация на этом этапе НЕ реализована: при
``live_enabled=True`` и заданном токене метод бросает понятную ошибку. Реальные
вызовы Instagram Graph API добавляются отдельным этапом после проверки офиц.
документации и безопасной реализации.

Токен (``INSTAGRAM_ACCESS_TOKEN``) НИКОГДА не логируется и не попадает в ошибки —
клиент вообще не обращается к сети на этом этапе.
"""

from typing import Any

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с Instagram запланирована на Этап 7+"


class InstagramClient:
    """Доступ к Instagram Graph API (низкоуровневая заглушка)."""

    def __init__(self, token: str) -> None:
        self._token = token

    def publish_post(self, account_id: int | str, caption: str, media_path: str) -> Any:
        """Опубликовать медиа с подписью."""
        raise NotImplementedError(_STAGE)


class InstagramPublishingClient:
    """Безопасный adapter Instagram: preview работает, live пока не реализован.

    Порядок проверок в ``publish_post``: сначала live-флаг (без флага — ошибка без
    сети), затем токен, затем явная ошибка «live не реализован». Сеть не трогается.
    """

    platform = "instagram"
    # live-публикация ещё не реализована (для preview/диагностики).
    live_implemented = False

    def __init__(
        self,
        token: str | None = None,
        default_target_id: str | None = None,
        *,
        live_enabled: bool = False,
    ) -> None:
        self._token = token
        self._default_target_id = default_target_id
        self.live_enabled = live_enabled

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Live не реализован. Без ``live_enabled`` — ошибка без сети; токен не в тексте."""
        if not self.live_enabled:
            raise PublishError("instagram", "Live publishing disabled by config")
        if not self._token:
            raise PublishError(
                "instagram", "INSTAGRAM_ACCESS_TOKEN не задан — публикация недоступна"
            )
        raise PublishError("instagram", "Live publishing for instagram is not implemented yet")
