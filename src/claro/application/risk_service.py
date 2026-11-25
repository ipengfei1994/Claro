from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog

from claro.application.ports import CachePort
from claro.config.settings import ClaroSettings
from claro.data_access.repositories.risk_repository import (
    RiskRepository,
    StoredRiskResult,
)
from claro.domain.enums import RiskSeverity
from claro.risk_engine.evaluation.runner import evaluate_predictor
from claro.risk_engine.explainability import build_explanation
from claro.risk_engine.fusion import FusionConfig, fuse, load_fusion_config
from claro.risk_engine.llm import LLMAdapter, LLMConfig, LLMError
from claro.risk_engine.ml.data import leakage_report
from claro.risk_engine.ml.predictor import ModelLoadError, ModelPredictor
from claro.risk_engine.ml.trainer import TrainingConfig, TrainingError, train_risk_model
from claro.risk_engine.preprocessing import preprocess
from claro.risk_engine.rules import RuleContext, RuleEngine, RuleProvider
from claro.risk_engine.semantic import UnavailableSemanticDetector
from claro.risk_engine.taxonomy import RiskTaxonomy, load_taxonomy
from claro.risk_engine.types import DetectionFinding, ModelPrediction, RiskResult

logger = structlog.get_logger(__name__)


class RiskServiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DetectionRecord:
    stored: StoredRiskResult
    created: bool


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    message_id: UUID
    dataset_id: UUID | None
    is_synthetic: bool
    language: str
    duplicate_count: int
    now: datetime


class RiskService:
    """Orchestrates preprocessing, layered detection, fusion and persistence."""

    def __init__(
        self,
        settings: ClaroSettings,
        repository: RiskRepository,
        cache: CachePort | None = None,
        predictor: ModelPredictor | None = None,
        llm: LLMAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._taxonomy: RiskTaxonomy | None = None
        self._fusion: FusionConfig | None = None
        self._rules = RuleProvider(
            settings.resolved_rules_file(),
            self.taxonomy(),
            cache=cache,
            cache_ttl_seconds=settings.risk.cache_ttl_seconds,
        )
        self._engine: RuleEngine | None = None
        self._predictor_override = predictor
        self._predictor: ModelPredictor | None = None
        self._predictor_loaded = False
        self._predictor_reason: str | None = None
        self._semantic = UnavailableSemanticDetector()
        self._llm = llm or LLMAdapter(LLMConfig.from_settings(settings.risk.llm))
        self._logger = structlog.get_logger(__name__)

    # Configuration accessors -------------------------------------------------

    def taxonomy(self) -> RiskTaxonomy:
        if self._taxonomy is None:
            self._taxonomy = load_taxonomy(self._settings.resolved_taxonomy_file())
        return self._taxonomy

    def fusion_config(self) -> FusionConfig:
        if self._fusion is None:
            self._fusion = load_fusion_config(self._settings.resolved_thresholds_file())
        return self._fusion

    def rules_engine(self) -> RuleEngine:
        if self._engine is None:
            self._engine = self._rules.engine()
        return self._engine

    def reload_rules(self) -> dict[str, Any]:
        ruleset = self._rules.reload()
        self._engine = RuleEngine(ruleset, self.taxonomy())
        return {
            "rule_set_version": ruleset.version,
            "rules": len(ruleset.rules),
            "active_rules": len(self._engine.active_rules),
            "source": ruleset.source,
        }

    def sync_rules(self) -> dict[str, Any]:
        return self._repository.sync_rules(self._rules.load())

    # Model access ------------------------------------------------------------

    def _predictor_for(self, record: dict[str, Any]) -> ModelPredictor:
        path = Path(str(record["artifact_path"]))
        if not path.is_absolute():
            path = self._settings.resolve_project_path(path)
        return ModelPredictor.from_path(path)

    def predictor(self) -> ModelPredictor | None:
        if self._predictor_override is not None:
            return self._predictor_override
        if self._predictor_loaded:
            return self._predictor
        self._predictor_loaded = True
        record = None
        requested = self._settings.risk.ml.active_model_id
        if requested:
            record = self._repository.model(requested)
            if record is None:
                self._logger.warning("requested_model_missing", model_id=requested)
        if record is None:
            record = self._repository.active_model()
        if record is None:
            self._predictor_reason = "no active model registered; ML layer degraded"
            self._logger.warning("risk_model_unavailable", reason=self._predictor_reason)
            return None
        try:
            self._predictor = self._predictor_for(record)
        except ModelLoadError as error:
            self._predictor_reason = str(error)
            self._logger.warning("risk_model_load_failed", error=str(error))
            return None
        self._predictor_reason = None
        return self._predictor

    def reset_model_cache(self) -> None:
        if self._predictor_override is None:
            self._predictor = None
            self._predictor_loaded = False
            self._predictor_reason = None

    # Detection ---------------------------------------------------------------

    def detect(self, message_id: UUID, *, force: bool = False) -> DetectionRecord:
        if not force:
            existing = self._repository.get_risk_result(message_id)
            if existing is not None:
                return DetectionRecord(stored=existing, created=False)
        message = self._repository.message(message_id)
        if message is None:
            raise RiskServiceError(f"message not found: {message_id}")
        now = datetime.now(UTC)
        duplicate_count = self._repository.recent_duplicate_count(
            message.sender_ref,
            message.content_hash,
            message.occurred_at - timedelta(hours=self._settings.risk.duplicate_window_hours),
            exclude_message_id=message.id,
            until=message.occurred_at,
        )
        context = AnalysisContext(
            message_id=message.id,
            dataset_id=message.dataset_id,
            is_synthetic=message.is_synthetic,
            language=message.language,
            duplicate_count=duplicate_count,
            now=now,
        )
        result = self.analyze_text(message.content, context)
        created = self._repository.save_detection(message, result)
        stored = self._repository.get_risk_result(message_id)
        if stored is None:
            raise RiskServiceError("risk result was neither stored nor found")
        return DetectionRecord(stored=stored, created=created)

    def analyze_text(
        self,
        content: str,
        context: AnalysisContext | None = None,
        language: str = "zh-CN",
    ) -> RiskResult:
        taxonomy = self.taxonomy()
        config = self.fusion_config()
        timings: dict[str, float] = {}
        started = time.perf_counter()

        step = time.perf_counter()
        text = preprocess(content, language=language)
        timings["preprocess"] = _elapsed(step)

        step = time.perf_counter()
        rule_result = self.rules_engine().evaluate(
            text, RuleContext(recent_duplicate_count=context.duplicate_count if context else 0)
        )
        findings = list(rule_result.findings)
        timings["rules"] = _elapsed(step)

        step = time.perf_counter()
        prediction = self.predictor()
        model_prediction: ModelPrediction | None = None
        if prediction is not None:
            try:
                model_prediction = prediction.predict(text)
            except Exception as error:  # model inference must not break the pipeline
                self._logger.warning("risk_model_inference_failed", error=str(error))
                model_prediction = None
        timings["ml"] = _elapsed(step)

        step = time.perf_counter()
        semantic = self._semantic.analyze(text)
        if semantic is not None:
            findings.extend(semantic.findings)
            timings["semantic"] = semantic.latency_ms
        else:
            timings["semantic"] = _elapsed(step)

        step = time.perf_counter()
        llm_reason = self._llm.reason
        llm_findings: list[DetectionFinding] = []
        if self._llm.available:
            try:
                llm_result = self._llm.analyze(text, tuple(findings))
            except LLMError as error:
                llm_reason = f"LLM analysis failed: {error}"
                self._logger.warning("llm_layer_degraded", error=str(error))
            else:
                if llm_result is not None:
                    timings["llm"] = llm_result.latency_ms
                    finding = _llm_finding(llm_result, taxonomy)
                    if finding is not None:
                        llm_findings.append(finding)
                        findings.append(finding)
        timings.setdefault("llm", _elapsed(step))

        if model_prediction is not None:
            findings.extend(_ml_findings(model_prediction, config.ml_min_probability))

        step = time.perf_counter()
        fusion = fuse(
            findings=tuple(findings),
            prediction=model_prediction,
            taxonomy=taxonomy,
            config=config,
        )
        timings["fusion"] = _elapsed(step)

        step = time.perf_counter()
        explanation = build_explanation(
            text=text,
            findings=tuple(findings),
            prediction=model_prediction,
            fusion=fusion,
            semantic_reason=self._semantic.reason,
            llm_reason=llm_reason,
            fusion_config=config.to_dict(),
        )
        explanation["rule_engine"] = rule_result.stats
        timings["explanation"] = _elapsed(step)
        timings["total"] = _elapsed(started)

        methods = sorted(
            {
                finding.layer
                for finding in findings
                if finding.layer in {"rule", "ml", "semantic", "llm"}
            }
        )
        return RiskResult(
            id=uuid4(),
            message_id=context.message_id if context else uuid4(),
            dataset_id=context.dataset_id if context else None,
            risk_score=fusion.risk_score,
            risk_level=fusion.risk_level,
            suggested_action=fusion.suggested_action,
            confidence=fusion.confidence,
            categories=fusion.categories,
            detection_methods=tuple(methods),
            findings=tuple(findings),
            explanation=explanation,
            model_id=model_prediction.model_id if model_prediction is not None else None,
            timings_ms={key: round(value, 3) for key, value in timings.items()},
            detected_at=context.now if context else datetime.now(UTC),
            is_synthetic=context.is_synthetic if context else False,
        )

    # Query -------------------------------------------------------------------

    def result(self, message_id: UUID) -> StoredRiskResult:
        stored = self._repository.get_risk_result(message_id)
        if stored is None:
            raise RiskServiceError(f"risk result not found for message: {message_id}")
        return stored

    def explain(self, message_id: UUID) -> dict[str, Any]:
        stored = self.result(message_id)
        return {
            "risk_result": stored.to_dict(),
            "findings": self._repository.findings(message_id),
        }

    def detect_pending(self, dataset_name: str, limit: int = 100) -> dict[str, Any]:
        message_ids = self._repository.pending_message_ids(
            dataset_name, limit=min(limit, self._settings.risk.max_batch_size)
        )
        results: list[dict[str, Any]] = []
        for message_id in message_ids:
            record = self.detect(message_id)
            results.append(
                {
                    "message_id": str(message_id),
                    "risk_level": record.stored.risk_level,
                    "risk_score": round(record.stored.risk_score, 4),
                    "created": record.created,
                }
            )
        levels: dict[str, int] = {}
        for item in results:
            levels[item["risk_level"]] = levels.get(item["risk_level"], 0) + 1
        return {
            "dataset": dataset_name,
            "requested": limit,
            "detected": len(results),
            "levels": dict(sorted(levels.items())),
            "results": results,
        }

    # Training and evaluation -------------------------------------------------

    def train(self, dataset_name: str, algorithm: str | None = None) -> dict[str, Any]:
        examples = self._repository.training_examples(dataset_name)
        if not examples:
            raise TrainingError(f"dataset has no labeled messages: {dataset_name}")
        chosen_algorithm = algorithm or self._settings.risk.ml.algorithm
        name = f"risk-{chosen_algorithm}"
        version = self._repository.next_model_version(name)
        config = TrainingConfig(
            algorithm=chosen_algorithm,
            c_values=tuple(self._settings.risk.ml.c_values),
            min_df=self._settings.risk.ml.min_df,
            max_features=self._settings.risk.ml.max_features,
            ngram_min=self._settings.risk.ml.ngram_min,
            ngram_max=self._settings.risk.ml.ngram_max,
            dataset_name=dataset_name,
            model_version=version,
        )
        labels = self.taxonomy().db_categories
        outcome = train_risk_model(
            examples,
            labels,
            config,
            self._settings.resolved_models_dir(),
            project_root=self._settings.resolve_project_path(Path(".")),
        )
        self._repository.save_model(outcome.metadata, dataset_name, version)
        self.reset_model_cache()
        return {
            **outcome.to_dict(),
            "model_registered": True,
            "notice": outcome.metadata["notice"],
        }

    def evaluate(
        self,
        dataset_name: str,
        split: str = "test",
        model_id: str | None = None,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        predictor = self._evaluation_predictor(model_id)
        examples = self._repository.training_examples(dataset_name)
        if not examples:
            raise RiskServiceError(f"dataset has no labeled messages: {dataset_name}")
        selected = [item for item in examples if item.split == split]
        if not selected:
            raise RiskServiceError(f"dataset has no '{split}' split: {dataset_name}")
        train = [item for item in examples if item.split == "train"]
        labels = self.taxonomy().db_categories
        outcome = evaluate_predictor(
            predictor, selected, labels, self.rules_engine(), train_examples=train
        )
        leakage = leakage_report(train, selected)
        run_id = None
        if persist:
            run_id = self._repository.save_evaluation(
                model_id=predictor.model_id,
                dataset_name=dataset_name,
                split=split,
                outcome=outcome,
                leakage=leakage,
            )
        return {
            **outcome.to_dict(),
            "run_id": str(run_id) if run_id else None,
            "model_id": predictor.model_id,
            "dataset": dataset_name,
            "split": split,
            "leakage": leakage,
            "notice": (
                "Metrics come from a synthetic template dataset. Repeated templates across "
                "player-based splits inflate scores; content-disjoint metrics expose part of it."
            ),
        }

    def _evaluation_predictor(self, model_id: str | None) -> ModelPredictor:
        if self._predictor_override is not None:
            return self._predictor_override
        if model_id:
            record = self._repository.model(model_id)
            if record is None:
                raise RiskServiceError(f"model not found: {model_id}")
            return self._predictor_for(record)
        predictor = self.predictor()
        if predictor is None:
            raise RiskServiceError(self._predictor_reason or "no active model available")
        return predictor

    # Status ------------------------------------------------------------------

    def status(self, dataset_name: str | None = None) -> dict[str, Any]:
        taxonomy = self.taxonomy()
        ruleset = self._rules.load()
        record = self._repository.active_model()
        predictor = self.predictor()
        return {
            "taxonomy": {
                "version": taxonomy.version,
                "categories": len(taxonomy.categories),
                "risk_categories": len(taxonomy.risk_categories),
                "db_categories": list(taxonomy.db_categories),
            },
            "rules": {
                "version": ruleset.version,
                "source": ruleset.source,
                "rules": len(ruleset.rules),
                "active": len([rule for rule in ruleset.rules if rule.status == "active"]),
            },
            "fusion": self.fusion_config().to_dict(),
            "model": {
                "requested": self._settings.risk.ml.active_model_id,
                "active": record,
                "loaded": predictor.model_id if predictor is not None else None,
                "degraded_reason": self._predictor_reason if predictor is None else None,
            },
            "semantic": {"status": "not_available", "reason": self._semantic.reason},
            "llm": {
                "status": "disabled" if self._llm.reason else "available",
                "reason": self._llm.reason,
            },
            "detection_stats": self._repository.stats(dataset_name),
        }

    def datasets(self) -> list[str]:
        return self._repository.dataset_names()

    def evaluation(self, run_id: UUID) -> dict[str, Any]:
        record = self._repository.evaluation(run_id)
        if record is None:
            raise RiskServiceError(f"evaluation run not found: {run_id}")
        return record

    def evaluation_cases(
        self, run_id: UUID, error_type: str | None = None, limit: int = 1_000
    ) -> list[dict[str, Any]]:
        if self._repository.evaluation(run_id) is None:
            raise RiskServiceError(f"evaluation run not found: {run_id}")
        return self._repository.evaluation_cases(run_id, error_type, limit)


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _ml_findings(prediction: ModelPrediction, minimum_probability: float) -> list[DetectionFinding]:
    findings: list[DetectionFinding] = []
    for db_category, probability in sorted(
        prediction.probabilities.items(), key=lambda item: item[1], reverse=True
    ):
        threshold = max(
            prediction.thresholds.get(db_category, minimum_probability), minimum_probability
        )
        if probability < threshold:
            continue
        findings.append(
            DetectionFinding(
                layer="ml",
                detector=f"ml.{prediction.algorithm}",
                detector_version=str(prediction.model_version),
                category=db_category,
                db_category=db_category,
                score=probability,
                confidence=probability,
                details={
                    "model_id": prediction.model_id,
                    "threshold": round(threshold, 4),
                },
            )
        )
    return findings


def _llm_finding(llm_result: Any, taxonomy: RiskTaxonomy) -> DetectionFinding | None:
    judgement = llm_result.judgement
    if not judgement.risk or not judgement.category:
        return None
    if not taxonomy.has(judgement.category):
        return None
    category = taxonomy.category(judgement.category)
    if category.db_category is None:
        return None
    severity = judgement.severity or category.severity
    if severity not in {item.value for item in RiskSeverity}:
        severity = category.severity
    return DetectionFinding(
        layer="llm",
        detector="llm.chat",
        detector_version=llm_result.model,
        category=judgement.category,
        db_category=category.db_category,
        score=max(0.0, min(1.0, judgement.confidence)),
        confidence=max(0.0, min(1.0, judgement.confidence)),
        severity=severity,
        details={
            "rationale": judgement.rationale,
            "model": llm_result.model,
            "attempts": llm_result.attempts,
            "advisory_only": True,
        },
    )
