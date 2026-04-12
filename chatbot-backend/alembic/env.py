import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Importa os models para o Alembic detectar automaticamente
from app.models.models import Base
from app.core.config import get_settings

settings = get_settings()

# Configuração de logging do alembic.ini
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadados dos models — Alembic usa para gerar migrations
target_metadata = Base.metadata

# URL do banco — vem do .env, sobrescreve o alembic.ini
# Troca asyncpg por psycopg2 pois o Alembic roda de forma síncrona
def get_sync_url() -> str:
    url = settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def run_migrations_offline() -> None:
    """Gera SQL sem conectar ao banco — útil para revisar antes de aplicar."""
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Roda migrations de forma assíncrona."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_sync_url()

    # Usa engine síncrono para o Alembic
    from sqlalchemy import create_engine
    sync_url = get_sync_url()
    connectable = create_engine(sync_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
