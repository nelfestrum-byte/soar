# New Connectors Get `HIDDEN_FIELDS` by Default (S8)

> Реализует S8 из `docs/concepts/BAGFIX_PLAN.md`. P13
> (`docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`)
> редактирует секреты только там, где `HIDDEN_FIELDS` явно объявлен; все
> 24 встроенных коннектора его получили, но оба пути создания **нового**
> коннектора — ручной шаблон и OpenAPI-генератор — оставляют его пустым.
> Именно этими путями коннекторы и будут появляться в проде дальше.

## [S1] Problem

`CONNECTOR_TEMPLATE` (`orchestrator/api/connectors.py:50-64`),
используемый `POST /connectors/{name}` (`create_connector`,
`connectors.py:664-710`) и отдаваемый `GET /connectors/template`
(`connectors.py:223-230`) для ручного создания:

```python
CONNECTOR_TEMPLATE = '''from soar.connectors.base import BaseConnector


class {class_name}(BaseConnector):
    def __init__(self, instance_name: str, **kwargs):
        super().__init__(instance_name)
        # TODO: add parameters

    def _connect_impl(self):
        # TODO: implement connection
        self._connected = True

    def disconnect(self):
        self._connected = False
'''
```

Нет строки `HIDDEN_FIELDS`. `_hidden_fields_for()`
(`connectors.py:91-103`) на классе без этого атрибута возвращает пустое
множество — редакция (`_redact_yaml`/`_redact_diff`) молча становится
no-op для любого нового коннектора, пока кто-то не допишет
`HIDDEN_FIELDS` руками при первой реальной правке `_connect_impl`. P13
модель — opt-in с дефолтом "не редактировать" (см.
`connector-secrets-schema-design.md` [S2].2: "Явная пометка
hidden-полей ... не эвристика"), а не opt-out — это осознанное свойство
самого механизма (явная декларация лучше угадывания по имени поля), но
дефолт **шаблона**, который получает каждый новый коннектор, должен
делать эту декларацию частью самого акта создания, не полагаться на то,
что автор коннектора вспомнит добавить её отдельно.

`OpenAPIGenerator._generate_class()` (`soar/tools/openapi.py:150-201`) —
генерирует класс из OpenAPI-спеки, включая `_extract_security()`
(`openapi.py:80-107`), которая уже парсит `securitySchemes` и добавляет
поля аутентификации в `__init__`/`self.<field> = <field>` (`api_key`,
`token`, `username`/`password`) — но нигде не добавляет
`HIDDEN_FIELDS` в тело генерируемого класса. Тот же класс дыры, что и в
ручном шаблоне: коннектор, сгенерированный из спеки с `apiKey`/`bearer`/
`basic` авторизацией, получает реальный секрет в конструкторе и в
`.example.yml` (`_generate_config`, `openapi.py:227-248` — уже кладёт
`YOUR_API_KEY`/`YOUR_BEARER_TOKEN`/`YOUR_PASSWORD` в пример), но не
объявляет, какое из этих полей — секрет, для целей редакции реальной
конфигурации после того, как placeholder заменён на настоящее значение.

## [S2] Solution

### [S2.1] `CONNECTOR_TEMPLATE` — пустой, но объявленный `HIDDEN_FIELDS`

```python
CONNECTOR_TEMPLATE = '''from typing import ClassVar

from soar.connectors.base import BaseConnector


class {class_name}(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = set()

    def __init__(self, instance_name: str, **kwargs):
        super().__init__(instance_name)
        # TODO: add parameters

    def _connect_impl(self):
        # TODO: implement connection
        self._connected = True

    def disconnect(self):
        self._connected = False
'''
```

Пустое множество — не регрессия текущего поведения (шаблон и сегодня не
знает заранее, какие поля появятся в `__init__`, который автор допишет
сам), но **присутствие строки** — тот сигнал, которого не хватает:
разработчик, добавляющий `password: str` в конструктор шаблонного
коннектора, видит `HIDDEN_FIELDS: ClassVar[set[str]] = set()` прямо над
собой и с большей вероятностью впишет туда `"password"`, чем вспомнит
добавить весь атрибут с нуля. Это осознанно эргономический, не
технический фикс для ручного пути — технической гарантии (что автор
обязательно заполнит множество) шаблон дать не может, только явная
декларация P13 и так не эвристика.

### [S2.2] `OpenAPIGenerator` — заполнить `HIDDEN_FIELDS` из `securitySchemes` автоматически

Здесь фикс — не только эргономический, а технический: генератор уже
знает точные имена auth-полей (`_extract_security()` их вычисляет для
`__init__`), значит может проставить `HIDDEN_FIELDS` без участия
человека. Собрать множество имён параллельно уже существующему циклу в
`_extract_security()` (`openapi.py:86-104`):

```python
def _extract_security(self) -> dict:
    result = {"params": "", "fields": "", "header_setup": "", "config_lines": [], "hidden_fields": set()}
    if not self.security_schemes:
        return result

    for name, scheme in self.security_schemes.items():
        if scheme.get("type") == "apiKey":
            param_name = scheme.get("name", "api_key")
            result["params"] += f"{param_name}: str = \"\",\n        "
            result["fields"] += f"self.{param_name} = {param_name}\n        "
            result["hidden_fields"].add(param_name)
            if scheme.get("in", "header") == "header":
                result["header_setup"] += f'headers["{param_name}"] = self.{param_name}\n        '

        elif scheme.get("type") == "http":
            if scheme.get("scheme") == "bearer":
                result["params"] += "token: str = \"\",\n        "
                result["fields"] += "self.token = token\n        "
                result["hidden_fields"].add("token")
                result['header_setup'] += 'headers["Authorization"] = f"Bearer {self.token}"\n        '
            elif scheme.get("scheme") == "basic":
                result["params"] += 'username: str = "",\n        password: str = "",\n        '
                result["fields"] += "self.username = username\n        self.password = password\n        "
                result["hidden_fields"].add("password")  # username — не секрет, не маскируется
                result["header_setup"] += "auth = httpx.BasicAuth(self.username, self.password)\n        "

        elif scheme.get("type") == "oauth2":
            result["config_lines"].append(f"# WARNING: OAuth2 scheme '{name}' requires manual implementation")

    return result
```

(`username` в `basic`-схеме намеренно **не** попадает в
`hidden_fields` — совпадает с конвенцией всех существующих коннекторов
с basic-подобной аутентификацией, например `elastic_basic` в
`elastic.example.yml`, где `username` виден в примере открытым текстом,
скрыт только `password`.)

`_generate_class()` (`openapi.py:150`) добавляет `ClassVar`-декларацию в
сгенерированный класс, используя `sec["hidden_fields"]`:

```python
def _generate_class(self, name: str) -> str:
    ...
    sec = self._extract_security()
    hidden_repr = "{" + ", ".join(f'"{f}"' for f in sorted(sec["hidden_fields"])) + "}" if sec["hidden_fields"] else "set()"
    return f'''"""Auto-generated from OpenAPI spec: {title}"""
from __future__ import annotations
from typing import ClassVar
import httpx
from soar.connectors.base import BaseConnector


class {class_name}(BaseConnector):
    """Connector for {title}"""

    HIDDEN_FIELDS: ClassVar[set[str]] = {hidden_repr}

    def __init__(
        ...
'''
```

`oauth2`-схема — не добавляет полей в `__init__` сегодня (только
`config_lines`-предупреждение, требует ручной реализации по докстрингу
`connector-secrets-schema-design.md` [S2].2, warning уже существует в
`generate_connector`'s `warnings` в API-ответе) — не участвует в
`hidden_fields` этим фиксом, потому что генератор не создаёт для неё
никакого поля, которое можно было бы скрыть; если автор дописывает
OAuth2-реализацию руками, он же дописывает и `HIDDEN_FIELDS` руками —
тот же путь, что [S2.1] для ручного шаблона.

## [S3] Testing Strategy

`tests/orchestrator/api/test_connectors.py`:

- **Новый** `test_create_connector_template_has_hidden_fields` —
  `POST /connectors/{name}` (или `GET /connectors/template`), проверить,
  что сгенерированный код содержит строку
  `HIDDEN_FIELDS: ClassVar[set[str]] = set()`.

`tests/soar/tools/test_openapi.py`:

- **Новый** `test_generate_class_hidden_fields_api_key` — спека с
  `apiKey`-схемой (`SPEC_API_KEY_HEADER`, уже есть в тестовом наборе
  файла) → сгенерированный код содержит
  `HIDDEN_FIELDS: ClassVar[set[str]] = {"X-API-Key"}` (или как называется
  параметр в конкретной тестовой спеке).
- **Новый** `test_generate_class_hidden_fields_bearer` — bearer-схема →
  `{"token"}`.
- **Новый** `test_generate_class_hidden_fields_basic` — basic-схема →
  `{"password"}`, явно **не** содержит `"username"`.
- **Новый** `test_generate_class_no_security_empty_hidden_fields` —
  спека без `securitySchemes` → `set()`.
- **Regression**: `test_generate_creates_files`,
  `test_generate_config`/`test_generate_config_with_auth` (после фикса
  S7, см. `docs/compose/specs/2026-07-28-test-suite-green-design.md`) —
  не ломаются добавлением `HIDDEN_FIELDS` в генерируемый `.py`
  (`.example.yml`, который эти тесты проверяют, не меняется этим
  треком — `_generate_config` и так уже кладёт секреты в пример
  открытым текстом как плейсхолдер `YOUR_*`, это не редактируемый через
  API артефакт, а шаблон для ручного заполнения, редакция к нему не
  применяется по определению P13, только к реальному `{name}.yml`).
- Сквозной тест: `POST /connectors/generate` с `apiKey`-спекой →
  созданный коннектор → `GET /connectors/{name}/schema` (существующая
  ручка P13) отдаёт `hidden: true` для поля из `securitySchemes` без
  ручной правки кода после генерации.

## [S4] Success Criteria

- [ ] `CONNECTOR_TEMPLATE` объявляет `HIDDEN_FIELDS: ClassVar[set[str]] =
      set()` — присутствует в любом созданном вручную коннекторе с
      первого коммита
- [ ] `OpenAPIGenerator` автоматически заполняет `HIDDEN_FIELDS` именами
      auth-полей из `apiKey`/`bearer`/`basic`-схем `securitySchemes`,
      без участия человека
- [ ] `username` в `basic`-схеме не попадает в `HIDDEN_FIELDS` —
      согласовано с конвенцией существующих коннекторов
- [ ] `GET /connectors/{name}/schema` для сгенерированного коннектора
      сразу отдаёт корректный `hidden: bool` без ручной правки кода
- [ ] Существующие тесты `test_openapi.py`/`test_connectors.py` не
      регрессируют
