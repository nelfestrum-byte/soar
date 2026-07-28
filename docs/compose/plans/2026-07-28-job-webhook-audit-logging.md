# Plan: Audit-Log Job Creation (`POST /jobs`, `POST /webhooks/{name}`)

Spec: [`docs/compose/specs/2026-07-28-job-webhook-audit-logging-design.md`](../specs/2026-07-28-job-webhook-audit-logging-design.md)

## `POST /jobs`

- [ ] Add failing test `test_create_job_writes_audit_log` to
  `tests/orchestrator/api/test_jobs_api.py`: create a `webhook`/`manual`
  workflow meta so `enqueue()` succeeds, `POST /jobs`, then assert an
  `AuditLog` row exists with `action == "job.create"`,
  `resource_id == <job id from response>`, `detail["workflow_name"]`
  matching the posted `workflow_name`
- [ ] Regression assertions (same file): `test_create_job_not_found` (404)
  and a new disabled-workflow 409 case do **not** produce an `AuditLog` row
  — query count before/after
- [ ] `orchestrator/api/jobs.py::create_job`: drop the router-level
  `dependencies=[Depends(require_role(*_RW))]`, add explicit
  `user: CurrentUser = Depends(require_role(*_RW))` and
  `db: AsyncSession = Depends(get_db)` params (same pattern as
  `cancel_job` below it in the same file); after successful `enqueue()`,
  call `audit_service.record(db, user=user, action="job.create",
  resource_type="job", resource_id=job.id, request=request,
  detail={"workflow_name": job.workflow_name})` before returning
  `job.to_dict()`
- [ ] Run `python -m pytest tests/orchestrator/api/test_jobs_api.py -v`

## `POST /webhooks/{name}`

- [ ] Add failing test `test_webhook_success_writes_audit_log` to
  `tests/orchestrator/api/test_webhooks_api.py`: valid token, enabled
  webhook workflow → assert `AuditLog` row with `actor_type == "webhook"`,
  `actor_name == f"webhook:{workflow_name}"`, `action == "job.create"`,
  `resource_id == <job_id from response>`, `detail == {"workflow_name":
  ..., "triggered_by": "webhook"}` (no request body/payload in `detail`)
- [ ] Regression assertions: invalid-token (403) and disabled-workflow
  (409) cases write zero new `AuditLog` rows (count before/after) —
  extend existing tests in `test_webhooks_api.py`/`test_webhook_auth.py`
- [ ] `orchestrator/api/webhooks.py::handle_webhook`: add
  `db: AsyncSession = Depends(get_db)` param; after successful
  `enqueue()`, build `actor = CurrentUser(id=0, role="service",
  type="webhook", username=f"webhook:{workflow_name}")` and call
  `audit_service.record(db, user=actor, action="job.create",
  resource_type="job", resource_id=job.id, request=request,
  detail={"workflow_name": workflow_name, "triggered_by": "webhook"})`
  before returning `{"job_id": job.id}`; 403/409 branches unchanged (no
  audit call)
- [ ] Run `python -m pytest tests/orchestrator/api/test_webhooks_api.py tests/orchestrator/api/test_webhook_auth.py -v`

## Docs

- [ ] `AGENTS.md` "Audit trail" section: note `POST /jobs` and
  `POST /webhooks/{name}` are now covered (webhook uses the synthetic
  `actor_type="webhook"` actor, not a real user/service account) — merge
  into the existing paragraph, re-read current content first since it may
  have been touched by other work in the meantime
- [ ] Write `docs/compose/reports/job-webhook-audit-logging.md` per report
  convention

## Verification

- [ ] `python -m pytest tests/orchestrator/api/test_jobs_api.py tests/orchestrator/api/test_webhooks_api.py -v`
- [ ] `python -m pytest tests/ -q` — confirm the only failure is the
  pre-existing unrelated `tests/soar/tools/test_openapi.py::test_generate_config`
