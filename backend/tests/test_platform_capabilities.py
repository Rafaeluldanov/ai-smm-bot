"""Тесты capability-слоя платформ (offline, без сети)."""

from app.config import Settings
from app.integrations.platform_capabilities import (
    LIVE_NOT_IMPLEMENTED,
    build_platform_capabilities,
    route_media,
)

_IMG = {"media_kind": "image"}
_VID = {"media_kind": "video"}


def _caps() -> dict:
    return build_platform_capabilities(Settings())


# --------------------------------------------------------------------------- #
# Регистрация, флаги, лимиты                                                    #
# --------------------------------------------------------------------------- #


def test_all_platforms_registered() -> None:
    assert set(_caps()) == {"vk", "telegram", "instagram", "youtube", "rutube"}


def test_live_flags_default_false() -> None:
    fields = Settings.model_fields
    for flag in (
        "telegram_live_publishing_enabled",
        "vk_live_publishing_enabled",
        "instagram_live_publishing_enabled",
        "youtube_live_publishing_enabled",
        "rutube_live_publishing_enabled",
    ):
        assert fields[flag].default is False


def test_live_not_implemented_set() -> None:
    assert frozenset({"instagram", "youtube", "rutube"}) == LIVE_NOT_IMPLEMENTED


def test_max_media_limits() -> None:
    caps = _caps()
    assert caps["vk"].max_images == 5
    assert caps["telegram"].max_images == 10
    assert caps["instagram"].max_images == 10
    assert caps["youtube"].max_images == 0
    assert caps["youtube"].max_videos == 1
    assert caps["rutube"].max_videos == 1


def test_capability_flags() -> None:
    caps = _caps()
    assert caps["vk"].supports_image_group and not caps["vk"].supports_video
    assert caps["telegram"].supports_image_group and not caps["telegram"].supports_video
    assert caps["instagram"].supports_image_group and caps["instagram"].supports_video
    assert caps["youtube"].supports_video and not caps["youtube"].supports_image
    assert caps["rutube"].supports_video and not caps["rutube"].supports_image


def test_live_flag_names() -> None:
    caps = _caps()
    assert caps["vk"].live_flag_name == "VK_LIVE_PUBLISHING_ENABLED"
    assert caps["telegram"].live_flag_name == "TELEGRAM_LIVE_PUBLISHING_ENABLED"
    assert caps["instagram"].live_flag_name == "INSTAGRAM_LIVE_PUBLISHING_ENABLED"
    assert caps["youtube"].live_flag_name == "YOUTUBE_LIVE_PUBLISHING_ENABLED"
    assert caps["rutube"].live_flag_name == "RUTUBE_LIVE_PUBLISHING_ENABLED"


# --------------------------------------------------------------------------- #
# route_media: решения по типам медиа                                          #
# --------------------------------------------------------------------------- #


def test_image_group_on_image_platforms_attaches() -> None:
    caps = _caps()
    for platform in ("vk", "telegram", "instagram"):
        decision = route_media(caps[platform], [_IMG, _IMG, _IMG])
        assert decision.would_attach_media is True
        assert decision.selected_media_kind == "image_group"
        assert decision.selected_count == 3
        assert decision.unsupported_media_reason is None


def test_image_group_on_video_platforms_unsupported() -> None:
    caps = _caps()
    for platform in ("youtube", "rutube"):
        decision = route_media(caps[platform], [_IMG, _IMG, _IMG])
        assert decision.would_attach_media is False
        assert decision.selected_media_kind == "none"
        assert decision.unsupported_media_reason is not None
        assert "фото" in decision.unsupported_media_reason.lower()


def test_video_on_video_platforms_attaches() -> None:
    caps = _caps()
    for platform in ("youtube", "rutube", "instagram"):
        decision = route_media(caps[platform], [_VID])
        assert decision.would_attach_media is True
        assert decision.selected_media_kind == "video"
        assert decision.selected_count == 1


def test_video_on_image_platforms_unsupported() -> None:
    caps = _caps()
    for platform in ("vk", "telegram"):
        decision = route_media(caps[platform], [_VID])
        assert decision.would_attach_media is False
        assert decision.unsupported_media_reason is not None


def test_mixed_on_image_platform_selects_photos_skips_video() -> None:
    caps = _caps()
    decision = route_media(caps["telegram"], [_IMG, _IMG, _VID])
    assert decision.would_attach_media is True
    assert decision.selected_media_kind == "image_group"
    assert decision.selected_count == 2
    assert any("video skipped" in w for w in decision.media_warnings)


def test_mixed_on_video_platform_selects_video() -> None:
    caps = _caps()
    decision = route_media(caps["youtube"], [_IMG, _IMG, _VID])
    assert decision.would_attach_media is True
    assert decision.selected_media_kind == "video"
    assert any("фото" in w.lower() for w in decision.media_warnings)


def test_image_limit_truncation_warns() -> None:
    caps = _caps()
    decision = route_media(caps["vk"], [_IMG] * 7)  # vk max_images = 5
    assert decision.selected_count == 5
    assert any("лимит" in w.lower() for w in decision.media_warnings)


def test_no_media_reports_unsupported() -> None:
    caps = _caps()
    decision = route_media(caps["vk"], [])
    assert decision.would_attach_media is False
    assert decision.unsupported_media_reason is not None
