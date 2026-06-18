"""Тесты помощников текста поста: хэштеги, CTA, сокращение."""

from app.services.post_text_helpers import (
    build_cta,
    build_hashtags,
    clean_hashtag,
    shorten_text,
)


def test_clean_hashtag_basic() -> None:
    assert clean_hashtag("Футболки с логотипом") == "#футболкислоготипом"
    assert clean_hashtag("#TEEON") == "#teeon"
    assert clean_hashtag("УФ-печать") == "#уфпечать"
    assert clean_hashtag("   ") == ""


def test_build_hashtags_teeon() -> None:
    tags = build_hashtags(
        "teeon",
        "Футболки с логотипом на заказ",
        "футболки",
        ["футболки с логотипом", "футболки на заказ"],
    )
    assert "#teeon" in tags
    assert "#футболкислоготипом" in tags
    assert all(" " not in tag for tag in tags)
    assert len(tags) == len(set(tags))


def test_build_hashtags_fabric() -> None:
    tags = build_hashtags(
        "fabric-souvenirs", "Кружки с логотипом", "кружки", ["кружки с логотипом"]
    )
    assert "#фабрикасувениров" in tags


def test_build_cta_teeon() -> None:
    assert build_cta("teeon", "product").startswith("Напишите нам — подберём изделие")
    assert build_cta("teeon", "expert").startswith("Пришлите логотип и тираж")


def test_build_cta_fabric() -> None:
    assert build_cta("fabric-souvenirs", "selling").startswith("Пришлите задачу и тираж")


def test_shorten_text() -> None:
    long_text = "слово " * 100
    short = shorten_text(long_text, 50)
    assert len(short) <= 50
    assert short.endswith("…")
    assert shorten_text("короткий текст", 50) == "короткий текст"
