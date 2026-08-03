"""Create sync_records table.

Revision ID: b8c83ca7aa53
Revises: 935c9f58df30
Create Date: 2026-08-02 09:58:21.866842
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c83ca7aa53"
down_revision: str | None = "935c9f58df30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create sync_records table."""
    op.create_table(
        "sync_records",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "server_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "user_id"),
    )
    op.create_index(
        op.f("ix_sync_records_server_updated_at"),
        "sync_records",
        ["server_updated_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop sync_records table."""
    op.drop_index(op.f("ix_sync_records_server_updated_at"), table_name="sync_records")
    op.drop_table("sync_records")
