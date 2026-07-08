"""Клиент YouTube: безопасный adapter-скелет публикации видео/shorts.

``YouTubePublishingClient`` реализует протокол ``PublishingClient`` и участвует в
dry-run/preview (какое видео ушло бы — по capability-слою). LIVE-публикация на этом
этапе НЕ реализована: при ``live_enabled=True`` и заданном токене метод бросает
понятную ошибку. Реальная загрузка через YouTube Data API добавляется отдельным
этапом после проверки офиц. документации и безопасной реализации.

Токен (``YOUTUBE_ACCESS_TOKEN``) НИКОГДА не логируется и не попадает в ошибки —
клиент не обращается к сети на этом этапе.
"""

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse


class YouTubePublishingClient:
    """Безопасный adapter YouTube: preview работает, live пока не реализован."""

    platform = "youtube"
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
            raise PublishError("youtube", "Live publishing disabled by config")
        if not self._token:
            raise PublishError("youtube", "YOUTUBE_ACCESS_TOKEN не задан — публикация недоступна")
        raise PublishError("youtube", "Live publishing for youtube is not implemented yet")
