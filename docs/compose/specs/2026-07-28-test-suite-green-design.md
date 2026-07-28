# Green Test Suite: Fix `test_generate_config` + Guard Optional-Dependency Modules (S7)

> Реализует S7 из `docs/concepts/BAGFIX_PLAN.md`. `main` — красный
> (`1 failed, 648 passed, 1 skipped` на момент ревью; на момент написания
> этой спеки — `1 failed, 686 passed, 1 skipped`, тот же единственный
> провал). Дополнительно — 5 тестовых модулей коннекторов не собираются
> в окружении без опциональных зависимостей.

## [S1] Problem

### [S1.1] `test_generate_config` — код и тест расходятся в имени инстанса

`tests/soar/tools/test_openapi.py::test_generate_config`:

```python
def test_generate_config():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    config = gen._generate_config("my_api")
    assert "instances:" in config
    assert "my_api:" in config
```

`OpenAPIGenerator._generate_config()` (`soar/tools/openapi.py:227-232`):

```python
def _generate_config(self, name: str) -> str:
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Connector"
    instance_name = f"{class_name}1"
    lines = ["instances:", f"  {instance_name}:"]
    ...
```

Для `name="my_api"` генерируется `MyApiConnector1:` — тест ждёт
`my_api:`. Ни один из существующих сгенерированных/сгенерированных
вручную коннекторов не следует конвенции `<ClassName>N` для ключа
инстанса — везде используется snake_case имя, произвольно описывающее
конкретный инстанс, обычно с префиксом самого имени коннектора
(`elastic_main`, `elastic_basic` в `soar/connectors/elastic/
elastic.example.yml`), либо просто `{name}` для template'а нового
коннектора (`CONFIG_TEMPLATE` в `orchestrator/api/connectors.py:66-69`:
`instances:\n  {name}:\n`). `MyApiConnector1` — единственное место в
кодовой базе, где ключ инстанса образуется из имени **класса**, а не
имени **коннектора** (`name`, snake_case, тот же аргумент, что везде
служит ключом реестра/директории/файла).

Это расхождение — не тестовая опечатка, а реальный дрейф конвенции:
сгенерированный `.example.yml` выглядит непохожим на все остальные
example-файлы в проекте, что усложняет ручное сопоставление
"инстанс → коннектор" при копировании из example в реальный
`{name}.yml`.

### [S1.2] 5 тестовых модулей падают на импорте без опциональных зависимостей

Проверено (`ToolSearch`/чтение исходников на этапе этой спеки):
`misp.py` (`import pymisp`), `mysql.py` (`import pymysql`),
`shodan.py` (`import shodan`), `winrm.py` (`import winrm`, pip-имя
`pywinrm`) — top-level импорты стороннего пакета. `smb_rpc.py`
использует `smbprotocol` (`from smbprotocol.connection import
Connection`, ...), не `impacket` — обзор ревью 2026-07-27 назвал пятый
пакет `impacket` неточно; фактическая зависимость этого модуля —
`smbprotocol`. Соответствующие тестовые файлы
(`tests/soar/test_misp_connector.py`, `test_mysql_connector.py`,
`test_shodan_connector.py`, `test_winrm_connector.py`,
`test_smb_rpc_connector.py`) делают `from soar.connectors.<x>.<x> import
<X>Connector` на верхнем уровне — если соответствующий сторонний пакет
не установлен, **сбор** тестового модуля (не отдельный тест) падает
`ImportError`/`ModuleNotFoundError` до того, как pytest успевает
что-либо собрать из файла — pytest репортит это как ошибку коллекции
(`errors`), не как `failed`/`skipped` отдельного теста. Ни один из этих
пяти пакетов не объявлен в `pyproject.toml` вообще (полностью
опциональны, не "забыты в manifest") — воспроизводится в любом окружении
без ручной установки всех пяти вручную (в окружении, где писалась эта
спека, все пять оказались установлены — испытание проведено чтением
исходников и `pyproject.toml`, не прогоном с намеренно урезанным venv;
зафиксировать точный воспроизводящий venv на этапе плана).

## [S2] Solution

### [S2.1] Выбор целевого имени инстанса — `name`, не `f"{class_name}N"`

Синхронизировать код с тестом и с конвенцией остального проекта:
инстанс-ключ — сам `name` (snake_case, тот же аргумент функции), без
суффикса и без превращения в class-case:

```python
def _generate_config(self, name: str) -> str:
    lines = ["instances:", f"  {name}:"]
    ...
```

(`class_name` в этой функции остаётся нужен только для случаев, где он
уже используется — на самом деле в текущем теле `_generate_config` он
вычисляется, но не используется больше нигде после построения
`instance_name` — убрать неиспользуемую переменную заодно, раз она
существовала только ради старого `instance_name`.) Выбор `name` вместо,
например, `f"{name}_1"` — потому что тест ожидает точное совпадение
`"my_api:"` (не `"my_api_1:"`), и потому что `CONFIG_TEMPLATE` для
ручного создания коннектора (`connectors.py:66-69`) уже использует
голый `{name}` без суффикса — сгенерированный из OpenAPI-спеки коннектор
получает тот же формат, что и созданный вручную, единообразно.

### [S2.2] `skipif`/`importorskip` на 5 модулях коннекторов

`pytest.importorskip(...)` в начале каждого файла — импортирует пакет
и **скипает весь модуль** (не падает ошибкой коллекции), если пакет не
установлен:

```python
# tests/soar/test_misp_connector.py
import pytest

pytest.importorskip("pymisp")

from unittest.mock import MagicMock, patch
from soar.connectors.misp.misp import MISPConnector
...
```

Аналогично: `pytest.importorskip("pymysql")` в `test_mysql_connector.py`,
`pytest.importorskip("shodan")` в `test_shodan_connector.py`,
`pytest.importorskip("winrm")` в `test_winrm_connector.py`,
`pytest.importorskip("smbprotocol")` в `test_smb_rpc_connector.py`
(не `"impacket"` — исправляя неточность самого ревью, см. [S1.2]).

Результат: в окружении без соответствующего пакета — `1 skipped` на
модуль вместо ошибки коллекции; в окружении, где пакет установлен
(как в dev/CI сегодня) — поведение не меняется вообще, все тесты
собираются и идут как раньше. Не требует изменений `pyproject.toml`
(эти зависимости остаются недекларированными опциональными — фиксация
как "требование dev-окружения" per план означает: пакет нужен, **если**
хочешь эти тесты реально прогнать не-skipped, не что пакет обязателен
для `pip install` пакета целиком).

Отдельно, на этапе плана — решить, стоит ли завести
`pyproject.toml`-секцию опциональных extras (`[project.optional-
dependencies]`, `dev-connectors = ["pymisp", "pymysql", "shodan",
"pywinrm", "smbprotocol"]`) — упростило бы CI-конфигурацию (`pip install
.[dev-connectors]` вместо перечисления вручную), но это расширение
scope за пределы "тесты не падают на коллекции"; сам S7 не требует
такой секции, `importorskip` работает и без неё.

## [S3] Testing Strategy

- `test_generate_config`/`test_generate_config_with_auth` — прогнать
  после [S2.1], оба зелёные без изменения тела теста (только код
  генератора меняется).
- `test_generate_creates_files` (`soar/tools/test_openapi.py:260-268`) —
  regression-проверка: генерация по-прежнему создаёт 3 файла, содержимое
  `.py`/`__init__.py` не завязано на изменённую строку, не должно
  сломаться побочно.
- Верификация [S2.2] — прогнать `python -m pytest tests/soar/ -v` дважды:
  один раз в окружении со всеми пятью пакетами (текущее — все тесты
  идут, не скипаются), один раз в venv, где все пять намеренно
  деинсталлированы (`pip uninstall pymisp pymysql shodan pywinrm
  smbprotocol -y`) — все 5 файлов дают `skipped`, не `error`, весь
  остальной suite не затронут.
- Финальная проверка: `python -m pytest tests/ -v` → `0 failed`, без
  errors коллекции, в любом из двух окружений (с полным набором
  опциональных пакетов или без него).

## [S4] Success Criteria

- [ ] `test_generate_config`/`test_generate_config_with_auth` проходят
      без изменения тела теста
- [ ] Сгенерированный `.example.yml` использует `{name}:` как ключ
      инстанса, единообразно с `CONFIG_TEMPLATE` для коннекторов,
      создаваемых вручную
- [ ] `tests/soar/test_misp_connector.py`, `test_mysql_connector.py`,
      `test_shodan_connector.py`, `test_winrm_connector.py`,
      `test_smb_rpc_connector.py` скипаются (не падают ошибкой
      коллекции), если соответствующий опциональный пакет не установлен
- [ ] `python -m pytest tests/` — `0 failed` на `main` в обоих
      окружениях (полный набор опциональных зависимостей / без них)
- [ ] Никакое существующее прохождение теста не регрессирует (весь
      остальной suite — 685+ тестов на момент этой спеки — не тронут)
