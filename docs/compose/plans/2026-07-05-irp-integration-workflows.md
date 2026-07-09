# IRP Integration Workflows — спецификация (без реализации)

> [!NOTE]
> Спека этапа «воркфлоу» интеграции с SOC Core (IRP). Реализация ОТЛОЖЕНА —
> ждём багфиксы в `main`. Не начинать до отмашки.
> Контракт: `docs/integration/soc-core-integration-contract.md` (утверждён SOC Core).
> Коннектор `soar/connectors/irp/` уже готов и протестирован — воркфлоу строятся поверх него.

**Goal:** реализовать SOAR-сторону контракта — приём событий IRP (webhook), триаж-пайплайн
SIEM-алертов с watermark/бэкфиллом (Фаза 2), reconciliation-поллер и первый
response-плейбук (Фаза 1) — с журналированием каждого решения (никаких тихих дропов).

**Architecture:** четыре workflow поверх существующих `WebhookWorkflow`/`ScheduledWorkflow`
(`soar/workflows/base.py`) + durable watermark-store. Вся связь с IRP — только через
`IRPConnector` (никаких прямых записей в их PG/Redis, кроме heartbeat-ключа, который
предусмотрен контрактом §8).

**Tech Stack:** Python 3.11+, существующий orchestrator (queue/worker/scheduler),
`IRPConnector`, elasticsearch-py (через существующий elastic-коннектор), pytest.

## Global Constraints

- Реализация — только после стабилизации `main` (багфиксы в работе).
- Ни одного молчаливого дропа: каждое решение «не отправлять» = запись в лог workflow
  с причиной + счётчик в `WorkflowResult.data`.
- Все контрактные значения (пороги, whitelist/blacklist, critical assets) читаются
  из config.json SOC Core — SOAR их не дублирует (источник правды у них).
- `Date`-семантика: `source_ref` всегда строится от **event-time**, не от времени обработки
  (формула `make_source_ref` из контракта §4.3).
- Shadow-режим обязателен до cutover: тег `soar:shadow`, боевой прогон без отключения
  legacy-пайплайна SOC Core.

---

## File Structure

| File | Purpose |
|------|---------|
| `soar/workflows/irp_events.py` | `IrpEventsWorkflow(WebhookWorkflow)` — приёмник событий IRP, диспетчер response-логики |
| `soar/workflows/alert_triage.py` | `AlertTriageWorkflow(ScheduledWorkflow)` — pull ES → триаж → ingest (Фаза 2) |
| `soar/workflows/irp_reconcile.py` | `IrpReconcileWorkflow(ScheduledWorkflow)` — сверка пропущенных webhook-событий |
| `soar/workflows/respond_basic.py` | `BasicResponseWorkflow(ManualWorkflow)` — первый плейбук: comment + response steps (Фаза 1, без деструктива) |
| `soar/tools/watermark.py` | `WatermarkStore` — durable отметки прогресса (файл JSON, atomic write) |
| `soar/tools/triage_policy.py` | чтение политик триажа из SOC Core settings API + локальный кэш |
| `tests/soar/test_irp_events_workflow.py` | тесты приёмника |
| `tests/soar/test_alert_triage_workflow.py` | тесты триажа: гейты, watermark, бэкфилл-чанки |
| `tests/soar/test_watermark_store.py` | тесты durable-store |
| `tests/soar/test_irp_reconcile.py` | тесты поллера |

---

## Task 1: WatermarkStore

**Files:** `soar/tools/watermark.py`, `tests/soar/test_watermark_store.py`

Durable-хранилище отметок «до какого `@timestamp` обработано». JobStore оркестратора
in-memory — не подходит; нужен файл (переживает рестарт, без новых зависимостей).

**Interfaces:**

```python
class WatermarkStore:
    def __init__(self, path: str): ...          # JSON-файл, atomic write (tmp+rename)
    def get(self, key: str) -> str | None: ...  # ISO-8601 UTC или None (первый запуск)
    def set(self, key: str, ts: str) -> None: ...
```

**Правила:**
- [ ] запись только ПОСЛЕ успешного ingest всего чанка (at-least-once, контракт §4.3)
- [ ] первый запуск (нет watermark): начать с `now - TIME_WINDOW`, НЕ с эпохи
- [ ] ключи: `siem_alerts` (триаж), `irp_reconcile` (поллер) — один store, разные ключи
- [ ] тест: рестарт (новый инстанс, тот же файл) читает прежнее значение; битый JSON → None + warning

## Task 2: AlertTriageWorkflow (Фаза 2 контракта)

**Files:** `soar/workflows/alert_triage.py`, `soar/tools/triage_policy.py`,
`tests/soar/test_alert_triage_workflow.py`

`ScheduledWorkflow`, `interval = 60`. Порт логики `wf_siem_alert.py` + legacy
`process_group` из soc_bot (см. анализ в контракте §4.1) на наш рантайм.

**Шаги цикла (каждый шаг журналируется):**

1. `heartbeat` — `IRPConnector.send_heartbeat()` (в начале цикла, не в конце:
   упавший цикл не должен выглядеть живым)
2. `load_policy` — политики из SOC Core settings API (`triage_policy.py`, кэш TTL 60с;
   недоступно → последний кэш + warning; кэша нет → цикл прерывается с ошибкой, БЕЗ
   обработки с пустыми политиками — пустой whitelist опаснее пропущенного цикла)
3. `fetch` — ES-агрегация групп rule×host от `watermark − overlap(5 мин)` до `now`,
   чанками по `TIME_WINDOW` (10 мин); если отставание > 1 чанк → режим `backfill=True`
4. `triage` — по группе:
   - whitelist-дроп → лог `dropped:whitelist`
   - CVE-верификация (Wazuh) → `dropped:cve_patched` — ВИДИМЫЙ лог, не тихий return
   - blacklist / critical asset → эскалация sev=4, причина в лог и в description алерта
   - гейт отправки: `sev >= 3 OR count >= threshold` (допущение Д-1 ниже)
     → `dropped:below_threshold`
   - обогащение TI (AbuseIPDB/OTX/VT — существующие коннекторы) + расчёт вердикта
     (порт `calculate_verdict`)
5. `ingest` — `IRPConnector.ingest_alert(...)`: поля по контракту §4.2.1
   (observables только public IP + хеши, теги `sys:soar` [+ `soar:shadow` в shadow-режиме],
   `event_time` = время чанка, `triage_run_id` = job id)
   - обработка всех трёх `action`: `created`/`merged`/`skipped` — счётчики в результат
6. `advance_watermark` — только после успешного ingest всех групп чанка

**`WorkflowResult.data`:** `{fetched, ingested_created, ingested_merged, skipped_irp,
dropped: {whitelist, cve_patched, below_threshold}, backfill_chunks, watermark}` —
прозрачность цикла одним взглядом.

**Чек-лист:**
- [ ] чанк-реплей: тест «6 часов даунтайма → 36 чанков по 10 мин, watermark движется почанково»
- [ ] упавший ingest в середине чанка → watermark НЕ движется, повтор идемпотентен (`merged`)
- [ ] shadow-режим: конфиг-флаг `shadow: true` → тег `soar:shadow` во всех алертах
- [ ] дедуп внутри цикла: Redis SOC Core недоступен нам для их dedup-ключей — наш дедуп
      только через идемпотентный `source_ref` (детерминированный от event-time-бакета)
- [ ] UEBA: НЕ вызываем ничего — скоринг делает их ingest (`score_ueba=True` на их стороне)

## Task 3: IrpEventsWorkflow (приёмник webhook, Фаза 1)

**Files:** `soar/workflows/irp_events.py`, `tests/soar/test_irp_events_workflow.py`

`WebhookWorkflow`, имя регистрации — ровно `irp-events` (зашито в
`SOAR_WEBHOOK_URL = http://<host>:8000/webhooks/irp-events` у SOC Core),
`token` = `SOAR_WEBHOOK_TOKEN` (уже согласован). Оркестратор сам проверяет токен
и кладёт payload в `context["payload"]` — workflow получает готовый dict.

**Логика `run(context)`:**
- [ ] валидация: `event` из списка контракта §5.1
      (`alert.created|alert.merged|alert.status_changed|incident.created|incident.status_changed`);
      неизвестный event → лог + `{"handled": False}`, НЕ ошибка (forward-compat)
- [ ] дедуп с reconciliation: отметить `alert.id` как «увиден» (Redis/наш, TTL 24ч,
      ключ `irp_seen:{id}`) — поллер (Task 4) пропускает увиденные
- [ ] диспетчеризация (МVP — таблица правил в коде, позже конфиг):
      `alert.created` + `severity >= 3` + НЕ тег `soar:shadow` → enqueue `BasicResponseWorkflow`
      с контекстом `{alert_id, severity, rule_name, entity}`;
      остальные события — только лог (задел под будущие плейбуки)
- [ ] эхо-фильтр: события наших же shadow-алертов не порождают response (иначе
      shadow-прогон начнёт реагировать на копии)

## Task 4: IrpReconcileWorkflow (страховка webhook)

**Files:** `soar/workflows/irp_reconcile.py`, `tests/soar/test_irp_reconcile.py`

`ScheduledWorkflow`, `interval = 300`. Контракт §5.2: webhook = быстрый путь,
поллер = гарантия.

- [ ] `IRPConnector.list_alerts(created_after=watermark['irp_reconcile'], ...)`
      — параметр фильтра уточнить по факту их API (`/list` принимает `created_at`-фильтр?
      если нет — запросить у SOC Core, это 5 строк на их стороне; см. Допущение Д-2)
- [ ] для каждого алерта БЕЗ отметки `irp_seen:{id}` → та же диспетчеризация, что в Task 3
      (общая функция, не копия)
- [ ] watermark `irp_reconcile` двигается по max(`created_at`) обработанных
- [ ] тест: алерт, пришедший и через webhook и через поллер → response ровно один

## Task 5: BasicResponseWorkflow (первый плейбук, Фаза 1)

**Files:** `soar/workflows/respond_basic.py`

Цель — доказать end-to-end цикл в их UI, БЕЗ деструктивных действий:

- [ ] `ensure_response_steps(alert_id, texts)` — шаги из справочника по `rule_name`
      (MVP: generic-набор из 3 шагов, если правила нет в справочнике)
- [ ] `add_comment(alert_id, "SOAR: взят в обработку, job {id}, шаги зарегистрированы")`
- [ ] выполняемые автоматикой шаги отмечаются `toggle_response_step(..., done=True)`
      сразу после фактического выполнения, НЕ авансом
- [ ] `transition_alert` НЕ вызывается в MVP (статусы двигают аналитики);
      исключение — ничего. Деструктив — только Фаза 4 (pending-approval у SOC Core)

## Task 6: конфигурация и деплой-заготовка

- [ ] `config.yaml` оркестратора: инстанс `irp_main` (см. `irp.example.yml`),
      флаг `shadow`, путь watermark-файла (volume в docker-compose!)
- [ ] `deploy/stage/docker-compose.yml`: volume под watermark, env для токенов
- [ ] хост оркестратора → согласовать и передать SOC Core для `SOAR_WEBHOOK_URL`

---

## Открытые допущения (подтвердить до реализации)

- **Д-1. Гейт одиночных HIGH**: в ответе SOC Core (Д-2 их ревью) закрыт вопрос про
  *инциденты*, но не про *гейт отправки алерта*: legacy шлёт при `sev>=3 OR count>=threshold`,
  их SOAR-путь — при `sev==4 OR count>=threshold`. Спека принимает **legacy-поведение**
  (прод живёт на нём) — подтвердить у SOC Core явно.
- **Д-2. Фильтр `created_after` в `GET /alerts/list`** — есть ли; если нет, запросить.
- **Д-3. Settings API для политик триажа** (whitelist/blacklist/пороги) — каким эндпоинтом
  читать config.json; зафиксировать в контракте §9.2.
- **Д-4. Справочник response-шагов по правилам** — у SOC Core тексты живут во фронте
  (`ruleExplanations.ts`); для Task 5 нужен либо экспорт, либо свой минимальный набор.

## Порядок реализации

Task 1 → Task 3 (+ Task 5) → Task 4 — это Фаза 1, включает `SOAR_WEBHOOK_ENABLED=true`.
Затем Task 2 + Task 6 — Фаза 2 (shadow), cutover по критериям контракта (В-5: 7 дней, ≤2%).
