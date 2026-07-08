# 21. CRM-форма «БОТ СММ» (Onboarding / Configurator)

Слой конфигурации, который позволяет человеку из **внешней CRM** во вкладке
**«БОТ СММ»** заполнить форму и подключить проект к AI-SMM-боту: сайт/темы,
ресурсы продвижения, ключевые слова, источники контента, категории продвижения
и план публикаций — а затем безопасно запустить `semi_auto`/`dry-run`.

CRM — внешняя неизвестная система, поэтому бэкенд отдаёт **JSON-схему формы** и
набор REST-эндпоинтов. Любая CRM отрисовывает форму по схеме и вызывает API.

> С версии **v0.2.0** этот же конфигуратор переиспользуется SaaS-личным кабинетом
> (`/saas/onboarding/*`): регистрация, аккаунты, привязка проекта к аккаунту и
> биллинг во внутренних units. CRM-эндпоинты `/crm/bot-smm/*` не изменены;
> `projects.account_id` — nullable, поэтому CRM-интеграция полностью сохранена.
> См. [25_SaaS_регистрация_проекты_биллинг.md](25_SaaS_регистрация_проекты_биллинг.md).

> **Безопасность (главное).** Ни один сценарий не публикует реальные посты и не
> включает live VK/Telegram. Режим `auto_publish` запрещён. Секрет ресурса
> (`api_key`) хранится зашифрованно и **никогда** не возвращается через API —
> наружу отдаются только `api_key_present` и `api_key_masked`.

---

## 1. Как CRM открывает форму

1. CRM запрашивает схему формы:
   `GET /crm/bot-smm/form-schema` → `BotSmmFormSchema` (разделы и поля).
2. CRM рисует форму по разделам (`sections`) и полям (`fields`): у поля есть
   `type` (`text`/`textarea`/`url`/`bool`/`number`/`select`/`multiselect`/`list`/
   `keyvalue`/`time`/`date`/`secret`), `required`, `required_if`, `options`,
   `default`, `help`.
3. Черновик формы сохраняется в бэкенде:
   `POST /crm/bot-smm/onboarding-drafts` с телом `{ "payload": { ... } }`.
4. Пользователь дозаполняет форму: `PATCH /crm/bot-smm/onboarding-drafts/{id}`.
5. Проверка: `POST /crm/bot-smm/onboarding-drafts/{id}/validate`.
6. Превью (dry-run, без записи): `POST /crm/bot-smm/onboarding-drafts/{id}/preview`.
7. Применение: `POST /crm/bot-smm/onboarding-drafts/{id}/apply?dry_run=false`.

---

## 2. Разделы формы

| Раздел | Ключ | Назначение |
| --- | --- | --- |
| Проект | `project` | slug, название, отображаемое имя, ID в CRM |
| Сайт или тематика | `site_or_topics` | сайт **или** темы/референсы, если сайта нет |
| Ресурсы продвижения | `resources` | VK / Telegram / Instagram / YouTube / RuTube / Яндекс Диск / сайт / другое |
| Ключевые слова | `keywords` | SEO-запросы для контент-плана |
| Источники контента | `content_sources` | откуда брать медиа |
| Категории продвижения | `promotion_categories` | связка ключей, приоритетов, медиа-тегов |
| План публикаций | `publishing_plan` | расписание, платформы, режим |
| Проверка и превью | `review_and_preview` | валидация, превью, безопасный запуск |

Разделы `resources`, `keywords`, `content_sources`, `promotion_categories`,
`publishing_plan` — **повторяемые** (`repeatable=true`). У `resources` и
`promotion_categories` — `min_items=1`.

### Поля разделов (кратко)

- **project**: `slug` (обязателен, латиница), `name`, `display_name`
  (обязателен), `crm_external_id`.
- **site_or_topics**: `has_website`, `website_url` (обязателен при
  `has_website==true`), `manual_topics` (обязателен при `has_website==false`),
  `reference_sites`, `business_description`, `geography`, `brand_tone`,
  `forbidden_phrases`, `required_review`.
- **resources**: `resource_type`, `title`, `api_key` (secret), `external_id`,
  `url`, `yandex_public_url`, `yandex_root_folder`, `tags`, `keywords`,
  `live_enabled` (по умолчанию `false`).
- **keywords**: `query`, `frequency`, `cluster`, `product`, `technology`,
  `intent`, `priority`.
- **content_sources**: `source_type`, `title`, `url`, `root_folder`,
  `allowed_folders`, `media_tags`.
- **promotion_categories**: `title`, `description`, `resource_titles`,
  `keyword_queries`, `product_priorities`, `technology_priorities`,
  `media_tags`, `default_site_url`, `cta`, `tone`, `require_review`.
- **publishing_plan**: `category_title`, `weekdays` (0=Пн…6=Вс),
  `posts_per_day`, `publish_times` (HH:MM), `platforms`, `mode`
  (`draft`/`semi_auto`/`auto_schedule`; `auto_publish` недоступен),
  `start_date`, `end_date`, `timezone`.

---

## 3. Что и как создаётся при apply

`apply?dry_run=false` детерминированно создаёт/обновляет записи (публикаций нет):

1. **Проект** (`projects`): по `slug` (создаётся или обновляется `website_url`).
2. **Конфигурация** (`crm_bot_project_configs`): один конфиг на проект.
3. **Ресурсы** (`crm_smm_resources`): `live_enabled` принудительно `false`,
   секрет кодируется и не возвращается.
4. **Ключи** (`crm_keywords`).
5. **Источники контента** (`crm_content_sources`).
6. **Категории** (`crm_promotion_categories`): ключи/ресурсы связываются по
   человекочитаемым значениям (`keyword_queries` → `keyword_ids`,
   `resource_titles` → `resource_ids`).
7. **Планы публикаций** (`crm_publishing_plans`): привязка к категории по
   `category_title`; `auto_publish` отсеян валидацией.

`dry_run=true` (по умолчанию) ничего не пишет — возвращает `CrmPreviewResult`
с тем, что **будет** создано.

### Идемпотентность (apply можно запускать повторно)

`apply?dry_run=false` **идемпотентен**: повторный запуск с тем же пейлоадом
**не создаёт дубли** — существующие записи находятся по ключу и обновляются на
месте. Ключи идемпотентности:

| Сущность | Ключ поиска |
| --- | --- |
| `CrmBotProjectConfig` | `project_id` (или `crm_external_id`) |
| `CrmSmmResource` | `config_id` + `resource_type` + `title` |
| `CrmKeyword` | `config_id` + `query` |
| `CrmContentSource` | `config_id` + `source_type` + `title` + `url` |
| `CrmPromotionCategory` | `config_id` + `title` |
| `CrmPublishingPlan` | `config_id` + `category_id` (или + расписание, если планов несколько на категорию) |

- Изменённые в пейлоаде поля **обновляют** существующие записи (без роста
  количества).
- Пустой/`null` `api_key` при повторном apply **не затирает** уже сохранённый
  секрет; непустой `api_key` — заменяет его.
- `dry_run=true` по-прежнему ничего не пишет.

---

## 4. Подключение ресурсов

- **VK**: `resource_type="vk"`, нужен `external_id` (group_id, напр. `240102732`)
  **или** `url`. Токен — в поле `api_key` (хранится зашифрованно).
- **Telegram**: `resource_type="telegram"`, канал в `external_id` (`@channel`),
  токен бота — в `api_key`.
- **Instagram / YouTube / RuTube**: `resource_type="instagram"|"youtube"|"rutube"`,
  токен — в `api_key`, аккаунт/канал — в `external_id`. Live-публикация пока
  реализована как adapter-скелет (dry-run/preview), см.
  [24_Мультиплатформенная_публикация_медиа.md](24_Мультиплатформенная_публикация_медиа.md).
  `resource_type` — обычная строка (миграция БД не требуется).
- **Яндекс Диск**: `resource_type="yandex_disk"`, обязателен `yandex_public_url`
  (публичная ссылка на папку), опционально `yandex_root_folder`.
- **Сайт**: `resource_type="website"`, `url`.

Проверка ресурса — **безопасная**, без сети и без печати секрета:
`POST /crm/bot-smm/resources/{id}/test-connection` c телом
`{ "test_connection": true }`. VK `groups.getById` возможен только в реальной
среде; здесь выполняется offline dry-run (`performed=false`).

---

## 5. Ключи и график

- Ключевые слова задают SEO-семантику: из них и приоритетов категории строится
  **контент-план** (`POST /crm/bot-smm/categories/{id}/preview-plan?days=30`).
- Каждый день плана содержит тему, SEO-запрос, продукт/технологию, **ссылку на
  сайт** и медиа-тег.
- График: `weekdays` (0..6), `posts_per_day`, `publish_times` (HH:MM),
  `platforms` (`telegram`/`vk`), `timezone` (по умолчанию `Europe/Moscow`).
- `posts_per_week` для прогона выводится как `posts_per_day × число дней недели`.

---

## 6. Почему dry-run и semi_auto безопасны

- **dry-run** (`run-dry`): выполняет план шагов, но **не создаёт** темы/посты и
  ничего не публикует.
- **semi_auto** (`run-semi-auto`): создаёт посты и отправляет их на ревью
  (`needs_review`), но **не публикует** и не планирует (`allow_auto_publish=false`,
  `allow_auto_schedule=false`, `require_human_review=true`).
- **live publish выключен по умолчанию**: реальные публикации VK/Telegram
  включаются только флагами окружения (`VK_LIVE_PUBLISHING_ENABLED`,
  `TELEGRAM_LIVE_PUBLISHING_ENABLED`), которые по умолчанию `false`. На этом
  этапе конфигуратор их не трогает.
- `auto_publish` запрещён и на уровне схемы (`disabled_modes`), и валидацией.

---

## 7. Подключение новых пользователей/клиентов

1. Клиент открывает вкладку «БОТ СММ» в CRM — форма рисуется по `form-schema`.
2. Заполняет проект, сайт/темы, ресурсы, ключи, категории, график.
3. `validate` → `preview` → `apply?dry_run=false`.
4. Проверяет контент-план категории (`preview-plan`).
5. Запускает `run-dry`, затем `run-semi-auto` — посты уходят на ревью.
6. После ручного согласования (вне этого слоя) и явного включения live-флагов
   возможна публикация — но это отдельный, осознанный шаг.

Для каждого клиента — **свой проект и своя конфигурация**; данные изолированы по
`project_id`/`config_id`.

---

## 8. Вторая группа (сувенирка)

Архитектура готова ко второму проекту без изменения кода:

- есть preset-профиль `fabric-souvenirs` (см. `seo_content_sources.py`) —
  используется как основа, если slug совпадает;
- новый клиент **без сайта** → строится временный SEO-профиль из
  `manual_topics`/`reference_sites` и ключей (метод
  `build_seo_profile_from_config`);
- при появлении сайта `website_url` становится главным источником ссылок.

Достаточно повторить онбординг для второй группы: создать проект (`slug`),
указать ресурсы (VK-группа сувенирки, Яндекс Диск), ключи и категории — код
переиспользуется полностью.

---

## 9. API (сводка)

| Метод | Путь | Назначение |
| --- | --- | --- |
| GET | `/crm/bot-smm/form-schema` | Схема формы |
| POST | `/crm/bot-smm/onboarding-drafts` | Создать черновик |
| GET | `/crm/bot-smm/onboarding-drafts/{id}` | Получить черновик |
| PATCH | `/crm/bot-smm/onboarding-drafts/{id}` | Обновить черновик |
| POST | `/crm/bot-smm/onboarding-drafts/{id}/validate` | Валидация |
| POST | `/crm/bot-smm/onboarding-drafts/{id}/preview` | Превью (dry-run) |
| POST | `/crm/bot-smm/onboarding-drafts/{id}/apply?dry_run=true` | Применить |
| GET | `/crm/bot-smm/projects/{project_id}/config` | Конфигурация проекта |
| PATCH | `/crm/bot-smm/projects/{project_id}/config` | Обновить конфигурацию |
| POST | `/crm/bot-smm/resources/{id}/test-connection` | Безопасная проверка |
| POST | `/crm/bot-smm/categories/{id}/preview-plan?days=30` | Контент-план |
| POST | `/crm/bot-smm/categories/{id}/run-dry` | Сухой прогон |
| POST | `/crm/bot-smm/categories/{id}/run-semi-auto` | Semi-auto (needs_review) |
| GET | `/crm/bot-smm/categories/{id}/run-preview` | Превью прогона |

---

## 10. CLI и Makefile

```bash
# Схема формы (без БД)
make crm-form-schema

# Валидация онбординга (без БД)
make crm-onboarding-validate payload_path=backend/examples/crm_bot_smm_onboarding_teeon.json

# Превью онбординга (dry-run)
make crm-onboarding-preview payload_path=backend/examples/crm_bot_smm_onboarding_teeon.json

# Применить онбординг (создаёт записи; требует БД)
make crm-onboarding-apply payload_path=backend/examples/crm_bot_smm_onboarding_teeon.json

# Контент-план категории на N дней (требует БД)
make crm-category-plan category_id=1 days=30
```

Пример безопасного пейлоада: `backend/examples/crm_bot_smm_onboarding_teeon.json`
(без реальных токенов — `api_key: null` или `"PASTE_IN_CRM_SECRET_FIELD"`).

---

## 11. Модель данных (миграция `0011_crm_bot_smm_configurator`)

`crm_bot_project_configs`, `crm_smm_resources`, `crm_keywords`,
`crm_content_sources`, `crm_promotion_categories`, `crm_publishing_plans`,
`crm_onboarding_drafts`. Секрет ресурса — в `api_key_encrypted`
(сервисный слой `crm_secret_service`, сейчас заглушка; TODO: KMS/Fernet).
