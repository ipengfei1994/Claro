"""Enforcement Center: simulated enforcement records, player state and expiry."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.charts import action_bar, donut_chart
from claro.ui.common import (
    TARGET_TYPE_LABELS,
    action_text,
    current_actor,
    fmt_dt,
    fmt_duration,
    page_header,
    require,
    status_text,
)

_ENFORCEMENT_ACTIONS = ["warn", "block", "mute", "temp_ban", "perm_ban"]


def render(container: AppContainer) -> None:
    service = require(container.enforcement_service, "EnforcementService")
    actor = current_actor()
    st.title("Enforcement Center")
    st.caption("处置模拟引擎 · 所有处置均为平台内部模拟，不会触达真实游戏服务")

    stats = (
        container.governance_repository.governance_stats()
        if container.governance_repository
        else {}
    )
    by_status = stats.get("enforcement_by_status", {})
    by_action = stats.get("enforcement_by_action", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("处置记录总数", sum(by_status.values()))
    c2.metric("已执行", by_status.get("executed", 0))
    c3.metric("失败", by_status.get("failed", 0))
    c4.metric("已到期/解除", by_status.get("expired", 0) + by_status.get("released", 0))

    col_left, col_right = st.columns(2)
    with col_left:
        if by_action:
            st.plotly_chart(
                action_bar(by_action, title="处置类型分布", height=260), width="stretch"
            )
        else:
            st.info("暂无处置类型分布数据。")
    with col_right:
        if by_status:
            st.plotly_chart(
                donut_chart(
                    [status_text(k) for k in by_status],
                    list(by_status.values()),
                    title="处置状态分布",
                    height=260,
                ),
                width="stretch",
            )
        else:
            st.info("暂无处置状态分布数据。")

    tabs = st.tabs(["处置记录", "玩家模拟状态", "手动处置模拟", "到期与解除"])
    with tabs[0]:
        _render_records(service)
    with tabs[1]:
        _render_player_states(service)
    with tabs[2]:
        _render_manual(service, actor)
    with tabs[3]:
        _render_expiry(service, actor)


def _render_records(service: Any) -> None:
    page_header("历史处置记录", "所有记录 simulated = true。")
    records = service.get_enforcement_history(limit=300)
    if not records:
        st.info("暂无处置记录。")
        return
    st.dataframe(
        [
            {
                "时间": fmt_dt(item["executed_at"] or item["created_at"]),
                "动作": action_text(item["action_type"]),
                "对象类型": TARGET_TYPE_LABELS.get(item["target_type"], item["target_type"]),
                "对象": item["target_ref"],
                "服务器": item["server_ref"] or "—",
                "状态": status_text(item["status"]),
                "时长": fmt_duration(item["duration_seconds"]),
                "到期": fmt_dt(item["expires_at"]),
                "模拟": "是" if item["simulated"] else "否",
                "理由": item["reason"],
            }
            for item in records
        ],
        hide_index=True,
        width="stretch",
        height=420,
    )
    st.caption(f"共 {len(records)} 条记录")


def _render_player_states(service: Any) -> None:
    page_header("玩家模拟状态", "禁言/封禁状态仅存在于平台内部模拟。")
    player_ref = st.text_input("按玩家标识查询", placeholder="player-0001", key="en_player_query")
    if st.button("查询状态", key="en_player_query_btn"):
        if not player_ref.strip():
            st.warning("请输入玩家标识。")
        else:
            state = service.get_player_enforcement_state(player_ref.strip(), fresh=True)
            summary = service.is_player_restricted(player_ref.strip())
            col1, col2, col3 = st.columns(3)
            col1.metric("受限制", "是" if summary["restricted"] else "否")
            col2.metric("禁言中", "是" if summary["muted"] else "否")
            col3.metric("封禁中", "是" if summary["banned"] else "否")
            if state:
                st.json(state)
            else:
                st.info("该玩家当前无模拟状态记录。")

    st.divider()
    states = service.list_player_states(limit=200)
    if not states:
        st.info("暂无玩家模拟状态记录。")
        return
    st.dataframe(
        [
            {
                "玩家": item["player_ref"],
                "作用范围": item["scope_ref"],
                "服务器": item["server_ref"] or "—",
                "禁言到期": fmt_dt(item["mute_until"]),
                "封禁到期": fmt_dt(item["ban_until"]),
                "永久封禁": "是" if item["permanent_ban"] else "否",
                "警告次数": item["warn_count"],
                "更新时间": fmt_dt(item["updated_at"]),
            }
            for item in states
        ],
        hide_index=True,
        width="stretch",
        height=380,
    )


def _render_manual(service: Any, actor: dict[str, str]) -> None:
    page_header("手动处置模拟", "为指定决策模拟一次平台内处置；重复处置由幂等键保护。")
    st.info(
        "处置动作：WARN 生成警告；BLOCK 将消息标记为不可展示；"
        "MUTE/TEMP_BAN/PERM_BAN 写入玩家模拟状态。"
    )
    with st.form("en_manual_form"):
        decision_id = st.text_input("决策 ID (decision_id)", placeholder="UUID")
        c1, c2 = st.columns(2)
        action = c1.selectbox("处置动作", _ENFORCEMENT_ACTIONS, key="en_action")
        target_type = c2.selectbox("对象类型", list(TARGET_TYPE_LABELS), key="en_target_type")
        target_ref = st.text_input("处置对象", placeholder="消息 ID 或玩家标识")
        c3, c4 = st.columns(2)
        duration_seconds = c3.number_input(
            "时长（秒，0 表示永久/不适用）", min_value=0, value=3600, step=300
        )
        scope_ref = c4.text_input("作用范围（可选，默认 *）", placeholder="*")
        reason = st.text_area("处置理由（必填）", height=80, key="en_reason")
        force_failure = st.checkbox("模拟执行失败（用于验证失败记录）")
        confirm = st.checkbox("我确认仅在平台内部模拟该处置")
        submitted = st.form_submit_button("执行模拟处置", type="primary")
    if not submitted:
        return
    try:
        if not confirm:
            raise ValueError("请勾选确认后再执行")
        if not decision_id.strip() or not target_ref.strip():
            raise ValueError("决策 ID 与处置对象不能为空")
        if len(reason.strip()) < 3:
            raise ValueError("处置理由至少 3 个字符")
        result = service.simulate_enforcement(
            decision_id=UUID(decision_id.strip()),
            action=action,
            target_ref=target_ref.strip(),
            reason=reason.strip(),
            actor_ref=actor["ref"],
            target_type=target_type,
            duration_seconds=int(duration_seconds) or None,
            scope_ref=scope_ref.strip() or None,
            force_failure=force_failure,
        )
        st.success(
            f"处置记录已写入：{action_text(result['action_type'])} → "
            f"状态 {status_text(result['status'])}"
        )
        st.json(result)
    except Exception as error:  # noqa: BLE001
        st.error(f"处置模拟失败：{error}")


def _render_expiry(service: Any, actor: dict[str, str]) -> None:
    page_header("到期扫描与解除", "到期处置自动标记为 expired；解除记录 released。")
    c1, c2 = st.columns(2)
    if c1.button("扫描到期处置", key="en_expire_btn"):
        try:
            count = service.expire_due_enforcements(limit=500)
            st.success(f"本次扫描到期处置 {count} 条")
        except Exception as error:  # noqa: BLE001
            st.error(f"扫描失败：{error}")

    with c2.form("en_release_form"):
        enforcement_id = st.text_input("处置记录 ID", placeholder="UUID")
        release_reason = st.text_input("解除理由")
        confirm = st.checkbox("我确认解除该模拟处置")
        if st.form_submit_button("解除处置"):
            try:
                if not confirm:
                    raise ValueError("请勾选确认后再解除")
                if not enforcement_id.strip() or len(release_reason.strip()) < 3:
                    raise ValueError("处置 ID 与解除理由（≥3 字）必填")
                result = service.release_enforcement(
                    UUID(enforcement_id.strip()),
                    actor_ref=actor["ref"],
                    reason=release_reason.strip(),
                )
                st.success(f"处置已解除：{status_text(result.get('status'))}")
            except Exception as error:  # noqa: BLE001
                st.error(f"解除失败：{error}")
