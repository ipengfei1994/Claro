from __future__ import annotations

from claro.application.health import HealthRegistration, HealthService


class _FailingCheck:
    def check(self) -> None:
        raise ConnectionError("service unavailable")


def test_health_service_reports_failure_without_hiding_it() -> None:
    service = HealthService(
        [
            HealthRegistration(name="redis", check=None),
            HealthRegistration(name="postgresql", check=_FailingCheck()),
        ]
    )
    results = {result.name: result for result in service.check_all()}
    assert results["redis"].status == "disabled"
    assert results["postgresql"].status == "unhealthy"
    assert "service unavailable" in results["postgresql"].detail
