# SOAR

Минималистичный SOAR (Security Orchestration, Automation and Response) без
LLM: детерминированные автоматические расследования на ECS-схеме,
автоматическое закрытие стандартных кейсов с ложными срабатываниями.

Подробная архитектура, паттерны и правила разработки — в [AGENTS.md](AGENTS.md).
Этот README — про запуск, конфигурацию и деплой.

## Компоненты

| Компонент | Назначение |
|---|---|
| [`soar/`](soar/) | Python-пакет: коннекторы к внешним системам, actions, workflows |
| [`orchestrator/`](orchestrator/) | FastAPI-сервис: очередь задач, воркеры, планировщик, git-версионирование конфигурации |
| [`ui/`](ui/) | Vue.js SPA — стенд для ручного тестирования, не часть продукта |

## Быстрый старт (локально)

```bash
python -m pip install -r orchestrator/requirements.txt
python -m uvicorn orchestrator.main:app --reload --port 8000
```

Без `config.yaml` в рабочей директории сервис стартует с дефолтами:
SQLite-файл `./soar.db`, in-memory очередь и job-store, auth выключена
(анонимный admin — см. [Auth](#auth)). API — `http://localhost:8000/status`,
Swagger — `http://localhost:8000/docs`.

Тесты, линт, типы:

```bash
python -m pytest tests/ -v
ruff check .
mypy orchestrator/ soar/ --ignore-missing-imports
```

## Конфигурация (`config.yaml`)

Путь к файлу — переменная окружения `SOAR_CONFIG` (по умолчанию
`config.yaml` в рабочей директории). Все секции опциональны — отсутствующие
берут значения по умолчанию из `orchestrator/config.py`.

### `workers`

| Поле | По умолчанию | Описание |
|---|---|---|
| `count` | `4` | Число воркеров (asyncio tasks), исполняющих jobs параллельно |
| `default_timeout` | `300` | Таймаут выполнения workflow в секундах, если не задан в его meta |

### `queue` — очередь задач

| Поле | По умолчанию | Описание |
|---|---|---|
| `backend` | `memory` | `memory` (один инстанс) или `redis` (распределённое развёртывание) |
| `redis_url` | `redis://localhost:6379/0` | Только для `backend: redis` |
| `redis_max_connections` | `10` | Размер пула соединений |
| `redis_push_timeout` | `5.0` | Таймаут постановки job в очередь, сек |
| `redis_pop_timeout` | `1.0` | Таймаут ожидания job воркером, сек |

`memory` — только для одного инстанса оркестратора; `redis` — при
нескольких инстансах/распределённой нагрузке. См. Known Limitation #2 в
[AGENTS.md](AGENTS.md#known-limitations) (at-most-once delivery).

### `database` — SQLite / PostgreSQL

| Поле | По умолчанию | Описание |
|---|---|---|
| `url` | `sqlite+aiosqlite:///./soar.db` | SQLAlchemy async URL. Переключение SQLite↔PostgreSQL — только этим полем, отдельного флага backend нет |
| `pool_size` | `10` | Игнорируется для SQLite |
| `max_overflow` | `20` | Игнорируется для SQLite |
| `table_prefix` | `""` | Префикс имён таблиц (`^[a-zA-Z0-9_]*$`) — см. ниже |

Используется auth-таблицами (`users`, `refresh_tokens`, `api_keys`) всегда,
и job-историей (`workflow_jobs`) — если `jobs.persistence: sql`.

**PostgreSQL:**

```yaml
database:
  url: postgresql+asyncpg://soar:soar@postgres:5432/soar
```

**table_prefix** — если одна физическая база данных используется
несколькими инстансами SOAR (staging + prod на одном Postgres, несколько
клиентских деплоев и т.п.), у каждого инстанса должен быть свой
`table_prefix`, иначе таблицы (`users`, `workflow_jobs`, ...) столкнутся по
имени:

```yaml
database:
  table_prefix: "stage_"
```

Применяется на уровне процесса при старте (до импорта ORM-моделей) —
не может быть изменён без рестарта. Подробности реализации —
[AGENTS.md → Database backend](AGENTS.md#database-backend-sqlitepostgresql-и-table-prefix).

### `jobs` — история выполнения workflow

| Поле | По умолчанию | Описание |
|---|---|---|
| `log_dir` | `/var/log/soar/jobs` | Каталог логов job (один файл на job) |
| `keep_completed` | `1000` | Сколько завершённых jobs хранить (FIFO-эвикшн) — только для `persistence: memory` |
| `persistence` | `memory` | `memory` (по умолчанию, история теряется при рестарте) или `sql` (персистентно, поверх `database.url`) |

```yaml
jobs:
  persistence: sql
```

С `sql` job-история переживает рестарт контейнера/процесса, а
`recover_on_startup()` реально восстанавливает зависшие `RUNNING` jobs
после падения (без `sql` это no-op — hранилище на старте пустое).

### `soar` — расположение расширяемого кода

| Поле | По умолчанию | Описание |
|---|---|---|
| `workflows_dir` | `/app/data/workflows` | `.py`-файлы workflow (имя файла = ключ в реестре) |
| `connectors_dir` | `/app/data/connectors` | Директории коннекторов (код + `.yml`-конфиг) |
| `actions_dir` | `/app/data/actions` | `.py`-файлы actions |
| `tools_dir` | `soar/tools` | Read-only discovery для `GET /tools` |

### `git` — версионирование конфигурации

| Поле | По умолчанию | Описание |
|---|---|---|
| `workflows_repo` | `/app/data` | Git-репозиторий, в который автокоммитится любое изменение через API |
| `author_name` / `author_email` | `SOAR Orchestrator` / `soar@local` | Автор автокоммитов |

### `logging`

| Поле | По умолчанию | Описание |
|---|---|---|
| `level` | `INFO` | Уровень логирования (loguru) |
| `file` | `/var/log/soar/orchestrator.log` | Файл лога сервиса |

### `server`

| Поле | По умолчанию | Описание |
|---|---|---|
| `trusted_proxies` | `[]` | IP реверс-прокси для корректного rate-limiting по реальному IP (`["127.0.0.1"]` за nginx в одном контейнере) |

### `auth` — JWT / API-key аутентификация {#auth}

| Поле | По умолчанию | Описание |
|---|---|---|
| `secret_key` | `""` | Пусто = **auth выключена**, все запросы — анонимный admin (Docker-сетевое доверие) |
| `access_token_ttl` | `1800` | TTL access-токена, сек |
| `refresh_token_ttl` | `604800` | TTL refresh-токена, сек |
| `algorithm` | `HS256` | Алгоритм JWT |
| `cors_origins` | `["http://localhost:3000", "http://localhost:5173"]` | Разрешённые origins (обязательны при `allow_credentials=True`, `"*"` не подходит) |

#### Пользователи

**Бутстрап первого admin'а — только через CLI** (пока не существует ни
одного пользователя, вызывать API просто некому — им нужен уже
залогиненный admin). CLI сам читает `SOAR_CONFIG`/`config.yaml` — то же
самое, чем пользуется сервис — так что `database.url` и
`database.table_prefix` всегда совпадают с тем, что реально запущено:

```bash
python -m orchestrator.auth.cli create-user --username admin --role admin
# без --password — интерактивный запрос (getpass)
```

На стенде — та же команда внутри контейнера, `SOAR_CONFIG` уже указывает
на [`deploy/stage/config.yaml`](deploy/stage/config.yaml) (Postgres +
`table_prefix: "stage_"`) через переменную окружения самого контейнера:

```bash
docker compose exec orchestrator python -m orchestrator.auth.cli create-user --username admin --role admin
```

CLI также умеет `deactivate-user`/`activate-user --username X` — тот же
soft-delete, что и ниже, для случаев без доступа к UI/API.

**Дальнейшее управление — через API/UI** (`admin`-only, `Authorization:
Bearer <access_token>`), UI-страница — `/users` (пункт «Users» в навбаре,
виден только `admin`):

```bash
# создать
curl -X POST http://localhost:8000/auth/users \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "at-least-8-chars", "role": "analyst"}'

# список — без password_hash
curl http://localhost:8000/auth/users -H "Authorization: Bearer $ACCESS_TOKEN"

# изменить роль / деактивировать / сбросить пароль — один и тот же PATCH,
# поля независимы и все опциональны
curl -X PATCH http://localhost:8000/auth/users/<id> \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
curl -X PATCH http://localhost:8000/auth/users/<id> \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"is_active": false}'
curl -X PATCH http://localhost:8000/auth/users/<id> \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"password": "new-password-here"}'
```

Жёсткого удаления нет — только soft-delete через `is_active` (уже
проверяется при логине). `PATCH` на **свой собственный** аккаунт с
`is_active: false` возвращает `409` — админ не может случайно
заблокировать сам себя; деактивировать себя может только *другой* admin.
Деактивация блокирует новые `/auth/login`, но уже выданный access-токен
остаётся валиден до истечения `access_token_ttl` (до 30 мин по умолчанию)
— JWT self-contained и не перепроверяется по БД на каждый запрос. Уже
выданные refresh-токены тоже не отзываются автоматически. Все
create/update пишутся в audit log (`GET /audit-log?resource_type=user`) —
пароль в `detail` никогда не попадает, только флаг `password_reset: true`.

#### API-ключи (M2M)

Только через API, нужна роль `admin` (JWT залогиненного admin'а в
заголовке `Authorization: Bearer <access_token>`):

```bash
# создать — ключ возвращается один раз, повторно не показывается
curl -X POST http://localhost:8000/auth/keys \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "soc-core-backend", "role": "service"}'

# список — без самого ключа, только id/name/prefix/role/last_used_at
curl http://localhost:8000/auth/keys -H "Authorization: Bearer $ACCESS_TOKEN"

# удалить
curl -X DELETE http://localhost:8000/auth/keys/<id> -H "Authorization: Bearer $ACCESS_TOKEN"
```

Опционально `expires_at` (ISO 8601) в теле `POST /auth/keys` — TTL ключа.

#### Аутентификация (логин / refresh / logout)

```bash
# логин — access_token (TTL access_token_ttl) + refresh_token (TTL refresh_token_ttl)
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "..."}'

# все дальнейшие запросы — Bearer access_token
curl http://localhost:8000/jobs -H "Authorization: Bearer $ACCESS_TOKEN"

# access_token истёк (401) — обменять refresh_token на новую пару
# (ротация: старый refresh_token отзывается сразу)
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" -d '{"refresh_token": "..."}'

# logout — отозвать refresh_token
curl -X POST http://localhost:8000/auth/logout \
  -H "Content-Type: application/json" -d '{"refresh_token": "..."}'

# кто я
curl http://localhost:8000/auth/me -H "Authorization: Bearer $ACCESS_TOKEN"
```

M2M-клиенты используют API-ключ напрямую в `Authorization: Bearer soar_<hex>`
— без `/auth/login` и без refresh (ключ статический, живёт до `expires_at`
или ручного удаления через `DELETE /auth/keys/{id}`).

UI (`ui/`) делает то же самое автоматически — см. `ui/src/api.js` /
`ui/src/store/auth.js`: форма логина, авто-refresh при 401, logout.

Роли: `admin`, `analyst`, `viewer`, `service`. Подробности — [AGENTS.md → Authentication](AGENTS.md#authentication-orchestratorauth).

## Логи — где что смотреть

В проекте три независимых источника логов — эксплуатационный, per-job и
audit trail. Они не взаимозаменяемы: у каждого свой смысл, своё хранилище
и свой способ доступа.

| Что | Где хранится | Как посмотреть | Кто видит |
|---|---|---|---|
| **Access-лог** (запросы к API) | Файл `config.logging.file` (+ stderr) | `docker compose exec orchestrator tail -f /var/log/soar/orchestrator.log` | Только с доступом к контейнеру — через API не отдаётся |
| **Job-лог** (вывод конкретного запуска workflow) | Файл в `jobs.log_dir`, один на job | `GET /logs/{job_id}` или `GET /logs/{job_id}/stream` (SSE); в UI — кнопка **Log** на странице Jobs | Роли `analyst`/`service`/`admin` |
| **Audit trail** (кто/что/когда изменил) | Таблица `audit_log` в БД (`database.url`) | `GET /audit-log`; в UI — раздел **Audit Log** в навигации | Только `admin` |

### Access-лог

Одна строка на запрос: `method`, `path`, `status`, `duration_ms`,
`client_ip`, `user_id`, плюс сквозной `request_id` (тот же, что в заголовке
ответа `X-Request-ID`) — по нему можно склеить access-лог с любым другим
логом, случившимся в рамках того же запроса. Туда же попадают
security-события, которые раньше проходили молча: неудачные попытки
аутентификации (401/403), срабатывание rate-limit (429), невалидный
`X-Webhook-Token`.

```bash
docker compose -f deploy/stage/docker-compose.yml exec orchestrator \
  tail -f /var/log/soar/orchestrator.log
```

Тела запросов и заголовок `Authorization`/`X-Webhook-Token` в этот лог
никогда не пишутся.

### Job-лог

Вывод конкретного запуска workflow (stdout subprocess'а). Доступен через
API и в UI — на странице **Jobs** у завершённого/выполняющегося job'а есть
кнопка **Log**, которая ведёт на `/logs/:id` (живой tail через SSE, пока
job не завершится).

### Audit trail

Кто именно вызвал мутирующий эндпоинт (создание/изменение/удаление
workflow, action, connector, API-ключа, отмена job'а) — записывается в
БД, читается через `GET /audit-log` (`admin`-only, с фильтрами по
`resource_type`, `resource_id`, `action`, `actor_name`, `since`/`until`,
пагинация `limit`/`offset`).

> **Важно:** без фильтров `GET /audit-log` возвращает записи **по всем
> типам ресурсов сразу** (workflows, actions, connectors, api-keys, jobs),
> отсортированные по времени — это не журнал одного конкретного workflow,
> а общий поток. Чтобы увидеть историю только одного ресурса —
> `?resource_type=workflow&resource_id=<name>`.

В UI это решено так: раздел **Audit Log** в навигации (виден только
`admin`) показывает общий поток с формой фильтров; а на страницах
**Workflows** / **Actions** / **Connectors** / **Jobs** / **API Keys** у
каждой строки есть кнопка **Audit**, которая ведёт на `/audit-log` уже
предзаполненным фильтром `resource_type`+`resource_id` для этой конкретной
записи — так что "все workflow в кучу" видно только на общей странице, а
из конкретного workflow/action/connector можно попасть сразу в его
собственную историю.

## Способы деплоя

### 1. Локально / dev (SQLite, in-memory очередь и job-store)

```bash
python -m uvicorn orchestrator.main:app --reload --port 8000
```

Ничего дополнительно поднимать не нужно — используется дефолтный
`config.yaml` из рабочей директории (или его отсутствие → дефолты).

### 2. Docker Compose — стенд (`deploy/stage/`)

Полный стек: orchestrator + UI + Redis (очередь) + PostgreSQL
(auth + job-история).

```bash
cd deploy/stage
docker compose up --build -d
```

Первый деплой на свежую БД — токены/таблицы уже создаёт сам сервис
(`create_all()` при старте), Alembic нужно только **пометить** как
смигрированный (не накатывать миграцию заново):

```bash
make migrate-stamp-initial
```

При будущих изменениях схемы (новая Alembic-миграция в составе релиза):

```bash
make migrate
```

- UI: `http://localhost:3000`
- API: `http://localhost:8000/status`, `http://localhost:8000/docs`

Конфиг стенда — [`deploy/stage/config.yaml`](deploy/stage/config.yaml)
(Postgres, `table_prefix: "stage_"`, `jobs.persistence: sql`, Redis-очередь).
Остальные команды (`up`/`down`/`logs`/`restart`/`status`) — [`deploy/stage/Makefile`](deploy/stage/Makefile),
подробнее — [`deploy/stage/README.md`](deploy/stage/README.md).

**Апгрейд стенда при изменении кода.** Код копируется в образ на этапе
сборки (`COPY soar/ /app/soar/` в `Dockerfile.orchestrator`), а не
монтируется живьём — значит любое изменение требует пересборки:

```bash
cd deploy/stage
docker compose up --build -d   # пересобрать образ(ы) + пересоздать изменившиеся контейнеры

# если релиз принёс новую Alembic-миграцию — та же дилемма stamp/upgrade:
make migrate-stamp-initial   # миграция только добавляет новую таблицу (create_all() уже создал её при старте)
make migrate                 # миграция меняет существующую таблицу (create_all() тут не поможет)
```

Порядок важен: `migrate` делает `docker compose exec orchestrator ...` —
запускать его нужно **после** пересборки/пересоздания контейнера, иначе
команда попадёт в ещё старый контейнер со старыми миграциями. `postgres`/
`redis` не пересоздаются, если их образы не менялись — job-история и
пользователи переживают апгрейд.

### 3. Production-дистрибуция — `soarctl` (`deploy/prod/`)

Отдельный профиль для распространения инстанса за пределы одной машины
разработки — в первую очередь для air-gapped окружений: без реестра
образов, сборка на машине с интернетом, перенос одного самодостаточного
файла, установка офлайн.

```bash
# 1. Машина с интернетом — собрать бандл (образы + compose + сам soarctl)
python deploy/soarctl package --version 0.9.0 --output soar-bundle-0.9.0.tar.gz
# перенести файл на целевую машину (USB/scp — вне зоны ответственности soarctl)

# 2. Целевая машина (офлайн с этого момента)
python soarctl install soar-bundle-0.9.0.tar.gz --dir soar-prod && cd soar-prod
python soarctl doctor            # preflight: docker, порты, место на диске
python soarctl init              # генерирует .env (секреты) + config.yaml — один раз
python soarctl up
python soarctl migrate --fresh   # первый деплой — см. ту же дилемму stamp/upgrade выше
python soarctl users create --username admin --role admin
```

Апгрейд на новую версию — **тот же instance dir**, тот же порядок
`install → up → migrate`:

```bash
python soarctl install soar-bundle-0.9.1.tar.gz --dir soar-prod   # обновит только SOAR_VERSION в .env
python soarctl up                                                  # пересоздаст только orchestrator/ui
python soarctl migrate --fresh   # или --upgrade — только если релиз принёс миграцию
```

`install` на уже инициализированном инстансе трогает только `SOAR_VERSION`
— `AUTH_SECRET_KEY`/`POSTGRES_PASSWORD` не перегенерируются (иначе апгрейд
заблокировал бы доступ к собственной БД). День-2 операции —
`soarctl status`/`logs`/`backup create`/`backup restore --confirm`/`down`.
Один инстанс на вызов — мультиинстансность вне scope (см. [AGENTS.md → Known Limitations #9](AGENTS.md#known-limitations)).
Подробнее — [`deploy/prod/README.md`](deploy/prod/README.md) и
[`docs/compose/specs/2026-07-22-deploy-cli-design.md`](docs/compose/specs/2026-07-22-deploy-cli-design.md).

### 4. Production вне Docker Compose

Тот же образ/код, свой `config.yaml` с реальными `database.url` (managed
Postgres), `queue.backend: redis` (managed Redis), `auth.secret_key`
(сгенерированный секрет) и, при необходимости, `database.table_prefix`
(если БД шарится с другими окружениями/инстансами). Перед первым стартом на
уже существующей БД — та же логика stamp/upgrade, что и для Compose (см.
выше и [AGENTS.md → Database backend](AGENTS.md#database-backend-sqlitepostgresql-и-table-prefix)).

## Дальше

- [AGENTS.md](AGENTS.md) — архитектура, паттерны, security, known limitations, версии
- [`docs/compose/specs/`](docs/compose/specs/) — дизайн-документы фич
- [`docs/compose/plans/`](docs/compose/plans/) — пошаговые планы реализации
- [`docs/compose/reports/`](docs/compose/reports/) — отчёты о выполненных фичах
