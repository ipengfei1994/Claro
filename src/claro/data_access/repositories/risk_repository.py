from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import session_scope
from claro.data_access.models import (
    Dataset,
    DetectionRule,
    EvaluationCase,
    EvaluationRun,
    Message,
    MessageLabel,
    MLModel,
    RiskFinding,
)
from claro.data_access.models import RiskResult as RiskResultRow
from claro.domain.enums import RuleStatus
from claro.risk_engine.ml.data import TrainingExample
from claro.risk_engine.rules import RuleSet
from claro.risk_engine.types import RiskResult


@dataclass(frozen=True, slots=True)
class MessageSnapshot:
    id: UUID
    dataset_id: UUID | None
    sender_ref: str
    content: str
    content_hash: str
    channel: str
    language: str
    occurred_at: datetime
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class StoredRiskResult:
    message_id: UUID
    risk_result_id: UUID
    risk_score: float
    risk_level: str
    suggested_action: str
    confidence: float
    categories: list[dict[str, Any]]
    detection_methods: list[str]
    model_id: str | None
    detected_at: datetime
    explanation: dict[str, Any]
    timings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_result_id": str(self.risk_result_id),
            "message_id": str(self.message_id),
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level,
            "suggested_action": self.suggested_action,
            "confidence": round(self.confidence, 4),
            "categories": self.categories,
            "detection_methods": self.detection_methods,
            "model_id": self.model_id,
            "detected_at": self.detected_at.isoformat(),
            "explanation": self.explanation,
            "timings_ms": self.timings,
        }


class RiskRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def message(self, message_id: UUID) -> MessageSnapshot | None:
        with session_scope(self._sessions) as session:
            row = session.get(Message, message_id)
            if row is None:
                return None
            return MessageSnapshot(
                id=row.id,
                dataset_id=row.dataset_id,
                sender_ref=row.sender_ref,
                content=row.content,
                content_hash=row.content_hash,
                channel=row.channel,
                language=row.language,
                occurred_at=row.occurred_at,
                is_synthetic=row.is_synthetic,
            )

    def dataset_id(self, name: str) -> UUID | None:
        with session_scope(self._sessions) as session:
            return session.scalar(select(Dataset.id).where(Dataset.name == name))

    def dataset_names(self) -> list[str]:
        with session_scope(self._sessions) as session:
            return [
                str(value) for value in session.scalars(select(Dataset.name).order_by(Dataset.name))
            ]

    def training_examples(self, dataset_name: str) -> list[TrainingExample]:
        statement = (
            select(
                Message.id,
                Message.sender_ref,
                Message.content,
                Message.content_hash,
                MessageLabel.label,
                MessageLabel.risk_category,
                MessageLabel.split,
            )
            .join(MessageLabel, MessageLabel.message_id == Message.id)
            .join(Dataset, Dataset.id == Message.dataset_id)
            .where(Dataset.name == dataset_name)
            .order_by(Message.occurred_at, Message.id)
        )
        with session_scope(self._sessions) as session:
            rows = session.execute(statement).all()
        return [
            TrainingExample(
                message_id=str(row[0]),
                player_ref=row[1],
                content=row[2],
                content_hash=row[3],
                label=str(row[4]),
                category=str(row[5]) if row[5] else None,
                split=str(row[6]),
            )
            for row in rows
        ]

    def recent_duplicate_count(
        self,
        sender_ref: str,
        content_hash: str,
        since: datetime,
        *,
        exclude_message_id: UUID | None = None,
        until: datetime | None = None,
    ) -> int:
        conditions = [
            Message.sender_ref == sender_ref,
            Message.content_hash == content_hash,
            Message.occurred_at >= since,
        ]
        if until is not None:
            conditions.append(Message.occurred_at <= until)
        if exclude_message_id is not None:
            conditions.append(Message.id != exclude_message_id)
        statement = select(func.count()).select_from(Message).where(*conditions)
        with session_scope(self._sessions) as session:
            return int(session.scalar(statement) or 0)

    def pending_message_ids(self, dataset_name: str, limit: int = 100) -> list[UUID]:
        statement = (
            select(Message.id)
            .join(Dataset, Dataset.id == Message.dataset_id)
            .outerjoin(RiskResultRow, RiskResultRow.message_id == Message.id)
            .where(Dataset.name == dataset_name, RiskResultRow.id.is_(None))
            .order_by(Message.occurred_at)
            .limit(limit)
        )
        with session_scope(self._sessions) as session:
            return list(session.scalars(statement))

    def get_risk_result(self, message_id: UUID) -> StoredRiskResult | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(RiskResultRow).where(RiskResultRow.message_id == message_id)
            )
            if row is None:
                return None
            return _stored_result(row)

    def save_detection(self, message: MessageSnapshot, result: RiskResult) -> bool:
        try:
            with session_scope(self._sessions) as session:
                existing = session.scalar(
                    select(RiskResultRow.id).where(RiskResultRow.message_id == message.id)
                )
                if existing is not None:
                    return False
                rule_ids = _rule_ids(session)
                conflicts = result.explanation.get("question_answers", {}).get("conflicts", [])
                session.add(
                    RiskResultRow(
                        id=result.id,
                        dataset_id=message.dataset_id,
                        message_id=message.id,
                        ml_model_id=result.model_id,
                        risk_score=Decimal(str(result.risk_score)),
                        risk_level=result.risk_level,
                        suggested_action=result.suggested_action,
                        confidence=Decimal(str(result.confidence)),
                        categories=[item.to_dict() for item in result.categories],
                        detection_methods=list(result.detection_methods),
                        evidence={
                            "findings": [finding.to_dict() for finding in result.findings],
                            "conflicts": conflicts,
                        },
                        explanation=result.explanation,
                        detector_versions=_detector_versions(result),
                        timings=result.timings_ms,
                        detected_at=result.detected_at,
                        is_synthetic=message.is_synthetic,
                    )
                )
                for finding in result.findings:
                    session.add(
                        RiskFinding(
                            message_id=message.id,
                            rule_id=rule_ids.get(finding.rule_id or ""),
                            detector=finding.detector,
                            detector_version=finding.detector_version,
                            category=finding.db_category,
                            score=Decimal(str(finding.score)),
                            confidence=Decimal(str(finding.confidence)),
                            evidence={
                                "taxonomy_category": finding.category,
                                "rule_id": finding.rule_id,
                                "severity": finding.severity,
                                "spans": [span.to_dict() for span in finding.evidence],
                                "details": finding.details,
                            },
                        )
                    )
                session.flush()
            return True
        except IntegrityError:
            return False

    def findings(self, message_id: UUID) -> list[dict[str, Any]]:
        phase_03_detectors = (
            RiskFinding.detector.like("rule.%"),
            RiskFinding.detector.like("ml.%"),
            RiskFinding.detector.like("semantic.%"),
            RiskFinding.detector.like("llm.%"),
        )
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(RiskFinding)
                .where(
                    RiskFinding.message_id == message_id,
                    or_(*phase_03_detectors),
                )
                .order_by(RiskFinding.detector)
            ).all()
            return [
                {
                    "detector": row.detector,
                    "detector_version": row.detector_version,
                    "category": row.category,
                    "score": float(row.score),
                    "confidence": float(row.confidence),
                    "evidence": row.evidence,
                }
                for row in rows
            ]

    def sync_rules(self, ruleset: RuleSet) -> dict[str, Any]:
        created, updated, disabled = 0, 0, 0
        current_keys = {rule.id for rule in ruleset.rules}
        with session_scope(self._sessions) as session:
            existing = {
                (row.rule_key, row.version): row
                for row in session.scalars(
                    select(DetectionRule).where(DetectionRule.dataset_id.is_(None))
                )
            }
            for rule in ruleset.rules:
                definition = rule.to_dict()
                definition["keywords"] = list(rule.terms)
                definition["taxonomy_category"] = rule.category
                definition["managed_by"] = ruleset.source
                row = existing.get((rule.id, rule.version))
                if row is None:
                    session.add(
                        DetectionRule(
                            dataset_id=None,
                            rule_key=rule.id,
                            version=rule.version,
                            rule_type=rule.type,
                            definition=definition,
                            status=rule.status,
                            is_synthetic=True,
                        )
                    )
                    created += 1
                else:
                    row.rule_type = rule.type
                    row.definition = definition
                    row.status = rule.status
                    row.is_synthetic = True
                    updated += 1
            for (rule_key, _), row in existing.items():
                managed = isinstance(row.definition, dict) and (
                    row.definition.get("managed_by") is not None
                )
                if (
                    managed
                    and rule_key not in current_keys
                    and row.status == RuleStatus.ACTIVE.value
                ):
                    row.status = RuleStatus.DISABLED.value
                    disabled += 1
        return {
            "rules_in_file": len(ruleset.rules),
            "created": created,
            "updated": updated,
            "disabled": disabled,
            "version": ruleset.version,
        }

    def next_model_version(self, name: str) -> int:
        with session_scope(self._sessions) as session:
            current = session.scalar(select(func.max(MLModel.version)).where(MLModel.name == name))
            return int(current or 0) + 1

    def save_model(self, metadata: dict[str, Any], dataset_name: str, version: int) -> None:
        name = str(metadata["model_name"])
        evaluation = metadata.get("evaluation_metrics", {})
        with session_scope(self._sessions) as session:
            session.execute(
                update(MLModel)
                .where(MLModel.name == name, MLModel.status == "active")
                .values(status="archived")
            )
            dataset_id = session.scalar(select(Dataset.id).where(Dataset.name == dataset_name))
            session.add(
                MLModel(
                    id=str(metadata["model_id"]),
                    name=name,
                    version=version,
                    algorithm=str(metadata["algorithm"]),
                    dataset_name=dataset_name,
                    dataset_id=dataset_id,
                    training_params={
                        "split_sizes": metadata.get("split_sizes", {}),
                        "candidates": metadata.get("candidate_results", []),
                    },
                    feature_config=metadata.get("feature_config", {}),
                    hyperparameters=metadata.get("hyperparameters", {}),
                    metrics=evaluation,
                    per_label_metrics=evaluation.get("test", {})
                    .get("multilabel", {})
                    .get("per_label", {}),
                    thresholds=metadata.get("thresholds", {}),
                    artifact_path=str(metadata["artifact_path"]),
                    status="active",
                    is_synthetic=True,
                )
            )

    def active_model(self) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(MLModel)
                .where(MLModel.status == "active")
                .order_by(MLModel.trained_at.desc())
                .limit(1)
            )
            return _model_dict(row)

    def model(self, model_id: str) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            return _model_dict(session.get(MLModel, model_id))

    def list_models(self, limit: int = 20) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(MLModel).order_by(MLModel.trained_at.desc()).limit(limit)
            ).all()
            return [item for item in (_model_dict(row) for row in rows) if item is not None]

    def save_evaluation(
        self,
        *,
        model_id: str,
        dataset_name: str,
        split: str,
        outcome: Any,
        leakage: dict[str, Any],
    ) -> UUID:
        with session_scope(self._sessions) as session:
            run = EvaluationRun(
                model_id=model_id,
                dataset_name=dataset_name,
                split=split,
                message_count=outcome.message_count,
                metrics=outcome.metrics,
                per_label=outcome.metrics.get("multilabel", {}).get("per_label", {}),
                case_counts=outcome.case_counts,
                leakage=leakage,
                is_synthetic=True,
            )
            session.add(run)
            session.flush()
            for case in outcome.error_cases:
                try:
                    message_id = UUID(case.message_id)
                except (TypeError, ValueError):
                    message_id = None
                session.add(
                    EvaluationCase(
                        run_id=run.id,
                        message_id=message_id,
                        error_type=case.error_type,
                        category=case.category,
                        predicted_score=Decimal(str(case.predicted_score)),
                        truth_label=case.truth_label,
                        truth_category=case.truth_category,
                        detail=case.detail,
                    )
                )
            session.flush()
            return run.id

    def evaluation(self, run_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.get(EvaluationRun, run_id)
            if row is None:
                return None
            return {
                "run_id": str(row.id),
                "model_id": row.model_id,
                "dataset": row.dataset_name,
                "split": row.split,
                "messages": row.message_count,
                "metrics": row.metrics,
                "case_counts": row.case_counts,
                "leakage": row.leakage,
                "created_at": row.created_at.isoformat(),
            }

    def evaluation_cases(
        self, run_id: UUID, error_type: str | None = None, limit: int = 1_000
    ) -> list[dict[str, Any]]:
        statement = select(EvaluationCase).where(EvaluationCase.run_id == run_id)
        if error_type:
            statement = statement.where(EvaluationCase.error_type == error_type)
        statement = statement.order_by(
            EvaluationCase.error_type, EvaluationCase.predicted_score
        ).limit(limit)
        with session_scope(self._sessions) as session:
            rows = session.scalars(statement).all()
            return [
                {
                    "case_id": str(row.id),
                    "message_id": str(row.message_id) if row.message_id else None,
                    "error_type": row.error_type,
                    "category": row.category,
                    "predicted_score": float(row.predicted_score),
                    "truth_label": row.truth_label,
                    "truth_category": row.truth_category,
                    "detail": row.detail,
                }
                for row in rows
            ]

    def stats(self, dataset_name: str | None = None, sample: int = 5_000) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            conditions: list[Any] = []
            if dataset_name:
                dataset_id = session.scalar(select(Dataset.id).where(Dataset.name == dataset_name))
                if dataset_id is None:
                    return {"dataset": dataset_name, "risk_results": 0}
                conditions.append(RiskResultRow.dataset_id == dataset_id)
            total = int(
                session.scalar(select(func.count()).select_from(RiskResultRow).where(*conditions))
                or 0
            )
            levels = {
                str(level): int(count)
                for level, count in session.execute(
                    select(RiskResultRow.risk_level, func.count())
                    .where(*conditions)
                    .group_by(RiskResultRow.risk_level)
                )
            }
            timings = session.scalars(
                select(RiskResultRow.timings)
                .where(*conditions)
                .order_by(RiskResultRow.detected_at.desc())
                .limit(sample)
            ).all()
        values = [
            float(item["total"])
            for item in timings
            if isinstance(item, dict) and isinstance(item.get("total"), (int, float))
        ]
        return {
            "dataset": dataset_name,
            "risk_results": total,
            "levels": dict(sorted(levels.items())),
            "latency_ms": {
                "samples": len(values),
                "average": round(float(np.mean(values)), 3) if values else None,
                "p50": round(float(np.percentile(values, 50)), 3) if values else None,
                "p95": round(float(np.percentile(values, 95)), 3) if values else None,
            },
        }


def _stored_result(row: RiskResultRow) -> StoredRiskResult:
    return StoredRiskResult(
        message_id=row.message_id,
        risk_result_id=row.id,
        risk_score=float(row.risk_score),
        risk_level=str(row.risk_level),
        suggested_action=str(row.suggested_action),
        confidence=float(row.confidence),
        categories=list(row.categories or []),
        detection_methods=list(row.detection_methods or []),
        model_id=row.ml_model_id,
        detected_at=row.detected_at,
        explanation=dict(row.explanation or {}),
        timings=dict(row.timings or {}),
    )


def _detector_versions(result: RiskResult) -> dict[str, Any]:
    versions: dict[str, Any] = {
        finding.detector: finding.detector_version for finding in result.findings
    }
    if result.model_id:
        versions["ml_model"] = result.model_id
    return versions


def _rule_ids(session: Session) -> dict[str, UUID]:
    rows = session.execute(
        select(DetectionRule.rule_key, DetectionRule.id, DetectionRule.version)
        .where(DetectionRule.dataset_id.is_(None))
        .order_by(DetectionRule.rule_key, DetectionRule.version.desc())
    ).all()
    result: dict[str, UUID] = {}
    for rule_key, rule_id, _version in rows:
        result.setdefault(str(rule_key), rule_id)
    return result


def _model_dict(row: MLModel | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "model_id": row.id,
        "name": row.name,
        "version": row.version,
        "algorithm": row.algorithm,
        "dataset": row.dataset_name,
        "artifact_path": row.artifact_path,
        "status": row.status,
        "trained_at": row.trained_at.isoformat(),
        "feature_config": row.feature_config,
        "hyperparameters": row.hyperparameters,
        "thresholds": row.thresholds,
        "metrics": row.metrics,
    }
