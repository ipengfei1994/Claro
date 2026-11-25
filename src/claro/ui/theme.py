"""Minimal Enterprise theme tokens for the Streamlit interface.

The palette is deliberately restrained: one accent colour, a small set of
status colours, and neutral surfaces. All badges are rendered with inline
styles so that light, dark and system themes remain legible.
"""

from __future__ import annotations

LIGHT_THEME = """
  --primary-color: #2563EB;
  --background-color: #FFFFFF;
  --secondary-background-color: #F3F4F6;
  --text-color: #111827;
  --code-background-color: #F3F4F6;
  color-scheme: light;
"""

DARK_THEME = """
  --primary-color: #60A5FA;
  --background-color: #0F172A;
  --secondary-background-color: #1E293B;
  --text-color: #E2E8F0;
  --code-background-color: #1E293B;
  color-scheme: dark;
"""

_SEVERITY_COLORS: dict[str, str] = {
    "normal": "#64748B",
    "low": "#0EA5E9",
    "medium": "#D97706",
    "high": "#DC2626",
    "critical": "#9333EA",
}

_STATUS_COLORS: dict[str, str] = {
    "allow": "#16A34A",
    "warn": "#D97706",
    "flag": "#0EA5E9",
    "review": "#2563EB",
    "block": "#DC2626",
    "mute": "#7C3AED",
    "temp_ban": "#B45309",
    "perm_ban": "#991B1B",
    "restrict": "#991B1B",
    "pending": "#64748B",
    "open": "#2563EB",
    "in_review": "#2563EB",
    "escalated": "#D97706",
    "second_review": "#7C3AED",
    "approved": "#16A34A",
    "resolved": "#16A34A",
    "finalized": "#16A34A",
    "rejected": "#DC2626",
    "executed": "#16A34A",
    "failed": "#DC2626",
    "expired": "#64748B",
    "released": "#0EA5E9",
    "cancelled": "#64748B",
    "auto_decided": "#16A34A",
    "pending_review": "#2563EB",
    "human_reviewed": "#16A34A",
    "overridden": "#7C3AED",
}

_NEUTRAL = "#64748B"


def theme_style(theme: str) -> str:
    """Return a ``<style>`` block for the requested theme preference."""
    if theme == "system":
        return (
            f"<style>:root {{{LIGHT_THEME}}} "
            f"@media (prefers-color-scheme: dark) {{ :root {{{DARK_THEME}}} }}</style>"
        )
    variables = DARK_THEME if theme == "dark" else LIGHT_THEME
    return f"<style>:root {{{variables}}}</style>"


def badge(label: str, *, severity: str | None = None, status: str | None = None) -> str:
    """Render a compact status pill that adapts to any theme."""
    key = (severity or status or "").lower()
    color = _SEVERITY_COLORS.get(key) or _STATUS_COLORS.get(key) or _NEUTRAL
    return (
        f'<span style="display:inline-block;padding:1px 8px;border-radius:9999px;'
        f"font-size:0.72rem;line-height:1.4;font-weight:600;white-space:nowrap;"
        f'background:{color}22;color:{color};border:1px solid {color}55;">{label}</span>'
    )


def severity_color(severity: str | None) -> str:
    return _SEVERITY_COLORS.get((severity or "").lower(), _NEUTRAL)


def status_color(status: str | None) -> str:
    return _STATUS_COLORS.get((status or "").lower(), _NEUTRAL)
