from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from claro.analytics.data_access import AnalyticsRepository
from claro.analytics.services import AnalyticsService
from claro.analytics.strategy import StrategyReplayService
from claro.application.demo_service import DemoService
from claro.application.enforcement_service import EnforcementService
from claro.application.events import EventEnvelope
from claro.application.explorer_service import ExplorerService
from claro.application.feedback_audit_service import FeedbackAuditService
from claro.application.governance_cache import GovernanceCacheService
from claro.application.governance_decision_service import GovernanceDecisionService
from claro.application.governance_pipeline_service import GovernancePipelineService
from claro.application.health import HealthRegistration, HealthService
from claro.application.moderation_service import ModerationService
from claro.application.policy_evaluation_service import PolicyEvaluationService
from claro.application.policy_service import PolicyService
from claro.application.ports import CachePort, EventBusPort
from claro.application.processing_service import ClaroProcessingService
from claro.application.risk_service import RiskService
from claro.application.safety_cache import SafetyCacheService
from claro.config.settings import ClaroSettings, load_settings
from claro.data_access.database import create_database_engine, create_session_factory
from claro.data_access.repositories.explorer_repository import ExplorerRepository
from claro.data_access.repositories.governance_repository import (
    GovernanceRepository,
    GovernanceTopics,
)
from claro.data_access.repositories.policy_repository import PolicyRepository
from claro.data_access.repositories.risk_repository import RiskRepository
from claro.data_access.repositories.safety_repository import SafetyRepository
from claro.governance.decision import DecisionThresholds
from claro.infrastructure.health import DatabaseHealthCheck
from claro.infrastructure.kafka import KafkaEventBus, KafkaProducer
from claro.infrastructure.logging import configure_logging
from claro.infrastructure.memory import InMemoryEventBus
from claro.infrastructure.redis import RedisCacheAdapter


@dataclass
class AppContainer:
    settings: ClaroSettings
    engine: Engine
    session_factory: sessionmaker
    event_bus: EventBusPort
    cache: CachePort | None
    safety_cache: SafetyCacheService | None
    health_service: HealthService
    risk_repository: RiskRepository | None = None
    risk_service: RiskService | None = None
    governance_repository: GovernanceRepository | None = None
    policy_repository: PolicyRepository | None = None
    policy_service: PolicyService | None = None
    governance_cache: GovernanceCacheService | None = None
    policy_evaluation_service: PolicyEvaluationService | None = None
    governance_decision_service: GovernanceDecisionService | None = None
    moderation_service: ModerationService | None = None
    enforcement_service: EnforcementService | None = None
    feedback_audit_service: FeedbackAuditService | None = None
    analytics_repository: AnalyticsRepository | None = None
    analytics_service: AnalyticsService | None = None
    strategy_replay_service: StrategyReplayService | None = None
    explorer_repository: ExplorerRepository | None = None
    explorer_service: ExplorerService | None = None
    governance_pipeline_service: GovernancePipelineService | None = None
    processing_service: ClaroProcessingService | None = None
    demo_service: DemoService | None = None
    producer: KafkaProducer | None = None

    def verify_connections(self) -> None:
        results = self.health_service.check_all()
        unhealthy = [result for result in results if result.status == "unhealthy"]
        if unhealthy:
            details = "; ".join(f"{result.name}: {result.detail}" for result in unhealthy)
            raise RuntimeError(f"required services are unavailable: {details}")

    def publish_test_event(self) -> EventEnvelope:
        event = EventEnvelope(
            event_type="claro.health.check",
            payload={"synthetic": True, "purpose": "connectivity-check"},
        )
        self.event_bus.publish(event)
        return event

    def close(self) -> None:
        errors: list[Exception] = []
        try:
            self.event_bus.close()
        except Exception as error:
            errors.append(error)
        if self.producer is not None:
            try:
                self.producer.close()
            except Exception as error:
                errors.append(error)
        if self.cache is not None:
            try:
                self.cache.close()
            except Exception as error:
                errors.append(error)
        try:
            self.engine.dispose()
        except Exception as error:
            errors.append(error)
        if errors:
            raise ExceptionGroup("failed to close application resources", errors)


def create_app_container(settings: ClaroSettings | None = None) -> AppContainer:
    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings)
    engine = create_database_engine(resolved_settings)
    session_factory = create_session_factory(engine)
    registrations = [
        HealthRegistration(
            name="postgresql" if resolved_settings.app.mode == "full" else "sqlite",
            check=DatabaseHealthCheck(engine),
        )
    ]

    if resolved_settings.app.mode == "development":
        event_bus: EventBusPort = InMemoryEventBus()
        cache = None
        safety_cache = None
        registrations.extend(
            [
                HealthRegistration(name="redis", check=None),
                HealthRegistration(name="kafka", check=None),
            ]
        )
    else:
        if not resolved_settings.redis.url or not resolved_settings.kafka.bootstrap_servers:
            raise ValueError("full mode service URLs must be configured")
        redis_adapter = RedisCacheAdapter(
            resolved_settings.redis.url, resolved_settings.redis.socket_timeout
        )
        kafka_adapter = KafkaEventBus(
            resolved_settings.kafka.bootstrap_servers,
            resolved_settings.kafka.topic,
            resolved_settings.kafka.client_id,
            resolved_settings.kafka.security_protocol,
        )
        event_bus = cast(EventBusPort, kafka_adapter)
        cache = cast(CachePort, redis_adapter)
        safety_cache = SafetyCacheService(redis_adapter, SafetyRepository(session_factory))
        registrations.extend(
            [
                HealthRegistration(name="redis", check=redis_adapter),
                HealthRegistration(name="kafka", check=kafka_adapter),
            ]
        )

    risk_repository = RiskRepository(session_factory)
    governance_repository = GovernanceRepository(
        session_factory,
        topics=GovernanceTopics(
            evaluated=resolved_settings.governance.topics.evaluated,
            decision=resolved_settings.governance.topics.decisions,
            moderation=resolved_settings.governance.topics.moderation,
            enforcement=resolved_settings.governance.topics.enforcement,
            feedback=resolved_settings.governance.topics.feedback,
        ),
    )
    policy_repository = PolicyRepository(session_factory)
    policy_service = PolicyService(
        policy_repository,
        cache=cache,
        cache_ttl_seconds=resolved_settings.governance.policy_cache_ttl_seconds,
    )
    governance_cache = (
        GovernanceCacheService(
            cache,
            governance_repository,
            rate_window_seconds=resolved_settings.governance.rate_limit_window_seconds,
        )
        if cache is not None
        else None
    )
    feedback_audit_service = FeedbackAuditService(governance_repository)
    analytics_repository = AnalyticsRepository(engine)
    analytics_service = AnalyticsService(analytics_repository)
    strategy_replay_service = StrategyReplayService(
        analytics_repository, policy_repository, session_factory
    )
    explorer_repository = ExplorerRepository(engine)
    risk_service = RiskService(resolved_settings, risk_repository, cache=cache)
    enforcement_service = EnforcementService(governance_repository, cache=governance_cache)
    policy_evaluation_service = PolicyEvaluationService(
        governance_repository,
        policy_service,
        cache=governance_cache,
        rate_window_seconds=resolved_settings.governance.rate_limit_window_seconds,
    )
    governance_decision_service = GovernanceDecisionService(
        governance_repository,
        thresholds=DecisionThresholds(
            low_confidence=resolved_settings.governance.low_confidence_threshold,
            high_risk_confidence=resolved_settings.governance.high_risk_confidence_threshold,
        ),
        review_sla_hours=resolved_settings.governance.review_sla_hours,
    )
    governance_pipeline_service = GovernancePipelineService(
        governance_repository,
        policy_evaluation_service,
        governance_decision_service,
        enforcement_service=enforcement_service,
        auto_enforce=True,
    )
    # A dedicated multi-topic producer is only created in full mode; development
    # mode keeps the in-memory bus and skips the publish stage explicitly.
    producer: KafkaProducer | None = None
    if resolved_settings.app.mode == "full" and resolved_settings.kafka.bootstrap_servers:
        producer = KafkaProducer(
            resolved_settings.kafka.bootstrap_servers,
            f"{resolved_settings.kafka.client_id}-processing",
            resolved_settings.kafka.security_protocol,
            resolved_settings.kafka.producer_timeout_ms,
        )
    moderation_service = ModerationService(
        governance_repository, feedback_service=feedback_audit_service
    )
    processing_service = ClaroProcessingService(
        session_factory=session_factory,
        risk_service=risk_service,
        governance_pipeline=governance_pipeline_service,
        governance_repository=governance_repository,
        risk_topic=resolved_settings.kafka.risk_topic,
        publisher=producer,
    )
    return AppContainer(
        settings=resolved_settings,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        cache=cache,
        safety_cache=safety_cache,
        risk_repository=risk_repository,
        risk_service=risk_service,
        governance_repository=governance_repository,
        policy_repository=policy_repository,
        policy_service=policy_service,
        governance_cache=governance_cache,
        policy_evaluation_service=policy_evaluation_service,
        governance_decision_service=governance_decision_service,
        moderation_service=moderation_service,
        enforcement_service=enforcement_service,
        feedback_audit_service=feedback_audit_service,
        analytics_repository=analytics_repository,
        analytics_service=analytics_service,
        strategy_replay_service=strategy_replay_service,
        explorer_repository=explorer_repository,
        explorer_service=ExplorerService(
            explorer_repository, governance_repository, analytics_service
        ),
        governance_pipeline_service=governance_pipeline_service,
        processing_service=processing_service,
        demo_service=DemoService(
            session_factory=session_factory,
            engine=engine,
            processing=processing_service,
            governance=governance_repository,
            moderation=moderation_service,
            enforcement=enforcement_service,
            feedback=feedback_audit_service,
            strategy=strategy_replay_service,
        ),
        producer=producer,
        health_service=HealthService(registrations),
    )
