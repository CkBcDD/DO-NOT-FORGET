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
from PySide6.QtGui import QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
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

        self._entry_cache = EntryCache()

        layout = QVBoxLayout()

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
            slider.setRange(1, 5)
            slider.setTickInterval(1)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setValue(3)
            slider.setToolTip(tooltip)

            value_label = QLabel(str(slider.value()))
            value_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            value_label.setMinimumWidth(24)

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

        self.energy_slider, self.energy_value_label = _add_slider_row(
            "能量水平 Energy (1–5):", "记录当下的能量充沛度，1=低能量，5=高能量"
        )
        self.energy_slider.valueChanged.connect(self.on_energy_value_changed)

        self.body_input = QLineEdit()
        self.trigger_input = QLineEdit()
        self.need_input = QLineEdit()

        structured_inputs = [
            ("身体感受 Body Sensation:", self.body_input, "例如：胸口紧绷"),
            ("触发事件 Trigger:", self.trigger_input, "例如：会议讨论"),
            ("需求/界限 Need or Boundary:", self.need_input, "例如：需要短暂休息"),
        ]

        for label_text, line_edit, placeholder in structured_inputs:
            line_edit.setMaxLength(30)
            line_edit.setPlaceholderText(placeholder)
            row = QHBoxLayout()
            row_label = QLabel(label_text)
            row.addWidget(row_label)
            row.addWidget(line_edit)
            layout.addLayout(row)

        self.text_edit = QTextEdit()
        self.text_edit.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.text_edit)

        self.counter = QLabel(f"0 / {ENTRY_CHARACTER_LIMIT}")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.counter)

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
        self.history_list.setModel(self.history_list_model)
        self.history_list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.history_list.selectionModel().currentChanged.connect(
            self.on_history_selection_changed
        )
        self.history_splitter.addWidget(self.history_list)

        self.history_content = QTextBrowser()
        self.history_content.setOpenExternalLinks(False)
        self.history_content.setReadOnly(True)
        self.history_splitter.addWidget(self.history_content)

        self.history_splitter.setMinimumHeight(160)
        self.history_splitter.setStretchFactor(0, 1)
        self.history_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.history_splitter)

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
        self.intensity_value_label.setText(str(clamp_scale_value(value)))

    def on_energy_value_changed(self, value: int) -> None:
        """Update energy value label when slider changes."""
        self.energy_value_label.setText(str(clamp_scale_value(value)))

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

        mood = self.mood_selector.currentData() or "unspecified"
        body_sensation = self.body_input.text().strip()
        trigger_event = self.trigger_input.text().strip()
        need_boundary = self.need_input.text().strip()
        # send append request to DB worker; it will reload entries and emit them
        payload = {
            "text": text,
            "mood": mood,
            "db_path": DATABASE_PATH,
            "body_sensation": body_sensation,
            "trigger_event": trigger_event,
            "need_boundary": need_boundary,
            "emotion_intensity": self.intensity_slider.value(),
            "energy_level": self.energy_slider.value(),
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
            return

        entry = self.history_list_model.get_entry(current)
        if entry is None:
            self.history_content.setHtml(
                render_empty_history_html(self.is_dark_theme())
            )
            return

        self.history_content.setHtml(
            render_entry_detail_html(entry, self.is_dark_theme())
        )

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
