"""Promote seed root account to super_admin

Revision ID: 004_super_admin
Revises: 003_refresh_tokens
Create Date: 2026-11-02

"""

from typing import Sequence, Union

from alembic import op

revision: str = "004_super_admin"
down_revision: Union[str, None] = "003_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Compatibility: fixed product seed account "root" becomes the unique super_admin
    op.execute(
        """
        UPDATE users
        SET role = 'super_admin'
        WHERE lower(email) = 'root'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET role = 'admin'
        WHERE role = 'super_admin'
        """
    )
