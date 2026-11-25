from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class RiskSummary:
    day: date
    server_ref: str
    category: str
    message_count: int
    high_risk_count: int


@dataclass(frozen=True)
class PolicyEffectiveness:
    policy_key: str
    policy_version: int
    decision_count: int
    review_count: int
    block_count: int


class OfflineAnalyticsPort(Protocol):
    def risk_summary(self, start: date, end: date) -> list[RiskSummary]: ...

    def policy_effectiveness(self, start: date, end: date) -> list[PolicyEffectiveness]: ...
