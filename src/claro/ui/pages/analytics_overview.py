"""Analytics overview: canonical KPIs and cross-domain charts."""

from __future__ import annotations

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.analytics_ui import (
    analytics_filters,
    bar_chart,
    line_chart,
    metric_row,
    render_banner,
    service_from,
)
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    page_header("Analytics · 总览", "所有指标来自统一口径服务层，页面不直接执行 SQL。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_overview")
    result = service.overview(filters)
    render_banner(result)

    metric_row(
        result["kpis"],
        [
            ("消息总量", "total_messages"),
            ("风险消息", "risk_messages"),
            ("Risk Rate", "risk_rate"),
            ("高风险消息", "high_risk_messages"),
            ("治理决策", "governance_decisions"),
            ("自动处置率", "automatic_handling_rate"),
            ("人工审核率", "review_rate"),
            ("误杀率（检测层）", "false_positive_rate"),
        ],
    )
    st.caption(
        f"去重风险玩家 {result['kpis']['unique_risk_players']} · "
        f"重复违规玩家 {result['kpis']['repeat_offenders']} · "
        f"有状态决策样本 {result['kpis']['eligible_finalized_decisions']}"
    )
    automatic_detail = result["kpis"].get("automatic_handling_rate_detail") or {}
    if automatic_detail.get("low_sample"):
        st.warning(
            f"自动处置率与人工审核率样本量不足（{automatic_detail.get('sample_size')} < 30），"
            "因此显示为不可计算，而不是 0% 或 100%。"
        )
    st.caption(
        f"检测层误杀率 {result['kpis']['false_positive_rate']} · "
        f"漏判率 {result['kpis']['false_negative_rate']} · "
        f"样本量 {result['kpis']['detection_sample_size']} · "
        f"Precision {result['kpis']['detection_precision']} · "
        f"Recall {result['kpis']['detection_recall']}"
    )

    series = service.risk(filters, "day")
    line_chart(series["series"], "bucket", "risk_rate", "日度 Risk Rate 趋势")
    bar_chart(series["categories"], "category", "message_count", "风险类别分布")
    governance = service.governance(filters)
    bar_chart(
        governance["decision_distribution"][:12],
        "action",
        "decision_count",
        "治理动作分布（前 12）",
    )
    community = service.community(filters, limit=10)
    bar_chart(
        community["servers"],
        "server_name",
        "risk_rate",
        "服务器 Risk Rate 对比",
    )

    page_header("数据质量摘要")
    st.json(result["quality"])
    st.warning(
        "本页所有数据均为合成数据。检测层误杀率/漏判率来自 risk_event 与合成 ground truth "
        "的对比，不代表真实线上人工审核结果。"
    )
