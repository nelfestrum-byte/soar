# SOAR

Минималистичный SOAR: детерминированные автоматические расследования на
ECS-схеме и авто-закрытие типовых кейсов с ложными срабатываниями — без
LLM внутри движка. Каждое решение объяснимо и воспроизводимо: путь от
алерта до вердикта виден целиком, ничего не решается "по вероятности".

При этом сам SOAR спроектирован под LLM-агентскую разработку: API отдаёт
самоописание коннекторов/actions/workflow без чтения исходников,
проверяет код при сохранении и возвращает полный traceback вместо
`str(error)` — агент может писать и чинить интеграции прямо в живой
инфраструктуре, а не только по документации. Любое изменение кода
версионируется через git — история, diff и restore доступны из коробки,
как и полный аудит запросов и security-событий.

## Быстрый старт (локально)

```bash
python -m pip install -r orchestrator/requirements.txt
python -m uvicorn orchestrator.main:app --reload --port 8000
```

Без `config.yaml` в рабочей директории сервис стартует с дефолтами:
SQLite-файл `./soar.db`, in-memory очередь, auth выключена (анонимный
admin). API — `http://localhost:8000/status`, Swagger —
`http://localhost:8000/docs`.

```bash
python -m pytest tests/ -v
ruff check .
mypy orchestrator/ soar/ --ignore-missing-imports
```

## Деплой — `soarctl`

Модель дистрибуции: **или собрать образы прямо на целевой машине (если у
неё есть интернет), или собрать на отдельной машине и перенести бандл
файлом на air-gapped цель.** Реестра образов нет — `soarctl package`
кладёт все четыре рантайм-образа + compose-файл + шаблон конфига в один
самодостаточный tar, `soarctl install` из бандла сети не касается вообще.
Дизайн — [`docs/compose/specs/2026-07-22-deploy-cli-design.md`](docs/compose/specs/2026-07-22-deploy-cli-design.md)
(air-gapped флоу) и [`docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md`](docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md)
(on-site флоу). Только один инстанс за раз — `soarctl` не умеет управлять
несколькими параллельно, см. `AGENTS.md`, Known Limitations #8.

### On-site (эта машина имеет интернет)

Чекаут — сам инстанс, отдельной директории не заводится:

```bash
git clone <url> soar && cd soar
./soarctl doctor
./soarctl install                   # git checkout <ref> если дан --ref, docker build
./soarctl init --interactive        # .env + config.yaml, спросит auth.cors_origins
./soarctl up
./soarctl migrate --fresh           # первый деплой — см. "Миграции" ниже
./soarctl users create --username admin --role admin
```

Если `pip install` внутри `docker build` не может достучаться до
`pypi.org` (некоторые сети режут именно этот домен по SNI, оставляя
доступными другие хосты на том же CDN — `files.pythonhosted.org`,
`deb.debian.org`), задайте `PIP_INDEX_URL` в шелле перед `install`/
`update`:

```bash
PIP_INDEX_URL=https://mirror.yandex.ru/pypi/simple ./soarctl install
```

Читается один раз на каждый `docker build`, нигде не сохраняется —
задавать заново для каждого следующего `soarctl update` на той же сети.
Не задано — обычный дефолт `pypi.org`, поведение не меняется.

`./soarctl` — обёртка в корне репозитория (`git clone`-стиль: без
префикса `python deploy/soarctl`, без шага установки в PATH). Любая
подкоманда сама находит инстанс от текущего каталога вверх — работает из
корня чекаута или любого его подкаталога, так же как `git` ищет корень
репозитория; `--dir` остаётся как явный override, если он когда-нибудь
понадобится. `install` по умолчанию берёт чекаут, в котором вы стоите;
`--repo <path>` — указать другой локальный чекаут. Флага `--repo <url>`
нет — клонировать нужно самостоятельно, `soarctl` работает только с уже
существующим чекаутом. Версия берётся из
`git describe --tags --always --dirty` — суффикс `-dirty` значит, что в
рабочем дереве были незакоммиченные изменения на момент сборки.

Обновление on-site инстанса:

```bash
./soarctl update --ref v1.3.0            # или без --ref — подтянет текущую ветку
./soarctl migrate --fresh                # только если новая версия принесла миграцию
```

`update` подтягивает/чекаутит новый код, пересобирает образы
`orchestrator`/`ui`, бампает `SOAR_VERSION` в `.env` и запускает
`soarctl up` — `docker compose down` не вызывается никогда, а так как
`postgres`/`redis` не меняют тег образа при обновлении, compose не
пересоздаёт и эти два контейнера. `--migrate fresh`/`--migrate upgrade`
применяет миграции той же командой; без флага решение о
`fresh`/`upgrade` остаётся за вами (см. "Миграции" ниже). Работает только
для инстансов, установленных через `soarctl install` on-site —
bundle-инстансы обновляются через `install <new-bundle>` (см.
"Air-gapped" ниже).

### Air-gapped (сборка на машине с интернетом → перенос бандла → офлайн-установка)

```bash
python deploy/soarctl package --version X.Y.Z --output soar-bundle-X.Y.Z.tar.gz
```

Собирает `soar-orchestrator`/`soar-ui` из исходников, тянет
`redis:7-alpine`/`postgres:16-alpine`, и сохраняет все четыре образа плюс
`deploy/prod/docker-compose.yml`, `config.yaml.template` и сам `soarctl` в
один tar. Перенести файл на целевую машину (USB, scp — вне зоны
ответственности `soarctl`).

```bash
python soarctl install soar-bundle-X.Y.Z.tar.gz --dir soar-prod
cd soar-prod
python soarctl doctor            # preflight: docker, порты, место на диске
python soarctl init              # генерирует .env-секреты + config.yaml — один раз
```

Ни один шаг после `install` сети не касается.

Отредактируйте `config.yaml` и задайте `auth.cors_origins` под реальный
origin UI (например, `["https://soar.example.com"]`) — `soarctl init`
рендерит шаблон как есть и не знает вашего домена. Если пропустить это,
останется дефолт из кода (`localhost:3000`/`5173`), и UI не сможет
залогиниться (браузер отклонит по CORS) при заходе с реального адреса.

Проверьте `server.trusted_proxies` в `config.yaml` — там должен быть IP
контейнера `ui` в сети `soar-net` (см. `docker-compose.yml`). Менять
один без другого нельзя: рассинхрон делает rate limiter/audit log либо
снова глобальным (IP не совпадает), либо доверяющим не тому пиру (если
подсеть поменяли руками).

`docker-compose.yml` публикует `orchestrator` на `8000:8000` без TLS —
JWT и пароли идут открытым текстом по этому порту. Перед тем как открыть
инстанс за пределы localhost/доверенной LAN, поставьте перед ним
TLS-терминирующий LB/reverse proxy — `soarctl` его не разворачивает (см.
M11 в `docs/concepts/BAGFIX_PLAN.md`).

```bash
python soarctl up
python soarctl migrate --fresh   # первый запуск — см. "Миграции" ниже
python soarctl users create --username admin --role admin
```

Обновление на новую версию:

1. На машине сборки: `soarctl package --version X.Y.Z --output ...`,
   перенести новый бандл.
2. На целевой: `soarctl install <new-bundle> --dir <та же директория
   инстанса>` — это `docker load`-ит новые образы и (раз `.env` уже
   существует) бампает только `SOAR_VERSION` в нём, никогда не трогая
   `AUTH_SECRET_KEY`/`POSTGRES_PASSWORD` (это заблокировало бы доступ
   инстанса к его же БД) — `init` заново запускать не нужно.
3. `soarctl up` — compose пересоздаёт контейнеры на новом теге образа
   `SOAR_VERSION` из `.env`. **Сделать это до `migrate`** — `migrate`
   выполняет `docker compose exec orchestrator ...` внутри того
   контейнера, что сейчас запущен, так что запуск раньше `up` выполнит
   команду в ещё старом контейнере со старым `alembic/versions/`, а не с
   новым.
4. Проверить `alembic/versions/` новой версии на предмет изменений
   (сравнить с тем, что уже было до этого апдейта), затем
   `soarctl migrate --fresh` или `--upgrade` (см. ниже) — только если
   новая версия действительно принесла миграцию, иначе пропустить шаг.

### Миграции: `--fresh` vs `--upgrade`

`init_db()`/`create_all()` выполняется на каждом старте оркестратора и
только создаёт таблицы, которых ещё нет — существующие никогда не
меняет.

- **Добавлена новая таблица** (первый деплой, или миграция, которая
  только добавляет таблицу): `create_all()` уже создал её к моменту
  запуска этой команды — используйте `soarctl migrate --fresh`
  (`alembic stamp head`), **не** `--upgrade`, иначе Alembic попробует
  сделать `CREATE TABLE` на том, что уже существует, и упадёт.
- **Изменена существующая таблица** (миграция добавляет/меняет колонку
  в таблице, которая уже была): `create_all()` тут не поможет —
  используйте `soarctl migrate --upgrade` (`alembic upgrade head`).

Автоопределения нет — выбор не того варианта может повредить состояние
миграций, см. non-goals в deploy-cli спеке. Если сомневаетесь — посмотрите,
что конкретно делает новая миграция в `alembic/versions/`.

### День-2 операции

```bash
soarctl status                                   # статус контейнеров + /health
soarctl logs [orchestrator|ui|redis|postgres]    # логи в реальном времени
soarctl users create/deactivate/activate --username X [--role R]
soarctl backup create --output backup-$(date +%F).tar.gz
soarctl backup restore backup-2026-07-22.tar.gz --confirm
soarctl down / up / restart
```

`backup create`/`restore` покрывают базу Postgres и volume `soar-data`
(workflows/actions/connectors вместе с их git-историей) одним архивом.
`restore` перезаписывает и то, и другое — без `--confirm` не запускается.

### Данные

- `config.yaml` / `.env` — локальны для инстанса, генерируются
  `soarctl init`, никогда не коммитятся (см. `deploy/.gitignore`)
- Именованные volumes (фиксированные имена, расчёт на один инстанс):
  `soar-data`, `soar-logs`, `soar-redis-data`, `soar-postgres-data`

## Документация

- [AGENTS.md](AGENTS.md) — архитектура, паттерны, команды: источник
  истины для разработки (в том числе для агентов, читающих этот repo)
- [docs/agents/known-limitations.md](docs/agents/known-limitations.md) — известные ограничения
- [docs/concepts/BAGFIX_PLAN.md](docs/concepts/BAGFIX_PLAN.md) — трек багфикса перед пилотом
- [CHANGELOG.md](CHANGELOG.md) — история версий

## Осознанное ограничение: без изоляции workflow

Workflow выполняются как обычный subprocess на том же хосте — без
контейнеризации или sandbox на каждый job. Это осознанный компромисс
ради скорости и простоты, а не недосмотр: проект — SOAR для
автоматизации конкретных сценариев расследования security-кейсов, а не
универсальная платформа для запуска недоверенного кода в масштабах
всей компании. Код workflow должен быть таким же доверенным, как
остальной кодбейз.
