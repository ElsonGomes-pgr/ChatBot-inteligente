"""
Fixtures partilhadas para todos os testes.

Usa SQLite async em memória para testes rápidos sem precisar de Postgres real.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.models import Base
from app.core.config import Settings


# ── Engine de teste (SQLite async in-memory) ──────────────────────────────

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


# ── Settings de teste ─────────────────────────────────────────────────────

_test_settings = Settings(
    debug=True,
    environment="test",
    database_url="sqlite+aiosqlite:///:memory:",
    redis_url="redis://localhost:6379/15",
    ai_provider="anthropic",
    anthropic_api_key="test-key",
    n8n_webhook_secret="test_webhook_secret",
    api_key="test_api_key",
    rate_limit_per_minute=1000,
    meta_app_secret="test_meta_secret",
    n8n_callback_url="",
    slack_webhook_url="",
    slack_bot_token="",
    slack_signing_secret="test_slack_secret",
    slack_handoff_channel="",
)


def _override_get_settings():
    return _test_settings


# ── Mock Redis ────────────────────────────────────────────────────────────

def _make_mock_redis():
    """Cria um mock de Redis com suporte a pipeline."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    redis.ping = AsyncMock()

    pipe_mock = AsyncMock()
    pipe_mock.incr = MagicMock(return_value=pipe_mock)
    pipe_mock.expire = MagicMock(return_value=pipe_mock)
    pipe_mock.execute = AsyncMock(return_value=[1, True])
    redis.pipeline = MagicMock(return_value=pipe_mock)

    return redis


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Cria e destrói as tabelas em cada teste."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """Sessão de DB para testes."""
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture
def test_settings():
    """Settings de teste acessíveis nos testes."""
    return _test_settings


@pytest_asyncio.fixture
async def client(db_session):
    """
    Client HTTP para testar a API completa.
    Substitui as dependências reais por mocks.
    """
    mock_redis = _make_mock_redis()

    # Patch database module to use test engine (lazy init)
    import app.db.database as db_module
    db_module._engine = test_engine
    db_module._async_session = TestSessionLocal

    async def override_get_db():
        yield db_session

    async def override_get_redis():
        return mock_redis

    from app.db.database import get_db
    from app.db.redis_client import get_redis
    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    # Patch get_settings em todos os módulos que usam a nível de módulo
    with patch("app.core.config.get_settings", _override_get_settings), \
         patch("app.core.security.settings", _test_settings), \
         patch("app.api.routes.messages.settings", _test_settings), \
         patch("app.api.routes.conversations.settings", _test_settings), \
         patch("app.db.redis_client.get_redis", override_get_redis):

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    app.dependency_overrides.clear()

    # Reset lazy singletons so other tests start fresh
    db_module._engine = None
    db_module._async_session = None
