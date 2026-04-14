import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import verify_api_key, verify_webhook_secret
from app.core.tasks import create_tracked_task
from app.db.database import get_db
from app.db.redis_client import get_redis, SessionCache
from app.models.models import Conversation, ConversationStatusEnum, MessageRoleEnum, User
from app.schemas.schemas import AgentReply
from app.services.conversation_service import ConversationService
from app.services.n8n_callback import N8nCallbackService
from app.services.timeout_service import TimeoutService

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = structlog.get_logger()
settings = get_settings()
n8n_callback = N8nCallbackService()


# ── Listagem — protegido por API key (painel / agentes) ───────────────────

@router.get("/")
async def list_conversations(
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    """Lista conversas com filtro opcional por status. Para o painel do agente."""
    query = select(Conversation).order_by(Conversation.started_at.desc()).limit(min(limit, 200))

    if status:
        query = query.where(Conversation.status == ConversationStatusEnum(status))

    result = await db.execute(query)
    conversations = result.scalars().all()

    return [
        {
            "id": str(c.id),
            "user_id": str(c.user_id),
            "channel": c.channel.value,
            "status": c.status.value,
            "intent": c.intent.value if c.intent else None,
            "urgency_score": c.urgency_score,
            "human_mode": c.human_mode,
            "assigned_agent_id": c.assigned_agent_id,
            "started_at": c.started_at.isoformat() if c.started_at else None,
        }
        for c in conversations
    ]


# ── GET por ID — protegido por API key (painel / agentes) ─────────────────

@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    """Retorna conversa com histórico completo de mensagens."""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conv_uuid)
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    return {
        "id": str(conversation.id),
        "user_id": str(conversation.user_id),
        "channel": conversation.channel.value,
        "status": conversation.status.value,
        "intent": conversation.intent.value if conversation.intent else None,
        "urgency_score": conversation.urgency_score,
        "human_mode": conversation.human_mode,
        "assigned_agent_id": conversation.assigned_agent_id,
        "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
        "closed_at": conversation.closed_at.isoformat() if conversation.closed_at else None,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role.value,
                "content": m.content,
                "intent": m.intent.value if m.intent else None,
                "urgency_score": m.urgency_score,
                "tokens_used": m.tokens_used,
                "created_at": m.created_at.isoformat(),
            }
            for m in conversation.messages
        ],
    }


# ── POST — handoff/close protegido por webhook secret (n8n) ──────────────

@router.post("/{conversation_id}/handoff")
async def handoff_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(verify_webhook_secret),
):
    """Transfere conversa para atendimento humano."""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    cache = SessionCache(redis)
    svc = ConversationService(db, cache)

    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    await svc.trigger_human_handoff(conversation, agent_id="pending")
    return {"ok": True, "conversation_id": conversation_id, "status": "human_mode"}


@router.post("/{conversation_id}/close")
async def close_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(verify_api_key),
):
    """Encerra conversa."""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    cache = SessionCache(redis)
    svc = ConversationService(db, cache)

    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    await svc.close_conversation(conversation)
    return {"ok": True, "conversation_id": conversation_id, "status": "closed"}


# ── POST — agente humano responde ao usuário ──────────────────────────────

@router.post("/{conversation_id}/reply")
async def agent_reply(
    conversation_id: str,
    body: AgentReply,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(verify_api_key),
):
    """
    Agente humano envia mensagem de volta ao usuário.
    Salva no DB e notifica o n8n para entregar no canal original.
    """
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    cache = SessionCache(redis)
    svc = ConversationService(db, cache)

    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    if not conversation.human_mode:
        raise HTTPException(status_code=400, detail="Conversa não está em modo humano")

    # Valida que o agente está atribuído a esta conversa
    if conversation.assigned_agent_id and conversation.assigned_agent_id != body.agent_id:
        raise HTTPException(
            status_code=403,
            detail="Este agente não está atribuído a esta conversa",
        )

    # Busca o external_id do usuário para entregar no canal correto
    user_result = await db.execute(
        select(User).where(User.id == conversation.user_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Salva mensagem do agente
    agent_msg = await svc.add_message(
        conversation.id,
        MessageRoleEnum.agent,
        body.text,
    )

    logger.info("agent_reply_saved",
                conversation_id=conversation_id,
                agent_id=body.agent_id)

    # Notifica n8n em background para entregar a resposta no canal do usuário
    create_tracked_task(
        n8n_callback.notify_agent_reply(
            conversation_id=conversation_id,
            channel=conversation.channel.value,
            text=body.text,
            agent_id=body.agent_id,
            external_user_id=user.external_id,
        )
    )

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "message_id": str(agent_msg.id),
    }


# ── POST — cleanup de conversas inativas (chamado por cron do n8n) ────────

@router.post("/cleanup")
async def cleanup_stale_conversations(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(verify_webhook_secret),
):
    """
    Fecha conversas inativas. Chamar via cron no n8n a cada 15 minutos.
    """
    cache = SessionCache(redis)
    timeout_svc = TimeoutService(db, cache)
    closed = await timeout_svc.close_stale_conversations()
    return {"ok": True, "conversations_closed": closed}
