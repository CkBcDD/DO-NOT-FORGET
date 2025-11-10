from __future__ import annotations

import csv
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
DATABASE_PATH = Path("journal.sqlite3")
LEGACY_JSON_PATH = Path("journal.json")
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

# Basic logging for debugging and operational visibility
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


@dataclass
class JournalEntry:
    id: int
    timestamp: str
    mood: str
    text: str
    body_sensation: str = ""
    trigger_event: str = ""
    need_boundary: str = ""


def initialize_storage(db_path: Path, legacy_json_path: Path) -> None:
    """Ensure the SQLite storage exists and migrate legacy JSON if present."""

    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moments (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    mood TEXT NOT NULL,
                    text TEXT NOT NULL,
                    body_sensation TEXT NOT NULL DEFAULT '',
                    trigger_event TEXT NOT NULL DEFAULT '',
                    need_boundary TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_moments_timestamp ON moments(timestamp)"
            )
            ensure_structured_fields(conn)
    except sqlite3.DatabaseError:
        logging.exception("Failed to initialize journal database at %s", db_path)
        raise

    migrate_legacy_json(legacy_json_path, db_path)


def ensure_structured_fields(conn: sqlite3.Connection) -> None:
    """Ensure newly added structured feeling columns exist on the moments table."""

    try:
        columns = {
            column_info[1]
            for column_info in conn.execute("PRAGMA table_info(moments)").fetchall()
        }
    except sqlite3.DatabaseError:
        logging.exception("Failed to inspect journal database schema.")
        raise

    column_specs = {
        "body_sensation": "ALTER TABLE moments ADD COLUMN body_sensation TEXT NOT NULL DEFAULT ''",
        "trigger_event": "ALTER TABLE moments ADD COLUMN trigger_event TEXT NOT NULL DEFAULT ''",
        "need_boundary": "ALTER TABLE moments ADD COLUMN need_boundary TEXT NOT NULL DEFAULT ''",
    }

    for column_name, alter_sql in column_specs.items():
        if column_name in columns:
            continue
        try:
            conn.execute(alter_sql)
        except sqlite3.DatabaseError:
            logging.exception(
                "Failed to add column %s to journal database.", column_name
            )
            raise


def migrate_legacy_json(json_path: Path, db_path: Path) -> None:
    """Import legacy JSON moments into SQLite, preserving the original file."""

    if not json_path.exists() or json_path.stat().st_size == 0:
        return

    try:
        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        logging.exception("Failed to read legacy journal JSON from %s", json_path)
        return

    raw_moments = data.get("moments", []) if isinstance(data, dict) else []
    payload: list[tuple[int, str, str, str, str, str, str]] = []
    for entry in raw_moments:
        if not isinstance(entry, dict):
            continue
        try:
            entry_id = int(entry.get("id", 0)) if entry.get("id") is not None else 0
            timestamp = str(entry.get("timestamp", ""))
            mood = str(entry.get("mood", "unspecified"))
            text = str(entry.get("text", ""))
            body_sensation = entry.get("body_sensation") or ""
            trigger_event = entry.get("trigger_event") or ""
            need_boundary = entry.get("need_boundary") or ""
            if not isinstance(body_sensation, str):
                body_sensation = str(body_sensation)
            if not isinstance(trigger_event, str):
                trigger_event = str(trigger_event)
            if not isinstance(need_boundary, str):
                need_boundary = str(need_boundary)
            body_sensation = body_sensation.strip()[:30]
            trigger_event = trigger_event.strip()[:30]
            need_boundary = need_boundary.strip()[:30]
        except (TypeError, ValueError):
            logging.exception(
                "Skipping invalid legacy entry during migration: %s", entry
            )
            continue
        payload.append(
            (
                entry_id,
                timestamp,
                mood,
                text,
                body_sensation,
                trigger_event,
                need_boundary,
            )
        )

    if not payload:
        return

    try:
        with sqlite3.connect(db_path) as conn:
            existing = conn.execute("SELECT COUNT(*) FROM moments").fetchone()[0]
            if existing:
                logging.info("Skipping legacy migration; database already has entries.")
                return
            conn.executemany(
                """
                INSERT OR IGNORE INTO moments (
                    id,
                    timestamp,
                    mood,
                    text,
                    body_sensation,
                    trigger_event,
                    need_boundary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            logging.info(
                "Migrated %d legacy journal entries into SQLite storage.", len(payload)
            )
    except sqlite3.DatabaseError:
        logging.exception("Failed to migrate legacy JSON moments into SQLite.")


def append_entry_to_journal(
    text: str,
    mood: str,
    db_path: Path,
    body_sensation: str = "",
    trigger_event: str = "",
    need_boundary: str = "",
) -> None:
    """Persist a new journal entry into the SQLite database."""

    now = datetime.now().astimezone()
    timestamp = now.isoformat(timespec="seconds")
    entry_id = int(now.timestamp() * 1000)

    body_sensation = ((body_sensation or "").strip())[:30]
    trigger_event = ((trigger_event or "").strip())[:30]
    need_boundary = ((need_boundary or "").strip())[:30]

    new_entry = JournalEntry(
        id=entry_id,
        timestamp=timestamp,
        mood=mood,
        text=text,
        body_sensation=body_sensation,
        trigger_event=trigger_event,
        need_boundary=need_boundary,
    )

    try:
        with sqlite3.connect(db_path) as conn:
            for attempt in range(3):
                try:
                    conn.execute(
                        """
                        INSERT INTO moments (
                            id,
                            timestamp,
                            mood,
                            text,
                            body_sensation,
                            trigger_event,
                            need_boundary
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_entry.id,
                            new_entry.timestamp,
                            new_entry.mood,
                            new_entry.text,
                            new_entry.body_sensation,
                            new_entry.trigger_event,
                            new_entry.need_boundary,
                        ),
                    )
                    break
                except sqlite3.IntegrityError:
                    new_entry.id += 1
            else:
                raise sqlite3.IntegrityError(
                    "Failed to generate unique journal entry ID"
                )
    except sqlite3.DatabaseError:
        logging.exception("Failed to append journal entry to database.")
        raise


def load_journal_entries(db_path: Path) -> list[JournalEntry]:
    """Load journal entries from SQLite ordered by timestamp descending."""

    if not db_path.exists():
        return []

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    id,
                    timestamp,
                    mood,
                    text,
                    body_sensation,
                    trigger_event,
                    need_boundary
                FROM moments
                ORDER BY timestamp DESC, id DESC
                """
            ).fetchall()
    except sqlite3.DatabaseError:
        logging.exception("Failed to load journal entries from SQLite.")
        return []

    entries: list[JournalEntry] = []
    for row in rows:
        try:
            entries.append(
                JournalEntry(
                    id=int(row["id"]) if row["id"] is not None else 0,
                    timestamp=str(row["timestamp"] or ""),
                    mood=str(row["mood"] or "unspecified"),
                    text=str(row["text"] or ""),
                    body_sensation=str(row["body_sensation"] or ""),
                    trigger_event=str(row["trigger_event"] or ""),
                    need_boundary=str(row["need_boundary"] or ""),
                )
            )
        except (TypeError, ValueError):
            logging.exception("Skipping malformed database row: %s", dict(row))

    return entries


def export_journal_to_csv(db_path: Path, csv_path: Path) -> int:
    """Write journal entries to a CSV file and return the number of rows exported."""

    entries = load_journal_entries(db_path)

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "id",
                    "timestamp",
                    "mood",
                    "text",
                    "body_sensation",
                    "trigger_event",
                    "need_boundary",
                ]
            )
            for entry in reversed(entries):
                writer.writerow(
                    [
                        entry.id,
                        entry.timestamp,
                        entry.mood,
                        entry.text,
                        entry.body_sensation,
                        entry.trigger_event,
                        entry.need_boundary,
                    ]
                )
    except OSError:
        logging.exception("Failed to write journal CSV export to %s", csv_path)
        raise

    return len(entries)


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
        try:
            append_entry_to_journal(
                text,
                mood,
                DATABASE_PATH,
                body_sensation=body_sensation,
                trigger_event=trigger_event,
                need_boundary=need_boundary,
            )
        except Exception as exc:  # broad catch to surface unexpected errors
            logging.exception("Failed to archive entry")
            QMessageBox.critical(self, "Archive Failed", f"Could not save file: {exc}")
            return

        QMessageBox.information(
            self, "Archived", f"Entry archived to {DATABASE_PATH.resolve()}"
        )

        self.text_edit.clear()
        self.body_input.clear()
        self.trigger_input.clear()
        self.need_input.clear()
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
        entries = load_journal_entries(DATABASE_PATH)

        self.history_list.blockSignals(True)
        self.history_list.clear()

        for entry in entries:
            preview = " ".join(entry.text.strip().split())
            if len(preview) > 48:
                preview = preview[:47] + "…"
            display_lines = [
                entry.timestamp or str(entry.id),
                f"情绪 Mood: {entry.mood}",
            ]
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
                display_lines.append(f"结构 Structured: {structured_preview}")
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

        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry is None:
            self.history_content.setPlainText("还没有记录。")
            return

        timestamp = entry.timestamp or str(entry.id)
        mood = entry.mood
        text = entry.text
        entry_id = entry.id

        detail_lines = [timestamp, f"情绪 Mood: {mood}"]
        if entry.body_sensation.strip():
            detail_lines.append(
                f"身体感受 Body Sensation: {entry.body_sensation.strip()}"
            )
        if entry.trigger_event.strip():
            detail_lines.append(f"触发事件 Trigger: {entry.trigger_event.strip()}")
        if entry.need_boundary.strip():
            detail_lines.append(
                f"需求/界限 Need or Boundary: {entry.need_boundary.strip()}"
            )
        if entry_id:
            detail_lines.append(f"ID: {entry_id}")
        detail_lines.append("")
        detail_lines.append(text)

        self.history_content.setPlainText("\n".join(detail_lines))

    def export_journal(self) -> None:
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


def main() -> int:
    initialize_storage(DATABASE_PATH, LEGACY_JSON_PATH)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MemoWindow()
    window.resize(520, 520)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
