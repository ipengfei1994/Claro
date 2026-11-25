"""Strategy evaluation and isolated replay playground."""

from __future__ import annotations

from typing import Any
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


def _rate_cell(entry: dict[str, Any], key: str) -> str:
    """Render a gated rate as value or an explicit unavailable marker."""
    value = entry.get(key)
    if isinstance(value, dict):
        if value.get("value") is None:
            return "不可计算"
        return f"{value['value']:.3f}"
    return "不可计算" if value is None else f"{value:.3f}"


def render(container: AppContainer) -> None:
    page_header("Strategy Evaluation", "策略效果评估、版本对比与历史数据回放。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_strategy")
    result = service.strategy(filters)
    render_banner(result)

    ranking = [row for row in result["policies"] if row["evaluated_messages"] > 0]
    page_header("策略命中分析")
    st.caption(
        "命中数仅说明策略被触发过多少次，不代表治理效果。"
        "下表同时给出识别质量、误杀风险、漏判风险与人工审核负载。"
    )
    if ranking:
        for row in ranking:
            row["hit_rate_display"] = _rate_cell(row, "hit_rate")
            row["automatic_action_display"] = _rate_cell(row, "automatic_action_rate")
            row["manual_review_display"] = _rate_cell(row, "manual_review_rate")
            row["precision_display"] = (
                "不可计算" if row["precision"] is None else f"{row['precision']:.3f}"
            )
            row["recall_display"] = (
                "不可计算" if row["recall"] is None else f"{row['recall']:.3f}"
            )
            row["fpr_display"] = (
                "不可计算"
                if row["false_positive_rate"] is None
                else f"{row['false_positive_rate']:.3f}"
            )
            row["fnr_display"] = (
                "不可计算"
                if row["false_negative_rate"] is None
                else f"{row['false_negative_rate']:.3f}"
            )
        bar_chart(ranking[:20], "policy_key", "replay_hit_messages", "策略命中消息数")
        dataframe(
            [
                {
                    "策略": row["policy_key"],
                    "命中消息": row["replay_hit_messages"],
                    "命中率": row["hit_rate_display"],
                    "自动执行": row["automatic_action_display"],
                    "人工审核占比": row["manual_review_display"],
                    "Precision": row["precision_display"],
                    "Recall": row["recall_display"],
                    "误杀率": row["fpr_display"],
                    "漏判率": row["fnr_display"],
                    "质量样本": row["quality_sample_size"],
                }
                for row in ranking
            ]
        )
        summary = result["quality_summary"]
        st.info(
            f"{summary['policies_with_quality_data']} / {summary['policies_total']} 条策略"
            f"具备质量样本（需 ≥ {summary['min_samples']}）。{summary['note']}"
        )
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
            pool = item.get("sample_pool") or {}
            st.caption(
                f"回放样本池：{pool.get('definition', '—')} · "
                f"含风险事件 {pool.get('with_risk_event', '—')} · "
                f"无风险事件 {pool.get('without_risk_event', '—')} · "
                f"真阳性 {pool.get('truth_positives', '—')} · "
                f"真阴性 {pool.get('truth_negatives', '—')}"
            )
            st.json({"baseline": item["baseline"], "candidate": item["candidate"]})
            st.json(item["differences"])
            if item["low_sample"]:
                st.warning("样本数低于 100，结果仅作探索性参考。")
            page_header("逐策略效果对比（基线 vs 候选）")
            st.caption(
                "每条策略独立统计：命中数高不代表效果好，需同时看误杀率、漏判率与人工审核占比。"
            )
            baseline_rows = {
                row["policy_key"]: row for row in item["baseline"].get("policy_effectiveness", [])
            }
            candidate_rows = {
                row["policy_key"]: row
                for row in item["candidate"].get("policy_effectiveness", [])
            }
            comparison_rows = []
            for key in sorted(
                set(baseline_rows) | set(candidate_rows),
                key=lambda k: -(baseline_rows.get(k, candidate_rows.get(k))["hit_messages"]),
            ):
                base = baseline_rows.get(key, {})
                cand = candidate_rows.get(key, {})
                comparison_rows.append(
                    {
                        "策略": key,
                        "基线命中": base.get("hit_messages", 0),
                        "候选命中": cand.get("hit_messages", 0),
                        "基线Precision": (
                            "不可计算"
                            if base.get("precision") is None
                            else f"{base['precision']:.3f}"
                        ),
                        "候选Precision": (
                            "不可计算"
                            if cand.get("precision") is None
                            else f"{cand['precision']:.3f}"
                        ),
                        "基线误杀率": (
                            "不可计算"
                            if base.get("false_positive_rate") is None
                            else f"{base['false_positive_rate']:.3f}"
                        ),
                        "候选误杀率": (
                            "不可计算"
                            if cand.get("false_positive_rate") is None
                            else f"{cand['false_positive_rate']:.3f}"
                        ),
                        "基线漏判率": (
                            "不可计算"
                            if base.get("false_negative_rate") is None
                            else f"{base['false_negative_rate']:.3f}"
                        ),
                        "候选漏判率": (
                            "不可计算"
                            if cand.get("false_negative_rate") is None
                            else f"{cand['false_negative_rate']:.3f}"
                        ),
                        "基线审核占比": (
                            "不可计算"
                            if base.get("manual_review_rate") is None
                            else f"{base['manual_review_rate']:.3f}"
                        ),
                        "候选审核占比": (
                            "不可计算"
                            if cand.get("manual_review_rate") is None
                            else f"{cand['manual_review_rate']:.3f}"
                        ),
                    }
                )
            dataframe(comparison_rows, height=420)
            dataframe(comparison["cases"][:100])
    st.caption("回放只读历史消息与策略快照；不触发处置、不修改正式决策，结果标记为 Simulation。")
