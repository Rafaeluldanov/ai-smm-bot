"""SaaS личный кабинет Botfleet (server-rendered HTML, без сборки/зависимостей/CDN).

Каждая страница ``/ui/*`` — самодостаточный HTML со встроенными CSS и vanilla-JS,
который обращается к существующим JSON-API (``/auth``, ``/saas``, ``/billing``).
Dev-токен и активный ``account_id`` хранятся в ``localStorage``.

Брендинг Botfleet (inline SVG-логотип «флот ботов»/нейро-орбита), светлая/тёмная
тема (переключатель в header; выбор в ``localStorage['botfleet_theme']``,
``data-theme`` на ``<html>``; все цвета — через CSS-переменные) и раздел «Гайд»
(``/ui/guide``) с инструкциями по подключению.

Личный кабинет:
- общий header: справа email/имя, баланс активного аккаунта и dropdown
  (Пополнить счёт / Выйти); гостю — кнопки Войти/Регистрация;
- левый sidebar на страницах кабинета: Проекты (со списком) / Тарифы /
  Аналитика / Настройки;
- упрощённая форма нового проекта, массовый импорт ключевых слов, платформы,
  медиа-источники, категории продвижения рядом с расписанием;
- дашборд проекта с карточками платформ; планировщик расписания внутри платформы.

Безопасность UI:
- ``api_key`` вводится в ``<input type=password>`` и очищается после отправки —
  секрет не показывается повторно; сервер возвращает только маску/флаг наличия;
- живые публикации выключены: чекбокса включения ``live_enabled`` в UI нет,
  на форму уходит ``live_enabled:false``; ``auto_publish`` не предлагается;
- пользовательские значения (имена аккаунтов/проектов, теги) экранируются
  хелпером ``esc()`` перед вставкой в ``innerHTML`` — защита от stored XSS;
- HTML статичен и НЕ содержит серверных секретов/токенов; реальных платежей нет.
"""

import html
import json
import re

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.services.unit_economics_service import UnitEconomicsService

router = APIRouter(prefix="/ui", tags=["ui"])


def _safe_slug(value: str) -> str:
    """Нормализовать сегмент пути (тип платформы) в безопасный slug.

    Отсекает любые HTML/JS-спецсимволы из path-параметра — защита от reflected XSS
    при вставке в ``<title>`` и в JS-константу ``PLATFORM``.
    """
    cleaned = re.sub(r"[^a-z0-9_-]", "", value.lower())[:20]
    return cleaned or "platform"


_DARK_VARS = (
    "--bg:#0d0f14;--surface:#171a21;--surface-soft:#12141a;--text:#e7e9ee;--muted:#98a2b3;"
    "--border:#262b36;--accent:#6ea0ff;--accent-soft:rgba(110,160,255,.16);--danger:#ff6b6b;"
    "--success:#3ecf8e;--shadow:rgba(0,0,0,.45);--input-bg:#10131a;--button-bg:#4f8cff"
)

_CSS = (
    """
/* Светлая тема — база; тёмная — [data-theme=dark] или prefers-color-scheme. */
:root{--bg:#f5f6f9;--surface:#ffffff;--surface-soft:#fbfcfe;--text:#161a20;--muted:#5f6b7a;--border:#e6e8ee;--accent:#4f8cff;--accent-soft:rgba(79,140,255,.12);--danger:#e5484d;--success:#2f9e6f;--shadow:rgba(16,24,40,.08);--input-bg:#f4f6f9;--button-bg:#4f8cff;--card:var(--surface);--fg:var(--text);--err:var(--danger);--ok:var(--success);--sb:var(--surface-soft)}
:root[data-theme="dark"]{"""
    + _DARK_VARS
    + """}
@media (prefers-color-scheme: dark){:root:not([data-theme]){"""
    + _DARK_VARS
    + """}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.topbar{display:flex;align-items:center;gap:12px;padding:10px 18px;background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;color:var(--text);font-size:16px}
.brand:hover{text-decoration:none}
.brandlogo{flex:0 0 auto;display:block}
.brandlogo .orbit{fill:none;stroke:var(--border);stroke-width:1.2}
.brandlogo .orbit.o2{stroke:var(--accent-soft)}
.brandlogo .lnk{stroke:var(--accent);stroke-width:1;opacity:.4}
.brandlogo .node{fill:var(--muted)}
.brandlogo .node.hot{fill:var(--accent)}
.brandlogo .core{fill:var(--accent)}
.page-ctx{color:var(--muted);font-size:13px;border-left:1px solid var(--border);padding-left:12px}
.spacer{flex:1}
.themebtn{background:transparent;border:1px solid var(--border);color:var(--text);border-radius:10px;min-width:38px;height:34px;padding:0 8px;font-size:15px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
.themebtn:hover{background:var(--accent-soft)}
.acctbox{position:relative}
.acctbtn{display:flex;align-items:center;gap:8px;background:transparent;color:var(--text);border:1px solid var(--border);border-radius:22px;padding:5px 12px;cursor:pointer;font:inherit}
.acctbtn .uicon{width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.acctbtn .caret{color:var(--muted)}
.menu{position:absolute;right:0;top:112%;background:var(--surface);border:1px solid var(--border);border-radius:10px;min-width:190px;box-shadow:0 10px 30px var(--shadow);overflow:hidden;z-index:30}
.menu a{display:block;padding:10px 14px;color:var(--text)}
.menu a:hover{background:var(--surface-soft);text-decoration:none}
.layout{display:grid;grid-template-columns:240px 1fr;min-height:calc(100vh - 54px)}
.layout.nosb{grid-template-columns:1fr}
.sidebar{background:var(--surface-soft);border-right:1px solid var(--border);padding:14px 12px}
.brand-full{display:flex;align-items:center;gap:10px;padding:2px 4px 14px;margin-bottom:6px;border-bottom:1px solid var(--border);color:var(--text)}
.brand-full:hover{text-decoration:none}
.brand-full .brand-name{font-weight:700;font-size:16px;line-height:1.1}
.brand-full .brand-tag{display:block;font-weight:500;font-size:11px;color:var(--muted);letter-spacing:.02em}
.sb-group{margin-bottom:10px}
.sb-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
.sb-title{font-weight:600;color:var(--text);font-size:14px;letter-spacing:.02em}
.sb-add{display:inline-flex;width:26px;height:26px;align-items:center;justify-content:center;border:1px solid var(--border);border-radius:7px;color:var(--accent);line-height:1}
.sb-add:hover{background:var(--surface);text-decoration:none}
.sb-projects{margin:8px 0 4px;display:flex;flex-direction:column;gap:2px}
.sb-proj{display:block;padding:6px 9px;border-radius:7px;color:var(--text);font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sb-proj:hover{background:var(--surface);text-decoration:none}
.sb-proj.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
.sb-hint{padding:6px 9px;font-size:12px}
.sb-link{display:block;padding:8px 9px;border-radius:7px;color:var(--text);margin-top:2px;font-size:14px}
.sb-link:hover{background:var(--surface);text-decoration:none}
.sb-link.active,.sb-title.active{color:var(--accent);background:var(--accent-soft)}
.sb-link.active{font-weight:600}
.content{padding:22px 26px;max-width:1000px}
.content.narrow{max-width:560px;margin:0 auto}
h1{font-size:22px;margin:0 0 8px}h2{font-size:16px;margin:22px 0 6px}h3{margin:0 0 6px;font-size:15px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin:14px 0;box-shadow:0 1px 2px var(--shadow)}
label{display:block;margin:8px 0 4px;color:var(--muted);font-size:13px}
label.chk{display:inline-flex;align-items:center;gap:6px;color:var(--text)}
input,select,textarea{width:100%;padding:8px 10px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;font:inherit}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent-soft);border-color:var(--accent)}
textarea{min-height:120px;resize:vertical}
input[type=checkbox]{width:auto}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;align-items:center;border:1px dashed var(--border);border-radius:8px;padding:10px;margin:8px 0}
.row input,.row select{width:100%}
button{background:var(--button-bg);color:#fff;border:0;border-radius:8px;padding:9px 14px;font:inherit;cursor:pointer}
button.sec{background:transparent;color:var(--accent);border:1px solid var(--accent)}
button.mini{padding:4px 10px;font-size:13px}
button.ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}
.muted{color:var(--muted);font-size:13px}
.inline{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.badge{display:inline-block;background:var(--border);border-radius:6px;padding:2px 8px;font-size:12px;color:var(--muted);margin:2px 4px 2px 0}
.pill{display:inline-block;border-radius:20px;padding:2px 10px;font-size:12px}
.pill.ok{background:var(--accent-soft);color:var(--success)}
.pill.off{background:rgba(154,164,178,.16);color:var(--muted)}
.err{display:none;background:rgba(229,72,77,.12);border:1px solid var(--danger);color:var(--danger);padding:10px;border-radius:8px;margin:10px 0;white-space:pre-wrap}
pre{display:none;background:var(--surface-soft);border:1px solid var(--border);border-radius:8px;padding:12px;overflow:auto;max-height:460px;white-space:pre-wrap;word-break:break-word}
table.kw{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
table.kw th,table.kw td{border:1px solid var(--border);padding:3px 4px;text-align:left}
table.kw input,table.kw select{border:0;background:transparent;padding:5px 4px}
.days{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.days label{display:inline-flex;align-items:center;gap:5px;margin:0;color:var(--text);font-size:14px}
.pcard{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px;box-shadow:0 1px 2px var(--shadow)}
.pcard .meta{color:var(--muted);font-size:13px;margin:4px 0 10px;word-break:break-word}
/* Карточка Instagram (справочные поля key/value) */
.ig-fields{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin:8px 0 4px}
.ig-fields>div{background:var(--surface-soft);border:1px solid var(--border);border-radius:9px;padding:8px 10px}
.ig-fields .k{display:block;font-size:12px;color:var(--muted);margin-bottom:2px}
.ig-fields .v{font-size:13px;color:var(--text);word-break:break-all}
.ig-fields code{background:transparent;padding:0}
code{background:var(--surface-soft);border:1px solid var(--border);border-radius:5px;padding:1px 5px;font-size:12px}
/* Гайд */
.hero{background:linear-gradient(135deg,var(--accent-soft),transparent);border:1px solid var(--border);border-radius:14px;padding:18px 22px;margin:4px 0 16px}
.hero p{color:var(--muted);margin:6px 0 0;max-width:660px}
.steps{list-style:none;counter-reset:st;padding:0;margin:8px 0 6px;display:grid;gap:8px}
.steps li{counter-increment:st;position:relative;padding:9px 12px 9px 42px;background:var(--surface-soft);border:1px solid var(--border);border-radius:9px}
.steps li::before{content:counter(st);position:absolute;left:10px;top:8px;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.guide-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.gcard{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;box-shadow:0 1px 2px var(--shadow)}
.gcard h3{display:flex;align-items:center;gap:8px}
.gcard ul{margin:6px 0 0;padding-left:18px;color:var(--text)}
.gcard li{margin:4px 0}
.faq details{border:1px solid var(--border);border-radius:10px;padding:8px 12px;margin:6px 0;background:var(--surface)}
.faq summary{cursor:pointer;font-weight:600;color:var(--text)}
.faq p{color:var(--muted);margin:8px 0 0}
.tag{display:inline-block;background:var(--accent-soft);color:var(--accent);border-radius:20px;padding:1px 9px;font-size:12px;font-weight:600}
/* Гайд: якорные быстрые ссылки, выбор платформы, блоки-выноски */
.quicklinks{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 18px}
.quicklinks a{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:5px 12px;font-size:13px;color:var(--text)}
.quicklinks a:hover{background:var(--accent-soft);border-color:var(--accent);text-decoration:none}
.platform-pick{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin:6px 0 16px}
.pick-card{display:block;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center;color:var(--text);box-shadow:0 1px 2px var(--shadow)}
.pick-card:hover{border-color:var(--accent);text-decoration:none;transform:translateY(-1px)}
.pick-card .ico{font-size:26px;line-height:1}
.pick-card b{display:block;margin-top:6px}
.pick-card .st{display:block;font-size:12px;color:var(--muted);margin-top:3px}
.callout{border-left:4px solid var(--accent);background:var(--accent-soft);padding:10px 12px;border-radius:8px;margin:10px 0}
.callout.warn{border-color:var(--danger);background:rgba(229,72,77,.10)}
.callout.ok{border-color:var(--success);background:rgba(47,158,111,.12)}
.callout b{display:block;margin-bottom:3px}
.callout ul{margin:6px 0 0;padding-left:18px}
.gcard ol{margin:6px 0 0;padding-left:18px;color:var(--text)}
.gcard ol li{margin:5px 0}
.subhint{color:var(--muted);font-size:13px;margin:2px 0 10px}
h2[id],h3[id]{scroll-margin-top:72px}
.anchor-h{display:flex;align-items:center;gap:8px}
/* Проектный dashboard: заголовок + действия + сетка платформ */
.proj-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:2px 0 4px}
.proj-head h1{margin:0}
.proj-actions{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 4px}
.ptiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin:8px 0 6px;align-items:stretch}
.ptile{display:flex;flex-direction:column;gap:6px;background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px;box-shadow:0 1px 2px var(--shadow);color:var(--text);min-height:150px;transition:transform .08s,border-color .08s}
.ptile:hover{border-color:var(--accent);transform:translateY(-2px);text-decoration:none;box-shadow:0 6px 18px var(--shadow)}
.ptile .ico{font-size:24px;line-height:1}
.ptile .pname{font-weight:700;font-size:15px}
.ptile .prow{font-size:12px;color:var(--muted);word-break:break-all}
.ptile .open{margin-top:auto;font-size:13px;color:var(--accent);font-weight:600}
.ptile.soon{opacity:.72}
/* Вкладки страницы платформы */
.tabs{display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid var(--border);margin:10px 0 14px}
.tab{background:transparent;border:1px solid transparent;border-bottom:0;color:var(--muted);border-radius:9px 9px 0 0;padding:8px 14px;cursor:pointer;font:inherit;font-size:14px}
.tab:hover{color:var(--text);background:var(--surface-soft)}
.tab.active{color:var(--accent);background:var(--surface);border-color:var(--border);font-weight:600}
.tabpane{display:none}
.tabpane.active{display:block}
.pw-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:2px 0 6px}
.pw-head .big{font-size:30px;line-height:1}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;margin:6px 0}
.kv>div{background:var(--surface-soft);border:1px solid var(--border);border-radius:9px;padding:8px 10px}
.kv .k{display:block;font-size:12px;color:var(--muted);margin-bottom:2px}
.kv .v{font-size:13px;color:var(--text);word-break:break-all}
/* Задачи расписания */
.sched-list{display:grid;gap:12px;margin:8px 0}
.sched-task{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px;box-shadow:0 1px 2px var(--shadow)}
.sched-task.paused{opacity:.6}
.sched-task h3{margin:0 0 4px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sched-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px;margin:8px 0}
.sched-grid .k{display:block;font-size:11px;color:var(--muted)}
.sched-grid .v{font-size:13px;color:var(--text)}
.sched-task .acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
/* Аналитика */
.an-filters{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;align-items:end}
.an-cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin:10px 0}
.an-cell{background:var(--surface-soft);border:1px solid var(--border);border-radius:7px;min-height:64px;padding:5px;font-size:11px;color:var(--muted)}
.an-cell .d{font-weight:700;color:var(--text)}
.an-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin:1px}
.an-dot.published{background:var(--success)}
.an-dot.scheduled{background:var(--accent)}
.an-dot.failed{background:var(--danger)}
.an-dot.needs_review{background:#c98a00}
.an-est{font-size:15px;font-weight:700;color:var(--accent)}
.price-table{width:100%;border-collapse:collapse;margin:8px 0;font-size:14px}
.price-table th,.price-table td{border:1px solid var(--border);padding:8px 10px;text-align:left}
.price-table th{background:var(--surface-soft);color:var(--muted);font-weight:600}
.price-table td.u{font-weight:700;color:var(--accent);white-space:nowrap}
@media (max-width:760px){.layout{grid-template-columns:1fr}.sidebar{border-right:0;border-bottom:1px solid var(--border)}.page-ctx{display:none}.an-cal{grid-template-columns:repeat(7,1fr)}}
"""
)

# Временный inline SVG-логотип Botfleet: ядро + орбитальные узлы («флот ботов» /
# нейро-орбита). Цвета — через CSS-переменные, адаптируется к light/dark. Без CDN.
_LOGO_SVG = (
    "<svg class='brandlogo' width='32' height='32' viewBox='0 0 36 36' "
    "role='img' aria-label='Botfleet'>"
    "<circle class='orbit' cx='18' cy='18' r='13.5'/>"
    "<circle class='orbit o2' cx='18' cy='18' r='7.5'/>"
    "<g class='lnks'>"
    "<line class='lnk' x1='18' y1='18' x2='18' y2='4.5'/>"
    "<line class='lnk' x1='18' y1='18' x2='29.7' y2='11.25'/>"
    "<line class='lnk' x1='18' y1='18' x2='29.7' y2='24.75'/>"
    "<line class='lnk' x1='18' y1='18' x2='18' y2='31.5'/>"
    "<line class='lnk' x1='18' y1='18' x2='6.3' y2='24.75'/>"
    "<line class='lnk' x1='18' y1='18' x2='6.3' y2='11.25'/>"
    "</g>"
    "<circle class='node hot' cx='18' cy='4.5' r='2.4'/>"
    "<circle class='node' cx='29.7' cy='11.25' r='2.2'/>"
    "<circle class='node' cx='29.7' cy='24.75' r='2.2'/>"
    "<circle class='node hot' cx='18' cy='31.5' r='2.2'/>"
    "<circle class='node' cx='6.3' cy='24.75' r='2.2'/>"
    "<circle class='node' cx='6.3' cy='11.25' r='2.2'/>"
    "<circle class='core' cx='18' cy='18' r='3.6'/>"
    "</svg>"
)

BRAND_NAME = "Botfleet"
BRAND_TAGLINE = "ИИ-флот для автопостинга"


def _brand_full() -> str:
    """Полный бренд (логотип + название + подпись) — для верха sidebar."""
    return (
        "<a class='brand-full' href='/ui/'>"
        f"{_LOGO_SVG}<span class='brand-text'>"
        f"<span class='brand-name'>{BRAND_NAME}</span>"
        f"<span class='brand-tag'>{BRAND_TAGLINE}</span></span></a>"
    )


def _header(title: str) -> str:
    """Верхний header: бренд + контекст страницы + переключатель темы + аккаунт.

    Метки dropdown (Пополнить счёт / Выйти) и кнопки гостя присутствуют в HTML
    всегда — JS лишь переключает видимость и подставляет имя/баланс.
    """
    ctx = html.escape(title)
    return (
        "<header class='topbar'>"
        f"<a class='brand' href='/ui/' title='{BRAND_NAME}'>{_LOGO_SVG}"
        f"<span class='brand-name'>{BRAND_NAME}</span></a>"
        f"<span class='page-ctx'>{ctx}</span>"
        "<span class='spacer'></span>"
        "<button id='themebtn' class='themebtn' onclick='toggleTheme()' "
        "title='Переключить тему: Светлая / Тёмная (День / Ночь)' "
        "aria-label='Переключить тему'><span id='themeicon'>🌙</span></button>"
        "<div id='acctbox' class='acctbox'>"
        "<div class='guest'>"
        "<a href='/ui/login'><button class='sec mini'>Войти</button></a> "
        "<a href='/ui/register'><button class='mini'>Регистрация</button></a>"
        "</div>"
        "<div class='acctwrap' style='display:none'>"
        "<button class='acctbtn' onclick='toggleAcctMenu(event)'>"
        "<span class='uicon'>👤</span><span id='acct-label'>…</span>"
        "<span class='caret'>▾</span></button>"
        "<div id='acctmenu' class='menu' style='display:none'>"
        "<a href='/ui/billing'>Пополнить счёт</a>"
        "<a href='#' onclick='logout();return false'>Выйти</a>"
        "</div></div></div></header>"
    )


# Общие JS-помощники: токен/аккаунт, fetch с Authorization, esc/XSS, инициализация
# header+sidebar (initShell) на каждой странице кабинета.
_SHARED_JS = r"""
function tok(){return localStorage.getItem('smm_token')||''}
function setTok(t){localStorage.setItem('smm_token',t)}
function acc(){return localStorage.getItem('smm_account_id')||''}
function setAcc(id){localStorage.setItem('smm_account_id',String(id))}
function logout(){localStorage.removeItem('smm_token');localStorage.removeItem('smm_account_id');location.href='/ui/login'}
async function api(method,path,body,auth){
  const h={'Content-Type':'application/json'};
  if(auth!==false && tok()) h['Authorization']=tok();
  const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  let d=null; try{d=await r.json()}catch(e){}
  if(!r.ok){throw new Error((d&&(d.detail||JSON.stringify(d)))||('HTTP '+r.status))}
  return d;
}
function err(el,e){if(!el)return;el.textContent=String(e&&e.message?e.message:e);el.style.display='block'}
function json(el,o){if(!el)return;el.textContent=JSON.stringify(o,null,2);el.style.display='block'}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function gv(id){const el=document.getElementById(id);if(!el)return '';return el.type==='checkbox'?el.checked:el.value.trim()}
function gl(id){const v=gv(id);return v?String(v).split(',').map(s=>s.trim()).filter(Boolean):[]}
function needAccount(el){const a=parseInt(acc());if(!a){err(el,new Error('Войдите в аккаунт (кнопки Войти/Регистрация справа сверху).'));return 0}return a}
function slugify(s){
  const m={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'};
  return String(s||'').toLowerCase().split('').map(c=>m[c]!==undefined?m[c]:c).join('')
    .replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,50)||'project';
}
function toggleAcctMenu(e){if(e)e.stopPropagation();const m=document.getElementById('acctmenu');if(m)m.style.display=(m.style.display==='none'||!m.style.display)?'block':'none';}
function copyText(t){t=String(t==null?'':t);
  if(navigator.clipboard&&navigator.clipboard.writeText){return navigator.clipboard.writeText(t);}
  try{const ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();document.execCommand('copy');document.body.removeChild(ta);return Promise.resolve();}catch(e){return Promise.reject(e);}}
function toggleCalendar(){const p=document.getElementById('calpanel');if(p)p.style.display=(p.style.display==='none'||!p.style.display)?'block':'none';}
/* Тема: localStorage['botfleet_theme'] = light|dark; на <html> data-theme. */
function getTheme(){const t=localStorage.getItem('botfleet_theme');if(t==='light'||t==='dark')return t;return (window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);const i=document.getElementById('themeicon');if(i)i.textContent=(t==='dark'?'☀️':'🌙');const b=document.getElementById('themebtn');if(b)b.title=(t==='dark'?'Тёмная тема (Ночь) — нажмите для Светлой':'Светлая тема (День) — нажмите для Тёмной');}
function toggleTheme(){const next=getTheme()==='dark'?'light':'dark';localStorage.setItem('botfleet_theme',next);applyTheme(next);}
function initTheme(){applyTheme(getTheme());}
async function vkCheck(rid){
  const el=document.getElementById('vkchk-'+rid); if(!el)return;
  el.textContent='Проверка доступа…';
  try{
    const r=await api('POST','/integrations/vk/oauth/check?resource_id='+rid);
    if(!r.connected){el.innerHTML="<span class='muted'>"+esc(r.message||'VK не подключён')+"</span>";return;}
    const yn=b=>b?'✔':'✗';
    el.innerHTML=`Аккаунт VK: ${yn(r.user_ok)}<br>Админ группы: ${yn(r.group_visible)}<br>Загрузка фото: ${yn(r.photo_upload_ok)}`
      +(r.message?`<br><span class='muted'>${esc(r.message)}</span>`:'')
      +((r.warnings&&r.warnings.length)?`<br><span class='muted'>${esc(r.warnings.join('; '))}</span>`:'');
  }catch(x){el.innerHTML="<span style='color:var(--err)'>"+esc(x&&x.message?x.message:x)+"</span>";}
}
document.addEventListener('click',()=>{const m=document.getElementById('acctmenu');if(m)m.style.display='none';});
async function initShell(){
  const box=document.getElementById('acctbox');
  const sb=document.getElementById('sb-projects');
  if(!tok()){ if(sb) sb.innerHTML="<div class='muted sb-hint'>Войдите, чтобы увидеть проекты.</div>"; return; }
  let me;
  try{ me=await api('GET','/auth/me'); }
  catch(e){ if(sb) sb.innerHTML="<div class='muted sb-hint'>Сессия истекла — войдите заново.</div>"; return; }
  let aid=acc();
  if(!aid && me.accounts && me.accounts[0]){ aid=me.accounts[0].id; setAcc(aid); }
  if(box){
    const name=me.user.full_name||me.user.email||'аккаунт';
    let bal='';
    if(aid){ try{ const b=await api('GET','/billing/account/'+aid+'/balance'); bal=' · '+b.balance_units+' units'; }catch(e){} }
    const lbl=document.getElementById('acct-label'); if(lbl) lbl.innerHTML=esc(name)+esc(bal);
    const g=box.querySelector('.guest'); if(g) g.style.display='none';
    const w=box.querySelector('.acctwrap'); if(w) w.style.display='';
  }
  if(sb){
    if(!aid){ sb.innerHTML="<div class='muted sb-hint'>Нет аккаунтов.</div>"; return; }
    try{
      const ps=await api('GET','/saas/accounts/'+aid+'/projects');
      const apid=String(window.ACTIVE_PID==null?'':window.ACTIVE_PID);
      sb.innerHTML = ps.length
        ? ps.map(p=>`<a class='sb-proj${String(p.id)===apid?' active':''}' href='/ui/projects/${p.id}/dashboard' title='${esc(p.name)}'>${esc(p.name)}</a>`).join('')
        : "<div class='muted sb-hint'>Проектов нет. Создайте новый.</div>";
    }catch(e){ sb.innerHTML="<div class='muted sb-hint'>—</div>"; }
  }
}
initTheme();
initShell();
"""


def _sidebar(active: str = "") -> str:
    """Левый sidebar: бренд Botfleet + Проекты (список) / Тарифы / Аналитика / Гайд / Настройки."""

    def cls(key: str) -> str:
        return " active" if active == key else ""

    return (
        "<aside class='sidebar'>"
        f"{_brand_full()}"
        "<div class='sb-group'><div class='sb-head'>"
        f"<a class='sb-title{cls('projects')}' href='/ui/projects'>Проекты</a>"
        "<a class='sb-add' href='/ui/projects/new' title='Новый проект'>+</a></div>"
        "<div id='sb-projects' class='sb-projects'><div class='muted sb-hint'>…</div></div></div>"
        f"<a class='sb-link{cls('tariffs')}' href='/ui/tariffs'>Тарифы</a>"
        f"<a class='sb-link{cls('analytics')}' href='/ui/analytics'>Аналитика</a>"
        f"<a class='sb-link{cls('guide')}' href='/ui/guide'>Гайд</a>"
        f"<a class='sb-link{cls('settings')}' href='/ui/settings'>Настройки</a>"
        "</aside>"
    )


def _page(
    title: str,
    body: str,
    script: str = "",
    active: str = "",
    sidebar: bool = True,
    active_pid: int | None = None,
) -> HTMLResponse:
    """Собрать страницу кабинета: header + (опционально) sidebar + контент."""
    esc_title = html.escape(title)
    main_cls = "content" if sidebar else "content narrow"
    layout_cls = "layout" if sidebar else "layout nosb"
    aside = _sidebar(active) if sidebar else ""
    inner = f"{aside}<main class='{main_cls}'><h1>{esc_title}</h1>{body}</main>"
    # Ранняя установка темы в <head> — до рендера, чтобы не мигало (FOUC). Плюс
    # активный проект (для подсветки в sidebar).
    active_pid_js = f"window.ACTIVE_PID={int(active_pid)};" if active_pid is not None else ""
    theme_init = (
        "<script>(function(){try{var t=localStorage.getItem('botfleet_theme');"
        "if(t!=='light'&&t!=='dark'){t=(window.matchMedia&&"
        "window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}"
        "document.documentElement.setAttribute('data-theme',t);}catch(e){}})();"
        f"{active_pid_js}</script>"
    )
    document = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc_title} — {BRAND_NAME}</title><style>{_CSS}</style>{theme_init}</head><body>"
        f"{_header(title)}<div class='{layout_cls}'>{inner}</div>"
        f"<script>{_SHARED_JS}</script><script>{script}</script></body></html>"
    )
    return HTMLResponse(document)


# --------------------------------------------------------------------------- #
# Публичные страницы (без sidebar): лендинг, вход, регистрация                 #
# --------------------------------------------------------------------------- #


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ui_index() -> HTMLResponse:
    body = (
        "<div class='card'>Личный кабинет «Бот СММ». Реальных платежей нет (внутренние units), "
        "живые публикации выключены, все прогоны — dry-run / на ревью.</div>"
        "<div class='card inline'>"
        "<a href='/ui/register'><button>Регистрация</button></a>"
        "<a href='/ui/login'><button class='sec'>Вход</button></a>"
        "<a href='/ui/projects'><button class='sec'>Мои проекты</button></a>"
        "</div><p class='muted' id='who'></p>"
    )
    script = (
        "(async()=>{try{if(tok()){const me=await api('GET','/auth/me');"
        "document.getElementById('who').innerHTML='Вы вошли как '+esc(me.user.email)+' · аккаунтов: '+me.accounts.length;}"
        "}catch(e){}})();"
    )
    return _page("Личный кабинет", body, script, sidebar=False)


@router.get("/register", response_class=HTMLResponse)
def ui_register() -> HTMLResponse:
    body = (
        "<div class='card'><form id='f'>"
        "<label>Email</label><input id='email' type='email' required>"
        "<label>Пароль (мин. 8 символов)</label><input id='password' type='password' minlength='8' required autocomplete='new-password'>"
        "<label>Имя</label><input id='full_name'>"
        "<label>Название рабочего пространства</label><input id='account_name'>"
        "<div style='margin-top:12px'><button>Зарегистрироваться</button></div>"
        "</form><div id='error' class='err'></div></div>"
        "<p class='muted'>Уже есть аккаунт? <a href='/ui/login'>Войти</a></p>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();"
        "try{const d=await api('POST','/auth/register',{email:gv('email'),password:gv('password'),"
        "full_name:gv('full_name')||null,account_name:gv('account_name')||null},false);"
        "setTok(d.token); if(d.accounts&&d.accounts[0]) setAcc(d.accounts[0].id);"
        "location.href='/ui/projects';}catch(x){err(eEl,x)}});"
    )
    return _page("Регистрация", body, script, sidebar=False)


@router.get("/login", response_class=HTMLResponse)
def ui_login() -> HTMLResponse:
    body = (
        "<div class='card'><form id='f'>"
        "<label>Email</label><input id='email' type='email' required>"
        "<label>Пароль</label><input id='password' type='password' required autocomplete='current-password'>"
        "<div style='margin-top:12px'><button>Войти</button></div>"
        "</form><div id='error' class='err'></div></div>"
        "<p class='muted'>Нет аккаунта? <a href='/ui/register'>Регистрация</a></p>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();"
        "try{const d=await api('POST','/auth/login',{email:gv('email'),password:gv('password')},false);"
        "setTok(d.token); if(d.accounts&&d.accounts[0]) setAcc(d.accounts[0].id);"
        "location.href='/ui/projects';}catch(x){err(eEl,x)}});"
    )
    return _page("Вход", body, script, sidebar=False)


# --------------------------------------------------------------------------- #
# Кабинет: аккаунты, проекты                                                  #
# --------------------------------------------------------------------------- #


@router.get("/accounts", response_class=HTMLResponse)
def ui_accounts() -> HTMLResponse:
    body = (
        "<div class='card'><div id='list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');const L=document.getElementById('list');"
        "(async()=>{try{const me=await api('GET','/auth/me');"
        "if(!me.accounts.length){L.textContent='Нет аккаунтов.';return}"
        "const cur=acc();"
        "L.innerHTML=me.accounts.map(a=>`<div class='inline' style='margin:6px 0'>`"
        "+`<span class='badge'>#${a.id}</span> <b>${esc(a.name)}</b> <span class='muted'>(${esc(a.slug)})</span>`"
        "+(String(a.id)===String(cur)?` <span class='pill ok'>активный</span>`:` <button class='mini sec' onclick='setAcc(${a.id});location.reload()'>Выбрать</button>`)+`</div>`).join('');"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Аккаунты", body, script, active="settings")


@router.get("/projects", response_class=HTMLResponse)
def ui_projects() -> HTMLResponse:
    body = (
        "<div class='inline'><a href='/ui/projects/new'><button>+ Новый проект</button></a></div>"
        "<div class='card'><div id='list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');const L=document.getElementById('list');"
        "(async()=>{const a=needAccount(eEl);if(!a)return;try{"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "if(!ps.length){L.innerHTML=\"Проектов нет. <a href='/ui/projects/new'>Создайте новый.</a>\";return}"
        "L.innerHTML=ps.map(p=>`<div class='inline' style='margin:8px 0'>`"
        "+`<span class='badge'>#${p.id}</span> <a href='/ui/projects/${p.id}/dashboard'><b>${esc(p.name)}</b></a> <span class='muted'>(${esc(p.slug)})</span>`"
        "+` <a href='/ui/projects/${p.id}/dashboard'><button class='mini sec'>Дашборд</button></a>`"
        "+` <a href='/ui/projects/${p.id}/settings'><button class='mini ghost'>Настройки</button></a></div>`).join('');"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Проекты", body, script, active="projects")


# --------------------------------------------------------------------------- #
# Форма нового проекта                                                         #
# --------------------------------------------------------------------------- #

# JS формы: repeatable-секции, массовый разбор ключей, сбор payload, preview/apply.
_FORM_JS = r"""
const PLATFORMS=['vk','telegram','instagram','youtube','rutube','other'];
const SOURCES=['yandex_disk','google_drive','manual','upload','website','other'];
const WEEKDAYS=[['0','Пн'],['1','Вт'],['2','Ср'],['3','Чт'],['4','Пт'],['5','Сб'],['6','Вс']];
function opts(arr,sel){return arr.map(o=>`<option${o===sel?' selected':''}>${o}</option>`).join('')}
function rv(r,n){const el=r.querySelector('[name="'+n+'"]');return el?String(el.value).trim():''}
function rl(r,n){const v=rv(r,n);return v?v.split(',').map(s=>s.trim()).filter(Boolean):[]}
function kvparse(s){const o={};(s||'').split(',').map(x=>x.trim()).filter(Boolean).forEach(p=>{const i=p.indexOf(':');if(i>0){o[p.slice(0,i).trim()]=parseInt(p.slice(i+1).trim())||0}});return o}

function tpl(kind){
  if(kind==='media_sources') return "<div class='row'>"
    +"<select name='source_type'>"+opts(SOURCES)+"</select>"
    +"<input name='title' placeholder='название'>"
    +"<input name='url' placeholder='ссылка'>"
    +"<input name='root_folder' placeholder='корневая папка'>"
    +"<input name='media_tags' placeholder='медиа-теги через запятую'>"
    +"<button type='button' class='mini ghost' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='platforms') return "<div class='row'>"
    +"<input name='title' placeholder='название'>"
    +"<select name='platform_type'>"+opts(PLATFORMS)+"</select>"
    +"<input name='external_id' placeholder='ID (group/channel)'>"
    +"<input name='url' placeholder='ссылка'>"
    +"<input name='api_key' type='password' autocomplete='off' placeholder='API-ключ/токен (секрет)'>"
    +"<input name='tags' placeholder='теги через запятую'>"
    +"<input name='keywords' placeholder='ключи через запятую'>"
    +"<span class='pill off' title='Живые публикации выключены на этом этапе'>live: выкл</span>"
    +"<button type='button' class='mini ghost' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='categories') return "<div class='row'>"
    +"<input name='title' placeholder='название категории *'>"
    +"<input name='description' placeholder='описание/ракурс'>"
    +"<input name='product_priorities' placeholder='продукты: футболки:5, худи:3'>"
    +"<input name='technology_priorities' placeholder='технологии: DTF-печать:5'>"
    +"<input name='media_tags' placeholder='медиа-теги через запятую'>"
    +"<input name='keyword_queries' placeholder='ключи (запросы) через запятую'>"
    +"<input name='cta' placeholder='призыв к действию'>"
    +"<input name='default_site_url' placeholder='ссылка по умолчанию'>"
    +"<button type='button' class='mini ghost' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='plans'){
    const wd=WEEKDAYS.map(w=>`<label><input type='checkbox' class='wd' value='${w[0]}'>${w[1]}</label>`).join('');
    return "<div class='row plan'>"
      +"<input name='name' placeholder='название плана'>"
      +"<select name='platform'>"+opts(PLATFORMS)+"</select>"
      +"<input name='category_title' placeholder='тег/категория (необязательно)'>"
      +"<input name='start_date' type='date'>"
      +"<input name='end_date' type='date'>"
      +"<input name='publish_times' placeholder='время HH:MM через запятую' value='10:00'>"
      +"<input name='posts_per_day' type='number' min='1' value='1'>"
      +"<select name='mode'><option value='draft'>draft</option><option value='semi_auto'>semi_auto</option></select>"
      +"<div class='days' style='grid-column:1/-1'>Дни: "+wd+"</div>"
      +"<button type='button' class='mini ghost' onclick='this.closest(\".plan\").remove()'>✕ удалить план</button></div>";
  }
  return '';
}
function addRow(id){const c=document.getElementById(id);if(c)c.insertAdjacentHTML('beforeend',tpl(id));}

// --- Массовый импорт ключевых слов --- //
function kwHeuristics(q){
  const s=q.toLowerCase();let product='',technology='';
  if(/футболк|маек|поло/.test(s))product='футболки';
  else if(/худи/.test(s))product='худи';
  else if(/свитшот/.test(s))product='свитшоты';
  else if(/лонгслив/.test(s))product='лонгсливы';
  else if(/кепк|бейсболк/.test(s))product='кепки';
  else if(/жилет/.test(s))product='жилетки';
  else if(/куртк/.test(s))product='куртки';
  else if(/дождевик/.test(s))product='дождевики';
  if(/dtf|дтф/.test(s))technology='DTF-печать';
  else if(/вышив/.test(s))technology='вышивка';
  else if(/гравиров/.test(s))technology='гравировка';
  else if(/уф/.test(s))technology='УФ-печать';
  else if(/шелкограф/.test(s))technology='шелкография';
  return {product,technology};
}
function parseKwLine(line){
  const parts=String(line).split(/[\t;,]+|\s+/).map(s=>s.trim()).filter(Boolean);
  if(!parts.length) return null;
  let freq=0; const last=parts[parts.length-1];
  if(/^\d+$/.test(last)){ freq=parseInt(last,10); parts.pop(); }
  const query=parts.join(' ').trim();
  if(!query) return null;
  const h=kwHeuristics(query);
  return {query,frequency:freq,product:h.product,technology:h.technology,cluster:'',priority:freq};
}
function kwRowHtml(r){
  return "<tr>"
    +`<td><input value="${esc(r.query)}"></td>`
    +`<td><input type="number" value="${r.frequency||0}" style="max-width:70px"></td>`
    +`<td><input value="${esc(r.product||'')}"></td>`
    +`<td><input value="${esc(r.technology||'')}"></td>`
    +`<td><input value="${esc(r.cluster||'')}"></td>`
    +`<td><input type="number" value="${r.priority||0}" style="max-width:70px"></td>`
    +"<td><button type='button' class='mini ghost' onclick='this.closest(\"tr\").remove()'>✕</button></td></tr>";
}
function parseKeywords(){
  const ta=document.getElementById('kw_bulk');const tb=document.querySelector('#kwtable tbody');
  if(!ta||!tb)return;
  const rows=ta.value.split(/\n+/).map(parseKwLine).filter(Boolean);
  tb.insertAdjacentHTML('beforeend',rows.map(kwRowHtml).join(''));
  ta.value='';
}
function addKwRow(){const tb=document.querySelector('#kwtable tbody');if(tb)tb.insertAdjacentHTML('beforeend',kwRowHtml({query:'',frequency:0,priority:0}));}
function clearKw(){const tb=document.querySelector('#kwtable tbody');if(tb)tb.innerHTML='';}
function loadKwFile(input){
  const f=input.files&&input.files[0];if(!f)return;
  const rd=new FileReader();
  rd.onload=()=>{const ta=document.getElementById('kw_bulk');if(ta){ta.value=(ta.value?ta.value+'\n':'')+rd.result;parseKeywords();}};
  rd.readAsText(f);input.value='';
}
function collectKeywords(){
  return [...document.querySelectorAll('#kwtable tbody tr')].map(tr=>{
    const c=tr.querySelectorAll('input');
    return {query:c[0].value.trim(),frequency:parseInt(c[1].value)||0,product:c[2].value.trim()||null,
      technology:c[3].value.trim()||null,cluster:c[4].value.trim(),priority:parseInt(c[5].value)||0,intent:'commercial'};
  }).filter(k=>k.query);
}

function collectMedia(){
  return [...document.querySelectorAll('#media_sources .row')].map(r=>({
    source_type:rv(r,'source_type'),title:rv(r,'title'),url:rv(r,'url')||null,
    root_folder:rv(r,'root_folder')||null,media_tags:rl(r,'media_tags')}))
    .filter(m=>m.title||m.url||m.root_folder||m.media_tags.length);
}
function collectPlatforms(){
  return [...document.querySelectorAll('#platforms .row')].map(r=>({
    platform_type:rv(r,'platform_type'),title:rv(r,'title'),api_key:rv(r,'api_key')||null,
    external_id:rv(r,'external_id')||null,url:rv(r,'url')||null,live_enabled:false,
    tags:rl(r,'tags'),keywords:rl(r,'keywords')}))
    .filter(p=>p.title||p.api_key||p.external_id||p.url||p.tags.length||p.keywords.length);
}
function collectCategories(){
  return [...document.querySelectorAll('#categories .row')].map(r=>({
    title:rv(r,'title'),description:rv(r,'description'),
    product_priorities:kvparse(rv(r,'product_priorities')),technology_priorities:kvparse(rv(r,'technology_priorities')),
    media_tags:rl(r,'media_tags'),keyword_queries:rl(r,'keyword_queries'),resource_titles:[],
    default_site_url:rv(r,'default_site_url')||null,cta:rv(r,'cta')})).filter(c=>c.title);
}
function collectPlans(defCat){
  return [...document.querySelectorAll('#plans .plan')].map(p=>{
    const get=n=>{const el=p.querySelector('[name="'+n+'"]');return el?String(el.value).trim():''};
    const wd=[...p.querySelectorAll('.wd:checked')].map(c=>parseInt(c.value));
    const times=get('publish_times').split(/[,\s]+/).map(s=>s.trim()).filter(Boolean);
    const plat=get('platform');
    return {category_title:get('category_title')||defCat,platforms:plat?[plat]:[],weekdays:wd,
      posts_per_day:parseInt(get('posts_per_day'))||1,publish_times:times,mode:get('mode')||'draft',
      timezone:'Europe/Moscow',start_date:get('start_date')||null,end_date:get('end_date')||null};
  }).filter(p=>p.platforms.length||p.publish_times.length||p.weekdays.length);
}

function buildPayload(){
  const cname=gv('company_name');
  let slug=gv('project_slug'); if(!slug) slug=slugify(cname);
  const pname=gv('project_name')||cname;
  let cats=collectCategories();
  if(!cats.length) cats=[{title:'Основное продвижение',description:'Категория по умолчанию.',
    product_priorities:{},technology_priorities:{},media_tags:[],keyword_queries:['основное продвижение'],
    resource_titles:[],default_site_url:null,cta:''}];
  const defCat=cats[0].title;
  return {
    company:{company_name:cname,business_description:gv('business_description'),
      has_website:gv('has_website'),website_url:gv('has_website')?(gv('website_url')||null):null,
      manual_topics:gl('manual_topics'),geography:gl('geography'),brand_tone:gv('brand_tone')},
    project:{project_slug:slug,project_name:pname,default_site_url:gv('default_site_url')||null},
    keywords:collectKeywords(),
    media_sources:collectMedia(),
    platforms:collectPlatforms(),
    promotion_categories:cats,
    publishing_plans:collectPlans(defCat),
    billing:{tariff_plan_slug:gv('tariff_plan_slug')||null,
      starting_topup_amount:parseInt(gv('starting_topup_amount'))||null,accept_terms:gv('accept_terms')},
  };
}
function renderResult(res){
  const c=res.crm||{};
  const rows=[
    ['Проект', esc((c.project&&(c.project.display_name||c.project.name))||'—')],
    ['Платформы', (c.resources||[]).length],
    ['Ключи', c.keywords_count||0],
    ['Медиа-источники', c.content_sources_count||0],
    ['Категории', (c.categories||[]).length],
    ['Планы расписания', (c.plans||[]).length],
    ['Баланс', res.billing_balance_units==null?'—':res.billing_balance_units+' units'],
  ];
  const warn=(res.warnings||[]).concat(c.warnings||[]);
  let h='<div class="card"><h3>'+(res.dry_run?'Предпросмотр (dry-run)':'Проект создан ✅')+'</h3>'
    +rows.map(r=>`<span class='badge'>${r[0]}: ${r[1]}</span>`).join('');
  if(warn.length) h+='<div class="muted" style="margin-top:8px">Предупреждения:<ul>'+warn.map(w=>`<li>${esc(w)}</li>`).join('')+'</ul></div>';
  h+='</div>';
  const sEl=document.getElementById('summary'); if(sEl){sEl.innerHTML=h;sEl.style.display='block';}
  json(document.getElementById('result'),res);
}
async function submitOnboarding(kind){
  const eEl=document.getElementById('error');
  const a=needAccount(eEl); if(!a) return;
  const payload=buildPayload();
  if(!payload.company.company_name){ err(eEl,new Error('Укажите название компании.')); return; }
  if(!payload.platforms.length){ err(eEl,new Error('Добавьте хотя бы одну платформу публикации.')); return; }
  if(kind==='apply' && !payload.billing.accept_terms){ err(eEl,new Error('Отметьте «Принимаю условия», чтобы создать проект.')); return; }
  eEl.style.display='none';
  try{
    const res=await api('POST','/saas/onboarding/'+kind,{account_id:a,payload});
    renderResult(res);
    // Безопасность: очищаем секреты из формы после отправки.
    document.querySelectorAll('input[name="api_key"]').forEach(i=>i.value='');
    if(kind==='apply' && res.project_id){ setTimeout(()=>location.href='/ui/projects/'+res.project_id+'/dashboard',1100); }
  }catch(x){err(eEl,x)}
}
"""


def _project_form_body(mode_apply_label: str = "Создать проект") -> str:
    """Тело формы проекта (используется для нового проекта и настроек)."""
    return (
        "<div class='card'><h2>Компания</h2>"
        "<label>Название компании *</label><input id='company_name'>"
        "<label>Описание бизнеса</label><textarea id='business_description'></textarea>"
        "<label class='chk'><input id='has_website' type='checkbox'> Есть сайт</label>"
        "<label>Сайт / рекламируемый ресурс</label><input id='website_url' placeholder='https://…'>"
        "<label>Тематика, если сайта нет (через запятую)</label><input id='manual_topics'>"
        "<label>География (через запятую)</label><input id='geography'>"
        "<label>Стиль текстов</label><select id='brand_tone'>"
        "<option value=''>— по умолчанию —</option>"
        "<option>деловой</option><option>экспертный</option><option>дружелюбный</option>"
        "<option>продающий</option><option>премиальный</option><option>простой и понятный</option>"
        "</select></div>"
        # --- Ключи: массовый импорт --- #
        "<div class='card'><h2>Ключевые слова</h2>"
        "<label>Вставьте ключевые запросы списком</label>"
        "<textarea id='kw_bulk' placeholder='производство маек и футболок 9&#10;жилетки купить опт 9&#10;производство кепок москва 9&#10;контрактное производство футболок 9'></textarea>"
        "<div class='inline' style='margin-top:8px'>"
        "<button type='button' class='sec' onclick='parseKeywords()'>Разобрать ключи</button>"
        "<label class='chk' style='margin:0'>Файл (.txt/.csv): "
        "<input type='file' accept='.txt,.csv' onchange='loadKwFile(this)' style='width:auto'></label>"
        "<button type='button' class='mini ghost' onclick='addKwRow()'>+ строка</button>"
        "<button type='button' class='mini ghost' onclick='clearKw()'>очистить</button></div>"
        "<p class='muted'>Строку можно разделять табом, «;», «,» или пробелами; последнее число — частотность.</p>"
        "<table class='kw'><thead><tr><th>query</th><th>frequency</th><th>product</th>"
        "<th>technology</th><th>cluster</th><th>priority</th><th></th></tr></thead>"
        "<tbody></tbody></table></div>"
        # --- Медиа-источники --- #
        "<div class='card'><h2>Медиа-источники</h2>"
        "<p class='muted'>Google Drive пока только сохраняется как источник, без live-интеграции.</p>"
        "<div id='media_sources'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"media_sources\")'>+ источник</button></div>"
        # --- Платформы --- #
        "<div class='card'><h2>Платформы публикации</h2>"
        "<p class='muted'>Секрет (api_key) не возвращается и очищается после отправки. "
        "Живая публикация включается отдельно после проверки.</p>"
        "<div id='platforms'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"platforms\")'>+ платформа</button></div>"
        # --- Категории продвижения (рядом с расписанием) --- #
        "<div class='card'><h2>Категории продвижения</h2>"
        "<p class='muted'>Если не создать категорию, будет добавлена «Основное продвижение».</p>"
        "<div id='categories'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"categories\")'>+ категория</button></div>"
        # --- Расписание --- #
        "<div class='card'><h2>Расписание публикаций</h2>"
        "<p class='muted'>Без плана расписания бот ничего не публикует. Если тег не выбран — "
        "бот сам выберет приоритет по частотности ключей. Режимы: draft / semi_auto (на ревью).</p>"
        "<div id='plans'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"plans\")'>+ план</button></div>"
        # --- Дополнительно --- #
        "<details class='card'><summary class='muted'>Дополнительно (код проекта, тариф, стартовое пополнение)</summary>"
        "<label>Название проекта (по умолчанию — название компании)</label><input id='project_name'>"
        "<label>Код проекта (slug, латиницей; по умолчанию из названия)</label><input id='project_slug' placeholder='my-brand'>"
        "<label>Ссылка по умолчанию</label><input id='default_site_url'>"
        "<label>Тариф (slug)</label><input id='tariff_plan_slug' placeholder='starter'>"
        "<label>Стартовое пополнение (units)</label><input id='starting_topup_amount' type='number' placeholder='0'></details>"
        # --- Preview / Apply --- #
        "<div class='card'>"
        "<label class='chk'><input id='accept_terms' type='checkbox'> Принимаю условия (обязательно для создания)</label>"
        "<div class='inline' style='margin-top:12px'>"
        "<button type='button' class='sec' onclick='submitOnboarding(\"preview\")'>Preview</button>"
        f"<button type='button' onclick='submitOnboarding(\"apply\")'>{mode_apply_label}</button></div></div>"
        "<div id='error' class='err'></div><div id='summary'></div><pre id='result'></pre>"
    )


@router.get("/projects/new", response_class=HTMLResponse)
def ui_project_new() -> HTMLResponse:
    init = (
        "['media_sources','platforms','categories','plans'].forEach(addRow);"
        "const eEl=document.getElementById('error');if(!acc()){eEl.style.display='block';"
        "eEl.textContent='Аккаунт не выбран — войдите или зарегистрируйтесь (кнопки справа сверху).';}"
        # Автогенерация slug из названия компании (если код проекта не задан вручную).
        "const cn=document.getElementById('company_name'),ps=document.getElementById('project_slug');"
        "if(cn&&ps)cn.addEventListener('input',()=>{if(!ps.dataset.touched)ps.placeholder=slugify(cn.value)||'my-brand'});"
        "if(ps)ps.addEventListener('input',()=>{ps.dataset.touched='1'});"
    )
    return _page(
        "Новый проект", _project_form_body("Создать проект"), _FORM_JS + init, active="projects"
    )


@router.get("/projects/{project_id}/settings", response_class=HTMLResponse)
def ui_project_settings(project_id: int) -> HTMLResponse:
    body = (
        "<p class='muted'>Обновление конфигурации — идемпотентный повторный онбординг: "
        "введите конфигурацию заново и нажмите «Сохранить». Код проекта (slug) зафиксирован, "
        "живые публикации выключены.</p>"
        "<div class='card'><div id='cur' class='muted'>Текущее состояние…</div></div>"
        + _project_form_body("Сохранить")
    )
    script = (
        f"const PID={project_id};"
        "const eEl=document.getElementById('error');"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        "document.getElementById('cur').innerHTML=`<b>${esc(d.project_name)}</b> (${esc(d.project_slug)}) · `"
        "+`платформы ${d.platforms_count}, категории ${d.categories_count}, баланс ${d.billing_balance_units==null?'—':d.billing_balance_units} units`;"
        "const cn=document.getElementById('company_name'); if(cn)cn.value=d.project_name;"
        "const s=document.getElementById('project_slug'); if(s){s.value=d.project_slug;s.readOnly=true;s.dataset.touched='1';}"
        "const n=document.getElementById('project_name'); if(n)n.value=d.project_name;"
        "}catch(x){err(eEl,x)}})();"
        "['media_sources','platforms','categories','plans'].forEach(addRow);"
    )
    return _page(
        f"Настройки проекта #{project_id}",
        body,
        _FORM_JS + script,
        active="projects",
        active_pid=project_id,
    )


# --------------------------------------------------------------------------- #
# Платформы: метаданные, гайды подключения (в разделах платформы, не в общем)  #
# --------------------------------------------------------------------------- #

# Канонический набор площадок Botfleet для сетки dashboard и страниц платформ.
# kind: ready | connect | media | site | soon.
_PLATFORM_META: dict[str, dict[str, str]] = {
    "telegram": {"icon": "✈️", "label": "Telegram", "kind": "ready"},
    "vk": {"icon": "🅥", "label": "VK", "kind": "connect"},
    "instagram": {"icon": "📸", "label": "Instagram", "kind": "connect"},
    "yandex_disk": {"icon": "🗂", "label": "Яндекс Диск", "kind": "media"},
    "website": {"icon": "🌐", "label": "Website", "kind": "site"},
    "youtube": {"icon": "🎬", "label": "YouTube", "kind": "soon"},
    "rutube": {"icon": "▶️", "label": "RuTube", "kind": "soon"},
}
# Порядок карточек платформ на дашборде проекта.
_PLATFORM_ORDER = ["vk", "telegram", "instagram", "yandex_disk", "website", "youtube", "rutube"]


def _platform_label(platform: str) -> str:
    meta = _PLATFORM_META.get(platform)
    return meta["label"] if meta else platform


def _platform_icon(platform: str) -> str:
    meta = _PLATFORM_META.get(platform)
    return meta["icon"] if meta else "🔌"


def _telegram_guide_html() -> str:
    """Подробный гайд подключения Telegram (внутри страницы платформы)."""
    return "".join(
        [
            "<p class='subhint'>Самый простой старт: бот в канале + токен от BotFather.</p>",
            "<div class='gcard'><h3>Шаги подключения</h3><ol>"
            "<li>Откройте <b>BotFather</b> в Telegram, создайте бота командой "
            "<code>/newbot</code> и получите <b>TELEGRAM_BOT_TOKEN</b>.</li>"
            "<li>Создайте канал (или откройте существующий).</li>"
            "<li>Добавьте бота <b>администратором</b> канала.</li>"
            "<li>Дайте боту право <b>публиковать сообщения</b> (и медиа).</li>"
            "<li>Укажите <b>@channel_username</b> или числовой channel id "
            "(<code>-100xxxxxxxxxx</code>).</li>"
            "<li>Проверьте <code>getMe</code> — бот жив и токен верный.</li>"
            "<li>Проверьте <code>getChat</code> — канал доступен боту.</li>"
            "<li>Проверьте <code>getChatMember</code> — бот админ с правом постить.</li>"
            "</ol></div>",
            "<div class='callout warn'><b>Частая ошибка: Bad Request: chat not found</b>"
            "<ul>"
            "<li>Неверный @username канала.</li>"
            "<li>Бот не добавлен администратором.</li>"
            "<li>Канал приватный.</li>"
            "<li>Username канала поменяли, а .env/настройки не обновили.</li>"
            "</ul></div>",
            "<div class='callout'><b>Безопасность и медиа</b><ul>"
            "<li>Live-публикация выключена по умолчанию — сначала <b>dry-run</b>.</li>"
            "<li>Telegram <b>media group</b> работает с несколькими фото "
            "(<code>sendMediaGroup</code>); HEIC→JPEG конвертируется.</li>"
            "</ul></div>",
        ]
    )


def _vk_guide_html() -> str:
    """Подробный гайд подключения VK (внутри страницы платформы)."""
    return "".join(
        [
            "<p class='subhint'>Текст — по ключу сообщества; фото через API — по личному "
            "user-token админа.</p>",
            "<div class='gcard'><h3>Шаги подключения</h3><ol>"
            "<li>Определите <b>Group ID</b> сообщества.</li>"
            "<li>Для text-only может работать <b>community token</b> сообщества.</li>"
            "<li>Фото через API требуют <b>user-token</b> владельца/админа/редактора.</li>"
            "<li>User-token получаем через публичный <b>HTTPS OAuth callback</b>.</li>"
            "</ol></div>",
            "<div class='callout warn'><b>Ошибка 27 — Group authorization failed</b>"
            "<p>Означает, что токен не пользовательский или не имеет прав на "
            "<code>photos.*</code>. Botfleet пробует <b>wall strategy</b> и "
            "<b>album strategy</b>; если обе дают <b>error 27</b> — нужен user-token.</p>"
            "</div>",
            "<div class='callout warn'><b>OAuth и домен</b><ul>"
            "<li>VK ID требует <b>публичный HTTPS-домен</b> в доверенных Redirect URL.</li>"
            "<li><code>localhost</code>/<code>127.0.0.1</code> обычно не подходят для "
            "production OAuth.</li>"
            "<li>Cloudflare/ngrok-туннели могут блокироваться сетью — лучше нормальный "
            "домен вида <code>app.domain.ru</code>.</li>"
            "</ul></div>",
            "<div class='callout ok'><b>После подключения проверьте</b><ul>"
            "<li><code>users.get</code> — вернул пользователя (токен валиден).</li>"
            "<li><code>groups.get filter=admin</code> — видит вашу группу.</li>"
            "<li><code>vk-api-photo-probe-upload</code> — вернул wall/album стратегию.</li>"
            "</ul></div>",
            "<p class='muted'>Пока публичного домена нет: VK работает "
            "<span class='tag'>text-only</span>, а Telegram — с картинками.</p>",
        ]
    )


def _instagram_guide_html() -> str:
    """Подробный гайд подключения Instagram (внутри страницы платформы)."""
    return "".join(
        [
            "<p class='subhint'>Публикация идёт через Meta Graph API; live готовится.</p>",
            "<div class='gcard'><h3>Классический путь</h3><ol>"
            "<li>Аккаунт должен быть <b>Professional</b>: Business или Creator.</li>"
            "<li>Professional Instagram → <b>Facebook Page</b> → <b>Meta Developer</b> "
            "App → <b>Graph API</b>.</li>"
            "<li>Получите App ID, App Secret, Redirect URI, Access Token, Instagram User ID.</li>"
            "</ol></div>",
            "<div class='callout warn'><b>Если Facebook Page не создаётся</b><ul>"
            "<li>Проверьте <b>accountquality</b> (качество аккаунта).</li>"
            "<li>Не кликайте много раз подряд.</li>"
            "<li>Попробуйте позже.</li>"
            "<li>Перейдите к «<b>Instagram API with Instagram Login</b>» — путь без "
            "Facebook Page.</li>"
            "</ul></div>",
            "<div class='callout warn'><b>Meta блокирует регистрацию разработчика</b>"
            "<p>На новом устройстве Meta может писать «устройство, которым обычно не "
            "пользуетесь». Решение:</p><ul>"
            "<li>не чистить cookies;</li>"
            "<li>оставить Chrome залогиненным;</li>"
            "<li>подождать 12–24 часа.</li>"
            "</ul></div>",
            "<div class='callout'><b>Как публикует Instagram</b>"
            "<p>Через <code>/{ig-user-id}/media</code> (создать контейнер с "
            "<b>публичным image_url</b>) → <code>/{ig-user-id}/media_publish</code>.</p>"
            "<p>Нужен <b>публичный image_url</b> (прямая HTTPS-ссылка). Локальный файл и "
            "приватный Яндекс Диск не подходят — позже нужен <b>media-proxy Botfleet</b>.</p>"
            "</div>",
        ]
    )


def _yandex_guide_html() -> str:
    """Подробный гайд подключения Яндекс Диска (медиа-источник)."""
    return "".join(
        [
            "<p class='subhint'>Медиа-источник: откуда бот берёт фото и видео.</p>",
            "<div class='gcard'><h3>Настройка</h3><ul>"
            "<li>Укажите <b>публичную ссылку</b> на папку.</li>"
            "<li>Задайте <b>root folder</b> (корневую папку контента).</li>"
            "<li>Разложите медиа по <b>папкам и тегам</b> (продукты, технологии).</li>"
            "<li><b>HEIC/HEIF</b> автоматически конвертируется в JPEG.</li>"
            "</ul></div>",
            "<div class='callout'><b>Доступ платформ к медиа</b><ul>"
            "<li>Telegram и VK могут <b>скачивать файл</b> с диска и прикреплять.</li>"
            "<li>Instagram требует <b>публичный image_url</b> или media-proxy — прямого "
            "скачивания файла недостаточно.</li>"
            "</ul></div>",
        ]
    )


def _platform_guide_html(platform: str) -> str:
    """Гайд подключения по платформе (для страницы платформы и /ui/guide/{platform})."""
    builders = {
        "telegram": _telegram_guide_html,
        "vk": _vk_guide_html,
        "instagram": _instagram_guide_html,
        "yandex_disk": _yandex_guide_html,
    }
    builder = builders.get(platform)
    if builder is not None:
        return builder()
    if platform in {"youtube", "rutube"}:
        label = _platform_label(platform)
        return (
            f"<div class='callout'><b>{html.escape(label)} — планируется</b>"
            "<p>Адаптер-скелет участвует в preview; live-публикация видео появится "
            "отдельным этапом.</p></div>"
        )
    return (
        "<div class='callout'><b>Гайд появится позже</b>"
        "<p>Подключение этой площадки ещё готовится.</p></div>"
    )


# --------------------------------------------------------------------------- #
# Дашборд проекта                                                             #
# --------------------------------------------------------------------------- #


def _instagram_dashboard_card(settings: Settings) -> str:
    """Справочная карточка Instagram (без секретов) — вкладка «Настройки» платформы.

    App Secret и Access Token НИКОГДА не выводятся значением — только факт наличия
    («секрет сохранён») или «не задан». App ID / Redirect URI / User ID НЕсекретны.
    Кнопки: локальная проверка настроек (без сети), гайд, копирование Redirect URI.
    Кнопки live-публикации нет.
    """
    app_id = html.escape(settings.instagram_app_id or "не задан")
    redirect = html.escape(settings.instagram_redirect_uri_effective or "—")
    user_id = html.escape(settings.instagram_effective_user_id or "—")
    secret_txt = "секрет сохранён (скрыт)" if settings.instagram_app_secret else "не задан"
    token_txt = "токен сохранён (скрыт)" if settings.instagram_access_token else "не задан"
    connected = bool(settings.instagram_access_token)
    status_pill = (
        "<span class='pill ok'>Токен сохранён</span>"
        if connected
        else "<span class='pill off'>Не подключено</span>"
    )
    return (
        "<div class='card' id='ig-card'>"
        "<h2>Instagram</h2>"
        "<div class='inline' style='margin:2px 0 8px'>"
        f"{status_pill}"
        "<span class='pill off'>Готовится подключение</span>"
        "<span class='pill off'>live выключен</span></div>"
        # Ключевая подсказка по публичному image_url (Part 2).
        "<p class='muted'>Instagram API публикует не локальный файл, а публичный HTTPS "
        "<b>image_url</b>. Для Яндекс Диска нужен прямой публичный URL или будущий "
        "media-proxy Botfleet.</p>"
        "<div class='ig-fields'>"
        f"<div><span class='k'>Instagram App ID</span><span class='v'><code>{app_id}</code></span></div>"
        f"<div><span class='k'>Instagram App Secret</span><span class='v'>{secret_txt}</span></div>"
        f"<div><span class='k'>Redirect URI</span><span class='v'><code id='ig-redirect'>{redirect}</code></span></div>"
        f"<div><span class='k'>Access Token</span><span class='v'>{token_txt}</span></div>"
        f"<div><span class='k'>Instagram User ID</span><span class='v'><code>{user_id}</code></span></div>"
        "<div><span class='k'>Публичный image_url</span><span class='v'>обязателен</span></div>"
        "</div>"
        "<div class='inline' style='margin-top:10px'>"
        "<button class='mini sec' onclick='igCheck()'>Проверить настройки</button>"
        "<a href='/ui/guide/instagram'><button class='mini ghost'>Открыть гайд Instagram</button></a>"
        "<button class='mini ghost' onclick='igCopyRedirect()'>Скопировать Redirect URI</button>"
        "</div>"
        "<div id='ig-check' class='muted' style='margin-top:8px'></div></div>"
    )


@router.get("/projects/{project_id}/dashboard", response_class=HTMLResponse)
def ui_project_dashboard(project_id: int) -> HTMLResponse:
    _settings = get_settings()
    ig_cfg = {
        "user_id": _settings.instagram_effective_user_id or "",
        "token_present": bool(_settings.instagram_access_token),
    }
    body = (
        # Заголовок проекта (h1 заменяется на «Проект: {имя}» из JS) + баланс.
        "<div class='proj-head'><span id='pbadges'></span></div>"
        # Действия проекта.
        f"<div class='proj-actions'>"
        f"<a href='/ui/projects/{project_id}/settings'><button class='sec mini'>Настройки проекта</button></a>"
        f"<a href='/ui/projects/{project_id}/settings#platforms'><button class='mini'>Создать платформу</button></a>"
        "<button class='mini sec' onclick='toggleSchedPicker()'>Создать расписание</button></div>"
        "<div id='sched-picker' class='card' style='display:none'>"
        "<p class='muted'>Выберите платформу для нового расписания:</p>"
        "<div id='sched-picker-links' class='inline'></div></div>"
        # Сетка платформ (кликабельные карточки → страница платформы).
        "<h2>Платформы</h2><div id='plats' class='ptiles'>"
        "<div class='muted'>Загрузка…</div></div>"
        # Компактная активность после платформ.
        "<h2>Активность</h2><div id='activity' class='card muted'>Загрузка…</div>"
        "<div id='error' class='err'></div>"
    )
    platform_meta = {
        k: {"icon": v["icon"], "label": v["label"], "kind": v["kind"]}
        for k, v in _PLATFORM_META.items()
    }
    script = (
        f"const PID={project_id};"
        f"const IG_CFG={json.dumps(ig_cfg)};"
        f"const PLATFORM_META={json.dumps(platform_meta, ensure_ascii=False)};"
        f"const PLATFORM_ORDER={json.dumps(_PLATFORM_ORDER)};"
        "function toggleSchedPicker(){const p=document.getElementById('sched-picker');"
        "if(p)p.style.display=(p.style.display==='none'||!p.style.display)?'block':'none';}"
        "const eEl=document.getElementById('error');"
        "const P=document.getElementById('plats');const A=document.getElementById('activity');"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        # Заголовок «Проект: {имя}».
        "const h1=document.querySelector('main h1');if(h1)h1.textContent='Проект: '+(d.project_name||('#'+PID));"
        "document.getElementById('pbadges').innerHTML="
        "`<span class='badge'>${esc(d.project_slug)}</span>`"
        "+`<span class='badge'>баланс: ${d.billing_balance_units==null?'—':d.billing_balance_units} units</span>`"
        "+`<span class='badge'>платформы: ${d.platforms_count}</span>`"
        "+`<span class='badge'>планы: ${d.active_plans_count}</span>`;"
        # Карта ресурсов по типу платформы (без секрета).
        "const byType={};((d.extra&&d.extra.platforms)||[]).forEach(p=>{byType[p.platform_type]=p;});"
        "function tile(pt){const m=PLATFORM_META[pt]||{icon:'🔌',label:pt,kind:''};const r=byType[pt];"
        "const soon=m.kind==='soon';"
        "const on=!!(r&&(r.external_id||r.url||r.has_api_key||r.yandex_public_url));"
        "let rows='';"
        "if(pt==='vk'){rows=`<div class='prow'>Group ID: ${esc((r&&r.external_id)||'—')}</div>`"
        "+`<div class='prow'>token: ${(r&&r.has_api_key)?'сохранён':'нет'}</div>`"
        "+`<div class='prow'>live: выключен</div>`"
        "+`<div class='prow'>⚠️ Фото через API требуют user-token</div>`;}"
        "else if(pt==='telegram'){rows=`<div class='prow'>Channel: ${esc((r&&r.external_id)||'—')}</div>`"
        "+`<div class='prow'>bot token: ${(r&&r.has_api_key)?'сохранён':'нет'}</div>`"
        "+`<div class='prow'>media group: поддерживается</div>`"
        "+`<div class='prow'>live: выключен</div>`;}"
        "else if(pt==='instagram'){rows=`<div class='prow'>User ID: ${esc((r&&r.external_id)||IG_CFG.user_id||'—')}</div>`"
        "+`<div class='prow'>token: ${((r&&r.has_api_key)||IG_CFG.token_present)?'сохранён':'нет'}</div>`"
        "+`<div class='prow'>image_url required</div>`"
        "+`<div class='prow'>live: выключен</div>`;}"
        "else if(pt==='yandex_disk'){rows=`<div class='prow'>источник: Яндекс Диск</div>`"
        "+`<div class='prow'>root: ${esc((r&&r.yandex_root_folder)||'—')}</div>`"
        "+`<div class='prow'>public url: ${(r&&r.yandex_public_url)?'да':'—'}</div>`"
        "+`<div class='prow'>теги: ${esc(((r&&r.tags)||[]).join(', ')||'—')}</div>`;}"
        "else if(pt==='website'){rows=`<div class='prow'>${esc((r&&r.url)||'—')}</div>`;}"
        "else{rows=`<div class='prow'>Планируется</div>`;}"
        "const st=soon?`<span class='pill off'>скоро</span>`:(on?`<span class='pill ok'>настроено</span>`:`<span class='pill off'>не настроено</span>`);"
        "return `<a class='ptile${soon?` soon`:``}' href='/ui/projects/${PID}/platforms/${encodeURIComponent(pt)}'>`"
        "+`<div class='inline'><span class='ico'>${m.icon}</span> <span class='pname'>${esc(m.label)}</span></div>`"
        "+`<div>${st}</div>${rows}<span class='open'>Открыть →</span></a>`;}"
        "P.innerHTML=PLATFORM_ORDER.map(tile).join('');"
        # Пикер платформ для нового расписания — только настроенные площадки.
        "const cfg=PLATFORM_ORDER.filter(pt=>byType[pt]&&(PLATFORM_META[pt]||{}).kind!=='soon');"
        "const links=cfg.length?cfg:['telegram','vk','instagram'];"
        "document.getElementById('sched-picker-links').innerHTML=links.map(pt=>"
        "`<a href='/ui/projects/${PID}/platforms/${encodeURIComponent(pt)}/schedule'><button class='mini sec'>${esc((PLATFORM_META[pt]||{}).label||pt)}</button></a>`).join('');"
        # Компактная активность: рекомендации + последние посты.
        "const acts=(d.next_recommended_actions||[]);"
        "const recent=(d.recent_posts||[]);"
        "A.classList.remove('muted');"
        "A.innerHTML=`<b>Next actions</b><ul>`+(acts.length?acts.map(a=>`<li>${esc(a)}</li>`).join(''):`<li class='muted'>—</li>`)+`</ul>`"
        "+`<b>Последние посты</b>`+(recent.length?`<ul>`+recent.map(p=>`<li>${esc(p.title||('#'+p.id))} — <span class='muted'>${esc(p.status)}</span></li>`).join('')+`</ul>`:`<p class='muted'>Постов пока нет.</p>`);"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Проект", body, script, active="projects", active_pid=project_id)


# --------------------------------------------------------------------------- #
# Страница платформы (workspace): вкладки, гайд, расписание, preview, аналитика #
# --------------------------------------------------------------------------- #

# Общий JS: рендер задач расписания как отдельных карточек. Кнопки Изменить/Пауза/
# Удалить/Preview — БЕЗ разрушительных действий (безопасные заглушки/локальные).
_SCHED_TASKS_JS = r"""
const WDSHORT=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
function nextRun(weekdays,times){
  if(!weekdays||!weekdays.length||!times||!times.length)return '—';
  const now=new Date();const wd=weekdays.slice().sort((a,b)=>a-b);const tm=times.slice().sort();
  for(let add=0;add<8;add++){
    const dt=new Date(now.getFullYear(),now.getMonth(),now.getDate()+add);
    const mon=(dt.getDay()+6)%7; if(wd.indexOf(mon)<0)continue;
    for(const t of tm){const pr=String(t).split(':');const h=parseInt(pr[0])||0,mi=parseInt(pr[1])||0;
      const cand=new Date(dt.getFullYear(),dt.getMonth(),dt.getDate(),h,mi);
      if(cand>now)return cand.toLocaleString('ru-RU',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});}
  }
  return '—';
}
function schedTaskCard(t){
  const days=(t.weekdays||[]).map(i=>WDSHORT[i]||i).join(' ')||'—';
  const times=(t.publish_times||[]).join(', ')||'—';
  const plats=(t.platforms||[]).join(', ')||'—';
  const status=t.is_active?'active':'draft';
  const modeTxt=(t.mode||'draft')+' · live_disabled';
  return `<div class='sched-task' id='task-${t.id}'>`
   +`<h3>${esc(t.name||'План публикаций')} <span class='pill ${t.is_active?'ok':'off'}'>${status}</span></h3>`
   +`<div class='sched-grid'>`
   +`<div><span class='k'>Платформа</span><span class='v'>${esc(plats)}</span></div>`
   +`<div><span class='k'>Категория/тег</span><span class='v'>${esc(t.category_title||'—')}</span></div>`
   +`<div><span class='k'>Дни недели</span><span class='v'>${esc(days)}</span></div>`
   +`<div><span class='k'>Время</span><span class='v'>${esc(times)}</span></div>`
   +`<div><span class='k'>Период</span><span class='v'>${esc((t.start_date||'—')+' … '+(t.end_date||'—'))}</span></div>`
   +`<div><span class='k'>Режим</span><span class='v'>${esc(modeTxt)}</span></div>`
   +`<div><span class='k'>Стоимость публикации</span><span class='v'>${t.cost_per_post_units==null?'—':(t.cost_per_post_units+' units')}</span></div>`
   +`<div><span class='k'>Следующая публикация</span><span class='v'>${esc(nextRun(t.weekdays,t.publish_times))}</span></div>`
   +`</div><div class='acts'>`
   +`<button class='mini sec' onclick='editTask(${t.id})'>Изменить</button>`
   +`<button class='mini ghost' onclick='pauseTask(${t.id})'>Пауза/Возобновить</button>`
   +`<button class='mini ghost' onclick='previewTask(${t.id})'>Preview ближайших постов</button>`
   +`<button class='mini ghost' onclick='deleteTask(${t.id})'>Удалить</button>`
   +`</div><div id='taskmsg-${t.id}' class='muted' style='margin-top:6px'></div></div>`;
}
function renderSchedTasks(tasks,platform,hostId){
  const host=document.getElementById(hostId); if(!host)return;
  const list=(tasks||[]).filter(t=>!platform||(t.platforms||[]).indexOf(platform)>=0);
  host.innerHTML=list.length?list.map(schedTaskCard).join('')
    :"<div class='card muted'>Расписаний нет. Создайте новое ниже.</div>";
}
function _taskMsg(id,html){const m=document.getElementById('taskmsg-'+id);if(m){m.innerHTML=html;}}
function editTask(id){_taskMsg(id,"Измените поля в форме ниже и сохраните новый план (редактирование существующего появится позже).");
  const f=document.getElementById('preview');if(f)f.scrollIntoView({behavior:'smooth'});}
function pauseTask(id){const c=document.getElementById('task-'+id);if(c)c.classList.toggle('paused');
  _taskMsg(id,"<span class='pill off'>Пауза переключена локально</span> — на бота не влияет (плановая рассылка из UI не запускается).");}
function previewTask(id){_taskMsg(id,"Preview ближайших постов — dry-run: см. кнопку «Preview (dry-run)» в форме ниже. Ничего не публикуется.");}
function deleteTask(id){if(!confirm('Удалить расписание? (действие безопасное, план на боте не трогается)'))return;
  _taskMsg(id,"Удаление плана появится позже — разрушительные действия не выполняются из UI.");}
"""


def _vk_settings_pane(settings: Settings) -> str:
    """Пане «Настройки» для VK: OAuth-подключение (справочно, без секретов)."""
    app_id = html.escape(settings.vk_app_id or "не задан")
    redirect = html.escape(settings.vk_oauth_redirect_uri or "—")
    base = html.escape(settings.vk_oauth_base_domain or "app.teeon.ru")
    return (
        "<div class='card'><h3>Подключение VK (OAuth)</h3>"
        "<p class='muted'>Фото для VK — только через личный VK user token "
        "(не ключ сообщества).</p>"
        "<div class='kv'>"
        f"<div><span class='k'>OAuth App ID</span><span class='v'>{app_id}</span></div>"
        "<div><span class='k'>Group ID</span><span class='v' id='vk-gid'>—</span></div>"
        f"<div><span class='k'>Redirect URI</span><span class='v'><code>{redirect}</code></span></div>"
        f"<div><span class='k'>Базовый домен</span><span class='v'><code>{base}</code></span></div>"
        "</div>"
        "<div class='callout'><b>Что вставить в VK ID</b>"
        f"<p>Базовый домен: <code>{base}</code><br>Доверенный Redirect URL: "
        f"<code>{redirect}</code></p></div>"
        "<div class='inline'>"
        "<span id='vk-connect'><button class='mini' disabled>Подключить VK</button></span>"
        "<button class='mini ghost' onclick='vkCheckWs()'>Проверить доступ</button></div>"
        "<div id='vk-check-host' class='muted' style='margin-top:6px'></div></div>"
    )


def _platform_settings_pane(platform: str, settings: Settings) -> str:
    """HTML вкладки «Настройки» для конкретной платформы."""
    if platform == "vk":
        return _vk_settings_pane(settings)
    if platform == "instagram":
        return _instagram_dashboard_card(settings)
    if platform == "yandex_disk":
        return (
            "<div class='card'><h3>Медиа-источник</h3>"
            "<div class='kv'>"
            "<div><span class='k'>Тип источника</span><span class='v' id='yd-type'>Яндекс Диск</span></div>"
            "<div><span class='k'>Root folder</span><span class='v' id='yd-root'>—</span></div>"
            "<div><span class='k'>Публичная ссылка</span><span class='v' id='yd-public'>—</span></div>"
            "<div><span class='k'>Медиа-теги</span><span class='v' id='yd-tags'>—</span></div>"
            "</div>"
            "<p class='muted'>Изменить источник: "
            "<a id='yd-settings-link' href='#'>Настройки проекта →</a></p></div>"
        )
    return (
        "<div class='card'><h3>Настройки платформы</h3>"
        "<p class='muted'>Параметры этой площадки задаются в онбординге проекта.</p>"
        "<p class='muted'><a id='pl-settings-link' href='#'>Открыть настройки проекта →</a></p>"
        "</div>"
    )


@router.get("/projects/{project_id}/platforms/{platform}", response_class=HTMLResponse)
def ui_platform_workspace(project_id: int, platform: str) -> HTMLResponse:
    """Рабочая область платформы: вкладки Обзор/Настройки/Гайд/Расписание/Preview/Аналитика."""
    platform = _safe_slug(platform)
    settings = get_settings()
    label = _platform_label(platform)
    icon = _platform_icon(platform)
    tabs = [
        ("overview", "Обзор"),
        ("settings", "Настройки"),
        ("guide", "Гайд подключения"),
        ("schedule", "Расписание"),
        ("preview", "Preview"),
        ("analytics", "Аналитика"),
    ]

    def _tab_btn(index: int, key: str, name: str) -> str:
        active = " active" if index == 0 else ""
        return (
            f"<button class='tab{active}' onclick='showTab(\"{key}\")' "
            f"data-tab='{key}'>{html.escape(name)}</button>"
        )

    tabs_bar = "".join(_tab_btn(i, key, name) for i, (key, name) in enumerate(tabs))
    guide_html = _platform_guide_html(platform)
    settings_pane = _platform_settings_pane(platform, settings)
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a></div>"
        f"<div class='pw-head'><span class='big'>{icon}</span>"
        f"<h2 style='margin:0'>{html.escape(label)}</h2>"
        "<span id='pw-status' class='pill off'>…</span></div>"
        f"<div class='tabs'>{tabs_bar}</div>"
        # Обзор
        "<div class='tabpane active' id='pane-overview'>"
        "<div class='card'><div id='pw-overview' class='muted'>Загрузка…</div></div></div>"
        # Настройки
        f"<div class='tabpane' id='pane-settings'>{settings_pane}</div>"
        # Гайд
        f"<div class='tabpane' id='pane-guide'>{guide_html}</div>"
        # Расписание
        "<div class='tabpane' id='pane-schedule'>"
        "<div class='inline'><a id='sched-new-link' href='#'>"
        "<button class='mini'>Создать расписание</button></a></div>"
        "<div id='sched-host' class='sched-list'><div class='muted'>Загрузка…</div></div></div>"
        # Preview
        "<div class='tabpane' id='pane-preview'>"
        "<div class='card'><h3>Preview (dry-run)</h3>"
        "<p class='muted'>Проверка «что и куда ушло бы» без публикации. Живые публикации "
        "выключены; реальные вызовы API не выполняются.</p>"
        "<a id='preview-link' href='#'><button class='mini sec'>Открыть планировщик и Preview</button></a>"
        "</div></div>"
        # Аналитика
        "<div class='tabpane' id='pane-analytics'>"
        "<div class='card'><h3>Аналитика площадки</h3>"
        "<p class='muted'>Эффективность постов этой площадки, охваты и рекомендации — "
        "в разделе аналитики (офлайн-демо, без вызовов внешних API).</p>"
        "<a href='/ui/analytics'><button class='mini sec'>Открыть аналитику</button></a>"
        "</div></div>"
        "<div id='error' class='err'></div>"
    )
    vk_cfg = {
        "app_id": settings.vk_app_id or "",
        "redirect_uri": settings.vk_oauth_redirect_uri or "",
        "base_domain": settings.vk_oauth_base_domain or "",
        "configured": bool(settings.vk_oauth_configured),
    }
    ig_cfg = {
        "app_id": settings.instagram_app_id or "",
        "redirect_uri": settings.instagram_redirect_uri_effective or "",
        "user_id": settings.instagram_effective_user_id or "",
        "app_secret_present": bool(settings.instagram_app_secret),
        "token_present": bool(settings.instagram_access_token),
        "live_enabled": bool(settings.instagram_live_publishing_enabled),
    }
    ig_js = (
        "function igCheck(){const el=document.getElementById('ig-check');if(!el)return;"
        "const yn=b=>b?'✔ задан':'— не задан';"
        "const rows=['App ID: '+yn(!!IG_CFG.app_id),'App Secret: '+yn(IG_CFG.app_secret_present),"
        "'Redirect URI: '+yn(!!IG_CFG.redirect_uri),'Access Token: '+yn(IG_CFG.token_present),"
        "'Instagram User ID: '+yn(!!IG_CFG.user_id),"
        "'Live: '+(IG_CFG.live_enabled?'включён (⚠️ live-клиент ещё не реализован)':'выключен (только preview/dry-run)')];"
        "el.innerHTML=\"<b>Локальная проверка (без сети):</b><br>\"+rows.map(esc).join('<br>')"
        "+\"<br><span class='muted'>Публикация использует публичный HTTPS image_url; реальные вызовы Meta API ещё не выполняются.</span>\";}"
        "function igCopyRedirect(){const t=(IG_CFG&&IG_CFG.redirect_uri)||'';const el=document.getElementById('ig-check');"
        'copyText(t).then(()=>{if(el)el.innerHTML="<span class=\'pill ok\'>Redirect URI скопирован</span> <code>"+esc(t)+"</code>";})'
        '.catch(()=>{if(el)el.innerHTML="<span class=\'muted\'>Скопируйте вручную: </span><code>"+esc(t)+"</code>";});}'
    )
    script = (
        f"const PID={project_id};const PLATFORM={json.dumps(platform)};"
        f"const VK_CFG={json.dumps(vk_cfg)};const IG_CFG={json.dumps(ig_cfg)};"
        + ig_js
        + "let WS_RID=null;"
        "function showTab(name){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));"
        "document.querySelectorAll('.tabpane').forEach(p=>p.classList.toggle('active',p.id==='pane-'+name));"
        "if(location.hash!=='#'+name){history.replaceState(null,'','#'+name);}}"
        "function vkCheckWs(){if(WS_RID==null){return;}const host=document.getElementById('vk-check-host');"
        "if(host&&!document.getElementById('vkchk-'+WS_RID))host.innerHTML=\"<div id='vkchk-\"+WS_RID+\"'></div>\";"
        "vkCheck(WS_RID);}"
        "const eEl=document.getElementById('error');"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        "const aid=d.account_id||acc()||'<account_id>';"
        "const r=((d.extra&&d.extra.platforms)||[]).find(p=>p.platform_type===PLATFORM);"
        "const on=!!(r&&(r.external_id||r.url||r.has_api_key||r.yandex_public_url));"
        "const stEl=document.getElementById('pw-status');"
        "if(stEl){stEl.className='pill '+(on?'ok':'off');stEl.textContent=on?'настроено':'не настроено';}"
        # Обзор
        "const ov=document.getElementById('pw-overview');"
        "if(ov){ov.classList.remove('muted');"
        "ov.innerHTML=`<div class='kv'>`"
        "+`<div><span class='k'>Статус</span><span class='v'>${on?'настроено':'не настроено'}</span></div>`"
        "+`<div><span class='k'>Идентификатор</span><span class='v'>${esc((r&&(r.external_id||r.url))||'—')}</span></div>`"
        "+`<div><span class='k'>Токен</span><span class='v'>${(r&&r.has_api_key)?'сохранён (маска)':'нет'}</span></div>`"
        "+`<div><span class='k'>Live</span><span class='v'>выключен</span></div>`"
        "+`</div><p class='muted'>Гайд подключения и расписание — на соседних вкладках.</p>`;}"
        # ссылки
        "const sl=document.getElementById('sched-new-link');if(sl)sl.href='/ui/projects/'+PID+'/platforms/'+encodeURIComponent(PLATFORM)+'/schedule';"
        "const pv=document.getElementById('preview-link');if(pv)pv.href='/ui/projects/'+PID+'/platforms/'+encodeURIComponent(PLATFORM)+'/schedule#preview';"
        "const psl=document.getElementById('pl-settings-link');if(psl)psl.href='/ui/projects/'+PID+'/settings';"
        "const ydl=document.getElementById('yd-settings-link');if(ydl)ydl.href='/ui/projects/'+PID+'/settings';"
        # Yandex disk pane fill
        "if(PLATFORM==='yandex_disk'&&r){const g=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v;};"
        "g('yd-root',(r.yandex_root_folder||'—'));g('yd-public',r.yandex_public_url?'да':'—');g('yd-tags',((r.tags||[]).join(', ')||'—'));}"
        # VK connect
        "if(PLATFORM==='vk'){WS_RID=r?r.id:null;const g=document.getElementById('vk-gid');if(g)g.textContent=(r&&r.external_id)||'—';"
        "const vc=document.getElementById('vk-connect');"
        "if(vc){if(r){vc.innerHTML=`<a href='/integrations/vk/oauth/start?account_id=${encodeURIComponent(aid)}&project_id=${PID}&resource_id=${r.id}'><button class='mini'>${r.has_api_key?'Переподключить VK':'Подключить VK'}</button></a>`;}"
        "else{vc.innerHTML=`<span class='muted'>Сначала добавьте VK в настройках проекта.</span>`;}}}"
        # Расписание
        "renderSchedTasks((d.extra&&d.extra.schedule_tasks)||[],PLATFORM,'sched-host');"
        # Открыть вкладку из hash
        "const h=(location.hash||'').replace('#','');if(h)showTab(h);"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page(label, body, _SCHED_TASKS_JS + script, active="projects", active_pid=project_id)


# --------------------------------------------------------------------------- #
# Планировщик расписания внутри платформы                                     #
# --------------------------------------------------------------------------- #

_SCHEDULE_JS = r"""
const WEEKDAYS=[['0','Пн'],['1','Вт'],['2','Ср'],['3','Чт'],['4','Пт'],['5','Сб'],['6','Вс']];
let CTX={slug:'',name:'',ext:null,url:null};
function wdSelected(){return [...document.querySelectorAll('.wd:checked')].map(c=>parseInt(c.value))}
function planObject(){
  const cat=gv('cat')||'Основное продвижение';
  const times=gv('publish_times').split(/[,\s]+/).map(s=>s.trim()).filter(Boolean);
  return {category_title:cat,platforms:[PLATFORM],weekdays:wdSelected(),
    posts_per_day:parseInt(gv('posts_per_day'))||1,publish_times:times,mode:gv('mode')||'draft',
    timezone:'Europe/Moscow',start_date:gv('start_date')||null,end_date:gv('end_date')||null};
}
function schedPayload(){
  const cat=gv('cat')||'Основное продвижение';
  return {
    company:{company_name:CTX.name||CTX.slug,business_description:'',has_website:false,website_url:null,
      manual_topics:['контент'],geography:[],brand_tone:''},
    project:{project_slug:CTX.slug,project_name:CTX.name},
    keywords:[],media_sources:[],
    platforms:[{platform_type:PLATFORM,title:PLATFORM,api_key:null,external_id:CTX.ext,url:CTX.url,live_enabled:false,tags:[],keywords:[]}],
    promotion_categories:[{title:cat,description:'',product_priorities:{},technology_priorities:{},
      media_tags:[],keyword_queries:['основное продвижение'],resource_titles:[],default_site_url:null,cta:''}],
    publishing_plans:[planObject()],
    billing:{accept_terms:false},
  };
}
function showPlan(){json(document.getElementById('result'),{publishing_plans:[planObject()]});
  const eEl=document.getElementById('error');if(eEl)eEl.style.display='none';}
async function previewPlan(){
  const eEl=document.getElementById('error');const a=needAccount(eEl);if(!a)return;eEl.style.display='none';
  try{const res=await api('POST','/saas/onboarding/preview',{account_id:a,payload:schedPayload()});
    json(document.getElementById('result'),res);}catch(x){err(eEl,x)}
}
async function initSchedule(){
  const eEl=document.getElementById('error');
  document.getElementById('days').innerHTML='Дни: '+WEEKDAYS.map(w=>`<label><input type='checkbox' class='wd' value='${w[0]}'>${w[1]}</label>`).join('');
  try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');
    CTX.slug=d.project_slug;CTX.name=d.project_name;
    const pl=((d.extra&&d.extra.platforms)||[]).find(p=>p.platform_type===PLATFORM);
    if(pl){CTX.ext=pl.external_id;CTX.url=pl.url;}
    document.getElementById('ctx').innerHTML=`<b>${esc(d.project_name)}</b> · платформа <b>${esc(PLATFORM)}</b> · баланс ${d.billing_balance_units==null?'—':d.billing_balance_units} units`;
    renderSchedTasks((d.extra&&d.extra.schedule_tasks)||[],PLATFORM,'sched-host');
  }catch(x){err(eEl,x)}
}
initSchedule();
"""


@router.get("/projects/{project_id}/platforms/{platform}/schedule", response_class=HTMLResponse)
def ui_platform_schedule(project_id: int, platform: str) -> HTMLResponse:
    platform = _safe_slug(platform)
    body = (
        f"<div class='inline'>"
        f"<a href='/ui/projects/{project_id}/platforms/{platform}'>"
        "<button class='sec mini'>← К платформе</button></a>"
        f"<a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='ghost mini'>К проекту</button></a></div>"
        "<div class='card'><div id='ctx' class='muted'>Загрузка…</div></div>"
        # Существующие расписания как отдельные задачи.
        "<h2>Задачи расписания</h2>"
        "<div id='sched-host' class='sched-list'><div class='muted'>Загрузка…</div></div>"
        "<div class='card' id='preview'><h2>Новый план публикаций</h2>"
        "<label>Название плана</label><input id='name' placeholder='Осенняя кампания'>"
        "<label>Тег / категория продвижения</label><input id='cat' placeholder='необязательно'>"
        "<p class='muted'>Если тег не выбран — бот сам выберет приоритет по частотности ключей.</p>"
        "<div class='inline'><div style='flex:1'><label>Дата начала</label><input id='start_date' type='date'></div>"
        "<div style='flex:1'><label>Дата окончания</label><input id='end_date' type='date'></div></div>"
        "<label>Дни недели</label><div id='days' class='days'></div>"
        "<label>Время публикаций (HH:MM через запятую)</label><input id='publish_times' value='10:00,18:00'>"
        "<div class='inline'><div style='flex:1'><label>Постов в день</label><input id='posts_per_day' type='number' min='1' value='1'></div>"
        "<div style='flex:1'><label>Режим</label><select id='mode'>"
        "<option value='draft'>draft</option><option value='semi_auto'>semi_auto</option></select></div></div>"
        "<p class='muted'>Без плана расписания бот ничего не публикует. Живые публикации выключены — "
        "прогоны только dry-run / на ревью.</p>"
        "<div class='inline' style='margin-top:12px'>"
        "<button type='button' class='sec' onclick='showPlan()'>Показать план</button>"
        "<button type='button' onclick='previewPlan()'>Preview (dry-run)</button></div></div>"
        "<div id='error' class='err'></div><pre id='result'></pre>"
    )
    # platform приходит из URL; для JS передаём как JSON-строку (безопасно экранировано).
    script = (
        f"const PID={project_id};const PLATFORM={json.dumps(platform)};"
        + _SCHED_TASKS_JS
        + _SCHEDULE_JS
    )
    return _page(
        f"Расписание · {_platform_label(platform)}",
        body,
        script,
        active="projects",
        active_pid=project_id,
    )


# --------------------------------------------------------------------------- #
# Тарифы / Аналитика / Настройки (плейсхолдеры) и Биллинг                      #
# --------------------------------------------------------------------------- #


@router.get("/tariffs", response_class=HTMLResponse)
def ui_tariffs() -> HTMLResponse:
    economics = UnitEconomicsService()
    rows = economics.build_pricing_table()
    cfg = economics.pricing_config()
    table_rows = "".join(
        f"<tr><td>{html.escape(str(r['title']))}</td>"
        f"<td class='u'>{html.escape(str(r['units']))} units</td>"
        f"<td class='muted'>{html.escape(str(r['note']))}</td></tr>"
        for r in rows
    )
    body = (
        "<div class='grid'>"
        "<div class='pcard'><h3>Starter</h3><p class='meta'>Для старта: один проект, "
        "базовые платформы.</p></div>"
        "<div class='pcard'><h3>Pro</h3><p class='meta'>Больше проектов и платформ, "
        "приоритетная генерация.</p></div>"
        "<div class='pcard'><h3>Agency</h3><p class='meta'>Много аккаунтов/проектов, "
        "командная работа.</p></div>"
        "</div>"
        "<h2>Стоимость действий (units)</h2>"
        "<p class='muted'>units — внутренняя валюта Botfleet. Цена считается из реальных "
        "токенов провайдера с наценкой; порог — минимальная стоимость действия.</p>"
        "<table class='price-table'><thead><tr><th>Действие</th><th>Стоимость</th>"
        "<th>Пояснение</th></tr></thead><tbody>"
        f"{table_rows}</tbody></table>"
        "<div class='callout'><b>Как считается стоимость</b>"
        "<p>себестоимость_usd = вход/1M×цена_вход + выход/1M×цена_выход;<br>"
        "цена_клиента_usd = себестоимость × наценка;<br>"
        "units = max(минимум, ceil(цена_клиента × курс_usd→unit)).</p>"
        f"<p class='muted'>Модель: {html.escape(str(cfg['ai_pricing_model']))}; "
        f"вход ${html.escape(str(cfg['ai_input_usd_per_1m']))}/1M, "
        f"выход ${html.escape(str(cfg['ai_output_usd_per_1m']))}/1M; "
        f"наценка ×{html.escape(str(cfg['markup_multiplier']))}; "
        f"курс {html.escape(str(cfg['usd_to_unit_rate']))} units/$.</p></div>"
        "<div class='callout ok'><b>Правила списаний</b><ul>"
        "<li>Генерация списывается после создания черновика (draft/needs_review).</li>"
        "<li>Публикация списывается только после успешной публикации.</li>"
        "<li>Аналитика списывается после успешного отчёта.</li>"
        "<li>dry-run / preview — бесплатно (0 units).</li>"
        "<li>Неуспешная публикация не списывает units; повтор не списывает дважды "
        "(идемпотентность).</li>"
        "</ul></div>"
        "<p class='muted'>Реальные платежи пока не подключены; пополнение тестовое во "
        "внутренних units. <a href='/ui/billing'>Тестовое пополнение →</a></p>"
    )
    return _page("Тарифы", body, "", active="tariffs")


@router.get("/analytics", response_class=HTMLResponse)
def ui_analytics() -> HTMLResponse:
    economics = UnitEconomicsService()
    depth_prices = {row["depth"]: row["units"] for row in economics.analytics_price_table()}
    body = (
        # Верхний блок: баланс + подсказка.
        "<div class='card'><div id='an-balance' class='muted'>Баланс: загрузка…</div>"
        "<p class='muted'>Preview бесплатно, запуск отчёта списывает units. Источник метрик "
        "всегда указывается (internal / manual / estimated / api / demo). Реальные вызовы "
        "внешних API не выполняются.</p></div>"
        # Фильтры
        "<div class='card'><div class='an-filters'>"
        "<div><label>Проект</label><select id='an-project'>"
        "<option value=''>— выберите —</option></select></div>"
        "<div><label>Платформа</label><select id='an-platform'>"
        "<option value='all'>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option>"
        "<option value='website'>Website</option></select></div>"
        "<div><label>Период</label><select id='an-period'>"
        "<option value='today'>Сегодня</option><option value='7d' selected>7 дней</option>"
        "<option value='30d'>30 дней</option><option value='month'>Текущий месяц</option>"
        "<option value='custom'>Произвольный</option></select></div>"
        "<div><label>Статус</label><select id='an-status'>"
        "<option value=''>Все</option><option value='published'>published</option>"
        "<option value='scheduled'>scheduled</option><option value='rejected'>failed</option>"
        "<option value='needs_review'>needs_review</option></select></div>"
        "<div><label>Глубина</label><select id='an-depth'>"
        "<option value='light'>light</option><option value='standard'>standard</option>"
        "<option value='deep'>deep</option></select></div>"
        "<div><label>Постов в отчёте</label><input id='an-count' type='number' min='1' value='1'></div>"
        "</div>"
        # Блок стоимости
        "<div class='inline' style='margin-top:10px'>"
        "<span class='muted'>Предварительная стоимость: </span>"
        "<span id='an-estimate' class='an-est'>—</span>"
        "<button class='mini sec' onclick='anPreview()'>Preview (бесплатно)</button>"
        "<button class='mini' id='an-run-btn' onclick='anRunDry()'>Запустить анализ</button></div>"
        "<div id='an-msg' class='muted' style='margin-top:6px'></div></div>"
        # Календарь
        "<h2>Календарь публикаций</h2>"
        "<div class='card'><div class='muted' style='margin-bottom:6px'>"
        "<span class='an-dot published'></span> published "
        "<span class='an-dot scheduled'></span> scheduled "
        "<span class='an-dot failed'></span> failed "
        "<span class='an-dot needs_review'></span> needs_review</div>"
        "<div id='an-cal' class='an-cal'></div>"
        "<p class='muted'>Выберите проект — календарь и посты подгрузятся.</p></div>"
        # Список постов
        "<h2>Посты</h2>"
        "<div id='an-posts' class='muted'>Выберите проект.</div>"
        # Карточка анализа поста
        "<h2>Детализация поста</h2>"
        "<div class='card' id='an-detail'>"
        "<p class='muted'>Откройте анализ поста в списке выше.</p></div>"
        # Ручной ввод метрик
        "<h2>Метрики вручную</h2>"
        "<div class='card'>"
        "<button class='mini sec' onclick='anManualToggle()'>Внести метрики вручную</button>"
        "<span class='muted'> — сохранение бесплатно (0 units), source=manual.</span>"
        "<div id='an-manual' style='display:none;margin-top:10px'>"
        "<label>ID поста</label><input id='m-post' type='number' placeholder='post_id'>"
        "<div class='an-filters'>"
        "<div><label>views</label><input id='m-views' type='number' value='0'></div>"
        "<div><label>reach</label><input id='m-reach' type='number' value='0'></div>"
        "<div><label>impressions</label><input id='m-impressions' type='number' value='0'></div>"
        "<div><label>likes</label><input id='m-likes' type='number' value='0'></div>"
        "<div><label>comments</label><input id='m-comments' type='number' value='0'></div>"
        "<div><label>shares</label><input id='m-shares' type='number' value='0'></div>"
        "<div><label>saves</label><input id='m-saves' type='number' value='0'></div>"
        "<div><label>clicks</label><input id='m-clicks' type='number' value='0'></div>"
        "<div><label>followers_delta</label><input id='m-followers' type='number' value='0'></div>"
        "</div>"
        "<div style='margin-top:8px'><button class='mini' onclick='anManualSave()'>"
        "Сохранить метрики</button></div>"
        "<div id='an-manual-msg' class='muted' style='margin-top:6px'></div></div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const AN_PRICES={json.dumps(depth_prices)};"
        "let AN_BAL=0;let AN_POSTS=[];"
        "function pid(){return parseInt(gv('an-project'))||0;}"
        "function anEstimate(){const depth=gv('an-depth');const n=Math.max(1,parseInt(gv('an-count'))||1);"
        "const per=AN_PRICES[depth]||AN_PRICES.light||10;const total=per*n;"
        "const el=document.getElementById('an-estimate');if(el)el.textContent=total+' units';"
        "const btn=document.getElementById('an-run-btn');"
        "if(btn){if(AN_BAL<total){btn.disabled=true;btn.textContent='Пополнить баланс';}else{btn.disabled=false;btn.textContent='Запустить анализ';}}"
        "return total;}"
        "async function anPreview(){const a=parseInt(acc());const p=pid();const m=document.getElementById('an-msg');"
        "if(!a||!p){if(m)m.textContent='Выберите проект.';return;}"
        "try{const r=await api('POST','/analytics/accounts/'+a+'/preview',{project_id:p,depth:gv('an-depth'),platform:gv('an-platform'),status:gv('an-status')||null});"
        'if(m)m.innerHTML="<span class=\'pill ok\'>preview</span> Оценка: <b>"+r.estimated_units+" units</b> на "+r.post_count+" постов — списания нет.";}catch(x){if(m)m.textContent=String(x.message||x);}}'
        "async function anRunDry(){const a=parseInt(acc());const p=pid();const m=document.getElementById('an-msg');"
        "if(!a||!p){if(m)m.textContent='Выберите проект.';return;}"
        "const u=anEstimate();if(AN_BAL<u){location.href='/ui/billing';return;}"
        "try{const r=await api('POST','/analytics/accounts/'+a+'/run-dry',{project_id:p,depth:gv('an-depth'),platform:gv('an-platform'),status:gv('an-status')||null});"
        'if(m)m.innerHTML="<span class=\'pill ok\'>dry-run</span> Отчёт готов к запуску: <b>"+r.estimated_units+" units</b> за "+r.post_count+" постов. Списания нет; запуск с оплатой — отдельным действием.";}catch(x){if(m)m.textContent=String(x.message||x);}}'
        "function calDot(d){let s='';if(d.published_count)s+=\"<span class='an-dot published'></span>\";if(d.scheduled_count)s+=\"<span class='an-dot scheduled'></span>\";if(d.failed_count)s+=\"<span class='an-dot failed'></span>\";if(d.needs_review_count)s+=\"<span class='an-dot needs_review'></span>\";return s;}"
        "function renderCalendar(days){const host=document.getElementById('an-cal');if(!host)return;"
        "host.innerHTML=days.length?days.map(d=>`<div class='an-cell'><span class='d'>${esc(d.date)}</span><br>${calDot(d)}<br><span class='muted'>${(d.posts||[]).length} п.</span></div>`).join(''):\"<div class='muted'>Нет постов за период.</div>\";}"
        "function renderPosts(rows){AN_POSTS=rows;const host=document.getElementById('an-posts');if(!host)return;"
        "host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(r=>`<div class='sched-task'><h3>${esc(r.title)} <span class='pill ${r.status==='published'?'ok':'off'}'>${esc(r.status)}</span></h3>`"
        "+`<div class='sched-grid'>`"
        "+`<div><span class='k'>Платформы</span><span class='v'>${esc((r.platforms||[]).join(', ')||'—')}</span></div>`"
        "+`<div><span class='k'>media_count</span><span class='v'>${r.media_count}</span></div>`"
        "+`<div><span class='k'>Источник аналитики</span><span class='v'>${esc(r.analytics_source)}</span></div>`"
        "+`<div><span class='k'>quality_score</span><span class='v'>${r.quality_score}</span></div>`"
        "+`<div><span class='k'>engagement_score</span><span class='v'>${r.engagement_score}</span></div>`"
        "+`</div><div class='acts'><button class='mini sec' onclick='anOpenCard(${r.post_id})'>Открыть анализ</button></div></div>`).join('')"
        ":\"<div class='card muted'>Постов нет.</div>\";}"
        "async function anOpenCard(postId){const d=document.getElementById('an-detail');const eEl=document.getElementById('error');"
        "try{const c=await api('GET','/analytics/posts/'+postId+'/card?depth=deep');"
        "const mt=c.metrics||{};"
        "let recs=(c.recommendations||[]).map(x=>`<li>${esc(x)}</li>`).join('')||'<li class=\"muted\">—</li>';"
        "let pubs=(c.publications||[]).map(p=>`${esc(p.platform)} (${esc(p.status)})${p.external_url?(' · '+esc(p.external_url)):''}`).join('<br>')||'—';"
        "d.innerHTML=`<h3>${esc(c.title||('#'+c.post_id))} <span class='pill off'>источник: ${esc(c.metrics_source)}</span></h3>`"
        "+`<div class='muted' style='margin-bottom:6px'>Публикации:<br>${pubs}</div>`"
        "+`<div class='kv'>`"
        "+`<div><span class='k'>Показы (impressions)</span><span class='v'>${mt.impressions}</span></div>`"
        "+`<div><span class='k'>Охват (reach)</span><span class='v'>${mt.reach}</span></div>`"
        "+`<div><span class='k'>Просмотры (views)</span><span class='v'>${mt.views}</span></div>`"
        "+`<div><span class='k'>Лайки</span><span class='v'>${mt.likes}</span></div>`"
        "+`<div><span class='k'>Комментарии</span><span class='v'>${mt.comments}</span></div>`"
        "+`<div><span class='k'>Репосты/shares</span><span class='v'>${mt.shares}</span></div>`"
        "+`<div><span class='k'>Сохранения (saves)</span><span class='v'>${mt.saves}</span></div>`"
        "+`<div><span class='k'>Клики</span><span class='v'>${mt.clicks}</span></div>`"
        "+`<div><span class='k'>followers_delta</span><span class='v'>${mt.followers_delta}</span></div>`"
        "+`<div><span class='k'>ER</span><span class='v'>${mt.er}</span></div>`"
        "+`<div><span class='k'>CTR</span><span class='v'>${mt.ctr}</span></div>`"
        "+`</div><h3>Рекомендации (deep)</h3><ul>${recs}</ul>`"
        "+`<p class='muted'>Стоимость deep-анализа: ${c.cost_units} units.</p>`;}"
        "catch(x){err(eEl,String(x.message||x));}}"
        "function anManualToggle(){const f=document.getElementById('an-manual');if(f)f.style.display=(f.style.display==='none')?'block':'none';}"
        "async function anManualSave(){const post=parseInt(gv('m-post'));const msg=document.getElementById('an-manual-msg');"
        "if(!post){if(msg)msg.textContent='Укажите ID поста.';return;}"
        "const body={views:+gv('m-views')||0,reach:+gv('m-reach')||0,impressions:+gv('m-impressions')||0,likes:+gv('m-likes')||0,comments:+gv('m-comments')||0,shares:+gv('m-shares')||0,saves:+gv('m-saves')||0,clicks:+gv('m-clicks')||0,followers_delta:+gv('m-followers')||0};"
        "try{const r=await api('POST','/analytics/posts/'+post+'/manual-metrics',body);"
        'if(msg)msg.innerHTML="<span class=\'pill ok\'>сохранено</span> source="+esc(r.source)+" (0 units).";}catch(x){if(msg)msg.textContent=String(x.message||x);}}'
        "async function loadProject(){const a=parseInt(acc());const p=pid();if(!a||!p)return;"
        "const plat=gv('an-platform');const st=gv('an-status')||null;"
        "try{const posts=await api('GET','/analytics/projects/'+p+'/posts?platform='+encodeURIComponent(plat)+(st?('&post_status='+encodeURIComponent(st)):''));"
        "renderPosts(posts);const cnt=document.getElementById('an-count');if(cnt)cnt.value=Math.max(1,posts.length);anEstimate();"
        "const cal=await api('GET','/analytics/projects/'+p+'/calendar?platform='+encodeURIComponent(plat));renderCalendar(cal.days||[]);"
        "}catch(x){}}"
        "['an-depth','an-count'].forEach(id=>{const e=document.getElementById(id);if(e)e.addEventListener('input',anEstimate);});"
        "['an-project','an-platform','an-status'].forEach(id=>{const e=document.getElementById(id);if(e)e.addEventListener('change',loadProject);});"
        "const eEl=document.getElementById('error');"
        "(async()=>{try{anEstimate();const a=parseInt(acc());if(!a)return;"
        "try{const b=await api('GET','/billing/account/'+a+'/balance');AN_BAL=b.balance_units;"
        "document.getElementById('an-balance').innerHTML=`Баланс: <b>${b.balance_units}</b> units · <a href='/ui/billing'>Пополнить</a>`;anEstimate();}catch(e){}"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "const sel=document.getElementById('an-project');"
        "if(sel&&ps.length)sel.innerHTML=\"<option value=''>— выберите —</option>\"+ps.map(p=>`<option value='${p.id}'>${esc(p.name)}</option>`).join('');"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Аналитика", body, script, active="analytics")


def _guide_body() -> str:
    """Обзорный гайд Botfleet: что это, проекты, платформы, расписание, units.

    Подробные инструкции подключения площадок вынесены в разделы платформ
    (``/ui/guide/{platform}`` и вкладка «Гайд» на странице платформы). Здесь —
    только обзор и ссылки. Полностью статический текст, без секретов.
    """

    def _pg(platform: str, sub: str) -> str:
        label = _platform_label(platform)
        icon = _platform_icon(platform)
        return (
            f"<a class='pick-card' href='/ui/guide/{platform}'>"
            f"<span class='ico'>{icon}</span><b>{html.escape(label)}</b>"
            f"<span class='st'>{sub}</span></a>"
        )

    return "".join(
        [
            "<div class='hero'><p>Botfleet — «флот ботов» для автопостинга: один проект "
            "готовит публикации сразу под несколько площадок. Это обзор; подробные "
            "инструкции подключения — в разделе каждой платформы.</p></div>",
            "<div class='quicklinks'>"
            "<a href='#botfleet'>Что такое Botfleet</a>"
            "<a href='#projects'>Проекты</a>"
            "<a href='#platforms'>Платформы</a>"
            "<a href='#schedule'>Расписание</a>"
            "<a href='#units'>units</a>"
            "<a href='#preview'>preview / dry-run</a>"
            "<a href='#live'>Почему live выключен</a>"
            "<a href='#security'>Безопасность</a>"
            "</div>",
            # Быстрый старт (краткий)
            "<h2>Быстрый старт</h2>"
            "<ol class='steps'>"
            "<li>Зарегистрируйтесь и создайте проект.</li>"
            "<li>Подключите площадки (гайд — в разделе платформы).</li>"
            "<li>Добавьте медиа-источник и расписание.</li>"
            "<li>Запустите preview / dry-run и проверьте результат.</li>"
            "</ol>",
            # Что такое Botfleet
            "<h2 id='botfleet'>Что такое Botfleet</h2>"
            "<div class='guide-grid'>"
            "<div class='gcard'><h3>🧠 Один проект — много площадок</h3><ul>"
            "<li>Проект хранит бренд, ключи, медиа-источники и расписание.</li>"
            "<li>Из одного контента бот готовит варианты под каждую площадку.</li>"
            "<li>Каждая площадка подключается своим ключом/токеном.</li>"
            "</ul></div>"
            "<div class='gcard'><h3>🛟 Безопасно по умолчанию</h3><ul>"
            "<li>Сначала preview / dry-run, затем ревью.</li>"
            "<li>Live-публикация — только с явным флагом.</li>"
            "<li>Секреты хранятся в окружении, в UI — только маска.</li>"
            "</ul></div></div>",
            # Проекты
            "<h2 id='projects'>Как устроены проекты</h2>"
            "<p class='muted'>Аккаунт (workspace) → проекты → платформы. Вы видите только "
            "свои аккаунты и проекты. В проекте — платформы публикации, медиа-источники, "
            "категории продвижения и расписания.</p>",
            # Платформы (ссылки на платформенные гайды)
            "<h2 id='platforms'>Как устроены платформы</h2>"
            "<p class='subhint'>Инструкция подключения — внутри каждой площадки. Откройте "
            "нужный гайд:</p>"
            "<div class='platform-pick'>"
            + _pg("telegram", "Текст + фото")
            + _pg("vk", "Текст + фото (user-token)")
            + _pg("instagram", "Нужен image_url")
            + _pg("yandex_disk", "Медиа-источник")
            + "</div>"
            "<p class='muted'>Будущие площадки: YouTube, RuTube, Google Drive — "
            "адаптеры-скелеты, live планируется.</p>",
            # Расписание
            "<h2 id='schedule'>Что такое расписание</h2>"
            "<p class='muted'>Расписание — отдельные задачи внутри платформы: дни недели, "
            "время, тег/категория, режим (draft / semi_auto). Без плана бот ничего не "
            "публикует; плановая рассылка не запускается из интерфейса случайно.</p>",
            # units
            "<h2 id='units'>Что такое units</h2>"
            "<p class='muted'>units — внутренняя валюта Botfleet. Списываются за платные "
            "действия: генерация текста, публикация, аналитика, пересборка расписания. "
            "Цены и правила — на странице <a href='/ui/tariffs'>Тарифы</a>. dry-run / "
            "preview — бесплатно.</p>",
            # preview
            "<h2 id='preview'>Что такое preview / dry-run</h2>"
            "<p class='muted'>Безопасный прогон: видно, что и куда ушло бы, без отправки и "
            "без вызовов внешних API. С него начинается любая проверка площадки.</p>",
            # live
            "<h2 id='live'>Почему live выключен по умолчанию</h2>"
            "<div class='callout warn'><b>Защита от случайной публикации</b>"
            "<p>Живые публикации выключены для всех площадок и включаются отдельным флагом "
            "окружения только после ревью. Из интерфейса live не включается.</p></div>",
            # Безопасность (кратко)
            "<h2 id='security'>Безопасность</h2>"
            "<div class='callout ok'><ul>"
            "<li>Вы видите только свои аккаунты и проекты.</li>"
            "<li>Секреты не показываются — только маска.</li>"
            "<li>Списание атомарное и идемпотентное; неуспех не списывает units.</li>"
            "<li>Разрушительные действия требуют подтверждения.</li>"
            "</ul></div>",
            # FAQ (кратко)
            "<h2 id='faq'>Частые вопросы</h2>"
            "<div class='faq'>"
            "<details><summary>Где инструкция подключения площадки?</summary>"
            "<p>В разделе платформы: откройте проект → карточку площадки → вкладка «Гайд "
            "подключения», либо ссылки выше.</p></details>"
            "<details><summary>Можно ли несколько проектов и платформ?</summary>"
            "<p>Да. Аккаунт содержит несколько проектов, в проекте — несколько площадок, у "
            "каждой свои настройки и расписания.</p></details>"
            "<details><summary>Как проверить, ничего не публикуя?</summary>"
            "<p>preview / dry-run на странице платформы — без отправки и внешних вызовов.</p>"
            "</details>"
            "</div>",
        ]
    )


@router.get("/guide", response_class=HTMLResponse)
@router.get("/help", response_class=HTMLResponse)
@router.get("/onboarding-guide", response_class=HTMLResponse)
def ui_guide() -> HTMLResponse:
    """Обзорный раздел «Гайд» — что такое Botfleet + ссылки на гайды платформ."""
    return _page("Как подключиться к Botfleet", _guide_body(), "", active="guide")


@router.get("/guide/{platform}", response_class=HTMLResponse)
def ui_platform_guide(platform: str) -> HTMLResponse:
    """Отдельный гайд подключения площадки (Telegram/VK/Instagram/Яндекс Диск)."""
    platform = _safe_slug(platform)
    label = _platform_label(platform)
    icon = _platform_icon(platform)
    body = (
        "<div class='inline'><a href='/ui/guide'>"
        "<button class='sec mini'>← Все гайды</button></a></div>"
        f"<div class='pw-head'><span class='big'>{icon}</span>"
        f"<h2 style='margin:0'>Гайд подключения · {html.escape(label)}</h2></div>"
        + _platform_guide_html(platform)
    )
    return _page(f"Гайд · {label}", body, "", active="guide")


@router.get("/settings", response_class=HTMLResponse)
def ui_settings() -> HTMLResponse:
    body = (
        "<div class='card'><div id='info' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Аккаунты</h3><p class='muted'>Переключить активный аккаунт: "
        "<a href='/ui/accounts'>Аккаунты →</a></p>"
        "<p class='muted'>Биллинг и тестовое пополнение: <a href='/ui/billing'>Биллинг →</a></p>"
        "<p class='muted'>Живые публикации выключены на этом этапе.</p></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{try{if(!tok()){document.getElementById('info').textContent='Вы не вошли.';return}"
        "const me=await api('GET','/auth/me');"
        "document.getElementById('info').innerHTML=`<b>${esc(me.user.full_name||me.user.email)}</b> · `"
        "+`${esc(me.user.email)} · аккаунтов: ${me.accounts.length}`;"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Настройки", body, script, active="settings")


@router.get("/billing", response_class=HTMLResponse)
def ui_billing() -> HTMLResponse:
    settings = get_settings()
    pay_live = bool(settings.payments_live_enabled)
    banner = (
        ""
        if pay_live
        else (
            "<div class='callout warn'><b>Боевые платежи выключены</b>"
            "<p>Сейчас создаётся mock/sandbox invoice. Баланс пополняется только после "
            "оплаты (mock-pay). Реальные деньги не списываются.</p></div>"
        )
    )
    body = (
        # Баланс
        "<div class='card'><div id='bal' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='sec mini' onclick='refresh()'>Обновить баланс</button></div></div>"
        # Пополнение
        "<h2>Пополнение</h2>"
        f"{banner}"
        "<div class='card'>"
        "<label>Сумма (units)</label>"
        "<div class='inline' style='margin:4px 0'>"
        "<button class='mini ghost' onclick='setAmt(100)'>100</button>"
        "<button class='mini ghost' onclick='setAmt(500)'>500</button>"
        "<button class='mini ghost' onclick='setAmt(1000)'>1000</button>"
        "<button class='mini ghost' onclick='setAmt(5000)'>5000</button>"
        "<button class='mini ghost' onclick='setAmt(10000)'>10000</button></div>"
        "<input id='amount' type='number' min='1' value='500' oninput='invPreview()'>"
        "<div class='an-filters' style='margin-top:8px'>"
        "<div><label>Метод</label><select id='method'>"
        "<option value='bank_card'>Банковская карта</option>"
        "<option value='sbp'>СБП</option>"
        "<option value='qr'>QR-код</option>"
        "<option value='invoice_for_ip'>Счёт для ИП</option>"
        "<option value='invoice_for_company'>Счёт для ООО</option></select></div>"
        "<div><label>Провайдер</label><select id='provider'></select></div>"
        "</div>"
        "<div id='inv-preview' class='muted' style='margin-top:6px'></div>"
        "<div class='inline' style='margin-top:10px'>"
        "<button onclick='createInvoice()'>Создать счёт</button></div>"
        "<div id='inv-result' class='muted' style='margin-top:8px'></div></div>"
        # Реквизиты плательщика
        "<h2>Реквизиты плательщика</h2>"
        "<div class='card'>"
        "<label>Тип клиента</label><select id='customer_type'>"
        "<option value='individual'>Физлицо</option><option value='ip'>ИП</option>"
        "<option value='company'>ООО</option></select>"
        "<div class='an-filters' style='margin-top:8px'>"
        "<div><label>ИНН</label><input id='inn'></div>"
        "<div><label>КПП</label><input id='kpp'></div>"
        "<div><label>ОГРН/ОГРНИП</label><input id='ogrn'></div>"
        "<div><label>Название/ФИО</label><input id='legal_name'></div>"
        "<div><label>Email</label><input id='email'></div>"
        "<div><label>Телефон</label><input id='phone'></div></div>"
        "<div style='margin-top:8px'><button class='mini sec' onclick='saveProfile()'>"
        "Сохранить реквизиты</button></div>"
        "<div id='profile-msg' class='muted' style='margin-top:6px'></div></div>"
        # История
        "<h2>История</h2>"
        "<div class='card'><h3>Счета</h3><div id='invoices' class='muted'>—</div></div>"
        "<div class='card'><h3>Операции (units)</h3><div id='ledger' class='muted'>—</div></div>"
        "<div class='card'><h3>Usage-события</h3><div id='usage' class='muted'>—</div></div>"
        # Безопасность
        "<div class='callout ok'><b>Безопасность платежей</b><ul>"
        "<li>Платежи проходят через provider webhook; баланс пополняется только после "
        "paid.</li>"
        "<li>Создание счёта не меняет баланс; повтор оплаты не пополняет дважды.</li>"
        "<li>Ручное пополнение (manual topup) — только через admin/CLI.</li>"
        "<li>Секреты провайдеров не показываются (только маска).</li>"
        "</ul></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PAY_LIVE={json.dumps(pay_live)};"
        "const eEl=document.getElementById('error');const B=document.getElementById('bal');"
        "function setAmt(v){const a=document.getElementById('amount');if(a){a.value=v;invPreview();}}"
        "async function refresh(){const a=needAccount(eEl);if(!a)return;try{"
        "const b=await api('GET','/billing/account/'+a+'/balance');"
        "B.innerHTML=`Аккаунт #${b.account_id}: <b>${b.balance_units}</b> ${esc(b.currency)} · тариф ${esc(b.tariff_plan_slug||'—')} · ${esc(b.status)}`;"
        "}catch(x){err(eEl,x)}}"
        "async function invPreview(){const a=parseInt(acc());if(!a)return;const amt=parseInt(gv('amount'))||0;"
        "if(amt<=0)return;try{const r=await api('POST','/billing/account/'+a+'/topup/preview',{amount_units:amt,method:gv('method'),provider:gv('provider')||null});"
        "const el=document.getElementById('inv-preview');if(el)el.textContent=amt+' units ≈ '+r.amount_rub+' ₽ · провайдер '+r.provider+(r.payments_live_enabled?'':' (mock/sandbox)');}catch(e){}}"
        "async function createInvoice(){const a=needAccount(eEl);if(!a)return;const amt=parseInt(gv('amount'));"
        "if(!amt||amt<=0){err(eEl,new Error('Укажите сумму > 0.'));return}eEl.style.display='none';"
        "const customer={customer_type:gv('customer_type'),inn:gv('inn')||null,kpp:gv('kpp')||null,ogrn:gv('ogrn')||null,legal_name:gv('legal_name')||null,email:gv('email')||null,phone:gv('phone')||null};"
        "try{const inv=await api('POST','/billing/account/'+a+'/invoices',{amount_units:amt,method:gv('method'),provider:gv('provider')||null,customer:customer});"
        "const R=document.getElementById('inv-result');"
        "let pay=inv.provider==='mock'?`<button class='mini' onclick='mockPay(${inv.id})'>Оплатить (mock)</button>`:'';"
        "R.innerHTML=`<span class='pill off'>${esc(inv.status)}</span> Счёт #${inv.id} на ${inv.amount_units} units (${inv.amount_rub} ₽) · ${esc(inv.provider)}/${esc(inv.method)}`"
        "+(inv.qr_payload?`<br><span class='muted'>QR: <code>${esc(inv.qr_payload)}</code></span>`:'')+`<br>${pay}`;"
        "loadHistory();}catch(x){err(eEl,x)}}"
        "async function mockPay(id){const a=parseInt(acc());eEl.style.display='none';"
        "try{const inv=await api('POST','/billing/invoices/'+id+'/mock-pay',{});"
        "document.getElementById('inv-result').innerHTML=`<span class='pill ok'>${esc(inv.status)}</span> Счёт #${inv.id} оплачен — баланс пополнен.`;"
        "refresh();initShell();loadHistory();}catch(x){err(eEl,x)}}"
        "async function saveProfile(){const a=needAccount(eEl);if(!a)return;const msg=document.getElementById('profile-msg');"
        "try{await api('PUT','/billing/account/'+a+'/profile',{customer_type:gv('customer_type'),inn:gv('inn')||null,kpp:gv('kpp')||null,ogrn:gv('ogrn')||null,legal_name:gv('legal_name')||null,email:gv('email')||null,phone:gv('phone')||null});"
        "if(msg)msg.innerHTML=\"<span class='pill ok'>сохранено</span>\";}catch(x){if(msg)msg.textContent=String(x.message||x);}}"
        "async function loadHistory(){const a=parseInt(acc());if(!a)return;"
        "try{const inv=await api('GET','/billing/account/'+a+'/invoices');"
        "document.getElementById('invoices').innerHTML=inv.length?inv.map(i=>`<div>#${i.id} · ${esc(i.status)} · ${i.amount_units} units (${i.amount_rub} ₽) · ${esc(i.provider)}/${esc(i.method)}</div>`).join(''):'—';}catch(e){}"
        "try{const l=await api('GET','/billing/account/'+a+'/ledger');"
        "document.getElementById('ledger').innerHTML=l.length?l.map(e=>`<div>${esc(e.entry_type)} ${e.amount_units>0?'+':''}${e.amount_units} → ${e.balance_after_units} · ${esc(e.description)}</div>`).join(''):'—';}catch(e){}"
        "try{const us=await api('GET','/billing/account/'+a+'/usage-events');"
        "document.getElementById('usage').innerHTML=us.length?us.map(u=>`<div>${esc(u.event_type)} · ${u.units} units</div>`).join(''):'—';}catch(e){}}"
        "(async()=>{try{const prov=await api('GET','/billing/providers');const sel=document.getElementById('provider');"
        "if(sel)sel.innerHTML=prov.map(p=>`<option value='${p.provider}'${p.usable?'':' disabled'}>${p.provider}${p.usable?'':' (недоступен)'}</option>`).join('');}catch(e){}"
        "refresh();invPreview();loadHistory();"
        "const a=parseInt(acc());if(a){try{const pr=await api('GET','/billing/account/'+a+'/profile');if(pr){"
        "['customer_type','inn','kpp','ogrn','legal_name','email','phone'].forEach(k=>{const el=document.getElementById(k);if(el&&pr[k]!=null)el.value=pr[k];});}}catch(e){}}"
        "})();"
    )
    return _page("Биллинг", body, script, active="settings")
