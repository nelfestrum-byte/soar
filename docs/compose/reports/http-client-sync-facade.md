# Report: `HttpClient` Sync Facade + TI Connector Migration (S1)

Spec: `docs/compose/specs/2026-07-28-http-client-sync-facade-design.md`
Plan: `docs/compose/plans/2026-07-28-http-client-sync-facade.md`

## What was built

- `soar/tools/http_client.py` (modified) — new `SyncHttpClient` class, a
  synchronous twin of `HttpClient` built over `httpx.Client` (not a wrapper
  over the async `HttpClient` via `asyncio.run()` — see spec [S2] for why:
  a fresh event loop per call has no concurrency to gain from, and breaks if
  ever called from inside a running loop). Same `get_json`/`post_json`
  contract minus `await`, plus a new `verify: bool = True` parameter on both
  methods (forwarded to `httpx.Client(timeout=30, verify=verify)`) so
  `rstcloud`/`kaspersky_opentip` keep their `verify_ssl: false` support.
  `_key`/`_ttl_for` on `HttpClient` were extracted into module-level pure
  functions `_cache_key`/`_ttl_for` (no behavior change), reused by
  `SyncHttpClient` instead of cross-class bound-method reuse.
  `CacheBackend`/`InMemoryCache`/`RedisCache`/`_is_private_ip`/
  `_validate_external_url` are unchanged.
- `soar/tools/__init__.py` (modified) — new `http_client_sync =
  SyncHttpClient()` default singleton next to the existing `http_client`.
- `soar/runner.py` (modified) — `_build_http_client(config)`'s inline cache
  selection was extracted into `_build_cache(http_cfg, queue_cfg) ->
  CacheBackend | None` (identical branches/errors, `_build_http_client`
  calls it internally so its existing tests are unaffected). New
  `_build_http_client_sync(http_client: HttpClient) -> SyncHttpClient` reuses
  the already-built `http_client`'s `_cache`/`_default_ttl`/`_domain_ttl` so
  both singletons share one `CacheBackend` instance built from the same
  `http_client:` config section, without re-parsing config twice. Module
  level: `tools.http_client_sync = _build_http_client_sync(tools.http_client)`
  right after the existing `tools.http_client = _build_http_client(config)`
  line — call position relative to `workflows.init()`/`connectors.init()`/
  `actions.init()` is untouched, per task instructions that reordering is a
  separate spec (`2026-07-28-http-client-init-order-design.md`).
- Three connectors migrated off `requests`/`requests.Session` onto
  `http_client_sync`:
  - `soar/connectors/abusech/abusech.py` — `_post` now calls
    `http_client_sync.post_json(url, data, headers={"User-Agent": ...})`.
    `_session`/custom `__init__`/`disconnect` removed entirely (no
    persistent session needed — `SyncHttpClient` opens a connection
    per-request); `_connect_impl` is a no-op, `is_connected`/`disconnect`
    fall back to `BaseConnector`'s defaults.
  - `soar/connectors/rstcloud/rstcloud.py` — `_get` calls
    `http_client_sync.get_json(url, headers=self._headers(),
    verify=self.verify_ssl)`, `_headers()` builds `Authorization: Bearer
    {api_key}` + `User-Agent`. `check_url` builds the query string with
    `urllib.parse.urlencode` and appends it to the URL, since
    `SyncHttpClient.get_json` has no `params=` kwarg (mirrors how
    `_validate_external_url`/cache-key already treat the full URL as the
    unit of identity).
  - `soar/connectors/kaspersky_opentip/kaspersky_opentip.py` — identical
    pattern to `rstcloud`, `X-Api-Key` header instead of `Bearer`.
  - `urlhaus`/`crtsh` left untouched, per spec [S4] (documented backlog for
    a future migration pass, not blocking this one).

## Tests

- `tests/soar/tools/test_http_client.py` (extended, +16 tests) — mirrors
  every existing async `get_json`/`post_json` test for `SyncHttpClient`
  (network hit + log, cache hit, `cached=False` bypass, no-cache-backend
  no-op, SSRF guard) using a `_mock_sync_client` helper standing in for
  `httpx.Client() as client` (no `AsyncMock`/`await`), plus new tests
  asserting `httpx.Client(timeout=30, verify=...)` gets the right `verify`
  value by default and when overridden, on both `get_json`/`post_json`.
- `tests/soar/test_runner.py` (extended, +1 test) —
  `test_build_http_client_sync_shares_cache_with_async_client`: builds an
  `HttpClient` via `_build_http_client`, passes it to
  `_build_http_client_sync`, asserts the sync client's `_cache` `is` the
  same object and `_default_ttl`/`_domain_ttl` match. Existing
  `test_build_http_client_*` tests pass unmodified (behavior of
  `_build_http_client` itself didn't change).
- `tests/soar/test_abusech_connector.py` (new — none existed before this
  work) — 13 tests covering every public method
  (`get_malware_iocs`/`get_iocs_by_tag`/`get_iocs_by_country`/`get_feeds`/
  `get_bazaar_samples`/`get_bazaar_file`/`get_urlhaus_urls`/
  `get_urlhaus_host`), `_connect_impl` no-op, and `_ensure_connected` setting
  `is_connected` via the real `BaseConnector` path, mocking
  `http_client_sync.post_json` instead of `requests.Session`.
- `tests/soar/test_rstcloud_connector.py` / `test_kaspersky_opentip_connector.py`
  (rewritten) — same public-method coverage as before (`check_ip`/
  `check_domain`/`check_hash`/`check_url`, `_connect_impl`, `disconnect`),
  mocking `http_client_sync.get_json` instead of `requests.Session`;
  `check_url` assertions updated to the new query-string-in-URL shape;
  added an explicit `verify_ssl=False` test on `check_ip` for each connector.

## Verification

- Target suite: `python -m pytest tests/soar/tools/test_http_client.py
  tests/soar/test_abusech_connector.py tests/soar/test_rstcloud_connector.py
  tests/soar/test_kaspersky_opentip_connector.py tests/soar/test_runner.py -v`
  → **70 passed**.
- Full suite: `python -m pytest tests/ -q` → **714 passed, 1 failed, 1
  skipped**. The one failure is the pre-existing, unrelated
  `tests/soar/tools/test_openapi.py::test_generate_config` (documented as
  known in the task and in `docs/concepts/BAGFIX_PLAN.md` S7) — zero new
  failures introduced by this change.

## Non-goals confirmed untouched

Per spec [S4]: `urlhaus`/`crtsh` and the SDK-based connectors
(`virus_total`/`shodan`/`fofa`/`censys`/`misp`) were not migrated. Per task
instructions: `soar/runner.py`'s call order of `workflows.init()`/
`connectors.init()`/`actions.init()` relative to the `http_client`/
`http_client_sync` singleton assignment was left exactly as-is — that
reordering belongs to the separate, not-yet-implemented
`docs/compose/specs/2026-07-28-http-client-init-order-design.md`.
`docs/concepts/BAGFIX_PLAN.md` was not modified.

## Docs

`docs/concepts/UPGRADE-v2.md` P12 updated (closes D5 from
`docs/concepts/BAGFIX_PLAN.md`): the Part 1 problem statement's "Actions для
VT, AbuseCh, Kaspersky…" was corrected to "Коннекторы" (those are
connectors, not actions — `soar/actions/` is empty). The Part 2
"Реализовано" section for P12 now describes the v0.12 gap (async-only tool,
no call-sites) and this fix (sync facade + 3 real connector consumers,
remaining TI-connector migration recorded as backlog, not a blocker), and
links this plan/report alongside the original ones.

## Files changed

- `soar/tools/http_client.py` (modified — `SyncHttpClient`, extracted
  `_cache_key`/`_ttl_for` module functions)
- `soar/tools/__init__.py` (modified — `http_client_sync` singleton)
- `soar/runner.py` (modified — `_build_cache`, `_build_http_client_sync`)
- `soar/connectors/abusech/abusech.py` (modified)
- `soar/connectors/rstcloud/rstcloud.py` (modified)
- `soar/connectors/kaspersky_opentip/kaspersky_opentip.py` (modified)
- `tests/soar/tools/test_http_client.py` (modified)
- `tests/soar/test_runner.py` (modified)
- `tests/soar/test_abusech_connector.py` (new)
- `tests/soar/test_rstcloud_connector.py` (rewritten)
- `tests/soar/test_kaspersky_opentip_connector.py` (rewritten)
- `docs/concepts/UPGRADE-v2.md` (modified — P12 status, D5)
- `docs/compose/specs/2026-07-28-http-client-sync-facade-design.md` (new)
- `docs/compose/plans/2026-07-28-http-client-sync-facade.md` (new)
- `docs/compose/reports/http-client-sync-facade.md` (this file)
