"""Unit tests for simulated enforcement planning and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from claro.domain.enums import DecisionAction, EnforcementTargetType
from claro.governance.enforcement import (
    EnforcementValidationError,
    plan_enforcement,
    validate_target_ref,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
MESSAGE_ID = "00000000-0000-0000-0000-000000000001"


def test_warn_plan_targets_player() -> None:
    plan = plan_enforcement(
        action=DecisionAction.WARN.value,
        target_type=None,
        duration_seconds=None,
        now=NOW,
    )
    assert plan.target_type == EnforcementTargetType.PLAYER.value
    assert plan.duration_seconds is None
    assert plan.expires_at is None
    assert plan.simulated is True


def test_block_plan_targets_message() -> None:
    plan = plan_enforcement(
        action=DecisionAction.BLOCK.value,
        target_type=EnforcementTargetType.MESSAGE.value,
        duration_seconds=None,
        now=NOW,
    )
    assert plan.target_type == EnforcementTargetType.MESSAGE.value
    assert plan.expires_at is None


def test_mute_plan_uses_default_duration() -> None:
    plan = plan_enforcement(
        action=DecisionAction.MUTE.value,
        target_type=None,
        duration_seconds=None,
        now=NOW,
    )
    assert plan.duration_seconds == 3600
    assert plan.expires_at == NOW + timedelta(seconds=3600)


def test_temp_ban_plan_uses_explicit_duration() -> None:
    plan = plan_enforcement(
        action=DecisionAction.TEMP_BAN.value,
        target_type=None,
        duration_seconds=120,
        now=NOW,
    )
    assert plan.duration_seconds == 120
    assert plan.expires_at == NOW + timedelta(seconds=120)


def test_perm_ban_has_no_expiry() -> None:
    plan = plan_enforcement(
        action=DecisionAction.PERM_BAN.value,
        target_type=None,
        duration_seconds=None,
        now=NOW,
    )
    assert plan.duration_seconds is None
    assert plan.expires_at is None


def test_player_server_target_is_allowed() -> None:
    plan = plan_enforcement(
        action=DecisionAction.MUTE.value,
        target_type=EnforcementTargetType.PLAYER_SERVER.value,
        duration_seconds=60,
        now=NOW,
    )
    assert plan.target_type == EnforcementTargetType.PLAYER_SERVER.value


@pytest.mark.parametrize(
    ("action", "target_type", "duration"),
    [
        (DecisionAction.REVIEW.value, None, None),
        (DecisionAction.BLOCK.value, EnforcementTargetType.PLAYER.value, None),
        (DecisionAction.BLOCK.value, None, 60),
        (DecisionAction.WARN.value, EnforcementTargetType.MESSAGE.value, None),
        (DecisionAction.WARN.value, None, 60),
        (DecisionAction.MUTE.value, EnforcementTargetType.MESSAGE.value, 60),
        (DecisionAction.MUTE.value, None, 0),
        (DecisionAction.TEMP_BAN.value, None, -5),
        (DecisionAction.TEMP_BAN.value, None, 2_592_001),
        (DecisionAction.PERM_BAN.value, None, 60),
    ],
)
def test_invalid_plans_rejected(action: str, target_type: str | None, duration: int | None) -> None:
    with pytest.raises(EnforcementValidationError):
        plan_enforcement(
            action=action,
            target_type=target_type,
            duration_seconds=duration,
            now=NOW,
        )


def test_naive_datetime_rejected() -> None:
    with pytest.raises(EnforcementValidationError, match="timezone-aware"):
        plan_enforcement(
            action=DecisionAction.WARN.value,
            target_type=None,
            duration_seconds=None,
            now=datetime(2026, 11, 25, 12, 0),
        )


def test_explicit_simulate_false_is_supported() -> None:
    plan = plan_enforcement(
        action=DecisionAction.WARN.value,
        target_type=None,
        duration_seconds=None,
        now=NOW,
        simulate=False,
    )
    assert plan.simulated is False


def test_block_target_must_match_message_id() -> None:
    validate_target_ref(DecisionAction.BLOCK.value, MESSAGE_ID, message_id=MESSAGE_ID)
    with pytest.raises(EnforcementValidationError, match="must equal"):
        validate_target_ref(DecisionAction.BLOCK.value, "player.001", message_id=MESSAGE_ID)


def test_player_target_must_not_be_message_id() -> None:
    with pytest.raises(EnforcementValidationError, match="must not be"):
        validate_target_ref(DecisionAction.MUTE.value, MESSAGE_ID, message_id=MESSAGE_ID)


def test_empty_target_rejected() -> None:
    with pytest.raises(EnforcementValidationError, match="non-empty"):
        validate_target_ref(DecisionAction.WARN.value, "", message_id=MESSAGE_ID)
