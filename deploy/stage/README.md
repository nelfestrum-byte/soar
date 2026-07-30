# SOAR Stage Environment

## Quick Start

```bash
cd deploy/stage
docker compose up --build
```

- UI: http://localhost:3000
- API: http://localhost:8000/status

## Services

| Service | Port | Description |
|---------|------|-------------|
| orchestrator | 8000 | FastAPI + workers + scheduler |
| ui | 3000 | Vue.js SPA (nginx) |
| redis | 6379 | Queue backend |
| postgres | 5432 (internal only) | Auth DB + job history (`database.url`) |

## Queue Backend Configuration

SOAR supports three queue backends — this stand's `config.yaml` uses `sql`
(see below); `memory`/`redis` are shown for reference.

### In-Memory (schema default, not this stand's)
```yaml
queue:
  backend: memory
```

### Redis
```yaml
queue:
  backend: redis
  redis_url: redis://redis:6379/0
  redis_max_connections: 10
  redis_push_timeout: 5.0
  redis_pop_timeout: 1.0
```

### SQL (what this stand actually runs)
```yaml
queue:
  backend: sql
  sql_poll_interval: 0.5

jobs:
  persistence: sql   # required alongside backend: sql, or the orchestrator fails fast at startup
```

Polls the same `workflow_jobs` table `jobs.persistence: sql` already
writes to — no separate broker, no at-most-once job loss on connection
drop (unlike `redis`, see `docs/agents/known-limitations.md` #2). `redis`
service stays up in this compose file regardless — it's optional for
`http_client.cache_backend: redis`, not required for the queue anymore.
Full details — [docs/agents/config-reference.md → Queue backend](../../docs/agents/config-reference.md#queue-backend).

## Database (SQLite / PostgreSQL) and Table Prefix

`config.yaml` here already points at the `postgres` service:

```yaml
database:
  url: postgresql+asyncpg://soar:soar@postgres:5432/soar
  table_prefix: "stage_"   # avoids collisions if this DB is shared with other SOAR instances

jobs:
  persistence: sql          # persist job history across restarts (default is in-memory)
```

First deploy against a fresh Postgres DB — the app's own startup already
creates the tables, so mark the DB as migrated instead of re-running the
migration:

```bash
make migrate-stamp-initial
```

Any later schema change ships as a new Alembic migration; apply it with:

```bash
make migrate
```

Full explanation (why `stamp` and not `upgrade` on first deploy) — see
[docs/agents/config-reference.md → Database backend](../../docs/agents/config-reference.md#database-backend-sqlitepostgresql-и-table-prefix).

## Commands

```bash
# Start
docker compose up -d

# Stop
docker compose down

# Rebuild
docker compose up --build

# Logs
docker compose logs -f orchestrator
docker compose logs -f ui
docker compose logs -f redis

# Scale workers (edit docker-compose.yml)
docker compose up -d --scale orchestrator=1
```

## Health Check

`GET /health` is unauthenticated (liveness probe — used by the Docker
healthcheck itself, since it can't hold credentials):
```bash
curl http://localhost:8000/health
```

`GET /status` has the actual detail (queue/workers/jobs) but requires auth
once `auth.secret_key` is set:
```bash
curl http://localhost:8000/status -H "Authorization: Bearer $ACCESS_TOKEN"
```

## Data

- Config: `config.yaml` (mount into container)
- Logs: `soar-logs` volume
- Data: `soar-data` volume
- Redis: `redis-data` volume
- Postgres: `postgres-data` volume

## Privilege Narrowing (job-runner UID/rlimits — opt-in, off by default)

`Dockerfile.orchestrator` bakes in everything the mechanism needs
(`soar-runner` user, fixed uid/gid `5001`, `setpriv` granted
`cap_setuid,cap_setgid+ep`, `/app/config.yaml` mode 640 owned `soar:soar`,
`/app/data/state` group-writable by `soar-runner`) but this stand's
`config.yaml` does **not** set `jobs.runner_uid` — every job subprocess
still runs as `soar`, same as before this feature existed. To turn it on:

```yaml
jobs:
  runner_uid: 5001
  runner_gid: 5001
  runner_max_memory_mb: 512
  runner_max_cpu_seconds: 300
  runner_max_procs: 32
```

No `cap_add` needed in `docker-compose.yml` — `setpriv`'s file capability
works with Docker's default capability set (verified; see
`docs/compose/reports/privilege-narrowing.md`). Independently of
`runner_uid`, every job subprocess already gets a per-job scoped config
(only the connector instances its workflow statically imports, not the
full `config.yaml`) — that part is always on, no opt-in.

Before relying on this in a real deployment, verify by hand once against a
running stack (a real job submitted through the API, not just a shell
probe):

```bash
docker compose exec orchestrator sh -c "cat /app/config.yaml"          # denied — orchestrator's own shell runs as soar, this checks soar's own read still works, expect success
docker compose exec orchestrator ps -o user,cmd -C python              # confirm at least one runner process is UID soar-runner while a job runs
```

and confirm a job that imports a real connector (`from soar.connectors.
<type> import <instance>`) still succeeds end-to-end — this stand's compose
file was not re-verified against a live run with `runner_uid` set as part
of the Phase 4 session that added the mechanism (deferred; see the report).
