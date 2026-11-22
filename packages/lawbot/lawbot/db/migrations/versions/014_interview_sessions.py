"""interview_sessions and interview_turns for CareerBot mock interview

Revision ID: 014_interview_sessions
Revises: 013_user_jds
Create Date: 2026-11-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_interview_sessions"
down_revision: Union[str, None] = "013_user_jds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="in_progress"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("target_role", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("resume_id", sa.Uuid(), nullable=True),
        sa.Column("jd_id", sa.Uuid(), nullable=True),
        sa.Column("resume_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("jd_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("report", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["resume_id"], ["user_resumes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["jd_id"], ["user_jds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_sessions_user_id", "interview_sessions", ["user_id"])
    op.create_index(
        "ix_interview_sessions_user_updated",
        "interview_sessions",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "interview_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_text", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_interview_turns_session_seq"),
    )
    op.create_index("ix_interview_turns_session_id", "interview_turns", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_turns_session_id", table_name="interview_turns")
    op.drop_table("interview_turns")
    op.drop_index("ix_interview_sessions_user_updated", table_name="interview_sessions")
    op.drop_index("ix_interview_sessions_user_id", table_name="interview_sessions")
    op.drop_table("interview_sessions")
