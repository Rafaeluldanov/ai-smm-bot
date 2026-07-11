# 33. Botfleet: self-service подключение платформ (v0.3.6)

Клиент **не трогает `.env`**. Все площадки подключаются прямо в личном кабинете: клиент
вводит токен/ID в форму, секреты сохраняются зашифрованно, показывается только маска, а
бот использует credentials **проекта** (не глобальные env-переменные). Все действия
логируются автоматически.

> Live-публикации и боевые платежи по-прежнему выключены. Проверка подключения безопасна
> (read-only) и по умолчанию офлайн — реальные вызовы внешних API не выполняются.

## 1. `.env` — только для системных дефолтов

`.env` теперь используется только для: системных production-секретов, fallback/dev
credentials, глобальных feature-flags и server config. **Клиентские платформы хранятся в
БД** (`crm_smm_resources`) на уровне project/account.

## 2. Где хранятся подключения

Модель `CrmSmmResource` (одна запись на project + platform_key). Миграция **0018**
добавила поля подключения:

- `resource_type` = platform_key (telegram/vk/instagram/yandex_disk/website/…);
- основной токен площадки — `api_key_encrypted` (+ `api_key_masked`);
- `app_id` (несекретный), `app_secret_encrypted` (+ `app_secret_masked`);
- `external_id`, `url`, `yandex_public_url`, `yandex_root_folder`, `tags`;
- `status`, `last_check_at`, `last_check_status`, `last_check_message`;
- `resource_metadata` (redirect_uri, default_cta и др. несекретные параметры);
- `live_enabled=false` по умолчанию (защита от случайной публикации).

Секреты шифруются через `crm_secret_service` и **никогда** не возвращаются наружу — только
маска (`••••1234`) и факт наличия.

## 3. Как подключить в UI

Откройте проект → карточку площадки → вкладка **«Настройки»** → блок **«Подключение»**:

- **Telegram** — Bot token (из @BotFather) + Channel username/id.
- **VK** — Access token + Group ID (+ опц. App ID / App Secret / Redirect URI для OAuth).
- **Instagram** — Access token + Instagram User ID (+ опц. App ID / App Secret).
- **Яндекс Диск** — публичная ссылка + root folder + теги.
- **Сайт** — URL + CTA.

Кнопки: **Сохранить**, **Проверить подключение**, **Отключить**. Секретные поля
write-only: значение не отображается; чтобы не менять сохранённый секрет — оставьте поле
пустым. Для planned-площадок форма показана, но подключение/публикация выключены.

## 4. Проверка подключения (safe checks)

`platform_connection_check_service` — только READ-ONLY, ничего не публикует:

- **Telegram**: getMe → getChat → getChatMember (бот-админ с правом постить). «chat not
  found» объясняется понятно.
- **VK**: groups.getById → users.get (тип токена) → groups.get filter=admin. Ошибка **27**
  = токен не пользовательский/без прав `photos.*`.
- **Instagram**: GET `/{ig-user-id}?fields=id,username`. Нужен публичный HTTPS image_url.
- **Яндекс Диск**: валидация публичной ссылки + опц. доступность.
- **Сайт**: валидация URL + опц. HEAD/GET.
- **Planned**: статус `planned` (интеграция в разработке).

Результат: `ok | warning | error | planned`, список проверенных пунктов, что именно
проверено, какие права нужны и что делать при ошибке. По умолчанию проверка **офлайн**
(валидация полей и подсказки); онлайн-проба возможна с внедрённым HTTP-клиентом (в тестах
— `httpx.MockTransport`, без реальной сети).

## 5. Автоматические логи (audit)

Логи создаются **автоматически** (клиент их не заполняет):
`platform.connection.created/updated/secret.updated/checked/check.failed/deleted`, а также
schedule/preview/publication/analytics/billing. В workspace платформы есть блок **«Журнал
действий»** (последние 20 событий проекта по площадке): действие, время, статус — **без
секретов** (метаданные санитизируются).

API логов: `GET /projects/{id}/platform-connections/{platform_key}/logs`.

## 6. Публикация использует credentials проекта

При публикации креды резолвятся в порядке:

1. **`project_connection`** — подключение платформы данного проекта (БД);
2. **`env_fallback`** — глобальные `.env`-креды, **только в local** (dev-совместимость);
3. **`missing`** — понятная ошибка «Платформа не подключена в проекте. Откройте платформу
   и заполните API/ID.»

Токен другого проекта использовать нельзя (поиск строго по `project_id`). Токен **никогда**
не попадает в payload/preview/raw/ошибки — наружу отдаётся только `credentials_source` и
`token_present`. Dry-run/preview показывает источник кредов, но не сам токен.

## 7. Безопасность и tenant-изоляция

- Секреты шифруются, наружу — только маска/факт наличия.
- Все роуты под `require_project_access`: чужой проект недоступен.
- `live_enabled` из UI всегда остаётся `false` (защита от случайной публикации).
- Проверки read-only; ничего не публикуется и не пишется на площадки.

## 8. API подключений

- `GET /projects/{id}/platform-connections` — список (маски).
- `GET /projects/{id}/platform-connections/{platform_key}` — подключение + схема формы.
- `GET …/{platform_key}/schema` — поля/шаги/предупреждения.
- `POST …/{platform_key}` — создать/обновить (секреты write-only).
- `POST …/{platform_key}/check` — безопасная проверка (офлайн).
- `DELETE …/{platform_key}` — отключить (soft delete).
- `GET …/{platform_key}/logs` — журнал действий.

## 9. Что дальше

- OAuth-потоки per client (VK ID / Meta) вместо ручного ввода токена;
- media-proxy для публичных `image_url` (Instagram/Pinterest/CMS) —
  реализован в [34_Botfleet_Media_Proxy_Public_Image_URL.md](34_Botfleet_Media_Proxy_Public_Image_URL.md);
- движок автоматизации расписаний использует эти подключения (креды проекта) —
  [35_Botfleet_Schedule_Automation_Engine.md](35_Botfleet_Schedule_Automation_Engine.md);
- production secrets manager (KMS/Fernet) вместо dev-кодирования секретов;
- реальные метрики платформенных API;
- онлайн-проверки подключения за явным флагом в проде.
