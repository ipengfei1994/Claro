"""Governance Decisions: decision distribution, history and explainability."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.charts import action_bar, donut_chart
from claro.ui.common import (
    action_text,
    current_actor,
    fmt_dt,
    fmt_score,
    page_header,
    require,
    status_text,
)

_DECISION_STATUSES = ["auto_decided", "pending_review", "human_reviewed", "overridden", "cancelled"]
_DECISION_ACTIONS = [
    "allow",
    "warn",
    "flag",
    "review",
    "block",
    "mute",
    "temp_ban",
    "perm_ban",
]


def render(container: AppContainer) -> None:
    service = require(container.governance_decision_service, "GovernanceDecisionService")
    actor = current_actor()
    st.title("Governance Decisions")
    st.caption("治理决策 · 自动决策与人工审核分流、动作分布与决策解释")

    stats = (
        container.governance_repository.governance_stats()
        if container.governance_repository
        else {}
    )
    by_status = stats.get("decisions_by_status", {})
    by_action = {k: v for k, v in stats.get("decisions_by_action", {}).items()}
    auto = by_status.get("auto_decided", 0)
    pending = by_status.get("pending_review", 0)
    human = by_status.get("human_reviewed", 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("自动决策", auto)
    c2.metric("待人工审核", pending)
    c3.metric("人工已审", human)
    c4.metric("决策总数", sum(by_status.values()))

    col_left, col_right = st.columns(2)
    with col_left:
        if by_action:
            st.plotly_chart(
                action_bar(by_action, title="治理动作分布", height=280), width="stretch"
            )
        else:
            st.info("暂无决策动作分布数据。")
    with col_right:
        if by_status:
            labels = [status_text(k) for k in by_status]
            st.plotly_chart(
                donut_chart(labels, list(by_status.values()), title="决策状态分布", height=280),
                width="stretch",
            )
        else:
            st.info("暂无决策状态分布数据。")

    page_header("决策历史", "按状态、动作与是否需人工审核筛选。")
    f1, f2, f3 = st.columns([1, 1, 2])
    status_filter = f1.selectbox("状态", ["全部", *_DECISION_STATUSES], key="gd_status")
    action_filter = f2.selectbox(
        "动作",
        ["全部", "allow", "warn", "flag", "review", "block", "mute", "temp_ban", "perm_ban"],
        key="gd_action",
    )
    review_filter = f3.selectbox("是否需人工审核", ["全部", "需要", "不需要"], key="gd_review")

    decisions = service.list_decisions(
        status=None if status_filter == "全部" else status_filter,
        action=None if action_filter == "全部" else action_filter,
        requires_review=None if review_filter == "全部" else review_filter == "需要",
        limit=300,
    )
    if not decisions:
        st.info("当前筛选条件下没有决策记录。")
        return
    st.dataframe(
        [
            {
                "时间": fmt_dt(item["decided_at"]),
                "动作": action_text(item["action"]),
                "状态": status_text(item["decision_status"]),
                "风险分": fmt_score(item["risk_score"]),
                "置信度": fmt_score(item["confidence"]),
                "需审核": "是" if item["requires_review"] else "否",
                "优先级": item["priority"],
                "决策人": item["decided_by"],
                "理由": item["decision_reason"],
                "消息": item["message_id"][:8],
            }
            for item in decisions
        ],
        hide_index=True,
        width="stretch",
        height=340,
    )

    labels = [
        f"{fmt_dt(item['decided_at'])} · {action_text(item['action'])} · {item['id'][:8]}"
        for item in decisions
    ]
    chosen = st.selectbox("查看决策解释", labels, key="gd_explain_select")
    _render_explanation(service, decisions[labels.index(chosen)], actor)


def _render_explanation(service: Any, decision: dict[str, Any], actor: dict[str, str]) -> None:
    st.divider()
    page_header("决策解释", "回答为什么采取该动作、哪些风险与策略影响决策。")
    try:
        explanation = service.explain_decision(UUID(decision["id"]))
    except Exception as error:  # noqa: BLE001
        st.error(f"读取决策解释失败：{error}")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最终动作", action_text(explanation["action"]))
    c2.metric("状态", status_text(explanation["decision_status"]))
    c3.metric("置信度", fmt_score(explanation["confidence"]))
    c4.metric("是否需审核", "是" if explanation["requires_review"] else "否")
    st.markdown(f"**决策理由**：{explanation['decision_reason']}")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**证据**")
        st.json(explanation.get("evidence") or {})
        if explanation.get("review_trigger"):
            st.markdown("**人工审核触发原因**")
            st.info(explanation["review_trigger"])
    with col_right:
        st.markdown("**命中的策略**")
        st.json(explanation.get("policy") or {})
        if explanation.get("alternatives"):
            st.markdown("**其他候选动作及被否决原因**")
            st.json(explanation["alternatives"])

    if actor["role"] != "admin":
        st.caption("决策覆盖需要管理员身份（当前为模拟身份切换）。")
        return
    with st.expander("覆盖决策（管理员操作，写入审核与审计记录）"):
        st.warning(
            "覆盖会修改决策状态、写入人工审核记录，并保留原始风险结果与系统动作；此操作同时进入追加式审计日志。"
        )
        reason = st.text_area("覆盖原因（必填）", key="gd_override_reason", height=80)
        c1, c2 = st.columns(2)
        target_status = c1.selectbox(
            "目标状态", ["overridden", "cancelled"], key="gd_override_status"
        )
        target_action = c2.selectbox(
            "人工最终动作",
            ["保持系统动作", *_DECISION_ACTIONS],
            key="gd_override_action",
        )
        confirm = st.checkbox("我确认覆盖该决策", key="gd_override_confirm")
        if st.button("提交决策覆盖", key="gd_override_btn"):
            try:
                if not confirm:
                    raise ValueError("请勾选确认后再覆盖")
                if len(reason.strip()) < 3:
                    raise ValueError("覆盖原因至少 3 个字符")
                result = service.override_decision(
                    UUID(decision["id"]),
                    actor_ref=actor["ref"],
                    actor_role=actor["role"],
                    reason=reason.strip(),
                    action=None if target_action == "保持系统动作" else target_action,
                    status=target_status,
                )
                st.success(
                    f"决策已覆盖为 {status_text(result.get('decision_status'))}；"
                    f"审核记录 {str(result.get('review_id'))[:8]}"
                )
                st.rerun()
            except Exception as error:  # noqa: BLE001
                st.error(f"覆盖失败：{error}")
