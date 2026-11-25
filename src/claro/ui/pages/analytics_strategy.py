"""Strategy evaluation and isolated replay playground."""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from claro.bootstrap import AppContainer
from claro.domain.enums import DecisionAction
from claro.ui.analytics_ui import (
    analytics_filters,
    bar_chart,
    dataframe,
    render_banner,
    service_from,
)
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    page_header("Strategy Evaluation", "策略效果评估、版本对比与历史数据回放。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_strategy")
    result = service.strategy(filters)
    render_banner(result)

    ranking = [row for row in result["policies"] if row["evaluated_messages"] > 0]
    page_header("策略命中分析")
    if ranking:
        bar_chart(ranking[:20], "policy_key", "hit_rate", "策略命中率（有评估记录的消息）")
        dataframe(ranking)
    else:
        st.info("当前筛选条件下没有策略评估记录；累计命中计数见 KPI 输出。")
    st.caption(result["version_comparison"]["reason"])

    page_header("Strategy Playground · 隔离回放")
    replay = container.strategy_replay_service
    if replay is None:
        st.error("回放服务不可用。")
        return
    with st.form("analytics_replay_form"):
        sample_limit = st.number_input("样本上限", min_value=10, max_value=5000, value=500, step=10)
        policy_key = st.text_input("候选策略 key（例如 gov-score-070-review）")
        action = st.selectbox("候选动作", [item.value for item in DecisionAction], index=3)
        disabled = st.text_input("候选禁用的策略 key（逗号分隔）")
        candidate_label = st.text_input("候选标签", value="candidate")
        submitted = st.form_submit_button("运行回放")
    if submitted:
        candidate = {
            "action_overrides": {policy_key: action} if policy_key else {},
            "disabled_policies": [item.strip() for item in disabled.split(",") if item.strip()],
            "candidate_label": candidate_label,
        }
        try:
            run = replay.run(
                filters, candidate, sample_limit=int(sample_limit), executed_by="ui"
            )
            st.session_state["_analytics_replay_run_id"] = run["run_id"]
            st.success(f"回放完成：{run['run_id']} · 样本 {run['sample_count']}")
        except ValueError as error:
            st.error(f"回放失败：{error}")

    run_id = st.session_state.get("_analytics_replay_run_id")
    if run_id:
        comparison = replay.compare(UUID(str(run_id)))
        if comparison["runs"]:
            item = comparison["runs"][0]
            st.json({"baseline": item["baseline"], "candidate": item["candidate"]})
            st.json(item["differences"])
            if item["low_sample"]:
                st.warning("样本数低于 100，结果仅作探索性参考。")
            dataframe(comparison["cases"][:100])
    st.caption("回放只读历史消息与策略快照；不触发处置、不修改正式决策，结果标记为 Simulation。")
