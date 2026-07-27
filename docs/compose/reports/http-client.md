# Report: HTTP Client Tool (Logging + Optional Caching)

Spec: `docs/compose/specs/2026-07-27-http-client-design.md`
Plan: `docs/compose/plans/2026-07-27-http-client.md`

## What was built

- `soar/tools/http_client.py` (new) — `CacheBackend` protocol, `InMemoryCache`
  (per-process TTL cache), `RedisCache` (shared cache over `redis-py`,
  lazy-connects via `redis.from_url`), `HttpClient` (`get_json`/`post_json`),
  `_validate_external_url`/`_is_private_ip` (SSRF guard). Matches spec [S4]
  code exactly, with one deliberate fix: the SSRF-check port from
  `orchestrator/api/connectors.py::_validate_external_url` raises
  `HTTPException` for both "not an IP literal" (control flow) and "blocked
  private IP" (real error), which are distinguishable by exception *type* in
  the original. Since this port raises `ValueError` for both purposes, reusing
  the same nested try/except-ValueError structure verbatim would have
  swallowed the "blocked" error as if it were "not an IP literal, keep
  going". Rewrote that branch to test `ip is not None` explicitly instead of
  relying on catching `ValueError` for control flow — behavior (which
  addresses are blocked) is unchanged, only the internal control flow differs
  from a literal one-to-one line port.
- `soar/tools/__init__.py` (modified) — exports a default `http_client =
  HttpClient()` singleton (no cache backend) so `from soar.tools import
  http_client` works immediately; `soar/runner.py` reassigns it once config
  is known.
- `orchestrator/config.py` (modified) — `HttpClientConfig` (`cache_backend:
  str = "memory"`, `default_ttl: int = 3600`, `domain_ttl: dict[str, int] =
  {}`) and `OrchestratorConfig.http_client` field, per spec [S6].
- `soar/runner.py` (modified) — new `_build_http_client(config: dict) ->
  HttpClient` reads the `http_client` section from the same `SOAR_CONFIG`
  yaml dict already loaded for `soar_config`/external dirs (no new file
  read, no dependency on `orchestrator.config`, preserving the one-way
  `soar/` → not-`orchestrator/` dependency rule). `cache_backend: redis`
  reuses `queue.redis_url`; if that's empty, raises `ValueError` at import
  time (fail-fast, no silent fallback to memory) per spec [S6]. Unknown
  `cache_backend` values also raise. Result replaces `soar.tools.http_client`
  at module load.

## Tests

- `tests/soar/tools/test_http_client.py` (new, 18 tests) — `InMemoryCache`
  roundtrip + TTL expiry, `RedisCache` get/set against a mocked
  `redis.from_url`, `_validate_external_url` (direct private/loopback IPs,
  domain resolving to private/metadata IPs via mocked `socket.getaddrinfo`,
  public-domain allow, non-http(s) scheme reject), `get_json` (network hit +
  single `_log.info`, cache-hit on second call + `_log.debug`, `cached=False`
  always bypasses, `cache=None` + `cached=True` is a no-op, SSRF guard
  applied), `post_json` (never cached even with a backend configured, SSRF
  guard applied). Confirmed these fail with
  `ModuleNotFoundError: soar.tools.http_client` before the implementation
  existed.
- `tests/soar/test_runner.py` (extended, +6 tests) — `_build_http_client`:
  default memory cache, `none` backend has no cache, ttl/domain_ttl passed
  through, `redis` backend builds `RedisCache` from `queue.redis_url`
  (mocked `redis.from_url`, no real Redis needed), `redis` backend with
  empty `queue.redis_url` raises, unknown backend raises.
- `tests/orchestrator/test_config.py` (extended, +3 assertions/1 test) —
  `HttpClientConfig` defaults, YAML round-trip including `http_client`
  section, standalone default-value test.

## Verification

- New module's own tests: `python -m pytest tests/soar/tools/test_http_client.py tests/soar/test_runner.py tests/orchestrator/test_config.py -q` → 32 passed.
- Full suite: `python -m pytest -q` → **621 passed, 4 failed, 1 skipped**.
  The 4 failures are pre-existing and unrelated to this change — confirmed
  by `git stash`-ing this work and re-running the same tests against the
  unmodified branch, which reproduces the identical 4 failures:
  - `tests/orchestrator/test_redis_integration.py::test_redis_integration_push_pop`
  - `tests/orchestrator/test_redis_integration.py::test_redis_integration_multiple_jobs`
  - `tests/orchestrator/test_redis_integration.py::test_redis_integration_clear`
    (all three require a live Redis server, not available in this sandbox)
  - `tests/soar/tools/test_openapi.py::test_generate_config` (pre-existing
    bug/flake in the unrelated OpenAPI connector generator, untouched by
    this spec)

## Non-goals confirmed untouched

Per spec [S9]: no threat-intel connector was migrated to `HttpClient`; no
per-workflow metrics or dry-run convention work was done. Per task
instructions: `orchestrator/api/connectors.py`, `orchestrator/core/queue/`,
and `soar/connectors/*` were not modified.

## Files changed

- `soar/tools/http_client.py` (new)
- `soar/tools/__init__.py` (modified)
- `orchestrator/config.py` (modified)
- `soar/runner.py` (modified)
- `tests/soar/tools/test_http_client.py` (new)
- `tests/soar/test_runner.py` (modified)
- `tests/orchestrator/test_config.py` (modified)
- `docs/compose/plans/2026-07-27-http-client.md` (new)
- `docs/compose/reports/http-client.md` (this file)
