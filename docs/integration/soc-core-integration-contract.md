# Контракт интеграции: SOAR ⇄ SOC Core Control (IRP)

**Версия:** 0.1-draft — на утверждение команде SOC Core
**Дата:** 2026-07-05
**Стороны:** SOAR (orchestrator, этот репозиторий) и SOC Core Control (`soc_bot`, ветка `feature/v2-frontend`)

---

## 1. Цель и принципы

Встроить SOAR в экосистему SOC Core для законченного цикла прохождения инцидента:
детект → триаж → инцидент → реагирование → закрытие, по современным стандартам:

- **Прозрачность** — каждое автоматическое решение (дроп, эскалация, действие на инфраструктуре)
  журналируется и видно аналитику в UI SOC Core.
- **Предсказуемость** — политики триажа и реагирования версионируются (git), поведение
  воспроизводимо; бэкфилл даёт тот же результат, что живая обработка.
- **Никаких тихих действий** — потеря/пропуск алерта невозможны молча: отказ любого компонента
  превращается в *видимую задержку*, а не в потерю данных.
- **Границы ответственности** — см. §2; ни одна сторона не пишет в БД другой стороны напрямую,
  только через API.

## 2. Границы ответственности

| Домен | Владелец | Комментарий |
| --- | --- | --- |
| Детект (SIEM-правила, sigma, источники в ES) | SOC Core | без изменений |
| UEBA (детекторы, скоринг, baseline, пороги, decay) | SOC Core | **SOAR не участвует**; UEBA-ветка `correlator → create_or_merge_alert` остаётся как есть |
| Ingestion + триаж SIEM-алертов (ES → обогащение → вердикт → гейты → Inbox) | **SOAR** | переносится из `bot/pipeline.py` / `soar_workflows/wf_siem_alert.py` в workflow оркестратора (§4) |
| IRP: Alert Inbox, инциденты, статусы, аудит, RBAC, UI | SOC Core | мастер жизненного цикла алерта/инцидента |
| Response-автоматизация (действия на инфраструктуре, плейбуки реагирования) | **SOAR** | триггерится событиями IRP (§5), результаты пишет обратно через API (§6) |
| Политики триажа (whitelist/blacklist/пороги/critical assets) | SOC Core (config.json — источник правды) | SOAR читает через API, не дублирует |

Модуль `soar_workflows/` в SOC Core фиксируется как ingestion-прослойка и **не развивается
в сторону response** (устраняется двухдвижковая проблема legacy/SOAR-путей: канонический
пайплайн становится один — на стороне SOAR).

## 3. Схема потоков

```
ПОТОК 1 (SOAR → IRP): доставка SIEM-алертов
  ES ──pull 60s──> SOAR orchestrator (триаж-workflow) ──POST /api/v2/alerts/ingest──> Alert Inbox

ПОТОК 2 (IRP → SOAR): события жизненного цикла
  create_or_merge_alert() / transition_incident() ──webhook (fire-and-forget)──> SOAR
  покрывает ВСЕ источники: SIEM (наши), UEBA, дайджест, watchlist, ручные

ПОТОК 3 (SOAR → IRP): writeback реагирования
  комментарии / response steps / переходы статусов ──существующее API v2──> alert_history

ПОТОК 4 (health): SOAR ──heartbeat──> Redis SOC Core ──watchdog-правило──> алерт в Inbox
```

## 4. Поток 1 — ingestion SIEM-алертов (переносится в SOAR)

### 4.1. Что делает SOAR

Workflow `wf_alert_triage` (порт логики `wf_siem_alert.py` + legacy `process_group`):

1. **Pull из ES** по расписанию (60 с), агрегация групп rule×host — как текущий
   `ElasticAlertConnector.fetch_alert_groups`.
2. **Триаж** — каждый шаг журналируется с результатом и причиной (run journal оркестратора):
   whitelist-проверка, CVE-верификация через Wazuh, blacklist/critical-asset эскалация,
   порог отсечения, TI-обогащение (AbuseIPDB/OTX/VT), расчёт вердикта.
   **Дроп — это тоже журналируемое решение** («дропнут: whitelist», «отсечён: count 2 < порог 3»),
   а не молчаливый `continue`.
3. **Доставка** в Alert Inbox через ingest-эндпоинт (§4.2).
4. UEBA-скоринг по SIEM-алерту: вызывается **только если** ingest вернул `action=created`
   (защита от двойного начисления при повторной обработке). Механизм вызова — п. открытых
   вопросов (§9, В-3).

### 4.2. Требуется от SOC Core: ingest-эндпоинт

`POST /api/v2/alerts/ingest` — HTTP-обёртка над существующей `core/alert_inbox.py::create_or_merge_alert()`
(сейчас вызывается только in-process). Авторизация — сервисный токен (§7).

Тело: параметры `create_or_merge_alert` (title, source, alert_type, severity, source_ref,
description, summary, observables, tags, tlp, pap, event_count, mitre_tactics, rule_name,
entity, verdict_score, verdict_text, es_doc_id, es_doc_index) плюс новые поля от SOAR:

```json
{
  "...": "поля create_or_merge_alert",
  "triage_run_id": "srun_9f3a1c",        // сквозной ID прогона в SOAR — для связки аудита
  "event_time": "2026-07-05T10:40:00Z",  // время события (не обработки) — для бэкфилла
  "backfill": false                       // true = алерт доставлен с задержкой (догон)
}
```

Ответ: `{"id": 123, "action": "created" | "merged"}` — `action` нужен SOAR для гейта UEBA-скоринга
и идемпотентного реплея.

Skip/noise-паттерны (`ALERT_SKIP_PATTERNS`, `ALERT_NOISE_PATTERNS`) продолжают применяться
внутри `create_or_merge_alert` — источник правды у SOC Core.

Новые поля SOAR (`triage_run_id`, `event_time`, `backfill`) не требуют изменения схемы
`alert_inbox` — ingest-эндпоинт складывает их в существующий `raw_payload JSONB`;
`backfill` дополнительно дублируется тегом `backfill` для видимости в UI.

#### 4.2.1. Семантика полей: структура обязательна, MD — только тело карточки

Свободный формат — только `description` (Markdown, ≤200k). Остальные поля питают механику IRP,
SOAR обязуется заполнять их корректно:

| Поле | Что от него зависит в IRP |
| --- | --- |
| `source_ref` | идемпотентность / merge (`ON CONFLICT`) |
| `observables[] {dataType, data}` | корреляция `ioc_match`, блок «участники»; **только публичные IP + хеши** (внутренние IP склеивают несвязанные инциденты) |
| `entity` | корреляция `entity_burst`/`subnet_match`, группировки, счётчик повторов правила |
| `rule_name` | `entity_burst`, FP-rate автопилота, тексты шагов реагирования (`ruleExplanations`) |
| `severity` (1–4) | гейт `auto_severity`, дашборд, лейблы |
| `verdict_score` / `verdict_text` | quick verdict, фильтр `min_verdict`; при merge перезаписываются свежими значениями |
| `mitre_tactics` | панель MITRE-покрытия |
| `tags` | конвенции SOC Core (`mitre:*`, `ti:*`, `priority:critical`); маркер источника SOAR — `sys:soar`; noise-паттерны матчатся по title+rule_name+**tags** |
| `es_doc_id` / `es_doc_index` | Kibana flyout deep-link |
| `description` | Markdown-тело карточки; SOAR сохраняет привычную структуру секций (VERDICT → контекст → SOURCE → Links) |
| `summary`, `tlp`, `pap` | legacy TheHive — см. В-7 |

Семантика merge при повторном push с тем же `source_ref`: `severity` = GREATEST,
`verdict_*` = свежие, `event_count` суммируется — SOAR вправе дообогащать созданный алерт
повторным push.

### 4.3. Гарантии доставки (при отказе SOAR)

Модель: **at-least-once поверх durable-источника**. ES хранит алерты — оркестратор ничего
не буферизирует незаменимо.

- **Watermark**: после каждого успешного цикла SOAR сохраняет отметку последнего обработанного
  `@timestamp` в durable-хранилище. Watermark двигается только после успешного ingest.
- **Догон после даунтайма**: на старте — выборка от `watermark − overlap(5 мин)` до `now`,
  реплей **чанками размером в time window (10 мин)** — сохраняет семантику порога count-на-окно
  (один большой запрос раздул бы count и изменил решения гейта).
- **Идемпотентность**: `source_ref` строится по формуле SOC Core
  (`core/alert_payload.py::make_source_ref`) с передачей **event-time** (`now=` параметр уже
  существует), а не времени обработки. Повторы поглощаются `ON CONFLICT (source_ref)`.
- **Прозрачность догона**: бэкфильнутые алерты несут `backfill: true` + оригинальный
  `event_time` — детект-задержка видна аналитику, метрики MTTD не искажаются.
- Ограничение: retention ES по `.internal.alerts-*` должен покрывать максимальный
  предполагаемый даунтайм (проверить ILM — §9, В-4).

### 4.4. Миграция без риска: shadow-режим

До отключения текущего пайплайна SOC Core обе реализации работают параллельно N дней:
SOAR пишет алерты с тегом `soar:shadow` (или в отдельный источник), результаты сравниваются
(количество, severity, вердикты, дропы). Cutover — после совпадения на согласованном пороге.
Расхождения legacy/SOAR-путей SOC Core (одиночные HIGH: legacy шлёт, SOAR-путь дропает)
разрешаются на этом этапе явным решением (§9, В-2).

## 5. Поток 2 — события жизненного цикла (webhook IRP → SOAR)

### 5.1. Требуется от SOC Core: хук в двух точках

`core/alert_inbox.py::create_or_merge_alert()` и `core/alert_incidents.py::transition_incident()`
(+ `transition_status` алертов) — после успешного коммита отправляют событие:

```
POST {SOAR_URL}/webhooks/irp-events
X-Webhook-Token: <токен воркфлоу>
```

```json
{
  "event": "alert.created | alert.merged | alert.status_changed | incident.created | incident.status_changed",
  "ts": "2026-07-05T10:41:03Z",
  "alert":   { "id": 123, "source_ref": "...", "alert_type": "UEBA-Alert", "severity": 3,
               "rule_name": "...", "entity": "...", "status": "new" },
  "incident": { "id": 45, "status": "investigating", "link_rule": "ioc_match" },
  "transition": { "from": "new", "to": "acknowledged", "user_id": 7 }
}
```

Приёмная сторона у SOAR уже существует: `POST /webhooks/{workflow_name}` c per-workflow токеном.

### 5.2. Семантика: fire-and-forget + reconciliation

- Хук **не блокирует** пайплайн SOC Core: timeout ≤ 2 с, ошибка POST = warning в лог,
  алерт создаётся в любом случае. SOC Core не ретраит.
- Гарантию даёт **reconciliation-поллинг** на стороне SOAR: раз в N минут выборка
  `GET /api/v2/alerts/list` (существующий эндпоинт) по `created_at > watermark` — добор
  событий, пропущенных за даунтайм SOAR. Пропущенный webhook = задержка, не потеря.

## 6. Поток 3 — writeback реагирования (SOAR → IRP)

Всё реагирование SOAR отражается в IRP через существующее API v2 — попадает в `alert_history`
и UI автоматически:

| Действие SOAR | Механизм IRP | Примечание |
| --- | --- | --- |
| Комментарий о ходе/результате действия | `add_comment` (API комментариев алерта) | каждый шаг response-workflow; содержит `triage_run_id`/job id SOAR |
| Прогресс автоматических шагов | `alert_response_steps` (`ensure_steps`/`toggle_step` через API) | шаги workflow регистрируются как чек-лист алерта — аналитик видит прогресс автоматики в UI; гейт «resolved только при выполненных шагах» продолжает работать |
| Перевод статусов | `transition_status` / `transition_incident` через API | SOAR **подчиняется матрице переходов** — недопустимый переход = ошибка SOAR, не обход |
| Деструктивные действия (блокировка УЗ/IP, изоляция хоста) | **только после подтверждения человеком** | Фаза 2: механизм pending-approval в UI SOC Core (аналог существующего паттерна auto_action + undo). До его появления деструктивные шаги SOAR требуют подтверждения на стороне SOAR |

Прямые записи SOAR в PostgreSQL SOC Core — **запрещены** контрактом.

## 7. Аутентификация M2M

Текущее API SOC Core — только сессионная кука (TTL 8 ч), для M2M непригодно. Требуется:

- **Сервисный токен** (заголовок `X-API-Token` или `Authorization: Bearer`) → маппинг на
  сервисную учётку.
- **Роль `soar_service`** в `api/rbac.py::ROLE_PERMISSIONS` (default-allow отсутствует —
  без явной роли всё упрётся в 403): `alert_inbox: read+write`, `playbooks: read`,
  + ресурс ingest. Зеркалить в frontend `usePermissions.ts` не требуется (M2M).
- Токены — в конфиге обеих сторон, ротация по регламенту SOC Core (`docs/09-secret-rotation.md`).

Обратное направление (IRP → SOAR): существующий `X-Webhook-Token` per-workflow.

## 8. Поток 4 — health-интеграция

- SOAR-оркестратор пишет `orchestrator_heartbeat` в Redis SOC Core (TTL 180 с, каждый цикл) —
  по образцу существующих `bot_heartbeat`/`correlator_heartbeat`; появляется на Health-странице.
- **Watchdog-правило `ORCHESTRATOR_DOWN`** в коррелятору SOC Core (по образцу `ES_DATA_GAP`):
  heartbeat протух → алерт severity 4 в Alert Inbox, cooldown 1 ч. Коррелятор — независимый
  контейнер, переживает смерть оркестратора.
- Вместе с §4.3 и §5.2: смерть SOAR = видимый CRIT-алерт + автоматический догон после подъёма.
  Тихая потеря невозможна.

## 9. Сопутствующие правки SOC Core (вне API, но в рамках контракта)

1. **Развязать UEBA-алертинг от TheHive**: сейчас запись UEBA-алертов в Inbox гейтится
   `UEBA_THEHIVE_ENABLED` + непустыми `THEHIVE_URL`/`THEHIVE_KEY` (`correlator/digest.py:411`).
   TheHive мёртв; чистка его конфига молча остановит UEBA-алерты. Ввести отдельный флаг
   `UEBA_ALERTS_ENABLED` для Inbox-записи.
2. **API чтения политик триажа** (whitelist/blacklist/пороги/critical assets из config.json) —
   если существующий settings-эндпоинт покрывает, зафиксировать его в контракте.

## Открытые вопросы (нужно решение SOC Core)

- **В-1. Формат ingest**: принимается ли схема §4.2 (поля `create_or_merge_alert` + 3 поля SOAR)?
- **В-2. Политика гейта для одиночных HIGH**: legacy шлёт при `sev ≥ 3`, SOAR-путь — при `sev == 4`.
  Какое поведение канонично? (Фиксируется в workflow SOAR и в регламенте.)
- **В-3. UEBA-скоринг по SIEM-алертам**: `update_ueba_v3` сейчас вызывается из пайплайна бота.
  Варианты: (а) перенести вызов внутрь `create_or_merge_alert` при `action=created` (у SOC Core,
  рекомендуется — скоринг остаётся полностью их доменом); (б) отдельный API-эндпоинт, зовёт SOAR.
- **В-4. Retention ES** по `.internal.alerts-*` — фактический ILM? Определяет максимальный
  покрываемый даунтайм для догона.
- **В-5. Shadow-период**: длительность и критерий совпадения для cutover (предложение: 7 дней,
  расхождение ≤ 2% по созданным алертам с разбором каждого расхождения).
- **В-6. Судьба `bot/` и `soar_workflows/`** после cutover: SIEM-ветка бота выводится из
  эксплуатации; `soar_workflows/connectors/elastic.py` может остаться для нужд коррелятора?
- **В-7. Поля `summary` (HTML), `tlp`, `pap`** — legacy TheHive: рендерится ли `summary`
  где-либо в UI SOC Core? Если нет — SOAR их не заполняет (дефолты), поле кандидат
  на deprecated.

## Сводка доработок

**SOC Core (всё — небольшое):**
1. `POST /api/v2/alerts/ingest` (§4.2)
2. Webhook-хук fire-and-forget в `create_or_merge_alert` + `transition_incident`/`transition_status` (§5)
3. Сервисный токен + роль `soar_service` (§7)
4. Watchdog `ORCHESTRATOR_DOWN` (§8)
5. Развязка UEBA-гейта от TheHive (§9.1)

**SOAR:**
1. ES pull-коннектор с durable watermark + чанк-реплей догона (§4.3)
2. Порт триаж-логики (`wf_alert_triage`) с журналированием каждого решения (§4.1)
3. Reconciliation-поллер поверх `GET /alerts/list` (§5.2)
4. Writeback-клиент API v2 (комментарии, response steps, статусы) (§6)
5. Heartbeat-писатель в Redis SOC Core (§8)
6. Shadow-режим и отчёт сравнения для cutover (§4.4)

## Фазы внедрения

| Фаза | Содержание | Зависимости |
| --- | --- | --- |
| 0 | Утверждение контракта, ответы на В-1…В-7 | — |
| 1 | M2M-токен, webhook, writeback, heartbeat/watchdog — SOAR реагирует на существующие алерты; пайплайн SOC Core не тронут | SOC Core §§5,7,8 |
| 2 | Порт ingestion в SOAR, shadow-режим параллельно с legacy | SOC Core §4.2, В-2, В-3 |
| 3 | Cutover: legacy SIEM-ветка бота отключается; каноничный пайплайн — SOAR | отчёт shadow-сравнения |
| 4 | Pending-approval для деструктивных действий в UI SOC Core | по готовности SOC Core |
