import uuid
from datetime import datetime, UTC
from sqlalchemy import (
    String, Text, Boolean, Float, Integer,
    ForeignKey, DateTime, JSON, Enum as SAEnum, Uuid
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    pass


class ChannelEnum(str, enum.Enum):
    messenger = "messenger"
    website = "website"
    whatsapp = "whatsapp"
    api = "api"


class IntentEnum(str, enum.Enum):
    support = "support"
    sales = "sales"
    question = "question"
    urgency = "urgency"
    unknown = "unknown"


class MessageRoleEnum(str, enum.Enum):
    user = "user"
    bot = "bot"
    agent = "agent"


class ConversationStatusEnum(str, enum.Enum):
    active = "active"
    human_mode = "human_mode"
    closed = "closed"
    waiting = "waiting"


class ResolvedByEnum(str, enum.Enum):
    bot = "bot"
    agent = "agent"


def _utcnow():
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    channel: Mapped[ChannelEnum] = mapped_column(SAEnum(ChannelEnum))
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    rating: Mapped[int | None] = mapped_column(Integer)  # CSAT 1-5
    comment: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[ResolvedByEnum | None] = mapped_column(SAEnum(ResolvedByEnum))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="feedback")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[ChannelEnum] = mapped_column(SAEnum(ChannelEnum))
    status: Mapped[ConversationStatusEnum] = mapped_column(
        SAEnum(ConversationStatusEnum), default=ConversationStatusEnum.active
    )
    human_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    intent: Mapped[IntentEnum | None] = mapped_column(SAEnum(IntentEnum))
    urgency_score: Mapped[float] = mapped_column(Float, default=0.0)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")
    feedback: Mapped["Feedback | None"] = relationship(back_populates="conversation", uselist=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[MessageRoleEnum] = mapped_column(SAEnum(MessageRoleEnum))
    content: Mapped[str] = mapped_column(Text)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    intent: Mapped[IntentEnum | None] = mapped_column(SAEnum(IntentEnum))
    urgency_score: Mapped[float | None] = mapped_column(Float)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
