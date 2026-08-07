# PoC-фидбек (elastic_trueconf/TrueConf): bootstrap-traceback, формат тела PUT, подсказки схемы

> Разбор отчёта "SOAR (новый продукт): PoC-коннектор к Elasticsearch на
> инциденте TrueConf" — слепое (без доступа к кодовой базе) тестирование
> боевого стенда, 7 находок. Отчёт написан вне обычного цикла
> specs→plans→reports (ad hoc тест инструмента), в `docs/reports/` на момент
> этого спека не сохранён — разбор идёт по тексту, присланному в чате.
>
> Часть находок уже закрыта коммитами, предшествующими этому спеку:
> **№1** (безусловный egress-блок на приватные адреса) —
> [`2026-08-06-egress-policy-design.md`](2026-08-06-egress-policy-design.md),
> commit `ad0dc6c`, allowlist теперь конфигурируется (`config.yaml` →
> `egress.mode`/`egress.allow`) и виден через `GET /runtime` + документирован
> в `system_prompt.md` §6. **№2** (PUT `/config` теряет hidden-поле при
> `********`) и часть **№7** (агент не мог сохранить код коннектора без
> ручного копирования человеком) — оба закрыты
> [`2026-08-06-connector-code-agent-unlock-design.md`](2026-08-06-connector-code-agent-unlock-design.md),
> commit `857ecd2`: `PUT /connectors/{name}/code` вернули роли `agent`, а
> `PUT /connectors/{name}/config` закрыли для неё **целиком** (не только
> merge-логику) — воспроизведённый в отчёте сценарий ("agent шлёт `********`,
> поле пропадает") сегодня даёт `403` до того, как код вообще доходит до
> `_merge_hidden_fields`. См. `docs/agents/known-limitations.md` #9.
>
> Этот спек — по тому, что осталось: **№3** (реальный баг в коде, не
> документационный пробел — подтверждено чтением `soar/runner.py` и
> `orchestrator/core/worker.py`, не только текстом отчёта), **№4**, **№6**.
> №5 и остаток №7 разобраны в [S0] и не требуют кода.

## [S0] Найденное, но не требующее кода

**№5 — у Workflow нет `POST /workflows/{name}`, у Connector есть.**
Не асимметрия документации: `system_prompt.md` §2 перечисляет "symmetric API
groups" явно как `GET /{kind}`, `GET /{kind}/{name}`, `GET /{kind}/{name}/code`,
`PUT /{kind}/{name}/code`, `DELETE` — создание (`POST`) в этот список не
входит и не заявлено симметричным. У Workflow есть свой эквивалент —
`GET /workflows/code/template` (`orchestrator/api/workflows.py:202`).
`POST /connectors/{name}` существует не ради симметрии, а потому что у
коннектора, в отличие от воркфлоу, два файла (`.py` + `.yml`) и структура
каталога, которую нужно инициализировать разом; воркфлоу — один файл, и
первый `PUT .../code` создаёт его без промежуточного шага. Разница
обоснована структурой сущности, не баг. Вне объёма этого спека.

**№7 (остаток) — review/approve-флоу для admin-gated действий.**
Большая часть уже закрыта `857ecd2`: `PUT /connectors/{name}/code` — ровно
то действие, которое в отчёте описано как "самое чувствительное, получившее
наименее эргономичный путь" — снова доступно `agent`. Остаётся закрыт только
`PUT /connectors/{name}/config` (значения credential'ов), и это осознанное
решение, не забытый кусок review-флоу: `known-limitations.md` #9 прямо
говорит, что роль `agent` и так имеет произвольное исполнение кода в
субпроцессе джобы — давать ей ещё и запись значений секретов было бы шагом
назад, а не отсутствующей фичей. `propose`/`apply`-эндпоинты под один этот
случай (человек вписывает значение в форму) — оverengineering относительно
задачи. Вне объёма.

## [S1] №3 — `result_error` не содержит traceback для сбоев bootstrap-фазы

### Problem

Отчёт описывает разницу в поведении между сбоями внутри `run()` (полный
traceback в `result_error` — верно) и сбоями до входа в `run()` (только
`"Process failed"`, реальный traceback только через `GET /logs/{id}`).
Чтение кода подтверждает: это не документационный пробел, а конкретный баг.

`soar/runner.py:122-124` — три вызова на уровне **модуля**, вне `try/except`
в `main()` (строки 142-159):

```python
connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))
workflows.init(external_dir=external_dirs.get("workflows"))
```

`connectors.init()` (`soar/connectors/__init__.py:127`) конструирует каждый
инстанс: `bucket[instance_name] = cls(instance_name=instance_name, **params)`
— ровно там воспроизводится `TypeError: missing api_key` из отчёта. Ничто
между этой строкой и завершением процесса эту ошибку не ловит: Python
печатает необработанный traceback в **stderr** процесса и завершает его
кодом 1; `main()` не запускается, JSON-строка с `result_error` в stdout
никогда не печатается.

`orchestrator/core/worker.py:145-146`:

```python
if not job.result_error:
    job.result_error = stdout.decode() if stdout else "Process failed"
```

читает только `stdout` (пустой в этом случае) — traceback остаётся в
`stderr`, который эта ветка не читает вообще. `result_error` получает
литерал `"Process failed"`.

`system_prompt.md` §5 обещает ровно противоположное: "Full traceback on
failure ... including failures that happen before `run()` is even entered
(bad constructor, unknown workflow name, or an import that doesn't
resolve)". Обещание выполняется для `workflows.execute()` внутри `main()`'s
`try/except` и не выполняется для `connectors.init()`/`actions.init()`/
`workflows.init()` — а конструирование коннектора при старте job-процесса
это не пограничный случай: это единственный способ, которым коннектор вообще
появляется (§3 `system_prompt.md` — импорт инстанса на уровне модуля).

### Solution

Обернуть bootstrap-вызовы в тот же JSON-контракт, что и `main()`, но только
в контексте реального запуска субпроцесса — гейт `if __name__ == "__main__"`,
как уже сделано для `install_audit_hook()` (строки 57-73; обоснование в
докстрине там же: тесты импортируют `from soar import runner` в процессе
pytest, где `__name__ != "__main__"`, и должны продолжать получать исходный
`raise` на импорте, не перехваченный/отформатированный сбой).

```python
def _bootstrap() -> None:
    tools.http_client = _build_http_client(config)
    connectors.init(external_dir=external_dirs.get("connectors"))
    actions.init(external_dir=external_dirs.get("actions"))
    workflows.init(external_dir=external_dirs.get("workflows"))


if __name__ == "__main__":
    install_audit_hook(parse_egress_policy(config.get("egress", {})))
    try:
        _bootstrap()
    except Exception:
        print(json.dumps({
            "success": False,
            "workflow_name": os.environ.get("SOAR_WORKFLOW_NAME", ""),
            "duration_seconds": None,
            "data": None,
            "error": traceback.format_exc(),
        }))
        flush_audit_hook()
        sys.exit(1)
else:
    _bootstrap()
```

(`install_audit_hook(...)` остаётся на своём месте, до `_bootstrap()` —
только оборачивается в тот же `if __name__ == "__main__":` блок, который уже
существует; порядок "hook раньше любого init()" не меняется.)

`import traceback` поднимается на уровень модуля (сейчас он локальный,
внутри `main()`). `flush_audit_hook()` вызывается и в этой ветке — hook уже
установлен раньше, и события, случившиеся до сбоя (например частичная
попытка `socket.connect`), не должны теряться.

`worker.py` не меняется: раз `result_error` теперь приходит как последняя
строка JSON в stdout при любом исходе (успех, сбой в `run()`, сбой в
bootstrap), путь `stdout.decode() if stdout else "Process failed"` остаётся
резервным для того, что всё ещё не гарантирует JSON на stdout — `SIGKILL` по
таймауту/OOM, где никакого `main()`/`_bootstrap()` вообще не было. Это не
регрессия, это единственный оставшийся случай, для которого фолбэк и
существовал.

## [S2] №4 — `PUT .../code` и `.../config` молча принимают JSON-конверт как сырой текст

### Problem

`orchestrator/api/connectors.py` (аналогично `actions.py`, `workflows.py`):
`body = await request.body()`, `content = body.decode("utf-8")` — без
Pydantic-модели и без проверки формы. Тело `{"content": "<yaml>"}` — валидный
UTF-8 — записывается в файл целиком, включая фигурные скобки и `\n` как
текст, а не перевод строки. Ответ `200 OK` / `{"status": "saved", ...}` не
даёт никакого сигнала, что записано не то, что предполагал вызывающий —
особенно правдоподобная ошибка, раз `GET` на том же ресурсе отдаёт именно
конверт `{"name", "content"}`.

### Solution

Узкая эвристика, не блокирующая произвольный JSON-подобный текст (легитимный
код воркфлоу может начинаться с `{`) — отклоняется конкретно форма,
совпадающая с конвертом `GET`:

```python
# orchestrator/api/validation.py
def reject_json_envelope(content: str) -> None:
    stripped = content.lstrip()
    if not stripped.startswith("{"):
        return
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return
    if isinstance(parsed, dict) and "content" in parsed and set(parsed) <= {"name", "content"}:
        raise HTTPException(
            status_code=422,
            detail='Body must be the raw file content, not a JSON envelope '
                   'like {"content": ...} — PUT and GET use different body shapes.',
        )
```

Условие требует одновременно: (а) весь body — валидный JSON, (б)
верхнеуровневый объект — `dict`, (в) ключи — подмножество `{"name",
"content"}`, включающее `"content"`. Ложных срабатываний на реальном коде
практически нет — ни один существующий встроенный коннектор/воркфлоу/экшен
не начинается с `{"content": ...}` как первой конструкцией файла, и
Python-код с `{` в начале строки без этого специфического ключевого набора
не совпадёт.

Вызывается после `content = body.decode("utf-8")`, до записи файла, на всех
четырёх write-роутах: `connectors.py::save_connector_code`,
`::save_connector_config`, `actions.py`'s `PUT /{name}/code`,
`workflows.py`'s `PUT /{name}/code`.

Дополнительно — `system_prompt.md` §2 получает явную фразу про форму тела:
"PUT принимает сырой текст файла в теле запроса — не JSON, не `{name,
content}` (та форма только у ответа `GET` на этом же ресурсе)".

## [S3] №6 — `GET /connectors/{name}/schema` не подсказывает формат для сложных типов

### Problem

`orchestrator/core/introspect.py::_fields` отдаёт `{"name", "type",
"default"}`, где `"type"` — `ast.unparse` аннотации (`"list[str]"`,
`"dict[str, str]"` и т.п.) без примера значения. Поле `hosts: list[str]`,
заполненное через Swagger UI как плоская строка `"192.168.1.51:9200"`,
проходит валидацию записи (это валидный YAML — строка) и падает только в
рантайме джобы с `ValueError: URL must include a 'scheme'...`.

### Solution

Не расширять AST-парсинг семантикой полей (коннектор её не объявляет) —
синтетическая подсказка, выведенная из строки типа, на стороне
API-роута (`orchestrator/api/connectors.py::get_connector_schema`), не в
`introspect.py` (там — структура для машины, не форматирование для
человека):

```python
_FORMAT_HINTS: dict[str, str] = {
    "list[str]": 'YAML-список строк, например: ["host1", "host2"]',
    "dict[str, str]": "YAML-отображение, например: {key: value}",
    "bool": "true или false",
}


def _format_hint(type_str: str) -> str | None:
    return _FORMAT_HINTS.get(type_str.strip())
```

Добавляется как необязательный ключ `format_hint` в каждый элемент `fields`
(отсутствует/`None` для типов не из таблицы — `str`, `int` самоочевидны и
подсказки не требуют). Перед реализацией — `grep -rn ": list\[\|: dict\[\|:
\s*bool" soar-content-pack` (или туда, куда переехали встроенные коннекторы
после Content-as-Contentpack, см. `docs/agents/known-limitations.md`) —
таблица покрывает типы, которые реально встречаются в существующих
конструкторах, не исчерпывающий парсер произвольных типовых выражений.

## Риск / что не входит в этот спек

- №1, №2 закрыты предыдущими коммитами (`ad0dc6c`, `857ecd2`) — не трогаются.
- №5, остаток №7 — см. [S0], без кода.
- `"Process failed"` в `worker.py` остаётся как резервная ветка для путей,
  всё ещё не гарантирующих JSON на stdout (`SIGKILL`/timeout) — не
  расширяется на чтение `stderr`, чтобы не заводить второй источник
  диагностики рядом с уже существующим контрактом "JSON — последняя строка
  stdout".
- Формат-подсказки [S3] — не валидация: Swagger UI по-прежнему примет
  `hosts` как плоскую строку и запись пройдёт (валидация конструктора
  требует импорта, а платформа принципиально не импортирует контент на
  запись — см. `ENTITY-MODEL.md`, принцип 4). Это подсказка на месте, где
  человек/агент видит схему, а не gate на запись.
