"""Единый слой возможностей платформ публикации (Yandex Disk media → platform).

Здесь описано, какие типы медиа принимает каждая SMM-платформа (текст, фото,
альбом фото, видео, группа видео), лимиты и имя live-флага. На основе этих
возможностей ``route_media`` решает, что именно уйдёт на платформу и какие
предупреждения показать в dry-run — без обращения к сети и без публикации.

Добавление новой платформы = одна запись в ``build_platform_capabilities`` и
клиент, реализующий ``PublishingClient``. Конкретные клиенты не содержат
capability-логики — только транспорт.
"""

from dataclasses import dataclass, field
from functools import lru_cache

from app.config import Settings, get_settings


@dataclass(slots=True)
class PlatformCapabilities:
    """Возможности одной платформы публикации."""

    platform: str
    supports_text: bool
    supports_image: bool
    supports_image_group: bool
    supports_video: bool
    supports_video_group: bool
    max_images: int
    max_videos: int
    max_text_length: int | None
    live_flag_name: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MediaRoutingDecision:
    """Решение о том, что уйдёт на платформу для данного набора медиа."""

    would_attach_media: bool
    # image_group | image | video_group | video | none
    selected_media_kind: str
    selected_count: int
    media_warnings: list[str]
    unsupported_media_reason: str | None


# Человекочитаемые ярлыки платформ (для сообщений/предупреждений).
DISPLAY_LABELS: dict[str, str] = {
    "vk": "VK",
    "telegram": "Telegram",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "rutube": "RuTube",
}

# Платформы, у которых live-публикация ещё не реализована (только dry-run/preview).
LIVE_NOT_IMPLEMENTED: frozenset[str] = frozenset({"instagram", "youtube", "rutube"})


def display_label(platform: str) -> str:
    """Ярлык платформы для сообщений (``VK``/``Telegram``/…)."""
    return DISPLAY_LABELS.get(platform, platform)


def build_platform_capabilities(settings: Settings) -> dict[str, PlatformCapabilities]:
    """Собрать реестр возможностей платформ из настроек (лимиты — из конфига)."""
    return {
        "vk": PlatformCapabilities(
            platform="vk",
            supports_text=True,
            supports_image=True,
            supports_image_group=True,
            supports_video=False,  # video upload пока не реализован
            supports_video_group=False,
            max_images=settings.vk_media_group_max_photos or 5,
            max_videos=0,
            max_text_length=None,
            live_flag_name="VK_LIVE_PUBLISHING_ENABLED",
            notes=["Текст + фото-группа live-ready. Видео пока пропускается."],
        ),
        "telegram": PlatformCapabilities(
            platform="telegram",
            supports_text=True,
            supports_image=True,
            supports_image_group=True,
            supports_video=False,  # video upload пока не реализован
            supports_video_group=False,
            max_images=settings.telegram_media_group_max_photos or 10,
            max_videos=0,
            max_text_length=4096,
            live_flag_name="TELEGRAM_LIVE_PUBLISHING_ENABLED",
            notes=["Текст + фото-альбом live-ready. Видео пока пропускается."],
        ),
        "instagram": PlatformCapabilities(
            platform="instagram",
            supports_text=True,
            supports_image=True,
            supports_image_group=True,  # carousel
            supports_video=True,  # reels
            supports_video_group=False,
            max_images=10,
            max_videos=1,
            max_text_length=2200,
            live_flag_name="INSTAGRAM_LIVE_PUBLISHING_ENABLED",
            notes=["Live-публикация пока не реализована — только dry-run/preview."],
        ),
        "youtube": PlatformCapabilities(
            platform="youtube",
            supports_text=False,  # текст — только описание/заголовок видео
            supports_image=False,
            supports_image_group=False,
            supports_video=True,
            supports_video_group=False,
            max_images=0,
            max_videos=1,
            max_text_length=5000,
            live_flag_name="YOUTUBE_LIVE_PUBLISHING_ENABLED",
            notes=["Видео/shorts. Live-публикация пока не реализована — dry-run/preview."],
        ),
        "rutube": PlatformCapabilities(
            platform="rutube",
            supports_text=False,  # текст — только описание видео
            supports_image=False,
            supports_image_group=False,
            supports_video=True,
            supports_video_group=False,
            max_images=0,
            max_videos=1,
            max_text_length=None,
            live_flag_name="RUTUBE_LIVE_PUBLISHING_ENABLED",
            notes=["Видео. Live-публикация пока не реализована — dry-run/preview."],
        ),
    }


@lru_cache
def get_platform_capabilities() -> dict[str, PlatformCapabilities]:
    """Реестр возможностей платформ (кешируется; лимиты — из настроек)."""
    return build_platform_capabilities(get_settings())


def get_capabilities(platform: str) -> PlatformCapabilities | None:
    """Возможности платформы или ``None``, если платформа неизвестна."""
    return get_platform_capabilities().get(platform)


def _count_kinds(media_items: list[dict[str, object]]) -> tuple[int, int]:
    images = sum(1 for item in media_items if str(item.get("media_kind")) == "image")
    videos = sum(1 for item in media_items if str(item.get("media_kind")) == "video")
    return images, videos


def _unsupported_reason(caps: PlatformCapabilities, images: int, videos: int) -> str:
    label = display_label(caps.platform)
    if images and not caps.supports_image and not videos:
        return (
            f"{label}: пост содержит только фото ({images}), а платформа принимает видео — "
            "медиа не будет прикреплено"
        )
    if videos and not caps.supports_video and not images:
        return (
            f"Видео не прикрепляется: {label} не загружает видео на этом этапе — уйдёт только текст"
        )
    if not images and not videos:
        return f"{label}: подходящее медиа не найдено"
    return f"{label}: доступное медиа не поддерживается платформой"


def route_media(
    caps: PlatformCapabilities, media_items: list[dict[str, object]]
) -> MediaRoutingDecision:
    """Решить, что уйдёт на платформу для набора ``media_items`` (image/video).

    Приоритет — фото, если платформа их принимает; иначе видео, если принимает;
    иначе медиа не прикрепляется (с понятной причиной). Предупреждения — про
    усечение по лимиту, пропуск неподдерживаемого типа и т. п. Сеть не трогается.
    """
    images_total, videos_total = _count_kinds(media_items)
    warnings: list[str] = []
    label = display_label(caps.platform)

    if caps.supports_image and images_total:
        if caps.supports_image_group and images_total >= 2:
            count = min(images_total, caps.max_images)
            kind = "image_group" if count >= 2 else "image"
            if images_total > caps.max_images:
                warnings.append(
                    f"{label}: лимит {caps.max_images} фото — будут отправлены первые "
                    f"{caps.max_images} из {images_total}"
                )
        else:
            count = 1
            kind = "image"
            if images_total > 1:
                warnings.append(
                    f"{label}: альбом не поддерживается — будет отправлено 1 фото из {images_total}"
                )
        if videos_total:
            if caps.supports_video:
                warnings.append(
                    f"{label}: смешанные фото+видео — видео в этот пост не войдёт "
                    f"({videos_total} видео)"
                )
            else:
                warnings.append(f"{label} video upload is not implemented; video skipped")
        return MediaRoutingDecision(True, kind, count, warnings, None)

    if caps.supports_video and videos_total:
        group = caps.supports_video_group and videos_total >= 2
        count = min(videos_total, caps.max_videos) if group else 1
        kind = "video_group" if group else "video"
        if not caps.supports_video_group and videos_total > 1:
            warnings.append(f"{label}: одно видео за раз — будет отправлено 1 из {videos_total}")
        if images_total and not caps.supports_image:
            warnings.append(
                f"{label}: фото не поддерживается — {images_total} фото пропущено, "
                "отправим только видео"
            )
        return MediaRoutingDecision(True, kind, count, warnings, None)

    reason = _unsupported_reason(caps, images_total, videos_total)
    return MediaRoutingDecision(False, "none", 0, [reason], reason)
