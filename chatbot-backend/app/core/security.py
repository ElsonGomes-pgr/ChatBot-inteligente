"""
Dependências de segurança reutilizáveis:
- verify_webhook_secret: valida X-Webhook-Secret (n8n → backend)
- verify_api_key: valida X-API-Key (painel/admin → backend)
- RateLimiter: middleware de rate limiting por IP usando Redis
"""

import hmac
import time
import structlog
from fastapi import Header, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


# ── Autenticação webhook (n8n → backend) ─────────────────────────────────

def verify_webhook_secret(x_webhook_secret: str = Header(...)):
    """Valida o secret enviado pelo n8n nos webhooks."""
    if not hmac.compare_digest(x_webhook_secret, settings.n8n_webhook_secret):
        raise HTTPException(status_code=401, detail="Webhook secret inválido")


# ── Autenticação API key (painel/agentes → backend) ──────────────────────

def verify_api_key(x_api_key: str = Header(...)):
    """Valida a chave de API para endpoints administrativos e de agente."""
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="API key não configurada no servidor")
    if not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API key inválida")


# ── Rate limiting por IP via Redis ────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Limita requests por IP usando Redis com janela deslizante de 1 minuto.
    Aplica-se apenas aos endpoints /api/. Health e docs ficam livres.
    """

    async def dispatch(self, request: Request, call_next):
        # Não limita health checks e docs
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Importa aqui para evitar circular import no startup
        from app.db.redis_client import get_redis

        try:
            redis = await get_redis()
            client_ip = request.client.host if request.client else "unknown"
            key = f"ratelimit:{client_ip}"
            window = 60  # 1 minuto

            current = await redis.get(key)
            if current and int(current) >= settings.rate_limit_per_minute:
                logger.warning("rate_limit_exceeded", ip=client_ip)
                return Response(
                    content='{"detail":"Rate limit excedido. Tente novamente em 1 minuto."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(window)},
                )

            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window)
            await pipe.execute()

        except Exception as e:
            # Se Redis falhar, deixa passar (fail-open) — não bloqueia o serviço
            logger.warning("rate_limit_redis_error", error=str(e))

        return await call_next(request)


# ── Validação de assinatura Meta/Messenger ────────────────────────────────

def verify_meta_signature(payload: bytes, signature_header: str) -> bool:
    """
    Valida X-Hub-Signature-256 enviada pela Meta em cada webhook do Messenger.
    Deve ser chamada no n8n ou no endpoint que recebe eventos da Meta diretamente.
    """
    if not settings.meta_app_secret:
        logger.warning("meta_app_secret_not_configured")
        return False

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        settings.meta_app_secret.encode(),
        payload,
        "sha256",
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)
