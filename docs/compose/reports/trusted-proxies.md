# Report: `server.trusted_proxies` for nginx-fronted deploys (B4)

Spec: `docs/compose/specs/2026-07-28-trusted-proxies-design.md`
Plan: `docs/compose/plans/2026-07-28-trusted-proxies.md`

## Summary

`deploy/prod`/`deploy/stage` put nginx (the `ui` container) in front of the
orchestrator, but neither `config.yaml.template` nor `config.yaml` ever set
`server.trusted_proxies` — the Pydantic default `[]` silently won, so
`resolve_client_ip()` (`orchestrator/core/net.py`, unchanged by this fix)
never trusted `X-Real-IP`/`X-Forwarded-For` from nginx. Every real client's
IP collapsed to the `ui` container's docker-bridge address: the 5/60s login
rate limiter became a single global bucket (any user's failed logins locked
out everyone), the general 120/60s rate limit became global instead of
per-client, and `AuditLog.client_ip` was identical on every row.

`resolve_client_ip()` itself does exact string comparison against
`trusted_proxies`, not CIDR matching, and the default docker bridge network
doesn't guarantee a stable IP for `ui`. Fixed per spec by giving `ui` a
deterministic static IP on a custom docker network with a fixed subnet, then
pointing `trusted_proxies` at that exact IP.

## Changes

- `deploy/prod/docker-compose.yml` / `deploy/stage/docker-compose.yml` —
  added a top-level `networks: soar-net` with IPAM `subnet: 172.28.0.0/24`;
  every service (`redis`, `postgres`, `orchestrator`, `ui`) now explicitly
  joins `soar-net` (required — once a compose file declares a top-level
  `networks:`, services that don't list it get a second, disconnected
  default network); `ui` additionally pins `ipv4_address: 172.28.0.10`.
- `deploy/prod/config.yaml.template` / `deploy/stage/config.yaml` — new
  `server: trusted_proxies: ["172.28.0.10"]` section, with a comment tying
  the IP to the compose network config and referencing B4.
- `deploy/prod/README.md` — new checklist item next to the existing
  `auth.cors_origins` reminder: verify `server.trusted_proxies` matches the
  `ui` container's IP on `soar-net`, and don't change one without the other.
- `tests/orchestrator/core/test_net.py` (new) — direct unit tests for
  `resolve_client_ip()` using a mocked `Request`, exercising an exact match
  on a non-loopback IP (`172.28.0.10`, mirroring the compose network) and a
  mismatch case. Existing coverage
  (`tests/orchestrator/api/test_rate_limiter.py`,
  `tests/orchestrator/api/test_access_log_middleware.py`) only ever proves
  trust for `127.0.0.1`, because `httpx.ASGITransport` always presents that
  as `request.client.host` — it couldn't demonstrate the matching is exact
  IP comparison rather than something coincidentally tied to loopback.

`resolve_client_ip()` (`orchestrator/core/net.py`) was **not** modified —
per spec, the bug was purely that the trusted IP was never configured for
the multi-container deploy, not a code defect.

## Testing

New tests were not "failing before, passing after" in the traditional
test-first sense — this is a config-only fix, and `resolve_client_ip()`'s
matching logic already worked correctly. They were run standalone
immediately to confirm coverage:

```
tests/orchestrator/core/test_net.py .. (2 passed)
tests/orchestrator/api/test_rate_limiter.py .. (2 passed)
tests/orchestrator/api/test_access_log_middleware.py .... (4 passed)
```

Full suite:

```
python -m pytest tests/ -q
1 failed, 688 passed, 1 skipped, 13 warnings in 104.12s
```

The one failure is pre-existing and unrelated:
`tests/soar/tools/test_openapi.py::test_generate_config` (confirmed as the
sole failure on the unmodified tree before this change — same count modulo
the 2 new tests: 686 passed before, 688 after). No new regressions.

Deploy-time manual verification (spec S4 — `docker compose up`, `docker
inspect soar-ui` for `NetworkSettings.Networks.soar-net.IPAddress` matching
`trusted_proxies`, and IP stability across a restart) was **not** run in
this environment — no `docker compose` access here. This step remains a
manual/deploy-time check per the spec, not a pytest.

## Success criteria (spec S5)

- [x] `deploy/prod/docker-compose.yml`/`deploy/stage/docker-compose.yml` —
      `ui` has a static IP on a dedicated subnet
- [x] `deploy/prod/config.yaml.template`/`deploy/stage/config.yaml` —
      `server.trusted_proxies` contains that same IP, with a comment
      explaining its origin and the sync requirement with the compose file
- [x] `deploy/prod/README.md` — startup checklist item next to
      `auth.cors_origins`
- [ ] Login rate limiter and general rate limit become per-real-client-IP
      on an nginx-fronted deploy — logically follows from the config fix,
      not independently verifiable without `docker compose` in this
      environment (see manual verification note above)
- [ ] `AuditLog.client_ip` reflects the real client IP, not `ui`'s IP —
      same caveat as above
- [x] `resolve_client_ip()` unchanged — fix is entirely in deploy config
