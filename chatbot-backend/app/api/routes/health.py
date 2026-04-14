import httpx
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import get_settings
from app.db.database import get_db
from app.db.redis_client import get_redis

router = APIRouter(tags=["health"])
logger = structlog.get_logger()
settings = get_settings()


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Verifica saúde do backend, banco, Redis e n8n."""
    checks = {"database": "ok", "redis": "ok", "n8n": "ok"}

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "error"

    try:
        await redis.ping()
    except Exception:
        checks["redis"] = "error"

    # n8n — tenta aceder ao endpoint de health do n8n
    try:
        if settings.n8n_callback_url:
            # Deriva a base URL do n8n a partir do callback URL
            from urllib.parse import urlparse
            parsed = urlparse(settings.n8n_callback_url)
            n8n_base = f"{parsed.scheme}://{parsed.netloc}"
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{n8n_base}/healthz")
                if r.status_code != 200:
                    checks["n8n"] = "degraded"
        else:
            checks["n8n"] = "not_configured"
    except Exception:
        checks["n8n"] = "unreachable"

    all_ok = all(v == "ok" for v in checks.values())
    critical_ok = checks["database"] == "ok" and checks["redis"] == "ok"
    status = "ok" if all_ok else ("degraded" if critical_ok else "error")

    status_code = 200 if critical_ok else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            **checks,
            "version": "1.0.0",
        },
    )
