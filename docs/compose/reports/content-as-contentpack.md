---
feature: content-as-contentpack
date: 2026-07-30
spec: docs/compose/specs/2026-07-30-content-as-contentpack-design.md
plan: docs/compose/plans/2026-07-30-content-as-contentpack.md
---

# Report: Контент как контентпак — Phase 3

Branch: `feat/entity-model-phase3` (off `main` @ `8ddb546`, which already
contains Phase 1 — `soar/runtime_contract.py`, content-venv — and Phase 2 —
`soar/connectors/_proxy.py::ConnectorProxy`, `MUTATING_METHODS`,
`ConnectorRegistry` namespaced by type).

**New sibling repository:** `D:\projects\soar-content-pack` — `git init`,
**no remote configured**, local-only. It is a genuinely separate
repository, not a submodule or subdirectory of this one; its git history
starts fresh at this phase (one commit as of this report:
`c9981aa Initial import: 24 base connectors moved from soar/connectors/ (Phase 3, entity-model plan)`).
It is not pushed anywhere — nothing to clone, nothing to fetch.

## What was built

All 6 sections of the plan, in order.

### 1. Manifest + generator

`soar-content-pack/tools/gen_manifest.py` — AST-based, never imports a
connector. For every `connectors/<name>/<name>.py`: walks top-level
`ast.Import`/`ast.ImportFrom` nodes, drops standard-library module names
(`sys.stdlib_module_names`) and anything rooted at `soar` (platform
imports, always available regardless of where connector code physically
lives — not something a pack declares), keeps the rest as `imports:`.
Separately reads the class-level `MUTATING_METHODS` set via
`ast.Assign`/`ast.AnnAssign`, same pattern `orchestrator/core/introspect.py`
already uses for `HIDDEN_FIELDS`. Verified against real connector code: e.g.
`smb_rpc.py`'s `from smbprotocol.connection import Connection` correctly
resolves to `imports: [smbprotocol]`; `abusech.py`'s
`from soar.tools import http_client_sync` correctly resolves to `imports:
[]` (platform import, excluded).

`soar-content-pack/manifest.yaml` — generated (`python tools/gen_manifest.py
--version 1.0.0`), 24 connector entries, `runtime_version: "1"`.

### 2. Marker of origin + install planning

`orchestrator/core/pack_install.py` (new): `read_manifest`
(zip bytes → dict, for the API upload path), `read_manifest_from_dir`
(plain directory → dict, for the base-pack-baked-into-the-image path),
`check_runtime_compat` (major-version match against
`soar/runtime_contract.py::RUNTIME_VERSION`), `check_dependencies` (every
`imports:` entry must resolve to some `CONTRACT[...]["import_names"]`,
returns the missing list rather than raising — caller decides what a
non-empty list means), `plan_install` (categorizes every manifest
connector into `new`/`update`/`unchanged`/`skip_modified` by comparing the
current on-disk sha256 against `.soar-content.yaml`'s recorded sha256 and
the manifest's version against the marker's recorded version),
`apply_install`/`apply_install_dir` (writes `new`+`update`, never touches
`skip_modified`, updates the marker only for what was actually written).

`.soar-content.yaml` lives in `connectors_dir` itself (like
`orchestrator_state.yaml`, not in git): `pack`, `pack_version`,
`installed_at`, `entries: {<name>: {version, sha256}}`. `modified` is
**not** a stored field — every reader (`plan_install`, `soarctl content
list`) recomputes the current file's sha256 and compares against the
recorded one at read time, so it can never itself drift out of sync.

### 3. `soarctl content install|list|remove`

`deploy/soarctl_lib/content.py` (new) — structural mirror of `backup.py`:
one throwaway alpine container dumps `connectors/` out of the `soar-data`
volume as a tar (`tar czf - -C /data connectors`, `mkdir -p` first so an
empty volume doesn't error), the plan is computed against that in-memory
tar + the marker parsed out of it, and the write-back is a **merge**
`tar xzf - -C /data` (unlike `backup.restore_data_volume`, which does
`rm -rf /data/* &&` first — that's correct for a restore, wrong for an
install: it would delete every connector the pack doesn't mention).
`remove()` needs an actual deletion, which a merge-write tar can't do, so
it runs one extra `docker run ... rm -rf /data/connectors/<name>` before
writing the updated marker back. `_validate_name` (same
`^[a-zA-Z0-9_-]+$` shape as `orchestrator/api/validation.py::validate_name`)
guards the CLI-supplied connector name against injection into that shell
command.

Wired into `deploy/soarctl_lib/cli.py`: `content install <path> [--ref
REF]`, `content list`, `content remove <name> [--force]`.

### 4. `POST /connectors/pack/install`

New `orchestrator/api/packs.py`, `router = APIRouter(prefix="/connectors/pack",
tags=["connectors"], dependencies=[Depends(require_role("admin"))])` — one
route, `POST /install`. admin-only (not `agent`, matching `/transfer/import`'s
risk category, not the broader `_ADMIN = ("admin", "agent")` individual
connectors get). Preflight: `read_manifest` → `check_runtime_compat` →
`check_dependencies` (400 before anything is written if any is declared
outside the contract) → `plan_install`; if `plan["update"]` is non-empty
(existing, unmodified connectors that would be overwritten) and `force`
isn't set, returns `{"status": "conflicts", "conflicts": [...]}` without
writing, same shape as `/transfer/import`. On success, `apply_install` runs
and `audit.service.record(..., action="pack.install",
resource_type="connector_pack", detail={"pack_version", "installed",
"skip_modified"})` is written (names only, never file contents — same
principle `transfer.export`/`transfer.import` already follow). Registered
in `orchestrator/api/__init__.py` + `orchestrator/main.py`.

### 5. The actual move

24 connector directories copied unchanged (byte-for-byte, `cp -r`, no code
edits) from `soar/connectors/<name>/` into
`soar-content-pack/connectors/<name>/`, then `git rm`'d from this repo.
`soar/connectors/` now contains only `__init__.py`, `base.py`, `_proxy.py`
(and `.gitignore`, which also moved to the pack repo since it's about
runtime-config `.yml` files, not code). 15 of the 24 connectors'
dedicated `tests/soar/test_*_connector.py` files moved to
`soar-content-pack/tests/` alongside their code (see Deviations — the plan
assumed 24, reality is 15); the pack repo's `tests/conftest.py` puts both
the pack repo root and the sibling `soar` repo on `sys.path` so the moved
tests' `from soar.connectors.base import BaseConnector`-style platform
imports still resolve. `soar/requirements.txt` is unchanged in content,
gained a comment explaining why (Phase 1 already decided the dependency
contract describes what content-venv guarantees, not where the code using
it happens to live).

One new smoke test stays in this repo:
`tests/orchestrator/core/test_pack_install.py` exercises the full
`read_manifest → check_runtime_compat → check_dependencies → plan_install →
apply_install` pipeline against a synthetic one-connector pack (a fake
`vt`-importing connector, not real vendor code) — 18 tests, all four plan
categories plus the no-op-leaves-marker-untouched case.

### 6. Seeding moves

`orchestrator/main.py::seed_defaults()` now only `os.makedirs`s the three
data dirs — the old `shutil.copytree` connector branch is gone (nothing to
copy from anymore) and so are the workflows/actions `shutil.copy2` loops
(already dead code before this phase: `soar/workflows/`/`soar/actions/`
only ever contained `__init__.py`/`base.py`, both excluded from the copy).

New `seed_connector_pack(config)`, called right after `seed_defaults(config)`
in `lifespan()`: reads `SOAR_BASE_PACK_PATH` (default `/app/base-pack`),
skips quietly (debug log) if no `manifest.yaml` is there, otherwise runs
the exact same `check_runtime_compat` → `check_dependencies` →
`plan_install` → `apply_install_dir` pipeline `soarctl content install`
uses. **Runs on every startup**, not gated on `connectors_dir` being
empty — `plan_install` is idempotent (already-installed-and-untouched
connectors land in `unchanged`), so this is what actually closes E4: a
newer image's base pack reaches an existing installation the next time the
container restarts, not only on the very first `up`.

`deploy/{prod,stage}/Dockerfile.orchestrator`: the old
`find /app/soar/connectors ... cp -rn ...` build-time seeding block is
gone, replaced by `COPY --from=basepack . /app/base-pack/` (an extra named
build context — see Deviations) and `ENV SOAR_BASE_PACK_PATH=/app/base-pack`.
`deploy/soarctl_lib/bundle.py::build_images()` passes
`--build-context basepack=<repo_root>/../soar-content-pack` on the
orchestrator build. `deploy/stage/docker-compose.yml`'s `build:` gained
`additional_contexts: {basepack: ../../../soar-content-pack}` (Compose
v2.17+ feature).

## Judgment calls

**`deploy/soarctl_lib/content.py` duplicates pure planning logic instead of
importing `orchestrator/core/pack_install.py`.** Checked first: `grep -r
"from orchestrator" deploy/` returns nothing — `deploy/` has never imported
`orchestrator/` anywhere, at any phase. The two sides also read genuinely
different data shapes for a structural reason, not just historical
accident: `orchestrator/core/pack_install.py`'s functions take
`connectors_dir` as a real filesystem path (the orchestrator process has
direct disk access to it — it's a mounted volume from its own
perspective); `deploy/soarctl_lib/content.py`'s functions take an
in-memory `files: dict[path, bytes]` pulled out of a tar dump (soarctl runs
on the host, outside any container, with no direct access to the
`soar-data` docker volume at all — same reason `backup.py` shells out to a
throwaway alpine container instead of touching the volume's files
directly). Forcing a shared import here would mean picking one of those
two shapes as canonical and adapting the other side to fit it, which is a
bigger change than the ~40 lines of `plan_install`/sha256 logic it would
save. Kept both implementations deliberately small and side-by-side in
this report for anyone who needs to change the algorithm to find both.

**`POST /connectors/pack/install` got its own file (`orchestrator/api/packs.py`)
despite being a single route.** The spec's own suggestion was "decide by
route count" — by that literal metric this should have gone into
`connectors.py`. It didn't, because `connectors.py` is already ~750 lines
covering a genuinely different concern (CRUD + history/diff/restore of
*one* connector's code and config) — bulk multi-connector installs against
a manifest and a marker file is a different mental model, closer in shape
to `transfer.py` (also its own file, 2 routes) or `runtime.py` (also its
own file, 1 route) than to anything already in `connectors.py`. Route
count was the spec's suggested proxy for "is this its own concern", not
the actual criterion; here the concern was already clearly separate.

**Marker fields beyond the spec's YAML sketch:** the spec showed
`pack`/`pack_version`/`installed_at`/`entries.{version,sha256}`. Kept
exactly that — no additional fields turned out to be needed. `modified` is
explicitly *not* a marker field (spec is explicit that it must be computed
at read time, not cached), which I followed literally in both
implementations.

**`soarctl content install`'s no-op semantics:** the plan flagged this as
undecided ("marker не тронут, или тронут только installed_at/version —
решить и зафиксировать тестом"). Chose "marker completely untouched on a
true no-op" (nothing in `new`/`update`) — simplest, and
`test_install_same_version_twice_is_noop` in
`tests/deploy/test_content_cli.py` pins this by asserting
`marker_after == marker_before` byte-for-byte (including `installed_at`).
`orchestrator/core/pack_install.py::apply_install`/`apply_install_dir`
follow the same rule for consistency between the two implementations.

## Deviations from the spec / things that didn't quite fit reality

**The plan says "24 `tests/soar/test_*_connector.py` files move"; only 15
exist.** Checked before moving anything: `abusech`, `censys`, `crtsh`,
`fofa`, `freeipa`, `kaspersky_opentip`, `misp`, `mysql`, `rstcloud`,
`security_onion`, `shodan`, `smb_rpc`, `urlhaus`, `wazuh`, `winrm` have
dedicated test files. `active_directory`, `elastic`, `file`, `mssql`,
`postgresql`, `smtp`, `ssh`, `telegram`, `virus_total` never had one — this
predates this phase entirely, it's a pre-existing test-coverage gap in the
connectors themselves, not something this move caused or should paper
over by inventing tests. Moved exactly the 15 that exist; the report and
`AGENTS.md`/pack repo `README.md` say 15, not 24.

**Two platform-level tests silently depended on a real built-in connector
being physically present, and would have failed the moment the connectors
moved — found by actually running the suite after the move, not by
inspection.** `tests/soar/test_connectors_init.py` and
`tests/soar/test_connector_registry.py` both wrote only a `.yml` config
into an external dir and relied on `soar/connectors/file/file.py` (or
`urlhaus`) still being importable from the *package* to supply the actual
connector class — `ConnectorRegistry._discover_classes()` (built-in
package scan) found the class, `_discover_external()` only ever needed to
supply the config. Once `soar/connectors/file/` no longer exists, nothing
populates `self._classes["file"]` and every one of those tests fails with
`AttributeError`/`StopIteration`/`assert None is not None`. Fixed by
writing a synthetic connector `.py` file directly into each test's
`tmp_path` external dir instead of leaning on a real built-in — this is
exactly the class of defect the prior two phases' reports flagged
("agents found real bugs this way"): the fix also surfaced a second, more
interesting latent bug in `ConnectorRegistry._discover_external()` itself
(see next paragraph).

**`ConnectorRegistry._discover_external`'s `if fqn in sys.modules:
continue` skip is a process-global cache keyed by module name, and it
leaked across the fixed tests once they no longer had a built-in class to
fall back on.** Reusing the same synthetic type name (`"file"` /
`"widget"`) across more than one test in the same pytest process meant the
second test's brand-new `ConnectorRegistry()` instance would still see an
empty `_classes` for that type — `_discover_external` had already imported
a same-named module for an *earlier* test's registry and skipped
re-importing it for this one, even though `self._classes` is per-instance
state, not global. This is the same mechanism `known-limitations.md`'s
former #9 (E1) described for the built-in-vs-`connectors_dir` duplicate —
it turns out it also bites two different `ConnectorRegistry` instances in
the same process reusing a type name, independent of the built-in-package
question. In production this is invisible (`ConnectorRegistry.init()` runs
exactly once per `soar.runner` subprocess — one job, one process, no
second instance to collide with). Fixed the tests by generating a unique
type name per fixture invocation (`uuid.uuid4().hex[:8]` suffix) rather
than touching the registry's cross-instance-unsafe caching, which is a
pre-existing characteristic outside this phase's scope — flagged here, not
fixed, since fixing it would mean giving `ConnectorRegistry` per-instance
import isolation (e.g. via `importlib.util.module_from_spec` without ever
touching the shared `sys.modules`), a real behavior change with its own
spec.

**Dockerfile/build-context wiring is unverified by an actual `docker
build`, as instructed.** What changed, concretely, so a human can review
before this ships:
- `deploy/prod/Dockerfile.orchestrator` and
  `deploy/stage/Dockerfile.orchestrator`: `COPY --from=basepack .
  /app/base-pack/` — this requires an extra named build context called
  `basepack`. Plain `docker build` (no `--build-context`) will fail on
  this line with "from stage basepack could not be found" or similar; it
  needs either Buildx (`docker buildx build --build-context
  basepack=<path>`) or a sufficiently recent plain `docker build` that
  proxies to Buildx by default (Docker 23+, `DOCKER_BUILDKIT=1` at least).
  Not tested against either.
- `deploy/soarctl_lib/bundle.py::build_images()` now passes
  `--build-context basepack=<repo_root>/../soar-content-pack` — assumes
  the sibling layout unconditionally; if the pack repo isn't checked out
  next to the soar repo on the build machine, this will fail at build
  time with a clear docker error (missing context path), not silently.
- `deploy/stage/docker-compose.yml`'s `build.additional_contexts` requires
  Compose v2.17+; not checked against whatever Compose version is actually
  deployed to the stage box.
- None of `soarctl package`, `soarctl install --repo`, or `docker compose
  build` were actually run in this environment — no docker daemon
  available in the sandbox this phase ran in. The pure-Python install
  pipeline (`orchestrator/core/pack_install.py`,
  `deploy/soarctl_lib/content.py`) *was* exercised end-to-end against the
  real 24-connector pack (see Verification) — only the "get the pack bytes
  into the image" half is unverified.

**Addendum (verified post-merge, orchestrating session, same day):** the
Dockerfile/build-context wiring above was subsequently verified for real —
`DOCKER_BUILDKIT=1 docker compose -f deploy/stage/docker-compose.yml build
orchestrator` from the actual repo checkout (not a nested worktree, where
the sibling-relative path doesn't resolve) succeeded, `additional_contexts`
correctly resolved `basepack` to the sibling `soar-content-pack` checkout,
and the built image's `/app/base-pack/` contains the real manifest +24
connector directories. `orchestrator.main.seed_connector_pack()` was run
directly inside the built image against a temp `connectors_dir` (via
`docker run ... python -c "..."`) and correctly installed all 24
connectors with a `.soar-content.yaml` marker; `/app/content-venv/bin/
python` then successfully discovered and imported all 24 connector
classes via `ConnectorRegistry.init(external_dir=...)`. Compose v2.17+
`additional_contexts` support and the "get the pack bytes into the image"
gap noted above are both closed. Not covered by this addendum: `soarctl
package`/`soarctl install --repo` themselves (the CLI wrapper around
`bundle.py::build_images()`) — only the underlying `docker compose build`
mechanics were exercised directly.

## Testing

`tests/orchestrator/core/test_pack_install.py` — 18 tests: `read_manifest`
(zip + missing-manifest + bad-zip), `read_manifest_from_dir`,
`check_runtime_compat` (matching/mismatched major), `check_dependencies`
(all-guaranteed / missing-import), `plan_install` (empty-marker-all-new,
same-version-same-sha-unchanged, new-version-same-sha-update,
modified-file-skip_modified), `apply_install` (writes+marker,
skips-modified, no-op-leaves-marker-untouched), `apply_install_dir`.

`tests/orchestrator/api/test_pack_routes.py` — 11 tests: clean install,
same-version-twice no-op, conflicts without force, force installs,
missing-dependency 400 before write, incompatible runtime_version 400,
invalid-zip 400, non-admin (analyst/viewer, parametrized) 403, audit log
written on install, audit log NOT written (count unchanged) on a
conflicts-response.

`tests/deploy/test_content_cli.py` — 10 tests, mocked `run()` (no real
docker/subprocess) with a stateful fake volume that persists writes across
successive calls within one test (so a second `install()` call actually
sees the first's marker): fresh install all-new, same-version-twice no-op
(marker byte-identical before/after), install-after-manual-edit →
skip_modified (other connector untouched), new-version updates the
unmodified connector, `list_installed` on empty volume, `remove` on
unmodified, `remove` modified without `--force` refuses
(`ContentError`), `remove` modified with `--force` succeeds, `remove`
unknown connector raises, `remove` rejects an unsafe name
(`../../etc`).

`tests/deploy/test_soarctl_cli.py` — 4 new dispatch tests added to the
existing per-subcommand pattern (`content install`/`list`/`remove`
dispatch, `remove` error → nonzero exit).

`tests/soar/test_connector_registry.py` and `test_connectors_init.py` —
rewritten to use synthetic connector types (see Deviations above); same
assertions/behavior coverage as before, 5 + 4 tests respectively, all
passing.

## Verification

- `python -m pytest tests/orchestrator/core/test_pack_install.py
  tests/orchestrator/api/test_pack_routes.py tests/deploy/test_content_cli.py
  tests/deploy/test_soarctl_cli.py tests/soar/test_connector_registry.py
  tests/soar/test_connectors_init.py -q` — 62 passed.
- Full suite, baseline (this branch's tip on `main`, before any change in
  this phase): `python -m pytest tests/ -q` → **894 passed, 1 skipped, 3
  failed** (the 3 are `tests/orchestrator/test_redis_integration.py`,
  pre-existing, need a live Redis container, unrelated to this work).
- Full suite, after all changes in this phase: `python -m pytest tests/ -q`
  → **792 passed, 1 skipped, 3 failed** — same 3 Redis-integration
  failures, nothing else broke. The drop from 894 → 792 is expected, not a
  regression: 15 connector test files (not 24, see Deviations) moved to
  the pack repo removed roughly 145 test functions from this repo's count;
  this phase's own new tests (`test_pack_install.py` 18 +
  `test_pack_routes.py` 11 + `test_content_cli.py` 10 + 4 new
  `test_soarctl_cli.py` dispatch tests + net rewrite of
  `test_connector_registry.py`/`test_connectors_init.py`) add back 43.
  894 − 145 + 43 = 792, matching exactly.
- `ruff check .` — baseline (before this phase) 40 pre-existing errors,
  none in files this phase touches. After this phase: **37 errors**, all
  in the same pre-existing files as baseline (`orchestrator/api/connectors.py`,
  `orchestrator/core/queue/redis_queue.py`, `orchestrator/core/subprocess_runner.py`,
  and a handful of pre-existing test files) — 3 fewer because 3 of the
  baseline's findings lived in the 15 test files that moved out. Verified
  separately: `ruff check` scoped to just the files this phase created or
  modified (`pack_install.py`, `packs.py`, `main.py`, `content.py`,
  `cli.py`, `bundle.py`, all new/rewritten test files) → **0 findings**.
- `soar-content-pack`'s own test suite: `python -m pytest tests/ -q` (run
  from `D:\projects\soar-content-pack`) → **145 passed**.
- End-to-end smoke test of the real pipeline against the real 24-connector
  pack (substituting for the plan's "manual `soarctl content install
  <base-pack-path>`" step — no docker daemon available in this
  environment, see Deviations): ran
  `orchestrator/core/pack_install.read_manifest_from_dir` →
  `check_runtime_compat` → `check_dependencies` → `plan_install` →
  `apply_install_dir` directly against `D:\projects\soar-content-pack`
  into a fresh temp `connectors_dir` — all 24 connectors installed
  (`plan["new"]` = 24, `check_dependencies` returned `[]`, confirming
  `soar/runtime_contract.py::CONTRACT` genuinely covers every real
  connector's declared imports), a second install of the same manifest
  produced `plan["unchanged"]` = 24 with zero writes. Repeated the same
  scenario through `deploy/soarctl_lib/content.install()` against a fake
  docker volume (same tar-pipe code path a real `soarctl content install`
  would use, minus the actual `docker` process) — identical result, `content
  list` afterward showed all 24 with `modified: False`.

## Success criteria (from the spec, [S11])

- [x] `soar/connectors/` contains only `__init__.py`/`base.py`/`_proxy.py`
- [x] Manifest generated by `gen_manifest.py` (AST, no import); includes
      `imports`/`mutating_methods` per connector
- [x] `.soar-content.yaml` marker; `modified` computed from current
      sha256, never stored
- [x] Install refuses **before writing to disk** if a declared import
      isn't in `CONTRACT` (`check_dependencies` runs before
      `plan_install`/`apply_install` in both the API route and
      `seed_connector_pack`)
- [x] `soarctl content install/list/remove` — alpine tar pipe, no bind
      mount
- [x] `POST /connectors/pack/install` — admin-only, conflict-preflight
      with `force`, audit, shared `orchestrator/core/` logic (not
      duplicated between this route and `seed_connector_pack`)
- [x] Seeding uses the same install path as manual install, every
      startup — closes E4
- [x] `docs/agents/known-limitations.md` #9 (E1) removed (closed, with a
      footnote in the established convention); #10 (E2) was already
      closed by Phase 1, left as-is per the spec's own conditional
- [x] `pytest tests/` green modulo the 3 pre-existing Redis-integration
      failures; `ruff check .` — 0 new findings (37 pre-existing,
      unrelated to this phase, same set as baseline minus 3 that moved
      out with the connector tests)
