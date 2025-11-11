"""Database operations and data persistence."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from pathlib import Path

from src.models import EntryCache, JournalEntry
from src.utils import clamp_scale_value


def apply_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    """Apply recommended PRAGMA tunings to an open SQLite connection.

    This centralizes the WAL and sync/temp_store settings so all code paths
    opening the DB get consistent behavior.
    """
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        logging.info(
            "Applied SQLite PRAGMAs: journal_mode=WAL, synchronous=NORMAL, temp_store=MEMORY"
        )
    except sqlite3.DatabaseError:
        logging.exception("Failed to apply SQLite PRAGMA settings.")


def initialize_storage(db_path: Path, legacy_json_path: Path) -> None:
    """Ensure the SQLite storage exists and migrate legacy JSON if present."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(db_path) as conn:
            # Apply centralized PRAGMA optimizations so schema creation and
            # subsequent operations use WAL and tuned sync/temp_store settings.
            apply_sqlite_pragmas(conn)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moments (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    mood TEXT NOT NULL,
                    text TEXT NOT NULL,
                    body_sensation TEXT NOT NULL DEFAULT '',
                    trigger_event TEXT NOT NULL DEFAULT '',
                    need_boundary TEXT NOT NULL DEFAULT '',
                    emotion_intensity INTEGER NOT NULL DEFAULT 3,
                    energy_level INTEGER NOT NULL DEFAULT 3
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
        "emotion_intensity": "ALTER TABLE moments ADD COLUMN emotion_intensity INTEGER NOT NULL DEFAULT 3",
        "energy_level": "ALTER TABLE moments ADD COLUMN energy_level INTEGER NOT NULL DEFAULT 3",
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
    payload: list[tuple[int, str, str, str, str, str, str, int, int]] = []
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
            emotion_intensity = clamp_scale_value(entry.get("emotion_intensity"), 3)
            energy_level = clamp_scale_value(entry.get("energy_level"), 3)
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
                emotion_intensity,
                energy_level,
            )
        )

    if not payload:
        return

    try:
        with sqlite3.connect(db_path) as conn:
            # ensure the connection benefits from performance tuning for writes
            apply_sqlite_pragmas(conn)
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
                    need_boundary,
                    emotion_intensity,
                    energy_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    emotion_intensity: int = 3,
    energy_level: int = 3,
    cache: EntryCache | None = None,
) -> None:
    """将新的 journal 条目持久化到 SQLite 数据库。

    如果提供了缓存对象，会自动将新条目添加到缓存中，避免下次 refresh 时的 DB 查询。

    Args:
        text: 条目内容文本
        mood: 心情标签
        db_path: 数据库路径
        body_sensation: 身体感受
        trigger_event: 触发事件
        need_boundary: 需求/界限
        emotion_intensity: 情绪强度 (1-5)
        energy_level: 能量水平 (1-5)
        cache: 可选缓存对象，用于增量更新
    """
    from datetime import datetime

    now = datetime.now().astimezone()
    timestamp = now.isoformat(timespec="seconds")
    entry_id = int(now.timestamp() * 1000)

    body_sensation = ((body_sensation or "").strip())[:30]
    trigger_event = ((trigger_event or "").strip())[:30]
    need_boundary = ((need_boundary or "").strip())[:30]
    intensity_value = clamp_scale_value(emotion_intensity)
    energy_value = clamp_scale_value(energy_level)

    new_entry = JournalEntry(
        id=entry_id,
        timestamp=timestamp,
        mood=mood,
        text=text,
        body_sensation=body_sensation,
        trigger_event=trigger_event,
        need_boundary=need_boundary,
        emotion_intensity=intensity_value,
        energy_level=energy_value,
    )

    try:
        with sqlite3.connect(db_path) as conn:
            # apply PRAGMA optimizations for journal writes
            apply_sqlite_pragmas(conn)
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
                            need_boundary,
                            emotion_intensity,
                            energy_level
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_entry.id,
                            new_entry.timestamp,
                            new_entry.mood,
                            new_entry.text,
                            new_entry.body_sensation,
                            new_entry.trigger_event,
                            new_entry.need_boundary,
                            new_entry.emotion_intensity,
                            new_entry.energy_level,
                        ),
                    )
                except sqlite3.IntegrityError:
                    new_entry.id += 1
                    continue

                # 成功写入，更新缓存
                if cache is not None:
                    cache.add_entry(new_entry)
                return

            raise sqlite3.IntegrityError("Failed to generate unique journal entry ID")
    except sqlite3.DatabaseError:
        logging.exception("Failed to append journal entry to database.")
        raise


def load_journal_entries(
    db_path: Path, cache: EntryCache | None = None
) -> list[JournalEntry]:
    """加载 journal 条目。如果提供了缓存对象，优先使用缓存避免数据库查询。

    Args:
        db_path: 数据库文件路径
        cache: 可选的缓存对象。如果缓存有效（已加载过数据），直接返回缓存数据；
               否则从 DB 加载并更新缓存。

    Returns:
        按 timestamp DESC 排序的 JournalEntry 列表
    """
    # 如果提供了有效的缓存，直接使用缓存数据（O(1) 操作，无 DB 查询）
    if cache is not None and cache.is_valid():
        return cache.get_all_ordered()

    # 缓存无效或未提供，从数据库加载
    if not db_path.exists():
        return []

    try:
        with sqlite3.connect(db_path) as conn:
            # ensure readers use the same connection-level PRAGMA where helpful
            apply_sqlite_pragmas(conn)
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
                    need_boundary,
                    emotion_intensity,
                    energy_level
                FROM moments
                ORDER BY timestamp DESC, id DESC
                """
            ).fetchall()
    except sqlite3.DatabaseError:
        logging.exception("Failed to load journal entries from SQLite.")
        return []

    if not rows:
        return []

    entries: list[JournalEntry] = []
    for row in rows:
        row_dict = dict(row)
        try:
            entries.append(
                JournalEntry(
                    id=int(row_dict.get("id", 0))
                    if row_dict.get("id") is not None
                    else 0,
                    timestamp=str(row_dict.get("timestamp", "")),
                    mood=str(row_dict.get("mood", "unspecified")),
                    text=str(row_dict.get("text", "")),
                    body_sensation=str(row_dict.get("body_sensation", "")),
                    trigger_event=str(row_dict.get("trigger_event", "")),
                    need_boundary=str(row_dict.get("need_boundary", "")),
                    emotion_intensity=clamp_scale_value(
                        row_dict.get("emotion_intensity")
                    ),
                    energy_level=clamp_scale_value(row_dict.get("energy_level")),
                )
            )
        except (TypeError, ValueError):
            logging.exception("Skipping malformed database row: %s", row_dict)
            continue

    # 更新缓存
    if cache is not None:
        cache.load_all(entries)

    return entries


def export_journal_to_csv(db_path: Path, csv_path: Path) -> int:
    """Write journal entries to a CSV file and return the number of rows exported.

    Uses streaming export to avoid loading all entries into memory at once,
    which reduces memory usage and improves performance for large datasets.
    """
    if not db_path.exists():
        return 0

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(db_path) as conn:
            apply_sqlite_pragmas(conn)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    id,
                    timestamp,
                    mood,
                    text,
                    body_sensation,
                    trigger_event,
                    need_boundary,
                    emotion_intensity,
                    energy_level
                FROM moments
                ORDER BY timestamp ASC, id ASC
                """
            )
            return _write_entries_to_csv(cursor, csv_path)
    except sqlite3.DatabaseError:
        logging.exception("Failed to export journal entries from SQLite.")
        raise
    except OSError:
        logging.exception("Failed to write journal CSV export to %s", csv_path)
        raise


def _write_entries_to_csv(cursor: sqlite3.Cursor, csv_path: Path) -> int:
    """Write database cursor rows to CSV file using streaming approach."""
    row_count = 0
    batch_size = 1000

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
                "emotion_intensity",
                "energy_level",
            ]
        )

        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break

            for row in rows:
                writer.writerow(
                    [
                        row["id"],
                        row["timestamp"],
                        row["mood"],
                        row["text"],
                        row["body_sensation"],
                        row["trigger_event"],
                        row["need_boundary"],
                        row["emotion_intensity"],
                        row["energy_level"],
                    ]
                )
                row_count += 1

    return row_count
