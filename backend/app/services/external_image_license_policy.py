"""Политика лицензий и безопасности внешних изображений (Этап 9).

Главное правило: внешнее изображение НИКОГДА не является нашим кейсом/портфолио.
Здесь — чистые функции оценки прав и ограничений. Без БД, сети и AI.

``candidate_or_result`` — это либо ``ExternalImageProviderResult``, либо
``ExternalImageCandidate`` (у них совпадают нужные атрибуты).
"""

from typing import Any

from app.schemas.external_image import ExternalImageSafetyReport


def normalize_license_name(value: str) -> str:
    """Привести имя лицензии к нижнему регистру со схлопыванием пробелов."""
    return " ".join(value.lower().split())


def _attribution_text(candidate: Any) -> str:
    """Сформировать строку атрибуции (автор + лицензия + ссылка)."""
    author = getattr(candidate, "author_name", None) or "автор не указан"
    license_name = getattr(candidate, "license_name", None) or "лицензия не указана"
    parts = [f"Фото: {author}", license_name]
    license_url = getattr(candidate, "license_url", None)
    if license_url:
        parts.append(f"({license_url})")
    return ", ".join(parts)


def build_forbidden_usage(candidate_or_result: Any) -> list[str]:
    """Список запрещённых способов использования.

    Внешнее изображение всегда нельзя выдавать за свой кейс/портфолио.
    """
    forbidden: list[str] = ["claim_as_own_case", "portfolio"]
    if not getattr(candidate_or_result, "commercial_use_allowed", False):
        forbidden.append("commercial_use")
        forbidden.append("ads")
    if getattr(candidate_or_result, "contains_logo", False):
        forbidden.append("ads")
        forbidden.append("branding")
    if getattr(candidate_or_result, "contains_people", False):
        forbidden.append("ads_without_model_release")
    if not getattr(candidate_or_result, "modification_allowed", False):
        forbidden.append("modification")
    return list(dict.fromkeys(forbidden))


def evaluate_candidate_safety(candidate: Any) -> ExternalImageSafetyReport:
    """Оценить безопасность использования кандидата."""
    commercial = bool(getattr(candidate, "commercial_use_allowed", False))
    safe = bool(getattr(candidate, "safe_for_business", False))
    has_logo = bool(getattr(candidate, "contains_logo", False))
    has_people = bool(getattr(candidate, "contains_people", False))

    can_use_organically = commercial and safe
    can_use_in_ads = commercial and safe and not has_logo and not has_people

    warnings: list[str] = []
    if not commercial:
        warnings.append("Лицензия запрещает коммерческое использование")
    if has_logo:
        warnings.append("На изображении чужой логотип — нельзя в рекламе")
    if has_people:
        warnings.append("В кадре люди — для рекламы нужен model release")
    if not safe:
        warnings.append("Изображение не помечено как безопасное для бизнеса")
    warnings.append("Внешнее изображение нельзя выдавать за наш кейс/портфолио")

    required_attribution = None
    if getattr(candidate, "attribution_required", False):
        required_attribution = _attribution_text(candidate)

    return ExternalImageSafetyReport(
        candidate_id=int(getattr(candidate, "id", 0)),
        can_use_organically=can_use_organically,
        can_use_in_ads=can_use_in_ads,
        can_claim_as_own_case=False,
        required_attribution=required_attribution,
        warnings=warnings,
        forbidden_usage=build_forbidden_usage(candidate),
    )


def can_convert_to_media_asset(candidate: Any) -> tuple[bool, list[str]]:
    """Можно ли конвертировать кандидата в MediaAsset (и почему нет)."""
    reasons: list[str] = []
    review_status = getattr(candidate, "review_status", "candidate")

    if review_status == "rejected":
        reasons.append("Кандидат отклонён (rejected) — конвертация запрещена")
    elif review_status == "converted_to_media_asset":
        reasons.append("Кандидат уже сконвертирован в MediaAsset")
    elif review_status not in {"approved", "needs_review"}:
        reasons.append(
            f"Статус '{review_status}' не допускает конвертацию (нужен approved/needs_review)"
        )

    if not getattr(candidate, "commercial_use_allowed", False):
        reasons.append("Лицензия запрещает коммерческое использование")
    if not getattr(candidate, "safe_for_business", False):
        reasons.append("Изображение не безопасно для бизнес-использования")

    return (len(reasons) == 0), reasons
