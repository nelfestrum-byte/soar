# Plan: Agent Dev-Loop — Этап 3

Spec: [`docs/compose/specs/2026-07-22-agent-devloop-stage3-design.md`](../specs/2026-07-22-agent-devloop-stage3-design.md)

Зависит от Этапа 2 (merged в `main`) — новые `_RO`-ручки (`describe`,
`/prompts`) должны существовать, чтобы получить `agent` автоматически
через общие константы.

## Phase 1 — S5: аудит текущего RBAC перед правкой

- [ ] `grep -rn 'require_role(' orchestrator/` — зафиксировать (в тексте
  отчёта, не в коде) полный список мест с литералом `"admin"` напрямую
  (не через tuple-константу); сверить с [S4]-таблицей "явно не трогаем" —
  должно быть ровно 6 точек (`audit.py`, `transfer.py`,
  `auth/router.py` ×4/5 если считать все ручки). Если найдётся ещё одна —
  остановиться и разобрать отдельно перед продолжением.

## Phase 2 — S3: разрешить роль agent в валидации

- [ ] Тест в `tests/orchestrator/` (там, где уже тестируется
  `UserCreate`/`ROLES`, иначе новый `tests/orchestrator/auth/
  test_service_roles.py`) — `"agent"` проходит `UserCreate`/`UserUpdate`
  валидацию (падает — роли ещё нет в `ROLES`)
- [ ] `orchestrator/auth/service.py:12` — `ROLES = {"admin", "analyst",
  "viewer", "service", "agent"}`
- [ ] Тест: `POST /auth/users {"role": "agent"}` → `201`, `role ==
  "agent"` в ответе
- [ ] Расширить `tests/deploy/test_soarctl_users.py` — позитивный кейс
  `create(role="agent")` не поднимает `ValueError` (падает)
- [ ] `deploy/soarctl_lib/users.py:13` — `_ROLES = ("admin", "analyst",
  "viewer", "service", "agent")`
- [ ] `orchestrator/auth/cli.py:70` — добавить `"agent"` в `choices=[...]`
  на `--role`
- [ ] `python -m pytest tests/orchestrator/ -k role
  tests/deploy/test_soarctl_users.py -v`

## Phase 3 — S4: расширить tuple-константы кода и jobs

- [ ] Расширить тесты (по одному параметризованному случаю на файл, или
  добавить в существующие `test_actions_api.py`/`test_connectors_api.py`/
  `test_workflows_api.py`/`test_jobs_api.py`/`test_logs_api.py`/
  `test_tools_api.py`/`test_prompts_api.py`) — пользователь с ролью
  `agent` получает `200`/`202` на все ручки из колонки "Стало" таблицы
  [S4]: `PUT`/`DELETE`/`restore` actions/connectors/workflows,
  `POST /jobs`, `POST /jobs/{id}/cancel`, `GET /logs/{job_id}`,
  все `_RO`-ручки включая `describe`/`/prompts/system`/`/prompts/user`
  (GET); `403` на `PUT /prompts/user` для agent (падает — роли пока нет
  в tuple-ах)
- [ ] `orchestrator/api/actions.py:20-21` — `_RO`, `_ADMIN` — добавить
  `"agent"`
- [ ] `orchestrator/api/connectors.py:28-30` — `_RO`, `_RW`, `_ADMIN` —
  добавить `"agent"`
- [ ] `orchestrator/api/workflows.py:18-20` — `_RO`, `_RW`, `_ADMIN` —
  добавить `"agent"`
- [ ] `orchestrator/api/jobs.py:13-15` — `_RO`, `_RW`, `_ANALYST` —
  добавить `"agent"`
- [ ] `orchestrator/api/logs.py:13` — `_RW` — добавить `"agent"`
- [ ] `orchestrator/api/tools.py:9` — `_RO` — добавить `"agent"`
- [ ] `orchestrator/api/status.py:7` — `_RO` — добавить `"agent"`
- [ ] `orchestrator/api/prompts.py` — `_RO` — добавить `"agent"`
  (`_ADMIN` для `PUT /prompts/user` — **не трогать**, остаётся admin-only)
- [ ] Тест: роль `agent` — `403` на `POST /auth/users`, `POST
  /auth/keys`, `GET /audit-log`, `GET /transfer/export` (или
  эквивалент), `PUT /prompts/user`
- [ ] Regression: тест для ролей `viewer`/`analyst`/`service`/`admin` —
  прогнать без изменений в ожиданиях, убедиться доступ не расширился
  случайно
- [ ] `python -m pytest tests/orchestrator/ -v`

## Phase 4 — Full verification

- [ ] `python -m pytest tests/orchestrator/ tests/soar/ tests/deploy/ -v`
  (полный прогон)
- [ ] `ruff check orchestrator/ soar/ deploy/`
- [ ] Свериться с [S8] критериями успеха спека — по каждому пункту
- [ ] Обновить `AGENTS.md`/`docs/agents/security-patterns.md` — список
  ролей `admin`/`analyst`/`viewer`/`service` → `+ agent` с описанием прав
  (только после того, как код смержен — правило `CLAUDE.md`)
