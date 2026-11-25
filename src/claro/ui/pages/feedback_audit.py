"""Feedback & Audit: human feedback, error analysis and the append-only audit trail."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.charts import bar_chart, donut_chart
from claro.ui.common import (
    FEEDBACK_LABELS,
    current_actor,
    fmt_dt,
    fmt_score,
    page_header,
    require,
)

_FEEDBACK_TYPES = list(FEEDBACK_LABELS)


def render(container: AppContainer) -> None:
    service = require(container.feedback_audit_service, "FeedbackAuditService")
    actor = current_actor()
    st.title("Feedback & Audit")
    st.caption("反馈与审计 · 误杀漏判记录、决策覆盖与追加式审计日志")

    stats = service.feedback_stats()
    total = stats.get("total", 0)
    correct_rate = stats.get("correct_rate")
    fp_rate = stats.get("false_positive_rate")
    fn_rate = stats.get("false_negative_rate")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("反馈总数", total)
    c2.metric("识别正确率", _pct(correct_rate))
    c3.metric("误杀率", _pct(fp_rate))
    c4.metric("漏判率", _pct(fn_rate))

    col_left, col_right = st.columns(2)
    with col_left:
        by_type = {FEEDBACK_LABELS.get(k, k): v for k, v in stats.get("by_type", {}).items()}
        if by_type:
            st.plotly_chart(
                donut_chart(
                    list(by_type), list(by_type.values()), title="反馈类型分布", height=280
                ),
                width="stretch",
            )
        else:
            st.info("暂无反馈类型分布数据。")
    with col_right:
        breakdown = service.error_breakdown()
        labelled = {FEEDBACK_LABELS.get(k, k): v for k, v in breakdown.items() if v}
        if labelled:
            st.plotly_chart(
                bar_chart(
                    list(labelled), list(labelled.values()), title="错误类型分布", height=280
                ),
                width="stretch",
            )
        else:
            st.info("暂无错误案例。")

    tabs = st.tabs(["人工反馈", "误杀与漏判", "决策覆盖", "审计日志"])
    with tabs[0]:
        _render_feedback(service, actor)
    with tabs[1]:
        _render_errors(service)
    with tabs[2]:
        _render_overrides(container)
    with tabs[3]:
        _render_audit(service)


def _render_feedback(service: Any, actor: dict[str, str]) -> None:
    page_header("反馈提交", "反馈保留原始模型预测与人工最终结果，用于错误分析。")
    with st.form("fa_feedback_form"):
        message_id = st.text_input("消息 ID (message_id)", placeholder="UUID")
        c1, c2 = st.columns(2)
        decision_id = c1.text_input("决策 ID（可选）", placeholder="UUID")
        review_id = c2.text_input("审核记录 ID（可选）", placeholder="UUID")
        feedback_type = st.selectbox("反馈类型", _FEEDBACK_TYPES, key="fa_feedback_type")
        difference_reason = st.text_area("差异原因（必填）", height=80, key="fa_diff_reason")
        confirm = st.checkbox("我确认提交该反馈")
        if st.form_submit_button("提交反馈", type="primary"):
            try:
                if not confirm:
                    raise ValueError("请勾选确认后再提交")
                if not message_id.strip():
                    raise ValueError("消息 ID 必填")
                if len(difference_reason.strip()) < 3:
                    raise ValueError("差异原因至少 3 个字符")
                result = service.submit_feedback(
                    message_id=UUID(message_id.strip()),
                    feedback_type=feedback_type,
                    difference_reason=difference_reason.strip(),
                    reviewer_ref=actor["ref"],
                    decision_id=UUID(decision_id.strip()) if decision_id.strip() else None,
                    review_id=UUID(review_id.strip()) if review_id.strip() else None,
                )
                label = "（错误案例）" if result.get("is_error_case") else ""
                st.success(f"反馈已提交{label}")
            except Exception as error:  # noqa: BLE001
                st.error(f"提交失败：{error}")

    st.divider()
    page_header("反馈记录")
    rows = service.get_feedback(limit=200)
    if not rows:
        st.info("暂无反馈记录。")
        return
    st.dataframe(
        [
            {
                "时间": fmt_dt(item["created_at"]),
                "类型": FEEDBACK_LABELS.get(item["feedback_type"], item["feedback_type"]),
                "审核人": item["reviewer_ref"],
                "审核记录": str(item.get("review_id") or "")[:8],
                "原始风险分": fmt_score((item.get("original_risk") or {}).get("risk_score")),
                "策略版本": item.get("policy_version"),
                "模型版本": item.get("model_version"),
                "差异原因": item["difference_reason"],
                "消息": item["message_id"][:8],
            }
            for item in rows
        ],
        hide_index=True,
        width="stretch",
        height=320,
    )


def _render_errors(service: Any) -> None:
    page_header("误杀与漏判", "false_positive 为误杀，false_negative 为漏判。")
    filter_type = st.selectbox(
        "错误类型", ["全部", *list(service.error_breakdown())], key="fa_error_filter"
    )
    cases = service.get_error_cases(
        feedback_type=None if filter_type == "全部" else filter_type, limit=200
    )
    if not cases:
        st.info("暂无错误案例。")
        return
    st.dataframe(
        [
            {
                "时间": fmt_dt(item["created_at"]),
                "类型": FEEDBACK_LABELS.get(item["feedback_type"], item["feedback_type"]),
                "审核人": item["reviewer_ref"],
                "原始预测": item.get("original_prediction"),
                "原始风险": item.get("original_risk"),
                "人工最终": item.get("final_risk"),
                "差异原因": item["difference_reason"],
            }
            for item in cases
        ],
        hide_index=True,
        width="stretch",
        height=360,
    )


def _render_overrides(container: AppContainer) -> None:
    page_header("决策覆盖记录", "人工覆盖系统判断的记录，来自审计日志与决策状态。")
    repository = require(container.governance_repository, "GovernanceRepository")
    decisions = repository.list_decisions(status="overridden", limit=200)
    if not decisions:
        st.info("暂无决策覆盖记录。")
        return
    st.dataframe(
        [
            {
                "时间": fmt_dt(item["decided_at"]),
                "决策人": item["decided_by"],
                "动作": item["action"],
                "风险分": fmt_score(item["risk_score"]),
                "覆盖理由": item["decision_reason"],
                "消息": item["message_id"][:8],
            }
            for item in decisions
        ],
        hide_index=True,
        width="stretch",
    )


def _render_audit(service: Any) -> None:
    page_header("审计日志", "追加式记录：界面不提供修改或删除审计记录的能力。")
    f1, f2 = st.columns(2)
    entity_type = f1.text_input(
        "资源类型（可选）",
        placeholder="policy / policy_decision / moderation_case",
        key="fa_entity",
    )
    action = f2.text_input("动作（可选）", placeholder="policy.created", key="fa_action")
    rows = service.get_audit_logs(
        entity_type=entity_type.strip() or None, action=action.strip() or None, limit=300
    )
    if not rows:
        st.info("暂无审计记录。")
        return
    st.dataframe(
        [
            {
                "时间": fmt_dt(item["created_at"]),
                "操作": item["action"],
                "资源": item["entity_type"],
                "资源ID": item["entity_id"][:8],
                "操作人": item["actor_ref"],
                "角色": item["actor_role"],
                "理由": item["reason"],
            }
            for item in rows
        ],
        hide_index=True,
        width="stretch",
        height=420,
    )
    labels = [
        f"{fmt_dt(item['created_at'])} · {item['action']} · {item['entity_id'][:8]}"
        for item in rows
    ]
    chosen = st.selectbox("查看审计详情（变更前后状态）", labels, key="fa_audit_select")
    st.json(rows[labels.index(chosen)])


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)
