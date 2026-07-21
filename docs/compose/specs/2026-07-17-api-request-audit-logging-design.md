# API Request Logging + Audit Trail

## [S1] Problem

The orchestrator API has no observability into who is calling it and what
they change, despite `v0.5.1` having added full JWT/API-key/RBAC
authentication:

1. **No request/response logging.** `orchestrator/main.py` has three
   `@app.middleware("http")`/`add_middleware` registrations (CORS at
   `main.py:233-239`, body-size limit at `main.py:242-252`, rate limiting at
   `main.py:259-285`) — none of them log the request they handled. The only
   visible trace of an HTTP call is uvicorn's own default access log
   (stdout), which is not code this project controls, carries no
   correlation id, and stops at method/path/status — no latency, no caller
   identity.
2. **No correlation id.** Nothing in the codebase sets or reads a
   `request_id`/`X-Request-ID` (verified: zero matches repo-wide). A support
   request "job X failed, what did the API see around that time" cannot be
   answered by joining request logs to job logs.
3. **Auth failures are silent.** `get_current_user`
   (`orchestrator/auth/dependencies.py:17-49`) raises `HTTPException(401)` at
   three points (lines 26, 42, 49) and `require_role`
   (`dependencies.py:52-58`) raises `403` — none of these call `logger.*`.
   Same for the two `429` rate-limit responses
   (`main.py:280`, `main.py:283`) and the `403 Invalid token` in
   `orchestrator/api/webhooks.py:21`. Brute-force attempts, forbidden-role
   probes, and webhook token guessing all leave zero trace.
4. **No audit trail for mutations.** Mutating routes (workflow/action/
   connector code edits, API-key create/delete, job cancel) all pass through
   `require_role(...)` as a bare `dependencies=[...]` entry — the resolved
   `CurrentUser` is discarded, never logged, never persisted. The one
   mutation-adjacent record that exists, git auto-commit
   (`orchestrator/core/git_manager.py:53-77`), always commits as the fixed
   `config.git.author_name`/`author_email` (default `"SOAR Orchestrator"
   <soar@local>` — `config.py:57-58`), not the user who made the API call.
   There is no way to answer "who changed workflow X" — from the API or from
   `git log`.

This spec covers `GET /audit-log` visibility being admin-only, in-app (no
external aggregator — consistent with this project staying infra-minimal;
see `AGENTS.md` v0.7 entry, no ELK/Loki/Grafana anywhere in `deploy/`).

## [S2] Solution overview

Three independent, orthogonal mechanisms — deliberately not one generic
"log everything" interceptor, because a generic body-capturing middleware
cannot tell secrets (passwords, tokens, connector configs) from harmless
payload, and cannot know the semantic resource type/id a route mutates:

1. **Access log** (ops-facing, ephemeral) — one structured log line per
   request via a new `@app.middleware("http")`, tagged with a per-request
   `request_id`. Stays in the existing loguru file/stderr sinks
   (`config.logging.file`) — no new sink, no API exposure, viewed the same
   way `orchestrator.log` is viewed today (`docker exec`/`docker compose
   logs`).
2. **Security-event logging** — explicit `logger.warning()` calls added at
   the seven existing failure points listed in [S1].3, reusing the same
   sinks. Cheap, no new infra.
3. **Audit trail** (product-facing, durable) — new `audit_log` table in the
   same Postgres/SQLite database job history and auth already use
   (`orchestrator/db/`), written explicitly from each mutating route (mirrors
   how those routes already call `git.commit()` explicitly rather than via a
   generic hook), exposed read-only via `GET /audit-log` (admin-only,
   paginated) — same shape as the existing `GET /logs/{job_id}` precedent in
   `orchestrator/api/logs.py`.

Complementary, not part of the audit table itself: git commit author is
fixed today (`git_manager.py:57-60`); this spec makes it the acting user so
`git log` on `workflows/`/`connectors/`/`actions/` also reflects reality.

## [S3] Correlation id + access log middleware

`orchestrator/main.py` — new middleware, registered **after**
`rate_limit_middleware` (last `@app.middleware("http")` in the file) so it
wraps the body-limit and rate-limit middlewares and captures their `413`/
`429` responses too, not just successful routes:

```python
import uuid

@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    request_id = uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    start = time.monotonic()

    with logger.contextualize(request_id=request_id):
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.bind(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            client_ip=_resolve_client_ip(request),
            user_id=getattr(request.state, "user_id", None),
        ).info("request")

    response.headers["X-Request-ID"] = request_id
    return response
```

`_resolve_client_ip(request)` extracts the trusted-proxy-aware IP resolution
currently inlined in `rate_limit_middleware` (`main.py:261-271`) into a
shared function, called from both middlewares — avoids duplicating the
`X-Real-IP`/`X-Forwarded-For` logic a second time.

**Caller identity without duplicating auth logic:** the middleware runs
outside FastAPI's dependency-injection phase, so it cannot call
`get_current_user` itself without re-implementing JWT/API-key decoding.
Instead, `get_current_user` (`orchestrator/auth/dependencies.py:17-49`) sets
`request.state.user_id` / `request.state.user_role` as a side effect on
every return path (including the anonymous-admin path at line 22, and the
API-key path at line 47) — the middleware reads it back *after* `call_next`
returns, once routing/dependency resolution has already run:

```python
async def get_current_user(request: Request) -> CurrentUser:
    ...
    user = CurrentUser(...)  # however each branch already builds it
    request.state.user_id = user.id
    request.state.user_role = user.role
    return user
```

Routes that don't use `get_current_user` at all (only `webhooks.py`, token-
authenticated) leave `request.state.user_id` unset — the access log line
shows `user_id=None` for those, which is correct (a different, non-JWT
credential authorized the call). No change to `webhooks.py` needed for this.

**Log format:** current `logger.add()` calls (`main.py:149-150`) use
loguru's default format, which does not render `extra` fields. Add an
explicit format including `{extra}` so the bound fields above (and the
audit-adjacent fields in [S5]) are actually visible in the log file:

```python
_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message} | {extra}"
logger.add(config.logging.file, level=config.logging.level, format=_LOG_FORMAT)
logger.add(sys.stderr, level=config.logging.level, format=_LOG_FORMAT)
```

No new config field — reuses `config.logging.file`/`level` as-is.

**Non-goal:** request/response bodies are never logged by this middleware —
`limit_request_body` (`main.py:247-250`) already reads the body for size
checking; the access-log middleware does not touch `request.body()` at all,
only method/path/status/timing.

## [S4] Security-event logging

Add one `logger.warning(...)` call at each existing failure branch — no new
mechanism, just visibility at points that currently fail silently:

| File : line | Trigger | Log |
|---|---|---|
| `orchestrator/auth/dependencies.py:26` | missing/malformed `Authorization` header | `logger.warning("auth.unauthenticated", path=request.url.path, client_ip=...)` |
| `orchestrator/auth/dependencies.py:42` | API-key path, no DB session factory | `logger.warning("auth.invalid_credentials", reason="no_db")` |
| `orchestrator/auth/dependencies.py:49` | JWT decode failed and API key not found | `logger.warning("auth.invalid_credentials", path=request.url.path, client_ip=...)` |
| `orchestrator/auth/dependencies.py:56` (`require_role`) | authenticated but wrong role | `logger.warning("auth.forbidden", user_id=user.id, role=user.role, path=request.url.path)` |
| `main.py:280` | login rate limit hit | `logger.warning("auth.login_rate_limited", client_ip=client_ip)` |
| `main.py:283` | general rate limit hit | `logger.warning("rate_limited", client_ip=client_ip, path=request.url.path)` |
| `orchestrator/api/webhooks.py:21` | bad/missing `X-Webhook-Token` | `logger.warning("webhook.invalid_token", workflow_name=workflow_name, client_ip=request.client.host if request.client else "unknown")` |

All use `logger.bind(...).warning(...)` or keyword-arg `logger.warning(msg,
**fields)` (loguru supports both) — never log the token/credential value
itself, only the fact of failure and non-secret context.

## [S5] Audit trail — schema

New package `orchestrator/audit/` (mirrors `orchestrator/auth/` shape —
`models.py` + `service.py`):

`orchestrator/audit/models.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.db.base import Base, prefixed


class AuditLog(Base):
    __tablename__ = prefixed("audit_log")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)   # "user" | "service"
    actor_name: Mapped[str] = mapped_column(String(128), nullable=False)  # denormalized: survives actor deletion
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)       # "workflow.update"
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # "workflow"
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # e.g. {"commit": "a1b2c3d"}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

`actor_id`/`actor_type` mirror `CurrentUser.id`/`CurrentUser.type`
(`orchestrator/auth/dependencies.py:9-14`) — kept separate because `User.id`
and `ApiKey.id` are different autoincrement sequences and can collide
numerically. `actor_name` is denormalized (not a FK) so the audit trail
stays readable after a user/API key is deleted — matches why `JobRecord.
triggered_by` (`store/models.py:15`) is already a plain string rather than
an FK.

`orchestrator/audit/service.py`:

```python
async def record(
    db: AsyncSession, *, user: CurrentUser, action: str, resource_type: str,
    resource_id: str, request: Request, detail: dict | None = None,
) -> None:
    entry = AuditLog(
        actor_id=user.id, actor_type=user.type, actor_name=user.username or str(user.id),
        action=action, resource_type=resource_type, resource_id=resource_id,
        client_ip=_resolve_client_ip(request),
        request_id=getattr(request.state, "request_id", None),
        detail=detail, created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.commit()
```

Reuses `_resolve_client_ip` from [S3] (moved to a shared module, e.g.
`orchestrator/core/net.py`, to avoid a circular import between `main.py` and
`audit/service.py`).

Alembic revision `alembic/versions/000X_audit_log.py` adds the table,
following the same autogenerate-then-hand-verify process as
`0001_initial_auth_and_jobs.py` (per the postgres-migration spec, [S6]
there).

## [S6] Audit trail — call sites

Routes currently discard the resolved `CurrentUser` (`dependencies=[Depends(
require_role(*_ADMIN))]`) — instrumented routes switch to injecting it as a
parameter (`user: CurrentUser = Depends(require_role(*_ADMIN))`) and add
`db: AsyncSession = Depends(get_db)` where not already present, then call
`audit.record(...)` right after the mutation succeeds — same placement
pattern as the existing `git.commit(...)` calls:

| Route | File : line | `action` | `resource_type` / `resource_id` |
|---|---|---|---|
| `PUT /workflows/{name}/code` | `workflows.py:179` | `workflow.update` | `workflow` / `name` |
| `DELETE /workflows/{name}/code` | `workflows.py:217` | `workflow.delete` | `workflow` / `name` |
| `POST /workflows/{name}/enable` | `workflows.py:109` | `workflow.enable` | `workflow` / `name` |
| `POST /workflows/{name}/disable` | `workflows.py:122` | `workflow.disable` | `workflow` / `name` |
| `PUT /actions/{name}` | `actions.py:73` | `action.update` | `action` / `name` |
| `DELETE /actions/{name}` | `actions.py:102` | `action.delete` | `action` / `name` |
| `POST /connectors/generate` | `connectors.py:203` | `connector.generate` | `connector` / `body.name` |
| `POST /connectors/{name}` | `connectors.py:359` | `connector.create` | `connector` / `name` |
| `PUT /connectors/{name}/code` | `connectors.py:286` | `connector.update_code` | `connector` / `name` |
| `PUT /connectors/{name}/config` | `connectors.py:334` | `connector.update_config` | `connector` / `name` |
| `DELETE /connectors/{name}` | `connectors.py:396` | `connector.delete` | `connector` / `name` |
| `POST /auth/keys` | `auth/router.py:86` | `apikey.create` | `apikey` / new key id |
| `DELETE /auth/keys/{key_id}` | `auth/router.py:99` | `apikey.delete` | `apikey` / `key_id` |
| `POST /jobs/{job_id}/cancel` | `jobs.py:68` | `job.cancel` | `job` / `job_id` |

`detail` carries the git `commit_hash` where one exists (workflow/action/
connector routes) so an audit row and a git commit can be cross-referenced.

**Explicitly not instrumented:** read-only routes (`GET`), `POST /connectors/
preview`, `GET /connectors/preview` (no persisted resource), `POST /jobs`
(job creation is already fully captured by `JobRecord.triggered_by` +
`triggered_at`, a second audit row would be redundant), `/auth/login|refresh|
logout` (covered by [S4] security-event logging instead — these are auth
events, not resource mutations).

## [S7] Git commit author — use the acting user

`orchestrator/core/git_manager.py::commit()` (`git_manager.py:53-77`) —
accept an optional per-call author override, falling back to the configured
default for callers with no user context:

```python
async def commit(
    self, filepath: str, message: str,
    author_name: str | None = None, author_email: str | None = None,
) -> str:
    name = author_name or self.author_name
    email = author_email or self.author_email
    ...  # use name/email instead of self.author_name/self.author_email throughout
```

Call sites in [S6] that already call `git.commit(...)` (workflows.py:203,
actions.py:96/113, connectors.py:231/305/353/390/408) pass
`author_name=user.username or f"user-{user.id}", author_email=f"{user.username
or user.id}@soar.local"` — synthetic email since users have no email field
today (`orchestrator/auth/models.py:14` has no `email` column). Calls with
no user in scope (`ensure_repo()` at `git_manager.py:42-51`) are unaffected,
keep the configured default.

## [S8] API — `GET /audit-log`

New `orchestrator/api/audit.py`, registered in `orchestrator/api/__init__.py`
and `main.py` (`app.include_router(audit_router)`), same shape as
`orchestrator/api/logs.py`:

```python
router = APIRouter(prefix="/audit-log", tags=["audit"])

@router.get("", dependencies=[Depends(require_role("admin"))])
async def list_audit_log(
    db: AsyncSession = Depends(get_db),
    actor_name: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    ...  # filter AuditLog by the given params, order_by(created_at.desc())
```

Admin-only (stricter than `/logs/{job_id}`'s `analyst/service/admin` — audit
data is about *who did what*, more sensitive than job execution output). No
SSE stream (unlike `/logs/{job_id}/stream`) — this is a post-hoc
investigation log, not a live tail.

## [S9] Testing strategy

- `tests/orchestrator/api/test_access_log_middleware.py` (new) — assert
  `X-Request-ID` header present on every response (including a `429` and a
  `413`), same `request_id` value logged via a captured loguru sink
  (`logger.add(list.append, ...)` pattern already usable with `caplog`-style
  capture), `user_id` present after an authenticated call and absent for an
  anonymous one.
- `tests/orchestrator/auth/test_security_event_logging.py` (new) — one test
  per row in [S4]'s table, asserting a `logger.warning` call happens
  (capture via loguru sink) without asserting on log message wording (avoid
  brittle string-matching, assert on bound fields / call count instead).
- `tests/orchestrator/audit/test_audit_service.py` (new) — `record()`
  against an in-memory SQLite engine, same fixture pattern as
  `tests/orchestrator/store/test_sql_job_store.py`.
- `tests/orchestrator/api/test_audit_log_api.py` (new) — `GET /audit-log`
  RBAC (403 for non-admin), filters, pagination; extend each of
  `test_workflows_api.py`/`test_actions_api.py`/`test_connectors_api.py`/
  `test_auth_api.py`/`test_jobs_api.py` with one assertion per mutating
  route in [S6]'s table that a matching `AuditLog` row now exists after the
  call.
- `tests/orchestrator/test_git_manager.py` — extend for `commit(...,
  author_name=..., author_email=...)` overriding `GIT_AUTHOR_NAME`/
  `GIT_AUTHOR_EMAIL` in the resulting commit, and confirm omitting them keeps
  today's fixed-author behavior (backward compatibility).
- Alembic: extend the existing schema-drift smoke test
  (`tests/orchestrator/test_alembic_schema.py`) to cover the new
  `audit_log` table.

## [S10] Non-goals / open decisions

- **No log retention/rotation policy** for `audit_log` in this spec — the
  table grows unbounded, same as `workflow_jobs` does today without
  `jobs.keep_completed` applying to the SQL backend. Follow-up if/when it
  becomes an operational problem, not speculative now.
- **No external log aggregator** (Loki/ELK) — matches this project's
  minimal-infra stance; access log stays file/stdout, audit trail stays
  queryable via the API only.
- **AGENTS.md "No auth until v0.8"** reference is already stale (auth landed
  in v0.5.1) — out of scope to fix here per this project's rule of not
  updating `AGENTS.md` ahead of a completed task; will be corrected in the
  v0.7 entry write-up alongside this feature's own entry once implemented.
- **Open for review:** should `workflow.enable`/`workflow.disable` really be
  audited (table in [S6] includes them) or is that noise for a low-risk
  toggle? Leaning yes — cheap to add, and "who turned off workflow X" is a
  realistic incident question — but flagging since it's the one row in that
  table without an existing git-commit precedent to piggyback on.

## [S11] Success criteria

- [ ] Every request gets a unique `request_id`, returned in `X-Request-ID`
      and present on the access-log line and on any security-event log
      emitted during that request
- [ ] Access log line includes method, path, status, duration_ms, client_ip
      (trusted-proxy aware, reusing existing resolution logic), user_id when
      authenticated — visible in `config.logging.file`
- [ ] All seven failure points in [S4] log a `warning` with no secret values
      in the log line
- [ ] All fourteen mutating routes in [S6] write an `AuditLog` row after a
      successful mutation, with the real caller's `actor_id`/`actor_name`
- [ ] `GET /audit-log` is admin-only, paginated, filterable, and returns
      rows written by [S6]
- [ ] Git commits made via instrumented routes carry the acting user as
      author (`git log` shows real usernames, not the fixed default)
- [ ] Default config / existing deployments: no behavior change if nobody
      reads the new log fields or the new endpoint — no new required config
- [ ] All existing tests pass unmodified; new tests cover access log,
      security-event logging, audit service, audit API, and git author
      override
