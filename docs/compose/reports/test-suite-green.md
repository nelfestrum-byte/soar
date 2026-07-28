# Report: Green Test Suite — `_generate_config` instance key + optional-dependency guards (S7)

Spec: `docs/compose/specs/2026-07-28-test-suite-green-design.md`
Plan: `docs/compose/plans/2026-07-28-test-suite-green.md`

## What was built

- `soar/tools/openapi.py::_generate_config` — instance key in the generated
  `.example.yml` is now the plain `name` argument (snake_case, e.g.
  `my_api:`), not `f"{class_name}1"` (e.g. `MyApiConnector1:`). The
  now-unused `class_name`/`instance_name` locals in this function were
  removed. This matches the convention used everywhere else in the codebase
  (`CONFIG_TEMPLATE` in `orchestrator/api/connectors.py`, hand-written
  `*.example.yml` files) — `_generate_init` still computes `class_name` for
  the Python class name, unaffected.
- `tests/soar/test_misp_connector.py`, `test_mysql_connector.py`,
  `test_shodan_connector.py`, `test_winrm_connector.py`,
  `test_smb_rpc_connector.py` — each now starts with
  `pytest.importorskip("<package>")` before importing the connector module,
  so collection skips cleanly (`1 skipped` per module) instead of failing
  with `ImportError`/`ModuleNotFoundError` in an environment missing that
  optional third-party package. Verified per-file package names by reading
  each connector module's imports directly: `pymisp` (`misp.py`), `pymysql`
  (`mysql.py`), `shodan` (`shodan.py`), `winrm` (`winrm.py`, pip name
  `pywinrm`), and `smbprotocol` (`smb_rpc.py` — confirmed via `from
  smbprotocol.connection import Connection` etc.; the original 2026-07-27
  review had misnamed this dependency `impacket`).
- `tests/orchestrator/api/test_connectors_api.py::test_generated_connector_config`
  — one assertion updated from `"GenConfigTestConnector1:" in content` to
  `"gen_config_test:" in content`. This test was not named in the spec, but
  it asserted the exact same broken convention that [S1.1]/[S2.1] fix; it
  passed on unpatched `main` only because it encoded the bug as expected
  behavior. Discovered by running the full suite after the `_generate_config`
  fix — without updating this assertion, the suite would not be green.
- `docs/compose/plans/2026-07-28-test-suite-green.md` — plan (new file, all
  items checked off).

## Test-first confirmation

Before the fix, `tests/soar/tools/test_openapi.py -v` showed the single
expected failure:

```
tests/soar/tools/test_openapi.py::test_generate_config FAILED
AssertionError: assert 'my_api:' in 'instances:\n  MyApiConnector1:\n    base_url: https://api.example.com\n'
1 failed, 25 passed in 0.33s
```

All other tests in that file, including `test_generate_config_with_auth` and
`test_generate_creates_files`, already passed and were unaffected by the fix.

## Verification

Targeted run after the fix (all five optional packages are installed in this
environment, so none of the guarded modules skip — they run normally,
confirming `importorskip` is a no-op when the package is present):

```
python -m pytest tests/soar/tools/test_openapi.py tests/soar/test_misp_connector.py \
  tests/soar/test_mysql_connector.py tests/soar/test_shodan_connector.py \
  tests/soar/test_winrm_connector.py tests/soar/test_smb_rpc_connector.py -v
=> 64 passed
```

Full suite:

```
python -m pytest tests/ -q
=> 687 passed, 1 skipped, 13 warnings in 73.47s
```

The one skip (`tests/orchestrator/test_subprocess_runner_env.py`, `SOAR_CONFIG
not in env`) is pre-existing and unrelated to this change — documented in
that test as expected behavior before a different, unrelated fix.

`0 failed`, matching [S4] success criteria: `main`'s single known failure
(`test_generate_config`) is fixed, no existing passing test regressed
(686 → 687 passed reflects the one previously-red test now green; total
count otherwise unchanged), and no collection errors occur for the five
optional-dependency connector test modules.

## Out of scope (per [S2.2], not done)

- No `pyproject.toml` `[project.optional-dependencies]` extras section was
  added for the five optional connector packages — the spec explicitly
  scoped this out as an optional follow-up, not required for "tests don't
  fail on collection."
- `docs/concepts/BAGFIX_PLAN.md` was not touched — this spec's [S4] success
  criteria don't reference it.
