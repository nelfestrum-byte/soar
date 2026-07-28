# Report: Audit-Log Job Creation (`POST /jobs`, `POST /webhooks/{name}`)

Spec: `docs/compose/specs/2026-07-28-job-webhook-audit-logging-design.md`
Plan: `docs/compose/plans/2026-07-28-job-webhook-audit-logging.md`

## Summary

Implemented BAGFIX_PLAN S4: `POST /jobs` and `POST /webhooks/{name}` are the
most mutating actions in the system (a workflow can do anything a script
can), and were the only mutating routes that never wrote to `audit_log`,
despite `AGENTS.md`'s blanket claim that `record()` fires "from every
mutating route." Implemented per spec:

1. `orchestrator/api/jobs.py::create_job` — replaced the router-level
   `dependencies=[Depends(require_role(*_RW))]` with an explicit
   `user: CurrentUser = Depends(require_role(*_RW))` parameter (same
   pattern already used by `cancel_job` in the same file) plus
   `db: AsyncSession = Depends(get_db)`. RBAC is unchanged — same roles,
   just now accessible inside the function body. After a successful
   `enqueue()`, writes `job.create` with `resource_id=job.id` and
   `detail={"workflow_name": job.workflow_name}`. The 404/409 branches are
   unchanged and write nothing.
2. `orchestrator/api/webhooks.py::handle_webhook` — added
   `db: AsyncSession = Depends(get_db)` (the route had no DB session at
   all before). Since the route has no `CurrentUser` (webhooks authenticate
   via per-workflow `X-Webhook-Token`, not JWT/RBAC), it builds a synthetic
   actor: `CurrentUser(id=0, role="service", type="webhook",
   username=f"webhook:{workflow_name}")` — a third `actor_type` value
   alongside the existing `"user"`/`"service"`, no migration needed since
   the column is a plain `String(16)`, not a SQL enum. Writes `job.create`
   with `detail={"workflow_name": ..., "triggered_by": "webhook"}` only on
   successful `enqueue()` — the 403 (invalid token) and 409 (disabled)
   branches are unchanged and write nothing.
3. Neither route puts `body.context`/the webhook JSON payload into the
   audit `detail` — only `workflow_name` (and `triggered_by` for the
   webhook case). Per spec [S2.1], `job.context` is already stored in
   `job_store` and visible to `viewer` via `GET /jobs`; `audit_log` is a
   separate, `admin`-only surface, and duplicating arbitrary user-supplied
   context into it adds no value while inflating `detail`. This
   deliberately does not touch the adjacent M12 known issue
   (`job.context` exposure via `GET /jobs`) — out of scope for S4.

## Files changed

- `orchestrator/api/jobs.py` — `create_job`: explicit `user`/`db` params,
  `audit_service.record(..., action="job.create", ...)` after successful
  enqueue.
- `orchestrator/api/webhooks.py` — `handle_webhook`: added
  `db: AsyncSession = Depends(get_db)`, synthetic `CurrentUser` actor,
  `audit_service.record(..., action="job.create", ...)` after successful
  enqueue.
- `tests/orchestrator/api/test_jobs_api.py` — new
  `test_create_job_writes_audit_log`,
  `test_create_job_not_found_writes_no_audit_log`,
  `test_create_job_disabled_writes_no_audit_log`.
- `tests/orchestrator/api/test_webhooks_api.py` — new
  `test_webhook_success_writes_audit_log`; extended `test_webhook_disabled`
  to assert zero new `audit_log` rows.
- `tests/orchestrator/api/test_webhook_auth.py` — extended
  `test_webhook_wrong_token`, `test_webhook_missing_token`,
  `test_webhook_disabled_workflow` to assert zero new `audit_log` rows
  (these cover the real 403/409 paths with a webhook meta already
  registered, complementing `test_webhooks_api.py`'s 404-flavored cases).
- `AGENTS.md` — "Audit trail" section: dropped the unqualified "из каждого
  мутирующего роута" claim, documented the one remaining exception
  (`POST /transfer/{export,import}`, tracked separately as BAGFIX_PLAN S3)
  and the new `POST /jobs`/`POST /webhooks/{name}` coverage, including the
  synthetic `actor_type="webhook"` actor shape.

## Testing

Tests were added first and confirmed failing against the pre-change code
(no `audit_log` row after `POST /jobs`/`POST /webhooks/{name}`), then made
to pass by the implementation.

```
python -m pytest tests/orchestrator/api/test_jobs_api.py tests/orchestrator/api/test_webhooks_api.py tests/orchestrator/api/test_webhook_auth.py -v
```

All 20 tests pass (10 in `test_jobs_api.py`, 5 in `test_webhooks_api.py`,
5 in `test_webhook_auth.py`).

Full suite:

```
1 failed, 690 passed, 1 skipped
```

The 1 failure is pre-existing and unrelated:
`tests/soar/tools/test_openapi.py::test_generate_config` — a known bug in
`soar/tools/openapi.py`'s `_generate_config` (uses the class name as the
instance key instead of the requested connector name), fixed by a separate
spec, confirmed to fail identically before this change.

## Success criteria (spec S4)

- [x] `POST /jobs` пишет `job.create` с `workflow_name` в `detail` и
      `job_id` в `resource_id`, RBAC не меняется
- [x] `POST /webhooks/{name}` пишет `job.create` с синтетическим
      `actor_type="webhook"` только на успешный enqueue, не на 403/409
- [x] `job.context`/`body.context` целиком не попадает в `detail`
      audit-записи
- [x] `AGENTS.md` "Audit trail" перестаёт содержать неверное общее
      заявление без исключений
