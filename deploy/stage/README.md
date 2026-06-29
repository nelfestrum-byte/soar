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

# Scale workers (edit docker-compose.yml)
docker compose up -d --scale orchestrator=1
```

## Data

- Config: `config.yaml` (mount into container)
- Logs: `soar-logs` volume
- Data: `soar-data` volume
