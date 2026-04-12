"""Adiciona tabela de feedback de atendimento

Revision ID: 003_feedback
Revises: 002_performance_indexes
Create Date: 2025-01-03 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_feedback"
down_revision: Union[str, None] = "002_performance_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabela de feedback enviado pelo usuário ao final do atendimento
    op.create_table(
        "feedbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        # CSAT: 1-5
        sa.Column("rating", sa.Integer(), nullable=True),
        # Comentário livre
        sa.Column("comment", sa.Text(), nullable=True),
        # Quem atendeu (bot ou agente)
        sa.Column("resolved_by", sa.String(50), nullable=True),  # "bot" | "agent"
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_feedbacks_conversation_id", "feedbacks", ["conversation_id"])
    op.create_index("ix_feedbacks_rating", "feedbacks", ["rating", "created_at"])

    # Adiciona coluna de duração em segundos na conversa (preenchida ao fechar)
    op.add_column("conversations", sa.Column(
        "duration_seconds",
        sa.Integer(),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("conversations", "duration_seconds")
    op.drop_table("feedbacks")
