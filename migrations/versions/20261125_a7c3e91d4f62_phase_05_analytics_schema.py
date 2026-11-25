"""phase 05 analytics schema

Revision ID: a7c3e91d4f62
Revises: c79ffc3a04ff
Create Date: 2026-11-25 16:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c3e91d4f62"
down_revision: str | None = "c79ffc3a04ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_replay_run",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset_name", sa.String(length=191), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_label", sa.String(length=191), nullable=False),
        sa.Column("candidate_label", sa.String(length=191), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("definition_version", sa.String(length=32), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("simulation", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("executed_by", sa.String(length=191), nullable=False),
        sa.CheckConstraint("sample_count >= 0", name="ck_analytics_replay_run_sample_count"),
        sa.PrimaryKeyConstraint("run_id", name="pk_analytics_replay_run"),
    )
    op.create_index(
        "ix_analytics_replay_run_created", "analytics_replay_run", ["created_at"], unique=False
    )
    op.create_table(
        "analytics_replay_case",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_hit", sa.Boolean(), nullable=False),
        sa.Column("candidate_hit", sa.Boolean(), nullable=False),
        sa.Column("baseline_action", sa.String(length=32), nullable=False),
        sa.Column("candidate_action", sa.String(length=32), nullable=False),
        sa.Column("baseline_policy_key", sa.String(length=120), nullable=True),
        sa.Column("candidate_policy_key", sa.String(length=120), nullable=True),
        sa.Column("diff_type", sa.String(length=32), nullable=False),
        sa.Column("truth_label", sa.String(length=16), nullable=True),
        sa.Column("baseline_fp", sa.Boolean(), nullable=False),
        sa.Column("baseline_fn", sa.Boolean(), nullable=False),
        sa.Column("candidate_fp", sa.Boolean(), nullable=False),
        sa.Column("candidate_fn", sa.Boolean(), nullable=False),
        sa.Column("risk_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analytics_replay_run.run_id"],
            name="fk_analytics_replay_case_run_id_analytics_replay_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analytics_replay_case"),
        sa.UniqueConstraint("run_id", "message_id", name="uq_analytics_replay_case_run_message"),
    )
    op.create_index(
        "ix_analytics_replay_case_run", "analytics_replay_case", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_replay_case_run", table_name="analytics_replay_case")
    op.drop_table("analytics_replay_case")
    op.drop_index("ix_analytics_replay_run_created", table_name="analytics_replay_run")
    op.drop_table("analytics_replay_run")
