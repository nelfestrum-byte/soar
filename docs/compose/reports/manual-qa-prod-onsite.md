# Ручное E2E QA — чистый prod-стенд (on-site), роль admin

Дата: 2026-07-31. Полный пошаговый лог — [`manual-qa-prod-onsite.log.md`](manual-qa-prod-onsite.log.md).
Сценарий — [`docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md`](../plans/2026-07-31-manual-qa-prod-onsite.md).

## 1. Итог одной строкой

Стенд поднят полностью и с первой реальной живой верификацией сборки `deploy/prod` (Phase 0 — 100% успех); сценарий пройден **частично**: Phases 0–5 и 7–9 пройдены практически без находок, но **Phase 6 (запуск воркфлоу) заблокирован критическим, воспроизводимым дефектом продукта**, который делает основной документированный паттерн написания автоматизации (workflow → actions → connector) нерабочим при включённом (всегда включённом) credential scoping — всего найдено **8 дефектов/расхождений**: 1 критический баг продукта, 1 высокой severity баг продукта (тот же кластер), 1 подтверждённый API-баг средней severity, 4 неточности в самом плане/документации (не в продукте), 1 находка — позитивная (первая живая верификация сборки).

## 2. Покрытие по фазам

| Phase | Что проверено | Verdict |
|---|---|---|
| 0.1–0.10 | git status, sibling-репо, docker cleanup, `soarctl doctor/install/init/up/migrate`, создание admin, health-check | OK (1 SUSPICIOUS: `ui` без healthcheck-блока — неточность плана) |
| 1.1–1.3 | `POST /auth/login`, `GET /auth/me`, `POST/GET /auth/keys` | OK |
| 2.1–2.6 | `GET /tools`, `GET /tools/{name}`, `GET /runtime`, `GET /{connectors,actions,workflows}/template`, `GET /connectors`, `GET /prompts/system` | 1 FAIL (`GET /tools/{name}` 404 для синглтонов), остальное OK |
| 3.1–3.7 | `POST/PUT /connectors/qa_httpbin{,/code,/config}`, `GET .../schema,/config,/describe,/code/history` | OK (1 неточность документации: raw body, не JSON) |
| 4.1–4.4 | `PUT /actions/{check_qa_ip,notify_qa_event}`, `GET /actions`, `GET .../describe` | OK |
| 5.1–5.4 | `PUT /workflows/qa_manual_test/code`, `POST .../enable`, `GET /workflows{,/qa_manual_test}` | OK |
| 6.1–6.2 | `POST /jobs` (dry-run ×4 попытки, real) | **FAIL — заблокировано критическим дефектом продукта** |
| 7.1–7.3 | `GET /logs/{id}`, `GET /logs/{id}/stream` (SSE) | 1 FAIL (следствие блокера Phase 6), SSE-формат OK |
| 8.1–8.5 | `GET /audit-log` (connector/action/workflow/job фильтры) | OK, без находок |
| 9.1 | history/diff/restore workflow | OK |
| 9.2 | webhook (позитив+негатив) | OK (1 неточность плана: единый токен) |
| 9.3 | `GET /status` | OK |
| 9.4 | RBAC (analyst → hidden field) | OK |
| 9.5 | rate limiting `/auth/login` | OK |
| 9.6 | `POST /transfer/{export,import}` (preflight+force) | OK |

## 3. Найденные дефекты

### Д1 — [КРИТИЧЕСКИЙ, кандидат в блокер пилота] `soar/runner.py` инициализирует реестры в неверном порядке — ломает основной документированный паттерн workflow

**Что сделано:** создан воркфлоу `qa_manual_test`, импортирующий actions на верхнем уровне модуля (`from soar.actions.check_qa_ip import check_qa_ip`) — ровно паттерн из самого промпт-плана (Phase 5.1) и из "движок vs поведение" в AGENTS.md. Запущен через `POST /jobs`.

**Что ожидалось:** воркфлоу успешно выполняется, вызывает `check_qa_ip()`/`notify_qa_event()`, которые вызывают коннектор `qa_httpbin`.

**Что получилось:** `ValueError: Workflow 'qa_manual_test' not found` — верхнеуровневый traceback, который вообще не намекает на реальную причину. Расследование (лог джобы + чтение `soar/runner.py:95-97`) показало: `workflows.init()` вызывается ДО `connectors.init()`/`actions.init()`, хотя единственный способ резолвить `from soar.connectors.<type> import <instance>` — через `_install_shims()`, вызываемый в конце `connectors.init()`, и `from soar.actions.<name> import <func>` резолвится только после `actions.init()`. Любой воркфлоу с верхнеуровневым импортом action/connector гарантированно падает на `workflows.init()`.

**Воспроизводимо:** да, 100%, 6 из 6 прогонов джоб этой сессии, независимо от dry_run/real.

**Классификация:** баг продукта, `soar/runner.py:95-97` (порядок должен быть connectors → actions → workflows, а не workflows первым).

**Почему не было замечено раньше:** ни в `soar/workflows/`, ни в `soar-content-pack` нет ни одного встроенного примера workflow — это первый в истории проекта живой прогон реального воркфлоу с реальными импортами через `python -m soar.runner` в контейнере.

### Д2 — [ВЫСОКАЯ, тот же кластер] `parse_connector_usage` не видит транзитивное использование коннектора через actions — компаундируется с Д1 без выхода

**Что сделано:** как воркараунд для Д1 перенёс импорты actions внутрь `run()` (deferred import) — воркфлоу успешно зарегистрировался.

**Что ожидалось:** credential scoping (Фаза 4, `orchestrator/core/subprocess_runner.py::build_scoped_config`) даёт джобе доступ к коннектору `qa_httpbin`, раз воркфлоу транзитивно (через actions) его использует.

**Что получилось:** `connectors_dir` пуст ("Registered 0 connectors") — `parse_connector_usage` (`orchestrator/core/introspect.py:141-151`) сканирует **только прямые (нерекурсивные) top-level statements Module** самого файла воркфлоу; и "концептный", и "плоский" фасад доступа к коннектору, будучи не на верхнем уровне ИМЕННО файла воркфлоу (а внутри `run()` или транзитивно через action), не детектируются.

**Итог компаунда:** чтобы credential scoping увидел коннектор, импорт обязан быть верхнеуровневым в файле воркфлоу (⇒ триггерит Д1). Чтобы обойти Д1, импорт нужно унести внутрь `run()` (⇒ триггерит Д2, пустые креды). Пересечение множеств решений пусто — **нет способа только через контент workflow заставить документированный паттерн работать**, пока не исправлен хотя бы Д1.

**Классификация:** баг продукта (`orchestrator/core/introspect.py::parse_connector_usage`, дизайн предполагает только прямой импорт), архитектурно ожидаемое ограничение согласно докстрингу build_scoped_config, но в связке с Д1 даёт полный тупик для actions-based паттерна.

**Ссылка:** `docs/concepts/ENTITY-MODEL.md` принцип 5 (изоляция рантайма), `docs/agents/security-patterns.md` "Credential scoping — всегда включён".

### Д3 — [СРЕДНЯЯ] `GET /tools/{name}` 404 для всех singleton-записей, возвращаемых `GET /tools`

**Что сделано:** `GET /tools` вернул `http_client`/`http_client_sync`/`seen_store`/`watermark_store` с `module: "__init__"`. `GET /tools/http_client_sync` (то же имя) → 404.

**Что ожидалось:** докстринг + сигнатуры методов (AGENTS.md принцип 4: "Уже действует для инструментов `GET /tools`").

**Что получилось:** `{"detail":"Tool not found"}`. Причина (`orchestrator/api/tools.py:41-53`): `get_tool` ищет только среди классов (`parse_classes`), у синглтонов имя (`http_client_sync`) не совпадает с именем класса (`SyncHttpClient`) — синтетическая ветка, которая есть в `list_tools` (строки 35-37), в `get_tool` отсутствует полностью.

**Воспроизводимо:** да, для всех 4 синглтонов; class-based tools (`GET /tools/WatermarkStore`) работают нормально — контрольная проверка пройдена.

**Классификация:** баг API (`orchestrator/api/tools.py`), не дрейф модели сущностей.

### Н1–Н4 — неточности в плане/документации (не дефекты продукта)

- **Н1:** `PUT /connectors/{name}/code` (и аналогичные `/actions`, `/workflows/.../code`) принимают raw source как тело запроса, не JSON-обёртку — не специфицировано явно в `api-reference.md`.
- **Н2:** поле в `GET /workflows/{name}` называется `type`, план формулирует как `workflow_type`.
- **Н3:** пример кода коннектора в самом плане (Phase 3.2) использует неверный путь импорта `from soar.tools.http_client import http_client_sync` — реально `http_client_sync` определён в `soar/tools/__init__.py`, не в подмодуле `http_client.py`.
- **Н4:** план (Phase 9) предполагает единый `SOAR_WEBHOOK_TOKEN` для всех webhook-воркфлоу — на деле токен per-workflow (более безопасно), `SOAR_WEBHOOK_TOKEN` из `.env` ведёт себя как любой неверный токен.

### П1 — позитивная находка

Первая живая верификация сборки `deploy/prod` с реальным `--build-context basepack=...` (сиблинг-репозиторий `soar-content-pack`) — прошла чисто, без единой ошибки (два venv, `COPY --from=basepack`, все 24 коннектора засеялись).

### Расширение известного ограничения #6

`AuditLog.actor_name` как числовой id из-за отсутствия username в JWT payload (известное ограничение #6) распространяется и на **git commit author** (`git_author()`, `orchestrator/audit/service.py:12-16`) — коммиты от JWT-пользователя подписываются как `user-<id>`, не логином. Тот же корень, не новый дефект, но область действия шире, чем описано в known-limitations.md.

## 4. Что не покрыто

- **SOAR_AUDIT_EVENT connector.call / connector.call.dry_run** (Phase 7.1 основная цель) — ни разу не воспроизведено ни в одной из 6 джоб этой сессии из-за блокера Д1/Д2 (ConnectorProxy ни разу не был реально вызван).
- **Редакция kwargs в HIDDEN_FIELDS через реальный лог** (Phase 7.2, опционально) — та же причина, пропущено.
- **SSE true-streaming поведение** (задержка между чанками) — формат подтверждён, но джобы этого стенда выполняются <1с, инкрементальность на глаз не отличить от быстрого дампа.
- **Reload на restore workflow-кода** (Phase 9.1) — restore отработал, но строгое доказательство именно reload (а не просто чтения файла при следующем job) не получено в рамках доступных проверок.
- Ни один прогон workflow → actions → connector в этой сессии не дошёл до реального HTTP-вызова httpbin.org — сетевая связность контейнера наружу не проверена (заблокировано раньше, на импорте).

## 5. Остановка и повторный подъём стенда

**Стенд оставлен поднятым** — не сношен, по правилу 10.3 плана.

Остановить:
```bash
python deploy/soarctl down
```

Поднять заново:
- Если только контейнеры были остановлены (образы/данные на месте): `python deploy/soarctl up` → `python deploy/soarctl migrate` (без `--fresh`, БД не пустая).
- Если нужна полная пересборка образов (например, после исправления Д1/Д2/Д3 в коде): весь Phase 0 заново от `python deploy/soarctl install`.

Тестовые артефакты этой сессии на стенде: коннектор `qa_httpbin`, экшены `check_qa_ip`/`notify_qa_event`, воркфлоу `qa_manual_test`/`qa_webhook_test`, пользователь `qa_analyst`, API-ключ `qa-service-key` — можно удалить через API (`DELETE /connectors/qa_httpbin`, и т.д.) перед использованием стенда для чего-либо ещё, либо оставить как есть для дальнейшей ручной проверки поверх живого API.
