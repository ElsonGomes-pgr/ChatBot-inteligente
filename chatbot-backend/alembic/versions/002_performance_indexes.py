"""Adiciona indices de performance e tags ao usuario

Revision ID: 002_performance_indexes
Revises: 001_initial
Create Date: 2025-01-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_performance_indexes"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Coluna tags para segmentar usuários (ex: ["vip", "reclamante"])
    op.add_column("users", sa.Column(
        "tags",
        sa.JSON(),
        nullable=False,
        server_default="[]",
    ))

    # Índice parcial: conversas ativas (consulta mais frequente)
    op.execute("""
        CREATE INDEX ix_conversations_active
        ON conversations (user_id, started_at DESC)
        WHERE status IN ('active', 'human_mode', 'waiting')
    """)

    # Índice para relatórios por canal + período
    op.create_index(
        "ix_conversations_channel_started",
        "conversations",
        ["channel", "started_at"],
    )

    # Índice para busca de mensagens por role (ex: todas as msgs do bot)
    op.create_index(
        "ix_messages_role",
        "messages",
        ["role", "created_at"],
    )

    # Índice para somar tokens por conversa (relatório de custo)
    op.create_index(
        "ix_messages_tokens",
        "messages",
        ["conversation_id", "tokens_used"],
    )

    # Índice no email do usuário para busca por CRM
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_messages_tokens", table_name="messages")
    op.drop_index("ix_messages_role", table_name="messages")
    op.drop_index("ix_conversations_channel_started", table_name="conversations")
    op.execute("DROP INDEX IF EXISTS ix_conversations_active")
    op.drop_column("users", "tags")
