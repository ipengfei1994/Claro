"""Streamlit entry point: grouped navigation and shared chrome.

Navigation is grouped by job-to-be-done rather than by module, so a moderator
lands on the work queue, an analyst on analytics, and an auditor on the audit
trail. All labels are Chinese and use one vocabulary across pages.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import streamlit as st

from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.ui import cache
from claro.ui.common import get_container, render_flash, render_sidebar_identity
from claro.ui.screens import (
    analytics_community,
    analytics_governance,
    analytics_model,
    analytics_overview,
    analytics_risk,
    analytics_strategy,
    enforcement_center,
    feedback_audit,
    governance_decisions,
    message_explorer,
    moderation_workbench,
    overview,
    policy_center,
    risk_intelligence,
    settings,
)
from claro.ui.theme import apply_theme

PageRenderer = Callable[[AppContainer], None]

NAVIGATION: dict[str, list[tuple[str, PageRenderer, str]]] = {
    "监控": [
        ("治理总览", overview.render, "overview"),
    ],
    "处置": [
        ("消息探查", message_explorer.render, "messages"),
        ("审核工作台", moderation_workbench.render, "moderation"),
        ("治理决策", governance_decisions.render, "decisions"),
        ("处置中心", enforcement_center.render, "enforcement"),
    ],
    "策略与情报": [
        ("策略中心", policy_center.render, "policy"),
        ("风险情报", risk_intelligence.render, "risk-intelligence"),
    ],
    "分析": [
        ("分析总览", analytics_overview.render, "analytics"),
        ("风险分析", analytics_risk.render, "analytics-risk"),
        ("社区分析", analytics_community.render, "analytics-community"),
        ("治理分析", analytics_governance.render, "analytics-governance"),
        ("模型分析", analytics_model.render, "analytics-model"),
        ("策略评估", analytics_strategy.render, "analytics-strategy"),
    ],
    "审计与配置": [
        ("反馈与审计", feedback_audit.render, "audit"),
        ("系统设置", settings.render, "settings"),
    ],
}


def run() -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(Path(__file__).resolve()),
            "--server.port",
            str(load_settings().ui.port),
        ]
    )


def render() -> None:
    st.set_page_config(page_title="Claro · 内容安全治理", layout="wide")
    container = get_container()
    apply_theme(container.settings.ui.theme)

    page = st.navigation(_build_pages(container), position="sidebar")

    st.sidebar.divider()
    render_sidebar_identity()
    st.sidebar.caption(f"运行模式：{container.settings.app.mode}")
    if st.sidebar.button(
        "刷新数据",
        width="stretch",
        help=f"清空页面缓存。仪表盘结果缓存 {cache.TTL_SECONDS} 秒，避免每次交互重跑聚合查询。",
    ):
        cache.clear()
        st.rerun()
    st.sidebar.caption("Claro · 内容安全与风险治理")
    st.sidebar.caption("合成数据演示 · 非真实运营数据")

    render_flash()
    try:
        page.run()
    except Exception as error:  # noqa: BLE001 - surface failures instead of a blank page
        st.error(f"页面渲染失败：{error}")
        with st.expander("错误详情"):
            st.exception(error)


def _build_pages(container: AppContainer) -> dict[str, list[st.Page]]:
    sections: dict[str, list[st.Page]] = {}
    for group, entries in NAVIGATION.items():
        pages = []
        for index, (title, renderer, url_path) in enumerate(entries):
            pages.append(
                st.Page(
                    _bind(renderer, container),
                    title=title,
                    url_path=url_path,
                    default=(group == "监控" and index == 0),
                )
            )
        sections[group] = pages
    return sections


def _bind(renderer: PageRenderer, container: AppContainer) -> Callable[[], None]:
    def runner() -> None:
        renderer(container)

    runner.__name__ = getattr(renderer, "__name__", "page")
    return runner


if __name__ == "__main__":
    render()
