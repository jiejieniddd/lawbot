"""Add users.avatar_url

Revision ID: 005_user_avatar
Revises: 004_super_admin
Create Date: 2026-11-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_user_avatar"
down_revision: Union[str, None] = "004_super_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
