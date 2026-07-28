# Plan: `HttpClient` Sync Facade + TI Connector Migration (S1)

Spec: `docs/compose/specs/2026-07-28-http-client-sync-facade-design.md`

## Tests first (`tests/soar/tools/test_http_client.py`)

- [ ] Mirror each existing async test for a new `SyncHttpClient`, patching
      `soar.tools.http_client.httpx.Client` instead of `httpx.AsyncClient`,
      no `await`/no `pytest.mark.asyncio`:
  - [ ] `get_json`: network hit + single `_log.info`
  - [ ] `get_json`: second call with same url+headers is a cache hit, `_log.debug` fired
  - [ ] `get_json`: `cached=False` always bypasses cache
  - [ ] `get_json`: `cache=None` + `cached=True` is a no-op
  - [ ] `get_json`: SSRF guard applied (`_validate_external_url` raises before request)
  - [ ] `post_json`: basic request, never cached, `_log.info` fired
  - [ ] `post_json`: SSRF guard applied
  - [ ] `get_json`/`post_json`: default `verify=True` passed to `httpx.Client(..., verify=True)`
  - [ ] `get_json`/`post_json`: explicit `verify=False` passed through to `httpx.Client(..., verify=False)`
- [ ] Confirm new tests fail before `SyncHttpClient` exists (`ImportError`)

## Implementation — `soar/tools/http_client.py`

- [ ] Extract `_cache_key(url, headers)` / `_ttl_for(domain_ttl, default_ttl, url, ttl)` as
      module-level functions (pure, no `self`) — reused by both `HttpClient` and `SyncHttpClient`
      instead of cross-class bound-method reuse (per spec [S2] discussion)
- [ ] `HttpClient._key`/`_ttl_for` become thin wrappers calling the module-level functions
      (no behavior change, existing tests keep passing unmodified)
- [ ] Add `SyncHttpClient` class: same constructor signature as `HttpClient`
      (`cache`, `default_ttl`, `domain_ttl`), `get_json(url, headers=None, ttl=None,
      cached=True, verify=True)` and `post_json(url, payload, headers=None, verify=True)`,
      built over `httpx.Client(timeout=30, verify=verify)`, reusing
      `_validate_external_url`/`_cache_key`/`_ttl_for`/`CacheBackend` unchanged

## Implementation — `soar/tools/__init__.py`

- [ ] `from soar.tools.http_client import HttpClient, SyncHttpClient`
- [ ] Add `http_client_sync = SyncHttpClient()` default singleton next to existing `http_client`

## Implementation — `soar/runner.py`

- [ ] Extract `_build_cache(http_cfg, queue_cfg)` from the existing cache-selection branch
      inside `_build_http_client` (same behavior: `memory`/`redis`/`none`/unknown → same errors)
- [ ] `_build_http_client(config)` calls `_build_cache` internally — unchanged external behavior,
      existing `tests/soar/test_runner.py::test_build_http_client_*` keep passing unmodified
- [ ] Add `_build_http_client_sync(http_client: HttpClient) -> SyncHttpClient` that reuses
      `http_client`'s already-built `_cache`/`_default_ttl`/`_domain_ttl` — guarantees one
      shared `CacheBackend` instance between both singletons, built from the same
      `http_client:` config section, without re-parsing config twice
- [ ] Module level: `tools.http_client = _build_http_client(config)` (unchanged position/line),
      then `tools.http_client_sync = _build_http_client_sync(tools.http_client)` right after —
      do NOT reorder relative to `workflows.init()`/`connectors.init()`/`actions.init()`
      (separate spec `2026-07-28-http-client-init-order-design.md` owns that)
- [ ] New test: `_build_http_client_sync` returns a `SyncHttpClient` whose `_cache` `is` the
      input `HttpClient`'s `_cache`, and whose `_default_ttl`/`_domain_ttl` match

## Implementation — connector migration (3 connectors)

- [ ] `soar/connectors/abusech/abusech.py`: drop `requests`/`_session`/custom `__init__`/
      `disconnect` (falls back to `BaseConnector.disconnect`); `_connect_impl` becomes a no-op
      (`http_client_sync` opens a connection per request, nothing to hold); `_post` calls
      `http_client_sync.post_json(url, data, headers={"User-Agent": "SOAR-Connector/1.0"})`
- [ ] `soar/connectors/rstcloud/rstcloud.py`: drop `requests`/`_session`; `_connect_impl` no-op;
      `_get(path)` calls `http_client_sync.get_json(f"{base_url}{path}", headers=self._headers(),
      verify=self.verify_ssl)`; `check_url` builds `?url=...` query string via `urlencode`
      (no `params=` kwarg on `SyncHttpClient.get_json`) and calls the same client
- [ ] `soar/connectors/kaspersky_opentip/kaspersky_opentip.py`: same pattern as `rstcloud`,
      `X-Api-Key` header instead of `Authorization: Bearer`
- [ ] `urlhaus`/`crtsh` untouched (per spec [S4], explicit backlog)

## Tests — connector migration

- [ ] New `tests/soar/test_abusech_connector.py` (none exists today) — mock
      `soar.connectors.abusech.abusech.http_client_sync.post_json`, assert each public method's
      return-value contract unchanged (`get_malware_iocs`, `get_iocs_by_tag`,
      `get_iocs_by_country`, `get_feeds`, `get_bazaar_samples`, `get_bazaar_file`,
      `get_urlhaus_urls`, `get_urlhaus_host`)
- [ ] Rewrite `tests/soar/test_rstcloud_connector.py`: replace `requests.Session` mocks with
      `patch.object(rstcloud_module.http_client_sync, "get_json", ...)`; keep
      `test_rstcloud_init`/`test_rstcloud_init_with_options` as-is (no session anymore, drop
      `_session`/`_connect_impl`/`disconnect` session-specific assertions); assert `verify_ssl`
      is forwarded as `verify=` kwarg
- [ ] Rewrite `tests/soar/test_kaspersky_opentip_connector.py` — mirror rstcloud changes

## Docs

- [ ] `docs/concepts/UPGRADE-v2.md` P12 (D5 from `BAGFIX_PLAN.md`): reword "Реализовано" to
      reflect a working sync path + 3 real connector consumers, with the remaining TI-connector
      migration documented as backlog, not a blocker; fix "Actions для VT, AbuseCh..." wording
      (those are connectors, not actions) in the Part 1 problem statement

## Verification

- [ ] `python -m pytest tests/soar/tools/test_http_client.py tests/soar/test_abusech_connector.py tests/soar/test_rstcloud_connector.py tests/soar/test_kaspersky_opentip_connector.py -v`
- [ ] `python -m pytest tests/ -q` — confirm the only failure is the known pre-existing
      `tests/soar/tools/test_openapi.py::test_generate_config`, zero new failures
- [ ] Write report `docs/compose/reports/http-client-sync-facade.md`
