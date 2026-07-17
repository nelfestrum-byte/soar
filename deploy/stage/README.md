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

SOAR supports two queue backends:

### In-Memory (Default)
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
[AGENTS.md → Database backend](../../AGENTS.md#database-backend-sqlitepostgresql-и-table-prefix).

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

Check Redis connectivity:
```bash
curl http://localhost:8000/status
```

## Data

- Config: `config.yaml` (mount into container)
- Logs: `soar-logs` volume
- Data: `soar-data` volume
- Redis: `redis-data` volume
- Postgres: `postgres-data` volume
