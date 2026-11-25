"""Overview page: platform status, governance activity and synthetic-data notice."""

from __future__ import annotations

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    st.title("Claro")
    st.caption("Everything under control. · 内容安全与风险治理平台")

    settings = container.settings
    repository = container.governance_repository
    try:
        stats = repository.governance_stats() if repository is not None else {}
    except Exception as error:  # noqa: BLE001 - surfaced to the operator
        st.error(f"治理统计读取失败：{error}")
        stats = {}

    decisions = sum(stats.get("decisions_by_status", {}).values())
    auto_decided = stats.get("decisions_by_status", {}).get("auto_decided", 0)
    policies = 0
    if container.policy_repository is not None:
        policies = container.policy_repository.counts().get("policies", 0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("运行模式", settings.app.mode)
    col2.metric("事件传输", container.event_bus.transport)
    col3.metric("治理策略", policies)
    col4.metric("治理决策", decisions)

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("自动决策", auto_decided)
    col6.metric("待人工审核", stats.get("open_cases", 0))
    col7.metric("模拟处罚记录", sum(stats.get("enforcement_by_status", {}).values()))
    col8.metric("审核操作", stats.get("reviews", 0))

    page_header("服务状态", "基础设施连通性由 HealthService 实时检测。")
    try:
        results = container.health_service.check_all()
        st.dataframe(
            [result.to_dict() for result in results],
            hide_index=True,
            width="stretch",
        )
    except Exception as error:  # noqa: BLE001
        st.error(f"健康检查失败：{error}")

    if settings.app.mode == "development":
        st.info(
            "开发模式使用 SQLite 与内存事件总线。Redis 与 Kafka 处于禁用状态，"
            "内存总线仅用于同步模拟，不代表 Kafka 已集成。"
        )
    else:
        st.success(
            "全量模式：PostgreSQL 为业务状态权威来源，Redis 提供缓存，"
            "Kafka 承载治理事件流（Outbox Pattern 保证一致性）。"
        )

    page_header("合成数据声明")
    st.warning(
        "本平台全部玩家、服务器、联盟、消息、检测结果与治理记录均为合成数据（synthetic），"
        "用于本地演示与验证，不代表任何真实线上运营数据。所有处罚均为平台内部模拟，"
        "不会触达任何真实游戏服务。"
    )
    st.code(
        "PowerShell: .\\scripts\\claro.ps1 migrate\n"
        "PowerShell: .\\scripts\\claro.ps1 seed\n"
        "PowerShell: .\\scripts\\claro.ps1 governance-seed-policies",
        language="powershell",
    )
