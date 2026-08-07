# Report: PoC-фидбек (elastic_trueconf/TrueConf) — оставшиеся фиксы

Spec: `docs/compose/specs/2026-08-07-poc-feedback-fixes-design.md`
Plan: `docs/compose/plans/2026-08-07-poc-feedback-fixes.md`

## Summary

Отчёт слепого PoC-тестирования (коннектор к Elasticsearch на инциденте
TrueConf) назвал 7 проблем. Разбор показал: №1 (egress-блок) и №2 (потеря
hidden-поля при `PUT /config`) уже были закрыты предыдущими коммитами
(`ad0dc6c`, `857ecd2`) до того, как этот фикс начался — стенд тестировался
на билде, где они ещё не были применены. №5 (нет `POST /workflows/{name}`)
и остаток №7 (review/approve-флоу) разобраны и закрыты как by-design, без
кода — см. спек [S0]. Реализованы №3, №4, №6.

Реализация шла в двух параллельных сабагентах в изолированных worktree —
один на №3 (`soar/runner.py`), другой на №4+№6 (`orchestrator/api/*.py`).
Оба worktree были созданы от коммита на 2 позиции раньше текущего `HEAD`
(не хватало `857ecd2` и `ad0dc6c`); агент на №4+№6 сам обнаружил это и
синхронизировал незатронутые своей задачей файлы через path-scoped `git
checkout <branch> -- <paths>` (`merge`/`reset`/`stash` были заблокированы
песочницей). Агент на №3 (`soar/runner.py`, единственный файл, тронутый и
`ad0dc6c`) этого не сделал — реализовал фикс поверх устаревшей версии файла
без egress-политики. Результат обеих веток вручную сверен и перенесён на
`HEAD` этой сессией: файлы, не пересекавшиеся с `ad0dc6c`/`857ecd2`,
скопированы как есть; `soar/runner.py` слит вручную (egress-логика из
`ad0dc6c` + `_bootstrap()`/`try-except`-реструктуризация из фикса №3).

## Changes

### №3 — bootstrap-traceback (`soar/runner.py`)

`tools.http_client = _build_http_client(config)` + `connectors.init()` +
`actions.init()` + `workflows.init()` вынесены в `_bootstrap()`. Под `if
__name__ == "__main__":` (тот же гейт, что и у `install_audit_hook()`) вызов
обёрнут в `try/except Exception`, печатающий тот же JSON-контракт, что и
`main()` (`success: False`, `workflow_name` из `SOAR_WORKFLOW_NAME`,
`error: traceback.format_exc()`), затем `flush_audit_hook()` и `sys.exit(1)`.
Вне `__main__` (обычный импорт, `from soar import runner` — путь тестового
сьюта) `_bootstrap()` вызывается без обёртки и по-прежнему поднимает
исключение некапчено. `import traceback` поднят на уровень модуля (был
локальным внутри `main()`).

`orchestrator/core/worker.py` не тронут — фолбэк `"Process failed"` остаётся
для путей, всё ещё не гарантирующих JSON на stdout (`SIGKILL`/timeout).

### №4 — PUT envelope guard

`orchestrator/api/validation.py::reject_json_envelope(content)` — если
`content` парсится как JSON-объект, где ключ `"content"` присутствует, а все
ключи — подмножество `{"name", "content"}`, бросает `422` вместо тихой
записи. Подключено в `connectors.py` (`save_connector_code`,
`save_connector_config`), `actions.py` и `workflows.py` (`PUT .../code`).

Находка при реализации: `actions.py`/`workflows.py` уже принимали свой
собственный JSON-конверт `{"code": ...}` (формат, которым пишет Monaco-
редактор в UI, `ui/src/api.js`) — отличный от `{"content": ...}` у `GET`/
`connectors.py`. Guard целится в ключ `"content"` конкретно, поэтому легитимный
`{"code": ...}` не задет; добавлен отдельный regression-тест на это.

`orchestrator/prompts/system_prompt.md` §2 получил явную фразу про формат
тела `PUT` (сырой текст, не JSON, не конверт `GET`).

### №6 — schema format hints

`orchestrator/api/connectors.py::_FORMAT_HINTS`/`_format_hint()` — таблица
на 3 типа (`list[str]`, `dict[str, str]`, `bool`), не парсер произвольных
типов. `GET /connectors/{name}/schema` добавляет опциональный `format_hint`
в каждое поле. Контентпак (`soar-content-pack`) не выгружен в этом воркдире
— таблица сверена только с локальными тестовыми фикстурами, ограничена
тремя типами из спека.

## Tests

- `tests/soar/test_runner.py` — 2 новых subprocess-теста (bootstrap-сбой →
  JSON traceback + exit 1; успешный запуск не затронут), 1 regression-тест
  (голый импорт по-прежнему поднимает исключение), 1 структурный тест на
  исходник (`_bootstrap()` вызван ровно дважды, обёрнутый и голый вызовы в
  правильном порядке)
- `tests/orchestrator/test_worker_execute.py` — 1 новый e2e-тест через
  реальный (не мокнутый) `SubprocessRunner` + `Worker._execute()`:
  `job.result_error` содержит настоящий traceback, не `"Process failed"`
- `tests/orchestrator/api/test_connectors_api.py` — 6 новых тестов (envelope
  reject на code/config, full-envelope reject, dict-literal regression,
  format_hint present/absent)
- `tests/orchestrator/api/test_actions_api.py`,
  `tests/orchestrator/api/test_workflows_api.py` — по 1-2 новых теста на
  envelope reject + `{"code":...}` regression каждый
- `tests/orchestrator/api/test_validation.py` — юнит-тесты на
  `reject_json_envelope` напрямую

Полный набор: `pytest -q` (без `test_redis_integration.py`) → **886 passed,
9 skipped**. Пропуски — те же, что и на `HEAD` до этого фикса (нужен живой
Redis, не связано с этими изменениями).

`ruff check` на затронутых файлах — 10 находок, все на строках, которые
этот фикс не трогал (`B904` на пред-существующих `except`-блоках в
`connectors.py`, `UP012` на пред-существующей конвенции byte-string фикстур
в тестах, которой следует и новый код). `mypy` на затронутых production-
файлах — 37 находок в 16 файлах, ни одна не в новом коде (`soar/runner.py`
даёт 3 находки на строках `_build_http_client`, скопированных без
изменений из `HEAD`; `connectors.py` — 4 находки на пред-существующих
строках, не связанных с `_FORMAT_HINTS`/`_format_hint`).

## Verification

Ручная проверка на живом стенде не выполнялась — недоступен из этой сессии.
Пункт остаётся открытым в плане.

## Deviations

- №4 применён на четырёх маршрутах, а не на едином решении сразу для двух
  разных форматов конверта (`{"content":...}` у connectors, `{"code":...}`
  у actions/workflows) — уже существовавшая асимметрия форматов между
  роутами не входила в объём этого фикса, только защита от смешения формата
  `GET`-ответа с телом `PUT`.
- №6 ограничен тремя типами из спека (контентпак недоступен локально для
  более широкой сверки) — расширение таблицы при появлении новых типовых
  паттернов в реальных коннекторах оставлено на будущее, не блокирует этот
  фикс.
