"""Utility functions for formatting, rendering, and data manipulation."""

from __future__ import annotations

from datetime import datetime

from src.constants import (
    EMPTY_HISTORY_TEMPLATE,
    ENTRY_DETAIL_TEMPLATE,
    MOOD_DISPLAY_LOOKUP,
)
from src.models import JournalEntry


def clamp_scale_value(raw: object, default: int = 3) -> int:
    """Convert raw slider-like values to the canonical 1-5 scale."""
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = default
    return max(1, min(5, value))


def format_timestamp_display(timestamp: str) -> str:
    """Render ISO timestamps into a compact, reader-friendly string."""
    if not timestamp:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    return dt.strftime("%Y-%m-%d %H:%M")


def review_theme_colors(dark_mode: bool) -> dict[str, str]:
    """Choose review pane colors based on the current palette."""
    if dark_mode:
        return {
            "text": "#dfe6e9",
            "secondary": "#a4b0be",
            "divider": "#3a3f44",
            "art": "#c8ced3",
        }
    return {
        "text": "#2d3436",
        "secondary": "#636e72",
        "divider": "#dfe6e9",
        "art": "#7f8c8d",
    }


def render_entry_detail_html(entry: JournalEntry, dark_mode: bool = False) -> str:
    """Render the selected journal entry via the Jinja2 template."""
    colors = review_theme_colors(dark_mode)
    structured_fields: list[dict[str, str]] = []

    intensity_value = clamp_scale_value(entry.emotion_intensity)
    energy_value = clamp_scale_value(entry.energy_level)

    field_specs = (
        ("身体感受 Body Sensation", entry.body_sensation),
        ("触发事件 Trigger", entry.trigger_event),
        ("需求/界限 Need or Boundary", entry.need_boundary),
    )

    for label, raw_value in field_specs:
        trimmed = (raw_value or "").strip()
        if trimmed:
            structured_fields.append({"label": label, "value": trimmed})

    return ENTRY_DETAIL_TEMPLATE.render(
        colors=colors,
        timestamp_display=format_timestamp_display(entry.timestamp),
        mood_display=MOOD_DISPLAY_LOOKUP.get(entry.mood, entry.mood),
        emotion_intensity=intensity_value,
        energy_level=energy_value,
        structured_fields=structured_fields,
        body_text=entry.text,
        has_body=bool(entry.text.strip()),
        empty_body_notice="（此刻的记录为空）",
    )


def render_empty_history_html(dark_mode: bool) -> str:
    """Render a friendly empty-state message that respects theme colors."""
    colors = review_theme_colors(dark_mode)
    return EMPTY_HISTORY_TEMPLATE.render(colors=colors)
