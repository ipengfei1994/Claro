"""Shared helpers for the Phase 05 analytics pages."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import plotly.express as px
import streamlit as st

from claro.analytics.filters import AnalyticsFilters
from claro.domain.enums import RiskCategory, RiskSeverity
from claro.ui.common import fmt_clock, fmt_int, fmt_pct, fmt_score
from claro.ui.theme import resolve_theme

_ACCENT = "#2563EB"
_NEUTRAL = "#64748B"


def analytics_filters(container: Any, *, key_prefix: str) -> AnalyticsFilters:
    """Render global filters and return the object passed to every service."""
    today = datetime.now(UTC).date()
    defaults = st.session_state.get(f"{key_prefix}_dates", (today - timedelta(days=365), today))
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
        dataset_name = st.text_input("数据集名称（留空=全部）", key=f"{key_prefix}_dataset") or None
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
    left.caption(f"数据窗口：{fmt_clock(window.get('start'))} → {fmt_clock(window.get('end'))}")
    right.caption(f"数据源：{result.get('data_source_label', '—')}")
    extra.caption(f"口径：{result.get('definition', {}).get('version', '—')}")
    st.caption(
        f"数据集：{window.get('dataset', '—')} · 生成时间：{fmt_clock(result.get('generated_at'))}"
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
        column.metric(label, _display(key, value))


def _display(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if "rate" in key:
        return fmt_pct(value)
    if isinstance(value, int):
        return fmt_int(value)
    if isinstance(value, float):
        return fmt_int(value) if value.is_integer() else fmt_score(value, 3)
    return str(value)


_AXIS_LABELS = {
    "bucket": "时间",
    "day": "日期",
    "week": "周",
    "month": "月份",
    "hour": "小时",
    "category": "风险类别",
    "severity": "风险等级",
    "action": "治理动作",
    "server_name": "服务器",
    "alliance_name": "联盟",
    "player_ref": "玩家",
    "policy_key": "策略",
    "risk_rate": "风险率",
    "review_rate": "人工审核率",
    "message_count": "消息数",
    "total_messages": "消息数",
    "risk_messages": "风险消息数",
    "high_risk_messages": "高风险消息数",
    "decision_count": "决策数",
    "replay_hit_messages": "命中消息数",
    "count": "数量",
}


def _axis_label(field: str) -> str:
    return _AXIS_LABELS.get(field, field)


_TIME_FIELDS = {"bucket", "day", "week", "month", "hour"}


def _is_time_field(field: str) -> bool:
    return field in _TIME_FIELDS


def _date_axis(field: str) -> dict[str, str]:
    """Use a local, unambiguous date format instead of Plotly's US default."""
    return {
        "tickformat": "%m-%d" if field in {"bucket", "day", "hour"} else "%Y-%m",
        "hoverformat": "%Y-%m-%d %H:%M" if field == "hour" else "%Y-%m-%d",
    }


def _drop_low_sample(
    rows: list[dict[str, Any]], *, min_sample: int | None, sample_field: str
) -> tuple[list[dict[str, Any]], int]:
    """Remove buckets whose denominator is too small to be a rate.

    A two-message day with zero flagged messages renders as 0% and turns a trend
    line into a cliff. Those buckets are dropped and the count is reported, so
    the chart shows a rate instead of an artefact of an empty bucket.
    """
    if not min_sample or not rows:
        return rows, 0
    kept = [row for row in rows if (row.get(sample_field) or 0) >= min_sample]
    return kept, len(rows) - len(kept)


def line_chart(
    rows: list[dict[str, Any]],
    x: str,
    y: str,
    title: str,
    *,
    min_sample: int | None = None,
    sample_field: str = "total_messages",
) -> None:
    rows, suppressed = _drop_low_sample(rows, min_sample=min_sample, sample_field=sample_field)
    if not rows:
        empty_state("当前筛选条件下没有可展示的时间序列。")
        return
    tokens = resolve_theme()
    figure = px.line(
        rows, x=x, y=y, title=title, markers=True, labels={x: _axis_label(x), y: _axis_label(y)}
    )
    figure.update_layout(
        height=320,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": tokens.muted},
        title={"font": {"color": tokens.text, "size": 13}, "x": 0, "xanchor": "left"},
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
        xaxis={
            "gridcolor": tokens.grid,
            "linecolor": tokens.border,
            "tickfont": {"color": tokens.muted},
            **(_date_axis(x) if _is_time_field(x) else {}),
        },
        yaxis={
            "gridcolor": tokens.grid,
            "linecolor": tokens.border,
            "tickfont": {"color": tokens.muted},
            "tickformat": ".0%" if "rate" in y else None,
        },
        hoverlabel={"bgcolor": tokens.surface_alt, "bordercolor": tokens.border},
    )
    figure.update_traces(line={"color": tokens.accent, "width": 2})
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    if suppressed:
        st.caption(
            f"已剔除 {suppressed} 个样本量不足 {min_sample} 的时间桶："
            "这些桶的比率没有统计意义，画出来会变成假的下探。"
        )


def bar_chart(
    rows: list[dict[str, Any]], x: str, y: str, title: str, *, color: str | None = None
) -> None:
    if not rows:
        empty_state("当前筛选条件下没有可展示的数据。")
        return
    tokens = resolve_theme()
    figure = px.bar(
        rows,
        x=x,
        y=y,
        title=title,
        color_discrete_sequence=[color or tokens.accent],
        labels={x: _axis_label(x), y: _axis_label(y)},
    )
    figure.update_layout(
        height=340,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": tokens.muted},
        title={"font": {"color": tokens.text, "size": 13}, "x": 0, "xanchor": "left"},
        xaxis={
            "tickangle": -20,
            "gridcolor": "rgba(0,0,0,0)",
            "linecolor": tokens.border,
            "tickfont": {"color": tokens.muted},
        },
        yaxis={
            "gridcolor": tokens.grid,
            "linecolor": tokens.border,
            "tickfont": {"color": tokens.muted},
            "tickformat": ".0%" if "rate" in y else None,
        },
        hoverlabel={"bgcolor": tokens.surface_alt, "bordercolor": tokens.border},
        margin={"l": 40, "r": 20, "t": 50, "b": 80},
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


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
