# API Reference

Полные таблицы эндпоинтов orchestrator. Индекс/навигация — в [AGENTS.md](../../AGENTS.md).

### Workflows
| Method | Path | Description |
|--------|------|-------------|
| GET | /workflows | Список registered workflows (runtime meta) |
| GET | /workflows/{name} | Получить meta workflow |
| POST | /workflows/{name}/enable | Включить workflow |
| POST | /workflows/{name}/disable | Выключить workflow |
| POST | /workflows/reload | Перечитать файлы и обновить job_manager |
| POST | /workflows/scheduler/reload | Пересоздать jobs планировщика из текущих metas |
| GET | /workflows/{name}/code | Получить код workflow |
| PUT | /workflows/{name}/code | Сохранить код workflow — 422 если код не парсится или не содержит класс-наследник `BaseWorkflow`/`ScheduledWorkflow`/`WebhookWorkflow`/`ManualWorkflow` (`validate_workflow_code`) |
| DELETE | /workflows/{name}/code | Удалить файл workflow |
| GET | /workflows/code/template | Шаблон workflow |
| GET | /workflows/{name}/code/history | История коммитов файла |
| GET | /workflows/{name}/code/history/{commit} | Содержимое файла на конкретном коммите |
| GET | /workflows/{name}/code/diff?a=&b= | Diff между двумя коммитами |
| POST | /workflows/{name}/code/restore `{"commit": "..."}` | Откат на коммит (admin), коммитится от актора, триггерит reload |

`GET /workflows`/`GET /workflows/{name}` включают `docstring` (докстринг класса workflow, `""` если не задан). Поле типа воркфлоу называется `type` (`manual`/`scheduled`/`webhook`), не `workflow_type` — не путать с одноимённым полем `WorkflowJob.workflow_type` во внутренней модели job'а.

`PUT /workflows/{name}/code`, `PUT /actions/{name}`, `PUT /connectors/{name}/code` принимают raw source как тело запроса (`Content-Type: text/plain` или без явного типа) — не JSON-обёртку вида `{"code": "..."}`.

### Actions
| Method | Path | Description |
|--------|------|-------------|
| GET | /actions | Список actions — `[{name, summary}]`, `summary` = первая строка докстринга функции |
| GET | /actions/template | Шаблон boilerplate |
| GET | /actions/{name} | Получить код |
| GET | /actions/{name}/code | Получить код (алиас) |
| GET | /actions/{name}/describe | Сигнатура + докстринг функции, AST без импорта (`{name, signature, docstring, module}`) |
| PUT | /actions/{name} | Сохранить код — 422 если код не парсится или нет функции с именем `name` (`validate_action_code`) |
| DELETE | /actions/{name} | Удалить action |
| GET | /actions/{name}/history | История коммитов файла |
| GET | /actions/{name}/history/{commit} | Содержимое файла на конкретном коммите |
| GET | /actions/{name}/diff?a=&b= | Diff между двумя коммитами |
| POST | /actions/{name}/restore `{"commit": "..."}` | Откат на коммит (admin), без reload |

### Connectors
| Method | Path | Description |
|--------|------|-------------|
| GET | /connectors | Список коннекторов — включает `summary` (первая строка докстринга класса) при `has_code` |
| GET | /connectors/template | Шаблон кода + конфига |
| GET | /connectors/{name} | Meta коннектора (class_name, has_code, has_config, summary) |
| GET | /connectors/{name}/describe | Докстринг класса + constructor + публичные методы (сигнатура, докстринг), AST без импорта |
| GET | /connectors/{name}/schema | Типизированные поля конструктора + `hidden: bool` (из `HIDDEN_FIELDS`), AST без импорта |
| POST | /connectors/{name} | Создать коннектор |
| DELETE | /connectors/{name} | Удалить коннектор |
| GET | /connectors/{name}/code | Получить код .py |
| PUT | /connectors/{name}/code | Сохранить код .py — 422 если код не парсится или нет класса-наследника `BaseConnector` (`validate_connector_code`); `403` если не-`admin` сужает `HIDDEN_FIELDS` относительно версии на диске |
| GET | /connectors/{name}/config | Получить конфиг .yml (`_CONFIG_RO` — `agent` получает `403`) — значения hidden-полей замаскированы `"********"` для всех ролей, включая `admin`; при нечитаемом `.py` маскируется всё |
| PUT | /connectors/{name}/config | Сохранить конфиг .yml (роль `admin` буквально) — merge-on-write для hidden-полей (плейсхолдер `"********"` не затирает старое значение) |
| POST | /connectors/generate | Генерация коннектора из OpenAPI spec — `HIDDEN_FIELDS` проставляются из `securitySchemes`; `403` если не-`admin` перезаписывает существующий коннектор кодом с более узким `HIDDEN_FIELDS` |
| POST | /connectors/preview | Парсинг OpenAPI spec (POST, тело) |
| GET | /connectors/preview | Парсинг OpenAPI spec (GET, URL) — SSRF-защищён |
| GET | /connectors/{name}/code/history[/{commit}] | История/версия `.py` |
| GET | /connectors/{name}/code/diff?a=&b= | Diff `.py` между коммитами |
| POST | /connectors/{name}/code/restore `{"commit": "..."}` | Откат `.py` на коммит, без reload; `403` если не-`admin` откатывается на версию с более узким `HIDDEN_FIELDS` |
| GET | /connectors/{name}/config/history | Список коммитов `.yml` — без значений, доступен и `agent` |
| GET | /connectors/{name}/config/history/{commit} | Версия `.yml` (`_CONFIG_RO`) — hidden-поля замаскированы, как и в `GET /config` |
| GET | /connectors/{name}/config/diff?a=&b= | Diff `.yml` между коммитами (`_CONFIG_RO`) — значения hidden-полей в `+`/`-` строках замаскированы, факт изменения виден |
| POST | /connectors/{name}/config/restore `{"commit": "..."}` | Откат `.yml` на коммит (роль `admin` буквально) |

**Разделение владения (v0.23):** код коннектора — роль `agent` наравне с
`admin`; значения конфига — только `admin`. Роль `agent` получает `403` на
всех ручках конфига, кроме `GET /{name}/schema` (имена полей, типы, флаг
`hidden` — без значений) и `GET /{name}/config/history` (список коммитов).
`HIDDEN_FIELDS` можно расширить, но сузить — только ролью `admin`, и это
проверяется на всех трёх путях записи кода (`PUT /code`, `POST /code/restore`,
`POST /generate`). Подробности и границы гарантии —
`docs/agents/security-patterns.md`, спека
`docs/compose/specs/2026-08-06-connector-code-agent-unlock-design.md`.

### Tools

| Method | Path | Description |
|--------|------|-------------|
| GET | /tools | Список классов `soar/tools/` (name, module, summary) — AST, без импорта |
| GET | /tools/{name} | Докстринг, сигнатура конструктора и публичных методов класса |

### Runtime

| Method | Path | Description |
|--------|------|-------------|
| GET | /runtime | Read-only, без PUT/DELETE — снимок содержимого content-venv: `runtime_version` (из `soar/runtime_contract.py`), `python_version`, `guaranteed` (пакеты из `CONTRACT`, реально установленные — `distribution`/`version`/`import_names`/`kind`), `present_not_guaranteed` (установлено, но не в контракте — `import_names` из `top_level.txt`). Локально/в тестах без Docker — `content_python == sys.executable`, `guaranteed` отражает то, что реально стоит в текущем venv |

### Prompts
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | /prompts/system | `_RO` | Встроенный системный промпт (`orchestrator/prompts/system_prompt.md`) — версионируется с кодом, не редактируется через API; 404 если файл не найден по `config.soar.system_prompt_path` |
| GET | /prompts/user | `_RO` | Пользовательский промпт (`{"content": null}`, если не задан) |
| PUT | /prompts/user | admin | Сохранить пользовательский промпт (`{"content": "..."}`) — git-commit, без history/diff/restore (см. `docs/compose/specs/2026-07-22-agent-devloop-stage2-design.md` [S6]) |

### Transfer
| Method | Path | Description |
|--------|------|-------------|
| POST | /transfer/export | Экспорт конфигурации в ZIP |
| POST | /transfer/import | Импорт конфигурации из ZIP |

### Jobs
| Method | Path | Description |
|--------|------|-------------|
| POST | /jobs | Запустить workflow |
| GET | /jobs | Список jobs |
| GET | /jobs/{id} | Статус job |
| POST | /jobs/{id}/cancel | Отменить job |

### Webhooks
| Method | Path | Description |
|--------|------|-------------|
| POST | /webhooks/{workflow_name} | Отправить webhook |

### Logs
| Method | Path | Description |
|--------|------|-------------|
| GET | /logs/{job_id} | Получить лог |
| GET | /logs/{job_id}/stream | SSE стрим лога |

### Status
| Method | Path | Description |
|--------|------|-------------|
| GET | /status | Воркеры, очередь, статистика (требует роль) |
| GET | /health | Liveness-проба, без auth (Docker healthcheck) |

### Auth
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | /auth/login | — | Логин (username + password) → access_token + refresh_token |
| POST | /auth/refresh | — | Ротация refresh_token → новый access_token |
| POST | /auth/logout | любой | Отзыв refresh_token |
| GET | /auth/me | любой | Текущий пользователь |
| POST | /auth/users | admin | Создать пользователя |
| GET | /auth/users | admin | Список пользователей |
| PATCH | /auth/users/{id} | admin | Изменить role/is_active/password (все поля опциональны); 409 на self-deactivate |
| POST | /auth/keys | admin | Создать API-ключ (возвращается один раз) |
| GET | /auth/keys | admin | Список API-ключей |
| DELETE | /auth/keys/{key_id} | admin | Удалить API-ключ |

### Audit
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | /audit-log | admin | Журнал мутаций (кто/что/когда), фильтры + пагинация |
