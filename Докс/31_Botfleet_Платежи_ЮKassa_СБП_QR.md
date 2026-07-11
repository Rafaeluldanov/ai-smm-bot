# 31. Botfleet: платежи для России — ЮKassa, СБП, QR, счета ИП/ООО (v0.3.4)

Документ описывает платёжный контур Botfleet для России: внутреннюю валюту units, методы
оплаты (карта / СБП / QR / счёт ИП / счёт ООО), mock- и sandbox-провайдеров, жизненный
цикл счёта, идемпотентность вебхуков и защиту от двойного пополнения, а также чек-лист
перед подключением боевого эквайринга.

> **Реальные платежи ВЫКЛЮЧЕНЫ** (`PAYMENTS_LIVE_ENABLED=false` по умолчанию). Это
> sandbox/mock-этап: реальные деньги не списываются, сеть к платёжным API не вызывается
> (`PAYMENTS_PROVIDER_HTTP_ENABLED=false`). Данные банковской карты Botfleet **не
> собирает и не хранит** — карта вводится только на стороне провайдера.

## 1. Цель платёжного контура

Дать клиенту (физлицо / ИП / ООО) понятный способ пополнить баланс в units и прозрачные
правила списаний, при этом:

- не хранить данные карт (PCI-периметр — на стороне провайдера);
- пополнять баланс строго после подтверждённой оплаты (`paid`), ровно один раз;
- быть идемпотентным к повторным вебхукам и повторной mock-оплате;
- изолировать счета по аккаунтам (чужой счёт нельзя увидеть/оплатить).

## 2. units (внутренняя валюта)

- 1 unit ≈ 1 ₽ — ориентировочный курс для MVP-учёта (`BILLING_UNIT_PRICE_RUB`).
- Стоимость действия в units считается из реальных токенов AI-провайдера с наценкой ×2
  (`BILLING_MARKUP_MULTIPLIER`); порог — минимальная стоимость действия.
- Комиссия эквайринга (ЮKassa/СБП) **пока не входит** в цену units и будет показываться
  отдельно после подключения провайдера.
- НДС/налоги и бухгалтерия оформляются позже с бухгалтером и юристом.

Пополнение: `POST /billing/account/{id}/invoices` → счёт (не меняет баланс) → оплата →
`paid` → зачисление units (`manual_topup` с ключом `invoice-{id}-paid`, идемпотентно).

## 3. Методы оплаты

| Метод | Значение | Кому | Что нужно в профиле |
|-------|----------|------|---------------------|
| Банковская карта | `bank_card` | все | email (для чека) |
| СБП | `sbp` | все | email |
| QR-код | `qr` | все | email |
| Счёт для ИП | `invoice_for_ip` | ИП | ИНН, наименование/ФИО, email (ОГРНИП опц.) |
| Счёт для ООО | `invoice_for_company` | ООО | ИНН, юр. наименование, email (КПП опц.) |
| Ручное (admin) | `manual_admin_topup` | админ | — (CLI/админ) |

Готовность реквизитов под метод проверяет `BillingProfileService`
(`backend/app/services/billing_profile_service.py`): `validate_profile_for_method`,
`profile_ready_for_invoice`, `mask_profile`, `readiness`. Эндпоинт
`GET /billing/account/{id}/profile/readiness` отдаёт чипы готовности для UI.

### Карта / СБП / QR

Карта вводится **только у провайдера**. Для СБП/QR провайдер формирует QR-код; до
подключения sandbox/live UI показывает текстовый `qr_payload` (mock/sandbox) и кнопку
«Скопировать payload».

### Счёт ИП / ООО

Формируется по реквизитам плательщика (`BillingProfile`: ИНН/КПП/ОГРН/ОГРНИП/юр. имя/
email/телефон). Если реквизитов не хватает — UI показывает предупреждение «нужны
реквизиты».

## 4. Жизненный цикл счёта

```
draft → pending → paid       (оплачен, баланс пополнен один раз)
                → canceled    (отменён, баланс не меняется)
                → failed      (неуспех, баланс не меняется)
                → expired     (просрочен, баланс не меняется)
```

Константы: `PAYMENT_STATUS_*` (`payment_provider.py`). Инварианты:

- создание счёта **не** пополняет баланс;
- `paid` пополняет **один раз** (идемпотентно по ключу счёта);
- `failed/canceled/expired` **не** пополняют;
- сумма счёта **неизменяема после pending** (`set_invoice_amount` — только в `draft`);
- дубликат `paid`-вебхука/повтор mock-pay **не** пополняет второй раз.

Транзакции (`PaymentTransaction.status`): `pending | succeeded | failed | canceled |
refunded`. Журнал вебхуков (`PaymentWebhookLog.status`): `received | processed | ignored
| failed`.

## 5. Mock-провайдер (sandbox-flow)

Всегда доступен, без сети и денег. `create_invoice` возвращает `provider_payment_id`,
`payment_url`, `qr_payload` (для sbp/qr), `status=pending`. Управление статусом:

- `POST /billing/invoices/{id}/mock-pay` → `paid` + зачисление (идемпотентно);
- `POST /billing/invoices/{id}/mock-fail` → `failed` (без зачисления);
- `POST /billing/invoices/{id}/mock-cancel` → `canceled`;
- `POST /billing/invoices/{id}/mock-expire` → `expired`.

Все эндпоинты требуют гард доступа к счёту (`require_invoice_access`): чужой счёт → 404.
Mock-pay доступен только в local/sandbox.

## 6. YooKassa (ЮKassa) sandbox-adapter

`backend/app/services/payments/yookassa_payment_service.py`. **Боевой HTTP не
реализован** — реальные вызовы стоят за `PAYMENTS_PROVIDER_HTTP_ENABLED` (default false):
при включённом флаге провайдер честно бросает ошибку, а не имитирует платёж.

- `YOOKASSA_SANDBOX_ENABLED=true` → детерминированный fake-счёт без сети
  (`provider_payment_id=yoo_sandbox_…`, `payment_url`, `qr_payload` для sbp/qr).
- `build_yookassa_payment_payload(invoice, method, customer)` → санитизированный payload:
  `amount.value` (строка, 2 знака), `currency=RUB`, `capture=true`,
  `confirmation.type=redirect` + `return_url`, `description`, `metadata`
  (account_id/invoice_id/amount_units), `payment_method_data.type` (bank_card/sbp).
- Секреты (`YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_SECRET`) в payload/лог/UI не попадают.
- Вебхук: подпись (`X-Yookassa-Signature`, HMAC-SHA256, placeholder). Без webhook-секрета
  вебхук не доверенный; в production недоверенный вебхук → **HTTP 403**.

Конфиг: `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_SECRET`,
`YOOKASSA_RETURN_URL`, `YOOKASSA_CONFIRMATION_TYPE=redirect`.

## 7. T-Bank / CloudPayments / Robokassa (planned)

Скелеты провайдеров (`tbank`, `cloudpayments`, `robokassa`): `create_invoice` доступен
только при соответствующем `*_SANDBOX_ENABLED=true`, иначе — понятная ошибка. Live не
реализован. Секреты из конфига не логируются.

## 8. Идемпотентность и защита вебхуков

Эндпоинт `POST /billing/webhooks/{provider}`:

- неизвестный провайдер → 400;
- **недоверенная подпись**: production → 403; local/mock → вебхук не обрабатывается
  (лог `status=failed`), без пополнения;
- дубликат по `provider_event_id` (событие уже `processed`) → `ignored`, без пополнения;
- дубликат `paid` по уже оплаченному счёту → идемпотентно, без второго зачисления;
- payload сохраняется санитизированным (без секретов/подписей).

Миграция `0017_payment_webhook_hardening` добавляет в `payment_webhook_logs`:
`provider_event_id`, `status`, `processed_at`, `error_message` (SQLite/PostgreSQL).

## 9. Защита от бесплатного использования

- пополнение — только после `paid`;
- платные действия проверяют баланс (`ensure_balance`/`debit_for_action`), при нехватке
  действие не выполняется (402); dry-run/preview бесплатны;
- создание счёта и `failed`-оплата не дают units;
- изоляция: чужой счёт нельзя оплатить/просмотреть.

## 10. Возвраты (planned)

`PaymentRefundResult` и `refund_or_compensate` заложены; провайдерские возвраты будут
реализованы вместе с боевым подключением (частичный/полный refund → `TX_STATUS_REFUNDED`).

## 11. Юридический / бухгалтерский чек-лист

- [ ] оферта, политика конфиденциальности, условия оплаты — вывести из черновиков
      (`/ui/legal/offer`, `/privacy`, `/payments`) с юристом;
- [ ] фискализация (54-ФЗ): чеки формирует провайдер, проверить передачу email/receipt;
- [ ] НДС/налоговый режим, учёт комиссии эквайринга в цене units;
- [ ] договор с провайдером и реквизиты юрлица Botfleet.

## 12. Что нужно перед боевым запуском платежей

- [ ] договор с провайдером (ЮKassa/банк), shop/merchant id;
- [ ] webhook URL (HTTPS) + проверка подписи (`YOOKASSA_WEBHOOK_SECRET`);
- [ ] успешный **sandbox-прогон** оплаты и вебхука;
- [ ] реализованный боевой HTTP-клиент + аккуратное включение
      `PAYMENTS_PROVIDER_HTTP_ENABLED` и `PAYMENTS_LIVE_ENABLED`;
- [ ] бухгалтерия/налоги/оферта/privacy/terms/payment policy готовы;
- [ ] мониторинг платежей и алерты по несоответствиям баланса.

> `PAYMENTS_LIVE_ENABLED=false` — единственный «главный рубильник»: пока он выключен,
> все счета остаются mock/sandbox и реальные деньги не двигаются.
