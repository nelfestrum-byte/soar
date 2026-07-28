# Plan: `PUT /connectors/{name}/code` — Literal `admin` Only (B3)

Спека: `docs/compose/specs/2026-07-28-connector-code-agent-lockdown-design.md`

## Tests first

- [x] Добавить `test_agent_forbidden_from_connector_code_write` в
      `tests/orchestrator/api/test_connectors_api.py` — создать коннектор с
      `HIDDEN_FIELD_CONNECTOR_CODE` под `admin`, переключить override
      `get_current_user` на `_agent`, вызвать
      `PUT /connectors/{name}/code` с телом без `HIDDEN_FIELDS` (например
      `VALID_CONNECTOR_CODE`) → ожидать `403`. Подтвердить, что тест падает
      (`200`) на текущем коде (`require_role(*_ADMIN)` пропускает `agent`).
- [x] Добавить `test_admin_can_write_connector_code_after_lockdown` —
      regression: та же операция под `admin` (default override) —
      `200`, `status == "saved"`, `commit` непустой.
- [x] Убедиться, что тесты на `PUT /config`
      (`test_put_config_agent_cannot_change_hidden_field`,
      `test_put_config_admin_can_change_hidden_field`,
      `test_put_config_agent_can_change_non_hidden_field`) остаются
      зелёными без изменений — этот трек их не трогает.
- [x] Обнаружен и обновлён существующий regression-тест
      `tests/orchestrator/api/test_agent_role_rbac.py::
      test_agent_can_write_and_delete_connector_code` — кодировал старое
      поведение (`agent` пишет код коннектора → `200`). Разбит на два:
      `test_agent_can_create_and_delete_connector` (роуты `POST`/`DELETE`
      не тронуты этим треком, остаются на `_ADMIN`) и
      `test_agent_cannot_write_connector_code` (новый explicit-403,
      документирует именно этот фикс — соответствует заявленному в шапке
      файла принципу "explicit 403s on routes that intentionally did not").

## Implementation

- [x] В `orchestrator/api/connectors.py`, `save_connector_code`
      (`PUT /{name}/code`) — заменить
      `user: CurrentUser = Depends(require_role(*_ADMIN))` на
      `user: CurrentUser = Depends(require_role("admin"))`. Один литерал,
      тот же паттерн, что уже используется для `/auth/*`, `/audit-log`,
      `/transfer/*`, `PUT /prompts/user`.
- [x] Не трогать `restore_connector_code` (`POST /{name}/code/restore`) —
      остаётся на `*_ADMIN` сознательно (см. спека [S2]).
- [x] Не трогать `save_connector_config` (`PUT /{name}/config`) — уже
      корректно реализует field-level admin-check внутри обработчика, вне
      скоупа этого трека.

## Verification

- [x] `python -m pytest tests/orchestrator/api/test_connectors_api.py -v`
      — новый тест проходит, все существующие тесты в файле остаются
      зелёными (43 passed).
- [x] `python -m pytest tests/orchestrator/api/test_agent_role_rbac.py -v`
      — 70 passed после обновления regression-теста.
- [x] `python -m pytest tests/ -q` — полный набор зелёный (700 passed,
      1 skipped — pre-existing, несвязанный), без новых падений.

## Docs

- [x] `docs/agents/security-patterns.md` — дополнить абзац "Connector
      secret redaction" (описание D2): «`agent` получает `403` при попытке
      сменить credential» дополнить «и при попытке переписать код
      коннектора (`PUT /{name}/code` — admin-only литерал)».

## Report

- [x] Написать `docs/compose/reports/connector-code-agent-lockdown.md`
      после завершения.
