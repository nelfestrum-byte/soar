# BAGFIX_PLAN.md — трек исправлений по pre-production ревью

> Источник: [`docs/compose/reports/prod-readiness-review-2026-07-27.md`](../compose/reports/prod-readiness-review-2026-07-27.md)
> (полное ревью бэкенда от 2026-07-27: `orchestrator/`, `soar/`, `alembic/`,
> конфиги деплоя; вне скоупа — `ui/`, тела коннекторов).
>
> Этот файл — **трекер**, а не спека. Он не заменяет цикл
> `specs/ → plans/ → reports/` из `CLAUDE.md`: пункты уровня **B** и **S**
> получают обычный спек/план перед реализацией, пункты уровня **M** и **D** —
> точечные правки, идут напрямую.
>
> Нумерация сквозная и стабильна: **B** — блокеры пилота, **S** — существенные
> (долг пилота), **M** — мелкие, **D** — расхождения документации с кодом.
> Не перенумеровывать при закрытии — помечать `[x]` и оставлять на месте.
>
> **Смежный трек:** [`ENTITY-MODEL.md`](ENTITY-MODEL.md) (E1–E8) — дрейф от
> модели сущностей по итогам разбора 2026-07-29. Другая ось: здесь дефекты
> относительно ожидаемого поведения, там — расхождение кода с концептом
> проекта. E1 и E2 — полноценные баги (уровня B/S по критериям этого файла),
> но ведутся там, чтобы не разрывать причинно-следственную связь с моделью.

## Статус

| Уровень | Всего | Закрыто |
|---------|-------|---------|
| B (блокеры) | 4 | 4 |
| S (существенные) | 8 | 8 |
| M (мелкие) | 13 | 13 |
| D (документация) | 8 | 8 |

**Критерий выхода на пилот: все B закрыты.** ✅ Достигнуто 2026-07-28 — все
B1-B4 и, вместе с ними, все S1-S8 и D1-D8 реализованы через цикл
`specs/ → plans/ → reports/` (см. ссылки на отчёты в каждом пункте ниже).
M1-M13 закрыты точечными правками 2026-07-29 (без отдельного цикла
specs/plans/reports — см. правило в шапке файла), тесты — зелёные.

---

## B. Блокеры — до включения на живой инфраструктуре

### - [x] B1. Деактивация пользователя не отзывает доступ

> Закрыто 2026-07-28 — отчёт: [`auth-deactivation-revocation.md`](../compose/reports/auth-deactivation-revocation.md).

**Где:** `orchestrator/auth/service.py:63-93` (`rotate_refresh_token`),
`orchestrator/auth/router.py:57-72` (`POST /auth/refresh`),
`orchestrator/auth/service.py:173-188` (`update_user`).

**Суть:** `authenticate_user()` фильтрует по `is_active`, но только на
`/auth/login`. `rotate_refresh_token()` проверяет `revoked_at` и `expires_at`
и **не смотрит `User.is_active`**. Каждый `/auth/refresh` выдаёт новый
access-токен и новый refresh на 7 дней. Ни `PATCH /auth/users/{id}
{is_active: false}`, ни `python -m orchestrator.auth.cli deactivate-user`
не отзывают доступ — деактивированный аккаунт работает бессрочно.

**Почему блокер:** ломает единственный способ отключить скомпрометированного
пользователя или агента. Заодно обесценивает recovery-путь принятого риска
P15 (`UPGRADE-v2.md`), который прямо опирается на работающую деактивацию.

**Фикс:**
- [x] тест: деактивированный пользователь получает 401 на `/auth/refresh`
- [x] тест: `update_user(is_active=False)` помечает `revoked_at` всем живым refresh-токенам
- [x] `rotate_refresh_token()` — вернуть `None`, если `user is None or not user.is_active`
- [x] `update_user()` — при `is_active=False` (и при смене роли) проставить `revoked_at` активным токенам пользователя
- [x] то же поведение для `set_user_active()` (путь CLI)

### - [x] B2. `GET /connectors/{name}/config/diff` отдаёт секреты роли `viewer`

> Закрыто 2026-07-28 — отчёт: [`connector-diff-redaction-fix.md`](../compose/reports/connector-diff-redaction-fix.md).

**Где:** `orchestrator/api/connectors.py:34` (`_DIFF_KV_RE`), `124-139`
(`_redact_diff`), `592-601` (роут на `_RO`).

**Суть:** регулярка требует префикс `+`/`-`:
`^([+-])(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$`. В unified diff неизменённые
строки — контекст с ведущим пробелом. Любая правка соседнего поля выводит
неизменённый `password`/`api_key`/`token` в контекст, редакция его пропускает.
Воспроизведено на реальном `git diff`:

```
@@ -1,4 +1,4 @@
 instances:
   x1:
-    base_url: https://a
+    base_url: https://b
     password: SUPERSECRET      ← контекстная строка, регулярка не матчит
```

**Почему блокер:** ровно та дыра, которую закрывал P13, осталась открытой в
третьем из трёх редактируемых эндпоинтов; читает самая низкопривилегированная
роль `viewer`.

**Фикс:**
- [x] тест: diff двух версий, где hidden-поле **не менялось**, а менялось соседнее → значение замаскировано
- [x] тест: diff, где hidden-поле менялось (`+`/`-`) → обе стороны замаскированы (регрессия существующего поведения)
- [x] `_DIFF_KV_RE` → `^([+\- ])(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$`, сохранить исходный префиксный символ в выводе

### - [x] B3. Роль `agent` обходит редакцию секретов, переписав `HIDDEN_FIELDS`

> Закрыто 2026-07-28 — отчёт: [`connector-code-agent-lockdown.md`](../compose/reports/connector-code-agent-lockdown.md).

**Где:** `orchestrator/api/connectors.py:31` (`_ADMIN = ("admin", "agent")`),
`91-104` (`_hidden_fields_for`), `512-547` (`PUT /{name}/code`),
`orchestrator/api/validation.py:67-74` (`validate_connector_code`).

**Суть:** что маскировать — определяется AST-разбором `HIDDEN_FIELDS` в том же
файле коннектора, который `agent` вправе перезаписать. `validate_connector_code`
требует только класс-наследник `BaseConnector`. Эксплуатация в два запроса:
`PUT /connectors/ssh/code` (тот же класс без `HIDDEN_FIELDS`) →
`GET /connectors/ssh/config` (пароли открытым текстом). Merge-on-write в
`PUT /config` тоже отваливается: при пустом `hidden` проверка
`user.role != "admin"` не выполняется вовсе.

**Почему блокер:** P13 проектировался так, чтобы `agent` получал 403 на
секретах. Контроль обходится, потому что политика хранится в данных, которыми
управляет контролируемый субъект.

**Фикс (минимальный, выбран для пилота):**
- [x] тест: `agent` получает 403 на `PUT /connectors/{name}/code`
- [x] тест: `admin` по-прежнему может писать код коннектора
- [x] `PUT /connectors/{name}/code` — литеральный `("admin",)` вместо `_ADMIN`, как уже сделано для `/transfer/*` и `PUT /prompts/user`
- [x] отразить сужение прав `agent` в `docs/agents/security-patterns.md` (см. D2)

> Альтернатива, если правка коннекторов агентом реально понадобится: запрет
> сужения `HIDDEN_FIELDS` относительно предыдущей версии файла. Дороже,
> отдельная спека, **не в этот трек**.

### - [x] B4. За nginx все клиенты выглядят одним IP

> Закрыто 2026-07-28 — отчёт: [`trusted-proxies.md`](../compose/reports/trusted-proxies.md).

**Где:** `deploy/prod/nginx.conf:15-17`, `orchestrator/core/net.py:9-17`,
`deploy/prod/config.yaml.template` и `deploy/stage/config.yaml` (нет секции
`server.trusted_proxies` → дефолт `[]` из `orchestrator/config.py:76`).

**Суть:** `resolve_client_ip()` доверяет `X-Real-IP`/`X-Forwarded-For` только
от `trusted_proxies`. В проде список пуст → для всего трафика через nginx
`client_ip` = IP контейнера nginx. Последствия:
- логин-лимитер 5 req/60s становится **глобальным** — 5 неудачных попыток
  блокируют логин всем пользователям (`orchestrator/main.py:267,279-282`);
- общий лимит 120 req/60s — тоже общий на всех;
- `AuditLog.client_ip` одинаков во всех записях, атрибуция по IP невозможна.

**Почему блокер:** тривиальный перманентный DoS аутентификации + обнуление
атрибуции в audit trail, который пишется под комплаенс.

**Фикс (конфиг, не код):**
- [x] `deploy/prod/config.yaml.template` — секция `server.trusted_proxies` с IP/подсетью docker-сети nginx и комментарием
- [x] `deploy/stage/config.yaml` — то же
- [x] `deploy/prod/README.md` — пункт чеклиста запуска рядом с `auth.cors_origins` (P17)
- [x] тест: `resolve_client_ip()` берёт `X-Real-IP`, когда peer в `trusted_proxies`, и игнорирует, когда нет (проверить, что покрытие уже есть)

---

## S. Существенные — долг пилота

### - [x] S1. P12 закрыт формально: `HttpClient` не используется ни одним call-site

> Закрыто 2026-07-28 — отчёт: [`http-client-sync-facade.md`](../compose/reports/http-client-sync-facade.md).

**Где:** `soar/tools/http_client.py`, `soar/connectors/*`, `soar/actions/` (пуст).

**Суть:** единственные упоминания `http_client` в `soar/` — сам модуль,
`soar/tools/__init__.py` и `soar/runner.py`. Все 24 коннектора синхронные и
ходят через `requests` напрямую; `HttpClient.get_json`/`post_json` — `async def`,
из синхронного метода коннектора не вызываются без `asyncio.run()`. Проблема,
ради которой писался P12 (TI-запросы без кэша и без единого лога), в проде
остаётся в прежнем виде.

**Фикс:** синхронный фасад над `HttpClient` (или синхронная реализация с тем
же контрактом логирования/кэша) + миграция 2-3 TI-коннекторов как образец.
**Требует спеки.** Пометить P12 в `UPGRADE-v2.md` как «тул поставлен, адаптация
не сделана» (см. D5).

### - [x] S2. `from soar.tools import http_client` даёт неинициализированный экземпляр

> Закрыто 2026-07-28 — отчёт: [`http-client-init-order.md`](../compose/reports/http-client-init-order.md).

**Где:** `soar/runner.py:36-37` vs `:63`, `soar/tools/__init__.py:4-6`.

**Суть:** `actions.init()`/`connectors.init()` импортируют модули на строках
36-37, а `tools.http_client = _build_http_client(config)` — на строке 63.
Любой модуль с `from soar.tools import http_client` на верхнем уровне навсегда
захватывает дефолтный экземпляр без конфига. Докстринг в
`soar/tools/__init__.py` обещает ровно обратное.

**Фикс:**
- [x] тест: action-модуль, импортирующий `http_client` верхним уровнем, видит сконфигурированный экземпляр
- [x] перенести построение синглтона выше `workflows.init()`/`connectors.init()`/`actions.init()` (либо ленивый module-level `__getattr__`)

### - [x] S3. `POST /transfer/export` отдаёт секреты без редакции и без audit-записи

> Закрыто 2026-07-28 — отчёт: [`transfer-export-import-hardening.md`](../compose/reports/transfer-export-import-hardening.md).

**Где:** `orchestrator/api/transfer.py:38-39` (yml как есть), весь роутер —
ни одного `audit_service.record()`.

**Суть:** модель P13 объявлена как «write-only секреты, прочитать через API
нельзя никому, включая admin» — экспорт это тот же API, редакции там нет.
Выгрузка всех credential'ов системы не оставляет следа в audit trail.
`/import` дополнительно не прогоняет код через `validate_*_code` (обход P1) и
не коммитит импортированные файлы (недоступны git-история и rollback из P8).

**Фикс:**
- [x] тест: экспортированный `{name}.yml` содержит `********` вместо hidden-полей
- [x] тест: `/export` и `/import` пишут `audit_log`
- [x] тест: `/import` отклоняет невалидный код воркфлоу/экшена/коннектора
- [x] применить `_redact_yaml` к yml в экспорте (переиспользовать, не дублировать)
- [x] `audit_service.record()` в обоих роутах
- [x] `/import` — `validate_*_code` перед записью + `git.commit()` после

### - [x] S4. Запуск workflow не пишется в audit-log

> Закрыто 2026-07-28 — отчёт: [`job-webhook-audit-logging.md`](../compose/reports/job-webhook-audit-logging.md).

**Где:** `orchestrator/api/jobs.py:23-38` (`POST /jobs`),
`orchestrator/api/webhooks.py:11-43`.

**Суть:** аудируется только `job.cancel`. Запуск workflow — самое мутирующее
действие в системе (блокировка IP, отключение учётки, удаление файла).
AGENTS.md утверждает, что `record()` вызывается «из каждого мутирующего роута».

**Фикс:**
- [x] тест: `POST /jobs` пишет `job.create` с `workflow_name` и `job_id`
- [x] тест: успешный вебхук пишет `job.create` с `actor_type` вебхука
- [x] `audit_service.record()` в обоих роутах (для вебхука — синтетический актор, у него нет `CurrentUser`; решить формат до реализации)

### - [x] S5. Логи джобов не чистятся никогда

> Закрыто 2026-07-28 — отчёт: [`job-log-purge.md`](../compose/reports/job-log-purge.md).

**Где:** `orchestrator/store/sql_job_store.py:102-115` (`purge_old`),
`orchestrator/core/scheduler.py:22-32` (retention job).

**Суть:** `jobs.retention_days` удаляет строки в БД, но файлы
`/var/log/soar/jobs/<workflow>/<job_id>.log` не трогает ничто. Удаление строки
уничтожает `log_path`, после чего файл осиротел навсегда. На проде с
`retention_days: 90` — гарантированное заполнение диска.

**Фикс:**
- [x] тест: `purge_old` удаляет файлы логов удаляемых джобов
- [x] собрать `log_path` перед `DELETE`, удалить файлы после успешного коммита транзакции; ошибки удаления файла логировать, не ронять cleanup

### - [x] S6. Партиальный индекс из спеки P14 не создаётся на штатной установке прода

> Закрыто 2026-07-28 — отчёт: [`workflow-jobs-index-table-prefix.md`](../compose/reports/workflow-jobs-index-table-prefix.md).

**Где:** `alembic/versions/42fbd47b0d46_add_workflow_jobs_pending_index.py`,
`orchestrator/store/models.py:10-14`, `deploy/soarctl_lib/migrate.py:26-27`.

**Суть:** штатная последовательность прода — `soarctl up && soarctl migrate
--fresh`, а `--fresh` = `alembic stamp head`, который не выполняет DDL. На
любой свежей проде индекса нет. Смежно: миграции используют литеральное
`workflow_jobs`, игнорируя `database.table_prefix` — для `deploy/stage`
(`table_prefix: "stage_"`) `alembic upgrade head` работает не с той таблицей,
что приложение.

**Фикс (варианты, выбрать в спеке):** объявить индекс в модели (тогда его
создаёт `create_all`) **или** развести `--fresh` на «stamp + догоняющие
индексы». Решить заодно, чинить ли `table_prefix` в миграциях или закрепить
как ограничение.

### - [x] S7. Тест-сьют на `main` красный

> Закрыто 2026-07-28 — отчёт: [`test-suite-green.md`](../compose/reports/test-suite-green.md).

**Где:** `tests/soar/tools/test_openapi.py::test_generate_config`,
`soar/tools/openapi.py:227-232`.

**Суть:** `1 failed, 648 passed, 1 skipped`. Тест ждёт имя инстанса `my_api:`,
код генерирует `MyApiConnector1:`. Расхождение не разрешено — надо решить,
какое поведение правильное, и привести второе к нему.
(Отдельно: 5 тестовых модулей не собираются из-за отсутствующих опциональных
зависимостей `pymisp`/`pymysql`/`shodan`/`impacket`/`pywinrm` — это окружение,
не код; зафиксировать как требование dev-окружения или пометить `skipif`.)

**Фикс:**
- [x] выбрать целевое имя инстанса и синхронизировать код с тестом
- [x] `skipif` по наличию опциональной зависимости в 5 модулях коннекторов
      (уточнение по факту: пятый пакет — `smbprotocol`, не `impacket`, как
      было названо выше — см. отчёт)

### - [x] S8. Новые коннекторы не получают `HIDDEN_FIELDS`

> Закрыто 2026-07-28 — отчёт: [`new-connector-hidden-fields-default.md`](../compose/reports/new-connector-hidden-fields-default.md).

**Где:** `orchestrator/api/connectors.py:50-64` (`CONNECTOR_TEMPLATE`),
`soar/tools/openapi.py` (генератор), `openapi.py:239-248` (`_generate_config`
кладёт в yml `api_key`/`token`/`password`).

**Суть:** все 24 встроенных коннектора объявление имеют, любой **новый** — нет.
Редакция P13 opt-in с дефолтом «не редактировать», а именно этим путём
коннекторы и будут создаваться в проде.

**Фикс:**
- [x] тест: коннектор, созданный через `POST /connectors/{name}`, имеет `HIDDEN_FIELDS` в шаблоне
- [x] тест: сгенерированный из OpenAPI-спеки коннектор объявляет в `HIDDEN_FIELDS` поля из `securitySchemes`
- [x] `HIDDEN_FIELDS: ClassVar[set[str]] = set()` в `CONNECTOR_TEMPLATE`
- [x] `OpenAPIGenerator` заполняет `HIDDEN_FIELDS` именами auth-полей

---

## M. Мелкие — по ходу пилота

> Закрыты 2026-07-29 точечными правками (без отдельного цикла specs/plans/reports,
> как и предписано правилом в шапке файла) — тесты зелёные, полный прогон
> `pytest tests/` не показал регрессий (780 passed, 1 skipped).

- [x] **M1.** `HttpClient` логирует полный URL с query-string — при переходе TI-коннекторов на него API-ключи вида `?apikey=...` попадут в лог. Редактировать query-параметры перед логированием. `soar/tools/http_client.py:145,159` — **закрыто**: добавлена `_log_safe_url()` (обрезает query/fragment), применена во всех 4 местах логирования (`HttpClient`/`SyncHttpClient` × GET/POST), тесты на нередактированный `apikey` в `tests/soar/tools/test_http_client.py`.
- [x] **M2.** `RateLimiter._requests` — `defaultdict`, ключи-IP никогда не удаляются, растёт неограниченно. `orchestrator/main.py:225-237` — **закрыто**: добавлен `_sweep()`, вызывается из `is_allowed()` не чаще раза за `window`, удаляет ключи с полностью устаревшими таймстемпами; тесты в `tests/orchestrator/api/test_rate_limiter.py`.
- [x] **M3.** `GET /connectors/preview` вызывает `preview_spec(Request, body)` — передаёт **класс** `Request`, а не инстанс; работает только потому, что аргумент не используется. `orchestrator/api/connectors.py:332` — **закрыто**: `preview_spec_url` теперь принимает `request: Request` и передаёт реальный инстанс; regression-тест `test_preview_spec_url` в `tests/orchestrator/api/test_connectors_api.py`.
- [x] **M4.** SSRF-guard резолвит DNS, затем httpx резолвит повторно — окно DNS-rebinding (смягчено `follow_redirects=False`). `orchestrator/api/connectors.py:290-315`, `soar/tools/http_client.py:80-105` — **закрыто как принятый остаточный риск** (по аналогии с P5/P6/P10/P11/P15): полноценный фикс требует IP-pinning (кастомный transport поверх httpx) ради TOCTOU-окна, эксплуатируемого только при контроле над DNS того же вызывающего процесса — не сочтено оправданным на фоне сложности/хрупкости; решение задокументировано в докстрингах обеих `_validate_external_url`.
- [x] **M5.** `stream_log` открывает `job.log_path` без проверки существования → 500 внутри SSE-генератора. `orchestrator/api/logs.py:39` — **закрыто**: генератор ждёт появления файла (тот же поллинг-паттерн, что и ожидание новых строк), выходит без ошибки, если джоба уже в терминальном статусе и файл так и не появился; тест `test_log_stream_file_not_yet_created_terminal_job_ends_cleanly`.
- [x] **M6.** `handle_webhook`: `await request.json()` без try → 500 на невалидном JSON от внешней системы. `orchestrator/api/webhooks.py:32` — **закрыто**: обёрнуто в `try/except ValueError` → 400; тест `test_webhook_invalid_json_body_returns_400`.
- [x] **M7.** `ConcurrencyPolicy.QUEUE` + `SQLQueue` = вечный цикл: `pop()` уже ставит `RUNNING`, а busy-wait ждёт «нет RUNNING». Латентно — `load_workflow_metas` никогда не назначает `QUEUE`. `orchestrator/core/worker.py:47-49`, `orchestrator/core/queue/sql_queue.py:56-60` — **закрыто**: `count_by_status` получил `exclude_job_id`, busy-wait в `worker.py` исключает свою же джобу из подсчёта `RUNNING`; regression-тест `test_queue_policy_does_not_deadlock_on_sql_queue_self_claim` (без фикса зависал бы — обёрнут в `asyncio.wait_for`).
- [x] **M8.** `decode_access_token` → `int(payload["sub"])` без защиты: токен, подписанный тем же ключом, но без `sub`, даёт 500 вместо 401. `orchestrator/auth/dependencies.py:42` — **закрыто**: `int(payload["sub"])` обёрнут в `try/except (KeyError, TypeError, ValueError)` → 401 + `auth.invalid_token_claims`; тесты на отсутствующий и нечисловой `sub` в `tests/orchestrator/auth/test_security_event_logging.py`.
- [x] **M9.** `soar/connectors/irp/` — пустая директория (только `__pycache__`), светится в `GET /connectors` как коннектор без кода — **уже закрыто до этого прохода**: директория отсутствует в дереве (см. `docs/compose/plans/2026-07-10-remove-irp-tools-api.md`), проверено `git`/`glob` — нечего чинить.
- [x] **M10.** Redis остаётся в `deploy/prod/docker-compose.yml:3-13` после перехода на `queue.backend: sql` — неиспользуемый компонент в проде — **закрыто документацией, не удалением**: сервис остаётся намеренно доступным для опционального `soar.http_client.cache_backend: redis` (см. прецедент в `deploy/stage/README.md` → «Queue Backend Configuration»); добавлен аналогичный поясняющий комментарий в `deploy/prod/docker-compose.yml`.
- [x] **M11.** Прод публикует `8000:8000` без TLS; JWT и пароли ходят открытым текстом, если снаружи нет своего LB. Явный пункт runbook'а. `deploy/prod/docker-compose.yml:33-34` — **закрыто**: явный пункт добавлен в `deploy/prod/README.md` рядом с чеклистом `cors_origins`/`trusted_proxies`.
- [x] **M12.** `job.context` (payload вебхука целиком) хранится в БД и отдаётся роли `viewer` через `GET /jobs`. `orchestrator/models/job.py:38-51`, `orchestrator/api/jobs.py:41` — **закрыто**: `GET /jobs` и `GET /jobs/{id}` теперь резолвят `CurrentUser` и вырезают `context` из ответа для роли `viewer` (`analyst`+ видят как раньше); тесты в `tests/orchestrator/api/test_jobs_api.py`.
- [x] **M13.** `GET /workflows` отдаёт webhook-токен (`token`, если задан) роли `viewer` — самой низкопривилегированной read-only роли достаётся credential уровня «запустить произвольный workflow без дальнейшей авторизации» (см. `orchestrator/api/webhooks.py:28` — токен единственная защита эндпоинта). Найдено при работе над `docs/compose/specs/2026-07-29-ui-control-visibility-design.md` (стадия 3, отображение webhook-URL в UI) — UI периметр не расширяет (значение и так читаемо через DevTools любым авторизованным `viewer`), но сама раздача токена такой роли — самостоятельный найденный баг бэкенда. `orchestrator/api/workflows.py:80,96-97` (`_RO`, `if hasattr(m, "token") and m.token: item["token"] = m.token`) — **закрыто**: `token` теперь включается только если `user.role in _RW` (`analyst`/`admin`/`agent`); тесты в `tests/orchestrator/api/test_workflows_api.py`.

---

## D. Документация — расхождения с кодом

Правятся **вместе** с соответствующим кодовым пунктом, не раньше (правило
`CLAUDE.md`: не обновлять агентские файлы заранее).

- [x] **D1.** `docs/agents/security-patterns.md`: «значения hidden-полей маскируются в `GET /config`, `/config/history[/{commit}]`, `/config/diff` для всех ролей, включая admin» — неверно дважды (B2: diff отдаёт контекстные строки; S3: `/transfer/export` без редакции). Обновить с B2 и S3 — **закрыто**, оба уточнения внесены (B2: диф покрывает и контекстные строки; S3: `/transfer/export` покрыт тем же write-only периметром)
- [x] **D2.** `docs/agents/security-patterns.md`: «`agent` получает 403 при попытке сменить credential» — обходится через B3. Обновить с B3 — **закрыто**, дополнено «и при попытке переписать код коннектора»
- [x] **D3.** `AGENTS.md`: audit пишется «из каждого мутирующего роута» — нет для `POST /jobs`, `POST /webhooks/{name}`, `/transfer/{export,import}`. Обновить с S3/S4 — **закрыто**, все три пути теперь пишут audit-запись, формулировка обновлена
- [x] **D4.** `soar/tools/__init__.py:4-6`: «actions can always `from soar.tools import http_client`» — не работает. Обновить с S2 — **закрыто**: после S2 утверждение докстринга стало фактически верным, правка текста не потребовалась
- [x] **D5.** `UPGRADE-v2.md` P12 помечен «Реализовано» — тул поставлен, ни одного call-site нет, адаптация невозможна без синхронного фасада. Переформулировать статус с S1. Там же: «Actions для VT, AbuseCh, Kaspersky…» — таких actions не существует, это коннекторы (`soar/actions/` пуст) — **закрыто**, статус и формулировка поправлены
- [x] **D6.** `UPGRADE-v2.md` P15: recovery от self-lockout опирается на деактивацию, которая не работает (B1). Перепроверить формулировку принятого риска после B1 — **закрыто**
- [x] **D7.** `alembic/versions/42fbd47b0d46_*.py` ссылается на «known-limitation #9» — номер после перенумерации в v0.12 не существует (актуальный — #8). Поправить ссылку — **закрыто попутно в S6**: докстринг миграции переписан целиком (см. отчёт S6), сталая ссылка на «#9» в нём больше не встречается
- [x] **D8.** `UPGRADE-v2.md` P14 / спека `2026-07-27-sql-job-queue-design.md` [S5]: партиальный индекс на штатной установке прода не создаётся. Обновить с S6 — **закрыто**

---

## Что подтверждено как корректно реализованное

Не трогать, регрессии в этих местах при фиксах выше — критичны:

P1 (`validate_*_code` в PUT), P2 (traceback в `WorkflowResult.traceback` →
`runner.main()` → `result_error`), P7 (роль `agent` заведена; `/transfer/*`,
`/auth/*`, `/audit-log`, `PUT /prompts/user` — литеральный `admin`),
P8 (history/diff/restore на всех трёх сущностях), P9 (токен из
`orchestrator_state.yaml` приоритетнее классового), P13 в части `GET /config`
и `/config/history`, P14 (`SQLQueue` — атомарный claim, `FOR UPDATE SKIP
LOCKED` на Postgres; orphan-PENDING исчез, т.к. очередь и стор — одна таблица),
P16 (`git diff --cached --quiet` вместо string-match stderr).

Архитектурных дыр ревью не нашло: разделение `orchestrator`/`soar`,
subprocess-изоляция раннера, очередь поверх одной таблицы, AST-интроспекция
без импорта, git как хранилище версий — внутренне согласованы и держат
нагрузку пилота. Принятые риски P5/P6/P10/P11/P15 остаются приемлемыми
(P15 — после закрытия B1).
