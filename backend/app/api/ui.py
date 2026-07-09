"""Минимальный SaaS-личный кабинет (server-rendered HTML, без сборки/зависимостей).

Каждая страница ``/ui/*`` — самодостаточный HTML со встроенными CSS и vanilla-JS,
который обращается к существующим JSON-API (``/auth``, ``/saas``, ``/billing``).
Dev-токен хранится в ``localStorage`` и отправляется в заголовке ``Authorization``.

Безопасность UI:
- ``api_key`` вводится в ``<input type=password>`` и очищается после отправки —
  секрет не показывается повторно; сервер возвращает только маску;
- ``live_enabled`` на форме выключен и всегда уходит ``false``; auto_publish не
  предлагается; все действия — только preview/apply (dry-run/безопасно);
- HTML статичен и НЕ содержит серверных секретов/токенов.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/ui", tags=["ui"])

_CSS = """
:root{--bg:#0f1115;--card:#181b22;--fg:#e6e6e6;--muted:#9aa4b2;--accent:#4f8cff;--err:#ff6b6b;--ok:#3ecf8e;--border:#2a2f3a}
@media (prefers-color-scheme: light){:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1a1a;--muted:#666;--border:#e2e5ea}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
nav{display:flex;gap:14px;flex-wrap:wrap;align-items:center;padding:12px 20px;background:var(--card);border-bottom:1px solid var(--border)}
nav a{color:var(--accent);text-decoration:none}nav a:hover{text-decoration:underline}nav .sp{flex:1}
.container{max-width:920px;margin:24px auto;padding:0 20px}
h1{font-size:22px}h2{font-size:17px;margin-top:26px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;margin:14px 0}
label{display:block;margin:8px 0 4px;color:var(--muted);font-size:13px}
input,select,textarea{width:100%;padding:8px 10px;background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:7px;font:inherit}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;align-items:center;border:1px dashed var(--border);border-radius:8px;padding:10px;margin:8px 0}
.row input,.row select{width:100%}
button{background:var(--accent);color:#fff;border:0;border-radius:7px;padding:9px 14px;font:inherit;cursor:pointer}
button.sec{background:transparent;color:var(--accent);border:1px solid var(--accent)}
button.mini{padding:4px 8px;font-size:13px}
.muted{color:var(--muted);font-size:13px}
.err{display:none;background:rgba(255,107,107,.12);border:1px solid var(--err);color:var(--err);padding:10px;border-radius:8px;margin:10px 0;white-space:pre-wrap}
pre{display:none;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;overflow:auto;max-height:420px;white-space:pre-wrap;word-break:break-word}
.inline{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.badge{display:inline-block;background:var(--border);border-radius:6px;padding:2px 8px;font-size:12px;color:var(--muted)}
"""

_NAV = (
    "<nav><a href='/ui/'>SMM SaaS</a>"
    "<a href='/ui/projects'>Проекты</a>"
    "<a href='/ui/projects/new'>Новый проект</a>"
    "<a href='/ui/accounts'>Аккаунты</a>"
    "<a href='/ui/billing'>Биллинг</a>"
    "<span class='sp'></span>"
    "<a href='/ui/login'>Войти</a>"
    "<a href='#' onclick='logout();return false'>Выйти</a></nav>"
)

# Общие JS-помощники (fetch с Authorization, хранение токена, вывод ошибок/JSON).
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
function err(el,e){el.textContent=String(e&&e.message?e.message:e);el.style.display='block'}
function json(el,o){el.textContent=JSON.stringify(o,null,2);el.style.display='block'}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function gv(id){const el=document.getElementById(id);if(!el)return '';return el.type==='checkbox'?el.checked:el.value.trim()}
function gl(id){const v=gv(id);return v?String(v).split(',').map(s=>s.trim()).filter(Boolean):[]}
function needAccount(el){const a=parseInt(acc());if(!a){err(el,new Error('Сначала выберите аккаунт на /ui/accounts (или зарегистрируйтесь).'));return 0}return a}
"""


def _page(title: str, body: str, script: str = "") -> HTMLResponse:
    """Собрать самодостаточную HTML-страницу кабинета."""
    html = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title} — SMM SaaS</title><style>{_CSS}</style></head><body>"
        f"{_NAV}<main class='container'><h1>{title}</h1>{body}</main>"
        f"<script>{_SHARED_JS}</script><script>{script}</script></body></html>"
    )
    return HTMLResponse(html)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ui_index() -> HTMLResponse:
    body = (
        "<div class='card'>Минимальный личный кабинет «Бот СММ». "
        "Реальных платежей нет (units), live-публикации выключены, все прогоны — dry-run.</div>"
        "<div class='card inline'>"
        "<a href='/ui/register'><button>Регистрация</button></a>"
        "<a href='/ui/login'><button class='sec'>Вход</button></a>"
        "<a href='/ui/projects/new'><button class='sec'>Новый проект</button></a>"
        "</div><p class='muted' id='who'></p>"
    )
    script = (
        "(async()=>{try{if(tok()){const me=await api('GET','/auth/me');"
        "document.getElementById('who').textContent='Вы вошли как '+me.user.email+' · аккаунтов: '+me.accounts.length;}"
        "}catch(e){}})();"
    )
    return _page("Личный кабинет", body, script)


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
    return _page("Регистрация", body, script)


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
    return _page("Вход", body, script)


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
        "L.innerHTML=me.accounts.map(a=>`<div class='inline' style='margin:6px 0'>`"
        "+`<span class='badge'>#${a.id}</span> <b>${esc(a.name)}</b> <span class='muted'>(${esc(a.slug)})</span>`"
        "+` <button class='mini' onclick='setAcc(${a.id});location.href=\"/ui/projects\"'>Выбрать</button></div>`).join('');"
        "const cur=acc(); if(cur) L.innerHTML+=`<p class='muted'>Текущий аккаунт: #${cur}</p>`;"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Аккаунты", body, script)


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
        "if(!ps.length){L.textContent='Проектов нет. Создайте новый.';return}"
        "L.innerHTML=ps.map(p=>`<div class='inline' style='margin:6px 0'>`"
        "+`<span class='badge'>#${p.id}</span> <b>${esc(p.name)}</b> <span class='muted'>(${esc(p.slug)})</span>`"
        "+` <a href='/ui/projects/${p.id}/dashboard'><button class='mini sec'>Дашборд</button></a>`"
        "+` <a href='/ui/projects/${p.id}/settings'><button class='mini sec'>Настройки</button></a></div>`).join('');"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page("Проекты", body, script)


# --- Форма создания/настройки проекта (repeatable-секции на vanilla-JS) --- #

_FORM_JS = r"""
function tpl(kind){
  if(kind==='keywords') return "<div class='row'>"
    +"<input name='query' placeholder='запрос *'>"
    +"<input name='product' placeholder='продукт'>"
    +"<input name='technology' placeholder='технология'>"
    +"<input name='cluster' placeholder='кластер'>"
    +"<input name='priority' type='number' placeholder='приоритет' value='0'>"
    +"<select name='intent'><option>commercial</option><option>informational</option><option>brand</option><option>process</option><option>price</option></select>"
    +"<button type='button' class='mini sec' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='media_sources') return "<div class='row'>"
    +"<select name='source_type'><option>yandex_disk</option><option>google_drive</option><option>manual</option><option>upload</option><option>website</option><option>other</option></select>"
    +"<input name='title' placeholder='название'>"
    +"<input name='url' placeholder='URL'>"
    +"<input name='root_folder' placeholder='корневая папка'>"
    +"<input name='media_tags' placeholder='медиа-теги через запятую'>"
    +"<button type='button' class='mini sec' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='platforms') return "<div class='row'>"
    +"<select name='platform_type'><option>vk</option><option>telegram</option><option>instagram</option><option>youtube</option><option>rutube</option><option>other</option></select>"
    +"<input name='title' placeholder='название'>"
    +"<input name='api_key' type='password' autocomplete='off' placeholder='API ключ/токен (секрет)'>"
    +"<input name='external_id' placeholder='ID (group/channel)'>"
    +"<input name='url' placeholder='URL'>"
    +"<input name='tags' placeholder='теги через запятую'>"
    +"<input name='keywords' placeholder='ключи через запятую'>"
    +"<label class='muted' title='Живые публикации выключены на этом этапе'><input type='checkbox' disabled> live (выкл)</label>"
    +"<button type='button' class='mini sec' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='categories') return "<div class='row'>"
    +"<input name='title' placeholder='название категории *'>"
    +"<input name='keyword_queries' placeholder='ключи (запросы) через запятую'>"
    +"<input name='product_priorities' placeholder='приоритеты продуктов: футболка:5, худи:3'>"
    +"<input name='media_tags' placeholder='медиа-теги через запятую'>"
    +"<input name='resource_titles' placeholder='платформы (по названию) через запятую'>"
    +"<input name='cta' placeholder='призыв к действию'>"
    +"<button type='button' class='mini sec' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  if(kind==='plans') return "<div class='row'>"
    +"<input name='category_title' placeholder='категория (по названию)'>"
    +"<input name='platforms' placeholder='платформы через запятую (telegram,vk)'>"
    +"<input name='weekdays' placeholder='дни 0-6 через запятую'>"
    +"<input name='posts_per_day' type='number' value='1'>"
    +"<input name='publish_times' placeholder='время HH:MM через запятую'>"
    +"<select name='mode'><option>draft</option><option>semi_auto</option><option>auto_schedule</option></select>"
    +"<button type='button' class='mini sec' onclick='this.closest(\".row\").remove()'>✕</button></div>";
  return '';
}
function addRow(id){const c=document.getElementById(id);c.insertAdjacentHTML('beforeend',tpl(id));}
function rows(id){return [...document.querySelectorAll('#'+id+' .row')];}
function rv(r,n){const el=r.querySelector('[name="'+n+'"]');return el?String(el.value).trim():'';}
function rl(r,n){const v=rv(r,n);return v?v.split(',').map(s=>s.trim()).filter(Boolean):[]}
function kvparse(s){const o={};(s||'').split(',').map(x=>x.trim()).filter(Boolean).forEach(p=>{const i=p.indexOf(':');if(i>0){o[p.slice(0,i).trim()]=parseInt(p.slice(i+1).trim())||0}});return o}
function buildPayload(){
  return {
    company:{company_name:gv('company_name'),business_description:gv('business_description'),
      has_website:gv('has_website'),website_url:gv('website_url')||null,
      manual_topics:gl('manual_topics'),geography:gl('geography'),brand_tone:gv('brand_tone')},
    project:{project_slug:gv('project_slug'),project_name:gv('project_name'),default_site_url:gv('default_site_url')||null},
    keywords:rows('keywords').map(r=>({query:rv(r,'query'),product:rv(r,'product')||null,technology:rv(r,'technology')||null,
      cluster:rv(r,'cluster'),priority:parseInt(rv(r,'priority'))||0,intent:rv(r,'intent')||'commercial'})).filter(k=>k.query),
    media_sources:rows('media_sources').map(r=>({source_type:rv(r,'source_type'),title:rv(r,'title'),url:rv(r,'url')||null,
      root_folder:rv(r,'root_folder')||null,media_tags:rl(r,'media_tags')}))
      .filter(m=>m.title||m.url||m.root_folder||m.media_tags.length),
    platforms:rows('platforms').map(r=>({platform_type:rv(r,'platform_type'),title:rv(r,'title'),api_key:rv(r,'api_key')||null,
      external_id:rv(r,'external_id')||null,url:rv(r,'url')||null,live_enabled:false,tags:rl(r,'tags'),keywords:rl(r,'keywords')}))
      .filter(p=>p.title||p.api_key||p.external_id||p.url||p.tags.length||p.keywords.length),
    promotion_categories:rows('categories').map(r=>({title:rv(r,'title'),keyword_queries:rl(r,'keyword_queries'),
      product_priorities:kvparse(rv(r,'product_priorities')),media_tags:rl(r,'media_tags'),
      resource_titles:rl(r,'resource_titles'),cta:rv(r,'cta')})).filter(c=>c.title),
    publishing_plans:rows('plans').map(r=>({category_title:rv(r,'category_title')||null,platforms:rl(r,'platforms'),
      weekdays:rl(r,'weekdays').map(Number),posts_per_day:parseInt(rv(r,'posts_per_day'))||1,
      publish_times:rl(r,'publish_times'),mode:rv(r,'mode')||'draft'}))
      .filter(p=>p.category_title||p.platforms.length||p.publish_times.length||p.weekdays.length),
    billing:{tariff_plan_slug:gv('tariff_plan_slug')||null,
      starting_topup_amount:parseInt(gv('starting_topup_amount'))||null,accept_terms:gv('accept_terms')},
  };
}
async function submitOnboarding(kind){
  const eEl=document.getElementById('error');const rEl=document.getElementById('result');
  const a=needAccount(eEl);if(!a)return;
  try{
    const payload=buildPayload();
    const res=await api('POST','/saas/onboarding/'+kind,{account_id:a,payload});
    json(rEl,res);
    // Безопасность: очищаем секреты из формы после отправки (не показываем повторно).
    document.querySelectorAll('input[name=\"api_key\"]').forEach(i=>i.value='');
    if(kind==='apply' && res.project_id){
      rEl.textContent='Проект создан (#'+res.project_id+'). Открываю дашборд…\n'+rEl.textContent;
      setTimeout(()=>location.href='/ui/projects/'+res.project_id+'/dashboard',1200);
    }
  }catch(x){err(eEl,x)}
}
"""


def _project_form_body(readonly_slug: str | None) -> str:
    slug_attr = f" value='{readonly_slug}' readonly" if readonly_slug else ""
    return (
        "<div class='card'><h2>Компания</h2>"
        "<label>Название компании *</label><input id='company_name'>"
        "<label>Описание бизнеса</label><textarea id='business_description'></textarea>"
        "<label><input id='has_website' type='checkbox'> Есть сайт</label>"
        "<label>Адрес сайта</label><input id='website_url' placeholder='https://…'>"
        "<label>Темы (если нет сайта), через запятую</label><input id='manual_topics'>"
        "<label>География, через запятую</label><input id='geography'>"
        "<label>Тон бренда</label><input id='brand_tone'></div>"
        "<div class='card'><h2>Проект</h2>"
        f"<label>Код проекта (slug) *</label><input id='project_slug'{slug_attr}>"
        "<label>Название проекта</label><input id='project_name'>"
        "<label>Ссылка по умолчанию</label><input id='default_site_url'></div>"
        "<div class='card'><h2>Ключевые слова</h2><div id='keywords'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"keywords\")'>+ ключ</button></div>"
        "<div class='card'><h2>Медиа-источники</h2>"
        "<p class='muted'>Google Drive пока только сохраняется как источник (без интеграции).</p>"
        "<div id='media_sources'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"media_sources\")'>+ источник</button></div>"
        "<div class='card'><h2>Платформы</h2>"
        "<p class='muted'>Секрет (api_key) не возвращается и очищается после отправки. Live-публикация выключена.</p>"
        "<div id='platforms'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"platforms\")'>+ платформа</button></div>"
        "<div class='card'><h2>Категории продвижения</h2><div id='categories'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"categories\")'>+ категория</button></div>"
        "<div class='card'><h2>Расписание публикаций</h2>"
        "<p class='muted'>Автопубликация недоступна. Все прогоны — только preview/semi-auto на ревью.</p>"
        "<div id='plans'></div>"
        "<button type='button' class='sec mini' onclick='addRow(\"plans\")'>+ план</button></div>"
        "<div class='card'><h2>Биллинг</h2>"
        "<label>Тариф (slug)</label><input id='tariff_plan_slug' placeholder='starter'>"
        "<label>Стартовое пополнение (units)</label><input id='starting_topup_amount' type='number' placeholder='0'>"
        "<label><input id='accept_terms' type='checkbox'> Принимаю условия (обязательно для Apply)</label></div>"
        "<div class='card inline'>"
        "<button type='button' class='sec' onclick='submitOnboarding(\"preview\")'>Preview (dry-run)</button>"
        "<button type='button' onclick='submitOnboarding(\"apply\")'>Apply</button></div>"
        "<div id='error' class='err'></div><pre id='result'></pre>"
    )


@router.get("/projects/new", response_class=HTMLResponse)
def ui_project_new() -> HTMLResponse:
    init = (
        "['keywords','media_sources','platforms','categories','plans'].forEach(addRow);"
        "const eEl=document.getElementById('error');if(!acc()){eEl.style.display='block';"
        "eEl.textContent='Аккаунт не выбран — зарегистрируйтесь или выберите на /ui/accounts.';}"
    )
    return _page("Новый проект", _project_form_body(None), _FORM_JS + init)


@router.get("/projects/{project_id}/dashboard", response_class=HTMLResponse)
def ui_project_dashboard(project_id: int) -> HTMLResponse:
    body = (
        "<div class='inline'>"
        f"<a href='/ui/projects/{project_id}/settings'><button class='sec mini'>Настройки</button></a></div>"
        "<div class='card'><div id='dash' class='muted'>Загрузка…</div></div>"
        "<div id='error' class='err'></div><pre id='raw'></pre>"
    )
    script = (
        f"const PID={project_id};"
        "const eEl=document.getElementById('error');const D=document.getElementById('dash');"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        "D.innerHTML=`<h2>${esc(d.project_name)} <span class='muted'>(${esc(d.project_slug)})</span></h2>`"
        "+`<p><span class='badge'>платформы: ${d.platforms_count}</span> `"
        "+`<span class='badge'>медиа-источники: ${d.media_sources_count}</span> `"
        "+`<span class='badge'>категории: ${d.categories_count}</span> `"
        "+`<span class='badge'>активные планы: ${d.active_plans_count}</span> `"
        "+`<span class='badge'>на ревью: ${d.posts_needing_review}</span> `"
        "+`<span class='badge'>баланс: ${d.billing_balance_units==null?'—':d.billing_balance_units} units</span></p>`"
        "+`<h2>Рекомендации</h2><ul>`+ (d.next_recommended_actions||[]).map(a=>`<li>${esc(a)}</li>`).join('') +`</ul>`;"
        "json(document.getElementById('raw'),d);"
        "}catch(x){err(eEl,x)}})();"
    )
    return _page(f"Дашборд проекта #{project_id}", body, script)


@router.get("/projects/{project_id}/settings", response_class=HTMLResponse)
def ui_project_settings(project_id: int) -> HTMLResponse:
    body = (
        "<p class='muted'>Обновление конфигурации — идемпотентный повторный онбординг: "
        "введите конфигурацию заново и нажмите Apply (перезапишет настройки проекта; "
        "slug зафиксирован). Live-публикации выключены.</p>"
        "<div class='card'><div id='cur' class='muted'>Текущее состояние…</div></div>"
        + _project_form_body(readonly_slug="")  # slug заполняется из проекта в JS
    )
    script = (
        f"const PID={project_id};"
        "const eEl=document.getElementById('error');"
        "(async()=>{try{const d=await api('GET','/saas/projects/'+PID+'/dashboard');"
        "document.getElementById('cur').innerHTML=`<b>${esc(d.project_name)}</b> (${esc(d.project_slug)}) · `"
        "+`платформы ${d.platforms_count}, категории ${d.categories_count}, баланс ${d.billing_balance_units==null?'—':d.billing_balance_units} units`;"
        "const s=document.getElementById('project_slug'); if(s){s.value=d.project_slug;s.readOnly=true;}"
        "const n=document.getElementById('project_name'); if(n)n.value=d.project_name;"
        "}catch(x){err(eEl,x)}})();"
        # Форма стартует с пустыми строками секций — конфигурацию нужно ввести заново
        # для обновления (полного read-back конфигурации на этом этапе нет).
        "['keywords','media_sources','platforms','categories','plans'].forEach(addRow);"
    )
    return _page(f"Настройки проекта #{project_id}", body, _FORM_JS + script)


@router.get("/billing", response_class=HTMLResponse)
def ui_billing() -> HTMLResponse:
    body = (
        "<div class='card'><div id='bal' class='muted'>Загрузка…</div>"
        "<div class='inline' style='margin-top:12px'>"
        "<button class='sec' onclick='refresh()'>Обновить баланс</button>"
        "<button onclick='topup()'>Тест-пополнение +100 units</button></div>"
        "<p class='muted'>Реальных платежей нет — пополнение во внутренних units (fake/manual).</p></div>"
        "<div id='error' class='err'></div><pre id='result'></pre>"
    )
    script = (
        "const eEl=document.getElementById('error');const B=document.getElementById('bal');"
        "const rEl=document.getElementById('result');"
        "async function refresh(){const a=needAccount(eEl);if(!a)return;try{"
        "const b=await api('GET','/billing/account/'+a+'/balance');"
        "B.innerHTML=`Аккаунт #${b.account_id}: <b>${b.balance_units}</b> ${esc(b.currency)} · тариф ${esc(b.tariff_plan_slug||'—')} · ${esc(b.status)}`;"
        "}catch(x){err(eEl,x)}}"
        "async function topup(){const a=needAccount(eEl);if(!a)return;try{"
        "const e=await api('POST','/billing/account/'+a+'/manual-topup',{amount_units:100,description:'UI test top-up'});"
        "json(rEl,e); refresh();}catch(x){err(eEl,x)}}"
        "refresh();"
    )
    return _page("Биллинг", body, script)
