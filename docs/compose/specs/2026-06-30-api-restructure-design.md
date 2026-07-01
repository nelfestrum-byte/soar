# API Restructure: Entity-First Design

## [S1] Problem

Current API endpoints don't reflect the three core entities (connectors, actions, workflows):

- `/workflows` only manages runtime state (enable/disable), while source code lives at `/workflow-files` — confusing split
- `/files` provides generic file access across all directories, overlapping with entity-specific endpoints
- No consistent CRUD pattern: workflows have code endpoints under a separate prefix, actions only have code CRUD, connectors have code+config

The naming creates confusion about what "workflow" means and where to find source code.

## [S2] Solution

Adopt entity-first API design where each entity (workflow, action, connector) owns its endpoints:

### Workflows — runtime state
```
GET    /workflows                    — list all workflow metas
GET    /workflows/{name}             — get single meta
POST   /workflows/{name}/enable      — enable
POST   /workflows/{name}/disable     — disable
POST   /workflows/reload             — reload from files
```

### Workflows — source code
```
GET    /workflows/{name}/code        — get source code
PUT    /workflows/{name}/code        — save source code
DELETE /workflows/{name}/code        — delete source file
GET    /workflows/code/template      — boilerplate template
```

### Actions (stateless — code only)
```
GET    /actions                      — list
GET    /actions/{name}               — get source code
PUT    /actions/{name}               — save source code
DELETE /actions/{name}               — delete
GET    /actions/template             — boilerplate template
```

### Connectors (code + config)
```
GET    /connectors                   — list
GET    /connectors/{name}            — get overview (class_name, has_code, has_config)
POST   /connectors/{name}            — create
DELETE /connectors/{name}            — delete
GET    /connectors/{name}/code       — get .py
PUT    /connectors/{name}/code       — save .py
GET    /connectors/{name}/config     — get .yml
PUT    /connectors/{name}/config     — save .yml
GET    /connectors/template          — boilerplate
```

### Unchanged
- Jobs, Webhooks, Logs, Status — no changes

### Removed
- `/files` — generic file API (redundant with entity endpoints)
- `/workflow-files` — replaced by `/workflows/{name}/code`

## [S3] Breaking changes

| Before | After |
|---|---|
| `GET /workflow-files` | `GET /workflows` (runtime) + code at `GET /workflows/{name}/code` |
| `GET /workflow-files/{name}` | `GET /workflows/{name}/code` |
| `PUT /workflow-files/{name}` | `PUT /workflows/{name}/code` |
| `DELETE /workflow-files/{name}` | `DELETE /workflows/{name}/code` |
| `GET /files` | Removed |
| `GET /files/{path}` | Removed |
| `PUT /files/{path}` | Removed |
| `POST /files/upload` | Removed |
| `DELETE /files/{path}` | Removed |
| `GET /files/{path}/history` | Removed |
| `GET /files/{path}/history/{commit}` | Removed |
| `POST /files/{path}/restore/{commit}` | Removed |

## [S4] Files to modify

1. `orchestrator/api/workflows.py` — add code CRUD endpoints (`/{name}/code`, `/code/template`)
2. `orchestrator/api/workflow_files.py` — delete file entirely
3. `orchestrator/api/files.py` — delete file entirely
4. `orchestrator/api/__init__.py` — remove workflow_files_router, files_router exports
5. `orchestrator/main.py` — remove workflow_files_router, files_router from includes
6. `ui/src/api.js` — update all API calls to match new endpoints
7. `AGENTS.md` — update API endpoints documentation

## [S5] Verification

- Run `ruff check orchestrator/` for lint
- Run `mypy orchestrator/ --ignore-missing-imports` for type check
- Run `python -m pytest tests/ -v` for tests
- Verify UI dev server works with new endpoints
