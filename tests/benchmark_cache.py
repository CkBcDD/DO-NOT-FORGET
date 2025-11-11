#!/usr/bin/env python3
"""Performance comparison demo: shows the difference before and after cache optimization."""

import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ..src.models import EntryCache
from ..src.storage import (
    append_entry_to_journal,
    initialize_storage,
    load_journal_entries,
)


def benchmark_without_cache(db_path: Path, num_records: int, num_refreshes: int):
    """Benchmark: multiple refreshes without using a cache."""
    start = time.perf_counter()
    for _ in range(num_refreshes):
        load_journal_entries(db_path, cache=None)
    elapsed = time.perf_counter() - start
    return elapsed


def benchmark_with_cache(db_path: Path, num_records: int, num_refreshes: int):
    """Optimized benchmark: multiple refreshes using an in-memory cache."""
    cache = EntryCache()

    # First load (will query the DB and populate the cache)
    load_journal_entries(db_path, cache=cache)

    start = time.perf_counter()
    for _ in range(num_refreshes):
        load_journal_entries(db_path, cache=cache)
    elapsed = time.perf_counter() - start
    return elapsed


def main():
    print("=" * 70)
    print("DO-NOT-FORGET Cache Optimization Benchmark")
    print("=" * 70)
    print()

    tmpdir = tempfile.mkdtemp()
    try:
        db_path = Path(tmpdir) / "bench.db"
        initialize_storage(db_path, Path(tmpdir) / "legacy.json")

        # Create test data
        test_cases = [100, 500, 1000, 2000]
        num_refreshes = 100

        print("Performance Test Configuration:")
        print(f"   - Each test case includes {num_refreshes} refresh_history() calls")
        print()

        for num_records in test_cases:
            # Clear database
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM moments")

            # Insert test data
            print(f"Generating {num_records} test records...", end="", flush=True)
            for i in range(num_records):
                append_entry_to_journal(
                    text=f"Entry {i + 1}", mood="calm", db_path=db_path
                )
            print(" OK")

            # Run benchmark
            print(f"\nTest Case: {num_records} records")
            print("   " + "-" * 52)

            # Without cache
            elapsed_no_cache = benchmark_without_cache(
                db_path, num_records, num_refreshes
            )
            time_per_refresh_no_cache = elapsed_no_cache / num_refreshes * 1000
            print(
                f"   NO CACHE:  {elapsed_no_cache:.4f}s total "
                f"({time_per_refresh_no_cache:.3f}ms per call)"
            )

            # With cache
            elapsed_with_cache = benchmark_with_cache(
                db_path, num_records, num_refreshes
            )
            time_per_refresh_with_cache = elapsed_with_cache / num_refreshes * 1000
            print(
                f"   WITH CACHE: {elapsed_with_cache:.6f}s total "
                f"({time_per_refresh_with_cache:.6f}ms per call)"
            )

            # Calculate improvement
            speedup = time_per_refresh_no_cache / max(
                time_per_refresh_with_cache, 0.000001
            )
            improvement = (
                (time_per_refresh_no_cache - time_per_refresh_with_cache)
                / time_per_refresh_no_cache
                * 100
            )
            print(f"   SPEEDUP: {speedup:.0f}x ({improvement:.1f}% faster)")

        print()
        print("=" * 70)
        print("Summary:")
        print("   - First refresh: cache loads from the DB (similar to no-cache)")
        print("   - Subsequent refreshes: cache uses in-memory data (100-1000x faster)")
        print("   - Performance improvement scales with record count")
        print("=" * 70)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
