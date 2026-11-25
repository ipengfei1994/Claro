"""Shared helpers for the Phase 05 analytics pages."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import plotly.express as px
import streamlit as st

from claro.analytics.filters import AnalyticsFilters
from claro.domain.enums import RiskCategory, RiskSeverity

_ACCENT = "#2563EB"
_NEUTRAL = "#64748B"


def analytics_filters(container: Any, *, key_prefix: str) -> AnalyticsFilters:
    """Render global filters and return the object passed to every service."""
    today = datetime.now(UTC).date()
    defaults = st.session_state.get(
        f"{key_prefix}_dates", (today - timedelta(days=365), today)
    )
    dates = st.sidebar.date_input(
        "分析时间范围",
        value=defaults,
        key=f"{key_prefix}_dates",
    )
    if isinstance(dates, (list, tuple)) and len(dates) == 2:
        start, end = dates
    else:
        st.sidebar.warning("请提供完整的起止日期。")
        st.stop()
        raise AssertionError("unreachable")
    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    with st.sidebar.expander("分析筛选器", expanded=True):
        dataset_name = st.text_input(
            "数据集名称（留空=全部）", key=f"{key_prefix}_dataset"
        ) or None
        server_ref = st.text_input("服务器 ref", key=f"{key_prefix}_server") or None
        alliance_ref = st.text_input("联盟 ref", key=f"{key_prefix}_alliance") or None
        player_ref = st.text_input("玩家 ref", key=f"{key_prefix}_player") or None
        category_choice = st.selectbox(
            "风险类别",
            ["全部", *(item.value for item in RiskCategory)],
            key=f"{key_prefix}_category",
        )
        severity_choice = st.selectbox(
            "风险等级",
            ["全部", *(item.value for item in RiskSeverity)],
            key=f"{key_prefix}_severity",
        )
        policy_key = st.text_input("策略 key", key=f"{key_prefix}_policy") or None
        model_id = st.text_input("模型 ID", key=f"{key_prefix}_model") or None
    return AnalyticsFilters(
        start=start_dt,
        end=end_dt,
        dataset_name=dataset_name,
        server_ref=server_ref,
        alliance_ref=alliance_ref,
        player_ref=player_ref,
        risk_category=None if category_choice == "全部" else category_choice,
        risk_severity=None if severity_choice == "全部" else severity_choice,
        policy_key=policy_key,
        model_id=model_id,
    )


def render_banner(result: dict[str, Any]) -> None:
    """Show data tier, window, definition and freshness above every chart."""
    window = result.get("filters", {})
    left, right, extra = st.columns([2, 2, 1])
    left.caption(
        f"数据窗口：{window.get('start', '—')} → {window.get('end', '—')}"
    )
    right.caption(f"数据源：{result.get('data_source_label', '—')}")
    extra.caption(f"口径：{result.get('definition', {}).get('version', '—')}")
    st.caption(
        f"数据集：{window.get('dataset', '—')} · "
        f"生成时间：{result.get('generated_at', '—')}"
    )
    if result.get("notes"):
        with st.expander("指标口径与限制", expanded=False):
            for note in result["notes"]:
                st.caption(f"• {note}")


def empty_state(message: str) -> None:
    st.info(message)


def metric_row(metrics: dict[str, Any], keys: list[tuple[str, str]]) -> None:
    """Render a row of metrics with explicit missing-value handling.

    A gated rate may arrive as a dictionary carrying its numerator, denominator
    and sample size; when its value is unavailable it is rendered as an
    explicit dash rather than a misleading zero.
    """
    columns = st.columns(len(keys))
    for column, (label, key) in zip(columns, keys, strict=False):
        value = metrics.get(key)
        if isinstance(value, dict):
            value = value.get("value", value.get("risk_rate"))
        column.metric(label, "—" if value is None else value)


def line_chart(rows: list[dict[str, Any]], x: str, y: str, title: str) -> None:
    if not rows:
        empty_state("当前筛选条件下没有可展示的时间序列。")
        return
    figure = px.line(rows, x=x, y=y, title=title, markers=True)
    figure.update_layout(
        height=320,
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"color": "#111827"},
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
    )
    figure.update_traces(line={"color": _ACCENT})
    st.plotly_chart(figure, width="stretch")


def bar_chart(
    rows: list[dict[str, Any]], x: str, y: str, title: str, *, color: str | None = None
) -> None:
    if not rows:
        empty_state("当前筛选条件下没有可展示的数据。")
        return
    figure = px.bar(rows, x=x, y=y, title=title, color_discrete_sequence=[color or _ACCENT])
    figure.update_layout(
        height=340,
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"color": "#111827"},
        xaxis={"tickangle": -20},
        margin={"l": 40, "r": 20, "t": 50, "b": 80},
    )
    st.plotly_chart(figure, width="stretch")


def dataframe(rows: list[dict[str, Any]], *, height: int = 360) -> None:
    if not rows:
        empty_state("当前筛选条件下没有记录。")
        return
    st.dataframe(rows, hide_index=True, width="stretch", height=height)


def service_from(container: Any) -> Any:
    """Fail loudly when the analytics service is unavailable."""
    if container.analytics_service is None:
        st.error("分析服务不可用，请检查运行模式。")
        st.stop()
    return container.analytics_service
