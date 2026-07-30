# Контент как контентпак — Phase 3 модели сущностей

> Реализует Фазу 3 из `docs/concepts/ENTITY-MODEL.md`. Зависит от Фазы 1
> (контентный venv — установщик пака проверяет объявленные импорты против
> того же контракта, которым уже пользуется `GET /runtime`) и Фазы 2
> (`MUTATING_METHODS` на коннекторах — манифест пака читает это же поле
> через AST, не заводит второе объявление). Закрывает структурную часть
> **E1**: 24 коннектора уезжают из пакета `soar/` в отдельный репозиторий
> базового пака, `soar/connectors/` перестаёт быть исключением из правила
> "пакет содержит только контракт и реестр".

## [S1] Problem

`soar/connectors/` — единственный слой из четырёх сущностей, где контент
живёт внутри пакета (`soar/workflows/`, `soar/actions/` уже пустые,
только `__init__.py`/`base.py`). Следствия, зафиксированные в **E1** и
**E4**:

- Коннектор физически лежит и в `soar/connectors/<name>/`, и (после
  `cp -rn` на build/seed) в `connectors_dir`. `ConnectorRegistry.init()`
  грузит оба — встроенная копия всегда побеждает
  (`if fqn in sys.modules: continue` в `_discover_external`). Правка кода
  через API молча не применяется.
- Обновления не доезжают до существующих инсталляций: сидинг — once, при
  первом пустом volume (`seed_defaults()` в `orchestrator/main.py`, копирует,
  только если `dest` не существует). Новый коннектор релиза в существующей
  инсталляции не появляется никогда.
- Нет маркера происхождения: нельзя ответить "что установлено, из какого
  пака, версии, менял ли пользователь" — то есть невозможно безопасно
  обновить, не затерев правки пользователя.

## [S2] Solution overview

```
soar/connectors/base.py, __init__.py   ← остаётся (контракт+реестр, проект)
soar-content-pack/  (отдельный репозиторий, не подмодуль)
├── manifest.yaml                       ← [S3]
├── connectors/
│   ├── virus_total/virus_total.py
│   ├── ssh/ssh.py
│   └── ... (24 каталога, без изменений в самом коде — переезд, не переписывание)
```

```
soarctl content install|list|remove      ← [S6], по образцу soarctl backup
POST /transfer/pack/install               ← [S7], по образцу /transfer/import
```

Маркер происхождения ([S4]) — таблица/файл на инсталляции, отдельно от
самого пака (пак — версионированный внешний артефакт, инсталляция —
состояние конкретного volume).

## [S3] Манифест пака

`manifest.yaml` в корне репозитория пака:

```yaml
name: soar-base-connectors
version: "1.4.0"
runtime_version: "1"          # совместимая версия контракта из soar/runtime_contract.py
connectors:
  - name: virus_total
    path: connectors/virus_total/virus_total.py
    imports: [vt]              # объявленные top-level импорты — проверяются на установке ([S5])
  - name: ssh
    path: connectors/ssh/ssh.py
    imports: [paramiko]
  # ... остальные 22
```

`imports`/`connectors` **не пишутся руками на каждый релиз пака** —
генерируются скриптом `soar-content-pack/tools/gen_manifest.py`
(живёт в репозитории пака, не в `soar/`) через `ast.parse` на каждый файл
(`ast.Import`/`ast.ImportFrom` на top-level, тот же принцип, что
`orchestrator/core/introspect.py` — не импортировать, чтобы собрать
манифест на машине без всех вендорских SDK сразу). `MUTATING_METHODS`
каждого коннектора (Фаза 2, `soar/connectors/base.py`) тоже читается этим
скриптом через AST (`_hidden_fields`-подобный паттерн на
`ast.Assign`/`ast.AnnAssign` с именем `MUTATING_METHODS`) и попадает в
манифест как `mutating_methods: [...]` на запись — источник истины для
dry-run остаётся код коннектора, манифест — производная, не второй ввод.

## [S4] Маркер происхождения на инсталляции

Новый файл `<connectors_dir>/.soar-content.yaml` (рядом с самими
каталогами коннекторов, не в git — как `orchestrator_state.yaml`, но для
контент-каталога, не для `workflows_dir`):

```yaml
pack: soar-base-connectors
pack_version: "1.4.0"
installed_at: "2026-07-30T12:00:00Z"
entries:
  virus_total:
    version: "1.4.0"          # версия пака, из которого установлен именно этот коннектор
    sha256: "..."              # хэш содержимого на момент установки — сравнивается при update
    modified: false             # true, если текущий sha256 файла на диске != installed sha256
```

`modified` вычисляется **на чтении**, не хранится статично устаревшим —
`soarctl content list`/установщик пересчитывают sha256 текущего файла
против записанного каждый раз, а не доверяют кэшу поля (иначе поле само
станет вторым источником истины и будет расходиться). Хранится только
`sha256` на момент установки; `modified` — вычисляемое поле в выводе
команды, не в файле.

Обновление пака (`soarctl content install <pack> --upgrade` или
`update`-семантика, см. [S6]): для каждого коннектора в новом маншифесте —
если `entries[name]` нет — ставится (новый коннектор релиза, закрывает
**E4**); если есть и `sha256` совпадает с текущим файлом на диске —
перезаписывается на новую версию; если не совпадает (`modified: true`,
пользователь правил через API) — **не трогается**, warning в вывод
команды с именем коннектора и рекомендацией сравнить руками (тот же принцип,
что `history`/`diff`/`restore` уже даёт для git — здесь нет git-diff, т.к.
это про файл на диске до/после установки пака, не про историю API-правок).

## [S5] Проверка зависимостей на установке

Источник истины — `soar/runtime_contract.py::CONTRACT` (Фаза 1), **общий**
с `GET /runtime`, не второй список. Установщик ([S6]/[S7]) на каждый
`imports:` пункт манифеста:

1. Если импорт есть в `CONTRACT` (протокольный или вендорский, уже
   гарантирован контентным venv) — ок, ничего делать не нужно.
2. Если импорта нет в `CONTRACT` — **отказ до записи на диск**, с
   сообщением, каких пакетов не хватает и что установка пака,
   расширяющего контракт, — релиз платформы (Фаза 1, `soar/requirements.txt`
   + `runtime_contract.py`), не то, что можно решить на месте.

Это воспроизводит на уровне пака ровно то поведение, которого не хватало
для встроенных коннекторов до Фазы 1 (**E2** — коннектор появлялся в
реестре путей, зависимость от которого отсутствовала, и падал в рантайме).
Теперь несовпадение ловится на `soarctl content install`, не после того,
как в коннектор уже завели пароль от прод-хоста.

## [S6] `soarctl content install|list|remove`

По образцу `soarctl backup create|restore`
(`deploy/soarctl_lib/backup.py`) — под-парсер, запись в volume через
одноразовый alpine-контейнер (`restore_data_volume`-паттерн: `docker run
--rm -v soar-data:/data alpine ...`, без bind-mount, без host-path
translation).

```
soarctl content install <pack-path-or-url> [--ref REF]
    — клонирует/распаковывает пак, читает manifest.yaml, проверяет
      runtime_version совместимость (major должен совпадать с
      soar/runtime_contract.py::RUNTIME_VERSION инсталляции — читается из
      образа тем же путём, что soarctl doctor уже умеет проверять
      контейнер), проверяет зависимости ([S5]), затем per-connector:
      новый → копирует, есть и не modified → перезаписывает, modified →
      skip+warning; пишет/обновляет .soar-content.yaml

soarctl content list
    — читает .soar-content.yaml, выводит таблицу
      name / pack_version / modified

soarctl content remove <connector-name>
    — удаляет каталог коннектора из connectors_dir + запись из
      .soar-content.yaml; отказывает, если modified=true без --force
      (не молча терять правки пользователя)
```

`deploy/soarctl_lib/content.py` — новый модуль, симметричный
`backup.py`/`git_source.py` по структуре (тонкие функции, `run()` для
docker-вызовов, никакой бизнес-логики в `cli.py` — существующий паттерн
`soarctl`).

## [S7] Установка через API

`POST /connectors/pack/install` (не `/transfer/import` — семантика другая:
`transfer` — "экспорт/импорт **своих** сущностей", здесь — "сторонний
контент с версией и происхождением"; слияние двух ручек потеряло бы маркер
происхождения, который `transfer` не обязан нести). Переиспользует
машинерию `orchestrator/api/transfer.py` там, где она **не специфична**
transfer'у — path traversal (`validate_path_within`), разбор архива,
conflict-preflight/`force` — выносится в `orchestrator/core/` (тот же
паттерн, что уже сделан для `history.py`/`introspect.py`, не дублируется
между `transfer.py` и новым роутом).

```python
# orchestrator/core/pack_install.py
def read_manifest(pack_bytes: bytes) -> dict: ...
def check_runtime_compat(manifest: dict, runtime_version: str) -> None: ...
def check_dependencies(manifest: dict, contract: dict) -> list[str]:  # missing imports
    ...
def plan_install(manifest: dict, existing_marker: dict) -> dict:  # {new: [...], update: [...], skip_modified: [...]}
    ...
def apply_install(plan: dict, connectors_dir: str) -> None: ...
```

`orchestrator/api/connectors.py` (или новый `orchestrator/api/packs.py` —
решить на этапе плана по размеру: если роутов больше 2-3, отдельный файл,
как остальные сущности) — `POST /connectors/pack/install`:
`admin`-only (та же категория риска, что `/transfer/import`), пишет
`audit.service.record` (`pack.install`, detail = имена
установленных/обновлённых/пропущенных коннекторов, не содержимое файлов —
тот же принцип, что уже есть у `transfer.export`/`transfer.import`),
триггерит тот же reload, что `PUT .../code`
(`load_workflow_metas`-аналог для коннекторов — на самом деле коннекторы
не имеют отдельного "reload", `ConnectorRegistry.init()` вызывается
`soar.runner`-субпроцессом на каждую джобу заново — уточнить на этапе
плана, нужен ли какой-то сигнал оркестратору вообще, или это чисто
файловая операция, которую следующая джоба подхватит сама).

## [S8] Сидинг переезжает

`orchestrator/main.py::seed_defaults()` — сегодня копирует
`soar/connectors/*`/`soar/workflows/*`/`soar/actions/*` в data-каталоги при
пустом volume. После переезда 24 коннекторов из `soar/connectors/` в
отдельный репозиторий пака, `seed_defaults()` для коннекторов заменяется
на: при старте (`lifespan`), если `.soar-content.yaml` не существует и
`connectors_dir` пуст — установить **базовый пак** (встроенный в образ,
см. ниже) тем же путём, что [S6]/[S7] ("поставить недостающие, изменённые
пользователем не трогать" — на первом старте это тривиально, изменённых
ещё нет).

Базовый пак **не тянется по сети** на air-gap инсталляциях — версия пака,
соответствующая релизу платформы, копируется в образ на сборке
(`COPY` в Dockerfile, аналогично сегодняшнему `COPY soar/`), путь
известен через `SOAR_BASE_PACK_PATH` (env, дефолт
`/app/base-pack`). `soarctl content install /app/base-pack` — тот же код
пути, что для любого другого пака, разница только в источнике (локальный
путь в образе vs внешний git/архив). Это закрывает **E4**: `soarctl
update` (git pull + rebuild + `up`) больше не полагается на "volume пуст
только один раз" — при следующем `up` `seed`-эквивалент сравнивает
manifest новой версии образа с `.soar-content.yaml` и доустанавливает
недостающее/новое, а не только на пустом volume.

`workflows_dir`/`actions_dir` — **не входят в эту фазу** (`soar/workflows/`
и `soar/actions/` пакета и так уже пустые за вычетом `__init__.py`/
`base.py`; сегодняшние строки `seed_defaults()`, копирующие
`soar/workflows/*.py`/`soar/actions/*.py`, в реальности не копируют ничего
кроме `__init__.py`/`base.py`, которые сами исключены — это мёртвый код
уже сегодня, удаляется этим же заходом как часть очистки, не отдельным
треком).

## [S9] Пакет очищается

`soar/connectors/` — после переезда: `__init__.py`, `base.py`, `_proxy.py`
(из Фазы 2). Никаких каталогов интеграций. `soar/requirements.txt` теряет
все вендорские SDK-строки, кроме тех, что реально нужны платформенным
инструментам (`httpx`/`requests`/`pyyaml`/`loguru` остаются — используются
`http_client`/`runner.py`/watermark; протокольные — тоже остаются, они
часть контракта Фазы 1 независимо от того, где физически лежит код,
который их использует, — контракт описывает, что **гарантировано**
content-venv, не что использует сам пакет `soar/`). Вендорские (`vt-py`,
`shodan`, `pymisp`, `elasticsearch`) — тоже остаются в контракте (Фаза 1
их уже туда включила: "граница набора — протокол или вендор", оба входят
в контракт, вопрос был не "ставить или нет", а "откуда взялся код,
который их использует" — эта фаза меняет **источник кода**, не набор
пакетов content-venv).

## [S10] Testing Strategy

- `tests/deploy/test_content_cli.py` — `soarctl content install/list/remove`
  на моках `docker`/`subprocess` (тот же паттерн, что все `tests/deploy/`
  — см. `AGENTS.md`, "все на моках subprocess"): install нового пака →
  все коннекторы новые; повторный install той же версии → все `modified:
  false`, no-op; install после ручной правки файла коннектора → этот
  коннектор в `skip_modified`, остальные обновлены; `remove` без `--force`
  на modified → отказ
- `tests/orchestrator/core/test_pack_install.py` — `read_manifest`,
  `check_runtime_compat` (несовместимый `runtime_version` → явная ошибка),
  `check_dependencies` (импорт не в CONTRACT → список недостающих, не
  исключение — вызывающий код решает, 400 или что), `plan_install` (три
  категории: new/update/skip_modified) на synthetic manifest + marker
- `tests/orchestrator/api/test_pack_routes.py` — `POST
  /connectors/pack/install`: conflict-preflight без `force` (аналог
  transfer), успешная установка пишет audit, admin-only (403 для
  analyst/viewer)
- `tests/soar/test_runtime_contract.py` (Фаза 1) — regression: удаление
  коннекторов из `soar/connectors/` не меняет `CONTRACT` (зависимости
  остаются платформенными независимо от физического источника кода,
  см. [S9])
- Существующие 24 `tests/soar/test_*_connector.py` — путь импорта в
  тестах меняется с `soar.connectors.<type>.<type>` на путь пака (если
  тесты остаются в основном репозитории как часть миграции — решить на
  этапе плана: тесты коннекторов, скорее всего, **тоже переезжают** в
  репозиторий пака вместе с кодом, т.к. тестируют контент, не платформу;
  в основном репозитории остаётся один пример/smoke-тест на пайплайн
  install, не 24 файла провера конкретных API вендоров)

## [S11] Success Criteria

- [ ] `soar/connectors/` содержит только `__init__.py`/`base.py`/`_proxy.py`
      — ни одного каталога интеграции (закрывает структурную часть **E1**)
- [ ] Манифест пака генерируется скриптом (AST, без импорта), не пишется
      руками; включает `imports`/`mutating_methods` на каждый коннектор
- [ ] `.soar-content.yaml` — маркер происхождения; `modified` вычисляется
      от текущего sha256, не хранится статично
- [ ] Установка пака отказывает **до записи на диск**, если объявленный
      импорт не в `soar/runtime_contract.py::CONTRACT`
- [ ] `soarctl content install/list/remove` — по образцу
      `soarctl backup`, docker-запись через alpine, без bind-mount
- [ ] `POST /connectors/pack/install` — admin-only, conflict-preflight с
      `force`, audit, переиспользует общую (не transfer-специфичную)
      машинерию из `orchestrator/core/`
- [ ] Сидинг на старте использует тот же install-путь, что ручная
      установка — не отдельный однократный `shutil.copytree`; новые
      коннекторы релиза появляются на существующих инсталляциях после
      `soarctl update` (закрывает **E4**)
- [ ] `docs/agents/known-limitations.md` пункты 9 (E1) и 10 (E2, если ещё
      не снят в Фазе 1) — удалены как описывающие несуществующее состояние
- [ ] Полный прогон `pytest tests/` зелёный, `ruff check .` без находок
