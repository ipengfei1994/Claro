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
from claro.ui.theme import badge  # re-exported for page use

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
    if not value:
        return "—"
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


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
