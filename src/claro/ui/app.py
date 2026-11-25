from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import streamlit as st

from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.ui.common import get_container, render_flash, render_sidebar_identity
from claro.ui.pages import (
    analytics_community,
    analytics_governance,
    analytics_model,
    analytics_overview,
    analytics_risk,
    analytics_strategy,
    enforcement_center,
    feedback_audit,
    governance_decisions,
    moderation_workbench,
    overview,
    policy_center,
)
from claro.ui.theme import theme_style

PAGES: dict[str, Callable[[AppContainer], None]] = {
    "总览": overview.render,
    "Policy Center": policy_center.render,
    "Moderation Workbench": moderation_workbench.render,
    "Governance Decisions": governance_decisions.render,
    "Enforcement Center": enforcement_center.render,
    "Feedback & Audit": feedback_audit.render,
    "分析 · 总览": analytics_overview.render,
    "分析 · 风险": analytics_risk.render,
    "分析 · 社区": analytics_community.render,
    "分析 · 治理": analytics_governance.render,
    "分析 · 模型": analytics_model.render,
    "分析 · 策略评估": analytics_strategy.render,
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
    st.set_page_config(page_title="Claro · 内容治理", layout="wide")
    container = get_container()
    st.markdown(theme_style(container.settings.ui.theme), unsafe_allow_html=True)

    st.sidebar.title("Claro")
    st.sidebar.caption("Everything under control.")
    render_sidebar_identity()
    choice = st.sidebar.radio("导航", list(PAGES), key="_claro_nav")
    st.sidebar.divider()
    st.sidebar.caption(f"运行模式：{container.settings.app.mode}")
    st.sidebar.caption("合成数据演示 · 非真实运营数据")

    render_flash()
    try:
        PAGES[choice](container)
    except Exception as error:  # noqa: BLE001 - surface failures instead of a blank page
        st.error(f"页面渲染失败：{error}")
        with st.expander("错误详情"):
            st.exception(error)


if __name__ == "__main__":
    render()
