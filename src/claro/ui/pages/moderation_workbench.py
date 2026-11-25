"""Moderation Workbench: queue, case detail and human review actions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.charts import severity_bar
from claro.ui.common import (
    FEEDBACK_LABELS,
    MODERATION_ACTION_LABELS,
    action_text,
    current_actor,
    fmt_dt,
    fmt_score,
    page_header,
    require,
    severity_text,
    status_text,
)
from claro.ui.theme import badge

_OPEN_STATUSES = ["pending", "in_review", "escalated", "second_review"]
_STATUS_OPTIONS = [
    "pending",
    "in_review",
    "escalated",
    "second_review",
    "approved",
    "rejected",
    "resolved",
    "finalized",
]
_REVIEW_ACTIONS = ["approve", "reject", "override", "escalate", "request_second_review", "reopen"]
_FINAL_ACTIONS = ["allow", "warn", "flag", "review", "block", "mute", "temp_ban", "perm_ban"]
_RISK_LEVELS = ["critical", "high", "medium", "low", "normal"]


def render(container: AppContainer) -> None:
    service = require(container.moderation_service, "ModerationService")
    actor = current_actor()
    st.title("Moderation Workbench")
    st.caption("人工审核工作台 · 队列、状态机与审核操作（角色为模拟身份）")

    stats = (
        container.governance_repository.governance_stats()
        if container.governance_repository
        else {}
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待审核任务", stats.get("open_cases", 0))
    c2.metric("超时任务", stats.get("overdue_cases", 0))
    c3.metric("审核操作总数", stats.get("reviews", 0))
    c4.metric("当前身份", actor["label"])

    page_header("审核队列", "按风险等级、状态、负责人与关键词筛选；点击行查看详情。")
    filters = st.columns([1, 1, 1, 1, 2])
    status_filter = filters[0].selectbox(
        "状态", ["全部", *_STATUS_OPTIONS], index=0, key="mw_status"
    )
    level_filter = filters[1].selectbox(
        "风险等级", ["全部", *_RISK_LEVELS], index=0, key="mw_level"
    )
    assignee_filter = filters[2].selectbox("负责人", ["全部", "未分配"], index=0, key="mw_assignee")
    overdue_filter = filters[3].checkbox("仅看超时", key="mw_overdue")
    search = filters[4].text_input("搜索（内容 / 玩家）", key="mw_search").strip()

    statuses = None
    if status_filter == "全部":
        statuses = st.session_state.get("mw_statuses") or list(_OPEN_STATUSES)
    else:
        statuses = [status_filter]
    assignee = None
    if assignee_filter == "未分配":
        assignee = "unassigned"

    cases = service.queue(
        statuses=statuses,
        assignee=assignee,
        risk_level=None if level_filter == "全部" else level_filter,
        overdue=overdue_filter,
        search=search or None,
        limit=300,
    )
    if not cases:
        st.info("当前筛选条件下没有审核任务。")
        return

    level_counts: dict[str, int] = {}
    for case in cases:
        key = str(case.get("risk_level") or "unknown")
        level_counts[key] = level_counts.get(key, 0) + 1
    col_chart, col_table = st.columns([1, 2])
    with col_chart:
        st.plotly_chart(
            severity_bar(level_counts, title="队列风险分布", height=260), width="stretch"
        )
    rows = [
        {
            "优先级": case["priority"],
            "风险": severity_text(case.get("risk_level")),
            "状态": status_text(case["status"]),
            "建议动作": action_text(case.get("suggested_action")),
            "玩家": case["sender_ref"],
            "服务器": case["server_ref"],
            "内容": _short(case.get("content")),
            "负责": case.get("assignee_ref") or "未分配",
            "超时": "是" if case.get("overdue") else "否",
            "开启时间": fmt_dt(case.get("opened_at")),
        }
        for case in cases
    ]
    with col_table:
        event = st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            height=300,
            on_select="rerun",
            selection_mode="single-row",
            key="mw_queue",
        )
    selected_rows = event.selection.rows if hasattr(event, "selection") else []
    default_index = selected_rows[0] if selected_rows else 0
    labels = [
        f"{case['priority']} · {severity_text(case.get('risk_level'))} · "
        f"{case['sender_ref']} · {case['case_id'][:8]}"
        for case in cases
    ]
    chosen = st.selectbox("选择任务", labels, index=default_index, key="mw_case_select")
    case = cases[labels.index(chosen)]
    _render_detail(service, container, UUID(case["case_id"]), actor)


def _render_detail(
    service: Any, container: AppContainer, case_id: UUID, actor: dict[str, str]
) -> None:
    st.divider()
    try:
        detail = service.detail(case_id)
    except Exception as error:  # noqa: BLE001
        st.error(f"读取审核详情失败：{error}")
        return

    case = detail["case"]
    decision = detail.get("decision") or {}
    evaluation = detail.get("evaluation") or {}
    risk = detail.get("risk") or {}
    message = detail.get("message") or {}

    top = st.columns([3, 1, 1, 1])
    top[0].markdown(f"### 审核任务 {case_id}")
    top[0].caption(
        f"状态 {status_text(case.get('status'))} · 优先级 {case.get('priority')} · "
        f"需二次复核 {'是' if case.get('required_second_review') else '否'} · "
        f"锁版本 v{case.get('lock_version')}"
    )
    top[1].metric("风险等级", severity_text(case.get("risk_level")))
    top[2].metric("风险分", fmt_score(case.get("risk_score")))
    top[3].metric("建议动作", action_text(case.get("suggested_action")))

    left, right = st.columns(2)
    with left:
        page_header("消息与玩家")
        st.markdown("**原始消息**")
        st.code(message.get("content", "—"), language=None)
        st.caption(
            f"归一化哈希 {message.get('content_hash', '—')} · 频道 {message.get('channel')} · "
            f"语言 {message.get('language')} · 发生时间 {fmt_dt(message.get('occurred_at'))}"
        )
        st.markdown("**玩家信息**")
        st.json(
            {
                "sender_ref": message.get("sender_ref"),
                "server_ref": message.get("server_ref"),
                "alliance_id": message.get("alliance_id"),
                "player_id": message.get("player_id"),
                "channel": message.get("channel"),
            }
        )
        history = risk.get("evidence", {}).get("risk_history") if risk else None
        if history:
            st.markdown("**玩家历史风险**")
            st.json(history)

        page_header("风险识别结果")
        risk_level_text = str(risk.get("risk_level"))
        st.markdown(
            f"等级 {badge(severity_text(risk_level_text), severity=risk_level_text)}"
        )
        st.caption(
            f"风险分 {fmt_score(risk.get('risk_score'))} · "
            f"置信度 {fmt_score(risk.get('confidence'))} · "
            f"检测方法 {', '.join(risk.get('detection_methods', [])) or '—'} · "
            f"模型 {risk.get('model_id') or '—'}"
        )
        categories = risk.get("categories") or []
        if categories:
            st.markdown("**风险类别**")
            st.dataframe(categories, hide_index=True, width="stretch")
        if risk.get("evidence"):
            st.markdown("**风险证据**")
            st.json(risk["evidence"])
        if risk.get("explanation"):
            with st.expander("模型解释"):
                st.json(risk["explanation"])

    with right:
        page_header("策略与决策")
        if decision:
            st.caption(
                f"决策动作 {action_text(decision.get('action'))} · "
                f"状态 {status_text(decision.get('decision_status'))} · "
                f"置信度 {fmt_score(decision.get('confidence'))} · "
                f"需人工审核 {'是' if decision.get('requires_review') else '否'}"
            )
            st.markdown(f"**系统理由**：{decision.get('decision_reason') or '—'}")
            explanation = decision.get("explanation") or {}
            if explanation.get("alternatives"):
                st.markdown("**被否决的候选动作**")
                st.json(explanation["alternatives"])
        if evaluation:
            st.markdown("**命中策略**")
            st.dataframe(
                [
                    {
                        "策略": item.get("policy_key"),
                        "动作": action_text(item.get("action")),
                        "优先级": item.get("priority"),
                        "版本": item.get("version"),
                    }
                    for item in evaluation.get("matched_policies", [])
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(f"评估理由：{evaluation.get('evaluation_reason') or '—'}")
            if evaluation.get("conflicts"):
                st.markdown("**策略冲突**")
                st.json(evaluation["conflicts"])

        st.markdown("**历史审核记录**")
        reviews = detail.get("reviews") or []
        if reviews:
            st.dataframe(
                [
                    {
                        "时间": fmt_dt(item["created_at"]),
                        "审核人": item["reviewer_ref"],
                        "角色": item["reviewer_role"],
                        "操作": MODERATION_ACTION_LABELS.get(item["action"], item["action"]),
                        "理由": item["reason"],
                        "状态变更": (
                            f"{status_text(item.get('from_status'))} → "
                            f"{status_text(item.get('to_status'))}"
                        ),
                    }
                    for item in reviews
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("尚无审核记录。")
        with st.expander("案件事件流"):
            st.dataframe(detail.get("events") or [], hide_index=True, width="stretch")
        if detail.get("enforcements"):
            with st.expander("关联处置记录"):
                st.dataframe(detail["enforcements"], hide_index=True, width="stretch")
        if detail.get("feedback"):
            with st.expander("关联反馈"):
                st.dataframe(detail["feedback"], hide_index=True, width="stretch")

    _render_actions(service, detail, actor)


def _render_actions(service: Any, detail: dict[str, Any], actor: dict[str, str]) -> None:
    st.divider()
    page_header("审核操作", "系统判断与人工判断明确区分；修改系统建议必须填写理由。")
    case = detail.get("case") or {}
    raw_case_id = case.get("case_id") or case.get("id")
    if not raw_case_id:
        st.warning("该审核任务缺少可操作详情（关联消息可能已被清理），请从队列重新选择。")
        return
    case_id = UUID(str(raw_case_id))
    lock_version = case.get("lock_version")

    col_claim, col_hint = st.columns([1, 3])
    if col_claim.button(
        "认领任务", key="mw_claim", disabled=case.get("status") not in _OPEN_STATUSES
    ):
        try:
            service.claim(
                case_id,
                reviewer_ref=actor["ref"],
                reviewer_role=actor["role"],
                expected_lock_version=lock_version,
            )
            st.success("任务已认领")
            st.rerun()
        except Exception as error:  # noqa: BLE001
            st.error(f"认领失败：{error}")
    col_hint.caption(
        "升级与二次复核需高级审核员或管理员角色。二次复核必须由与申请人不同的审核人完成。"
    )

    with st.form("mw_review_form"):
        c1, c2, c3 = st.columns(3)
        action = c1.selectbox("审核操作", _REVIEW_ACTIONS, key="mw_action")
        final_action = c2.selectbox(
            "最终处置建议", ["（不改动）", *_FINAL_ACTIONS], key="mw_final_action"
        )
        final_level = c3.selectbox(
            "最终风险等级", ["（不改动）", *_RISK_LEVELS], key="mw_final_level"
        )
        final_category = st.text_input("最终风险类别（可选）", key="mw_final_category")
        reason = st.text_area("审核理由（必填）", key="mw_reason", height=80)
        notes = st.text_input("备注（可选）", key="mw_notes")
        feedback_type = st.selectbox(
            "反馈类型（可选，用于反馈闭环）",
            ["（不提交）", *FEEDBACK_LABELS],
            key="mw_feedback_type",
        )
        feedback_reason = st.text_input("反馈差异原因（提交反馈时必填）", key="mw_feedback_reason")
        confirm = st.checkbox("我确认提交本次审核（写入状态机与审计日志）")
        submitted = st.form_submit_button("提交审核", type="primary")

    if not submitted:
        return
    try:
        if not confirm:
            raise ValueError("请勾选确认后再提交")
        if len(reason.strip()) < 3:
            raise ValueError("审核理由至少 3 个字符")
        result = service.submit_review(
            case_id,
            reviewer_ref=actor["ref"],
            reviewer_role=actor["role"],
            action=action,
            reason=reason.strip(),
            final_action=final_action if final_action != "（不改动）" else None,
            final_level=final_level if final_level != "（不改动）" else None,
            final_category=final_category.strip() or None,
            notes=notes.strip() or None,
            expected_lock_version=lock_version,
            feedback_type=None if feedback_type == "（不提交）" else feedback_type,
            feedback_difference_reason=feedback_reason.strip() or None,
        )
        st.success(
            f"审核已提交：{MODERATION_ACTION_LABELS.get(action, action)} → "
            f"状态 {status_text(result.get('to_status'))}"
        )
        if result.get("feedback"):
            st.info(f"已提交反馈：{FEEDBACK_LABELS.get(result['feedback']['feedback_type'])}")
        st.rerun()
    except Exception as error:  # noqa: BLE001
        st.error(f"提交失败：{error}")


def _short(value: Any, length: int = 60) -> str:
    text = str(value or "")
    return text if len(text) <= length else text[: length - 1] + "…"
