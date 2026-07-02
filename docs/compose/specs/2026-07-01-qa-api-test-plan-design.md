# QA Test Plan — SOAR API

## [S1] Problem

All SOAR API endpoints must be tested for correctness (happy-path returns expected data) and error handling (bad input, missing resources, invalid names). Additionally, several end-to-end SOAR usage scenarios must be designed and verified via the API — creating and successfully running different workflow types. No code changes in the project codebase; all testing is via API calls only.

## [S2] Scope — Endpoint Inventory

### Workflows (`/workflows`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| W1 | GET | `/workflows` | 200, returns list | — |
| W2 | GET | `/workflows/{name}` | 200, returns meta dict | 404 if not found |
| W3 | POST | `/workflows/{name}/enable` | 200, `status: enabled` | 404 if not found |
| W4 | POST | `/workflows/{name}/disable` | 200, `status: disabled` | 404 if not found |
| W5 | POST | `/workflows/reload` | 200, `status: reloaded` + count | — |
| W6 | POST | `/workflows/scheduler/reload` | 200, `status: reloaded` | — |
| W7 | GET | `/workflows/code/template` | 200, returns `content` | Invalid `wf_type` falls back to scheduled template |
| W8 | GET | `/workflows/{name}/code` | 200, returns source | 404 if not found; 400 invalid name |
| W9 | PUT | `/workflows/{name}/code` | 200, `status: saved` + commit | 400 invalid name; path traversal → 403 |
| W10 | DELETE | `/workflows/{name}/code` | 200, `status: deleted` + commit | 404 if not found; 400 invalid name |

### Actions (`/actions`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| A1 | GET | `/actions` | 200, returns sorted list | — |
| A2 | GET | `/actions/template` | 200, returns `content` | — |
| A3 | GET | `/actions/{name}` | 200, returns source | 404 if not found; 400 invalid name |
| A4 | PUT | `/actions/{name}` | 200, `status: saved` + commit | 400 invalid name; path traversal → 403 |
| A5 | DELETE | `/actions/{name}` | 200, `status: deleted` + commit | 404 if not found |

### Connectors (`/connectors`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| C1 | GET | `/connectors` | 200, returns list with name/class_name/has_code/has_config | — |
| C2 | GET | `/connectors/template` | 200, returns `code` + `config` | — |
| C3 | GET | `/connectors/{name}/code` | 200, returns source | 404 if not found |
| C4 | PUT | `/connectors/{name}/code` | 200, `status: saved` + commit | 400 invalid name |
| C5 | GET | `/connectors/{name}/config` | 200, returns content (empty if no file) | — |
| C6 | PUT | `/connectors/{name}/config` | 200, `status: saved` + commit | 400 invalid name |
| C7 | POST | `/connectors/{name}` | 201, `status: created` + commit | 409 if already exists |
| C8 | DELETE | `/connectors/{name}` | 200, `status: deleted` + commit | 404 if not found |

### Jobs (`/jobs`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| J1 | POST | `/jobs` | 202, returns job dict with id/status | 404 if workflow not found/disabled |
| J2 | GET | `/jobs` | 200, returns list; filter by status/workflow_name/triggered_by, limit/offset | — |
| J3 | GET | `/jobs/{job_id}` | 200, returns job dict | 404 if not found |
| J4 | POST | `/jobs/{job_id}/cancel` | 200, returns updated job | 404 if not found |

### Webhooks (`/webhooks`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| WH1 | POST | `/webhooks/{workflow_name}` | 202, returns `job_id` | 404 workflow not found; 403 invalid token; 409 disabled; not a webhook type → 404 |

### Logs (`/logs`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| L1 | GET | `/logs/{job_id}` | 200, returns plain text | 404 job not found; 404 log file not found |
| L2 | GET | `/logs/{job_id}/stream` | 200, SSE stream | 404 job not found; 404 no log path |

### Status (`/status`)
| # | Method | Path | Happy-path check | Error cases |
|---|--------|------|-----------------|-------------|
| S1 | GET | `/status` | 200, returns workers/queue/jobs/scheduler | — |

### Validation (`/validation.py`)
| # | Test | Expected |
|---|------|----------|
| V1 | Name: empty string | 400 "Invalid name" |
| V2 | Name: >100 chars | 400 "Invalid name" |
| V3 | Name: special chars (`../`, `@#$`) | 400 "Name contains invalid characters" |
| V4 | Name: valid `^[a-zA-Z0-9_\-]+$` | Passes validation |
| V5 | Path traversal in request | 403 "Access denied" |
| V6 | Body > 5 MB | 413 |

## [S3] Test Infrastructure

### Framework
- **pytest + pytest-asyncio** — async test functions
- **httpx AsyncClient** with `ASGITransport(app=app)` — in-process HTTP testing (no real server)
- **unittest.mock.MagicMock** for GitManager (avoid real git commits during tests)

### Fixture Pattern
Each test file uses an `autouse` fixture that wires up `app.state` with:
```python
queue = InMemoryQueue()
job_store = JobStore()
runner = SubprocessRunner()
git = MagicMock()
config = OrchestratorConfig()

job_manager = JobManager(queue=queue, job_store=job_store, runner=runner, log_dir="/tmp/test_logs")
job_manager.set_metas([])
pool = WorkerPool(count=2, queue=queue, runner=runner, job_store=job_store, default_timeout=300)
scheduler = OrchestratorScheduler(job_manager)

app.state.job_manager = job_manager
app.state.pool = pool
app.state.scheduler = scheduler
app.state.git = git
app.state.config = config
app.state.job_store = job_store
app.state.queue = queue
```

### Naming Convention
- Test files: `tests/orchestrator/api/test_<group>.py`
- Test functions: `test_<endpoint_description>_<scenario>`

## [S4] Test Files

| File | Covers |
|------|--------|
| `tests/orchestrator/api/test_workflows_api.py` | W1–W10 |
| `tests/orchestrator/api/test_actions_api.py` | A1–A5 |
| `tests/orchestrator/api/test_connectors_api.py` | C1–C8 |
| `tests/orchestrator/api/test_jobs_api.py` | J1–J4 |
| `tests/orchestrator/api/test_webhooks_api.py` | WH1 |
| `tests/orchestrator/api/test_logs_api.py` | L1–L2 |
| `tests/orchestrator/api/test_status_api.py` | S1 |
| `tests/orchestrator/api/test_validation_api.py` | V1–V6 |
| `tests/orchestrator/api/test_scenarios.py` | E2E scenarios (S5) |

## [S5] End-to-End SOAR Scenarios

Each scenario runs a full lifecycle via API: create workflow code → enable → trigger → verify job status → check logs.

### Scenario 1: Manual Workflow — Fire and Forget
1. GET `/workflows/code/template?wf_type=manual&name=manual_test`
2. PUT `/workflows/manual_test/code` with the template body
3. POST `/workflows/reload` — verify count increased
4. POST `/workflows/manual_test/enable`
5. POST `/jobs` with `workflow_name: manual_test`
6. GET `/jobs/{job_id}` — verify status transitions (pending → running → completed/failed)
7. GET `/logs/{job_id}` — verify log content exists

### Scenario 2: Webhook Workflow — External Trigger
1. Create webhook workflow via PUT `/workflows/webhook_test/code`
2. POST `/workflows/reload`
3. POST `/webhooks/webhook_test` with body `{"event": "alert", "severity": "high"}` + valid token
4. Verify job created, status transitions, log exists
5. Error cases: test 403 (wrong token), 409 (disabled workflow), 404 (non-webhook type)

### Scenario 3: Scheduled Workflow — Enable/Disable Cycle
1. Create scheduled workflow via PUT `/workflows/scheduled_test/code`
2. POST `/workflows/reload`
3. POST `/workflows/scheduled_test/disable`
4. POST `/jobs` with `workflow_name: scheduled_test` — expect 404 (disabled)
5. POST `/workflows/scheduled_test/enable`
6. POST `/jobs` with `workflow_name: scheduled_test` — expect 202
7. GET `/jobs/{job_id}` — verify completion

### Scenario 4: Connector CRUD Lifecycle
1. POST `/connectors/test_connector` — create
2. GET `/connectors` — verify appears in list with has_code=True, has_config=True
3. PUT `/connectors/test_connector/code` — update code
4. GET `/connectors/test_connector/code` — verify updated content
5. PUT `/connectors/test_connector/config` — update config
6. GET `/connectors/test_connector/config` — verify updated content
7. DELETE `/connectors/test_connector` — delete
8. GET `/connectors` — verify removed

### Scenario 5: Action CRUD Lifecycle
1. GET `/actions/template?name=test_action` — get template
2. PUT `/actions/test_action` with template body
3. GET `/actions` — verify appears in list
4. GET `/actions/test_action` — verify content
5. DELETE `/actions/test_action`
6. GET `/actions` — verify removed

### Scenario 6: Job Lifecycle — Create, Monitor, Cancel
1. Create a workflow, enable it
2. POST `/jobs` — create job
3. GET `/jobs` — list jobs, verify new job appears
4. GET `/jobs/{id}` — get specific job
5. POST `/jobs/{id}/cancel` — cancel (if still pending/running)
6. GET `/jobs/{id}` — verify status is `cancelled`

### Scenario 7: Cross-Resource Validation
1. Test invalid names on all name-based endpoints (workflows, actions, connectors)
2. Test path traversal attempts (e.g., `../../etc/passwd` as workflow name)
3. Test body size limit (>5MB payload)
4. Verify consistent error response format

## [S6] Test Execution Order

Tests should be runnable independently, but the recommended execution order for manual QA:

1. **Validation tests** — `test_validation_api.py` (foundation)
2. **Status** — `test_status_api.py` (sanity check)
3. **Workflows CRUD** — `test_workflows_api.py`
4. **Actions CRUD** — `test_actions_api.py`
5. **Connectors CRUD** — `test_connectors_api.py`
6. **Jobs** — `test_jobs_api.py`
7. **Webhooks** — `test_webhooks_api.py`
8. **Logs** — `test_logs_api.py`
9. **E2E Scenarios** — `test_scenarios.py`

Run all: `python -m pytest tests/orchestrator/api/ -v`

## [S7] Success Criteria

- [ ] All endpoints return correct HTTP status codes
- [ ] All endpoints return correctly shaped JSON responses
- [ ] All error cases return descriptive error messages
- [ ] Name validation rejects invalid characters consistently
- [ ] Path traversal attacks are blocked (403)
- [ ] Request body size limit enforced (413)
- [ ] At least 7 E2E scenarios pass end-to-end
- [ ] All tests pass: `pytest tests/orchestrator/api/ -v` → 0 failures
