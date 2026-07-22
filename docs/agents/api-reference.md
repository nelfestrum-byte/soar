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

### Actions
| Method | Path | Description |
|--------|------|-------------|
| GET | /actions | Список actions |
| GET | /actions/template | Шаблон boilerplate |
| GET | /actions/{name} | Получить код |
| GET | /actions/{name}/code | Получить код (алиас) |
| PUT | /actions/{name} | Сохранить код — 422 если код не парсится или нет функции с именем `name` (`validate_action_code`) |
| DELETE | /actions/{name} | Удалить action |
| GET | /actions/{name}/history | История коммитов файла |
| GET | /actions/{name}/history/{commit} | Содержимое файла на конкретном коммите |
| GET | /actions/{name}/diff?a=&b= | Diff между двумя коммитами |
| POST | /actions/{name}/restore `{"commit": "..."}` | Откат на коммит (admin), без reload |

### Connectors
| Method | Path | Description |
|--------|------|-------------|
| GET | /connectors | Список коннекторов |
| GET | /connectors/template | Шаблон кода + конфига |
| GET | /connectors/{name} | Meta коннектора (class_name, has_code, has_config) |
| POST | /connectors/{name} | Создать коннектор |
| DELETE | /connectors/{name} | Удалить коннектор |
| GET | /connectors/{name}/code | Получить код .py |
| PUT | /connectors/{name}/code | Сохранить код .py — 422 если код не парсится или нет класса-наследника `BaseConnector` (`validate_connector_code`) |
| GET | /connectors/{name}/config | Получить конфиг .yml |
| PUT | /connectors/{name}/config | Сохранить конфиг .yml |
| POST | /connectors/generate | Генерация коннектора из OpenAPI spec |
| POST | /connectors/preview | Парсинг OpenAPI spec (POST, тело) |
| GET | /connectors/preview | Парсинг OpenAPI spec (GET, URL) — SSRF-защищён |
| GET | /connectors/{name}/code/history[/{commit}] | История/версия `.py` |
| GET | /connectors/{name}/code/diff?a=&b= | Diff `.py` между коммитами |
| POST | /connectors/{name}/code/restore `{"commit": "..."}` | Откат `.py` на коммит (admin), без reload |
| GET | /connectors/{name}/config/history[/{commit}] | История/версия `.yml` |
| GET | /connectors/{name}/config/diff?a=&b= | Diff `.yml` между коммитами |
| POST | /connectors/{name}/config/restore `{"commit": "..."}` | Откат `.yml` на коммит (admin) |

### Tools

| Method | Path | Description |
|--------|------|-------------|
| GET | /tools | Список классов `soar/tools/` (name, module, summary) — AST, без импорта |
| GET | /tools/{name} | Докстринг, сигнатура конструктора и публичных методов класса |

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
