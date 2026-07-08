"""Хеширование паролей и dev-токены без внешних зависимостей.

passlib/bcrypt в проекте не установлены, поэтому используем стандартную библиотеку:
- пароли: PBKDF2-HMAC-SHA256, формат ``pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>``;
  сырой пароль НИКОГДА не хранится/не логируется; сравнение — постоянного времени.
- dev-токен сессии: ``<user_id>.<hmac>`` — это НЕ продакшн-JWT, а безопасная
  заглушка на время SaaS-каркаса (подпись защищает от тривиальной подделки id).
"""

import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 100_000
_SALT_BYTES = 16

# Dev-секрет для подписи токена (НЕ продакшн). Реальная auth-система заменит это
# на настоящий JWT/сессии. Секрет можно переопределить переменной окружения
# ``SAAS_DEV_TOKEN_SECRET`` (не в .env), чтобы не хардкодить его в проде.
_DEV_TOKEN_SECRET = os.environ.get(
    "SAAS_DEV_TOKEN_SECRET", "saas-dev-token-secret-not-for-production"
).encode("utf-8")


class PasswordHasher:
    """PBKDF2-хешер паролей (без внешних зависимостей)."""

    def __init__(self, iterations: int = _DEFAULT_ITERATIONS) -> None:
        self._iterations = max(1, iterations)

    def hash(self, password: str) -> str:
        """Вернуть строку хранения хеша (с солью). Сырой пароль не сохраняется."""
        salt = os.urandom(_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, self._iterations)
        return f"{_ALGORITHM}${self._iterations}${salt.hex()}${digest.hex()}"

    def verify(self, password: str, stored: str) -> bool:
        """Проверить пароль против сохранённого хеша (constant-time)."""
        parts = stored.split("$")
        if len(parts) != 4 or parts[0] != _ALGORITHM:
            return False
        try:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected = bytes.fromhex(parts[3])
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(digest, expected)


def _sign(user_id: int) -> str:
    return hmac.new(_DEV_TOKEN_SECRET, str(user_id).encode("utf-8"), hashlib.sha256).hexdigest()[
        :32
    ]


def make_dev_token(user_id: int) -> str:
    """Собрать подписанный dev-токен сессии для пользователя."""
    return f"{user_id}.{_sign(user_id)}"


def parse_dev_token(token: str) -> int | None:
    """Вернуть user_id из валидного dev-токена или None."""
    if not token:
        return None
    raw = token[7:] if token.startswith("Bearer ") else token
    parts = raw.split(".")
    if len(parts) != 2 or not parts[0].isdigit():
        return None
    user_id = int(parts[0])
    return user_id if hmac.compare_digest(parts[1], _sign(user_id)) else None
