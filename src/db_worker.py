"""Background database worker running in its own QThread.

This module exposes DBWorker, a QObject that performs storage operations
off the UI thread and emits signals with results. The worker intentionally
does not update the UI-thread cache; instead it returns loaded data which
the main thread should use to update its cache and widgets.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from src import storage
from src.constants import DATABASE_PATH


class DBWorker(QObject):
    """Worker running in a dedicated QThread to perform DB tasks.

    Signals:
        entries_loaded: emitted with list[JournalEntry] when load completes
        append_failed: emitted with str message when append fails
        load_failed: emitted with str message when load fails
        append_succeeded: emitted with no args when append succeeded
    """

    entries_loaded = Signal(object)  # will send list[JournalEntry]
    append_failed = Signal(str)
    load_failed = Signal(str)
    append_succeeded = Signal()

    def __init__(self) -> None:
        super().__init__()

    @Slot(object)
    def load_entries(self, payload=None) -> None:
        """Load entries from DB (runs in worker thread) and emit results.

        payload is unused but accepted so connections can pass a dummy arg.
        """
        try:
            # determine db_path: payload may contain a Path or None -> fallback to constants
            db_path = payload if isinstance(payload, Path) else DATABASE_PATH
            entries = storage.load_journal_entries(db_path)
        except Exception as exc:  # defensive: emit failure and return
            logging.exception("DBWorker failed to load entries")
            try:
                self.load_failed.emit(str(exc))
            except Exception:
                pass
            return

        # emit loaded entries to UI thread
        try:
            self.entries_loaded.emit(entries)
        except Exception:
            logging.exception("Failed to emit entries_loaded signal")

    @Slot(object)
    def append_entry(self, payload) -> None:
        """Append an entry to DB using a payload dict; then load entries.

        The payload should contain the same args that storage.append_entry_to_journal
        expects (text, mood, db_path, body_sensation, trigger_event,
        need_boundary, emotion_intensity, energy_level).
        """
        try:
            # defensively unpack expected fields from payload
            text = payload.get("text")
            mood = payload.get("mood")
            db_path = payload.get("db_path")
            body_sensation = payload.get("body_sensation", "")
            trigger_event = payload.get("trigger_event", "")
            need_boundary = payload.get("need_boundary", "")
            emotion_intensity = int(payload.get("emotion_intensity", 3))
            energy_level = int(payload.get("energy_level", 3))

            # call storage append but do NOT provide the UI cache (avoid cross-thread mutation)
            storage.append_entry_to_journal(
                text,
                mood,
                db_path,
                body_sensation=body_sensation,
                trigger_event=trigger_event,
                need_boundary=need_boundary,
                emotion_intensity=emotion_intensity,
                energy_level=energy_level,
                cache=None,
            )
        except Exception as exc:
            logging.exception("DBWorker failed to append entry")
            try:
                self.append_failed.emit(str(exc))
            except Exception:
                pass
            return

        # notify success and then refresh entries list
        try:
            self.append_succeeded.emit()
        except Exception:
            logging.exception("Failed to emit append_succeeded")

        # reload entries and emit them (so UI can update cache and list)
        try:
            entries = storage.load_journal_entries(db_path)
            self.entries_loaded.emit(entries)
        except Exception as exc:
            logging.exception("DBWorker failed to reload after append")
            try:
                self.load_failed.emit(str(exc))
            except Exception:
                pass
