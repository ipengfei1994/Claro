"""Semantic detection layer.

The semantic layer is intentionally *not* implemented in Phase 03.

Reason: the project does not ship a validated local embedding model, and
sentence-transformers/torch would add a large optional dependency. Wrapping
TF-IDF character similarity here would be lexical matching, which the Phase 03
contract explicitly forbids presenting as semantic detection. The interface is
kept so that a real embedding model can be added with measured gains later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from claro.risk_engine.preprocessing import PreprocessedText
from claro.risk_engine.types import DetectionFinding


@dataclass(frozen=True, slots=True)
class SemanticResult:
    findings: tuple[DetectionFinding, ...]
    model_id: str
    latency_ms: float


class SemanticDetector(Protocol):
    @property
    def reason(self) -> str | None: ...

    def analyze(self, text: PreprocessedText) -> SemanticResult | None: ...


class UnavailableSemanticDetector:
    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason or (
            "semantic model not configured; see docs/RISK_ENGINE.md for the deferral rationale"
        )

    @property
    def reason(self) -> str:
        return self._reason

    def analyze(self, text: PreprocessedText) -> SemanticResult | None:
        return None
