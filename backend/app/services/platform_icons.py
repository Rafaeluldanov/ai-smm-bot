"""Оригинальные inline SVG-иконки платформ в стиле Botfleet.

ВАЖНО:
- Это НЕ официальные логотипы: иконки нарисованы оригинально, «в духе» площадки, без
  копирования товарных знаков один в один.
- Только inline SVG, никаких внешних URL/CDN и никаких растровых картинок.
- Используют ``currentColor`` — цвет берётся из акцент-класса контейнера, поэтому иконки
  аккуратно выглядят в light/dark темах.

Иконка = строка ``<svg …>…</svg>`` c ``viewBox="0 0 24 24"`` без width/height (размер
задаёт CSS ``.platform-icon svg``). Общий стиль — тонкие линии ``stroke=currentColor``.
"""

from __future__ import annotations

_OPEN = (
    "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' "
    "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' focusable='false'>"
)


def _svg(inner: str) -> str:
    return f"{_OPEN}{inner}</svg>"


# Каждая иконка оригинальна и абстрактна («в духе», не копия логотипа).
PLATFORM_ICON_SVG: dict[str, str] = {
    # Мессенджеры / соцсети
    "telegram": _svg(
        "<path d='M4 12.5 20 5l-2.6 14-5-4.2-2.7 2.5.2-4z'/><path d='m9.7 13.3 6.2-5.1'/>"
    ),
    "vk": _svg(
        "<path d='M4 7h3.2c.4 4.3 2 6.4 3 6.9V7h3v4.2c1.2-.2 2.4-1.7 2.9-4.2H22c-.5 2.6-2 4.3-3.3 5 1.3.8 2.6 2.3 3.3 5h-2.9c-.6-2.2-1.9-3.6-3.1-3.7V17h-.4c-3.6 0-6.5-2.7-8.6-10z'/>"
    ),
    "instagram": _svg(
        "<rect x='4' y='4' width='16' height='16' rx='5'/><circle cx='12' cy='12' r='3.6'/><circle cx='17' cy='7' r='1'/>"
    ),
    "whatsapp_business": _svg(
        "<path d='M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z'/><path d='M9 9.5c0 3 2.5 5.5 5.5 5.5.6 0 1-.5 1-.5l-1.5-1-1 .6c-1-.4-1.8-1.2-2.2-2.2l.6-1-1-1.5s-.5.4-.5 1.1z'/>"
    ),
    "odnoklassniki": _svg(
        "<circle cx='12' cy='7.5' r='3.3'/><path d='M8 13c1.2 1 2.5 1.5 4 1.5S14.8 14 16 13'/><path d='m9 19 3-3 3 3'/><path d='M12 14.5V17'/>"
    ),
    "tenchat": _svg(
        "<rect x='4' y='7' width='16' height='12' rx='2.5'/><path d='M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7'/><path d='M8 12h8'/>"
    ),
    "linkedin": _svg(
        "<rect x='4' y='4' width='16' height='16' rx='3'/><path d='M8 11v5'/><path d='M8 8v.01'/><path d='M12 16v-3a2 2 0 0 1 4 0v3'/><path d='M12 16v-5'/>"
    ),
    "x_twitter": _svg(
        "<path d='M5 5l14 14'/><path d='M19 5 5 19'/><path d='M5 5h3l11 14h-3z' stroke-width='0.9'/>"
    ),
    "threads": _svg(
        "<path d='M15.5 12c0-2.2-1.3-3.7-3.4-3.7-1.8 0-3 1-3.1 2.6M8 13.5c.2 2 1.7 3.3 3.8 3.3 2.4 0 3.7-1.5 3.7-3.6 0-2.3-1.9-3.2-4-3.2-1.2 0-2 .5-2 1.4 0 .8.7 1.3 1.6 1.3 1.3 0 2.1-1 2.1-2.7'/><path d='M12 4a8 8 0 1 0 0 16'/>"
    ),
    "facebook_page": _svg(
        "<rect x='4' y='4' width='16' height='16' rx='4'/><path d='M14 8h-1.3c-.9 0-1.4.6-1.4 1.5V11H14M10 11h4M12.3 11v6'/>"
    ),
    "pikabu": _svg(
        "<rect x='5' y='4' width='14' height='14' rx='3'/><path d='M9 10h.01M15 10h.01'/><path d='M9.5 13.5c.7.7 1.6 1 2.5 1s1.8-.3 2.5-1'/><path d='m9 18-1.5 2M15 18l1.5 2'/>"
    ),
    # Видео
    "youtube": _svg(
        "<rect x='3.5' y='6' width='17' height='12' rx='3.5'/><path d='m11 9.5 4 2.5-4 2.5z'/>"
    ),
    "rutube": _svg(
        "<rect x='3.5' y='6' width='17' height='12' rx='3.5'/><path d='m11 9.5 4 2.5-4 2.5z'/><path d='M7 9v6' stroke-width='1.4'/>"
    ),
    "tiktok": _svg(
        "<path d='M13 5v9.5a3.2 3.2 0 1 1-3.2-3.2c.4 0 .8.1 1.2.2'/><path d='M13 5c.4 2 1.8 3.4 3.8 3.6'/>"
    ),
    # Блоги / медиа
    "dzen": _svg(
        "<path d='M12 3c.4 4 1 5.6 4.8 6.2C13 9.7 12.4 11.6 12 15c-.4-3.4-1-5.3-4.8-5.8C11 8.6 11.6 7 12 3z'/><circle cx='12' cy='12' r='9' stroke-width='1.2'/>"
    ),
    "vc_ru": _svg(
        "<rect x='4' y='5' width='16' height='12' rx='2.5'/><path d='M7 9h6M7 12h8'/><path d='M8 17l-1 2 3-2z'/>"
    ),
    "blog_cms": _svg(
        "<path d='M7 4h7l4 4v12H7z'/><path d='M14 4v4h4'/><path d='M9.5 12h5M9.5 15h5'/>"
    ),
    "pinterest": _svg(
        "<circle cx='12' cy='12' r='8.5'/><path d='M11 16.5 12.4 10a2.2 2.2 0 1 1 2 1.6c-1 .6-2.2 0-2.2 0'/>"
    ),
    # Сайт / e-mail
    "website": _svg(
        "<circle cx='12' cy='12' r='8.5'/><path d='M3.5 12h17M12 3.5c2.5 2.4 2.5 14.6 0 17M12 3.5c-2.5 2.4-2.5 14.6 0 17'/>"
    ),
    "email": _svg("<rect x='3.5' y='6' width='17' height='12' rx='2.5'/><path d='m4 8 8 5 8-5'/>"),
    # Хранилища
    "yandex_disk": _svg(
        "<path d='M7 18a4 4 0 0 1-.6-7.95A5 5 0 0 1 16 9.2 3.5 3.5 0 0 1 17 18z'/><path d='M9 15.5h6' stroke-width='1.3'/>"
    ),
    "google_drive": _svg(
        "<path d='M9.5 4h5L21 15h-5z'/><path d='M9.5 4 4 14l2.5 4L12 8.5z' stroke-width='1.3'/><path d='M6.5 18h9l2.5-3H9z' stroke-width='1.3'/>"
    ),
    # Справочники / маркетплейсы
    "two_gis": _svg(
        "<path d='M12 21c4-4.5 6-7.6 6-10a6 6 0 1 0-12 0c0 2.4 2 5.5 6 10z'/><circle cx='12' cy='11' r='2.4'/>"
    ),
    "avito": _svg(
        "<rect x='4' y='5' width='16' height='14' rx='2.5'/><circle cx='9' cy='10' r='1.6'/><path d='M13 9h4M13 12h4M7 15h10'/>"
    ),
}

# Запасная иконка (розетка/подключение) для платформ без своей иконки.
FALLBACK_ICON_SVG: str = _svg(
    "<path d='M9 7V4M15 7V4'/><rect x='7' y='7' width='10' height='7' rx='2'/>"
    "<path d='M12 14v3a3 3 0 0 1-3 3'/>"
)


def platform_icon_svg(key: str) -> str:
    """Вернуть inline SVG-иконку платформы (или запасную)."""
    return PLATFORM_ICON_SVG.get(key, FALLBACK_ICON_SVG)
