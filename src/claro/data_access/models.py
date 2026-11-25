from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from claro.domain.enums import (
    CaseStatus,
    DatasetSplit,
    DecisionAction,
    EnforcementStatus,
    EnforcementTargetType,
    FeedbackType,
    GovernanceDecisionStatus,
    GroundTruthLabel,
    MessageDisplayStatus,
    MessageStatus,
    ModerationAction,
    OutboxStatus,
    PolicyType,
    ProcessingStage,
    ProcessingStatus,
    RiskCategory,
    RiskSeverity,
    RuleStatus,
    RuleType,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        normalized = value.astimezone(UTC)
        if dialect.name == "postgresql":
            return normalized
        return normalized.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def portable_enum(enum_type: type[Enum], *, length: int | None = None) -> SAEnum:
    kwargs = {"length": length} if length is not None else {}
    return SAEnum(
        enum_type,
        native_enum=False,
        values_callable=lambda enum_class: [item.value for item in enum_class],
        validate_strings=True,
        **kwargs,
    )


def portable_jsonb() -> JSONB:
    return JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class Dataset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "dataset"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    messages: Mapped[list[Message]] = relationship(back_populates="dataset")


class Server(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "server"
    __table_args__ = (
        UniqueConstraint("dataset_id", "server_ref", name="uq_server_dataset_server_ref"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    server_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Alliance(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "alliance"
    __table_args__ = (
        UniqueConstraint("dataset_id", "alliance_ref", name="uq_alliance_dataset_alliance_ref"),
        Index("ix_alliance_server_id", "server_id"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("server.id", ondelete="CASCADE"), nullable=False
    )
    server_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    alliance_ref: Mapped[str] = mapped_column(String(96), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Player(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "player"
    __table_args__ = (
        UniqueConstraint("dataset_id", "player_ref", name="uq_player_dataset_player_ref"),
        Index("ix_player_server_id", "server_id"),
        Index("ix_player_alliance_id", "alliance_id"),
        CheckConstraint(
            "risk_propensity >= 0 AND risk_propensity <= 1",
            name="risk_propensity_range",
        ),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    player_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("server.id", ondelete="CASCADE"), nullable=False
    )
    server_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    alliance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alliance.id", ondelete="SET NULL"), nullable=True
    )
    alliance_ref: Mapped[str | None] = mapped_column(String(96), nullable=True)
    behavior_profile: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    risk_propensity: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    activity_factor: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    chattiness: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    account_created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PlayerBlacklistEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "player_blacklist_entry"
    __table_args__ = (
        UniqueConstraint("player_ref", name="uq_player_blacklist_entry_player_ref"),
        Index("ix_player_blacklist_entry_blocked_until", "blocked_until"),
    )

    player_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class Message(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_sender_occurred", "sender_ref", "occurred_at"),
        Index("ix_message_player_occurred", "player_id", "occurred_at"),
        Index("ix_message_server_occurred", "server_id", "occurred_at"),
        Index("ix_message_alliance_occurred", "alliance_id", "occurred_at"),
        Index("ix_message_status_ingested", "status", "ingested_at"),
        CheckConstraint("length(content) > 0", name="content_not_empty"),
    )

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="SET NULL"), nullable=True
    )
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player.id", ondelete="SET NULL"), nullable=True
    )
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("server.id", ondelete="SET NULL"), nullable=True
    )
    alliance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alliance.id", ondelete="SET NULL"), nullable=True
    )
    external_message_id: Mapped[str] = mapped_column(String(191), nullable=False, unique=True)
    sender_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    server_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    status: Mapped[str] = mapped_column(portable_enum(MessageStatus), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    display_status: Mapped[str] = mapped_column(
        portable_enum(MessageDisplayStatus, length=16),
        nullable=False,
        default=MessageDisplayStatus.VISIBLE,
        server_default=MessageDisplayStatus.VISIBLE.value,
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dataset: Mapped[Dataset | None] = relationship(back_populates="messages")
    processing_events: Mapped[list[ProcessingEvent]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    risk_findings: Mapped[list[RiskFinding]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    policy_decisions: Mapped[list[PolicyDecision]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    moderation_case: Mapped[ModerationCase | None] = relationship(
        back_populates="message", cascade="all, delete-orphan", uselist=False
    )


class MessageLabel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "message_label"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_message_label_message_id"),
        Index("ix_message_label_dataset_split_label", "dataset_id", "split", "label"),
        Index("ix_message_label_dataset_category", "dataset_id", "risk_category"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(portable_enum(GroundTruthLabel), nullable=False)
    risk_category: Mapped[str | None] = mapped_column(portable_enum(RiskCategory), nullable=True)
    split: Mapped[str] = mapped_column(portable_enum(DatasetSplit), nullable=False)
    annotator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    annotator_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    labeled_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProcessingEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "processing_event"
    __table_args__ = (
        UniqueConstraint("message_id", "sequence", name="uq_processing_event_message_sequence"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(portable_enum(ProcessingStage), nullable=False)
    status: Mapped[str] = mapped_column(portable_enum(ProcessingStatus), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    message: Mapped[Message] = relationship(back_populates="processing_events")


class DetectionRule(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "detection_rule"
    __table_args__ = (
        UniqueConstraint("rule_key", "version", name="uq_detection_rule_key_version"),
        Index("ix_detection_rule_dataset_status", "dataset_id", "status"),
    )

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=True
    )
    rule_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_type: Mapped[str] = mapped_column(portable_enum(RuleType, length=32), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(portable_enum(RuleStatus), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    risk_findings: Mapped[list[RiskFinding]] = relationship(back_populates="rule")


class RiskFinding(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_finding"
    __table_args__ = (
        Index("ix_risk_finding_message_category", "message_id", "category"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_rule.id", ondelete="SET NULL"), nullable=True
    )
    detector: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(portable_enum(RiskCategory), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    message: Mapped[Message] = relationship(back_populates="risk_findings")
    rule: Mapped[DetectionRule | None] = relationship(back_populates="risk_findings")


class RiskEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_event"
    __table_args__ = (
        Index("ix_risk_event_message_occurred", "message_id", "occurred_at"),
        Index("ix_risk_event_dataset_category_occurred", "dataset_id", "category", "occurred_at"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_score_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detection_rule.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(portable_enum(RiskCategory), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    severity: Mapped[str] = mapped_column(portable_enum(RiskSeverity), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Policy(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "policy"
    __table_args__ = (
        UniqueConstraint("policy_key", "version", name="uq_policy_key_version"),
        Index("ix_policy_dataset_status", "dataset_id", "status"),
        Index("ix_policy_enabled_priority", "enabled", "priority"),
    )

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=True
    )
    policy_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(portable_enum(RuleStatus), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_type: Mapped[str | None] = mapped_column(
        portable_enum(PolicyType, length=32), nullable=True
    )
    target_scope: Mapped[dict[str, Any] | None] = mapped_column(portable_jsonb(), nullable=True)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(portable_jsonb(), nullable=True)
    action: Mapped[str | None] = mapped_column(
        portable_enum(DecisionAction, length=32), nullable=True
    )
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emergency: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(191), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(191), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    decisions: Mapped[list[PolicyDecision]] = relationship(back_populates="policy")
    versions: Mapped[list[PolicyVersion]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )


class PolicyVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "policy_version"
    __table_args__ = (
        UniqueConstraint("policy_id", "version", name="uq_policy_version_policy_version"),
        Index("ix_policy_version_policy_created", "policy_id", "created_at"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policy.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    policy_type: Mapped[str] = mapped_column(portable_enum(PolicyType, length=32), nullable=False)
    target_scope: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    action: Mapped[str] = mapped_column(portable_enum(DecisionAction, length=32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(191), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)

    policy: Mapped[Policy] = relationship(back_populates="versions")


class PolicyEvaluation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "policy_evaluation"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "policy_snapshot_hash", name="uq_policy_evaluation_message_snapshot"
        ),
        Index("ix_policy_evaluation_message_evaluated", "message_id", "evaluated_at"),
        Index("ix_policy_evaluation_selected", "selected_policy_id", "evaluated_at"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_score_range"),
    )

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    risk_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_result.id", ondelete="SET NULL"), nullable=True
    )
    policy_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    risk_level: Mapped[str] = mapped_column(portable_enum(RiskSeverity), nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    matched_policies: Mapped[list[dict[str, Any]]] = mapped_column(
        portable_jsonb(), nullable=False, default=list
    )
    unmatched_policies: Mapped[list[dict[str, Any]]] = mapped_column(
        portable_jsonb(), nullable=False, default=list
    )
    matched_conditions: Mapped[list[dict[str, Any]]] = mapped_column(
        portable_jsonb(), nullable=False, default=list
    )
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(
        portable_jsonb(), nullable=False, default=list
    )
    selected_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy.id", ondelete="SET NULL"), nullable=True
    )
    selected_policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_action: Mapped[str] = mapped_column(
        portable_enum(DecisionAction, length=32), nullable=False
    )
    evaluation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PolicyRule(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "policy_rule"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "rule_key", "version", name="uq_policy_rule_policy_key_version"
        ),
        Index("ix_policy_rule_dataset_status", "dataset_id", "status"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="threshold_range"),
    )

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policy.id", ondelete="CASCADE"), nullable=False
    )
    detection_rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detection_rule.id", ondelete="CASCADE"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    category: Mapped[str] = mapped_column(portable_enum(RiskCategory), nullable=False)
    rule_type: Mapped[str] = mapped_column(portable_enum(RuleType, length=32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    action: Mapped[str] = mapped_column(portable_enum(DecisionAction), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    status: Mapped[str] = mapped_column(portable_enum(RuleStatus), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PolicyDecision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "policy_decision"
    __table_args__ = (
        Index("ix_policy_decision_message_decided", "message_id", "decided_at"),
        Index("ix_policy_decision_status_decided", "decision_status", "decided_at"),
        UniqueConstraint("decision_key", name="uq_policy_decision_decision_key"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_score_range"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy.id"), nullable=False)
    action: Mapped[str] = mapped_column(portable_enum(DecisionAction), nullable=False)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    risk_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_result.id", ondelete="SET NULL"), nullable=True
    )
    policy_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_evaluation.id", ondelete="SET NULL"), nullable=True
    )
    decision_key: Mapped[str | None] = mapped_column(String(191), nullable=True)
    decision_status: Mapped[str | None] = mapped_column(
        portable_enum(GovernanceDecisionStatus, length=32), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    requires_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(191), nullable=True)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(portable_jsonb(), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    message: Mapped[Message] = relationship(back_populates="policy_decisions")
    policy: Mapped[Policy] = relationship(back_populates="decisions")
    enforcement_actions: Mapped[list[EnforcementAction]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )


class ModerationCase(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "moderation_case"
    __table_args__ = (
        Index("ix_moderation_case_status_priority", "status", "priority"),
        Index("ix_moderation_case_status_due", "status", "due_at"),
        Index("ix_moderation_case_assignee", "assignee_ref", "status"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(portable_enum(CaseStatus), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    assignee_ref: Mapped[str | None] = mapped_column(String(191), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_decision.id", ondelete="SET NULL"), nullable=True
    )
    risk_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_result.id", ondelete="SET NULL"), nullable=True
    )
    required_second_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    final_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_level: Mapped[str | None] = mapped_column(portable_enum(RiskSeverity), nullable=True)
    final_action: Mapped[str | None] = mapped_column(
        portable_enum(DecisionAction, length=32), nullable=True
    )
    risk_snapshot: Mapped[dict[str, Any] | None] = mapped_column(portable_jsonb(), nullable=True)
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reopened_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    message: Mapped[Message] = relationship(back_populates="moderation_case")
    events: Mapped[list[CaseEvent]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[ModerationReview]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    enforcement_actions: Mapped[list[EnforcementAction]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class ModerationReview(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "moderation_review"
    __table_args__ = (
        Index("ix_moderation_review_case_created", "case_id", "created_at"),
        Index("ix_moderation_review_reviewer_created", "reviewer_ref", "created_at"),
        CheckConstraint(
            "system_confidence IS NULL OR (system_confidence >= 0 AND system_confidence <= 1)",
            name="system_confidence_range",
        ),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moderation_case.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_decision.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(portable_enum(ModerationAction, length=32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    final_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_level: Mapped[str | None] = mapped_column(portable_enum(RiskSeverity), nullable=True)
    final_action: Mapped[str | None] = mapped_column(
        portable_enum(DecisionAction, length=32), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_status: Mapped[str | None] = mapped_column(portable_enum(CaseStatus), nullable=True)
    to_status: Mapped[str | None] = mapped_column(portable_enum(CaseStatus), nullable=True)
    system_action: Mapped[str | None] = mapped_column(
        portable_enum(DecisionAction, length=32), nullable=True
    )
    system_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_level: Mapped[str | None] = mapped_column(portable_enum(RiskSeverity), nullable=True)
    system_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    case: Mapped[ModerationCase] = relationship(back_populates="reviews")


class ModerationRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "moderation_record"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_moderation_record_idempotency"),
        Index(
            "ix_moderation_record_dataset_action_occurred", "dataset_id", "action", "occurred_at"
        ),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_score_range"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moderation_case.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    action: Mapped[str] = mapped_column(portable_enum(DecisionAction), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(portable_jsonb(), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CaseEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "case_event"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moderation_case.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(191), nullable=True)
    from_status: Mapped[str | None] = mapped_column(portable_enum(CaseStatus), nullable=True)
    to_status: Mapped[str | None] = mapped_column(portable_enum(CaseStatus), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)

    case: Mapped[ModerationCase] = relationship(back_populates="events")


class EnforcementAction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "enforcement_action"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_enforcement_action_idempotency"),
        Index("ix_enforcement_action_target_executed", "target_ref", "executed_at"),
        Index("ix_enforcement_action_status_expires", "status", "expires_at"),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policy_decision.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moderation_case.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(portable_enum(EnforcementStatus), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    target_type: Mapped[str | None] = mapped_column(
        portable_enum(EnforcementTargetType, length=32), nullable=True
    )
    server_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    decision: Mapped[PolicyDecision] = relationship(back_populates="enforcement_actions")
    case: Mapped[ModerationCase | None] = relationship(back_populates="enforcement_actions")


class PlayerEnforcementState(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "player_enforcement_state"
    __table_args__ = (
        UniqueConstraint("player_ref", "scope_ref", name="uq_player_enforcement_state_scope"),
        Index("ix_player_enforcement_state_mute", "mute_until"),
        Index("ix_player_enforcement_state_ban", "ban_until"),
    )

    player_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    scope_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    server_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mute_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ban_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    permanent_ban: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    warn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_enforcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("enforcement_action.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class GovernanceFeedback(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "governance_feedback"
    __table_args__ = (
        Index("ix_governance_feedback_type_created", "feedback_type", "created_at"),
        Index("ix_governance_feedback_message", "message_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_decision.id", ondelete="SET NULL"), nullable=True
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moderation_review.id", ondelete="SET NULL"), nullable=True
    )
    feedback_type: Mapped[str] = mapped_column(
        portable_enum(FeedbackType, length=32), nullable=False
    )
    difference_reason: Mapped[str] = mapped_column(Text, nullable=False)
    original_prediction: Mapped[dict[str, Any]] = mapped_column(
        portable_jsonb(), nullable=False, default=dict
    )
    original_risk: Mapped[dict[str, Any]] = mapped_column(
        portable_jsonb(), nullable=False, default=dict
    )
    final_risk: Mapped[dict[str, Any]] = mapped_column(
        portable_jsonb(), nullable=False, default=dict
    )
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(191), nullable=True)
    reviewer_ref: Mapped[str] = mapped_column(String(191), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OutboxEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "outbox_event"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_event_dedupe_key"),
        Index("ix_outbox_event_status_available", "status", "available_at"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )

    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(191), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    topic: Mapped[str] = mapped_column(String(191), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        portable_enum(OutboxStatus, length=16),
        nullable=False,
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RiskResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_result"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_risk_result_message_id"),
        Index("ix_risk_result_dataset_detected", "dataset_id", "detected_at"),
        Index("ix_risk_result_level_detected", "risk_level", "detected_at"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_score_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    ml_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("ml_model.id", ondelete="SET NULL"), nullable=True
    )
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    risk_level: Mapped[str] = mapped_column(portable_enum(RiskSeverity), nullable=False)
    suggested_action: Mapped[str] = mapped_column(portable_enum(DecisionAction), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    categories: Mapped[list[dict[str, Any]]] = mapped_column(
        portable_jsonb(), nullable=False, default=list
    )
    detection_methods: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False, default=dict)
    explanation: Mapped[dict[str, Any]] = mapped_column(
        portable_jsonb(), nullable=False, default=dict
    )
    detector_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    timings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MLModel(Base):
    __tablename__ = "ml_model"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ml_model_name_version"),
        Index("ix_ml_model_status_trained", "status", "trained_at"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(191), nullable=False)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="SET NULL"), nullable=True
    )
    training_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    feature_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False, default=dict)
    per_label_metrics: Mapped[dict[str, Any]] = mapped_column(
        portable_jsonb(), nullable=False, default=dict
    )
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    trained_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EvaluationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evaluation_run"
    __table_args__ = (Index("ix_evaluation_run_model_created", "model_id", "created_at"),)

    model_id: Mapped[str] = mapped_column(
        ForeignKey("ml_model.id", ondelete="CASCADE"), nullable=False
    )
    dataset_name: Mapped[str] = mapped_column(String(191), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    per_label: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False)
    case_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    leakage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EvaluationCase(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evaluation_case"
    __table_args__ = (Index("ix_evaluation_case_run_type", "run_id", "error_type"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_run.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message.id", ondelete="SET NULL"), nullable=True
    )
    error_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predicted_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    truth_label: Mapped[str] = mapped_column(String(16), nullable=False)
    truth_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(portable_jsonb(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class InboxEvent(Base):
    __tablename__ = "inbox_event"
    __table_args__ = (
        UniqueConstraint(
            "source_topic", "source_partition", "source_offset", name="uq_inbox_event_source"
        ),
        Index("ix_inbox_event_status_next_retry", "status", "next_retry_at"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "status IN ('received', 'processed', 'retry', 'dlq')",
            name="status_valid",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_topic: Mapped[str] = mapped_column(String(191), nullable=False)
    source_partition: Mapped[int] = mapped_column(Integer, nullable=False)
    source_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_entity_created", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_event_action_created", "action", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(191), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(portable_jsonb(), nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(portable_jsonb(), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
