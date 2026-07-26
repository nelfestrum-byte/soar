# Connector Config Schema + Secret Field Redaction

> Реализует P13 из `docs/concepts/UPGRADE-v2.md`. Заменяет план "sidecar-
> файл вне git" на редакцию значений на уровне API-ответа поверх схемы,
> выведенной из сигнатуры конструктора коннектора — без изменения формата
> хранения (`{name}.yml`, единая git-история).

## [S1] Problem

`GET /connectors/{name}/config` (`orchestrator/api/connectors.py:429`)
отдаёт содержимое `{name}.yml` как есть — пароли, API-ключи, bind-DN
пароли открытым текстом. RBAC на этой ручке:

```
orchestrator/api/connectors.py:29
_RO = ("viewer", "analyst", "service", "admin", "agent")
```

`viewer` — самая низкопривилегированная read-only роль — имеет доступ.
Хуже: `PUT /connectors/{name}/config` (`connectors.py:498-532`) пишет
файл и коммитит его в git через `GitManager`; `GET .../config/history`
(`connectors.py:452`), `.../config/history/{commit}` (`connectors.py:459`),
`.../config/diff` (`connectors.py:468`) — тоже `_RO` — отдают содержимое
любой прошлой версии. Даже если замаскировать текущее значение, любой
пароль, когда-либо сохранённый через API, остаётся читаемым той же ролью
через историю.

Дополнительно: конфиг — произвольный YAML без схемы
(`instances: {id: {ключ: значение, ...}}`, см. любой `*.example.yml`).
Определить "это поле — секрет" эвристикой по имени ключа (`password`,
`token`, ...) ненадёжно — ложные срабатывания/промахи на нестандартных
именах, и такое решение не документируется само по себе.

Обнаружено в ходе pre-release ревью, 2026-07-27, до первого продового
использования — исторических секретов в git нет, чистить нечего.

## [S2] Solution Overview

1. **Схема полей — не новая сущность, а расширение существующей
   AST-интроспекции.** Конструкторы коннекторов уже полностью типизированы
   (пример: `ElasticConnector.__init__(self, instance_name: str, host: str
   = "localhost", port: int = 9200, api_key: str = "", ...)`,
   `soar/connectors/elastic/elastic.py:7-17`). `orchestrator/core/
   introspect.py::parse_classes` уже парсит эти сигнатуры для `/describe`,
   но `_signature()` сейчас возвращает только имена аргументов без типов и
   дефолтов. Расширяем `_signature`/добавляем `_fields()` — извлекать
   `ast.arg.annotation` и сопоставленные `fn.args.defaults` (позиционные
   дефолты выровнены с хвостом списка аргументов).
2. **Явная пометка hidden-полей** — новый class-level атрибут на каждом
   коннекторе:
   ```python
   class ElasticConnector(BaseConnector):
       HIDDEN_FIELDS: ClassVar[set[str]] = {"password", "api_key"}
   ```
   Читается тем же AST-парсером (`ast.Assign` в теле класса, значение —
   `Set`/литерал строк) — без импорта, тот же принцип, что весь
   `introspect.py`. Явная декларация, не эвристика: точна, ревьюится один
   раз на коннектор, не гадает по имени.
3. **Новая read-only ручка** `GET /connectors/{name}/schema` — отдаёт
   `[{name, type, default, hidden}, ...]` по активному инстансу коннектора.
   На `_RO` — сама схема не содержит значений, не секрет.
4. **Редакция на уровне API-ответа**, не отдельный файл вне git:
   `GET /config`, `/config/history`, `/config/history/{commit}` парсят
   YAML, заменяют значения hidden-полей на `"********"` перед отдачей —
   всем ролям, включая `admin` (write-only секреты: задать можно, прочитать
   обратно через API нельзя, ни одной ролью). `/config/diff` — построчная
   редакция: строка вида `key: value` в diff-выводе, если `key` — hidden,
   значение в `+`/`-` строке заменяется на `********` (факт изменения виден,
   значения — нет).
5. **`PUT /config` — merge-on-write + разделение прав по полю, не по
   ручке:**
   - Если новое значение hidden-поля равно плейсхолдеру `"********"` —
     сохраняем текущее значение с диска (не перезаписываем).
   - Если новое значение hidden-поля отличается от плейсхолдера и от
     текущего — это попытка задать секрет: требует роль `admin` буквально
     (`require_role("admin")`, не `require_role(*_ADMIN)` — тот же паттерн,
     что уже используется для `/auth/users`, `/auth/keys`, `/audit-log`,
     `/transfer/*`, `PUT /prompts/user`, см. `AGENTS.md`). Запрос от
     `agent` с изменённым hidden-полем — `403`.
   - Не-hidden поля правит `agent` как сейчас, через существующий
     `require_role(*_ADMIN)` (`_ADMIN = ("admin", "agent")`).
6. **Хранение не меняется** — один файл `{name}.yml`, одна git-история,
   без sidecar-файлов и без правок `_ensure_connected()`/загрузчика
   коннектора. Секреты по-прежнему физически лежат в git — но никогда не
   возвращаются через API никому, включая `admin`, что делает их
   присутствие в git безопасным (эквивалентно шифрованному хранилищу с
   точки зрения API-поверхности, которая — единственный доступный
   пользователям путь в этой системе).

## [S3] Architecture

```
orchestrator/
├── core/
│   └── introspect.py            # MODIFY: _fields() — type+default extraction,
│                                 #         parse HIDDEN_FIELDS class attribute
└── api/
    └── connectors.py             # MODIFY: GET /schema (NEW), редакция в
                                   #         GET config/history/history+diff,
                                   #         merge-on-write + role split в PUT config

soar/
└── connectors/
    ├── elastic/elastic.py        # MODIFY: + HIDDEN_FIELDS
    ├── ssh/ssh.py                 # MODIFY: + HIDDEN_FIELDS
    ├── active_directory/*.py      # MODIFY: + HIDDEN_FIELDS
    └── ... (все 23 коннектора)    # MODIFY: + HIDDEN_FIELDS

ui/src/views/
└── Connectors.vue                 # MODIFY: schema-driven форма вместо textarea (см. S7)

tests/orchestrator/
├── test_introspect.py             # MODIFY: тест _fields()/HIDDEN_FIELDS парсинга
└── api/test_connectors.py         # MODIFY: редакция/merge/RBAC-тесты
```

## [S4] Schema Extraction (`introspect.py`)

```python
def _fields(fn: ast.FunctionDef) -> list[dict]:
    args = [a for a in fn.args.args if a.arg != "self"]
    defaults = fn.args.defaults
    pad = len(args) - len(defaults)
    out = []
    for i, a in enumerate(args):
        default = None
        if i >= pad:
            d = defaults[i - pad]
            default = ast.literal_eval(d) if isinstance(d, ast.Constant) else None
        out.append({
            "name": a.arg,
            "type": ast.unparse(a.annotation) if a.annotation else "str",
            "default": default,
        })
    return out

def _hidden_fields(node: ast.ClassDef) -> set[str]:
    for item in node.body:
        if (isinstance(item, ast.AnnAssign) or isinstance(item, ast.Assign)) \
                and _target_name(item) == "HIDDEN_FIELDS":
            value = item.value
            if isinstance(value, (ast.Set, ast.List)):
                return {el.value for el in value.elts if isinstance(el, ast.Constant)}
    return set()
```

`parse_classes()` включает `"fields": _fields(init)` и
`"hidden_fields": _hidden_fields(node)` в возвращаемый dict наряду с уже
существующими `constructor`/`methods` — без изменения формата,
существующие потребители (`/describe`) не ломаются.

## [S5] API: `GET /connectors/{name}/schema`

```python
@router.get("/{name}/schema", dependencies=[Depends(require_role(*_RO))])
async def get_connector_schema(name: str, request: Request):
    validate_name(name)
    classes = parse_classes(_connector_module_path(name))  # существующий helper
    cls = next((c for c in classes if not c["name"].startswith("Base")), classes[0])
    hidden = cls["hidden_fields"]
    return {"fields": [
        {**f, "hidden": f["name"] in hidden} for f in cls["fields"]
    ]}
```

## [S6] Редакция и merge-on-write в существующих ручках

Общая функция (модуль `connectors.py`, рядом с существующими helper'ами):

```python
_MASK = "********"

def _redact(name: str, content: str) -> str:
    hidden = _hidden_fields_for(name)  # переиспользует parse_classes
    if not hidden:
        return content
    data = pyyaml.safe_load(content) or {}
    for instance in data.get("instances", {}).values():
        for key in hidden:
            if key in instance:
                instance[key] = _MASK
    return pyyaml.safe_dump(data, sort_keys=False)
```

- `GET /config` → `return {"name": name, "content": _redact(name, content)}`.
- `GET /config/history/{commit}` → та же редакция на `history.get_version(...)`.
- `GET /config/diff` → редакция построчно на результате `history.diff_versions`:
  для строк, начинающихся `+`/`-` и матчащих `^\s*(\w+):\s`, если группа 1 —
  hidden-ключ, заменить хвост строки после `:` на `_MASK`.
- `PUT /config`: перед записью — распарсить старый (если есть) и новый YAML,
  для каждого hidden-поля: если новое значение == `_MASK` → взять старое
  значение из старого файла; иначе если новое значение != старому → require
  `admin` буквально (проверка роли **внутри** обработчика, не в
  `dependencies=[...]`, т.к. решение зависит от содержимого запроса — роут
  остаётся на `require_role(*_ADMIN)` в декораторе для не-secret веток, но
  добавляет ручную проверку `if user.role != "admin": raise HTTPException(403)`
  при обнаружении реального изменения hidden-поля).

## [S7] Stage UI Implementation (`ui/src/views/Connectors.vue`)

Текущее состояние: `configMode` рендерит один `<textarea>` (строки 60-75),
привязанный к `configContent`, сохраняющий сырой текст через
`saveConfig()` → `api.saveConnectorConfig(name, content)`
(`Connectors.vue:145-156`). Полностью заменяется на форму, управляемую
схемой:

1. `editConfig(name)` дополнительно вызывает новый `api.getConnectorSchema(name)`
   параллельно с `api.getConnectorConfig(name)`, результат — `schemaFields`.
2. Форма строится по `schemaFields`, не по textarea:
   - обычное поле (`hidden: false`) — `<input>` с типом по `type`
     (`str`→text, `int`/`float`→number, `bool`→checkbox), `v-model` на
     локальный объект `instanceValues[fieldName]`.
   - hidden-поле — `<input type="password">`, **всегда пустой при
     открытии формы** (не предзаполняется `********`, чтобы не путать
     "маска" с "реальное значение" визуально), с плейсхолдером `"оставьте
     пустым, чтобы не менять"`. При сборке payload на save: если поле
     осталось пустым — не включать в объект вообще (бэкенд трактует
     отсутствие ключа как "не менялось", эквивалентно `_MASK`); если
     заполнено — отправить как есть.
   - hidden-поля рендерятся, но `disabled` для не-`admin` (`auth.role !==
     'admin'`) — клиентская подсказка, не граница безопасности (граница —
     `[S6]` на бэкенде); подпись "только admin может менять credentials".
3. `saveConfig()` сериализует `instanceValues` обратно в YAML
   (`instances: {<instance_id>: {...}}`) и шлёт как раньше через
   `api.saveConnectorConfig` — формат тела ручки не меняется, меняется
   только то, что строит его форма, а не пользователь руками.
4. Fallback: если `GET /schema` вернул пустой список полей (нестандартный/
   generated-коннектор без типизированного `__init__`) — показать прежний
   raw-textarea как деградацию, не блокировать редактирование.
5. `api.js` — добавить `getConnectorSchema(name)` (`GET
   /connectors/{name}/schema`), без изменений в `getConnectorConfig`/
   `saveConnectorConfig`.

## [S8] Все существующие коннекторы получают `HIDDEN_FIELDS`

Явный список (по `*.example.yml`, один атрибут на файл, без изменения
поведения конструктора):

| Коннектор | `HIDDEN_FIELDS` |
|---|---|
| elastic | `password`, `api_key` |
| ssh | `password` |
| active_directory | `bind_password` |
| freeipa | `bind_password` |
| security_onion | `password`, `api_key` |
| wazuh | `password` |
| postgresql / mysql / mssql | `password` |
| virus_total | `api_key` |
| abusech | `api_key` |
| smtp | `password` |
| telegram | `bot_token` |
| winrm | `password` |
| smb_rpc | `password` |
| shodan / fofa / censys | `api_key` (censys дополнительно `api_secret`) |
| misp | `api_key` |
| rstcloud | `api_key` |
| kaspersky_opentip | `api_key` |
| urlhaus / crtsh | — (публичные API, без credentials) |
| file | — (без credentials) |

Точный список полей на коннектор верифицируется по текущей сигнатуре
`__init__` на этапе плана — таблица выше по `*.example.yml`, не финальный
источник истины.

## [S9] Testing Strategy

- `introspect.py`: unit-тест `_fields()` на сигнатуре с разными типами/
  дефолтами (`str`, `int`, `bool`, без дефолта); тест `_hidden_fields()`
  на классе с `HIDDEN_FIELDS` и без.
- `GET /connectors/{name}/schema`: тест на реальном коннекторе (elastic),
  проверка `hidden: true` на `password`/`api_key`.
- `GET /config`: тест что `viewer` получает `********` вместо реального
  значения; `admin` — тоже `********` (write-only для всех).
- `GET /config/history`, `/config/diff`: тест что старое значение из
  прошлого коммита тоже маскируется.
- `PUT /config`: тест merge-on-write (плейсхолдер не затирает старое
  значение); тест что `agent` получает `403` при попытке изменить
  hidden-поле на реальное значение; тест что `admin` может изменить
  hidden-поле; тест что оба могут менять не-hidden поля.
- Regression: все существующие тесты `test_connectors.py` проходят без
  изменений (формат хранения не менялся).

## [S10] Success Criteria

- [ ] `GET /connectors/{name}/schema` отдаёт типизированные поля с
      `hidden: bool`, выведенным из `HIDDEN_FIELDS`, без импорта модуля
      коннектора
- [ ] `GET /config`, `/config/history[/{commit}]` никогда не возвращают
      реальное значение hidden-поля ни одной роли, включая `admin`
- [ ] `/config/diff` показывает факт изменения hidden-поля, не значения
- [ ] `PUT /config` отклоняет попытку `agent` изменить hidden-поле (`403`),
      разрешает `admin`; не-hidden поля пишут обе роли как раньше
- [ ] Merge-on-write не затирает существующий секрет при сохранении формы
      с пустым hidden-полем
- [ ] Все 23 коннектора получили `HIDDEN_FIELDS`, ни один существующий
      тест коннектора не сломан
- [ ] `ui/src/views/Connectors.vue` — форма по схеме вместо raw-textarea
      для конфига, hidden-поля видимы только как password-input с
      `disabled` для не-admin, значения никогда не предзаполняются
- [ ] Fallback на raw-textarea для коннекторов без схемы работает
