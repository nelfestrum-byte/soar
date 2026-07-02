# QA Bugfix Plan — SOAR Orchestrator API

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/qa-bugfixes.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 bugs identified in the QA report, restoring full workflow lifecycle and API consistency.

**Architecture:** Backend-only fixes in `orchestrator/api/` and `orchestrator/main.py`, plus minor frontend alignment in `ui/src/api.js`. The root cause of BUG-1 is that PUT endpoints write raw bytes instead of extracting JSON `code` field, and no state/meta updates occur after save/delete. CORS middleware is added in `main.py`.

**Tech Stack:** Python 3.11, FastAPI, PyYAML

---

## Bug Summary

| # | Severity | Description | Root Cause |
|---|----------|-------------|------------|
| 1 | CRITICAL | Workflow not registered after PUT /code | PUT writes raw JSON `{"code":"..."}` to .py file; no state update |
| 2 | CRITICAL | Actions: GET /{name}/code missing | Endpoint not implemented |
| 3 | CRITICAL | Connectors: GET /{name} returns 405 | Endpoint not implemented |
| 4 | CRITICAL | Connectors: generate doesn't register | No state update after generate |
| 5 | HIGH | OpenAPI spec wrong prefix | Routers mounted without /api prefix |
| 6 | HIGH | Import with corrupt file: 500 no JSON | No structured error response |
| 7 | HIGH | Double-encoded content in GET /actions/{name} | Same root cause as BUG-1 (raw JSON written to file) |
| 8 | HIGH | CORS preflight not working | No CORS middleware |
| 9 | MEDIUM | Workflow template ignores path param | Only used in WEBHOOK_TEMPLATE, silent ignore elsewhere |
| 10 | MEDIUM | Empty code saved without validation | No validation on PUT |
| 11 | MEDIUM | Git-commit empty on first save/delete | Expected for new files (nothing to commit yet) |
| 12 | LOW | Path traversal returns SPA HTML | SPA catch-all, no 400 for invalid paths |
| 13 | LOW | Double "Connector" suffix in generated class | `class_name + "Connector"` when name already ends with "Connector" |

---

## Global Constraints

- All changes in `orchestrator/` (backend) and `ui/src/api.js` (frontend)
- No changes to `soar/` package — only orchestrator and UI
- Preserve backward compatibility: raw-body PUT still works (fallback)
- Tests: `python -m pytest tests/orchestrator/ -v`
- Lint: `ruff check .`

---

## File Map

| File | Changes |
|------|---------|
| `orchestrator/api/workflows.py` | BUG-1: Parse JSON in PUT, add state update after PUT/DELETE, add reload |
| `orchestrator/api/actions.py` | BUG-2+BUG-7: Add GET /{name}/code, fix PUT to parse JSON |
| `orchestrator/api/connectors.py` | BUG-3+BUG-4: Add GET /{name}, update state after generate |
| `orchestrator/main.py` | BUG-5+BUG-8: Add CORS middleware, mount routers under /api prefix |
| `orchestrator/api/transfer.py` | BUG-6: Add structured JSON error for corrupt import |
| `ui/src/api.js` | BUG-1+BUG-7: Change PUT to send `{"code": content}` JSON |
| `orchestrator/api/connectors.py:278` | BUG-13: Fix double "Connector" suffix |
| `orchestrator/api/workflows.py:147` | BUG-9: Document path param only used for webhook type |
| `orchestrator/api/workflows.py:165` | BUG-10: Add code validation |

---

## Task 1: Fix PUT /workflows/{name}/code (BUG-1 — CRITICAL)

**Covers:** BUG-1, BUG-10

**Files:**
- Modify: `orchestrator/api/workflows.py:165-180`
- Modify: `ui/src/api.js:22-23`

**Interfaces:**
- Consumes: `request.body()` from FastAPI
- Produces: Writes Python code to `{workflows_dir}/{name}.py`, updates `orchestrator_state.yaml`, reloads `job_manager._metas`

- [ ] **Step 1: Fix PUT endpoint in workflows.py**

Replace the PUT handler to parse JSON `{"code": "..."}` body, with fallback to raw body for backward compatibility:

```python
@router.put("/{name}/code")
async def save_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    raw = await request.body()
    try:
        import json
        body = json.loads(raw)
        code = body.get("code", "")
    except (json.JSONDecodeError, ValueError):
        code = raw.decode("utf-8")

    if not code.strip():
        raise HTTPException(status_code=422, detail="Code must not be empty")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)

    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"workflows/{name}.py", f"Update workflow {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}

    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {"status": "saved", "commit": commit_hash}
```

- [ ] **Step 2: Update frontend api.js to send JSON**

Change `saveWorkflowCode` to send `{"code": content}`:

```javascript
saveWorkflowCode: (name, content) =>
    request(`/workflows/${name}/code`, { method: 'PUT', body: JSON.stringify({ code: content }) }),
```

- [ ] **Step 3: Add state update to DELETE endpoint**

Add the same reload logic to `delete_workflow_code`:

```python
@router.delete("/{name}/code")
async def delete_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    os.remove(filepath)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"workflows/{name}.py", f"Delete workflow {name}")
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}

    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {"status": "deleted", "commit": commit_hash}
```

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/orchestrator/ -v -k "workflow"
ruff check orchestrator/api/workflows.py
```

---

## Task 2: Fix actions API — add GET /{name}/code + fix PUT (BUG-2, BUG-7)

**Covers:** BUG-2, BUG-7

**Files:**
- Modify: `orchestrator/api/actions.py:43-71`
- Modify: `ui/src/api.js:37-38`

**Interfaces:**
- Consumes: `request.body()` from FastAPI
- Produces: New endpoint `GET /actions/{name}/code` returns `{"name": ..., "content": ...}`

- [ ] **Step 1: Add GET /{name}/code endpoint**

Add before the existing `GET /{name}` endpoint:

```python
@router.get("/{name}/code")
async def get_action_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Action not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}
```

- [ ] **Step 2: Fix PUT to parse JSON like workflows**

```python
@router.put("/{name}")
async def save_action(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    raw = await request.body()
    try:
        import json
        body = json.loads(raw)
        code = body.get("code", "")
    except (json.JSONDecodeError, ValueError):
        code = raw.decode("utf-8")

    if not code.strip():
        raise HTTPException(status_code=422, detail="Code must not be empty")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"actions/{name}.py", f"Update action {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    return {"status": "saved", "commit": commit_hash}
```

- [ ] **Step 3: Update frontend api.js**

Change `saveAction` to send JSON:

```javascript
saveAction: (name, content) =>
    request(`/actions/${name}`, { method: 'PUT', body: JSON.stringify({ code: content }) }),
```

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/orchestrator/ -v -k "action"
ruff check orchestrator/api/actions.py
```

---

## Task 3: Fix connectors API — add GET /{name} + update state after generate (BUG-3, BUG-4, BUG-13)

**Covers:** BUG-3, BUG-4, BUG-13

**Files:**
- Modify: `orchestrator/api/connectors.py:52-80,158-190,267-278`

**Interfaces:**
- Consumes: filesystem scan of connectors_dir
- Produces: New `GET /connectors/{name}` returns connector metadata

- [ ] **Step 1: Add GET /{name} endpoint**

Add after the `list_connectors` endpoint:

```python
@router.get("/{name}")
async def get_connector(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    connectors_dir = config.soar.connectors_dir
    dirpath = os.path.join(connectors_dir, name)
    validate_path_within(connectors_dir, dirpath)
    if not os.path.exists(dirpath) or not os.path.isdir(dirpath):
        raise HTTPException(status_code=404, detail="Connector not found")
    py_file = os.path.join(dirpath, f"{name}.py")
    yml_file = os.path.join(dirpath, f"{name}.yml")
    has_code = os.path.exists(py_file)
    has_config = os.path.exists(yml_file)
    class_name = ""
    if has_code:
        try:
            with open(py_file) as f:
                class_name = _parse_class_name(f.read())
        except Exception:
            pass
    return {
        "name": name,
        "class_name": class_name,
        "has_code": has_code,
        "has_config": has_config,
    }
```

Note: This route must be placed AFTER `/template` and `/preview` static routes, or use a path that doesn't conflict. Since `/{name}` would match `/template` and `/preview`, we need to reorder — put `/{name}` BEFORE `/{name}/code` and AFTER static routes.

Actually, looking at the existing code, `/{name}/code` and `/{name}/config` and `/{name}` (POST/DELETE) are already there. The `GET /{name}` needs to be added. FastAPI matches in order, so we place it after the static routes (`/template`, `/preview`, `/generate`) but before the parameterized routes.

- [ ] **Step 2: Fix double "Connector" suffix in class_name generation**

Line 278 — change:
```python
class_name = "".join(w.capitalize() for w in name.split("_")) + "Connector"
```
to:
```python
class_name = "".join(w.capitalize() for w in name.split("_"))
if not class_name.endswith("Connector"):
    class_name += "Connector"
```

- [ ] **Step 3: Add state update after generate**

After the git commit loop in `generate_connector`, add state reload:

```python
from orchestrator.main import load_workflow_metas
job_manager = request.app.state.job_manager
scheduler = request.app.state.scheduler
workflows = load_workflow_metas(config)
job_manager.set_metas(workflows)
await scheduler.reload(workflows)
```

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/orchestrator/ -v -k "connector"
ruff check orchestrator/api/connectors.py
```

---

## Task 4: Add CORS middleware + fix router prefix (BUG-5, BUG-8)

**Covers:** BUG-5, BUG-8

**Files:**
- Modify: `orchestrator/main.py:178-201`

**Interfaces:**
- Consumes: FastAPI app
- Produces: CORS headers on all responses, routers mounted under `/api`

- [ ] **Step 1: Add CORS middleware**

Add after `app = FastAPI(...)` and before the body-size middleware:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: Mount routers under /api prefix**

Change router includes from:
```python
app.include_router(workflows_router)
app.include_router(actions_router)
...
```
to:
```python
app.include_router(workflows_router, prefix="/api")
app.include_router(actions_router, prefix="/api")
app.include_router(connectors_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")
app.include_router(logs_router, prefix="/api")
app.include_router(status_router, prefix="/api")
app.include_router(transfer_router, prefix="/api")
```

Note: The nginx config already strips `/api/` when proxying (`proxy_pass http://orchestrator:8000/`). With this change, the orchestrator itself will also serve at `/api/` directly. The nginx proxy will double-prefix. We need to either:
- Update nginx to proxy without stripping: `proxy_pass http://orchestrator:8000/api/;`
- OR keep routers at root and fix OpenAPI spec separately

**Decision:** Keep routers at root (no prefix change) — the nginx proxy already handles `/api/` → `/` mapping. Fix OpenAPI spec to document the correct `/api/` paths instead.

Actually, re-reading nginx: `location /api/ { proxy_pass http://orchestrator:8000/; }` — the trailing slash on proxy_pass means `/api/workflows` → `/workflows`. So the orchestrator serves at root. The OpenAPI spec shows root paths, which is correct for the orchestrator. The UI uses `/api/` prefix via nginx.

**Revised approach:** Keep routers at root. The OpenAPI spec is auto-generated by FastAPI and will show root paths — that's correct. The real issue is that `GET /docs` shows root paths but the UI must call `/api/`. This is by design (nginx proxy).

- [ ] **Step 3: Verify**

```bash
python -m pytest tests/orchestrator/ -v
ruff check orchestrator/main.py
```

---

## Task 5: Fix transfer import error handling (BUG-6)

**Covers:** BUG-6

**Files:**
- Modify: `orchestrator/api/transfer.py`

**Interfaces:**
- Consumes: upload file from request
- Produces: Structured JSON error response on corrupt file

- [ ] **Step 1: Add try/except around import logic**

Find the import endpoint and wrap the ZIP processing in a try/except that returns structured JSON:

```python
@router.post("/import")
async def import_entities(request: Request, file: UploadFile, force: bool = False):
    try:
        # ... existing import logic ...
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid file: not a valid ZIP archive")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
```

- [ ] **Step 2: Verify**

```bash
python -m pytest tests/orchestrator/ -v -k "transfer"
ruff check orchestrator/api/transfer.py
```

---

## Task 6: Fix workflow template path param (BUG-9)

**Covers:** BUG-9

**Files:**
- Modify: `orchestrator/api/workflows.py:146-149`

**Interfaces:**
- Consumes: query params `name`, `wf_type`, `path`
- Produces: Template with correct substitutions

- [ ] **Step 1: Only substitute path for webhook type**

The template uses `.format(name=name, path=path)` — this works for WEBHOOK_TEMPLATE which has `{path}`. For SCHEDULED and MANUAL templates, `{path}` is absent so it's silently ignored. This is actually fine behavior. The fix is to document it or return an error if path is specified for non-webhook types.

Minimal fix — just add a note in the response:

```python
@router.get("/code/template")
async def get_workflow_template(name: str = "MyWorkflow", wf_type: str = "scheduled", path: str = "my-endpoint"):
    template = TEMPLATES.get(wf_type, SCHEDULED_TEMPLATE)
    result = {"content": template.format(name=name, path=path)}
    if wf_type != "webhook" and path != "my-endpoint":
        result["warning"] = "path parameter is only used for webhook workflows"
    return result
```

- [ ] **Step 2: Verify**

```bash
ruff check orchestrator/api/workflows.py
```

---

## Task 7: Run full verification

**Covers:** All

**Files:** None (verification only)

- [ ] **Step 1: Run all orchestrator tests**

```bash
python -m pytest tests/orchestrator/ -v
```

- [ ] **Step 2: Run lint**

```bash
ruff check orchestrator/
```

- [ ] **Step 3: Run typecheck**

```bash
mypy orchestrator/ --ignore-missing-imports
```

---

## Execution Order

1. **Task 1** (BUG-1) — Most critical, blocks everything
2. **Task 2** (BUG-2+BUG-7) — Actions consistency
3. **Task 3** (BUG-3+BUG-4+BUG-13) — Connectors
4. **Task 4** (BUG-5+BUG-8) — CORS + spec
5. **Task 5** (BUG-6) — Error handling
6. **Task 6** (BUG-9) — Template
7. **Task 7** — Full verification

Tasks 1-3 are independent and can run in parallel. Tasks 4-6 are independent and can run in parallel after 1-3.
