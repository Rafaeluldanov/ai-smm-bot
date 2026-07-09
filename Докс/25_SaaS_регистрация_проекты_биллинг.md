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
