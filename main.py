from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

ENTRY_CHARACTER_LIMIT = 100
JOURNAL_PATH = Path("journal.json")
GENTLE_REMINDER_INTERVAL_MS = 10 * 60 * 1000
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


def append_entry_to_journal(text: str, mood: str, path: Path) -> None:
    now = datetime.now().astimezone()
    timestamp = now.isoformat(timespec="seconds")
    entry_id = int(now.timestamp())

    new_entry = {"id": entry_id, "timestamp": timestamp, "mood": mood, "text": text}

    # Load existing moments
    moments = []
    if path.exists() and path.stat().st_size > 0:
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                moments = data.get("moments", [])
        except (OSError, json.JSONDecodeError):
            moments = []

    # Append new moment
    moments.append(new_entry)

    # Save back to file
    data = {"moments": moments}
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_journal_entries(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    raw_moments = data.get("moments", [])
    entries: list[dict[str, str]] = []
    for entry in raw_moments:
        if not isinstance(entry, dict):
            continue
        entries.append(
            {
                "id": str(entry.get("id", "")),
                "timestamp": str(entry.get("timestamp", "")),
                "mood": str(entry.get("mood", "unspecified")),
                "text": str(entry.get("text", "")),
            }
        )

    entries.sort(key=lambda item: item["timestamp"] or item["id"], reverse=True)
    return entries


class MemoWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DO-NOT-FORGET Memo Pad")

        layout = QVBoxLayout()

        self.instructions = QLabel("Anchor this moment (<=100 chars):")
        layout.addWidget(self.instructions)

        self.mood_label = QLabel("情绪 Mood:")
        layout.addWidget(self.mood_label)

        self.mood_selector = QComboBox()
        for label, value in MOOD_CHOICES:
            self.mood_selector.addItem(label, userData=value)
        layout.addWidget(self.mood_selector)

        self.text_edit = QTextEdit()
        self.text_edit.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.text_edit)

        self.counter = QLabel(f"0 / {ENTRY_CHARACTER_LIMIT}")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.counter)

        self.save_button = QPushButton("Archive to JSON")
        self.save_button.clicked.connect(self.archive_entry)
        layout.addWidget(self.save_button)

        self.history_label = QLabel("回望 Past Entries:")
        layout.addWidget(self.history_label)

        self.history_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.history_list = QListWidget()
        self.history_list.itemSelectionChanged.connect(
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

        self.refresh_history()

    def on_text_changed(self) -> None:
        text = self.text_edit.toPlainText()
        if len(text) > ENTRY_CHARACTER_LIMIT:
            cursor = self.text_edit.textCursor()
            position = cursor.position()

            # Protect against recursive signal emission while truncating text
            self.text_edit.blockSignals(True)
            self.text_edit.setPlainText(text[:ENTRY_CHARACTER_LIMIT])
            self.text_edit.blockSignals(False)

            cursor.setPosition(min(position, ENTRY_CHARACTER_LIMIT))
            self.text_edit.setTextCursor(cursor)
            text = self.text_edit.toPlainText()

        self.counter.setText(f"{len(text)} / {ENTRY_CHARACTER_LIMIT}")

    def archive_entry(self) -> None:
        text = self.text_edit.toPlainText()
        mood = self.mood_selector.currentData() or "unspecified"
        try:
            append_entry_to_journal(text, mood, JOURNAL_PATH)
        except OSError as exc:
            QMessageBox.critical(self, "Archive Failed", f"Could not save file: {exc}")
            return

        QMessageBox.information(
            self, "Archived", f"Entry archived to {JOURNAL_PATH.resolve()}"
        )

        self.text_edit.clear()
        self.refresh_history()

    def minimize_to_tray(self) -> None:
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
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tray_icon.hide()
        if self.reminder_timer.isActive():
            self.reminder_timer.stop()

    def quit_application(self) -> None:
        if self.reminder_timer.isActive():
            self.reminder_timer.stop()
        self.tray_icon.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def closeEvent(self, event: QCloseEvent) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.minimize_to_tray()
        else:
            super().closeEvent(event)

    def show_gentle_reminder(self) -> None:
        if self.tray_icon.isVisible() and self.isHidden():
            self.tray_icon.showMessage(
                "DO-NOT-FORGET",
                "Capture the feeling worth keeping.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def refresh_history(self) -> None:
        entries = load_journal_entries(JOURNAL_PATH)

        self.history_list.blockSignals(True)
        self.history_list.clear()

        for entry in entries:
            preview = " ".join(entry["text"].strip().split())
            if len(preview) > 48:
                preview = preview[:47] + "…"
            display_lines = [
                entry["timestamp"] or entry["id"],
                f"情绪 Mood: {entry['mood']}",
            ]
            if preview:
                display_lines.append(preview)
            item = QListWidgetItem("\n".join(display_lines))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.history_list.addItem(item)

        self.history_list.blockSignals(False)

        if entries:
            self.history_list.setCurrentRow(0)
        else:
            self.history_content.setPlainText("还没有记录。")

    def on_history_selection_changed(self) -> None:
        item = self.history_list.currentItem()
        if item is None:
            self.history_content.setPlainText("还没有记录。")
            return

        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        timestamp = entry.get("timestamp", "") or entry.get("id", "")
        mood = entry.get("mood", "unspecified")
        text = entry.get("text", "")
        entry_id = entry.get("id", "")

        detail_lines = [timestamp, f"情绪 Mood: {mood}"]
        if entry_id:
            detail_lines.append(f"ID: {entry_id}")
        detail_lines.append("")
        detail_lines.append(text)

        self.history_content.setPlainText("\n".join(detail_lines))


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MemoWindow()
    window.resize(520, 520)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
