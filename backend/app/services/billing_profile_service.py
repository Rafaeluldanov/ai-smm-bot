"""Валидация реквизитов плательщика (физлицо / ИП / ООО) под метод оплаты.

Реквизиты хранятся в :class:`app.models.payment.BillingProfile`. Данные банковской
карты НИКОГДА не хранятся и не валидируются здесь — карта вводится только на стороне
платёжного провайдера. Этот сервис проверяет полноту юридических реквизитов для чеков
и счетов ИП/ООО и умеет маскировать реквизиты для показа в UI.
"""

from __future__ import annotations

from typing import Any

from app.services.payments.payment_provider import (
    METHOD_INVOICE_COMPANY,
    METHOD_INVOICE_IP,
    PAYMENT_METHODS,
)

# Методы, доступные физлицу без юр. реквизитов (нужен только email для чека).
_CARD_LIKE_METHODS: tuple[str, ...] = ("bank_card", "sbp", "qr")


def _val(profile: Any, field: str) -> str:
    """Прочитать поле профиля как строку (профиль — ORM-объект или dict)."""
    if profile is None:
        return ""
    raw = profile.get(field) if isinstance(profile, dict) else getattr(profile, field, None)
    return str(raw).strip() if raw not in (None, "") else ""


def _mask_tail(value: str, visible: int = 4) -> str:
    """Замаскировать значение, оставив последние ``visible`` символов."""
    value = value.strip()
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


def _mask_email(value: str) -> str:
    """Замаскировать email: п***@домен."""
    value = value.strip()
    if "@" not in value:
        return _mask_tail(value)
    local, _, domain = value.partition("@")
    head = local[0] if local else ""
    return f"{head}***@{domain}"


class BillingProfileService:
    """Проверка готовности реквизитов плательщика к оплате выбранным методом."""

    def validate_profile_for_method(self, profile: Any, payment_method: str) -> list[str]:
        """Вернуть список НЕДОСТАЮЩИХ реквизитов для метода (пусто → всё заполнено).

        - карта/СБП/QR: нужен email (для фискального чека 54-ФЗ);
        - счёт ИП: ИНН + наименование/ФИО + email (ОГРНИП опционален);
        - счёт ООО: ИНН + юр. наименование + email (КПП опционален).
        """
        method = (payment_method or "").strip().lower()
        if method not in PAYMENT_METHODS:
            return [f"Неизвестный метод оплаты: {payment_method!r}"]
        if profile is None:
            return ["Заполните реквизиты плательщика"]

        errors: list[str] = []
        email = _val(profile, "email")
        if method in _CARD_LIKE_METHODS:
            if not email:
                errors.append("Укажите email для чека")
            return errors

        if method == METHOD_INVOICE_IP:
            if not _val(profile, "inn"):
                errors.append("Для счёта ИП укажите ИНН")
            if not _val(profile, "legal_name"):
                errors.append("Укажите наименование/ФИО ИП")
            if not email:
                errors.append("Укажите email для счёта и чека")
        elif method == METHOD_INVOICE_COMPANY:
            if not _val(profile, "inn"):
                errors.append("Для счёта ООО укажите ИНН")
            if not _val(profile, "legal_name"):
                errors.append("Укажите юридическое наименование")
            if not email:
                errors.append("Укажите email для счёта и чека")
        return errors

    def profile_ready_for_invoice(self, profile: Any, method: str) -> bool:
        """True, если реквизитов достаточно для оплаты методом ``method``."""
        return not self.validate_profile_for_method(profile, method)

    def mask_profile(self, profile: Any) -> dict[str, Any]:
        """Вернуть безопасное для показа представление реквизитов (маскированное).

        Секретов в профиле нет, но ИНН/КПП/ОГРН/email/телефон маскируются на всякий
        случай (минимизация раскрытия ПДн в интерфейсе/логах).
        """
        if profile is None:
            return {}
        return {
            "customer_type": _val(profile, "customer_type") or "individual",
            "legal_name": _val(profile, "legal_name"),
            "inn": _mask_tail(_val(profile, "inn")),
            "kpp": _mask_tail(_val(profile, "kpp")),
            "ogrn": _mask_tail(_val(profile, "ogrn")),
            "ogrnip": _mask_tail(_val(profile, "ogrnip")),
            "email": _mask_email(_val(profile, "email")),
            "phone": _mask_tail(_val(profile, "phone")),
        }

    def readiness(self, profile: Any) -> dict[str, Any]:
        """Готовность реквизитов по каждому методу (для чипов в UI)."""
        methods = ("bank_card", "sbp", "qr", METHOD_INVOICE_IP, METHOD_INVOICE_COMPANY)
        ready = {m: self.profile_ready_for_invoice(profile, m) for m in methods}
        missing = {m: self.validate_profile_for_method(profile, m) for m in methods}
        return {
            "has_profile": profile is not None,
            "customer_type": _val(profile, "customer_type") or "individual",
            "ready": ready,
            "missing": missing,
            "masked": self.mask_profile(profile),
        }
