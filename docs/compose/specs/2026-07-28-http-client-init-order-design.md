# Fix `HttpClient` Singleton Init Order (S2)

> Реализует S2 из `docs/concepts/BAGFIX_PLAN.md`. `from soar.tools import
> http_client` в любом модуле верхнего уровня навсегда захватывает
> неконфигурированный дефолтный инстанс — докстринг обещает обратное.

## [S1] Problem

`soar/runner.py`:

```
35  workflows.init(external_dir=external_dirs.get("workflows"))
36  connectors.init(external_dir=external_dirs.get("connectors"))
37  actions.init(external_dir=external_dirs.get("actions"))
...
63  tools.http_client = _build_http_client(config)
```

`*.init()` на строках 35-37 импортируют все модули workflows/actions/
connectors (реестры сканируют директории и делают `importlib` на каждый
найденный файл). Любой такой модуль, содержащий на верхнем уровне
`from soar.tools import http_client` (не `import soar.tools as tools` +
`tools.http_client` — именно `from ... import`), делает Python-биндинг
имени `http_client` в своём namespace **в момент импорта** — на объект,
на который в этот момент указывает `soar.tools.http_client`, то есть на
дефолт из `soar/tools/__init__.py`:

```python
http_client = HttpClient()  # cache=None — pure logging-proxy
```

Переприсваивание `tools.http_client = _build_http_client(config)` на
строке 63 создаёт **новый** объект и перепривязывает имя
`http_client` в модуле `soar.tools` — но модуль коннектора/action,
импортировавший `http_client` строкой выше, продолжает держать ссылку на
старый объект (`HttpClient()` без кэша, дефолтные `default_ttl`/
`domain_ttl`). Это стандартная семантика Python `from module import name`
— переприсваивание в исходном модуле не распространяется на уже
выполненные `from`-импорты в других модулях.

Докстринг `soar/tools/__init__.py:3-6` обещает ровно обратное: "actions
can always `from soar.tools import http_client` ... without wiring
anything themselves" — неверно при текущем порядке вызовов, см. D4.

## [S2] Solution

Переставить порядок: собрать `http_client`/`http_client_sync`
(см. `docs/compose/specs/2026-07-28-http-client-sync-facade-design.md`)
**до** `workflows.init()`/`connectors.init()`/`actions.init()` —
пользовательский код ещё не импортирован, любой последующий `from
soar.tools import http_client` в нём захватит уже финальный,
сконфигурированный объект:

```python
# soar/runner.py — новый порядок

tools.http_client = _build_http_client(config)      # NEW: раньше init()
tools.http_client_sync = _build_http_client_sync(config)  # см. S1-спеку

workflows.init(external_dir=external_dirs.get("workflows"))
connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))
```

`_build_http_client(config)` не переносится телом — переносится только
**вызов**. Само построение уже не зависит ни от чего, что появляется в
`init()` (оно читает только `config` dict, распарсенный из YAML раньше
обоих блоков) — переупорядочивание безопасно, нет скрытой зависимости
`init()` → `http_client`, только обратная (потенциальная) зависимость
`init()`-импортируемый код → `http_client`, которую и чиним.

### Альтернатива, рассмотренная и отклонённая

**Ленивый `module-level __getattr__`** в `soar/tools/__init__.py`
(PEP 562) — `from soar.tools import http_client` вызывает
`__getattr__("http_client")` **на каждое обращение**, только если
обращаться через атрибут модуля напрямую в момент использования, а не
через `from ... import name` (тот всё равно делает биндинг имени один
раз в момент импорта — `__getattr__` module-level решает проблему только
для `import soar.tools as tools; tools.http_client`, не для `from
soar.tools import http_client`, который и есть корень проблемы согласно
докстрингу самого модуля). Не решает заявленный сценарий, отклонено.
Переупорядочивание вызовов — единственный фикс, реально совместимый с
обещанием докстринга ("can always `from soar.tools import
http_client`").

## [S3] Testing Strategy

Новый тест в `tests/soar/test_runner.py` (или новый файл, если такого
пока нет — проверить на этапе плана):

- Создать фикстурный `actions`/`connectors` модуль (временный файл в
  `tmp_path`, обнаруживаемый через `external_dir`), который на верхнем
  уровне делает `from soar.tools import http_client` и на импорт
  сохраняет `id(http_client)` в module-level переменную, читаемую тестом
  после `runner`-инициализации.
- Прогнать инициализационную последовательность `runner.py`
  (извлечь в тестируемую функцию, если сейчас это top-level код модуля —
  на этапе плана решить, оборачивать ли top-level логику `runner.py` в
  функцию `_init()` для тестируемости, не меняя `main()`/контракт
  subprocess).
- Assert: `id(http_client)`, увиденный фикстурным модулем, совпадает с
  `id(tools.http_client)` после инициализации (тот же объект, не дефолт).
- Regression: `tools.http_client` по-прежнему собирается из
  `http_client:` секции конфига (cache backend/ttl) — существующее
  покрытие `_build_http_client()` не меняется.

## [S4] Success Criteria

- [ ] Любой module-level `from soar.tools import http_client` в
      workflow/action/connector-коде видит сконфигурированный инстанс,
      не дефолт
- [ ] `_build_http_client()`/эквивалент для `http_client_sync`
      (см. S1-спеку) вызываются раньше `workflows.init()`/
      `connectors.init()`/`actions.init()`
- [ ] Существующее поведение (какой backend/ttl выбирается из конфига)
      не меняется — меняется только момент присваивания
- [ ] `soar/tools/__init__.py` докстринг остаётся верным без изменения
      текста (утверждение и так было про желаемое поведение — не про
      факт до фикса; после фикса факт совпадает с докстрингом)
- [ ] `docs/agents/*.md`/`AGENTS.md` — если где-то описан порядок
      инициализации `runner.py`, свериться и поправить вместе с этим
      фиксом (D4)
