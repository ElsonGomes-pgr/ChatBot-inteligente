"""
Endpoint de métricas operacionais.

Retorna estatísticas em tempo real do sistema:
- Total de conversas por status
- Taxa de handoff
- Tempo médio de resposta
- Volume por canal
"""

from datetime import datetime, UTC, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app.core.security import verify_api_key
from app.db.database import get_db
from app.models.models import Conversation, Message, ConversationStatusEnum, ChannelEnum, MessageRoleEnum

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/")
async def get_metrics(
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    """Retorna métricas operacionais das últimas N horas (padrão: 24)."""
    since = datetime.now(UTC) - timedelta(hours=min(hours, 720))  # max 30 dias

    # Conversas por status
    status_result = await db.execute(
        select(
            Conversation.status,
            func.count(Conversation.id),
        )
        .where(Conversation.started_at >= since)
        .group_by(Conversation.status)
    )
    by_status = {row[0].value: row[1] for row in status_result.all()}

    # Volume por canal
    channel_result = await db.execute(
        select(
            Conversation.channel,
            func.count(Conversation.id),
        )
        .where(Conversation.started_at >= since)
        .group_by(Conversation.channel)
    )
    by_channel = {row[0].value: row[1] for row in channel_result.all()}

    # Taxa de handoff
    total_convs = sum(by_status.values())
    handoff_count = by_status.get("human_mode", 0)
    handoff_rate = (handoff_count / total_convs * 100) if total_convs > 0 else 0.0

    # Total de mensagens por role
    role_result = await db.execute(
        select(
            Message.role,
            func.count(Message.id),
        )
        .where(Message.created_at >= since)
        .group_by(Message.role)
    )
    by_role = {row[0].value: row[1] for row in role_result.all()}

    # Média de mensagens por conversa
    msg_count_result = await db.execute(
        select(func.count(Message.id))
        .where(Message.created_at >= since)
    )
    total_msgs = msg_count_result.scalar() or 0
    avg_msgs = (total_msgs / total_convs) if total_convs > 0 else 0.0

    # Tokens totais usados
    tokens_result = await db.execute(
        select(func.coalesce(func.sum(Message.tokens_used), 0))
        .where(Message.created_at >= since)
    )
    total_tokens = tokens_result.scalar() or 0

    return {
        "period_hours": hours,
        "since": since.isoformat(),
        "conversations": {
            "total": total_convs,
            "by_status": by_status,
            "by_channel": by_channel,
            "handoff_rate_percent": round(handoff_rate, 1),
        },
        "messages": {
            "total": total_msgs,
            "by_role": by_role,
            "avg_per_conversation": round(avg_msgs, 1),
        },
        "tokens": {
            "total_used": total_tokens,
        },
    }
