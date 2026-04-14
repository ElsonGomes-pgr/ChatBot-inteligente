import uuid
from datetime import datetime, UTC
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models.models import (
    User, Conversation, Message,
    ChannelEnum, ConversationStatusEnum,
    IntentEnum, MessageRoleEnum
)
from app.schemas.schemas import IncomingMessage
from app.db.redis_client import SessionCache


class ConversationService:

    def __init__(self, db: AsyncSession, cache: SessionCache):
        self.db = db
        self.cache = cache

    # ── Usuário ────────────────────────────────────────────────────────────

    async def get_or_create_user(self, msg: IncomingMessage) -> User:
        result = await self.db.execute(
            select(User).where(
                and_(
                    User.external_id == msg.external_user_id,
                    User.channel == msg.channel,
                )
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                external_id=msg.external_user_id,
                channel=msg.channel,
                name=msg.user_name,
                email=msg.user_email,
                phone=msg.user_phone,
                metadata_=msg.metadata,
            )
            self.db.add(user)
            await self.db.flush()
        else:
            # Atualiza dados se o utilizador enviou info nova
            if msg.user_name and msg.user_name != user.name:
                user.name = msg.user_name
            if msg.user_email and msg.user_email != user.email:
                user.email = msg.user_email
            if msg.user_phone and msg.user_phone != user.phone:
                user.phone = msg.user_phone

        return user

    # ── Conversa ───────────────────────────────────────────────────────────

    async def get_active_conversation(self, user_id: uuid.UUID) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.status.in_([
                        ConversationStatusEnum.active,
                        ConversationStatusEnum.human_mode,
                        ConversationStatusEnum.waiting,
                    ])
                )
            )
            .order_by(Conversation.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_conversation(self, user: User, channel: ChannelEnum) -> Conversation:
        conversation = Conversation(
            user_id=user.id,
            channel=channel,
        )
        self.db.add(conversation)
        await self.db.flush()

        # Inicializa sessão no Redis
        await self.cache.set(str(conversation.id), {
            "conversation_id": str(conversation.id),
            "user_id": str(user.id),
            "channel": channel.value,
            "human_mode": False,
            "message_count": 0,
        })

        return conversation

    async def get_or_create_conversation(self, user: User, channel: ChannelEnum) -> Conversation:
        conversation = await self.get_active_conversation(user.id)
        if not conversation:
            conversation = await self.create_conversation(user, channel)
        return conversation

    # ── Mensagens ──────────────────────────────────────────────────────────

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: MessageRoleEnum,
        content: str,
        intent: IntentEnum | None = None,
        urgency_score: float | None = None,
        tokens_used: int = 0,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            intent=intent,
            urgency_score=urgency_score,
            tokens_used=tokens_used,
        )
        self.db.add(message)
        await self.db.flush()

        # Atualiza cache com última mensagem e incrementa contador
        session = await self.cache.get(str(conversation_id))
        msg_count = (session.get("message_count", 0) + 1) if session else 1
        await self.cache.update(str(conversation_id), {
            "last_message": content[:200],
            "message_count": msg_count,
        })

        return message

    async def get_recent_history(
        self, conversation_id: uuid.UUID, limit: int = 10
    ) -> list[dict]:
        """Retorna histórico recente no formato para o prompt da IA."""
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()

        # Inverte para ordem cronológica e formata para a IA
        return [
            {"role": m.role.value if m.role.value != "bot" else "assistant", "content": m.content}
            for m in reversed(messages)
        ]

    # ── Handoff ────────────────────────────────────────────────────────────

    async def trigger_human_handoff(
        self, conversation: Conversation, agent_id: str
    ) -> None:
        conversation.human_mode = True
        conversation.status = ConversationStatusEnum.human_mode
        conversation.assigned_agent_id = agent_id

        await self.cache.set_human_mode(str(conversation.id), agent_id)

    async def close_conversation(self, conversation: Conversation) -> None:
        now = datetime.now(UTC)
        conversation.status = ConversationStatusEnum.closed
        conversation.closed_at = now
        if conversation.started_at:
            started = conversation.started_at
            # Garante timezone-aware (SQLite retorna naive)
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            conversation.duration_seconds = int((now - started).total_seconds())
        await self.cache.delete(str(conversation.id))

    # ── Verificação de human_mode ──────────────────────────────────────────

    async def is_human_mode(self, conversation_id: str) -> bool:
        """Consulta Redis primeiro (mais rápido), fallback no DB."""
        session = await self.cache.get(conversation_id)
        if session:
            return session.get("human_mode", False)

        result = await self.db.execute(
            select(Conversation.human_mode)
            .where(Conversation.id == uuid.UUID(conversation_id))
        )
        row = result.first()
        return row[0] if row else False

    # ── Atualiza intenção da conversa ──────────────────────────────────────

    async def update_intent(
        self,
        conversation: Conversation,
        intent: IntentEnum,
        urgency_score: float,
    ) -> None:
        conversation.intent = intent
        conversation.urgency_score = urgency_score
