"""System Settings: runtime configuration, health and demo-data controls.

Everything shown here is read from the live settings object and live services.
Secrets are masked before rendering — the page never prints a password, token or
credential, only the fact that one is configured.
"""

from __future__ import annotations

import platform
import re
import sys
from importlib import metadata

import pandas as pd
import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui.common import (
    data_table,
    fmt_int,
    render_empty,
    render_section,
    status_text,
)
from claro.ui.theme import THEME_LABELS, resolve_theme

_STATUS_BADGES = {"healthy": "正常", "degraded": "降级", "unhealthy": "不可用", "unknown": "未检查"}


def render(container: AppContainer) -> None:
    tokens = resolve_theme()
    st.title("系统设置")
    st.caption("运行配置、依赖健康状态与演示数据管理")

    _render_runtime(container, tokens)
    st.divider()
    _render_health(container)
    st.divider()
    _render_configuration(container)
    st.divider()
    _render_demo(container)
    st.divider()
    _render_limits()


def _render_runtime(container: AppContainer, tokens) -> None:
    settings = container.settings
    render_section("运行环境", "本机原生 Windows 部署，无容器化依赖。")
    kpi_cols = st.columns(4, gap="small")
    kpi_cols[0].metric("运行模式", settings.app.mode)
    kpi_cols[1].metric("Claro 版本", _version("claro"))
    kpi_cols[2].metric("Python", sys.version.split()[0])
    kpi_cols[3].metric("主题", THEME_LABELS.get(settings.ui.theme, settings.ui.theme))
    st.caption(
        f"当前渲染配色：{'深色' if tokens.kind == 'dark' else '浅色'} · "
        f"操作系统 {platform.system()} {platform.release()} · "
        "在右上角菜单「Settings → Theme」中可切换 "
        "System / Light / Dark，选择会被记住。"
    )


def _render_health(container: AppContainer) -> None:
    render_section("依赖健康", "每次检查都会真实连接对应服务；未启用的组件显示为未检查。")
    if st.button("重新检查", key="settings_health"):
        st.session_state.pop("settings_health_results", None)
    results = st.session_state.get("settings_health_results")
    if results is None:
        try:
            results = [
                {"name": item.name, "status": item.status, "detail": item.detail}
                for item in container.health_service.check_all()
            ]
        except Exception as error:  # noqa: BLE001
            st.warning(f"健康检查失败：{error}")
            results = []
        st.session_state["settings_health_results"] = results
    if not results:
        render_empty("没有可检查的组件")
        return
    frame = pd.DataFrame(
        [
            {
                "组件": item["name"],
                "状态": _STATUS_BADGES.get(item["status"], status_text(item["status"])),
                "详情": item["detail"] or "—",
            }
            for item in results
        ]
    )
    data_table(frame, column_config={"详情": st.column_config.TextColumn("详情", width="large")})


def _render_configuration(container: AppContainer) -> None:
    settings = container.settings
    render_section("连接与阈值", "密码等敏感值只显示是否已配置，不显示内容。")
    rows = [
        ("数据库", "连接串", _mask_url(settings.database.url)),
        (
            "数据库",
            "连接池",
            f"size {settings.database.pool_size} / overflow {settings.database.max_overflow}",
        ),
        ("Kafka", "Broker", settings.kafka.bootstrap_servers),
        ("Kafka", "内容事件 Topic", settings.kafka.topic),
        ("Kafka", "死信 Topic", settings.kafka.dead_letter_topic),
        ("Kafka", "消费者组", settings.kafka.consumer_group),
        ("Redis", "启用", "是" if settings.redis.enabled else "否"),
        ("Redis", "地址", _mask_url(settings.redis.url)),
        ("风控", "规则文件", str(settings.risk.rules_file)),
        ("风控", "分类体系", str(settings.risk.taxonomy_file)),
        ("治理", "自动处置低置信阈值", f"{settings.governance.low_confidence_threshold:.2f}"),
        ("治理", "高风险置信阈值", f"{settings.governance.high_risk_confidence_threshold:.2f}"),
        ("治理", "审核 SLA", f"{settings.governance.review_sla_hours} 小时"),
        ("LLM", "启用", "是" if settings.risk.llm.enabled else "否（默认关闭）"),
        ("日志", "级别 / 目录", f"{settings.logging.level} / {settings.logging.directory}"),
    ]
    frame = pd.DataFrame(rows, columns=["分组", "配置项", "值"])
    data_table(
        frame,
        column_config={"值": st.column_config.TextColumn("值", width="large")},
    )
    st.caption("修改配置请编辑项目根目录 `.env`（模板见 `.env.example`），随后重启应用。")


def _render_demo(container: AppContainer) -> None:
    render_section("演示数据", "固定随机种子的隔离数据集，可随时清理，不影响其他数据。")
    service = container.demo_service
    if service is None:
        render_empty("演示服务未启用", "当前运行模式不支持生成演示数据。")
        return
    try:
        status = service.status()
    except Exception as error:  # noqa: BLE001
        st.warning(f"演示数据状态读取失败：{error}")
        return

    if not status.get("exists"):
        st.info("演示数据集尚未生成。在终端运行 `claro demo-run` 或 `scripts/run_demo.ps1`。")
        return

    columns = st.columns(4, gap="small")
    columns[0].metric("消息", fmt_int(status.get("messages")))
    columns[1].metric("风险结果", fmt_int(status.get("risk")))
    columns[2].metric("审核案例", fmt_int(status.get("cases")))
    columns[3].metric("反馈记录", fmt_int(status.get("feedback")))
    st.caption(f"数据集名称：`{status.get('dataset')}`（合成数据）")

    confirm = st.checkbox(
        "我确认要删除演示数据集及其关联的决策、处置与审计记录",
        key="demo_clean_confirm",
    )
    if st.button("清理演示数据", disabled=not confirm, key="demo_clean_button"):
        try:
            deleted = service.clean()
        except Exception as error:  # noqa: BLE001
            st.error(f"清理失败：{error}")
            return
        st.success("已清理：" + "，".join(f"{key} {value}" for key, value in deleted.items()))
        st.session_state.pop("settings_health_results", None)
        st.rerun()


def _render_limits() -> None:
    render_section("已知限制", "诚实标注能力边界，避免把演示能力当成生产能力。")
    st.markdown(
        "- 身份为**模拟**：侧栏身份切换不是登录鉴权，所有角色都能执行全部操作。\n"
        "- 处置动作**模拟执行**：禁言、封禁写入本地状态表，不会下发到任何游戏服务器。\n"
        "- 数据为**合成数据**，指标只用于验证链路，不等于线上效果。\n"
        "- Hive / Hadoop 未安装，离线特征与大规模抽样分析不可用（已明确降级）。\n"
        "- LLM 检测层默认关闭，未配置外部模型时不会启用。"
    )


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "dev"


def _mask_url(url: str) -> str:
    """Hide credentials inside a connection URL before display."""
    if not url:
        return "—"
    return re.sub(r"//([^:/@]+):([^@]*)@", r"//\1:****@", str(url))
