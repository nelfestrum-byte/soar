# Plan: Сужение прав — Phase 4

Spec: `docs/compose/specs/2026-07-30-privilege-narrowing-design.md`

Ветка: `feat/entity-model-phase4`, из `main` (после Phase 1-3 смерджены).
Мердж после зелёного `pytest tests/` (кросс-платформенная часть) и ручной
POSIX-верификации на `deploy/stage`.

## 1. Статический вывод используемых коннекторов

Tests first (`tests/orchestrator/core/test_introspect.py`, дополнение):

- [ ] `parse_connector_usage` на файле с `from soar.connectors.virus_total
      import vt_main` → `[("virus_total", "vt_main")]`
- [ ] Два импорта разных типов → оба в результате
- [ ] `from soar.connectors.ssh import prod as ssh_prod` (alias) →
      `[("ssh", "ssh_prod")]`
- [ ] Файл без импортов коннекторов → `[]`
- [ ] Импорт не из `soar.connectors.*` (например `from soar.tools import
      http_client`) — игнорируется
- [ ] Confirm tests fail before function exists

Implementation:

- [ ] `orchestrator/core/introspect.py`: `parse_connector_usage(path)` —
      как в spec [S2]

## 2. Конфиг-срез на джобу

Tests first (`tests/orchestrator/test_subprocess_runner_env.py`, дополнение):

- [ ] Функция, строящая временный конфиг (найти/создать имя —
      например `build_scoped_config(workflow_file, full_config)` в
      `subprocess_runner.py`) — на воркфлоу с одним используемым
      инстансом возвращает путь к YAML, содержащему только
      `instances: {<instance>: {...}}` для нужного типа, остальные типы/
      инстансы исключены
- [ ] Полный `config.yaml` (с `auth.secret_key`/`database.url`) не
      копируется и не симлинкается в scoped-конфиг — только
      `soar.connectors_dir` секция и необходимые для рантайма
      `soar.workflows_dir`/`soar.actions_dir`/`soar.tools_dir`
      (workflow-файл и actions воркфлоу нужны субпроцессу так же, как
      сегодня — сужаются только connector-креды, не весь конфиг)
- [ ] Временный каталог создаётся через `tempfile.mkdtemp`, символические
      ссылки (`os.symlink`, мокнуть в тесте) на реальные `.py` нужных
      типов коннекторов, отфильтрованные `.yml`
- [ ] Confirm tests fail before implementation

Tests first (`tests/orchestrator/test_worker.py`, дополнение):

- [ ] Временный конфиг-каталог удаляется в `finally` после нормального
      завершения джобы
- [ ] Удаляется и при timeout/cancel (те же ветки, что закрывают
      `_log_file`)
- [ ] Confirm tests fail before cleanup wired in

Implementation:

- [ ] `orchestrator/core/subprocess_runner.py`: `build_scoped_config(...)`
      — использует `parse_connector_usage` + путь до файла воркфлоу
      (проверить/добавить поле пути в `WorkflowMeta`, если отсутствует —
      см. spec [S2] п.1)
- [ ] `SubprocessRunner.start()`: строит scoped config, передаёт его путь
      как `SOAR_CONFIG` вместо `_CONFIG_PATH` (полного конфига), когда
      `parse_connector_usage` дал непустой результат; fallback-поведение
      на пустой результат — решить и задокументировать при реализации (см.
      spec [S2] последний абзац)
- [ ] `Worker._execute`: `finally`-блок удаляет временный каталог
      (`shutil.rmtree`), симметрично закрытию `_log_file`

## 3. Отдельный UID + rlimits (POSIX/Docker)

Tests first (`tests/orchestrator/test_subprocess_runner_privileges.py`,
новый файл, `skipif(sys.platform == "win32")`):

- [ ] `_drop_privileges(uid, gid, max_memory_bytes, max_cpu_seconds,
      max_procs)` возвращает callable; вызов этого callable вызывает
      `resource.setrlimit` три раза с правильными парами значений,
      `os.setgid(gid)`, `os.setuid(uid)` в правильном порядке (gid до uid)
- [ ] `SubprocessRunner.start()` передаёt `preexec_fn` в
      `create_subprocess_exec` только если `config.jobs.runner_uid`
      задан и платформа не Windows
- [ ] `runner_uid=None` (дефолт) — `preexec_fn=None`, поведение не
      меняется относительно сегодняшнего
- [ ] Confirm tests fail before implementation

Implementation:

- [ ] `orchestrator/config.py::JobsConfig`: `runner_uid`, `runner_gid`,
      `runner_max_memory_mb` (дефолт 512), `runner_max_cpu_seconds`
      (дефолт 300), `runner_max_procs` (дефолт 32)
- [ ] `orchestrator/core/subprocess_runner.py`: `_drop_privileges(...)` —
      как в spec [S3], POSIX-guard
- [ ] `deploy/{prod,stage}/Dockerfile.orchestrator`: `soar-runner`
      пользователь/группа, `chmod 640 config.yaml` + `chown soar:soar`
      (или соответствующий путь для `deploy/stage`, где `config.yaml`
      копируется в образ, а не генерируется `soarctl init`)
- [ ] Зафиксировать в реализации выбранный механизм смены UID
      (root-старт оркестратора и `setuid` на себя после bind, либо
      альтернатива) — если выбранный механизм требует менять `USER soar`
      на `USER root` в Dockerfile с последующим self-drop в
      `orchestrator/main.py`, явно описать это в отчёте как изменение
      периметра, не тихую деталь

## 4. Docs

- [ ] `docs/concepts/ENTITY-MODEL.md`: отметить чеклист части 4 "Перед
      релизом" — снять пункты 9/10 known-limitations (если ещё не сняты
      предыдущими фазами), обновить раздел "Модель сущностей" в
      `AGENTS.md` на фактическое состояние
- [ ] `AGENTS.md`: новая запись Version history после реализации; секция
      "Security patterns"/`docs/agents/security-patterns.md` — добавить
      описание credential scoping + UID/rlimit narrowing

## Verification

- [ ] `python -m pytest tests/orchestrator/core/test_introspect.py
      tests/orchestrator/test_subprocess_runner_env.py
      tests/orchestrator/test_worker.py -v`
- [ ] `python -m pytest tests/orchestrator/test_subprocess_runner_privileges.py -v`
      (скипается на Windows dev-машине — приемлемо, POSIX-only функционал;
      реально прогоняется в Linux CI/deploy stage, если такой контур есть)
- [ ] `python -m pytest tests/ -q` — ноль новых failures
- [ ] `ruff check .`
- [ ] Ручная POSIX-верификация на `deploy/stage` (Linux Docker): джоба под
      `soar-runner` не может `cat /app/config.yaml`, не может писать в
      git-репозиторий воркфлоу; воркфлоу с `from soar.connectors.<type>
      import <instance>` получает креды только для использованных
      инстансов (проверить логом/временным конфигом, не оставлять только
      "должно работать")
- [ ] Написать отчёт `docs/compose/reports/privilege-narrowing.md`,
      включая явную пометку принятого/отложенного компромисса по UID
