from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

HealthStatus = Literal["healthy", "disabled", "simulated", "unhealthy"]


class HealthCheck(Protocol):
    def check(self) -> None: ...


@dataclass(frozen=True)
class HealthRegistration:
    name: str
    check: HealthCheck | None
    status_if_disabled: HealthStatus = "disabled"


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    status: HealthStatus
    detail: str
    checked_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at.isoformat(),
        }


class HealthService:
    def __init__(self, registrations: Sequence[HealthRegistration]) -> None:
        self.registrations = tuple(registrations)

    def check_all(self) -> list[ComponentHealth]:
        results: list[ComponentHealth] = []
        for registration in self.registrations:
            checked_at = datetime.now(UTC)
            if registration.check is None:
                results.append(
                    ComponentHealth(
                        name=registration.name,
                        status=registration.status_if_disabled,
                        detail="Not enabled in the current mode",
                        checked_at=checked_at,
                    )
                )
                continue
            try:
                registration.check.check()
            except Exception as error:
                results.append(
                    ComponentHealth(
                        name=registration.name,
                        status="unhealthy",
                        detail=f"{type(error).__name__}: {error}",
                        checked_at=checked_at,
                    )
                )
            else:
                results.append(
                    ComponentHealth(
                        name=registration.name,
                        status="healthy",
                        detail="Connection successful",
                        checked_at=checked_at,
                    )
                )
        return results
