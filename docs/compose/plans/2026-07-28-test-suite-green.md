# Plan: Green Test Suite — `_generate_config` instance key + optional-dependency guards (S7)

Спека: `docs/compose/specs/2026-07-28-test-suite-green-design.md`

## Tests first

- [x] Запустить `python -m pytest tests/soar/tools/test_openapi.py -v` на
      текущем коде — подтвердить, что `test_generate_config` падает
      (`MyApiConnector1:` вместо `my_api:`), а `test_generate_config_with_auth`
      и `test_generate_creates_files` уже проходят (тело этих тестов не
      меняется).
- [x] Прочитать импорты 5 тестовых файлов коннекторов
      (`test_misp_connector.py`, `test_mysql_connector.py`,
      `test_shodan_connector.py`, `test_winrm_connector.py`,
      `test_smb_rpc_connector.py`) и соответствующих модулей коннекторов —
      подтвердить точные имена сторонних пакетов (`pymisp`, `pymysql`,
      `shodan`, `winrm`/`smbprotocol`) перед правкой.

## Implementation

- [x] `soar/tools/openapi.py::_generate_config` — заменить
      `class_name = "".join(...) + "Connector"` / `instance_name =
      f"{class_name}1"` на прямое использование `name` как ключа инстанса
      (`f"  {name}:"`), убрать неиспользуемую переменную `class_name` в
      этой функции (она не нужна нигде дальше по телу `_generate_config`).
- [x] Добавить `pytest.importorskip("pymisp")` в начало
      `tests/soar/test_misp_connector.py` (до импорта `MISPConnector`).
- [x] Добавить `pytest.importorskip("pymysql")` в начало
      `tests/soar/test_mysql_connector.py`.
- [x] Добавить `pytest.importorskip("shodan")` в начало
      `tests/soar/test_shodan_connector.py`.
- [x] Добавить `pytest.importorskip("winrm")` в начало
      `tests/soar/test_winrm_connector.py`.
- [x] Добавить `pytest.importorskip("smbprotocol")` в начало
      `tests/soar/test_smb_rpc_connector.py` (не `"impacket"`).
- [x] (Обнаружено при полном прогоне, не было в исходном плане)
      `tests/orchestrator/api/test_connectors_api.py::test_generated_connector_config`
      явно проверял старую конвенцию (`GenConfigTestConnector1:`) —
      обновлена одна строка assert на `gen_config_test:`, синхронно с
      [S2.1]; без этого правки `_generate_config` полный suite не был бы
      зелёным.

## Verification

- [x] `python -m pytest tests/soar/tools/test_openapi.py
      tests/soar/test_misp_connector.py tests/soar/test_mysql_connector.py
      tests/soar/test_shodan_connector.py tests/soar/test_winrm_connector.py
      tests/soar/test_smb_rpc_connector.py -v` — все зелёные (пакеты
      установлены в этом окружении, значит модули не скипаются, а реально
      прогоняются). 64 passed.
- [x] Полный `python -m pytest tests/ -q` — `687 passed, 1 skipped`,
      `0 failed`.

## Report

- [x] Написать `docs/compose/reports/test-suite-green.md` после завершения.
