.PHONY: help up down dev pi logs ps clean setup

COMPOSE        = docker compose -f docker/docker-compose.yml
COMPOSE_DEV    = $(COMPOSE) -f docker/docker-compose.dev.yml
COMPOSE_PI     = $(COMPOSE) -f docker/docker-compose.pi.yml

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────

setup:          ## First-time setup: copy .env and check dependencies
	@if [ ! -f docker/.env ]; then \
		cp docker/.env.example docker/.env; \
		echo "Created docker/.env — edit it before running 'make up'"; \
	else \
		echo "docker/.env already exists"; \
	fi
	@command -v docker >/dev/null 2>&1 || (echo "Docker not found — install Docker Desktop or Docker Engine"; exit 1)
	@docker compose version >/dev/null 2>&1 || (echo "Docker Compose v2 not found"; exit 1)
	@echo "Setup complete. Edit docker/.env then run: make up"

# ── Running ───────────────────────────────────────────────────────────────

up:             ## Start the full stack (production mode)
	$(COMPOSE) --env-file docker/.env up -d

dev:            ## Start the stack with dev overrides (extra ports, hot reload)
	$(COMPOSE_DEV) --env-file docker/.env up

pi:             ## Start the Raspberry Pi / off-grid stack
	$(COMPOSE_PI) --env-file docker/.env up -d

down:           ## Stop all services
	$(COMPOSE) --env-file docker/.env down

restart:        ## Restart a specific service: make restart svc=opentakserver
	$(COMPOSE) --env-file docker/.env restart $(svc)

# ── Observability ─────────────────────────────────────────────────────────

logs:           ## Tail logs (all services). Override: make logs svc=nginx
	$(COMPOSE) --env-file docker/.env logs -f $(svc)

ps:             ## Show running container status
	$(COMPOSE) --env-file docker/.env ps

# ── Database ──────────────────────────────────────────────────────────────

db-shell:       ## Open a psql shell to the SkiTAK database
	$(COMPOSE) --env-file docker/.env exec postgres \
		psql -U $$(grep POSTGRES_USER docker/.env | cut -d= -f2) skitak

db-backup:      ## Dump the database to backups/skitak-$(date).dump
	@mkdir -p backups
	$(COMPOSE) --env-file docker/.env exec -T postgres \
		pg_dump -U $$(grep POSTGRES_USER docker/.env | cut -d= -f2) skitak \
		> backups/skitak-$$(date +%Y%m%d-%H%M%S).dump
	@echo "Backup saved to backups/"

# ── Health ────────────────────────────────────────────────────────────────

smoke:          ## Check that the API and plugin are up
	@curl -fsS http://localhost:8081/api/health >/dev/null 2>&1 \
		&& echo "OTS API:        ok" \
		|| curl -fsSk https://localhost/api/health >/dev/null && echo "OTS API:        ok (via nginx)"
	@curl -fsSk https://localhost/api/skitak/health >/dev/null && echo "SkiTAK plugin:  ok"

# ── Cleanup ───────────────────────────────────────────────────────────────

clean:          ## Remove containers and volumes (DESTRUCTIVE — data is lost)
	@echo "WARNING: This will delete all data including the database."
	@read -p "Type YES to confirm: " confirm; \
	if [ "$$confirm" = "YES" ]; then \
		$(COMPOSE) --env-file docker/.env down -v; \
	fi

# ── Building ──────────────────────────────────────────────────────────────

build:          ## Rebuild all Docker images
	$(COMPOSE) --env-file docker/.env build

build-dashboard: ## Build the React dashboard
	cd dashboard && npm ci && npm run build
