"""Сервисный слой секретов CRM-ресурсов (шифрование и маскирование).

ВНИМАНИЕ: на этом этапе это ЗАГЛУШКА без настоящей криптографии — секрет лишь
обратимо кодируется (base64) с префиксом-меткой. Задача слоя — изолировать место
хранения секрета так, чтобы позже без изменения остального кода заменить
реализацию на реальное шифрование.

TODO(security): заменить ``encrypt_secret``/``decrypt_secret`` на KMS/Fernet:
- ключ шифрования брать из защищённого хранилища (KMS, Vault, env), не из кода;
- ``api_key_encrypted`` хранить как шифртекст Fernet;
- ротация ключей и версионирование через префикс схемы.

ГЛАВНОЕ ПРАВИЛО БЕЗОПАСНОСТИ: ни ``encrypt_secret``-результат, ни исходный секрет
НИКОГДА не отдаются наружу (API/логи/тесты). Наружу — только ``mask_secret`` и
факт наличия секрета (``api_key_present``).
"""

import base64

# Метка схемы кодирования (позволит отличать версии при миграции на Fernet).
_ENC_PREFIX = "crm-enc-v0:"
_MASK_CHAR = "•"


def encrypt_secret(plaintext: str) -> str:
    """Закодировать секрет для хранения (ЗАГЛУШКА, не настоящее шифрование)."""
    encoded = base64.urlsafe_b64encode(plaintext.encode("utf-8")).decode("ascii")
    return f"{_ENC_PREFIX}{encoded}"


def decrypt_secret(stored: str) -> str:
    """Восстановить секрет из хранимого значения (используется внутри, не в API)."""
    if not stored.startswith(_ENC_PREFIX):
        raise ValueError("Неизвестная схема хранения секрета")
    encoded = stored[len(_ENC_PREFIX) :]
    return base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")


def mask_secret(plaintext: str) -> str:
    """Безопасная маска секрета для показа в UI/CRM (без утечки значения).

    Показывает не более 4 последних символов и только для достаточно длинных
    секретов; короткие секреты маскируются целиком.
    """
    if not plaintext:
        return ""
    tail = plaintext[-4:] if len(plaintext) >= 8 else ""
    return f"{_MASK_CHAR * 4}{tail}"


def is_encrypted(stored: str | None) -> bool:
    """Проверить, что значение похоже на хранимый секрет нашей схемы."""
    return bool(stored) and stored.startswith(_ENC_PREFIX)  # type: ignore[union-attr]
