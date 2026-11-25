from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from claro.application.events import EventEnvelope
from claro.data_access.repositories.risk_repository import StoredRiskResult
from claro.domain.enums import DecisionAction, RiskSeverity

RISK_ASSESSED_EVENT = "game.risk.assessed.v1"

RiskLevel = Literal["normal", "low", "medium", "high", "critical"]
RiskAction = Literal["allow", "warn", "review", "block", "restrict"]


class CategoryScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category: str = Field(min_length=1, max_length=64)
    db_category: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    score: float = Field(ge=0, le=1)
    level: RiskLevel


class RiskAssessedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    synthetic: bool
    message_id: UUID
    dataset_id: UUID | None
    risk_result_id: UUID
    risk_score: float = Field(ge=0, le=1)
    risk_level: RiskLevel
    suggested_action: RiskAction
    confidence: float = Field(ge=0, le=1)
    categories: list[CategoryScore]
    detection_methods: list[str]
    model_id: str | None
    detected_at: datetime

    @field_validator("detected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("detected_at must be timezone-aware")
        return value

    @classmethod
    def from_json_mapping(cls, payload: Mapping[str, Any]) -> RiskAssessedPayload:
        """Parse a JSON-decoded event payload into a validated model.

        Events travelling through Kafka carry UUIDs and timestamps as JSON
        strings. ``model_validate_json`` parses them before strict validation,
        matching the convention used by persisted message events.
        """
        try:
            return cls.model_validate_json(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid risk assessment payload: {error}") from error

    @classmethod
    def from_stored(cls, stored: StoredRiskResult, synthetic: bool) -> RiskAssessedPayload:
        categories = [
            CategoryScore(
                category=str(item["category"]),
                db_category=str(item["db_category"]),
                name=str(item["name"]),
                score=float(item["score"]),
                level=_level(str(item["level"])),
            )
            for item in stored.categories
            if item.get("db_category")
        ]
        return cls(
            synthetic=synthetic,
            message_id=stored.message_id,
            dataset_id=None,
            risk_result_id=stored.risk_result_id,
            risk_score=stored.risk_score,
            risk_level=_level(stored.risk_level),
            suggested_action=_action(stored.suggested_action),
            confidence=stored.confidence,
            categories=categories,
            detection_methods=list(stored.detection_methods),
            model_id=stored.model_id,
            detected_at=stored.detected_at,
        )

    def with_dataset(self, dataset_id: UUID | None) -> RiskAssessedPayload:
        if dataset_id == self.dataset_id:
            return self
        return self.model_copy(update={"dataset_id": dataset_id})

    def to_event(self, trace_id: str | None = None) -> EventEnvelope:
        return EventEnvelope(
            event_id=self.risk_result_id,
            event_type=RISK_ASSESSED_EVENT,
            payload=self.model_dump(mode="json"),
            occurred_at=self.detected_at,
            trace_id=trace_id,
        )


def _level(value: str) -> RiskLevel:
    if value not in {item.value for item in RiskSeverity}:
        raise ValueError(f"unknown risk level: {value}")
    return value  # type: ignore[return-value]


def _action(value: str) -> RiskAction:
    if value not in {item.value for item in DecisionAction}:
        raise ValueError(f"unknown decision action: {value}")
    return value  # type: ignore[return-value]
