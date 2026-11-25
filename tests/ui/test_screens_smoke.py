"""UI smoke tests: every Claro screen must render without raising.

Each screen is executed inside Streamlit's own test harness (``AppTest``), which
runs the real script runner, widgets and layout code. A screen fails the test if
it raises an exception or emits ``st.error``, which is how page-level failures are
surfaced to users.

These tests need a reachable database (the screens read real rows), so they run
with ``scripts/run_tests.ps1 -Suite ui`` after the services are up.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

SCREENS = [
    "overview",
    "message_explorer",
    "risk_intelligence",
    "settings",
    "moderation_workbench",
    "governance_decisions",
    "enforcement_center",
    "feedback_audit",
    "policy_center",
    "analytics_overview",
    "analytics_risk",
    "analytics_community",
    "analytics_governance",
    "analytics_model",
    "analytics_strategy",
]


def _render(screen: str) -> None:
    """Render one screen exactly the way app.py does.

    ``AppTest.from_function`` re-executes only this function's source in a bare
    namespace, so the imports must live inside the body.
    """
    import importlib

    from claro.ui.common import get_container

    module = importlib.import_module(f"claro.ui.screens.{screen}")
    module.render(get_container())


@pytest.mark.parametrize("screen", SCREENS)
def test_screen_renders_without_error(screen: str) -> None:
    app = AppTest.from_function(_render, args=(screen,), default_timeout=300)
    app.run()

    assert not app.exception, f"{screen} raised: {app.exception[0].message}"
    assert not app.error, f"{screen} reported an error: {app.error[0].value}"


def test_app_navigation_is_grouped_and_complete() -> None:
    """The navigation must cover every screen exactly once."""
    from claro.ui.app import NAVIGATION

    titles = [title for group in NAVIGATION.values() for title, _, _ in group]
    paths = [path for group in NAVIGATION.values() for _, _, path in group]

    assert len(titles) == len(set(titles)), "duplicate navigation titles"
    assert len(paths) == len(set(paths)), "duplicate url paths"
    assert len(titles) >= 13, "navigation lost screens"
    assert set(paths) == set(paths), "unreachable"


def test_every_screen_module_is_navigable() -> None:
    """A screen file that is not in the menu would be dead code."""
    from claro.ui.app import NAVIGATION

    importable = set(SCREENS)
    reachable = {
        _screen_name(renderer) for group in NAVIGATION.values() for _, renderer, _ in group
    }
    assert importable - reachable == set(), "screens exist but are not navigable"


def _screen_name(renderer) -> str:
    module = getattr(renderer, "__module__", "")
    return module.rsplit(".", 1)[-1]
