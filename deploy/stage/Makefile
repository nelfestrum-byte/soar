.PHONY: up down logs build restart migrate migrate-stamp-initial

up:
	docker compose up -d

# First deploy against a fresh Postgres DB only: the orchestrator's own startup
# (init_db/create_all) already creates the tables on first boot, so there is
# nothing for `alembic upgrade head` to apply yet — it would try to CREATE TABLE
# on tables that already exist and fail. `stamp head` marks the DB as being at
# the current migration head without re-running the DDL. Run this once, right
# after the first `make up`/`make build`.
migrate-stamp-initial:
	docker compose exec orchestrator python -m alembic stamp head

# Every later schema change ships as a new Alembic migration — apply it with
# this (create_all() only creates missing tables, it never alters existing
# ones, so this is the only path for real schema changes going forward).
migrate:
	docker compose exec orchestrator python -m alembic upgrade head

down:
	docker compose down

build:
	docker compose up --build -d

logs:
	docker compose logs -f

logs-orchestrator:
	docker compose logs -f orchestrator

logs-ui:
	docker compose logs -f ui

restart:
	docker compose restart

status:
	docker compose ps

clean:
	docker compose down -v
