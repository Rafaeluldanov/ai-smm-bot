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
from app.services.platform_catalog_service import (
    PlatformCatalogItem,
    PlatformCatalogService,
)
from app.services.platform_connection_schema_service import PlatformConnectionSchemaService
from app.services.unit_economics_service import UnitEconomicsService

_CATALOG = PlatformCatalogService()
_CONN_SCHEMA = PlatformConnectionSchemaService()

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
/* Каталог платформ: адаптивная сетка карточек с оригинальными SVG-иконками */
.platform-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin:10px 0 6px;align-items:stretch}
@media(max-width:900px){.platform-grid{grid-template-columns:repeat(auto-fill,minmax(200px,1fr))}}
@media(max-width:560px){.platform-grid{grid-template-columns:1fr}}
.platform-card{display:flex;flex-direction:column;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:0 1px 2px var(--shadow);color:var(--text);min-height:170px;transition:transform .08s,border-color .08s,box-shadow .08s}
.platform-card:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 8px 22px var(--shadow);text-decoration:none}
.platform-card.planned,.platform-card.research{opacity:.82}
.platform-card-head{display:flex;align-items:center;gap:10px}
.platform-icon{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:12px;background:var(--surface-soft);border:1px solid var(--border);color:var(--accent);flex:0 0 auto}
.platform-icon svg{width:24px;height:24px;display:block}
.pc-title{font-weight:700;font-size:15px}
.pc-cat{font-size:11px;color:var(--muted)}
.pc-badge{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--border);background:var(--surface-soft);color:var(--muted);width:fit-content}
.pc-badge.active{color:#1f9d55;border-color:rgba(31,157,85,.4)}
.pc-badge.beta{color:#c07d0a;border-color:rgba(192,125,10,.4)}
.pc-badge.planned,.pc-badge.research{color:var(--muted)}
.pc-conn{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:2px}
.pc-conn .prow{word-break:break-word}
.platform-card .open{margin-top:auto;font-size:13px;color:var(--accent);font-weight:600}
.pw-head .platform-icon{width:46px;height:46px;border-radius:14px}
.pw-head .platform-icon svg{width:28px;height:28px}
/* Форма подключения платформы (self-service) */
.cf-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin:8px 0}
.cf-field label{display:block;font-size:12px;color:var(--muted);margin-bottom:3px}
.cf-field input{width:100%}
.cf-field .cf-help{font-size:11px;margin-top:2px}
.cf-field .req{color:var(--danger)}
/* Акценты иконок платформ (оригинальные цвета «в духе», не официальные логотипы) */
.accent-telegram{color:#3aa0e0}.accent-vk{color:#4b74b3}.accent-instagram{color:#c95a9b}
.accent-website{color:#4a8f7b}.accent-yandex_disk{color:#d15a3a}.accent-youtube{color:#d1483a}
.accent-rutube{color:#7a5ad1}.accent-dzen{color:#3aa08a}.accent-odnoklassniki{color:#d58a2a}
.accent-google_drive{color:#3a8fd1}.accent-facebook_page{color:#4b74b3}.accent-tiktok{color:#c85a86}
.accent-pinterest{color:#c8483a}.accent-tenchat{color:#3a7fa0}.accent-vc_ru{color:#c07d0a}
.accent-linkedin{color:#3a6fa0}.accent-x_twitter{color:#6a7a86}.accent-threads{color:#8a5ad1}
.accent-email{color:#4a8f7b}.accent-blog_cms{color:#7a86a0}.accent-whatsapp_business{color:#3aa05a}
.accent-two_gis{color:#3aa05a}.accent-avito{color:#3a8fd1}.accent-pikabu{color:#3aa08a}
.accent-default{color:var(--accent)}
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
.an-summary{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:8px 0}
.an-summary .an-stat{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:10px 12px;box-shadow:0 1px 2px var(--shadow)}
.an-summary .an-stat .k{display:block;font-size:11px;color:var(--muted)}
.an-summary .an-stat .v{font-size:20px;font-weight:700;color:var(--text)}
.an-plat-ico{display:inline-flex;vertical-align:middle;width:18px;height:18px;color:var(--accent)}
.an-plat-ico svg{width:18px;height:18px}
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
.site-footer{padding:16px 26px;border-top:1px solid var(--border);color:var(--muted);font-size:12px;text-align:center}
.site-footer a{color:var(--muted)}.site-footer a:hover{color:var(--accent)}
.an-big{font-size:26px;font-weight:700;color:var(--text)}
.ap-status{display:inline-block;padding:6px 14px;border-radius:20px;font-weight:700;font-size:15px}
.ap-status.running{background:rgba(34,197,94,.15);color:#16a34a}
.ap-status.ready{background:rgba(59,130,246,.15);color:#2563eb}
.ap-status.setup{background:rgba(234,179,8,.18);color:#b45309}
.ap-status.problem{background:rgba(239,68,68,.15);color:#dc2626}
.ap-status.paused{background:var(--surface);color:var(--muted);border:1px solid var(--border)}
.ap-hero{font-size:22px;font-weight:800;margin:2px 0 4px}
.ap-big-btn{font-size:16px;padding:12px 24px;font-weight:700}
.ap-step{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}
.ap-step .dot{width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:13px;flex:0 0 auto}
.ap-step .dot.done{background:rgba(34,197,94,.18);color:#16a34a}
.ap-step .dot.todo{background:var(--surface);border:1px solid var(--border);color:var(--muted)}
.bnav{display:none}
@media (max-width:760px){.layout{grid-template-columns:1fr}.sidebar{border-right:0;border-bottom:1px solid var(--border)}.page-ctx{display:none}.an-cal{grid-template-columns:repeat(7,1fr)}
.bnav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:50;background:var(--surface);border-top:1px solid var(--border)}
.bnav-item{flex:1;text-align:center;padding:10px 4px;font-size:12px;color:var(--muted);text-decoration:none}
.bnav-item.active{color:var(--accent);font-weight:700}
.content{padding-bottom:64px}}
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
        "<a id='notif-bell' class='bell' href='/ui/notifications' title='Уведомления' "
        "aria-label='Уведомления' style='position:relative;text-decoration:none;font-size:18px;"
        "margin-right:10px;display:none'>🔔<span id='notif-count' style='display:none;position:"
        "absolute;top:-6px;right:-8px;background:#e5484d;color:#fff;border-radius:10px;font-size:"
        "10px;padding:0 5px;line-height:16px'>0</span></a>"
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
        "<a href='/ui/settings#sessions'>Сессии</a>"
        "<a href='#' onclick='logout();return false'>Выйти</a>"
        "</div></div></div></header>"
    )


# Общие JS-помощники: токен/аккаунт, fetch с Authorization, esc/XSS, инициализация
# header+sidebar (initShell) на каждой странице кабинета.
_SHARED_JS = r"""
function tok(){return localStorage.getItem('smm_token')||''}
function setTok(t){if(t)localStorage.setItem('smm_token',t)}
function csrf(){return localStorage.getItem('smm_csrf')||''}
function setCsrf(t){if(t)localStorage.setItem('smm_csrf',t)}
function acc(){return localStorage.getItem('smm_account_id')||''}
function setAcc(id){localStorage.setItem('smm_account_id',String(id))}
function saveSession(d){if(d){setTok(d.access_token||d.token); if(d.csrf_token)setCsrf(d.csrf_token);}}
function clearSession(){localStorage.removeItem('smm_token');localStorage.removeItem('smm_account_id');localStorage.removeItem('smm_csrf');}
async function logout(){try{await apiRaw('POST','/auth/logout');}catch(e){} clearSession();location.href='/ui/login'}
async function logoutAll(){try{await api('POST','/auth/logout-all');}catch(e){} clearSession();location.href='/ui/login'}
const _UNSAFE=['POST','PUT','PATCH','DELETE'];
function apiRaw(method,path,body,auth){
  const h={'Content-Type':'application/json'};
  if(auth!==false && tok()) h['Authorization']=tok();
  if(_UNSAFE.indexOf(method)>=0 && csrf()) h['X-CSRF-Token']=csrf();
  return fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
}
async function api(method,path,body,auth){
  let r=await apiRaw(method,path,body,auth);
  // 401 → одна попытка refresh (refresh-cookie httpOnly шлётся автоматически), затем повтор.
  if(r.status===401 && auth!==false && path.indexOf('/auth/')!==0){
    try{const rf=await fetch('/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'}});
      if(rf.ok){const d=await rf.json();saveSession(d);r=await apiRaw(method,path,body,auth);}
      else{clearSession();location.href='/ui/login';}
    }catch(e){}
  }
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
  const bell=document.getElementById('notif-bell');
  if(bell){ bell.style.display='';
    try{ const uc=await api('GET','/notifications/unread-count'); const nc=document.getElementById('notif-count');
      if(nc){ if(uc.unread_count>0){ nc.textContent=uc.unread_count>99?'99+':uc.unread_count; nc.style.display=''; } else { nc.style.display='none'; } }
    }catch(e){}
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
    """Левый sidebar (autopilot-first): Сегодня / Проекты / Аналитика / Оплата / Настройки / Advanced.

    Простая клиентская навигация. Сложные разделы (эксперименты, решения, воркер, вебхуки, доставка,
    безопасность) вынесены в Advanced, чтобы не перегружать основной сценарий «автопилот работает сам».
    """

    def cls(key: str) -> str:
        return " active" if active == key else ""

    return (
        "<aside class='sidebar'>"
        f"{_brand_full()}"
        f"<a class='sb-link{cls('today')}' href='/ui/today'>Сегодня</a>"
        "<div class='sb-group'><div class='sb-head'>"
        f"<a class='sb-title{cls('projects')}' href='/ui/projects'>Автопилот · Проекты</a>"
        "<a class='sb-add' href='/ui/projects/new' title='Новый проект'>+</a></div>"
        "<div id='sb-projects' class='sb-projects'><div class='muted sb-hint'>…</div></div></div>"
        f"<a class='sb-link{cls('analytics')}' href='/ui/analytics'>Аналитика</a>"
        f"<a class='sb-link{cls('tariffs')}' href='/ui/tariffs'>Оплата</a>"
        f"<a class='sb-link{cls('guide')}' href='/ui/guide'>Гайд</a>"
        f"<a class='sb-link{cls('settings')}' href='/ui/settings'>Настройки</a>"
        f"<a class='sb-link{cls('advanced')}' href='/ui/advanced'>Advanced</a>"
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
    footer = (
        "<footer class='site-footer'>"
        "<span class='muted'>© Botfleet · черновики документов, требуется юридическая "
        "проверка</span> "
        "<a href='/ui/legal/terms'>Условия</a> · "
        "<a href='/ui/legal/privacy'>Конфиденциальность</a> · "
        "<a href='/ui/legal/offer'>Оферта</a> · "
        "<a href='/ui/legal/payments'>Оплата</a>"
        "</footer>"
    )
    bottom_nav = _bottom_nav(active) if sidebar else ""
    document = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc_title} — {BRAND_NAME}</title><style>{_CSS}</style>{theme_init}</head><body>"
        f"{_header(title)}<div class='{layout_cls}'>{inner}</div>{footer}{bottom_nav}"
        f"<script>{_SHARED_JS}</script><script>{script}</script></body></html>"
    )
    return HTMLResponse(document)


def _bottom_nav(active: str = "") -> str:
    """Мобильная нижняя навигация (видна только на узких экранах): autopilot-first."""

    def cls(key: str) -> str:
        return " active" if active == key else ""

    return (
        "<nav class='bnav'>"
        f"<a class='bnav-item{cls('today')}' href='/ui/today'>Сегодня</a>"
        f"<a class='bnav-item{cls('projects')}' href='/ui/projects'>Автопилот</a>"
        f"<a class='bnav-item{cls('analytics')}' href='/ui/analytics'>Аналитика</a>"
        f"<a class='bnav-item{cls('tariffs')}' href='/ui/tariffs'>Оплата</a>"
        f"<a class='bnav-item{cls('advanced')}' href='/ui/advanced'>Ещё</a>"
        "</nav>"
    )


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
        "saveSession(d); if(d.accounts&&d.accounts[0]) setAcc(d.accounts[0].id);"
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
        "saveSession(d); if(d.accounts&&d.accounts[0]) setAcc(d.accounts[0].id);"
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
    item = _CATALOG.get(platform)
    if item is not None:
        return item.title_ru
    meta = _PLATFORM_META.get(platform)
    return meta["label"] if meta else platform


def _platform_icon(platform: str) -> str:
    meta = _PLATFORM_META.get(platform)
    return meta["icon"] if meta else "🔌"


def _platform_icon_svg(platform: str) -> str:
    """Оригинальная inline SVG-иконка платформы из каталога (стиль Botfleet)."""
    return _CATALOG.icon_svg(platform)


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
            "приватный Яндекс Диск не подходят — используется <b>Botfleet Media Proxy</b>: "
            "временная ссылка <code>/media/public/{token}</code> (см. вкладку «Обзор» → "
            "«Публичные ссылки на медиа» и страницу Media Proxy). В production нужен "
            "публичный HTTPS-домен.</p>"
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


def _platform_catalog_card(project_id: int, item: PlatformCatalogItem) -> str:
    """Карточка платформы для сетки дашборда (server-rendered, оригинальная SVG-иконка).

    ``.pc-conn[data-conn=key]`` — слот статуса подключения: JS дозаполняет его для
    настроенных площадок; по умолчанию показывает короткое описание из каталога.
    """
    href = f"/ui/projects/{project_id}/platforms/{item.key}"
    return (
        f"<a class='platform-card {item.support_level}' href='{href}' "
        f"data-platform='{item.key}'>"
        "<div class='platform-card-head'>"
        f"<span class='platform-icon {item.accent_class}'>{item.icon_svg}</span>"
        f"<div><div class='pc-title'>{html.escape(item.title_ru)}</div>"
        f"<div class='pc-cat'>{html.escape(item.category_title)}</div></div></div>"
        f"<span class='pc-badge {item.support_level}'>{html.escape(item.support_title)}</span>"
        f"<div class='pc-conn' data-conn='{item.key}'>"
        f"<span class='prow'>{html.escape(item.notes_short)}</span></div>"
        "<span class='open'>Открыть →</span></a>"
    )


@router.get("/projects/{project_id}/dashboard", response_class=HTMLResponse)
def ui_project_dashboard(project_id: int) -> HTMLResponse:
    _settings = get_settings()
    ig_cfg = {
        "user_id": _settings.instagram_effective_user_id or "",
        "token_present": bool(_settings.instagram_access_token),
    }
    cards = "".join(_platform_catalog_card(project_id, item) for item in _CATALOG.dashboard_items())
    body = (
        # Заголовок проекта (h1 заменяется на «Проект: {имя}» из JS) + баланс.
        "<div class='proj-head'><span id='pbadges'></span></div>"
        # Autopilot-first: главный CTA ведёт в автопилот (v0.5.6).
        "<div class='hero'><div class='ap-hero'>Автопостинг работает сам</div>"
        "<p class='muted'>Подключите площадки, дайте Яндекс Диск и выберите календарь — "
        "дальше Botfleet сам пишет и публикует.</p>"
        f"<a href='/ui/projects/{project_id}/autopilot'><button class='ap-big-btn'>Открыть автопилот</button></a></div>"
        # Действия проекта.
        f"<div class='proj-actions'>"
        f"<a href='/ui/projects/{project_id}/settings'><button class='sec mini'>Настройки проекта</button></a>"
        f"<a href='/ui/projects/{project_id}/settings#platforms'><button class='mini'>Создать платформу</button></a>"
        "<button class='mini sec' onclick='toggleSchedPicker()'>Создать расписание</button></div>"
        "<div id='sched-picker' class='card' style='display:none'>"
        "<p class='muted'>Выберите платформу для нового расписания:</p>"
        "<div id='sched-picker-links' class='inline'></div></div>"
        # Карточка контент-оптимизации (v0.4.2).
        "<div class='card'><h3>Рекомендации контента и A/B-тесты</h3>"
        "<p class='muted'>Botfleet подсказывает лучшую тему/CTA и помогает проверить варианты "
        "постов A/B. Live-публикаций нет — варианты идут в очередь ревью.</p>"
        "<div id='opt-hint' class='muted'>Лучший CTA / лучшая тема — загрузка…</div>"
        "<div id='sugg-hint' class='muted'>Новые рекомендации — загрузка…</div>"
        "<div id='td-hint' class='muted'>Следующая тема · почему бот её выберет — загрузка…</div>"
        "<div id='md-hint' class='muted'>Следующее медиа · почему бот выберет эти фото — загрузка…</div>"
        "<div id='rev-hint' class='muted'>Ревью медиатеки · активные задачи — загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        f"<a href='/ui/projects/{project_id}/recommendations'><button class='mini'>Рекомендации контента</button></a>"
        f"<a href='/ui/projects/{project_id}/experiment-suggestions'><button class='mini sec'>A/B предложения</button></a>"
        f"<a href='/ui/projects/{project_id}/topic-decisions'><button class='mini sec'>Следующая тема</button></a>"
        f"<a href='/ui/projects/{project_id}/media-decisions'><button class='mini sec'>Следующее медиа</button></a>"
        f"<a href='/ui/projects/{project_id}/media-curation-review'><button class='mini sec'>Ревью медиатеки</button></a>"
        f"<a href='/ui/projects/{project_id}/experiments'><button class='mini ghost'>A/B тесты</button></a>"
        f"<a href='/ui/projects/{project_id}/optimization'><button class='mini ghost'>Оптимизация</button></a>"
        "</div></div>"
        # Сетка платформ из каталога (server-rendered, оригинальные SVG-иконки).
        "<h2>Платформы</h2>"
        "<p class='muted'>Каталог площадок Botfleet: активные, ближайшие и планируемые. "
        "Карточки кликабельны — откройте площадку, чтобы увидеть настройки, гайд и статус.</p>"
        f"<div id='plats' class='platform-grid'>{cards}</div>"
        # Компактная активность после платформ.
        "<h2>Активность</h2><div id='activity' class='card muted'>Загрузка…</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};"
        # Подсказка оптимизации (лучший CTA / лучшая тема) в карточке дашборда.
        "(async()=>{try{const s=await api('GET','/experiments/projects/'+PID+'/strategy');"
        "const el=document.getElementById('opt-hint');if(!el)return;el.classList.remove('muted');"
        "const cta=(s.best_cta&&s.best_cta[0])||'—';const topic=(s.will_do_more&&s.will_do_more[0])||'—';"
        "el.innerHTML='Лучший CTA: <b>'+esc(''+cta)+'</b> · Лучшая тема: <b>'+esc(''+topic)+'</b>';}catch(e){}})();"
        # Подсказка новых рекомендаций worker-а (A/B предложения).
        "(async()=>{try{const d=await api('GET','/experiment-suggestions/projects/'+PID+'/dashboard');"
        "const el=document.getElementById('sugg-hint');if(!el)return;el.classList.remove('muted');"
        "el.innerHTML='Новые рекомендации: <b>'+d.active_count+'</b> · экспериментов: <b>'+d.experiments_created+'</b>';}catch(e){}})();"
        # Подсказка «Следующая тема» (автовыбор темы, preview — без записи).
        "(async()=>{try{const r=await api('POST','/topic-decisions/projects/'+PID+'/preview',{});"
        "const el=document.getElementById('td-hint');if(!el)return;el.classList.remove('muted');"
        "el.innerHTML='Следующая тема: <b>'+esc(''+r.selected_topic)+'</b> · '+Math.round((r.confidence_score||0)*100)+'% ('+esc(''+r.decision_source)+')';}catch(e){}})();"
        # Подсказка «Следующее медиа» (автовыбор медиа, preview — без записи).
        "(async()=>{try{const r=await api('POST','/media-decisions/projects/'+PID+'/preview',{});"
        "const el=document.getElementById('md-hint');if(!el)return;el.classList.remove('muted');"
        "el.innerHTML='Следующее медиа: <b>'+esc(''+r.selected_strategy)+'</b> · '+esc(''+r.selected_media_count)+' шт · '+Math.round((r.confidence_score||0)*100)+'% ('+esc(''+r.decision_source)+')';}catch(e){}})();"
        # Подсказка «Ревью медиатеки» (активные задачи согласования + overdue).
        "(async()=>{try{const d=await api('GET','/media-curation-review/projects/'+PID+'/dashboard');"
        "const el=document.getElementById('rev-hint');if(!el)return;el.classList.remove('muted');"
        "el.innerHTML='Ревью медиатеки: активных задач <b>'+d.active_review_tasks+'</b> · на одобрении: <b>'+d.approved+'</b> · overdue: <b>'+d.overdue+'</b>';}catch(e){}})();"
        f"const IG_CFG={json.dumps(ig_cfg)};"
        "function toggleSchedPicker(){const p=document.getElementById('sched-picker');"
        "if(p)p.style.display=(p.style.display==='none'||!p.style.display)?'block':'none';}"
        "const eEl=document.getElementById('error');"
        "const A=document.getElementById('activity');"
        # Статус подключения + ключевые данные для карточки настроенной площадки (без секретов).
        "function connRows(pt,r){"
        "if(pt==='vk')return `<div class='prow'>Group ID: ${esc((r&&r.external_id)||'—')}</div>`"
        "+`<div class='prow'>token: ${(r&&r.has_api_key)?'сохранён':'нет'} · live: выключен</div>`;"
        "if(pt==='telegram')return `<div class='prow'>Channel: ${esc((r&&r.external_id)||'—')}</div>`"
        "+`<div class='prow'>bot token: ${(r&&r.has_api_key)?'сохранён':'нет'} · media group</div>`;"
        "if(pt==='instagram')return `<div class='prow'>User ID: ${esc((r&&r.external_id)||IG_CFG.user_id||'—')}</div>`"
        "+`<div class='prow'>token: ${((r&&r.has_api_key)||IG_CFG.token_present)?'сохранён':'нет'} · image_url required</div>`;"
        "if(pt==='yandex_disk')return `<div class='prow'>root: ${esc((r&&r.yandex_root_folder)||'—')}</div>`"
        "+`<div class='prow'>public url: ${(r&&r.yandex_public_url)?'да':'—'} · теги: ${esc(((r&&r.tags)||[]).join(', ')||'—')}</div>`;"
        "if(pt==='website')return `<div class='prow'>${esc((r&&r.url)||'—')}</div>`;"
        "return '';}"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        # Заголовок «Проект: {имя}».
        "const h1=document.querySelector('main h1');if(h1)h1.textContent='Проект: '+(d.project_name||('#'+PID));"
        "document.getElementById('pbadges').innerHTML="
        "`<span class='badge'>${esc(d.project_slug)}</span>`"
        "+`<span class='badge'>баланс: ${d.billing_balance_units==null?'—':d.billing_balance_units} units</span>`"
        "+`<span class='badge'>платформы: ${d.platforms_count}</span>`"
        "+`<span class='badge'>планы: ${d.active_plans_count}</span>`;"
        # Карта ресурсов по типу платформы (без секрета) — дозаполняем карточки каталога.
        "const byType={};((d.extra&&d.extra.platforms)||[]).forEach(p=>{byType[p.platform_type]=p;});"
        "document.querySelectorAll('.pc-conn').forEach(slot=>{const pt=slot.dataset.conn;const r=byType[pt];"
        "if(!r)return;const on=!!(r.external_id||r.url||r.has_api_key||r.yandex_public_url);"
        "const st=`<span class='pill ${on?'ok':'off'}'>${on?'подключено':'не подключено'}</span>`;"
        "const rows=connRows(pt,r);slot.innerHTML=`<div class='prow'>${st}</div>`+rows;});"
        # Пикер платформ для нового расписания — только настроенные площадки.
        "const links=Object.keys(byType);const use=links.length?links:['telegram','vk','instagram'];"
        "document.getElementById('sched-picker-links').innerHTML=use.map(pt=>"
        "`<a href='/ui/projects/${PID}/platforms/${encodeURIComponent(pt)}/schedule'><button class='mini sec'>${esc(pt)}</button></a>`).join('');"
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


def _connection_form_html(platform: str, planned: bool) -> str:
    """Server-rendered форма подключения платформы (поля из схемы, без секретов).

    Секреты — write-only: значение не рендерится, показывается только статус/маска (JS).
    """
    schema = _CONN_SCHEMA.get_connection_schema(platform)
    disabled = " disabled" if planned else ""
    rows: list[str] = []
    for f in schema.fields:
        fid = f"cf-{f.name}"
        ph = html.escape(f.placeholder or "")
        if f.secret:
            help_txt = "Секрет не показывается. Оставьте поле пустым, чтобы не менять сохранённый."
            inp = (
                f"<input id='{fid}' type='password' autocomplete='new-password' "
                f"data-field='{f.name}' data-secret='1' placeholder='{ph}'{disabled}>"
            )
        else:
            input_type = "url" if f.type == "url" else "text"
            list_hint = " (через запятую)" if f.type == "list" else ""
            help_txt = html.escape(f.help or "") + list_hint
            inp = (
                f"<input id='{fid}' type='{input_type}' data-field='{f.name}' "
                f"placeholder='{ph}'{disabled}>"
            )
        req = " <span class='req'>*</span>" if f.required else ""
        rows.append(
            f"<div class='cf-field'><label for='{fid}'>{html.escape(f.label)}{req}</label>"
            f"{inp}<div class='cf-help muted'>{help_txt}</div></div>"
        )
    steps = "".join(f"<li>{html.escape(s)}</li>" for s in schema.test_steps)
    warns = "".join(f"<li>{html.escape(w)}</li>" for w in schema.warnings)
    btns = (
        "<button class='mini' onclick='connSave()'>Сохранить</button>"
        "<button class='mini sec' onclick='connCheck()'>Проверить подключение</button>"
        "<button class='mini ghost' onclick='connDisconnect()'>Отключить</button>"
        if not planned
        else "<button class='mini' disabled>Интеграция в разработке</button>"
    )
    return (
        "<div class='card' id='conn-card'><h3>Подключение</h3>"
        "<p class='muted'>Заполните ключи и ID площадки — они хранятся в проекте (не в .env), "
        "секреты шифруются и показываются только маской.</p>"
        "<div id='conn-status' class='muted' style='margin-bottom:8px'>Загрузка…</div>"
        f"<div class='cf-grid'>{''.join(rows)}</div>"
        f"<div class='inline' style='margin-top:10px'>{btns}</div>"
        "<div id='conn-result' class='muted' style='margin-top:8px'></div>"
        f"<div class='callout' style='margin-top:10px'><b>Что проверяется</b><ul>{steps}</ul></div>"
        + (f"<div class='callout warn'><b>Важно</b><ul>{warns}</ul></div>" if warns else "")
        + f"<p class='muted'>{html.escape(schema.media_requirements)}</p></div>"
    )


def _media_proxy_section_html(project_id: int, settings: Settings) -> str:
    """Секция «Публичные ссылки на медиа» (media-proxy) для платформ с image_url."""
    base = html.escape(settings.media_proxy_public_base_url_effective or "—")
    https_ready = settings.media_proxy_https_ready
    enabled = settings.media_proxy_enabled
    ttl_h = settings.media_proxy_default_ttl_seconds // 3600
    max_mb = settings.media_proxy_max_bytes // (1024 * 1024)
    ready_pill = (
        "<span class='pill ok'>HTTPS готов</span>"
        if https_ready
        else "<span class='pill off'>HTTPS не готов</span>"
    )
    warn = (
        ""
        if https_ready
        else (
            "<div class='callout warn'><b>Нужен публичный HTTPS-домен</b>"
            "<p>Локальный/не-HTTPS base URL недоступен внешним платформам (Instagram/Meta). "
            "Задайте PUBLIC_APP_URL / MEDIA_PROXY_PUBLIC_BASE_URL с публичным HTTPS.</p></div>"
        )
    )
    return (
        "<div class='card' id='mediaproxy-card'><h3>Публичные ссылки на медиа</h3>"
        "<p class='muted'>Instagram API требует публичный HTTPS <b>image_url</b>. Botfleet "
        "Media Proxy создаёт временную ссылку вида "
        "<code>https://app.example.ru/media/public/****</code> — она ограничена сроком "
        "действия и её можно отозвать.</p>"
        "<div class='kv'>"
        f"<div><span class='k'>MEDIA_PROXY_ENABLED</span><span class='v'>{'true' if enabled else 'false'}</span></div>"
        f"<div><span class='k'>Public base URL</span><span class='v'><code>{base}</code></span></div>"
        f"<div><span class='k'>HTTPS ready</span><span class='v'>{ready_pill}</span></div>"
        f"<div><span class='k'>Default TTL</span><span class='v'>{ttl_h} ч</span></div>"
        f"<div><span class='k'>Max file size</span><span class='v'>{max_mb} MB</span></div>"
        "</div>"
        f"{warn}"
        "<div class='inline' style='margin-top:10px'>"
        f"<a href='/ui/projects/{project_id}/media-proxy'><button class='mini sec'>Открыть список ссылок</button></a>"
        "<a href='/ui/guide/instagram'><button class='mini ghost'>Гайд по media proxy</button></a>"
        "</div>"
        "<p class='muted' style='margin-top:6px'>Живая публикация Instagram выключена — "
        "это foundation для публичного image_url (dry-run ссылок не создаёт).</p></div>"
    )


@router.get("/projects/{project_id}/platforms/{platform}", response_class=HTMLResponse)
def ui_platform_workspace(project_id: int, platform: str) -> HTMLResponse:
    """Рабочая область платформы: вкладки Обзор/Настройки/Гайд/Расписание/Preview/Аналитика."""
    platform = _safe_slug(platform)
    settings = get_settings()
    item = _CATALOG.get(platform)
    label = _platform_label(platform)
    icon_svg = _platform_icon_svg(platform)
    accent = item.accent_class if item is not None else "accent-default"
    support_badge = (
        f"<span class='pc-badge {item.support_level}'>{html.escape(item.support_title)}</span>"
        if item is not None
        else ""
    )
    planned = bool(item is not None and item.is_planned)
    planned_banner = (
        (
            "<div class='callout warn'><b>Интеграция в разработке</b>"
            f"<p>{html.escape(item.title_ru)} — {html.escape(item.support_title.lower())}. "
            "Подключение и публикация пока выключены (кнопки недоступны). Доступны обзор, "
            "роадмап и демо-аналитика; реальные вызовы API не выполняются.</p></div>"
        )
        if planned and item is not None
        else ""
    )
    roadmap_extra = (
        (
            "<div class='card'><h3>Роадмап интеграции</h3>"
            f"<p class='muted'>{html.escape(item.notes_short)}</p><ul>"
            "<li>Подключение аккаунта/токена площадки.</li>"
            "<li>Безопасный preview/dry-run без реальных вызовов API.</li>"
            "<li>Публикация по расписанию — после платформенных тестов.</li>"
            "<li>Демо-аналитика уже доступна по существующим постам.</li>"
            "</ul></div>"
        )
        if item is not None and (item.is_planned or item.support_level == "beta")
        else ""
    )
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
    conn_form = _connection_form_html(platform, planned)
    settings_pane = conn_form + _platform_settings_pane(platform, settings)
    # Media proxy: для платформ, которым нужен публичный image_url (Instagram и др.).
    media_proxy_section = (
        _media_proxy_section_html(project_id, settings)
        if item is not None and item.requires_public_media_url
        else ""
    )
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a></div>"
        f"<div class='pw-head'><span class='platform-icon {accent}'>{icon_svg}</span>"
        f"<h2 style='margin:0'>{html.escape(label)}</h2>"
        f"{support_badge}"
        "<span id='pw-status' class='pill off'>…</span></div>"
        f"{planned_banner}"
        f"<div class='tabs'>{tabs_bar}</div>"
        # Обзор
        "<div class='tabpane active' id='pane-overview'>"
        "<div class='card'><div id='pw-overview' class='muted'>Загрузка…</div></div>"
        f"{roadmap_extra}"
        f"{media_proxy_section}"
        # Журнал действий (аудит проекта по платформе, без секретов).
        "<div class='card'><h3>Журнал действий</h3>"
        "<p class='muted'>Логи создаются автоматически: подключение, изменение токена, "
        "проверка, расписание, публикация, аналитика. Секреты не пишутся.</p>"
        "<div id='conn-logs' class='muted'>Загрузка…</div></div></div>"
        # Настройки
        f"<div class='tabpane' id='pane-settings'>{settings_pane}</div>"
        # Гайд
        f"<div class='tabpane' id='pane-guide'>{guide_html}</div>"
        # Расписание
        "<div class='tabpane' id='pane-schedule'>"
        "<div class='inline'><a id='sched-new-link' href='#'>"
        "<button class='mini'>Создать расписание</button></a></div>"
        "<div id='sched-host' class='sched-list'><div class='muted'>Загрузка…</div></div>"
        # Автоматизация расписаний (движок due-задач → draft, без live).
        "<div class='card' id='sched-automation'><h3>Автоматизация расписаний</h3>"
        "<div class='callout'><b>Как это работает</b>"
        "<p>Botfleet находит due-задачи и создаёт <b>draft/needs_review</b> посты + "
        "публикации (pending/scheduled), списывая units. <b>Живая публикация выключена</b> "
        "— всё уходит на ревью. Повторный запуск не создаёт дубли (идемпотентность).</p>"
        "<p class='muted'>Подключите платформу (вкладка «Настройки»), если она не "
        "подключена. Если не хватает units — пополните баланс.</p></div>"
        "<div id='sa-tasks' class='muted'>Загрузка задач…</div>"
        "<div class='inline' style='margin-top:10px'>"
        "<button class='mini sec' onclick='saPreviewDue()'>Preview due</button>"
        "<button class='mini' onclick='saRunDue()'>Создать drafts сейчас</button>"
        "<a id='sa-runs-link' href='#'><button class='mini ghost'>История запусков</button></a>"
        "</div>"
        "<div id='sa-result' class='muted' style='margin-top:8px'></div>"
        # Мини-статус фонового worker-а.
        "<p class='muted' style='margin-top:8px'>Фоновый worker: <span id='sa-worker'>—</span> · "
        "<a href='/ui/scheduler'>Открыть автоматизацию →</a></p></div></div>"
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
    # --- JS формы подключения (self-service) + журнал действий --- #
    conn_js = (
        "const CBASE='/projects/'+PID+'/platform-connections/'+encodeURIComponent(PLATFORM);"
        "function cf(name){return document.querySelector(`[data-field='${name}']`);}"
        "function connPayload(){const out={};document.querySelectorAll('#conn-card [data-field]').forEach(el=>{"
        "const v=(el.value||'').trim();if(el.dataset.secret){if(v)out[el.dataset.field]=v;}"
        "else{out[el.dataset.field]=el.dataset.field==='tags'?v.split(',').map(s=>s.trim()).filter(Boolean):v;}});return out;}"
        "async function connLoad(){try{const d=await api('GET',CBASE);const c=d.connection;const st=document.getElementById('conn-status');"
        "if(!c){if(st)st.innerHTML=\"<span class='pill off'>не подключено</span> Заполните поля и сохраните.\";return;}"
        "['title','external_id','url','root_folder','app_id','redirect_uri','default_cta'].forEach(k=>{const el=cf(k);if(el&&c[k]!=null)el.value=c[k];});"
        "const tg=cf('tags');if(tg&&Array.isArray(c.tags))tg.value=c.tags.join(', ');"
        "const sec=c.api_key_masked?(' · токен: '+esc(c.api_key_masked)):' · токен: —';"
        "const lc=c.last_check_status?(`<br>Последняя проверка: <b>${esc(c.last_check_status)}</b> · ${esc(c.last_check_at||'')} · ${esc(c.last_check_message||'')}`):'';"
        "if(st)st.innerHTML=`<span class='pill ${c.connected?'ok':'off'}'>${c.connected?'подключено':'черновик'}</span> статус: ${esc(c.status)}${sec}${lc}`;"
        "}catch(e){}}"
        "async function connSave(){const R=document.getElementById('conn-result');R.textContent='Сохранение…';"
        "try{const c=await api('POST',CBASE,connPayload());R.innerHTML=\"<span class='pill ok'>сохранено</span> токен: \"+esc(c.api_key_masked||'—');"
        "document.querySelectorAll('#conn-card [data-secret]').forEach(el=>{el.value='';});connLoad();connLogs();initShell();}catch(x){R.textContent=String(x.message||x);}}"
        "async function connCheck(){const R=document.getElementById('conn-result');R.textContent='Проверка…';"
        "try{const r=await api('POST',CBASE+'/check',{});"
        "const items=(r.checks||[]).map(i=>`<div>${i.ok?'✅':(i.status==='warning'?'⚠️':(i.status==='planned'?'🕓':'❌'))} <b>${esc(i.label)}</b> — ${esc(i.message)}</div>`).join('');"
        "const steps=(r.next_steps||[]).map(s=>`<li>${esc(s)}</li>`).join('');"
        "R.innerHTML=`<div class='callout ${r.status==='ok'?'ok':(r.status==='error'?'':'warn')}'><b>Проверка: ${esc(r.status)}</b><div class='muted'>${esc(r.message)}</div>${items}`+(steps?`<b>Что делать</b><ul>${steps}</ul>`:'')+`</div>`;"
        "connLoad();connLogs();}catch(x){R.textContent=String(x.message||x);}}"
        "async function connDisconnect(){if(!confirm('Отключить платформу? Секрет будет деактивирован.'))return;"
        "const R=document.getElementById('conn-result');try{await api('DELETE',CBASE);R.innerHTML=\"<span class='pill off'>отключено</span>\";"
        "document.querySelectorAll('#conn-card [data-field]').forEach(el=>{el.value='';});connLoad();connLogs();initShell();}catch(x){R.textContent=String(x.message||x);}}"
        "async function connLogs(){const host=document.getElementById('conn-logs');if(!host)return;"
        "try{const rows=await api('GET',CBASE+'/logs?limit=20');host.classList.remove('muted');"
        "host.innerHTML=rows.length?`<table class='price-table'><thead><tr><th>Действие</th><th>Когда</th><th>Статус</th></tr></thead><tbody>`"
        "+rows.map(r=>`<tr><td>${esc(r.action)}</td><td class='muted'>${esc((r.created_at||'').replace('T',' ').slice(0,16))}</td><td>${esc(r.status||'—')}</td></tr>`).join('')+`</tbody></table>`"
        ":\"<div class='muted'>Пока нет действий.</div>\";}catch(e){}}"
        "window.connSave=connSave;window.connCheck=connCheck;window.connDisconnect=connDisconnect;"
        "connLoad();connLogs();"
    )
    # --- JS автоматизации расписаний (preview/run due, задачи) --- #
    sa_js = (
        "const SBASE='/schedule/projects/'+PID;"
        "const saRunsLink=document.getElementById('sa-runs-link');"
        "if(saRunsLink)saRunsLink.href='/ui/projects/'+PID+'/schedule-runs?platform='+encodeURIComponent(PLATFORM);"
        "async function saLoadTasks(){const host=document.getElementById('sa-tasks');if(!host)return;"
        "try{const rows=await api('GET',SBASE+'/tasks?platform_key='+encodeURIComponent(PLATFORM));host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(t=>`<div class='sched-grid'>`"
        "+`<div><span class='k'>План</span><span class='v'>#${t.plan_id} ${esc(t.title||'')}</span></div>`"
        "+`<div><span class='k'>Время</span><span class='v'>${esc((t.publish_times||[]).join(', ')||'—')}</span></div>`"
        "+`<div><span class='k'>Подключение</span><span class='v'><span class='pill ${t.connection_status==='missing'?'off':'ok'}'>${esc(t.connection_status)}</span></span></div>`"
        "+`<div><span class='k'>units/пост</span><span class='v'>${t.estimated_units_per_post}</span></div>`"
        "+`<div><span class='k'>Следующий</span><span class='v'>${esc((t.next_run_at||'—').replace('T',' ').slice(0,16))}</span></div>`"
        "+`</div>`+((t.warnings||[]).length?`<div class='muted'>⚠️ ${esc(t.warnings.join('; '))}</div>`:'')).join('<hr>')"
        ":\"<div class='muted'>Задач расписания нет. Создайте расписание выше.</div>\";}catch(e){}}"
        "async function saPreviewDue(){const a=needAccount(eEl);if(!a)return;const R=document.getElementById('sa-result');R.textContent='Preview…';"
        "try{const r=await api('POST',SBASE+'/preview-due',{account_id:a,platform_key:PLATFORM});"
        "R.innerHTML=`<span class='pill ok'>preview</span> Due: <b>${r.due_count}</b> · units нужно: <b>${r.total_units}</b> · баланс ${r.balance_units} · `"
        "+(r.affordable?'хватает':'<b>не хватает — пополните</b>')+`<div class='muted'>`+(r.entries||[]).map(e=>esc(e.platform_key+' '+e.planned_time+' → '+e.outcome)).join('<br>')+`</div>`;"
        "}catch(x){err(eEl,x)}}"
        "async function saRunDue(){const a=needAccount(eEl);if(!a)return;if(!confirm('Создать drafts по due-задачам? (live-публикации нет)'))return;"
        "const R=document.getElementById('sa-result');R.textContent='Создание drafts…';"
        "try{const r=await api('POST',SBASE+'/run-due',{account_id:a,platform_key:PLATFORM});"
        "R.innerHTML=`<span class='pill ok'>готово</span> Создано drafts: <b>${r.created}</b> · пропущено: ${r.skipped}`"
        "+`<div class='muted'>`+(r.entries||[]).map(e=>esc((e.platform_key||PLATFORM)+' → '+(e.outcome||e.status))).join('<br>')+`</div>`;"
        "initShell();}catch(x){err(eEl,x)}}"
        "window.saPreviewDue=saPreviewDue;window.saRunDue=saRunDue;"
        "async function saWorker(){const el=document.getElementById('sa-worker');if(!el)return;"
        "try{const s=await api('GET','/scheduler-worker/status');"
        "el.innerHTML=s.enabled?\"<span class='pill ok'>включён</span>\":\"<span class='pill off'>выключен</span>\";}catch(e){}}"
        "saLoadTasks();saWorker();"
    )
    return _page(
        label,
        body,
        _SCHED_TASKS_JS + script + conn_js + sa_js,
        active="projects",
        active_pid=project_id,
    )


@router.get("/projects/{project_id}/media-proxy", response_class=HTMLResponse)
def ui_media_proxy(project_id: int) -> HTMLResponse:
    """Страница media-proxy проекта: статус, список публичных ссылок, отзыв."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a></div>"
        "<h2>Публичные ссылки на медиа (Media Proxy)</h2>"
        "<p class='muted'>Instagram и другие платформы требуют публичный HTTPS "
        "<b>image_url</b>. Botfleet выдаёт временную ссылку "
        "<code>/media/public/{token}</code>: токен случайный, хранится только хеш, ссылка "
        "ограничена по времени и отзывается. Живая публикация Instagram выключена.</p>"
        # Статус
        "<div class='card'><h3>Статус</h3><div id='mp-status' class='kv'>"
        "<div class='muted'>Загрузка…</div></div></div>"
        # Список ссылок
        "<h2>Ссылки</h2>"
        "<div id='mp-links' class='muted'>Загрузка…</div>"
        "<div class='callout ok' style='margin-top:12px'><b>Безопасность</b><ul>"
        "<li>Raw-токен не хранится в БД (только sha256-хеш) и не пишется в логи/аудит.</li>"
        "<li>Ссылка ограничена по времени, отзывается, привязана к проекту/медиа.</li>"
        "<li>Content-type ограничен allowlist, размер — лимитом; внутренние пути не "
        "раскрываются.</li>"
        "</ul></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "function fmtTtl(s){return Math.round((s||0)/3600)+' ч';}"
        "async function mpStatus(){try{const s=await api('GET','/media-proxy/projects/'+PID+'/status');"
        "const host=document.getElementById('mp-status');"
        "const rd=s.https_ready?\"<span class='pill ok'>да</span>\":\"<span class='pill off'>нет</span>\";"
        "host.innerHTML=`<div><span class='k'>MEDIA_PROXY_ENABLED</span><span class='v'>${s.enabled}</span></div>`"
        "+`<div><span class='k'>Public base URL</span><span class='v'><code>${esc(s.base_url||'—')}</code></span></div>`"
        "+`<div><span class='k'>HTTPS ready</span><span class='v'>${rd}</span></div>`"
        "+`<div><span class='k'>Default TTL</span><span class='v'>${fmtTtl(s.default_ttl_seconds)}</span></div>`"
        "+`<div><span class='k'>Max size</span><span class='v'>${Math.round((s.max_bytes||0)/1048576)} MB</span></div>`;"
        "if((s.warnings||[]).length||(s.errors||[]).length){host.innerHTML+=`<div class='v muted'>`+[...(s.errors||[]),...(s.warnings||[])].map(esc).join('<br>')+`</div>`;}"
        "}catch(x){err(eEl,x)}}"
        "async function mpRevoke(id){if(!confirm('Отозвать ссылку?'))return;"
        "try{await api('DELETE','/media-proxy/projects/'+PID+'/links/'+id);mpLinks();}catch(x){err(eEl,x)}}"
        "window.mpRevoke=mpRevoke;"
        "async function mpLinks(){const host=document.getElementById('mp-links');"
        "try{const rows=await api('GET','/media-proxy/projects/'+PID+'/links');host.classList.remove('muted');"
        "host.innerHTML=rows.length?`<table class='price-table'><thead><tr><th>ID</th><th>Purpose</th><th>Статус</th>"
        "<th>Media</th><th>Истекает</th><th>Обращений</th><th></th></tr></thead><tbody>`"
        "+rows.map(r=>`<tr><td>#${r.id}</td><td>${esc(r.purpose)}</td>"
        "<td><span class='pill ${r.status==='active'?'ok':'off'}'>${esc(r.status)}</span></td>"
        "<td>#${r.media_asset_id} ${esc(r.content_type||'')}</td>"
        "<td class='muted'>${esc((r.expires_at||'').replace('T',' ').slice(0,16))}</td>"
        "<td>${r.hit_count}</td>"
        "<td>${r.status==='active'?`<button class='mini ghost' onclick='mpRevoke(${r.id})'>Отозвать</button>`:''}</td></tr>`).join('')"
        "+`</tbody></table>`:\"<div class='card muted'>Ссылок пока нет. Создайте их на странице платформы или через API/CLI.</div>\";"
        "}catch(x){err(eEl,x)}}"
        "mpStatus();mpLinks();"
    )
    return _page("Media Proxy", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/schedule-runs", response_class=HTMLResponse)
def ui_schedule_runs(project_id: int) -> HTMLResponse:
    """Страница истории прогонов расписания проекта (что бот сделал/пропустил)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a></div>"
        "<h2>История запусков расписания</h2>"
        "<p class='muted'>Что сделал движок автоматизации по due-задачам: создал draft, "
        "пропустил (дубликат) или остановился на ошибке (нет подключения / не хватает "
        "units). <b>Живой публикации нет</b> — всё уходит на ревью.</p>"
        # Фильтры
        "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='sr-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Статус</label><select id='sr-status'>"
        "<option value=''>Все</option><option value='draft_created'>draft_created</option>"
        "<option value='skipped'>skipped</option><option value='failed'>failed</option>"
        "<option value='insufficient_balance'>insufficient_balance</option>"
        "<option value='missing_credentials'>missing_credentials</option></select></div>"
        "</div></div>"
        "<div id='sr-list' class='muted'>Загрузка…</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "function stPill(s){const ok=s==='draft_created';const off=(s==='failed'||s==='missing_credentials'||s==='insufficient_balance');"
        "return `<span class='pill ${ok?'ok':(off?'off':'')}'>${esc(s)}</span>`;}"
        "async function loadRuns(){const host=document.getElementById('sr-list');"
        "const p=gv('sr-platform');const st=gv('sr-status');"
        "let url='/schedule/projects/'+PID+'/runs?';if(p)url+='platform_key='+encodeURIComponent(p)+'&';if(st)url+='run_status='+encodeURIComponent(st);"
        "try{const rows=await api('GET',url);host.classList.remove('muted');"
        "host.innerHTML=rows.length?`<table class='price-table'><thead><tr><th>ID</th><th>Дата</th><th>Платформа</th><th>План</th>"
        "<th>Статус</th><th>Post</th><th>Pub</th><th>units</th><th>Ошибка</th></tr></thead><tbody>`"
        "+rows.map(r=>`<tr><td>#${r.id}</td><td class='muted'>${esc((r.run_date||'')+' '+(r.planned_time||''))}</td>"
        "<td>${esc(r.platform_key)}</td><td>${r.plan_id?('#'+r.plan_id):'—'}</td>"
        "<td>${stPill(r.status)}</td><td>${r.post_id?('#'+r.post_id):'—'}</td>"
        "<td>${r.publication_id?('#'+r.publication_id):'—'}</td><td>${r.units_charged}</td>"
        "<td class='muted'>${esc(r.error_message||'')}</td></tr>`).join('')+`</tbody></table>`"
        ":\"<div class='card muted'>Запусков ещё нет. Откройте платформу и нажмите «Создать drafts сейчас».</div>\";"
        "}catch(x){err(eEl,x)}}"
        "['sr-platform','sr-status'].forEach(id=>{const e=document.getElementById(id);if(e)e.addEventListener('change',loadRuns);});"
        "const q=new URLSearchParams(location.search).get('platform');if(q){const s=document.getElementById('sr-platform');if(s)s.value=q;}"
        "loadRuns();"
    )
    return _page("Запуски расписания", body, script, active="projects", active_pid=project_id)


@router.get("/scheduler", response_class=HTMLResponse)
def ui_scheduler() -> HTMLResponse:
    """Страница фонового scheduler-worker: статус, безопасный tick, lease."""
    body = (
        "<h2>Фоновый worker расписаний</h2>"
        "<div class='callout warn'><b>Живые публикации выключены</b>"
        "<p>Worker создаёт только <b>draft/needs_review</b> посты по due-задачам расписаний "
        "и списывает units за успех. Реальные публикации и внешние вызовы платформ НЕ "
        "выполняются. В production worker должен идти <b>отдельным процессом/контейнером</b> "
        "(не внутри web-приложения).</p></div>"
        # Статус
        "<div class='card'><h3>Статус</h3><div id='sw-status' class='kv'>"
        "<div class='muted'>Загрузка…</div></div>"
        "<div id='sw-warnings' class='muted' style='margin-top:6px'></div></div>"
        # Эксперименты и рекомендации (v0.4.3)
        "<div class='card'><h3>Эксперименты и рекомендации</h3>"
        "<p class='muted'>Worker может предлагать эксперименты/темы (без live-публикации). "
        "Генерация worker-ом и авто-создание экспериментов выключены по умолчанию.</p>"
        "<div id='sw-exp' class='kv'><div class='muted'>Загрузка…</div></div>"
        "<div id='sw-exp-tick' class='muted' style='margin-top:6px'></div></div>"
        # Автовыбор тем в worker (v0.4.4)
        "<div class='card'><h3>Автовыбор тем в worker</h3>"
        "<p class='muted'>Worker сам выбирает тему/CTA/формат для слота по обучению (без "
        "live-публикации). Автовыбор worker-ом выключен по умолчанию; dry-run по умолчанию.</p>"
        "<div id='sw-topic' class='kv'><div class='muted'>Загрузка…</div></div></div>"
        # Автовыбор медиа в worker (v0.4.5)
        "<div class='card'><h3>Автовыбор медиа в worker</h3>"
        "<p class='muted'>Worker сам выбирает media strategy и конкретные медиа для слота по "
        "теме/тегам/платформе/обучению (без live-публикации; публичные ссылки не создаются). "
        "Автовыбор worker-ом выключен по умолчанию; dry-run по умолчанию.</p>"
        "<div id='sw-media' class='kv'><div class='muted'>Загрузка…</div></div></div>"
        # Оценка качества медиа в worker (v0.4.6)
        "<div class='card'><h3>Media quality scoring in worker</h3>"
        "<p class='muted'>Worker оценивает качество/дубли медиатеки проектов — "
        "правило-ориентированно, без внешнего AI и без live-публикации. Оценка worker-ом "
        "выключена по умолчанию; dry-run по умолчанию.</p>"
        "<div id='sw-quality' class='kv'><div class='muted'>Загрузка…</div></div></div>"
        # Fingerprint и дубли медиа в worker (v0.4.7)
        "<div class='card'><h3>Fingerprint и дубли медиа в worker</h3>"
        "<p class='muted'>Worker считает локальные fingerprint и кластеры дублей медиатеки — "
        "без внешнего AI/vision, без сети по умолчанию, без удаления файлов и без live-публикации. "
        "Fingerprint worker-ом выключен по умолчанию; dry-run по умолчанию.</p>"
        "<div id='sw-fingerprint' class='kv'><div class='muted'>Загрузка…</div></div></div>"
        # Курирование медиатеки в worker (v0.4.8)
        "<div class='card'><h3>Курирование медиатеки в worker</h3>"
        "<p class='muted'>Worker предлагает задачи очистки/разметки медиатеки — без внешнего AI, "
        "без применения тегов/скрытия/удаления автоматически, без live-публикации. Курирование "
        "worker-ом выключено по умолчанию; dry-run по умолчанию.</p>"
        "<div id='sw-curation' class='kv'><div class='muted'>Загрузка…</div></div></div>"
        # Действия
        "<div class='card'><h3>Безопасный запуск</h3>"
        "<p class='muted'>Preview tick — dry-run (ничего не создаёт). Run one safe tick — "
        "создаёт draft/needs_review, если включён режим создания черновиков; live не будет.</p>"
        "<div class='inline'>"
        "<button class='mini sec' onclick='swTickDry()'>Preview tick</button>"
        "<button class='mini' onclick='swTick()'>Run one safe tick</button>"
        "<a href='/ui/projects/1/schedule-runs'><button class='mini ghost'>Открыть запуски расписания</button></a>"
        "</div>"
        "<div id='sw-result' class='muted' style='margin-top:8px'></div></div>"
        # Lease
        "<div class='card'><h3>Lease (DB-lock)</h3><div id='sw-leases' class='muted'>Загрузка…</div>"
        "<p class='muted'>Lease гарантирует один активный worker. Если процесс умер — lease "
        "истекает по TTL и перехватывается.</p></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "function yn(b){return b?\"<span class='pill ok'>да</span>\":\"<span class='pill off'>нет</span>\";}"
        "async function swStatus(){try{const s=await api('GET','/scheduler-worker/status');"
        "const host=document.getElementById('sw-status');"
        "host.innerHTML=`<div><span class='k'>Включён</span><span class='v'>${yn(s.enabled)}</span></div>`"
        "+`<div><span class='k'>Dry-run</span><span class='v'>${yn(s.dry_run)}</span></div>`"
        "+`<div><span class='k'>Создаёт черновики</span><span class='v'>${yn(s.create_drafts)}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(s.live_publish)}</span></div>`"
        "+`<div><span class='k'>Интервал</span><span class='v'>${s.interval_seconds} c</span></div>`"
        "+`<div><span class='k'>Batch</span><span class='v'>${s.batch_size}</span></div>`;"
        "document.getElementById('sw-warnings').innerHTML=(s.warnings||[]).map(esc).join('<br>');"
        "const es=s.experiment_suggestions||{};const eh=document.getElementById('sw-exp');"
        "if(eh){eh.innerHTML=`<div><span class='k'>EXPERIMENT_SUGGESTIONS_WORKER_ENABLED</span><span class='v'>${yn(es.worker_enabled)}</span></div>`"
        "+`<div><span class='k'>EXPERIMENT_SUGGESTIONS_DRY_RUN</span><span class='v'>${yn(es.dry_run)}</span></div>`"
        "+`<div><span class='k'>EXPERIMENT_SUGGESTIONS_AUTO_CREATE</span><span class='v'>${yn(es.auto_create)}</span></div>`"
        "+`<div><span class='k'>SCHEDULE_EXPERIMENTS_ENABLED</span><span class='v'>${yn(es.schedule_experiments_enabled)}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(false)}</span></div>`;}"
        "const ts=s.auto_topic_selection||{};const th=document.getElementById('sw-topic');"
        "if(th){th.innerHTML=`<div><span class='k'>AUTO_TOPIC_SELECTION_WORKER_ENABLED</span><span class='v'>${yn(ts.worker_enabled)}</span></div>`"
        "+`<div><span class='k'>AUTO_TOPIC_SELECTION_DRY_RUN</span><span class='v'>${yn(ts.dry_run)}</span></div>`"
        "+`<div><span class='k'>AUTO_TOPIC_SELECTION_ENABLED</span><span class='v'>${yn(ts.enabled)}</span></div>`"
        "+`<div><span class='k'>min confidence</span><span class='v'>${ts.min_confidence}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(false)}</span></div>`;}"
        "const ms=s.auto_media_selection||{};const mh=document.getElementById('sw-media');"
        "if(mh){mh.innerHTML=`<div><span class='k'>AUTO_MEDIA_SELECTION_WORKER_ENABLED</span><span class='v'>${yn(ms.worker_enabled)}</span></div>`"
        "+`<div><span class='k'>AUTO_MEDIA_SELECTION_DRY_RUN</span><span class='v'>${yn(ms.dry_run)}</span></div>`"
        "+`<div><span class='k'>AUTO_MEDIA_SELECTION_ENABLED</span><span class='v'>${yn(ms.enabled)}</span></div>`"
        "+`<div><span class='k'>AUTO_MEDIA_SELECTION_CREATE_PUBLIC_LINKS</span><span class='v'>${yn(ms.create_public_links)}</span></div>`"
        "+`<div><span class='k'>min confidence</span><span class='v'>${ms.min_confidence}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(false)}</span></div>`;}"
        "const mq=s.media_quality_scoring||{};const qh=document.getElementById('sw-quality');"
        "if(qh){qh.innerHTML=`<div><span class='k'>MEDIA_QUALITY_SCORING_WORKER_ENABLED</span><span class='v'>${yn(mq.worker_enabled)}</span></div>`"
        "+`<div><span class='k'>MEDIA_QUALITY_SCORING_DRY_RUN</span><span class='v'>${yn(mq.dry_run)}</span></div>`"
        "+`<div><span class='k'>MEDIA_QUALITY_SCORING_ENABLED</span><span class='v'>${yn(mq.enabled)}</span></div>`"
        "+`<div><span class='k'>MEDIA_QUALITY_EXTERNAL_AI_ENABLED</span><span class='v'>${yn(mq.external_ai)}</span></div>`"
        "+`<div><span class='k'>порог good</span><span class='v'>${mq.min_good_score}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(false)}</span></div>`;}"
        "const mf=s.media_fingerprinting||{};const fh=document.getElementById('sw-fingerprint');"
        "if(fh){fh.innerHTML=`<div><span class='k'>MEDIA_FINGERPRINTING_WORKER_ENABLED</span><span class='v'>${yn(mf.worker_enabled)}</span></div>`"
        "+`<div><span class='k'>MEDIA_FINGERPRINTING_DRY_RUN</span><span class='v'>${yn(mf.dry_run)}</span></div>`"
        "+`<div><span class='k'>MEDIA_FINGERPRINTING_ENABLED</span><span class='v'>${yn(mf.enabled)}</span></div>`"
        "+`<div><span class='k'>MEDIA_FINGERPRINTING_EXTERNAL_AI_ENABLED</span><span class='v'>${yn(mf.external_ai)}</span></div>`"
        "+`<div><span class='k'>MEDIA_DUPLICATE_AUTO_DELETE_ENABLED</span><span class='v'>${yn(mf.auto_delete)}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(false)}</span></div>`;}"
        "const mc=s.media_curation||{};const ch=document.getElementById('sw-curation');"
        "if(ch){ch.innerHTML=`<div><span class='k'>MEDIA_CURATION_WORKER_ENABLED</span><span class='v'>${yn(mc.worker_enabled)}</span></div>`"
        "+`<div><span class='k'>MEDIA_CURATION_DRY_RUN</span><span class='v'>${yn(mc.dry_run)}</span></div>`"
        "+`<div><span class='k'>MEDIA_CURATION_ENABLED</span><span class='v'>${yn(mc.enabled)}</span></div>`"
        "+`<div><span class='k'>MEDIA_CURATION_AUTO_APPLY_TAGS</span><span class='v'>${yn(mc.auto_apply_tags)}</span></div>`"
        "+`<div><span class='k'>MEDIA_CURATION_AUTO_DELETE_ENABLED</span><span class='v'>${yn(mc.auto_delete)}</span></div>`"
        "+`<div><span class='k'>Live-публикация</span><span class='v'>${yn(false)}</span></div>`;}"
        "}catch(x){err(eEl,x)}}"
        "function tickSummary(r){return `<span class='pill ${r.lease_acquired?'ok':'off'}'>lease ${r.lease_acquired?'ok':'занята'}</span> `"
        "+`dry_run=${r.dry_run} · scanned=${r.targets_scanned} · drafts=${r.drafts_created} · runs=${r.schedule_runs_created} · `"
        "+`skipped=${r.skipped} · missing_creds=${r.missing_credentials} · low_balance=${r.insufficient_balance}`"
        "+`<div class='muted'>Предложения: enabled=${r.experiment_suggestions_enabled} · created=${r.experiment_suggestions_created} · experiments=${r.experiments_created} · no live publish</div>`"
        "+`<div class='muted'>Автовыбор тем: enabled=${r.auto_topic_selection_enabled} · previewed=${r.topic_decisions_previewed} · created=${r.topic_decisions_created} · low_conf=${r.low_confidence_decisions} · no live publish</div>`"
        "+`<div class='muted'>Автовыбор медиа: enabled=${r.auto_media_selection_enabled} · previewed=${r.media_decisions_previewed} · created=${r.media_decisions_created} · low_conf=${r.low_confidence_media_decisions} · no_media=${r.no_media_decisions} · no live publish</div>`"
        "+`<div class='muted'>Качество медиа: enabled=${r.media_quality_scoring_enabled} · scanned=${r.media_quality_assets_scanned} · snapshots=${r.media_quality_snapshots_created} · weak=${r.media_quality_weak_count} · дубли=${r.media_quality_duplicate_count} · no external AI</div>`"
        "+`<div class='muted'>Fingerprint медиа: enabled=${r.media_fingerprinting_enabled} · fp_prev=${r.media_fingerprints_previewed} · fp_new=${r.media_fingerprints_created} · clusters_prev=${r.duplicate_clusters_previewed} · clusters_new=${r.duplicate_clusters_created} · no external AI</div>`"
        "+`<div class='muted'>Курирование: enabled=${r.media_curation_enabled} · prev=${r.media_curation_tasks_previewed} · created=${r.media_curation_tasks_created} · hidden=${r.media_curation_hidden_count} · no auto-apply/delete</div>`"
        "+((r.errors||[]).length?`<div class='muted'>`+r.errors.map(esc).join('<br>')+`</div>`:'');}"
        "async function swTickDry(){const R=document.getElementById('sw-result');R.textContent='Preview…';"
        "try{const r=await api('POST','/scheduler-worker/tick-dry',{});R.innerHTML=tickSummary(r);swLeases();}catch(x){err(eEl,x)}}"
        "async function swTick(){if(!confirm('Запустить один безопасный тик? (live-публикации нет)'))return;"
        "const R=document.getElementById('sw-result');R.textContent='Тик…';"
        "try{const r=await api('POST','/scheduler-worker/tick',{force:true});R.innerHTML=tickSummary(r);swStatus();swLeases();}catch(x){err(eEl,x)}}"
        "async function swLeases(){try{const rows=await api('GET','/scheduler-worker/leases');"
        "const host=document.getElementById('sw-leases');host.classList.remove('muted');"
        "host.innerHTML=rows.length?`<table class='price-table'><thead><tr><th>Ключ</th><th>Владелец</th><th>Статус</th><th>Истекает</th></tr></thead><tbody>`"
        "+rows.map(r=>`<tr><td>${esc(r.lease_key)}</td><td class='muted'>${esc(r.owner_id)}</td>"
        "<td><span class='pill ${r.status==='active'?'ok':'off'}'>${esc(r.status)}</span></td>"
        "<td class='muted'>${esc((r.expires_at||'').replace('T',' ').slice(0,19))}</td></tr>`).join('')+`</tbody></table>`"
        ":\"<div class='muted'>Активных lease нет.</div>\";}catch(e){}}"
        "swStatus();swLeases();"
    )
    return _page("Scheduler", body, script, active="scheduler")


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
        "<h2>units и оплата</h2>"
        "<div class='callout'><b>Как считаются деньги (MVP)</b><ul>"
        "<li>1 unit ≈ 1 ₽ — ориентировочный курс для учёта (BILLING_UNIT_PRICE_RUB).</li>"
        "<li>Стоимость действия в units берётся из таблицы выше (себестоимость × наценка).</li>"
        "<li>Наценка ×2 к себестоимости токенов AI-провайдера (markup).</li>"
        "<li>Комиссия эквайринга (YooKassa/СБП) пока не входит в цену units и будет "
        "показываться отдельно после подключения провайдера.</li>"
        "<li>НДС/налоги и бухгалтерский учёт оформляются позже с бухгалтером и юристом; "
        "текущие суммы — предварительные, оферта в статусе черновика.</li>"
        "</ul></div>"
        "<div class='callout warn'><b>Боевые платежи выключены</b>"
        "<p>Сейчас пополнение тестовое (mock/sandbox), реальные деньги не списываются. "
        "Данные карты вводятся только на стороне провайдера — не в Botfleet.</p></div>"
        "<p class='muted'>Реальные платежи пока не подключены; пополнение тестовое во "
        "внутренних units. <a href='/ui/billing'>Тестовое пополнение →</a> · "
        "<a href='/ui/legal/payments'>Условия оплаты (черновик) →</a></p>"
    )
    return _page("Тарифы", body, "", active="tariffs")


@router.get("/analytics", response_class=HTMLResponse)
def ui_analytics() -> HTMLResponse:
    economics = UnitEconomicsService()
    depth_prices = {row["depth"]: row["units"] for row in economics.analytics_price_table()}
    platform_icons = {i.key: i.icon_svg for i in _CATALOG.items()}
    body = (
        # Верхний блок: баланс + подсказка.
        "<div class='card'><div id='an-balance' class='muted'>Баланс: загрузка…</div>"
        "<p class='muted'>Preview бесплатно, запуск отчёта списывает units. Источник метрик "
        "всегда указывается (internal / manual / estimated / api / demo). Демо-метрики — "
        "оценка по тексту и структуре, НЕ реальные API-данные. Реальные вызовы внешних API "
        "не выполняются.</p>"
        "<p class='muted'>Импорт метрик, ручной ввод и влияние на обучение — на странице "
        "<a href='/ui/metrics'>«Метрики и обучение»</a>.</p></div>"
        # Summary cards (сводка по проекту).
        "<div id='an-summary' class='an-summary'></div>"
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
        # Demo-аналитика по существующим публикациям (offline).
        "<h2>Demo-аналитика постов</h2>"
        "<p class='muted'>По уже существующим публикациям VK/Telegram: оценка охвата, ER и "
        "качества. Источник метрик указан на каждой карточке; live-вызовов API нет.</p>"
        "<div id='an-demo' class='muted'>Выберите проект.</div>"
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
        f"const PLATFORM_ICONS={json.dumps(platform_icons, ensure_ascii=False)};"
        "let AN_BAL=0;let AN_POSTS=[];"
        "function platIco(pt){return PLATFORM_ICONS[pt]?`<span class='an-plat-ico'>${PLATFORM_ICONS[pt]}</span>`:'';}"
        "function pid(){return parseInt(gv('an-project'))||0;}"
        "function renderSummary(s){const host=document.getElementById('an-summary');if(!host)return;"
        "if(!s){host.innerHTML='';return;}"
        "const cell=(k,v)=>`<div class='an-stat'><span class='k'>${esc(k)}</span><span class='v'>${esc(String(v))}</span></div>`;"
        "host.innerHTML=cell('Всего постов',s.total_posts)+cell('Опубликовано',s.published)+cell('Запланировано',s.scheduled)+cell('Failed',s.failed)"
        "+cell('Средний quality',s.avg_quality_score)+cell('Средний engagement',s.avg_engagement_score)+cell('Средний ER %',s.avg_er_percent);}"
        "function demoCard(c){return `<div class='sched-task'><h3>${platIco(c.platform)} ${esc(c.title)} `"
        "+`<span class='pill ${c.status==='published'?'ok':'off'}'>${esc(c.status)}</span> `"
        "+`<span class='pill off'>источник: ${esc(c.source)}</span></h3>`"
        "+`<div class='muted' style='margin:2px 0 6px'>${esc(c.text_preview||'')}</div>`"
        "+`<div class='sched-grid'>`"
        "+`<div><span class='k'>Площадка</span><span class='v'>${esc(c.platform)}</span></div>`"
        "+`<div><span class='k'>quality_score</span><span class='v'>${c.quality_score}</span></div>`"
        "+`<div><span class='k'>engagement_score</span><span class='v'>${c.engagement_score}</span></div>`"
        "+`<div><span class='k'>Просмотры (est)</span><span class='v'>${c.estimated_views}</span></div>`"
        "+`<div><span class='k'>Охват (est)</span><span class='v'>${c.estimated_reach}</span></div>`"
        "+`<div><span class='k'>Лайки (est)</span><span class='v'>${c.estimated_likes}</span></div>`"
        "+`<div><span class='k'>ER %</span><span class='v'>${c.er_percent}</span></div>`"
        "+`<div><span class='k'>CTR %</span><span class='v'>${c.ctr_percent}</span></div>`"
        "+`<div><span class='k'>media / хэштеги</span><span class='v'>${c.media_count} / ${c.hashtags_count}</span></div>`"
        "+`</div>`"
        "+(c.external_url?`<div class='muted'>Ссылка: <a href='${esc(c.external_url)}' target='_blank' rel='noopener'>${esc(c.external_url)}</a></div>`:'')"
        "+`<div class='acts'><button class='mini sec' onclick='anOpenCard(${c.post_id})'>Открыть анализ</button></div></div>`;}"
        "function renderDemo(cards){const host=document.getElementById('an-demo');if(!host)return;host.classList.remove('muted');"
        "host.innerHTML=cards.length?cards.map(demoCard).join(''):\"<div class='card muted'>Публикаций для демо-аналитики нет.</div>\";}"
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
        "try{const s=await api('GET','/analytics/projects/'+p+'/demo-summary?platform='+encodeURIComponent(plat));renderSummary(s);}catch(e){}"
        "try{const dm=await api('GET','/analytics/projects/'+p+'/demo?platform='+encodeURIComponent(plat));renderDemo(dm);}catch(e){}"
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
        # Активные сессии (v0.3.2).
        "<div class='card' id='sessions'><h3>🖥 Активные сессии</h3>"
        "<div id='sess-list' class='muted'>Загрузка…</div>"
        "<div style='margin-top:10px'><button class='mini sec' onclick='logoutAll()'>"
        "Выйти со всех устройств</button></div></div>"
        # Настройки уведомлений (v0.5.0).
        "<div class='card' id='notif-prefs'><h3>🔔 Уведомления</h3>"
        "<div id='np-info' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<label><input type='checkbox' id='np-inapp' checked disabled> В приложении (in-app)</label>"
        "<label><input type='checkbox' id='np-email' disabled> Email</label>"
        "<label><input type='checkbox' id='np-telegram' disabled> Telegram</label>"
        "<label><input type='checkbox' id='np-digest' disabled> Дайджест</label>"
        "<label><input type='checkbox' id='np-webhook' disabled> Webhook</label>"
        "</div>"
        "<p class='muted'>Внешняя доставка (email/Telegram/дайджест/webhook/push) выключена по "
        "умолчанию и в MVP не отправляется. "
        "<a href='/ui/notifications'>Уведомления →</a> · "
        "<a href='/ui/notification-delivery'>Доставка уведомлений →</a> · "
        "<a href='/ui/notification-digests'>Дайджесты →</a> · "
        "<a href='/ui/notification-safety'>Безопасность →</a> · "
        "<a href='/ui/notification-preferences'>Настройки уведомлений →</a></p></div>"
        # Email-уведомления (v0.5.3).
        "<div class='card' id='email-settings'><h3>✉️ Email-уведомления</h3>"
        "<ul class='muted'>"
        "<li>Email-доставка: <b>выключена</b> (SMTP live off, external delivery off).</li>"
        "<li>Дайджест-email: выключен по умолчанию.</li>"
        "<li>Отписка (unsubscribe footer): включена.</li>"
        "<li>SMTP: <b>не live</b>; SMTP-пароль хранится только в env и не показывается.</li>"
        "</ul>"
        "<p class='muted'>Preview email-шаблонов: <a href='/ui/email-templates'>Email-шаблоны →</a></p></div>"
        # Telegram-уведомления (v0.5.4).
        "<div class='card' id='telegram-settings'><h3>📨 Telegram-уведомления</h3>"
        "<ul class='muted'>"
        "<li>Telegram-доставка: <b>выключена</b> (live send off, external delivery off).</li>"
        "<li>Привязка чата: включена; chat_id хранится зашифрованно и маской.</li>"
        "<li>Тестовая отправка: выключена по умолчанию (только dry-run).</li>"
        "<li>Webhook/polling: sandbox; реальные Telegram API-вызовы выключены (dry-run).</li>"
        "<li>Bot token и webhook secret хранятся только в env и не показываются.</li>"
        "</ul>"
        "<p class='muted'>Подключение, webhook и preview: <a href='/ui/notification-telegram'>Telegram-уведомления →</a></p></div>"
        # Индикаторы безопасности.
        "<div class='card'><h3>🔒 Безопасность</h3><ul class='muted'>"
        "<li>Live-публикации выключены по умолчанию.</li>"
        "<li>Секреты показываются только маской (никогда полным значением).</li>"
        "<li>Платные действия требуют баланс.</li>"
        "<li>Preview / dry-run бесплатны.</li>"
        "<li>Вы видите только свои аккаунты и проекты (tenant-изоляция).</li>"
        "<li>Сессия защищена: access/refresh-токены, ротация, revoke, CSRF, rate limit.</li>"
        "<li>В production dev-токен запрещён; cookies Secure; авторизация обязательна.</li>"
        "</ul>"
        "<p class='muted'>Проверка боевой готовности: "
        "<a href='/health/security-readiness'>/health/security-readiness</a></p></div>"
        # Юридические документы (черновики).
        "<div class='card'><h3>📄 Документы</h3><p class='muted'>Черновики — перед "
        "публичным запуском требуется юридическая проверка:</p>"
        "<ul class='muted'>"
        "<li><a href='/ui/legal/terms'>Условия использования</a></li>"
        "<li><a href='/ui/legal/privacy'>Политика конфиденциальности</a></li>"
        "<li><a href='/ui/legal/offer'>Публичная оферта</a></li>"
        "<li><a href='/ui/legal/payments'>Оплата и возвраты</a></li>"
        "</ul></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{try{if(!tok()){document.getElementById('info').textContent='Вы не вошли.';return}"
        "const me=await api('GET','/auth/me');"
        "document.getElementById('info').innerHTML=`<b>${esc(me.user.full_name||me.user.email)}</b> · `"
        "+`${esc(me.user.email)} · аккаунтов: ${me.accounts.length}`;"
        "const sl=document.getElementById('sess-list');"
        "try{const ss=await api('GET','/auth/sessions');"
        "sl.innerHTML=ss.length?ss.map(s=>`<div style='margin:4px 0'>#${s.id} · ${esc(s.ip_address||'—')} · ${esc(s.user_agent||'—').slice(0,60)} · <span class='muted'>активна</span></div>`).join(''):'Активных сессий нет.';"
        "}catch(e){sl.textContent='—';}"
        "try{const pr=await api('GET','/notifications/preferences');"
        "document.getElementById('np-info').textContent='in-app: '+(pr.in_app_enabled?'вкл':'выкл')+' · внешняя доставка: '+(pr.external_delivery_enabled?'вкл':'выкл (по умолчанию)');"
        "document.getElementById('np-inapp').checked=!!pr.in_app_enabled;"
        "}catch(e){document.getElementById('np-info').textContent='—';}"
        "if(location.hash==='#sessions'){document.getElementById('sessions').scrollIntoView();}"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Настройки", body, script, active="settings")


# --------------------------------------------------------------------------- #
# Юридические страницы (черновики — не финальные, не юридическая консультация) #
# --------------------------------------------------------------------------- #

_LEGAL_DOCS: dict[str, dict[str, str]] = {
    "terms": {
        "title": "Условия использования",
        "en": "Terms of Service",
        "intro": "Условия использования сервиса Botfleet.",
    },
    "privacy": {
        "title": "Политика конфиденциальности",
        "en": "Privacy Policy",
        "intro": "Политика обработки персональных данных.",
    },
    "offer": {
        "title": "Публичная оферта",
        "en": "Public Offer",
        "intro": "Публичная оферта об оказании услуг.",
    },
    "payments": {
        "title": "Оплата и возвраты",
        "en": "Payment Policy",
        "intro": "Условия оплаты, тарификации и возвратов.",
    },
}


def _legal_body(doc: dict[str, str]) -> str:
    return (
        "<div class='callout warn'><b>Черновик</b>"
        "<p>Перед публичным запуском требуется юридическая проверка. Тексты не являются "
        "юридической консультацией.</p></div>"
        f"<div class='card'><h2>{html.escape(doc['title'])} "
        f"<span class='muted'>({html.escape(doc['en'])})</span></h2>"
        f"<p class='muted'>{html.escape(doc['intro'])}</p>"
        "<p class='muted'>Черновик документа. Финальная редакция будет опубликована перед "
        "запуском. Разделы: предмет, права и обязанности, ограничение ответственности, "
        "персональные данные, платежи и возвраты, применимое право.</p></div>"
        "<div class='inline'>"
        "<a href='/ui/legal/terms'><button class='mini ghost'>Условия</button></a>"
        "<a href='/ui/legal/privacy'><button class='mini ghost'>Конфиденциальность</button></a>"
        "<a href='/ui/legal/offer'><button class='mini ghost'>Оферта</button></a>"
        "<a href='/ui/legal/payments'><button class='mini ghost'>Оплата</button></a></div>"
    )


@router.get("/legal/{doc}", response_class=HTMLResponse)
def ui_legal(doc: str) -> HTMLResponse:
    """Юридическая страница-черновик (terms/privacy/offer/payments)."""
    meta = _LEGAL_DOCS.get(_safe_slug(doc))
    if meta is None:
        meta = {
            "title": "Документ",
            "en": "Document",
            "intro": "Документ не найден.",
        }
    return _page(f"{meta['title']} · черновик", _legal_body(meta), "", sidebar=False)


@router.get("/billing", response_class=HTMLResponse)
def ui_billing() -> HTMLResponse:
    settings = get_settings()
    pay_live = bool(settings.payments_live_enabled)
    default_provider = html.escape(settings.payments_default_provider or "mock")
    provider_mode = "live" if pay_live else "mock/sandbox"
    banner = (
        ""
        if pay_live
        else (
            "<div class='callout warn'><b>Боевые платежи выключены</b> "
            "<span class='pill off'>PAYMENTS_LIVE_ENABLED=false</span>"
            "<p>Сейчас создаётся mock/sandbox invoice. Баланс пополняется только после "
            "оплаты (mock-pay). Реальные деньги не списываются.</p></div>"
        )
    )
    body = (
        # Верхние карточки: баланс, тариф, режим платежей, провайдер.
        "<div class='grid'>"
        "<div class='card'><h3>Баланс</h3><div id='bal' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='sec mini' onclick='refresh()'>Обновить</button></div></div>"
        "<div class='card'><h3>Тариф</h3><div id='tariff' class='muted'>—</div></div>"
        "<div class='card'><h3>Боевые платежи</h3>"
        f"<div class='muted'><span class='pill {'ok' if pay_live else 'off'}'>"
        f"PAYMENTS_LIVE_ENABLED={'true' if pay_live else 'false'}</span></div></div>"
        "<div class='card'><h3>Провайдер</h3>"
        f"<div class='muted'>по умолчанию <b>{default_provider}</b> · режим {provider_mode}</div>"
        "</div></div>"
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
        "<div><label>Метод</label><select id='method' onchange='invPreview()'>"
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
        "<div id='inv-result' class='muted' style='margin-top:8px'></div>"
        # Предупреждение о карте (карта вводится только у провайдера).
        "<div class='callout warn' style='margin-top:10px'>"
        "<b>Не вводите банковскую карту в Botfleet</b>"
        "<p>Данные карты вводятся только на стороне платёжного провайдера "
        "(YooKassa/банк). Botfleet не хранит и не запрашивает номер карты/CVV. "
        "Mock-pay доступен только в local/sandbox.</p></div></div>"
        # Реквизиты плательщика
        "<h2>Реквизиты плательщика</h2>"
        "<div class='card'>"
        "<div id='profile-readiness' class='inline' style='margin-bottom:8px'></div>"
        "<label>Тип клиента</label><select id='customer_type' onchange='loadReadiness()'>"
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
        "<div id='profile-msg' class='muted' style='margin-top:6px'></div>"
        "<p class='muted' style='margin-top:6px'>Для карты/СБП/QR нужен email (чек). "
        "Для счёта ИП/ООО — ИНН, наименование и email. Заполните реквизиты, иначе оплата "
        "недоступна.</p></div>"
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
        "<li>Дубликат вебхука (provider_event_id) игнорируется — двойного пополнения нет.</li>"
        "<li>Ручное пополнение (manual topup) — только через admin/CLI.</li>"
        "<li>Секреты провайдеров не показываются (только маска).</li>"
        "</ul></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PAY_LIVE={json.dumps(pay_live)};"
        "const eEl=document.getElementById('error');const B=document.getElementById('bal');"
        "function setAmt(v){const a=document.getElementById('amount');if(a){a.value=v;invPreview();}}"
        "function copyText(t){try{navigator.clipboard.writeText(t);}catch(e){}}"
        "window.copyText=copyText;"
        "async function refresh(){const a=needAccount(eEl);if(!a)return;try{"
        "const b=await api('GET','/billing/account/'+a+'/balance');"
        "B.innerHTML=`Аккаунт #${b.account_id}: <b>${b.balance_units}</b> ${esc(b.currency)}`;"
        "const t=document.getElementById('tariff');if(t)t.innerHTML=`${esc(b.tariff_plan_slug||'—')} · ${esc(b.status)}`;"
        "}catch(x){err(eEl,x)}}"
        "async function loadReadiness(){const a=parseInt(acc());if(!a)return;"
        "try{const r=await api('GET','/billing/account/'+a+'/profile/readiness');"
        "const map={bank_card:'Карта',sbp:'СБП',qr:'QR',invoice_for_ip:'Счёт ИП',invoice_for_company:'Счёт ООО'};"
        "const el=document.getElementById('profile-readiness');if(!el)return;"
        "el.innerHTML=Object.keys(map).map(k=>`<span class='pill ${r.ready[k]?'ok':'off'}' title='${esc((r.missing[k]||[]).join('; '))}'>${map[k]}: ${r.ready[k]?'готово':'нужны реквизиты'}</span>`).join(' ');"
        "}catch(e){}}"
        "async function invPreview(){const a=parseInt(acc());if(!a)return;const amt=parseInt(gv('amount'))||0;"
        "if(amt<=0)return;try{const r=await api('POST','/billing/account/'+a+'/topup/preview',{amount_units:amt,method:gv('method'),provider:gv('provider')||null});"
        "const el=document.getElementById('inv-preview');if(el)el.textContent=amt+' units ≈ '+r.amount_rub+' ₽ · провайдер '+r.provider+(r.payments_live_enabled?'':' (mock/sandbox)');}catch(e){}}"
        "async function createInvoice(){const a=needAccount(eEl);if(!a)return;const amt=parseInt(gv('amount'));"
        "if(!amt||amt<=0){err(eEl,new Error('Укажите сумму > 0.'));return}eEl.style.display='none';"
        "const customer={customer_type:gv('customer_type'),inn:gv('inn')||null,kpp:gv('kpp')||null,ogrn:gv('ogrn')||null,legal_name:gv('legal_name')||null,email:gv('email')||null,phone:gv('phone')||null};"
        "try{const inv=await api('POST','/billing/account/'+a+'/invoices',{amount_units:amt,method:gv('method'),provider:gv('provider')||null,customer:customer});"
        "const R=document.getElementById('inv-result');"
        "let qr='';if(inv.qr_payload){qr=`<div class='card' style='margin-top:8px'><b>QR / СБП</b>`"
        "+`<div class='muted' style='margin:4px 0'>QR-код сформирует платёжный провайдер после подключения sandbox/live. Пока — payload для проверки:</div>`"
        "+`<code style='word-break:break-all'>${esc(inv.qr_payload)}</code>`"
        "+`<div style='margin-top:6px'><button class='mini sec' onclick='copyText(${JSON.stringify(inv.qr_payload)})'>Скопировать payload</button></div></div>`;}"
        "R.innerHTML=`<span class='pill off'>${esc(inv.status)}</span> Счёт #${inv.id} на ${inv.amount_units} units (${inv.amount_rub} ₽) · ${esc(inv.provider)}/${esc(inv.method)}`+qr;"
        "loadHistory();}catch(x){err(eEl,x)}}"
        "async function mockAction(id,act){eEl.style.display='none';"
        "try{const inv=await api('POST','/billing/invoices/'+id+'/'+act,{});"
        "refresh();initShell();loadHistory();}catch(x){err(eEl,x)}}"
        "window.mockAction=mockAction;"
        "async function saveProfile(){const a=needAccount(eEl);if(!a)return;const msg=document.getElementById('profile-msg');"
        "try{await api('PUT','/billing/account/'+a+'/profile',{customer_type:gv('customer_type'),inn:gv('inn')||null,kpp:gv('kpp')||null,ogrn:gv('ogrn')||null,legal_name:gv('legal_name')||null,email:gv('email')||null,phone:gv('phone')||null});"
        "if(msg)msg.innerHTML=\"<span class='pill ok'>сохранено</span>\";loadReadiness();}catch(x){if(msg)msg.textContent=String(x.message||x);}}"
        "function invRow(i){const acts=(i.status==='pending'&&i.provider==='mock')?"
        "`<button class='mini' onclick='mockAction(${i.id},\"mock-pay\")'>Оплатить</button> `"
        "+`<button class='mini sec' onclick='mockAction(${i.id},\"mock-fail\")'>Fail</button> `"
        "+`<button class='mini sec' onclick='mockAction(${i.id},\"mock-cancel\")'>Отмена</button>`:'';"
        "return `<tr><td>#${i.id}</td><td>${esc(i.provider)}</td><td>${esc(i.method)}</td>"
        "<td><span class='pill ${i.status==='paid'?'ok':'off'}'>${esc(i.status)}</span></td>"
        "<td>${i.amount_units} u (${i.amount_rub} ₽)</td><td>${acts}</td></tr>`;}"
        "async function loadHistory(){const a=parseInt(acc());if(!a)return;"
        "try{const inv=await api('GET','/billing/account/'+a+'/invoices');"
        "document.getElementById('invoices').innerHTML=inv.length?"
        "`<table class='price-table'><thead><tr><th>ID</th><th>Провайдер</th><th>Метод</th><th>Статус</th><th>Сумма</th><th>Действия</th></tr></thead><tbody>`+inv.map(invRow).join('')+`</tbody></table>`:'—';}catch(e){}"
        "try{const l=await api('GET','/billing/account/'+a+'/ledger');"
        "document.getElementById('ledger').innerHTML=l.length?l.map(e=>`<div>${esc(e.entry_type)} ${e.amount_units>0?'+':''}${e.amount_units} → ${e.balance_after_units} · ${esc(e.description)}</div>`).join(''):'—';}catch(e){}"
        "try{const us=await api('GET','/billing/account/'+a+'/usage-events');"
        "document.getElementById('usage').innerHTML=us.length?us.map(u=>`<div>${esc(u.event_type)} · ${u.units} units</div>`).join(''):'—';}catch(e){}}"
        "(async()=>{try{const prov=await api('GET','/billing/providers');const sel=document.getElementById('provider');"
        "if(sel)sel.innerHTML=prov.map(p=>`<option value='${p.provider}'${p.usable?'':' disabled'}>${p.provider} (${p.mode})${p.usable?'':' — недоступен'}</option>`).join('');}catch(e){}"
        "refresh();invPreview();loadHistory();loadReadiness();"
        "const a=parseInt(acc());if(a){try{const pr=await api('GET','/billing/account/'+a+'/profile');if(pr){"
        "['customer_type','inn','kpp','ogrn','legal_name','email','phone'].forEach(k=>{const el=document.getElementById(k);if(el&&pr[k]!=null)el.value=pr[k];});loadReadiness();}}catch(e){}}"
        "})();"
    )
    return _page("Биллинг", body, script, active="settings")


# --------------------------------------------------------------------------- #
# v0.4.0: Ревью / Обучение / Автоматизация                                     #
# --------------------------------------------------------------------------- #


@router.get("/review", response_class=HTMLResponse)
def ui_review_index() -> HTMLResponse:
    """Лендинг ревью: выбрать проект и открыть его очередь постов."""
    body = (
        "<h2>Очередь на ревью</h2>"
        "<div class='callout warn'><b>Полуавтоматический режим.</b>"
        "<p>Бот по расписанию создаёт черновики (draft/needs_review). Вы открываете пост, "
        "редактируете текст и медиа, одобряете, отклоняете или запрашиваете правки и "
        "нажимаете «Опубликовать». Бот запоминает ваши решения и учится. "
        "<b>Живая публикация выключена</b> — реальная отправка возможна только при включённых "
        "safety gates.</p></div>"
        "<div class='card'><h3>Проекты</h3>"
        "<div id='rv-projects' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{const a=needAccount(eEl);if(!a)return;try{"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "const host=document.getElementById('rv-projects');host.classList.remove('muted');"
        "host.innerHTML=ps.length?ps.map(p=>`<div class='sched-task'><b>${esc(p.name)}</b> "
        "<a href='/ui/projects/${p.id}/review'><button class='mini'>Открыть очередь</button></a> "
        "<a href='/ui/projects/${p.id}/learning'><button class='mini sec'>Чему научился</button></a> "
        "<a href='/ui/projects/${p.id}/automation'><button class='mini ghost'>Автоматизация</button></a>"
        "</div>`).join(''):\"<div class='muted'>Нет проектов.</div>\";"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Ревью", body, script, active="review")


@router.get("/projects/{project_id}/review", response_class=HTMLResponse)
def ui_project_review(project_id: int) -> HTMLResponse:
    """Очередь ревью проекта: карточки постов со скорингом и кнопками решений."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/learning'><button class='ghost mini'>Чему бот научился</button></a>"
        f"<a href='/ui/projects/{project_id}/metrics'><button class='ghost mini'>Метрики</button></a>"
        f"<a href='/ui/projects/{project_id}/automation'><button class='ghost mini'>Автоматизация</button></a></div>"
        "<h2>Очередь постов на ревью</h2>"
        "<p class='muted'>Метрики опубликованных постов и их влияние на обучение — на "
        f"<a href='/ui/projects/{project_id}/metrics'>странице «Метрики и обучение»</a> "
        "(ER, CTR, источник).</p>"
        "<div class='callout warn'><b>Живая публикация выключена.</b> Кнопка «Опубликовать» "
        "отправит пост только при включённых safety gates (подключение платформы, live-флаг, "
        "баланс). Иначе — покажем причину и ничего не спишем.</div>"
        # Легенда действий (строки нужны и как справка, и как якорь для тестов).
        "<div class='card'><b>Действия по посту:</b> "
        "<span class='badge'>Открыть</span> <span class='badge'>Одобрить</span> "
        "<span class='badge'>Запросить правки</span> <span class='badge'>Отклонить</span> "
        "<span class='badge'>Опубликовать</span></div>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>Статус</label><select id='rv-status'>"
        "<option value=''>В очереди</option><option value='needs_review'>needs_review</option>"
        "<option value='changes_requested'>changes_requested</option>"
        "<option value='draft'>draft</option><option value='approved'>approved</option></select></div>"
        "<div><label>Платформа</label><select id='rv-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "</div></div>"
        "<div id='rv-list' class='muted'>Загрузка…</div>"
        "<div id='rv-msg' class='muted'></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('rv-msg');"
        "function scorePill(v){const ok=v>=70;const off=v<40;return `<span class='pill ${ok?'ok':(off?'off':'')}'>${v}</span>`;}"
        "function card(it){"
        "const reasons=(it.learning_reasons||[]).slice(0,3).map(esc).join(' · ');"
        "const warns=(it.warnings||[]).slice(0,3).map(esc).join(' · ');"
        "const exp=it.experiment?`<span class='badge'>A/B ${esc(it.experiment.variant_key)} · ${esc(it.experiment.title||'эксперимент')}</span>`:'';"
        "return `<div class='card' data-pid='${it.post_id}'>"
        "<div class='inline'><b>#${it.post_id}</b> <span class='pill'>${esc(it.status)}</span> "
        "<span class='muted'>${esc(it.platform||'—')}</span> <b>${esc(it.title||'')}</b> ${exp}</div>"
        "<div class='muted'>${esc(it.text_preview||'')}</div>"
        "<div class='kv'><div>Качество</div><div>${scorePill(it.quality_score)}</div>"
        "<div>Прогноз вовлечения</div><div>${it.predicted_engagement_score}</div>"
        "<div>Соответствие профилю</div><div>${it.fit_score}</div>"
        "<div>Медиа</div><div>${it.media_count}</div></div>"
        "${reasons?`<div class='muted'>Обучение: ${reasons}</div>`:''}"
        "${warns?`<div class='muted'>⚠ ${warns}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini' onclick='rvApprove(${it.post_id})'>Одобрить</button>"
        "<button class='mini sec' onclick='rvChanges(${it.post_id})'>Запросить правки</button>"
        "<button class='mini sec' onclick='rvReject(${it.post_id})'>Отклонить</button>"
        "<button class='mini ghost' onclick='rvPublish(${it.post_id})'>Опубликовать</button>"
        "</div></div>`;}"
        "async function loadQueue(){const host=document.getElementById('rv-list');"
        "const st=gv('rv-status');const pf=gv('rv-platform');"
        "let url='/review/projects/'+PID+'/queue?';if(st)url+='review_status='+encodeURIComponent(st)+'&';"
        "if(pf)url+='platform='+encodeURIComponent(pf);"
        "try{const q=await api('GET',url);host.classList.remove('muted');"
        "host.innerHTML=q.count?q.items.map(card).join(''):\"<div class='card muted'>Очередь пуста — новых постов на ревью нет.</div>\";"
        "}catch(x){err(eEl,x)}}"
        "async function rvApprove(id){try{await api('POST','/review/posts/'+id+'/approve',{});msg.textContent='Пост #'+id+' одобрен.';loadQueue();}catch(x){err(eEl,x)}}"
        "async function rvReject(id){try{await api('POST','/review/posts/'+id+'/reject',{reason_tags:['не та тема']});msg.textContent='Пост #'+id+' отклонён.';loadQueue();}catch(x){err(eEl,x)}}"
        "async function rvChanges(id){try{await api('POST','/review/posts/'+id+'/request-changes',{reason_tags:['нужны правки']});msg.textContent='По посту #'+id+' запрошены правки.';loadQueue();}catch(x){err(eEl,x)}}"
        "async function rvPublish(id){try{const r=await api('POST','/review/posts/'+id+'/publish-now',{confirm:true});"
        "if(r.blocked){msg.textContent='Публикация заблокирована: '+esc(r.reason)+' (ничего не списано).';}"
        "else{msg.textContent='Пост #'+id+' опубликован.';}loadQueue();}catch(x){err(eEl,x)}}"
        "window.rvApprove=rvApprove;window.rvReject=rvReject;window.rvChanges=rvChanges;window.rvPublish=rvPublish;"
        "['rv-status','rv-platform'].forEach(id=>{const e=document.getElementById(id);if(e)e.addEventListener('change',loadQueue);});"
        "loadQueue();"
    )
    return _page("Ревью проекта", body, script, active="review", active_pid=project_id)


@router.get("/learning", response_class=HTMLResponse)
def ui_learning_index() -> HTMLResponse:
    """Лендинг обучения: выбрать проект и открыть блок «Чему бот научился»."""
    body = (
        "<h2>Чему бот научился</h2>"
        "<p class='muted'>Бот строит персональный профиль по вашим одобрениям, правкам, "
        "отклонениям и метрикам постов. Данные одного клиента не смешиваются с другими.</p>"
        "<div class='card'><h3>Проекты</h3><div id='ln-projects' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{const a=needAccount(eEl);if(!a)return;try{"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "const host=document.getElementById('ln-projects');host.classList.remove('muted');"
        "host.innerHTML=ps.length?ps.map(p=>`<div class='sched-task'><b>${esc(p.name)}</b> "
        "<a href='/ui/projects/${p.id}/learning'><button class='mini'>Открыть профиль</button></a></div>`).join('')"
        ":\"<div class='muted'>Нет проектов.</div>\";}catch(x){err(eEl,x)}})();"
    )
    return _page("Обучение", body, script, active="learning")


@router.get("/projects/{project_id}/learning", response_class=HTMLResponse)
def ui_project_learning(project_id: int) -> HTMLResponse:
    """Блок «Чему бот научился»: темы, CTA, теги, время, уверенность, рекомендации."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/review'><button class='ghost mini'>Очередь ревью</button></a>"
        f"<a href='/ui/projects/{project_id}/metrics'><button class='ghost mini'>Метрики</button></a>"
        f"<a href='/ui/projects/{project_id}/learning/metrics'><button class='ghost mini'>Влияние метрик</button></a></div>"
        "<h2>Чему бот научился</h2>"
        "<div class='card'><div class='kv'>"
        "<div>Уверенность профиля</div><div id='ln-confidence'>—</div>"
        "<div>Версия профиля</div><div id='ln-version'>—</div>"
        "<div>Обработано сигналов</div><div id='ln-events'>—</div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='lnRebuild()'>Пересчитать профиль</button></div></div>"
        "<div class='grid'>"
        "<div class='card'><h3>Предпочитаемые темы</h3><div id='ln-preferred-topics' class='muted'>—</div></div>"
        "<div class='card'><h3>Отклонённые темы</h3><div id='ln-rejected-topics' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучший призыв к действию (CTA)</h3><div id='ln-cta' class='muted'>—</div></div>"
        "<div class='card'><h3>Длина текста</h3><div id='ln-length' class='muted'>—</div></div>"
        "<div class='card'><h3>Сильные теги</h3><div id='ln-high-tags' class='muted'>—</div></div>"
        "<div class='card'><h3>Слабые теги</h3><div id='ln-low-tags' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучшее медиа</h3><div id='ln-media' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучшее время публикаций</h3><div id='ln-times' class='muted'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Что бот будет делать</h3><div id='ln-recs' class='muted'>—</div></div>"
        "<div class='card'><h3>Последние решения</h3><div id='ln-events-list' class='muted'>—</div></div>"
        "<div id='ln-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('ln-msg');"
        "function fill(id,arr,pre){const el=document.getElementById(id);"
        "el.classList.remove('muted');el.innerHTML=(arr&&arr.length)?arr.map(v=>`<span class='badge'>${(pre||'')+esc(''+v)}</span>`).join(' '):\"<span class='muted'>пока нет данных</span>\";}"
        "async function load(){try{const s=await api('GET','/learning/projects/'+PID+'/summary');"
        "document.getElementById('ln-confidence').textContent=Math.round((s.confidence_score||0)*100)+'%';"
        "document.getElementById('ln-version').textContent=s.profile_version||0;"
        "document.getElementById('ln-events').textContent=s.updated_from_events_count||0;"
        "fill('ln-preferred-topics',s.preferred_topics);fill('ln-rejected-topics',s.rejected_topics);"
        "fill('ln-cta',s.preferred_cta);fill('ln-high-tags',s.high_performing_tags,'#');"
        "fill('ln-low-tags',s.low_performing_tags,'#');fill('ln-media',s.preferred_media_types);"
        "fill('ln-times',s.best_publish_times);"
        "const tl=s.preferred_text_length||{};document.getElementById('ln-length').innerHTML=tl.target?`около ${tl.target} символов`:\"<span class='muted'>пока нет данных</span>\";"
        "const recs=s.recommendations||[];document.getElementById('ln-recs').innerHTML=recs.length?recs.map(r=>`<div>• ${esc(r)}</div>`).join(''):\"<span class='muted'>Недостаточно данных — соберём после первых решений.</span>\";"
        "const ev=s.recent_events||[];document.getElementById('ln-events-list').innerHTML=ev.length?ev.map(e=>`<div class='muted'>#${e.post_id} · ${esc(e.event_type)}${e.rating?(' · '+e.rating+'★'):''}</div>`).join(''):\"<span class='muted'>Событий пока нет.</span>\";"
        "}catch(x){err(eEl,x)}}"
        "async function lnRebuild(){try{const a=acc();let url='/learning/projects/'+PID+'/rebuild';if(a)url+='?account_id='+a;"
        "const r=await api('POST',url,{});msg.textContent='Профиль пересчитан (версия '+r.profile_version+').';load();}catch(x){err(eEl,x)}}"
        "window.lnRebuild=lnRebuild;load();"
    )
    return _page("Обучение проекта", body, script, active="learning", active_pid=project_id)


@router.get("/projects/{project_id}/automation", response_class=HTMLResponse)
def ui_project_automation(project_id: int) -> HTMLResponse:
    """Настройки режима автоматизации проекта: semi_auto / full_auto + safety gates."""
    _s = get_settings()

    def _yn(value: bool) -> str:
        return "вкл" if value else "выкл"

    auto_topic_block = (
        "<div class='card'><h3>Автовыбор тем (v0.4.4)</h3>"
        "<p class='muted'>Worker сам выбирает тему/CTA/формат/медиа для слота по обучению, "
        "метрикам, A/B winners и предложениям. Создаётся только draft/needs_review — "
        "<b>live-публикаций нет</b>; при низкой уверенности пост уходит в ревью.</p>"
        "<ul>"
        f"<li>AUTO_TOPIC_SELECTION_ENABLED: <b>{_yn(_s.auto_topic_selection_enabled)}</b></li>"
        f"<li>AUTO_TOPIC_SELECTION_WORKER_ENABLED: <b>{_yn(_s.auto_topic_selection_worker_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>AUTO_TOPIC_SELECTION_DRY_RUN: <b>{_yn(_s.auto_topic_selection_dry_run)}</b></li>"
        f"<li>min confidence: <b>{_s.auto_topic_selection_min_confidence_safe}</b></li>"
        "</ul>"
        f"<a href='/ui/projects/{project_id}/topic-decisions'>"
        "<button class='mini'>Открыть «Выбор тем по обучению»</button></a></div>"
    )
    auto_media_block = (
        "<div class='card'><h3>Автовыбор медиа (v0.4.5)</h3>"
        "<p class='muted'>Worker сам выбирает media strategy (text_only/single_image/media_group/"
        "carousel_ready/…) и конкретные медиа для слота по теме, тегам, платформе, обучению, "
        "A/B winners, метрикам и доступности. Создаётся только draft/needs_review — "
        "<b>live-публикаций нет</b>; <b>публичные ссылки автоматически не создаются</b>; "
        "при низкой уверенности пост уходит в ревью. <b>Instagram требует public image_url.</b></p>"
        "<ul>"
        f"<li>AUTO_MEDIA_SELECTION_ENABLED: <b>{_yn(_s.auto_media_selection_enabled)}</b></li>"
        f"<li>AUTO_MEDIA_SELECTION_WORKER_ENABLED: <b>{_yn(_s.auto_media_selection_worker_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>AUTO_MEDIA_SELECTION_DRY_RUN: <b>{_yn(_s.auto_media_selection_dry_run)}</b></li>"
        f"<li>min confidence: <b>{_s.auto_media_selection_min_confidence_safe}</b></li>"
        f"<li>AUTO_MEDIA_SELECTION_CREATE_PUBLIC_LINKS: <b>{_yn(_s.auto_media_selection_create_public_links)}</b> "
        "(по умолчанию выкл)</li>"
        "</ul>"
        f"<a href='/ui/projects/{project_id}/media-decisions'>"
        "<button class='mini'>Открыть «Выбор медиа по обучению»</button></a></div>"
    )
    media_quality_block = (
        "<div class='card'><h3>Оценка качества медиа (v0.4.6)</h3>"
        "<p class='muted'>Botfleet оценивает качество/релевантность/свежесть/уникальность/"
        "пригодность медиа и выявляет повторы и дубли — <b>правило-ориентированно, без внешнего "
        "AI</b> и <b>без live-публикаций</b>. Сильные медиа поднимаются в автовыборе, слабые "
        "уходят в предупреждение.</p>"
        "<ul>"
        f"<li>MEDIA_QUALITY_SCORING_ENABLED: <b>{_yn(_s.media_quality_scoring_enabled)}</b></li>"
        f"<li>MEDIA_QUALITY_SCORING_WORKER_ENABLED: <b>{_yn(_s.media_quality_scoring_worker_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_QUALITY_SCORING_DRY_RUN: <b>{_yn(_s.media_quality_scoring_dry_run)}</b></li>"
        f"<li>MEDIA_QUALITY_EXTERNAL_AI_ENABLED: <b>{_yn(_s.media_quality_external_ai_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>порог good: <b>{_s.media_quality_min_good_score_safe}</b> · "
        f"excellent: <b>{_s.media_quality_min_excellent_score_safe}</b></li>"
        "</ul>"
        f"<a href='/ui/projects/{project_id}/media-quality'>"
        "<button class='mini'>Открыть «Качество медиа»</button></a></div>"
    )
    media_fingerprint_block = (
        "<div class='card'><h3>Fingerprint и дубли медиа (v0.4.7)</h3>"
        "<p class='muted'>Botfleet считает локальные fingerprint медиа (sha256 + perceptual "
        "hash + сигнатуры) и группирует визуально похожие/дублирующиеся медиа в кластеры — "
        "<b>без внешнего AI/vision</b>, <b>без сети по умолчанию</b> и <b>без удаления файлов</b>. "
        "Автовыбор медиа избегает почти-одинаковых фото в подборке.</p>"
        "<ul>"
        f"<li>MEDIA_FINGERPRINTING_ENABLED: <b>{_yn(_s.media_fingerprinting_enabled)}</b></li>"
        f"<li>MEDIA_FINGERPRINTING_WORKER_ENABLED: <b>{_yn(_s.media_fingerprinting_worker_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_FINGERPRINTING_DRY_RUN: <b>{_yn(_s.media_fingerprinting_dry_run)}</b></li>"
        f"<li>MEDIA_FINGERPRINTING_EXTERNAL_AI_ENABLED: <b>{_yn(_s.media_fingerprinting_external_ai_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_DUPLICATE_AUTO_DELETE_ENABLED: <b>{_yn(_s.media_duplicate_auto_delete_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        "</ul>"
        f"<a href='/ui/projects/{project_id}/media-fingerprints'>"
        "<button class='mini'>Открыть «Fingerprint медиа»</button></a> "
        f"<a href='/ui/projects/{project_id}/media-duplicates'>"
        "<button class='mini sec'>Открыть «Дубли»</button></a></div>"
    )
    media_curation_block = (
        "<div class='card'><h3>Media curation worker (v0.4.8)</h3>"
        "<p class='muted'>Botfleet предлагает задачи очистки/разметки медиатеки (проверить дубли, "
        "подтвердить теги, скрыть дубль, заменить слабое медиа). Теги применяются <b>только после "
        "подтверждения</b>; <b>файлы не удаляются</b>; <b>без внешнего AI</b>; live-публикаций нет. "
        "Скрытые медиа исключаются из авто-подбора.</p>"
        "<ul>"
        f"<li>MEDIA_CURATION_ENABLED: <b>{_yn(_s.media_curation_enabled)}</b></li>"
        f"<li>MEDIA_CURATION_WORKER_ENABLED: <b>{_yn(_s.media_curation_worker_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_CURATION_DRY_RUN: <b>{_yn(_s.media_curation_dry_run)}</b></li>"
        f"<li>MEDIA_CURATION_AUTO_APPLY_TAGS: <b>{_yn(_s.media_curation_auto_apply_tags)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_CURATION_AUTO_HIDE_DUPLICATES: <b>{_yn(_s.media_curation_auto_hide_duplicates)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_CURATION_AUTO_DELETE_ENABLED: <b>{_yn(_s.media_curation_auto_delete_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        "</ul>"
        f"<a href='/ui/projects/{project_id}/media-curation'>"
        "<button class='mini'>Открыть «Очистка и разметка медиатеки»</button></a></div>"
    )
    media_curation_review_block = (
        "<div class='card'><h3>Media curation review (v0.4.9)</h3>"
        "<p class='muted'>Медиатека курируется через workflow согласования: задачи на проверку, "
        "ответственные, комментарии, история решений. Изменения (теги/видимость) применяются "
        "<b>только после одобрения (approved)</b>; авто-применение и уведомления выключены; "
        "<b>файлы не удаляются</b>; <b>без внешнего AI</b>; live-публикаций/платежей нет.</p>"
        "<ul>"
        f"<li>MEDIA_CURATION_REVIEW_ENABLED: <b>{_yn(_s.media_curation_review_enabled)}</b></li>"
        f"<li>MEDIA_CURATION_REVIEW_REQUIRE_APPROVAL: <b>{_yn(_s.media_curation_review_require_approval)}</b> "
        "(по умолчанию вкл)</li>"
        f"<li>MEDIA_CURATION_REVIEW_AUTO_APPLY_AFTER_APPROVAL: <b>{_yn(_s.media_curation_review_auto_apply_after_approval)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_CURATION_REVIEW_NOTIFY_ENABLED: <b>{_yn(_s.media_curation_review_notify_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        f"<li>MEDIA_CURATION_REVIEW_EXTERNAL_AI_ENABLED: <b>{_yn(_s.media_curation_review_external_ai_enabled)}</b> "
        "(по умолчанию выкл)</li>"
        "</ul>"
        f"<a href='/ui/projects/{project_id}/media-curation-review'>"
        "<button class='mini'>Открыть «Ревью медиатеки»</button></a></div>"
    )
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/review'><button class='ghost mini'>Очередь ревью</button></a></div>"
        "<h2>Режим автоматизации</h2>"
        "<div class='callout warn'><b>Автоматический режим публикует live только если включены "
        "все safety gates.</b> Иначе бот создаёт draft/needs_review и пишет понятную причину.</div>"
        "<div class='grid'>"
        "<div class='card'><h3>Полуавтоматический</h3>"
        "<p class='muted'>Бот создаёт черновики по расписанию. Вы одобряете и публикуете вручную.</p>"
        "<button class='mini' onclick='setMode(\"semi_auto\")'>Включить semi_auto</button></div>"
        "<div class='card'><h3>Полностью автоматический</h3>"
        "<p class='muted'>Бот сам публикует, если все safety gates включены и качество выше порога.</p>"
        "<div><label>Подтверждение</label> "
        "<input id='fa-confirm' placeholder='ENABLE_FULL_AUTO' style='width:220px'></div>"
        "<p class='muted'>Чтобы включить, введите <b>ENABLE_FULL_AUTO</b>.</p>"
        "<button class='mini' onclick='setMode(\"full_auto\")'>Включить full_auto</button></div>"
        "</div>"
        "<div class='card'><h3>Требования (safety gates)</h3>"
        "<ul id='ag-checklist'>"
        "<li>Баланс units достаточен</li>"
        "<li>Платформа подключена</li>"
        "<li>Живая публикация включена (live-флаг)</li>"
        "<li>Качество контента выше порога</li>"
        "<li>Профиль обучения готов</li>"
        "<li>Медиа доступно</li>"
        "</ul></div>"
        f"{auto_topic_block}"
        f"{auto_media_block}"
        f"{media_quality_block}"
        f"{media_fingerprint_block}"
        f"{media_curation_block}"
        f"{media_curation_review_block}"
        "<div class='card'><h3>Текущие планы</h3><div id='ag-plans' class='muted'>Загрузка…</div></div>"
        "<div id='ag-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('ag-msg');"
        "async function load(){try{const s=await api('GET','/automation/projects/'+PID+'/settings');"
        "const host=document.getElementById('ag-plans');host.classList.remove('muted');"
        "host.innerHTML=s.plans_count?(`<div class='muted'>Режим проекта: <b>${esc(s.effective_mode)}</b> · "
        "профиль: ${s.learning_profile_ready?('готов, '+Math.round((s.learning_confidence||0)*100)+'%'):'ещё не готов'}</div>`+"
        "s.plans.map(p=>`<div class='sched-task'>План #${p.plan_id} · ${esc((p.platforms||[]).join(', '))} · "
        "<span class='pill ${p.automation_mode===\"full_auto\"?'ok':''}'>${esc(p.automation_mode)}</span> "
        "· порог ${p.min_quality_score_for_auto} · авто-публикация: ${p.auto_publish_enabled?'да':'нет'}</div>`).join(''))"
        ":\"<div class='muted'>Планов расписания ещё нет — создайте расписание на странице платформы.</div>\";"
        "}catch(x){err(eEl,x)}}"
        "async function setMode(mode){try{const body={automation_mode:mode};"
        "if(mode==='full_auto'){body.auto_publish_enabled=true;body.confirm=gv('fa-confirm');}"
        "await api('POST','/automation/projects/'+PID+'/settings',body);"
        "msg.textContent='Режим обновлён: '+mode;load();}catch(x){err(eEl,x)}}"
        "window.setMode=setMode;load();"
    )
    return _page("Автоматизация проекта", body, script, active="scheduler", active_pid=project_id)


# --------------------------------------------------------------------------- #
# v0.4.1: Метрики и обучение (импорт метрик, ручной ввод, влияние на обучение)  #
# --------------------------------------------------------------------------- #

# Общий блок предупреждений (нужен и как справка, и как якорь для тестов).
_METRICS_WARNING_HTML = (
    "<div class='callout warn'><b>Реальные API-метрики выключены.</b> "
    "Demo/estimated метрики <b>не являются реальными показателями</b> площадки. "
    "Live-публикации не выполняются, внешние вызовы по умолчанию отключены.</div>"
)

# Селектор источника метрик (все источники — для фильтров и форм).
_SOURCE_OPTIONS_HTML = (
    "<option value='demo'>demo</option>"
    "<option value='manual'>manual</option>"
    "<option value='estimated'>estimated</option>"
    "<option value='internal'>internal</option>"
    "<option value='api'>api</option>"
)


@router.get("/metrics", response_class=HTMLResponse)
def ui_metrics_index() -> HTMLResponse:
    """Лендинг метрик: выбрать проект и открыть «Метрики и обучение»."""
    body = (
        "<h2>Метрики и обучение</h2>"
        + _METRICS_WARNING_HTML
        + "<div class='card'><h3>Проекты</h3><div id='mx-projects' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{const a=needAccount(eEl);if(!a)return;try{"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "const host=document.getElementById('mx-projects');host.classList.remove('muted');"
        "host.innerHTML=ps.length?ps.map(p=>`<div class='sched-task'><b>${esc(p.name)}</b> "
        "<a href='/ui/projects/${p.id}/metrics'><button class='mini'>Метрики</button></a> "
        "<a href='/ui/projects/${p.id}/learning/metrics'><button class='mini sec'>Влияние на обучение</button></a></div>`).join('')"
        ":\"<div class='muted'>Нет проектов.</div>\";}catch(x){err(eEl,x)}})();"
    )
    return _page("Метрики", body, script, active="metrics")


@router.get("/projects/{project_id}/metrics", response_class=HTMLResponse)
def ui_project_metrics(project_id: int) -> HTMLResponse:
    """Страница «Метрики и обучение»: сводка, фильтры, импорт, ручной ввод."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/learning/metrics'><button class='ghost mini'>Влияние на обучение</button></a>"
        f"<a href='/ui/projects/{project_id}/learning'><button class='ghost mini'>Чему бот научился</button></a></div>"
        "<h2>Метрики и обучение</h2>"
        + _METRICS_WARNING_HTML
        # Фильтры
        + "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='mx-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Источник</label><select id='mx-source'>"
        "<option value=''>Все</option>" + _SOURCE_OPTIONS_HTML + "</select></div>"
        "<div><label>Глубина</label><select id='mx-depth'>"
        "<option value='light'>light</option><option value='standard' selected>standard</option>"
        "<option value='deep'>deep</option></select></div>"
        "<div><label>Период с</label><input id='mx-from' placeholder='YYYY-MM-DD' style='width:130px'></div>"
        "<div><label>Период по</label><input id='mx-to' placeholder='YYYY-MM-DD' style='width:130px'></div>"
        "</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='mxPreview()'>Preview import</button>"
        "<button class='mini' onclick='mxRunDemo()'>Run demo import</button>"
        "<button class='mini ghost' onclick=\"document.getElementById('mx-manual').scrollIntoView()\">Внести метрики вручную</button>"
        "<button class='mini ghost' onclick='mxRebuild()'>Пересчитать обучение</button>"
        "</div></div>"
        # Summary cards
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Постов с метриками</div><div id='mx-with' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Средний ER</div><div id='mx-er' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Средний CTR</div><div id='mx-ctr' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Лучший пост</div><div id='mx-best' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Лучший тег</div><div id='mx-tag' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Лучшее время</div><div id='mx-time' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Посты и метрики</h3><div id='mx-posts' class='muted'>Загрузка…</div></div>"
        # Ручной ввод метрик
        "<div class='card' id='mx-manual'><h3>Внести метрики вручную "
        "<span class='badge'>бесплатно</span></h3>"
        "<p class='muted'>Источник: <b>manual</b>. Метрики сохранятся как снимок и повлияют на обучение.</p>"
        "<div class='an-filters'>"
        "<div><label>publication_id</label><input id='mm-pub' type='number' style='width:120px'></div>"
        "<div><label>views</label><input id='mm-views' type='number' style='width:100px'></div>"
        "<div><label>reach</label><input id='mm-reach' type='number' style='width:100px'></div>"
        "<div><label>impressions</label><input id='mm-impr' type='number' style='width:100px'></div>"
        "<div><label>likes</label><input id='mm-likes' type='number' style='width:100px'></div>"
        "<div><label>comments</label><input id='mm-comments' type='number' style='width:100px'></div>"
        "<div><label>shares</label><input id='mm-shares' type='number' style='width:100px'></div>"
        "<div><label>saves</label><input id='mm-saves' type='number' style='width:100px'></div>"
        "<div><label>clicks</label><input id='mm-clicks' type='number' style='width:100px'></div>"
        "<div><label>followers_delta</label><input id='mm-fd' type='number' style='width:100px'></div>"
        "</div>"
        "<div class='inline' style='margin-top:8px'><button class='mini' onclick='mxManualSave()'>Сохранить метрики</button></div>"
        "</div>"
        "<div id='mx-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('mx-msg');"
        "function q(){return {platform_key:gv('mx-platform')||null,source:gv('mx-source')||'demo',"
        "depth:gv('mx-depth')||'standard',period_start:gv('mx-from')||null,period_end:gv('mx-to')||null};}"
        "async function loadDash(){try{let url='/metrics/projects/'+PID+'/dashboard?';"
        "const p=gv('mx-platform');const s=gv('mx-source');if(p)url+='platform='+encodeURIComponent(p)+'&';if(s)url+='source='+encodeURIComponent(s);"
        "const d=await api('GET',url);"
        "document.getElementById('mx-with').textContent=d.with_metrics_count+' / '+d.posts_count;"
        "document.getElementById('mx-er').textContent=(d.avg_er_percent!=null?d.avg_er_percent+'%':'—');"
        "document.getElementById('mx-ctr').textContent=(d.avg_ctr_percent!=null?d.avg_ctr_percent+'%':'—');"
        "document.getElementById('mx-best').textContent=d.best_post?('#'+d.best_post.post_id+' · '+d.best_post.er_percent+'%'):'—';"
        "document.getElementById('mx-tag').textContent=(d.best_tags&&d.best_tags[0])?('#'+d.best_tags[0]):'—';"
        "document.getElementById('mx-time').textContent=(d.best_times&&d.best_times[0])||'—';"
        "const host=document.getElementById('mx-posts');host.classList.remove('muted');"
        "host.innerHTML=d.posts.length?`<table class='price-table'><thead><tr><th>Пост</th><th>Платформа</th><th>Источник</th>"
        "<th>ER</th><th>CTR</th><th>Reach</th><th>Лайки</th><th>Сохр.</th><th>Клики</th></tr></thead><tbody>`"
        "+d.posts.map(r=>`<tr><td>#${r.post_id}</td><td>${esc(r.platform)}</td><td><span class='badge'>${esc(r.source)}</span></td>"
        "<td>${r.er_percent}%</td><td>${r.ctr_percent}%</td><td>${r.reach}</td><td>${r.likes}</td><td>${r.saves}</td><td>${r.clicks}</td></tr>`).join('')+`</tbody></table>`"
        ":\"<div class='muted'>Метрик пока нет — запустите demo-импорт или внесите вручную.</div>\";"
        "}catch(x){err(eEl,x)}}"
        "async function mxPreview(){try{const r=await api('POST','/metrics/projects/'+PID+'/preview',q());"
        "msg.textContent='Preview: публикаций '+r.publications_found+', оценка '+r.estimated_units+' units ('+esc(r.source)+').';}catch(x){err(eEl,x)}}"
        "async function mxRunDemo(){try{const b=q();b.source='demo';b.idempotency_key='ui-demo-'+PID+'-'+Date.now();"
        "const r=await api('POST','/metrics/projects/'+PID+'/run',b);"
        "msg.textContent='Импорт demo: '+esc(r.status)+', снимков '+r.snapshots_created+', списано '+r.units_charged+' units.';loadDash();}catch(x){err(eEl,x)}}"
        "async function mxRebuild(){try{const r=await api('POST','/metrics/projects/'+PID+'/learning/rebuild-preview',{});"
        "msg.textContent='Пересчёт (превью): версия '+r.profile_version+'. '+((r.changes||[]).slice(0,2).join(' · '));loadDash();}catch(x){err(eEl,x)}}"
        "async function mxManualSave(){try{const pub=parseInt(gv('mm-pub'));if(!pub){msg.textContent='Укажите publication_id';return;}"
        "const body={};[['views','mm-views'],['reach','mm-reach'],['impressions','mm-impr'],['likes','mm-likes'],"
        "['comments','mm-comments'],['shares','mm-shares'],['saves','mm-saves'],['clicks','mm-clicks'],['followers_delta','mm-fd']]"
        ".forEach(([k,id])=>{const v=gv(id);if(v!=='')body[k]=parseInt(v);});"
        "const r=await api('POST','/metrics/publications/'+pub+'/manual',body);"
        "msg.textContent='Метрики сохранены: ER '+(r.er_percent!=null?r.er_percent+'%':'—')+', CTR '+(r.ctr_percent!=null?r.ctr_percent+'%':'—')+' (бесплатно).';loadDash();}catch(x){err(eEl,x)}}"
        "window.mxPreview=mxPreview;window.mxRunDemo=mxRunDemo;window.mxRebuild=mxRebuild;window.mxManualSave=mxManualSave;"
        "['mx-platform','mx-source'].forEach(id=>{const e=document.getElementById(id);if(e)e.addEventListener('change',loadDash);});"
        "loadDash();"
    )
    return _page("Метрики проекта", body, script, active="metrics", active_pid=project_id)


@router.get("/projects/{project_id}/metrics/import", response_class=HTMLResponse)
def ui_project_metrics_import(project_id: int) -> HTMLResponse:
    """Импорт метрик: preview / demo-run + история прогонов."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/metrics'>"
        "<button class='sec mini'>← Метрики</button></a></div>"
        "<h2>Импорт метрик</h2>"
        + _METRICS_WARNING_HTML
        + "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='mi-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Источник</label><select id='mi-source'>"
        + _SOURCE_OPTIONS_HTML
        + "</select></div>"
        "<div><label>Глубина</label><select id='mi-depth'>"
        "<option value='light'>light</option><option value='standard' selected>standard</option>"
        "<option value='deep'>deep</option></select></div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='miPreview()'>Preview import</button>"
        "<button class='mini' onclick='miRun()'>Run demo import</button></div></div>"
        "<div class='card'><h3>История импортов</h3><div id='mi-list' class='muted'>Загрузка…</div></div>"
        "<div id='mi-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('mi-msg');"
        "async function loadRuns(){try{const rows=await api('GET','/metrics/projects/'+PID+'/imports');"
        "const host=document.getElementById('mi-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?`<table class='price-table'><thead><tr><th>ID</th><th>Источник</th><th>Платформа</th>"
        "<th>Статус</th><th>Снимков</th><th>units</th></tr></thead><tbody>`"
        "+rows.map(r=>`<tr><td>#${r.id}</td><td><span class='badge'>${esc(r.source)}</span></td><td>${esc(r.platform_key||'все')}</td>"
        "<td>${esc(r.status)}</td><td>${r.snapshots_created}</td><td>${r.units_charged}</td></tr>`).join('')+`</tbody></table>`"
        ":\"<div class='muted'>Импортов ещё нет.</div>\";}catch(x){err(eEl,x)}}"
        "function q(){return {platform_key:gv('mi-platform')||null,source:gv('mi-source')||'demo',depth:gv('mi-depth')||'standard'};}"
        "async function miPreview(){try{const r=await api('POST','/metrics/projects/'+PID+'/preview',q());"
        "msg.textContent='Preview: публикаций '+r.publications_found+', '+r.estimated_units+' units.';}catch(x){err(eEl,x)}}"
        "async function miRun(){try{const b=q();b.idempotency_key='ui-imp-'+PID+'-'+Date.now();"
        "const r=await api('POST','/metrics/projects/'+PID+'/run',b);"
        "msg.textContent='Импорт: '+esc(r.status)+', снимков '+r.snapshots_created+'.';loadRuns();}catch(x){err(eEl,x)}}"
        "window.miPreview=miPreview;window.miRun=miRun;loadRuns();"
    )
    return _page("Импорт метрик", body, script, active="metrics", active_pid=project_id)


@router.get("/projects/{project_id}/metrics/manual", response_class=HTMLResponse)
def ui_project_metrics_manual(project_id: int) -> HTMLResponse:
    """Отдельная страница ручного ввода метрик публикации (source=manual, бесплатно)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/metrics'>"
        "<button class='sec mini'>← Метрики</button></a></div>"
        "<h2>Ручной ввод метрик <span class='badge'>бесплатно</span></h2>"
        "<p class='muted'>Источник: <b>manual</b>. Введите publication_id и известные метрики "
        "(неизвестные оставьте пустыми — они не считаются нулём).</p>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>publication_id</label><input id='mm-pub' type='number' style='width:120px'></div>"
        "<div><label>views</label><input id='mm-views' type='number' style='width:100px'></div>"
        "<div><label>reach</label><input id='mm-reach' type='number' style='width:100px'></div>"
        "<div><label>impressions</label><input id='mm-impr' type='number' style='width:100px'></div>"
        "<div><label>likes</label><input id='mm-likes' type='number' style='width:100px'></div>"
        "<div><label>comments</label><input id='mm-comments' type='number' style='width:100px'></div>"
        "<div><label>shares</label><input id='mm-shares' type='number' style='width:100px'></div>"
        "<div><label>saves</label><input id='mm-saves' type='number' style='width:100px'></div>"
        "<div><label>clicks</label><input id='mm-clicks' type='number' style='width:100px'></div>"
        "<div><label>followers_delta</label><input id='mm-fd' type='number' style='width:100px'></div>"
        "</div>"
        "<div class='inline' style='margin-top:8px'><button class='mini' onclick='mmSave()'>Сохранить метрики</button></div></div>"
        "<div id='mm-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('mm-msg');"
        "async function mmSave(){try{const pub=parseInt(gv('mm-pub'));if(!pub){msg.textContent='Укажите publication_id';return;}"
        "const body={};[['views','mm-views'],['reach','mm-reach'],['impressions','mm-impr'],['likes','mm-likes'],"
        "['comments','mm-comments'],['shares','mm-shares'],['saves','mm-saves'],['clicks','mm-clicks'],['followers_delta','mm-fd']]"
        ".forEach(([k,id])=>{const v=gv(id);if(v!=='')body[k]=parseInt(v);});"
        "const r=await api('POST','/metrics/publications/'+pub+'/manual',body);"
        "msg.textContent='Сохранено: ER '+(r.er_percent!=null?r.er_percent+'%':'—')+' (бесплатно).';}catch(x){err(eEl,x)}}"
        "window.mmSave=mmSave;"
    )
    return _page("Ручной ввод метрик", body, script, active="metrics", active_pid=project_id)


@router.get("/projects/{project_id}/learning/metrics", response_class=HTMLResponse)
def ui_project_learning_metrics(project_id: int) -> HTMLResponse:
    """«Как метрики повлияли на обучение»: сводка профиля + пересчёт по метрикам."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/metrics'>"
        "<button class='sec mini'>← Метрики</button></a>"
        f"<a href='/ui/projects/{project_id}/learning'><button class='ghost mini'>Чему бот научился</button></a></div>"
        "<h2>Как метрики повлияли на обучение</h2>"
        + _METRICS_WARNING_HTML
        + "<div class='card'><div class='kv'>"
        "<div>Уверенность профиля</div><div id='lm-conf'>—</div>"
        "<div>Версия профиля</div><div id='lm-ver'>—</div>"
        "<div>Средний ER (метрики)</div><div id='lm-er'>—</div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='lmPreview()'>Пересчитать (превью)</button>"
        "<button class='mini' onclick='lmRebuild()'>Пересчитать обучение</button></div></div>"
        "<div class='grid'>"
        "<div class='card'><h3>Лучшие темы</h3><div id='lm-topics' class='muted'>—</div></div>"
        "<div class='card'><h3>Слабые темы</h3><div id='lm-weak' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучший CTA</h3><div id='lm-cta' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучший тип медиа</h3><div id='lm-media' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучшее время</h3><div id='lm-time' class='muted'>—</div></div>"
        "<div class='card'><h3>Сильные теги</h3><div id='lm-tags' class='muted'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Что изменилось после метрик</h3><div id='lm-changes' class='muted'>—</div></div>"
        "<div class='card'><h3>Последние импорты метрик</h3><div id='lm-events' class='muted'>—</div></div>"
        "<div id='lm-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('lm-msg');"
        "function fill(id,arr,pre){const el=document.getElementById(id);el.classList.remove('muted');"
        "el.innerHTML=(arr&&arr.length)?arr.map(v=>`<span class='badge'>${(pre||'')+esc(''+v)}</span>`).join(' '):\"<span class='muted'>пока нет данных</span>\";}"
        "async function load(){try{const s=await api('GET','/learning/projects/'+PID+'/summary');"
        "document.getElementById('lm-conf').textContent=Math.round((s.confidence_score||0)*100)+'%';"
        "document.getElementById('lm-ver').textContent=s.profile_version||0;"
        "const perf=s.performance_patterns||{};document.getElementById('lm-er').textContent=(perf.avg_engagement_rate!=null?Math.round(perf.avg_engagement_rate*10000)/100+'%':'—');"
        "fill('lm-topics',s.preferred_topics);fill('lm-weak',s.rejected_topics);fill('lm-cta',s.preferred_cta);"
        "fill('lm-media',s.preferred_media_types);fill('lm-time',s.best_publish_times);fill('lm-tags',s.high_performing_tags,'#');"
        "const ev=(s.recent_events||[]).filter(e=>e.event_type==='analytics_imported');"
        "document.getElementById('lm-events').innerHTML=ev.length?ev.map(e=>`<div class='muted'>#${e.post_id} · импорт метрик</div>`).join(''):\"<span class='muted'>Импортов метрик пока нет.</span>\";"
        "}catch(x){err(eEl,x)}}"
        "async function lmPreview(){try{const r=await api('POST','/metrics/projects/'+PID+'/learning/rebuild-preview',{});"
        "document.getElementById('lm-changes').innerHTML=(r.changes||[]).map(c=>`<div>• ${esc(c)}</div>`).join('')||'—';load();}catch(x){err(eEl,x)}}"
        "async function lmRebuild(){try{const r=await api('POST','/metrics/projects/'+PID+'/learning/rebuild',{});"
        "msg.textContent='Профиль пересчитан (версия '+r.profile_version+', списано '+r.units_charged+' units).';"
        "document.getElementById('lm-changes').innerHTML=(r.changes||[]).map(c=>`<div>• ${esc(c)}</div>`).join('')||'—';load();}catch(x){err(eEl,x)}}"
        "window.lmPreview=lmPreview;window.lmRebuild=lmRebuild;load();"
    )
    return _page("Обучение по метрикам", body, script, active="metrics", active_pid=project_id)


# --------------------------------------------------------------------------- #
# v0.4.2: A/B-эксперименты и оптимизация тем                                   #
# --------------------------------------------------------------------------- #

_EXPERIMENTS_WARNING_HTML = (
    "<div class='callout warn'><b>Live-публикаций нет.</b> Варианты идут в очередь ревью. "
    "Demo/estimated метрики не являются реальными показателями. Обучение строго по проекту "
    "(cross-client learning отключён).</div>"
)


@router.get("/experiments", response_class=HTMLResponse)
def ui_experiments_index() -> HTMLResponse:
    """Лендинг экспериментов: выбрать проект."""
    body = (
        "<h2>A/B-эксперименты</h2>"
        + _EXPERIMENTS_WARNING_HTML
        + "<div class='card'><h3>Проекты</h3><div id='ex-projects' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{const a=needAccount(eEl);if(!a)return;try{"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "const host=document.getElementById('ex-projects');host.classList.remove('muted');"
        "host.innerHTML=ps.length?ps.map(p=>`<div class='sched-task'><b>${esc(p.name)}</b> "
        "<a href='/ui/projects/${p.id}/experiments'><button class='mini'>Эксперименты</button></a> "
        "<a href='/ui/projects/${p.id}/optimization'><button class='mini sec'>Оптимизация</button></a></div>`).join('')"
        ":\"<div class='muted'>Нет проектов.</div>\";}catch(x){err(eEl,x)}})();"
    )
    return _page("Эксперименты", body, script, active="experiments")


@router.get("/optimization", response_class=HTMLResponse)
def ui_optimization_index() -> HTMLResponse:
    """Лендинг оптимизации: выбрать проект."""
    body = (
        "<h2>Оптимизация тем</h2>"
        "<p class='muted'>Что Botfleet рекомендует публиковать дальше на основе истории проекта.</p>"
        "<div class='card'><h3>Проекты</h3><div id='op-projects' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{const a=needAccount(eEl);if(!a)return;try{"
        "const ps=await api('GET','/saas/accounts/'+a+'/projects');"
        "const host=document.getElementById('op-projects');host.classList.remove('muted');"
        "host.innerHTML=ps.length?ps.map(p=>`<div class='sched-task'><b>${esc(p.name)}</b> "
        "<a href='/ui/projects/${p.id}/optimization'><button class='mini'>Рекомендации</button></a></div>`).join('')"
        ":\"<div class='muted'>Нет проектов.</div>\";}catch(x){err(eEl,x)}})();"
    )
    return _page("Оптимизация", body, script, active="optimization")


@router.get("/projects/{project_id}/experiments", response_class=HTMLResponse)
def ui_project_experiments(project_id: int) -> HTMLResponse:
    """Список A/B-экспериментов проекта + создание."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/optimization'><button class='ghost mini'>Оптимизация</button></a>"
        f"<a href='/ui/projects/{project_id}/recommendations'><button class='ghost mini'>Рекомендации</button></a></div>"
        "<h2>A/B-эксперименты</h2>"
        + _EXPERIMENTS_WARNING_HTML
        + "<div class='card'><h3>Создать A/B по теме</h3>"
        "<div class='an-filters'>"
        "<div><label>Платформа</label><select id='ex-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Тема</label><input id='ex-topic' placeholder='Напр. Футболки с логотипом' style='width:280px'></div>"
        "<div><label>Вариантов</label><select id='ex-count'><option>2</option><option>3</option></select></div>"
        "</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='exPreview()'>Посмотреть варианты</button>"
        "<button class='mini' onclick='exCreate()'>Создать A/B по теме</button>"
        f"<a href='/ui/projects/{project_id}/recommendations'><button class='mini ghost'>Посмотреть рекомендации</button></a>"
        "</div><div id='ex-preview' class='muted' style='margin-top:8px'></div></div>"
        "<div class='card'><h3>Эксперименты</h3><div id='ex-list' class='muted'>Загрузка…</div></div>"
        "<div id='ex-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('ex-msg');"
        "function stPill(s){const ok=s==='completed';return `<span class='pill ${ok?'ok':''}'>${esc(s)}</span>`;}"
        "async function loadList(){try{const rows=await api('GET','/experiments/projects/'+PID);"
        "const host=document.getElementById('ex-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?`<table class='price-table'><thead><tr><th>ID</th><th>Тип</th><th>Платформа</th>"
        "<th>Статус</th><th>Winner</th><th>Confidence</th></tr></thead><tbody>`"
        "+rows.map(r=>`<tr><td><a href='/ui/projects/'+PID+'/experiments/${r.id}'>#${r.id}</a></td>"
        "<td>${esc(r.experiment_type)}</td><td>${esc(r.platform_key||'все')}</td>"
        "<td>${stPill(r.status)}</td><td>${r.winner_variant_id?('#'+r.winner_variant_id):'—'}</td>"
        "<td>${Math.round((r.confidence_score||0)*100)}%</td></tr>`).join('')+`</tbody></table>`"
        ":\"<div class='muted'>Экспериментов ещё нет — создайте A/B по теме.</div>\";}catch(x){err(eEl,x)}}"
        "function body(){return {platform_key:gv('ex-platform')||null,topic:gv('ex-topic'),variant_count:parseInt(gv('ex-count')||'2')};}"
        "async function exPreview(){try{const b=body();if(!b.topic){msg.textContent='Укажите тему';return;}"
        "const r=await api('POST','/experiments/projects/'+PID+'/preview-topic',b);"
        "document.getElementById('ex-preview').innerHTML='Оценка: '+r.estimated_units+' units. '+r.variants.map(v=>`<div class='sched-task'><b>${esc(v.variant_key)}</b> ${esc(v.title||'')}<div class='muted'>${esc(v.text_preview||'')}</div></div>`).join('');}catch(x){err(eEl,x)}}"
        "async function exCreate(){try{const b=body();if(!b.topic){msg.textContent='Укажите тему';return;}"
        "b.idempotency_key='ui-ex-'+PID+'-'+Date.now();const r=await api('POST','/experiments/projects/'+PID+'/create-from-topic',b);"
        "msg.textContent='Эксперимент #'+r.experiment.id+' создан ('+r.outcome+'). Варианты — в очереди ревью.';loadList();}catch(x){err(eEl,x)}}"
        "window.exPreview=exPreview;window.exCreate=exCreate;loadList();"
    )
    return _page("Эксперименты проекта", body, script, active="experiments", active_pid=project_id)


@router.get("/projects/{project_id}/experiments/{experiment_id}", response_class=HTMLResponse)
def ui_project_experiment_detail(project_id: int, experiment_id: int) -> HTMLResponse:
    """Детали эксперимента: варианты, метрики, winner."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/experiments'>"
        "<button class='sec mini'>← Эксперименты</button></a></div>"
        "<h2>Эксперимент</h2>"
        + _EXPERIMENTS_WARNING_HTML
        + "<div class='card'><div id='ex-head' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Варианты</h3><div id='ex-variants' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Выбор winner (победителя)</h3>"
        "<p class='muted'>Выберите вручную или автоматически по метрикам. Winner обновляет обучение.</p>"
        "<div class='inline'><button class='mini' onclick='exAuto()'>Авто-winner по метрикам</button>"
        "<span id='ex-manual'></span></div>"
        "<div id='ex-winner' class='card muted' style='margin-top:8px'></div></div>"
        "<div id='ex-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const EID={experiment_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('ex-msg');"
        "async function load(){try{const s=await api('GET','/experiments/'+EID);"
        "const e=s.experiment;"
        "document.getElementById('ex-head').classList.remove('muted');"
        "document.getElementById('ex-head').innerHTML=`<b>${esc(e.title)}</b><div class='muted'>${esc(e.hypothesis||'')}</div>"
        "<div class='kv'><div>Статус</div><div><span class='pill ${e.status===\"completed\"?'ok':''}'>${esc(e.status)}</span></div>"
        "<div>Тип</div><div>${esc(e.experiment_type)}</div><div>Confidence</div><div>${Math.round((e.confidence_score||0)*100)}%</div></div>`;"
        "const host=document.getElementById('ex-variants');host.classList.remove('muted');"
        "host.innerHTML=s.variants.map(v=>`<div class='card' ${v.is_winner?\"style='border:2px solid var(--ok,#2a2)'\":''}>"
        "<div class='inline'><b>${esc(v.variant_key)}</b> ${esc(v.title||'')} ${v.is_winner?\"<span class='pill ok'>winner</span>\":''}</div>"
        "<div class='kv'><div>Угол</div><div>${esc(v.angle||'')}</div><div>CTA</div><div>${esc(v.cta_type||'')}</div>"
        "<div>Качество</div><div>${v.quality_score!=null?v.quality_score:'—'}</div>"
        "<div>Прогноз вовлечения</div><div>${v.predicted_engagement_score!=null?v.predicted_engagement_score:'—'}</div>"
        "<div>ER</div><div>${v.er_percent!=null?v.er_percent+'%':'—'}</div>"
        "<div>CTR</div><div>${v.ctr_percent!=null?v.ctr_percent+'%':'—'}</div></div></div>`).join('');"
        "document.getElementById('ex-manual').innerHTML=s.variants.map(v=>`<button class='mini sec' onclick='exManual(${v.id})'>Выбрать ${esc(v.variant_key)}</button>`).join(' ');"
        "if(s.winner){document.getElementById('ex-winner').classList.remove('muted');"
        "document.getElementById('ex-winner').innerHTML='<b>Победитель: '+esc(s.winner.variant_key)+'</b> ('+esc(s.winner.winner_reason||'')+')<br>'+(s.winner_explanation||[]).map(esc).join('<br>');}"
        "}catch(x){err(eEl,x)}}"
        "async function exManual(vid){try{const r=await api('POST','/experiments/'+EID+'/choose-winner',{method:'manual',variant_id:vid});"
        "msg.textContent='Winner выбран вручную. Обучение обновлено.';load();}catch(x){err(eEl,x)}}"
        "async function exAuto(){try{const r=await api('POST','/experiments/'+EID+'/choose-winner',{method:'auto'});"
        "msg.textContent='Winner выбран автоматически по метрикам.';load();}catch(x){err(eEl,x)}}"
        "window.exManual=exManual;window.exAuto=exAuto;load();"
    )
    return _page("Эксперимент", body, script, active="experiments", active_pid=project_id)


@router.get("/projects/{project_id}/optimization", response_class=HTMLResponse)
def ui_project_optimization(project_id: int) -> HTMLResponse:
    """Оптимизация: стратегия тем + рекомендации."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/experiments'><button class='ghost mini'>Эксперименты</button></a>"
        f"<a href='/ui/projects/{project_id}/experiment-suggestions'><button class='ghost mini'>Предложения worker-а</button></a></div>"
        "<h2>Что Botfleet рекомендует публиковать дальше</h2>"
        + _EXPERIMENTS_WARNING_HTML
        + "<div class='card'><div class='kv'>"
        "<div>Уверенность профиля</div><div id='op-conf'>—</div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini' onclick='opGenerate()'>Сгенерировать рекомендации</button>"
        "<button class='mini sec' onclick='opWorkerPreview()'>Preview worker suggestions</button>"
        f"<a href='/ui/projects/{project_id}/experiment-suggestions'><button class='mini ghost'>Предложения worker-а</button></a>"
        "</div><div id='op-sugg' class='muted' style='margin-top:6px'></div></div>"
        "<div class='grid'>"
        "<div class='card'><h3>Публиковать чаще</h3><div id='op-more' class='muted'>—</div></div>"
        "<div class='card'><h3>Избегать</h3><div id='op-avoid' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучший CTA</h3><div id='op-cta' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучшее медиа</h3><div id='op-media' class='muted'>—</div></div>"
        "<div class='card'><h3>Лучшее время</h3><div id='op-time' class='muted'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Рекомендации тем</h3><div id='op-recs' class='muted'>Загрузка…</div></div>"
        "<div id='op-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('op-msg');"
        "function fill(id,arr,pre){const el=document.getElementById(id);el.classList.remove('muted');"
        "el.innerHTML=(arr&&arr.length)?arr.map(v=>`<span class='badge'>${(pre||'')+esc(''+v)}</span>`).join(' '):\"<span class='muted'>пока нет данных</span>\";}"
        "let RECS=[];"
        "async function load(){try{const s=await api('GET','/experiments/projects/'+PID+'/strategy');"
        "document.getElementById('op-conf').textContent=Math.round((s.confidence_score||0)*100)+'%';"
        "fill('op-more',s.will_do_more);fill('op-avoid',s.will_avoid);fill('op-cta',s.best_cta);"
        "fill('op-media',s.best_media_types);fill('op-time',s.best_publish_times);"
        "const r=await api('GET','/experiments/projects/'+PID+'/recommendations');RECS=r.recommendations;"
        "const host=document.getElementById('op-recs');host.classList.remove('muted');"
        "host.innerHTML=RECS.length?RECS.map((x,i)=>`<div class='sched-task'>"
        "<span class='pill'>${esc(x.category)}</span> <b>${esc(''+x.topic)}</b> <span class='muted'>· ${Math.round(x.confidence_score*100)}% · ${esc(x.reason)}</span> "
        "<button class='mini sec' onclick='opAB(${i})'>Создать A/B</button></div>`).join('')"
        ":\"<div class='muted'>Пока недостаточно данных для рекомендаций.</div>\";"
        "}catch(x){err(eEl,x)}}"
        "async function opAB(i){try{const topic=''+(RECS[i]&&RECS[i].topic||'');if(!topic)return;"
        "const r=await api('POST','/experiments/projects/'+PID+'/create-from-topic',{topic:topic,variant_count:2,idempotency_key:'ui-op-'+PID+'-'+Date.now()});"
        "msg.textContent='Эксперимент #'+r.experiment.id+' создан по теме «'+esc(topic)+'». Варианты — в очереди ревью.';}catch(x){err(eEl,x)}}"
        "async function opGenerate(){try{const r=await api('POST','/experiment-suggestions/projects/'+PID+'/generate',{});"
        "document.getElementById('op-sugg').textContent='Создано предложений: '+r.created+' (пропущено '+r.skipped+'). Открыть: Предложения worker-а.';}catch(x){err(eEl,x)}}"
        "async function opWorkerPreview(){try{const r=await api('POST','/experiment-suggestions/projects/'+PID+'/worker-preview',{});"
        "document.getElementById('op-sugg').textContent='Preview worker: enabled='+r.enabled+', scanned='+r.scanned+' (worker-генерация выключена по умолчанию).';}catch(x){err(eEl,x)}}"
        "window.opGenerate=opGenerate;window.opWorkerPreview=opWorkerPreview;window.opAB=opAB;load();"
    )
    return _page("Оптимизация проекта", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/recommendations", response_class=HTMLResponse)
def ui_project_recommendations(project_id: int) -> HTMLResponse:
    """Отдельная страница рекомендаций тем проекта."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/optimization'>"
        "<button class='sec mini'>← Оптимизация</button></a>"
        f"<a href='/ui/projects/{project_id}/experiments'><button class='ghost mini'>Эксперименты</button></a>"
        f"<a href='/ui/projects/{project_id}/experiment-suggestions'><button class='ghost mini'>Предложения worker-а</button></a></div>"
        "<h2>Рекомендации контента</h2>"
        + _EXPERIMENTS_WARNING_HTML
        + "<div class='card'><h3>Рекомендации worker-а</h3>"
        "<p class='muted'>Botfleet сам находит возможности (темы, CTA, форматы) и сохраняет их "
        "как предложения. Live-публикаций нет — варианты уйдут в очередь ревью.</p>"
        f"<div class='inline'><a href='/ui/projects/{project_id}/experiment-suggestions'>"
        "<button class='mini'>Открыть предложения worker-а</button></a></div></div>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='rc-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div></div></div>"
        "<div id='rc-list' class='muted'>Загрузка…</div>"
        "<div id='rc-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('rc-msg');"
        "async function load(){try{const p=gv('rc-platform');let url='/experiments/projects/'+PID+'/recommendations';if(p)url+='?platform_key='+encodeURIComponent(p);"
        "const r=await api('GET',url);const host=document.getElementById('rc-list');host.classList.remove('muted');"
        "host.innerHTML=r.recommendations.length?r.recommendations.map(x=>`<div class='card'>"
        "<div class='inline'><span class='pill'>${esc(x.category)}</span> <b>${esc(''+x.topic)}</b> "
        "<span class='muted'>${Math.round(x.confidence_score*100)}%</span></div>"
        "<div class='muted'>${esc(x.reason)}</div>"
        "<div class='muted'>CTA: ${esc(''+(x.suggested_cta||'—'))} · медиа: ${esc(''+(x.suggested_media_type||'—'))} · время: ${esc(''+(x.suggested_time||'—'))}</div>"
        "${(x.risk_flags&&x.risk_flags.length)?`<div class='muted'>⚠ ${x.risk_flags.map(esc).join(', ')}</div>`:''}</div>`).join('')"
        ":\"<div class='card muted'>Пока недостаточно данных — соберите feedback и метрики.</div>\";}catch(x){err(eEl,x)}}"
        "const e=document.getElementById('rc-platform');if(e)e.addEventListener('change',load);load();"
    )
    return _page(
        "Рекомендации контента", body, script, active="optimization", active_pid=project_id
    )


@router.get("/projects/{project_id}/experiment-suggestions", response_class=HTMLResponse)
def ui_project_experiment_suggestions(project_id: int) -> HTMLResponse:
    """Рекомендации worker-а: активные предложения + приём/отклонение/создание A/B."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/optimization'>"
        "<button class='sec mini'>← Оптимизация</button></a>"
        f"<a href='/ui/projects/{project_id}/experiments'><button class='ghost mini'>Эксперименты</button></a></div>"
        "<h2>Рекомендации worker-а</h2>"
        "<div class='callout warn'><b>Live-публикаций нет.</b> Варианты уйдут в очередь ревью. "
        "Авто-создание экспериментов worker-ом выключено по умолчанию. Demo/estimated метрики "
        "не являются реальными показателями; обучение строго по проекту.</div>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='es-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='esPreview()'>Preview</button>"
        "<button class='mini' onclick='esGenerate()'>Сгенерировать предложения</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Активных</div><div id='es-active' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Принято</div><div id='es-accepted' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Экспериментов</div><div id='es-exp' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Средняя уверенность</div><div id='es-conf' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Активные предложения</h3><div id='es-list' class='muted'>Загрузка…</div></div>"
        "<div id='es-preview' class='muted'></div>"
        "<div id='es-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');const msg=document.getElementById('es-msg');"
        "function card(s){"
        "const risks=(s.risk_flags||[]).map(esc).join(', ');"
        "const sig=(s.source_signals||[]).map(esc).join(', ');"
        "const canExp=['publish_more','explore','fill_gap','retest','weak_topic_fix'].includes(s.suggestion_type);"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(s.suggestion_type)}</span> "
        "<b>${esc(''+s.topic)}</b> <span class='muted'>${Math.round(s.confidence_score*100)}% · ${esc(s.status)}</span></div>"
        "<div class='muted'>${esc(s.reason||'')}</div>"
        "<div class='muted'>CTA: ${esc(''+(s.suggested_cta||'—'))} · медиа: ${esc(''+(s.suggested_media_type||'—'))} · время: ${esc(''+(s.suggested_publish_time||'—'))}</div>"
        "${sig?`<div class='muted'>Сигналы: ${sig}</div>`:''}${risks?`<div class='muted'>⚠ ${risks}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini' onclick='esAccept(${s.id})'>Принять</button>"
        "<button class='mini sec' onclick='esReject(${s.id})'>Отклонить</button>"
        "<button class='mini sec' onclick='esDismiss(${s.id})'>Скрыть</button>"
        "${canExp?`<button class='mini ghost' onclick='esCreate(${s.id})'>Создать A/B тест</button>`:''}"
        "</div></div>`;}"
        "async function loadDash(){try{const d=await api('GET','/experiment-suggestions/projects/'+PID+'/dashboard');"
        "document.getElementById('es-active').textContent=d.active_count;"
        "document.getElementById('es-accepted').textContent=d.accepted;"
        "document.getElementById('es-exp').textContent=d.experiments_created;"
        "document.getElementById('es-conf').textContent=Math.round((d.avg_confidence||0)*100)+'%';"
        "const host=document.getElementById('es-list');host.classList.remove('muted');"
        "host.innerHTML=d.active_suggestions.length?d.active_suggestions.map(card).join('')"
        ":\"<div class='muted'>Активных предложений нет — нажмите «Сгенерировать предложения».</div>\";}catch(x){err(eEl,x)}}"
        "async function esPreview(){try{const p=gv('es-platform');const r=await api('POST','/experiment-suggestions/projects/'+PID+'/preview',{platform_key:p||null});"
        "document.getElementById('es-preview').innerHTML='<b>Preview ('+r.suggestions.length+'):</b> '+r.suggestions.map(x=>`<div class='sched-task'>${esc(''+x.topic)} · ${Math.round((x.confidence_score||0)*100)}%${x.meets_confidence?'':' (ниже порога)'}</div>`).join('');}catch(x){err(eEl,x)}}"
        "async function esGenerate(){try{const p=gv('es-platform');const r=await api('POST','/experiment-suggestions/projects/'+PID+'/generate',{platform_key:p||null});"
        "msg.textContent='Создано предложений: '+r.created+' (пропущено '+r.skipped+').';loadDash();}catch(x){err(eEl,x)}}"
        "async function esAccept(id){try{await api('POST','/experiment-suggestions/'+id+'/accept',{});msg.textContent='Принято.';loadDash();}catch(x){err(eEl,x)}}"
        "async function esReject(id){try{await api('POST','/experiment-suggestions/'+id+'/reject',{reason:'не сейчас'});msg.textContent='Отклонено.';loadDash();}catch(x){err(eEl,x)}}"
        "async function esDismiss(id){try{await api('POST','/experiment-suggestions/'+id+'/dismiss',{});msg.textContent='Скрыто.';loadDash();}catch(x){err(eEl,x)}}"
        "async function esCreate(id){try{const r=await api('POST','/experiment-suggestions/'+id+'/create-experiment',{});"
        "msg.textContent='A/B эксперимент #'+r.experiment_id+' создан ('+r.outcome+'). Варианты — в очереди ревью.';loadDash();}catch(x){err(eEl,x)}}"
        "window.esPreview=esPreview;window.esGenerate=esGenerate;window.esAccept=esAccept;window.esReject=esReject;window.esDismiss=esDismiss;window.esCreate=esCreate;"
        "loadDash();"
    )
    return _page("Предложения worker-а", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/topic-decisions", response_class=HTMLResponse)
def ui_project_topic_decisions(project_id: int) -> HTMLResponse:
    """Выбор тем по обучению: решения worker-а «почему бот выбрал эту тему»."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/optimization'>"
        "<button class='sec mini'>← Оптимизация</button></a>"
        f"<a href='/ui/projects/{project_id}/automation'><button class='ghost mini'>Автоматизация</button></a>"
        f"<a href='/ui/review'><button class='ghost mini'>Очередь ревью</button></a></div>"
        "<h2>Выбор тем по обучению</h2>"
        "<div class='callout warn'><b>Решение создаёт draft/needs_review, live не выполняется.</b> "
        "Автовыбор worker-ом выключен по умолчанию; при низкой уверенности пост уходит в ревью с "
        "пометкой low_confidence. Обучение строго по проекту.</div>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='td-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Статус</label><select id='td-status'>"
        "<option value=''>Любой</option><option value='selected'>selected</option>"
        "<option value='draft_created'>draft_created</option><option value='preview'>preview</option>"
        "</select></div>"
        "<div><label>Источник</label><select id='td-source'>"
        "<option value=''>Любой</option><option value='learning_profile'>learning_profile</option>"
        "<option value='ab_winner'>ab_winner</option>"
        "<option value='experiment_suggestion'>experiment_suggestion</option>"
        "<option value='metrics'>metrics</option><option value='crm_category'>crm_category</option>"
        "</select></div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='tdPreview()'>Preview следующей темы</button>"
        "<button class='mini' onclick='tdCreate()'>Создать решение</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Всего</div><div id='td-total' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Низкая уверенность</div><div id='td-low' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Средняя уверенность</div><div id='td-conf' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Автовыбор worker</div><div id='td-worker' class='an-big'>—</div></div>"
        "</div>"
        "<div id='td-preview' class='muted'></div>"
        "<div class='card'><h3>Решения</h3><div id='td-list' class='muted'>Загрузка…</div></div>"
        "<div id='td-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('td-msg');"
        "function tdcard(d){"
        "const risks=(d.risk_flags||[]).map(esc).join(', ');"
        "const reasons=(d.reasons||[]).slice(0,3).map(esc).join(' · ');"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(d.decision_source)}</span> "
        "<b>${esc(''+d.selected_topic)}</b> <span class='muted'>${Math.round(d.confidence_score*100)}% · ${esc(d.status)}</span></div>"
        "<div class='muted'>CTA: ${esc(''+(d.selected_cta||'—'))} · формат: ${esc(''+(d.selected_format||'—'))} · медиа: ${esc(''+(d.selected_media_strategy||'—'))}</div>"
        "${reasons?`<div class='muted'>${reasons}</div>`:''}${risks?`<div class='muted'>⚠ ${risks}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>"
        "<a href='/ui/projects/'+PID+'/topic-decisions/'+d.id><button class='mini sec'>Почему эта тема</button></a>"
        "${d.schedule_run_id?`<span class='muted'>run #${d.schedule_run_id}</span>`:''}"
        "</div></div>`;}"
        "async function loadTD(){try{const d=await api('GET','/topic-decisions/projects/'+PID+'/dashboard');"
        "document.getElementById('td-total').textContent=d.total;"
        "document.getElementById('td-low').textContent=d.low_confidence_count;"
        "document.getElementById('td-conf').textContent=Math.round((d.avg_confidence||0)*100)+'%';"
        "document.getElementById('td-worker').textContent=d.worker_enabled?'вкл':'выкл';"
        "const q=[];const st=gv('td-status');const sr=gv('td-source');const pf=gv('td-platform');"
        "if(pf)q.push('platform_key='+pf);if(st)q.push('decision_status='+st);if(sr)q.push('source='+sr);"
        "const rows=await api('GET','/topic-decisions/projects/'+PID+(q.length?'?'+q.join('&'):''));"
        "const host=document.getElementById('td-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(tdcard).join(''):"
        "\"<div class='muted'>Решений нет — нажмите «Создать решение».</div>\";}catch(x){err(eEl,x)}}"
        "async function tdPreview(){try{const p=gv('td-platform');"
        "const r=await api('POST','/topic-decisions/projects/'+PID+'/preview',{platform_key:p||null});"
        "document.getElementById('td-preview').innerHTML=`<div class='card'><b>Preview:</b> ${esc(''+r.selected_topic)} "
        "(${Math.round((r.confidence_score||0)*100)}%, ${esc(r.decision_source)})<div class='muted'>${(r.reasons||[]).slice(0,3).map(esc).join(' · ')}</div>"
        "${(r.risk_flags||[]).length?`<div class='muted'>⚠ ${(r.risk_flags||[]).map(esc).join(', ')}</div>`:''}</div>`;}catch(x){err(eEl,x)}}"
        "async function tdCreate(){try{const p=gv('td-platform');"
        "const r=await api('POST','/topic-decisions/projects/'+PID+'/create',{platform_key:p||null});"
        "msg.textContent='Решение #'+r.id+': '+r.selected_topic+' ('+r.outcome+'). Пост не создан, live нет.';loadTD();}catch(x){err(eEl,x)}}"
        "window.tdPreview=tdPreview;window.tdCreate=tdCreate;window.loadTD=loadTD;"
        "['td-platform','td-status','td-source'].forEach(i=>{const el=document.getElementById(i);if(el)el.addEventListener('change',loadTD);});"
        "loadTD();"
    )
    return _page(
        "Выбор тем по обучению", body, script, active="optimization", active_pid=project_id
    )


@router.get("/projects/{project_id}/topic-decisions/{decision_id}", response_class=HTMLResponse)
def ui_project_topic_decision_detail(project_id: int, decision_id: int) -> HTMLResponse:
    """Детали решения: тема, альтернативы, разбор оценки, причины, риски, связанный пост."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/topic-decisions'>"
        "<button class='sec mini'>← Решения</button></a></div>"
        "<h2>Почему бот выбрал эту тему</h2>"
        "<div class='callout warn'>Решение влияет только на draft/needs_review — live-публикаций нет.</div>"
        "<div id='td-detail' class='muted'>Загрузка…</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const DID={decision_id};const eEl=document.getElementById('error');"
        "async function load(){try{const d=await api('GET','/topic-decisions/'+DID);"
        "const alts=(d.alternatives||[]).map(a=>`<div class='sched-task'>${esc(''+a.topic)} · ${Math.round((a.confidence_score||0)*100)}% (${esc(''+a.decision_source)})</div>`).join('')||'<span class=muted>нет</span>';"
        "const reasons=(d.reasons||[]).map(r=>`<li>${esc(r)}</li>`).join('');"
        "const risks=(d.risk_flags||[]).map(esc).join(', ')||'—';"
        "const sig=(d.source_signals||[]).map(esc).join(', ')||'—';"
        "document.getElementById('td-detail').classList.remove('muted');"
        "document.getElementById('td-detail').innerHTML=`"
        "<div class='card'><div class='inline'><span class='pill'>${esc(d.decision_source)}</span> <b>${esc(''+d.selected_topic)}</b> "
        "<span class='muted'>${Math.round(d.confidence_score*100)}% · ${esc(d.status)}</span></div>"
        "<div class='muted'>CTA: ${esc(''+(d.selected_cta||'—'))} · формат: ${esc(''+(d.selected_format||'—'))} · "
        "медиа: ${esc(''+(d.selected_media_strategy||'—'))} · время: ${esc(''+(d.selected_publish_time||'—'))}</div>"
        "<div class='muted'>Ожидаемое качество: ${d.expected_quality_score??'—'} · вовлечённость: ${d.expected_engagement_score??'—'} · "
        "версия профиля: ${d.learning_profile_version??'—'}</div></div>"
        "<div class='card'><h3>Причины</h3><ul>${reasons}</ul></div>"
        "<div class='card'><h3>Риски</h3><div class='muted'>${risks}</div></div>"
        "<div class='card'><h3>Сигналы источников</h3><div class='muted'>${sig}</div></div>"
        "<div class='card'><h3>Альтернативы</h3>${alts}</div>"
        "<div class='card'><h3>Связанный прогон/пост</h3><div class='muted'>run: ${d.schedule_run_id??'—'} · план: ${d.publishing_plan_id??'—'}</div>"
        "<div class='inline' style='margin-top:8px'><button class='mini sec' onclick='applyDry()'>Показать влияние на draft</button></div>"
        "<div id='td-apply' class='muted'></div></div>`;}catch(x){err(eEl,x)}}"
        "async function applyDry(){try{const r=await api('POST','/topic-decisions/'+DID+'/apply-dry',{});"
        "document.getElementById('td-apply').textContent='generation_notes: '+JSON.stringify(r.draft_payload.generation_notes);}catch(x){err(eEl,x)}}"
        "window.applyDry=applyDry;load();"
    )
    return _page("Решение о теме", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/media-decisions", response_class=HTMLResponse)
def ui_project_media_decisions(project_id: int) -> HTMLResponse:
    """Выбор медиа по обучению: решения worker-а «почему бот выбрал эти медиа»."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/optimization'>"
        "<button class='sec mini'>← Оптимизация</button></a>"
        f"<a href='/ui/projects/{project_id}/topic-decisions'><button class='ghost mini'>Выбор тем</button></a>"
        f"<a href='/ui/projects/{project_id}/automation'><button class='ghost mini'>Автоматизация</button></a>"
        f"<a href='/ui/review'><button class='ghost mini'>Очередь ревью</button></a>"
        f"<a href='/ui/projects/{project_id}/media-proxy'><button class='ghost mini'>Media proxy</button></a></div>"
        "<h2>Выбор медиа по обучению</h2>"
        "<div class='callout warn'><b>Решение создаёт draft/needs_review, live не выполняется.</b> "
        "Автовыбор worker-ом выключен по умолчанию; публичные ссылки автоматически не создаются; "
        "при низкой уверенности пост уходит в ревью. <b>Instagram требует public image_url.</b> "
        "Обучение строго по проекту.</div>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='md-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Статус</label><select id='md-status'>"
        "<option value=''>Любой</option><option value='selected'>selected</option>"
        "<option value='applied_to_draft'>applied_to_draft</option><option value='preview'>preview</option>"
        "<option value='skipped'>skipped</option><option value='failed'>failed</option>"
        "</select></div>"
        "<div><label>Стратегия</label><select id='md-strategy'>"
        "<option value=''>Любая</option><option value='text_only'>text_only</option>"
        "<option value='single_image'>single_image</option><option value='media_group'>media_group</option>"
        "<option value='carousel_ready'>carousel_ready</option><option value='video_later'>video_later</option>"
        "<option value='no_media_available'>no_media_available</option>"
        "</select></div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='mdPreview()'>Preview следующего медиа</button>"
        "<button class='mini' onclick='mdCreate()'>Создать решение</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Всего</div><div id='md-total' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Низкая уверенность</div><div id='md-low' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Без медиа</div><div id='md-nomedia' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Средняя уверенность</div><div id='md-conf' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Автовыбор worker</div><div id='md-worker' class='an-big'>—</div></div>"
        "</div>"
        "<div id='md-preview' class='muted'></div>"
        "<div class='card'><h3>Решения</h3><div id='md-list' class='muted'>Загрузка…</div></div>"
        "<div id='md-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('md-msg');"
        "function mdcard(d){"
        "const risks=(d.risk_flags||[]).map(esc).join(', ');"
        "const reasons=(d.reasons||[]).slice(0,3).map(esc).join(' · ');"
        "const tags=(d.selected_media_tags||[]).slice(0,6).map(esc).join(', ');"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(d.decision_source)}</span> "
        "<b>${esc(''+d.selected_strategy)}</b> <span class='muted'>${Math.round(d.confidence_score*100)}% · ${esc(d.status)}</span></div>"
        "<div class='muted'>медиа: ${esc(''+d.selected_media_count)} шт · ${esc(''+(d.platform_key||'—'))} · public url: ${d.needs_public_image_url?'да':'нет'} · proxy: ${d.media_proxy_ready?'готов':'нет'}</div>"
        "${tags?`<div class='muted'>теги: ${tags}</div>`:''}"
        "${reasons?`<div class='muted'>${reasons}</div>`:''}${risks?`<div class='muted'>⚠ ${risks}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>"
        "<a href='/ui/projects/'+PID+'/media-decisions/'+d.id><button class='mini sec'>Почему эти медиа</button></a>"
        "${d.schedule_run_id?`<span class='muted'>run #${d.schedule_run_id}</span>`:''}"
        "${d.schedule_topic_decision_id?`<span class='muted'>тема #${d.schedule_topic_decision_id}</span>`:''}"
        "</div></div>`;}"
        "async function loadMD(){try{const d=await api('GET','/media-decisions/projects/'+PID+'/dashboard');"
        "document.getElementById('md-total').textContent=d.total;"
        "document.getElementById('md-low').textContent=d.low_confidence_count;"
        "document.getElementById('md-nomedia').textContent=d.no_media_count;"
        "document.getElementById('md-conf').textContent=Math.round((d.avg_confidence||0)*100)+'%';"
        "document.getElementById('md-worker').textContent=d.worker_enabled?'вкл':'выкл';"
        "const q=[];const st=gv('md-status');const sr=gv('md-strategy');const pf=gv('md-platform');"
        "if(pf)q.push('platform_key='+pf);if(st)q.push('decision_status='+st);if(sr)q.push('strategy='+sr);"
        "const rows=await api('GET','/media-decisions/projects/'+PID+(q.length?'?'+q.join('&'):''));"
        "const host=document.getElementById('md-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(mdcard).join(''):"
        "\"<div class='muted'>Решений нет — нажмите «Создать решение».</div>\";}catch(x){err(eEl,x)}}"
        "async function mdPreview(){try{const p=gv('md-platform');"
        "const r=await api('POST','/media-decisions/projects/'+PID+'/preview',{platform_key:p||null});"
        "document.getElementById('md-preview').innerHTML=`<div class='card'><b>Preview:</b> ${esc(''+r.selected_strategy)} "
        "(${Math.round((r.confidence_score||0)*100)}%, ${esc(r.decision_source)}, медиа: ${esc(''+r.selected_media_count)})"
        "<div class='muted'>${(r.reasons||[]).slice(0,3).map(esc).join(' · ')}</div>"
        "${(r.risk_flags||[]).length?`<div class='muted'>⚠ ${(r.risk_flags||[]).map(esc).join(', ')}</div>`:''}</div>`;}catch(x){err(eEl,x)}}"
        "async function mdCreate(){try{const p=gv('md-platform');"
        "const r=await api('POST','/media-decisions/projects/'+PID+'/create',{platform_key:p||null});"
        "msg.textContent='Решение #'+r.id+': '+r.selected_strategy+' ('+r.outcome+'). Пост не создан, live нет.';loadMD();}catch(x){err(eEl,x)}}"
        "window.mdPreview=mdPreview;window.mdCreate=mdCreate;window.loadMD=loadMD;"
        "['md-platform','md-status','md-strategy'].forEach(i=>{const el=document.getElementById(i);if(el)el.addEventListener('change',loadMD);});"
        "loadMD();"
    )
    return _page(
        "Выбор медиа по обучению", body, script, active="optimization", active_pid=project_id
    )


@router.get("/projects/{project_id}/media-decisions/{decision_id}", response_class=HTMLResponse)
def ui_project_media_decision_detail(project_id: int, decision_id: int) -> HTMLResponse:
    """Детали решения: медиа, альтернативы, причины, риски, сигналы, связанный пост."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-decisions'>"
        "<button class='sec mini'>← Решения</button></a>"
        f"<a href='/ui/projects/{project_id}/media-proxy'><button class='ghost mini'>Media proxy</button></a></div>"
        "<h2>Почему бот выбрал эти медиа</h2>"
        "<div class='callout warn'>Решение влияет только на draft/needs_review — live-публикаций нет; "
        "публичные ссылки автоматически не создаются. Instagram требует public image_url.</div>"
        "<div id='md-detail' class='muted'>Загрузка…</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const DID={decision_id};const eEl=document.getElementById('error');"
        "async function load(){try{const d=await api('GET','/media-decisions/'+DID);"
        "const alts=(d.alternatives||[]).map(a=>`<div class='sched-task'>${esc(''+a.strategy)} · медиа: ${esc(''+(a.media_count??'—'))}</div>`).join('')||'<span class=muted>нет</span>';"
        "const reasons=(d.reasons||[]).map(r=>`<li>${esc(r)}</li>`).join('');"
        "const risks=(d.risk_flags||[]).map(esc).join(', ')||'—';"
        "const sig=(d.source_signals||[]).map(esc).join(', ')||'—';"
        "const tags=(d.selected_media_tags||[]).map(esc).join(', ')||'—';"
        "const ids=(d.selected_media_asset_ids||[]).join(', ')||'—';"
        "const mqs=d.media_quality_summary||{};"
        "const mqIssues=(mqs.common_issues||[]).map(x=>esc(x[0])+' ('+x[1]+')').join(', ')||'—';"
        "const mds=d.media_diversity_summary||{};"
        "const mcs=d.media_curation_summary||{};"
        "document.getElementById('md-detail').classList.remove('muted');"
        "document.getElementById('md-detail').innerHTML=`"
        "<div class='card'><div class='inline'><span class='pill'>${esc(d.decision_source)}</span> <b>${esc(''+d.selected_strategy)}</b> "
        "<span class='muted'>${Math.round(d.confidence_score*100)}% · ${esc(d.status)}</span></div>"
        "<div class='muted'>платформа: ${esc(''+(d.platform_key||'—'))} · медиа: ${esc(''+d.selected_media_count)} шт · "
        "public url: ${d.needs_public_image_url?'да':'нет'} · media proxy: ${d.media_proxy_ready?'готов':'нет'}</div>"
        "<div class='muted'>ожидаемая оценка медиа: ${d.expected_media_score??'—'} · версия профиля: ${d.learning_profile_version??'—'}</div></div>"
        "<div class='card'><h3>Выбранные медиа</h3><div class='muted'>id: ${ids}</div><div class='muted'>теги: ${tags}</div></div>"
        "<div class='card'><h3>Качество выбранных медиа</h3>"
        "<div class='muted'>средний балл: ${mqs.average_selected_score??'—'} · слабых: ${mqs.weak_selected_count??0} · повторов: ${mqs.duplicate_warning_count??0}</div>"
        "<div class='muted'>баллы: ${(mqs.selected_media_scores||[]).join(', ')||'—'}</div>"
        "<div class='muted'>частые проблемы: ${mqIssues}</div>"
        "<div class='inline' style='margin-top:6px'><a href='/ui/projects/'+PID+'/media-quality'><button class='mini sec'>Открыть «Качество медиа»</button></a></div></div>"
        "<div class='card'><h3>Разнообразие подборки (v0.4.7)</h3>"
        "<div class='muted'>diversity_score: ${mds.diversity_score??'—'} · пропущено похожих: ${mds.similar_media_skipped_count??0} · кластеры: ${(mds.duplicate_cluster_ids||[]).join(', ')||'—'}</div>"
        "${(mds.selected_similarity_warnings||[]).length?`<div class='muted'>⚠ ${(mds.selected_similarity_warnings||[]).map(esc).join(' · ')}</div>`:''}"
        "<div class='inline' style='margin-top:6px'><a href='/ui/projects/'+PID+'/media-duplicates'><button class='mini sec'>Открыть «Дубли»</button></a></div></div>"
        "<div class='card'><h3>Курирование (v0.4.8)</h3>"
        "<div class='muted'>скрыто медиа пропущено: ${mcs.hidden_media_skipped_count??0} · ретег-подсказок: ${mcs.retag_suggestions_available??0} · слабые медиа: ${mcs.weak_media_warning?'да':'нет'}</div>"
        "<div class='inline' style='margin-top:6px'><a href='/ui/projects/'+PID+'/media-curation'><button class='mini sec'>Открыть «Курирование»</button></a></div></div>"
        "<div class='card'><h3>Причины</h3><ul>${reasons}</ul></div>"
        "<div class='card'><h3>Риски</h3><div class='muted'>${risks}</div></div>"
        "<div class='card'><h3>Сигналы источников</h3><div class='muted'>${sig}</div></div>"
        "<div class='card'><h3>Альтернативы</h3>${alts}</div>"
        "<div class='card'><h3>Связанный прогон/пост</h3><div class='muted'>run: ${d.schedule_run_id??'—'} · план: ${d.publishing_plan_id??'—'} · тема: ${d.schedule_topic_decision_id??'—'}</div>"
        "<div class='inline' style='margin-top:8px'><button class='mini sec' onclick='applyDry()'>Показать влияние на draft</button></div>"
        "<div id='md-apply' class='muted'></div></div>`;}catch(x){err(eEl,x)}}"
        "async function applyDry(){try{const r=await api('POST','/media-decisions/'+DID+'/apply-dry',{});"
        "document.getElementById('md-apply').textContent='generation_notes: '+JSON.stringify(r.draft_payload.generation_notes);}catch(x){err(eEl,x)}}"
        "window.applyDry=applyDry;load();"
    )
    return _page("Решение о медиа", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/media-quality", response_class=HTMLResponse)
def ui_project_media_quality(project_id: int) -> HTMLResponse:
    """Качество медиа: оценка/дубли/пригодность медиатеки (правило-ориентированно, без AI)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-decisions'>"
        "<button class='sec mini'>← Выбор медиа</button></a>"
        f"<a href='/ui/projects/{project_id}/automation'><button class='ghost mini'>Автоматизация</button></a>"
        f"<a href='/ui/projects/{project_id}/media-fingerprints'><button class='ghost mini'>Fingerprint</button></a>"
        f"<a href='/ui/projects/{project_id}/media-duplicates'><button class='ghost mini'>Дубли</button></a>"
        f"<a href='/ui/projects/{project_id}/media-curation'><button class='ghost mini'>Курирование</button></a>"
        f"<a href='/ui/projects/{project_id}/media-proxy'><button class='ghost mini'>Media proxy</button></a></div>"
        "<h2>Качество медиа</h2>"
        "<div class='callout warn'><b>Оценка правило-ориентированная — без внешнего AI и без "
        "live-публикаций.</b> Показываются баллы, проблемы и повторы; внутренние пути к файлам "
        "не отображаются. Оценка worker-ом выключена по умолчанию.</div>"
        "<div class='card'><div class='an-filters'>"
        "<div><label>Платформа</label><select id='mq-platform'>"
        "<option value=''>Все</option><option value='telegram'>Telegram</option>"
        "<option value='vk'>VK</option><option value='instagram'>Instagram</option></select></div>"
        "<div><label>Статус</label><select id='mq-status'>"
        "<option value=''>Любой</option><option value='excellent'>excellent</option>"
        "<option value='good'>good</option><option value='weak'>weak</option>"
        "<option value='needs_tags'>needs_tags</option><option value='duplicate'>duplicate</option>"
        "<option value='unsupported'>unsupported</option></select></div>"
        "<div><label>Мин. балл</label><input id='mq-minscore' type='number' min='0' max='100' "
        "placeholder='0' style='width:90px'></div></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='mini sec' onclick='mqPreview()'>Preview оценки</button>"
        "<button class='mini' onclick='mqScore()'>Оценить медиатеку</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Всего медиа</div><div id='mq-total' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Оценено</div><div id='mq-scored' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Excellent</div><div id='mq-exc' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Good</div><div id='mq-good' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Weak</div><div id='mq-weak' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Дубли</div><div id='mq-dup' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Средний балл</div><div id='mq-avg' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Частые проблемы</h3><div id='mq-issues' class='muted'>—</div></div>"
        "<div id='mq-msg' class='muted'></div>"
        "<div class='card'><h3>Медиа</h3><div id='mq-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('mq-msg');"
        "function mqcard(d){"
        "const issues=(d.issue_codes||[]).map(esc).join(', ');"
        "const acts=(d.recommended_actions||[]).slice(0,2).map(esc).join(' · ');"
        "return `<div class='card'><div class='inline'><span class='pill ${d.overall_score>=70?'ok':'off'}'>${esc(''+d.status)}</span> "
        "<b>медиа #${esc(''+d.media_asset_id)}</b> <span class='muted'>overall ${esc(''+d.overall_score)}</span></div>"
        "<div class='muted'>качество ${d.quality_score} · релевантность ${d.relevance_score} · свежесть ${d.freshness_score} · уник. ${d.uniqueness_score} · платформа ${d.platform_fit_score}</div>"
        "${issues?`<div class='muted'>⚠ ${issues}</div>`:''}${acts?`<div class='muted'>${acts}</div>`:''}"
        "${d.duplicate_of_media_asset_id?`<div class='muted'>возможный дубль #${esc(''+d.duplicate_of_media_asset_id)}</div>`:''}"
        "</div>`;}"
        "async function loadMQ(){try{const d=await api('GET','/media-quality/projects/'+PID+'/dashboard');"
        "document.getElementById('mq-total').textContent=d.total_media;"
        "document.getElementById('mq-scored').textContent=d.scored;"
        "document.getElementById('mq-exc').textContent=d.excellent;"
        "document.getElementById('mq-good').textContent=d.good;"
        "document.getElementById('mq-weak').textContent=d.weak;"
        "document.getElementById('mq-dup').textContent=d.duplicates;"
        "document.getElementById('mq-avg').textContent=d.avg_score;"
        "document.getElementById('mq-issues').textContent=(d.common_issues||[]).map(x=>x[0]+' ('+x[1]+')').join(', ')||'—';"
        "const q=[];const st=gv('mq-status');const pf=gv('mq-platform');const ms=gv('mq-minscore');"
        "if(pf)q.push('platform_key='+pf);if(st)q.push('snapshot_status='+st);if(ms)q.push('min_score='+ms);"
        "const rows=await api('GET','/media-quality/projects/'+PID+(q.length?'?'+q.join('&'):''));"
        "const host=document.getElementById('mq-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(mqcard).join(''):"
        "\"<div class='muted'>Снимков нет — нажмите «Оценить медиатеку».</div>\";}catch(x){err(eEl,x)}}"
        "async function mqPreview(){try{const p=gv('mq-platform');"
        "const r=await api('POST','/media-quality/projects/'+PID+'/score-preview',{platform_key:p||null,limit:100});"
        "msg.textContent='Preview: оценено '+r.scored+' · excellent '+r.excellent+' · weak '+r.weak+' · дубли '+r.duplicates+' (без записи).';}catch(x){err(eEl,x)}}"
        "async function mqScore(){if(!confirm('Оценить медиатеку и записать снимки? (без внешнего AI, без live)'))return;"
        "try{const p=gv('mq-platform');"
        "const r=await api('POST','/media-quality/projects/'+PID+'/score',{platform_key:p||null,limit:100});"
        "msg.textContent='Снимков создано: '+r.snapshots_created+'. Live-публикаций нет.';loadMQ();}catch(x){err(eEl,x)}}"
        "window.mqPreview=mqPreview;window.mqScore=mqScore;window.loadMQ=loadMQ;"
        "['mq-platform','mq-status','mq-minscore'].forEach(i=>{const el=document.getElementById(i);if(el)el.addEventListener('change',loadMQ);});"
        "loadMQ();"
    )
    return _page("Качество медиа", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/media-fingerprints", response_class=HTMLResponse)
def ui_project_media_fingerprints(project_id: int) -> HTMLResponse:
    """Fingerprint медиа: локальные хэши/сигнатуры для поиска дублей (без внешнего AI)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-quality'>"
        "<button class='sec mini'>← Качество медиа</button></a>"
        f"<a href='/ui/projects/{project_id}/media-duplicates'><button class='ghost mini'>Дубли и похожие</button></a></div>"
        "<h2>Fingerprint медиа</h2>"
        "<div class='callout warn'><b>Локальные fingerprint — без внешнего AI/vision, без сети "
        "по умолчанию, без live-публикаций.</b> Хранятся только хэши/сигнатуры; внутренние пути "
        "к файлам не отображаются. Fingerprint worker-ом выключен по умолчанию.</div>"
        "<div class='card'><div class='inline'>"
        "<button class='mini sec' onclick='fpPreview()'>Preview fingerprints</button>"
        "<button class='mini' onclick='fpCalc()'>Рассчитать fingerprints</button>"
        f"<a href='/ui/projects/{project_id}/media-duplicates'><button class='mini ghost'>Открыть дубли</button></a>"
        "</div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Всего fingerprint</div><div id='fp-total' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Calculated</div><div id='fp-calc' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Partial</div><div id='fp-part' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Unavailable</div><div id='fp-unav' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Failed</div><div id='fp-fail' class='an-big'>—</div></div>"
        "</div>"
        "<div id='fp-msg' class='muted'></div>"
        "<div class='card'><h3>Fingerprint</h3><div id='fp-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('fp-msg');"
        "function fpcard(d){"
        "const ph=d.perceptual_hash?String(d.perceptual_hash).slice(0,12):'—';"
        "const sh=d.file_sha256_prefix?String(d.file_sha256_prefix).slice(0,12):'—';"
        "const ts=(d.tag_signature&&d.tag_signature.signature)?String(d.tag_signature.signature).slice(0,40):'—';"
        "return `<div class='card'><div class='inline'><span class='pill ${d.status==='calculated'?'ok':'off'}'>${esc(''+d.status)}</span> "
        "<b>медиа #${esc(''+d.media_asset_id)}</b> <span class='muted'>источник ${esc(''+d.source)}</span></div>"
        "<div class='muted'>sha256: ${esc(sh)} · perceptual: ${esc(ph)}</div>"
        "<div class='muted'>теги: ${esc(ts)}</div>"
        "${d.calculated_at?`<div class='muted'>рассчитано: ${esc(String(d.calculated_at).replace('T',' ').slice(0,19))}</div>`:''}"
        "</div>`;}"
        "async function loadFP(){try{const rows=await api('GET','/media-fingerprints/projects/'+PID);"
        "const counts={calculated:0,partial:0,unavailable:0,failed:0};"
        "rows.forEach(r=>{if(counts[r.status]!==undefined)counts[r.status]++;});"
        "document.getElementById('fp-total').textContent=rows.length;"
        "document.getElementById('fp-calc').textContent=counts.calculated;"
        "document.getElementById('fp-part').textContent=counts.partial;"
        "document.getElementById('fp-unav').textContent=counts.unavailable;"
        "document.getElementById('fp-fail').textContent=counts.failed;"
        "const host=document.getElementById('fp-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(fpcard).join(''):"
        "\"<div class='muted'>Fingerprint нет — нажмите «Рассчитать fingerprints».</div>\";}catch(x){err(eEl,x)}}"
        "async function fpPreview(){try{const r=await api('POST','/media-fingerprints/projects/'+PID+'/preview',{limit:100});"
        "msg.textContent='Preview: просканировано '+r.scanned+' · calculated '+r.calculated+' · partial '+r.partial+' (без записи).';}catch(x){err(eEl,x)}}"
        "async function fpCalc(){if(!confirm('Рассчитать fingerprint медиатеки? (локально, без внешнего AI/сети)'))return;"
        "try{const r=await api('POST','/media-fingerprints/projects/'+PID+'/calculate',{limit:100,dry_run:false});"
        "msg.textContent='Создано fingerprint: '+r.created+'. Live-публикаций нет.';loadFP();}catch(x){err(eEl,x)}}"
        "window.fpPreview=fpPreview;window.fpCalc=fpCalc;window.loadFP=loadFP;loadFP();"
    )
    return _page("Fingerprint медиа", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/media-duplicates", response_class=HTMLResponse)
def ui_project_media_duplicates(project_id: int) -> HTMLResponse:
    """Дубли и похожие медиа: кластеры по fingerprint (без удаления файлов)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-fingerprints'>"
        "<button class='sec mini'>← Fingerprint</button></a>"
        f"<a href='/ui/projects/{project_id}/media-quality'><button class='ghost mini'>Качество медиа</button></a>"
        f"<a href='/ui/projects/{project_id}/media-curation'><button class='ghost mini'>Открыть курирование</button></a></div>"
        "<h2>Дубли и похожие медиа</h2>"
        "<div class='callout warn'><b>Файлы НЕ удаляются на этом этапе.</b> Кластеры строятся "
        "локально по fingerprint — без внешнего AI, без live-публикаций. Действия: оставить "
        "главное, скрыть дубль, добавить теги, заменить в подборке, объединить серию.</div>"
        "<div class='card'><div class='inline'>"
        "<button class='mini sec' onclick='dupPreview()'>Preview кластеров</button>"
        "<button class='mini' onclick='dupCalc()'>Построить кластеры</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Fingerprint</div><div id='dp-fp' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Точных дублей</div><div id='dp-exact' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Почти-дублей</div><div id='dp-near' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Серий</div><div id='dp-series' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Активных</div><div id='dp-active' class='an-big'>—</div></div>"
        "</div>"
        "<div id='dp-msg' class='muted'></div>"
        "<div class='card'><h3>Кластеры</h3><div id='dp-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('dp-msg');"
        "function dpcard(d){"
        "const reasons=(d.reasons||[]).slice(0,3).map(esc).join(' · ');"
        "const acts=(d.recommended_actions||[]).map(esc).join(', ');"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(''+d.cluster_type)}</span> "
        "<b>similarity ${esc(''+d.similarity_score)}</b> <span class='muted'>${esc(''+d.status)}</span></div>"
        "<div class='muted'>canonical #${esc(''+d.canonical_media_asset_id)} · медиа: ${esc(''+(d.member_media_asset_ids||[]).join(', '))}</div>"
        "${reasons?`<div class='muted'>${reasons}</div>`:''}"
        "<div class='muted'>действия: ${esc(acts)}</div>"
        "${d.id?`<div class='inline' style='margin-top:6px'>`"
        "+`<button class='mini sec' onclick='dupReview(${d.id},\"reviewed\")'>Отметить просмотренным</button>`"
        "+`<button class='mini ghost' onclick='dupReview(${d.id},\"ignored\")'>Игнорировать</button></div>`:''}"
        "</div>`;}"
        "async function loadDup(){try{const d=await api('GET','/media-fingerprints/projects/'+PID+'/dashboard');"
        "document.getElementById('dp-fp').textContent=d.total_fingerprints;"
        "document.getElementById('dp-exact').textContent=d.exact_duplicates;"
        "document.getElementById('dp-near').textContent=d.near_duplicates;"
        "document.getElementById('dp-series').textContent=d.same_series;"
        "document.getElementById('dp-active').textContent=d.active_clusters;"
        "const rows=await api('GET','/media-fingerprints/projects/'+PID+'/duplicates');"
        "const host=document.getElementById('dp-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(dpcard).join(''):"
        "\"<div class='muted'>Кластеров нет — нажмите «Построить кластеры».</div>\";}catch(x){err(eEl,x)}}"
        "async function dupPreview(){try{const r=await api('POST','/media-fingerprints/projects/'+PID+'/duplicates/preview',{});"
        "msg.textContent='Preview: найдено кластеров '+r.clusters_found+' (без записи).';}catch(x){err(eEl,x)}}"
        "async function dupCalc(){if(!confirm('Построить кластеры дублей? (локально, без удаления файлов)'))return;"
        "try{const r=await api('POST','/media-fingerprints/projects/'+PID+'/duplicates/calculate',{dry_run:false});"
        "msg.textContent='Создано кластеров: '+r.clusters_created+'. Файлы не удаляются.';loadDup();}catch(x){err(eEl,x)}}"
        "async function dupReview(cid,action){try{await api('POST','/media-fingerprints/projects/'+PID+'/duplicates/'+cid+'/review',{action:action});"
        "msg.textContent='Кластер #'+cid+': '+action+'.';loadDup();}catch(x){err(eEl,x)}}"
        "window.dupPreview=dupPreview;window.dupCalc=dupCalc;window.dupReview=dupReview;loadDup();"
    )
    return _page(
        "Дубли и похожие медиа", body, script, active="optimization", active_pid=project_id
    )


@router.get("/projects/{project_id}/media-curation", response_class=HTMLResponse)
def ui_project_media_curation(project_id: int) -> HTMLResponse:
    """Очистка и разметка медиатеки: задачи курирования (без удаления файлов, без AI)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-quality'>"
        "<button class='sec mini'>← Качество медиа</button></a>"
        f"<a href='/ui/projects/{project_id}/media-duplicates'><button class='ghost mini'>Дубли</button></a>"
        f"<a href='/ui/projects/{project_id}/media-decisions'><button class='ghost mini'>Выбор медиа</button></a>"
        f"<a href='/ui/projects/{project_id}/media-curation-review'><button class='mini'>Доска ревью медиатеки</button></a></div>"
        "<h2>Очистка и разметка медиатеки</h2>"
        "<div class='callout warn'><b>Файлы НЕ удаляются.</b> Изменения (теги/скрытие) "
        "применяются <b>только после подтверждения</b>. Без внешнего AI; live-публикаций нет. "
        "Скрытые медиа не участвуют в авто-подборе; их можно вернуть.</div>"
        "<div class='card'><div class='inline'>"
        "<button class='mini sec' onclick='curPreview()'>Preview задач</button>"
        "<button class='mini' onclick='curGenerate()'>Сгенерировать задачи</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Активных задач</div><div id='cu-active' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Дубли</div><div id='cu-dup' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Ретег</div><div id='cu-retag' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Слабые</div><div id='cu-weak' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Скрыто</div><div id='cu-hidden' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>В подборе</div><div id='cu-sel' class='an-big'>—</div></div>"
        "</div>"
        "<div id='cu-msg' class='muted'></div>"
        "<div class='card'><h3>Задачи</h3><div id='cu-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('cu-msg');"
        "function cucard(t){"
        "const tags=(t.suggested_tags||[]).slice(0,6).map(esc).join(', ');"
        "const risks=(t.risk_flags||[]).map(esc).join(', ');"
        "const aff=(t.affected_media_asset_ids||[]).join(', ');"
        "let btns=`<a href='/ui/projects/'+PID+'/media-curation/tasks/'+t.id><button class='mini sec'>Открыть</button></a>`;"
        "if(t.task_type==='retag_suggestion'||t.task_type==='missing_tags'){btns+=`<button class='mini' onclick='curApply(${t.id},\"approve_tags\")'>Approve tags</button>`;}"
        "if(t.task_type==='duplicate_review'){btns+=`<button class='mini' onclick='curApply(${t.id},\"mark_duplicate\")'>Mark duplicate</button>`"
        "+`<button class='mini ghost' onclick='curApply(${t.id},\"ignore_cluster\")'>Ignore cluster</button>`;}"
        "if(t.task_type==='weak_media_review'){btns+=`<button class='mini' onclick='curApply(${t.id},\"hide_from_selection\")'>Hide</button>`;}"
        "if(t.media_asset_id){btns+=`<button class='mini ghost' onclick='curRestore(${t.media_asset_id})'>Restore media</button>`;}"
        "btns+=`<button class='mini ghost' onclick='curReject(${t.id})'>Reject</button>`"
        "+`<button class='mini ghost' onclick='curIgnore(${t.id})'>Ignore</button>`;"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(t.task_type)}</span> "
        "<b>${esc(''+t.title)}</b> <span class='muted'>${Math.round(t.confidence_score*100)}% · ${esc(t.status)}</span></div>"
        "<div class='muted'>${esc(''+(t.reason||'—'))}</div>"
        "${t.media_asset_id?`<div class='muted'>медиа #${esc(''+t.media_asset_id)}${t.duplicate_cluster_id?' · кластер #'+t.duplicate_cluster_id:''}</div>`:''}"
        "${tags?`<div class='muted'>теги: ${tags}</div>`:''}${risks?`<div class='muted'>⚠ ${risks}</div>`:''}"
        "${aff?`<div class='muted'>затронуты: ${aff}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>${btns}</div></div>`;}"
        "async function loadCU(){try{const d=await api('GET','/media-curation/projects/'+PID+'/dashboard');"
        "document.getElementById('cu-active').textContent=d.active_tasks;"
        "document.getElementById('cu-dup').textContent=d.duplicate_tasks;"
        "document.getElementById('cu-retag').textContent=d.retag_tasks;"
        "document.getElementById('cu-weak').textContent=d.weak_media_tasks;"
        "document.getElementById('cu-hidden').textContent=d.hidden_media_count;"
        "document.getElementById('cu-sel').textContent=d.selectable_media_count;"
        "const rows=await api('GET','/media-curation/projects/'+PID+'?task_status=proposed');"
        "const host=document.getElementById('cu-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(cucard).join(''):"
        "\"<div class='muted'>Задач нет — нажмите «Сгенерировать задачи».</div>\";}catch(x){err(eEl,x)}}"
        "async function curPreview(){try{const r=await api('POST','/media-curation/projects/'+PID+'/preview',{limit:100});"
        "msg.textContent='Preview: найдено задач '+r.tasks_found+' (без записи).';}catch(x){err(eEl,x)}}"
        "async function curGenerate(){try{const r=await api('POST','/media-curation/projects/'+PID+'/generate',{dry_run:false});"
        "msg.textContent='Создано задач: '+r.tasks_created+'. Файлы не удаляются.';loadCU();}catch(x){err(eEl,x)}}"
        "async function curApply(id,action){try{const r=await api('POST','/media-curation/tasks/'+id+'/apply',{action:action});"
        "msg.textContent='Задача #'+id+': '+(r.outcome||action)+'.';loadCU();}catch(x){err(eEl,x)}}"
        "async function curReject(id){try{await api('POST','/media-curation/tasks/'+id+'/reject',{});msg.textContent='Задача #'+id+' отклонена.';loadCU();}catch(x){err(eEl,x)}}"
        "async function curIgnore(id){try{await api('POST','/media-curation/tasks/'+id+'/ignore',{});msg.textContent='Задача #'+id+' проигнорирована.';loadCU();}catch(x){err(eEl,x)}}"
        "async function curRestore(mid){try{await api('POST','/media-curation/projects/'+PID+'/media-assets/'+mid+'/restore',{});msg.textContent='Медиа #'+mid+' возвращено в подбор.';loadCU();}catch(x){err(eEl,x)}}"
        "window.curPreview=curPreview;window.curGenerate=curGenerate;window.curApply=curApply;"
        "window.curReject=curReject;window.curIgnore=curIgnore;window.curRestore=curRestore;loadCU();"
    )
    return _page(
        "Очистка и разметка медиатеки", body, script, active="optimization", active_pid=project_id
    )


@router.get("/projects/{project_id}/media-curation/tasks/{task_id}", response_class=HTMLResponse)
def ui_project_media_curation_task(project_id: int, task_id: int) -> HTMLResponse:
    """Детали задачи курирования: тип, причина, предложенные теги, затронутые медиа, действия."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-curation'>"
        "<button class='sec mini'>← Задачи</button></a></div>"
        "<h2>Задача курирования</h2>"
        "<div class='callout warn'>Файлы не удаляются; изменения — только после подтверждения; "
        "без внешнего AI.</div>"
        "<div id='cu-detail' class='muted'>Загрузка…</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const TID={task_id};const eEl=document.getElementById('error');"
        "async function load(){try{const t=await api('GET','/media-curation/tasks/'+TID);"
        "const tags=(t.suggested_tags||[]).map(esc).join(', ')||'—';"
        "const prod=(t.suggested_products||[]).map(esc).join(', ')||'—';"
        "const tech=(t.suggested_technologies||[]).map(esc).join(', ')||'—';"
        "const sig=(t.source_signals||[]).map(esc).join(', ')||'—';"
        "const aff=(t.affected_media_asset_ids||[]).join(', ')||'—';"
        "document.getElementById('cu-detail').classList.remove('muted');"
        "document.getElementById('cu-detail').innerHTML=`"
        "<div class='card'><div class='inline'><span class='pill'>${esc(t.task_type)}</span> <b>${esc(''+t.title)}</b> "
        "<span class='muted'>${Math.round(t.confidence_score*100)}% · ${esc(t.status)}</span></div>"
        "<div class='muted'>${esc(''+(t.reason||'—'))}</div>"
        "<div class='muted'>медиа: ${t.media_asset_id??'—'} · кластер: ${t.duplicate_cluster_id??'—'} · снимок: ${t.quality_snapshot_id??'—'}</div></div>"
        "<div class='card'><h3>Предложенные теги</h3><div class='muted'>теги: ${tags}</div>"
        "<div class='muted'>продукты: ${prod} · технологии: ${tech}</div>"
        "<div class='muted'>сигналы: ${sig}</div></div>"
        "<div class='card'><h3>Затронутые медиа</h3><div class='muted'>${aff}</div></div>"
        "<div class='card'><h3>Действия</h3><div class='inline'>"
        "${(t.task_type==='retag_suggestion'||t.task_type==='missing_tags')?`<button class='mini' onclick='act(\"approve_tags\")'>Approve tags</button>`:''}"
        "${t.task_type==='duplicate_review'?`<button class='mini' onclick='act(\"mark_duplicate\")'>Mark duplicate</button><button class='mini ghost' onclick='act(\"keep_canonical\")'>Keep canonical</button><button class='mini ghost' onclick='act(\"ignore_cluster\")'>Ignore cluster</button>`:''}"
        "${t.task_type==='weak_media_review'?`<button class='mini' onclick='act(\"hide_from_selection\")'>Hide</button>`:''}"
        "${t.media_asset_id?`<button class='mini ghost' onclick='restore(${t.media_asset_id})'>Restore media</button>`:''}"
        "<button class='mini ghost' onclick='act(\"mark_reviewed\")'>Mark reviewed</button>"
        "<button class='mini ghost' onclick='rej()'>Reject</button></div>"
        "<div id='cu-act' class='muted'></div></div>`;}catch(x){err(eEl,x)}}"
        "async function act(a){try{const r=await api('POST','/media-curation/tasks/'+TID+'/apply',{action:a});"
        "document.getElementById('cu-act').textContent='Результат: '+(r.outcome||a);load();}catch(x){err(eEl,x)}}"
        "async function rej(){try{await api('POST','/media-curation/tasks/'+TID+'/reject',{});document.getElementById('cu-act').textContent='Отклонено.';load();}catch(x){err(eEl,x)}}"
        "async function restore(mid){try{await api('POST','/media-curation/projects/'+PID+'/media-assets/'+mid+'/restore',{});document.getElementById('cu-act').textContent='Медиа возвращено в подбор.';load();}catch(x){err(eEl,x)}}"
        "window.act=act;window.rej=rej;window.restore=restore;load();"
    )
    return _page("Задача курирования", body, script, active="optimization", active_pid=project_id)


@router.get("/projects/{project_id}/media-curation-review", response_class=HTMLResponse)
def ui_project_media_curation_review(project_id: int) -> HTMLResponse:
    """Доска ревью медиатеки: задачи на проверку, ответственные, приоритеты, статусы, действия."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-curation'>"
        "<button class='sec mini'>← Курирование</button></a>"
        f"<a href='/ui/projects/{project_id}/media-quality'><button class='ghost mini'>Качество</button></a>"
        f"<a href='/ui/projects/{project_id}/media-duplicates'><button class='ghost mini'>Дубли</button></a>"
        f"<a href='/ui/projects/{project_id}/review-workload'><button class='mini'>Нагрузка ревьюеров</button></a>"
        f"<a href='/ui/projects/{project_id}/notifications'><button class='ghost mini'>Уведомления</button></a></div>"
        "<h2>Ревью медиатеки</h2>"
        "<div class='callout warn'><b>Файлы НЕ удаляются.</b> Изменения (теги/скрытие) применяются "
        "<b>только после одобрения (approved)</b>. Без внешнего AI; live-публикаций и реальных "
        "платежей нет.</div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>proposed</div><div id='rb-proposed' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>assigned</div><div id='rb-assigned' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>in_review</div><div id='rb-inreview' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>changes_requested</div><div id='rb-changes' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>approved</div><div id='rb-approved' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>applied</div><div id='rb-applied' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>overdue</div><div id='rb-overdue' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><div class='inline'>"
        "<label>Статус <select id='rb-fstatus' onchange='loadRB()'>"
        "<option value=''>все</option><option>proposed</option><option>assigned</option>"
        "<option>in_review</option><option>changes_requested</option><option>approved</option>"
        "<option>applied</option><option>rejected</option><option>ignored</option></select></label>"
        "<label>Приоритет <select id='rb-fpriority' onchange='loadRB()'>"
        "<option value=''>все</option><option>urgent</option><option>high</option>"
        "<option>normal</option><option>low</option></select></label>"
        "<label>Тип <select id='rb-ftype' onchange='loadRB()'>"
        "<option value=''>все</option><option>duplicate_review</option><option>retag_suggestion</option>"
        "<option>missing_tags</option><option>weak_media_review</option></select></label>"
        "<label><input type='checkbox' id='rb-foverdue' onchange='loadRB()'> только overdue</label>"
        "</div></div>"
        "<div id='rb-msg' class='muted'></div>"
        "<div class='card'><h3>Задачи ревью</h3><div id='rb-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('rb-msg');"
        "function rbcard(t){"
        "const tags=(t.suggested_tags||[]).slice(0,6).map(esc).join(', ');"
        "const due=t.due_at?(' · срок '+esc(t.due_at.slice(0,10))):'';"
        "const asg=t.assignee_user_id?(' · ответств. #'+t.assignee_user_id):'';"
        "const ov=t.is_overdue?\" <span class='pill warn'>overdue</span>\":'';"
        "const act=t.suggested_action||'mark_reviewed';"
        "let btns=`<a href='/ui/projects/'+PID+'/media-curation-review/tasks/'+t.id><button class='mini sec'>Открыть</button></a>`;"
        "btns+=`<button class='mini ghost' onclick='rbAssign(${t.id})'>Assign</button>`"
        "+`<button class='mini ghost' onclick='rbStart(${t.id})'>Start review</button>`"
        "+`<button class='mini' onclick='rbApprove(${t.id})'>Approve</button>`"
        "+`<button class='mini ghost' onclick='rbRequest(${t.id})'>Request changes</button>`"
        "+`<button class='mini ghost' onclick='rbReject(${t.id})'>Reject</button>`;"
        "if(t.review_status==='approved'){btns+=`<button class='mini' onclick='rbApply(${t.id},\"${esc(act)}\")'>Apply approved</button>`;}"
        "btns+=`<button class='mini ghost' onclick='rbIgnore(${t.id})'>Ignore</button>`"
        "+`<button class='mini ghost' onclick='rbRestore(${t.id})'>Restore</button>`;"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(t.task_type)}</span> "
        "<b>${esc(''+t.title)}</b> <span class='pill'>${esc(t.review_status)}</span> "
        "<span class='pill'>prio: ${esc(t.priority)}</span>${ov} "
        "<span class='muted'>${Math.round(t.confidence_score*100)}%${asg}${due}</span></div>"
        "<div class='muted'>${esc(''+(t.reason||'—'))}</div>"
        "${tags?`<div class='muted'>теги: ${tags}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>${btns}</div></div>`;}"
        "function fval(id){return document.getElementById(id).value;}"
        "async function loadRB(){try{"
        "const d=await api('GET','/media-curation-review/projects/'+PID+'/dashboard');"
        "document.getElementById('rb-proposed').textContent=d.proposed;"
        "document.getElementById('rb-assigned').textContent=d.assigned;"
        "document.getElementById('rb-inreview').textContent=d.in_review;"
        "document.getElementById('rb-changes').textContent=d.changes_requested;"
        "document.getElementById('rb-approved').textContent=d.approved;"
        "document.getElementById('rb-applied').textContent=d.applied;"
        "document.getElementById('rb-overdue').textContent=d.overdue;"
        "let qs='?limit=200';const st=fval('rb-fstatus');if(st)qs+='&review_status='+encodeURIComponent(st);"
        "const pr=fval('rb-fpriority');if(pr)qs+='&priority='+encodeURIComponent(pr);"
        "const tp=fval('rb-ftype');if(tp)qs+='&task_type='+encodeURIComponent(tp);"
        "if(document.getElementById('rb-foverdue').checked)qs+='&overdue=true';"
        "const rows=await api('GET','/media-curation-review/projects/'+PID+qs);"
        "const host=document.getElementById('rb-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(rbcard).join(''):"
        "\"<div class='muted'>Задач нет. Сгенерируйте задачи на странице «Курирование».</div>\";}catch(x){err(eEl,x)}}"
        "async function rbAssign(id){const u=prompt('ID пользователя-ответственного:');if(!u)return;"
        "try{await api('POST','/media-curation-review/tasks/'+id+'/assign',{assignee_user_id:parseInt(u,10)});"
        "msg.textContent='Задача #'+id+': назначен ответственный.';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbStart(id){try{await api('POST','/media-curation-review/tasks/'+id+'/start-review',{});"
        "msg.textContent='Задача #'+id+': начата проверка.';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbApprove(id){try{const r=await api('POST','/media-curation-review/tasks/'+id+'/approve',{});"
        "msg.textContent='Задача #'+id+': '+(r.outcome||'approved')+' (apply отдельно).';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbRequest(id){const c=prompt('Что нужно поправить?');if(c===null)return;"
        "try{await api('POST','/media-curation-review/tasks/'+id+'/request-changes',{comment:c});"
        "msg.textContent='Задача #'+id+': запрошены правки.';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbReject(id){try{await api('POST','/media-curation-review/tasks/'+id+'/reject',{});"
        "msg.textContent='Задача #'+id+': отклонена.';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbApply(id,action){try{const r=await api('POST','/media-curation-review/tasks/'+id+'/apply',{action:action});"
        "msg.textContent='Задача #'+id+': '+(r.outcome||action)+'. Файлы не удаляются.';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbIgnore(id){try{await api('POST','/media-curation-review/tasks/'+id+'/ignore',{});"
        "msg.textContent='Задача #'+id+': проигнорирована.';loadRB();}catch(x){err(eEl,x)}}"
        "async function rbRestore(id){try{await api('POST','/media-curation-review/tasks/'+id+'/restore',{});"
        "msg.textContent='Задача #'+id+': медиа возвращено в подбор.';loadRB();}catch(x){err(eEl,x)}}"
        "window.loadRB=loadRB;window.rbAssign=rbAssign;window.rbStart=rbStart;window.rbApprove=rbApprove;"
        "window.rbRequest=rbRequest;window.rbReject=rbReject;window.rbApply=rbApply;window.rbIgnore=rbIgnore;"
        "window.rbRestore=rbRestore;loadRB();"
    )
    return _page("Ревью медиатеки", body, script, active="optimization", active_pid=project_id)


@router.get(
    "/projects/{project_id}/media-curation-review/tasks/{task_id}", response_class=HTMLResponse
)
def ui_project_media_curation_review_task(project_id: int, task_id: int) -> HTMLResponse:
    """Детали задачи ревью: данные, before/after, комментарии, timeline, действия."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/media-curation-review'>"
        "<button class='sec mini'>← Доска ревью</button></a></div>"
        "<h2>Задача ревью медиатеки</h2>"
        "<div class='callout warn'>Файлы не удаляются; изменения — только после approved; без "
        "внешнего AI.</div>"
        "<div id='rt-detail' class='muted'>Загрузка…</div>"
        "<div class='card'><h3>Комментарии</h3><div id='rt-comments' class='muted'>—</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<input id='rt-comment' placeholder='Комментарий (без секретов/путей)' style='width:60%'>"
        "<button class='mini' onclick='rtComment()'>Добавить комментарий</button></div></div>"
        "<div class='card'><h3>История решений (timeline)</h3><div id='rt-timeline' class='muted'>—</div></div>"
        "<div id='rt-act' class='muted'></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const TID={task_id};const eEl=document.getElementById('error');"
        "function stateRows(st){const m=(st&&st.media)||{};const ks=Object.keys(m);"
        "if(!ks.length)return '—';return ks.map(k=>`#${esc(k)}: ${esc(m[k].selection_visibility||'')}`).join(' · ');}"
        "async function load(){try{const d=await api('GET','/media-curation-review/tasks/'+TID);"
        "const t=d.task;const tags=(t.suggested_tags||[]).map(esc).join(', ')||'—';"
        "document.getElementById('rt-detail').classList.remove('muted');"
        "document.getElementById('rt-detail').innerHTML=`"
        "<div class='card'><div class='inline'><span class='pill'>${esc(t.task_type)}</span> <b>${esc(''+t.title)}</b> "
        "<span class='pill'>${esc(t.review_status)}</span> <span class='pill'>prio: ${esc(t.priority)}</span> "
        "<span class='muted'>${Math.round(t.confidence_score*100)}%</span></div>"
        "<div class='muted'>${esc(''+(t.reason||'—'))}</div>"
        "<div class='muted'>ответственный: ${t.assignee_user_id??'—'} · reviewer: ${t.reviewer_user_id??'—'} · "
        "срок: ${t.due_at?esc(t.due_at.slice(0,10)):'—'}${d.is_overdue?' · <b>overdue</b>':''}</div>"
        "<div class='muted'>предложенные теги: ${tags} · действие: ${esc(''+(d.suggested_action||'—'))}</div></div>"
        "<div class='card'><h3>До / после</h3>"
        "<div class='muted'>до: ${stateRows(d.before_state)}</div>"
        "<div class='muted'>после: ${stateRows(d.after_state)}</div></div>"
        "<div class='card'><h3>Действия</h3><div class='inline'>"
        "<button class='mini ghost' onclick='rtAssign()'>Assign</button>"
        "<button class='mini ghost' onclick='rtAct(\"start-review\",{})'>Start review</button>"
        "<button class='mini' onclick='rtAct(\"approve\",{})'>Approve</button>"
        "<button class='mini ghost' onclick='rtReq()'>Request changes</button>"
        "<button class='mini ghost' onclick='rtAct(\"reject\",{})'>Reject</button>"
        "${t.review_status==='approved'?`<button class='mini' onclick='rtApply(\"${esc(t.suggested_action||\"mark_reviewed\")}\")'>Apply approved</button>`:''}"
        "<button class='mini ghost' onclick='rtAct(\"ignore\",{})'>Ignore</button>"
        "<button class='mini ghost' onclick='rtAct(\"restore\",{})'>Restore</button></div>"
        "<div class='muted' style='margin-top:6px'>Файлы не удаляются; apply — только после approved.</div></div>`;"
        "const cs=d.comments||[];const ch=document.getElementById('rt-comments');ch.classList.remove('muted');"
        "ch.innerHTML=cs.length?cs.map(c=>`<div class='sched-task'><span class='pill'>${esc(c.comment_type)}</span> "
        "${esc(''+(c.comment_text||''))} <span class='muted'>${c.user_id?('#'+c.user_id):'система'} · ${c.created_at?esc(c.created_at.slice(0,16)):''}</span></div>`).join(''):"
        "\"<div class='muted'>Комментариев нет.</div>\";"
        "const tl=d.timeline||[];const th=document.getElementById('rt-timeline');th.classList.remove('muted');"
        "th.innerHTML=tl.length?tl.map(e=>`<div class='sched-task'><span class='pill'>${esc(e.kind)}</span> "
        "<span class='muted'>${e.at?esc(e.at.slice(0,16)):''} ${e.user_id?('· #'+e.user_id):''}</span>"
        "${e.comment_text?(' — '+esc(''+e.comment_text)):''}</div>`).join(''):'—';"
        "}catch(x){err(eEl,x)}}"
        "async function rtAct(path,body){try{const r=await api('POST','/media-curation-review/tasks/'+TID+'/'+path,body);"
        "document.getElementById('rt-act').textContent='Результат: '+(r.outcome||path);load();}catch(x){err(eEl,x)}}"
        "async function rtApply(action){try{const r=await api('POST','/media-curation-review/tasks/'+TID+'/apply',{action:action});"
        "document.getElementById('rt-act').textContent='Применение: '+(r.outcome||action)+' (файлы не удаляются).';load();}catch(x){err(eEl,x)}}"
        "async function rtAssign(){const u=prompt('ID пользователя-ответственного:');if(!u)return;"
        "rtAct('assign',{assignee_user_id:parseInt(u,10)});}"
        "async function rtReq(){const c=prompt('Что нужно поправить?');if(c===null)return;rtAct('request-changes',{comment:c});}"
        "async function rtComment(){const el=document.getElementById('rt-comment');const v=el.value.trim();if(!v)return;"
        "try{await api('POST','/media-curation-review/tasks/'+TID+'/comments',{comment_text:v});el.value='';load();}catch(x){err(eEl,x)}}"
        "window.rtAct=rtAct;window.rtApply=rtApply;window.rtAssign=rtAssign;window.rtReq=rtReq;window.rtComment=rtComment;load();"
    )
    return _page(
        "Задача ревью медиатеки", body, script, active="optimization", active_pid=project_id
    )


@router.get("/notifications", response_class=HTMLResponse)
def ui_notifications() -> HTMLResponse:
    """Inbox уведомлений пользователя: фильтры, карточки, прочитать/скрыть."""
    body = (
        "<div class='inline'><a href='/ui/notification-delivery'><button class='ghost mini'>Доставка</button></a>"
        "<a href='/ui/notification-digests'><button class='ghost mini'>Дайджесты</button></a></div>"
        "<h2>Уведомления</h2>"
        "<div class='callout'>Внутренние (in-app) уведомления. Внешней доставки (email/SMS/"
        "push) нет — она выключена по умолчанию.</div>"
        "<div class='card'><div class='inline'>"
        "<label>Показать <select id='nf-status' onchange='loadNotif()'>"
        "<option value='unread'>непрочитанные</option><option value=''>все</option>"
        "<option value='read'>прочитанные</option></select></label>"
        "<label>Тип <select id='nf-type' onchange='loadNotif()'>"
        "<option value=''>все</option><option>review_assigned</option><option>review_mentioned</option>"
        "<option>review_comment</option><option>review_approved</option><option>review_rejected</option>"
        "<option>task_overdue</option><option>post_needs_review</option>"
        "<option>experiment_suggestion_created</option><option>experiment_winner_selected</option>"
        "<option>learning_profile_updated</option></select></label>"
        "<label>Приоритет <select id='nf-priority' onchange='loadNotif()'>"
        "<option value=''>все</option><option>urgent</option><option>high</option>"
        "<option>normal</option><option>low</option></select></label>"
        "<button class='mini sec' onclick='readAll()'>Прочитать все</button></div></div>"
        "<div id='nf-summary' class='muted'></div>"
        "<div class='card'><div id='nf-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "function fv(id){return document.getElementById(id).value;}"
        "function nfcard(n){"
        "const url=n.action_url?`<a href='${esc(n.action_url)}'><button class='mini sec'>Открыть</button></a>`:'';"
        "const rd=n.status==='unread'?`<button class='mini' onclick='markRead(${n.id})'>Прочитано</button>`:'';"
        "return `<div class='card'><div class='inline'><span class='pill'>${esc(n.notification_type)}</span> "
        "<b>${esc(''+n.title)}</b> <span class='pill'>${esc(n.priority)}</span> "
        "<span class='muted'>${esc(n.status)} · ${n.created_at?esc(n.created_at.slice(0,16)):''}</span></div>"
        "<div class='muted'>${esc(''+(n.message||''))}</div>"
        "${n.entity_type?`<div class='muted'>${esc(n.entity_type)} #${esc(''+(n.entity_id||''))}</div>`:''}"
        "<div class='inline' style='margin-top:8px'>${url}${rd}"
        "<button class='mini ghost' onclick='dismissN(${n.id})'>Скрыть</button></div></div>`;}"
        "async function loadNotif(){try{"
        "let qs='?limit=100';const st=fv('nf-status');if(st)qs+='&status_filter='+encodeURIComponent(st);"
        "const tp=fv('nf-type');if(tp)qs+='&notification_type='+encodeURIComponent(tp);"
        "const pr=fv('nf-priority');if(pr)qs+='&priority='+encodeURIComponent(pr);"
        "const d=await api('GET','/notifications'+qs);"
        "document.getElementById('nf-summary').textContent='Непрочитанных: '+d.unread_count+' · показано: '+d.count;"
        "const host=document.getElementById('nf-list');host.classList.remove('muted');"
        "host.innerHTML=d.notifications.length?d.notifications.map(nfcard).join(''):"
        "\"<div class='muted'>Уведомлений нет.</div>\";}catch(x){err(eEl,x)}}"
        "async function markRead(id){try{await api('POST','/notifications/'+id+'/read',{});loadNotif();}catch(x){err(eEl,x)}}"
        "async function dismissN(id){try{await api('POST','/notifications/'+id+'/dismiss',{});loadNotif();}catch(x){err(eEl,x)}}"
        "async function readAll(){try{await api('POST','/notifications/read-all',{});loadNotif();}catch(x){err(eEl,x)}}"
        "window.loadNotif=loadNotif;window.markRead=markRead;window.dismissN=dismissN;window.readAll=readAll;loadNotif();"
    )
    return _page("Уведомления", body, script, active="notifications")


@router.get("/projects/{project_id}/notifications", response_class=HTMLResponse)
def ui_project_notifications(project_id: int) -> HTMLResponse:
    """Дашборд уведомлений проекта: непрочитанные, overdue, high/urgent, по типу."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К проекту</button></a>"
        f"<a href='/ui/projects/{project_id}/review-workload'><button class='ghost mini'>Нагрузка ревьюеров</button></a>"
        f"<a href='/ui/projects/{project_id}/notification-delivery'><button class='ghost mini'>Доставка</button></a>"
        f"<a href='/ui/projects/{project_id}/media-curation-review'><button class='ghost mini'>Ревью медиатеки</button></a></div>"
        "<h2>Уведомления проекта</h2>"
        "<div class='callout'>Только внутренние уведомления. Внешней доставки нет.</div>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Непрочитанные</div><div id='pn-unread' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Overdue</div><div id='pn-overdue' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>High/Urgent</div><div id='pn-high' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Всего</div><div id='pn-total' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>По типам</h3><div id='pn-types' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function load(){try{const d=await api('GET','/notifications/projects/'+PID+'/dashboard');"
        "document.getElementById('pn-unread').textContent=d.unread;"
        "document.getElementById('pn-overdue').textContent=d.overdue;"
        "document.getElementById('pn-high').textContent=d.high_priority;"
        "document.getElementById('pn-total').textContent=d.total;"
        "const t=document.getElementById('pn-types');t.classList.remove('muted');"
        "const es=Object.entries(d.by_type||{});"
        "t.innerHTML=es.length?es.map(([k,v])=>`<div class='sched-task'><span class='pill'>${esc(k)}</span> ${v}</div>`).join(''):"
        "\"<div class='muted'>Уведомлений нет.</div>\";}catch(x){err(eEl,x)}}"
        "load();"
    )
    return _page("Уведомления проекта", body, script, active="notifications", active_pid=project_id)


@router.get("/projects/{project_id}/review-workload", response_class=HTMLResponse)
def ui_project_review_workload(project_id: int) -> HTMLResponse:
    """Нагрузка ревьюеров: задачи, overdue, high/urgent, средний возраст, SLA."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/notifications'>"
        "<button class='sec mini'>← Уведомления проекта</button></a>"
        f"<a href='/ui/projects/{project_id}/media-curation-review'><button class='ghost mini'>Ревью медиатеки</button></a></div>"
        "<h2>Нагрузка ревьюеров</h2>"
        "<div class='callout'>Нагрузка по задачам ревью медиатеки. SLA — из настроек (часы). "
        "Внешней доставки уведомлений нет.</div>"
        "<div id='rw-meta' class='muted'></div>"
        "<div class='card'><div id='rw-table' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "function slaPill(s){const cls=(s==='overdue'||s==='critical')?'warn':(s==='due_soon'?'':'ok');"
        "return `<span class='pill ${cls}'>${esc(s)}</span>`;}"
        "async function load(){try{const d=await api('GET','/notifications/projects/'+PID+'/workload');"
        "document.getElementById('rw-meta').textContent='SLA: '+(d.sla_hours||'—')+' ч · без назначения (активные): '+(d.unassigned_active||0);"
        "const host=document.getElementById('rw-table');host.classList.remove('muted');"
        "if(!d.reviewers.length){host.innerHTML=\"<div class='muted'>Назначенных ревьюеров нет.</div>\";return;}"
        "host.innerHTML=`<table class='tbl'><thead><tr><th>Ревьюер</th><th>Задач</th><th>Overdue</th>"
        "<th>High/Urgent</th><th>Ср. возраст, ч</th><th>SLA</th></tr></thead><tbody>`+"
        "d.reviewers.map(r=>`<tr><td>#${r.reviewer_user_id}</td><td>${r.assigned_count}</td>"
        "<td>${r.overdue_count}</td><td>${r.high_priority_count}</td><td>${r.avg_age_hours}</td>"
        "<td>${slaPill(r.sla_status)}</td></tr>`).join('')+'</tbody></table>';}catch(x){err(eEl,x)}}"
        "load();"
    )
    return _page("Нагрузка ревьюеров", body, script, active="notifications", active_pid=project_id)


_DELIVERY_BANNER = (
    "<div class='callout warn'><b>Внешняя доставка выключена.</b> Сейчас работает только "
    "in-app / sandbox: email/Telegram/webhook используют mock-провайдеры и НИЧЕГО не отправляют "
    "наружу. Реальная доставка требует отдельных флагов и включается осознанно.</div>"
)


@router.get("/notification-delivery", response_class=HTMLResponse)
def ui_notification_delivery() -> HTMLResponse:
    """Доставка уведомлений (sandbox): статусы, каналы, логи, preview/send-dry/retry-dry."""
    body = (
        "<div class='inline'><a href='/ui/notifications'><button class='sec mini'>← Уведомления</button></a>"
        "<a href='/ui/notification-digests'><button class='ghost mini'>Дайджесты</button></a>"
        "<a href='/ui/notification-safety'><button class='ghost mini'>Безопасность</button></a>"
        "<a href='/ui/email-templates'><button class='ghost mini'>Email-шаблоны</button></a>"
        "<a href='/ui/notification-telegram'><button class='ghost mini'>Telegram</button></a></div>"
        "<h2>Доставка уведомлений</h2>"
        "<div class='muted'>Email-провайдер: mock/sandbox (SMTP live выключен). "
        "<a href='/ui/email-templates'>Preview email-шаблонов →</a></div>"
        "<div class='muted'>Telegram-провайдер: mock/sandbox (live выключен; нужна verified "
        "привязка). <a href='/ui/notification-telegram'>Telegram-уведомления →</a></div>"
        f"{_DELIVERY_BANNER}"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>pending</div><div id='dl-pending' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>sent</div><div id='dl-sent' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>failed</div><div id='dl-failed' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>skipped</div><div id='dl-skipped' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>disabled</div><div id='dl-disabled' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Каналы</h3><div class='inline'>"
        "<span class='pill'>Email: mock / disabled</span>"
        "<span class='pill'>Telegram: mock / disabled</span>"
        "<span class='pill'>Webhook: mock / disabled</span>"
        "<span class='pill'>Digest: disabled</span></div>"
        "<div class='muted' style='margin-top:6px'>Провайдеры sandbox: реальная отправка не выполняется.</div></div>"
        "<div class='card'><h3>Тест доставки (sandbox)</h3>"
        "<div class='inline'>"
        "<input id='dl-nid' placeholder='notification_id' style='width:150px'>"
        "<select id='dl-channel'><option>email</option><option>telegram</option><option>webhook</option></select>"
        "<button class='mini sec' onclick='dlPreview()'>Preview delivery</button>"
        "<button class='mini' onclick='dlSendDry()'>Send dry-run</button></div>"
        "<div id='dl-testout' class='muted'></div></div>"
        "<div id='dl-msg' class='muted'></div>"
        "<div class='card'><h3>Логи доставки</h3><div id='dl-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');const msg=document.getElementById('dl-msg');"
        "function dlrow(l){return `<div class='sched-task'><span class='pill'>${esc(l.channel)}</span> "
        "<span class='pill'>${esc(l.provider)}</span> <b>${esc(l.status)}</b> "
        "<span class='muted'>${esc(l.destination_masked||'')} · попыток ${l.attempts}"
        "${l.error_message?' · '+esc(l.error_message):''} · ${l.created_at?esc(l.created_at.slice(0,16)):''}</span> "
        "<button class='mini ghost' onclick='dlRetry(${l.id})'>Retry dry-run</button></div>`;}"
        "async function loadDL(){try{const logs=await api('GET','/notification-delivery/logs?limit=100');"
        "const cnt={pending:0,sent:0,failed:0,skipped:0,disabled:0};logs.forEach(l=>{if(cnt[l.status]!=null)cnt[l.status]++;});"
        "document.getElementById('dl-pending').textContent=cnt.pending;"
        "document.getElementById('dl-sent').textContent=cnt.sent;"
        "document.getElementById('dl-failed').textContent=cnt.failed;"
        "document.getElementById('dl-skipped').textContent=cnt.skipped;"
        "document.getElementById('dl-disabled').textContent=cnt.disabled;"
        "const host=document.getElementById('dl-list');host.classList.remove('muted');"
        "host.innerHTML=logs.length?logs.map(dlrow).join(''):\"<div class='muted'>Логов доставки нет.</div>\";}catch(x){err(eEl,x)}}"
        "function nid(){return parseInt(document.getElementById('dl-nid').value,10);}"
        "async function dlPreview(){const id=nid();if(!id)return;try{const ch=document.getElementById('dl-channel').value;"
        "const r=await api('POST','/notification-delivery/notifications/'+id+'/preview',{channels:[ch]});"
        "const pv=r.previews[0];document.getElementById('dl-testout').textContent='Провайдер '+pv.provider+' · '+pv.destination_masked+' · внешняя доставка: '+(pv.external_delivery_enabled?'вкл':'выкл');}catch(x){err(eEl,x)}}"
        "async function dlSendDry(){const id=nid();if(!id)return;try{const ch=document.getElementById('dl-channel').value;"
        "const r=await api('POST','/notification-delivery/notifications/'+id+'/send-dry',{channels:[ch]});"
        "msg.textContent='Dry-run: '+(r.results[0]?r.results[0].outcome:'—')+' (без внешней отправки).';loadDL();}catch(x){err(eEl,x)}}"
        "async function dlRetry(id){try{const r=await api('POST','/notification-delivery/logs/'+id+'/retry-dry',{});"
        "msg.textContent='Retry dry-run #'+id+': '+(r.outcome||'—');loadDL();}catch(x){err(eEl,x)}}"
        "window.dlPreview=dlPreview;window.dlSendDry=dlSendDry;window.dlRetry=dlRetry;loadDL();"
    )
    return _page("Доставка уведомлений", body, script, active="notifications")


@router.get("/projects/{project_id}/notification-delivery", response_class=HTMLResponse)
def ui_project_notification_delivery(project_id: int) -> HTMLResponse:
    """Дашборд доставки проекта: статусы/каналы/провайдеры (sandbox)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/notifications'>"
        "<button class='sec mini'>← Уведомления проекта</button></a>"
        "<a href='/ui/notification-delivery'><button class='ghost mini'>Моя доставка</button></a></div>"
        "<h2>Доставка уведомлений проекта</h2>"
        f"{_DELIVERY_BANNER}"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Всего</div><div id='pd-total' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>sent</div><div id='pd-sent' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>failed</div><div id='pd-failed' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>disabled</div><div id='pd-disabled' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>По каналам</h3><div id='pd-channels' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function load(){try{const d=await api('GET','/notification-delivery/projects/'+PID+'/dashboard');"
        "document.getElementById('pd-total').textContent=d.total;"
        "document.getElementById('pd-sent').textContent=d.sent;"
        "document.getElementById('pd-failed').textContent=d.failed;"
        "document.getElementById('pd-disabled').textContent=d.disabled;"
        "const ch=document.getElementById('pd-channels');ch.classList.remove('muted');"
        "const es=Object.entries(d.by_channel||{});"
        "ch.innerHTML=es.length?es.map(([k,v])=>`<div class='sched-task'><span class='pill'>${esc(k)}</span> ${v}</div>`).join(''):"
        "\"<div class='muted'>Доставок нет.</div>\";}catch(x){err(eEl,x)}}load();"
    )
    return _page(
        "Доставка уведомлений проекта", body, script, active="notifications", active_pid=project_id
    )


@router.get("/notification-digests", response_class=HTMLResponse)
def ui_notification_digests() -> HTMLResponse:
    """Дайджесты уведомлений: preview daily/weekly, список, generate dry-run."""
    body = (
        "<div class='inline'><a href='/ui/notification-delivery'>"
        "<button class='sec mini'>← Доставка</button></a>"
        "<a href='/ui/email-templates'><button class='ghost mini'>Email-шаблоны</button></a></div>"
        "<h2>Дайджесты уведомлений</h2>"
        "<div class='callout warn'><b>Внешняя доставка выключена.</b> Дайджест можно "
        "сгенерировать и посмотреть, но наружу он не отправляется (email выключен). "
        "Email-предпросмотр дайджеста: <a href='/ui/email-templates'>Email-шаблоны →</a></div>"
        "<div class='card'><div class='inline'>"
        "<label>Частота <select id='dg-freq'><option>daily</option><option>weekly</option></select></label>"
        "<button class='mini sec' onclick='dgPreview()'>Preview</button>"
        "<button class='mini ghost' onclick='dgGenDry()'>Generate dry-run</button></div>"
        "<div id='dg-preview' class='muted' style='margin-top:8px'></div></div>"
        "<div id='dg-msg' class='muted'></div>"
        "<div class='card'><h3>Недавние дайджесты</h3><div id='dg-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');const msg=document.getElementById('dg-msg');"
        "function freq(){return document.getElementById('dg-freq').value;}"
        "async function dgPreview(){try{const r=await api('POST','/notification-digests/preview',{frequency:freq()});"
        "document.getElementById('dg-preview').innerHTML=`<b>${esc(r.subject)}</b><br>уведомлений: ${r.notification_count} · "
        "дайджесты: ${r.digest_enabled?'вкл':'выкл'} · внешняя доставка: ${r.external_delivery_enabled?'вкл':'выкл'}"
        "<pre style='white-space:pre-wrap'>${esc(r.body_preview)}</pre>`;}catch(x){err(eEl,x)}}"
        "async function dgGenDry(){try{const r=await api('POST','/notification-digests/generate-dry',{frequency:freq()});"
        "msg.textContent='Dry-run: уведомлений '+r.notification_count+' (без записи).';}catch(x){err(eEl,x)}}"
        "async function loadDG(){try{const rows=await api('GET','/notification-digests');"
        "const host=document.getElementById('dg-list');host.classList.remove('muted');"
        "host.innerHTML=rows.length?rows.map(d=>`<div class='sched-task'><span class='pill'>${esc(d.frequency)}</span> "
        "<b>${esc(d.status)}</b> <span class='muted'>${esc(d.subject)} · ${d.notification_count} · ${d.created_at?esc(d.created_at.slice(0,16)):''}</span></div>`).join(''):"
        "\"<div class='muted'>Дайджестов нет.</div>\";}catch(x){err(eEl,x)}}"
        "window.dgPreview=dgPreview;window.dgGenDry=dgGenDry;loadDG();"
    )
    return _page("Дайджесты уведомлений", body, script, active="notifications")


_SAFETY_BANNER = (
    "<div class='callout warn'><b>Внешняя доставка выключена.</b> Настройки безопасности "
    "(отписки, лимиты, подавление, webhook) применятся, когда доставка будет включена. Реальный "
    "webhook выключен; секреты хранятся зашифрованно и наружу не отдаются.</div>"
)


@router.get("/notification-safety", response_class=HTMLResponse)
def ui_notification_safety() -> HTMLResponse:
    """Безопасность уведомлений: отписки, лимиты, подавление (для текущего пользователя)."""
    body = (
        "<div class='inline'><a href='/ui/notifications'><button class='sec mini'>← Уведомления</button></a>"
        "<a href='/ui/notification-preferences'><button class='ghost mini'>Настройки</button></a>"
        "<a href='/ui/notification-delivery'><button class='ghost mini'>Доставка</button></a></div>"
        "<h2>Безопасность уведомлений</h2>"
        f"{_SAFETY_BANNER}"
        "<div class='card'><h3>Отписки (opt-out)</h3>"
        "<div class='inline'>"
        "<select id='oo-scope'><option value='channel'>канал</option><option value='global'>всё</option>"
        "<option value='notification_type'>тип</option></select>"
        "<select id='oo-channel'><option>email</option><option>telegram</option><option>webhook</option><option>digest</option></select>"
        "<button class='mini' onclick='ooCreate()'>Отписаться</button></div>"
        "<div id='oo-list' class='muted' style='margin-top:8px'>Загрузка…</div></div>"
        "<div class='card'><h3>Лимиты доставки</h3><div id='rl-list' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Подавление (suppression)</h3><div id='sp-list' class='muted'>Загрузка…</div></div>"
        "<div id='ns-msg' class='muted'></div><div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');const msg=document.getElementById('ns-msg');"
        "async function loadOO(){try{const rows=await api('GET','/notification-safety/opt-outs');"
        "const h=document.getElementById('oo-list');h.classList.remove('muted');"
        "h.innerHTML=rows.length?rows.map(o=>`<div class='sched-task'><span class='pill'>${esc(o.scope)}</span> "
        "${esc(o.channel||'—')} <b>${esc(o.status)}</b> "
        "<button class='mini ghost' onclick='ooRevoke(${o.id})'>Вернуть</button></div>`).join(''):"
        "\"<div class='muted'>Отписок нет.</div>\";}catch(x){err(eEl,x)}}"
        "async function ooCreate(){try{const scope=document.getElementById('oo-scope').value;"
        "const ch=document.getElementById('oo-channel').value;"
        "await api('POST','/notification-safety/opt-outs',{scope:scope,channel:scope==='global'?null:ch});"
        "msg.textContent='Отписка создана.';loadOO();}catch(x){err(eEl,x)}}"
        "async function ooRevoke(id){try{await api('POST','/notification-safety/opt-outs/'+id+'/revoke',{});loadOO();}catch(x){err(eEl,x)}}"
        "async function loadRL(){try{const d=await api('GET','/notification-safety/rate-limits');"
        "const h=document.getElementById('rl-list');h.classList.remove('muted');"
        "h.innerHTML=d.buckets.length?d.buckets.map(b=>`<div class='sched-task'><span class='pill'>${esc(b.channel||'—')}</span> "
        "${b.count}/${b.limit} · осталось ${b.remaining}</div>`).join(''):"
        "\"<div class='muted'>Активных лимитов нет.</div>\";}catch(x){err(eEl,x)}}"
        "async function loadSP(){try{const rows=await api('GET','/notification-safety/suppressions');"
        "const h=document.getElementById('sp-list');h.classList.remove('muted');"
        "h.innerHTML=rows.length?rows.map(s=>`<div class='sched-task'><span class='pill'>${esc(s.channel)}</span> "
        "<b>${esc(s.status)}</b> · ${esc(s.reason)} · ошибок ${s.failure_count} "
        "${s.status==='active'?`<button class='mini ghost' onclick='spClear(${s.id})'>Снять</button>`:''}</div>`).join(''):"
        "\"<div class='muted'>Подавлений нет.</div>\";}catch(x){err(eEl,x)}}"
        "async function spClear(id){try{await api('POST','/notification-safety/suppressions/'+id+'/clear',{});loadSP();}catch(x){err(eEl,x)}}"
        "window.ooCreate=ooCreate;window.ooRevoke=ooRevoke;window.spClear=spClear;loadOO();loadRL();loadSP();"
    )
    return _page("Безопасность уведомлений", body, script, active="notifications")


@router.get("/notification-preferences", response_class=HTMLResponse)
def ui_notification_preferences() -> HTMLResponse:
    """Настройки уведомлений: каналы (masked), отписки, ссылки на безопасность."""
    body = (
        "<div class='inline'><a href='/ui/notification-safety'><button class='sec mini'>← Безопасность</button></a></div>"
        "<h2>Настройки уведомлений</h2>"
        f"{_SAFETY_BANNER}"
        "<div class='card'><h3>Каналы</h3>"
        "<div id='np-info' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<label><input type='checkbox' checked disabled> В приложении (in-app)</label>"
        "<label><input type='checkbox' disabled> Email</label>"
        "<label><input type='checkbox' disabled> Telegram</label>"
        "<label><input type='checkbox' disabled> Дайджест</label>"
        "<label><input type='checkbox' disabled> Webhook</label></div>"
        "<p class='muted'>Внешние каналы выключены по умолчанию. Управление отписками: "
        "<a href='/ui/notification-safety'>Безопасность уведомлений →</a></p></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "(async()=>{try{const pr=await api('GET','/notifications/preferences');"
        "document.getElementById('np-info').textContent='in-app: '+(pr.in_app_enabled?'вкл':'выкл')+' · внешняя доставка: '+(pr.external_delivery_enabled?'вкл':'выкл (по умолчанию)');"
        "}catch(e){document.getElementById('np-info').textContent='—';}})();"
    )
    return _page("Настройки уведомлений", body, script, active="notifications")


@router.get("/unsubscribe", response_class=HTMLResponse)
def ui_unsubscribe() -> HTMLResponse:
    """Инфо-страница отписки (реальная отписка — по ссылке /unsubscribe?token=...)."""
    body = (
        "<h2>Отписка от уведомлений</h2>"
        "<div class='callout'>Отписка выполняется по персональной ссылке из письма "
        "(<code>/unsubscribe?token=…</code>). Управлять подписками можно в кабинете: "
        "<a href='/ui/notification-safety'>Безопасность уведомлений →</a></div>"
        "<p class='muted'>Внешняя доставка выключена — сейчас это управление подпиской на будущее.</p>"
    )
    return _page("Отписка", body, "", sidebar=False)


@router.get("/projects/{project_id}/notification-safety", response_class=HTMLResponse)
def ui_project_notification_safety(project_id: int) -> HTMLResponse:
    """Безопасность уведомлений проекта: подавления и лимиты."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/notifications'>"
        "<button class='sec mini'>← Уведомления проекта</button></a>"
        f"<a href='/ui/projects/{project_id}/webhooks'><button class='ghost mini'>Webhooks</button></a></div>"
        "<h2>Безопасность уведомлений проекта</h2>"
        f"{_SAFETY_BANNER}"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Подавлений (активных)</div><div id='ps-active' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Лимит-бакетов</div><div id='ps-buckets' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Подавления</h3><div id='ps-sup' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function load(){try{"
        "const sup=await api('GET','/notification-safety/suppressions');"
        "document.getElementById('ps-active').textContent=sup.filter(s=>s.status==='active').length;"
        "const rl=await api('GET','/notification-safety/rate-limits');"
        "document.getElementById('ps-buckets').textContent=(rl.buckets||[]).length;"
        "const h=document.getElementById('ps-sup');h.classList.remove('muted');"
        "h.innerHTML=sup.length?sup.map(s=>`<div class='sched-task'><span class='pill'>${esc(s.channel)}</span> ${esc(s.status)} · ${esc(s.reason)}</div>`).join(''):"
        "\"<div class='muted'>Подавлений нет.</div>\";}catch(x){err(eEl,x)}}load();"
    )
    return _page(
        "Безопасность уведомлений проекта",
        body,
        script,
        active="notifications",
        active_pid=project_id,
    )


@router.get("/projects/{project_id}/webhooks", response_class=HTMLResponse)
def ui_project_webhooks(project_id: int) -> HTMLResponse:
    """Webhook-подписки проекта: список, создание, preview, отзыв (URL/secret masked)."""
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/notification-safety'>"
        "<button class='sec mini'>← Безопасность</button></a></div>"
        "<h2>Webhook-подписки</h2>"
        "<div class='callout warn'><b>Реальный вызов webhook выключен.</b> URL и signing secret "
        "хранятся зашифрованно; наружу показываются только маской. Доступен подписанный preview "
        "без реальной отправки.</div>"
        "<div class='card'><h3>Новая подписка</h3><div class='inline'>"
        "<input id='wh-title' placeholder='название' style='width:140px'>"
        "<input id='wh-url' placeholder='https://…' style='width:40%'>"
        "<button class='mini' onclick='whCreate()'>Создать</button></div>"
        "<div class='muted' style='margin-top:4px'>Signing secret сгенерируется автоматически (masked).</div></div>"
        "<div id='wh-msg' class='muted'></div>"
        "<div class='card'><h3>Подписки</h3><div id='wh-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const msg=document.getElementById('wh-msg');let AID=null;"
        "async function acct(){if(AID)return AID;const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        "AID=d.account_id||(d.extra&&d.extra.account_id);return AID;}"
        "function whrow(w){return `<div class='sched-task'><span class='pill'>${esc(w.status)}</span> "
        "<b>${esc(w.title)}</b> · ${esc(w.url_masked||'—')} · secret ${w.signing_secret_present?esc(w.signing_secret_masked||'•'):'нет'} "
        "· ${esc(w.signature_algorithm)}"
        "<div class='inline' style='margin-top:4px'><button class='mini sec' onclick='whPreview(${w.id})'>Preview</button>"
        "<button class='mini ghost' onclick='whRevoke(${w.id})'>Отозвать</button></div>"
        "<div id='wh-pv-${w.id}' class='muted'></div></div>`;}"
        "async function loadWH(){try{const aid=await acct();"
        "const rows=await api('GET','/notification-safety/webhooks?account_id='+aid+'&project_id='+PID);"
        "const h=document.getElementById('wh-list');h.classList.remove('muted');"
        "h.innerHTML=rows.length?rows.map(whrow).join(''):\"<div class='muted'>Подписок нет.</div>\";}catch(x){err(eEl,x)}}"
        "async function whCreate(){try{const aid=await acct();const url=document.getElementById('wh-url').value.trim();"
        "if(!url)return;await api('POST','/notification-safety/webhooks',{account_id:aid,project_id:PID,title:document.getElementById('wh-title').value||'webhook',url:url});"
        "msg.textContent='Подписка создана (URL/secret скрыты).';loadWH();}catch(x){err(eEl,x)}}"
        "async function whPreview(id){try{const pv=await api('POST','/notification-safety/webhooks/'+id+'/preview',{});"
        "document.getElementById('wh-pv-'+id).textContent='Подпись: '+pv.signature.slice(0,20)+'… · would_send: '+pv.would_send;}catch(x){err(eEl,x)}}"
        "async function whRevoke(id){try{await api('POST','/notification-safety/webhooks/'+id+'/revoke',{});loadWH();}catch(x){err(eEl,x)}}"
        "window.whCreate=whCreate;window.whPreview=whPreview;window.whRevoke=whRevoke;loadWH();"
    )
    return _page("Webhook-подписки", body, script, active="notifications", active_pid=project_id)


@router.get("/email-templates", response_class=HTMLResponse)
def ui_email_templates() -> HTMLResponse:
    """Email-шаблоны: список, preview (subject/text/html), safety-карточки, баннер."""
    _s = get_settings()

    def _yn(value: bool) -> str:
        return "вкл" if value else "выкл"

    body = (
        "<div class='inline'><a href='/ui/notification-delivery'><button class='sec mini'>← Доставка</button></a>"
        "<a href='/ui/notification-digests'><button class='ghost mini'>Дайджесты</button></a></div>"
        "<h2>Email-шаблоны</h2>"
        "<div class='callout warn'><b>Реальная email-доставка выключена.</b> Сейчас доступен "
        "preview/sandbox: письма рендерятся, но наружу не отправляются. SMTP-пароль хранится "
        "только в env и нигде не показывается.</div>"
        "<div class='grid'>"
        f"<div class='pcard'><div class='muted'>SMTP live</div><div class='an-big'>{_yn(_s.smtp_live_send_enabled_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>Email live</div><div class='an-big'>{_yn(_s.notification_email_enabled_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>External delivery</div><div class='an-big'>{_yn(_s.notification_external_delivery_enabled_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>Unsubscribe footer</div><div class='an-big'>{_yn(_s.email_unsubscribe_footer_enabled_effective)}</div></div>"
        "</div>"
        "<div class='card'><h3>Preview</h3><div class='inline'>"
        "<select id='et-type'></select>"
        "<button class='mini' onclick='etPreview()'>Показать</button></div>"
        "<div style='margin-top:8px'><div class='muted'>Subject</div><div id='et-subject' class='card'></div>"
        "<div class='muted'>Text</div><pre id='et-text' class='card' style='white-space:pre-wrap'></pre>"
        "<div class='muted'>HTML (экранированный предпросмотр)</div><pre id='et-html' class='card' style='white-space:pre-wrap'></pre></div></div>"
        "<div class='card'><h3>Шаблоны</h3><div id='et-list' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "async function loadET(){try{const rows=await api('GET','/email-templates');"
        "const sel=document.getElementById('et-type');sel.innerHTML=rows.map(t=>`<option>${esc(t.template_type)}</option>`).join('');"
        "const h=document.getElementById('et-list');h.classList.remove('muted');"
        "h.innerHTML=rows.map(t=>`<div class='sched-task'><span class='pill'>${esc(t.status)}</span> "
        "<b>${esc(t.template_type)}</b> <span class='muted'>${esc(t.purpose)}</span></div>`).join('');}catch(x){err(eEl,x)}}"
        "async function etPreview(){try{const tt=document.getElementById('et-type').value;"
        "const r=await api('POST','/email-templates/preview',{template_type:tt});"
        "document.getElementById('et-subject').textContent=r.subject;"
        "document.getElementById('et-text').textContent=r.text_body;"
        "document.getElementById('et-html').textContent=r.html_body;}catch(x){err(eEl,x)}}"
        "window.etPreview=etPreview;loadET();"
    )
    return _page("Email-шаблоны", body, script, active="notifications")


def _telegram_body(project_id: int | None = None) -> tuple[str, str]:
    """Собрать body+script страницы Telegram-уведомлений (общий для глобальной/проектной)."""
    _s = get_settings()

    def _yn(value: bool) -> str:
        return "вкл" if value else "выкл"

    body = (
        "<div class='inline'><a href='/ui/notification-delivery'><button class='sec mini'>← Доставка</button></a>"
        "<a href='/ui/email-templates'><button class='ghost mini'>Email-шаблоны</button></a></div>"
        "<h2>Telegram-уведомления</h2>"
        "<div class='callout warn'><b>Реальная Telegram-доставка выключена.</b> Сейчас доступен "
        "preview/sandbox: сообщения рендерятся и «отправляются» через mock, но наружу ничего не "
        "идёт. Bot token хранится только в env; chat_id хранится зашифрованно и показывается "
        "только маской.</div>"
        "<div class='grid'>"
        f"<div class='pcard'><div class='muted'>Telegram live</div><div class='an-big'>{_yn(_s.notification_telegram_live_send_enabled_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>External delivery</div><div class='an-big'>{_yn(_s.notification_external_delivery_enabled_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>Провайдер</div><div class='an-big'>mock</div></div>"
        f"<div class='pcard'><div class='muted'>Привязок</div><div id='tg-count' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Подключение Telegram</h3>"
        "<p class='muted'>1. Откройте вашего Telegram-бота Botfleet. "
        "2. Отправьте боту команду <code>/start &lt;token&gt;</code>. "
        "3. Нажмите «Проверить» (в MVP — введите chat_id вручную ниже).</p>"
        "<div class='inline'><button class='mini' onclick='tgCreate()'>Создать токен привязки</button></div>"
        "<div id='tg-token' class='muted' style='margin-top:8px'></div>"
        "<div style='margin-top:8px'><div class='muted'>Ручная проверка (MVP)</div><div class='inline'>"
        "<input id='tg-vtoken' placeholder='token'>"
        "<input id='tg-chat' placeholder='chat_id'>"
        "<input id='tg-user' placeholder='username'>"
        "<button class='mini sec' onclick='tgVerify()'>Проверить</button></div></div></div>"
        "<div class='card'><h3>Мои привязки</h3><div id='tg-list' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Preview / тест (dry-run)</h3><div class='inline'>"
        "<input id='tg-nid' placeholder='notification_id' style='max-width:160px'>"
        "<button class='mini' onclick='tgPreview()'>Preview уведомления</button>"
        "<button class='mini ghost' onclick='tgTest()'>Тест dry-run</button></div>"
        "<div class='muted' style='margin-top:8px'>Subject</div><div id='tg-subject' class='card'></div>"
        "<div class='muted'>Текст</div><pre id='tg-text' class='card' style='white-space:pre-wrap'></pre></div>"
        # --- v0.5.5: Incoming updates / Webhook ---
        "<div class='callout warn'><b>Реальные Telegram API-вызовы выключены.</b> Webhook принимает "
        "апдейты в sandbox, но setWebhook/getUpdates/deleteWebhook только dry-run. Bot token и "
        "webhook secret — только в env.</div>"
        "<div class='card'><h3>Incoming updates / Webhook</h3>"
        f"<div class='muted'>Webhook endpoint: <code>{html.escape(_s.notification_telegram_webhook_path_effective)}</code></div>"
        f"<div class='muted'>Public URL: <code>{html.escape(_s.notification_telegram_webhook_public_url_effective)}</code></div>"
        "<div class='grid' style='margin-top:8px'>"
        f"<div class='pcard'><div class='muted'>Webhook live</div><div class='an-big'>{_yn(_s.notification_telegram_webhook_live_enabled_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>Secret required</div><div class='an-big'>{_yn(_s.notification_telegram_webhook_secret_required_effective)}</div></div>"
        f"<div class='pcard'><div class='muted'>Secret configured</div><div class='an-big'>{_yn(bool((_s.notification_telegram_webhook_secret_token or '').strip()))}</div></div>"
        f"<div class='pcard'><div class='muted'>Polling live</div><div class='an-big'>{_yn(_s.notification_telegram_polling_live_enabled_effective)}</div></div>"
        "</div></div>"
        "<div class='card'><h3>Проверка /start token</h3>"
        "<p class='muted'>В MVP это sandbox. Реальный Telegram webhook/polling выключен.</p>"
        "<div class='inline'>"
        "<input id='tg-sim-token' placeholder='token'>"
        "<input id='tg-sim-chat' placeholder='chat_id'>"
        "<input id='tg-sim-user' placeholder='username'>"
        "<button class='mini' onclick='tgSimulate()'>Simulate /start update</button></div>"
        "<div id='tg-sim-res' class='muted' style='margin-top:8px'></div></div>"
        "<div class='card'><h3>Recent incoming updates</h3>"
        "<div class='inline'><button class='mini sec' onclick='tgUpdates()'>Обновить</button></div>"
        "<div id='tg-updates' class='muted' style='margin-top:8px'>—</div></div>"
        "<div class='card'><h3>Webhook management (dry-run)</h3><div class='inline'>"
        "<button class='mini ghost' onclick='tgWhSet()'>Preview setWebhook</button>"
        "<button class='mini ghost' onclick='tgWhInfo()'>getWebhookInfo dry-run</button>"
        "<button class='mini ghost' onclick='tgPollDry()'>polling dry-run</button></div>"
        "<pre id='tg-mgmt' class='card' style='white-space:pre-wrap;margin-top:8px'></pre>"
        "<div class='muted'>Управление live выключено — все вызовы только dry-run.</div></div>"
        "<div class='muted'>Логи доставки: <a href='/ui/notification-delivery'>Доставка уведомлений →</a></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "async function tgLoad(){try{const rows=await api('GET','/notification-telegram/bindings');"
        "document.getElementById('tg-count').textContent=rows.length;"
        "const h=document.getElementById('tg-list');h.classList.remove('muted');"
        "h.innerHTML=rows.length?rows.map(b=>`<div class='sched-task'><span class='pill'>${esc(b.status)}</span> "
        "chat ${esc(b.chat_id_masked||'—')} <span class='muted'>${esc(b.username||'')}</span> "
        "<button class='mini ghost' onclick='tgDisable(${b.id})'>Отключить</button> "
        "<button class='mini ghost' onclick='tgRevoke(${b.id})'>Отозвать</button></div>`).join(''):"
        "'<span class=muted>Привязок пока нет.</span>';}catch(x){err(eEl,x)}}"
        "async function tgCreate(){try{const r=await api('POST','/notification-telegram/bindings',{});"
        "document.getElementById('tg-token').innerHTML='<b>Команда для бота:</b> <code>'+esc(r.bot_command)+"
        "'</code><br><span class=muted>Токен показан один раз. Скопируйте и отправьте боту.</span>';"
        "document.getElementById('tg-vtoken').value=r.verification_token;tgLoad();}catch(x){err(eEl,x)}}"
        "async function tgVerify(){try{const r=await api('POST','/notification-telegram/bindings/verify',"
        "{token:document.getElementById('tg-vtoken').value,chat_id:document.getElementById('tg-chat').value,"
        "username:document.getElementById('tg-user').value});tgLoad();}catch(x){err(eEl,x)}}"
        "async function tgDisable(id){try{await api('POST','/notification-telegram/bindings/'+id+'/disable',{});tgLoad();}catch(x){err(eEl,x)}}"
        "async function tgRevoke(id){try{await api('POST','/notification-telegram/bindings/'+id+'/revoke',{});tgLoad();}catch(x){err(eEl,x)}}"
        "async function tgPreview(){try{const id=document.getElementById('tg-nid').value;"
        "const r=await api('POST','/notification-telegram/notifications/'+id+'/preview',{});"
        "document.getElementById('tg-subject').textContent=r.subject;document.getElementById('tg-text').textContent=r.text;}catch(x){err(eEl,x)}}"
        "async function tgTest(){try{const r=await api('POST','/notification-telegram/test-send-dry',{template_type:'system_notice'});"
        "document.getElementById('tg-subject').textContent=r.subject;"
        "document.getElementById('tg-text').textContent=(r.text||r.reason||'')+' [dry-run]';}catch(x){err(eEl,x)}}"
        # --- v0.5.5: webhook/updates/management ---
        "async function tgSimulate(){try{const r=await api('POST','/notification-telegram/simulate-update',"
        "{token:document.getElementById('tg-sim-token').value,chat_id:document.getElementById('tg-sim-chat').value,"
        "username:document.getElementById('tg-sim-user').value});"
        "document.getElementById('tg-sim-res').textContent='Статус: '+esc(r.status||'')+(r.chat_id_masked?(' · chat '+esc(r.chat_id_masked)):'');"
        "tgUpdates();}catch(x){err(eEl,x)}}"
        "async function tgUpdates(){try{const rows=await api('GET','/notification-telegram/updates');"
        "const h=document.getElementById('tg-updates');h.classList.remove('muted');"
        "h.innerHTML=rows.length?rows.map(u=>`<div class='sched-task'><span class='pill'>${esc(u.status)}</span> "
        "#${esc(u.update_id||'—')} ${esc(u.command||'')} <span class='muted'>${esc(u.username||'')}</span> "
        "<span class='muted'>${esc(u.text_preview||'')}</span></div>`).join(''):"
        "'<span class=muted>Апдейтов пока нет.</span>';}catch(x){err(eEl,x)}}"
        "async function tgWhSet(){try{const r=await api('POST','/notification-telegram/webhook/set-dry',{});"
        "document.getElementById('tg-mgmt').textContent=JSON.stringify(r,null,2);}catch(x){err(eEl,x)}}"
        "async function tgWhInfo(){try{const r=await api('GET','/notification-telegram/webhook/info-dry');"
        "document.getElementById('tg-mgmt').textContent=JSON.stringify(r,null,2);}catch(x){err(eEl,x)}}"
        "async function tgPollDry(){try{const r=await api('POST','/notification-telegram/polling/dry',{limit:10});"
        "document.getElementById('tg-mgmt').textContent=JSON.stringify(r,null,2);}catch(x){err(eEl,x)}}"
        "window.tgCreate=tgCreate;window.tgVerify=tgVerify;window.tgDisable=tgDisable;"
        "window.tgRevoke=tgRevoke;window.tgPreview=tgPreview;window.tgTest=tgTest;"
        "window.tgSimulate=tgSimulate;window.tgUpdates=tgUpdates;window.tgWhSet=tgWhSet;"
        "window.tgWhInfo=tgWhInfo;window.tgPollDry=tgPollDry;tgLoad();tgUpdates();"
    )
    return body, script


@router.get("/notification-telegram", response_class=HTMLResponse)
def ui_notification_telegram() -> HTMLResponse:
    """Telegram-уведомления: привязки, preview, тест dry-run, safety-баннер."""
    body, script = _telegram_body()
    return _page("Telegram-уведомления", body, script, active="notifications")


@router.get("/projects/{project_id}/notification-telegram", response_class=HTMLResponse)
def ui_project_notification_telegram(project_id: int) -> HTMLResponse:
    """Telegram-уведомления в контексте проекта (привязки/preview/тест — sandbox)."""
    body, script = _telegram_body(project_id)
    return _page(
        "Telegram-уведомления", body, script, active="notifications", active_pid=project_id
    )


# ======================================================================= #
# Autopilot-first client workspace (v0.5.6)                                #
# Primary UI: клиентский язык, без технического жаргона.                    #
# ======================================================================= #


@router.get("/today", response_class=HTMLResponse)
def ui_today() -> HTMLResponse:
    """Сегодня: что происходит, что требует внимания, следующий шаг, ближайшие публикации."""
    body = (
        "<p class='muted'>Обзор за сегодня по всем вашим проектам. Автопилот работает сам — "
        "здесь только то, что важно.</p>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Запланировано постов</div><div id='td-planned' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Создано постов</div><div id='td-created' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Ждут проверки</div><div id='td-review' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Автопилотов работает</div><div id='td-running' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Требует внимания</h3><div id='td-attention' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Следующий лучший шаг</h3>"
        "<div id='td-next' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Ближайшие публикации</h3><div id='td-next-posts' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        "const eEl=document.getElementById('error');"
        "async function tdLoad(){try{"
        "const projects=await api('GET','/projects');"
        "let planned=0,created=0,review=0,running=0;const attn=[];const nextPosts=[];let firstProject=null;"
        "for(const p of (projects||[])){"
        "if(!firstProject)firstProject=p;"
        "let d=null;try{d=await api('GET','/autopilot/projects/'+p.id);}catch(e){continue;}"
        "if(d.is_enabled)running++;"
        "for(const e of (d.next_posts||[])){planned++;nextPosts.push({project:p.name,platform:e.platform_key,time:e.planned_time,date:e.run_date,outcome:e.outcome});}"
        "for(const b of (d.blockers||[])){if(b.severity==='setup'||b.severity==='blocking')attn.push({project:p.name,msg:b.message,pid:p.id});}"
        "if(d.is_enabled&&d.can_publish_live===false){attn.push({project:p.name,msg:'Автопилот готовит посты, но публикация не включена',pid:p.id});}"
        "}"
        "document.getElementById('td-planned').textContent=planned;"
        "document.getElementById('td-created').textContent=created;"
        "document.getElementById('td-review').textContent=review;"
        "document.getElementById('td-running').textContent=running;"
        "const at=document.getElementById('td-attention');at.classList.remove('muted');"
        "at.innerHTML=attn.length?attn.map(a=>`<div class='sched-task'><b>${esc(a.project)}</b>: ${esc(a.msg)} `+"
        "`<a href='/ui/projects/${a.pid}/autopilot'>Открыть →</a></div>`).join(''):'<span class=muted>Всё в порядке 🎉</span>';"
        "const nx=document.getElementById('td-next');nx.classList.remove('muted');"
        "nx.innerHTML=firstProject?`<a href='/ui/projects/${firstProject.id}/autopilot'><button class='ap-big-btn'>Открыть автопилот</button></a>`:"
        "`<a href='/ui/projects/new'><button class='ap-big-btn'>Создать проект</button></a>`;"
        "const np=document.getElementById('td-next-posts');np.classList.remove('muted');"
        "np.innerHTML=nextPosts.length?nextPosts.slice(0,20).map(e=>`<div class='sched-task'>`+"
        "`<b>${esc(e.project)}</b> · ${esc(e.platform||'—')} · ${esc(e.date||'')} ${esc(e.time||'')} `+"
        "`<span class='pill'>${esc(e.outcome||'план')}</span></div>`).join(''):(firstProject?"
        "`<span class=muted>Пока нет ближайших публикаций. </span><a href='/ui/projects/${firstProject.id}/autopilot/calendar-assistant'>Создать календарь автопостинга →</a>`:"
        "'<span class=muted>Пока нет ближайших публикаций.</span>');"
        "}catch(x){err(eEl,x)}}tdLoad();"
    )
    return _page("Сегодня", body, script, active="today")


@router.get("/advanced", response_class=HTMLResponse)
def ui_advanced() -> HTMLResponse:
    """Advanced: сложные разделы для продвинутых пользователей (вне основного сценария)."""
    body = (
        "<p class='muted'>Продвинутые разделы. В обычном сценарии они не нужны — автопилот "
        "управляет ими сам. Откройте, только если хотите тонкой настройки.</p>"
        "<div class='grid'>"
        "<div class='pcard'><h3>Эксперименты</h3><p class='meta'>A/B-тесты тем и форматов.</p>"
        "<a href='/ui/experiments'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Оптимизация</h3><p class='meta'>Оптимизация тем по метрикам.</p>"
        "<a href='/ui/optimization'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Обучение</h3><p class='meta'>Профиль обучения проекта.</p>"
        "<a href='/ui/learning'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Метрики</h3><p class='meta'>Импорт и обратная связь метрик.</p>"
        "<a href='/ui/metrics'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Ревью</h3><p class='meta'>Очередь ревью и SLA.</p>"
        "<a href='/ui/review'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Автоматизация</h3><p class='meta'>Планировщик и настройки движка.</p>"
        "<a href='/ui/scheduler'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Уведомления</h3><p class='meta'>Доставка, дайджесты, безопасность.</p>"
        "<a href='/ui/notification-delivery'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Telegram-бот</h3><p class='meta'>Webhook/polling sandbox.</p>"
        "<a href='/ui/notification-telegram'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Email-шаблоны</h3><p class='meta'>SMTP sandbox и шаблоны писем.</p>"
        "<a href='/ui/email-templates'><button class='mini sec'>Открыть</button></a></div>"
        "<div class='pcard'><h3>Синхронизация медиа</h3><p class='meta'>Технические прогоны "
        "синхронизации Яндекс Диска (проекты → Картинки из Яндекс Диска).</p>"
        "<a href='/ui/projects'><button class='mini sec'>К проектам</button></a></div>"
        "<div class='pcard'><h3>Готовность к автопубликации</h3><p class='meta'>Проверка готовности "
        "проекта/площадок к реальной публикации. Per-project/per-platform live-переключатели НЕ "
        "включают глобальные условия публикации (*_LIVE_PUBLISHING_ENABLED управляются "
        "администратором).</p>"
        "<a href='/ui/projects'><button class='mini sec'>К проектам</button></a></div>"
        "</div>"
    )
    return _page("Advanced", body, "", active="advanced")


@router.get("/projects/{project_id}/live-readiness", response_class=HTMLResponse)
def ui_project_live_readiness(project_id: int) -> HTMLResponse:
    """Готовность к реальной автопубликации: проверка, площадки, включение live с подтверждением."""
    body = (
        f"{_ap_subnav(project_id, 'live-readiness')}"
        "<div class='hero'><div class='ap-hero'>Готовность к реальной автопубликации</div>"
        "<p class='muted'>Проверьте, может ли автопилот безопасно публиковать сам. Включение здесь "
        "не трогает глобальные условия публикации — реальная публикация сработает только если их "
        "включил администратор.</p></div>"
        "<div class='card'><div class='inline'>"
        "<span id='lr-status' class='ap-status setup'>Загрузка…</span>"
        "<span id='lr-score' class='pill'>—</span></div>"
        "<div id='lr-note' class='muted' style='margin-top:6px'></div>"
        "<div class='inline' style='margin-top:10px'>"
        "<button class='ap-big-btn sec' onclick='lrCheck()'>Проверить готовность</button></div></div>"
        "<div class='card'><h3>Что проверяем</h3><div id='lr-checklist' class='muted'>—</div></div>"
        "<div class='card'><h3>Что мешает</h3><div id='lr-blockers' class='muted'>—</div></div>"
        "<div class='grid'>"
        "<div class='pcard'><h3>Автопилот</h3><div id='lr-c-autopilot' class='meta'>—</div></div>"
        "<div class='pcard'><h3>Календарь</h3><div id='lr-c-calendar' class='meta'>—</div></div>"
        "<div class='pcard'><h3>Медиа</h3><div id='lr-c-media' class='meta'>—</div></div>"
        "<div class='pcard'><h3>Баланс</h3><div id='lr-c-balance' class='meta'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Площадки</h3>"
        "<p class='muted'>Чтобы включить площадку, введите подтверждение <b>ENABLE_PLATFORM_LIVE</b> "
        "в поле ниже и нажмите «Включить площадку».</p>"
        "<div id='lr-platforms' class='muted'>—</div></div>"
        "<div class='card'><h3>Безопасность</h3><div id='lr-security' class='muted'>—</div>"
        "<div class='muted' style='margin-top:8px'>Это не включает глобальные env-флаги. Реальная "
        "публикация сработает только если условия публикации включены администратором.</div></div>"
        "<div class='card'><h3>Включить реальную публикацию</h3>"
        "<p class='muted'>Введите подтверждение <b>ENABLE_LIVE_AUTOPILOT</b> и нажмите кнопку. "
        "Пока проект не готов — включение заблокировано.</p>"
        "<div class='inline'><input id='lr-confirm' placeholder='ENABLE_LIVE_AUTOPILOT' "
        "style='max-width:260px'></div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='ap-big-btn' onclick='lrEnableProject()'>Включить live для проекта</button>"
        "<button class='ap-big-btn sec' onclick='lrEnableFullAuto()'>Включить full-auto live</button>"
        "<button class='ap-big-btn ghost' onclick='lrDisable()'>Выключить live</button></div>"
        "<div id='lr-action-status' class='muted' style='margin-top:8px'></div></div>"
        f"<div class='card'><a href='/ui/projects/{project_id}/autopilot'>"
        "<button class='mini sec'>Вернуться к автопилоту</button></a></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "const toneMap={ready:'ready',warning:'setup',not_ready:'setup',blocked:'problem',"
        "failed:'problem',not_checked:'setup'};"
        "function lrConfirm(){return gv('lr-confirm');}"
        "function lrCard(id,ok,txt){const e=document.getElementById(id);e.textContent=txt;}"
        "async function lrLoad(){try{const d=await api('GET','/live-readiness/projects/'+PID);"
        "const st=document.getElementById('lr-status');st.className='ap-status '+(toneMap[d.status]||'setup');"
        "st.textContent=d.status_label||d.status;"
        "document.getElementById('lr-score').textContent='Готовность: '+(d.readiness_score||0)+'%';"
        "document.getElementById('lr-note').textContent=d.note||'';"
        "const cl=d.checklist||{};const clEl=document.getElementById('lr-checklist');clEl.classList.remove('muted');"
        "clEl.innerHTML=Object.keys(cl).map(k=>`<div class='sched-task'>${cl[k].done?'✓':'—'} ${esc(cl[k].label||k)}</div>`).join('');"
        "const bl=document.getElementById('lr-blockers');bl.classList.remove('muted');"
        "bl.innerHTML=(d.blockers&&d.blockers.length)?d.blockers.map(b=>`<div class='sched-task'>`+"
        "`<span class='pill'>${b.severity==='blocking'?'важно':(b.severity==='setup'?'настройка':'инфо')}</span> ${esc(b.message)}</div>`).join(''):'<span class=muted>Всё готово ✓</span>';"
        "lrCard('lr-c-autopilot',cl.autopilot&&cl.autopilot.done,(cl.autopilot&&cl.autopilot.running)?'Работает':((cl.autopilot&&cl.autopilot.done)?'Настроен':'Не настроен'));"
        "lrCard('lr-c-calendar',cl.calendar&&cl.calendar.done,(cl.calendar&&cl.calendar.done)?'Активен':'Не настроен');"
        "const ms=d.media_status||{};lrCard('lr-c-media',true,'Картинок: '+(ms.total||0)+(ms.enough?' ✓':' (мало)'));"
        "const bs=d.billing_status||{};lrCard('lr-c-balance',bs.enough,'Хватит примерно на '+(bs.approx_posts_left==null?'—':bs.approx_posts_left)+' постов');"
        "const ps=d.platform_statuses||{};const pf=document.getElementById('lr-platforms');pf.classList.remove('muted');"
        "pf.innerHTML=Object.keys(ps).length?Object.keys(ps).map(k=>lrPlatformCard(k,ps[k])).join(''):'<span class=muted>Площадки не выбраны.</span>';"
        "const sec=d.security_status||{};const se=document.getElementById('lr-security');se.classList.remove('muted');"
        "se.innerHTML=`<div class='sched-task'>Условия публикации (глобально): <b>${sec.global_live_any?'включены':'выключены администратором'}</b></div>`+"
        "`<div class='sched-task'>Live для проекта: <b>${sec.project_live_enabled?'включён':'выключен'}</b></div>`+"
        "`<div class='sched-task'>Full-auto: <b>${sec.full_auto_live_enabled?'включён':'выключен'}</b></div>`+"
        "`<div class='sched-task'>Подтверждение: <b>${sec.confirmation_required?'обязательно':'не требуется'}</b></div>`;"
        "}catch(x){err(eEl,x)}}"
        "function lrPlatformCard(k,p){const enabled=p.platform_live_enabled;const g=p.global_live_enabled;"
        "return `<div class='sched-task'><b>${esc(k)}</b> — ${esc(p.status||'')} `+"
        "`<span class='pill'>${g?'условия вкл':'условия выкл'}</span> `+"
        "`<span class='pill'>${enabled?'live вкл':'live выкл'}</span>`+"
        "((p.missing_fields&&p.missing_fields.length)?` <span class='muted'>нужно: ${esc(p.missing_fields.join(', '))}</span>`:'')+"
        "` <button class='mini sec' onclick='lrEnablePlatform(\"'+k+'\")'>Включить площадку</button>`+"
        "`<button class='mini ghost' onclick='lrDisablePlatform(\"'+k+'\")'>Выключить</button></div>`;}"
        "async function lrCheck(){try{await api('POST','/live-readiness/projects/'+PID+'/check',{});lrLoad();}catch(x){err(eEl,x)}}"
        "async function lrEnableProject(){try{const r=await api('POST','/live-readiness/projects/'+PID+'/enable',{confirmation:lrConfirm()});"
        "document.getElementById('lr-action-status').textContent=r.note||'Live для проекта включён ✓';lrLoad();}catch(x){err(eEl,x)}}"
        "async function lrEnableFullAuto(){try{const r=await api('POST','/live-readiness/projects/'+PID+'/full-auto-live/enable',{confirmation:lrConfirm()});"
        "document.getElementById('lr-action-status').textContent=r.ok?'Full-auto live включён ✓':'';lrLoad();}catch(x){err(eEl,x)}}"
        "async function lrDisable(){try{await api('POST','/live-readiness/projects/'+PID+'/disable',{});"
        "document.getElementById('lr-action-status').textContent='Live выключен';lrLoad();}catch(x){err(eEl,x)}}"
        "async function lrEnablePlatform(k){try{await api('POST','/live-readiness/projects/'+PID+'/platforms/'+k+'/enable',{confirmation:gv('lr-confirm')});lrLoad();}catch(x){err(eEl,x)}}"
        "async function lrDisablePlatform(k){try{await api('POST','/live-readiness/projects/'+PID+'/platforms/'+k+'/disable',{});lrLoad();}catch(x){err(eEl,x)}}"
        "window.lrCheck=lrCheck;window.lrEnableProject=lrEnableProject;window.lrEnableFullAuto=lrEnableFullAuto;"
        "window.lrDisable=lrDisable;window.lrEnablePlatform=lrEnablePlatform;window.lrDisablePlatform=lrDisablePlatform;lrLoad();"
    )
    return _page(
        "Готовность к автопубликации", body, script, active="projects", active_pid=project_id
    )


def _ap_subnav(project_id: int, current: str) -> str:
    """Подменю страниц автопилота проекта."""
    items = [
        ("autopilot", "Автопилот", ""),
        ("setup", "Настройка", "/setup"),
        ("platforms", "Площадки", "/platforms"),
        ("media", "Картинки", "/media"),
        ("calendar", "Календарь", "/calendar"),
        ("rules", "Стиль и цель", "/rules"),
    ]
    links = "".join(
        f"<a href='/ui/projects/{project_id}/autopilot{suffix}'>"
        f"<button class='mini {'sec' if key == current else 'ghost'}'>{label}</button></a>"
        for key, label, suffix in items
    )
    lr_cls = "sec" if current == "live-readiness" else "ghost"
    links += (
        f"<a href='/ui/projects/{project_id}/live-readiness'>"
        f"<button class='mini {lr_cls}'>Публикация</button></a>"
    )
    return f"<div class='inline' style='margin-bottom:10px'>{links}</div>"


@router.get("/projects/{project_id}/autopilot", response_class=HTMLResponse)
def ui_project_autopilot(project_id: int) -> HTMLResponse:
    """Автопилот проекта: главный статус, кнопка, карточки, блокеры, следующий шаг."""
    body = (
        f"{_ap_subnav(project_id, 'autopilot')}"
        "<div class='hero'><div class='ap-hero'>Автопостинг работает сам</div>"
        "<p class='muted'>Подключите площадки, дайте Яндекс Диск и выберите календарь — дальше "
        "Botfleet сам пишет тексты, выбирает картинки и публикует по календарю.</p></div>"
        "<div class='card'><div class='inline'>"
        "<span id='ap-status' class='ap-status setup'>Загрузка…</span>"
        "<span id='ap-mode' class='pill'>—</span></div>"
        "<div id='ap-summary' class='muted' style='margin-top:6px'></div>"
        "<div class='inline' style='margin-top:10px'>"
        "<button id='ap-start' class='ap-big-btn' onclick='apStart()'>Запустить автопилот</button>"
        "<button id='ap-pause' class='ap-big-btn sec' onclick='apPause()' style='display:none'>Поставить на паузу</button></div></div>"
        "<div class='grid'>"
        "<div class='pcard'><h3>Куда публикуем</h3><div id='ap-platforms' class='meta'>—</div>"
        f"<a href='/ui/projects/{project_id}/autopilot/platforms'><button class='mini sec'>Площадки</button></a></div>"
        "<div class='pcard'><h3>Откуда берём картинки</h3><div id='ap-media' class='meta'>—</div>"
        f"<a href='/ui/projects/{project_id}/autopilot/media'><button class='mini sec'>Яндекс Диск</button></a></div>"
        "<div class='pcard'><h3>Когда публикуем</h3><div id='ap-calendar' class='meta'>—</div>"
        f"<a href='/ui/projects/{project_id}/autopilot/calendar-assistant'><button class='mini sec'>Календарь автопостинга</button></a> "
        f"<a href='/ui/projects/{project_id}/autopilot/calendar'><button class='mini ghost'>Вручную</button></a></div>"
        "<div class='pcard'><h3>Что бот делает сам</h3><div class='meta'>Пишет текст · выбирает "
        "картинки · адаптирует под площадку · публикует по календарю · анализирует и обучается.</div></div>"
        "</div>"
        "<div class='card'><h3>Что требует внимания</h3><div id='ap-blockers' class='muted'>Загрузка…</div>"
        "<div id='ap-next' style='margin-top:8px'></div></div>"
        "<div class='card'><h3>Баланс и стоимость</h3><div id='ap-billing' class='muted'>—</div></div>"
        "<div class='card'><h3>Реальная публикация</h3><div id='ap-live' class='muted'>—</div>"
        f"<a href='/ui/projects/{project_id}/live-readiness'><button class='mini sec'>Готовность к автопубликации</button></a></div>"
        "<div class='card'><h3>Ближайшие публикации</h3><div id='ap-next-posts' class='muted'>—</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function apLoad(){try{const d=await api('GET','/autopilot/projects/'+PID);"
        "const toneMap={running:'running',ready:'ready',setup_required:'setup',blocked:'problem',paused:'paused',error:'problem'};"
        "const labelMap={running:'Работает',ready:'Готов к запуску',setup_required:'Нужно настроить',blocked:'Есть проблема',paused:'На паузе',error:'Ошибка'};"
        "const st=document.getElementById('ap-status');st.className='ap-status '+(toneMap[d.status]||'setup');"
        "st.textContent=labelMap[d.status]||d.status;"
        "document.getElementById('ap-mode').textContent=d.mode==='full_auto'?'Полный автопилот':'С проверкой';"
        "document.getElementById('ap-summary').textContent=(d.simple_client_summary&&d.simple_client_summary.headline)||'';"
        "document.getElementById('ap-start').style.display=d.is_enabled?'none':'';"
        "document.getElementById('ap-pause').style.display=d.is_enabled?'':'none';"
        "const pf=(d.connected_platforms||[]).filter(p=>p.connected).map(p=>esc(p.platform_key));"
        "document.getElementById('ap-platforms').textContent=pf.length?pf.join(', '):'Пока не подключено';"
        "const ms=d.media_status||{};document.getElementById('ap-media').textContent="
        "(d.yandex_disk_status&&d.yandex_disk_status.connected)?('Найдено картинок: '+(ms.total||0)):'Яндекс Диск не подключён';"
        "const cs=d.calendar_status||{};document.getElementById('ap-calendar').textContent="
        "cs.configured?('Публикуем: '+((cs.publish_times||[]).join(', ')||'по расписанию')):'Календарь не выбран';"
        "const bl=document.getElementById('ap-blockers');bl.classList.remove('muted');"
        "bl.innerHTML=(d.blockers&&d.blockers.length)?d.blockers.map(b=>`<div class='sched-task'>`+"
        "`<span class='pill'>${b.severity==='info'?'инфо':'важно'}</span> ${esc(b.message)}</div>`).join(''):'<span class=muted>Всё готово ✓</span>';"
        "const nb=d.next_best_action||{};document.getElementById('ap-next').innerHTML="
        "nb.label?`<button class='mini sec' onclick='apDoAction(\"'+nb.action+'\")'>${esc(nb.label)}</button>`:'';"
        "const b=d.balance_status||{};document.getElementById('ap-billing').innerHTML="
        "`Баланс: <b>${b.balance_units==null?'—':b.balance_units}</b> units · хватит примерно на `+"
        "`<b>${b.approx_posts_left==null?'—':b.approx_posts_left}</b> постов · один автопост ≈ ${b.cost_per_post||'—'} units · аналитика и обучение включены.`;"
        "const lr=d.live_readiness||{};const lrEl=document.getElementById('ap-live');lrEl.classList.remove('muted');"
        "lrEl.textContent=lr.note||'Проверьте готовность к реальной публикации.';"
        "const np=document.getElementById('ap-next-posts');np.classList.remove('muted');"
        "np.innerHTML=(d.next_posts&&d.next_posts.length)?d.next_posts.slice(0,10).map(e=>`<div class='sched-task'>`+"
        "`${esc(e.platform_key||'—')} · ${esc(e.run_date||'')} ${esc(e.planned_time||'')}</div>`).join(''):'<span class=muted>Появятся после настройки календаря.</span>';"
        "}catch(x){err(eEl,x)}}"
        "async function apStart(){try{const r=await api('POST','/autopilot/projects/'+PID+'/start',{});"
        "if(!r.ok){err(eEl,new Error(r.message||'Сначала завершите настройку'));}apLoad();}catch(x){err(eEl,x)}}"
        "async function apPause(){try{await api('POST','/autopilot/projects/'+PID+'/pause',{});apLoad();}catch(x){err(eEl,x)}}"
        "function apDoAction(a){const map={connect_platform:'/platforms',connect_media:'/media',configure_calendar:'/calendar-assistant',open_billing:'',open_calendar:'/calendar-assistant',fix_blocker:''};"
        "if(a==='start_autopilot'){apStart();return;}if(a==='open_billing'){location.href='/ui/tariffs';return;}"
        "location.href='/ui/projects/'+PID+'/autopilot'+(map[a]||'');}"
        "window.apStart=apStart;window.apPause=apPause;window.apDoAction=apDoAction;apLoad();"
    )
    return _page("Автопилот", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/autopilot/setup", response_class=HTMLResponse)
def ui_project_autopilot_setup(project_id: int) -> HTMLResponse:
    """Мастер настройки автопилота: пошаговый чек-лист."""
    body = (
        f"{_ap_subnav(project_id, 'setup')}"
        "<p class='muted'>Пять простых шагов — и автопилот заработает.</p>"
        "<div class='card'><div id='ap-steps'>Загрузка…</div></div>"
        "<div class='card'><h3>Что дальше</h3><div class='inline'>"
        f"<a href='/ui/projects/{project_id}/autopilot/platforms'><button class='mini sec'>1. Подключить площадку</button></a>"
        f"<a href='/ui/projects/{project_id}/autopilot/media'><button class='mini sec'>2. Подключить Яндекс Диск</button></a>"
        f"<a href='/ui/projects/{project_id}/autopilot/calendar'><button class='mini sec'>3. Выбрать календарь</button></a>"
        f"<a href='/ui/projects/{project_id}/autopilot'><button class='mini'>4. Запустить автопилот</button></a>"
        "</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function stLoad(){try{const d=await api('GET','/autopilot/projects/'+PID+'/checklist');"
        "const h=document.getElementById('ap-steps');"
        "h.innerHTML=(d.steps||[]).map(s=>`<div class='ap-step'><span class='dot ${s.done?'done':'todo'}'>${s.done?'✓':'•'}</span>`+"
        "`<span>${esc(s.title)}</span></div>`).join('')+`<p class='muted' style='margin-top:8px'>Готово ${d.done} из ${d.total}.</p>`;"
        "}catch(x){err(eEl,x)}}stLoad();"
    )
    return _page("Настройка автопилота", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/autopilot/platforms", response_class=HTMLResponse)
def ui_project_autopilot_platforms(project_id: int) -> HTMLResponse:
    """Площадки автопилота: карточки Telegram/VK/Instagram/OK со статусом подключения."""
    cards = [
        ("telegram", "Telegram", "готово"),
        ("vk", "VK", "готово"),
        ("instagram", "Instagram", "готово"),
        ("odnoklassniki", "Одноклассники", "скоро"),
        ("website", "Сайт", "готово"),
    ]
    tiles = "".join(
        f"<div class='pcard'><h3>{label}</h3>"
        f"<div class='meta' id='ap-pf-{key}'>—</div>"
        + (
            f"<a href='/ui/projects/{project_id}/platforms'><button class='mini sec'>Подключить</button></a>"
            if avail == "готово"
            else "<span class='pill off'>скоро</span>"
        )
        + "</div>"
        for key, label, avail in cards
    )
    body = (
        f"{_ap_subnav(project_id, 'platforms')}"
        "<p class='muted'>Выберите, куда публиковать. Подключение занимает пару минут.</p>"
        f"<div class='grid'>{tiles}</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function pfLoad(){try{const d=await api('GET','/autopilot/projects/'+PID);"
        "const map={};for(const p of (d.connected_platforms||[]))map[p.platform_key]=p;"
        "for(const k of ['telegram','vk','instagram','odnoklassniki','website']){"
        "const el=document.getElementById('ap-pf-'+k);if(!el)continue;"
        "const p=map[k];el.textContent=p?(p.connected?'Подключено ✓':'Нужно завершить подключение'):'Не подключено';}"
        "}catch(x){err(eEl,x)}}pfLoad();"
    )
    return _page("Площадки", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/autopilot/media", response_class=HTMLResponse)
def ui_project_autopilot_media(project_id: int) -> HTMLResponse:
    """Картинки автопилота: краткий статус синхронизации + ссылка на страницу Яндекс Диска."""
    body = (
        f"{_ap_subnav(project_id, 'media')}"
        "<p class='muted'>Загрузите фото в папку Яндекс Диска — Botfleet сам найдёт новые картинки "
        "и подготовит их для автопостинга.</p>"
        "<div class='grid'>"
        "<div class='pcard'><div class='muted'>Всего картинок</div><div id='am-total' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Хорошего качества</div><div id='am-good' class='an-big'>—</div></div>"
        "<div class='pcard'><div class='muted'>Статус</div><div id='am-status' class='an-big'>—</div></div>"
        "</div>"
        "<div class='card'><div id='am-summary' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        f"<a href='/ui/projects/{project_id}/yandex-sync'><button class='mini sec'>Настроить Яндекс Диск</button></a>"
        "<button class='mini' onclick='amSync()'>Синхронизировать сейчас</button></div>"
        "<div id='am-sync' class='muted' style='margin-top:8px'></div></div>"
        "<div class='muted'>Файлы не удаляются. В тестовом режиме внешняя сеть выключена.</div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function amLoad(){try{const d=await api('GET','/yandex-sync/projects/'+PID);"
        "document.getElementById('am-total').textContent=d.media_count||0;"
        "const q=d.quality_summary||{};document.getElementById('am-good').textContent=(q&&q.good)||0;"
        "document.getElementById('am-status').textContent=(d.simple_client_summary&&d.simple_client_summary.tone==='ready')?'Готово':'Настройка';"
        "document.getElementById('am-summary').textContent=(d.simple_client_summary&&d.simple_client_summary.headline)||'';"
        "}catch(x){err(eEl,x)}}"
        "async function amSync(){try{const r=await api('POST','/yandex-sync/projects/'+PID+'/run-dry',{});"
        "document.getElementById('am-sync').textContent='Проверка выполнена: '+esc(r.status)+'. Файлы не удаляются.';amLoad();}catch(x){err(eEl,x)}}"
        "window.amSync=amSync;amLoad();"
    )
    return _page("Картинки", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/autopilot/calendar", response_class=HTMLResponse)
def ui_project_autopilot_calendar(project_id: int) -> HTMLResponse:
    """Календарь автопилота: простой выбор частоты/времени/площадок."""
    body = (
        f"{_ap_subnav(project_id, 'calendar')}"
        "<p class='muted'>Выберите, как часто и когда публиковать. Botfleet сам подготовит "
        "и опубликует посты по этому плану.</p>"
        "<div class='card'><h3>Как часто</h3>"
        "<div class='inline'>"
        "<label><input type='radio' name='freq' value='daily' checked> Каждый день</label>"
        "<label><input type='radio' name='freq' value='weekdays'> По будням</label>"
        "<label><input type='radio' name='freq' value='three_per_week'> 3 раза в неделю</label>"
        "<label><input type='radio' name='freq' value='custom'> Свои дни</label></div>"
        "<div class='inline' style='margin-top:8px' id='cal-days'>"
        + "".join(
            f"<label><input type='checkbox' class='cal-wd' value='{i}'> {d}</label>"
            for i, d in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
        )
        + "</div></div>"
        "<div class='card'><h3>Время публикации</h3>"
        "<div class='inline'><input id='cal-time' value='10:00' style='max-width:100px'>"
        "<span class='muted'>по Москве</span></div></div>"
        "<div class='card'><h3>Площадки</h3><div class='inline'>"
        "<label><input type='checkbox' class='cal-pf' value='telegram' checked> Telegram</label>"
        "<label><input type='checkbox' class='cal-pf' value='vk'> VK</label>"
        "<label><input type='checkbox' class='cal-pf' value='instagram'> Instagram</label></div></div>"
        "<div class='card'><button class='ap-big-btn' onclick='calSave()'>Сохранить календарь</button>"
        "<div id='cal-status' class='muted' style='margin-top:8px'></div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "function calFreq(){const r=document.querySelector('input[name=freq]:checked');return r?r.value:'daily';}"
        "async function calSave(){try{"
        "const platforms=[...document.querySelectorAll('.cal-pf:checked')].map(x=>x.value);"
        "const weekdays=[...document.querySelectorAll('.cal-wd:checked')].map(x=>parseInt(x.value));"
        "const r=await api('POST','/autopilot/projects/'+PID+'/calendar',"
        "{platforms:platforms,frequency:calFreq(),weekdays:weekdays,publish_times:[gv('cal-time')]});"
        "document.getElementById('cal-status').textContent='Календарь сохранён ✓';}catch(x){err(eEl,x)}}"
        "window.calSave=calSave;"
    )
    return _page("Календарь", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/autopilot/calendar-assistant", response_class=HTMLResponse)
def ui_project_autopilot_calendar_assistant(project_id: int) -> HTMLResponse:
    """Календарь автопостинга: клиент выбирает цель и частоту — Botfleet строит календарь сам."""
    goals = [
        ("mixed", "Смешанная"),
        ("sales", "Продажи"),
        ("leads", "Заявки"),
        ("reach", "Охваты"),
        ("trust", "Доверие"),
        ("expertise", "Экспертность"),
    ]
    goal_opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in goals)
    body = (
        f"{_ap_subnav(project_id, 'calendar')}"
        "<div class='hero'><div class='ap-hero'>Календарь автопостинга</div>"
        "<p class='muted'>Выберите цель и частоту — Botfleet сам построит календарь: распределит "
        "дни и время, учтёт площадки, количество картинок и баланс. Botfleet сам будет писать "
        "текст, выбирать картинки и публиковать по этому календарю.</p></div>"
        "<div class='card'><div class='inline'>"
        "<button class='mini sec' onclick='caRecommend()'>Подобрать за меня</button>"
        "<span id='ca-reco' class='muted'></span></div></div>"
        "<div class='card'><h3>Цель</h3>"
        f"<select id='ca-goal'>{goal_opts}</select></div>"
        "<div class='card'><h3>Как часто публиковать</h3>"
        "<div id='ca-presets' class='muted'>Загрузка…</div></div>"
        "<div class='card'><h3>Площадки</h3><div class='inline'>"
        "<label><input type='checkbox' class='ca-pf' value='telegram' checked> Telegram</label>"
        "<label><input type='checkbox' class='ca-pf' value='vk'> VK</label>"
        "<label><input type='checkbox' class='ca-pf' value='instagram'> Instagram</label></div></div>"
        "<div class='card'><h3>Время публикации</h3>"
        "<div class='inline'><input id='ca-time' value='10:00' style='max-width:100px'>"
        "<span class='muted'>по Москве · оставьте пустым, чтобы Botfleet выбрал лучшее время</span></div></div>"
        "<div class='card'><div class='inline'>"
        "<button class='ap-big-btn sec' onclick='caPreview()'>Предварительный просмотр</button>"
        "<button class='ap-big-btn' onclick='caCreate()'>Создать календарь</button></div>"
        "<div id='ca-preview' style='margin-top:10px'></div></div>"
        "<div class='card' id='ca-apply-card' style='display:none'><h3>Применить к автопилоту</h3>"
        "<div class='muted' style='margin-bottom:8px'>Календарь создан. Примените его — Botfleet "
        "начнёт готовить публикации по плану (реальная публикация проходит условия безопасности).</div>"
        "<div class='inline'>"
        "<button class='ap-big-btn' onclick='caApply()'>Применить к автопилоту</button>"
        f"<a href='/ui/projects/{project_id}/autopilot'><button class='ap-big-btn sec'>Вернуться к автопилоту</button></a></div>"
        "<div id='ca-apply-status' class='muted' style='margin-top:8px'></div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "let CA_PRESET=null;let CA_PLAN=null;"
        "function caPayload(){return{preset:CA_PRESET,goal:gv('ca-goal'),"
        "platforms:[...document.querySelectorAll('.ca-pf:checked')].map(x=>x.value),"
        "publish_times:gv('ca-time')?[gv('ca-time')]:[]};}"
        "async function caLoadPresets(){try{const d=await api('GET','/autopilot-calendar/projects/'+PID+'/presets');"
        "const el=document.getElementById('ca-presets');el.classList.remove('muted');"
        "el.innerHTML=(d.presets||[]).map((p,i)=>`<label style='display:block;margin:4px 0'>`+"
        "`<input type='radio' name='ca-preset' value='${esc(p.preset)}' ${i===0?'checked':''} onchange='caPick(\"'+p.preset+'\")'> `+"
        "`<b>${esc(p.label)}</b> — ${esc(p.description)} `+"
        "`<span class='pill'>~${p.estimated_posts_per_month} постов/мес</span>`+"
        "((p.warnings&&p.warnings.length)?` <span class='muted'>${esc(p.warnings[0])}</span>`:'')+`</label>`).join('');"
        "if((d.presets||[]).length){CA_PRESET=d.presets[0].preset;}}catch(x){err(eEl,x)}}"
        "function caPick(p){CA_PRESET=p;}"
        "window.caPick=caPick;"
        "async function caRecommend(){try{const r=await api('POST','/autopilot-calendar/projects/'+PID+'/recommend',{});"
        "CA_PRESET=r.recommended_preset;const rd=document.querySelector(`input[name=ca-preset][value=${CSS.escape(r.recommended_preset)}]`);"
        "if(rd){rd.checked=true;}if(r.goal){document.getElementById('ca-goal').value=r.goal;}"
        "document.getElementById('ca-reco').textContent='Рекомендуем: '+esc(r.reason||'');}catch(x){err(eEl,x)}}"
        "function caRisks(rs){if(!rs||!rs.length)return '<span class=muted>Рисков не найдено ✓</span>';"
        "return rs.map(r=>`<div class='sched-task'><span class='pill'>${r.severity==='setup'?'настройка':'инфо'}</span> ${esc(r.message)}</div>`).join('');}"
        "async function caPreview(){try{const d=await api('POST','/autopilot-calendar/projects/'+PID+'/preview',caPayload());"
        "const e=d.estimates||{};document.getElementById('ca-preview').innerHTML="
        "`<div class='sched-task'>Дни: <b>${(d.weekday_labels||[]).join(', ')||'—'}</b> · время <b>${(d.publish_times||[]).join(', ')}</b></div>`+"
        "`<div class='sched-task'>Постов в месяц: <b>${e.estimated_posts_per_month||0}</b> · нужно картинок ~<b>${e.estimated_media_needed||0}</b> · `+"
        "`стоимость ~<b>${e.estimated_units_per_month||0}</b> units/мес</div>`+caRisks(d.risks);}catch(x){err(eEl,x)}}"
        "async function caCreate(){try{const d=await api('POST','/autopilot-calendar/projects/'+PID+'/create',caPayload());"
        "CA_PLAN=d.id;document.getElementById('ca-apply-card').style.display='';"
        "document.getElementById('ca-apply-status').textContent='Календарь создан (черновик). Примените его к автопилоту.';"
        "caPreview();}catch(x){err(eEl,x)}}"
        "async function caApply(){try{if(!CA_PLAN){err(eEl,new Error('Сначала создайте календарь'));return;}"
        "const r=await api('POST','/autopilot-calendar/projects/'+PID+'/plans/'+CA_PLAN+'/apply',{});"
        "document.getElementById('ca-apply-status').textContent=r.note||'Календарь применён ✓';}catch(x){err(eEl,x)}}"
        "window.caRecommend=caRecommend;window.caPreview=caPreview;window.caCreate=caCreate;window.caApply=caApply;"
        "caLoadPresets();"
    )
    return _page("Календарь автопостинга", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/autopilot/rules", response_class=HTMLResponse)
def ui_project_autopilot_rules(project_id: int) -> HTMLResponse:
    """Стиль и цель постинга: цель/тон/глубина/CTA."""
    body = (
        f"{_ap_subnav(project_id, 'rules')}"
        "<p class='muted'>Задайте цель и стиль — Botfleet будет писать тексты в нужном тоне.</p>"
        "<div class='card'><h3>Цель постинга</h3>"
        "<select id='rl-goal'>"
        "<option value='продажи'>Продажи</option><option value='заявки'>Заявки</option>"
        "<option value='охват'>Охват</option><option value='доверие'>Доверие</option>"
        "<option value='экспертность'>Экспертность</option></select></div>"
        "<div class='card'><h3>Тон</h3>"
        "<select id='rl-tone'>"
        "<option value='экспертный'>Экспертный</option><option value='дружелюбный'>Дружелюбный</option>"
        "<option value='продающий'>Продающий</option><option value='спокойный'>Спокойный</option></select></div>"
        "<div class='card'><h3>Глубина поста</h3>"
        "<select id='rl-depth'>"
        "<option value='normal'>Обычный</option><option value='deep'>Глубокий</option>"
        "<option value='expert'>Экспертный</option></select></div>"
        "<div class='card'><h3>Призыв к действию (CTA)</h3>"
        "<input id='rl-cta' placeholder='Например: Пишите в личные сообщения' style='min-width:280px'></div>"
        "<div class='card'><button class='ap-big-btn' onclick='rlSave()'>Сохранить</button>"
        "<div id='rl-status' class='muted' style='margin-top:8px'></div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function rlSave(){try{const r=await api('POST','/autopilot/projects/'+PID+'/content-rules',"
        "{business_goal:gv('rl-goal'),tone:gv('rl-tone'),post_depth:gv('rl-depth'),cta:gv('rl-cta')});"
        "document.getElementById('rl-status').textContent='Сохранено ✓';}catch(x){err(eEl,x)}}"
        "window.rlSave=rlSave;"
    )
    return _page("Стиль и цель", body, script, active="projects", active_pid=project_id)


@router.get("/projects/{project_id}/yandex-sync", response_class=HTMLResponse)
def ui_project_yandex_sync(project_id: int) -> HTMLResponse:
    """Картинки из Яндекс Диска: подключение, медиатека, последняя синхронизация, что дальше."""
    body = (
        f"{_ap_subnav(project_id, 'media')}"
        "<div class='hero'><div class='ap-hero'>Картинки из Яндекс Диска</div>"
        "<p class='muted'>Загрузите фото в папку — Botfleet сам найдёт новые картинки и подготовит "
        "их для автопостинга.</p></div>"
        "<div class='callout warn'><b>Файлы не удаляются.</b> В тестовом режиме внешняя сеть "
        "выключена — показывается текущее состояние медиатеки. Для автопостинга нужно минимум "
        "5 картинок.</div>"
        "<div class='grid'>"
        "<div class='pcard'><h3>Подключение</h3><div id='ys-conn' class='meta'>—</div></div>"
        "<div class='pcard'><h3>Медиатека</h3><div id='ys-media' class='meta'>—</div></div>"
        "<div class='pcard'><h3>Последняя синхронизация</h3><div id='ys-last' class='meta'>—</div></div>"
        "<div class='pcard'><h3>Что сделать дальше</h3><div id='ys-next' class='meta'>—</div></div>"
        "</div>"
        "<div class='card'><h3>Настройка</h3><div class='inline'>"
        "<input id='ys-url' placeholder='https://disk.yandex.ru/d/...' style='min-width:280px'>"
        "<input id='ys-folder' placeholder='Папка (например SMM)' value='SMM'>"
        "<input id='ys-tags' placeholder='теги через запятую'>"
        "<input id='ys-freq' placeholder='частота, мин' value='60' style='max-width:110px'>"
        "<button class='mini' onclick='ysSave()'>Сохранить</button></div>"
        "<div id='ys-save-status' class='muted' style='margin-top:8px'></div></div>"
        "<div class='card'><h3>Синхронизация</h3><div class='inline'>"
        "<button class='mini sec' onclick='ysHealth()'>Проверить</button>"
        "<button class='mini' onclick='ysRun()'>Синхронизировать сейчас</button>"
        "<button class='mini ghost' onclick='ysPreview()'>Предварительная проверка</button>"
        "<button class='mini ghost' onclick='ysPause()'>Пауза</button>"
        "<button class='mini ghost' onclick='ysResume()'>Возобновить</button></div>"
        "<div id='ys-run' class='muted' style='margin-top:8px'></div></div>"
        "<div class='card'><h3>История проверок</h3><div id='ys-runs' class='muted'>—</div></div>"
        "<div id='error' class='err'></div>"
    )
    script = (
        f"const PID={project_id};const eEl=document.getElementById('error');"
        "async function ysLoad(){try{const d=await api('GET','/yandex-sync/projects/'+PID);"
        "const pf=d.profile||{};"
        "document.getElementById('ys-conn').innerHTML=`${pf.has_public_url?'Подключено ✓':'Не подключено'}`+"
        "(pf.public_url_masked?(' · '+esc(pf.public_url_masked)):'')+(pf.root_folder?(' · папка '+esc(pf.root_folder)):'');"
        "document.getElementById('ys-media').innerHTML=`Всего: <b>${d.media_count||0}</b> · картинки ${d.image_count||0} · видео ${d.video_count||0}`;"
        "const ls=d.last_sync||{};document.getElementById('ys-last').textContent=ls.at?(esc(ls.status||'')+' · '+esc(ls.at)):'Проверок ещё не было';"
        "const nb=d.next_best_action||{};document.getElementById('ys-next').textContent=nb.label||'Синхронизировать сейчас';"
        "if(pf.public_url_masked&&!gv('ys-url'))document.getElementById('ys-url').placeholder=pf.public_url_masked;"
        "const runs=d.recent_runs||[];const rs=document.getElementById('ys-runs');rs.classList.remove('muted');"
        "rs.innerHTML=runs.length?runs.map(r=>`<div class='sched-task'><span class='pill'>${esc(r.status)}</span> `+"
        "`видно ${r.files_seen} · импорт ${r.files_imported} · ошибок ${r.files_failed} <span class='muted'>${esc(r.created_at||'')}</span></div>`).join(''):'<span class=muted>Проверок пока нет.</span>';"
        "}catch(x){err(eEl,x)}}"
        "async function ysSave(){try{await api('POST','/yandex-sync/projects/'+PID+'/profile',"
        "{public_url:gv('ys-url'),root_folder:gv('ys-folder'),default_tags:gl('ys-tags'),sync_frequency_minutes:parseInt(gv('ys-freq')||'60')});"
        "document.getElementById('ys-save-status').textContent='Сохранено ✓';ysLoad();}catch(x){err(eEl,x)}}"
        "async function ysHealth(){try{const r=await api('POST','/yandex-sync/projects/'+PID+'/health-check',{});"
        "document.getElementById('ys-run').textContent='Статус: '+esc(r.status)+'. '+((r.blockers&&r.blockers[0]&&r.blockers[0].message)||'');ysLoad();}catch(x){err(eEl,x)}}"
        "async function ysRun(){try{const r=await api('POST','/yandex-sync/projects/'+PID+'/run-dry',{});"
        "document.getElementById('ys-run').textContent='Проверка: '+esc(r.status)+'. Файлы не удаляются.';ysLoad();}catch(x){err(eEl,x)}}"
        "async function ysPreview(){try{const r=await api('POST','/yandex-sync/projects/'+PID+'/preview',{});"
        "document.getElementById('ys-run').textContent=esc(r.note||'')+' (без записи)';}catch(x){err(eEl,x)}}"
        "async function ysPause(){try{await api('POST','/yandex-sync/projects/'+PID+'/pause',{});ysLoad();}catch(x){err(eEl,x)}}"
        "async function ysResume(){try{await api('POST','/yandex-sync/projects/'+PID+'/resume',{});ysLoad();}catch(x){err(eEl,x)}}"
        "window.ysSave=ysSave;window.ysHealth=ysHealth;window.ysRun=ysRun;window.ysPreview=ysPreview;"
        "window.ysPause=ysPause;window.ysResume=ysResume;ysLoad();"
    )
    return _page("Картинки из Яндекс Диска", body, script, active="projects", active_pid=project_id)
