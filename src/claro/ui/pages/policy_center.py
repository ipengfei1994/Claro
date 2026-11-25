"""Policy Center: browse, author, version and test governance policies."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.common import (
    POLICY_TYPE_LABELS,
    action_text,
    current_actor,
    fmt_dt,
    page_header,
    require,
)

_POLICY_TYPES = list(POLICY_TYPE_LABELS)
_ACTIONS = ["allow", "warn", "flag", "review", "block", "mute", "temp_ban", "perm_ban"]

_CONDITION_EXAMPLES: dict[str, dict[str, Any]] = {
    "keyword": {"field": "content", "op": "contains", "value": "示例敏感词"},
    "regex": {"field": "content", "op": "regex", "value": "\\d{11}"},
    "risk_threshold": {"field": "risk_score", "op": "gte", "value": 0.85},
    "category": {"field": "category", "op": "in", "value": ["fraud"]},
    "rate_limit": {"field": "rate_count", "op": "gte", "value": 20},
    "composite": {
        "all": [
            {"field": "risk_score", "op": "gte", "value": 0.7},
            {"field": "channel", "op": "eq", "value": "world"},
        ]
    },
    "player": {"field": "sender_ref", "op": "eq", "value": "player-0001"},
    "server": {"field": "server_ref", "op": "eq", "value": "server-1"},
    "alliance": {"field": "alliance_id", "op": "eq", "value": "alliance-0001"},
    "whitelist": {"field": "sender_ref", "op": "eq", "value": "verified-player"},
    "blacklist": {"field": "sender_ref", "op": "eq", "value": "blacklisted-player"},
}


def render(container: AppContainer) -> None:
    service = require(container.policy_service, "PolicyService")
    actor = current_actor()
    st.title("Policy Center")
    st.caption("治理策略中心 · 版本管理、优先级、冲突检测与策略测试")

    counts = container.policy_repository.counts() if container.policy_repository else {}
    col1, col2, col3 = st.columns(3)
    col1.metric("策略总数", counts.get("policies", 0))
    col2.metric("已启用", counts.get("enabled", 0))
    col3.metric("已停用", counts.get("disabled", 0))

    tabs = st.tabs(["策略列表", "新建策略", "编辑与版本", "策略测试", "冲突检测"])
    with tabs[0]:
        _render_list(service)
    with tabs[1]:
        _render_create(service, actor)
    with tabs[2]:
        _render_edit(service, actor)
    with tabs[3]:
        _render_playground(service)
    with tabs[4]:
        _render_conflicts(service)


# --- List -----------------------------------------------------------------
def _render_list(service: Any) -> None:
    page_header("策略清单", "按启用状态、类型与关键词筛选。")
    col1, col2, col3 = st.columns([1, 1, 2])
    type_filter = col1.selectbox("策略类型", ["全部", *_POLICY_TYPES], key="pc_type_filter")
    enabled_filter = col2.selectbox("状态", ["全部", "已启用", "已停用"], key="pc_state_filter")
    keyword = col3.text_input("搜索（名称 / 键）", key="pc_search").strip().casefold()

    policies = service.list_policies(include_disabled=True)
    rows: list[dict[str, Any]] = []
    for item in policies:
        if type_filter != "全部" and item["policy_type"] != type_filter:
            continue
        if enabled_filter == "已启用" and not item["enabled"]:
            continue
        if enabled_filter == "已停用" and item["enabled"]:
            continue
        if keyword and keyword not in item["name"].casefold() and keyword not in item["policy_key"]:
            continue
        rows.append(
            {
                "策略键": item["policy_key"],
                "名称": item["name"],
                "类型": POLICY_TYPE_LABELS.get(item["policy_type"], item["policy_type"]),
                "动作": action_text(item["action"]),
                "优先级": item["priority"],
                "应急": "是" if item["emergency"] else "否",
                "版本": item["version"],
                "命中次数": item["hit_count"],
                "状态": "已启用" if item["enabled"] else "已停用",
                "生效开始": fmt_dt(item["effective_from"]),
                "最近更新": fmt_dt(item["updated_at"]),
            }
        )
    st.caption(f"共 {len(rows)} 条策略")
    st.dataframe(rows, hide_index=True, width="stretch", height=460)


# --- Create ---------------------------------------------------------------
def _render_create(service: Any, actor: dict[str, str]) -> None:
    page_header("新建策略", "条件与作用范围使用结构化 JSON，服务端执行校验。")
    policy_type = st.selectbox("策略类型", _POLICY_TYPES, key="pc_new_type")
    with st.form("pc_create_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        policy_key = col1.text_input("策略键 (policy_key)", placeholder="gov-my-rule")
        name = col2.text_input("策略名称", placeholder="示例治理策略")
        col3, col4, col5 = st.columns(3)
        action = col3.selectbox("治理动作", _ACTIONS, index=_ACTIONS.index("review"))
        priority = col4.number_input("优先级", min_value=0, max_value=10_000, value=500, step=10)
        emergency = col5.checkbox("应急策略", value=False)
        description = st.text_input("描述", placeholder="策略用途说明")
        target_scope_raw = st.text_area(
            "作用范围 (JSON)",
            value=json.dumps(_scope_example(policy_type), ensure_ascii=False, indent=2),
            height=120,
        )
        conditions_raw = st.text_area(
            "条件 (JSON)",
            value=json.dumps(
                _CONDITION_EXAMPLES.get(policy_type, {}), ensure_ascii=False, indent=2
            ),
            height=160,
        )
        change_reason = st.text_input("变更原因", placeholder="创建原因（写入审计日志）")
        submitted = st.form_submit_button("创建策略", type="primary")

    st.caption(
        "提示：keyword/regex 仅作用于 content 字段；risk_threshold 需作用于 risk_score；"
        "composite 使用 all/any 组合多个子条件。"
    )
    if not submitted:
        return
    try:
        target_scope = _parse_json(target_scope_raw, "作用范围")
        conditions = _parse_json(conditions_raw, "条件")
        if not change_reason.strip():
            raise ValueError("必须填写变更原因")
        if not policy_key.strip() or not name.strip():
            raise ValueError("策略键与名称不能为空")
        result = service.create_policy(
            policy_key=policy_key.strip(),
            name=name.strip(),
            description=description.strip(),
            policy_type=policy_type,
            target_scope=target_scope,
            conditions=conditions,
            action=action,
            priority=int(priority),
            emergency=bool(emergency),
            created_by=actor["ref"],
            change_reason=change_reason.strip(),
        )
        st.success(f"策略已创建：{result['policy_key']} (v{result['version']})")
    except Exception as error:  # noqa: BLE001
        st.error(f"创建失败：{error}")


# --- Edit & version -------------------------------------------------------
def _render_edit(service: Any, actor: dict[str, str]) -> None:
    policies = service.list_policies(include_disabled=True)
    if not policies:
        st.info("暂无策略。请先运行 governance-seed-policies 或新建策略。")
        return
    options = {
        f"{item['name']} · {item['policy_key']} (v{item['version']})": item for item in policies
    }
    label = st.selectbox("选择策略", list(options), key="pc_edit_select")
    policy = options[label]
    policy_id = UUID(policy["id"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("当前版本", policy["version"])
    col2.metric("命中次数", policy["hit_count"])
    col3.metric("优先级", policy["priority"])
    col4.metric("状态", "已启用" if policy["enabled"] else "已停用")
    st.caption(
        f"类型 {POLICY_TYPE_LABELS.get(policy['policy_type'], policy['policy_type'])} · "
        f"动作 {action_text(policy['action'])} · 更新人 {policy['updated_by']} · "
        f"{fmt_dt(policy['updated_at'])}"
    )

    toggle_cols = st.columns(2)
    if policy["enabled"]:
        if toggle_cols[0].button("停用策略", key="pc_disable"):
            _toggle(service, policy_id, enabled=False, actor=actor, policy=policy)
    else:
        if toggle_cols[0].button("启用策略", key="pc_enable"):
            _toggle(service, policy_id, enabled=True, actor=actor, policy=policy)

    page_header("调整策略", "修改将生成新版本，历史版本不可覆盖。")
    with st.form("pc_update_form"):
        c1, c2, c3 = st.columns(3)
        new_name = c1.text_input("名称", value=policy["name"])
        new_action = c2.selectbox("动作", _ACTIONS, index=_ACTIONS.index(policy["action"]))
        new_priority = c3.number_input(
            "优先级", min_value=0, max_value=10_000, value=int(policy["priority"]), step=10
        )
        new_emergency = st.checkbox("应急策略", value=bool(policy["emergency"]))
        new_conditions = st.text_area(
            "条件 (JSON)",
            value=json.dumps(policy["conditions"], ensure_ascii=False, indent=2),
            height=160,
        )
        new_scope = st.text_area(
            "作用范围 (JSON)",
            value=json.dumps(policy["target_scope"], ensure_ascii=False, indent=2),
            height=120,
        )
        update_reason = st.text_input("变更原因", placeholder="必填，写入版本与审计")
        confirm = st.checkbox("我确认按当前内容生成新版本")
        if st.form_submit_button("提交变更", type="primary"):
            try:
                if not confirm:
                    raise ValueError("请勾选确认后再提交")
                if not update_reason.strip():
                    raise ValueError("必须填写变更原因")
                result = service.update_policy(
                    policy_id,
                    actor_ref=actor["ref"],
                    reason=update_reason.strip(),
                    expected_version=int(policy["version"]),
                    name=new_name.strip(),
                    action=new_action,
                    priority=int(new_priority),
                    emergency=bool(new_emergency),
                    conditions=_parse_json(new_conditions, "条件"),
                    target_scope=_parse_json(new_scope, "作用范围"),
                )
                st.success(f"已生成新版本 v{result['version']}")
                service.invalidate()
            except Exception as error:  # noqa: BLE001
                st.error(f"更新失败：{error}")

    page_header("版本历史", "回滚会生成新版本，历史版本永久保留。")
    versions = service.versions(policy_id)
    st.dataframe(
        [
            {
                "版本": item["version"],
                "动作": action_text(item["action"]),
                "优先级": item["priority"],
                "启用": "是" if item["enabled"] else "否",
                "变更原因": item["change_reason"],
                "修改人": item["created_by"],
                "时间": fmt_dt(item["created_at"]),
            }
            for item in versions
        ],
        hide_index=True,
        width="stretch",
    )
    version_numbers = [item["version"] for item in versions]
    if len(version_numbers) >= 2:
        c1, c2 = st.columns(2)
        left = c1.selectbox("对比版本 A", version_numbers, index=0, key="pc_cmp_left")
        right = c2.selectbox(
            "对比版本 B", version_numbers, index=len(version_numbers) - 1, key="pc_cmp_right"
        )
        if st.button("比较版本", key="pc_compare"):
            diff = service.compare_versions(policy_id, int(left), int(right))
            if diff["identical"]:
                st.info("两个版本内容一致。")
            else:
                st.json(diff["changed"])

    with st.expander("回滚到历史版本"):
        target = st.selectbox(
            "目标版本",
            [v for v in version_numbers if v != policy["version"]],
            key="pc_rollback_target",
        )
        rollback_reason = st.text_input("回滚原因", key="pc_rollback_reason")
        confirm_rollback = st.checkbox("我确认执行回滚（将生成新版本）", key="pc_rollback_confirm")
        if st.button("执行回滚", key="pc_rollback_btn"):
            try:
                if not confirm_rollback:
                    raise ValueError("请勾选确认后再回滚")
                if not rollback_reason.strip():
                    raise ValueError("必须填写回滚原因")
                result = service.rollback_policy(
                    policy_id,
                    target_version=int(target),
                    actor_ref=actor["ref"],
                    reason=rollback_reason.strip(),
                )
                service.invalidate()
                st.success(f"已回滚，生成新版本 v{result['version']}")
            except Exception as error:  # noqa: BLE001
                st.error(f"回滚失败：{error}")


def _toggle(
    service: Any, policy_id: UUID, *, enabled: bool, actor: dict[str, str], policy: dict[str, Any]
) -> None:
    try:
        service.set_enabled(
            policy_id,
            enabled=enabled,
            actor_ref=actor["ref"],
            reason=("启用策略" if enabled else "停用策略") + f"：{policy['policy_key']}",
        )
        st.success("策略已启用" if enabled else "策略已停用")
        st.rerun()
    except Exception as error:  # noqa: BLE001
        st.error(f"操作失败：{error}")


# --- Playground -----------------------------------------------------------
def _render_playground(service: Any) -> None:
    page_header("策略测试", "输入一条消息测试命中情况；不会修改正式策略或执行处置。")
    content = st.text_area("消息内容", value="出售游戏金币，加 QQ 123456789 秒到账", height=100)
    col1, col2, col3 = st.columns(3)
    sc1, sc2 = col1.columns(2)
    risk_score = sc1.slider("风险分", 0.0, 1.0, 0.9, 0.01)
    risk_level = sc2.selectbox("风险等级", ["normal", "low", "medium", "high", "critical"], index=4)
    confidence = col2.slider("置信度", 0.0, 1.0, 0.9, 0.01)
    sender_ref = col2.text_input("玩家", value="playground-player")
    server_ref = col3.text_input("服务器", value="synthetic-server-1")
    channel = col3.selectbox("频道", ["world", "alliance", "private", "system"])
    rate_count = col3.number_input("窗口内消息数", min_value=0, max_value=500, value=0)

    if st.button("运行策略测试", type="primary", key="pc_playground_run"):
        try:
            result = service.playground(
                content=content,
                risk_score=float(risk_score),
                risk_level=risk_level,
                confidence=float(confidence),
                sender_ref=sender_ref,
                server_ref=server_ref,
                channel=channel,
                rate_count=int(rate_count),
            )
            _render_playground_result(result)
        except Exception as error:  # noqa: BLE001
            st.error(f"测试失败：{error}")


def _render_playground_result(result: dict[str, Any]) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("最终动作", action_text(result["action"]))
    selected = result.get("selected_policy") or {}
    col2.metric("选中策略", selected.get("policy_key", "—"))
    col3.metric("是否默认策略", "是" if result["selected_is_default"] else "否")
    st.caption(f"命中 {len(result['matched'])} 条策略 · 决策理由：{result['reason']}")

    st.markdown("**命中策略（按优先级排序）**")
    for item in result["matched"]:
        title = (
            f"{item['name']} · {item['policy_key']} → {action_text(item['action'])} "
            f"(优先级 {item['priority']}" + (", 应急" if item["emergency"] else "") + ")"
        )
        with st.expander(title, expanded=False):
            st.json(item["conditions"])

    if result["conflicts"]:
        st.markdown("**策略冲突**")
        st.json(result["conflicts"])
    else:
        st.caption("未检测到策略冲突。")


# --- Conflicts ------------------------------------------------------------
def _render_conflicts(service: Any) -> None:
    page_header("冲突检测", "检测同优先级、同作用范围但动作互斥的策略组合。")
    if st.button("重新扫描", key="pc_conflict_scan"):
        st.session_state["_pc_conflicts"] = service.conflict_scan()
    conflicts = st.session_state.get("_pc_conflicts", service.conflict_scan())
    if not conflicts:
        st.success("未检测到策略冲突。")
        return
    st.warning(f"检测到 {len(conflicts)} 组潜在冲突。")
    for conflict in conflicts:
        st.json(conflict)


# --- helpers --------------------------------------------------------------
def _parse_json(raw: str, name: str) -> Any:
    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} 不是合法 JSON：{error}") from error
    return value


def _scope_example(policy_type: str) -> dict[str, Any]:
    if policy_type == "server":
        return {"servers": ["synthetic-server-1"]}
    if policy_type == "alliance":
        return {"alliances": ["alliance-0001"]}
    if policy_type in {"whitelist", "blacklist", "player"}:
        return {"players": ["playground-player"]}
    return {}
