# v0.6 Upgrade: CachedHttpClient + Metrics + Dry-Run

> [!NOTE]
> Спек на следующую итерацию после bugfixes. Без LLM, без YAML DSL.
> Plan: `docs/compose/plans/2026-07-03-v06-upgrade.md` (создать перед началом работы)

## [S1] Problem

Три независимые потребности следующей итерации:

1. **Threat-intel actions** (VT, AbuseCh, Kaspersky, RST, URLhaus) делают HTTP-запросы без кэша и логирования. Одинаковые запросы повторяются в каждом workflow-запуске, внешние API квотируются, нет трассировки enrichment-запросов.

2. **`GET /status`** показывает только агрегированные счётчики за день. Нет per-workflow статистики — невозможно понять, какой workflow падает чаще других.

3. **Dry-run** не задокументирован как конвенция. Разработчики workflows не знают, как тестировать без выполнения мутаций.

## [S2] Solution Overview

### Feature 1: CachedHttpClient (`soar/tools/http_client.py`)

Shared HTTP-клиент для threat-intel actions:
- InMemory / Redis cache backend (тот же паттерн что и JobQueue)
- TTL настраивается per-domain через конфиг
- Логирует каждый запрос и cache-hit через loguru
- Синглтон, инициализируется один раз в `soar/__init__.py`
- Actions используют его вместо прямых http-запросов

### Feature 2: Per-workflow метрики в `/status`

Расширить `JobStore.stats()` — добавить срез per-workflow:
```json
{
  "jobs": {
    "running": 2,
    "completed_today": 15,
    "failed_today": 3,
    "by_workflow": {
      "alert_check": {"running": 1, "completed": 10, "failed": 1},
      "ioc_enrich":  {"running": 1, "completed": 5,  "failed": 2}
    }
  }
}
```
In-memory, без Postgres. Актуально пока процесс живёт — этого достаточно для оперативного мониторинга.

### Feature 3: Dry-run конвенция (документация + хелпер)

Не новая инфраструктура — конвенция через `context["dry_run"]`.

Добавить хелпер в `soar/workflows/base.py`:
```python
class BaseWorkflow:
    def is_dry_run(self, context: dict) -> bool:
        return bool(context.get("dry_run", False))
```

Документировать паттерн в AGENTS.md. Пример для workflow:
```python
def run(self, context):
    result = actions.vt_check_ip(ip)           # enrichment — всегда
    if not self.is_dry_run(context):
        actions.close_alert(alert_id)           # mutation — только в live
```

## [S3] Architecture

```
soar/
├── tools/
│   ├── __init__.py
│   ├── http_client.py          # CachedHttpClient (NEW)
│   └── openapi.py              # существующий
├── workflows/
│   └── base.py                 # добавить is_dry_run() (MODIFY)
└── __init__.py                 # инициализация http_client singleton (MODIFY)

orchestrator/
├── api/
│   └── status.py               # by_workflow в stats (MODIFY)
└── store/
    └── job_store.py            # stats() расширить (MODIFY)
```

## [S4] CachedHttpClient Design

```python
# soar/tools/http_client.py

class CacheBackend(Protocol):
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict, ttl: int) -> None: ...

class InMemoryCache:
    # dict с TTL через time.monotonic()

class RedisCache:
    # redis-py, ключ soar:httpcache:{key}

class CachedHttpClient:
    def __init__(self, cache: CacheBackend, default_ttl: int = 3600): ...
    
    async def get_json(self, url: str, headers: dict = {}, ttl: int | None = None) -> dict:
        key = sha256(url + str(sorted(headers.items()))).hexdigest()[:16]
        if cached := self._cache.get(key):
            _log.debug(f"cache hit: {url}")
            return cached
        _log.info(f"http GET {url}")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        data = resp.json()
        self._cache.set(key, data, ttl or self.default_ttl)
        return data
    
    async def post_json(self, url: str, payload: dict, headers: dict = {}) -> dict:
        # POST не кэшируется, только логируется
        _log.info(f"http POST {url}")
        ...

http_client = CachedHttpClient(InMemoryCache())  # singleton
```

### Конфиг TTL
```yaml
# config.yaml
http_cache:
  backend: memory  # memory | redis
  default_ttl: 3600
  domain_ttl:
    api.virustotal.com: 86400
    api.abusech.org: 3600
    api.kaspersky.com: 43200
```

## [S5] Per-workflow Metrics

`JobStore.stats()` сейчас делает один проход по `_jobs`. Добавить второй проход для per-workflow группировки — O(n) по jobs, приемлемо для in-memory store с keep_completed=1000.

Добавить метод `stats_by_workflow()` в `JobStore`, вызывать его из `status.py`.

## [S6] Config Changes

```python
# orchestrator/config.py — новые секции
class HttpCacheConfig(BaseModel):
    backend: str = "memory"
    default_ttl: int = 3600
    domain_ttl: dict[str, int] = {}

class OrchestratorConfig(BaseModel):
    ...
    http_cache: HttpCacheConfig = HttpCacheConfig()
```

`soar/` читает конфиг напрямую из env `SOAR_CONFIG` в `runner.py` — `CachedHttpClient` инициализируется там же.

## [S7] Dry-run Convention

Dry-run НЕ требует изменения воркеров или очереди. Только:
1. `BaseWorkflow.is_dry_run(context)` — хелпер
2. Документация в AGENTS.md с примером
3. Конвенция: enrichment-actions всегда выполняются, mutation-actions проверяют `is_dry_run`

Запуск dry-run: `POST /jobs {"workflow_name": "alert_check", "context": {"dry_run": true}}`

## [S8] Testing Strategy

- `CachedHttpClient`: unit-тесты с mock httpx; тест cache-hit (второй вызов не делает http); тест TTL expiry; тест POST не кэшируется
- `stats_by_workflow()`: unit-тест с несколькими jobs разных workflows
- `is_dry_run()`: тест что мутации пропускаются (в workflow-тесте)

## [S9] Success Criteria

- [ ] `CachedHttpClient` singleton доступен в `soar.tools`
- [ ] actions могут использовать `from soar.tools import http_client`
- [ ] `GET /status` возвращает `jobs.by_workflow` с running/completed/failed per workflow
- [ ] `BaseWorkflow.is_dry_run(context)` задокументирован и протестирован
- [ ] Все существующие тесты проходят
- [ ] Конфиг `http_cache` с дефолтами, не ломает существующие deployments
