"""embedding_settings singleton for vector embedding config

Revision ID: 010_embedding_settings
Revises: 009_user_preferences
Create Date: 2026-11-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_embedding_settings"
down_revision: Union[str, None] = "009_user_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embedding_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="auto"),
        sa.Column("embedding_model", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("api_base", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="384"),
        sa.Column("reuse_llm_provider", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("embedding_settings")
