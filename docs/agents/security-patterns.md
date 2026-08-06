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
**для всех ролей, включая `admin`** — в `/config/diff` это касается и строк
самой правки (`+`/`-`), и неизменённых контекстных строк вокруг неё
(`_DIFF_KV_RE` матчит все три префикса unified diff, B2) — секреты в этой системе write-only:
задать можно, прочитать обратно через API нельзя никому. `PUT /config` —
merge-on-write (плейсхолдер `"********"` = "не менять", берётся старое
значение с диска). Формат хранения (`{name}.yml`, git-история) не меняется —
секреты физически остаются в git, но никогда не возвращаются через API ни
одной ролью. Тот же write-only периметр покрывает и `POST /transfer/export`
(S3): экспортируемый `{name}.yml` редактируется той же `_redact_yaml`/
`_hidden_fields_for` перед упаковкой в архив — секрет, который нельзя
прочитать через `GET /config`, нельзя прочитать и через `/export`.

**Редакция fails closed.** `_hidden_fields_for` возвращает `set[str] | None`,
где `None` = «политика не читается» (нет `.py`, `SyntaxError`, нет классов) —
это не то же самое, что пустое множество («секретов нет», валидное
объявление, его делает `CONNECTOR_TEMPLATE`). При `None` `_redact_yaml`/
`_redact_diff` маскируют **все** значения под `instances.*`, а не ни одного.
До 2026-08-06 неизвестная политика означала «показывай всё» — любой путь,
оставляющий нечитаемый `.py` при живом `.yml`, раскрывал креды.

### Разделение владения коннектором: код агенту, значения человеку (2026-08-06)
Отменяет B3 (`PUT /connectors/{name}/code` — литеральный `admin`). Причина
отмены: барьер не держал. `POST /connectors/{name}` (роль `_ADMIN`, т.е.
агенту разрешена) коммитит шаблон с пустым `HIDDEN_FIELDS`, а `POST
/{name}/code/restore` оставался на `_ADMIN` — агент откатывался на свой же
шаблонный коммит и снимал редакцию, не касаясь `PUT`. Рассуждение B3 («любая
версия в истории писалась `admin`-ом») не учло шаблон от `POST`.

Действующая схема — `docs/compose/specs/2026-08-06-connector-code-agent-unlock-design.md`:

- `PUT /{name}/code` — `_ADMIN`: писать код коннектора это работа агента, он
  автор `__init__` и единственный, кто знает, какой параметр является credential.
- Конфиг закрыт от `agent` целиком: `GET`/`PUT /{name}/config`,
  `GET /{name}/config/history/{commit}`, `/config/diff`,
  `POST /{name}/config/restore` — `_CONFIG_RO` (`_RO` минус `agent`) на чтении
  и литеральный `admin` на записи. Агенту остаются `GET /{name}/schema`
  (имена полей + флаг `hidden`, без значений) и `GET /{name}/config/history`
  (факт изменения, не содержимое). Запись забрана вместе с чтением осознанно:
  `PUT` пишет файл целиком, слепая запись затирала бы невидимые значения.
- `HIDDEN_FIELDS` можно расширить, но не сузить: `_assert_hidden_fields_not_narrowed`
  требует `new >= old` для всех ролей кроме `admin`, и вызывается во **всех
  трёх** путях записи кода — `PUT /code`, `POST /code/restore` (содержимое
  целевого коммита проверяется до отката) и `POST /generate` (перезапись
  существующего коннектора). Полнота покрытия здесь и есть урок B3: политику
  нужно проверять на каждом пути записи носителя политики, а не на одном.

**Границы гарантии — не смягчать при пересказе.** Это защита целостности
политики редакции и гигиена API-поверхности, а **не** обеспеченная граница
против враждебного агента: у роли `agent` есть произвольное исполнение кода
(код воркфлоу + `POST /jobs`), в субпроцесс монтируются креды открытым YAML,
`ConnectorProxy` отдаёт `conn.api_key` и `conn._instance` сырыми, логи джоба
не редактируются. См. `docs/agents/known-limitations.md` и
`docs/compose/specs/2026-08-06-connector-secret-runtime-boundary-design.md`.

### Authentication (orchestrator/auth/)
- **Auth-disabled mode**: когда `auth.secret_key = ""` — `get_current_user` возвращает анонимного admin. Backward-совместимость с Docker-сетевым доверием и существующими тестами.
- **JWT access tokens** (HS256, TTL 30min): payload `{sub, role, type:"user", exp}`
- **Refresh tokens**: opaque UUID, TTL 7d, хранятся как `SHA-256(token)` в Postgres, ротируются при каждом `/auth/refresh`
- **API keys**: формат `soar_<32-byte-hex>`, хранятся как `SHA-256(key)`, для M2M сервисных аккаунтов
- **RBAC роли**: `admin` (полный доступ), `analyst`, `viewer`, `service`, `agent` (Stage 3/P7 — код actions/connectors/workflows + jobs/logs на равных с `admin`, но НЕ `/auth/users`, `/auth/keys`, `/audit-log`, `/transfer/*`, `PUT /prompts/user`, а с 2026-08-06 и НЕ конфиг коннектора — ни чтение, ни запись; эти остаются `admin`-only литералом либо через `_CONFIG_RO`, не через общий tuple); каждый эндпоинт декорирован `Depends(require_role(...))`
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

### Privilege narrowing (Фаза 4, orchestrator/core/subprocess_runner.py)
Слой 3 модели изоляции (`docs/concepts/ENTITY-MODEL.md`) — защита от
неаккуратного/умеренно враждебного контента, не от целенаправленного
атакующего с нативным кодом (то же явное ограничение скоупа, что и
content-venv в Фазе 1).

**Credential scoping — всегда включён:**
`orchestrator/core/introspect.py::parse_connector_usage` — статический
AST-скан (`ast.parse`, без импорта) `from soar.connectors.<type> import
<instance>` на верхнем уровне файла воркфлоу; возвращает `instance_name =
alias.name` (реальное имя инстанса, которое резолвит PEP 562
`__getattr__` в `soar/connectors/__init__.py::_install_shims`), **не**
`alias.asname` — `import prod as ssh_prod` должен сузить креды до "prod",
локальный алиас в реестр не попадает. `build_scoped_config` (там же)
строит по этому списку временный каталог (`tempfile.mkdtemp`) со срезом
`connectors_dir` (символические ссылки на `.py`, отфильтрованные `.yml`
только с нужными инстансами) и урезанным YAML-конфигом
(`workflows_dir`/`actions_dir`/`tools_dir`/`state_dir`/`connectors_dir` +
`http_client`; **без** `auth`/`database` — JWT-секрет и `database.url`
физически не попадают в файл, который видит субпроцесс). `SOAR_CONFIG`
субпроцесса указывает на этот срез, не на `orchestrator/config.yaml`.
Воркфлоу без статически найденных импортов получают пустой
`connectors_dir` (нулевые креды), не fallback на полный набор —
осознанное решение, задокументировано в `build_scoped_config`'s
docstring. Временный каталог создаётся mode `0700` (`tempfile.mkdtemp`
default) и явно перешируется до `0755`/`0644` (`_make_world_readable`) —
нужно, чтобы субпроцесс мог прочитать его после смены UID ниже; чувствительность
ограничена одним job'ом на время его исполнения, каталог удаляется в
`Worker._execute`'s `finally` на всех путях выхода (успех/ошибка/timeout/
cancel), тем же приёмом, что уже закрывает `_log_file`.

**UID/rlimit narrowing — опционален (`jobs.runner_uid`, `None` по
умолчанию), POSIX/Docker-only:** `_drop_privileges()` строит `preexec_fn`,
выставляющий `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC` из
`JobsConfig.runner_max_memory_mb/runner_max_cpu_seconds/runner_max_procs`.
UID/GID переключение — **не** `os.setuid`/`os.setgid` внутри
`preexec_fn`, вопреки первоначальному дизайну: замерено в Docker
(`docs/compose/reports/privilege-narrowing.md`), что непривилегированный
родительский процесс (`soar`, не root — намеренно, см. `USER soar` в
Dockerfile) не может сменить UID даже с `docker run --cap-add=SETUID
--cap-add=SETGID` — эти флаги наполняют только *bounding* set контейнера,
эффективный набор capability непривилегированного процесса остаётся
пустым, пока конкретный исполняемый бинарник не несёт файловую capability.
Выдать `cap_setuid,cap_setgid+ep` самому интерпретатору content-venv
означало бы, что **любой** код под ним (скомпрометированная джоба или баг
в собственной обработке запросов оркестратора) может вызвать `setuid(0)`
— больше привилегии, чем должна давать эта фича. Вместо этого — обёртка
argv в `setpriv --reuid=<uid> --regid=<gid> --clear-groups --` перед
командой субпроцесса; `setpriv` (`util-linux`, уже есть в базовом образе)
несёт эту capability точечно (`setcap cap_setuid,cap_setgid+ep
/usr/bin/setpriv` в Dockerfile), сам не исполняет код джобы — только
переключает identity и делает `execve` в реальную команду. Отдельный
пользователь `soar-runner` (фиксированный uid/gid, НЕ в группе `soar`) не
может прочитать `config.yaml` (`chmod 640`, owner `soar:soar`) и не может
писать в `git.workflows_repo`; может писать в `soar.state_dir`
(group-owned `soar-runner`, `chmod 770` — нужно
`soar/tools/watermark.py::WatermarkStore`/`SeenStore`). Все три границы
(config.yaml unreadable, git repo unwritable, state_dir writable,
rlimit-enforcement включая реальный `MemoryError` при превышении
`RLIMIT_AS`) проверены запуском реальных Linux-контейнеров, не только
юнит-тестами с моками — детали в отчёте фазы.

### Connector HTTP hardening
- Все HTTP-коннекторы: `timeout=30` на каждый запрос (Abuse.ch, Censys, Crtsh, Fofa, FreeIPA, Kaspersky, RstCloud, SecurityOnion, Urlhaus, Wazuh)
- SSH: `WarningPolicy()` вместо `AutoAddPolicy()` — MITM protection
- WinRM: `verify_ssl=True` по умолчанию, `server_cert_validation="validate"`
- Wazuh: пустые credentials по умолчанию, SSL verification включён, `urllib3` warnings не глушаются

### API hardening
- `DELETE /workflows/{name}/code` — cleanup `orchestrator_state.yaml` перед reload
- `GET /workflows/{name}` и `GET /workflows` — webhook token в response dict, но только если `user.role in _RW` (`analyst`/`admin`/`agent`) — `viewer` его не видит (M13, `docs/concepts/BAGFIX_PLAN.md`): токен — единственная защита `POST /webhooks/{name}`, отдавать его read-only роли было равносильно выдаче credential на запуск произвольного workflow
- `GET /jobs` и `GET /jobs/{id}` — `job.context` (сырой payload вебхука/пользовательский context, не редактируется как hidden-поля коннекторов) вырезается из ответа для `viewer` (M12); `analyst`+ видят как раньше
- `POST /jobs` — отдельный 409 для disabled workflow (`WorkflowDisabledError`)
- `POST /transfer/import` — Zip Slip protection (path traversal + `..` check), name validation
- `GET /connectors/preview` — SSRF protection: блокировка internal/private IPs и localhost
- `PUT /connectors/{name}/code` и `config` — UTF-8 validation + null byte check
- Git log history: null-byte delimiter вместо `|` (prevents delimiter injection)
- `CORSMiddleware(allow_credentials=True)` с конкретными origins из `config.auth.cors_origins` (не `"*"`)
