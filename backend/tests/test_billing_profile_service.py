"""Тесты валидации реквизитов плательщика (физлицо / ИП / ООО) под метод оплаты."""

from types import SimpleNamespace

from app.services.billing_profile_service import BillingProfileService

SVC = BillingProfileService()


def _profile(**fields: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "customer_type": "individual",
        "legal_name": None,
        "inn": None,
        "kpp": None,
        "ogrn": None,
        "ogrnip": None,
        "email": None,
        "phone": None,
    }
    base.update(fields)
    return SimpleNamespace(**base)


def test_none_profile_not_ready() -> None:
    assert SVC.validate_profile_for_method(None, "bank_card") == ["Заполните реквизиты плательщика"]
    assert SVC.profile_ready_for_invoice(None, "sbp") is False


def test_individual_card_requires_email() -> None:
    assert SVC.validate_profile_for_method(_profile(), "bank_card")  # нет email → ошибка
    ok = _profile(email="a@e.com")
    assert SVC.validate_profile_for_method(ok, "bank_card") == []
    assert SVC.profile_ready_for_invoice(ok, "sbp") is True
    assert SVC.profile_ready_for_invoice(ok, "qr") is True


def test_ip_invoice_validation() -> None:
    incomplete = _profile(customer_type="ip", email="ip@e.com")
    errors = SVC.validate_profile_for_method(incomplete, "invoice_for_ip")
    assert any("ИНН" in e for e in errors)
    assert any("ФИО" in e or "наименование" in e.lower() for e in errors)
    full = _profile(
        customer_type="ip", inn="770101010101", legal_name="ИП Иванов", email="ip@e.com"
    )
    assert SVC.validate_profile_for_method(full, "invoice_for_ip") == []


def test_company_invoice_requires_inn_name_email() -> None:
    incomplete = _profile(customer_type="company")
    errors = SVC.validate_profile_for_method(incomplete, "invoice_for_company")
    assert any("ИНН" in e for e in errors)
    assert any("наименование" in e.lower() for e in errors)
    assert any("email" in e.lower() for e in errors)
    full = _profile(
        customer_type="company", inn="7707083893", legal_name='ООО "Ромашка"', email="c@e.com"
    )
    assert SVC.profile_ready_for_invoice(full, "invoice_for_company") is True


def test_unknown_method_rejected() -> None:
    assert SVC.validate_profile_for_method(_profile(email="a@e.com"), "crypto")


def test_mask_profile_hides_details() -> None:
    profile = _profile(
        customer_type="company",
        inn="7707083893",
        kpp="770701001",
        legal_name='ООО "Ромашка"',
        email="director@romashka.ru",
        phone="+79991234567",
    )
    masked = SVC.mask_profile(profile)
    # Полные значения не раскрываются.
    assert masked["inn"].endswith("3893") and masked["inn"].startswith("*")
    assert masked["email"].startswith("d***@") and "romashka.ru" in masked["email"]
    assert "director" not in masked["email"]
    assert masked["phone"].endswith("4567") and masked["phone"].startswith("*")
    # legal_name показывается (публичное юр. имя).
    assert masked["legal_name"] == 'ООО "Ромашка"'


def test_mask_profile_no_full_secrets_in_blob() -> None:
    profile = _profile(inn="7707083893", email="director@romashka.ru", phone="+79991234567")
    blob = str(SVC.mask_profile(profile))
    assert "7707083893" not in blob
    assert "director@romashka.ru" not in blob
    assert "+79991234567" not in blob


def test_readiness_shape() -> None:
    r = SVC.readiness(_profile(email="a@e.com"))
    assert r["has_profile"] is True
    assert r["ready"]["bank_card"] is True
    assert r["ready"]["invoice_for_company"] is False  # нет ИНН/наименования
    assert "missing" in r and "masked" in r
