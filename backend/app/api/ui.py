"""SaaS личный кабинет v0.2.3 (server-rendered HTML, без сборки/зависимостей).

Каждая страница ``/ui/*`` — самодостаточный HTML со встроенными CSS и vanilla-JS,
который обращается к существующим JSON-API (``/auth``, ``/saas``, ``/billing``).
Dev-токен и активный ``account_id`` хранятся в ``localStorage``.

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

import json
import re

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/ui", tags=["ui"])


def _safe_slug(value: str) -> str:
    """Нормализовать сегмент пути (тип платформы) в безопасный slug.

    Отсекает любые HTML/JS-спецсимволы из path-параметра — защита от reflected XSS
    при вставке в ``<title>`` и в JS-константу ``PLATFORM``.
    """
    cleaned = re.sub(r"[^a-z0-9_-]", "", value.lower())[:20]
    return cleaned or "platform"


_CSS = """
:root{--bg:#0f1115;--card:#181b22;--fg:#e6e6e6;--muted:#9aa4b2;--accent:#4f8cff;--err:#ff6b6b;--ok:#3ecf8e;--border:#2a2f3a;--sb:#12151c}
@media (prefers-color-scheme: light){:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1a1a;--muted:#666;--border:#e2e5ea;--sb:#fbfcfe}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.topbar{display:flex;align-items:center;gap:12px;padding:10px 18px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20}
.brand{font-weight:700;color:var(--fg)}
.spacer{flex:1}
.acctbox{position:relative}
.acctbtn{display:flex;align-items:center;gap:8px;background:transparent;color:var(--fg);border:1px solid var(--border);border-radius:22px;padding:5px 12px;cursor:pointer;font:inherit}
.acctbtn .uicon{width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.acctbtn .caret{color:var(--muted)}
.menu{position:absolute;right:0;top:112%;background:var(--card);border:1px solid var(--border);border-radius:10px;min-width:190px;box-shadow:0 10px 30px rgba(0,0,0,.28);overflow:hidden;z-index:30}
.menu a{display:block;padding:10px 14px;color:var(--fg)}
.menu a:hover{background:var(--bg);text-decoration:none}
.layout{display:grid;grid-template-columns:240px 1fr;min-height:calc(100vh - 54px)}
.layout.nosb{grid-template-columns:1fr}
.sidebar{background:var(--sb);border-right:1px solid var(--border);padding:16px 12px}
.sb-group{margin-bottom:10px}
.sb-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
.sb-title{font-weight:600;color:var(--fg);font-size:14px;letter-spacing:.02em}
.sb-add{display:inline-flex;width:26px;height:26px;align-items:center;justify-content:center;border:1px solid var(--border);border-radius:7px;color:var(--accent);line-height:1}
.sb-add:hover{background:var(--bg);text-decoration:none}
.sb-projects{margin:8px 0 4px;display:flex;flex-direction:column;gap:2px}
.sb-proj{display:block;padding:6px 9px;border-radius:7px;color:var(--fg);font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sb-proj:hover{background:var(--bg);text-decoration:none}
.sb-hint{padding:6px 9px;font-size:12px}
.sb-link{display:block;padding:8px 9px;border-radius:7px;color:var(--fg);margin-top:2px;font-size:14px}
.sb-link:hover{background:var(--bg);text-decoration:none}
.sb-link.active,.sb-title.active{color:var(--accent)}
.content{padding:22px 26px;max-width:1000px}
.content.narrow{max-width:560px;margin:0 auto}
h1{font-size:22px;margin:0 0 8px}h2{font-size:16px;margin:22px 0 6px}h3{margin:0 0 6px;font-size:15px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin:14px 0}
label{display:block;margin:8px 0 4px;color:var(--muted);font-size:13px}
label.chk{display:inline-flex;align-items:center;gap:6px;color:var(--fg)}
input,select,textarea{width:100%;padding:8px 10px;background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:8px;font:inherit}
textarea{min-height:120px;resize:vertical}
input[type=checkbox]{width:auto}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;align-items:center;border:1px dashed var(--border);border-radius:8px;padding:10px;margin:8px 0}
.row input,.row select{width:100%}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 14px;font:inherit;cursor:pointer}
button.sec{background:transparent;color:var(--accent);border:1px solid var(--accent)}
button.mini{padding:4px 10px;font-size:13px}
button.ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}
.muted{color:var(--muted);font-size:13px}
.inline{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.badge{display:inline-block;background:var(--border);border-radius:6px;padding:2px 8px;font-size:12px;color:var(--muted);margin:2px 4px 2px 0}
.pill{display:inline-block;border-radius:20px;padding:2px 10px;font-size:12px}
.pill.ok{background:rgba(62,207,142,.16);color:var(--ok)}
.pill.off{background:rgba(154,164,178,.16);color:var(--muted)}
.err{display:none;background:rgba(255,107,107,.12);border:1px solid var(--err);color:var(--err);padding:10px;border-radius:8px;margin:10px 0;white-space:pre-wrap}
pre{display:none;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;overflow:auto;max-height:460px;white-space:pre-wrap;word-break:break-word}
table.kw{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
table.kw th,table.kw td{border:1px solid var(--border);padding:3px 4px;text-align:left}
table.kw input,table.kw select{border:0;background:transparent;padding:5px 4px}
.days{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.days label{display:inline-flex;align-items:center;gap:5px;margin:0;color:var(--fg);font-size:14px}
.pcard{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px}
.pcard .meta{color:var(--muted);font-size:13px;margin:4px 0 10px;word-break:break-word}
@media (max-width:760px){.layout{grid-template-columns:1fr}.sidebar{border-right:0;border-bottom:1px solid var(--border)}}
"""

# Статический header: справа гость-кнопки ИЛИ аккаунт+баланс с dropdown.
# Метки dropdown (Пополнить счёт / Выйти) присутствуют в HTML всегда — JS лишь
# переключает видимость и подставляет имя/баланс.
_HEADER = (
    "<header class='topbar'>"
    "<a class='brand' href='/ui/'>🤖 SMM SaaS</a>"
    "<span class='spacer'></span>"
    "<div id='acctbox' class='acctbox'>"
    "<div class='guest'>"
    "<a href='/ui/login'><button class='sec mini'>Войти</button></a> "
    "<a href='/ui/register'><button class='mini'>Регистрация</button></a>"
    "</div>"
    "<div class='acctwrap' style='display:none'>"
    "<button class='acctbtn' onclick='toggleAcctMenu(event)'>"
    "<span class='uicon'>👤</span><span id='acct-label'>…</span><span class='caret'>▾</span></button>"
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
      sb.innerHTML = ps.length
        ? ps.map(p=>`<a class='sb-proj' href='/ui/projects/${p.id}/dashboard' title='${esc(p.name)}'>${esc(p.name)}</a>`).join('')
        : "<div class='muted sb-hint'>Проектов нет. Создайте новый.</div>";
    }catch(e){ sb.innerHTML="<div class='muted sb-hint'>—</div>"; }
  }
}
initShell();
"""


def _sidebar(active: str = "") -> str:
    """Левый sidebar кабинета (Проекты со списком / Тарифы / Аналитика / Настройки)."""

    def cls(key: str) -> str:
        return " active" if active == key else ""

    return (
        "<aside class='sidebar'>"
        "<div class='sb-group'><div class='sb-head'>"
        f"<a class='sb-title{cls('projects')}' href='/ui/projects'>Проекты</a>"
        "<a class='sb-add' href='/ui/projects/new' title='Новый проект'>+</a></div>"
        "<div id='sb-projects' class='sb-projects'><div class='muted sb-hint'>…</div></div></div>"
        f"<a class='sb-link{cls('tariffs')}' href='/ui/tariffs'>Тарифы</a>"
        f"<a class='sb-link{cls('analytics')}' href='/ui/analytics'>Аналитика</a>"
        f"<a class='sb-link{cls('settings')}' href='/ui/settings'>Настройки</a>"
        "</aside>"
    )


def _page(
    title: str, body: str, script: str = "", active: str = "", sidebar: bool = True
) -> HTMLResponse:
    """Собрать страницу кабинета: header + (опционально) sidebar + контент."""
    main_cls = "content" if sidebar else "content narrow"
    layout_cls = "layout" if sidebar else "layout nosb"
    aside = _sidebar(active) if sidebar else ""
    inner = f"{aside}<main class='{main_cls}'><h1>{title}</h1>{body}</main>"
    html = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title} — SMM SaaS</title><style>{_CSS}</style></head><body>"
        f"{_HEADER}<div class='{layout_cls}'>{inner}</div>"
        f"<script>{_SHARED_JS}</script><script>{script}</script></body></html>"
    )
    return HTMLResponse(html)


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
    return _page(f"Настройки проекта #{project_id}", body, _FORM_JS + script, active="projects")


# --------------------------------------------------------------------------- #
# Дашборд проекта                                                             #
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/dashboard", response_class=HTMLResponse)
def ui_project_dashboard(project_id: int) -> HTMLResponse:
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/settings'>"
        "<button class='sec mini'>Настройки проекта</button></a></div>"
        "<div id='dash' class='muted'>Загрузка…</div>"
        "<h2>Платформы</h2><div id='plats' class='grid'></div>"
        "<div id='error' class='err'></div><pre id='raw'></pre>"
    )
    script = (
        f"const PID={project_id};"
        "const eEl=document.getElementById('error');const D=document.getElementById('dash');"
        "const P=document.getElementById('plats');"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        "D.innerHTML=`<div class='card'><h2>${esc(d.project_name)} <span class='muted'>(${esc(d.project_slug)})</span></h2>`"
        "+`<span class='badge'>баланс: ${d.billing_balance_units==null?'—':d.billing_balance_units} units</span>`"
        "+`<span class='badge'>платформы: ${d.platforms_count}</span>`"
        "+`<span class='badge'>медиа-источники: ${d.media_sources_count}</span>`"
        "+`<span class='badge'>категории: ${d.categories_count}</span>`"
        "+`<span class='badge'>планы: ${d.active_plans_count}</span>`"
        "+`<span class='badge'>на ревью: ${d.posts_needing_review}</span>`"
        "+`<h2>Последние посты</h2>`+((d.recent_posts||[]).length?`<ul>`+d.recent_posts.map(p=>`<li>${esc(p.title||('#'+p.id))} — <span class='muted'>${esc(p.status)}</span></li>`).join('')+`</ul>`:`<p class='muted'>Постов пока нет.</p>`)"
        "+`<h2>Next actions</h2><ul>`+(d.next_recommended_actions||[]).map(a=>`<li>${esc(a)}</li>`).join('')+`</ul></div>`;"
        # Карточки платформ (данные из dashboard.extra.platforms — без секрета).
        "const pl=(d.extra&&d.extra.platforms)||[];"
        "P.innerHTML= pl.length ? pl.map(p=>{"
        "const on=!!(p.external_id||p.url||p.has_api_key);"
        "const ref=esc(p.external_id||p.url||'');"
        "const pt=esc(p.platform_type);"
        "return `<div class='pcard'><h3>${esc(p.title||p.platform_type)} <span class='muted'>${pt}</span></h3>`"
        "+`<div class='meta'>${on?`<span class='pill ok'>настроено</span>`:`<span class='pill off'>не настроено</span>`} ${ref?('· '+ref):''}</div>`"
        "+`<div class='inline'>`"
        "+`<a href='/ui/projects/${PID}/settings'><button class='mini ghost'>Настройки</button></a>`"
        "+`<a href='/ui/projects/${PID}/platforms/${encodeURIComponent(p.platform_type)}/schedule'><button class='mini sec'>Расписание</button></a>`"
        "+`<a href='/ui/projects/${PID}/platforms/${encodeURIComponent(p.platform_type)}/schedule#preview'><button class='mini ghost'>Preview</button></a>`"
        "+`</div></div>`;}).join('')"
        ": `<div class='card muted'>Платформы не настроены. <a href='/ui/projects/${PID}/settings'>Добавьте платформу</a>.</div>`;"
        "json(document.getElementById('raw'),d);"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page(f"Дашборд проекта #{project_id}", body, script, active="projects")


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
  }catch(x){err(eEl,x)}
}
initSchedule();
"""


@router.get("/projects/{project_id}/platforms/{platform}/schedule", response_class=HTMLResponse)
def ui_platform_schedule(project_id: int, platform: str) -> HTMLResponse:
    platform = _safe_slug(platform)
    body = (
        f"<div class='inline'><a href='/ui/projects/{project_id}/dashboard'>"
        "<button class='sec mini'>← К дашборду</button></a></div>"
        "<div class='card'><div id='ctx' class='muted'>Загрузка…</div></div>"
        "<div class='card' id='preview'><h2>План публикаций</h2>"
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
    script = f"const PID={project_id};const PLATFORM={json.dumps(platform)};" + _SCHEDULE_JS
    return _page(f"Расписание · {platform}", body, script, active="projects")


# --------------------------------------------------------------------------- #
# Тарифы / Аналитика / Настройки (плейсхолдеры) и Биллинг                      #
# --------------------------------------------------------------------------- #


@router.get("/tariffs", response_class=HTMLResponse)
def ui_tariffs() -> HTMLResponse:
    body = (
        "<div class='grid'>"
        "<div class='pcard'><h3>Starter</h3><p class='meta'>Для старта: один проект, базовые платформы.</p></div>"
        "<div class='pcard'><h3>Pro</h3><p class='meta'>Больше проектов и платформ, приоритетная генерация.</p></div>"
        "<div class='pcard'><h3>Agency</h3><p class='meta'>Много аккаунтов/проектов, командная работа.</p></div>"
        "</div>"
        "<p class='muted'>Реальные платежи пока не подключены; пополнение тестовое во внутренних units. "
        "<a href='/ui/billing'>Тестовое пополнение →</a></p>"
    )
    return _page("Тарифы", body, "", active="tariffs")


@router.get("/analytics", response_class=HTMLResponse)
def ui_analytics() -> HTMLResponse:
    body = (
        "<div class='card'><h3>Аналитика</h3>"
        "<p class='muted'>Скоро: эффективность постов, расходы units, CTR, заявки.</p></div>"
    )
    return _page("Аналитика", body, "", active="analytics")


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
    body = (
        "<div class='card'><div id='bal' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:8px'>"
        "<button class='sec mini' onclick='refresh()'>Обновить баланс</button></div></div>"
        "<div class='card'><h2>Тестовое пополнение</h2>"
        "<label>Сумма (units)</label><input id='amount' type='number' min='1' value='100'>"
        "<label>Ключ идемпотентности (необязательно)</label><input id='idem' placeholder='например, topup-2026-07'>"
        "<div style='margin-top:12px'><button onclick='topup()'>Пополнить (тест)</button></div>"
        "<p class='muted'>Реальных платежей нет — пополнение во внутренних units (fake/manual).</p></div>"
        "<div id='error' class='err'></div><pre id='result'></pre>"
    )
    script = (
        "const eEl=document.getElementById('error');const B=document.getElementById('bal');"
        "async function refresh(){const a=needAccount(eEl);if(!a)return;try{"
        "const b=await api('GET','/billing/account/'+a+'/balance');"
        "B.innerHTML=`Аккаунт #${b.account_id}: <b>${b.balance_units}</b> ${esc(b.currency)} · тариф ${esc(b.tariff_plan_slug||'—')} · ${esc(b.status)}`;"
        "}catch(x){err(eEl,x)}}"
        "async function topup(){const a=needAccount(eEl);if(!a)return;"
        "const amt=parseInt(gv('amount'));if(!amt||amt<=0){err(eEl,new Error('Укажите сумму > 0.'));return}"
        "eEl.style.display='none';try{"
        "const body={amount_units:amt,description:'UI test top-up'};const k=gv('idem');if(k)body.idempotency_key=k;"
        "const e=await api('POST','/billing/account/'+a+'/manual-topup',body);"
        "json(document.getElementById('result'),e); refresh(); initShell();}catch(x){err(eEl,x)}}"
        "refresh();"
    )
    return _page("Биллинг", body, script, active="settings")
