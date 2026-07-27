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
