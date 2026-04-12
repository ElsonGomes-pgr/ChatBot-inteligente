# Makefile — atalhos para desenvolvimento
# Uso: make <comando>

.PHONY: up down logs migrate upgrade downgrade revision history current shell test

# ── Docker ────────────────────────────────────────────────────────────────────

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api

# ── Migrations (rodar dentro do container ou com .env local) ─────────────────

# Aplica todas as migrations pendentes
migrate:
	docker compose exec api alembic upgrade head

# Alias para migrate
upgrade:
	docker compose exec api alembic upgrade head

# Volta uma migration
downgrade:
	docker compose exec api alembic downgrade -1

# Volta até a migration especificada
# Uso: make downgrade-to REV=001_initial
downgrade-to:
	docker compose exec api alembic downgrade $(REV)

# Cria nova migration (detecção automática de mudanças nos models)
# Uso: make revision MSG="adiciona coluna xyz"
revision:
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"

# Ver histórico de migrations
history:
	docker compose exec api alembic history --verbose

# Ver migration atual aplicada no banco
current:
	docker compose exec api alembic current

# Ver SQL que será executado sem aplicar
# Uso: make sql FROM=001_initial TO=head
sql:
	docker compose exec api alembic upgrade $(FROM):$(TO) --sql

# ── Desenvolvimento ───────────────────────────────────────────────────────────

shell:
	docker compose exec api bash

test:
	docker compose exec api pytest tests/ -v

# Roda testes localmente (sem Docker)
test-local:
	pytest tests/ -v
