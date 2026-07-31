# Ручное E2E QA — чистый prod-стенд (on-site), роль admin

Дата: 2026-07-31 (верификационный повторный прогон). Полный пошаговый лог —
[`manual-qa-prod-onsite.log.md`](manual-qa-prod-onsite.log.md). Сценарий —
[`docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md`](../plans/2026-07-31-manual-qa-prod-onsite.md).

Этот прогон — повторный запуск того же сценария на **свежепересобранном**
стенде из текущего HEAD (`451d3e5`). Предыдущий прогон (тот же лог/отчёт,
зафиксированы в git history коммита `451d3e5`) нашёл критический блокер —
Д1 (`soar/runner.py`, неверный порядок init registries) и Д2
(`parse_connector_usage` не видел транзитивное использование коннектора
через actions), делавшие документированный паттерн workflow → actions →
connector полностью нерабочим под credential scoping, плюс Д3 (`GET
/tools/{name}` 404 для singleton-инструментов) и Н1–Н4 (неточности
документации). Коммит `451d3e5` их исправил. Цель этого прогона —
подтвердить, что фикс реально работает end-to-end на живом стенде, а не
просто закрыт по коду, и пройти оставшуюся часть сценария.

## 1. Итог одной строкой

Стенд поднят с нуля из текущего HEAD, критический блокер предыдущего прогона
(Д1/Д2) **подтверждённо устранён** — воркфлоу с документированным паттерном
(верхнеуровневый импорт actions) успешно выполнился end-to-end (dry-run
корректно блокирует мутацию, real-запуск делает реальный HTTP-вызов,
`SOAR_AUDIT_EVENT` в обоих ожидаемых форматах, редакция `HIDDEN_FIELDS`
подтверждена, restore workflow-кода подтверждённо триггерит reload); сценарий
пройден **полностью** (все 10 фаз, включая расширенное покрытие Phase 9) —
найдено **2 новых дефекта** (оба минорные/средние, не блокеры) и переиспользован
1 внешний фактор (httpbin.org был недоступен, заменён на postman-echo.com).

## 2. Покрытие по фазам

| Phase | Что проверено | Verdict |
|---|---|---|
| 0.1–0.10 | git status, sibling-репо, docker cleanup (снесён устаревший стек предыдущего прогона), `soarctl doctor/install/init --force/up/migrate --fresh`, создание admin, health-check | OK (2 SUSPICIOUS: унаследованное состояние машины от предыдущего прогона — не дефект продукта; `ui` без healthcheck-блока — неточность плана, известна из предыдущего прогона) |
| 1.1–1.3 | `POST /auth/login`, `GET /auth/me`, `POST/GET /auth/keys` | OK |
| 2.1–2.6 | `GET /tools`, `GET /tools/{name}` (Д3-фикс), `GET /runtime`, `GET /{connectors,actions,workflows}/template`, `GET /connectors`, `GET /prompts/system` | Д3 закрыт (404→200), но новая находка Д4 (см. ниже); остальное OK |
| 3.1–3.7 | `POST/PUT /connectors/qa_httpbin{,/code,/config}`, `GET .../schema,/config,/describe,/code/history` | OK |
| 4.1–4.4 | `PUT /actions/{check_qa_ip,notify_qa_event}`, `GET /actions`, `GET .../describe` | OK |
| 5.1–5.4 | `PUT /workflows/qa_manual_test/code` (верхнеуровневый импорт actions — паттерн, сломанный в предыдущем прогоне), `POST .../enable`, `GET /workflows{,/qa_manual_test}` | OK |
| 6.1–6.2 | `POST /jobs` (dry-run + real) | **OK — Д1/Д2 подтверждённо исправлены**; httpbin.org был недоступен (503, внешний фактор) — переключился на postman-echo.com |
| 7.1–7.3 | `GET /logs/{id}` (оба формата SOAR_AUDIT_EVENT дословно), редакция kwargs (доп. проверка), `GET /logs/{id}/stream` (SSE + audit_hook события) | OK, без находок |
| 8.1–8.4 | `GET /audit-log` (connector/action/workflow/job фильтры) | 1 минорная находка (Д5) на 8.1, остальное OK |
| 9.status/RBAC/webhook/ratelimit/history/diff/restore/transfer | `GET /status`, RBAC (analyst→403 на hidden field), webhook (позитив+негатив), rate limit, history/diff/restore workflow (проверен reload), transfer export/import (preflight+force) | OK, без находок |

## 3. Найденные дефекты

### Д4 — [СРЕДНЯЯ] `GET /tools/{name}` для singleton-инструментов не отдаёт docstring/сигнатуры даже после фикса Д3

**Что сделано:** предыдущий прогон нашёл, что `GET /tools/http_client_sync` возвращал 404 (Д3). Коммит `451d3e5` это исправил — проверил `GET /tools/http_client_sync` в этом прогоне.

**Что ожидалось:** согласно AGENTS.md принцип 4 ("Проект объясняет себя через API... Проверка на нарушение: если ответ на вопрос «что мне доступно?» требует... чтения исходников — принцип нарушен") и api-reference.md ("Докстринг, сигнатура конструктора и публичных методов класса") — полноценная информация для написания коннектора без чтения `soar/tools/http_client.py`.

**Что получилось:** статус теперь 200 (не 404 — Д3 в узком смысле закрыт), но тело ответа — `{"name":"http_client_sync","module":"__init__","summary":""}`, то же самое урезанное "synthetic entry", что и в `GET /tools`, без docstring/constructor/methods. Контрольный запрос `GET /tools/WatermarkStore` (class-based tool) вернул полный docstring+constructor+methods+fields. `GET /tools/SyncHttpClient`/`GET /tools/HttpClient` (реальные имена классов) — оба 404, т.к. `__all__` в `soar/tools/__init__.py` публикует только имя синглтона, не имя класса.

**Итог:** цель Phase 2 плана ("узнать точные сигнатуры get_json/post_json только из API, не по памяти") всё ещё не достижима. Пришлось прочитать `soar/tools/http_client.py` напрямую, чтобы продолжить Phase 3 — прямое нарушение "не читай остальной код заранее", но вынужденное.

**Почему это не regression фикса Д3:** коммит `451d3e5` буквально обещал сделать `get_tool` консистентным с `list_tools` для синглтонов ("matching GET /tools's existing behavior") — и сделал именно это. Но `list_tools` сам по себе никогда не нёс docstring/сигнатур для синглтонов (`summary:""` там же). Это более глубокий, ранее не описанный пробел в Принципе 4 конкретно для non-class инструментов — `http_client_sync` при этом флагманский пример из самого AGENTS.md ("Уже действует для инструментов (`GET /tools`)").

**Воспроизводимо:** да, для всех 4 синглтонов (`http_client`, `http_client_sync`, `seen_store`, `watermark_store`).

**Классификация:** баг API / пробел в Принципе 4 (`orchestrator/api/tools.py`, `orchestrator/core/introspect.py::parse_classes` не умеет интроспектировать модульные присвоения синглтонов), не дрейф модели сущностей в смысле E1-E10 (те все закрыты в v0.17-v0.20).

### Д5 — [МИНОРНАЯ] `PUT /connectors/{name}/config` пишет audit-запись даже когда git-коммит — реальный no-op

**Что сделано:** по ходу Phase 6 (переключение с httpbin.org на postman-echo.com) случайно переслал байт-в-байт идентичный `config.yml` дважды подряд.

**Что ожидалось:** согласно AGENTS.md ("Audit trail... пишется явным вызовом... из мутирующего роута, после успешной мутации") — audit-запись пишется только при реальном изменении.

**Что получилось:** `GitManager.commit()` (`orchestrator/core/git_manager.py:53-68`) корректно вернул `""` (диффа для файла нет, реальный no-op — это именно то поведение, которое было специально исправлено ранее, см. известные ограничения). Но `orchestrator/api/connectors.py:665-668` вызывает `audit_service.record(..., action="connector.update_config", ...)` безусловно после `commit()`, не проверяя `commit_hash` на пустоту. В `GET /audit-log?resource_type=connector` появилась запись `connector.update_config` с `detail.commit=""`, как будто произошла мутация, хотя файл не изменился.

**Воспроизводимо:** да, детерминированно (PUT дважды с одинаковым телом).

**Классификация:** минорный баг API (`orchestrator/api/connectors.py`, вероятно тот же паттерн есть и у `PUT /actions/{name}`, `PUT /workflows/{name}/code` — не проверял каждый роут отдельно в этом прогоне). Не путать с Phase 8.5 ("restore не пишет дублей аудита") — это другой случай (обычный `PUT`, не `restore`), но того же рода: audit-запись без реальной мутации.

### Внешний фактор (не дефект SOAR)

httpbin.org вернул `503 Service Temporarily Unavailable` на реальный (non-dry-run) запуск — подтверждено прямым `curl` с хоста (тоже 503), то есть сервис действительно был недоступен, не проблема сети контейнера. Traceback при этом показал полностью рабочую цепочку `workflow → action → ConnectorProxy → http_client → httpx` — упало только на сетевом ответе третьей стороны. Переключил коннектор на `postman-echo.com` (поддерживает и GET, и POST echo, в отличие от `api.ipify.org`) — реальный запуск прошёл успешно.

### Позитивные находки

- **П1.** Вторая подряд живая верификация полной сборки `deploy/prod` (`soarctl install`, два venv, `COPY --from=basepack`) — чисто, без единой ошибки.
- **П2.** Оба документированных формата `SOAR_AUDIT_EVENT` (`connector.call` и `connector.call.dry_run`) впервые в истории проекта подтверждены на реальном живом прогоне, дословно совпадают с ожиданием AGENTS.md/плана.
- **П3.** Редакция `HIDDEN_FIELDS` в kwargs прокси подтверждена вживую: `kwargs={'api_key': '***'}` в логе при реальном значении, дошедшем до вызова (`received_len=14`) — редакция только в логе, не в вызове.
- **П4.** Второй уровень наблюдаемости (`sys.addaudithook`, Принцип 5) подтверждён живьём в SSE-стриме — строки `soar.audit_hook | audit: {'event': 'socket.connect', ...}` рядом с proxy-уровнем.
- **П5.** Restore workflow-кода подтверждённо триггерит reload — job, запущенный сразу после restore на более старую версию, вернул результат без поля, добавленного в более новой версии (не просто чтение файла при следующем обращении).
- **П6.** Transfer conflict-preflight (без `force`) подтверждённо не пишет audit-запись; `force=true` пишет ровно одну `transfer.import`, без дублей.

## 4. Что не покрыто

- **UID/rlimit privilege narrowing** (`jobs.runner_uid`) — не включён на этом стенде (опция выключена по умолчанию), не тестировался в этом прогоне (уже отдельно верифицирован в Docker в рамках Фазы 4 privilege-narrowing, см. её собственный отчёт).
- **Истинная инкрементальность SSE-чанков** (задержка между чанками) — джобы этого стенда выполняются <2с, на глаз неотличимо от быстрого дампа; формат (`data: <line>\n\n`) подтверждён.
- **Мультиинстансность** — вне scope плана и известное ограничение #8.
- Не проверено, есть ли тот же паттерн Д5 (audit при no-op commit) у `PUT /actions/{name}` и `PUT /workflows/{name}/code` — нашёл только на `connectors/config`, не проверял остальные роуты отдельно.

## 5. Остановка и повторный подъём стенда

**Стенд оставлен поднятым** — не сношен, по правилу 10.3 плана.

Остановить:
```bash
python deploy/soarctl down
```

Поднять заново:
- Если только контейнеры были остановлены (образы/данные на месте): `python deploy/soarctl up` → `python deploy/soarctl migrate` (без `--fresh`, БД не пустая).
- Если нужна полная пересборка образов (например, после исправления Д4/Д5): весь Phase 0 заново от `python deploy/soarctl install`.

Тестовые артефакты этой сессии на стенде: коннектор `qa_httpbin` (base_url →
postman-echo.com, метод `echo_key` добавлен для проверки редакции),
экшены `check_qa_ip`/`notify_qa_event`, воркфлоу `qa_manual_test` (текущая
версия — восстановлена на коммит `44696a7`, без `echo_key`)/`qa_webhook_test`,
пользователь `qa_analyst`, API-ключ `qa-service-key` — можно удалить через
API перед использованием стенда для чего-либо ещё, либо оставить как есть
для дальнейшей ручной проверки поверх живого API.
