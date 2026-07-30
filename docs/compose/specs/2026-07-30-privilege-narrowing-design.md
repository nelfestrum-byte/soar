# Сужение прав — Phase 4 модели сущностей

> Реализует Фазу 4 из `docs/concepts/ENTITY-MODEL.md` — слой 3 решения 2
> (модель изоляции). Зависит от Фазы 2: сужение кредов до задачи выводит
> список используемых инстансов статически из импортов воркфлоу — это
> тривиально после `from soar.connectors.<type> import <instance>` (E6,
> Фаза 2), было бы невозможно при registry-доступе `connectors.<name>`,
> где имя инстанса — произвольная runtime-строка, а не токен, видимый AST.
> POSIX-специфичные пункты (отдельный UID, `RLIMIT_*`) применимы только на
> Linux/Docker — их ручная проверка выполняется в `deploy/stage`, не
> локально на Windows dev-машине; юнит-тесты мокают `os`/`resource`.

## [S1] Problem

`SubprocessRunner` (после Фазы 1 — запускает контентный интерпретатор, но
тем же UID, что и оркестратор) сегодня:

- Передаёт джобе **все** `.yml`-конфиги всех коннекторов через
  `soar.runner`'s собственную инициализацию (`connectors.init()` без
  ограничения на используемые инстансы) — компрометация пака в одной джобе
  = компрометация всех кредов инсталляции.
- Работает под тем же UID/группой, что процесс оркестратора — теоретически
  может писать в git-репозиторий (`config.git.workflows_repo`) и читать
  `config.yaml` (JWT-секрет, коннект к БД), хотя ему для исполнения
  воркфлоу это не нужно.
- Не ограничен по памяти/CPU/числу процессов — воркфлоу с утечкой памяти
  или fork-бомбой в контентном коде не изолирован от остального хоста.

Явно не в скоупе (решение 2, "вне скоупа"): `bubblewrap`,
namespace-изоляция, Docker-в-Docker. Защищаемся от неаккуратного и
умеренно враждебного контента, не от целенаправленного атакующего с
нативным кодом.

## [S2] Сужение кредов до задачи

Статический вывод используемых инстансов — новая функция в
`orchestrator/core/introspect.py`:

```python
_CONNECTOR_IMPORT_RE_NODE = ast.ImportFrom  # см. ниже — через AST, не regex


def parse_connector_usage(path: Path) -> list[tuple[str, str]]:
    """Static AST scan for `from soar.connectors.<type> import <instance>`
    at module top-level — the only supported import form after Фаза 2 (E6).
    Returns [(type_name, instance_name), ...]. Never imports the module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        parts = node.module.split(".")
        if len(parts) == 3 and parts[0] == "soar" and parts[1] == "connectors":
            type_name = parts[2]
            for alias in node.names:
                result.append((type_name, alias.asname or alias.name))
    return result
```

`SubprocessRunner.start()` (или новый шаг перед ним в `JobManager`/`Worker`)
— на каждую джобу:

1. `parse_connector_usage(workflow_file_path)` — путь берётся из
   `WorkflowMeta.file_path`/эквивалента (проверить на этапе плана, какое
   поле сегодня хранит путь до файла воркфлоу — если нет, добавить,
   аналогично тому, как `path`/`token` уже хранятся для webhook).
2. Строится **временный** конфиг-срез: только `.yml`-записи
   использованных `(type, instance)`, остальные инстансы того же типа —
   исключены из файла, который увидит субпроцесс.
3. Передаётся субпроцессу не как полный `SOAR_CONFIG` (тот же файл, что у
   оркестратора — секрет JWT, БД), а как **отдельный временный YAML**
   только с секцией `soar.connectors_dir`, указывающей на **временный
   каталог** с отфильтрованными `.yml`, символически связанным
   (`os.symlink`, не copy — избежать дублирования кода коннектора) на
   реальные `.py`-файлы коннекторов нужных типов. Полный
   `orchestrator/config.yaml` субпроцессу вообще не виден с этого шага
   (см. [S3] — то же самое, что уже нужно для UID-разделения, две меры
   усиливают друг друга: даже без смены UID процесс физически не получает
   путь к секретам, потому что ему не передан этот файл).
4. Временный каталог удаляется после завершения джобы (`finally` в
   `Worker._execute`, симметрично закрытию `_log_file`).

Воркфлоу, для которых `parse_connector_usage` возвращает пусто (не
используют коннекторы вовсе, либо используют старый `connectors.<name>`
registry-путь — после Фазы 2 остаётся рабочим для обратной совместимости,
но не анализируется статически) — получают **пустой** `connectors_dir`
(нулевые креды) либо (менее строгий вариант, если у инсталляции есть
воркфлоу, ещё не мигрированные на прямой импорт) — полный набор с warning
в лог джобы "static credential scoping unavailable for this workflow,
falling back to full config — migrate to `from soar.connectors.<type>
import <instance>`". Точное поведение fallback — решение на этапе плана,
зависит от того, сколько существующих воркфлоу в реальных инсталляциях
используют старую форму (проверить `tests/`/примеры в репозитории — если
ноль встроенных примеров используют `connectors.<name>` после Фазы 2,
можно жёстко требовать прямой импорт и не давать fallback).

## [S3] Отдельный UID для раннера

`SubprocessRunner.start()` (POSIX-only, `sys.platform != "win32"` guard —
код на Windows не падает, просто не применяет ограничение):

```python
import resource  # POSIX-only stdlib module

def _drop_privileges(uid: int, gid: int, max_memory_bytes: int, max_cpu_seconds: int, max_procs: int):
    def _preexec():
        resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NPROC, (max_procs, max_procs))
        os.setgid(gid)
        os.setuid(uid)
    return _preexec
```

`create_subprocess_exec(..., preexec_fn=_drop_privileges(...) if
sys.platform != "win32" and config.jobs.runner_uid else None)`. Новый
конфиг (`orchestrator/config.py::JobsConfig`):

```python
class JobsConfig(BaseModel):
    ...
    runner_uid: int | None = None   # None = не понижать привилегии (текущее поведение, дефолт для dev)
    runner_gid: int | None = None
    runner_max_memory_mb: int = 512
    runner_max_cpu_seconds: int = 300
    runner_max_procs: int = 32
```

`deploy/{prod,stage}/Dockerfile.orchestrator` — второй непривилегированный
пользователь **отдельный от `soar`** (который сегодня и владелец файлов, и
тот, под кем работает uvicorn) — `soar-runner`, без прав записи в
`/app/data` (git-репозиторий) и без прав чтения `/app/config.yaml`:

```dockerfile
RUN groupadd -r soar-runner && useradd -r -g soar-runner -d /app -s /sbin/nologin soar-runner
...
RUN chmod 640 /app/config.yaml && chown soar:soar /app/config.yaml   # soar-runner не в группе soar — не читает
```

`config.yaml` (prod) генерируется `soarctl init`, владелец/права
выставляются тем же шагом. `RUNNER_UID`/`RUNNER_GID` в `config.yaml` —
числовые id `soar-runner` (узнаваемы на сборке образа, фиксированные —
не `useradd` без `-r`, чтобы id был детерминирован между пересборками
одного Dockerfile).

**Компромисс, зафиксированный явно**: субпроцесс — потомок процесса
оркестратора (`soar` UID на момент fork), `os.setuid`/`setgid` в
`preexec_fn` требует, чтобы родительский процесс имел право сменить UID —
на практике либо оркестратор стартует как root и сразу роняет привилегии
для себя, либо (проще, меньше меняет существующий деплой) `soar-runner`
UID передаётся через `sudo`-подобный минимальный wrapper. Точный механизм
(root-стартовый оркестратор с `setuid` на себя после старта, vs
capability-based approach) — решается на этапе плана с явной пометкой
рисков в отчёте: смена архитектуры "оркестратор всегда non-root"
(`USER soar` в Dockerfile сегодня) — само по себе изменение периметра,
не тривиальная надстройка. Если риск слишком велик относительно ценности
для пилота — этот под-пункт можно отложить отдельным треком без блокировки
остальной Фазы 4 (сужение кредов [S2] не зависит от UID-разделения [S3] —
независимые меры, решение 2 явно называет их отдельными слоями).

## [S4] Testing Strategy

- `tests/orchestrator/core/test_introspect.py` (Фаза 1 файл, дополнение) —
  `parse_connector_usage` на synthetic воркфлоу-файлах: один импорт, два
  импорта из разных типов, импорт с `as`-алиасом, воркфлоу без импортов
  коннекторов → `[]`
- `tests/orchestrator/test_subprocess_runner_env.py` (дополнение) —
  временный конфиг-срез содержит только нужные `(type, instance)` записи
  (мокнуть filesystem/tempfile, проверить содержимое сгенерированного
  YAML); полный `config.yaml` не передаётся как `SOAR_CONFIG` дочернему
  процессу
- `tests/orchestrator/test_subprocess_runner_privileges.py` — новый файл,
  POSIX-only (`pytest.mark.skipif(sys.platform == "win32")`):
  `_drop_privileges` строит `preexec_fn`, вызывающий `resource.setrlimit`
  с правильными значениями из `JobsConfig` (мокнуть `resource`/`os.setuid`/
  `os.setgid`, не реально ронять привилегии тестового процесса)
- `tests/orchestrator/test_worker.py` — временный конфиг-каталог удаляется
  после завершения джобы, включая случаи timeout/cancel (те же ветки, что
  уже закрывают `_log_file`)
- Docker/deploy verification — ручная, не pytest (POSIX UID/rlimit
  реально проверяются только в `deploy/stage` на Linux-хосте, см. header)

## [S5] Success Criteria

- [ ] `parse_connector_usage` — статический вывод используемых
      `(type, instance)` пар из воркфлоу-файла, без импорта
- [ ] Субпроцесс получает конфиг-срез только с используемыми инстансами,
      не полный `connectors_dir`; полный `orchestrator/config.yaml`
      (JWT-секрет, БД) недоступен субпроцессу по пути
- [ ] (POSIX/Docker) `soar-runner` — отдельный UID от `soar`; `preexec_fn`
      выставляет `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC` из конфига
- [ ] (POSIX/Docker) раннер не может писать в git-репозиторий воркфлоу и
      не может прочитать `config.yaml` — проверено вручную на
      `deploy/stage`, зафиксировано в отчёте с точной командой проверки
- [ ] Компромисс по механизму смены UID (root-старт vs альтернатива)
      зафиксирован в отчёте явно, включая решение отложить/не отложить
- [ ] Полный прогон `pytest tests/` зелёный (кросс-платформенная часть),
      `ruff check .` без находок
- [ ] `docs/concepts/ENTITY-MODEL.md` — часть 4 "Перед релизом" выполнена
      целиком (см. отдельный чеклист там же)
