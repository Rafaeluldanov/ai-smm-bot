# 25. SaaS: регистрация, аккаунты, проекты, онбординг и биллинг (v0.2.0)

CRM-конфигуратор «БОТ СММ» превращён в SaaS-платформу с личным кабинетом:
пользователь регистрируется, создаёт аккаунт (workspace), заводит проекты через
форму онбординга и пополняет депозит во внутренних units. CRM-интеграция
сохранена — внешняя CRM использует те же сервисы/модели.

## Как работает регистрация

`POST /auth/register` (email, password, full_name, account_name) создаёт:
- **User** — пароль хранится ТОЛЬКО как PBKDF2-хеш (`pbkdf2_sha256$…`), сырой
  пароль не сохраняется и не логируется (passlib/bcrypt в проекте нет — используется
  стандартная `hashlib`);
- **Account** (workspace) с уникальным slug;
- **AccountMembership** — владелец (`role=owner`).

Ответ — подписанный **dev-токен** (`<user_id>.<hmac>`) + профиль + аккаунты. Это
dev-заглушка авторизации (не продакшн-JWT). `POST /auth/login` и `GET /auth/me`
(с токеном в заголовке `Authorization`) — вход и текущий профиль.

## Как создаются проекты (онбординг)

`GET /saas/onboarding/form-schema` отдаёт JSON-схему формы (разделы: company,
project, keywords, media_sources, platforms, promotion_categories,
publishing_plans, billing).

`POST /saas/onboarding/preview` / `apply` (тело: `account_id`, `payload`,
`allow_live`) внутри **переиспользуют** `CrmBotSmmFormService.apply_onboarding_payload`
(валидация, идемпотентный upsert, маскировка секретов, принудительный
`live_enabled=false`). SaaS-слой добавляет:
- привязку созданного проекта к аккаунту (`projects.account_id`);
- провижининг биллинга (счёт + стартовое пополнение).

Один аккаунт → несколько проектов. `GET /saas/accounts/{account_id}/projects` —
список проектов аккаунта.

### Ресурсы, медиа-источники, расписание

- **Платформы** (`platforms`) → CRM-ресурсы: vk/telegram/instagram/youtube/rutube.
  Секрет (`api_key`) хранится зашифрованно, наружу отдаётся только маска/флаг
  наличия. `live_enabled` всегда false.
- **Медиа-источники** (`media_sources`) → CRM-источники контента: yandex_disk,
  google_drive, manual, upload, website, other.
- **Расписание** (`publishing_plans`) → CRM-планы: дни/время/платформы/режим
  (draft/semi_auto/auto_schedule). **auto_publish запрещён.**

## Депозит и usage units

Единица учёта — внутренние **units** (условные токены). Реальных платежей нет:
пополнение — только ручное (fake-провайдер).

- `GET /billing/account/{id}/balance` — баланс.
- `POST /billing/account/{id}/manual-topup` — пополнение (идемпотентно по
  `idempotency_key`).
- `GET /billing/account/{id}/ledger` — журнал операций (topup/debit/refund).
- `GET /billing/account/{id}/usage-events` — usage-события.
- `POST /billing/estimate` — оценка стоимости действия в units.

Стоимость действий (units): `ai_generation=10`, `image_processing=3`,
`media_selection=2`, `publication_preview=1`, `publication_live=5`, `analytics=1`.
Тариф (`TariffPlan`) задаёт `included_units` — при создании счёта они начисляются.

**Если баланса не хватает — действие не выполняется** (`InsufficientBalanceError`,
HTTP 402): генерация/публикация не запускаются.

### Прогон проекта с биллингом

- `POST /saas/projects/{id}/run-dry` (`account_id`, `category_id`) — **только
  оценка** units, без списания и без создания постов.
- `POST /saas/projects/{id}/run-semi-auto` — проверка баланса → безопасный
  semi_auto-прогон (посты уходят на **ревью**) → списание за созданные посты.
  Публикаций нет.

## Дашборд проекта

`GET /saas/projects/{id}/dashboard`: информация о проекте, число платформ/медиа-
источников/категорий/активных планов, недавние посты, посты на ревью, баланс
биллинга, рекомендованные действия.

## Что безопасно (safety)

- **Live-публикации выключены** (`*_LIVE_PUBLISHING_ENABLED=false`); даже с
  `allow_live` онбординг НЕ включает live (только фиксирует запрос предупреждением).
- **auto_publish** недоступен; `publish-due` в разработке/тестах не запускается.
- Секреты (токены платформ) наружу не возвращаются — только маска.
- **Платёжный провайдер — fake/manual**, реальных списаний денег нет.
- Все тесты offline (SQLite, fake, `httpx.MockTransport`).

## CRM-совместимость

- Эндпоинты `/crm/bot-smm/*` не изменены и работают.
- SaaS и CRM используют одни модели/сервисы; `projects.account_id` — **nullable**,
  поэтому старые seed/CRM-проекты остаются валидными (не привязаны к аккаунту).
- `crm_external_id` сохранён как внешний ключ для CRM.
- Тест `test_crm_compatibility.py` проверяет, что прежний CRM-пейлоад
  (`backend/examples/crm_bot_smm_onboarding_teeon.json`) по-прежнему
  превьюится/применяется идемпотентно.

## Токены (в .env, НЕ в docs)

Токены платформ вводятся в форме онбординга (`api_key`) и хранятся зашифрованно на
стороне ресурса, либо задаются в `.env` для боевых клиентов
(`TELEGRAM_BOT_TOKEN`, `VK_ACCESS_TOKEN`, …). В документации реальные значения не
приводятся.

## CLI и демо

```bash
# Схема SaaS-формы
make saas-form-schema

# Онбординг (нужен существующий account_id; сначала регистрация через API)
make saas-onboarding-preview account_id=1 payload_path=backend/examples/saas_onboarding_teeon.json
make saas-onboarding-apply   account_id=1 payload_path=backend/examples/saas_onboarding_teeon.json

# Биллинг
make billing-balance account_id=1
make billing-topup   account_id=1 units=500
```

Демо через API (offline, без реальных публикаций/платежей):

```bash
# 1. Регистрация → получить token + account_id
curl -sX POST localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"password123","account_name":"My WS"}'
# 2. Онбординг проекта (account_id из ответа)
curl -sX POST localhost:8000/saas/onboarding/apply \
  -H 'Content-Type: application/json' \
  -d '{"account_id":1,"payload":{...см. backend/examples/saas_onboarding_teeon.json...}}'
# 3. Дашборд и баланс
curl -s localhost:8000/saas/projects/1/dashboard
curl -s localhost:8000/billing/account/1/balance
```

## Модель данных (новые таблицы, миграция 0013)

`users`, `accounts`, `account_memberships`, `tariff_plans`, `billing_accounts`,
`billing_ledger_entries`, `usage_events` + колонка `projects.account_id` (nullable).
Применить: `make migrate` (alembic upgrade head).

## Личный кабинет / UI (v0.2.2)

Минимальный веб-кабинет — server-rendered HTML-страницы `/ui/*`
(`backend/app/api/ui.py`), без фронтенд-сборки и без новых зависимостей. Каждая
страница отдаёт самодостаточный HTML со встроенными CSS и vanilla-JS, который
обращается к тем же JSON-API (`/auth`, `/saas`, `/billing`).

Страницы:

| Путь | Назначение |
|------|-----------|
| `/ui/register` | Регистрация → сохраняет dev-токен и account_id в `localStorage` |
| `/ui/login` | Вход |
| `/ui/accounts` | `GET /auth/me`, выбор текущего аккаунта |
| `/ui/projects` | Список проектов аккаунта |
| `/ui/projects/new` | Форма онбординга: Preview / Apply |
| `/ui/projects/{id}/dashboard` | Дашборд проекта |
| `/ui/projects/{id}/settings` | Идемпотентное обновление конфигурации (повторный Apply) |
| `/ui/billing` | Баланс + тест-пополнение (`manual-topup`) |

Как работает авторизация: после `register`/`login` dev-токен кладётся в
`localStorage`; все запросы к защищённым endpoint-ам уходят с заголовком
`Authorization`. Ошибки показываются в отдельном блоке, ответы preview/apply —
как читаемый JSON.

Форма нового проекта повторяет разделы онбординга (company, project, keywords,
media_sources, platforms, promotion_categories, publishing_plans, billing) с
repeatable-секциями. Медиа-источники: `yandex_disk / google_drive / manual /
upload / website / other` (**Google Drive пока только сохраняется как источник,
без реальной интеграции**). Платформы: `vk / telegram / instagram / youtube /
rutube / other`.

Безопасность UI:

- поле `api_key` — `<input type=password autocomplete=off>`, **очищается после
  отправки** (секрет не показывается повторно; сервер возвращает только маску);
- `live_enabled` на форме **выключен (disabled) и всегда уходит `false`**;
- **автопубликация** не предлагается; режимы плана — `draft / semi_auto /
  auto_schedule`; все прогоны — только preview/dry-run;
- HTML статичен и **не содержит серверных секретов/токенов** (проверяется тестом);
- `publish-due` из UI не вызывается.

Запуск: `make run`, затем открыть `http://localhost:8000/ui/register`. Платежи —
fake/manual (units), реальных списаний нет.

## Личный кабинет v0.2.3

Кабинет переработан из «технической формы» в нормальный личный кабинет с общей
раскладкой (header + sidebar) на всех страницах после входа. Реализация та же:
server-rendered HTML `/ui/*` (`backend/app/api/ui.py`), без сборки и новых
зависимостей.

### Header (account state и баланс)

Общий верхний header есть на каждой странице. `initShell()` (в общем JS) при
наличии токена в `localStorage` вызывает `GET /auth/me`, а затем
`GET /billing/account/{account_id}/balance` для активного аккаунта (если
`account_id` не выбран — берётся первый из `/auth/me`).

- залогинен: справа — иконка пользователя, имя/email и баланс в units, по клику —
  dropdown **«Пополнить счёт»** (→ `/ui/billing`) и **«Выйти»** (очищает
  `localStorage` и ведёт на `/ui/login`);
- гость: кнопки **«Войти»** и **«Регистрация»**.

Метки dropdown рендерятся статически (JS лишь переключает видимость и подставляет
имя/баланс через `esc()`), поэтому доступны и без выполнения скрипта.

### Sidebar

Левая колонка на страницах кабинета: **Проекты / Тарифы / Аналитика / Настройки**.
В разделе «Проекты» `initShell()` загружает `GET /saas/accounts/{account_id}/projects`
и показывает список (каждый проект — ссылка на `/ui/projects/{id}/dashboard`),
кнопку **«+ Новый проект»**; если проектов нет — «Проектов нет. Создайте новый.».
После Apply нового проекта список в sidebar обновляется при следующем открытии.

### Страницы

| Путь | Назначение |
|------|-----------|
| `/ui/register`, `/ui/login` | Регистрация/вход → dev-токен + account_id в `localStorage` |
| `/ui/projects` | Список проектов аккаунта |
| `/ui/projects/new` | Упрощённая форма нового проекта: Preview / Создать проект |
| `/ui/projects/{id}/dashboard` | Дашборд проекта + карточки платформ |
| `/ui/projects/{id}/settings` | Идемпотентное обновление конфигурации (повторный Apply) |
| `/ui/projects/{id}/platforms/{platform}/schedule` | Планировщик расписания внутри платформы |
| `/ui/billing` | Баланс + тестовое пополнение (units, `manual-topup`) |
| `/ui/tariffs` | Тарифы (Starter / Pro / Agency) — плейсхолдер |
| `/ui/analytics` | Аналитика — плейсхолдер «Скоро…» |
| `/ui/settings`, `/ui/accounts` | Настройки аккаунта и переключение активного аккаунта |

### Упрощённая форма нового проекта

- **Компания**: название\*, описание, «Есть сайт», сайт/рекламируемый ресурс,
  тематика (если сайта нет), география, **«Стиль текстов»** (select: деловой /
  экспертный / дружелюбный / продающий / премиальный / простой и понятный).
- Блок «Проект» убран из основной формы. UI сам генерирует `project_name`
  (= название компании или введённое) и `project_slug` (латинский slug из
  названия). Ручные поля «Название проекта» и «Код проекта (slug)» спрятаны в
  секцию **«Дополнительно»** вместе с тарифом и стартовым пополнением.

### Массовый импорт ключевых слов

Вместо ввода по одному — textarea **«Вставьте ключевые запросы списком»** и кнопка
**«Разобрать ключи»**. Парсер разбивает строку по табу / `;` / `,` / пробелам;
если последний токен — число, это `frequency` (и `priority`), остальное — `query`,
`intent` по умолчанию `commercial`. Эвристики проставляют `product` (футболки,
худи, свитшоты, лонгсливы, кепки, жилетки, куртки, дождевики) и `technology`
(DTF-печать, вышивка, гравировка, УФ-печать, шелкография). Результат — редактируемая
таблица `query | frequency | product | technology | cluster | priority`. Есть импорт
из файла `.txt/.csv` через `FileReader` (файл читается в браузере, на сервер как
файл не отправляется — содержимое попадает в textarea и парсится).

### Платформы, медиа-источники, категории и расписание

- **Платформы** (можно несколько): название, тип (`vk/telegram/instagram/youtube/
  rutube/other`), `external_id`, `url`, `api_key` (secret), теги, ключи. Признак
  `live_enabled` показан как **`live: выкл`** — включаемого чекбокса в UI нет,
  на форму всегда уходит `live_enabled:false` («Живая публикация включается
  отдельно после проверки»).
- **Медиа-источники**: тип (Яндекс Диск / Google Drive / ручная загрузка / сайт /
  другое), название, ссылка, корневая папка, медиа-теги (Google Drive — без live).
- **Категории продвижения** размещены рядом с расписанием; если пользователь не
  создал ни одной — UI добавляет дефолтную **«Основное продвижение»**.
- **Расписание** собирается как план внутри выбранной платформы: дни недели
  (чекбоксы 0–6), время публикаций (`HH:MM`), постов в день, тег/категория, режим
  `draft/semi_auto`, даты начала/окончания. Маппится в `publishing_plans` с
  `timezone: Europe/Moscow`. Пояснение: «Без плана расписания бот ничего не
  публикует»; если тег не выбран — «бот сам выберет приоритет по частотности
  ключей».

### Дашборд проекта и карточки платформ

`GET /saas/projects/{id}/dashboard` дополнен полем `extra.platforms` — карточки
платформ **без секрета** (`platform_type`, `title`, `external_id`, `url`,
`has_api_key`-флаг, `live_enabled`). На дашборде: баланс, счётчики
(платформы/медиа/категории/планы/на ревью), последние посты, next actions и
секция **«Платформы»** с карточками (статус «настроено / не настроено» и кнопки
**Настройки / Расписание / Preview**).

### Preview / Apply

На форме — **Preview** (`POST /saas/onboarding/preview`, dry-run: показывает
проект, платформы, ключи, медиа, категории, планы, предупреждения, баланс) и
**Создать проект** (`POST /saas/onboarding/apply`, требует отметки «Принимаю
условия»). После Apply — переход на дашборд проекта.

### Безопасность UI (v0.2.3)

- `api_key` — `<input type=password autocomplete=off>`, **очищается после отправки**;
- **включаемого чекбокса `live_enabled` в UI нет** — всегда `false`;
  `auto_publish` не предлагается; все прогоны — preview/dry-run или на ревью;
- пользовательские значения (имена аккаунтов/проектов, теги, предупреждения)
  экранируются `esc()` перед вставкой в `innerHTML` (защита от stored XSS);
  path-параметр `platform` нормализуется в безопасный slug (защита от reflected XSS);
- HTML статичен и **не содержит серверных секретов/токенов** (проверяется тестом);
- **`publish-due` из UI не вызывается** и в HTML не встречается.

## Подключение VK через OAuth (v0.2.5)

VK-ресурс проекта подключается **кнопкой «Подключить VK»** на карточке платформы в
дашборде — без ручного копирования OAuth-ссылки и **без ключа сообщества для фото**.
Роутер — `backend/app/api/integrations_vk.py`, сервис — `app/services/vk_oauth_service.py`,
низкоуровневый HTTP-клиент — `app/integrations/vk/oauth.py` (сеть в тестах —
`httpx.MockTransport`).

Поток:

1. `GET /integrations/vk/oauth/start?account_id&project_id&resource_id` — проверяет,
   что ресурс существует, тип `vk` и принадлежит проекту/аккаунту, затем собирает
   подписанный `state` и редиректит (307) на `https://oauth.vk.com/authorize`
   (`client_id=VK_APP_ID`, `redirect_uri=VK_OAUTH_REDIRECT_URI`, `scope=
   wall,photos,groups,offline`, `response_type=code`, `state`).
2. Пользователь подтверждает доступ в VK.
3. `GET /integrations/vk/oauth/callback?code&state` — проверяет подпись `state`
   (HMAC), меняет `code` на **пользовательский** access-token через
   `https://oauth.vk.com/access_token` и сохраняет токен в **секрет ресурса**
   (`crm_secret_service` — шифрование-заглушка + маска). Наружу — только маска и
   `api_key_present`; токен/секрет приложения не логируются и не возвращаются.
4. Safe-check (без публикаций): `users.get`, `groups.get filter=admin`,
   `photos.getWallUploadServer`. Callback показывает HTML-результат: токен подключён,
   аккаунт видит/не видит группу, загрузка фото ok/ошибка. При VK `error_code=27` —
   «Это не user token или аккаунт не имеет нужных прав».
5. `GET /integrations/vk/status?resource_id` — статус без сети (маска + факт токена);
   `POST /integrations/vk/oauth/check?resource_id` — повторный safe-check (кнопка
   «Проверить доступ»).

`state` подписан HMAC (тот же источник секрета, что и dev-токен) — подделать
account/project/resource нельзя; `start`/`callback` не требуют dev-токена (их
вызывает браузер/редирект VK). Настройки: `VK_APP_ID`, `VK_APP_SECRET`,
`VK_OAUTH_REDIRECT_URI` (в `.env`; `.env.example` обновлён, значения — не в репозитории).
VK live-публикация остаётся **выключенной**; ключ сообщества для фото не используется.

### VK OAuth подключение через кабинет (v0.2.6)

Готовый UI-сценарий (приложение VK **AI SMM Bot**, `VK_APP_ID=54671660`,
redirect `http://127.0.0.1:8000/integrations/vk/oauth/callback`):

1. В VK ID приложении добавить этот Redirect URL в «Доверенные».
2. `make vk-oauth-env` — локальный мастер `app.scripts.setup_vk_oauth_env`: спрашивает
   `VK_APP_SECRET` через `getpass` (не печатает), пишет в `.env` `VK_APP_ID`,
   `VK_OAUTH_REDIRECT_URI`, `VK_APP_SECRET`, `VK_DEFAULT_GROUP_ID` (если пусто) и
   `VK_LIVE_PUBLISHING_ENABLED=false`. `VK_ACCESS_TOKEN` не трогается, live не включается,
   `.env` не коммитится (прочие строки сохраняются).
3. UI: дашборд проекта TEEON → карточка **VK** показывает App ID, Group ID
   (`resource.external_id`), Redirect URI, статус токена (маска), подсказку про
   `make vk-oauth-env`, если `vk_oauth_configured=false`. Кнопки **«Подключить VK»**
   (→ `/integrations/vk/oauth/start`) и **«Проверить доступ»** (→ `.../oauth/check`).
   Статус-эндпоинт `/integrations/vk/status` отдаёт `app_id`/`redirect_uri`/`group_id`/
   `configured`/маску — **без токена и без секрета приложения**.
4. Callback показывает «VK подключён · Можно закрыть окно и вернуться в проект» и
   результат safe-check (без токена).
5. При «Загрузка фото ✔» — `make vk-photo-test-preview`/`-apply`
   (`app.scripts.prepare_vk_photo_test`): проверяет VK-ресурс, наличие токена и
   safe-check; при недоступной загрузке фото (VK error 27) **пост не создаётся** с
   объяснением; иначе создаёт media-group пост по тегу «футболка» (`platform_target=vk`,
   `media_policy=media_group`, `needs_review`). Публикаций нет; live VK — только
   отдельной ручной командой после dry-run.

`vk_oauth_configured` (в `Settings`) — истина при заданных `VK_APP_ID` + `VK_APP_SECRET`
+ `VK_OAUTH_REDIRECT_URI`. Все тесты offline (сеть — `httpx.MockTransport`).

### Локальный HTTPS для VK OAuth (без туннелей, v0.2.6)

VK ID требует HTTPS redirect. Вместо cloudflared/ngrok — прямой локальный HTTPS
`https://localhost:8443` (по умолчанию `VK_OAUTH_REDIRECT_URI` указывает сюда):

1. `make local-https-cert` — `app.scripts.setup_local_https` генерирует self-signed
   сертификат `tmp/certs/localhost-cert.pem` + ключ (openssl, SAN `DNS:localhost,
   IP:127.0.0.1`); при отсутствии openssl — понятная ошибка. `tmp/` в `.gitignore`.
2. `make vk-oauth-local-https` — `app.scripts.setup_vk_oauth_local_https` пишет в `.env`
   `VK_APP_ID=54671660`, `VK_OAUTH_REDIRECT_URI=https://localhost:8443/integrations/vk/oauth/callback`,
   `VK_LIVE_PUBLISHING_ENABLED=false`, `VK_APP_SECRET` (getpass, не печатается),
   `VK_DEFAULT_GROUP_ID` (если пусто). `VK_ACCESS_TOKEN` не трогается. Отчёт —
   `tmp/vk_oauth_local_https_report.txt` (без секретов).
3. `make run-https-local` — uvicorn с `--ssl-keyfile/--ssl-certfile` на `127.0.0.1:8443`
   (если сертификата нет — подсказка `make local-https-cert`).
4. В VK ID: базовый домен `localhost`, Redirect URL
   `https://localhost:8443/integrations/vk/oauth/callback` (запасной — `127.0.0.1` /
   `https://127.0.0.1:8443/...`).
5. UI по `https://localhost:8443/ui/projects` (принять предупреждение браузера) → TEEON
   → VK-карточка показывает App ID, Group ID, Redirect URI, статус токена, инструкцию
   VK ID и подсказку про локальный сертификат → «Подключить VK» → «Проверить доступ».

Карточка VK предупреждает, если страница открыта по `http://127.0.0.1:8000`, а callback
настроен на `https://localhost:8443` («Откройте https://localhost:8443/ui/projects»).
VK live-публикация остаётся выключенной; фото — только через личный user-token.

### VK browser publisher fallback (dev/local, v0.2.7)

Временный обходной путь, пока нет рабочего VK OAuth user-token: публикация поста с
картинками через **локальную автоматизацию браузера** — `app.scripts.vk_browser_publish_post`,
**без VK API-токенов**. Скрипт берёт `Post` из БД и его `generation_notes.media_files`,
готовит картинки (локальная копия или публичная папка Яндекс Диска, HEIC→JPEG) в
`tmp/vk_browser_uploads/post_{id}/`, открывает VK через Playwright (persistent profile
`tmp/vk_browser_profile`), где **владелец логинится вручную** (логин/пароль не хранятся),
вставляет текст (`vk_text` → `telegram_text` → `title`) и прикрепляет файлы.

- `make vk-browser-install` — dev-установка Playwright + Chromium (не prod-зависимость;
  модуль импортируется и без Playwright, браузер поднимается лениво).
- `make vk-browser-publish-preview post_id=…` — **dry-run** (по умолчанию): пост
  подготовлен в браузере, публикация НЕ нажимается.
- `make vk-browser-publish-live post_id=…` — реальная публикация, только с
  `--confirm-live true`; при успехе пишется `PostPublication` (platform `vk`,
  status `published`, external_url — если удалось определить).

Это **dev/local инструмент владельца аккаунта, НЕ SaaS production flow** (production —
официальный OAuth user-token). Не использует VK API, не печатает токенов/секретов, не
просит `VK_ACCESS_TOKEN`, не включает live VK API. Все тесты offline (без браузера).

### VK API photo upload strategies (v0.2.8)

Календарная (полностью автоматическая) публикация VK-фото идёт **через API**, без OAuth-
браузера. Стратегии: **wall** (`photos.getWallUploadServer`/`saveWallPhoto`), **album**
(`photos.getUploadServer`/`photos.save` в альбом группы, ищется по `VK_PHOTO_ALBUM_TITLE`
или создаётся), **auto** (wall → album при `error 27`; настройка `VK_PHOTO_UPLOAD_STRATEGY`).

- `make vk-api-photo-probe` / `vk-api-photo-probe-upload` — какая стратегия работает с
  текущим `VK_ACCESS_TOKEN` (никогда не вызывает `wall.post`; токен не печатается).
- `make vk-photo-test-apply account_id=… project_slug=teeon tag=футболка` — создаёт
  media-group пост `needs_review` **только если** probe рекомендует стратегию; в
  `generation_notes.vk_photo_upload_strategy` пишется `wall|album`.
- Для `media_policy=media_group` неуспешная загрузка на live — `PublishError` (календарь
  не публикует пустой пост). Браузерный publisher (Докс/13) — не основной способ.

### Публичный HTTPS VK OAuth callback (v0.2.9)

Для полностью автоматической (календарной) публикации VK с картинками через API нужен
**пользовательский** VK-токен (community token даёт `error 27` на `photos.*`). Токен
подключается через публичный HTTPS OAuth callback:

- `PUBLIC_APP_URL` (напр. `https://app.teeon.ru`) → `VK_OAUTH_REDIRECT_URI` выводится
  автоматически как `PUBLIC_APP_URL + /integrations/vk/oauth/callback` (если не задан явно).
  `settings.vk_oauth_base_domain` — базовый домен для VK ID.
- В VK ID приложении: базовый домен `app.teeon.ru`, Redirect URL —
  `https://app.teeon.ru/integrations/vk/oauth/callback`. Подсказку без секретов даёт
  `make vk-oauth-setup-info` (также проверяет, что `VK_LIVE_PUBLISHING_ENABLED=false`).
- В UI проекта (карточка VK): App ID, Redirect URI, инструкция VK ID; кнопки
  «Подключить VK» (`/integrations/vk/oauth/start`) и «Проверить доступ»
  (`/integrations/vk/oauth/check`). Callback сохраняет user-token в секрет ресурса
  (наружу — только маска, токен не печатается). Safe-check различает user/group token по
  `users.get` / `groups.get filter=admin` / `photos.getWallUploadServer`; при провале —
  «Токен не пользовательский или аккаунт не имеет прав администратора/редактора группы.»

### Botfleet UI: бренд, тема и гайд подключения (v0.2.10)

SaaS-кабинет (`backend/app/api/ui.py`, server-rendered HTML без сборки/CDN) получил
продуктовый вид:

- **Бренд Botfleet** в header (слева) и вверху sidebar, с временным **inline
  SVG-логотипом** (ядро + орбитальные узлы, «флот ботов»/нейро-орбита), цвета — через
  CSS-переменные, подпись «ИИ-флот для автопостинга».
- **Светлая/тёмная тема**: переключатель в header; выбор в
  `localStorage['botfleet_theme']` (`light|dark`), применяется через `data-theme` на
  `<html>`; при первом входе — `prefers-color-scheme`. JS: `getTheme()/applyTheme()/
  toggleTheme()/initTheme()`. Тёмная тема — clean dark (почти чёрный фон, тёмно-серые
  карточки). Все элементы адаптируются через CSS-переменные (`--bg/--surface/
  --surface-soft/--text/--muted/--border/--accent/--accent-soft/--danger/--success/
  --shadow/--input-bg/--button-bg`).
- **Sidebar**: Проекты (список + «+ Новый проект») / Тарифы / Аналитика / **Гайд** /
  Настройки; активный пункт подсвечивается.
- **Раздел «Гайд»** (`/ui/guide`, алиасы `/ui/help`, `/ui/onboarding-guide`) — «Как
  подключиться к Botfleet»: быстрый старт (8 шагов), поля проекта, подключение
  Telegram/VK/Яндекс Диска, как работают ключи и расписание, безопасность, FAQ.

Что важно из гайда: **live-публикации не включаются автоматически**; **секреты
скрываются** (только маска); **VK с картинками требует корректный user-token / публичный
OAuth** (community-token может публиковать только text-only); **Telegram media group**
можно проверять отдельно в dry-run при настроенном канале. Внешних CDN нет, секреты в
HTML не встраиваются, live-флаги из UI не включаются.

## Подключение платформ в Botfleet: Instagram + расширенный гайд (v0.2.11)

- **Карточка Instagram на дашборде** (`/ui/projects/{id}/dashboard`): статус (Не
  подключено / Токен сохранён / **live выключен**), справочные поля **Instagram App ID**,
  **Instagram App Secret**, **Redirect URI**, **Access Token**, **Instagram User ID**,
  напоминание про обязательный публичный `image_url`. App Secret и Access Token
  показываются **только маской** («секрет сохранён (скрыт)» / «не задан») — реальные
  значения из `.env` в HTML не попадают. Кнопки: «Проверить настройки» (локальная
  проверка `IG_CFG` **без вызовов Meta API**), «Открыть гайд Instagram», «Скопировать
  Redirect URI». Кнопки живой публикации нет.
- **Расширенный гайд** (`/ui/guide`): якорные разделы Telegram (BotFather, `chat not
  found`), VK (`user-token`, `error 27`, публичный HTTPS-домен), Instagram (Professional,
  `Facebook Page` → `Meta Developer` → Graph API, «Instagram API with Instagram Login`»,
  App ID/Secret/Redirect/Token/User ID, `media` + `media_publish`, публичный `image_url`),
  Яндекс Диск и медиа, Расписание, Будущие подключения (YouTube, RuTube, Google Drive,
  media-proxy, Аналитика — planned), Безопасность, FAQ.
- **Instagram dry-run preview**: `preview_publication` для постов с фото проставляет
  `needs_public_image_url`/`would_prepare_media` и предупреждение про публичный HTTPS
  `image_url`. Реальных вызовов Instagram/Meta API нет; live-клиент бросает `PublishError`.
- **Конфиг**: `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_REDIRECT_URI`,
  `INSTAGRAM_USER_ID` (в `.env.example` и `config.py`); Redirect URI выводится из
  `PUBLIC_APP_URL`, если не задан. Миграций нет.

## Продуктовый UX: платформы, расписания, юнит-экономика, аналитика (v0.2.12)

Личный кабинет приведён к продуктовой логике SaaS. Полное описание —
[26_Botfleet_SaaS_UX_платформы_расписания_аналитика.md](26_Botfleet_SaaS_UX_платформы_расписания_аналитика.md).

- **Рабочие области платформ** (`/ui/projects/{id}/platforms/{platform}`) с вкладками
  Обзор/Настройки/Гайд/Расписание/Preview/Аналитика. VK OAuth и Instagram-карточка
  переехали с дашборда в раздел платформы.
- **Чистый дашборд**: «Проект: {имя}», кнопки (Настройки / Создать платформу / Создать
  расписание), сетка кликабельных карточек площадок, компактная «Активность». Sidebar
  подсвечивает активный проект.
- **Задачи расписания**: каждый `CrmPublishingPlan` — отдельная карточка (дни/время/тег/
  режим/статус/стоимость units/следующая дата) с безопасными кнопками. Отдаются в
  `dashboard.extra.schedule_tasks` (без новой миграции).
- **Гайды**: общий `/ui/guide` — обзорный + ссылки; подробные инструкции на
  `/ui/guide/{platform}` и во вкладке платформы.
- **Юнит-экономика** (`unit_economics_service.py`): units из токенов провайдера × наценка
  с порогом; цены в `config.py`/`.env`. Правила списаний: успех/идемпотентность/не в
  минус; dry-run бесплатно. Витрина — `/ui/tariffs`.
- **Безопасность**: guard-функции tenant-изоляции (`saas_security_service.py`); чек-лист
  в Докс/26; секреты только маска; live off; rate-limit/audit — TODO.
- **Аналитика** (`/ui/analytics`, `analytics_planning_service.py`): фильтры (проект/
  платформа/период/глубина), календарь, оценка стоимости отчёта в units, метрики (ER,
  CTR, reach…). Офлайн-демо, без внешних API.

## Аналитика постов и платежи (v0.2.13)

- **Аналитика постов** (light/standard/deep = 10/20/40 units за пост): анализ контента,
  estimated-метрики, рекомендации, календарь, ручной ввод метрик (0 units). Списание —
  идемпотентно, 402 при нехватке. Источник метрик всегда указан.
- **Платежи (Россия)**: счета через провайдеров (mock реально; yookassa/tbank/
  cloudpayments — sandbox; robokassa — planned), методы карта/СБП/QR/счёт для ИП-ООО,
  профиль плательщика (ИНН/КПП/ОГРН). Баланс пополняется только после `paid`
  (mock-pay/webhook), идемпотентно. `PAYMENTS_LIVE_ENABLED=false` — реальных денег нет.
  Миграция 0014. Подробно — [27_Botfleet_аналитика_и_платежи.md](27_Botfleet_аналитика_и_платежи.md).

## Безопасность и tenant-изоляция (v0.3.1)

HTTP-гарды изолируют tenant'ы: аутентифицированный пользователь видит только свои
аккаунты/проекты (чужие → 404), в production анонимный доступ → 401. Billing-профиль и
ручное пополнение — только owner/admin. Аудит-лог (`GET /audit/account/{id}`) и редакция
секретов. Подробно — [28_Botfleet_SaaS_безопасность.md](28_Botfleet_SaaS_безопасность.md).

## Production auth / сессии (v0.3.2)

Регистрация/логин теперь создают серверную сессию и выдают access-токен (тело) +
refresh-cookie (HttpOnly). Добавлены `/auth/refresh` (ротация), `/auth/logout`,
`/auth/logout-all`, `/auth/sessions`. В production dev-токен запрещён, авторизация
обязательна, cookies Secure. Подробно —
[29_Botfleet_Production_Auth_Sessions.md](29_Botfleet_Production_Auth_Sessions.md).

## Обновление v0.3.6: self-service подключение платформ

Клиент подключает площадки сам в личном кабинете (форма токен/ID), **без `.env`**: секреты
шифруются и хранятся в проекте (`CrmSmmResource`, миграция 0018), наружу — только маска.
Бот использует credentials проекта, а не глобальные env. Есть безопасная проверка
подключения и автоматический журнал действий. Подробно —
[33_Botfleet_Self_Service_Platform_Connections.md](33_Botfleet_Self_Service_Platform_Connections.md).

## Обновление v0.3.7: media proxy (публичные image_url)

Для Instagram (и площадок, которым нужен публичный `image_url`) добавлен media-proxy:
`PublicMediaLink` (миграция 0019) + временные ссылки `/media/public/{token}` (raw-токен не
хранится, только sha256; срок/отзыв; HEIC→JPEG; content-type/размер ограничены). Живая
публикация Instagram выключена. Подробно —
[34_Botfleet_Media_Proxy_Public_Image_URL.md](34_Botfleet_Media_Proxy_Public_Image_URL.md).
