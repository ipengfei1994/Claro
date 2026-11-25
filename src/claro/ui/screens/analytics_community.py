"""Community analytics page: servers, alliances and player risk profiles."""

from __future__ import annotations

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui import cache
from claro.ui.analytics_ui import (
    analytics_filters,
    bar_chart,
    dataframe,
    render_banner,
    service_from,
)
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    page_header("Community Analytics", "服务器、联盟与玩家维度的风险分布。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_community")
    result = cache.analytics_community(service, filters, 200)
    render_banner(result)

    tab_servers, tab_alliances, tab_players = st.tabs(["Server", "Alliance", "Player"])
    with tab_servers:
        st.caption("同时展示风险数量与风险率；低样本单位需谨慎解读。")
        bar_chart(result["servers"][:20], "server_name", "risk_messages", "服务器风险数量 Top 20")
        dataframe(result["servers"])
    with tab_alliances:
        ranked = [row for row in result["alliances"] if not row["low_sample"]]
        st.caption(f"低样本联盟已从排名视图过滤：{len(result['alliances']) - len(ranked)} 个。")
        bar_chart(ranked[:20], "alliance_name", "risk_rate", "联盟风险率 Top 20")
        dataframe(result["alliances"][:100])
    with tab_players:
        st.caption("画像仅用于分析与模拟治理；模型分数不是玩家真实违规概率。")
        dataframe(result["players"])
