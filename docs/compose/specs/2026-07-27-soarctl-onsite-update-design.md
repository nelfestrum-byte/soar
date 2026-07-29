# `soarctl`: on-site установка из git + `update` без пересоздания БД

> **Superseded (2026-07-29)** — директорийная модель этого спека (`install
> --repo`/`--dir` копирует `docker-compose.yml`/`config.yaml.template` в
> отдельную instance-директорию, `--repo <url>` клонирует сам) заменена
> `docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md`: чекаут —
> это инстанс, `install`/`update`/`--ref`/`source.json`-маркер и решение
> "миграции без авто-детекта" остаются теми же по духу, изменилась только
> файловая раскладка. Оставлен как референс истории решения.

> Расширяет `docs/compose/specs/2026-07-22-deploy-cli-design.md`. Тот спек
> проектировал **air-gapped** путь (`package` на машине с интернетом →
> перенос tar-бандла → `install` без единого сетевого вызова на изолированной
> цели). Этот спек добавляет параллельный путь для случая, когда целевая
> машина **сама имеет доступ в интернет** (тот же git-чекаут, что и у
> разработчика/оператора, или свежий `git clone` прямо на месте) — без
> посредника-бандла. Существующий bundle-путь не меняется.

## [S1] Problem

Сегодня единственный способ обновить прод-инстанс — цикл из
`deploy/prod/README.md` → «Upgrading to a new version»: на **отдельной**
машине с интернетом собрать `soarctl package --version X.Y.Z`, перенести tar
на целевую машину, `soarctl install <bundle> --dir <тот же instance>`,
`soarctl up`, вручную решить `migrate --fresh` или `--upgrade`. Это осмысленно
для air-gap, но избыточно, когда:

1. **Установка и цель — одна и та же машина.** Оператор держит git-чекаут
   SOAR прямо на машине, где крутится прод (или готов сделать
   `git clone` там же — интернет есть). Гонять бандл через промежуточный tar
   ради этого не нужно — можно собрать образы прямо на месте
   (`docker build` без `docker save`/`docker load`).
2. **Обновление кода — это `git pull`, а не новый бандл.** Оператор уже
   умеет `git fetch`/`git checkout <tag>`; сегодня `soarctl` не знает, что
   инстанс вообще связан с каким-то git-чекаутом — `install` из бандла
   самодостаточен и специально ничего не помнит об источнике (см.
   `bundle.py`: цель бандл-модели — не требовать чекаута на целевой машине
   вообще). Нужен отдельный, более лёгкий путь именно для этого сценария.
3. **`config.yaml.template` рендерится вслепую.** `env.init_instance()`
   молча подставляет плейсхолдер `cors_origins: ["https://CHANGE-ME.example.com"]`
   — README теперь просит отредактировать это руками (чек-лист, закрывающий
   P17 из `UPGRADE-v2.md` документацией, не кодом). Для on-site-сценария,
   где оператор и так сидит за терминалом в момент установки, разумнее
   спросить домен интерактивно и не дать продолжить с фиктивным значением.
4. **«Обновить без сноса контейнеров и БД»** — сегодня это не то, что
   ломается, а то, что оператору приходится помнить руками: `docker compose
   down` в процессе апгрейда не нужен и не должен использоваться, но ничего
   в CLI явно не гарантирует и не проговаривает эту гарантию как контракт
   команды.

## [S2] Solution Overview

### `soarctl install --repo <url-or-path> [--ref REF]` — второй источник для `install`

Дополняет (не заменяет) `soarctl install <bundle.tar.gz>`. Один и тот же
subcommand, два взаимоисключающих источника:

```
soarctl install <bundle.tar.gz> [--dir PATH]              # существующий, без изменений
soarctl install --repo <url-or-path> [--ref REF] [--dir PATH]   # новый
```

`--repo` принимает:
- **локальный путь** к уже существующему чекауту (типичный случай —
  оператор передаёт `.`/путь к своему рабочему дереву, тому же, где ведётся
  разработка) — используется как есть, `git clone` не делается;
- **URL** — клонируется в `<dest_dir>/src`.

Что делает (аналог `bundle.package()`, но без `docker save`/`docker load` —
образы строятся и остаются локально):

1. `git -C <checkout> checkout <ref>`, если `--ref` передан.
2. `resolve_git_version(checkout)` — версия для тега образа и `.env`.
3. `docker build` `soar-orchestrator`/`soar-ui` из
   `<checkout>/deploy/prod/Dockerfile.*`, тег — resolved-версия. `docker
   pull` `redis:7-alpine`/`postgres:16-alpine` (интернет есть — в этом весь
   смысл on-site-режима, в отличие от air-gap).
4. Копирует `<checkout>/deploy/prod/docker-compose.yml` +
   `config.yaml.template` в `dest_dir` (та же структура instance-директории,
   что и после bundle-install — `init`/`up`/`migrate`/`users`/`backup`/
   `status` работают одинаково независимо от источника, без веток по коду).
5. Пишет `dest_dir/source.json`: `{"repo": "<аргумент --repo как есть>",
   "checkout": "<абсолютный путь к чекауту>"}` — единственное новое
   состояние, которое отличает git-инстанс от bundle-инстанса; читается
   только `update` (см. ниже).
6. Пишет `dest_dir/VERSION` тем же способом, что и `bundle.package()` —
   даунстрим-код (`env.init_instance`, `paths.read_version`) не знает и не
   должен знать, git это было или бандл.

`resolve_git_version()`:

```python
def resolve_git_version(checkout: Path) -> str:
    result = run(["git", "-C", str(checkout), "describe", "--tags", "--always", "--dirty"])
    return result.stdout.strip()
```

`--dirty` — намеренно: если оператор собрал образ с незакоммиченными
правками, это обязано быть видно в теге образа и в `SOAR_VERSION` внутри
`.env`/`soarctl status`, а не выглядеть как чистый релиз.

Общий шаг сборки образов выносится в `bundle.build_images(repo_root,
version) -> tuple[str, str]` (возвращает теги orchestrator/ui) и
переиспользуется и `bundle.package()`, и новым git-путём — сегодня
`bundle.package()` инлайнит `docker build`/`docker pull` без переиспользуемой
границы; после рефакторинга оба пути зовут одну и ту же функцию вместо
дублирования списка `docker build -f ... -t ...` аргументов.

### `soarctl init --interactive` / `--cors-origin URL` — опционально для обоих источников

`env.init_instance()` получает новый параметр `overrides: dict[str, str] |
None`, накладываемый поверх `generate_secrets()` перед рендером шаблона —
чистая функция, без I/O, тестируется как есть.

```python
def init_instance(directory: Path, force: bool = False, overrides: dict[str, str] | None = None) -> None:
    values = generate_secrets()
    values["SOAR_VERSION"] = read_version(directory)
    values["CORS_ORIGINS_JSON"] = json.dumps(["https://CHANGE-ME.example.com"])
    values.update(overrides or {})
    ...
```

`config.yaml.template` меняется, чтобы `cors_origins` стал настоящей
`${VAR}`-подстановкой вместо литерала, который сегодня руками правит README:

```diff
 auth:
   secret_key: "${AUTH_SECRET_KEY}"
-  # REQUIRED: set to the real UI origin(s) before going live — ...
-  cors_origins: ["https://CHANGE-ME.example.com"]
+  cors_origins: ${CORS_ORIGINS_JSON}
```

`json.dumps([...])` даёt валидный YAML flow-list (`["https://..."]`) — та же
подстрока, что и раньше, просто теперь она — значение переменной, а не
хардкод в шаблоне.

Новые флаги `init`:

- `--interactive` — спрашивает `UI origin(s), через запятую: `, валидирует
  каждый через чистую функцию `_valid_origin(url) -> bool` (схема
  `http(s)://`, без пути), повторяет вопрос при пустом/невалидном вводе.
  Без этого флага поведение не меняется — плейсхолдер остаётся плейсхолдером,
  ничего не ломается для существующего air-gap флоу.
- `--cors-origin URL` (`action="append"`, можно несколько раз) — задаёт
  значение без интерактивного ввода; конфликтует с `--interactive`
  (`parser.error`, если оба переданы — одно из двух, не смешивать источники
  правды).

Оба флага доступны на **обоих** источниках `install` (bundle и git) — это
свойство `init`, не привязанное к тому, как заполнялась instance-директория.
Для bundle/air-gap `--interactive` тоже валиден (человек всё ещё сидит за
терминалом в момент `init`), просто в air-gap-раннбуке он не упоминается как
обязательный шаг — README для `deploy/prod/` air-gap-пути не меняется в этой
части.

### `soarctl update` — новая команда, только для git-инстансов

```
soarctl update [--ref REF] [--migrate fresh|upgrade] [--dir PATH]
```

1. Читает `dest_dir/source.json` — если файла нет, явная ошибка: *"this
   instance wasn't installed via `soarctl install --repo` — bundle-based
   instances upgrade via `soarctl install <new-bundle>`, see README"*.
   Разделение путей осознанное: у bundle-инстанса на целевой машине нет
   чекаута и не должно быть (air-gap), пытаться унифицировать — значит
   тащить git-зависимость в air-gap-цель, что напрямую противоречит [S2]
   `2026-07-22-deploy-cli-design.md`.
2. `git -C <checkout> fetch --tags`, затем:
   - если передан `--ref` — `git -C <checkout> checkout <ref>`;
   - иначе — `git -C <checkout> pull --ff-only` на текущей ветке.
     `--ff-only`, не `--rebase`/force: чекаут, которым управляет `soarctl`,
     не должен расходиться с origin; расхождение — сигнал остановиться и
     разобраться руками, а не автоматически подмять историю.
3. `resolve_git_version(checkout)` → пересобрать оба образа тем же
   `bundle.build_images()`, что и `install` — новый тег, старые теги образов
   на диске не трогаются (дешёвый путь отката: вручную вернуть
   `SOAR_VERSION` в `.env` на предыдущее значение и `soarctl up`, если
   старый образ ещё не удалён `docker image prune`).
4. `env.update_version(dest_dir, new_version)` — **та же функция**, что уже
   используется `bundle.install()` на bundle-апгрейде: правит только
   `SOAR_VERSION` в `.env`, секреты не трогает.
5. `compose.up(dest_dir)` — буквально существующий `up()` (`docker compose
   up -d`). Ключевой момент дизайна: **отдельного "no-downtime"-режима не
   вводится** — гарантия "без сноса контейнеров и БД" следует из того, что
   изменились только теги образов `orchestrator`/`ui`; `redis`/`postgres` в
   `docker-compose.yml` ссылаются на неизменные `image:`-теги, поэтому
   `docker compose up -d` их не пересоздаёт и не перезапускает — это
   штатное поведение compose при частичном изменении конфигурации сервисов,
   не требует новой логики в `soarctl`.
6. Миграции — **не выполняются неявно**, тот же принцип, что у `soarctl
   migrate` (см. `migrate.py`, нет авто-детекта `stamp` vs `upgrade` —
   ошибка выбора портит состояние БД, см. non-goal в
   `2026-07-22-deploy-cli-design.md`). Если передан `--migrate {fresh,upgrade}`
   — вызывается соответствующий алиас после `up` (порядок важен по той же
   причине, что уже описана в README: `migrate` эксэкает в **текущий**
   запущенный контейнер, поэтому обязан идти после `up`, иначе применится
   `alembic/versions/` старого образа). Если флаг не передан — `update`
   печатает то же напоминание, что сегодня в README-шаге 4 «Upgrading to a
   new version»: проверить `alembic/versions/` новой версии и решить руками.
7. В конце — `status.check_health()` + `compose.ps()`, тот же вывод, что у
   `soarctl status`, чтобы оператор сразу увидел, что пересозданные
   контейнеры поднялись живыми.

## [S3] Architecture

```
deploy/soarctl_lib/
├── bundle.py            # MODIFY: extract build_images(repo_root, version) shared helper,
│                         #         package()/install() reuse it, no behavior change for bundle path
├── git_source.py         # NEW: install(repo, ref, dest_dir), update(instance_dir, ref, migrate)
│                         #      resolve_git_version(), source.json read/write
├── prompts.py            # NEW: _valid_origin() (pure, tested) + prompt_cors_origins() (thin input() loop)
├── env.py                # MODIFY: init_instance(..., overrides=None), CORS_ORIGINS_JSON default
├── cli.py                # MODIFY: install --repo/--ref (mutually exclusive w/ bundle positional),
│                         #         init --interactive/--cors-origin, new `update` subcommand
└── doctor.py              # MODIFY: +check_git_source(instance) — only runs if source.json exists

deploy/prod/
└── config.yaml.template   # MODIFY: cors_origins literal → ${CORS_ORIGINS_JSON}

deploy/prod/README.md      # MODIFY: new "On-site (this machine has internet)" section,
                            #         parallel to the existing air-gap walkthrough
```

## [S4] Non-goals

- **Унификация с bundle-апгрейдом.** `update` работает только для
  git-инстансов (`source.json` есть). Bundle-инстансы продолжают
  апгрейдиться через уже документированный `install <new-bundle>` — не
  переизобретаем air-gap путь.
- **Автоматический откат.** `update` не хранит и не переключает версии сам —
  только оставляет предыдущий образ на диске как ручной путь отхода.
  Отдельная `soarctl rollback` — вне scope.
- **Zero-downtime/blue-green.** Гарантия — «postgres/redis не трогаются»,
  не «orchestrator/ui обновляются без единой секунды простоя». Кратковременный
  рестарт этих двух контейнеров при `up -d` — ожидаемое поведение, не баг.
- **`deploy/stage/`** не трогаем — там уже есть свой `build:`-путь для того
  же по духу сценария «на месте, есть интернет», но на уровне QA-стенда
  (`Makefile`, секреты в `config.yaml`). Этот спек — про `deploy/prod/` с
  версионированием образов и секретами через `.env`, которых у `stage` нет.
- **Мультиинстансность** — по-прежнему Known Limitation #8, не расширяется
  и не сужается этим спеком.
- **Авто-detect stamp/upgrade** — не решается и здесь; `update --migrate`
  добавляет два тех же явных алиаса, а не умный выбор.

## [S5] Testing Strategy

- `resolve_git_version()`, `build_images()` — `run()` мокается
  (`subprocess.run`), как и весь остальной `soarctl_lib` (см.
  `2026-07-22-deploy-cli-design.md` [S4]) — без живого Docker/git.
- `env.init_instance(..., overrides=...)` — чистая функция, тест на то, что
  `overrides` побеждает дефолт `CORS_ORIGINS_JSON`, а без `overrides`
  сохраняется старое поведение (плейсхолдер).
- `prompts._valid_origin()` — таблица валидных/невалидных строк
  (`http://x`, `https://x`, `ftp://x` → False, `` → False, `x` → False).
  Сам `input()`-цикл в `prompt_cors_origins()` не юнит-тестируется — то же
  решение, что и для `getpass` в `orchestrator/auth/cli.py`, тонкая обвязка
  вокруг уже протестированной чистой функции.
- `git_source.update()` — тест на то, что при отсутствии `source.json`
  бросается понятная ошибка *до* любого `git`/`docker` вызова (fail-fast,
  без побочных эффектов на неправильном типе инстанса).
- End-to-end (install --repo . → init --interactive → up → migrate --fresh →
  users create → коммит правки → update → status) — ручной smoke-прогон на
  реальном Docker+git, тем же способом и с той же документацией результата
  в отчёте, что и e2e-прогон исходного `soarctl` (см.
  `2026-07-22-deploy-cli-design.md` [S4]). Отдельно проверить: `docker
  compose ps` показывает, что `soar-postgres`/`soar-redis` НЕ пересозданы
  (`CreatedAt`/uptime не изменились) после `update`, а `soar-orchestrator`/
  `soar-ui` пересозданы на новый образ — это и есть проверяемый критерий
  «без сноса контейнеров и БД», не просто утверждение в тексте.

## [S6] Success Criteria

- [ ] `soarctl install --repo <path>` собирает образы локально (без
      `docker save`/`docker load`) и создаёт instance-директорию, идентичную
      по структуре той, что создаёт bundle-install — `up`/`migrate`/`users`/
      `backup`/`status` не содержат веток по источнику
- [ ] `soarctl install --repo <url> --ref <tag>` клонирует репозиторий и
      чекаутит именно `<tag>`, версия образа/`.env` — из `git describe`, с
      суффиксом `-dirty`, если рабочее дерево было грязным на момент сборки
- [ ] `soarctl init --interactive` не даёт продолжить с фиктивным
      `cors_origins`; `soarctl init` без флагов ведёт себя как сегодня
      (плейсхолдер, ручное редактирование по README) — нет регрессии для
      air-gap пути
- [ ] `soarctl update` без `source.json` в instance-директории — явная
      ошибка, ноль побочных эффектов
- [ ] `soarctl update` после `git pull`/`checkout` пересобирает и
      перевыкатывает **только** `orchestrator`/`ui`; `postgres`/`redis`
      контейнеры не пересоздаются (проверено в e2e по `CreatedAt`)
- [ ] `soarctl update` не запускает миграции без явного `--migrate
      fresh|upgrade`; без флага печатает то же ручное напоминание, что
      сегодня в README
- [ ] `bundle.build_images()` переиспользуется и `package()`, и
      `git_source.install()`/`update()` — список `docker build`-аргументов
      не продублирован
- [ ] `deploy/prod/README.md` документирует on-site-путь как отдельный
      раздел, не переписывая существующий air-gap-раннбук
