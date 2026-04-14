"""
TimeoutService — fecha automaticamente conversas inativas.

Pode ser chamado:
  - Via cron job no n8n (recomendado): POST /api/v1/conversations/cleanup
  - Via task periódica dentro da app (alternativa)
"""

from datetime import datetime, UTC, timedelta
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from app.core.config import get_settings
from app.models.models import Conversation, ConversationStatusEnum, Message
from app.db.redis_client import SessionCache

logger = structlog.get_logger()
settings = get_settings()


class TimeoutService:

    def __init__(self, db: AsyncSession, cache: SessionCache):
        self.db = db
        self.cache = cache

    async def close_stale_conversations(self) -> int:
        """
        Fecha conversas que não tiveram atividade nos últimos N minutos.
        Conversas em human_mode usam o dobro do timeout (agentes precisam de mais tempo).
        Retorna quantidade de conversas fechadas.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=settings.conversation_timeout_minutes)
        human_cutoff = datetime.now(UTC) - timedelta(minutes=settings.conversation_timeout_minutes * 2)

        # Conversas ativas/waiting com timeout normal
        bot_stale = (
            select(Conversation.id)
            .where(
                and_(
                    Conversation.status.in_([
                        ConversationStatusEnum.active,
                        ConversationStatusEnum.waiting,
                    ]),
                    ~Conversation.id.in_(
                        select(Message.conversation_id)
                        .where(Message.created_at > cutoff)
                        .distinct()
                    ),
                )
            )
        )

        # Conversas em human_mode com timeout maior
        human_stale = (
            select(Conversation.id)
            .where(
                and_(
                    Conversation.status == ConversationStatusEnum.human_mode,
                    ~Conversation.id.in_(
                        select(Message.conversation_id)
                        .where(Message.created_at > human_cutoff)
                        .distinct()
                    ),
                )
            )
        )

        stale_query = bot_stale.union(human_stale)

        result = await self.db.execute(stale_query)
        stale_ids = [row[0] for row in result.all()]

        if not stale_ids:
            return 0

        # Fecha em batch
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id.in_(stale_ids))
            .values(
                status=ConversationStatusEnum.closed,
                closed_at=datetime.now(UTC),
            )
        )

        # Limpa sessões do Redis
        for cid in stale_ids:
            await self.cache.delete(str(cid))

        logger.info("stale_conversations_closed",
                     count=len(stale_ids),
                     timeout_minutes=settings.conversation_timeout_minutes)

        return len(stale_ids)
