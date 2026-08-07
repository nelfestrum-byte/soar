# План: PoC-фидбек (elastic_trueconf) — оставшиеся фиксы

Спек: [`docs/compose/specs/2026-08-07-poc-feedback-fixes-design.md`](../specs/2026-08-07-poc-feedback-fixes-design.md)

Порядок test-first: сначала падающий тест, потом код. №1 и №2 из отчёта уже
закрыты (`ad0dc6c`, `857ecd2`) — здесь не трогаются. №5 и остаток №7 — без
кода, см. спек [S0].

## 1. Bootstrap-traceback (№3)

- [x] `tests/soar/test_runner.py` — падающий тест: subprocess-запуск
      `python -m soar.runner` (по образцу существующего
      `test_install_in_subprocess_blocks_private_connect` в
      `tests/soar/test_audit_hook.py`) с конфигом, где у коннектора нет
      обязательного параметра конструктора → stdout содержит ровно одну
      валидную JSON-строку с `success: false` и `error`, содержащим
      `TypeError` и полный traceback (не `"Process failed"`); returncode 1
- [x] Тест регрессии: тот же сценарий, но импорт `from soar import runner`
      в процессе pytest (не subprocess, `__name__ != "__main__"`) — исходное
      исключение по-прежнему поднимается на импорте, не перехватывается
- [x] Тест: успешный запуск (валидный конфиг) — вывод не меняется относительно
      текущего поведения
- [x] `soar/runner.py` — `_bootstrap()`, гейт `if __name__ == "__main__"` с
      `try/except` вокруг `_bootstrap()`, `import traceback` на уровень модуля
- [x] `tests/orchestrator/test_worker*.py` — тест: job, чей субпроцесс падает
      в bootstrap-фазе, даёт `job.result_error`, содержащий traceback (не
      литерал `"Process failed"`) — конец до конца через `Worker._execute()`,
      не только `soar/runner.py` изолированно
- [ ] Ручная проверка (если стенд доступен) — воспроизвести сценарий отчёта
      (`missing api_key`) и убедиться, что `GET /jobs/{id}` отдаёт полный
      traceback без похода в `GET /logs/{id}` — не выполнялась, живой стенд
      недоступен из этой сессии

## 2. PUT body envelope guard (№4)

- [x] `tests/orchestrator/api/test_connectors_api.py` — падающий: `PUT
      /connectors/{name}/code` с телом `{"content": "..."}` → `422`, detail
      объясняет разницу формата
- [x] Тест: то же для `PUT /connectors/{name}/config`
- [x] `tests/orchestrator/api/test_actions_api.py` — то же для `PUT
      /actions/{name}/code`
- [x] `tests/orchestrator/api/test_workflows_api.py` — то же для `PUT
      /workflows/{name}/code`
- [x] Тест регрессии: легитимный код, начинающийся с `{` не в форме конверта
      (например файл, где первая непустая конструкция — `{"a": 1}` как
      значение внутри функции) — записывается штатно
- [x] Тест регрессии: тело `{"name": "x", "content": "y"}` (полный конверт
      `GET`, не только `{"content": ...}`) — тоже отклоняется (ключи —
      подмножество `{"name", "content"}`)
- [x] `orchestrator/api/validation.py::reject_json_envelope`
- [x] Применить в `connectors.py` (`save_connector_code`,
      `save_connector_config`), `actions.py`, `workflows.py` — после decode,
      до записи файла. Находка при реализации: `actions.py`/`workflows.py`
      уже принимали свой собственный конверт `{"code": ...}` (используется
      UI-редактором, `ui/src/api.js`) — отличный от `{"content": ...}` у
      `GET`/`connectors.py`. Guard целится именно в ключ `"content"`, поэтому
      легитимный `{"code": ...}` не задет; регресс-тест на это добавлен
- [x] `orchestrator/prompts/system_prompt.md` §2 — фраза про raw-body формат

## 3. Schema format hints (№6)

- [x] Проверка реальных типов в конструкторах коннекторов — контентпак
      (`soar-content-pack`) не выгружен в этом воркдире, таблица подсказок
      сверена с локальными тестовыми фикстурами; покрывает `list[str]`,
      `dict[str, str]`, `bool` — три типа из спека
- [x] `tests/orchestrator/api/test_connectors_api.py` — падающий: `GET
      /connectors/{name}/schema` для коннектора с полем `list[str]` содержит
      `format_hint` с примером
- [x] Тест: поле типа `str`/`int` не содержит `format_hint` (ключ отсутствует
      или `None`)
- [x] `orchestrator/api/connectors.py` — `_FORMAT_HINTS`, `_format_hint()`,
      применить в `get_connector_schema`

## 4. Документация

- [x] `CHANGELOG.md`
- [x] `AGENTS.md` — после выполнения (раздел "Runner contract")
- [x] `docs/compose/reports/poc-feedback-fixes.md`

## 5. Проверка

- [x] `pytest` целиком зелёный — 886 passed, 9 skipped (Redis-integration
      тесты исключены — нужен живой Redis, не относится к этим фиксам)
- [x] `ruff`/`mypy` на затронутых файлах — все находки на нетронутых строках
      (пред-существующий долг, не в объёме этого фикса), см. отчёт
