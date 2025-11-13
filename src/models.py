"""Data models for journal entries and caching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JournalEntry:
    """Represents a single journal entry with mood and structured feelings."""

    id: int
    timestamp: str
    mood: str
    text: str
    body_sensation: str = ""
    trigger_event: str = ""
    need_boundary: str = ""
    emotion_intensity: float = 3.0
    energy_level: float = 3.0


class EntryCache:
    """内存缓存管理器，维护 id→entry 映射以支持增量更新和快速访问。

    避免频繁的数据库查询和对象转换，将 refresh_history 的复杂度从 O(n) 降至 O(1)。
    """

    def __init__(self) -> None:
        # id → entry 映射，支持快速查找和存在性检查
        self._cache: dict[int, JournalEntry] = {}
        # 按 timestamp DESC 排序的 entry id 列表，用于迭代时保持顺序
        self._sorted_ids: list[int] = []

    def is_valid(self) -> bool:
        """检查缓存是否已初始化过。"""
        return bool(self._cache)

    def load_all(self, entries: list[JournalEntry]) -> None:
        """加载全量数据并更新缓存。通常在初始化或显式刷新时调用。"""
        self._cache.clear()
        self._sorted_ids.clear()
        for entry in entries:
            self._cache[entry.id] = entry
        # 按 timestamp DESC 排序（保持与数据库查询一致）
        self._sorted_ids = sorted(
            self._cache.keys(),
            key=lambda entry_id: (
                self._cache[entry_id].timestamp,
                self._cache[entry_id].id,
            ),
            reverse=True,
        )

    def add_entry(self, entry: JournalEntry) -> None:
        """增量添加一条新记录到缓存。"""
        self._cache[entry.id] = entry
        # 重新排序以保持顺序
        self._sorted_ids = sorted(
            self._cache.keys(),
            key=lambda entry_id: (
                self._cache[entry_id].timestamp,
                self._cache[entry_id].id,
            ),
            reverse=True,
        )

    def get_all_ordered(self) -> list[JournalEntry]:
        """返回按 timestamp DESC 排序的所有 entries。O(1) 操作，无 DB 查询。"""
        return [self._cache[entry_id] for entry_id in self._sorted_ids]

    def get_by_id(self, entry_id: int) -> JournalEntry | None:
        """按 id 查询单条记录。O(1) 操作。"""
        return self._cache.get(entry_id)

    def invalidate(self) -> None:
        """清空缓存，标记为需要重新加载。"""
        self._cache.clear()
        self._sorted_ids.clear()
