"""Plotly chart helpers kept intentionally sparse (Minimal Enterprise style)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go

from claro.ui.theme import severity_color, status_color

_ACCENT = "#2563EB"


def _layout(title: str, height: int = 300) -> dict[str, object]:
    return {
        "title": {"text": title, "font": {"size": 14}},
        "height": height,
        "margin": {"l": 10, "r": 10, "t": 40, "b": 10},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "showlegend": False,
    }


def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    colors: Sequence[str] | None = None,
    color: str = _ACCENT,
    horizontal: bool = True,
    height: int = 300,
) -> go.Figure:
    palette = list(colors) if colors else [color] * len(labels)
    if horizontal:
        figure = go.Figure(
            go.Bar(
                x=list(values),
                y=list(labels),
                orientation="h",
                marker_color=palette,
                text=[_fmt(value) for value in values],
                textposition="auto",
            )
        )
    else:
        figure = go.Figure(
            go.Bar(
                x=list(labels),
                y=list(values),
                marker_color=palette,
                text=[_fmt(value) for value in values],
                textposition="auto",
            )
        )
    figure.update_layout(**_layout(title, height), bargap=0.35)
    return figure


def donut_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    colors: Sequence[str] | None = None,
    height: int = 300,
) -> go.Figure:
    figure = go.Figure(
        go.Pie(
            labels=list(labels),
            values=list(values),
            hole=0.55,
            marker={"colors": list(colors) if colors else None},
            textinfo="value",
        )
    )
    layout = _layout(title, height)
    layout["showlegend"] = True
    layout["legend"] = {"orientation": "h", "y": -0.1}
    figure.update_layout(**layout)
    return figure


def severity_bar(mapping: Mapping[str, float], *, title: str = "", height: int = 300) -> go.Figure:
    order = ["critical", "high", "medium", "low", "normal"]
    keys = [key for key in order if key in mapping]
    keys += [key for key in mapping if key not in order]
    return bar_chart(
        keys,
        [mapping[key] for key in keys],
        title=title,
        colors=[severity_color(key) for key in keys],
        height=height,
    )


def action_bar(mapping: Mapping[str, float], *, title: str = "", height: int = 300) -> go.Figure:
    keys = list(mapping)
    return bar_chart(
        keys,
        [mapping[key] for key in keys],
        title=title,
        colors=[status_color(key) for key in keys],
        height=height,
    )


def _fmt(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"
