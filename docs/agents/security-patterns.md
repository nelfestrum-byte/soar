# Security Patterns

Детали security-механизмов orchestrator/soar. Индекс/навигация — в [AGENTS.md](../../AGENTS.md).

### Input validation (orchestrator/api/validation.py)
- `validate_name(name)` — regex `^[a-zA-Z0-9_\-]+$`, блокирует path traversal и shell metacharacters
- `validate_path_within(base, target)` — `normpath + startswith`, предотвращает directory escape
- `validate_commit(commit)` — regex `^[0-9a-f]{4,40}$`, используется history/diff/restore ручками
- `validate_workflow_code`/`validate_action_code`/`validate_connector_code` — `ast.parse` (без импорта, тот же принцип что `GET /tools`) на синтаксис + наличие ожидаемой точки входа; вызывается в `PUT`-обработчиках перед записью файла, 422 при провале
- SSRF protection — блокировка RFC 1918, link-local, localhost, cloud metadata IPs + DNS resolve (socket.getaddrinfo) + follow_redirects=False
- `soar/tools/http_client.py::_validate_external_url` — та же проверка, отдельная реализация (не импорт `orchestrator/`, `soar/` не зависит от оркестратора по архитектуре), поднимает `ValueError` вместо `HTTPException`; нужна там, где threat-intel actions строят URL из атакер-контролируемых данных алерта (IOC), не только из захардкоженного домена API

### Connector security (soar/connectors/)
- SQL: параметризованные запросы (PostgreSQL, MSSQL) + валидация имён (MySQL)
- LDAP: RFC 4515 escaping спецсимволов (`*`, `(`, `)`, `\`, NUL)
- File: path boundary check через `_resolve()` + `resolve()` + `startswith()`
- SSH: `WarningPolicy()` вместо `AutoAddPolicy()` (MITM protection)
- WinRM: SSL verification по умолчанию (`verify_ssl=True`)
- HTTP: `timeout=30` на все HTTP-запросы (prevents worker pool exhaustion)
- Wazuh: пустые credentials по умолчанию, SSL verification включён

### Connector secret redaction (orchestrator/api/connectors.py, orchestrator/core/introspect.py)
Каждый коннектор объявляет class-level `HIDDEN_FIELDS: ClassVar[set[str]]`
(парсится AST-интроспекцией, без импорта — `introspect.py::_hidden_fields()`,
та же безопасная схема, что уже используется для `/describe`). `GET
/connectors/{name}/schema` отдаёт типизированные поля с `hidden: bool`, сама
схема не секрет — доступна `_RO`. Значения hidden-полей маскируются
`"********"` в `GET /config`, `/config/history[/{commit}]`, `/config/diff`
**для всех ролей, включая `admin`** — секреты в этой системе write-only:
задать можно, прочитать обратно через API нельзя никому. `PUT /config` —
merge-on-write (плейсхолдер `"********"` = "не менять", берётся старое
значение с диска) + разделение прав по полю, не по ручке: реальное
изменение hidden-поля требует роль `admin` буквально (ручная проверка
внутри обработчика, не через `dependencies=[...]`, т.к. решение зависит от
содержимого запроса) — `agent` получает `403` при попытке сменить
credential, но по-прежнему правит не-hidden поля наравне с `admin`. Формат
хранения (`{name}.yml`, git-история) не меняется — секреты физически
остаются в git, но никогда не возвращаются через API ни одной ролью.

### Authentication (orchestrator/auth/)
- **Auth-disabled mode**: когда `auth.secret_key = ""` — `get_current_user` возвращает анонимного admin. Backward-совместимость с Docker-сетевым доверием и существующими тестами.
- **JWT access tokens** (HS256, TTL 30min): payload `{sub, role, type:"user", exp}`
- **Refresh tokens**: opaque UUID, TTL 7d, хранятся как `SHA-256(token)` в Postgres, ротируются при каждом `/auth/refresh`
- **API keys**: формат `soar_<32-byte-hex>`, хранятся как `SHA-256(key)`, для M2M сервисных аккаунтов
- **RBAC роли**: `admin` (полный доступ), `analyst`, `viewer`, `service`, `agent` (Stage 3/P7 — код actions/connectors/workflows + jobs/logs на равных с `admin`, но НЕ `/auth/users`, `/auth/keys`, `/audit-log`, `/transfer/*`, `PUT /prompts/user` — эти остаются `admin`-only литералом, не через общий tuple); каждый эндпоинт декорирован `Depends(require_role(...))`
- **Lazy DB session**: `get_current_user` не принимает `Depends(get_db)` — создаёт сессию только когда нужна проверка API-ключа (через `request.app.state.db_session_factory`)
- **bcrypt напрямую**: `import bcrypt` + `bcrypt.hashpw/checkpw` — passlib 1.7.4 несовместима с bcrypt≥5.0.0 (`__about__` был убран)
- **CORS**: `allow_origins=config.auth.cors_origins` + `allow_credentials=True`; `allow_origins=["*"]` несовместим с `credentials=True` в браузерах
- **Дефолтная DB**: `sqlite+aiosqlite:///./soar.db` (создаётся в рабочей директории). В продакшене — `postgresql+asyncpg://...` в `config.yaml`
- **CLI управления пользователями**: `create-user` / `deactivate-user` / `activate-user` (`python -m orchestrator.auth.cli <cmd> --username X [--role admin]`) — читает `SOAR_CONFIG`/`config.yaml` сам (как `main.py`), вызывает `configure_table_prefix()` до импорта `auth.models`, так что `database.url`/`table_prefix` всегда совпадают с тем, что использует запущенный сервис. Деактивация — soft-delete через `User.is_active` (уже проверяется в `authenticate_user`); жёсткого удаления нет. Нет `--db-url` env var (`SOAR_DB_URL` был убран — отдельный источник правды для БД был причиной бага с table_prefix). CLI остаётся единственным способом завести **первого** admin'а (bootstrap) — дальше управление уходит в `/auth/users` (API/UI)
- **`/auth/users`** (`orchestrator/auth/router.py`): `admin`-only, зеркалит `/auth/keys` — `POST` создать, `GET` список, `PATCH /{id}` частичное обновление (`role`/`is_active`/`password`, все опциональны, один эндпоинт вместо трёх). Self-lockout guard: `PATCH` на собственный `id` с `is_active: false` → 409. Каждый create/update пишет `audit_log` (`user.create`/`user.update`) через `orchestrator.audit.service.record` — `detail` никогда не содержит сырой пароль, только `password_reset: true`. UI — `ui/src/views/Users.vue`, пункт «Users» в навбаре только для `admin`

### Rate limiting (orchestrator/main.py)
- In-memory rate limiter: 120 req/60s per IP
- Логин `/auth/login`: строже — 5 req/60s (брутфорс-защита)
- Пропускает localhost/testclient для dev/тестов

### Request body limit
- 5MB максимум для POST/PUT/PATCH

### Subprocess isolation
- `create_subprocess_exec` (argument list, no shell) — prevent command injection
- Environment variable allowlist — предотвращает утечку секретов
- Log-per-job файл с guaranteed cleanup в finally block

### Connector HTTP hardening
- Все HTTP-коннекторы: `timeout=30` на каждый запрос (Abuse.ch, Censys, Crtsh, Fofa, FreeIPA, Kaspersky, RstCloud, SecurityOnion, Urlhaus, Wazuh)
- SSH: `WarningPolicy()` вместо `AutoAddPolicy()` — MITM protection
- WinRM: `verify_ssl=True` по умолчанию, `server_cert_validation="validate"`
- Wazuh: пустые credentials по умолчанию, SSL verification включён, `urllib3` warnings не глушаются

### API hardening
- `DELETE /workflows/{name}/code` — cleanup `orchestrator_state.yaml` перед reload
- `GET /workflows/{name}` и `GET /workflows` — webhook token в response dict
- `POST /jobs` — отдельный 409 для disabled workflow (`WorkflowDisabledError`)
- `POST /transfer/import` — Zip Slip protection (path traversal + `..` check), name validation
- `GET /connectors/preview` — SSRF protection: блокировка internal/private IPs и localhost
- `PUT /connectors/{name}/code` и `config` — UTF-8 validation + null byte check
- Git log history: null-byte delimiter вместо `|` (prevents delimiter injection)
- `CORSMiddleware(allow_credentials=True)` с конкретными origins из `config.auth.cors_origins` (не `"*"`)
