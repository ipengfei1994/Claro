from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog
import yaml
from redis.exceptions import RedisError

from claro.application.ports import CachePort
from claro.domain.enums import RiskSeverity, RuleStatus
from claro.risk_engine.preprocessing import PreprocessedText
from claro.risk_engine.taxonomy import RiskTaxonomy
from claro.risk_engine.types import DetectionFinding, EvidenceSpan

RuleType = Literal["keyword", "regex", "url_pattern", "blacklist", "repetition"]

RULE_TYPES: tuple[RuleType, ...] = (
    "keyword",
    "regex",
    "url_pattern",
    "blacklist",
    "repetition",
)
RULE_CACHE_KEY = "claro:risk:rules:v1"
MAX_EVIDENCE_PER_RULE = 5


class RuleConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    id: str
    name: str
    type: RuleType
    category: str
    severity: str
    weight: float
    priority: int
    status: str
    version: int
    description: str
    terms: tuple[str, ...] = ()
    negative_terms: tuple[str, ...] = ()
    pattern: str | None = None
    allow_hosts: tuple[str, ...] = ()
    entries: tuple[str, ...] = ()
    min_repeats: int = 3
    min_segment_length: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuleContext:
    recent_duplicate_count: int = 0


@dataclass(frozen=True, slots=True)
class RuleLayerResult:
    findings: tuple[DetectionFinding, ...]
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: int
    source: str
    rules: tuple[RuleDefinition, ...]


def load_rules(path: Path, taxonomy: RiskTaxonomy) -> RuleSet:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuleConfigurationError(f"rule file is unreadable: {path}") from error
    except yaml.YAMLError as error:
        raise RuleConfigurationError(f"rule file is not valid YAML: {error}") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise RuleConfigurationError("rule file must contain a 'rules' list")
    version = raw.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise RuleConfigurationError("rule set version must be a positive integer")

    rules = tuple(_parse_rule(item, index, taxonomy) for index, item in enumerate(raw["rules"]))
    ids = [rule.id for rule in rules]
    if len(set(ids)) != len(ids):
        raise RuleConfigurationError("rule ids must be unique")
    return RuleSet(version=version, source=str(path.name), rules=rules)


def _parse_rule(data: Any, index: int, taxonomy: RiskTaxonomy) -> RuleDefinition:
    if not isinstance(data, dict):
        raise RuleConfigurationError(f"rule at index {index} must be a mapping")
    rule_id = _text(data, "id", index)
    rule_type = _text(data, "type", index)
    if rule_type not in RULE_TYPES:
        raise RuleConfigurationError(f"rule {rule_id} has unknown type {rule_type}")
    category = _text(data, "category", index)
    if not taxonomy.has(category):
        raise RuleConfigurationError(f"rule {rule_id} references unknown category {category}")
    severity = _text(data, "severity", index)
    if severity not in {item.value for item in RiskSeverity}:
        raise RuleConfigurationError(f"rule {rule_id} has unknown severity {severity}")
    status = _text(data, "status", index)
    if status not in {item.value for item in RuleStatus}:
        raise RuleConfigurationError(f"rule {rule_id} has unknown status {status}")
    weight = data.get("weight")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not 0 <= weight <= 1:
        raise RuleConfigurationError(f"rule {rule_id} weight must be within [0, 1]")
    priority = data.get("priority", 100)
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise RuleConfigurationError(f"rule {rule_id} priority must be an integer")
    version = data.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise RuleConfigurationError(f"rule {rule_id} version must be a positive integer")

    terms = _string_tuple(data, "terms", required=False)
    negative_terms = _string_tuple(data, "negative_terms", required=False)
    pattern = data.get("pattern")
    allow_hosts = _string_tuple(data, "allow_hosts", required=False)
    entries = _string_tuple(data, "entries", required=False)
    if rule_type == "keyword" and not terms:
        raise RuleConfigurationError(f"keyword rule {rule_id} requires terms")
    if rule_type == "regex":
        if not isinstance(pattern, str) or not pattern:
            raise RuleConfigurationError(f"regex rule {rule_id} requires a pattern")
        try:
            re.compile(pattern)
        except re.error as error:
            raise RuleConfigurationError(f"rule {rule_id} pattern is invalid: {error}") from error
    if rule_type == "blacklist" and not entries:
        raise RuleConfigurationError(f"blacklist rule {rule_id} requires entries")
    min_repeats = data.get("min_repeats", 3)
    min_segment_length = data.get("min_segment_length", 2)
    for name, value, minimum in (
        ("min_repeats", min_repeats, 2),
        ("min_segment_length", min_segment_length, 1),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise RuleConfigurationError(f"rule {rule_id} {name} must be >= {minimum}")

    return RuleDefinition(
        id=rule_id,
        name=_text(data, "name", index),
        type=rule_type,
        category=category,
        severity=severity,
        weight=float(weight),
        priority=priority,
        status=status,
        version=version,
        description=_text(data, "description", index),
        terms=tuple(term.lower() for term in terms),
        negative_terms=tuple(term.lower() for term in negative_terms),
        pattern=pattern,
        allow_hosts=tuple(host.lower() for host in allow_hosts),
        entries=tuple(entry.lower() for entry in entries),
        min_repeats=min_repeats,
        min_segment_length=min_segment_length,
    )


def _text(data: dict[str, Any], key: str, index: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuleConfigurationError(f"rule at index {index} requires a non-empty '{key}'")
    return value.strip()


def _string_tuple(data: dict[str, Any], key: str, *, required: bool = True) -> tuple[str, ...]:
    value = data.get(key)
    if value is None and not required:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RuleConfigurationError(f"rule field '{key}' must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


class RuleEngine:
    def __init__(self, rules: RuleSet, taxonomy: RiskTaxonomy) -> None:
        self._taxonomy = taxonomy
        self._rules = tuple(
            sorted(
                (rule for rule in rules.rules if rule.status == RuleStatus.ACTIVE.value),
                key=lambda rule: (rule.priority, rule.id),
            )
        )
        self._compiled = {
            rule.id: re.compile(rule.pattern)  # type: ignore[arg-type]
            for rule in self._rules
            if rule.type == "regex"
        }
        self.version = rules.version

    @property
    def active_rules(self) -> tuple[RuleDefinition, ...]:
        return self._rules

    def evaluate(
        self, text: PreprocessedText, context: RuleContext | None = None
    ) -> RuleLayerResult:
        findings: list[DetectionFinding] = []
        suppressed = 0
        for rule in self._rules:
            if self._is_suppressed(rule, text):
                suppressed += 1
                continue
            finding = self._match(rule, text, context or RuleContext())
            if finding is not None:
                findings.append(finding)
        findings.sort(key=lambda item: (item.rule_id or "", -item.score))
        stats = {
            "rules_evaluated": len(self._rules),
            "rules_suppressed": suppressed,
            "rules_matched": len(findings),
            "rule_set_version": self.version,
        }
        return RuleLayerResult(findings=tuple(findings), stats=stats)

    def _is_suppressed(self, rule: RuleDefinition, text: PreprocessedText) -> bool:
        if not rule.negative_terms:
            return False
        return any(term in text.compact or term in text.normalized for term in rule.negative_terms)

    def _match(
        self, rule: RuleDefinition, text: PreprocessedText, context: RuleContext
    ) -> DetectionFinding | None:
        if rule.type == "keyword":
            evidence = self._keyword_evidence(rule, text)
        elif rule.type == "regex":
            evidence = self._regex_evidence(rule, text)
        elif rule.type == "url_pattern":
            evidence = self._url_evidence(rule, text)
        elif rule.type == "blacklist":
            evidence = self._blacklist_evidence(rule, text)
        elif rule.type == "repetition":
            evidence = self._repetition_evidence(rule, text, context)
        else:
            evidence = ()
        if not evidence:
            return None
        return self._finding(rule, evidence)

    def _keyword_evidence(
        self, rule: RuleDefinition, text: PreprocessedText
    ) -> tuple[EvidenceSpan, ...]:
        evidence: list[EvidenceSpan] = []
        seen: set[str] = set()
        for term in rule.terms:
            for source, value in (
                ("normalized", text.normalized),
                ("compact", text.compact),
                ("squashed", text.squashed),
            ):
                start = value.find(term)
                while start >= 0 and term not in seen:
                    evidence.append(
                        EvidenceSpan(text=term, start=start, end=start + len(term), source=source)
                    )
                    seen.add(term)
                    break
                if term in seen:
                    break
            if len(evidence) >= MAX_EVIDENCE_PER_RULE:
                break
        return tuple(evidence)

    def _regex_evidence(
        self, rule: RuleDefinition, text: PreprocessedText
    ) -> tuple[EvidenceSpan, ...]:
        pattern = self._compiled[rule.id]
        evidence: list[EvidenceSpan] = []
        seen: set[str] = set()
        for source, value in (("normalized", text.normalized), ("compact", text.compact)):
            for match in pattern.finditer(value):
                matched = match.group(0)
                if matched in seen:
                    continue
                seen.add(matched)
                evidence.append(
                    EvidenceSpan(
                        text=matched,
                        start=match.start(),
                        end=match.end(),
                        source=source,
                    )
                )
                if len(evidence) >= MAX_EVIDENCE_PER_RULE:
                    return tuple(evidence)
        return tuple(evidence)

    def _url_evidence(
        self, rule: RuleDefinition, text: PreprocessedText
    ) -> tuple[EvidenceSpan, ...]:
        evidence = [
            EvidenceSpan(text=url, source="original")
            for url, host in zip(text.features.urls, text.features.url_hosts, strict=False)
            if not _host_allowed(host, rule.allow_hosts)
        ]
        if not evidence and text.features.synthetic_link_token:
            evidence.append(EvidenceSpan(text="[synthetic-link]", source="original"))
        return tuple(evidence[:MAX_EVIDENCE_PER_RULE])

    def _blacklist_evidence(
        self, rule: RuleDefinition, text: PreprocessedText
    ) -> tuple[EvidenceSpan, ...]:
        evidence: list[EvidenceSpan] = []
        for url, host in zip(text.features.urls, text.features.url_hosts, strict=False):
            if any(host == entry or host.endswith(f".{entry}") for entry in rule.entries):
                evidence.append(EvidenceSpan(text=url, source="original"))
        if not evidence:
            for entry in rule.entries:
                if entry in text.compact or entry in text.normalized:
                    evidence.append(EvidenceSpan(text=entry, source="compact"))
        return tuple(evidence[:MAX_EVIDENCE_PER_RULE])

    def _repetition_evidence(
        self, rule: RuleDefinition, text: PreprocessedText, context: RuleContext
    ) -> tuple[EvidenceSpan, ...]:
        evidence = [
            EvidenceSpan(text=segment, source="normalized")
            for segment, count in text.features.repeated_segment_counts.items()
            if count >= rule.min_repeats and len(segment) >= rule.min_segment_length
        ]
        if len(evidence) < MAX_EVIDENCE_PER_RULE and (
            context.recent_duplicate_count >= rule.min_repeats
        ):
            evidence.append(
                EvidenceSpan(
                    text=f"recent_duplicates={context.recent_duplicate_count}",
                    source="history",
                )
            )
        return tuple(evidence[:MAX_EVIDENCE_PER_RULE])

    def _finding(
        self, rule: RuleDefinition, evidence: tuple[EvidenceSpan, ...]
    ) -> DetectionFinding:
        category = self._taxonomy.category(rule.category)
        return DetectionFinding(
            layer="rule",
            detector=f"rule.{rule.type}",
            detector_version=f"{rule.version}",
            category=rule.category,
            db_category=category.db_category or "other",
            score=rule.weight,
            confidence=0.95 if rule.type in {"regex", "blacklist"} else 0.85,
            severity=rule.severity,
            rule_id=rule.id,
            evidence=evidence,
            details={
                "rule_name": rule.name,
                "rule_type": rule.type,
                "pattern": rule.pattern,
                "terms": list(rule.terms),
                "description": rule.description,
                "priority": rule.priority,
            },
        )


def _host_allowed(host: str, allow_hosts: tuple[str, ...]) -> bool:
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allow_hosts)


class RuleProvider:
    def __init__(
        self,
        path: Path,
        taxonomy: RiskTaxonomy,
        cache: CachePort | None = None,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._path = path
        self._taxonomy = taxonomy
        self._cache = cache
        self._cache_ttl = cache_ttl_seconds
        self._logger = structlog.get_logger(__name__)
        self._cached: RuleSet | None = None
        self._cached_hash: str | None = None

    def load(self) -> RuleSet:
        digest = self._file_digest()
        if self._cached is not None and self._cached_hash == digest:
            return self._cached
        cached = self._read_cache(digest)
        if cached is not None:
            self._cached = cached
            self._cached_hash = digest
            return cached
        rules = parse_rule_set(self._path, self._taxonomy)
        self._cached = rules
        self._cached_hash = digest
        self._write_cache(rules, digest)
        return rules

    def reload(self) -> RuleSet:
        self._cached = None
        self._cached_hash = None
        if self._cache is not None:
            try:
                self._cache.delete(RULE_CACHE_KEY)
            except RedisError as error:
                self._logger.warning("rule_cache_invalidation_failed", error=str(error))
        return self.load()

    def engine(self) -> RuleEngine:
        return RuleEngine(self.load(), self._taxonomy)

    def re_engine(self) -> RuleEngine:
        return RuleEngine(self.reload(), self._taxonomy)

    def _file_digest(self) -> str:
        try:
            return hashlib.sha256(self._path.read_bytes()).hexdigest()
        except OSError as error:
            raise RuleConfigurationError(f"rule file is unreadable: {self._path}") from error

    def _read_cache(self, digest: str) -> RuleSet | None:
        if self._cache is None:
            return None
        try:
            raw = self._cache.get(RULE_CACHE_KEY)
        except RedisError as error:
            self._logger.warning("rule_cache_unavailable", error=str(error))
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            if payload.get("digest") != digest:
                return None
            rules = tuple(_rule_from_dict(item) for item in payload["rules"])
            version = int(payload["version"])
            source = str(payload.get("source", self._path.name))
        except (KeyError, TypeError, ValueError) as error:
            self._logger.warning("rule_cache_invalid", error=str(error))
            return None
        return RuleSet(version=version, source=source, rules=rules)

    def _write_cache(self, rules: RuleSet, digest: str) -> None:
        if self._cache is None:
            return
        payload = {
            "digest": digest,
            "version": rules.version,
            "source": rules.source,
            "rules": [rule.to_dict() for rule in rules.rules],
        }
        try:
            self._cache.set(
                RULE_CACHE_KEY,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ttl_seconds=self._cache_ttl,
            )
        except RedisError as error:
            self._logger.warning("rule_cache_write_failed", error=str(error))


def parse_rule_set(path: Path, taxonomy: RiskTaxonomy) -> RuleSet:
    return load_rules(path, taxonomy)


def _rule_from_dict(data: dict[str, Any]) -> RuleDefinition:
    return RuleDefinition(
        id=str(data["id"]),
        name=str(data["name"]),
        type=data["type"],
        category=str(data["category"]),
        severity=str(data["severity"]),
        weight=float(data["weight"]),
        priority=int(data["priority"]),
        status=str(data["status"]),
        version=int(data["version"]),
        description=str(data.get("description", "")),
        terms=tuple(data.get("terms", ())),
        negative_terms=tuple(data.get("negative_terms", ())),
        pattern=data.get("pattern"),
        allow_hosts=tuple(data.get("allow_hosts", ())),
        entries=tuple(data.get("entries", ())),
        min_repeats=int(data.get("min_repeats", 3)),
        min_segment_length=int(data.get("min_segment_length", 2)),
    )
