# Plan: API Request Logging + Audit Trail

Spec: [`docs/compose/specs/2026-07-17-api-request-audit-logging-design.md`](../specs/2026-07-17-api-request-audit-logging-design.md)

Decision from spec review: `workflow.enable`/`workflow.disable` ARE audited
(cheap, realistic incident question) — included in Phase 4's route table.

## Phase 1 — Correlation id + access log middleware

- [ ] Add `tests/orchestrator/api/test_access_log_middleware.py` (new,
  fails now — no `X-Request-ID` header exists yet):
  - `GET /status` (authenticated via `setup_app_state` mock-admin override)
    returns an `X-Request-ID` header, 32-hex-char-ish value
  - two sequential requests get two different `X-Request-ID` values
  - a `429` response (reuse `test_rate_limiter.py`'s trick of pre-filling
    `rate_limiter._requests`) still carries `X-Request-ID` (proves the
    middleware wraps rate limiting)
  - a captured loguru sink (`logger.add(records.append, serialize=False)`
    swapped in via fixture) shows one `"request"` message per call with
    `extra["method"]`, `extra["status"]`, `extra["duration_ms"]` present
  - `request.state.user_id` ends up on the access-log line for an
    authenticated call, `None` for `/webhooks/...` calls (no `Authorization`
    header)
- [ ] `orchestrator/core/net.py` (new): move `_resolve_client_ip(request,
  trusted_proxies)` out of `rate_limit_middleware` (`main.py:261-271`) into
  a standalone function; update `rate_limit_middleware` to call it
- [ ] `orchestrator/auth/dependencies.py`: in `get_current_user`, set
  `request.state.user_id` / `request.state.user_role` on all three return
  paths (anonymous-admin at line 22, JWT at line 33-37, API key at line 47)
  before returning
- [ ] `orchestrator/main.py`:
  - add `_LOG_FORMAT` constant with `{extra}`, pass to both `logger.add()`
    calls in `lifespan()` (`main.py:149-150`)
  - add `access_log_middleware` as the last `@app.middleware("http")`
    (after `rate_limit_middleware`), per spec [S3] — generates
    `request_id`, sets `request.state.request_id`, wraps `call_next` in
    `logger.contextualize(request_id=...)`, logs method/path/status/
    duration_ms/client_ip/user_id, sets `X-Request-ID` response header
- [ ] Run `python -m pytest tests/orchestrator/api/test_access_log_middleware.py tests/orchestrator/api/test_rate_limiter.py -v`
- [ ] Run full suite to confirm no regressions from the `request.state`
  additions: `python -m pytest tests/orchestrator/ -v`

## Phase 2 — Security-event logging

- [ ] Add `tests/orchestrator/auth/test_security_event_logging.py` (new
  dir+file, fails now):
  - one test per row of spec [S4]'s table — capture loguru via a sink
    fixture, assert `logger.warning` fired with the right `extra` keys
    present (not string-matching the message), for:
    - missing `Authorization` header → 401
    - garbage bearer token → 401
    - wrong role via `require_role` → 403
    - login rate limit hit → 429 on `/auth/login`
    - general rate limit hit → 429
    - bad `X-Webhook-Token` → 403
- [ ] `orchestrator/auth/dependencies.py`: add `logger.warning(...)` calls
  at lines 26, 42, 49 (`get_current_user`) and 56 (`require_role`) per spec
  [S4] table — import `loguru.logger`
- [ ] `orchestrator/main.py`: add `logger.warning(...)` at the two 429
  branches (`main.py:280`, `main.py:283`)
- [ ] `orchestrator/api/webhooks.py`: add `logger.warning(...)` at the
  invalid-token branch (`webhooks.py:21`) — import `loguru.logger`
- [ ] Run `python -m pytest tests/orchestrator/auth/test_security_event_logging.py -v`
- [ ] Run full suite: `python -m pytest tests/orchestrator/ -v`

## Phase 3 — Audit trail schema + service + migration

- [ ] Add `tests/orchestrator/audit/test_audit_service.py` (new dir+file,
  fails now — no `orchestrator.audit` package):
  - `record()` against an in-memory SQLite engine (same `db_engine`/
    `db_factory` fixture pattern as `tests/orchestrator/api/test_auth_api.py`)
    inserts one `AuditLog` row with expected `actor_id`/`actor_type`/
    `actor_name`/`action`/`resource_type`/`resource_id`/`client_ip`/
    `request_id`/`detail`/`created_at`
  - `actor_name` falls back to `str(user.id)` when `username` is empty
    (service-account/API-key case)
- [ ] `orchestrator/audit/__init__.py` (new, empty)
- [ ] `orchestrator/audit/models.py` (new): `AuditLog(Base)` per spec [S5]
  exact field list, `__tablename__ = prefixed("audit_log")`
- [ ] `orchestrator/audit/service.py` (new): `record(db, *, user, action,
  resource_type, resource_id, request, detail=None) -> None` per spec [S5],
  using `orchestrator.core.net._resolve_client_ip` from Phase 1 and
  `request.state.request_id` from Phase 1
- [ ] Run `python -m pytest tests/orchestrator/audit/test_audit_service.py -v`
- [ ] Alembic: `alembic revision --autogenerate -m "add audit_log table"`,
  hand-review the generated `alembic/versions/000X_add_audit_log_table.py`
  against `AuditLog`'s column list
- [ ] Extend `tests/orchestrator/test_alembic_schema.py` to cover
  `audit_log` in its drift-check assertions
- [ ] Run `python -m pytest tests/orchestrator/test_alembic_schema.py -v`

## Phase 4 — Wire audit calls into mutating routes

Per spec [S6] table (14 routes). For each: change
`dependencies=[Depends(require_role(*_ROLE))]` → inject
`user: CurrentUser = Depends(require_role(*_ROLE))` as a parameter, add
`db: AsyncSession = Depends(get_db)` where not already a parameter, call
`await audit.record(db, user=user, action=..., resource_type=..., resource_id=..., request=request, detail=...)` right after the mutation succeeds (same
placement as the existing `git.commit(...)` calls where one exists).

- [ ] Extend `tests/orchestrator/api/test_workflows_api.py`: after
  `PUT /workflows/{name}/code`, `DELETE /workflows/{name}/code`,
  `POST /workflows/{name}/enable`, `POST /workflows/{name}/disable` succeed,
  assert a matching `AuditLog` row exists (needs the `auth_client`-style
  fixture wired to a real test DB — reuse pattern from
  `tests/orchestrator/api/test_auth_api.py`, or add a lightweight
  `db_session`-only fixture if full JWT auth isn't otherwise needed for
  these tests)
- [ ] `orchestrator/api/workflows.py`: instrument `save_workflow_code`
  (`workflows.py:179`), `delete_workflow_code` (`workflows.py:217`),
  `enable_workflow` (`workflows.py:109`), `disable_workflow`
  (`workflows.py:122`)
- [ ] Extend `tests/orchestrator/api/test_actions_api.py` similarly for
  `PUT /actions/{name}`, `DELETE /actions/{name}`
- [ ] `orchestrator/api/actions.py`: instrument `update_action`
  (`actions.py:73`), `delete_action` (`actions.py:102`)
- [ ] Extend `tests/orchestrator/api/test_connectors_api.py` similarly for
  `POST /connectors/generate`, `POST /connectors/{name}`,
  `PUT /connectors/{name}/code`, `PUT /connectors/{name}/config`,
  `DELETE /connectors/{name}`
- [ ] `orchestrator/api/connectors.py`: instrument all five routes
  (`connectors.py:203,359,286,334,396`)
- [ ] Extend `tests/orchestrator/api/test_auth_api.py` for
  `POST /auth/keys`, `DELETE /auth/keys/{key_id}`
- [ ] `orchestrator/auth/router.py`: instrument `create_key`
  (`router.py:86`), `delete_key` (`router.py:99`) — these already take
  `db: AsyncSession = Depends(get_db)`, just add the `user` parameter and
  the `audit.record()` call
- [ ] Extend `tests/orchestrator/api/test_jobs_api.py` for
  `POST /jobs/{job_id}/cancel`
- [ ] `orchestrator/api/jobs.py`: instrument `cancel_job` (`jobs.py:68`) —
  needs `db: AsyncSession = Depends(get_db)` added (not currently a param)
- [ ] Run `python -m pytest tests/orchestrator/api/ -v`

## Phase 5 — Git commit author = acting user

- [ ] Extend `tests/orchestrator/test_git_manager.py`: `commit(filepath,
  message, author_name="alice", author_email="alice@soar.local")` produces
  a commit whose author (via `git log -1 --format=%an <%ae>`) is
  `alice <alice@soar.local>`; `commit(filepath, message)` (no override)
  keeps today's fixed-default behavior — fails now (no such params)
- [ ] `orchestrator/core/git_manager.py`: add optional `author_name`/
  `author_email` params to `commit()` per spec [S7], falling back to
  `self.author_name`/`self.author_email`
- [ ] Update the Phase 4 call sites that already call `git.commit(...)`
  (`workflows.py:203`, `actions.py:96,113`, `connectors.py:231,305,353,390,408`)
  to pass `author_name=user.username or f"user-{user.id}", author_email=f"{user.username or user.id}@soar.local"`
- [ ] Run `python -m pytest tests/orchestrator/test_git_manager.py tests/orchestrator/api/ -v`

## Phase 6 — `GET /audit-log` API

- [ ] Add `tests/orchestrator/api/test_audit_log_api.py` (new, fails now —
  no route):
  - non-admin (`analyst`) gets 403
  - admin gets 200 with rows written by a prior mutating call in the same
    test (reuse Phase 4's DB-wired fixture)
  - filters (`resource_type`, `action`, `actor_name`) narrow results
  - `limit`/`offset` pagination behaves like `GET /jobs`'s existing
    `Query(default=50, ge=1, le=500)` pattern
- [ ] `orchestrator/api/audit.py` (new): `GET /audit-log`, admin-only, per
  spec [S8]
- [ ] `orchestrator/api/__init__.py`: export `audit_router`
- [ ] `orchestrator/main.py`: `app.include_router(audit_router)`
- [ ] Run `python -m pytest tests/orchestrator/api/test_audit_log_api.py -v`

## Phase 7 — Full suite, lint, docs

- [ ] `python -m pytest tests/ -v`
- [ ] `ruff check .`
- [ ] `mypy orchestrator/ --ignore-missing-imports` (best-effort — check
  current baseline first, don't block on pre-existing errors unrelated to
  this change)
- [ ] Update `AGENTS.md`:
  - `Architecture` tree: add `orchestrator/audit/`, `orchestrator/core/net.py`
  - New subsection under "Key patterns" documenting request_id/access log/
    audit trail (mirror existing subsection style)
  - `File map` table: add rows for `audit/models.py`, `audit/service.py`,
    `api/audit.py`, `core/net.py`
  - Note the stale "No auth до v0.8" line is superseded (auth landed
    v0.5.1) — correct it while touching this section
  - `Version history`: new entry for this feature
- [ ] Write `docs/compose/reports/api-request-audit-logging.md` per report
  convention (what changed, verification performed, deviations from spec if
  any)

## Test commands (run after each phase, full suite before considering done)

```bash
python -m pytest tests/ -v
ruff check .
```
