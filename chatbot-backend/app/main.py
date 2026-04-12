import asyncio
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.security import RateLimitMiddleware
from app.core.tasks import background_tasks
from app.db.database import get_engine
from app.models.models import Base
from app.api.routes import messages, conversations, health, slack

settings = get_settings()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    engine = get_engine()
    if settings.debug:
        # Só cria tabelas automaticamente em desenvolvimento
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_created_debug_mode")
    logger.info("startup_complete", environment=settings.environment)
    yield
    # Shutdown: aguarda tasks em background (max 10s)
    if background_tasks:
        logger.info("waiting_background_tasks", count=len(background_tasks))
        await asyncio.wait(background_tasks, timeout=10)
    await engine.dispose()
    logger.info("shutdown_complete")


app = FastAPI(
    title="Chatbot API",
    version="1.0.0",
    description="Backend do sistema de chatbot inteligente com automação",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Middleware — ordem importa: o último adicionado executa primeiro
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [settings.app_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

# Rotas
app.include_router(health.router)
app.include_router(messages.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(slack.router, prefix="/api/v1")
