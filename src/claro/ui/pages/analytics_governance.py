"""Governance analytics page: decisions, moderation and simulated enforcement."""

from __future__ import annotations

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.analytics_ui import (
    analytics_filters,
    bar_chart,
    dataframe,
    metric_row,
    render_banner,
    service_from,
)
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    page_header("Governance Analytics", "治理决策、审核效率与模拟处置执行情况。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_gov")
    result = service.governance(filters)
    render_banner(result)

    metric_row(
        result["decisions"],
        [
            ("决策总数", "total_decisions"),
            ("有效终审样本", "eligible_finalized"),
            ("自动决策", "automatic_decisions"),
            ("自动处置率", "automatic_handling_rate"),
            ("人工审核率", "review_rate"),
            ("推翻率", "override_rate"),
        ],
    )
    bar_chart(
        result["decision_distribution"][:15],
        "action",
        "decision_count",
        "治理动作分布",
    )

    page_header("审核效率")
    moderation = result["moderation"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("任务总数", moderation["total_tasks"])
    col2.metric("已完成任务", moderation["completed_tasks"])
    col3.metric("P50 耗时（秒）", moderation["p50_seconds"] or "—")
    col4.metric("P90 耗时（秒）", moderation["p90_seconds"] or "—")
    st.caption(
        "耗时为 moderation_case.opened_at → closed_at 的任务关闭耗时，"
        "来源于合成快照，不代表人工审核耗时。"
    )
    dataframe(result["moderation_by_status"])

    page_header("模拟处置")
    if result["enforcement"]:
        dataframe(result["enforcement"])
    else:
        st.info("当前筛选条件下没有模拟处置记录。")

    page_header("误杀与漏判")
    confusion = result["observed_confusion"]
    st.caption(
        "仅覆盖 risk_result 已落库的消息（合成 ground truth 对照），"
        f"样本量 {confusion['samples']}；governance_feedback 为 0，线上误杀/漏判不可计算。"
    )
    st.json(confusion)
