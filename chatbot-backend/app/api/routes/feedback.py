"""
Endpoints de feedback do atendimento.
- POST /conversations/{id}/feedback — usuário envia avaliação
- GET /feedback/stats — métricas agregadas (para painel)
"""

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.security import verify_webhook_secret, verify_api_key
from app.db.database import get_db
from app.models.models import Conversation, Feedback, ResolvedByEnum
from app.schemas.schemas import FeedbackCreate, FeedbackResponse

router = APIRouter(tags=["feedback"])
logger = structlog.get_logger()


@router.post("/conversations/{conversation_id}/feedback", response_model=FeedbackResponse)
async def create_feedback(
    conversation_id: str,
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_webhook_secret),
):
    """
    Recebe feedback do usuário sobre o atendimento.
    Chamado pelo n8n ao final da conversa.
    """
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # Verifica se já existe feedback para esta conversa
    existing = await db.execute(
        select(Feedback).where(Feedback.conversation_id == conv_uuid)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Feedback já enviado para esta conversa")

    # Determina quem resolveu (bot ou agente)
    resolved_by = ResolvedByEnum.agent if conversation.human_mode else ResolvedByEnum.bot

    feedback = Feedback(
        conversation_id=conv_uuid,
        rating=body.rating,
        comment=body.comment,
        resolved_by=resolved_by,
    )
    db.add(feedback)
    await db.flush()

    logger.info("feedback_created",
                conversation_id=conversation_id,
                rating=body.rating,
                resolved_by=resolved_by.value)

    return FeedbackResponse(
        id=str(feedback.id),
        conversation_id=conversation_id,
        rating=feedback.rating,
        comment=feedback.comment,
        resolved_by=resolved_by.value,
        created_at=feedback.created_at.isoformat(),
    )


@router.get("/feedback/stats")
async def feedback_stats(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    """
    Retorna estatísticas agregadas de feedback para o painel.
    """
    result = await db.execute(
        select(
            func.count(Feedback.id).label("total"),
            func.avg(Feedback.rating).label("avg_rating"),
            func.count(Feedback.id).filter(Feedback.rating >= 4).label("positive"),
            func.count(Feedback.id).filter(Feedback.rating <= 2).label("negative"),
        )
    )
    row = result.one()

    total = row.total or 0
    avg_rating = round(float(row.avg_rating), 2) if row.avg_rating else 0.0
    positive = row.positive or 0
    negative = row.negative or 0

    # Stats por tipo de resolução
    by_resolver = await db.execute(
        select(
            Feedback.resolved_by,
            func.count(Feedback.id).label("count"),
            func.avg(Feedback.rating).label("avg_rating"),
        ).group_by(Feedback.resolved_by)
    )

    resolver_stats = {
        r.resolved_by.value if r.resolved_by else "unknown": {
            "count": r.count,
            "avg_rating": round(float(r.avg_rating), 2) if r.avg_rating else 0.0,
        }
        for r in by_resolver.all()
    }

    return {
        "total_feedbacks": total,
        "avg_rating": avg_rating,
        "positive_count": positive,
        "negative_count": negative,
        "csat_score": round((positive / total) * 100, 1) if total > 0 else 0.0,
        "by_resolver": resolver_stats,
    }
