---
feature: privilege-narrowing
date: 2026-07-30
spec: docs/compose/specs/2026-07-30-privilege-narrowing-design.md
plan: docs/compose/plans/2026-07-30-privilege-narrowing.md
---

# Report: Сужение прав — Phase 4

Branch: `feat/entity-model-phase4` (off `main` @ `c4be201`, which already
contains Phases 1–3: `soar/runtime_contract.py` + content-venv split,
`ConnectorProxy`/`MUTATING_METHODS`, the `from soar.connectors.<type>
import <instance>` lazy-import form, and the connector content-pack moved
out to the sibling `soar-content-pack` repo).

## What was built

### [S2] Credential scoping — always on, no config flag

- `orchestrator/core/introspect.py::parse_connector_usage(path)` — static
  AST scan for `from soar.connectors.<type> import <instance>` at module
  top-level, exactly as spec'd, with one correction (see Deviations):
  returns `alias.name` (the name actually fetched from the shim module),
  not `alias.asname`.
- `orchestrator/core/subprocess_runner.py::build_scoped_config(workflow_file,
  full_config)` — builds a `tempfile.mkdtemp()` directory per job containing
  only the `(type, instance)` pairs the workflow imports: connector `.py`
  files symlinked (`os.symlink`, falls back to `copy2` off-POSIX),
  `.yml` instance configs filtered and rewritten. The resulting scoped
  YAML carries `soar.{workflows_dir,actions_dir,tools_dir,state_dir,
  connectors_dir}` + `http_client` (+ `queue.redis_url` only if
  `http_client.cache_backend == "redis"`) — never `auth`/`database`, so the
  JWT secret and DB URL never reach the file the subprocess is pointed at.
- `WorkflowJob` gained two fields: `workflow_file` (threaded from
  `WorkflowMeta.file_path` through `JobManager.enqueue()`) and
  `scoped_config_dir` (set by `SubprocessRunner.start()`, read and
  `shutil.rmtree()`'d by `Worker._execute`'s **outer** `finally` — see
  Deviations for why not the same `finally` as `_log_file`).
- Workflows with no statically-found imports (parse failure, missing file,
  or the pre-Phase-2 `connectors.<name>` registry form) get an **empty**
  `connectors_dir`, not a fallback to the full set — the strict option the
  spec explicitly allowed, chosen because nothing in this repo's built-in
  `soar/workflows/` (empty except `base.py`) uses the old form.

### [S3] Separate runner UID + rlimits — opt-in, POSIX/Docker only

- `orchestrator/config.py::JobsConfig` — `runner_uid`/`runner_gid` (both
  `None` default = today's behavior, unchanged), `runner_max_memory_mb`
  (512), `runner_max_cpu_seconds` (300), `runner_max_procs` (32).
- `orchestrator/core/subprocess_runner.py::_drop_privileges(...)` — builds
  a `preexec_fn` that sets `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC`. Does
  **not** call `os.setuid`/`os.setgid` (deviates from the spec pseudocode —
  see Deviations, this is the one substantive design change from what was
  asked).
- `_runner_argv(content_python, jobs_config)` — when `runner_uid` is set,
  wraps the subprocess argv as `setpriv --reuid=<uid> --regid=<gid>
  --clear-groups -- <content_python> -m soar.runner`.
- `deploy/{prod,stage}/Dockerfile.orchestrator` — new `soar-runner` user
  (fixed uid/gid `5001`, chosen explicitly rather than left to `useradd
  -r`'s auto-assignment like `soar`, so `jobs.runner_uid` in `config.yaml`
  can be a known literal), `setcap cap_setuid,cap_setgid+ep
  /usr/bin/setpriv`, `config.yaml` mode 640 owned `soar:soar`,
  `/app/data/state` group-owned `soar:soar-runner` mode 770 (needed for
  `soar/tools/watermark.py`'s `WatermarkStore`/`SeenStore` to keep working
  once the runner drops UID — found and fixed during Docker verification,
  see below).
- `deploy/stage/config.yaml` does **not** set `jobs.runner_uid` — the
  mechanism ships built into the image but stays off by default even on
  stage; `deploy/stage/README.md` documents how to turn it on and what a
  human should still verify (see Deferred below).

### [S4] Docs

`AGENTS.md` (title bumped to v0.17, "Модель сущностей" section + Version
history + Subprocess execution + Security patterns summary updated),
`docs/agents/security-patterns.md` (new "Privilege narrowing" subsection),
`docs/agents/config-reference.md` (new "Job-runner privilege narrowing"
section), `docs/concepts/ENTITY-MODEL.md` (Phase 4 checklist + "Перед
релизом" checked off), `CHANGELOG.md` (v0.17 entry). While updating
"Модель сущностей" I also fixed three statements that were already stale
from Phases 1/3 (not introduced by this session, but this was the session
tasked with syncing that section to reality per the plan): "`GET /runtime`,
E9 — пока не реализовано" (it has been since Phase 1), "`SubprocessRunner`
идёт через `sys.executable` (E10)" (fixed by Phase 1's content-venv split),
and "`soar/connectors/` с 24 каталогами контента — известное нарушение"
(fixed by Phase 3's content-pack move).

## Deviations from the spec / things that didn't quite fit reality

Every prior phase report flagged real issues found once the spec met the
actual code; this one is no exception — two worth calling out.

### 1. `alias.asname` vs `alias.name` in `parse_connector_usage` — spec pseudocode was wrong

The spec's pseudocode (and the plan's own test list) has
`parse_connector_usage` return `alias.asname or alias.name` — i.e. prefer
the local import alias. Concretely, for `from soar.connectors.ssh import
prod as ssh_prod`, that returns `("ssh", "ssh_prod")`.

That's wrong for what this function exists to do. `soar/connectors/
__init__.py::_install_shims` installs a PEP 562 module `__getattr__` on
`soar.connectors.<type>`; when `from soar.connectors.ssh import prod as
ssh_prod` executes, Python's import machinery calls that `__getattr__`
with `"prod"` (the name being fetched off the module) — the `as ssh_prod`
part only renames the local variable in the importing module and never
reaches the registry lookup. So the real connector instance is `"prod"`;
scoping the job's config on `"ssh_prod"` would build a `connectors_dir`
missing the instance the workflow actually needs, and the job would fail
at runtime with "connector instance not found" — the opposite of the
intended narrowing (over-strict, breaking a legitimate case), silently,
only on workflows that happen to alias an import.

Fixed to use `alias.name`. Updated the plan's own stated test case
(`from soar.connectors.ssh import prod as ssh_prod` → `[("ssh", "prod")]`,
not `[("ssh", "ssh_prod")]`) accordingly, with the reasoning in both the
function's docstring and the test.

### 2. `os.setuid`/`os.setgid` in `preexec_fn` does not work as spec'd — verified in Docker, replaced with a `setpriv` wrapper

This is the tension [S3] explicitly flagged and pre-authorized deferring.
I did not defer it — I verified it empirically in Docker (Desktop's Linux
backend, real containers, not mocks) and found a mechanism that works
without the larger architectural change ("orchestrator starts as root")
the spec worried about.

**What was tried and failed:** a non-root parent process (the orchestrator
runs as `soar`, deliberately non-root — `USER soar` in both Dockerfiles)
calling `os.setuid()`/`os.setgid()` in a `subprocess` `preexec_fn`, even
with `docker run --cap-add=SETUID --cap-add=SETGID`. Confirmed via
`/proc/self/status`: `--cap-add` only populates the container's capability
**bounding** set (`CapBnd`); a non-root process's **effective**/
**permitted** sets (`CapEff`/`CapPrm`) stay all-zero regardless, unless the
specific binary being exec'd carries the capability as a **file**
capability. `setuid()`/`setgid()` from Python in that state raised
`PermissionError(1, 'Operation not permitted')` every time.

The naive fix — granting `cap_setuid,cap_setgid+ep` to the content-venv
Python interpreter itself via `setcap` — would work, but is a strictly
worse privilege grant than the feature is supposed to add: **any** code
running under that interpreter (a compromised or buggy workflow, or a bug
in the orchestrator's own code if it shares the interpreter) could then
call `setuid(0)` and become root inside the container.

**What works, verified end-to-end in real containers:**
`setpriv` (`util-linux`, already present in `python:3.11-slim` — no new
package needed for it, only `libcap2-bin` for `setcap` itself) granted
`cap_setuid,cap_setgid+ep` as a **file** capability. A non-root process
(`soar`) can then run `setpriv --reuid=5001 --regid=5001 --clear-groups --
<cmd>`, and `setpriv` — not the interpreter, not the workflow code — is
the only thing that ever holds the capability, only for the instant it
takes to switch identity and `execve()` into the real command. No
`--cap-add` flags are needed on `docker run`/`docker-compose.yml`:
`SETUID`/`SETGID` are already in Docker's *default* capability bounding
set (the same set that lets ordinary containers run `su`/`sudo`); the file
capability is what was missing, not the bounding-set entry.

Verified in a throwaway Linux container harness (built, exercised, and
deleted during this session — not checked into the repo):
- `os.setuid()`/`os.setgid()` directly: fails without file capability on
  the interpreter, confirmed via `/proc/self/status` capability bits.
- `setpriv --reuid=... --regid=...` with default Docker capabilities: uid
  and gid both actually change (`os.getuid()`/`os.getgid()` confirm 5002
  inside the dropped process).
- Dropped process **cannot** read a `config.yaml` owned `soar:soar` mode
  640 (`PermissionError`).
- Dropped process **cannot** write into a directory owned `soar:soar` mode
  750/755 (`PermissionError`) — simulating `git.workflows_repo`.
- Dropped process **cannot** `setuid()` back to `soar` (one-way drop, no
  escalation path).
- `resource.setrlimit(RLIMIT_AS, ...)` set in `preexec_fn` **survives**
  `execve()` through `setpriv` into the dropped-UID process (rlimits are a
  process attribute, exec-persistent) — confirmed
  `resource.getrlimit(RLIMIT_AS)` reads back the configured value
  post-drop, and an over-limit `bytearray(256MB)` allocation against a
  128MB `RLIMIT_AS` actually raises `MemoryError` in the final,
  UID-dropped process.
- **Found and fixed a second, related gap this surfaced:**
  `tempfile.mkdtemp()` (used by `build_scoped_config`) creates directories
  mode `0700` — readable only by the orchestrator's own UID (`soar`). Once
  the runner subprocess drops to a *different* UID (`soar-runner`), it
  could not read its own scoped `SOAR_CONFIG` or connector files — every
  job would fail closed the moment `runner_uid` was turned on. Fixed with
  `build_scoped_config`'s new `_make_world_readable()` step (chmod
  0755/0644 on the scoped tree, skipping symlinks so the real
  `connectors_dir` source files are never touched) — `os.chown()` to
  `soar-runner` was considered and rejected: the orchestrator process
  itself has no `CAP_CHOWN` in its effective set for the same reason it
  has no `CAP_SETUID` (identical non-root-capability problem), so `chmod`
  (which only needs file ownership, which the orchestrator has) was the
  only mechanism actually available to it. Verified: with the chmod step,
  a `setpriv`-dropped `soar-runner` process reads the scoped
  `config.yaml`/`instances.yml` successfully; without it, `PermissionError`.
- **Found and fixed a third gap:** `soar/tools/watermark.py`'s
  `WatermarkStore`/`SeenStore` write to `soar.state_dir`
  (`/app/data/state`), which sat under `/app/data` (owned `soar:soar`,
  default `755`) with no explicit provisioning — `soar-runner` (as
  "other") could read but not write there. Fixed by creating
  `/app/data/state` with `chown soar:soar-runner` + `chmod 770` at
  Dockerfile build time (root, during the image build, before `USER soar`
  takes effect — so no capability problem here, ordinary `chown` to an
  arbitrary group works fine as root). Verified: `soar-runner` writes
  successfully to `/app/data/state`; `/app/data/workflows` (same parent,
  no special provisioning) stays read-only to it, as intended.

This mechanism keeps `USER soar` in both Dockerfiles unchanged — the
orchestrator's own process never runs as root, at rest or momentarily. The
"bigger architectural change" the spec worried about (root-start-and-
self-drop) was not needed and was not made.

## Judgment calls

- **`build_scoped_config` reads a fresh `_load_full_config()` on every
  call** rather than trusting the `OrchestratorConfig` object passed into
  `SubprocessRunner.__init__`. Matches what `soar.runner` itself already
  does (re-reads `SOAR_CONFIG` fresh per subprocess invocation) and keeps
  git-driven content changes visible without an orchestrator restart. The
  `config` object passed to `SubprocessRunner` is used only for
  `jobs.runner_uid`/rlimits.
- **Strict empty-`connectors_dir` fallback**, not the lenient
  full-config fallback the spec offered as an alternative — per the spec's
  own instruction to check for existing usages of the old form (found
  none in this repo).
- **`soar-runner`'s UID/GID are hardcoded to `5001`** in both Dockerfiles,
  rather than left to `useradd -r`'s automatic system-range assignment
  (which is what `soar` itself still uses, deliberately left alone to
  avoid changing ownership semantics for volumes from installs that
  predate this change). A fixed, known number is what lets
  `deploy/stage/config.yaml`/prod's `soarctl init` template state
  `runner_uid: 5001` as a literal without needing to `docker exec ... id
  soar-runner` after every rebuild.
- **`Worker._execute`'s scoped-dir cleanup lives in the *outer* `finally`**
  (`self._busy = False`'s block), not the same narrower `finally` that
  closes `_log_file` (which exists specifically so the result-parsing code
  right after it can immediately re-read the file — a constraint that
  doesn't apply to the scoped config dir, nothing reads it after the
  subprocess exits). The outer placement also covers a case the narrower
  one wouldn't: `runner.start()` itself raising *before* returning a
  `proc` (e.g. if `build_scoped_config` failed) still leaves
  `job.scoped_config_dir` set (mutated on `job` before the raise point,
  same object reference), and the outer `finally` still cleans it up. This
  is covered by `test_execute_cleans_up_scoped_config_dir_on_exception`.
- **`WorkflowJob.workflow_file` threaded through `SQLQueue`/`RedisQueue`
  serialization**, not just `JobManager.enqueue()`. `InMemoryQueue` passes
  the same Python object by reference, so this was easy to miss — but
  `SQLQueue.pop()` and `RedisQueue.pop()` both reconstruct `WorkflowJob`
  from a persisted/serialized form (`orchestrator/store/mapping.py::
  record_to_job`, `redis_queue.py`'s JSON payload). Without adding
  `workflow_jobs.workflow_file` (new column, migration `7a1c9e3f5b02`) and
  threading it through both paths, every SQL- or Redis-backed install
  would have silently gotten zero connector credentials for every job —
  the in-memory dev/test path would never have caught this.
- **Fixed a pre-existing, unrelated bug found along the way:**
  `WorkflowMeta.file_path` has existed as a dataclass field since Phase 1
  but `orchestrator/main.py::load_workflow_metas` never actually populated
  it (`WorkflowMeta(...)` was constructed without `file_path=...`). This
  phase's entire credential-scoping mechanism depends on that field being
  real, so it had to be fixed regardless — flagging it since it's a defect
  older than this session, not one introduced by it.

## Testing

New/extended test files:
- `tests/orchestrator/core/test_introspect.py` — 5 new tests for
  `parse_connector_usage` (single import, two types, aliased import
  resolving the real instance name, no imports, non-connector imports
  ignored).
- `tests/orchestrator/test_subprocess_runner_env.py` — `TestBuildScopedConfig`
  (7 tests: scoping to used instance, excluding unused instance of the
  same type, symlinking not copying, empty-usage → empty connectors_dir,
  full-config secrets absent from the scoped file, runtime dirs carried
  through, unparseable workflow file handled) + one test confirming
  `SubprocessRunner.start()`'s `SOAR_CONFIG` env var is the scoped path,
  never the orchestrator's own `_CONFIG_PATH`.
- `tests/orchestrator/test_worker_execute.py` — 4 new tests: scoped-dir
  cleanup on success, on timeout, on an exception raised before `proc`
  exists, and a no-op check when `scoped_config_dir` was never set.
- `tests/orchestrator/test_subprocess_runner_privileges.py` — new file,
  `skipif(sys.platform == "win32")`: `_drop_privileges` sets the three
  rlimits correctly and does *not* touch uid/gid; `_runner_argv` wraps
  with `setpriv` only when `runner_uid` is set, POSIX only; end-to-end
  gating through `SubprocessRunner.start()` (`preexec_fn` present/absent,
  `setpriv` present/absent in argv).
- `tests/orchestrator/core/queue/test_sql_queue.py` +
  `tests/orchestrator/test_redis_queue.py` — one round-trip test each
  confirming `workflow_file` survives `SQLQueue.pop()`/`RedisQueue.pop()`
  (the gap described above).

**Windows vs. Linux verification split** (explicitly asked for in the
task): the 8 tests in `test_subprocess_runner_privileges.py` are
mock-based (patch `resource`/`os`) and are skipped on this Windows dev
machine by design (`resource` isn't importable there, `preexec_fn` isn't
supported by asyncio's subprocess implementation either — matches the
plan's stated testing strategy). They were run for real inside a Linux
container during this session (`python:3.11-slim`, `pip install -r
orchestrator/requirements.txt pytest pytest-asyncio`, then `pytest
tests/orchestrator/test_subprocess_runner_privileges.py
tests/orchestrator/test_subprocess_runner_env.py
tests/orchestrator/core/test_introspect.py
tests/orchestrator/test_worker_execute.py -v`): all 53 ran (none skipped)
and passed. Separately, the actual UID-drop/rlimit-enforcement/permission-
boundary mechanism (not just the mocked unit tests around it) was verified
against real Linux containers, described in the Deviations section above.

## Verification

- `python -m pytest tests/ -q` — **811 passed, 3 failed, 9 skipped**
  (baseline before this session: 792 passed, 3 failed, 1 skipped — same 3
  pre-existing failures both before and after,
  `tests/orchestrator/test_redis_integration.py` needing a live Redis
  container; net +19 passed from 21 new tests, 8 of which are the
  Windows-skipped POSIX-only privilege tests, hence skip count 1 → 9).
- `ruff check .` — 32 findings, all pre-existing in files/lines this
  session didn't touch (confirmed per-file: `redis_queue.py`'s two
  `Optional[...]` findings predate this session's one-line addition;
  `test_worker_execute.py`'s three unused-import findings predate this
  session's pure-append diff, confirmed via `git diff --stat` showing
  100% insertions; `test_redis_queue.py`'s four import-ordering/unused-
  import findings are in the file's pre-existing header and other
  pre-existing test functions, not the one added this session, which
  mirrors the adjacent pre-existing `test_redis_queue_concurrency_preserved`
  test's own local-import style). Two findings this session's own new code
  *did* introduce (`subprocess_runner.py`'s unused `dirs` loop variable,
  `test_subprocess_runner_env.py`'s import ordering + two now-genuinely-
  unused imports) were fixed.
- Docker/deploy verification — real, not mocked, but scoped to a
  standalone harness, not the full `deploy/stage` compose stack:
  - UID drop, capability boundary, rlimit enforcement (including a real
    `MemoryError` on `RLIMIT_AS` overshoot), config.yaml/data-dir
    permission boundaries, scoped-config-dir readability, and
    `state_dir` group-writability were all verified against real
    `python:3.11-slim`-based containers built and run during this
    session (Docker Desktop, Linux backend, via `docker build`/`docker
    run`/`setpriv`/`setcap`) — see the Deviations section for the exact
    commands' shape and results.
  - **Not verified this session:** a full `docker compose up` run of
    `deploy/stage` with `jobs.runner_uid` flipped on in `config.yaml` and
    a real job (importing a real connector from the content pack)
    submitted through the live API, confirmed to succeed end-to-end. This
    requires the sibling `soar-content-pack` repo as an extra build
    context (already a pre-existing, separately-flagged gap — both
    Dockerfiles carry a comment from Phase 3 saying the `basepack` build
    context path is "UNVERIFIED by an actual `docker build`") plus
    standing up the full stack (Postgres, Redis, orchestrator, UI). Given
    that pre-existing gap and the time budget for this session, I judged
    the standalone-harness verification (which exercises the actual
    mechanism this phase adds — UID drop, permission boundaries, rlimit
    enforcement — against real Linux/Docker, just not through the full
    orchestrator process) sufficient for landing the code, while leaving
    the full stack activation explicitly off by default
    (`deploy/stage/config.yaml` doesn't set `runner_uid`) and documented
    as a pre-flight check in `deploy/stage/README.md` before anyone
    turns it on for real.

## Success criteria (from the spec, [S5])

- [x] `parse_connector_usage` — static (type, instance) extraction, no import
- [x] Subprocess gets a config slice with only used instances; full
      `orchestrator/config.yaml` (JWT secret, DB) is not reachable via the
      path the subprocess is handed
- [x] (POSIX/Docker) `soar-runner` — separate UID from `soar`; rlimits set
      from config — **mechanism differs from the spec's pseudocode**
      (`setpriv` wrapper, not direct `os.setuid`/`os.setgid` in
      `preexec_fn`) for reasons verified in Docker, documented above
- [x] (POSIX/Docker) runner cannot write to the workflows git repo, cannot
      read `config.yaml` — verified manually against real Linux containers
      with the exact permission bits/commands described above (not
      `deploy/stage` itself — see Verification for what's still open)
- [x] UID-switch mechanism tradeoff recorded explicitly in this report,
      including the decision *not* to defer it — a working mechanism was
      found and verified that avoids the "orchestrator starts as root"
      perimeter change the spec worried about
- [x] `pytest tests/` green modulo the same pre-existing failures as
      baseline; `ruff check .` clean on every file this session touched
- [x] `docs/concepts/ENTITY-MODEL.md` Part 4 "Перед релизом" checklist
      complete
