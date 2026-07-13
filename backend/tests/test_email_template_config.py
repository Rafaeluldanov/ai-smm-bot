"""Тесты конфигурации email/SMTP (v0.5.3). Дефолты безопасны; live выключен; клампы работают."""

from app.config import Settings


def test_email_smtp_defaults_safe() -> None:
    s = Settings()
    # Никакой реальной email-доставки по умолчанию.
    assert s.smtp_live_send_enabled is False
    assert s.smtp_dry_run is True
    assert s.email_test_send_enabled is False
    assert s.email_test_send_dry_run is True
    # Эффективные флаги: всё выключено.
    assert s.smtp_live_send_enabled_effective is False
    assert s.notification_email_enabled_effective is False
    assert s.email_test_send_enabled_effective is False
    # Футер и preview включены (безопасно — только рендер).
    assert s.email_templates_enabled_effective is True
    assert s.email_unsubscribe_footer_enabled_effective is True


def test_smtp_not_configured_by_default() -> None:
    s = Settings()
    assert s.smtp_configured is False


def test_smtp_timeout_clamped() -> None:
    # 0 трактуется как «не задан» → дефолт 20; отрицательное → нижняя граница 1.
    assert Settings(smtp_timeout_seconds=0).smtp_timeout_seconds_safe == 20
    assert Settings(smtp_timeout_seconds=-5).smtp_timeout_seconds_safe == 1
    assert Settings(smtp_timeout_seconds=9999).smtp_timeout_seconds_safe == 120
    assert Settings(smtp_timeout_seconds=30).smtp_timeout_seconds_safe == 30


def test_email_test_allowed_recipients_parsed() -> None:
    s = Settings(email_test_allowed_recipients="A@e.com, b@e.com ,,")
    assert s.email_test_allowed_recipients_list == ["a@e.com", "b@e.com"]


def test_smtp_live_requires_all_flags() -> None:
    # Даже при включённом SMTP live, без external+email-live эффективный флаг остаётся False.
    s = Settings(
        smtp_host="smtp.example.com",
        smtp_from_email="from@example.com",
        smtp_live_send_enabled=True,
        smtp_dry_run=False,
    )
    assert s.smtp_live_send_enabled_effective is False
    # Все флаги включены → эффективный True (демонстрация «live-ready», в MVP не используется).
    s2 = Settings(
        notification_external_delivery_enabled=True,
        notification_email_enabled=True,
        notification_email_live_enabled=True,
        smtp_host="smtp.example.com",
        smtp_from_email="from@example.com",
        smtp_live_send_enabled=True,
        smtp_dry_run=False,
    )
    assert s2.smtp_live_send_enabled_effective is True
