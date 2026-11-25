"""Model performance analytics page."""

from __future__ import annotations

import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui import cache
from claro.ui.analytics_ui import (
    analytics_filters,
    dataframe,
    empty_state,
    render_banner,
    service_from,
)
from claro.ui.common import page_header


def render(container: AppContainer) -> None:
    page_header("Model Analytics", "模型指标来自持久化评估结果，不在页面重算。")
    service = service_from(container)
    filters = analytics_filters(container, key_prefix="an_model")
    result = cache.analytics_model(service, filters)
    render_banner(result)

    if not result["runs"]:
        empty_state("当前筛选条件下没有评估运行记录。")
        return
    run = result["runs"][0]
    binary = (run.get("metrics") or {}).get("binary", {})
    st.caption(
        f"模型 {run['model_name']} v{run['model_version']} · "
        f"数据集 {run['dataset_name']} · split {run['split']} · "
        f"样本 {run['message_count']}"
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Accuracy", binary.get("accuracy", "—"))
    col2.metric("Precision", binary.get("precision", "—"))
    col3.metric("Recall", binary.get("recall", "—"))
    col4.metric("F1", binary.get("f1", "—"))

    matrix = binary.get("confusion_matrix", {})
    if matrix:
        st.json({"confusion_matrix": matrix})
    else:
        st.info("该评估运行未保存混淆矩阵。")

    page_header("按类别表现")
    dataframe(result["per_category"])

    page_header("错误样例")
    dataframe(result["error_cases"])

    page_header("版本对比")
    if result["version_comparison_available"]:
        dataframe(
            [
                {
                    "model_version": item["model_version"],
                    "dataset": item["dataset_name"],
                    "split": item["split"],
                    "metrics": item["metrics"].get("binary", {}),
                }
                for item in result["runs"]
            ]
        )
    else:
        st.info(result["version_comparison_note"])

    page_header("模型与人工一致性")
    st.warning(result["model_human_agreement"]["reason"])
