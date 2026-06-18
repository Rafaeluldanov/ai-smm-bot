"""Заглушка Telegram-интерфейса согласования (Этап 6).

Строит структуру будущего сообщения-карточки и набор кнопок под текущий статус
поста. Реальный Telegram Bot API **не** вызывается — ничего не отправляется в
сеть. На Этапе 7 эта структура будет использована для реальной отправки.
"""

from pydantic import BaseModel, Field

from app.schemas.post_review import PostReviewCard

# Префикс callback_data кнопок (Telegram передаёт его обратно при нажатии).
_CALLBACK_PREFIX = "postreview"


class TelegramReviewButton(BaseModel):
    """Кнопка под карточкой согласования (inline keyboard button)."""

    action: str
    label: str
    callback_data: str


class TelegramReviewMessage(BaseModel):
    """Структура сообщения-карточки для Telegram (без отправки)."""

    post_id: int
    text: str
    parse_mode: str = "HTML"
    buttons: list[TelegramReviewButton] = Field(default_factory=list)


# Какие кнопки-решения показывать при каком статусе поста.
_BUTTON_LABELS: dict[str, str] = {
    "approve": "✅ Одобрить",
    "reject": "⛔ Отклонить",
    "request_changes": "✏️ На доработку",
    "return_to_draft": "↩️ В черновик",
    "open_post": "🔎 Открыть пост",
    "add_comment": "💬 Комментарий",
}

_DECISION_BUTTONS_BY_STATUS: dict[str, list[str]] = {
    "draft": ["approve", "reject"],
    "needs_media": ["reject", "return_to_draft"],
    "needs_review": ["approve", "reject", "request_changes", "return_to_draft"],
    "approved": ["request_changes", "reject", "return_to_draft"],
    "scheduled": [],
    "published": [],
    "rejected": ["return_to_draft"],
}

# Кнопки, доступные всегда (не меняют статус).
_ALWAYS_BUTTONS: list[str] = ["open_post", "add_comment"]


class TelegramReviewInterface:
    """Строит карточку и кнопки согласования (без обращения к Telegram)."""

    def build_review_message(self, card: PostReviewCard) -> TelegramReviewMessage:
        """Собрать структуру сообщения-карточки по данным поста."""
        return TelegramReviewMessage(
            post_id=card.post_id,
            text=self._render_text(card),
            buttons=self.build_buttons(card.post_id, card.status),
        )

    def build_buttons(self, post_id: int, status: str) -> list[TelegramReviewButton]:
        """Вернуть кнопки под текущий статус поста."""
        actions = [*_DECISION_BUTTONS_BY_STATUS.get(status, []), *_ALWAYS_BUTTONS]
        return [
            TelegramReviewButton(
                action=action,
                label=_BUTTON_LABELS[action],
                callback_data=f"{_CALLBACK_PREFIX}:{action}:{post_id}",
            )
            for action in actions
        ]

    @staticmethod
    def _render_text(card: PostReviewCard) -> str:
        """Сформировать текст карточки (заголовок, статус, превью, хэштеги)."""
        lines = [
            f"Пост #{card.post_id}: {card.title or 'Без заголовка'}",
            f"Статус: {card.status}",
            "",
            (card.telegram_text or "").strip(),
        ]
        if card.hashtags:
            lines.append("")
            lines.append(" ".join(card.hashtags))
        if card.warnings:
            lines.append("")
            lines.append("⚠ " + "; ".join(card.warnings))
        return "\n".join(lines)
