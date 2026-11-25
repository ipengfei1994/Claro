"""Minimal Enterprise design tokens for the Streamlit interface.

The palette is deliberately restrained: one accent colour, a small set of
semantic colours, and neutral surfaces. Colour *schemes* come from Streamlit's
native ``[theme.light]`` / ``[theme.dark]`` configuration, so every built-in
widget (dataframes, inputs, buttons) follows the active theme. This module only
resolves which scheme is active and provides matching tokens for the things
Streamlit cannot theme: Plotly figures and the small amount of injected HTML.

Nothing here overrides Streamlit's CSS variables — doing that is what previously
produced invisible text on dark backgrounds.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import streamlit as st

# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ThemeTokens:
    """Resolved surface/text/line colours for the active colour scheme."""

    kind: str
    text: str
    muted: str
    grid: str
    surface: str
    surface_alt: str
    border: str
    accent: str


LIGHT_TOKENS = ThemeTokens(
    kind="light",
    text="#111827",
    muted="#6B7280",
    grid="#E5E7EB",
    surface="#FFFFFF",
    surface_alt="#F9FAFB",
    border="#E5E7EB",
    accent="#2563EB",
)

DARK_TOKENS = ThemeTokens(
    kind="dark",
    text="#E5E7EB",
    muted="#94A3B8",
    grid="#334155",
    surface="#0F172A",
    surface_alt="#1E293B",
    border="#334155",
    accent="#60A5FA",
)

THEME_LABELS = {
    "system": "跟随系统",
    "light": "浅色",
    "dark": "深色",
}


def _context_scheme() -> str | None:
    """Return the colour scheme Streamlit is actually rendering right now."""
    try:
        theme = st.context.theme
    except Exception:  # noqa: BLE001 - context is unavailable outside a script run
        return None
    value = getattr(theme, "type", None) or (theme.get("type") if isinstance(theme, dict) else None)
    if isinstance(value, str) and value.lower() in {"light", "dark"}:
        return value.lower()
    return None


def resolve_theme(preference: str | None = None) -> ThemeTokens:
    """Resolve the tokens for the scheme Streamlit is rendering.

    ``preference`` is the configured default (``light``/``dark``/``system``).
    The live Streamlit scheme always wins when it is available, because that is
    the scheme the widgets are painted with. ``system`` falls back to light.
    """
    scheme = _context_scheme()
    if scheme is None:
        configured = (preference or "light").lower()
        scheme = "dark" if configured == "dark" else "light"
    return DARK_TOKENS if scheme == "dark" else LIGHT_TOKENS


def _palette(tokens: ThemeTokens | None) -> dict[str, str]:
    tokens = tokens or resolve_theme()
    if tokens.kind == "dark":
        return {
            "neutral": "#94A3B8",
            "info": "#38BDF8",
            "warning": "#FBBF24",
            "danger": "#F87171",
            "violet": "#C084FC",
            "positive": "#4ADE80",
            "accent": "#60A5FA",
        }
    return {
        "neutral": "#64748B",
        "info": "#0284C7",
        "warning": "#B45309",
        "danger": "#DC2626",
        "violet": "#7C3AED",
        "positive": "#15803D",
        "accent": "#2563EB",
    }


_CATEGORICAL_LIGHT = (
    "#2563EB",
    "#0D9488",
    "#B45309",
    "#7C3AED",
    "#BE123C",
    "#4D7C0F",
    "#0284C7",
    "#A21CAF",
)
_CATEGORICAL_DARK = (
    "#60A5FA",
    "#2DD4BF",
    "#FBBF24",
    "#C084FC",
    "#FB7185",
    "#A3E635",
    "#38BDF8",
    "#E879F9",
)

# --------------------------------------------------------------------------- #
# Semantic mapping: domain vocabulary -> palette slot
# --------------------------------------------------------------------------- #

_SEVERITY_SEMANTIC: dict[str, str] = {
    "normal": "neutral",
    "low": "info",
    "medium": "warning",
    "high": "danger",
    "critical": "violet",
}

_STATUS_SEMANTIC: dict[str, str] = {
    "allow": "positive",
    "warn": "warning",
    "flag": "info",
    "review": "accent",
    "block": "danger",
    "mute": "violet",
    "temp_ban": "warning",
    "perm_ban": "danger",
    "restrict": "danger",
    "pending": "neutral",
    "open": "accent",
    "in_review": "accent",
    "escalated": "warning",
    "second_review": "violet",
    "approved": "positive",
    "resolved": "positive",
    "finalized": "positive",
    "rejected": "danger",
    "executed": "positive",
    "failed": "danger",
    "expired": "neutral",
    "released": "info",
    "cancelled": "neutral",
    "auto_decided": "positive",
    "pending_review": "accent",
    "human_reviewed": "positive",
    "overridden": "violet",
    "processed": "positive",
    "duplicate": "neutral",
    "partial": "warning",
    "skipped": "neutral",
    "ok": "positive",
    "blocked": "danger",
    "unavailable": "danger",
    "unknown": "neutral",
    "healthy": "positive",
    "degraded": "warning",
    "down": "danger",
}

_CATEGORY_SEMANTIC: dict[str, str] = {
    "advertising": "warning",
    "spam": "warning",
    "fraud": "danger",
    "scam": "danger",
    "harassment": "danger",
    "abuse": "danger",
    "hate": "danger",
    "hate_speech": "danger",
    "violence": "danger",
    "sexual": "violet",
    "sexual_content": "violet",
    "self_harm": "violet",
    "suicidality": "violet",
    "privacy": "info",
    "politics": "info",
    "external_diversion": "info",
    "other": "neutral",
    "normal": "neutral",
}

_SEVERITY_COLORS_LIGHT = {
    key: _palette(LIGHT_TOKENS)[slot] for key, slot in _SEVERITY_SEMANTIC.items()
}
_SEVERITY_COLORS_DARK = {
    key: _palette(DARK_TOKENS)[slot] for key, slot in _SEVERITY_SEMANTIC.items()
}
_STATUS_COLORS_LIGHT = {key: _palette(LIGHT_TOKENS)[slot] for key, slot in _STATUS_SEMANTIC.items()}
_STATUS_COLORS_DARK = {key: _palette(DARK_TOKENS)[slot] for key, slot in _STATUS_SEMANTIC.items()}
_CATEGORY_COLORS_LIGHT = {
    key: _palette(LIGHT_TOKENS)[slot] for key, slot in _CATEGORY_SEMANTIC.items()
}
_CATEGORY_COLORS_DARK = {
    key: _palette(DARK_TOKENS)[slot] for key, slot in _CATEGORY_SEMANTIC.items()
}

# Backwards-compatible module level maps (light scheme).
SEVERITY_COLORS = _SEVERITY_COLORS_LIGHT
STATUS_COLORS = _STATUS_COLORS_LIGHT
CATEGORY_COLORS = _CATEGORY_COLORS_LIGHT


def _lookup(
    mapping_light: dict[str, str], mapping_dark: dict[str, str], key: str | None
) -> str | None:
    if not key:
        return None
    normalised = key.strip().lower().replace("-", "_")
    tokens = resolve_theme()
    table = mapping_dark if tokens.kind == "dark" else mapping_light
    return table.get(normalised)


def severity_color(severity: str | None, tokens: ThemeTokens | None = None) -> str:
    if tokens is not None:
        table = _SEVERITY_COLORS_DARK if tokens.kind == "dark" else _SEVERITY_COLORS_LIGHT
        return table.get((severity or "").strip().lower(), _palette(tokens)["neutral"])
    return (
        _lookup(_SEVERITY_COLORS_LIGHT, _SEVERITY_COLORS_DARK, severity)
        or _palette(None)["neutral"]
    )


def status_color(status: str | None, tokens: ThemeTokens | None = None) -> str:
    if tokens is not None:
        table = _STATUS_COLORS_DARK if tokens.kind == "dark" else _STATUS_COLORS_LIGHT
        return table.get((status or "").strip().lower(), _palette(tokens)["neutral"])
    return _lookup(_STATUS_COLORS_LIGHT, _STATUS_COLORS_DARK, status) or _palette(None)["neutral"]


def category_color(category: str | None, tokens: ThemeTokens | None = None) -> str:
    """Colour for a content category, stable across sessions and both themes."""
    tokens = tokens or resolve_theme()
    known = _lookup(_CATEGORY_COLORS_LIGHT, _CATEGORY_COLORS_DARK, category)
    if known:
        return known
    cycle = _CATEGORICAL_DARK if tokens.kind == "dark" else _CATEGORICAL_LIGHT
    digest = hashlib.sha256((category or "other").strip().lower().encode("utf-8")).digest()
    return cycle[digest[0] % len(cycle)]


def domain_color(
    key: str | None, *, kind: str = "status", tokens: ThemeTokens | None = None
) -> str:
    """Best-effort colour for a value whose domain is not known up front."""
    if kind == "severity":
        return severity_color(key, tokens)
    if kind == "category":
        return category_color(key, tokens)
    return status_color(key, tokens)


# --------------------------------------------------------------------------- #
# HTML helpers
# --------------------------------------------------------------------------- #


def badge(
    label: str,
    *,
    severity: str | None = None,
    status: str | None = None,
    category: str | None = None,
) -> str:
    """Render a compact pill whose colours are legible in both themes."""
    tokens = resolve_theme()
    if severity:
        color = severity_color(severity, tokens)
    elif category:
        color = category_color(category, tokens)
    else:
        color = status_color(status or label, tokens)
    return (
        f'<span class="claro-badge" style="background:{color}1f;color:{color};'
        f'border:1px solid {color}59;">{label}</span>'
    )


def section(title: str, description: str | None = None) -> str:
    """A section header with an optional one-line explanation."""
    body = f'<h3 class="claro-section-title">{title}</h3>'
    if description:
        body += f'<p class="claro-section-desc">{description}</p>'
    return f'<div class="claro-section">{body}</div>'


def empty_state(message: str, hint: str | None = None) -> str:
    body = f'<div class="claro-empty-title">{message}</div>'
    if hint:
        body += f'<div class="claro-empty-hint">{hint}</div>'
    return f'<div class="claro-empty">{body}</div>'


def kpi_value(value: str) -> str:
    return f'<div class="claro-kpi-value">{value}</div>'


def base_css(tokens: ThemeTokens) -> str:
    """Inject the small set of styles Streamlit cannot express natively.

    Only Claro-owned class names are styled, and every colour is derived from
    the resolved tokens, so nothing fights the native theme.
    """
    return f"""
<style>
:root {{
  --claro-text: {tokens.text};
  --claro-muted: {tokens.muted};
  --claro-border: {tokens.border};
  --claro-surface: {tokens.surface};
  --claro-surface-alt: {tokens.surface_alt};
  --claro-accent: {tokens.accent};
}}
.claro-brand {{
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 4px 0 8px;
}}
.claro-brand-name {{
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--claro-text);
}}
.claro-brand-tag {{
  font-size: 0.72rem;
  color: var(--claro-muted);
}}
.claro-badge {{
  display: inline-block;
  padding: 1px 8px;
  border-radius: 9999px;
  font-size: 0.72rem;
  line-height: 1.45;
  font-weight: 600;
  white-space: nowrap;
}}
.claro-section {{
  margin: 6px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--claro-border);
}}
.claro-section-title {{
  margin: 0;
  font-size: 0.95rem;
  font-weight: 650;
  color: var(--claro-text);
  letter-spacing: -0.005em;
}}
.claro-section-desc {{
  margin: 2px 0 0;
  font-size: 0.78rem;
  color: var(--claro-muted);
}}
.claro-kpi {{
  border: 1px solid var(--claro-border);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--claro-surface);
  height: 100%;
}}
.claro-kpi-label {{
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--claro-muted);
}}
.claro-kpi-value {{
  font-size: 1.55rem;
  font-weight: 650;
  line-height: 1.25;
  color: var(--claro-text);
  font-variant-numeric: tabular-nums;
}}
.claro-kpi-hint {{
  font-size: 0.72rem;
  color: var(--claro-muted);
}}
.claro-event {{
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 7px 0;
  border-bottom: 1px solid var(--claro-border);
  font-size: 0.83rem;
}}
.claro-event:last-child {{ border-bottom: none; }}
.claro-event-time {{
  color: var(--claro-muted);
  font-variant-numeric: tabular-nums;
  font-size: 0.75rem;
  white-space: nowrap;
}}
.claro-event-body {{ color: var(--claro-text); flex: 1; }}
.claro-empty {{
  border: 1px dashed var(--claro-border);
  border-radius: 10px;
  padding: 26px 18px;
  text-align: center;
  background: var(--claro-surface-alt);
}}
.claro-empty-title {{ font-size: 0.88rem; color: var(--claro-text); font-weight: 550; }}
.claro-empty-hint {{ font-size: 0.76rem; color: var(--claro-muted); margin-top: 4px; }}
.claro-mono {{
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.78rem;
}}
div[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
</style>
"""


def apply_theme(preference: str | None = None) -> ThemeTokens:
    """Inject Claro's base styles for the active scheme and return its tokens."""
    tokens = resolve_theme(preference)
    st.markdown(base_css(tokens), unsafe_allow_html=True)
    return tokens
