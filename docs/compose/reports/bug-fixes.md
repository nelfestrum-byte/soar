---
feature: bug-fixes
status: delivered
specs: []
plans:
  - docs/compose/plans/2026-07-01-fix-bugs.md
branch: main
commits: pending
---

# Bug Fixes — Final Report

## What Was Built

Fixed 8 bugs identified during code review: 4 critical (runtime crashes, broken UI), 3 important (data inconsistency, dead code), and 1 minor (dead code removal). All fixes are minimal, targeted patches — no refactoring beyond what's needed to fix each bug.

## What Changed

### Critical Fixes
1. **`send_tg_soc_team.py`**: Changed `.send()` to `.send_message()` — the old method doesn't exist on `TelegramConnector`, causing `AttributeError` at runtime.

2. **`BaseWorkflow.__init__`**: Added `__init__` that sets `self._logger` — subclasses like `MyAlertCheck` referenced `self._logger` which didn't exist.

3. **`Actions.vue`**: Fixed create action flow — `newName` was cleared before being captured, so `selected` was always `''` after creating. Now captures name first, then clears.

4. **`api.js`**: Added missing `getLogs(id)` method — `Logs.vue` called it but it didn't exist, breaking the logs page.

### Important Fixes
5. **Dead UI files**: Deleted `Files.vue` and `WorkflowFiles.vue` — neither had routes in `main.js` nor imports anywhere. `Files.vue` also called nonexistent API methods.

6. **`JobManager.enqueue`**: Added rollback on queue push failure — if `queue.push()` throws, the job is now marked `FAILED` with an error message instead of staying in `CREATED` state indefinitely.

7. **`BaseConnector.disconnect()`**: Changed from `raise NotImplementedError` to a no-op that sets `_connected = False` — subclasses that don't need real disconnection no longer have to override it.

### Minor Fixes
8. **`runner.py`**: Removed dead `os.environ.get()` calls whose results were discarded.

## Verification

- **205 tests pass** (0 failures)
- New tests added for each bug fix:
  - `tests/soar/test_send_tg_soc_team.py` — verifies `send_message` is called
  - `tests/soar/test_base_workflow_logger.py` — verifies `_logger` exists
  - `tests/soar/test_base_connector_disconnect.py` — verifies disconnect is no-op
  - `tests/orchestrator/test_job_manager_push_fail.py` — verifies job rollback on push failure
- Updated `tests/soar/test_base_connector.py` to match new disconnect behavior
- Lint clean (ruff)

## Files Changed

| File | Change |
|------|--------|
| `soar/actions/send_tg_soc_team.py` | `.send()` → `.send_message()` |
| `soar/workflows/base.py` | Added `__init__` with `self._logger` |
| `ui/src/views/Actions.vue` | Capture name before clearing in `createAction` |
| `ui/src/api.js` | Added `getLogs(id)` method |
| `ui/src/views/Files.vue` | Deleted (dead code) |
| `ui/src/views/WorkflowFiles.vue` | Deleted (dead code) |
| `orchestrator/core/job_manager.py` | Rollback job status on queue push failure |
| `soar/connectors/base.py` | `disconnect()` → no-op instead of `raise` |
| `soar/runner.py` | Removed dead env var reads |
| `tests/soar/test_send_tg_soc_team.py` | New test |
| `tests/soar/test_base_workflow_logger.py` | New test |
| `tests/soar/test_base_connector_disconnect.py` | New test |
| `tests/orchestrator/test_job_manager_push_fail.py` | New test |
| `tests/soar/test_base_connector.py` | Updated disconnect test |
