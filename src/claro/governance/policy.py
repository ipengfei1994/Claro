from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from claro.domain.enums import DecisionAction, PolicyType, RiskSeverity

MAX_CONDITION_DEPTH = 5
MAX_CONDITION_NODES = 64
MAX_REGEX_LENGTH = 200

_STRING_FIELDS = {
    "content",
    "content_hash",
    "channel",
    "language",
    "sender_ref",
    "server_ref",
    "alliance_id",
    "risk_level",
}
_NUMERIC_FIELDS = {"risk_score", "confidence", "rate_count", "content_length", "category_score"}
_LIST_FIELDS = {"category"}
_ALIASES = {
    "text": "content",
    "player_ref": "sender_ref",
    "server": "server_ref",
    "alliance": "alliance_id",
    "level": "risk_level",
}
_FIELDS = _STRING_FIELDS | _NUMERIC_FIELDS | _LIST_FIELDS
_SCOPE_KEYS = ("players", "alliances", "servers", "channels", "languages")

DEFAULT_ACTIONS: dict[str, str] = {
    RiskSeverity.NORMAL.value: DecisionAction.ALLOW.value,
    RiskSeverity.LOW.value: DecisionAction.ALLOW.value,
    RiskSeverity.MEDIUM.value: DecisionAction.WARN.value,
    RiskSeverity.HIGH.value: DecisionAction.REVIEW.value,
    RiskSeverity.CRITICAL.value: DecisionAction.REVIEW.value,
}

ACTION_RESTRICTIVENESS = {
    DecisionAction.ALLOW.value: 0,
    DecisionAction.WARN.value: 1,
    DecisionAction.FLAG.value: 2,
    DecisionAction.REVIEW.value: 3,
    DecisionAction.MUTE.value: 4,
    DecisionAction.BLOCK.value: 5,
    DecisionAction.TEMP_BAN.value: 6,
    DecisionAction.PERM_BAN.value: 7,
    DecisionAction.RESTRICT.value: 7,
}


class PolicyValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyContext:
    message_id: UUID
    content: str
    content_hash: str
    channel: str
    language: str
    sender_ref: str
    server_ref: str | None
    alliance_id: str | None
    risk_score: float
    risk_level: str
    confidence: float
    categories: tuple[str, ...]
    category_scores: Mapping[str, float]
    rate_count: int = 0
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    policy_id: UUID
    policy_key: str
    name: str
    description: str
    policy_type: str
    target_scope: dict[str, Any]
    conditions: dict[str, Any]
    action: str
    priority: int
    emergency: bool
    enabled: bool
    version: int
    effective_from: datetime
    effective_until: datetime | None
    created_by: str
    is_synthetic: bool = True

    def is_effective(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.effective_from > now:
            return False
        return self.effective_until is None or self.effective_until >= now

    def specificity(self) -> int:
        for index, key in enumerate(("players", "alliances", "servers")):
            values = self.target_scope.get(key) or []
            if values:
                return 4 - index
        return 1


@dataclass(frozen=True, slots=True)
class ConditionEvaluation:
    matched: bool
    leaves: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PolicyMatch:
    policy: PolicySnapshot
    leaves: tuple[dict[str, Any], ...]
    specificity: int


@dataclass(frozen=True, slots=True)
class PolicyEvaluationOutcome:
    action: str
    selected_policy: PolicySnapshot | None
    selected_is_default: bool
    matched: tuple[PolicyMatch, ...]
    unmatched: tuple[PolicySnapshot, ...]
    conflicts: tuple[dict[str, Any], ...]
    snapshot_hash: str
    reason: str
    matched_conditions: tuple[dict[str, Any], ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def policy_snapshot_hash(policy: PolicySnapshot) -> str:
    payload = {
        "policy_key": policy.policy_key,
        "version": policy.version,
        "name": policy.name,
        "description": policy.description,
        "policy_type": policy.policy_type,
        "target_scope": policy.target_scope,
        "conditions": policy.conditions,
        "action": policy.action,
        "priority": policy.priority,
        "emergency": policy.emergency,
        "enabled": policy.enabled,
        "effective_from": policy.effective_from,
        "effective_until": policy.effective_until,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def policies_snapshot_hash(policies: Sequence[PolicySnapshot]) -> str:
    digests = sorted(
        f"{item.policy_key}:{item.version}:{policy_snapshot_hash(item)}" for item in policies
    )
    return hashlib.sha256(canonical_json(digests).encode("utf-8")).hexdigest()


def validate_target_scope(scope: Any) -> dict[str, Any]:
    if not isinstance(scope, dict):
        raise PolicyValidationError("target_scope must be an object")
    unknown = set(scope) - set(_SCOPE_KEYS)
    if unknown:
        raise PolicyValidationError(f"target_scope contains unknown keys: {sorted(unknown)}")
    result: dict[str, Any] = {}
    for key in _SCOPE_KEYS:
        raw = scope.get(key, [])
        if raw is None:
            raw = []
        if not isinstance(raw, list) or not all(
            isinstance(item, str) and item.strip() for item in raw
        ):
            raise PolicyValidationError(f"target_scope.{key} must be a list of non-empty strings")
        result[key] = [item.strip() for item in raw]
    return result


def validate_policy_definition(
    *,
    policy_type: str,
    conditions: Any,
    target_scope: Any,
    action: str,
    priority: int,
) -> dict[str, Any]:
    if policy_type not in {item.value for item in PolicyType}:
        raise PolicyValidationError(f"unknown policy type: {policy_type}")
    if action not in {item.value for item in DecisionAction}:
        raise PolicyValidationError(f"unknown policy action: {action}")
    if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 1_000:
        raise PolicyValidationError("priority must be an integer between 0 and 1000")
    scope = validate_target_scope(target_scope)
    if not isinstance(conditions, dict) or not conditions:
        raise PolicyValidationError("conditions must be a non-empty object")
    validate_conditions(conditions)
    leaves = list(_iter_leaves(conditions))
    _validate_type_specific(policy_type, leaves)
    return {"conditions": conditions, "target_scope": scope}


def validate_conditions(conditions: Any) -> None:
    if not isinstance(conditions, dict):
        raise PolicyValidationError("conditions must be an object")
    count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal count
        if depth > MAX_CONDITION_DEPTH:
            raise PolicyValidationError("conditions exceed maximum nesting depth")
        if not isinstance(node, dict) or not node:
            raise PolicyValidationError("each condition node must be a non-empty object")
        count += 1
        if count > MAX_CONDITION_NODES:
            raise PolicyValidationError("conditions exceed maximum node count")
        if "all" in node or "any" in node or "not" in node:
            if len(node) != 1:
                raise PolicyValidationError("logical nodes must contain exactly one operator")
            key = next(iter(node))
            value = node[key]
            if key == "not":
                walk(value, depth + 1)
                return
            if not isinstance(value, list) or not value:
                raise PolicyValidationError(f"condition '{key}' must be a non-empty list")
            for child in value:
                walk(child, depth + 1)
            return
        _validate_leaf(node)

    walk(conditions, 0)
    if not any(True for _ in _iter_leaves(conditions)):
        raise PolicyValidationError("conditions must contain at least one leaf condition")


def _validate_leaf(leaf: dict[str, Any]) -> None:
    if set(leaf) - {"field", "op", "value"}:
        raise PolicyValidationError(f"leaf condition has unknown keys: {sorted(set(leaf))}")
    field = leaf.get("field")
    op = leaf.get("op")
    if not isinstance(field, str):
        raise PolicyValidationError("condition field must be a string")
    field = _normalize_field(field)
    if not isinstance(op, str) or op not in {
        "eq",
        "ne",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "regex",
        "gte",
        "gt",
        "lte",
        "lt",
        "exists",
    }:
        raise PolicyValidationError(f"unsupported condition operator: {op}")
    value = leaf.get("value")
    if field in _NUMERIC_FIELDS:
        if op not in {"eq", "ne", "gte", "gt", "lte", "lt", "in", "not_in", "exists"}:
            raise PolicyValidationError(f"operator '{op}' is not valid for numeric field '{field}'")
        if op not in {"exists"}:
            values = value if op in {"in", "not_in"} else [value]
            if not isinstance(values, list) or not all(
                isinstance(item, (int, float)) and not isinstance(item, bool) for item in values
            ):
                raise PolicyValidationError(f"field '{field}' requires numeric values")
        return
    if field == "category":
        if op not in {"eq", "ne", "in", "not_in", "exists"}:
            raise PolicyValidationError(f"operator '{op}' is not valid for category field")
        if op not in {"exists"}:
            values = value if op in {"in", "not_in"} else [value]
            if not isinstance(values, list) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise PolicyValidationError("category conditions require string values")
        return
    if op in {"gte", "gt", "lte", "lt"}:
        raise PolicyValidationError(f"operator '{op}' requires a numeric field")
    if field == "content" and op not in {
        "eq",
        "ne",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "regex",
        "exists",
    }:
        raise PolicyValidationError(f"operator '{op}' is not valid for content")
    if field in _STRING_FIELDS and field != "content" and op in {
        "contains",
        "not_contains",
        "regex",
    }:
        raise PolicyValidationError(f"operator '{op}' is only supported for content")
    if op == "regex":
        if not isinstance(value, str) or not value or len(value) > MAX_REGEX_LENGTH:
            raise PolicyValidationError(
                f"regex value must be a non-empty string up to {MAX_REGEX_LENGTH} characters"
            )
        try:
            re.compile(value, re.IGNORECASE)
        except re.error as error:
            raise PolicyValidationError(f"invalid regular expression: {error}") from error
        if "(?" in value or "\\1" in value:
            raise PolicyValidationError("regex may not use lookarounds or backreferences")
        return
    if op in {"contains", "not_contains"}:
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(item, str) and item for item in values):
            raise PolicyValidationError(f"'{op}' requires a non-empty string or string list")
        return
    if op == "exists":
        if value is not None and not isinstance(value, bool):
            raise PolicyValidationError("'exists' accepts an optional boolean value")
        return
    values = value if op in {"in", "not_in"} else [value]
    if op in {"in", "not_in"} and (not isinstance(values, list) or not values):
        raise PolicyValidationError(f"'{op}' requires a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise PolicyValidationError(f"field '{field}' requires non-empty string values")


def _normalize_field(field: str) -> str:
    field = _ALIASES.get(field, field)
    if field not in _FIELDS:
        raise PolicyValidationError(f"unsupported condition field: {field}")
    return field


def _iter_leaves(node: Any) -> Sequence[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    _collect_leaves(node, leaves)
    return leaves


def _collect_leaves(node: Any, leaves: list[dict[str, Any]]) -> None:
    if not isinstance(node, dict):
        return
    if "all" in node:
        for child in node["all"]:
            _collect_leaves(child, leaves)
    elif "any" in node:
        for child in node["any"]:
            _collect_leaves(child, leaves)
    elif "not" in node:
        _collect_leaves(node["not"], leaves)
    else:
        leaves.append(node)


def _validate_type_specific(policy_type: str, leaves: list[dict[str, Any]]) -> None:
    fields = {_normalize_field(str(leaf.get("field"))) for leaf in leaves}
    requirements = {
        PolicyType.KEYWORD: "content",
        PolicyType.REGEX: "content",
        PolicyType.RISK_THRESHOLD: "risk_score",
        PolicyType.CATEGORY: "category",
        PolicyType.PLAYER: "sender_ref",
        PolicyType.SERVER: "server_ref",
        PolicyType.ALLIANCE: "alliance_id",
        PolicyType.RATE_LIMIT: "rate_count",
    }
    required = requirements.get(PolicyType(policy_type))
    if required is not None and required not in fields:
        raise PolicyValidationError(
            f"policy type '{policy_type}' requires a condition on field '{required}'"
        )
    if policy_type == PolicyType.REGEX.value and not any(
        _normalize_field(str(leaf.get("field"))) == "content" and leaf.get("op") == "regex"
        for leaf in leaves
    ):
        raise PolicyValidationError("regex policies require a 'regex' condition on content")
    if policy_type == PolicyType.KEYWORD.value and not any(
        _normalize_field(str(leaf.get("field"))) == "content"
        and leaf.get("op") in {"contains", "in"}
        for leaf in leaves
    ):
        raise PolicyValidationError("keyword policies require a contains/in condition on content")


def evaluate_conditions(
    conditions: Mapping[str, Any], context: PolicyContext
) -> ConditionEvaluation:
    leaves: list[dict[str, Any]] = []

    def walk(node: Mapping[str, Any]) -> bool:
        if "all" in node:
            return all(walk(child) for child in node["all"])
        if "any" in node:
            return any(walk(child) for child in node["any"])
        if "not" in node:
            return not walk(node["not"])
        result, trace = _evaluate_leaf(node, context)
        leaves.append(trace)
        return result

    matched = walk(conditions)
    return ConditionEvaluation(matched=matched, leaves=tuple(leaves))


def _evaluate_leaf(leaf: Mapping[str, Any], context: PolicyContext) -> tuple[bool, dict[str, Any]]:
    field = _normalize_field(str(leaf.get("field")))
    op = str(leaf.get("op"))
    expected = leaf.get("value")
    actual = _context_value(field, context)
    if op == "exists":
        want = True if expected is None else bool(expected)
        matched = (actual is not None) is want
    elif op == "in":
        values = [str(item) for item in expected]
        matched = bool(set(actual) & set(values)) if field == "category" else actual in values
    elif op == "not_in":
        values = [str(item) for item in expected]
        matched = not (bool(set(actual) & set(values)) if field == "category" else actual in values)
    elif op in {"contains", "not_contains"}:
        terms = expected if isinstance(expected, list) else [expected]
        haystack = str(actual or "").casefold()
        hit = any(str(term).casefold() in haystack for term in terms)
        matched = hit if op == "contains" else not hit
    elif op == "regex":
        matched = bool(re.search(str(expected), str(actual or ""), re.IGNORECASE))
    elif op in {"gte", "gt", "lte", "lt", "eq", "ne"}:
        matched = _compare(actual, expected, op)
    else:
        raise PolicyValidationError(f"unsupported operator at evaluation time: {op}")
    trace = {
        "field": field,
        "op": op,
        "expected": expected,
        "actual": actual if not isinstance(actual, set) else sorted(actual),
        "matched": matched,
    }
    return matched, trace


def _compare(actual: Any, expected: Any, op: str) -> bool:
    if actual is None:
        return False
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        left: Any = float(actual)
        right: Any = float(expected)
    else:
        left = str(actual)
        right = str(expected)
    try:
        if op == "gte":
            return left >= right
        if op == "gt":
            return left > right
        if op == "lte":
            return left <= right
        if op == "lt":
            return left < right
        if op == "eq":
            return left == right
        return left != right
    except TypeError:
        return False


def _context_value(field: str, context: PolicyContext) -> Any:
    if field == "content":
        return context.content
    if field == "content_hash":
        return context.content_hash
    if field == "channel":
        return context.channel
    if field == "language":
        return context.language
    if field == "sender_ref":
        return context.sender_ref
    if field == "server_ref":
        return context.server_ref
    if field == "alliance_id":
        return context.alliance_id
    if field == "risk_level":
        return context.risk_level
    if field == "risk_score":
        return context.risk_score
    if field == "confidence":
        return context.confidence
    if field == "rate_count":
        return context.rate_count
    if field == "content_length":
        return len(context.content)
    if field == "category":
        return set(context.categories)
    if field == "category_score":
        return max(context.category_scores.values(), default=0.0)
    raise PolicyValidationError(f"unsupported condition field: {field}")


def _scope_matches(scope: Mapping[str, Any], context: PolicyContext) -> bool:
    checks = {
        "players": context.sender_ref,
        "servers": context.server_ref,
        "alliances": context.alliance_id,
        "channels": context.channel,
        "languages": context.language,
    }
    for key, value in checks.items():
        allowed = scope.get(key) or []
        if allowed and value not in allowed:
            return False
    return True


def _selection_key(match: PolicyMatch) -> tuple[Any, ...]:
    policy = match.policy
    return (
        0 if policy.emergency else 1,
        -policy.priority,
        -match.specificity,
        -ACTION_RESTRICTIVENESS.get(policy.action, 0),
        policy.policy_key,
        str(policy.policy_id),
    )


def evaluate_policies(
    context: PolicyContext,
    policies: Sequence[PolicySnapshot],
    *,
    default_policy: PolicySnapshot | None,
    now: datetime,
    default_actions: Mapping[str, str] | None = None,
) -> PolicyEvaluationOutcome:
    matched: list[PolicyMatch] = []
    unmatched: list[PolicySnapshot] = []
    for policy in policies:
        if not policy.is_effective(now):
            unmatched.append(policy)
            continue
        if not _scope_matches(policy.target_scope, context):
            unmatched.append(policy)
            continue
        evaluation = evaluate_conditions(policy.conditions, context)
        if evaluation.matched:
            matched.append(
                PolicyMatch(
                    policy=policy,
                    leaves=evaluation.leaves,
                    specificity=policy.specificity(),
                )
            )
        else:
            unmatched.append(policy)

    matched.sort(key=_selection_key)
    selected: PolicyMatch | None = None
    whitelist_skipped = False
    for candidate in matched:
        if (
            candidate.policy.policy_type == PolicyType.WHITELIST.value
            and context.risk_level in {RiskSeverity.HIGH.value, RiskSeverity.CRITICAL.value}
        ):
            whitelist_skipped = True
            continue
        selected = candidate
        break

    conflicts = _matched_conflicts(matched)
    snapshot_hash = policies_snapshot_hash(
        tuple(item.policy for item in matched) + tuple(unmatched)
    )
    if selected is None:
        actions = dict(DEFAULT_ACTIONS)
        if default_actions:
            actions.update(default_actions)
        action = actions.get(context.risk_level, DecisionAction.REVIEW.value)
        note = "no enabled policy matched; default risk-level action applied"
        if whitelist_skipped:
            note += "; whitelist exemption not applied to high or critical risk"
        return PolicyEvaluationOutcome(
            action=action,
            selected_policy=default_policy,
            selected_is_default=True,
            matched=tuple(matched),
            unmatched=tuple(unmatched),
            conflicts=tuple(conflicts),
            snapshot_hash=snapshot_hash,
            reason=note,
            matched_conditions=(),
        )
    reason = (
        f"policy '{selected.policy.policy_key}' version {selected.policy.version} selected by "
        "emergency, priority, scope specificity, action restrictiveness and key ordering"
    )
    if whitelist_skipped:
        reason += "; whitelist exemption not applied to high or critical risk"
    matched_conditions: list[dict[str, Any]] = []
    for leaf in selected.leaves:
        matched_conditions.append(
            {"policy_key": selected.policy.policy_key, **leaf, "matched": True}
        )
    return PolicyEvaluationOutcome(
        action=selected.policy.action,
        selected_policy=selected.policy,
        selected_is_default=False,
        matched=tuple(matched),
        unmatched=tuple(unmatched),
        conflicts=tuple(conflicts),
        snapshot_hash=snapshot_hash,
        reason=reason,
        matched_conditions=tuple(matched_conditions),
    )


def _matched_conflicts(matched: Sequence[PolicyMatch]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(matched):
        for right in matched[index + 1 :]:
            a, b = left.policy, right.policy
            if a.action == b.action:
                continue
            if a.emergency != b.emergency:
                continue
            if a.priority != b.priority:
                continue
            conflicts.append(
                {
                    "kind": "priority_tie",
                    "policies": [a.policy_key, b.policy_key],
                    "priority": a.priority,
                    "actions": [a.action, b.action],
                    "detail": (
                        "Matching policies share priority and emergency rank but differ in action"
                    ),
                }
            )
    return conflicts


def find_policy_conflicts(policies: Sequence[PolicySnapshot]) -> list[dict[str, Any]]:
    enabled = [item for item in policies if item.enabled]
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(enabled):
        for right in enabled[index + 1 :]:
            if left.action == right.action:
                continue
            if not _scopes_overlap(left.target_scope, right.target_scope):
                continue
            if left.emergency != right.emergency:
                continue
            if left.priority != right.priority:
                continue
            conflicts.append(
                {
                    "kind": "priority_tie",
                    "policies": [left.policy_key, right.policy_key],
                    "priority": left.priority,
                    "actions": [left.action, right.action],
                    "scope_overlap": True,
                    "detail": (
                        "Both policies are enabled with the same priority and emergency rank, "
                        "overlapping scope and different actions"
                    ),
                }
            )
    return conflicts


def _scopes_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    for key in ("players", "alliances", "servers", "channels", "languages"):
        a = set(left.get(key) or [])
        b = set(right.get(key) or [])
        if a and b and not (a & b):
            return False
    return True
