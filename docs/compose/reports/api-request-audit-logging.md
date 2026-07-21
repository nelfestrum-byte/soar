---
feature: api-request-audit-logging
status: delivered
specs:
  - docs/compose/specs/2026-07-17-api-request-audit-logging-design.md
plans:
  - docs/compose/plans/2026-07-18-api-request-audit-logging.md
branch: main
---

# API Request Logging + Audit Trail — Final Report

## What Was Built

Three previously-missing observability layers for the orchestrator API:

1. **Access log + correlation id** — every request gets a `request_id`
   (`X-Request-ID` response header), and a structured log line
   (method/path/status/duration_ms/client_ip/user_id).
2. **Security-event logging** — seven failure points that used to fail
   silently (401/403, rate-limit 429s, invalid webhook token) now emit
   `logger.warning`.
3. **Audit trail** — a new `audit_log` table records who did what to which
   resource, written explicitly from 14 mutating routes, readable via
   `GET /audit-log` (admin-only).

Plus a complementary fix: `GitManager.commit()` now accepts an
`author_name`/`author_email` override, so git commits made through the API
are attributed to the acting user instead of a fixed default.

## Architecture

Three independent mechanisms, deliberately not one generic interceptor —
a body-capturing middleware can't distinguish secrets from safe payload,
and can't know the resource semantics a route mutates:

```
access_log_middleware (main.py)     — ops-facing, stays in existing loguru sinks
logger.warning() at 7 call sites    — security signal, same sinks
orchestrator/audit/                 — product-facing, durable (DB), read via API
├── models.py    — AuditLog ORM model
└── service.py   — record() (write), git_author() (CurrentUser → commit author)
```

**Middleware ordering correction during implementation:** the spec's draft
said to register `access_log_middleware` *after* `rate_limit_middleware` so
it would "wrap" the rate limiter and tag 429s. Empirically this is
backwards — in Starlette, `@app.middleware("http")` registered *later*
ends up *innermost* (closest to the router), so a middleware registered
after `rate_limit_middleware` never even runs when the rate limiter
short-circuits before calling `call_next`. Fixed by registering
`access_log_middleware` last but understanding it correctly: middleware
registered last is outermost. This was caught immediately by a test
asserting `X-Request-ID` is present on a 429 response
(`test_access_log_middleware_wraps_rate_limited_response`), which failed
before the fix and passes after.

**Identity in middleware without duplicating auth logic:** `access_log_middleware`
runs outside FastAPI's dependency-injection phase, so it can't call
`get_current_user` itself. Instead `get_current_user`
(`orchestrator/auth/dependencies.py`) sets `request.state.user_id`/`user_role`
as a side effect on every return path; the middleware reads it back after
`call_next` returns, once routing has already resolved it.

**Audit call sites** follow the same placement pattern as the pre-existing
`git.commit(...)` calls (right after the mutation succeeds) — each mutating
route now takes `user: CurrentUser = Depends(require_role(...))` as an
injected parameter (previously discarded via `dependencies=[Depends(...)]`)
plus `db: AsyncSession = Depends(get_db)`, and calls
`audit.service.record(db, user=user, action=..., resource_type=..., resource_id=..., request=request, detail=...)`.

## Config

No new config fields. Reuses `config.logging.file`/`level` (format string
extended to include `{extra}` so bound fields are visible) and the existing
shared `database:` section for the new `audit_log` table.

## Key Findings During Verification

1. **JWT-authenticated users have no `username` in `AuditLog.actor_name`.**
   `get_current_user`'s JWT branch builds `CurrentUser` from the token
   payload (`id`, `role`, `type`) only — no DB lookup, by design, to avoid a
   round-trip on every request. `audit.service.record()`'s
   `actor_name = user.username or str(user.id)` therefore falls back to the
   numeric id for interactive (JWT) users; only API-key (service) actors
   carry a name (`CurrentUser.username = key.name`). Caught by a test that
   initially asserted `actor_name == "admin"` and failed — fixed the
   assertion, documented as a known limitation rather than adding a DB
   lookup to the hot auth path (out of scope for this task).
2. **The existing autouse test fixture (`tests/orchestrator/api/conftest.py`)
   had no DB wired.** Once 14 routes started requiring
   `db: AsyncSession = Depends(get_db)`, every existing workflow/action/
   connector/job test in that directory would have failed with a missing
   `app.state.db_session_factory`. Fixed once, centrally, by adding an
   in-memory SQLite engine + `get_db` override to the shared autouse
   fixture — all pre-existing tests kept passing without per-file changes.
3. **Alembic schema-drift test is import-order-sensitive.**
   `test_alembic_schema.py` compares a freshly-migrated DB against
   `Base.metadata` in the *current test process* — if an earlier-collected
   test file had already imported `orchestrator.main` (which now pulls in
   `orchestrator.audit.models`), `Base.metadata` would contain `audit_log`
   before the migration for it existed, and the test failed only in the
   full-suite run, not in isolation. Fixed by adding the audit migration
   immediately (not deferring it) and explicitly importing
   `orchestrator.audit.models` in both `alembic/env.py` and the test file,
   matching the existing pattern for auth/store models.
4. **loguru has no `logger.warning(msg, key=value)` shortcut** — kwargs
   passed that way are used for `str.format()`, not structured binding.
   Every security-event log site uses `logger.bind(**fields).warning(msg)`
   instead, which is a small deviation from the spec's illustrative
   pseudocode (spec examples weren't meant to be copy-paste-exact).

## Verification

- Full `tests/orchestrator/` suite: 255 passed, 1 skipped, 0 failed
- `ruff check` on all new/changed files: clean except two pre-existing
  `B904` findings in `orchestrator/api/connectors.py` on lines this task
  didn't touch (left as-is, out of scope)
- Manually verified `alembic upgrade head` applies the new `audit_log`
  migration cleanly against a scratch SQLite DB, column-for-column matching
  `AuditLog`
- Test-driven throughout: the middleware-ordering bug, the JWT-username
  gap, and the conftest DB-wiring gap were all caught by a test failing
  before the fix, not discovered after the fact

## Files Changed

**New:**
- `orchestrator/audit/models.py` — `AuditLog` ORM model
- `orchestrator/audit/service.py` — `record()`, `git_author()`
- `orchestrator/api/audit.py` — `GET /audit-log`
- `orchestrator/core/net.py` — `resolve_client_ip()` (extracted from
  `rate_limit_middleware`, shared by access log + audit + security-event logging)
- `alembic/versions/3067dea7c75b_add_audit_log_table.py`
- `tests/orchestrator/audit/test_audit_service.py`
- `tests/orchestrator/auth/test_security_event_logging.py`
- `tests/orchestrator/api/test_access_log_middleware.py`
- `tests/orchestrator/api/test_audit_log_api.py`

**Modified:**
- `orchestrator/main.py` — `access_log_middleware`, `_LOG_FORMAT`,
  `rate_limit_middleware` reuses `resolve_client_ip` + logs 429s,
  `audit_router` registered
- `orchestrator/auth/dependencies.py` — `request.state.user_id/user_role`,
  `logger.warning` at 401/403 sites
- `orchestrator/auth/router.py` — `create_key`/`delete_key` write audit rows
- `orchestrator/api/webhooks.py` — `logger.warning` on invalid token
- `orchestrator/api/workflows.py`, `actions.py`, `connectors.py`, `jobs.py`
  — 12 mutating routes write audit rows + pass acting-user git author
- `orchestrator/core/git_manager.py` — `commit()` accepts author override
- `alembic/env.py` — imports `orchestrator.audit.models`
- `tests/orchestrator/api/conftest.py` — in-memory DB + `get_db` override
  in the shared autouse fixture
- `tests/orchestrator/api/test_workflows_api.py`, `test_actions_api.py`,
  `test_connectors_api.py`, `test_jobs_api.py`, `test_auth_api.py` — audit-row
  assertions for the routes each file covers
- `tests/orchestrator/test_git_manager.py` — author-override coverage
- `tests/orchestrator/test_alembic_schema.py` — imports audit models
- `AGENTS.md` — architecture tree, three new Key patterns subsections,
  `GET /audit-log` endpoint table, file map, v0.8 entry
