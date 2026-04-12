"""
Endpoint que recebe interações do Slack (Block Kit actions).
O Slack faz POST aqui quando o agente clica em "Assumir conversa".

Configurar em: api.slack.com → seu app → Interactivity & Shortcuts
  Request URL: https://SEU_DOMINIO/api/v1/slack/actions
"""

import json
import hmac
import hashlib
import time
import structlog
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_db
from app.db.redis_client import get_redis, SessionCache
from app.models.models import Conversation
from app.services.conversation_service import ConversationService
from app.services.slack_service import SlackService

router = APIRouter(prefix="/slack", tags=["slack"])
logger = structlog.get_logger()
settings = get_settings()
slack_service = SlackService()


async def verify_slack_signature(request: Request) -> bytes:
    """Verifica assinatura do Slack para garantir que a requisição é legítima."""
    body = await request.body()

    slack_signature = request.headers.get("X-Slack-Signature", "")
    slack_timestamp = request.headers.get("X-Slack-Request-Timestamp", "")

    # Rejeita requests com mais de 5 minutos (previne replay attacks)
    if abs(time.time() - int(slack_timestamp)) > 300:
        raise HTTPException(status_code=400, detail="Request timestamp inválido")

    sig_basestring = f"v0:{slack_timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, slack_signature):
        raise HTTPException(status_code=401, detail="Assinatura Slack inválida")

    return body


@router.post("/actions")
async def slack_actions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Recebe ações do Slack (clique em botões do Block Kit).
    O Slack envia um form-encoded com campo 'payload' em JSON.
    """
    body = await verify_slack_signature(request)

    # Slack envia como application/x-www-form-urlencoded
    form = await request.form()
    raw_payload = form.get("payload")
    if not raw_payload:
        raise HTTPException(status_code=400, detail="Payload ausente")

    payload = json.loads(raw_payload)
    action_id = payload.get("actions", [{}])[0].get("action_id")

    if action_id == "assume_conversation":
        return await _handle_assume(payload, db, redis)

    # Outras ações — ignora silenciosamente
    return {"ok": True}


async def _handle_assume(payload: dict, db: AsyncSession, redis) -> dict:
    """Agente clicou em 'Assumir conversa'."""
    action = payload["actions"][0]
    conversation_id = action["value"]

    # Dados do agente que clicou
    agent = payload.get("user", {})
    agent_slack_id = agent.get("id", "unknown")
    agent_name = agent.get("name", "Agente")

    # Canal e timestamp da mensagem original (para editar depois)
    channel_id = payload.get("channel", {}).get("id")
    message_ts = payload.get("message", {}).get("ts")

    logger.info("agent_assuming_conversation",
                conversation_id=conversation_id,
                agent=agent_name)

    # Atualiza conversa no banco
    cache = SessionCache(redis)
    svc = ConversationService(db, cache)

    try:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id  # type: ignore
            )
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            logger.warning("conversation_not_found", conversation_id=conversation_id)
            # Mesmo assim, responde OK ao Slack para não mostrar erro
            return {"ok": True}

        await svc.trigger_human_handoff(conversation, agent_id=agent_slack_id)
        await db.commit()

        # Edita a mensagem no Slack para marcar como assumida
        if channel_id and message_ts and settings.slack_bot_token:
            await slack_service.update_message_assumed(
                channel_id=channel_id,
                message_ts=message_ts,
                agent_name=agent_name,
                conversation_id=conversation_id,
            )

        logger.info("conversation_assumed",
                    conversation_id=conversation_id,
                    agent=agent_name)

    except Exception as e:
        logger.error("assume_conversation_failed", error=str(e))

    return {"ok": True}
