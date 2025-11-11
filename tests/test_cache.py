#!/usr/bin/env python3
"""Unit tests for the caching mechanism."""

import tempfile
from pathlib import Path

from ..src.models import EntryCache, JournalEntry
from ..src.storage import (
    append_entry_to_journal,
    initialize_storage,
    load_journal_entries,
)


def test_entry_cache_basic():
    """Test basic cache functionality: load, query, add"""
    cache = EntryCache()

    # Cache should be invalid initially
    assert not cache.is_valid()

    # Create test data
    entries = [
        JournalEntry(
            id=1, timestamp="2025-01-01T10:00:00", mood="calm", text="Entry 1"
        ),
        JournalEntry(
            id=2, timestamp="2025-01-01T11:00:00", mood="joyful", text="Entry 2"
        ),
    ]

    # Load data
    cache.load_all(entries)
    assert cache.is_valid()

    # Verify ordering (timestamp DESC)
    ordered = cache.get_all_ordered()
    assert len(ordered) == 2
    assert ordered[0].id == 2
    assert ordered[1].id == 1

    # Verify single-item lookup
    entry = cache.get_by_id(1)
    assert entry is not None
    assert entry.text == "Entry 1"

    print("✓ Basic cache functionality test passed")


def test_entry_cache_add():
    """Test incremental addition to the cache"""
    cache = EntryCache()

    # Initial load
    initial_entries = [
        JournalEntry(id=1, timestamp="2025-01-01T10:00:00", mood="calm", text="Initial")
    ]
    cache.load_all(initial_entries)

    # Incremental add
    new_entry = JournalEntry(
        id=2, timestamp="2025-01-01T11:00:00", mood="joyful", text="Added later"
    )
    cache.add_entry(new_entry)

    # Verify both entries are in cache and the new one comes first
    ordered = cache.get_all_ordered()
    assert len(ordered) == 2
    assert ordered[0].id == 2
    assert ordered[1].id == 1

    print("✓ Cache incremental-add test passed")


def test_entry_cache_invalidation():
    """Test cache invalidation"""
    cache = EntryCache()

    entries = [
        JournalEntry(id=1, timestamp="2025-01-01T10:00:00", mood="calm", text="Entry")
    ]
    cache.load_all(entries)
    assert cache.is_valid()

    # Invalidate cache
    cache.invalidate()
    assert not cache.is_valid()

    print("✓ Cache invalidation test passed")


def test_load_with_cache():
    """Test load_journal_entries using the cache"""
    import shutil

    tmpdir = tempfile.mkdtemp()
    try:
        db_path = Path(tmpdir) / "test.db"
        # Initialize the database
        initialize_storage(db_path, Path(tmpdir) / "legacy.json")

        # Add a few entries
        for i in range(3):
            append_entry_to_journal(text=f"Entry {i + 1}", mood="calm", db_path=db_path)

        # First load (no cache): should query DB
        cache = EntryCache()
        entries1 = load_journal_entries(db_path, cache=cache)
        assert len(entries1) == 3
        assert cache.is_valid()

        # Second load (with cache): should return directly from cache (no DB query)
        entries2 = load_journal_entries(db_path, cache=cache)
        assert len(entries2) == 3
        assert entries1 == entries2

        # Verify cache result matches DB query
        db_entries = load_journal_entries(db_path, cache=None)
        assert len(db_entries) == 3
        assert entries1 == db_entries

        print("✓ Cache load test passed")
    finally:
        # Clean up temporary files
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_with_incremental_update():
    """Test incremental update scenario: load first, then add new records"""
    import shutil

    tmpdir = tempfile.mkdtemp()
    try:
        db_path = Path(tmpdir) / "test.db"
        # Initialize the database
        initialize_storage(db_path, Path(tmpdir) / "legacy.json")

        # Create cache and load initial data
        cache = EntryCache()
        append_entry_to_journal(text="Initial", mood="calm", db_path=db_path)
        entries1 = load_journal_entries(db_path, cache=cache)
        assert len(entries1) == 1

        # Add a new record via the cache (cache should update automatically)
        append_entry_to_journal(
            text="New Entry", mood="joyful", db_path=db_path, cache=cache
        )

        # Subsequent loads should use the cache (O(1) operation, direct return)
        entries2 = load_journal_entries(db_path, cache=cache)
        assert len(entries2) == 2
        # The new entry should be first
        assert entries2[0].text == "New Entry"
        assert entries2[1].text == "Initial"

        print("✓ Incremental update test passed")
    finally:
        # Clean up temporary files
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("Running cache unit tests...\n")
    test_entry_cache_basic()
    test_entry_cache_add()
    test_entry_cache_invalidation()
    test_load_with_cache()
    test_cache_with_incremental_update()
    print("\n✅ All tests passed! Cache optimization features are working correctly.")
