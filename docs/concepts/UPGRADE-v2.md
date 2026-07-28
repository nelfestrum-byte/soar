# UPGRADE-v2.md — готовность SOAR к деплою на живую инфраструктуру

> Контекст: три этапа `UPGRADE.md` (Agent Dev-Loop) реализованы, проект
> приближается к первому релизу на боевую инфраструктуру. Этот документ —
> pre-release ревью: то, что не было в фокусе `UPGRADE.md` (адаптация под
> LLM-агента), но становится критичным при переходе от MVP к живой системе
> с реальными credentials, реальными пользователями и реальными
> инцидентами. Работает вместе с `UPGRADE.md` (часть 1 и реестр рисков там
> не переоткрываются, кроме P6 — см. P13 ниже, который уточняет его оценку)
> и `docs/agents/known-limitations.md`.
>
> Нумерация проблем продолжает `UPGRADE.md` (P1–P11) начиная с P12.
> Каждый пункт, закрываемый в этом цикле, получает обычный спек/план по
> правилам `CLAUDE.md`; этот файл — карта находок, не замена спекам.

## Принцип этого документа

Как и в `UPGRADE.md`: если решение простое и точечное — делаем сейчас
(спека → план → реализация). Если требует новой подсистемы или крупного
редизайна — фиксируем как риск с условием пересмотра, а не блокируем
релиз недоделанной инфраструктурой под гипотетическую нагрузку.

## Часть 1 — Найденные проблемы

### P12. Threat-intel actions бьют во внешние API без кэша и логирования

Обнаружено при разборе исходного запроса пользователя ("нет логирующего и
кеширующего middleware инструмента для HTTP"), подтверждено по коду:
`soar/tools/http_client.py` не существует — `grep` по всему репозиторию на
`CachedHttpClient`/`http_client`/`HttpCache` даёт совпадения только в
документации (`AGENTS.md`, `CLAUDE.md`, `docs/compose/specs/2026-07-03-v06-upgrade-design.md`),
не в коде. Это уже специфицированная, но не реализованная фича из
v0.6-спеки (Feature 1) — сама спека написана 2026-07-03 и с тех пор не
исполнена. Actions для VT, AbuseCh, Kaspersky, RST, URLhaus, Shodan, Fofa,
Censys, crt.sh, MISP делают HTTP-запросы напрямую, без кэша (повторные
одинаковые запросы на каждый прогон workflow) и без единого лога
(нет трассировки enrichment-вызовов при разборе инцидента постфактум).

**Решение:** см. `docs/compose/specs/2026-07-27-http-client-design.md`.
Заменяет Feature 1 v0.6-спеки — Feature 2 (per-workflow метрики) и
Feature 3 (dry-run конвенция) из v0.6-спеки остаются в её скоупе,
не переносятся сюда.

### P13. Секреты коннекторов доступны в plaintext роли `viewer` — через текущий конфиг и через git-историю

Уточняет и переоценивает P6 из `UPGRADE.md`. P6 рассматривал риск только
в контексте роли `agent` ("агент не получает роль выше необходимой,
доступа к audit-log/user-management у него всё равно нет"). Проверка кода
показала, что вопрос шире:

```python
# orchestrator/api/connectors.py:29
_RO = ("viewer", "analyst", "service", "admin", "agent")
```

`GET /connectors/{name}/config` (`connectors.py:429`) висит на `_RO` —
самая низкопривилегированная read-only роль `viewer` читает пароли/
API-ключи/токены всех коннекторов (SSH, AD, БД, SMTP, Telegram,
VirusTotal, Shodan, Censys и т.д.) открытым текстом. Хуже: `PUT
/connectors/{name}/config` (`connectors.py:498-532`) пишет сырой YAML и
коммитит его в git через `GitManager` — а `GET .../config/history`,
`.../config/history/{commit}`, `.../config/diff` (все три — тоже `_RO`)
отдают содержимое **любой прошлой версии** файла, то есть каждый
когда-либо сохранённый пароль остаётся читаемым той же ролью `viewer`
через историю, даже если текущее значение как-то замаскировать.

На живой инфраструктуре роль `viewer` обычно раздаётся свободно именно
потому, что считается безопасной (SOC-аналитику для дашборда, сервисному
боту для чтения статуса) — риск куда выше, чем оценка P6 предполагала.

**Решение:** см. `docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`.

### P14. `queue.backend: redis` — дефолт в `deploy/prod/config.yaml.template`, несёт known-limitation #2

`deploy/prod/config.yaml.template:5-10` включает Redis-очередь по
умолчанию для продовых деплоев. Known-limitation #2
(`docs/agents/known-limitations.md`) уже документирует, что `RedisQueue` —
at-most-once, может тихо терять джобы при обрыве соединения. На MVP-стенде
это был теоретический риск; на живой инфраструктуре, где очередь несёт
реальные IR-задачи, обрыв соединения означает пропущенное расследование
без какого-либо сигнала об этом.

При разборе также обнаружилось: `JobManager.enqueue()`
(`orchestrator/core/job_manager.py:94-96`) пишет `PENDING`-запись в
`JobStore` до `queue.push()` — если джоб теряется в очереди, эта запись
остаётся орфанной навсегда, `recover_on_startup()` её не трогает (видит
только `RUNNING`). Рассмотрены и отклонены Celery+Redis (тянет замену
`JobManager`/`Worker`/`ConcurrencyPolicy`, новый компонент в деплое) и
RabbitMQ (не даёт надёжность бесплатно, тот же класс конфигурационной
нагрузки, что и Redis AOF, без структурного преимущества). Также
установлено, что `backend: memory` не решает проблему для этого риска, а
меняет её на худшую: очередь в памяти гарантированно теряется при **любом**
рестарте процесса (не только блэкауте), тогда как Redis с дефолтными
RDB-снапшотами (`deploy/prod/docker-compose.yml`, volume `redis-data`) уже
частично переживает рестарт.

**Решение:** см. `docs/compose/specs/2026-07-27-sql-job-queue-design.md`.

### P15. Нет защиты от деактивации последнего admin — теперь с реальными пользователями

Known-limitation #8 существовал и на MVP-стенде с тестовыми аккаунтами;
на живой системе `PATCH /auth/users/{id}` будет использоваться реальными
операторами для реального персонала — риск self-lockout (админ A
деактивирует/разжалует admin B, оставшись единственным, кто может
администрировать систему) перестаёт быть теоретическим.

**Решение: ничего не делаем.** Guard в API избыточен — восстановление уже
есть вне API: `python -m orchestrator.auth.cli create-user --role admin`
(`orchestrator/auth/cli.py`) создаёт нового admin-а независимо от текущего
состояния пользователей в БД. Путь требует доступа к серверу/БД, что и
является уместным барьером — self-lockout через API намеренно не чинится
через тот же API. **Принято как остаточный риск, recovery-путь — CLI**, не
пересматривается без нового триггера (например, отказа от прямого доступа
к серверу в проде).

### P16. Тихий пропуск audit-записи при "nothing to commit" — теперь с реальным compliance-ожиданием от audit-log

Known-limitation #7 — `GitManager.commit()` не распознаёт формулировку
`"nothing added to commit but untracked files present"`, роут делает
ранний `return` до `audit.service.record()`. На живой системе с реальными
инцидентами это означает дыры в audit trail именно там, где комплаенс
ожидает полноты — при наличии `__pycache__`/аналогичных generated-файлов
в рабочих директориях workflows/actions/connectors.

**Решение:** см. `docs/compose/specs/2026-07-27-git-manager-nothing-to-commit-design.md`.
Не расширение string-match и не только `.gitignore` — замена парсинга
текста ошибки на `git diff --cached --quiet` после `git add`, что
детерминированно определяет "нечего коммитить" независимо от локали
git-вывода и от присутствия посторонних untracked-файлов в рабочей
директории.

### P17. CORS origins по умолчанию не переопределены в prod-шаблоне

`orchestrator/config.py:13`: `cors_origins: list[str] =
["http://localhost:3000", "http://localhost:5173"]`.
`deploy/prod/config.yaml.template` не переопределяет `auth.cors_origins`.
Деплой по шаблону "как есть" безопасен (fail-closed — реальный UI-домен
браузером будет отклонён CORS), но UI не залогинится, пока оператор явно
не пропишет `auth.cors_origins` — не баг, а недокументированный шаг
чеклиста запуска.

**Решение:** не код приложения — `soarctl init`
(`deploy/soarctl_lib/env.py::init_instance()`) намеренно детерминирован и
неинтерактивен (air-gapped install без сетевых вызовов и промптов), делать
его интерактивным ради одного поля непропорционально. Вместо этого:
`deploy/prod/config.yaml.template` теперь содержит явный плейсхолдер
`auth.cors_origins: ["https://CHANGE-ME.example.com"]` с комментарием
(вместо отсутствия ключа и молчаливого наследования дефолта из
`config.py`), и `deploy/prod/README.md` — шаг чеклиста между `soarctl
init` и `soarctl up`, требующий прописать реальный домен UI. Сделано
напрямую, без цикла спек — правка не задевает код оркестратора.

## Часть 2 — Спеки

**Реализовано в v0.12** (2026-07-27) — P12/P13/P14/P16, каждая своим
циклом спек → план → отчёт по правилам `CLAUDE.md`. См. `CHANGELOG.md`
v0.12 и отчёты, на которые ссылается каждый пункт ниже.

### P12 → HTTP Client Tool

`docs/compose/specs/2026-07-27-http-client-design.md`. Один класс
`HttpClient` (`soar/tools/http_client.py`) — логирование безусловно,
кэш опционален через `cache_backend: memory | redis | none` в конфиге и
per-call флаг `cached`. Заменяет Feature 1 v0.6-спеки
(`2026-07-03-v06-upgrade-design.md`, `[S4]`) — та спека помечена
превзойдённой в этой части, Feature 2/3 остаются в её собственном скоупе.

**Реализовано** — план: `docs/compose/plans/2026-07-27-http-client.md`,
отчёт: `docs/compose/reports/http-client.md`.

### P13 → Connector Config Schema + Secret Redaction

`docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`. Схема
полей — расширение существующей AST-интроспекции
(`orchestrator/core/introspect.py`) на типы/дефолты конструктора +
явный class-level `HIDDEN_FIELDS` на каждом коннекторе. Редакция значений
на уровне API-ответа (`GET`/`history`/`diff`) для всех ролей включая
`admin` (write-only секреты); `PUT` разделяет права по полю — hidden-поля
меняет только буквально `admin`, не `_ADMIN`-tuple (который включает
`agent`). Формат хранения (`{name}.yml`, git-история) не меняется.
Включает дизайн stage UI (`ui/src/views/Connectors.vue` — форма по схеме
вместо raw-textarea).

**Реализовано** — план: `docs/compose/plans/2026-07-27-connector-secrets-schema.md`,
отчёт: `docs/compose/reports/connector-secrets-schema.md`.

### P16 → GitManager: детерминированное определение "нечего коммитить"

`docs/compose/specs/2026-07-27-git-manager-nothing-to-commit-design.md`.
Убирает string-match по stderr git'а в `GitManager.commit()` (пропускал
формулировку `"nothing added to commit but untracked files present"` и был
потенциально зависим от локали) — заменяет на `git diff --cached --quiet`
после `git add`, детерминированную проверку по exit-коду, не зависящую от
текста вывода git и от посторонних untracked-файлов в рабочей директории.

**Реализовано** — план: `docs/compose/plans/2026-07-27-git-manager-nothing-to-commit.md`,
отчёт: `docs/compose/reports/git-manager-nothing-to-commit.md`.

### P14 → SQL-Backed Job Queue + Job History Retention

`docs/compose/specs/2026-07-27-sql-job-queue-design.md`. `SQLQueue`
(`AbstractJobQueue`) — poll поверх уже существующей таблицы
`workflow_jobs`, не отдельный источник правды: `push()` — no-op (запись
уже сделана `JobManager.enqueue()`), `pop()` — атомарный claim (`FOR
UPDATE SKIP LOCKED` на Postgres, сериализация записи на SQLite). Валиден
только при `jobs.persistence: sql` (fail-fast иначе). Partial-индекс
`(status, triggered_at) WHERE status='PENDING'` держит claim-запрос
дешёвым независимо от объёма истории. Отдельно закрывает обнаруженный
попутно пробел — отсутствие retention для SQL job store: новый
`jobs.retention_days` (дефолт `0`, явный опт-ин) + периодическая очистка
через уже существующий `OrchestratorScheduler`, без нового компонента в
деплое. `deploy/prod/config.yaml.template`/`deploy/stage/config.yaml`
переключаются с `queue.backend: redis` на `sql`.

Партиальный индекс изначально создавался только миграцией
`42fbd47b0d46` — на штатной последовательности первой установки
(`soarctl up && soarctl migrate --fresh`) он молча отсутствовал, `--fresh`
лишь проставляет ревизию, не выполняет DDL (BAGFIX_PLAN S6). Исправлено:
`orchestrator/store/models.py::JobRecord.__table_args__` теперь тоже
объявляет тот же индекс (`Index(...)`), `create_all()` создаёт его на
любой свежей инсталляции независимо от `stamp head`/`upgrade head`;
миграция остаётся источником DDL для апгрейда существующих инсталляций.
Индекс гарантированно создаётся на любом пути установки, не только
апгрейд-пути. См.
`docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md`.

**Реализовано** — план: `docs/compose/plans/2026-07-27-sql-job-queue.md`,
отчёт: `docs/compose/reports/sql-job-queue.md` (индекс на fresh-install —
`docs/compose/plans/2026-07-28-workflow-jobs-index-table-prefix.md`,
`docs/compose/reports/workflow-jobs-index-table-prefix.md`).

## Часть 3 — Реестр рисков (дополняет реестр `UPGRADE.md`)

| # | Риск | Почему не чиним сейчас | Когда пересмотреть |
|---|------|------------------------|---------------------|
| P15 | Нет guard от деактивации последнего admin (known-limitation #7) | Recovery уже есть вне API — `orchestrator/auth/cli.py create-user --role admin` | Не пересматривается; переоценить только при отказе от прямого доступа к серверу/БД в проде |
| P17 | CORS origins по умолчанию (`localhost:3000/5173`) не переопределены в `deploy/prod/config.yaml.template` | Не код, а чеклист запуска | Добавить `auth.cors_origins` в runbook первого деплоя |

## Не в скоупе этого документа

- Полный редизайн секретного хранилища (внешний Vault/SOPS) — см. вариант
  C, отклонённый в пользу схема-driven подхода в спеке P13 как
  избыточный для текущего масштаба.
- Multi-instance/multi-agent сценарии — не изменились с `UPGRADE.md`,
  остаются вне скоупа.
