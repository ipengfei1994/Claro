from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from claro.domain.enums import DecisionAction, EnforcementTargetType

ENFORCEMENT_ACTIONS = {
    DecisionAction.WARN.value,
    DecisionAction.BLOCK.value,
    DecisionAction.MUTE.value,
    DecisionAction.TEMP_BAN.value,
    DecisionAction.PERM_BAN.value,
}
DEFAULT_DURATIONS = {
    DecisionAction.MUTE.value: 3_600,
    DecisionAction.TEMP_BAN.value: 86_400,
}
MAX_DURATIONS = {
    DecisionAction.MUTE.value: 86_400,
    DecisionAction.TEMP_BAN.value: 2_592_000,
}
DEFAULT_TARGETS = {
    DecisionAction.WARN.value: EnforcementTargetType.PLAYER.value,
    DecisionAction.BLOCK.value: EnforcementTargetType.MESSAGE.value,
    DecisionAction.MUTE.value: EnforcementTargetType.PLAYER.value,
    DecisionAction.TEMP_BAN.value: EnforcementTargetType.PLAYER.value,
    DecisionAction.PERM_BAN.value: EnforcementTargetType.PLAYER.value,
}


class EnforcementValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EnforcementPlan:
    action: str
    target_type: str
    duration_seconds: int | None
    expires_at: datetime | None
    simulated: bool = True


def plan_enforcement(
    *,
    action: str,
    target_type: str | None,
    duration_seconds: int | None,
    now: datetime,
    simulate: bool = True,
) -> EnforcementPlan:
    if action not in ENFORCEMENT_ACTIONS:
        raise EnforcementValidationError(
            f"action '{action}' cannot be enforced; expected one of {sorted(ENFORCEMENT_ACTIONS)}"
        )
    if now.tzinfo is None:
        raise EnforcementValidationError("now must be timezone-aware")
    resolved_type = target_type or DEFAULT_TARGETS[action]
    if resolved_type not in {item.value for item in EnforcementTargetType}:
        raise EnforcementValidationError(f"unknown enforcement target type: {resolved_type}")
    if action == DecisionAction.BLOCK.value:
        if resolved_type != EnforcementTargetType.MESSAGE.value:
            raise EnforcementValidationError("BLOCK enforcement targets a message")
        if duration_seconds is not None:
            raise EnforcementValidationError("BLOCK enforcement does not accept a duration")
    if action == DecisionAction.WARN.value:
        if resolved_type == EnforcementTargetType.MESSAGE.value:
            raise EnforcementValidationError("WARN enforcement targets a player")
        if duration_seconds is not None:
            raise EnforcementValidationError("WARN enforcement does not accept a duration")
    if action in {DecisionAction.MUTE.value, DecisionAction.TEMP_BAN.value}:
        if resolved_type == EnforcementTargetType.MESSAGE.value:
            raise EnforcementValidationError(f"{action} enforcement targets a player")
        duration = DEFAULT_DURATIONS[action] if duration_seconds is None else duration_seconds
        if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
            raise EnforcementValidationError("duration_seconds must be a positive integer")
        if duration > MAX_DURATIONS[action]:
            raise EnforcementValidationError(
                f"duration_seconds for {action} may not exceed {MAX_DURATIONS[action]}"
            )
        return EnforcementPlan(
            action=action,
            target_type=resolved_type,
            duration_seconds=duration,
            expires_at=now + timedelta(seconds=duration),
            simulated=simulate,
        )
    if action == DecisionAction.PERM_BAN.value:
        if resolved_type == EnforcementTargetType.MESSAGE.value:
            raise EnforcementValidationError("PERM_BAN enforcement targets a player")
        if duration_seconds is not None:
            raise EnforcementValidationError("PERM_BAN does not accept a duration")
        return EnforcementPlan(
            action=action,
            target_type=resolved_type,
            duration_seconds=None,
            expires_at=None,
            simulated=simulate,
        )
    return EnforcementPlan(
        action=action,
        target_type=resolved_type,
        duration_seconds=None,
        expires_at=None,
        simulated=simulate,
    )


def validate_target_ref(action: str, target_ref: str, *, message_id: str) -> None:
    if not isinstance(target_ref, str) or not target_ref.strip():
        raise EnforcementValidationError("target_ref must be a non-empty string")
    if action == DecisionAction.BLOCK.value and target_ref != message_id:
        raise EnforcementValidationError("BLOCK enforcement target must equal the message id")
    if action != DecisionAction.BLOCK.value and target_ref == message_id:
        raise EnforcementValidationError("player enforcement target must not be the message id")
