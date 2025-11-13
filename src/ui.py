"""User interface components and event handling."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.constants import (
    DATABASE_PATH,
    ENTRY_CHARACTER_LIMIT,
    GENTLE_REMINDER_INTERVAL_MS,
    MOOD_CHOICES,
    MOOD_DISPLAY_LOOKUP,
)
from src.db_worker import DBWorker
from src.models import EntryCache, JournalEntry
from src.storage import export_journal_to_csv
from src.utils import (
    clamp_scale_value,
    format_timestamp_display,
    render_empty_history_html,
    render_entry_detail_html,
)

BODY_SENSATION_PRESETS = ["胸口紧绷", "肩膀发冷", "手心潮湿"]
TRIGGER_PRESETS = ["会议讨论", "手机通知", "临时改期"]
NEED_PRESETS = ["需要短暂休息", "想说明界限", "渴望被陪伴"]


class JournalEntryListModel(QAbstractListModel):
    """自定义 List Model 用于虚拟化日志条目列表。

    采用 Model/View 架构实现懒加载，仅在可视区域渲染条目，
    大幅减少内存占用和 UI 构建成本，支持上万条记录的流畅显示。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[JournalEntry] = []

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        """返回模型中的行数。"""
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """返回指定索引和角色的数据。"""
        if not index.isValid() or index.row() >= len(self._entries):
            return None

        entry = self._entries[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            # 生成显示文本
            preview = " ".join(entry.text.strip().split())
            if len(preview) > 48:
                preview = preview[:47] + "…"

            timestamp_display = format_timestamp_display(entry.timestamp)
            mood_display = MOOD_DISPLAY_LOOKUP.get(entry.mood, entry.mood)

            display_lines = [f"[{timestamp_display}] {mood_display}"]
            display_lines.append(
                f"  * 强度 Intensity {entry.emotion_intensity}/5 | 能量 Energy {entry.energy_level}/5"
            )

            structured_preview = " | ".join(
                part
                for part in (
                    entry.body_sensation.strip(),
                    entry.trigger_event.strip(),
                    entry.need_boundary.strip(),
                )
                if part
            )

            if structured_preview:
                display_lines.append(f"  ~ {structured_preview}")
            if preview:
                display_lines.append(f"  -> {preview}")

            return "\n".join(display_lines)

        elif role == Qt.ItemDataRole.UserRole:
            # 存储完整的 entry 对象供详情显示使用
            return entry

        return None

    def get_entry(self, index: QModelIndex) -> JournalEntry | None:
        """获取指定索引的 JournalEntry 对象。"""
        if not index.isValid() or index.row() >= len(self._entries):
            return None
        return self._entries[index.row()]

    def set_entries(self, entries: list[JournalEntry]) -> None:
        """设置新的条目列表并通知视图更新。"""
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def clear(self) -> None:
        """清空所有条目。"""
        self.beginResetModel()
        self._entries = []
        self.endResetModel()


class MemoWindow(QWidget):
    """Main application window for the memo pad and journal review."""

    # Request signals (emit from UI thread, handled by DBWorker in worker thread)
    append_request = Signal(object)  # payload dict
    load_request = Signal(object)  # optional payload (unused)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DO-NOT-FORGET Memo Pad")
        self.setAutoFillBackground(True)
        self.setObjectName("MemoWindow")
        self._initial_palette: QPalette | None = None
        self._accent_color: QColor | None = None
        self._apply_fluent_theme()

        self._pending_entry_preview: str = ""

        self._entry_cache = EntryCache()

        layout = QVBoxLayout()
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(18)

        self.instructions = QLabel("Anchor this moment (<=100 chars):")
        layout.addWidget(self.instructions)

        self.mood_label = QLabel("情绪 Mood:")
        layout.addWidget(self.mood_label)

        self.mood_selector = QComboBox()
        for label, value in MOOD_CHOICES:
            self.mood_selector.addItem(label, userData=value)
        layout.addWidget(self.mood_selector)

        def _add_slider_row(label_text: str, tooltip: str) -> tuple[QSlider, QLabel]:
            slider = QSlider(Qt.Orientation.Horizontal)
            # 使用2-10范围来支持0.5档位(2=1.0, 3=1.5, ..., 10=5.0)
            slider.setRange(2, 10)
            slider.setTickInterval(2)  # 每整数位一个刻度
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setValue(6)  # 默认3.0对应值6
            slider.setToolTip(tooltip)
            # 允许流畅拖动，不自动吸附
            slider.setTracking(True)

            value_label = QLabel("3.0")  # 显示默认值
            value_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            value_label.setMinimumWidth(30)  # 增加宽度以容纳小数点

            row = QHBoxLayout()
            row_label = QLabel(label_text)
            row.addWidget(row_label)
            row.addWidget(slider)
            row.addWidget(value_label)
            layout.addLayout(row)
            return slider, value_label

        self.intensity_slider, self.intensity_value_label = _add_slider_row(
            "情绪强度 Intensity (1–5):", "记录当下感受的强烈程度，1=轻微，5=非常强烈"
        )
        self.intensity_slider.valueChanged.connect(self.on_intensity_value_changed)
        self.intensity_slider.sliderReleased.connect(self.on_intensity_slider_released)
        self.intensity_slider.valueChanged.connect(self.update_palette_for_mood)

        self.energy_slider, self.energy_value_label = _add_slider_row(
            "能量水平 Energy (1–5):", "记录当下的能量充沛度，1=低能量，5=高能量"
        )
        self.energy_slider.valueChanged.connect(self.on_energy_value_changed)
        self.energy_slider.sliderReleased.connect(self.on_energy_slider_released)
        self.energy_slider.valueChanged.connect(self.update_palette_for_mood)
        self.update_palette_for_mood()

        self.body_input = QLineEdit()
        self.trigger_input = QLineEdit()
        self.need_input = QLineEdit()

        structured_inputs = [
            (
                "身体感受 Body Sensation:",
                self.body_input,
                "例如：胸口紧绷",
                BODY_SENSATION_PRESETS,
                "常用身体感受 Quick picks:",
            ),
            (
                "触发事件 Trigger:",
                self.trigger_input,
                "例如：会议讨论",
                TRIGGER_PRESETS,
                "常用触发事件 Quick picks:",
            ),
            (
                "需求/界限 Need or Boundary:",
                self.need_input,
                "例如：需要短暂休息",
                NEED_PRESETS,
                "常用需求 Quick picks:",
            ),
        ]

        for (
            label_text,
            line_edit,
            placeholder,
            presets,
            chip_label,
        ) in structured_inputs:
            line_edit.setMaxLength(30)
            line_edit.setPlaceholderText(placeholder)
            row = QHBoxLayout()
            row_label = QLabel(label_text)
            row.addWidget(row_label)
            row.addWidget(line_edit)
            layout.addLayout(row)
            self._add_preset_chip_row(layout, chip_label, presets, line_edit)

        self.text_edit = QTextEdit()
        self.text_edit.textChanged.connect(self.on_text_changed)
        # 优化滚动流畅性
        if hasattr(self.text_edit.verticalScrollBar(), "setSingleStep"):
            self.text_edit.verticalScrollBar().setSingleStep(14)
        layout.addWidget(self.text_edit)

        self.counter = QLabel(f"0 / {ENTRY_CHARACTER_LIMIT}")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.counter)

        reminder_row = QHBoxLayout()
        reminder_label = QLabel("未来提醒 Revisit:")
        reminder_row.addWidget(reminder_label)
        self.reminder_selector = QComboBox()
        self.reminder_selector.addItem("No reminder", userData=0)
        for minutes in (15, 30, 60):
            self.reminder_selector.addItem(f"{minutes} 分钟后提醒", userData=minutes)
        reminder_row.addWidget(self.reminder_selector)
        reminder_row.addStretch()
        layout.addLayout(reminder_row)

        self.save_button = QPushButton("Archive to Journal")
        self.save_button.clicked.connect(self.archive_entry)
        layout.addWidget(self.save_button)

        self.export_button = QPushButton("Export Journal to CSV")
        self.export_button.clicked.connect(self.export_journal)
        layout.addWidget(self.export_button)

        self.history_label = QLabel("回望 Past Entries:")
        layout.addWidget(self.history_label)

        self.history_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 使用 QListView + 自定义 Model 替代 QListWidget
        self.history_list_model = JournalEntryListModel(self)
        self.history_list = QListView()
        self.history_list.setObjectName("HistoryListView")
        self.history_list.setModel(self.history_list_model)
        self.history_list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        # 优化滚动流畅性
        self.history_list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history_list.setUniformItemSizes(False)  # 保持 False 因为条目高度不统一
        # 启用平滑滚动
        if hasattr(self.history_list.verticalScrollBar(), "setSingleStep"):
            self.history_list.verticalScrollBar().setSingleStep(12)
        self.history_list.selectionModel().currentChanged.connect(
            self.on_history_selection_changed
        )
        self.history_splitter.addWidget(self.history_list)

        self.history_detail_widget = QWidget()
        self.history_detail_widget.setObjectName("HistoryDetailCard")
        self.history_detail_layout = QVBoxLayout()
        self.history_detail_layout.setContentsMargins(20, 20, 20, 18)
        self.history_detail_layout.setSpacing(12)
        self.history_detail_widget.setLayout(self.history_detail_layout)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(6)

        intensity_label = QLabel("情绪强度 Intensity:")
        metrics_row.addWidget(intensity_label)
        self.intensity_bar = QProgressBar()
        self.intensity_bar.setRange(0, 10)  # 0-10对应0-5.0
        self.intensity_bar.setValue(0)
        self.intensity_bar.setFormat("0.0 / 5.0")  # 自定义格式以显示小数
        metrics_row.addWidget(self.intensity_bar)

        energy_label = QLabel("能量 Energy:")
        metrics_row.addWidget(energy_label)
        self.energy_bar = QProgressBar()
        self.energy_bar.setRange(0, 10)  # 0-10对应0-5.0
        self.energy_bar.setValue(0)
        self.energy_bar.setFormat("0.0 / 5.0")  # 自定义格式以显示小数
        metrics_row.addWidget(self.energy_bar)

        metrics_row.addStretch()
        self.history_detail_layout.addLayout(metrics_row)

        self.history_content = QTextBrowser()
        self.history_content.setObjectName("HistoryDetailView")
        self.history_content.setOpenExternalLinks(False)
        self.history_content.setReadOnly(True)
        # 优化滚动流畅性
        self.history_content.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        if hasattr(self.history_content.verticalScrollBar(), "setSingleStep"):
            self.history_content.verticalScrollBar().setSingleStep(16)
        self.history_detail_layout.addWidget(self.history_content)

        self.history_splitter.addWidget(self.history_detail_widget)

        self.history_splitter.setMinimumHeight(160)
        self.history_splitter.setStretchFactor(0, 1)
        self.history_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.history_splitter)

        self._apply_shadow(self.history_detail_widget, blur_radius=32, y_offset=10)
        self._apply_shadow(self.history_list, blur_radius=26, y_offset=6)

        self.setLayout(layout)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.tray_icon.setToolTip("DO-NOT-FORGET")

        tray_menu = QMenu(self)
        restore_action = tray_menu.addAction("Restore")
        restore_action.triggered.connect(self.restore_from_tray)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_application)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(GENTLE_REMINDER_INTERVAL_MS)
        self.reminder_timer.timeout.connect(self.show_gentle_reminder)
        self.reminder_timer.setSingleShot(False)

        # Start DB worker thread and wire signals
        self._db_thread = QThread(self)
        self._db_worker = DBWorker()
        self._db_worker.moveToThread(self._db_thread)

        # connect UI requests to worker slots (queued connection ensures thread crossing)
        self.append_request.connect(self._db_worker.append_entry)
        self.load_request.connect(self._db_worker.load_entries)

        # connect worker responses back to UI slots
        self._db_worker.entries_loaded.connect(self._on_entries_loaded)
        self._db_worker.append_failed.connect(self._on_append_failed)
        self._db_worker.load_failed.connect(self._on_load_failed)
        self._db_worker.append_succeeded.connect(self._on_append_succeeded)

        self._db_thread.start()

        # initial async refresh
        self.refresh_history()

    def _add_preset_chip_row(
        self,
        container: QVBoxLayout,
        label_text: str,
        presets: list[str],
        target_input: QLineEdit,
    ) -> None:
        """Render a chip row offering quick preset values for structured fields."""
        if not presets:
            return

        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)

        hint_label = QLabel(label_text)
        hint_label.setObjectName("presetHintLabel")
        chip_row.addWidget(hint_label)

        for preset in presets:
            chip = QPushButton(preset)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setObjectName("presetChip")
            chip.clicked.connect(
                lambda _, value=preset, target=target_input: self._apply_preset_value(
                    target, value
                )
            )
            chip_row.addWidget(chip)

        chip_row.addStretch()
        container.addLayout(chip_row)

    def _apply_preset_value(self, target: QLineEdit, value: str) -> None:
        """Insert preset text into the target input and keep focus for refinement."""
        target.setText(value)
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)
        target.setCursorPosition(len(value))

    @staticmethod
    def _blend_colors(
        base_color: QColor, target_color: QColor, factor: float
    ) -> QColor:
        """Blend two colors, keeping alpha composition."""
        factor = max(0.0, min(1.0, factor))
        r = round(base_color.red() + (target_color.red() - base_color.red()) * factor)
        g = round(
            base_color.green() + (target_color.green() - base_color.green()) * factor
        )
        b = round(
            base_color.blue() + (target_color.blue() - base_color.blue()) * factor
        )
        a = round(
            base_color.alpha() + (target_color.alpha() - base_color.alpha()) * factor
        )
        return QColor(r, g, b, a)

    def _apply_shadow(
        self, target: QWidget, *, blur_radius: int = 24, y_offset: int = 6
    ) -> None:
        """Apply a soft drop shadow to match Fluent cards."""
        if target.graphicsEffect() is not None:
            return
        shadow = QGraphicsDropShadowEffect(target)
        shadow.setBlurRadius(blur_radius)
        shadow.setOffset(0, y_offset)
        shadow.setColor(QColor(0, 0, 0, 45))
        target.setGraphicsEffect(shadow)

    def _apply_fluent_theme(self) -> None:
        """Configure palette and styles to approximate Fluent Design."""
        app = QApplication.instance()
        QApplication.setStyle("Fusion")

        accent_color = QColor(15, 108, 189)
        foreground = QColor(32, 31, 30)
        neutral_window = QColor(243, 242, 241)
        neutral_base = QColor(255, 255, 255)
        subtle_border = QColor(32, 31, 30, 40)

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, neutral_window)
        palette.setColor(QPalette.ColorRole.Base, neutral_base)
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(255, 255, 255, 240))
        palette.setColor(QPalette.ColorRole.Text, foreground)
        palette.setColor(QPalette.ColorRole.WindowText, foreground)
        palette.setColor(QPalette.ColorRole.ButtonText, foreground)
        palette.setColor(QPalette.ColorRole.Button, QColor(255, 255, 255, 245))
        palette.setColor(QPalette.ColorRole.Highlight, accent_color)
        palette.setColor(QPalette.ColorRole.Link, accent_color)
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(0, 87, 158))

        if app is not None and isinstance(app, QApplication):
            app.setPalette(palette)

        self.setPalette(palette)
        self.setFont(QFont("Segoe UI", 10))

        accent_hex = accent_color.name()
        border_rgba = (
            f"rgba({subtle_border.red()}, {subtle_border.green()}, {subtle_border.blue()},"
            f" {subtle_border.alpha()})"
        )
        window_rgba = f"rgba({neutral_window.red()}, {neutral_window.green()}, {neutral_window.blue()}, 230)"
        base_rgba = f"rgba({neutral_base.red()}, {neutral_base.green()}, {neutral_base.blue()}, 240)"

        self.setStyleSheet(
            f"""
            QWidget {{
                background-color: transparent;
                color: {foreground.name()};
                font-family: "Segoe UI", sans-serif;
                font-size: 10pt;
            }}
            QWidget#MemoWindow {{
                background-color: {window_rgba};
            }}
            QLabel {{
                font-weight: 500;
            }}
            QLabel#presetHintLabel {{
                color: rgba(32, 31, 30, 173);
                font-size: 9pt;
                font-weight: 400;
            }}
            QLineEdit, QTextEdit, QTextBrowser {{
                background-color: {base_rgba};
                border: 1px solid {border_rgba};
                border-radius: 10px;
                padding: 8px 12px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border: 2px solid {accent_hex};
            }}
            QTextBrowser {{
                border: 1px solid {border_rgba};
            }}
            QListView#HistoryListView {{
                background-color: {base_rgba};
                border: 1px solid {border_rgba};
                border-radius: 12px;
                padding: 6px;
            }}
            QListView#HistoryListView::item {{
                margin: 4px;
                border-radius: 8px;
                padding: 8px;
            }}
            QListView#HistoryListView::item:selected {{
                background-color: {accent_hex};
                color: white;
            }}
            QPushButton {{
                background-color: {accent_hex};
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 600;
                color: white;
            }}
            QPushButton:hover {{
                background-color: #115ea3;
            }}
            QPushButton:pressed {{
                background-color: #0b4a82;
            }}
            QPushButton#presetChip {{
                background-color: transparent;
                color: {accent_hex};
                border: 1px solid {accent_hex};
                border-radius: 16px;
                padding: 4px 12px;
                font-weight: 500;
            }}
            QPushButton#presetChip:hover {{
                background-color: {accent_hex};
                color: white;
            }}
            QComboBox {{
                background-color: {base_rgba};
                border: 1px solid {border_rgba};
                border-radius: 10px;
                padding: 6px 12px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 28px;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                border-radius: 10px;
                selection-background-color: {accent_hex};
                selection-color: white;
            }}
            QSlider::groove:horizontal {{
                background: rgba(32, 31, 30, 77);
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {accent_hex};
                border-radius: 10px;
                width: 20px;
                margin: -8px 0;
            }}
            QProgressBar {{
                background-color: {base_rgba};
                border: 1px solid {border_rgba};
                border-radius: 8px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 8px;
            }}
            QTextBrowser#HistoryDetailView {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(32, 31, 30, 77);
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(32, 31, 30, 128);
            }}
            QScrollBar::handle:vertical:pressed {{
                background: {accent_hex};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: rgba(32, 31, 30, 77);
                border-radius: 6px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: rgba(32, 31, 30, 128);
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: {accent_hex};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
                background: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """
        )

        self._initial_palette = QPalette(palette)
        self._accent_color = accent_color

    def update_palette_for_mood(self, *_: object) -> None:
        """Blend background color using current intensity and energy sliders."""
        intensity = clamp_scale_value(self.intensity_slider.value())
        energy = clamp_scale_value(self.energy_slider.value())
        blend_ratio = (intensity + energy) / 10.0  # map to 0.2 - 1.0 range
        blend_ratio = max(0.0, min(1.0, blend_ratio))

        base_palette = getattr(self, "_initial_palette", QPalette(self.palette()))
        original_window = base_palette.color(QPalette.ColorRole.Window)
        original_base = base_palette.color(QPalette.ColorRole.Base)
        original_button = base_palette.color(QPalette.ColorRole.Button)
        original_alt = base_palette.color(QPalette.ColorRole.AlternateBase)
        original_highlight = base_palette.color(QPalette.ColorRole.Highlight)

        is_dark_theme = original_window.lightnessF() < 0.45

        if is_dark_theme:
            accent_hue = (0.58 - 0.18 * blend_ratio) % 1.0
            accent_sat = min(0.7, 0.28 + 0.4 * blend_ratio)
            accent_val = min(0.65, 0.35 + 0.25 * blend_ratio)
            accent_color = QColor.fromHsvF(accent_hue, accent_sat, accent_val)
            window_mix = 0.35 + 0.25 * blend_ratio
            base_mix = 0.25 + 0.2 * blend_ratio
            button_mix = 0.3 + 0.2 * blend_ratio
            highlight_mix = 0.55 + 0.25 * blend_ratio
        else:
            accent_hue = 0.08 + (1.0 - blend_ratio) * 0.18
            accent_sat = min(0.6, 0.25 + 0.35 * blend_ratio)
            accent_val = 0.94
            accent_color = QColor.fromHsvF(accent_hue, accent_sat, accent_val)
            window_mix = 0.6
            base_mix = 0.55
            button_mix = 0.5
            highlight_mix = 0.7

        alternate_mix = max(0.15, base_mix - 0.1)

        palette = QPalette(base_palette)
        palette.setColor(
            QPalette.ColorRole.Window,
            self._blend_colors(original_window, accent_color, window_mix),
        )
        palette.setColor(
            QPalette.ColorRole.Base,
            self._blend_colors(original_base, accent_color, base_mix),
        )
        palette.setColor(
            QPalette.ColorRole.Button,
            self._blend_colors(original_button, accent_color, button_mix),
        )
        palette.setColor(
            QPalette.ColorRole.AlternateBase,
            self._blend_colors(original_alt, accent_color, alternate_mix),
        )

        highlight_color = self._blend_colors(
            original_highlight, accent_color, highlight_mix
        )
        if is_dark_theme:
            highlight_color = highlight_color.lighter(125)
        else:
            highlight_color = highlight_color.darker(110)

        palette.setColor(QPalette.ColorRole.Highlight, highlight_color)
        palette.setColor(QPalette.ColorRole.Link, highlight_color)
        palette.setColor(QPalette.ColorRole.LinkVisited, highlight_color.darker(110))

        self.setPalette(palette)
        self.update()

    def on_text_changed(self) -> None:
        """Handle text input changes and enforce character limit."""
        text = self.text_edit.toPlainText()
        if len(text) > ENTRY_CHARACTER_LIMIT:
            cursor = self.text_edit.textCursor()
            position = cursor.position()

            self.text_edit.blockSignals(True)
            self.text_edit.setPlainText(text[:ENTRY_CHARACTER_LIMIT])
            self.text_edit.blockSignals(False)

            cursor.setPosition(min(position, ENTRY_CHARACTER_LIMIT))
            self.text_edit.setTextCursor(cursor)
            text = self.text_edit.toPlainText()

        self.counter.setText(f"{len(text)} / {ENTRY_CHARACTER_LIMIT}")

    def on_intensity_value_changed(self, value: int) -> None:
        """Update intensity value label when slider changes."""
        # 将内部值(2-10)转换为显示值(1.0-5.0)
        display_value = value / 2.0
        self.intensity_value_label.setText(f"{display_value:.1f}")

    def on_intensity_slider_released(self) -> None:
        """吸附到最近的档位(整数或0.5)当滑块释放时。"""
        current = self.intensity_slider.value()
        # 吸附到最近的偶数或奇数(对应整数或0.5档位)
        snapped = round(current)
        if snapped != current:
            self.intensity_slider.setValue(snapped)

    def on_energy_value_changed(self, value: int) -> None:
        """Update energy value label when slider changes."""
        # 将内部值(2-10)转换为显示值(1.0-5.0)
        display_value = value / 2.0
        self.energy_value_label.setText(f"{display_value:.1f}")

    def on_energy_slider_released(self) -> None:
        """吸附到最近的档位(整数或0.5)当滑块释放时。"""
        current = self.energy_slider.value()
        # 吸附到最近的整数档位
        snapped = round(current)
        if snapped != current:
            self.energy_slider.setValue(snapped)

    def archive_entry(self) -> None:
        """Save the current entry to the journal database."""
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                self, "Empty Entry", "Please enter some text before archiving."
            )
            return

        if len(text) > ENTRY_CHARACTER_LIMIT:
            text = text[:ENTRY_CHARACTER_LIMIT]

        self._pending_entry_preview = text
        mood = self.mood_selector.currentData() or "unspecified"
        body_sensation = self.body_input.text().strip()
        trigger_event = self.trigger_input.text().strip()
        need_boundary = self.need_input.text().strip()
        # 将滑块值(2-10)转换为实际值(1.0-5.0)
        intensity_value = self.intensity_slider.value() / 2.0
        energy_value = self.energy_slider.value() / 2.0
        # send append request to DB worker; it will reload entries and emit them
        payload = {
            "text": text,
            "mood": mood,
            "db_path": DATABASE_PATH,
            "body_sensation": body_sensation,
            "trigger_event": trigger_event,
            "need_boundary": need_boundary,
            "emotion_intensity": intensity_value,
            "energy_level": energy_value,
        }

        # optimistically disable save to avoid duplicate clicks while background write runs
        self.save_button.setEnabled(False)
        self.append_request.emit(payload)

    def notify_entry_archived(self) -> None:
        """Send a lightweight confirmation when an entry is saved."""
        notification_body = f"Entry archived to {DATABASE_PATH.resolve()}"

        if QSystemTrayIcon.isSystemTrayAvailable():
            icon_was_visible = self.tray_icon.isVisible()

            if not icon_was_visible:
                self.tray_icon.show()

            self.tray_icon.showMessage(
                "DO-NOT-FORGET",
                notification_body,
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )

            if not icon_was_visible:
                QTimer.singleShot(2600, self.tray_icon.hide)
        else:
            logging.info(notification_body)

    def minimize_to_tray(self) -> None:
        """Minimize the window to system tray."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.quit_application()
            return

        if not self.tray_icon.isVisible():
            self.tray_icon.show()
            self.tray_icon.showMessage(
                "DO-NOT-FORGET",
                "Memo pad is resting in the tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        if not self.reminder_timer.isActive():
            self.reminder_timer.start()
        self.hide()

    def restore_from_tray(self) -> None:
        """Restore the window from system tray."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tray_icon.hide()
        if self.reminder_timer.isActive():
            self.reminder_timer.stop()

    def quit_application(self) -> None:
        """Clean up and exit the application."""
        if self.reminder_timer.isActive():
            self.reminder_timer.stop()
        self.tray_icon.hide()
        # stop DB worker thread cleanly
        try:
            if hasattr(self, "_db_thread") and self._db_thread.isRunning():
                self._db_thread.quit()
                self._db_thread.wait(2000)
        except Exception:
            logging.exception("Failed to stop DB worker thread cleanly")

        app = QApplication.instance()
        if app is not None:
            app.quit()

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle system tray icon activation."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event - minimize to tray instead of exiting."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.minimize_to_tray()
        else:
            super().closeEvent(event)

    def show_gentle_reminder(self) -> None:
        """Show a periodic reminder notification."""
        if self.tray_icon.isVisible() and self.isHidden():
            self.tray_icon.showMessage(
                "DO-NOT-FORGET",
                "Capture the feeling worth keeping.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def is_dark_theme(self) -> bool:
        """Check the current palette to decide whether to render dark-mode art."""
        palette = self.history_content.palette()
        base_lightness = palette.color(QPalette.ColorRole.Base).lightnessF()
        window_lightness = palette.color(QPalette.ColorRole.Window).lightnessF()
        return min(base_lightness, window_lightness) < 0.5

    def refresh_history(self) -> None:
        """Refresh the history list.

        On the first call it loads entries from the database and caches them;subsequent calls use the cached data to avoid DB queries.
        When new entries are added, the cache is updated incrementally so refresh_history becomes an O(1) operation.
        """
        # request background load; UI will be updated by _on_entries_loaded
        self.load_request.emit(None)

    # ---- background worker callbacks ----
    @Slot(object)
    def _on_entries_loaded(self, entries) -> None:
        """Receive entries from worker, update cache and list in UI thread."""
        # update cache safely in UI thread
        try:
            if entries:
                self._entry_cache.load_all(entries)
        except Exception:
            logging.exception("Failed to update entry cache with loaded entries")

        # 使用 Model 更新列表，实现虚拟化渲染
        if not entries:
            self.history_list_model.clear()
            self.history_content.setHtml(
                render_empty_history_html(self.is_dark_theme())
            )
            self.intensity_bar.setValue(0)
            self.energy_bar.setValue(0)
            return

        self.history_list_model.set_entries(entries)

        # 选中第一项
        if self.history_list_model.rowCount() > 0:
            first_index = self.history_list_model.index(0, 0)
            self.history_list.setCurrentIndex(first_index)

    @Slot(str)
    def _on_append_failed(self, message: str) -> None:
        logging.error("Append failed: %s", message)
        QMessageBox.critical(self, "Archive Failed", f"Could not save entry: {message}")
        self.save_button.setEnabled(True)

    @Slot(str)
    def _on_load_failed(self, message: str) -> None:
        logging.error("Load failed: %s", message)
        QMessageBox.critical(self, "Load Failed", f"Could not load entries: {message}")

    @Slot()
    def _on_append_succeeded(self) -> None:
        # re-enable save button and clear inputs on successful append
        self.save_button.setEnabled(True)
        self.notify_entry_archived()

        delay_minutes = int(self.reminder_selector.currentData() or 0)
        preview = " ".join(getattr(self, "_pending_entry_preview", "").split())

        if delay_minutes > 0:
            if not preview:
                reminder_text = "回来看刚刚写下的那句话吧。"
            elif len(preview) > 60:
                reminder_text = preview[:59] + "…"
            else:
                reminder_text = preview

            def _fire_future_reminder(message: str = reminder_text) -> None:
                """Emit a gentle tray reminder referencing the saved snippet."""
                if not QSystemTrayIcon.isSystemTrayAvailable():
                    logging.info("Future reminder: %s", message)
                    return

                icon_was_visible = self.tray_icon.isVisible()
                if not icon_was_visible:
                    self.tray_icon.show()

                self.tray_icon.showMessage(
                    "未来的你 Future You",
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )

                if not icon_was_visible:
                    QTimer.singleShot(4200, self.tray_icon.hide)

            QTimer.singleShot(delay_minutes * 60_000, _fire_future_reminder)

        self.reminder_selector.setCurrentIndex(0)
        self._pending_entry_preview = ""

        self.text_edit.clear()
        self.body_input.clear()
        self.trigger_input.clear()
        self.need_input.clear()
        self.intensity_slider.setValue(3)
        self.energy_slider.setValue(3)

    def on_history_selection_changed(
        self, current: QModelIndex, previous: QModelIndex
    ) -> None:
        """Handle selection changes in history list."""
        if not current.isValid():
            self.history_content.setHtml(
                render_empty_history_html(self.is_dark_theme())
            )
            self.intensity_bar.setValue(0)
            self.energy_bar.setValue(0)
            return

        entry = self.history_list_model.get_entry(current)
        if entry is None:
            self.history_content.setHtml(
                render_empty_history_html(self.is_dark_theme())
            )
            self.intensity_bar.setValue(0)
            self.energy_bar.setValue(0)
            return

        self.history_content.setHtml(
            render_entry_detail_html(entry, self.is_dark_theme())
        )
        # 将浮点值(1.0-5.0)转换为进度条值(2-10)
        intensity_bar_value = int(clamp_scale_value(entry.emotion_intensity) * 2)
        energy_bar_value = int(clamp_scale_value(entry.energy_level) * 2)
        self.intensity_bar.setValue(intensity_bar_value)
        self.intensity_bar.setFormat(f"{entry.emotion_intensity:.1f} / 5.0")
        self.energy_bar.setValue(energy_bar_value)
        self.energy_bar.setFormat(f"{entry.energy_level:.1f} / 5.0")

    def export_journal(self) -> None:
        """Export journal entries to a CSV file."""
        suggested_name = (
            f"journal-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        )
        default_path = str(Path.home() / suggested_name)

        target_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Export Journal to CSV",
            default_path,
            "CSV Files (*.csv);;All Files (*)",
        )

        if not target_path_str:
            return

        target_path = Path(target_path_str)

        try:
            exported_rows = export_journal_to_csv(DATABASE_PATH, target_path)
        except Exception as exc:  # surfacing rare export failures
            logging.exception("Journal export failed")
            QMessageBox.critical(
                self, "Export Failed", f"Could not export journal: {exc}"
            )
            return

        if exported_rows == 0:
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported an empty journal to {target_path.resolve()}",
            )
        else:
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {exported_rows} entries to {target_path.resolve()}",
            )
