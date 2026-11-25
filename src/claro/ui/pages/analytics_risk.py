"""Risk analytics page: trend, categories, severity and anomalies."""

from __future__ import annotations

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.analytics_ui import (
    analytics_filters,
    bar_chart,
    dataframe,
    empty_state,
    line_chart,
    metric_row,
    render_banner,
    service_from,
)
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    page_header("Risk Analytics", "风险趋势、类别分布、时间变化与统计异常峰值。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_risk")
    grain = st.selectbox("时间粒度", ("hour", "day", "week", "month"), index=1)
    result = service.risk(filters, grain)
    render_banner(result)

    overview = service.overview(filters)
    metric_row(
        overview["kpis"],
        [
            ("消息总量", "total_messages"),
            ("风险消息", "risk_messages"),
            ("Risk Rate", "risk_rate"),
            ("高风险消息", "high_risk_messages"),
            ("涉及玩家", "unique_risk_players"),
            ("重复违规玩家", "repeat_offenders"),
        ],
    )

    line_chart(result["series"], "bucket", "risk_messages", "风险消息趋势")
    line_chart(result["series"], "bucket", "risk_rate", "Risk Rate 趋势")
    left, right = st.columns(2)
    with left:
        bar_chart(result["categories"], "category", "message_count", "类别数量")
    with right:
        bar_chart(result["severities"], "severity", "message_count", "风险等级分布")

    page_header("多标签共现")
    if result["cooccurrence"]:
        dataframe(result["cooccurrence"])
    else:
        empty_state("当前合成数据集中每条风险消息仅携带一个类别，共现矩阵为空。")

    page_header("统计异常峰值")
    peaks = result["anomaly_bucket_indices"]
    if peaks:
        st.warning(f"检测到 {len(peaks)} 个超过 mean + 3σ 的时间桶：{peaks}")
        dataframe([result["series"][index] for index in peaks])
    else:
        st.info("当前窗口内未检测到超过 mean + 3σ 的风险率峰值。")
