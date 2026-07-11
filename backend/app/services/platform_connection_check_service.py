"""Безопасные проверки подключения платформ (без публикаций и записи).

Все проверки READ-ONLY: getMe/getChat/groups.getById/GET профиля/доступность ссылки.
НИЧЕГО не публикуется, сообщения не отправляются, фото на стену не грузятся.

По умолчанию проверки идут **офлайн** (валидация наличия/формата полей и объяснение
нужных прав) — реальная сеть НЕ вызывается. Онлайн-проба выполняется только если передан
``http_client`` (в тестах — ``httpx.MockTransport``; в проде — реальный клиент за флагом).

Секреты (токены) используются только для запроса и НИКОГДА не попадают в результат.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

_TELEGRAM_BASE = "https://api.telegram.org"
_VK_BASE = "https://api.vk.com/method"
_INSTAGRAM_BASE = "https://graph.facebook.com/v19.0"
_VK_API_VERSION = "5.199"
_TIMEOUT = 5.0

_TELEGRAM_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_URL_RE = re.compile(r"^https://[^\s]+$", re.IGNORECASE)

# Статусы результата.
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_PLANNED = "planned"


@dataclass(frozen=True)
class PlatformCheckItem:
    """Один пункт проверки подключения."""

    key: str
    label: str
    ok: bool
    status: str
    message: str


@dataclass
class PlatformCheckResult:
    """Результат проверки подключения (без секретов)."""

    platform: str
    ok: bool
    status: str
    message: str
    checks: list[PlatformCheckItem] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "checks": [asdict(c) for c in self.checks],
            "next_steps": list(self.next_steps),
        }


@dataclass(frozen=True)
class ConnectionCheckInput:
    """Данные подключения для проверки (токен — только для запроса, не для вывода)."""

    platform_key: str
    token: str | None = None
    external_id: str | None = None
    url: str | None = None
    root_folder: str | None = None
    app_id: str | None = None


def _item(
    key: str, label: str, ok: bool, message: str, status: str | None = None
) -> PlatformCheckItem:
    return PlatformCheckItem(
        key=key,
        label=label,
        ok=ok,
        status=status or (STATUS_OK if ok else STATUS_ERROR),
        message=message,
    )


def _result(
    platform: str, checks: list[PlatformCheckItem], next_steps: list[str]
) -> PlatformCheckResult:
    """Свести пункты в общий результат (error > warning > ok)."""
    if any(c.status == STATUS_ERROR for c in checks):
        status, message = STATUS_ERROR, "Есть ошибки — подключение не готово."
    elif any(c.status == STATUS_WARNING for c in checks):
        status, message = STATUS_WARNING, "Проверьте предупреждения перед публикацией."
    else:
        status, message = STATUS_OK, "Подключение выглядит рабочим."
    return PlatformCheckResult(
        platform=platform,
        ok=status == STATUS_OK,
        status=status,
        message=message,
        checks=checks,
        next_steps=next_steps,
    )


class PlatformConnectionCheckService:
    """Проверки подключения по платформам (safe, read-only, offline-by-default)."""

    def check(
        self,
        data: ConnectionCheckInput,
        http_client: httpx.Client | None = None,
        planned: bool = False,
    ) -> PlatformCheckResult:
        """Единая точка: выбрать проверку по platform_key (или planned)."""
        if planned:
            return self.check_planned(data.platform_key)
        dispatch = {
            "telegram": self.check_telegram,
            "vk": self.check_vk,
            "instagram": self.check_instagram,
            "yandex_disk": self.check_yandex_disk,
            "website": self.check_website,
        }
        fn = dispatch.get(data.platform_key)
        if fn is None:
            return self.check_planned(data.platform_key)
        return fn(data, http_client)

    # --- Telegram ---

    def check_telegram(
        self, data: ConnectionCheckInput, http_client: httpx.Client | None = None
    ) -> PlatformCheckResult:
        checks: list[PlatformCheckItem] = []
        next_steps = [
            "Добавьте бота администратором канала с правом «Публикация сообщений».",
            "Проверьте @username или числовой id канала (-100…).",
        ]
        token = (data.token or "").strip()
        if not token:
            checks.append(
                _item(
                    "token",
                    "Bot token",
                    False,
                    "Токен не задан — заполните Bot token из @BotFather.",
                )
            )
            return _result("telegram", checks, next_steps)
        token_ok = bool(_TELEGRAM_TOKEN_RE.match(token))
        checks.append(
            _item(
                "token_format",
                "Формат токена",
                token_ok,
                "Формат токена корректен." if token_ok else "Токен не похож на формат <id>:<hash>.",
            )
        )
        if not (data.external_id or "").strip():
            checks.append(
                _item(
                    "channel", "Канал", False, "Не указан @username или id канала.", STATUS_WARNING
                )
            )

        if http_client is None:
            checks.append(
                _item(
                    "online",
                    "Онлайн-проверка",
                    True,
                    "getMe/getChat/getChatMember — при онлайн-проверке (сейчас офлайн).",
                    STATUS_WARNING,
                )
            )
            return _result("telegram", checks, next_steps)

        # Онлайн-проба (read-only): getMe → getChat → getChatMember.
        try:
            me = http_client.get(f"{_TELEGRAM_BASE}/bot{token}/getMe", timeout=_TIMEOUT).json()
        except (httpx.HTTPError, ValueError) as exc:
            checks.append(
                _item("getMe", "getMe", False, f"Сеть/ответ недоступны: {type(exc).__name__}.")
            )
            return _result("telegram", checks, next_steps)
        if not me.get("ok"):
            checks.append(_item("getMe", "getMe", False, "Токен отклонён Telegram (getMe не ok)."))
            return _result("telegram", checks, next_steps)
        bot_id = (me.get("result") or {}).get("id")
        checks.append(_item("getMe", "getMe", True, "Токен валиден, бот доступен."))
        chat_id = (data.external_id or "").strip()
        if chat_id:
            chat = http_client.get(
                f"{_TELEGRAM_BASE}/bot{token}/getChat",
                params={"chat_id": chat_id},
                timeout=_TIMEOUT,
            ).json()
            if chat.get("ok"):
                checks.append(_item("getChat", "getChat", True, "Канал найден и доступен боту."))
                member = http_client.get(
                    f"{_TELEGRAM_BASE}/bot{token}/getChatMember",
                    params={"chat_id": chat_id, "user_id": bot_id},
                    timeout=_TIMEOUT,
                ).json()
                status = ((member.get("result") or {}).get("status")) if member.get("ok") else None
                is_admin = status in ("administrator", "creator")
                checks.append(
                    _item(
                        "getChatMember",
                        "Права бота",
                        is_admin,
                        "Бот — администратор канала."
                        if is_admin
                        else "Бот не админ канала — добавьте с правом постить.",
                        STATUS_OK if is_admin else STATUS_WARNING,
                    )
                )
            else:
                checks.append(
                    _item(
                        "getChat",
                        "getChat",
                        False,
                        "Канал не найден (chat not found): проверьте @username и что бот добавлен.",
                    )
                )
        return _result("telegram", checks, next_steps)

    # --- VK ---

    def check_vk(
        self, data: ConnectionCheckInput, http_client: httpx.Client | None = None
    ) -> PlatformCheckResult:
        checks: list[PlatformCheckItem] = []
        next_steps = [
            "Для фото используйте личный user-token (не ключ сообщества).",
            "Проверьте Group ID сообщества.",
        ]
        token = (data.token or "").strip()
        if not token:
            checks.append(
                _item("token", "Access token", False, "Токен не задан — заполните access token VK.")
            )
            return _result("vk", checks, next_steps)
        if not (data.external_id or "").strip():
            checks.append(_item("group", "Group ID", False, "Не указан Group ID.", STATUS_WARNING))

        if http_client is None:
            checks.append(
                _item(
                    "online",
                    "Онлайн-проверка",
                    True,
                    "groups.getById/users.get/groups.get — при онлайн-проверке (сейчас офлайн).",
                    STATUS_WARNING,
                )
            )
            return _result("vk", checks, next_steps)

        params = {"access_token": token, "v": _VK_API_VERSION}
        try:
            groups = http_client.get(
                f"{_VK_BASE}/groups.getById",
                params={**params, "group_id": (data.external_id or "").strip()},
                timeout=_TIMEOUT,
            ).json()
        except (httpx.HTTPError, ValueError) as exc:
            checks.append(
                _item(
                    "groups.getById",
                    "groups.getById",
                    False,
                    f"Сеть/ответ недоступны: {type(exc).__name__}.",
                )
            )
            return _result("vk", checks, next_steps)
        error = groups.get("error")
        if error:
            code = error.get("error_code")
            if code == 27:
                checks.append(
                    _item(
                        "token_type",
                        "Тип токена",
                        False,
                        "Ошибка 27: токен без прав photos.* — нужен user-token.",
                        STATUS_ERROR,
                    )
                )
            else:
                checks.append(
                    _item(
                        "groups.getById",
                        "groups.getById",
                        False,
                        f"VK вернул ошибку {code}: {str(error.get('error_msg'))[:120]}",
                    )
                )
            return _result("vk", checks, next_steps)
        checks.append(_item("groups.getById", "groups.getById", True, "Сообщество найдено."))
        users = http_client.get(f"{_VK_BASE}/users.get", params=params, timeout=_TIMEOUT).json()
        is_user_token = bool(users.get("response"))
        checks.append(
            _item(
                "token_type",
                "Тип токена",
                True,
                "Пользовательский токен — фото доступны."
                if is_user_token
                else "Похоже на токен сообщества — вероятно text-only.",
                STATUS_OK if is_user_token else STATUS_WARNING,
            )
        )
        if is_user_token:
            admin = http_client.get(
                f"{_VK_BASE}/groups.get", params={**params, "filter": "admin"}, timeout=_TIMEOUT
            ).json()
            has_admin = bool((admin.get("response") or {}).get("count"))
            checks.append(
                _item(
                    "groups.admin",
                    "Права администратора",
                    has_admin,
                    "Есть админ-доступ к сообществам."
                    if has_admin
                    else "Админ-сообщества не найдены — проверьте права.",
                    STATUS_OK if has_admin else STATUS_WARNING,
                )
            )
        return _result("vk", checks, next_steps)

    # --- Instagram ---

    def check_instagram(
        self, data: ConnectionCheckInput, http_client: httpx.Client | None = None
    ) -> PlatformCheckResult:
        checks: list[PlatformCheckItem] = []
        next_steps = [
            "Аккаунт должен быть Professional (Business/Creator).",
            "Для публикации нужен публичный HTTPS image_url.",
        ]
        token = (data.token or "").strip()
        ig_id = (data.external_id or "").strip()
        if not token:
            checks.append(
                _item("token", "Access token", False, "Токен не задан — заполните Access Token.")
            )
        if not ig_id:
            checks.append(
                _item("user_id", "Instagram User ID", False, "Не указан Instagram User ID.")
            )
        if not token or not ig_id:
            return _result("instagram", checks, next_steps)

        if http_client is None:
            checks.append(
                _item(
                    "online",
                    "Онлайн-проверка",
                    True,
                    "GET /{ig-user-id}?fields=id,username — при онлайн-проверке (сейчас офлайн).",
                    STATUS_WARNING,
                )
            )
            return _result("instagram", checks, next_steps)

        try:
            resp = http_client.get(
                f"{_INSTAGRAM_BASE}/{ig_id}",
                params={"fields": "id,username", "access_token": token},
                timeout=_TIMEOUT,
            ).json()
        except (httpx.HTTPError, ValueError) as exc:
            checks.append(
                _item("profile", "Профиль", False, f"Сеть/ответ недоступны: {type(exc).__name__}.")
            )
            return _result("instagram", checks, next_steps)
        if resp.get("error"):
            msg = str((resp.get("error") or {}).get("message", ""))[:120]
            checks.append(
                _item(
                    "profile",
                    "Профиль",
                    False,
                    f"Meta API отклонил запрос: {msg} — проверьте токен/права/тип аккаунта.",
                )
            )
            return _result("instagram", checks, next_steps)
        checks.append(
            _item(
                "profile",
                "Профиль",
                bool(resp.get("id")),
                f"Аккаунт доступен (@{resp.get('username', '—')})."
                if resp.get("id")
                else "Профиль не получен.",
            )
        )
        checks.append(
            _item(
                "image_url",
                "Публичный image_url",
                True,
                "Для публикации нужен публичный HTTPS image_url (live выключен).",
                STATUS_WARNING,
            )
        )
        return _result("instagram", checks, next_steps)

    # --- Yandex Disk ---

    def check_yandex_disk(
        self, data: ConnectionCheckInput, http_client: httpx.Client | None = None
    ) -> PlatformCheckResult:
        checks: list[PlatformCheckItem] = []
        next_steps = [
            "Разложите медиа по папкам/тегам.",
            "Для Instagram нужен прямой публичный URL.",
        ]
        url = (data.url or "").strip()
        if not url:
            checks.append(
                _item("url", "Публичная ссылка", False, "Не указана публичная ссылка на папку.")
            )
            return _result("yandex_disk", checks, next_steps)
        url_ok = bool(_URL_RE.match(url))
        checks.append(
            _item(
                "url_format",
                "Формат ссылки",
                url_ok,
                "Ссылка выглядит корректной (HTTPS)."
                if url_ok
                else "Ссылка должна начинаться с https://",
            )
        )
        if http_client is None:
            checks.append(
                _item(
                    "reachable",
                    "Доступность",
                    True,
                    "Доступность ссылки проверится при онлайн-проверке (сейчас офлайн-валидация).",
                    STATUS_WARNING,
                )
            )
            return _result("yandex_disk", checks, next_steps)
        try:
            resp = http_client.get(url, timeout=_TIMEOUT)
            reachable = resp.status_code < 400
        except httpx.HTTPError as exc:
            reachable = False
            checks.append(
                _item(
                    "reachable", "Доступность", False, f"Ссылка недоступна: {type(exc).__name__}."
                )
            )
            return _result("yandex_disk", checks, next_steps)
        checks.append(
            _item(
                "reachable",
                "Доступность",
                reachable,
                "Публичная ссылка доступна."
                if reachable
                else "Ссылка вернула ошибку — проверьте доступ.",
            )
        )
        return _result("yandex_disk", checks, next_steps)

    # --- Website ---

    def check_website(
        self, data: ConnectionCheckInput, http_client: httpx.Client | None = None
    ) -> PlatformCheckResult:
        checks: list[PlatformCheckItem] = []
        next_steps = ["Сайт используется для ссылок/CTA, не как площадка публикации."]
        url = (data.url or "").strip()
        if not url:
            checks.append(_item("url", "URL", False, "Не указан URL сайта."))
            return _result("website", checks, next_steps)
        url_ok = bool(re.match(r"^https?://[^\s]+$", url, re.IGNORECASE))
        checks.append(
            _item(
                "url_format",
                "Формат URL",
                url_ok,
                "URL выглядит корректным." if url_ok else "URL должен начинаться с http(s)://",
            )
        )
        if http_client is None:
            checks.append(
                _item(
                    "reachable",
                    "Доступность",
                    True,
                    "Доступность сайта проверится при онлайн-проверке (сейчас офлайн).",
                    STATUS_WARNING,
                )
            )
            return _result("website", checks, next_steps)
        try:
            resp = http_client.get(url, timeout=_TIMEOUT)
            reachable = resp.status_code < 500
        except httpx.HTTPError as exc:
            checks.append(
                _item("reachable", "Доступность", False, f"Сайт недоступен: {type(exc).__name__}.")
            )
            return _result("website", checks, next_steps)
        checks.append(
            _item(
                "reachable",
                "Доступность",
                reachable,
                f"Сайт ответил ({resp.status_code})."
                if reachable
                else "Сайт вернул ошибку сервера.",
            )
        )
        return _result("website", checks, next_steps)

    # --- Planned / research ---

    def check_planned(self, platform_key: str) -> PlatformCheckResult:
        """Проверка для площадок в разработке: статус planned, live выключен."""
        item = PlatformCheckItem(
            key="planned",
            label="Интеграция",
            ok=False,
            status=STATUS_PLANNED,
            message="Интеграция в разработке — онлайн-проверка появится позже.",
        )
        return PlatformCheckResult(
            platform=platform_key,
            ok=False,
            status=STATUS_PLANNED,
            message="Площадка в разработке: подключение — черновик, публикация выключена.",
            checks=[item],
            next_steps=["Следите за обновлениями — интеграция готовится."],
        )


def get_platform_connection_check_service() -> PlatformConnectionCheckService:
    """DI-фабрика сервиса проверок подключения."""
    return PlatformConnectionCheckService()
