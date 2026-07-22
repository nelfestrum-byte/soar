# Deploy CLI (`soarctl`): распространение, установка и управление инстансом

## [S1] Problem

Сейчас единственный деплой-путь — `deploy/stage/`: `docker-compose.yml` с
`build: context: ../..` (собирает образ из исходников прямо на месте) плюс
Makefile из 8 команд и bootstrap первого admin'а отдельным вызовом
`docker compose exec orchestrator python -m orchestrator.auth.cli
create-user`. Это подходящий режим для внутреннего QA-стенда, но не для
распространения инстанса за пределы одной машины разработки:

1. **Целевая среда — air-gapped**, но текущая сборка требует интернета в
   момент `docker build` (`apt-get install git`, `pip install -r
   requirements.txt` внутри `Dockerfile.orchestrator`, `npm install` в
   `Dockerfile.ui`). Собрать образ на изолированной машине нечем.
2. **Секреты закоммичены.** `deploy/stage/config.yaml` содержит
   `auth.secret_key` прямо в git (сейчас — осознанно как test-секрет для
   стенда, но это не шаблон для реального инстанса).
3. **Нет единой точки входа оператора.** Старт/стоп — `make up`/`down`;
   бутстрап admin'а — прямой `docker compose exec` с полным путём модуля;
   выбор между `make migrate-stamp-initial` и `make migrate` требует от
   оператора вручную помнить правило из AGENTS.md («Database backend») —
   новая таблица → `stamp`, изменение существующей → `upgrade`. Это восемь
   разных мысленных моделей вместо одной.
4. **Нет версионирования артефакта.** Ничего не привязывает конкретный
   собранный образ к версии кода — нельзя однозначно сказать, что именно
   запущено на инстансе, и нечем «перенести именно это» на другую машину.

## [S2] Solution

### Принцип: сборка и установка — разные машины

Без реестра образов (решено явно, не проектируем push/pull-инфраструктуру).
Вместо этого — **сборка на машине с интернетом → перенос готового
артефакта → установка офлайн**:

1. На машине-сборщике: `docker compose build` для `orchestrator`/`ui`,
   локальные теги по версии приложения (`soar-orchestrator:X.Y.Z`,
   `soar-ui:X.Y.Z`, версия — из `VERSION`-файла в репозитории, синхронного
   с git-тегом релиза).
2. `docker save` **всех четырёх** образов рантайма — `soar-orchestrator`,
   `soar-ui`, `redis:7-alpine`, `postgres:16-alpine` — в один tar. Базовые
   образы (`redis`, `postgres`) обязаны попасть в бандл тоже: на
   air-gapped целевой машине их неоткуда подтянуть.
3. В тот же бандл кладутся: prod compose-файл (см. ниже, `image:`, не
   `build:`), `config.yaml.template`, сам `soarctl`.
4. На целевой машине: `docker load` из тарбола — сеть не участвует нигде
   в пути установки.

Перенос бандла с машины на машину (USB/защищённое копирование) — вне
scope этого CLI, это организационная процедура, не часть `soarctl`.

### Новый деплой-профиль `deploy/prod/` — не трогаем `deploy/stage/`

`deploy/stage/` остаётся как есть — внутренний QA-стенд, режим `build:`,
годится для быстрой итерации на одной машине с исходниками под рукой.
Добавляется параллельный `deploy/prod/docker-compose.yml` — те же четыре
сервиса (redis, postgres, orchestrator, ui), но:

- `image: soar-orchestrator:${SOAR_VERSION}` вместо `build:`
- все секреты (`auth.secret_key`, `POSTGRES_PASSWORD`, webhook-токен) —
  через `${VAR}` из `.env` (не в git), тем же механизмом, каким уже
  сегодня прокинут `SOAR_DB_PASSWORD`/`SOAR_WEBHOOK_TOKEN` в
  `deploy/stage/docker-compose.yml` — просто расширяем на всё
  чувствительное, включая `auth.secret_key`, которого в `.env`-варианте
  сегодня нет вообще (в stage он захардкожен в `config.yaml`)

### `soarctl` — два слоя

**Host-слой** — сам `soarctl`: Python на stdlib (argparse, в стиле уже
существующего `orchestrator/auth/cli.py` — не тащим новый CLI-фреймворк),
без зависимостей оркестратора. Работает и на машине-сборщике, и на
целевой — умеет только звать `docker`/`docker compose`.

**In-container слой** — всё, что требует доступа к БД/приложению,
`soarctl` прокидывает внутрь контейнера через `docker compose exec
orchestrator ...` — переиспользует существующий `orchestrator.auth.cli`
как есть, не дублирует его логику.

Команды первого среза (один инстанс за раз, см. [S3]):

| Команда | Слой | Что делает |
|---|---|---|
| `soarctl package [--version X.Y.Z]` | host | build + tag + `docker save` → один tar-бандл |
| `soarctl install <bundle.tar> [--dir PATH]` | host | `docker load` + распаковка compose/template в рабочую директорию инстанса; ничего не запускает |
| `soarctl init` | host | генерирует `.env` (`secrets.token_hex` для `AUTH_SECRET_KEY`/`POSTGRES_PASSWORD`/`SOAR_WEBHOOK_TOKEN`), рендерит `config.yaml` из template |
| `soarctl up` / `down` / `restart` | host | обёртка над `docker compose` для рабочей директории инстанса |
| `soarctl status` | host | `compose ps` + `GET /health`; `GET /status` тоже, если передан токен |
| `soarctl migrate --fresh` / `soarctl migrate` | in-container | явные алиасы на `alembic stamp head` / `alembic upgrade head` — **не** авто-детект (см. [S3], почему авто-детект пока небезопасен) |
| `soarctl users create/list/deactivate/activate` | in-container | прокси на `python -m orchestrator.auth.cli ...`, без изменений в самом auth CLI |
| `soarctl backup create/restore` | host + in-container | `pg_dump`/`pg_restore` внутри контейнера postgres + tar тома `soar-data` (workflows/actions/connectors, включая их `.git`) одним архивом |
| `soarctl logs [service]` | host | `compose logs -f` |
| `soarctl doctor` | host | preflight: `docker`/`docker compose` есть, порты свободны, `.env` заполнен и не дефолтный, есть место на диске под volumes |

### Конфиг/секреты

`config.yaml.template` использует `${VAR}`-подстановку — тот же механизм
docker compose, которым в `deploy/stage/docker-compose.yml` уже
прокидываются `SOAR_DB_PASSWORD`/`SOAR_WEBHOOK_TOKEN`. Ничего секретного
не запекается в образ и не коммитится.

## [S3] Non-goals

- **Мультиинстансность** (контексты/профили для нескольких одновременно
  управляемых инстансов) — явно вне scope, отдельный дизайн. Зафиксировано
  как Known Limitation #9 в AGENTS.md. `soarctl` работает с одной рабочей
  директорией инстанса за вызов (cwd или `--dir`).
- **Авто-детект `stamp` vs `upgrade`.** Дуальность `create_all()` +
  условный выбор Alembic-команды (см. AGENTS.md → Database backend) —
  реальная мина для автоматизации: неверный выбор ломает состояние БД.
  Пока это не устранено архитектурно (переход на чистый Alembic-путь без
  `create_all()` в проде — отдельная задача), `soarctl migrate` даёт два
  явных алиаса, а не одну «умную» команду.
- **Сборка внутри air-gapped машины** (свой pip/apt-зеркало и т.п.) — по
  явному решению переносится на потом; сейчас предполагается, что сборка
  всегда происходит на машине с интернетом, а на изолированную переносится
  готовый бандл.
- Реестр образов, push/pull, подпись образов, SBOM — вне scope (решено не
  использовать реестр).
- Kubernetes/Helm — только Docker Compose.

## [S4] Testing strategy

- Части `soarctl`, не требующие живого Docker — сборка/распаковка
  бандла, генерация `.env`, рендер `config.yaml.template` — обычные
  pytest-тесты, вызовы `docker`/`docker compose` мокаются
  (`subprocess.run`).
- End-to-end (package → install → init → up → status → users create →
  backup → down) — ручной/CI smoke-прогон на реальном Docker,
  задокументированный в отчёте, тем же способом, каким уже проверялись
  предыдущие деплой-изменения на реальном `deploy/stage` (см. записи
  v0.7/v0.8/v0.9 в AGENTS.md) — не обязательно попадает в `tests/`, следуя
  уже принятой в проекте практике для деплоя.

## [S5] Success criteria

- [ ] `soarctl package` на машине с интернетом собирает версионированный
      самодостаточный бандл без обращения к какому-либо реестру
- [ ] `soarctl install` + `soarctl init` + `soarctl up` на air-gapped
      машине проходят без единого сетевого вызова
- [ ] В `deploy/prod/` не закоммичено ни одного секрета
- [ ] `soarctl users create --admin` бутстрапит первого admin'а без того,
      чтобы оператор знал точный `docker compose exec ...
      orchestrator.auth.cli` вызов
- [ ] `soarctl backup create`/`restore` восстанавливает БД и
      workflows/actions/connectors (включая git-историю) одним циклом
- [ ] AGENTS.md документирует `deploy/prod/` + `soarctl` и ссылается на
      ограничение по мультиинстансности (#9)
