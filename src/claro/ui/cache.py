"""Short-lived cache for read-only dashboard queries.

The dashboards run multi-CTE aggregates over the whole message table, which is
the most expensive read in the product. Those aggregates also change slowly, so
a 45-second cache removes repeated work when a user navigates between pages or
moves a slider, while staying close enough to real time that the numbers still
describe "now" rather than "some time this morning".

Rules that keep the cache honest:

* Only pure reads are cached. Every write path (review, override, enforcement,
  feedback, policy change) goes through the live service and every page that
  writes always re-reads through the live service afterwards.
* Cache keys include every query parameter, so a different filter, grain or
  window can never return another query's rows.
* The sidebar "刷新数据" button clears the cache explicitly, so a demo can force
  fresh numbers at any moment instead of waiting for the TTL.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

TTL_SECONDS = 45


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def overview(_service: Any, window_days: int) -> dict[str, Any]:
    """Governance overview for one time window."""
    return _service.overview(days=window_days)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def analytics_overview(_service: Any, filters: dict[str, Any]) -> dict[str, Any]:
    return _service.overview(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def analytics_risk(_service: Any, filters: dict[str, Any], grain: str) -> dict[str, Any]:
    return _service.risk(filters, grain)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def analytics_governance(_service: Any, filters: dict[str, Any]) -> dict[str, Any]:
    return _service.governance(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def analytics_community(_service: Any, filters: dict[str, Any], limit: int) -> dict[str, Any]:
    return _service.community(filters, limit=limit)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def analytics_model(_service: Any, filters: dict[str, Any]) -> dict[str, Any]:
    return _service.model(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def analytics_strategy(_service: Any, filters: dict[str, Any]) -> dict[str, Any]:
    return _service.strategy(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def risk_intelligence(_service: Any) -> dict[str, Any]:
    return _service.risk_intelligence()


def clear() -> None:
    """Drop every cached dashboard result (used by the sidebar refresh button)."""
    st.cache_data.clear()
