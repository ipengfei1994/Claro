"""Shared helpers for the Claro governance pages.

Everything the UI needs to talk to the application layer passes through
:func:`get_container`, which caches a single :class:`AppContainer` for the
lifetime of the Streamlit server. Pages never touch SQL or repositories
directly; they call services exposed on the container.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st

from claro.bootstrap import AppContainer, create_app_container
from claro.ui.theme import badge, empty_state, section  # re-exported for page use

# --- Simulated identities -------------------------------------------------
# Single-machine demos switch reviewer identity through this list. This is
# explicitly simulated authentication, not a production login system.
SIMULATED_REVIEWERS: tuple[dict[str, str], ...] = (
    {"ref": "reviewer.alice", "role": "moderator", "label": "Alice · 审核员 (模拟)"},
    {"ref": "reviewer.bob", "role": "senior_moderator", "label": "Bob · 高级审核员 (模拟)"},
    {"ref": "reviewer.carol", "role": "admin", "label": "Carol · 管理员 (模拟)"},
    {"ref": "auditor.dave", "role": "auditor", "label": "Dave · 审计员 (模拟)"},
)

ACTION_LABELS: dict[str, str] = {
    "allow": "允许",
    "warn": "警告",
    "flag": "标记观察",
    "review": "人工审核",
    "block": "拦截",
    "mute": "禁言",
    "temp_ban": "临时封禁",
    "perm_ban": "永久封禁",
    "restrict": "限制",
}

STATUS_LABELS: dict[str, str] = {
    "pending": "待处理",
    "open": "待审核",
    "in_review": "审核中",
    "escalated": "已升级",
    "second_review": "二次复核",
    "approved": "已通过",
    "resolved": "已解决",
    "finalized": "已终审",
    "rejected": "已驳回",
    "executed": "已执行",
    "failed": "执行失败",
    "expired": "已到期",
    "released": "已解除",
    "cancelled": "已取消",
    "auto_decided": "自动决策",
    "pending_review": "待审核",
    "human_reviewed": "人工已审",
    "overridden": "已覆盖",
    "legacy": "历史记录",
}

RISK_LABELS: dict[str, str] = {
    "normal": "正常",
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "极高",
}

POLICY_TYPE_LABELS: dict[str, str] = {
    "keyword": "关键词",
    "regex": "正则",
    "risk_threshold": "风险阈值",
    "category": "风险类别",
    "player": "玩家",
    "server": "服务器",
    "alliance": "联盟",
    "whitelist": "白名单",
    "blacklist": "黑名单",
    "rate_limit": "限流",
    "composite": "组合",
}

FEEDBACK_LABELS: dict[str, str] = {
    "correct": "识别正确",
    "false_positive": "误杀",
    "false_negative": "漏判",
    "category_error": "类别错误",
    "level_error": "等级错误",
    "action_inappropriate": "处置不合理",
    "insufficient_evidence": "证据不足",
    "other": "其他",
}

MODERATION_ACTION_LABELS: dict[str, str] = {
    "approve": "审核通过",
    "reject": "确认违规",
    "override": "人工覆盖",
    "escalate": "升级处理",
    "request_second_review": "申请二次复核",
    "reopen": "重新打开",
}

TARGET_TYPE_LABELS: dict[str, str] = {
    "message": "单条消息",
    "player": "玩家",
    "player_server": "玩家(服务器内)",
}

CATEGORY_LABELS: dict[str, str] = {
    "spam": "垃圾广告",
    "fraud": "欺诈诱导",
    "harassment": "骚扰辱骂",
    "hate_speech": "仇恨言论",
    "self_harm": "自伤风险",
    "sexual_content": "色情内容",
    "violence": "暴力内容",
    "advertising": "广告导流",
    "external_diversion": "站外导流",
    "privacy": "隐私泄露",
    "politics": "涉政敏感",
    "other": "其他",
    "normal": "正常",
}

STAGE_LABELS: dict[str, str] = {
    "validate": "校验",
    "ingestion": "入库",
    "preprocessing": "预处理",
    "detection": "检测",
    "policy": "策略裁决",
    "governance": "治理决策",
    "moderation": "人工审核",
    "enforcement": "处置执行",
    "publish": "事件发布",
}

DETECTOR_LABELS: dict[str, str] = {
    "rule.keyword": "关键词规则",
    "rule.regex": "正则规则",
    "rule.blacklist": "黑名单规则",
    "rule.url_pattern": "外链规则",
    "ml.logistic_regression": "逻辑回归模型",
    "synthetic-keyword": "合成关键词器",
    "synthetic-rule-engine": "合成规则引擎",
}


@st.cache_resource(show_spinner="正在连接 Claro 服务...")
def get_container() -> AppContainer:
    """Return the process-wide application container."""
    container = create_app_container()
    if container.settings.app.mode == "full":
        container.verify_connections()
    return container


def current_actor() -> dict[str, str]:
    """Return the currently selected simulated reviewer identity."""
    actor = st.session_state.get("_claro_actor")
    if actor is None:
        actor = SIMULATED_REVIEWERS[0]
        st.session_state["_claro_actor"] = actor
    return dict(actor)


def render_sidebar_identity() -> dict[str, str]:
    """Render the simulated-identity switcher and return the active actor."""
    st.sidebar.markdown("### 模拟身份")
    labels = [item["label"] for item in SIMULATED_REVIEWERS]
    current = current_actor()
    index = next(
        (i for i, item in enumerate(SIMULATED_REVIEWERS) if item["ref"] == current["ref"]), 0
    )
    choice = st.sidebar.selectbox("审核身份", labels, index=index, key="_claro_actor_select")
    actor = next(item for item in SIMULATED_REVIEWERS if item["label"] == choice)
    st.session_state["_claro_actor"] = actor
    st.sidebar.caption("模拟身份认证：仅用于本机演示的角色切换，非生产级登录。")
    return dict(actor)


def page_header(title: str, subtitle: str = "") -> None:
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def flash(kind: str, message: str) -> None:
    st.session_state["_claro_flash"] = {"kind": kind, "message": message}


def render_flash() -> None:
    payload = st.session_state.pop("_claro_flash", None)
    if not payload:
        return
    renderer = {
        "success": st.success,
        "error": st.error,
        "warning": st.warning,
        "info": st.info,
    }.get(payload.get("kind", "info"), st.info)
    renderer(payload.get("message", ""))


def require(service: Any, name: str) -> Any:
    """Fail loudly if a governance service is missing from the container."""
    if service is None:
        st.error(f"治理服务 {name} 未启用，请检查运行模式与配置。")
        st.stop()
    return service


# --- Formatting helpers ---------------------------------------------------
def fmt_dt(value: Any) -> str:
    moment = _to_local(value)
    if moment is None:
        return "—" if not value else str(value)
    return moment.strftime("%Y-%m-%d %H:%M")


def fmt_score(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_duration(seconds: Any) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    if total <= 0:
        return "0s"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not hours:
        parts.append(f"{secs}s")
    return " ".join(parts) or f"{total}s"


def severity_text(level: Any) -> str:
    key = str(level or "").lower()
    return RISK_LABELS.get(key, str(level) if level else "—")


def action_text(action: Any) -> str:
    key = str(action or "").lower()
    return ACTION_LABELS.get(key, str(action) if action else "—")


def status_text(status: Any) -> str:
    key = str(status or "").lower()
    return STATUS_LABELS.get(key, str(status) if status else "—")


def severity_badge(level: Any) -> str:
    return badge(severity_text(level), severity=str(level or "").lower())


def status_badge(status: Any) -> str:
    return badge(status_text(status), status=str(status or "").lower())


def category_text(category: Any) -> str:
    key = str(category or "").lower()
    return CATEGORY_LABELS.get(key, str(category) if category else "—")


def detector_text(detector: Any) -> str:
    key = str(detector or "")
    return DETECTOR_LABELS.get(key, key or "—")


def stage_text(stage: Any) -> str:
    key = str(stage or "").lower()
    return STAGE_LABELS.get(key, str(stage) if stage else "—")


def category_badge(category: Any) -> str:
    return badge(category_text(category), category=str(category or "").lower())


# --- Numbers and time -----------------------------------------------------
def fmt_int(value: Any) -> str:
    """Thousands-separated integer, or an em dash when the value is missing."""
    if value is None or value == "":
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def fmt_pct(value: Any, digits: int = 1) -> str:
    """Format a 0..1 ratio as a percentage.

    Rate helpers in the analytics layer return a dictionary envelope; the ratio
    is unwrapped here so no page has to know that detail.
    """
    if isinstance(value, dict):
        value = value.get("risk_rate", value.get("value"))
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def ratio_display(detail: dict[str, Any] | None, digits: int = 1) -> tuple[str, str]:
    """Return ``(value, hint)`` for a gated rate, keeping low-sample honesty."""
    if not detail:
        return "—", "暂无数据"
    value = detail.get("value")
    denominator = fmt_int(detail.get("denominator"))
    if value is None:
        return "不可计算", f"样本量 {denominator} 不足，已抑制"
    return fmt_pct(value, digits), f"n = {denominator}"


def fmt_relative(value: Any) -> str:
    """Human relative time (刚刚 / 3 分钟前 / 2 天前) in local time."""
    moment = _to_local(value)
    if moment is None:
        return "—"
    delta = datetime.now(UTC) - moment
    seconds = delta.total_seconds()
    if seconds < 0:
        return moment.strftime("%m-%d %H:%M")
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    if seconds < 86400 * 30:
        return f"{int(seconds // 86400)} 天前"
    return moment.strftime("%Y-%m-%d")


def fmt_clock(value: Any) -> str:
    moment = _to_local(value)
    return "—" if moment is None else moment.strftime("%m-%d %H:%M:%S")


def _to_local(value: Any) -> datetime | None:
    """Coerce timestamps, pandas timestamps and ISO strings to local time.

    ``pandas.Timestamp`` subclasses ``datetime`` but overrides ``astimezone``
    with a signature that rejects the no-argument call, so values are converted
    back to a plain ``datetime`` first.
    """
    if value is None or value == "":
        return None
    try:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            moment = value
        else:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return datetime.fromtimestamp(moment.timestamp(), tz=UTC).astimezone()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def fmt_ms(value: Any) -> str:
    if value is None:
        return "—"
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{millis / 1000:.2f}s" if millis >= 1000 else f"{millis:.0f}ms"


# --- Layout helpers -------------------------------------------------------
def render_section(title: str, description: str | None = None) -> None:
    st.markdown(section(title, description), unsafe_allow_html=True)


def render_empty(message: str, hint: str | None = None) -> None:
    st.markdown(empty_state(message, hint), unsafe_allow_html=True)


def kpi_cards(items: list[tuple[str, str, str | None]], columns: int = 4) -> None:
    """Render KPI cards as ``(label, value, hint)`` triples."""
    for row_start in range(0, len(items), columns):
        row = items[row_start : row_start + columns]
        slots = st.columns(len(row), gap="small")
        for slot, (label, value, hint) in zip(slots, row, strict=False):
            with slot:
                body = (
                    f'<div class="claro-kpi"><div class="claro-kpi-label">{label}</div>'
                    f'<div class="claro-kpi-value">{value}</div>'
                )
                if hint:
                    body += f'<div class="claro-kpi-hint">{hint}</div>'
                body += "</div>"
                st.markdown(body, unsafe_allow_html=True)


def data_table(
    frame: Any,
    *,
    height: int | None = None,
    column_config: dict[str, Any] | None = None,
    empty_message: str = "当前筛选条件下没有数据",
    empty_hint: str | None = None,
) -> None:
    """Render a dataframe, or an explicit empty state instead of a bare header."""
    try:
        is_empty = frame is None or len(frame) == 0
    except TypeError:
        is_empty = frame is None
    if is_empty:
        render_empty(empty_message, empty_hint)
        return
    options: dict[str, Any] = {
        "hide_index": True,
        "column_config": column_config,
        "width": "stretch",
    }
    if height is not None:
        options["height"] = height
    st.dataframe(frame, **options)


def render_activity(items: list[dict[str, Any]], *, limit: int = 10) -> None:
    """Render the audit activity feed as a compact, theme-aware list."""
    if not items:
        render_empty("暂无治理活动", "执行一次演示流程后，这里会出现决策、审核与处置记录。")
        return
    rows = []
    for item in items[:limit]:
        rows.append(
            '<div class="claro-event">'
            f'<span class="claro-event-time">{fmt_relative(item.get("occurred_at"))}</span>'
            f'<span class="claro-event-body">{item.get("summary") or "—"}'
            f'<span class="claro-kpi-hint"> · {item.get("actor_ref") or "系统"}</span></span>'
            "</div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
