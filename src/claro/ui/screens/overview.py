"""Overview dashboard.

Everything on this page is derived from live PostgreSQL rows through
:class:`~claro.application.explorer_service.ExplorerService` and
:class:`~claro.analytics.services.AnalyticsService`. No number here is
hardcoded, and any metric whose sample is too small is shown as
"不可计算" rather than as zero.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui import cache
from claro.ui.charts import (
    action_bar,
    bar_chart,
    donut_chart,
    empty_figure,
    line_chart,
    severity_bar,
)
from claro.ui.common import (
    ACTION_LABELS,
    RISK_LABELS,
    category_text,
    data_table,
    fmt_int,
    fmt_pct,
    fmt_relative,
    kpi_cards,
    ratio_display,
    render_activity,
    render_empty,
    render_section,
    status_text,
)
from claro.ui.theme import category_color, resolve_theme, status_color

WINDOWS: dict[str, int] = {"近 7 天": 7, "近 30 天": 30, "近 90 天": 90, "近 1 年": 365}
_DEFAULT_WINDOW = "近 1 年"


def render(container: AppContainer) -> None:
    service = container.explorer_service
    if service is None:
        st.error("探查服务未启用，请检查运行模式与配置。")
        return

    tokens = resolve_theme()
    st.title("治理总览")
    st.caption("从消息入库到处置执行的全链路视图 · 合成演示数据，非真实运营数据")

    selector, _ = st.columns([3, 5], gap="small")
    with selector:
        choice = st.segmented_control(
            "时间范围",
            options=list(WINDOWS),
            default=_DEFAULT_WINDOW,
            key="overview_window",
            label_visibility="collapsed",
        )
    window = WINDOWS.get(choice or _DEFAULT_WINDOW, 365)

    try:
        data = cache.overview(service, window)
    except Exception as error:  # noqa: BLE001 - show the real failure, not a blank page
        st.error(f"总览数据加载失败：{error}")
        return

    kpis = data["kpis"]
    workload = data["workload"] or {}

    _render_kpis(kpis, workload, window)
    st.divider()
    _render_trend(data, kpis, tokens)
    st.divider()
    _render_distributions(data, tokens)
    st.divider()
    _render_operation(data, tokens)


def _render_kpis(kpis: dict, workload: dict, window: int) -> None:
    auto_value, auto_hint = ratio_display(kpis.get("automatic_handling_rate_detail"))
    review_value, review_hint = ratio_display(kpis.get("review_rate_detail"))
    fp_value, fp_hint = ratio_display(
        {
            "value": kpis.get("false_positive_rate"),
            "denominator": kpis.get("detection_sample_size"),
        }
    )
    render_section(
        f"核心指标 · 近 {window} 天",
        "风险消息率与自动处置率来自治理决策表；样本不足时按规则抑制，不展示失真的百分比。",
    )
    kpi_cards(
        [
            ("消息总量", fmt_int(kpis.get("total_messages")), "去重消息数"),
            (
                "风险消息率",
                fmt_pct(_rate(kpis.get("risk_rate"))),
                f"风险消息 {fmt_int(kpis.get('risk_messages'))} 条",
            ),
            (
                "高风险消息",
                fmt_int(kpis.get("high_risk_messages")),
                f"占比 {fmt_pct(_rate(kpis.get('high_risk_rate')))}",
            ),
            ("自动处置率", auto_value, auto_hint),
        ]
    )
    kpi_cards(
        [
            (
                "待处理案例",
                fmt_int(workload.get("pending_cases")),
                f"其中逾期 {fmt_int(workload.get('overdue_cases'))}",
            ),
            (
                "生效处置",
                fmt_int(workload.get("active_enforcements")),
                "已执行的模拟处置动作",
            ),
            ("人工审核率", review_value, review_hint),
            ("检测误杀率", fp_value, fp_hint),
        ]
    )


def _rate(value: object) -> object:
    """Unwrap the ``risk_rate`` helper's envelope into a plain ratio."""
    if isinstance(value, dict):
        return value.get("risk_rate", value.get("value"))
    return value


def _render_trend(data: dict, kpis: dict, tokens) -> None:
    render_section("消息与风险趋势", "按天聚合，用来判断风险是单点爆发还是持续存在。")
    timeline = data["timeline"]
    if not timeline:
        st.plotly_chart(
            empty_figure("所选时间范围内没有消息", tokens=tokens),
            width="stretch",
            config={"displayModeBar": False},
        )
        return
    frame = pd.DataFrame(timeline)
    frame["day"] = pd.to_datetime(frame["day"])
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.plotly_chart(
            line_chart(
                frame["day"],
                {
                    "消息量": frame["messages"].tolist(),
                    "风险消息": frame["risk_messages"].tolist(),
                    "高风险消息": frame["high_risk_messages"].tolist(),
                },
                height=300,
                tokens=tokens,
                gap_days=3,
            ),
            width="stretch",
            config={"displayModeBar": False},
        )
        st.caption(
            "相邻日期相隔超过 3 天处断线：没有消息的日期不画成下降，避免把空档读成风险归零。"
        )
    with right:
        total = kpis.get("total_messages")
        risky = kpis.get("risk_messages")
        high = kpis.get("high_risk_messages")
        peak = frame.loc[frame["messages"].idxmax()]
        render_section("区间摘要")
        st.markdown(
            '<div class="claro-kpi">'
            '<div class="claro-kpi-label">累计消息</div>'
            f'<div class="claro-kpi-value">{fmt_int(total)}</div>'
            f'<div class="claro-kpi-hint">单日峰值 {fmt_int(peak["messages"])} 条 · '
            f"{peak['day']:%Y-%m-%d}</div>"
            '<div class="claro-kpi-label" style="margin-top:12px;">风险占比</div>'
            f'<div class="claro-kpi-value">{fmt_pct(_rate(kpis.get("risk_rate")))}</div>'
            f'<div class="claro-kpi-hint">高风险 {fmt_int(high)} 条，'
            f"占风险消息 {fmt_pct(high / risky if risky else None)}</div>"
            "</div>",
            unsafe_allow_html=True,
        )


def _render_distributions(data: dict, tokens) -> None:
    render_section(
        "风险构成",
        "风险类别与等级决定处置路径；只统计窗口内有检测事件的日期，空白日不入图。",
    )
    category_rows = data["categories"]
    severities = {row["severity"]: row["events"] for row in data["severities"]}
    decisions = {row["action"]: row["decisions"] for row in data["decisions"]}

    first, second, third = st.columns(3, gap="medium")
    with first:
        if category_rows:
            st.plotly_chart(
                donut_chart(
                    [category_text(row["category"]) for row in category_rows],
                    [row["events"] for row in category_rows],
                    title="风险类别分布",
                    colors=[category_color(row["category"], tokens) for row in category_rows],
                    height=280,
                    tokens=tokens,
                ),
                width="stretch",
                config={"displayModeBar": False},
            )
        else:
            st.plotly_chart(
                empty_figure("暂无风险事件", tokens=tokens),
                width="stretch",
                config={"displayModeBar": False},
            )
    with second:
        if severities:
            st.plotly_chart(
                severity_bar(
                    severities, title="风险等级分布", height=280, tokens=tokens, labels=RISK_LABELS
                ),
                width="stretch",
                config={"displayModeBar": False},
            )
        else:
            st.plotly_chart(
                empty_figure("暂无风险等级数据", tokens=tokens),
                width="stretch",
                config={"displayModeBar": False},
            )
    with third:
        if decisions:
            st.plotly_chart(
                action_bar(
                    decisions, title="决策动作分布", height=280, tokens=tokens, labels=ACTION_LABELS
                ),
                width="stretch",
                config={"displayModeBar": False},
            )
        else:
            st.plotly_chart(
                empty_figure("暂无治理决策", tokens=tokens),
                width="stretch",
                config={"displayModeBar": False},
            )

    servers = data["servers"]
    if servers:
        frame = pd.DataFrame(servers).head(8)
        st.plotly_chart(
            bar_chart(
                [str(value) for value in frame["server_ref"]],
                frame["high_risk_messages"].astype(float).tolist(),
                title="高风险消息最多的服务器",
                colors=[status_color("high", tokens)] * len(frame),
                height=260,
                tokens=tokens,
            ),
            width="stretch",
            config={"displayModeBar": False},
        )
    st.caption(
        "决策动作分布包含 Phase 02 的历史批量决策（无决策状态标记）；"
        "自动处置率只统计带决策状态的记录，两者分母不同，不能直接相除。"
    )


def _render_operation(data: dict, tokens) -> None:
    render_section("运营视图", "谁在处理、处理了什么、还积压多少。")
    feed_col, data_col = st.columns([3, 2], gap="medium")
    with feed_col:
        st.markdown("**最近治理活动**")
        render_activity(data["activity"], limit=10)
    with data_col:
        st.markdown("**数据集概况**")
        datasets = data["datasets"]
        if not datasets:
            render_empty("还没有数据集", "运行 `claro demo-run` 生成演示数据。")
        else:
            frame = pd.DataFrame(datasets)
            for column in ("messages", "detected", "cases"):
                frame[column] = frame[column].map(fmt_int)
            frame["is_synthetic"] = frame["is_synthetic"].map(
                lambda value: "合成" if value else "真实"
            )
            frame["created_at"] = frame["created_at"].map(fmt_relative)
            data_table(
                frame[["name", "is_synthetic", "messages", "detected", "cases", "created_at"]],
                column_config={
                    "name": st.column_config.TextColumn("数据集"),
                    "is_synthetic": st.column_config.TextColumn("类型"),
                    "messages": st.column_config.TextColumn("消息"),
                    "detected": st.column_config.TextColumn("已检测"),
                    "cases": st.column_config.TextColumn("案例"),
                    "created_at": st.column_config.TextColumn("创建时间"),
                },
            )

    notes = data.get("notes") or []
    if notes:
        with st.expander("口径说明"):
            for note in notes:
                st.markdown(f"- {note}")

    quality = data.get("quality") or {}
    if quality:
        total = (quality.get("passed") or 0) + (quality.get("failed") or 0)
        st.caption(
            f"数据质量规则：通过 {fmt_int(quality.get('passed'))} / {fmt_int(total)}，"
            f"错误 {fmt_int(quality.get('errors'))}，告警 {fmt_int(quality.get('warnings'))}。"
            f"决策状态「{status_text('auto_decided')}」= 自动处置，"
            f"「{status_text('human_reviewed')}」= 人工终审。"
        )
