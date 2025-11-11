"""Main entry point for the DO-NOT-FORGET journal application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.constants import DATABASE_PATH, LEGACY_JSON_PATH
from src.storage import initialize_storage
from src.ui import MemoWindow


def main() -> int:
    """Initialize the database and launch the application."""
    initialize_storage(DATABASE_PATH, LEGACY_JSON_PATH)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MemoWindow()
    window.resize(520, 520)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
