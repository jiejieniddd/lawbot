"""mail_settings singleton for SMTP and password reset

Revision ID: 007_mail_settings
Revises: 006_rbac
Create Date: 2026-11-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_mail_settings"
down_revision: Union[str, None] = "006_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mail_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("smtp_host", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_security", sa.String(length=20), nullable=False, server_default="starttls"),
        sa.Column("smtp_username", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("smtp_password_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("from_address", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("from_name", sa.String(length=120), nullable=False, server_default="LawBot"),
        sa.Column("code_ttl_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("resend_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mail_settings")
