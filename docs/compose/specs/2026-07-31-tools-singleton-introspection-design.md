# `GET /tools` — интроспекция синглтонов и фабрик (Д4)

> Закрывает Д4 из `docs/compose/reports/manual-qa-prod-onsite.md` (прогон
> 2026-07-31). Коммит `451d3e5` устранил узкий баг Д3 (`GET
> /tools/{name}` 404 → 200 для синглтонов), но не восстановил содержимое:
> ответ для всех 4 синглтонов (`http_client`, `http_client_sync`,
> `seen_store`, `watermark_store`) — тот же урезанный `{"name", "module",
> "summary": ""}`, что и раньше. Принцип 4 (AGENTS.md) для этих
> инструментов на практике не выполняется.

## [S1] Problem

`orchestrator/core/introspect.py::parse_classes` — единственный источник
данных для `GET /tools`/`GET /tools/{name}`
(`orchestrator/api/tools.py:6,28,50`). Он видит только top-level
`ast.ClassDef`. `soar/tools/__init__.py::__all__` (E5, единственный
источник истины о том, что публично) содержит 6 имён, из которых **4 не
являются именами классов**:

```python
__all__ = [
    "http_client",        # экземпляр: http_client = HttpClient()          (__init__.py:8)
    "http_client_sync",   # экземпляр: http_client_sync = SyncHttpClient() (__init__.py:13)
    "WatermarkStore",     # класс — parse_classes видит, работает
    "SeenStore",          # класс — parse_classes видит, работает
    "watermark_store",    # функция-фабрика: def watermark_store(name)     (watermark.py:124)
    "seen_store",         # функция-фабрика: def seen_store(name, ttl=...) (watermark.py:131)
]
```

Это два разных случая, оба сейчас закрыты одним и тем же fallback'ом
(`tools.py:37`, `tools.py:56`) — синтетической записью без докстринга и
сигнатур:

1. **Экземпляр синглтона**, присвоенный на уровне модуля
   (`http_client`/`http_client_sync`) — реальный класс (`HttpClient`/
   `SyncHttpClient`) существует и находится `parse_classes`, но только по
   **имени класса**, а не по имени переменной, под которым инструмент
   публично известен. `GET /tools/HttpClient` (не в `__all__`) вернул бы
   полные данные, но `GET /tools/http_client` (то, что реально в
   `__all__` и то, что импортируют workflow/action-авторы) — нет.
2. **Функция-фабрика** (`watermark_store`/`seen_store`) — top-level
   `def`, `orchestrator/core/introspect.py::parse_functions` (строка 96)
   уже умеет её парсить (докстринг + сигнатура), но `tools.py` эту
   функцию никогда не вызывает — только `parse_classes`.

Отдельный, более глубокий слой того же пробела: `parse_classes`
(`introspect.py:57-64`) фильтрует методы класса через `isinstance(item,
ast.FunctionDef)`, что **не включает** `ast.AsyncFunctionDef`. `HttpClient`
(`soar/tools/http_client.py:154,176`) — `async def get_json`/`async def
post_json`. Даже если бы (1) был решён простым маппингом имя→класс,
`GET /tools/http_client` показал бы класс с `methods: []` — ровно те
сигнатуры, которые предыдущий QA-прогон был вынужден искать в исходнике
(`docs/compose/reports/manual-qa-prod-onsite.md`, Д4: "Пришлось прочитать
`soar/tools/http_client.py` напрямую"), остались бы недостижимы через API
даже после фикса (1). `SyncHttpClient.get_json`/`post_json`
(`http_client.py:206,228`) — обычные `def`, этой части бага не подвержены;
проблема специфична к `http_client`, не к `http_client_sync`.

Воспроизводится для всех 4 синглтонов детерминированно (Д4 в отчёте, `curl
GET /tools/http_client_sync` → `{"name":"http_client_sync","module":"__init__","summary":""}`).

## [S2] Solution

Три независимых, но связанных изменения — все в
`orchestrator/core/introspect.py` + `orchestrator/api/tools.py`, ни одно
не трогает `soar/tools/`:

**(a) `parse_classes` — включить `async def` методы.**
```python
if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
```
→
```python
if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_")
```
`_signature()` не меняется — читает только `fn.args`, идентичный атрибут
у обоих типов узлов. Аннотировать возвращаемый тип у `_signature`/
`_fields` как `ast.FunctionDef | ast.AsyncFunctionDef` для точности (не
обязательно для работы, но убирает вводящий в заблуждение type hint).

**(b) Новый AST-хелпер `parse_module_functions`-путь для фабрик** — уже
есть (`parse_functions`), просто **вызвать** его в `tools.py` для имён из
`public`, не найденных среди классов: пройтись `parse_functions(py_file)`
по тем же файлам `tools_dir.glob("*.py")`, что уже сканируются под
классы, и добавить в `result` совпадения `fn["name"] in public`, с
формой, отличимой от класса (`"kind": "function"`, `"signature"` вместо
`"constructor"`/`"methods"`/`"fields"`).

**(c) Новый AST-хелпер для резолва синглтон-экземпляров.**
`introspect.py`:

```python
def parse_instance_assignments(path: Path) -> dict[str, str]:
    """`name = ClassName(...)` на верхнем уровне модуля → {name: ClassName}.
    Используется для резолва синглтонов вроде `http_client = HttpClient()`
    (soar/tools/__init__.py) на их класс, без импорта модуля."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            out[target.id] = node.value.func.id
    return out
```

`tools.py`: собрать `classes_by_name` при первом проходе по
`tools_dir.glob("*.py")` (уже итерируется для (a)/(b), просто индексировать
результат `parse_classes` по имени класса вместо немедленной фильтрации
по `public`). Затем для имён из `public`, не покрытых ни классом, ни
функцией (a/b), вызвать `parse_instance_assignments(tools_dir /
"__init__.py")`; если `instance_name in public` резолвится в
`class_name`, и `class_name in classes_by_name` — вернуть запись класса
с `"name": instance_name` (не `class_name`) и дополнительным полем
`"instance_of": class_name`, чтобы ответ не выглядел как объявление
самого класса.

Порядок разрешения на каждое публичное имя: класс по имени → функция по
имени → инстанс-присвоение в `__init__.py` → синтетический fallback
(текущее поведение, оставить как последний рубеж на случай будущего
дрейфа `__all__`, не как норму).

## [S3] Regression check

- (a) расширяет набор методов, отдаваемых `GET /tools/{ClassName}` и
  `/connectors/.../describe` (используют тот же `parse_classes`,
  `orchestrator/api/connectors.py:83,101,406,422`) — включает `async def`
  методы, которых раньше не было в ответе. Сегодняшний рантайм
  workflow/action/connector синхронный (см.
  `2026-07-28-http-client-sync-facade-design.md` [S1]) — ни один
  встроенный класс, кроме `HttpClient`, `async def` методов не имеет,
  проверить это явно тестом ((S4), а не полагаться на факт), чтобы (a) не
  оказалось тихой регрессией для будущего async-класса с приватными
  helper-методами, случайно ставшими публичными.
- (b)/(c) только **добавляют** содержимое туда, где раньше был пустой
  synthetic-fallback (`summary: ""`) — в `tests/orchestrator/api/test_tools_api.py`
  ни `http_client_sync`, ни `watermark_store`, ни `seen_store` не
  встречаются по имени сегодня (только собирательно через `names` в
  `test_real_soar_tools_dunder_all_excludes_internals`), так что (b)/(c)
  не переписывают существующий зелёный тест — только должны не сломать
  `test_get_tool_returns_synthetic_entry_for_non_class_singleton`/
  `test_list_tools_shows_non_class_singletons_from_dunder_all` (см. [S4]).
- `GET /tools` (list, не `/tools/{name}`) должен получить те же три пути
  резолва — сейчас список строит synthetic-запись тем же способом
  (`tools.py:36-37`), одинаковый по духу с `get_tool`; не развести их в
  разные реализации.

## [S4] Testing Strategy

`tests/orchestrator/api/test_tools_api.py` (файл уже существует, 8
тестов). Важно для (c): `test_get_tool_returns_synthetic_entry_for_non_class_singleton`
и `test_list_tools_shows_non_class_singletons_from_dunder_all` заводят
`"some_singleton"` только в `__all__` фикстурного `__init__.py`
(`_write_init`), **без** реального `some_singleton = Widget()`
присвоения — под новым порядком резолва это по-прежнему падает через все
три пути в synthetic fallback, тесты остаются зелёными без изменений (это
и есть регрессионный контроль на "имя из `__all__`, которое ничему не
резолвится" — не путать с реальными `http_client`/`http_client_sync`,
которые как раз присвоены). `test_real_soar_tools_dunder_all_excludes_internals`
проверяет только *наличие* имён в списке, не `summary`/`methods` — не
защищает от регрессии по содержимому, поэтому новые тесты ниже нужны
отдельно:

- `test_get_tool_http_client_sync_returns_full_signature` — `GET
  /tools/http_client_sync` → `docstring` непустой, `constructor` есть,
  `methods` содержит `get_json`/`post_json`/`put_json` с непустыми
  `signature` (воспроизводит Д4 ровно, красный до (c), зелёный после).
- `test_get_tool_http_client_includes_async_methods` — `GET
  /tools/http_client` (или прямой юнит-тест `parse_classes` на
  `http_client.py`) → `methods` содержит `get_json`/`post_json`
  (воспроизводит async-пробел, красный до (a)).
- `test_get_tool_watermark_store_factory` /
  `test_get_tool_seen_store_factory` — `GET /tools/watermark_store` →
  `docstring`/`signature` непустые, форма отличима от class-based записи
  (например по отсутствию `constructor`/наличию `kind: "function"`).
- Регрессия: `test_get_tool_watermark_store_class` (существующий класс
  `WatermarkStore`, уже проходит сегодня) остаётся зелёным — (b)/(c) не
  должны перехватить резолв класса раньше него.
- Юнит-тест на `parse_instance_assignments` (`tests/orchestrator/test_introspect.py`,
  если есть, иначе рядом с существующими юнитами `parse_classes`) — на
  синтетическом временном файле `foo = Bar()` → `{"foo": "Bar"}`,
  плюс негативный случай `foo = some_func()` (звонок не по `Name`, а
  тривиальный сценарий) и `foo: Bar = Bar()` (`AnnAssign`, сейчас не
  покрыт функцией — решить, покрывать ли, или явно задокументировать как
  неподдерживаемую форму, раз `soar/tools/__init__.py` её не использует).

## [S5] Success Criteria

- [ ] `GET /tools/http_client_sync` отдаёт docstring + конструктор +
      `get_json`/`post_json`/`put_json` с сигнатурами — без чтения
      `soar/tools/http_client.py`
- [ ] `GET /tools/http_client` дополнительно отдаёт `get_json`/`post_json`
      (async-методы), не только докстринг класса
- [ ] `GET /tools/watermark_store`, `GET /tools/seen_store` отдают
      docstring + сигнатуру фабрики
- [ ] `GET /tools` (список) для всех 6 имён `__all__` даёт непустой
      `summary`, кроме случаев, когда докстринг у самого класса/функции
      действительно пуст
- [ ] Существующие тесты на `GET /tools/WatermarkStore`/`SeenStore`
      (class-based) остаются зелёными без изменений
- [ ] Ни один тест, полагавшийся на `summary: ""` для этих 4 имён как на
      ожидаемое поведение, не остался — либо обновлён, либо не
      существовал
