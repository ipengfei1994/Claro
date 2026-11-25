"""add authoritative player blacklist storage

Revision ID: 9a4c18e2d760
Revises: 56deb7122332
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a4c18e2d760"
down_revision: str | None = "56deb7122332"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_blacklist_entry",
        sa.Column("player_ref", sa.String(length=191), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_blacklist_entry")),
        sa.UniqueConstraint("player_ref", name=op.f("uq_player_blacklist_entry_player_ref")),
    )
    op.create_index(
        "ix_player_blacklist_entry_blocked_until",
        "player_blacklist_entry",
        ["blocked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_player_blacklist_entry_blocked_until", table_name="player_blacklist_entry")
    op.drop_table("player_blacklist_entry")
