"""Tests for JournalEntryListModel."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt

from ..src.models import JournalEntry
from ..src.ui import JournalEntryListModel


class TestJournalEntryListModel:
    """测试 JournalEntryListModel 的各项功能。"""

    def test_empty_model(self):
        """测试空模型的行为。"""
        model = JournalEntryListModel()
        assert model.rowCount() == 0
        assert model.data(QModelIndex()) is None

    def test_set_entries(self):
        """测试设置条目后的模型状态。"""
        model = JournalEntryListModel()
        entries = [
            JournalEntry(
                id=1,
                timestamp="2025-11-11 10:00:00",
                mood="happy",
                text="Test entry 1",
                body_sensation="relaxed",
                trigger_event="morning coffee",
                need_boundary="rest",
                emotion_intensity=4,
                energy_level=5,
            ),
            JournalEntry(
                id=2,
                timestamp="2025-11-11 11:00:00",
                mood="calm",
                text="Test entry 2",
                body_sensation="peaceful",
                trigger_event="meditation",
                need_boundary="quiet",
                emotion_intensity=3,
                energy_level=4,
            ),
        ]

        model.set_entries(entries)
        assert model.rowCount() == 2

    def test_data_display_role(self):
        """测试 DisplayRole 返回格式化的显示文本。"""
        model = JournalEntryListModel()
        entry = JournalEntry(
            id=1,
            timestamp="2025-11-11 10:00:00",
            mood="happy",
            text="This is a test entry with some content",
            body_sensation="relaxed",
            trigger_event="morning coffee",
            need_boundary="rest",
            emotion_intensity=4,
            energy_level=5,
        )

        model.set_entries([entry])
        index = model.index(0, 0)

        display_text = model.data(index, Qt.ItemDataRole.DisplayRole)
        assert display_text is not None
        # 时间戳会被 format_timestamp_display 格式化，去掉秒数
        assert "2025-11-11 10:00" in display_text
        assert "强度 Intensity 4/5" in display_text
        assert "能量 Energy 5/5" in display_text
        assert "relaxed" in display_text
        assert "morning coffee" in display_text
        assert "rest" in display_text

    def test_data_user_role(self):
        """测试 UserRole 返回完整的 JournalEntry 对象。"""
        model = JournalEntryListModel()
        entry = JournalEntry(
            id=1,
            timestamp="2025-11-11 10:00:00",
            mood="happy",
            text="Test entry",
            emotion_intensity=4,
            energy_level=5,
        )

        model.set_entries([entry])
        index = model.index(0, 0)

        retrieved_entry = model.data(index, Qt.ItemDataRole.UserRole)
        assert retrieved_entry == entry
        assert retrieved_entry.id == 1
        assert retrieved_entry.mood == "happy"

    def test_get_entry(self):
        """测试通过索引获取 entry。"""
        model = JournalEntryListModel()
        entries = [
            JournalEntry(
                id=1, timestamp="2025-11-11 10:00:00", mood="happy", text="Entry 1"
            ),
            JournalEntry(
                id=2, timestamp="2025-11-11 11:00:00", mood="calm", text="Entry 2"
            ),
        ]

        model.set_entries(entries)

        entry1 = model.get_entry(model.index(0, 0))
        assert entry1 is not None
        assert entry1.id == 1

        entry2 = model.get_entry(model.index(1, 0))
        assert entry2 is not None
        assert entry2.id == 2

        # 测试无效索引
        assert model.get_entry(QModelIndex()) is None
        assert model.get_entry(model.index(999, 0)) is None

    def test_clear(self):
        """测试清空模型。"""
        model = JournalEntryListModel()
        entries = [
            JournalEntry(
                id=1, timestamp="2025-11-11 10:00:00", mood="happy", text="Test entry"
            )
        ]

        model.set_entries(entries)
        assert model.rowCount() == 1

        model.clear()
        assert model.rowCount() == 0

    def test_long_text_truncation(self):
        """测试长文本预览会被截断。"""
        model = JournalEntryListModel()
        long_text = "a" * 100  # 创建一个很长的文本

        entry = JournalEntry(
            id=1, timestamp="2025-11-11 10:00:00", mood="happy", text=long_text
        )

        model.set_entries([entry])
        index = model.index(0, 0)

        display_text = model.data(index, Qt.ItemDataRole.DisplayRole)
        assert display_text is not None
        # 应该包含省略号，表示文本被截断
        assert "…" in display_text

    def test_large_dataset_performance(self):
        """测试大数据集的性能 - Model 应该能够处理上万条记录。"""
        model = JournalEntryListModel()

        # 创建 10,000 条记录
        entries = [
            JournalEntry(
                id=i,
                timestamp=f"2025-11-11 {i % 24:02d}:00:00",
                mood="happy" if i % 2 == 0 else "calm",
                text=f"Test entry {i}",
                emotion_intensity=(i % 5) + 1,
                energy_level=(i % 5) + 1,
            )
            for i in range(10000)
        ]

        # 设置大量数据应该很快完成（不会为每条创建 widget）
        model.set_entries(entries)
        assert model.rowCount() == 10000

        # 随机访问应该是 O(1)
        middle_entry = model.get_entry(model.index(5000, 0))
        assert middle_entry is not None
        assert middle_entry.id == 5000

        last_entry = model.get_entry(model.index(9999, 0))
        assert last_entry is not None
        assert last_entry.id == 9999

    def test_invalid_index(self):
        """测试无效索引的处理。"""
        model = JournalEntryListModel()
        entries = [
            JournalEntry(
                id=1, timestamp="2025-11-11 10:00:00", mood="happy", text="Test"
            )
        ]
        model.set_entries(entries)

        # 负数索引
        assert model.data(model.index(-1, 0)) is None

        # 超出范围的索引
        assert model.data(model.index(999, 0)) is None

        # 无效的 QModelIndex
        assert model.data(QModelIndex()) is None
