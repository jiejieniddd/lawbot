"""auth_challenges for password reset / login fail dual-write

Revision ID: 008_auth_challenges
Revises: 007_mail_settings
Create Date: 2026-11-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_auth_challenges"
down_revision: Union[str, None] = "007_mail_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_auth_challenges_purpose_subject_created",
        "auth_challenges",
        ["purpose", "subject", "created_at"],
    )
    # Partial index for active challenges (Postgres); ignored/no-op style on others via dialect
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_auth_challenges_active",
            "auth_challenges",
            ["purpose", "subject"],
            postgresql_where=sa.text("used_at IS NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_auth_challenges_active", table_name="auth_challenges")
    op.drop_index("ix_auth_challenges_purpose_subject_created", table_name="auth_challenges")
    op.drop_table("auth_challenges")
