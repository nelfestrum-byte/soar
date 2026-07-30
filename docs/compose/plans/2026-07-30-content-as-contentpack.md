# Plan: Контент как контентпак — Phase 3

Spec: `docs/compose/specs/2026-07-30-content-as-contentpack-design.md`

Ветка: `feat/entity-model-phase3`, из `main` (после Phase 1+2 смерджены —
зависит от `soar/runtime_contract.py` и `MUTATING_METHODS`). Мердж после
зелёного `pytest tests/` и `ruff check .`.

Отдельный репозиторий пака (`soar-content-pack` или похожее имя) — создать
как **отдельную git-инициализацию** внутри рабочего каталога плана
(например `../soar-content-pack` рядом с основным репо, не подкаталог/не
submodule этого репозитория) в рамках той же ветки работы; его история не
часть `soar`-репозитория. Точное имя/расположение — подтвердить с
пользователем перед созданием нового репозитория (создание нового
git-репозитория — не chisto код-левел решение, см. verification).

## 1. Манифест + генератор

Tests first (`tests/orchestrator/core/test_pack_install.py`, часть про
`read_manifest`):

- [ ] `read_manifest(pack_bytes)` — парсит `manifest.yaml` из tar/zip
      архива в dict; отсутствующий `manifest.yaml` → явная ошибка
- [ ] `check_runtime_compat(manifest, runtime_version="1")` — совпадающий
      major → ок; несовпадающий → `ValueError` с понятным текстом
- [ ] `check_dependencies(manifest, CONTRACT)` — импорт вне контракта →
      список недостающих имён; все внутри контракта → пустой список
- [ ] Confirm tests fail before module exists

Implementation:

- [ ] `soar-content-pack/tools/gen_manifest.py` (в репозитории пака) — AST
      сборка `manifest.yaml` из `connectors/*/*.py`: top-level
      `Import`/`ImportFrom` → `imports`, `MUTATING_METHODS` через
      `ast.Assign`/`ast.AnnAssign` → `mutating_methods`
- [ ] `manifest.yaml` — схема как в spec [S3]
- [ ] `orchestrator/core/pack_install.py`: `read_manifest`,
      `check_runtime_compat`, `check_dependencies` — как в spec [S7]

## 2. Маркер происхождения + план установки

Tests first (`tests/orchestrator/core/test_pack_install.py`, часть про
`plan_install`/`apply_install`):

- [ ] Пустой marker (первая установка) → все коннекторы манифеста в `new`
- [ ] Marker с записью, sha256 совпадает с диском → в `update` (если
      версия манифеста новее) или `unchanged` (если та же)
- [ ] Marker с записью, sha256 не совпадает (пользователь правил файл) →
      в `skip_modified`
- [ ] `apply_install(plan, connectors_dir)` — копирует `new`+`update`,
      пропускает `skip_modified`, обновляет marker-файл (новый sha256,
      версия) только для реально скопированных
- [ ] Confirm tests fail before implementation

Implementation:

- [ ] `orchestrator/core/pack_install.py`: `plan_install(manifest,
      existing_marker)`, `apply_install(plan, connectors_dir)`,
      `compute_sha256(path)`, `read_marker(connectors_dir)`/`write_marker(...)`
      — маркер `.soar-content.yaml`, схема как в spec [S4]

## 3. `soarctl content install|list|remove`

Tests first (`tests/deploy/test_content_cli.py`, мокать `subprocess`/`docker`
как остальные `tests/deploy/`):

- [ ] `content install <path>` на пустой инсталляции — все коннекторы
      установлены, marker создан, docker-вызов записи в volume
      (alpine tar-паттерн, как `backup.restore_data_volume`) — с
      правильными аргументами
- [ ] `content install <path>` повторно, без изменений на диске — no-op,
      marker не тронут (или тронут только `installed_at`/version — решить
      при реализации какой из двух, зафиксировать тестом)
- [ ] `content install <path>` после ручной правки одного коннектора —
      этот коннектор в выводе как `skip_modified`, остальные обновлены
- [ ] `content list` — таблица name/pack_version/modified, `modified`
      вычисляется на лету (не из статичного поля)
- [ ] `content remove <name>` без `--force` на modified → отказ,
      ненулевой exit code
- [ ] `content remove <name> --force` на modified → удаляет
- [ ] Confirm tests fail before `content.py` exists

Implementation:

- [ ] `deploy/soarctl_lib/content.py` — по образцу `backup.py`
      (docker-вызовы через `run()`, без бизнес-логики в `cli.py`),
      функции `install`/`list_installed`/`remove`, используют
      `orchestrator/core/pack_install.py`'s чистые функции там, где логика
      не зависит от FastAPI/DB (если `orchestrator/core/` не импортируется
      из `deploy/` сегодня — проверить существующий прецедент; если
      импорт нежелателен по слоям деплоя, продублировать минимальные
      чистые функции в `deploy/soarctl_lib/content.py` вместо импорта —
      решить на этапе реализации, не тащить FastAPI-зависимости в CLI)
- [ ] `deploy/soarctl_lib/cli.py`: под-парсер `content` с
      `install`/`list`/`remove`, по образцу `backup`

## 4. Установка через API

Tests first (`tests/orchestrator/api/test_pack_routes.py`):

- [ ] `POST /connectors/pack/install` без `force`, есть конфликты
      (существующие немодифицированные коннекторы, которые манифест
      обновит) → 200 со списком конфликтов, ничего не записано на диск
      (preflight, как `/transfer/import`)
- [ ] `POST ... ?force=true` → устанавливает, пишет `AuditLog`
      (`action="pack.install"`, `detail` — имена, не содержимое)
- [ ] Роль `analyst`/`viewer` → 403 (admin-only)
- [ ] Роль `admin` без force на чистой установке (нет конфликтов) → 200,
      установлено сразу
- [ ] Confirm tests fail before route exists

Implementation:

- [ ] Новый роутер `orchestrator/api/packs.py` (если объём роутов
      оправдывает отдельный файл — иначе добавить в `connectors.py`, решить
      по факту размера) — `POST /connectors/pack/install`, использует
      `orchestrator/core/pack_install.py`
- [ ] Регистрация роутера в `orchestrator/api/__init__.py` +
      `orchestrator/main.py`
- [ ] `audit.service.record(..., action="pack.install", resource_type="connector_pack", ...)`

## 5. Переезд 24 коннекторов + сидинг

- [ ] Создать (с подтверждения пользователя, см. шапку плана) репозиторий
      пака, перенести `soar/connectors/<24 dirs>/` туда без изменения кода
      (git mv эквивалент между репозиториями — copy + commit в новом репо,
      удаление в старом одним PR-циклом, не двумя разъехавшимися)
- [ ] Соответствующие 24 `tests/soar/test_*_connector.py` — переезжают в
      репозиторий пака вместе с кодом (spec [S10]); в основном репозитории
      остаётся один smoke/пример-тест на пайплайн install (не 24 файла)
- [ ] `soar/connectors/` в основном репозитории: остаются только
      `__init__.py`, `base.py`, `_proxy.py`
- [ ] `soar/requirements.txt` — не меняется по набору пакетов (spec [S9] —
      зависимости остаются платформенным контрактом независимо от
      физического источника кода), только комментарий, откуда теперь
      приходит код, который их использует
- [ ] `orchestrator/main.py::seed_defaults()` — коннекторная часть
      заменяется на install базового пака при пустом `.soar-content.yaml`
      (spec [S8]); ветки для `workflows`/`actions` в `seed_defaults()`
      удаляются как мёртвый код (уже сегодня копируют только
      `__init__.py`/`base.py`, исключённые тем же циклом)
- [ ] `deploy/{prod,stage}/Dockerfile.orchestrator`: `COPY` базового пака в
      `/app/base-pack` (было — неявно через `COPY soar/` + build-time `cp`
      блок, который удаляется), `ENV SOAR_BASE_PACK_PATH=/app/base-pack`
- [ ] `orchestrator/main.py::lifespan`: если `.soar-content.yaml`
      отсутствует — `pack_install` пайплайн на `SOAR_BASE_PACK_PATH`

## 6. Docs

- [ ] `docs/agents/known-limitations.md` — удалить пункты 9 (E1), 10 (E2 —
      если Фаза 1 их ещё не сняла) как описывающие несуществующее
      состояние
- [ ] `AGENTS.md` — "What is this" список коннекторов переезжает в
      описание базового пака (не перечислять 24 интеграции как часть
      этого репозитория); "File map" обновляется на новые пути
      (`orchestrator/core/pack_install.py`, `deploy/soarctl_lib/content.py`)

## Verification

- [ ] Подтвердить с пользователем расположение/имя репозитория пака перед
      его созданием (см. шапку плана) — блокирующий шаг перед началом
      раздела 5
- [ ] `python -m pytest tests/orchestrator/core/test_pack_install.py
      tests/deploy/test_content_cli.py tests/orchestrator/api/test_pack_routes.py -v`
- [ ] `python -m pytest tests/ -q` — ноль новых failures относительно
      baseline после Phase 1+2 (24 файла коннекторных тестов теперь
      отсутствуют в основном репо — ожидаемое уменьшение счётчика, не
      failure)
- [ ] `ruff check .`
- [ ] Ручная проверка: `soarctl content install <base-pack-path>` на чистой
      тестовой инсталляции — коннекторы появляются в `GET /connectors`
- [ ] Написать отчёт `docs/compose/reports/content-as-contentpack.md`
