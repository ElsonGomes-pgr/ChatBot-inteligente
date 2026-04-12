import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.database import get_db
from app.db.redis_client import get_redis

router = APIRouter(tags=["health"])
logger = structlog.get_logger()


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Verifica saúde do backend, banco e Redis."""
    db_ok = True
    redis_ok = True

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    try:
        await redis.ping()
    except Exception:
        redis_ok = False

    status = "ok" if (db_ok and redis_ok) else "degraded"

    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "version": "1.0.0",
    }
