"""Plotly chart helpers kept intentionally sparse (Minimal Enterprise style).

Every figure is built against the resolved theme tokens, so grids, axes, labels
and tooltips stay legible when the user switches between light and dark. Nothing
is hardcoded to a white plot area any more.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go

from claro.ui.theme import (
    ThemeTokens,
    category_color,
    resolve_theme,
    severity_color,
    status_color,
)

_FONT_FAMILY = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", '
    '"Microsoft YaHei", Roboto, sans-serif'
)


def _fmt(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _layout(title: str, height: int, tokens: ThemeTokens) -> dict[str, object]:
    return {
        "title": {
            "text": title,
            "font": {"size": 13, "color": tokens.text, "family": _FONT_FAMILY},
            "x": 0,
            "xanchor": "left",
        },
        "height": height,
        "margin": {"l": 8, "r": 8, "t": 44 if title else 12, "b": 8},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "showlegend": False,
        "font": {"family": _FONT_FAMILY, "size": 12, "color": tokens.muted},
        "hoverlabel": {
            "bgcolor": tokens.surface_alt,
            "bordercolor": tokens.border,
            "font": {"color": tokens.text, "family": _FONT_FAMILY, "size": 12},
        },
        "xaxis": _axis(tokens),
        "yaxis": _axis(tokens),
    }


def _axis(tokens: ThemeTokens) -> dict[str, object]:
    return {
        "gridcolor": tokens.grid,
        "linecolor": tokens.border,
        "zerolinecolor": tokens.grid,
        "tickfont": {"color": tokens.muted, "size": 11, "family": _FONT_FAMILY},
        "title": {"font": {"color": tokens.muted, "size": 11}},
        "automargin": True,
    }


def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    colors: Sequence[str] | None = None,
    color: str | None = None,
    horizontal: bool = True,
    height: int = 300,
    tokens: ThemeTokens | None = None,
) -> go.Figure:
    tokens = tokens or resolve_theme()
    palette = list(colors) if colors else [color or tokens.accent] * len(labels)
    texts = [_fmt(value) for value in values]
    if horizontal:
        trace = go.Bar(
            x=list(values),
            y=list(labels),
            orientation="h",
            marker_color=palette,
            marker_line_width=0,
            text=texts,
            textposition="auto",
            textfont={"color": tokens.text, "size": 11, "family": _FONT_FAMILY},
            hovertemplate="%{y}: %{x:,}<extra></extra>",
            cliponaxis=False,
        )
    else:
        trace = go.Bar(
            x=list(labels),
            y=list(values),
            marker_color=palette,
            marker_line_width=0,
            text=texts,
            textposition="auto",
            textfont={"color": tokens.text, "size": 11, "family": _FONT_FAMILY},
            hovertemplate="%{x}: %{y:,}<extra></extra>",
            cliponaxis=False,
        )
    figure = go.Figure(trace)
    layout = _layout(title, height, tokens)
    layout["bargap"] = 0.38
    if horizontal:
        layout["yaxis"] = {**layout["yaxis"], "gridcolor": "rgba(0,0,0,0)"}
        numeric = [float(value) for value in values if value is not None]
        if numeric and min(numeric) >= 0:
            layout["xaxis"] = {
                **layout["xaxis"],
                "gridcolor": "rgba(0,0,0,0)",
                "range": [0, max(numeric) * 1.14],
            }
        else:
            layout["xaxis"] = {**layout["xaxis"], "gridcolor": "rgba(0,0,0,0)"}
    else:
        layout["xaxis"] = {**layout["xaxis"], "gridcolor": "rgba(0,0,0,0)"}
    figure.update_layout(**layout)
    return figure


def _break_gaps(x: Sequence[object], values: Sequence[float], gap_days: int) -> tuple[list, list]:
    """Insert a break where two points are further apart than ``gap_days``.

    Joining two isolated days with a straight line invents a trend that never
    happened. A ``None`` between them makes Plotly stop the line instead.
    """
    xs = list(x)
    ys = list(values)
    if gap_days <= 0 or len(xs) < 2:
        return xs, ys
    out_x: list[object] = [xs[0]]
    out_y: list[float | None] = [ys[0]]
    for index in range(1, len(xs)):
        try:
            delta = (xs[index] - xs[index - 1]).days
        except (TypeError, AttributeError):
            out_x.append(xs[index])
            out_y.append(ys[index])
            continue
        if delta > gap_days:
            out_x.append(xs[index - 1])
            out_y.append(None)
        out_x.append(xs[index])
        out_y.append(ys[index])
    return out_x, out_y


def line_chart(
    x: Sequence[object],
    series: Mapping[str, Sequence[float]],
    *,
    title: str = "",
    height: int = 280,
    colors: Sequence[str] | None = None,
    fill: bool = False,
    tokens: ThemeTokens | None = None,
    gap_days: int = 0,
) -> go.Figure:
    """Multi-series line chart for timelines (one trace per series).

    ``gap_days`` breaks the line when consecutive points are further apart than
    that many days, so a sparse dataset is not drawn as a continuous decline.
    """
    tokens = tokens or resolve_theme()
    palette = list(colors) if colors else [tokens.accent, "#0D9488", "#B45309", "#7C3AED"]
    figure = go.Figure()
    for index, (name, values) in enumerate(series.items()):
        color = palette[index % len(palette)]
        xs, ys = _break_gaps(x, values, gap_days)
        figure.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                name=name,
                mode="lines",
                connectgaps=False,
                line={"color": color, "width": 2, "shape": "linear"},
                fill="tozeroy" if fill and index == 0 else None,
                fillcolor=f"{color}1f" if fill and index == 0 else None,
                hovertemplate="%{x|%m-%d} · " + name + ": %{y:,}<extra></extra>",
            )
        )
    layout = _layout(title, height, tokens)
    layout["showlegend"] = len(series) > 1
    if len(series) > 1:
        layout["legend"] = {
            "orientation": "h",
            "y": -0.18,
            "x": 0,
            "font": {"color": tokens.muted, "size": 11},
        }
    layout["xaxis"] = {**layout["xaxis"], "type": "date", "showgrid": False}
    figure.update_layout(**layout)
    return figure


def donut_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    colors: Sequence[str] | None = None,
    height: int = 300,
    tokens: ThemeTokens | None = None,
) -> go.Figure:
    tokens = tokens or resolve_theme()
    figure = go.Figure(
        go.Pie(
            labels=list(labels),
            values=list(values),
            hole=0.58,
            marker={
                "colors": list(colors) if colors else None,
                "line": {"color": tokens.surface, "width": 2},
            },
            textinfo="none",
            hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
        )
    )
    layout = _layout(title, height, tokens)
    layout["showlegend"] = True
    layout["legend"] = {
        "orientation": "v",
        "y": 0.5,
        "x": 1.02,
        "font": {"color": tokens.muted, "size": 11},
    }
    layout["margin"] = {"l": 8, "r": 8, "t": 44 if title else 12, "b": 8}
    figure.update_layout(**layout)
    return figure


def category_donut(
    mapping: Mapping[str, float], *, title: str = "", height: int = 300
) -> go.Figure:
    tokens = resolve_theme()
    keys = list(mapping)
    return donut_chart(
        keys,
        [mapping[key] for key in keys],
        title=title,
        colors=[category_color(key, tokens) for key in keys],
        height=height,
        tokens=tokens,
    )


def severity_bar(
    mapping: Mapping[str, float],
    *,
    title: str = "",
    height: int = 300,
    tokens: ThemeTokens | None = None,
    labels: Mapping[str, str] | None = None,
) -> go.Figure:
    tokens = tokens or resolve_theme()
    order = ["critical", "high", "medium", "low", "normal"]
    keys = [key for key in order if key in mapping]
    keys += [key for key in mapping if key not in order]
    return bar_chart(
        [labels.get(key, key) for key in keys] if labels else keys,
        [mapping[key] for key in keys],
        title=title,
        colors=[severity_color(key, tokens) for key in keys],
        height=height,
        tokens=tokens,
    )


def action_bar(
    mapping: Mapping[str, float],
    *,
    title: str = "",
    height: int = 300,
    tokens: ThemeTokens | None = None,
    labels: Mapping[str, str] | None = None,
) -> go.Figure:
    tokens = tokens or resolve_theme()
    keys = list(mapping)
    return bar_chart(
        [labels.get(key, key) for key in keys] if labels else keys,
        [mapping[key] for key in keys],
        title=title,
        colors=[status_color(key, tokens) for key in keys],
        height=height,
        tokens=tokens,
    )


def empty_figure(
    message: str, *, height: int = 240, tokens: ThemeTokens | None = None
) -> go.Figure:
    """Placeholder figure used when a chart has no data, instead of a blank box."""
    tokens = tokens or resolve_theme()
    figure = go.Figure()
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": tokens.muted, "size": 12, "family": _FONT_FAMILY},
    )
    layout = _layout("", height, tokens)
    figure.update_layout(**layout)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure
