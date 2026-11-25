"""Message Explorer: filter any message and read its full risk-to-decision trace.

The page is a read model over :class:`ExplorerService`. Filters are validated by
the service (unknown risk levels raise, empty filters are dropped) and every
query is parameterised SQL, so arbitrary user input cannot reach the database as
SQL text.
"""

from __future__ import annotations

from datetime import datetime, time

import pandas as pd
import streamlit as st

from claro.application.explorer_service import ExplorerError
from claro.bootstrap import AppContainer
from claro.ui.common import (
    ACTION_LABELS,
    CATEGORY_LABELS,
    RISK_LABELS,
    STATUS_LABELS,
    action_text,
    category_text,
    data_table,
    detector_text,
    fmt_clock,
    fmt_int,
    fmt_ms,
    fmt_pct,
    fmt_score,
    render_empty,
    render_section,
    severity_badge,
    severity_text,
    stage_text,
    status_text,
)
from claro.ui.theme import resolve_theme

_CASE_STATUSES = ["open", "in_review", "escalated", "second_review", "resolved", "rejected"]
_ANY = "全部"


def render(container: AppContainer) -> None:
    service = container.explorer_service
    if service is None:
        st.error("探查服务未启用，请检查运行模式与配置。")
        return

    st.title("消息探查")
    st.caption("按条件筛选消息，并查看单条消息从检测到处置的完整证据链")

    try:
        options = service.options()
    except Exception as error:  # noqa: BLE001
        st.error(f"筛选项加载失败：{error}")
        return

    filters = _render_filters(options)
    page_size = _render_page_size()

    page_key = "explorer_page"
    page = int(st.session_state.get(page_key, 1))
    try:
        result = service.search(**filters, page=page, page_size=page_size)
    except ExplorerError as error:
        st.warning(f"筛选条件无效：{error}")
        return
    except Exception as error:  # noqa: BLE001
        st.error(f"查询失败：{error}")
        return

    render_section(
        "结果",
        f"共 {fmt_int(result.total)} 条 · 第 {result.page}/{result.pages} 页 · "
        f"当前显示 {result.first_row}–{result.last_row}",
    )
    if not result.items:
        render_empty("没有匹配的消息", "放宽筛选条件，或先运行 `claro demo-run` 生成演示数据。")
        _render_pager(result, page_key)
        return

    frame = pd.DataFrame([_row_for_table(item) for item in result.items])
    # Messages that were never scored carry no risk_score; coerce so an empty
    # cell is blank instead of the string "None".
    frame["分数"] = pd.to_numeric(frame["分数"], errors="coerce")
    state = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"explorer_table_{result.page}_{page_size}",
        column_order=[
            "消息内容",
            "风险",
            "分数",
            "类别",
            "决策",
            "案例",
            "发生时间",
        ],
        column_config={
            "消息内容": st.column_config.TextColumn("消息内容", width="large"),
            "风险": st.column_config.TextColumn("风险", width="small"),
            "分数": st.column_config.NumberColumn("分数", format="%.4f", width="small"),
            "类别": st.column_config.TextColumn("类别", width="small"),
            "决策": st.column_config.TextColumn("决策", width="small"),
            "案例": st.column_config.TextColumn("案例", width="small"),
            "发生时间": st.column_config.TextColumn("发生时间", width="medium"),
        },
    )
    _render_pager(result, page_key)

    selection = list(getattr(state, "selection", {}).get("rows", []) or [])
    if not selection:
        st.caption("在上表中选择一行，即可展开该消息的完整证据链。")
        return
    message_id = frame.iloc[selection[0]]["message_id"]
    _render_detail(service, message_id)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def _render_filters(options: dict[str, list[str]]) -> dict:
    with st.expander("筛选条件", expanded=True):
        first, second, third = st.columns(3, gap="medium")
        with first:
            dataset = st.selectbox("数据集", [_ANY, *options.get("datasets", [])], key="ex_dataset")
            channel = st.selectbox("频道", [_ANY, *options.get("channels", [])], key="ex_channel")
        with second:
            risk = st.selectbox(
                "风险等级",
                [_ANY, *RISK_LABELS.keys()],
                key="ex_risk",
                format_func=lambda value: RISK_LABELS.get(value, value),
            )
            category = st.selectbox(
                "风险类别",
                [_ANY, *options.get("categories", [])],
                key="ex_category",
                format_func=lambda value: CATEGORY_LABELS.get(value, value),
            )
        with third:
            action = st.selectbox(
                "决策动作",
                [_ANY, *ACTION_LABELS.keys()],
                key="ex_action",
                format_func=lambda value: ACTION_LABELS.get(value, value),
            )
            case_status = st.selectbox(
                "案例状态",
                [_ANY, *_CASE_STATUSES],
                key="ex_case",
                format_func=lambda value: STATUS_LABELS.get(value, value),
            )

        text_col, date_col = st.columns([2, 3], gap="medium")
        with text_col:
            text = st.text_input("关键词（消息内容）", key="ex_text", max_chars=120)
        with date_col:
            span = st.date_input(
                "发生时间范围",
                value=(),
                key="ex_span",
                help="留空表示不限时间；时区按本机时区解释为当日 00:00–23:59。",
            )

    start, end = _span_to_datetimes(span)
    return {
        "dataset": None if dataset == _ANY else dataset,
        "channel": None if channel == _ANY else channel,
        "risk_level": None if risk == _ANY else risk,
        "category": None if category == _ANY else category,
        "decision_action": None if action == _ANY else action,
        "case_status": None if case_status == _ANY else case_status,
        "text": text or None,
        "start": start,
        "end": end,
    }


def _span_to_datetimes(span: object) -> tuple[datetime | None, datetime | None]:
    if not span:
        return None, None
    values = span if isinstance(span, (list, tuple)) else (span,)
    try:
        start = datetime.combine(values[0], time.min).astimezone()
    except (TypeError, ValueError, IndexError):
        return None, None
    end_date = values[1] if len(values) > 1 else values[0]
    end = datetime.combine(end_date, time.max).astimezone()
    return start, end


def _render_page_size() -> int:
    return int(
        st.select_slider("每页条数", options=[10, 25, 50, 100], value=25, key="ex_page_size")
    )


def _render_pager(result, page_key: str) -> None:
    left, middle, right = st.columns([1, 3, 1], gap="small")
    with left:
        if st.button("上一页", disabled=result.page <= 1, key=f"prev_{page_key}"):
            st.session_state[page_key] = max(1, result.page - 1)
            st.rerun()
    with right:
        if st.button("下一页", disabled=result.page >= result.pages, key=f"next_{page_key}"):
            st.session_state[page_key] = min(result.pages, result.page + 1)
            st.rerun()
    with middle:
        st.caption(f"第 {result.page} / {result.pages} 页")


def _row_for_table(item: dict) -> dict:
    return {
        "message_id": item["message_id"],
        "消息内容": item["excerpt"],
        "风险": severity_text(item.get("risk_level")),
        "分数": item.get("risk_score"),
        "类别": category_text(item.get("top_category")),
        "决策": action_text(item.get("decision_action")),
        "案例": status_text(item.get("case_status")),
        "发生时间": fmt_clock(item.get("occurred_at")),
    }


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def _render_detail(service, message_id: str) -> None:
    tokens = resolve_theme()
    st.divider()
    try:
        detail = service.detail(message_id)
    except ExplorerError as error:
        st.warning(str(error))
        return
    except Exception as error:  # noqa: BLE001
        st.error(f"消息详情加载失败：{error}")
        return

    header = detail["header"]
    st.markdown(f"### 消息 {header['message_id'][:8]}")
    st.markdown(
        f"{severity_badge(header.get('risk_level') or 'normal')} "
        f"&nbsp;分数 <span class='claro-mono'>{fmt_score(header.get('risk_score'))}</span> "
        f"&nbsp;·&nbsp; {category_text(header.get('top_category'))} "
        f"&nbsp;·&nbsp; {action_text(header.get('decision_action'))} "
        f"&nbsp;·&nbsp; 案例 {status_text(header.get('case_status'))}",
        unsafe_allow_html=True,
    )

    meta = st.columns(4, gap="small")
    meta[0].metric("发送者", header.get("sender_ref") or "—")
    meta[1].metric("服务器", header.get("server_ref") or "—")
    meta[2].metric("频道", header.get("channel") or "—")
    meta[3].metric("数据集", header.get("dataset_name") or "—")

    st.markdown(
        f"<div class='claro-kpi' style='margin:10px 0;'>"
        f"<div class='claro-kpi-label'>原始内容</div>"
        f"<div style='margin-top:6px;color:var(--claro-text);'>"
        f"{_escape(header.get('content'))}</div>"
        f"<div class='claro-kpi-hint' style='margin-top:8px;'>发生于 "
        f"{fmt_clock(header.get('occurred_at'))} · "
        f"入库 {fmt_clock(header.get('ingested_at'))}"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["风险证据", "处理轨迹", "治理与审计"])
    with tabs[0]:
        _render_evidence(detail, tokens)
    with tabs[1]:
        _render_trace(detail)
    with tabs[2]:
        _render_governance(detail)


def _render_evidence(detail: dict, tokens) -> None:
    risk = detail.get("risk_result")
    if risk:
        render_section(
            "融合结果",
            f"检测耗时 {fmt_ms((risk.get('timings') or {}).get('total_ms'))} · "
            f"置信度 {fmt_pct(risk.get('confidence'))}",
        )
        columns = st.columns(4, gap="small")
        columns[0].metric("风险分数", fmt_score(risk.get("risk_score")))
        columns[1].metric("风险等级", severity_text(risk.get("risk_level")))
        columns[2].metric("建议动作", action_text(risk.get("suggested_action")))
        columns[3].metric("参与层", fmt_int(len(risk.get("detection_methods") or [])))
        if risk.get("detection_methods"):
            st.caption("检测层：" + " · ".join(risk["detection_methods"]))
        with st.expander("解释与证据（原始 JSON）"):
            st.json({"explanation": risk.get("explanation"), "evidence": risk.get("evidence")})
    else:
        render_empty("该消息还没有融合风险结果", "检测流程可能尚未覆盖它，或仅有单层规则命中。")

    events = detail.get("risk_events") or []
    render_section("检测事件", "每个事件对应一次规则或模型命中，是融合分数的来源。")
    if events:
        frame = pd.DataFrame(
            [
                {
                    "类别": category_text(item.get("category")),
                    "等级": severity_text(item.get("severity")),
                    "分数": item.get("risk_score"),
                    "置信度": item.get("confidence"),
                    "规则": item.get("rule_id") or "—",
                    "时间": fmt_clock(item.get("occurred_at")),
                }
                for item in events
            ]
        )
        data_table(
            frame,
            column_config={
                "分数": st.column_config.NumberColumn("分数", format="%.4f"),
                "置信度": st.column_config.NumberColumn("置信度", format="%.4f"),
            },
        )
    else:
        render_empty("没有检测事件")

    findings = detail.get("findings") or []
    if findings:
        st.markdown("**原子检测证据**")
        frame = pd.DataFrame(
            [
                {
                    "检测器": detector_text(item.get("detector")),
                    "版本": item.get("detector_version") or "—",
                    "类别": category_text(item.get("category")),
                    "分数": item.get("score"),
                    "置信度": item.get("confidence"),
                }
                for item in findings
            ]
        )
        data_table(
            frame,
            column_config={
                "分数": st.column_config.NumberColumn("分数", format="%.3f"),
                "置信度": st.column_config.NumberColumn("置信度", format="%.3f"),
            },
        )


def _render_trace(detail: dict) -> None:
    trace = detail.get("trace") or []
    render_section("处理流水线", "按阶段记录的执行状态与耗时，用于定位卡点。")
    if not trace:
        render_empty("没有处理轨迹", "该消息可能来自历史数据集，未经过 Phase 06 流水线。")
        return
    frame = pd.DataFrame(
        [
            {
                "阶段": stage_text(item.get("stage")),
                "状态": status_text(item.get("status"))
                if item.get("status")
                else item.get("status"),
                "开始": fmt_clock(item.get("started_at")),
                "结束": fmt_clock(item.get("finished_at")),
                "详情": _brief(item.get("details")),
            }
            for item in trace
        ]
    )
    data_table(frame)


def _render_governance(detail: dict) -> None:
    governance = detail.get("governance") or {}
    if governance:
        render_section("治理决策链", "从策略裁决到人工审核、处置执行的完整链路。")
        decisions = governance.get("decisions") or []
        if decisions:
            latest = decisions[-1]
            columns = st.columns(3, gap="small")
            columns[0].metric("决策动作", action_text(latest.get("action")))
            columns[1].metric("决策状态", status_text(latest.get("decision_status")))
            columns[2].metric("决策时间", fmt_clock(latest.get("decided_at")))
            if latest.get("decision_reason"):
                st.caption(f"理由：{latest['decision_reason']}")
            if len(decisions) > 1:
                with st.expander(f"全部 {len(decisions)} 次策略裁决"):
                    st.json(decisions)
        evaluations = governance.get("evaluations") or []
        if evaluations:
            with st.expander(f"策略命中 {len(evaluations)} 次"):
                st.json(evaluations)
        case = governance.get("case")
        if case:
            with st.expander("审核案例"):
                st.json(case)
        enforcements = governance.get("enforcements") or []
        if enforcements:
            with st.expander(f"处置动作 {len(enforcements)} 条"):
                st.json(enforcements)
        if governance.get("reviews"):
            with st.expander("人工审核记录"):
                st.json(governance["reviews"])
        if governance.get("feedback"):
            with st.expander("反馈记录"):
                st.json(governance["feedback"])
    else:
        render_empty("该消息没有治理记录", "只有触发人工审核或自动处置的消息才会生成治理链路。")

    audit = detail.get("audit") or []
    render_section("审计事件", "请求方、动作、时间与变更前后状态。")
    if audit:
        frame = pd.DataFrame(
            [
                {
                    "对象": item.get("entity_type") or "—",
                    "动作": item.get("action") or "—",
                    "执行者": item.get("actor_ref") or "系统",
                    "理由": item.get("reason") or "—",
                    "时间": fmt_clock(item.get("created_at")),
                }
                for item in audit
            ]
        )
        data_table(frame)
        with st.expander("变更前后状态"):
            st.json(
                [
                    {
                        "action": item.get("action"),
                        "before": item.get("before_state"),
                        "after": item.get("after_state"),
                    }
                    for item in audit
                ]
            )
    else:
        render_empty("没有审计事件")

    reviews = detail.get("reviews") or []
    if reviews:
        render_section("人工审核")
        frame = pd.DataFrame(
            [
                {
                    "审核人": item.get("actor_ref") or "—",
                    "角色": item.get("actor_role") or "—",
                    "动作": item.get("action") or "—",
                    "理由": item.get("reason") or "—",
                    "时间": fmt_clock(item.get("created_at")),
                }
                for item in reviews
            ]
        )
        data_table(frame)

    feedback = detail.get("feedback") or []
    if feedback:
        render_section("反馈")
        frame = pd.DataFrame(
            [
                {
                    "类型": item.get("feedback_type") or "—",
                    "提交人": item.get("actor_ref") or "—",
                    "备注": item.get("notes") or "—",
                    "时间": fmt_clock(item.get("created_at")),
                }
                for item in feedback
            ]
        )
        data_table(frame)


def _brief(details: object) -> str:
    if not details:
        return "—"
    if isinstance(details, dict):
        parts = [f"{key}={value}" for key, value in list(details.items())[:3]]
        return " · ".join(parts) if parts else "—"
    return str(details)[:80]


def _escape(value: object) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )
