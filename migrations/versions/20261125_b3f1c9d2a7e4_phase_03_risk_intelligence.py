"""phase 03 risk intelligence storage

Revision ID: b3f1c9d2a7e4
Revises: 9a4c18e2d760
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3f1c9d2a7e4"
down_revision: str | None = "9a4c18e2d760"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "ml_model",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("dataset_name", sa.String(length=191), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("training_params", sa.JSON(), nullable=False),
        sa.Column("feature_config", sa.JSON(), nullable=False),
        sa.Column("hyperparameters", sa.JSON(), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("per_label_metrics", JSONB, nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_model")),
        sa.UniqueConstraint("name", "version", name=op.f("uq_ml_model_name_version")),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset.id"],
            name=op.f("fk_ml_model_dataset_id_dataset"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_ml_model_status_trained", "ml_model", ["status", "trained_at"], unique=False
    )

    op.create_table(
        "risk_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("ml_model_id", sa.String(length=191), nullable=True),
        sa.Column("risk_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "risk_level",
            sa.Enum(
                "normal",
                "low",
                "medium",
                "high",
                "critical",
                name="riskseverity",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "suggested_action",
            sa.Enum(
                "allow",
                "warn",
                "review",
                "block",
                "restrict",
                name="decisionaction",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("categories", JSONB, nullable=False),
        sa.Column("detection_methods", sa.JSON(), nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column("explanation", JSONB, nullable=False),
        sa.Column("detector_versions", sa.JSON(), nullable=False),
        sa.Column("timings", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_result")),
        sa.UniqueConstraint("message_id", name=op.f("uq_risk_result_message_id")),
        sa.CheckConstraint(
            "risk_score >= 0 AND risk_score <= 1",
            name=op.f("ck_risk_result_risk_score_range"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_risk_result_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset.id"],
            name=op.f("fk_risk_result_dataset_id_dataset"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name=op.f("fk_risk_result_message_id_message"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ml_model_id"],
            ["ml_model.id"],
            name=op.f("fk_risk_result_ml_model_id_ml_model"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_risk_result_dataset_detected",
        "risk_result",
        ["dataset_id", "detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_risk_result_level_detected",
        "risk_result",
        ["risk_level", "detected_at"],
        unique=False,
    )

    op.create_table(
        "evaluation_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=191), nullable=False),
        sa.Column("dataset_name", sa.String(length=191), nullable=False),
        sa.Column("split", sa.String(length=16), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("per_label", JSONB, nullable=False),
        sa.Column("case_counts", sa.JSON(), nullable=False),
        sa.Column("leakage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_run")),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ml_model.id"],
            name=op.f("fk_evaluation_run_model_id_ml_model"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_evaluation_run_model_created",
        "evaluation_run",
        ["model_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "evaluation_case",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("error_type", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("predicted_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("truth_label", sa.String(length=16), nullable=False),
        sa.Column("truth_category", sa.String(length=64), nullable=True),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_case")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_run.id"],
            name=op.f("fk_evaluation_case_run_id_evaluation_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name=op.f("fk_evaluation_case_message_id_message"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_evaluation_case_run_type", "evaluation_case", ["run_id", "error_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_case_run_type", table_name="evaluation_case")
    op.drop_table("evaluation_case")
    op.drop_index("ix_evaluation_run_model_created", table_name="evaluation_run")
    op.drop_table("evaluation_run")
    op.drop_index("ix_risk_result_level_detected", table_name="risk_result")
    op.drop_index("ix_risk_result_dataset_detected", table_name="risk_result")
    op.drop_table("risk_result")
    op.drop_index("ix_ml_model_status_trained", table_name="ml_model")
    op.drop_table("ml_model")
