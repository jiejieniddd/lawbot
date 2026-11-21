"""user_resumes for CareerBot resume upload

Revision ID: 012_user_resumes
Revises: 011_user_long_memories
Create Date: 2026-11-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_user_resumes"
down_revision: Union[str, None] = "011_user_long_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_resumes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("mime", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("structured", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_resumes_user_id", "user_resumes", ["user_id"])
    op.create_index(
        "ix_user_resumes_user_active",
        "user_resumes",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_resumes_user_active", table_name="user_resumes")
    op.drop_index("ix_user_resumes_user_id", table_name="user_resumes")
    op.drop_table("user_resumes")
