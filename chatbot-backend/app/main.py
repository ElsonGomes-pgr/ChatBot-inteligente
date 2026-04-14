import asyncio
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import RateLimitMiddleware
from app.core.tasks import background_tasks
from app.db.database import get_engine
from app.models.models import Base
from app.api.routes import messages, conversations, health, slack, metrics

settings = get_settings()

# Configura logging estruturado com proteção PII
configure_logging(debug=settings.debug)

# Inicializa Sentry se configurado
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            environment=settings.environment,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            send_default_pii=False,  # LGPD: não enviar PII para o Sentry
        )
    except ImportError:
        pass  # sentry-sdk não instalado, ignorar silenciosamente

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
def _get_cors_origins() -> list[str]:
    if settings.debug:
        return ["*"]
    origins = [settings.app_base_url]
    if settings.cors_allowed_origins:
        origins.extend(o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip())
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["X-API-Key", "X-Webhook-Secret", "Content-Type", "Authorization"],
)
app.add_middleware(RateLimitMiddleware)

# Rotas
app.include_router(health.router)
app.include_router(messages.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(slack.router, prefix="/api/v1")
app.include_router(metrics.router, prefix="/api/v1")
