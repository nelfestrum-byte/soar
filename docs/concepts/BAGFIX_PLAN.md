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

## Статус

| Уровень | Всего | Закрыто |
|---------|-------|---------|
| B (блокеры) | 4 | 0 |
| S (существенные) | 8 | 0 |
| M (мелкие) | 12 | 0 |
| D (документация) | 8 | 0 |

**Критерий выхода на пилот: все B закрыты.** S/M/D чинятся во время пилота.

---

## B. Блокеры — до включения на живой инфраструктуре

### - [ ] B1. Деактивация пользователя не отзывает доступ

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
- [ ] тест: деактивированный пользователь получает 401 на `/auth/refresh`
- [ ] тест: `update_user(is_active=False)` помечает `revoked_at` всем живым refresh-токенам
- [ ] `rotate_refresh_token()` — вернуть `None`, если `user is None or not user.is_active`
- [ ] `update_user()` — при `is_active=False` (и при смене роли) проставить `revoked_at` активным токенам пользователя
- [ ] то же поведение для `set_user_active()` (путь CLI)

### - [ ] B2. `GET /connectors/{name}/config/diff` отдаёт секреты роли `viewer`

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
- [ ] тест: diff двух версий, где hidden-поле **не менялось**, а менялось соседнее → значение замаскировано
- [ ] тест: diff, где hidden-поле менялось (`+`/`-`) → обе стороны замаскированы (регрессия существующего поведения)
- [ ] `_DIFF_KV_RE` → `^([+\- ])(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$`, сохранить исходный префиксный символ в выводе

### - [ ] B3. Роль `agent` обходит редакцию секретов, переписав `HIDDEN_FIELDS`

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
- [ ] тест: `agent` получает 403 на `PUT /connectors/{name}/code`
- [ ] тест: `admin` по-прежнему может писать код коннектора
- [ ] `PUT /connectors/{name}/code` — литеральный `("admin",)` вместо `_ADMIN`, как уже сделано для `/transfer/*` и `PUT /prompts/user`
- [ ] отразить сужение прав `agent` в `docs/agents/security-patterns.md` (см. D2)

> Альтернатива, если правка коннекторов агентом реально понадобится: запрет
> сужения `HIDDEN_FIELDS` относительно предыдущей версии файла. Дороже,
> отдельная спека, **не в этот трек**.

### - [ ] B4. За nginx все клиенты выглядят одним IP

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
- [ ] `deploy/prod/config.yaml.template` — секция `server.trusted_proxies` с IP/подсетью docker-сети nginx и комментарием
- [ ] `deploy/stage/config.yaml` — то же
- [ ] `deploy/prod/README.md` — пункт чеклиста запуска рядом с `auth.cors_origins` (P17)
- [ ] тест: `resolve_client_ip()` берёт `X-Real-IP`, когда peer в `trusted_proxies`, и игнорирует, когда нет (проверить, что покрытие уже есть)

---

## S. Существенные — долг пилота

### - [ ] S1. P12 закрыт формально: `HttpClient` не используется ни одним call-site

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

### - [ ] S2. `from soar.tools import http_client` даёт неинициализированный экземпляр

**Где:** `soar/runner.py:36-37` vs `:63`, `soar/tools/__init__.py:4-6`.

**Суть:** `actions.init()`/`connectors.init()` импортируют модули на строках
36-37, а `tools.http_client = _build_http_client(config)` — на строке 63.
Любой модуль с `from soar.tools import http_client` на верхнем уровне навсегда
захватывает дефолтный экземпляр без конфига. Докстринг в
`soar/tools/__init__.py` обещает ровно обратное.

**Фикс:**
- [ ] тест: action-модуль, импортирующий `http_client` верхним уровнем, видит сконфигурированный экземпляр
- [ ] перенести построение синглтона выше `workflows.init()`/`connectors.init()`/`actions.init()` (либо ленивый module-level `__getattr__`)

### - [ ] S3. `POST /transfer/export` отдаёт секреты без редакции и без audit-записи

**Где:** `orchestrator/api/transfer.py:38-39` (yml как есть), весь роутер —
ни одного `audit_service.record()`.

**Суть:** модель P13 объявлена как «write-only секреты, прочитать через API
нельзя никому, включая admin» — экспорт это тот же API, редакции там нет.
Выгрузка всех credential'ов системы не оставляет следа в audit trail.
`/import` дополнительно не прогоняет код через `validate_*_code` (обход P1) и
не коммитит импортированные файлы (недоступны git-история и rollback из P8).

**Фикс:**
- [ ] тест: экспортированный `{name}.yml` содержит `********` вместо hidden-полей
- [ ] тест: `/export` и `/import` пишут `audit_log`
- [ ] тест: `/import` отклоняет невалидный код воркфлоу/экшена/коннектора
- [ ] применить `_redact_yaml` к yml в экспорте (переиспользовать, не дублировать)
- [ ] `audit_service.record()` в обоих роутах
- [ ] `/import` — `validate_*_code` перед записью + `git.commit()` после

### - [ ] S4. Запуск workflow не пишется в audit-log

**Где:** `orchestrator/api/jobs.py:23-38` (`POST /jobs`),
`orchestrator/api/webhooks.py:11-43`.

**Суть:** аудируется только `job.cancel`. Запуск workflow — самое мутирующее
действие в системе (блокировка IP, отключение учётки, удаление файла).
AGENTS.md утверждает, что `record()` вызывается «из каждого мутирующего роута».

**Фикс:**
- [ ] тест: `POST /jobs` пишет `job.create` с `workflow_name` и `job_id`
- [ ] тест: успешный вебхук пишет `job.create` с `actor_type` вебхука
- [ ] `audit_service.record()` в обоих роутах (для вебхука — синтетический актор, у него нет `CurrentUser`; решить формат до реализации)

### - [ ] S5. Логи джобов не чистятся никогда

**Где:** `orchestrator/store/sql_job_store.py:102-115` (`purge_old`),
`orchestrator/core/scheduler.py:22-32` (retention job).

**Суть:** `jobs.retention_days` удаляет строки в БД, но файлы
`/var/log/soar/jobs/<workflow>/<job_id>.log` не трогает ничто. Удаление строки
уничтожает `log_path`, после чего файл осиротел навсегда. На проде с
`retention_days: 90` — гарантированное заполнение диска.

**Фикс:**
- [ ] тест: `purge_old` удаляет файлы логов удаляемых джобов
- [ ] собрать `log_path` перед `DELETE`, удалить файлы после успешного коммита транзакции; ошибки удаления файла логировать, не ронять cleanup

### - [ ] S6. Партиальный индекс из спеки P14 не создаётся на штатной установке прода

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

### - [ ] S7. Тест-сьют на `main` красный

**Где:** `tests/soar/tools/test_openapi.py::test_generate_config`,
`soar/tools/openapi.py:227-232`.

**Суть:** `1 failed, 648 passed, 1 skipped`. Тест ждёт имя инстанса `my_api:`,
код генерирует `MyApiConnector1:`. Расхождение не разрешено — надо решить,
какое поведение правильное, и привести второе к нему.
(Отдельно: 5 тестовых модулей не собираются из-за отсутствующих опциональных
зависимостей `pymisp`/`pymysql`/`shodan`/`impacket`/`pywinrm` — это окружение,
не код; зафиксировать как требование dev-окружения или пометить `skipif`.)

**Фикс:**
- [ ] выбрать целевое имя инстанса и синхронизировать код с тестом
- [ ] `skipif` по наличию опциональной зависимости в 5 модулях коннекторов

### - [ ] S8. Новые коннекторы не получают `HIDDEN_FIELDS`

**Где:** `orchestrator/api/connectors.py:50-64` (`CONNECTOR_TEMPLATE`),
`soar/tools/openapi.py` (генератор), `openapi.py:239-248` (`_generate_config`
кладёт в yml `api_key`/`token`/`password`).

**Суть:** все 24 встроенных коннектора объявление имеют, любой **новый** — нет.
Редакция P13 opt-in с дефолтом «не редактировать», а именно этим путём
коннекторы и будут создаваться в проде.

**Фикс:**
- [ ] тест: коннектор, созданный через `POST /connectors/{name}`, имеет `HIDDEN_FIELDS` в шаблоне
- [ ] тест: сгенерированный из OpenAPI-спеки коннектор объявляет в `HIDDEN_FIELDS` поля из `securitySchemes`
- [ ] `HIDDEN_FIELDS: ClassVar[set[str]] = set()` в `CONNECTOR_TEMPLATE`
- [ ] `OpenAPIGenerator` заполняет `HIDDEN_FIELDS` именами auth-полей

---

## M. Мелкие — по ходу пилота

- [ ] **M1.** `HttpClient` логирует полный URL с query-string — при переходе TI-коннекторов на него API-ключи вида `?apikey=...` попадут в лог. Редактировать query-параметры перед логированием. `soar/tools/http_client.py:145,159`
- [ ] **M2.** `RateLimiter._requests` — `defaultdict`, ключи-IP никогда не удаляются, растёт неограниченно. `orchestrator/main.py:225-237`
- [ ] **M3.** `GET /connectors/preview` вызывает `preview_spec(Request, body)` — передаёт **класс** `Request`, а не инстанс; работает только потому, что аргумент не используется. `orchestrator/api/connectors.py:332`
- [ ] **M4.** SSRF-guard резолвит DNS, затем httpx резолвит повторно — окно DNS-rebinding (смягчено `follow_redirects=False`). `orchestrator/api/connectors.py:290-315`, `soar/tools/http_client.py:80-105`
- [ ] **M5.** `stream_log` открывает `job.log_path` без проверки существования → 500 внутри SSE-генератора. `orchestrator/api/logs.py:39`
- [ ] **M6.** `handle_webhook`: `await request.json()` без try → 500 на невалидном JSON от внешней системы. `orchestrator/api/webhooks.py:32`
- [ ] **M7.** `ConcurrencyPolicy.QUEUE` + `SQLQueue` = вечный цикл: `pop()` уже ставит `RUNNING`, а busy-wait ждёт «нет RUNNING». Латентно — `load_workflow_metas` никогда не назначает `QUEUE`. `orchestrator/core/worker.py:47-49`, `orchestrator/core/queue/sql_queue.py:56-60`
- [ ] **M8.** `decode_access_token` → `int(payload["sub"])` без защиты: токен, подписанный тем же ключом, но без `sub`, даёт 500 вместо 401. `orchestrator/auth/dependencies.py:42`
- [ ] **M9.** `soar/connectors/irp/` — пустая директория (только `__pycache__`), светится в `GET /connectors` как коннектор без кода
- [ ] **M10.** Redis остаётся в `deploy/prod/docker-compose.yml:3-13` после перехода на `queue.backend: sql` — неиспользуемый компонент в проде
- [ ] **M11.** Прод публикует `8000:8000` без TLS; JWT и пароли ходят открытым текстом, если снаружи нет своего LB. Явный пункт runbook'а. `deploy/prod/docker-compose.yml:33-34`
- [ ] **M12.** `job.context` (payload вебхука целиком) хранится в БД и отдаётся роли `viewer` через `GET /jobs`. `orchestrator/models/job.py:38-51`, `orchestrator/api/jobs.py:41`

---

## D. Документация — расхождения с кодом

Правятся **вместе** с соответствующим кодовым пунктом, не раньше (правило
`CLAUDE.md`: не обновлять агентские файлы заранее).

- [ ] **D1.** `docs/agents/security-patterns.md`: «значения hidden-полей маскируются в `GET /config`, `/config/history[/{commit}]`, `/config/diff` для всех ролей, включая admin» — неверно дважды (B2: diff отдаёт контекстные строки; S3: `/transfer/export` без редакции). Обновить с B2 и S3
- [ ] **D2.** `docs/agents/security-patterns.md`: «`agent` получает 403 при попытке сменить credential» — обходится через B3. Обновить с B3
- [ ] **D3.** `AGENTS.md`: audit пишется «из каждого мутирующего роута» — нет для `POST /jobs`, `POST /webhooks/{name}`, `/transfer/{export,import}`. Обновить с S3/S4
- [ ] **D4.** `soar/tools/__init__.py:4-6`: «actions can always `from soar.tools import http_client`» — не работает. Обновить с S2
- [ ] **D5.** `UPGRADE-v2.md` P12 помечен «Реализовано» — тул поставлен, ни одного call-site нет, адаптация невозможна без синхронного фасада. Переформулировать статус с S1. Там же: «Actions для VT, AbuseCh, Kaspersky…» — таких actions не существует, это коннекторы (`soar/actions/` пуст)
- [ ] **D6.** `UPGRADE-v2.md` P15: recovery от self-lockout опирается на деактивацию, которая не работает (B1). Перепроверить формулировку принятого риска после B1
- [ ] **D7.** `alembic/versions/42fbd47b0d46_*.py` ссылается на «known-limitation #9» — номер после перенумерации в v0.12 не существует (актуальный — #8). Поправить ссылку
- [ ] **D8.** `UPGRADE-v2.md` P14 / спека `2026-07-27-sql-job-queue-design.md` [S5]: партиальный индекс на штатной установке прода не создаётся. Обновить с S6

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
