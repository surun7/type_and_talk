# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for PerformanceMonitor metric collection, aggregation, and persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

from agent_uia.performance.monitor import (
    MetricPoint,
    MetricType,
    PerformanceMonitor,
    default_monitor,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _record_n(monitor: PerformanceMonitor, name: str, n: int) -> None:
    """Record *n* timing values from 1.0 to *n* for the given metric *name*."""
    for i in range(1, n + 1):
        monitor.record(MetricPoint(name=name, type_=MetricType.TIMING, value=float(i)))


# ── tests ────────────────────────────────────────────────────────────────────


class TestPerformanceMonitor:
    """Tests for PerformanceMonitor."""

    def test_record_and_aggregate(self) -> None:
        """Record 100 timing values and verify mean, p50, p95, p99."""
        monitor = PerformanceMonitor(max_points=200)
        _record_n(monitor, "test_api", 100)

        agg = monitor.aggregate("test_api")

        assert agg["count"] == 100
        assert agg["sum"] == 5050.0  # sum(1..100) = 5050
        assert agg["mean"] == 50.5
        # p50 of uniformly-spaced integers 1..100 is ~50.5
        assert 50.0 <= agg["p50"] <= 51.0
        # p95 around 95.05
        assert 94.0 <= agg["p95"] <= 96.0
        # p99 around 99.01
        assert 98.0 <= agg["p99"] <= 100.0

    def test_memory_snapshot(self) -> None:
        """Verify memory_snapshot returns a dict with expected keys."""
        monitor = PerformanceMonitor()
        snap = monitor.memory_snapshot()

        assert isinstance(snap, dict)
        assert "rss_mb" in snap
        assert "vms_mb" in snap
        # Values should be positive floats (or nan if psutil unavailable).
        for key in ("rss_mb", "vms_mb"):
            assert isinstance(snap[key], float)

    def test_flush_to_disk(self, tmp_path: Path) -> None:
        """Record 5 points, flush, and verify the JSONL file has 5 lines.

        ``get_logs_dir`` is monkeypatched to point to *tmp_path* so the test
        does not write to the real logs directory.
        """
        monitor = PerformanceMonitor(max_points=50)
        _record_n(monitor, "flush_metric", 5)

        with mock.patch("agent_uia.performance.monitor.get_logs_dir", return_value=tmp_path):
            monitor.flush_to_disk()

        perf_file = tmp_path / "perf.jsonl"
        assert perf_file.exists()
        lines = perf_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5

        for line in lines:
            record = json.loads(line)
            assert record["name"] == "flush_metric"
            assert record["type"] == "timing"
            assert isinstance(record["value"], (int, float))
            assert "timestamp" in record
            assert "datetime" in record

    def test_time_context_manager_sync(self) -> None:
        """Use monitor.time(\"foo\") and verify a TIMING point is recorded >= 0."""
        monitor = PerformanceMonitor(max_points=50)

        with monitor.time("foo"):
            time.sleep(0.01)  # ~10 ms of wall time

        agg = monitor.aggregate("foo")
        assert agg["count"] == 1
        # Elapsed time should be positive (and >= 0).
        assert agg["min"] >= 0.0

    def test_default_monitor_singleton(self) -> None:
        """Two calls to default_monitor() must return the same instance."""
        m1 = default_monitor()
        m2 = default_monitor()
        assert m1 is m2
