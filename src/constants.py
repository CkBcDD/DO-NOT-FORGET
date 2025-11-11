"""Configuration constants and templates for the application."""

from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

from jinja2 import DictLoader, Environment, select_autoescape

# Database and file paths
ENTRY_CHARACTER_LIMIT = 100
DATABASE_PATH = Path("journal.sqlite3")
LEGACY_JSON_PATH = Path("journal.json")

# Notification timing
GENTLE_REMINDER_INTERVAL_MS = 10 * 60 * 1000

# Mood options with display labels and internal values
MOOD_CHOICES = [
    ("平静 Calm", "calm"),
    ("喜悦 Joyful", "joyful"),
    ("专注 Focused", "focused"),
    ("感恩 Grateful", "grateful"),
    ("疲惫 Tired", "tired"),
    ("焦虑 Anxious", "anxious"),
    ("沮丧 Frustrated", "frustrated"),
    ("悲伤 Sad", "sad"),
    ("愤怒 Angry", "angry"),
    ("不确定 Uncertain", "uncertain"),
    ("其他 Other", "other"),
]

# Reverse lookup for mood display
MOOD_DISPLAY_LOOKUP = {value: label for label, value in MOOD_CHOICES}

# Basic logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Jinja2 template environment for HTML rendering
TEMPLATE_ENV = Environment(
    loader=DictLoader(
        {
            "entry_detail.html": dedent(
                """\
                <div style='font-family:"Segoe UI",sans-serif; line-height:1.6; color:{{ colors.text }};'>
                    <div style='display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end; justify-content:space-between; margin-bottom:12px;'>
                        <div>
                            <div style='font-size:16px; font-weight:bold;'>{{ timestamp_display }}</div>
                            <div style='color:{{ colors.secondary }};'>情绪 Mood: {{ mood_display }}</div>
                        </div>
                        <div style='display:flex; flex-wrap:wrap; gap:18px; color:{{ colors.secondary }}; font-size:14px;'>
                            <div>情绪强度 Intensity: <strong style='color:{{ colors.text }};'>{{ emotion_intensity }}/5</strong></div>
                            <div>能量水平 Energy: <strong style='color:{{ colors.text }};'>{{ energy_level }}/5</strong></div>
                        </div>
                    </div>
                    {% if structured_fields %}
                    <div style='margin:8px 0;'>
                        <ul style='margin:0 0 0 16px; padding:0; color:{{ colors.secondary }};'>
                            {% for field in structured_fields %}
                            <li><strong>{{ field.label }}</strong>: {{ field.value | e }}</li>
                            {% endfor %}
                        </ul>
                    </div>
                    {% endif %}
                    <hr style='border:0; height:1px; background:{{ colors.divider }}; margin:12px 0;'>
                    <p style='white-space:pre-wrap; margin:0;'>
                        {% if has_body %}{{ body_text | e | replace('\n', '<br>') | safe }}{% else %}<em>{{ empty_body_notice }}</em>{% endif %}
                    </p>
                </div>
                """
            ),
            "empty_history.html": dedent(
                """\
                <div style='font-family:"Segoe UI",sans-serif; color:{{ colors.secondary }};'>
                    还没有记录。
                </div>
                """
            ),
        }
    ),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

ENTRY_DETAIL_TEMPLATE = TEMPLATE_ENV.get_template("entry_detail.html")
EMPTY_HISTORY_TEMPLATE = TEMPLATE_ENV.get_template("empty_history.html")
