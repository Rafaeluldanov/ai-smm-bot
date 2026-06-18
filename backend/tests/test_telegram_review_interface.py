"""Тесты заглушки Telegram-интерфейса согласования (без сети)."""

from app.integrations.telegram.review_interface import (
    TelegramReviewInterface,
    TelegramReviewMessage,
)
from app.schemas.post_review import PostReviewCard


def _card(status: str = "needs_review") -> PostReviewCard:
    return PostReviewCard(
        post_id=7,
        project_id=1,
        title="Футболки с логотипом",
        status=status,
        telegram_text="Текст для Telegram",
        hashtags=["#teeon"],
        review_actions_count=0,
    )


def test_build_message_contains_title_and_status() -> None:
    message = TelegramReviewInterface().build_review_message(_card())
    assert isinstance(message, TelegramReviewMessage)
    assert "Футболки с логотипом" in message.text
    assert "needs_review" in message.text
    assert message.post_id == 7


def test_buttons_for_needs_review() -> None:
    actions = [b.action for b in TelegramReviewInterface().build_buttons(7, "needs_review")]
    assert "approve" in actions
    assert "reject" in actions
    assert "request_changes" in actions


def test_buttons_for_rejected() -> None:
    actions = [b.action for b in TelegramReviewInterface().build_buttons(7, "rejected")]
    assert "return_to_draft" in actions
    assert "approve" not in actions


def test_buttons_always_have_open_and_comment() -> None:
    buttons = TelegramReviewInterface().build_buttons(7, "draft")
    actions = [b.action for b in buttons]
    assert "open_post" in actions
    assert "add_comment" in actions
    # callback_data строится локально, ничего не отправляется наружу.
    assert all(b.callback_data.startswith("postreview:") for b in buttons)
