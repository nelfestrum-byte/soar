# Plan: Runtime Boundary — Phase 1 модели сущностей

Spec: `docs/compose/specs/2026-07-30-runtime-boundary-design.md`

Ветка: `feat/runtime-boundary-phase1`, из `main` (уже содержит
`ENTITY-MODEL.md`). Мердж в `main` после зелёного `pytest tests/` и
`ruff check .`.

## 1. Контракт зависимостей — `soar/runtime_contract.py`

Tests first (`tests/soar/test_runtime_contract.py`, новый файл):

- [ ] `CONTRACT` — непустой dict, каждая запись имеет `import_names`
      (непустой список str) и `kind` ∈ `{"protocol", "vendor"}`
- [ ] Каждый ключ `CONTRACT` встречается как имя пакета (до `>=`) в строке
      `soar/requirements.txt` — парсинг `requirements.txt` в тесте через
      `re.match(r"^([A-Za-z0-9_.-]+)", line)`
- [ ] Обратная проверка: каждая строка `soar/requirements.txt` имеет ключ в
      `CONTRACT` (никто не забыт)
- [ ] Confirm test fails before `soar/runtime_contract.py` exists (`ImportError`)

Implementation:

- [ ] `soar/runtime_contract.py` — `RUNTIME_VERSION = "1"`, `CONTRACT` как в
      спеке [S4]; для `smbprotocol` проверить фактические top-level модули
      (`python -c "import smbprotocol, importlib.metadata as m;
      print(m.distribution('smbprotocol').read_text('top_level.txt'))"`
      в существующем dev-окружении, если пакет уже стоит — иначе взять
      `smbclient`+`smbprotocol` как в спеке)

## 2. Контентный venv — `SubprocessRunner` + Dockerfiles

Tests first (`tests/orchestrator/test_subprocess_runner_env.py`):

- [ ] `resolve_content_python()` возвращает `SOAR_CONTENT_PYTHON` из env,
      если задан
- [ ] `resolve_content_python()` возвращает `sys.executable`, если
      `SOAR_CONTENT_PYTHON` не задан/пуст
- [ ] `SubprocessRunner.start()` вызывает `create_subprocess_exec` с первым
      аргументом = результат `resolve_content_python()` (мокнуть
      `asyncio.create_subprocess_exec`, проверить `call_args`), не
      `sys.executable` напрямую
- [ ] Confirm tests fail before the change (текущий код использует
      `sys.executable` напрямую)

Implementation — `orchestrator/core/subprocess_runner.py`:

- [ ] Добавить `resolve_content_python() -> str` рядом с
      `_resolve_config_path()`, по образцу из спеки [S3]
- [ ] `_CONTENT_PYTHON = resolve_content_python()` на уровне модуля
- [ ] `start()`: заменить `sys.executable` на `_CONTENT_PYTHON` в
      `create_subprocess_exec(...)`

Implementation — `orchestrator/main.py`:

- [ ] Импортировать `resolve_content_python` из `subprocess_runner`
- [ ] В `lifespan()`: `app.state.content_python = resolve_content_python()`

Implementation — `deploy/prod/Dockerfile.orchestrator`,
`deploy/stage/Dockerfile.orchestrator`:

- [ ] Заменить единый `pip install` на два venv-блока, как в спеке [S3]
      (platform-venv на PATH, content-venv — нет)
- [ ] `ENV SOAR_CONTENT_PYTHON=/app/content-venv/bin/python`
- [ ] `pip install -r /app/soar/requirements.txt` в content-venv (было:
      нигде не устанавливался — закрывает **E2**)
- [ ] Остальное (создание `/app/data/*`, seed built-in connectors/
      workflows/actions, `chown`, `CMD`) — без изменений

Manual verification (не pytest, часть приёмки плана):

- [ ] `docker compose -f deploy/stage/docker-compose.yml build orchestrator`
      без ошибок
- [ ] `docker compose -f deploy/stage/docker-compose.yml run --rm
      orchestrator /app/content-venv/bin/python -c "import paramiko, ldap3,
      psycopg2, pymysql, pymssql, aiogram, shodan, pymisp, elasticsearch,
      vt, winrm, smbprotocol, httpx, requests, yaml, loguru"` — без
      ImportError
- [ ] `docker compose -f deploy/stage/docker-compose.yml run --rm
      orchestrator python -c "import fastapi, sqlalchemy, alembic"` — без
      ImportError (голый `python` = platform-venv через PATH)
- [ ] `docker compose -f deploy/stage/docker-compose.yml run --rm
      orchestrator /app/content-venv/bin/python -c "import fastapi"` — ДОЛЖЕН
      упасть с ImportError (граница реальна, не только на бумаге)

## 3. AST-метаданные воркфлоу

Tests first (`tests/orchestrator/core/test_introspect.py`, новый файл или
дополнение существующего, если есть — проверить перед созданием):

- [ ] `parse_workflow_meta()` на synthetic `ScheduledWorkflow` (docstring +
      `schedule`/`interval`) → `{"type": "scheduled", "schedule": ...,
      "interval": ..., "docstring": ...}`
- [ ] На synthetic `WebhookWorkflow` (`path`/`token`) → `{"type": "webhook",
      "path": ..., "token": ...}`
- [ ] На synthetic `ManualWorkflow` без доп. атрибутов → `{"type":
      "manual", "docstring": ...}`, без ключей `schedule`/`path`/`token`
- [ ] На файл без `BaseWorkflow`-подкласса → `None`
- [ ] На файл с синтаксической ошибкой → `SyntaxError` пробрасывается
      (не глотается внутри функции)
- [ ] Confirm tests fail before `parse_workflow_meta` exists

Tests first (`tests/orchestrator/test_main.py` — найти существующий тест
`load_workflow_metas`, если есть, иначе новый файл):

- [ ] Regression: `load_workflow_metas` на временном каталоге с одним
      `ScheduledWorkflow`-файлом (schedule/interval/docstring) отдаёт
      `WorkflowMeta` с теми же полями, что даёт сегодняшний import-based
      путь — тест до и после рефакторинга сравнивает одинаковый вход/выход
- [ ] Non-import guarantee: workflow-файл с side-effect на top-level
      (`Path("marker").touch()` вне какого-либо класса/функции) — после
      `load_workflow_metas(config)` файл `marker` **не создан**
- [ ] Существующий тест на `enabled`/`token` persistence через
      `orchestrator_state.yaml` (если есть) — не меняется, остаётся зелёным
- [ ] Confirm non-import test fails against current implementation first
      (baseline — подтверждает, что тест реально ловит регресс)

Implementation — `orchestrator/core/introspect.py`:

- [ ] Добавить `_TYPE_BY_BASE`, `_WORKFLOW_META_FIELDS`, `_base_name()`,
      `parse_workflow_meta()` — как в спеке [S5]. `_target_name` уже
      существует в модуле, переиспользуется без изменений

Implementation — `orchestrator/main.py`:

- [ ] Добавить `_iter_workflow_files(config)` — сканирует
      `_SOAR_PKG / "workflows"` (приоритет), затем `config.soar.workflows_dir`,
      с `seen`-дедупом по `py_file.stem`, пропуская `_`-префикс и `base.py`
- [ ] Переписать `load_workflow_metas(config)` на `_iter_workflow_files` +
      `parse_workflow_meta`, как в спеке [S5] — убрать
      `from soar.workflows import workflows as wf_registry` и
      `wf_registry.init()`/`.list()`
- [ ] Импортировать `parse_workflow_meta` из `orchestrator.core.introspect`
- [ ] Не менять сигнатуру `load_workflow_metas`, вызывающие места в
      `orchestrator/api/workflows.py` (4 места) не трогать

## 4. Аудит-хук

Tests first (`tests/soar/test_audit_hook.py`, новый файл):

- [ ] `_handle("socket.connect", (fake_sock_af_inet, ("10.0.0.1", 80)))` →
      `PermissionError`, событие `socket.connect.blocked` добавлено в
      `_events`
- [ ] `_handle("socket.connect", (fake_sock_af_inet, ("8.8.8.8", 443)))` →
      не поднимает, событие `socket.connect` добавлено в `_events`
- [ ] `_handle("socket.connect", (fake_sock_af_unix, ("/tmp/x",)))` — не
      IPv4/IPv6 адрес (`family` не в `{AF_INET, AF_INET6}`) → не поднимает,
      событие добавлено без проверки на private IP
- [ ] `_handle("open", ("/etc/passwd", "r", 0))` → событие `open` с `path`
      в `_events`
- [ ] `_handle("subprocess.Popen", ("/bin/sh", ["/bin/sh"], None, None))` →
      событие `subprocess.Popen` в `_events`
- [ ] `flush()` — пишет по одной `_log.bind(audit=True).info` строке на
      событие (мокнуть `loguru.logger`), очищает `_events`
- [ ] `flush()` на пустом `_events` — logger не вызывается
- [ ] Отдельный subprocess-тест: `python -c "import
      soar.audit_hook as h; h.install(); import socket;
      socket.getaddrinfo('localhost', None)"` — процесс завершается с кодом
      0 (хук не ломает нормальную резолюцию)
- [ ] Отдельный subprocess-тест: тот же паттерн, но реальный
      `socket.create_connection(("127.0.0.1", <closed_port>))` внутри
      `try/except PermissionError` — подтверждает, что хук реально
      перехватывает `socket.connect` на живом сокете, не только на
      синтетическом вызове `_handle`
- [ ] Confirm tests fail before `soar/audit_hook.py` exists

Implementation:

- [ ] `soar/audit_hook.py` — `_WATCHED`, `_events`, `_is_private_ip`,
      `_handle`, `flush`, `install` — как в спеке [S6]
- [ ] `soar/runner.py`: `from soar.audit_hook import install as
      install_audit_hook, flush as flush_audit_hook`; `install_audit_hook()`
      сразу после `setup_logging(level="INFO")`, до `config_path = ...` и
      до сборки `http_client`/`init()`
- [ ] `soar/runner.py::main()`: обернуть тело в `try/finally`,
      `flush_audit_hook()` в `finally`

## 5. `GET /runtime`

Tests first (`tests/orchestrator/api/test_runtime.py`, новый файл):

- [ ] `GET /runtime` (роль `viewer`+) → 200, форма `{runtime_version,
      python_version, guaranteed, present_not_guaranteed}`
- [ ] `guaranteed` содержит запись только для пакетов из `CONTRACT`,
      реально присутствующих в замоканном `importlib.metadata.distributions`
      (мокнуть на 2-3 fake dist, включая одну из `CONTRACT` и одну нет)
- [ ] Запись `guaranteed` содержит `import_names`/`kind` в точности как в
      `CONTRACT`
- [ ] `present_not_guaranteed` содержит незадекларированные пакеты с
      `import_names`, вычисленными из `top_level.txt` (мокнуть
      `dist.read_text`)
- [ ] Без auth (или роль ниже `viewer`) → 401/403 как у остальных
      read-only ручек (сверить с паттерном `test_status.py`/`test_routes.py`)
- [ ] Confirm tests fail before router exists

Implementation:

- [ ] `orchestrator/api/runtime.py` — `router`, `_content_venv_root`,
      `_site_packages`, `_python_version`, `_top_level_names`,
      `get_runtime` — как в спеке [S7]
- [ ] `orchestrator/api/__init__.py`: экспортировать `runtime_router`
- [ ] `orchestrator/main.py`: зарегистрировать `app.include_router(runtime_router)`
      рядом с `tools_router` (найти точное место регистрации роутеров —
      grep `include_router` в `main.py`)

## 6. Docs

- [ ] `docs/agents/known-limitations.md` — пункт 10 (E2, "Зависимости 11 из
      24 встроенных коннекторов не установлены в образ") — переформулировать
      под новое состояние (закрыто) или удалить, с указанием версии/отчёта
- [ ] `AGENTS.md` — раздел "API Endpoints" / File map: добавить `GET
      /runtime` в таблицу префиксов и в File map (`orchestrator/api/runtime.py`)
- [ ] `AGENTS.md` — "Version history": новая запись после реализации (в
      конце работы над этой фазой, не заранее — правило проекта)

## Verification

- [ ] `python -m pytest tests/soar/test_runtime_contract.py
      tests/orchestrator/test_subprocess_runner_env.py
      tests/orchestrator/core/test_introspect.py tests/orchestrator/test_main.py
      tests/soar/test_audit_hook.py tests/orchestrator/api/test_runtime.py -v`
- [ ] `python -m pytest tests/ -q` — только преэкзистентные известные
      failures (см. baseline из `AGENTS.md` version history — `test_suite-green`),
      ноль новых
- [ ] `ruff check .`
- [ ] `mypy orchestrator/ soar/ --ignore-missing-imports` — не блокирует
      мердж при преэкзистентных находках, но новых не добавлять
- [ ] Docker manual verification (раздел 2) — выполнить и зафиксировать
      результат в отчёте
- [ ] Написать отчёт `docs/compose/reports/runtime-boundary.md`
