"""create_bank_connections_table.

Revision ID: 9b7bdd7ac58f
Revises: a5d1b5e3f4a0
Create Date: 2026-08-25 14:14:28.002138
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b7bdd7ac58f"
down_revision: str | None = "a5d1b5e3f4a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create bank_connections table."""
    op.create_table(
        "bank_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop bank_connections table."""
    op.drop_table("bank_connections")
