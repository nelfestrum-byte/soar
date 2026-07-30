---
feature: entity-model-in-code
date: 2026-07-30
spec: docs/compose/specs/2026-07-30-entity-model-in-code-design.md
plan: docs/compose/plans/2026-07-30-entity-model-in-code.md
---

# Report: Модель сущностей в коде — Phase 2

Branch: `feat/entity-model-phase2` (off `main` @ `7e2e8d5`, which already
contains Phase 1 — `soar/runtime_contract.py`, `soar/audit_hook.py`,
`orchestrator/api/runtime.py`, `parse_workflow_meta`,
`resolve_content_python`).

## What was built

All seven sections of the plan, in order.

### 1. Connector registry — namespace by type (E8)

`soar/connectors/__init__.py::ConnectorRegistry` — `_connectors`/`_configs`
moved from flat `dict[instance_name, ...]` to `dict[type_name,
dict[instance_name, ...]]`. `_discover_classes`/`_discover_external` gained
the `obj.__module__ == fqn` check (mirroring `WorkflowRegistry._discover`),
closing the "one connector imports another's class and silently overwrites
the registration" bug. `_load_configs_from_dir` now warns and last-wins on
instance-name collision **within one type** (previously indistinguishable
from a cross-type collision — now it can't happen, and the true within-type
collision is at least visible). New `get_instance(type_name, instance_name)`
method, used by the shim. `list()` still returns the same flat
`[{"name", "type", "connected"}]` shape. `soar/connectors/es_http/` (the
empty ghost directory mentioned in the spec) did not exist in this checkout
— nothing to delete.

### 2. Lazy shims + `ConnectorProxy` (E6 + E3, one PR)

New `soar/connectors/_proxy.py::ConnectorProxy` wraps every public method
call of a `BaseConnector` instance: logs `SOAR_AUDIT_EVENT` to the job log
(loguru, whatever sink is configured — in production that's the job log
file per the Runner contract), redacts `HIDDEN_FIELDS` in the logged kwargs
(not in the real call), and blocks calls to methods declared in
`MUTATING_METHODS` when `soar.runtime_state.is_dry_run()` is true. New
`soar/runtime_state.py` holds the process-wide `dry_run` flag (one
`soar.runner` subprocess = one job, so this is safe). `soar/runner.py::main()`
calls `set_dry_run(bool(context.get("dry_run", False)))` right after
parsing `context`, before `workflows.execute()`.

`ConnectorRegistry.init()` now calls `_install_shims()` as its last step,
installing a `__getattr__` on `sys.modules["soar.connectors.<type>"]` for
every discovered type — so `from soar.connectors.<type> import <instance>`
resolves lazily to a `ConnectorProxy`. A typo in the instance name raises
`AttributeError` at the import site, not deep inside a workflow at call
time. `ConnectorRegistry.__getattr__` (the flat `connectors.<instance>`
path) was also changed to return `ConnectorProxy` instead of the raw
instance — there is now no public path that hands out a raw
`BaseConnector`.

`BaseConnector` gained `MUTATING_METHODS: ClassVar[set[str]] = set()`
(same convention as `HIDDEN_FIELDS`). All 24 connectors were reviewed and
given a concrete set — see "Judgment calls" below for the reasoning and the
full per-connector list.

Workflow/action templates (`orchestrator/api/workflows.py::TEMPLATES`,
`orchestrator/api/actions.py::ACTION_TEMPLATE`) got a `# from
soar.connectors.<type> import <instance>` comment line above the existing
`from soar.connectors import connectors` line — both paths are shown since
the template can't know which connector type is actually configured.

### 3. Audit trail: job log → `AuditLog`

New `orchestrator/core/audit_parse.py::parse_audit_events(log_text)` —
regex-based, scans for `SOAR_AUDIT_EVENT` lines, returns
`{"target", "dry_run", "duration_ms", "outcome", "job_id", "args", "kwargs"}`
per event (`args`/`kwargs` stay as the raw already-redacted string, not
re-parsed into structures, per spec [S6] — deliberately, to avoid a second
injection/parsing risk).

`orchestrator/audit/service.py::record_job_event(db, *, job, action,
resource_id, detail)` — the no-`Request` sibling of `record()`, same
synthetic-actor pattern as webhook-triggered `job.create`
(`actor_type="service"`, `actor_name=f"job:{job.workflow_name}"`).

`Worker.__init__` gained an optional `db_session_factory=None` parameter,
threaded through `WorkerPool.__init__` and `orchestrator/main.py`'s
`WorkerPool(...)` construction (`app.state.db_session_factory`).
`Worker._execute`, right after the existing B4 `result_data` parsing block,
reads the job log again, calls `parse_audit_events`, and — if
`db_session_factory` is set — opens a session and calls `record_job_event`
per event. Wrapped in `try/except Exception`, logs a warning on failure:
audit is observability, a parsing/DB error must never flip the job to
FAILED.

### 4. Actions: multiple exports per file (E7)

`soar/actions/__init__.py::_discover`/`_discover_external` now register
**every** public top-level callable whose `__module__` matches the file
(not just the one matching the filename). Collision between two files
exporting the same name — last-wins with a warning, same pattern as the
connector registry. `_discover_external` iterates `sorted(...)` now
(determinism for the collision case, matching the fix already applied to
connector config loading in section 1).

`orchestrator/api/actions.py::list_actions` was rewritten to be AST-only —
it never imports `actions_dir` content. Per spec [S7], this is
deliberate: after Phase 1's runtime boundary, importing user code from the
orchestrator process is off-limits (that's `soar.runner`'s job, in the
content venv); the real multi-export `ActionsRegistry` is only ever
instantiated inside `soar.runner`. The new `list_actions` walks
`actions_dir`, runs `parse_functions` (already existed in
`introspect.py`) per file, and emits one record per public function:
`{"name": fn_name, "file": filename_without_ext, "summary": ...}`. The old
`_describe_action_summary` helper (which re-parsed the same file a second
time, looking only for the filename-matching function) was deleted —
folded into the single AST pass.

### 5. Explicit tools surface (E5)

`soar/tools/__init__.py::__all__ = ["http_client", "http_client_sync",
"WatermarkStore", "SeenStore", "watermark_store", "seen_store"]`.

`orchestrator/core/introspect.py::_public_names(init_path)` — AST parser
for a module's `__all__` list, same pattern as the existing
`_hidden_fields`. `orchestrator/api/tools.py::list_tools`/`get_tool` now
filter `parse_classes` results by `_public_names(tools_dir / "__init__.py")`,
and add a synthetic entry (`module: "__init__"`) for every public name that
isn't a class (the two singletons, the two factories) — `parse_classes`
can't see module-level values.

`soar/tools/openapi.py::OpenAPIGenerator` moved verbatim to
`orchestrator/core/openapi_generator.py` (its only consumer is
`orchestrator/api/connectors.py`, and it generates connector code — an
orchestrator-side mechanism, not a workflow-runtime tool). The old file was
deleted outright, no re-export shim (per `CLAUDE.md`). The test file moved
with it: `tests/soar/tools/test_openapi.py` →
`tests/orchestrator/core/test_openapi_generator.py`.

`soar/tools/watermark.py` gained `watermark_store(name)` /
`seen_store(name, ttl=86400)` factories. Path comes from a new
`SoarConfig.state_dir` field (`orchestrator/config.py`, default
`/app/data/state`; `orchestrator/config.yaml` sets it to `/app/soar/state`
to match the existing `workflows_dir`/`connectors_dir`/`actions_dir`
convention there). The factories read `soar.state_dir` the same way
`soar/runner.py` already reads the rest of `config.yaml` — raw
`SOAR_CONFIG`-pointed YAML parse, no import of `orchestrator.config`
(`soar/` must not depend on `orchestrator/`, same rule already documented
in `http_client.py`'s SSRF-guard docstring).

### 6. Migrated the remaining 7 `requests`/`httpx` connectors to `http_client_sync`

`censys`, `crtsh`, `fofa`, `security_onion`, `urlhaus`, `wazuh`, `freeipa` —
all off raw `requests`/bare `httpx.Client` sessions now, using the shared
`http_client_sync` singleton (logging, SSRF guard, optional cache — the
same contract `abusech`/`rstcloud`/`kaspersky_opentip` already had from the
prior http-client-sync-facade track). Three real gaps in the facade's
contract surfaced while doing this — see "Deviations" below:
`SyncHttpClient` gained a `put_json` method (wazuh needed PUT), and
`security_onion.get_pcap`/`freeipa`'s login handshake stay on direct
`httpx.Client` calls for reasons specific to those two connectors.

## Judgment calls

### `MUTATING_METHODS` per connector

Went by method semantics — anything that sends/creates/deletes/modifies/
executes/writes external state is mutating; `get_*`/`search`/`list_*`/
`query` without side effects are not:

| Connector | `MUTATING_METHODS` |
|---|---|
| abusech, censys, crtsh, fofa, kaspersky_opentip, rstcloud, security_onion, shodan | `set()` — all read-only |
| active_directory | `modify_attribute`, `add_user`, `disable_user` |
| elastic | `index`, `delete`, `bulk`, `update`, `indices_create`, `indices_delete` |
| file | `write`, `write_json`, `append`, `delete` |
| freeipa | `user_add`, `user_disable`, `user_enable` |
| misp | `add_event`, `delete_event`, `add_attribute`, `add_sighting` |
| mssql, mysql, postgresql | `execute_raw`, `execute_many` (both always `commit()`; plain `execute` stays unmarked — used internally by `tables`/`columns` for `SELECT`, and arbitrary-SQL risk from `execute` itself is a pre-existing, out-of-scope concern) |
| smb_rpc | `upload_file`, `delete_file` (`download_file` reads from the remote share, writes only to local disk — not mutating from the external-system point of view) |
| smtp | `send_email`, `send_text`, `send_html` |
| ssh | `exec_command`, `put_file` (`get_file`/`list_dir` are reads) |
| telegram | `send_message`, `send_photo`, `send_document`, `send_animation` |
| urlhaus | `tag_url` |
| virus_total | `upload_file` |
| wazuh | `restart_agent` |
| winrm | `exec_command`, `upload_file`, `run_ps` (`download_file` is a read) |

### `SOAR_AUDIT_EVENT` line format / regex

Pinned down together, per spec instruction:

```
SOAR_AUDIT_EVENT connector.call target=<type>.<instance>.<method> args=<repr> kwargs=<repr> duration_ms=<int> outcome=<ok|error:ExcName> job_id=<id>
SOAR_AUDIT_EVENT connector.call.dry_run target=<type>.<instance>.<method> args=<repr> kwargs=<repr> job_id=<id>
```

Regex (`orchestrator/core/audit_parse.py`):

```python
_EVENT_RE = re.compile(
    r"SOAR_AUDIT_EVENT connector\.call(?P<dry_run>\.dry_run)? "
    r"target=(?P<target>\S+) args=(?P<args>.*?) kwargs=(?P<kwargs>.*?)"
    r"(?: duration_ms=(?P<duration_ms>\d+) outcome=(?P<outcome>\S+))?"
    r" job_id=(?P<job_id>\S*)\s*$"
)
```

The optional `duration_ms=`/`outcome=` group naturally fails to match on
dry-run lines (those fields aren't written), so one regex parses both
variants. Not anchored to line start — the writer's loguru sink prepends a
timestamp/level/logger-name prefix (or nothing, in tests using the default
sink), and the parser doesn't care what that prefix looks like, only that
`SOAR_AUDIT_EVENT` appears somewhere on the line. Verified against a
sanity check with nested `args`/`kwargs` containing lists/dicts with
commas and spaces — the literal `" kwargs="`/`" duration_ms="`/`" job_id="`
markers are enough to anchor the non-greedy groups correctly for any
realistic Python `str()` repr.

### `WatermarkStore`/`SeenStore` path source

`SoarConfig.state_dir` (new field, `orchestrator/config.py`), read from
`soar/tools/watermark.py` via the same raw-YAML pattern `soar/runner.py`
already uses (see section 5 above) — not a new "second config reader",
same mechanism reused.

### `Worker.db_session_factory` threading

Checked constructor call sites first: `WorkerPool` is the only place that
constructs `Worker` (`orchestrator/core/worker_pool.py`), and
`orchestrator/main.py::lifespan` is the only place that constructs
`WorkerPool`. Both got the new optional parameter; `app.state.db_session_factory`
(already built earlier in `lifespan`, used by `get_db`) is threaded straight
through. `tests/orchestrator/api/conftest.py`'s own `WorkerPool(...)` call
doesn't pass it — that's fine, it's optional and defaults to `None` (audit
disabled), which is correct for tests that don't need it.

## Deviations from the spec / things that didn't quite fit reality

Flagging these explicitly, as asked — none are silent workarounds, all are
called out in code comments at the point they matter too.

1. **`SyncHttpClient` needed a `put_json` it didn't have.** The spec's [S9]
   says "migrate censys/crtsh/fofa/freeipa/security_onion/urlhaus/wazuh the
   same way as abusech/rstcloud/kaspersky_opentip" — but those three are
   all static-header GET-only auth. `wazuh.restart_agent` is a PUT. Rather
   than leave `restart_agent` on raw `requests` (inconsistent, and the one
   truly mutating wazuh method would be the one method *not* going through
   the shared SSRF-guard/logging facade), I added a minimal `put_json` to
   `SyncHttpClient` (`soar/tools/http_client.py`), mirroring `post_json`
   exactly (never cached, same log format). Tested the same way
   `post_json` is tested (`tests/soar/tools/test_http_client.py`).

2. **`security_onion.get_pcap` returns raw bytes, not JSON.**
   `SyncHttpClient.get_json`/`post_json`/`put_json` all call `resp.json()`
   unconditionally — there's no facade method for a binary/pcap download.
   Rather than expand the facade's contract for one caller, `get_pcap`
   stays on a direct `httpx.Client` call (no `requests` — that dependency
   is fully gone from this connector). `self._base_url` is operator config,
   not per-call user input, so this doesn't introduce an SSRF gap that
   didn't already exist for every other connector's `host`/`port` fields.

3. **`freeipa`'s auth model is fundamentally incompatible with the
   facade's per-call `httpx.Client()` lifecycle.** This is the one real
   "spec doesn't fit reality" finding, closest in spirit to what Phase 1's
   agent found. FreeIPA's JSON-RPC API authenticates via a session
   **cookie** returned by `/session/login_password` — every subsequent
   call must resend that cookie. `abusech`/`rstcloud`/`kaspersky_opentip`
   (the reference pattern) all use a static header built from a
   config-time API key; none of them have a login step at all.
   `SyncHttpClient.get_json`/`post_json` open a fresh `httpx.Client()`
   per call and never expose the response's cookies to the caller, so
   there is no way to carry a session cookie through the shared facade as
   currently shaped. Resolution: `_connect_impl` does the one login POST
   directly via `httpx.Client` (with the same SSRF guard,
   `soar.tools.http_client._validate_external_url`, called by hand) and
   captures `resp.cookies["ipa_session"]`; every actual JSON-RPC call
   (`user_find`, `user_add`, ...) goes through `http_client_sync.post_json`
   with that cookie forwarded as a `Cookie:` header. This gets the bulk of
   FreeIPA traffic (everything workflows actually call) onto the shared
   logged/guarded path, at the cost of the one-time login handshake not
   going through it. Extending the facade to support cookie jars was
   judged out of scope for a single connector's auth model — flagging it
   here rather than silently working around it, per the task's request.

4. **`urlhaus`'s wire format changed from form-encoded to JSON.** The
   original `urlhaus.py` POSTed `application/x-www-form-urlencoded` bodies
   (`data=` kwarg on `requests`). `SyncHttpClient.post_json` only sends
   `application/json` bodies. This is not a new precedent, though — the
   `abusech` connector (migrated in the prior http-client-sync-facade
   phase, already on `main`) hits the *same* abuse.ch API family
   (`URLHAUS_API = "https://urlhaus-api.abuse.ch/v1/"`) and already sends
   JSON via `http_client_sync.post_json`. I followed the same already-
   accepted tradeoff for consistency rather than re-litigating it for the
   standalone `urlhaus` connector.

## Testing

New/changed test files (test-first throughout — each new assertion set was
run against the pre-change code and confirmed failing before implementing):

- `tests/soar/test_connector_registry.py`, `tests/soar/test_connector_proxy.py`,
  `tests/soar/test_runtime_state.py`, `tests/soar/test_connectors_init.py`
- `tests/orchestrator/core/test_audit_parse.py`,
  `tests/orchestrator/test_worker_audit_events.py`
- `tests/soar/test_actions_registry.py`,
  `tests/orchestrator/api/test_actions_api.py` (extended in place — see
  note below)
- `tests/orchestrator/api/test_tools_api.py` (extended in place),
  `tests/soar/tools/test_watermark.py`,
  `tests/orchestrator/core/test_openapi_generator.py` (moved from
  `tests/soar/tools/test_openapi.py`)
- `tests/soar/test_{censys,crtsh,fofa,freeipa,security_onion,urlhaus,wazuh}_connector.py`
  (rewritten or newly created), `tests/soar/tools/test_http_client.py`
  (added `put_json` coverage)

**Deviation from the plan's suggested filenames:** the plan's Testing
Strategy names `tests/orchestrator/api/test_actions_routes.py` and
`test_tools_routes.py` as new files. Both routes already had test files
(`test_actions_api.py`, `test_tools_api.py`) with existing, overlapping
coverage — I extended those in place instead of creating parallel files
that would duplicate the same route surface under a different name.

## Verification

```
python -m pytest tests/ -q
```
Baseline on `main` (before this phase): **808 passed, 3 failed (Redis
integration, needs a live Redis container — pre-existing/environmental,
unrelated), 1 skipped.**
After this phase: **894 passed, 3 failed (same 3 Redis tests), 1 skipped.**
Zero new failures; 86 new tests, all passing.

```
python -m pytest tests/soar/test_*_connector.py -q
```
149 passed (full sweep of all 24 connector test files).

```
ruff check .
```
Baseline on `main`: 43 pre-existing findings (17 F401, 13 I001, 8 P012, 2
P045, 2 B904, 1 F841), none in files this phase touches in a way that's my
responsibility to fix. After this phase: 40 findings — all still
pre-existing, in files I never touched (`orchestrator/core/subprocess_runner.py`,
`orchestrator/core/queue/redis_queue.py`, and a handful of test files
covering Redis/rate-limiter/subprocess-env scenarios). The 2 findings I did
introduce along the way (`B009`/`B018` in a new test file, `I001` in the
moved openapi test file) are fixed. `orchestrator/api/connectors.py` (2
pre-existing `B904`) and `soar/connectors/active_directory/active_directory.py`
(1 pre-existing `I001`) are both files this phase touches but the findings
predate my edits — left alone per "don't refactor outside the task."

Docker verification: not required for this phase (no Dockerfile changes) —
none were made.
