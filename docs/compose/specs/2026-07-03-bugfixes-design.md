# Bug Fixes: Code Review Findings v0.4–v0.5

> [!NOTE]
> Спек по результатам ревью кода. Только bugs и antipatterns — без рефакторинга.
> Plan: `docs/compose/plans/2026-07-03-bugfixes.md`

## [S1] Problem

В ходе ревью кода v0.4–v0.5 выявлено 7 проблем: 2 высокого уровня (данные теряются / логика ломается), 3 среднего (неработающие фичи и обходимые гарантии безопасности), 2 антипаттерна (нарушение правил проекта).

## [S2] Bugs

### [B1] Cancel race: CANCELLED → FAILED (HIGH)

**Файл:** `orchestrator/core/worker.py:87-96`

`JobManager.cancel()` убивает процесс и ставит статус CANCELLED. Но Worker ждёт `proc.communicate()`, и после возврата (returncode != 0) перезаписывает статус в FAILED — не перепроверяет стор.

**Исправление:** перечитать `job_store.get(job.id)` после `communicate()`, не менять статус если уже CANCELLED.

**Интерфейс:** `GET /jobs/{id}` → статус `cancelled` для отменённых jobs.

---

### [B2] MySQL tables() SQL-конкатенация (HIGH)

**Файл:** `soar/connectors/mysql/mysql.py:77`

```python
rows = self.execute("SHOW TABLES FROM %s" % db)  # строковое форматирование
```

`_validate_identifier(db)` защищает от эксплойта, но паттерн некорректен и несогласован с `columns()` (который использует бэктики). При смене валидатора — SQL-инъекция.

**Исправление:** использовать бэктики как в `columns()`:
```python
rows = self.execute(f"SHOW TABLES FROM `{db}`")
```

---

### [B3] RedisQueue не сериализует поле `concurrency` (MEDIUM)

**Файл:** `orchestrator/core/queue/redis_queue.py:50-92`

`push()` не включает `concurrency` в JSON. После `pop()` поле = дефолт `FORBID`. Worker проверяет `job.concurrency == ConcurrencyPolicy.QUEUE` — условие никогда не выполняется при Redis-бэкенде. QUEUE-политика сломана для Redis.

**Исправление:** добавить `"concurrency": job.concurrency.value` в push, восстанавливать через `ConcurrencyPolicy(item["concurrency"])` в pop.

---

### [B4] `result_data` всегда null (MEDIUM)

**Файл:** `orchestrator/core/worker.py:87-93`, `soar/runner.py:48-57`

Runner пишет JSON `{"success": ..., "data": {...}}` в stdout. Stdout перенаправлен в log-файл. Worker при успехе ставит `result_success=True` и не парсит вывод. `WorkflowJob.result_data` всегда `null`.

**Исправление:** читать последнюю непустую строку лог-файла после `communicate()`, парсить как JSON, заполнять `result_data` и `result_error`. Fallback: если строка не JSON — игнорировать.

**Интерфейс:** `GET /jobs/{id}` → `result_data` содержит `data` из `WorkflowResult`.

---

### [B5] Rate limiter отключается за nginx (MEDIUM)

**Файл:** `orchestrator/main.py:228-234`

Whitelist `127.0.0.1` — при запуске за nginx в том же контейнере (stage deploy) все запросы приходят с `127.0.0.1` → rate limiting фактически не работает.

**Исправление:** добавить поддержку `X-Real-IP` / `X-Forwarded-For` с конфигурируемым списком trusted proxies. Пока trusted proxies пуст — только `client.host` как сейчас.

```yaml
# config.yaml
server:
  trusted_proxies: []  # ["127.0.0.1"] для stage за nginx
```

---

### [B6] SSRF: доменные имена не резолвятся (MEDIUM)

**Файл:** `orchestrator/api/connectors.py:144-157`

`_validate_external_url()` блокирует IP-литералы, но не резолвит hostname. Домен, указывающий на `10.0.0.1` / `169.254.169.254`, проходит проверку.

**Исправление:** добавить DNS-резолв через `socket.getaddrinfo()` и проверять каждый A-запись через `ipaddress`. Заблокировать redirect (httpx `follow_redirects=False`).

---

### [B7] Приватные поля из роутов (ANTIPATTERN)

**Файлы:** `orchestrator/api/workflows.py:64`, `orchestrator/api/webhooks.py:11`, `orchestrator/api/status.py:24-25`

Роуты обращаются к `job_manager._metas`, `queue._redis`, `queue._ensure_connected()` напрямую — нарушает правило проекта «не обращаться к очереди напрямую из роутов».

**Исправление:**
- `JobManager.get_meta(name)`, `JobManager.list_metas()` — публичные методы
- `AbstractJobQueue.health() -> dict` — возвращает `{connected: bool, size: int}`

## [S3] Priority

| ID | Severity | Effort | Fix first |
|----|----------|--------|-----------|
| B1 | HIGH | Low | ✓ |
| B2 | HIGH | Low | ✓ |
| B4 | MEDIUM | Medium | ✓ |
| B3 | MEDIUM | Low | ✓ |
| B7 | ANTIPATTERN | Medium | ✓ |
| B5 | MEDIUM | Low | after B7 |
| B6 | MEDIUM | Medium | after B5 |

## [S4] Constraints

- Никакого рефакторинга за пределами фикса
- Каждый баг — отдельный коммит
- Test-first: сначала падающий тест, потом фикс, потом зелёный тест
- UI не трогать — только `soar/` и `orchestrator/`

## [S5] Verification

После каждого фикса:
```bash
python -m pytest tests/orchestrator/ tests/soar/ -v
ruff check orchestrator/ soar/
```

Все 205+ тестов должны проходить.
