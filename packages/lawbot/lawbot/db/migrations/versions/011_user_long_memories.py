"""user_long_memories for cross-session MemoryStore

Revision ID: 011_user_long_memories
Revises: 010_embedding_settings
Create Date: 2026-11-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_user_long_memories"
down_revision: Union[str, None] = "010_embedding_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_long_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mem_key", sa.String(length=128), nullable=False),
        sa.Column("text", sa.String(length=1000), nullable=False),
        sa.Column("mem_type", sa.String(length=32), nullable=False, server_default="case_fact"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "mem_key", name="ix_user_long_memories_user_key"),
    )
    op.create_index("ix_user_long_memories_user_id", "user_long_memories", ["user_id"])
    op.create_index(
        "ix_user_long_memories_user_updated",
        "user_long_memories",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_long_memories_user_updated", table_name="user_long_memories")
    op.drop_index("ix_user_long_memories_user_id", table_name="user_long_memories")
    op.drop_table("user_long_memories")
