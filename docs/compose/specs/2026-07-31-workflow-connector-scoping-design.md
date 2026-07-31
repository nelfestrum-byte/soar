# Fix workflow → action → connector pattern: init order + transitive credential scoping (Д1+Д2)

> Реализует Д1 и Д2 из `docs/compose/reports/manual-qa-prod-onsite.md` §3 —
> найдены в одной живой E2E-сессии 2026-07-31, компаундируются друг с другом
> (см. отчёт §3, "Итог компаунда"): без обоих фиксов основной документированный
> паттерн (`AGENTS.md` "движок vs поведение": workflow → actions → connector)
> нерабочий при включённом (всегда включённом) credential scoping. Один спек
> на оба пункта — они одна причинно-следственная цепочка, чинить по отдельности
> бессмысленно (частичный фикс всё равно оставляет паттерн нерабочим, см. отчёт).

## [S1] Problem

### Д1 — `soar/runner.py` инициализирует реестры в неверном порядке

`soar/runner.py:95-97`:

```python
workflows.init(external_dir=external_dirs.get("workflows"))
connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))
```

`workflows.init()` импортирует каждый файл в `workflows_dir` (и встроенный
`soar/workflows/`). Любой воркфлоу с верхнеуровневым
`from soar.actions.<name> import <func>` или
`from soar.connectors.<type> import <instance>` резолвится только если:

- `from soar.connectors.<type> import <instance>` — модуль-шим
  `soar.connectors.<type>` уже установлен в `sys.modules`, что происходит в
  `_install_shims()`, вызываемом **в конце** `connectors.init()`
  (`soar/connectors/__init__.py:130`);
- `from soar.actions.<name> import <func>` — `sys.modules["soar.actions.<name>"]`
  уже существует, что происходит внутри `actions.init()` →
  `_discover_external()` (`soar/actions/__init__.py:49-71`), которая явно
  регистрирует `fqn = f"soar.actions.{module_name}"` в `sys.modules` перед
  исполнением файла.

Оба реестра инициализируются **после** `workflows.init()` — на момент импорта
воркфлоу ни один из двух путей не резолвится. `WorkflowRegistry._discover_external`
(`soar/workflows/__init__.py:50-59`) ловит `ImportError` как warning и просто не
регистрирует воркфлоу — без пробрасывания причины. Результат при последующем
`workflows.execute(name, ...)`: `ValueError: Workflow '<name>' not found`
(`soar/workflows/__init__.py:112`) — верхнеуровневый traceback, не намекающий
на реальную причину (порядок инициализации).

Воспроизведено 100%, 6/6 прогонов джоб в QA-сессии, независимо от
`dry_run`/real (отчёт §3, Д1).

### Д2 — `parse_connector_usage` не видит connector-usage, транзитивный через actions

Воркараунд Д1 (перенос импорта action внутрь `run()`) регистрирует воркфлоу,
но credential scoping (`orchestrator/core/subprocess_runner.py::build_scoped_config`)
даёт джобе **пустой** `connectors_dir` — воркфлоу не может создать коннектор
даже когда сам вызов дойдёт до строки с ним.

`orchestrator/core/introspect.py::parse_connector_usage` (строки 123-151)
статически сканирует **только** `ast.ImportFrom`-узлы на верхнем уровне
**переданного файла** (файла воркфлоу) вида `from soar.connectors.<type>
import <instance>`. Если коннектор используется не напрямую воркфлоу, а
транзитивно через action (документированный паттерн из `AGENTS.md`
"движок vs поведение": "Код, переиспользуемый между несколькими workflow →
`soar/actions/`") — импорт `from soar.connectors.<type> import <instance>`
физически находится в файле action'а, не в файле воркфлоу. Сканер его не
видит **независимо от того, где стоит импорт action'а в самом воркфлоу**
(верхний уровень модуля или внутри `run()`) — сканируется только сам файл
воркфлоу, а внутри него нет ни одного `from soar.connectors...`.

Итог (отчёт §3, "Итог компаунда"): пересечение множеств решений для чистого
контента пусто. Импорт action'а обязан быть верхнеуровневым, чтобы
зарегистрировать воркфлоу (⇒ упирается в Д1 при старом порядке); коннектор,
используемый этим action'ом, при этом всё равно не виден scoping'у ни в каком
варианте — это отдельный, второй дефект, не устраняемый одним лишь фиксом Д1.

`build_scoped_config`'s docstring (`orchestrator/core/subprocess_runner.py:70-90`)
уже документирует один сознательно исключённый случай ("старая форма
`connectors.<name>` — не поддерживается") — но **не** упоминает
actions-паттерн вообще; транзитивность через actions не была учтена в
исходном дизайне E6/Фазы 2 `ENTITY-MODEL.md`, это пробел, а не намеренное
ограничение.

## [S2] Solution — Д1: порядок инициализации

`soar/runner.py` — переставить: `connectors.init()` → `actions.init()` →
`workflows.init()`.

Обоснование порядка (не любая перестановка корректна):

1. `connectors.init()` первым — он последним шагом вызывает `_install_shims()`,
   которая должна отработать до того, как что-либо (actions или workflows)
   попытается `from soar.connectors.<type> import <instance>` на верхнем
   уровне модуля.
2. `actions.init()` вторым — actions могут сами делать верхнеуровневый
   `from soar.connectors.<type> import <instance>` (документированный
   паттерн "action использует коннектор"), и это должно резолвиться уже на
   этапе импорта action'а, не только когда воркфлоу его использует.
3. `workflows.init()` последним — воркфлоу может верхнеуровнево импортировать
   и actions, и connectors напрямую; оба пути к этому моменту резолвятся.

`tools.http_client`/`tools.http_client_sync` (см.
`2026-07-28-http-client-init-order-design.md`) остаются собранными раньше всех
трёх `*.init()` — этот фикс не трогает их позицию, только переставляет
относительный порядок трёх `*.init()` вызовов между собой.

```python
tools.http_client = _build_http_client(config)
tools.http_client_sync = _build_http_client_sync(tools.http_client)

connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))
workflows.init(external_dir=external_dirs.get("workflows"))
```

## [S3] Solution — Д2: транзитивное разрешение connector-usage через actions

Расширить `parse_connector_usage`, не нарушая инвариант "никогда не
импортирует модуль" (докстринг, `E6`/`ENTITY-MODEL.md` Фаза 2): вместо одного
файла сканировать граф статических импортов "воркфлоу → actions", **рекурсивно**,
методом чистого AST (без `importlib`).

```python
def parse_connector_usage(
    path: Path,
    actions_dir: str | Path | None = None,
    _visited: set[Path] | None = None,
) -> list[tuple[str, str]]:
    if _visited is None:
        _visited = set()
    resolved = path.resolve()
    if resolved in _visited:
        return []
    _visited.add(resolved)

    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: list[tuple[str, str]] = []
    action_modules: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        parts = node.module.split(".")
        if len(parts) == 3 and parts[0] == "soar" and parts[1] == "connectors":
            type_name = parts[2]
            result.extend((type_name, alias.name) for alias in node.names)
        elif len(parts) == 3 and parts[0] == "soar" and parts[1] == "actions":
            action_modules.append(parts[2])

    if actions_dir:
        actions_root = Path(actions_dir)
        for module_name in action_modules:
            action_path = actions_root / f"{module_name}.py"
            if not action_path.is_file():
                continue
            try:
                result.extend(parse_connector_usage(action_path, actions_dir, _visited))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue  # broken action file must not blank out the rest of the scan
    return result
```

`action_modules.append(parts[2])` runs once per `ImportFrom` node (not once
per imported name) — which specific name is imported from the action module
doesn't matter for resolution, only the fact that `soar.actions.<module_name>`
is imported at all.

Ключевые решения:

- **`actions_dir` — новый опциональный параметр**, по умолчанию `None`.
  Обратная совместимость: все существующие вызовы `parse_connector_usage(path)`
  (5 тестов в `tests/orchestrator/core/test_introspect.py`) продолжают
  работать без изменений — без `actions_dir` рекурсия в actions просто не
  запускается (эквивалент сегодняшнего поведения).
- **Рекурсия, не фиксированная глубина 1.** Хотя документированный паттерн —
  один хоп (workflow → action → connector), рекурсивный обход actions →
  actions "бесплатен" и не требует отдельного проектного решения о лимите
  глубины — просто следует за фактическим графом импортов. Защита от цикла —
  множество `_visited` резолвленных путей.
- **Ошибка в одном action-файле не обнуляет остальные находки.** В отличие от
  `build_scoped_config`, который целиком оборачивает вызов
  `parse_connector_usage` в try/except (файл воркфлоу либо парсится целиком,
  либо даёт пустой список), здесь try/except стоит **вокруг каждого
  рекурсивного вызова по отдельности** — сломанный/нечитаемый action не должен
  лишать кредов остальные корректные импорты того же воркфлоу.
- **Не резолвится алиас `instance_name`, как и раньше** (уже описано в
  докстринге: `alias.name`, не `alias.asname`) — то же правило применяется
  внутри action-файлов симметрично.

`orchestrator/core/subprocess_runner.py::build_scoped_config` (строка ~97):

```python
usage = parse_connector_usage(Path(workflow_file), actions_dir=soar_cfg.get("actions_dir"))
```

Докстринги обновить:

- `parse_connector_usage` — заменить "at workflow module top-level" на
  описание транзитивного обхода через `soar.actions.*`-импорты; сохранить
  формулировку "Never imports the module" (по-прежнему верна — рекурсия идёт
  по AST, не по `importlib`).
- `build_scoped_config` — параграф "Workflows for which parse_connector_usage
  returns nothing... get a scoped config with an *empty* connectors_dir"
  остаётся верным (это про воркфлоу без вообще какого-либо статически
  резолвимого импорта); добавить, что "directly imports" теперь означает
  "directly, or transitively through `soar.actions.*` imports it uses".

### Альтернативы, рассмотренные и отклонённые

**Расширить `parse_connector_usage`, импортируя action-модуль реально
(`importlib`), чтобы прочитать его исходный код через `inspect.getsource`.**
Отклонено: нарушает инвариант "никогда не импортирует" (`ENTITY-MODEL.md`
принцип 5 — граница рантаймов, оркестраторный процесс не должен исполнять
контент); `_discover_external` в `actions/__init__.py` уже показывает, что
top-level код action-модуля может делать что угодно (в т.ч. сетевые вызовы на
импорте) — недопустимо для scoping-пути, который вызывается перед каждым
job'ом в привилегированном процессе оркестратора.

**Не чинить Д2, а задокументировать как ограничение** ("actions-based паттерн
не поддерживает credential scoping, используйте только прямой импорт
коннектора в воркфлоу"). Отклонено: `AGENTS.md` "движок vs поведение"
документирует actions как штатное место для переиспользуемого кода между
воркфлоу — де-факто запрещать credential-using action ломает ровно тот
паттерн, ради которого actions существуют. Отчёт (Д2) явно указывает на
компаунд с Д1: без фикса Д2 даже правильный порядок инициализации не даёт
рабочего результата для actions-based воркфлоу.

## [S4] Testing Strategy

### Д1 — `tests/soar/test_runner.py`

- Расширить существующий `test_runner_assigns_http_client_before_registry_init`
  (или добавить соседний тест) — по аналогии с уже работающей
  source-position-проверкой (`inspect.getsource(runner)` + `source.index(...)`):
  assert позиция `connectors.init(external_dir=` и `actions.init(external_dir=`
  меньше позиции `workflows.init(external_dir=`.
- Новый интеграционный тест на **свежих** инстансах `ConnectorRegistry`,
  `ActionsRegistry`, `WorkflowRegistry` (не на процесс-глобальных singleton'ах
  — по тому же паттерну, что уже применяется в
  `test_from_import_http_client_sees_configured_instance_when_assigned_before_init`,
  который создаёт `WorkflowRegistry()` напрямую, не трогая `soar.workflows.workflows`):
  - `tmp_path` fixtures: `connectors/qa_httpbin/{qa_httpbin.py содержит
    BaseConnector-подкласс, qa_httpbin.yml с одним instance}`,
    `actions/check_qa_ip.py` с `from soar.connectors.qa_httpbin import x` +
    функция, использующая `x`, `workflows/qa_manual_test.py` с
    `from soar.actions.check_qa_ip import check_qa_ip` + класс-наследник
    `ManualWorkflow`.
  - Правильный порядок: `ConnectorRegistry().init(external_dir=connectors_dir)`
    → `ActionsRegistry().init(external_dir=actions_dir)` →
    `WorkflowRegistry().init(external_dir=workflows_dir)`. Assert
    `workflow_registry.get_class("qa_manual_test") is not None`.
  - Регрессионный негативный тест — старый (баг) порядок:
    `WorkflowRegistry().init(...)` **до** инициализации connector/action
    реестров (свежие, неинициализированные `ConnectorRegistry`/`ActionsRegistry`
    для этого теста, либо просто не вызывать их init вовсе). Assert
    `get_class("qa_manual_test") is None` — воспроизводит ровно найденный баг,
    защищает от повторного дрейфа порядка.

### Д2 — `tests/orchestrator/core/test_introspect.py`

- `test_parse_connector_usage_follows_action_import_transitively`: workflow
  `.py` с `from soar.actions.check_x import check_x`; `actions_dir/check_x.py`
  с `from soar.connectors.virus_total import vt_main`. Assert
  `parse_connector_usage(workflow_path, actions_dir=actions_dir) ==
  [("virus_total", "vt_main")]`.
- `test_parse_connector_usage_without_actions_dir_ignores_action_imports`:
  тот же workflow-файл, вызов **без** `actions_dir` (или `actions_dir=None`).
  Assert `== []` — фиксирует backward-compatible дефолт.
- `test_parse_connector_usage_combines_direct_and_transitive_imports`:
  workflow импортирует один коннектор напрямую **и** action, который
  импортирует другой. Assert оба присутствуют.
- `test_parse_connector_usage_missing_action_file_is_skipped`: workflow
  ссылается на несуществующий `soar.actions.<x>` (нет файла в `actions_dir`)
  — no crash, `[]` (или остальные валидные находки, если есть).
- `test_parse_connector_usage_broken_action_file_does_not_abort_scan`:
  workflow импортирует connector напрямую **и** сломанный (SyntaxError)
  action. Assert прямой импорт всё равно присутствует в результате.
- `test_parse_connector_usage_action_import_cycle_does_not_recurse_infinitely`:
  action A импортирует action B, action B импортирует action A (или сам
  себя) — assert вызов завершается (no `RecursionError`), возвращает то, что
  реально резолвится один раз.

### Д2 — `tests/orchestrator/test_subprocess_runner_env.py::TestBuildScopedConfig`

- `test_scopes_transitively_through_action_import`: workflow импортирует
  `soar.actions.<x>`, `actions_dir/<x>.py` импортирует
  `soar.connectors.virus_total.vt_main`; `full_config["soar"]["actions_dir"]`
  указывает на этот `actions_dir`. Assert `scoped["soar"]["connectors_dir"]`
  содержит `virus_total/instances.yml` с `vt_main` (тот же паттерн проверки,
  что в `test_scopes_to_only_used_instance`).

## [S5] Success Criteria

- [ ] Воркфлоу с верхнеуровневым `from soar.actions.<name> import <func>`
      успешно регистрируется (`GET /workflows/{name}` находит его, job не
      падает с `Workflow '<name>' not found`)
- [ ] Тот же воркфлоу, запущенный через `POST /jobs`, получает в scoped
      `connectors_dir` credentials коннектора(ов), используемых
      транзитивно через action — `ConnectorProxy` реально резолвится в
      subprocess'е, а не падает на "Registered 0 connectors"
- [ ] `parse_connector_usage(path)` без `actions_dir` ведёт себя как раньше
      (все 5 существующих тестов зелёные без изменений)
- [ ] Сломанный/отсутствующий action-файл не приводит к падению всего
      static-scan'а и не обнуляет прямые импорты того же воркфлоу
- [ ] Цикл импортов между actions не даёт `RecursionError`
- [ ] `docs/agents/*.md`/`AGENTS.md` — если где-то описан порядок
      инициализации `runner.py` или объём credential scoping для actions,
      свериться и поправить вместе с этим фиксом
- [ ] Ручной E2E повтор (минимум) Phase 5-7 из
      `docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md` на пересобранном
      стенде — воркфлоу `qa_manual_test` с верхнеуровневыми импортами actions
      выполняется успешно, `SOAR_AUDIT_EVENT connector.call` появляется в логе
      джобы (закрывает "Что не покрыто" п.1 из отчёта)
