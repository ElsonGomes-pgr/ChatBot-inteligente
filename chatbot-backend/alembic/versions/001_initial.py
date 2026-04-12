"""Criacao inicial das tabelas: users, conversations, messages

Revision ID: 001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────
    channel_enum = postgresql.ENUM(
        "messenger", "website", "whatsapp", "api",
        name="channelenum", create_type=True
    )
    intent_enum = postgresql.ENUM(
        "support", "sales", "question", "urgency", "unknown",
        name="intentenum", create_type=True
    )
    message_role_enum = postgresql.ENUM(
        "user", "bot", "agent",
        name="messageroelenum", create_type=True
    )
    conversation_status_enum = postgresql.ENUM(
        "active", "human_mode", "closed", "waiting",
        name="conversationstatusenum", create_type=True
    )

    channel_enum.create(op.get_bind(), checkfirst=True)
    intent_enum.create(op.get_bind(), checkfirst=True)
    message_role_enum.create(op.get_bind(), checkfirst=True)
    conversation_status_enum.create(op.get_bind(), checkfirst=True)

    # ── Tabela: users ──────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("channel", sa.Enum("messenger", "website", "whatsapp", "api", name="channelenum"), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_external_id", "users", ["external_id"], unique=True)

    # ── Tabela: conversations ──────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.Enum("messenger", "website", "whatsapp", "api", name="channelenum"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "human_mode", "closed", "waiting", name="conversationstatusenum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("human_mode", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("intent", sa.Enum("support", "sales", "question", "urgency", "unknown", name="intentenum"), nullable=True),
        sa.Column("urgency_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("assigned_agent_id", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_status", "conversations", ["status"])

    # ── Tabela: messages ───────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.Enum("user", "bot", "agent", name="messageroelenum"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("intent", sa.Enum("support", "sales", "question", "urgency", "unknown", name="intentenum"), nullable=True),
        sa.Column("urgency_score", sa.Float(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS messageroelenum")
    op.execute("DROP TYPE IF EXISTS conversationstatusenum")
    op.execute("DROP TYPE IF EXISTS intentenum")
    op.execute("DROP TYPE IF EXISTS channelenum")
