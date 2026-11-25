"""Risk Intelligence: what the detection layer is made of and how it behaves.

This page answers "why did the platform fire?" at the detector level: rule
catalogue, per-detector hit counts, taxonomy usage, model cards and evaluation
runs — all read from the database. Missing artefacts are shown as missing rather
than implied.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from claro.bootstrap import AppContainer
from claro.ui import cache
from claro.ui.charts import bar_chart
from claro.ui.common import (
    category_text,
    data_table,
    detector_text,
    fmt_clock,
    fmt_int,
    fmt_pct,
    fmt_relative,
    fmt_score,
    kpi_cards,
    render_empty,
    render_section,
)
from claro.ui.theme import resolve_theme

_RULE_TYPE_LABELS = {
    "keyword": "关键词",
    "regex": "正则",
    "blacklist": "黑名单",
    "url_pattern": "外链模式",
    "ml": "模型",
    "composite": "组合",
}


def render(container: AppContainer) -> None:
    service = container.explorer_service
    if service is None:
        st.error("探查服务未启用，请检查运行模式与配置。")
        return

    tokens = resolve_theme()
    st.title("风险情报")
    st.caption("检测规则、检测层命中与模型资产的真实状态")

    try:
        data = cache.risk_intelligence(service)
    except Exception as error:  # noqa: BLE001
        st.error(f"风险情报加载失败：{error}")
        return

    coverage = data["coverage"] or {}
    _render_coverage(coverage)
    st.divider()
    _render_detectors(data["detectors"], tokens)
    st.divider()
    _render_taxonomy(data["taxonomy"])
    st.divider()
    _render_rules(data["rules"])
    st.divider()
    _render_models(data["models"], data["evaluations"])


def _render_coverage(coverage: dict) -> None:
    messages = int(coverage.get("messages") or 0)
    detected = int(coverage.get("detected_messages") or 0)
    findings = int(coverage.get("findings") or 0)
    events = int(coverage.get("events") or 0)
    findings_messages = int(coverage.get("findings_messages") or 0)

    render_section(
        "检测覆盖",
        "覆盖率 = 已写入融合结果的消息 / 全部消息。原子证据指单条规则或模型的命中记录。",
    )
    kpi_cards(
        [
            ("消息总量", fmt_int(messages), "含历史与演示数据集"),
            (
                "已出融合结果",
                fmt_int(detected),
                f"覆盖率 {fmt_pct(detected / messages if messages else None, 2)}",
            ),
            ("原子证据", fmt_int(findings), f"覆盖 {fmt_int(findings_messages)} 条消息"),
            ("风险事件", fmt_int(events), "按类别聚合后的检测事件"),
        ]
    )


def _render_detectors(detectors: list[dict], tokens) -> None:
    render_section("检测层命中", "哪一层在真正产出证据，决定后续调优投入方向。")
    if not detectors:
        render_empty("还没有检测命中记录", "运行 `claro demo-run` 或处理一条消息后再回来查看。")
        return
    frame = pd.DataFrame(
        [
            {
                "检测层": detector_text(row.get("detector")),
                "命中数": int(row.get("findings") or 0),
                "覆盖消息": int(row.get("messages") or 0),
                "最近命中": fmt_relative(row.get("last_seen")),
            }
            for row in detectors
        ]
    )
    left, right = st.columns([3, 2], gap="medium")
    with left:
        data_table(
            frame,
            column_config={
                "命中数": st.column_config.NumberColumn("命中数", format="%d"),
                "覆盖消息": st.column_config.NumberColumn("覆盖消息", format="%d"),
            },
        )
    with right:
        st.plotly_chart(
            bar_chart(
                frame["检测层"].tolist(),
                frame["命中数"].astype(float).tolist(),
                title="命中量对比",
                height=260,
                tokens=tokens,
            ),
            width="stretch",
            config={"displayModeBar": False},
        )


def _render_taxonomy(taxonomy: list[dict]) -> None:
    render_section(
        "风险类别使用情况", "类别分布决定策略与话术，平均分用于识别阈值偏松或偏紧的类别。"
    )
    if not taxonomy:
        render_empty("还没有风险事件")
        return
    frame = pd.DataFrame(
        [
            {
                "类别": category_text(row.get("category")),
                "事件数": int(row.get("events") or 0),
                "覆盖消息": int(row.get("messages") or 0),
                "平均分": float(row.get("avg_score") or 0),
            }
            for row in taxonomy
        ]
    )
    data_table(
        frame,
        column_config={
            "事件数": st.column_config.NumberColumn("事件数", format="%d"),
            "覆盖消息": st.column_config.NumberColumn("覆盖消息", format="%d"),
            "平均分": st.column_config.ProgressColumn(
                "平均分", min_value=0.0, max_value=1.0, format="%.3f"
            ),
        },
    )


def _render_rules(rules: list[dict]) -> None:
    render_section("规则目录", "规则版本与命中次数；未命中的规则同样列出，避免「看不见的规则」。")
    if not rules:
        render_empty("规则库为空")
        return
    frame = pd.DataFrame(
        [
            {
                "规则": row.get("rule_key"),
                "类型": _RULE_TYPE_LABELS.get(
                    str(row.get("rule_type") or ""), row.get("rule_type")
                ),
                "状态": row.get("status"),
                "版本": row.get("version"),
                "类别": category_text(row.get("category")),
                "命中": int(row.get("hits") or 0),
                "最近命中": fmt_clock(row.get("last_seen")),
                "说明": row.get("description") or "—",
            }
            for row in rules
        ]
    )
    data_table(
        frame,
        height=380,
        column_config={
            "命中": st.column_config.NumberColumn("命中", format="%d"),
            "说明": st.column_config.TextColumn("说明", width="large"),
        },
    )


def _render_models(models: list[dict], evaluations: list[dict]) -> None:
    render_section(
        "模型资产", "模型卡片来自 ml_model 表；评估指标来自 evaluation_run 的真实运行记录。"
    )
    if not models:
        render_empty(
            "还没有登记模型",
            "检测目前完全由规则层承担。训练模型后（`claro train-model`）会出现模型卡片。",
        )
    else:
        for model in models:
            metrics = model.get("metrics") or {}
            headline = {
                key: fmt_score(metrics.get(key), 3)
                for key in ("precision", "recall", "f1", "roc_auc", "accuracy")
                if metrics.get(key) is not None
            }
            title = f"{model.get('name')} · v{model.get('version')}"
            with st.expander(title, expanded=False):
                st.caption(
                    f"算法 {model.get('algorithm') or '—'} · 状态 {model.get('status') or '—'} · "
                    f"训练于 {fmt_clock(model.get('trained_at'))} · "
                    f"最近评估 {fmt_relative(model.get('last_evaluated'))}"
                )
                if headline:
                    columns = st.columns(len(headline), gap="small")
                    for column, (key, value) in zip(columns, headline.items(), strict=False):
                        column.metric(key.upper(), value)
                else:
                    render_empty("该模型没有评估指标")
                st.caption(f"产物路径：{model.get('artifact_path') or '未登记'}")
                with st.expander("特征配置"):
                    st.json(model.get("features") or {})

    render_section("最近评估运行")
    if not evaluations:
        render_empty("没有评估运行记录", "使用 `claro evaluate-model` 对模型做一次留出集评估。")
        return
    frame = pd.DataFrame(
        [
            {
                "数据集": row.get("dataset_name"),
                "划分": row.get("split"),
                "样本数": int(row.get("message_count") or 0),
                "指标": ", ".join(
                    f"{key}={value:.3f}"
                    for key, value in (row.get("metrics") or {}).items()
                    if isinstance(value, (int, float))
                )
                or "—",
                "时间": fmt_clock(row.get("created_at")),
            }
            for row in evaluations
        ]
    )
    data_table(
        frame,
        column_config={
            "样本数": st.column_config.NumberColumn("样本数", format="%d"),
            "指标": st.column_config.TextColumn("指标", width="large"),
        },
    )

    st.caption(
        "边界说明：Hive/Hadoop 未在本机安装，离线特征与大规模抽样分析不可用；"
        "此处的评估全部基于 PostgreSQL 中的合成数据，不代表线上效果。"
    )
