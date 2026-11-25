"""extend rule type columns for phase 03 rule kinds

Revision ID: c4a7e1d9b2f6
Revises: b3f1c9d2a7e4
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a7e1d9b2f6"
down_revision: str | None = "b3f1c9d2a7e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 02 sized these VARCHAR columns from the then-known enum values.
    # url_pattern, blacklist and repetition are longer, so widen explicitly.
    with op.batch_alter_table("detection_rule") as batch:
        batch.alter_column(
            "rule_type",
            existing_type=sa.String(length=7),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
    with op.batch_alter_table("policy_rule") as batch:
        batch.alter_column(
            "rule_type",
            existing_type=sa.String(length=7),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("policy_rule") as batch:
        batch.alter_column(
            "rule_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
    with op.batch_alter_table("detection_rule") as batch:
        batch.alter_column(
            "rule_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
