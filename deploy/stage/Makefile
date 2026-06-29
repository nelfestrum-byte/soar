.PHONY: up down logs build restart

up:
	docker compose up -d

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
