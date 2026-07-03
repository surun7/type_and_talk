# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Centralized performance metrics collection.

Provides a singleton-backed ``PerformanceMonitor`` that records metric points,
supports timing context managers, aggregates statistics, flushes to disk,
and captures memory snapshots.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import median, quantiles
from typing import Any

from agent_uia.paths import get_logs_dir


class MetricType(str, Enum):
    """Categorisation of a performance metric point."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMING = "timing"


@dataclass
class MetricPoint:
    """A single performance data point.

    Attributes:
        name: Metric identifier (e.g. ``"llm_call"``).
        type_: The kind of metric this point represents.
        value: Numeric measurement.
        tags: Optional key-value metadata (e.g. ``{"model": "gpt-4"}``).
        timestamp: Unix timestamp (seconds since epoch). Defaults to now.
    """

    name: str
    type_: MetricType
    value: float
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class _TimerContextManager(AbstractContextManager):
    """Context manager that records elapsed time as a TIMING metric point."""

    def __init__(self, monitor: PerformanceMonitor, name: str, tags: dict[str, str]) -> None:
        self._monitor = monitor
        self._name = name
        self._tags = tags
        self._start: float | None = None

    def __enter__(self) -> None:
        self._start = time.perf_counter()

    def __exit__(self, *args: Any) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        self._monitor.record(MetricPoint(name=self._name, type_=MetricType.TIMING, value=elapsed_ms, tags=self._tags))


class _AsyncTimerContextManager(AbstractAsyncContextManager):
    """Async context manager that records elapsed time as a TIMING metric point."""

    def __init__(self, monitor: PerformanceMonitor, name: str, tags: dict[str, str]) -> None:
        self._monitor = monitor
        self._name = name
        self._tags = tags
        self._start: float | None = None

    async def __aenter__(self) -> None:
        self._start = time.perf_counter()

    async def __aexit__(self, *args: Any) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        self._monitor.record(MetricPoint(name=self._name, type_=MetricType.TIMING, value=elapsed_ms, tags=self._tags))


# Module-level singleton; initialised lazily by ``default_monitor()``.
_default_monitor: PerformanceMonitor | None = None
_default_monitor_lock = threading.Lock()


class PerformanceMonitor:
    """Thread-safe collector of performance metric points.

    Records points into a fixed-size ring buffer, provides aggregation helpers,
    and can flush buffered data to a JSON Lines file on disk.

    Usage::

        monitor = PerformanceMonitor()
        monitor.record(MetricPoint("llm_call", MetricType.COUNTER, 1, tags={"model": "gpt-4"}))

        with monitor.time("llm_call", model="gpt-4"):
            ...

        async with monitor.time_async("llm_call", model="gpt-4"):
            ...
    """

    def __init__(self, max_points: int = 10000) -> None:
        self._buffer: deque[MetricPoint] = deque(maxlen=max_points)
        self._max_points = max_points
        self._lock = threading.Lock()

        # Track how many points have been flushed to disk so far.
        self._flushed_count: int = 0

    # ── record ──────────────────────────────────────────────────────────────────

    def record(self, point: MetricPoint) -> None:
        """Append a single metric point to the in-memory buffer.

        Thread-safe.  If the buffer is full the oldest point is evicted.
        """
        with self._lock:
            self._buffer.append(point)

    # ── timing helpers ──────────────────────────────────────────────────────────

    def time(self, name: str, **tags: str) -> AbstractContextManager:
        """Return a sync context manager that records elapsed milliseconds.

        Usage::

            with monitor.time("llm_call", model="gpt-4"):
                response = client.chat(...)
        """
        return _TimerContextManager(self, name, tags)

    def time_async(self, name: str, **tags: str) -> AbstractAsyncContextManager:
        """Return an async context manager that records elapsed milliseconds.

        Usage::

            async with monitor.time_async("llm_call", model="gpt-4"):
                response = await client.chat(...)
        """
        return _AsyncTimerContextManager(self, name, tags)

    # ── aggregation ─────────────────────────────────────────────────────────────

    def aggregate(self, name: str, since: float | None = None) -> dict[str, float]:
        """Compute summary statistics for all points matching *name*.

        Args:
            name: Metric name to filter for.
            since: Optional Unix timestamp; only include points recorded after
                this time.

        Returns:
            A dict with keys ``count``, ``sum``, ``min``, ``max``, ``mean``,
            ``p50``, ``p95``, ``p99``.  If no points match, count is 0 and
            the remaining fields are ``float("nan")``.
        """
        with self._lock:
            points = [p for p in self._buffer if p.name == name and (since is None or p.timestamp > since)]

        if not points:
            return {
                "count": 0,
                "sum": float("nan"),
                "min": float("nan"),
                "max": float("nan"),
                "mean": float("nan"),
                "p50": float("nan"),
                "p95": float("nan"),
                "p99": float("nan"),
            }

        values = sorted(p.value for p in points)
        n = len(values)
        total = sum(values)

        result: dict[str, float] = {
            "count": n,
            "sum": total,
            "min": values[0],
            "max": values[-1],
            "mean": total / n,
        }

        if n >= 3:
            qs = quantiles(values, n=100, method="exclusive")
            result["p50"] = qs[49]
            result["p95"] = qs[94]
            result["p99"] = qs[98]
        elif n == 2:
            result["p50"] = median(values)
            result["p95"] = values[-1]
            result["p99"] = values[-1]
        else:  # n == 1
            result["p50"] = values[0]
            result["p95"] = values[0]
            result["p99"] = values[0]

        return result

    # ── flush to disk ───────────────────────────────────────────────────────────

    def flush_to_disk(self) -> None:
        """Append all currently buffered points to a JSON Lines file.

        The file is written at ``<logs_dir>/perf.jsonl``.  After flushing the
        buffer is **not** cleared; points remain available for in-memory
        aggregation until they are eventually evicted by the ring buffer.
        """
        with self._lock:
            points = list(self._buffer)

        if not points:
            return

        log_path = get_logs_dir() / "perf.jsonl"

        lines: list[str] = []
        for p in points:
            record = {
                "name": p.name,
                "type": p.type_.value,
                "value": p.value,
                "tags": p.tags,
                "timestamp": p.timestamp,
                "datetime": datetime.fromtimestamp(p.timestamp, tz=timezone.utc).isoformat(),
            }
            lines.append(json.dumps(record, sort_keys=True, ensure_ascii=False))

        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")

        with self._lock:
            self._flushed_count += len(points)

    # ── memory snapshot ─────────────────────────────────────────────────────────

    def memory_snapshot(self) -> dict[str, float]:
        """Return a snapshot of current process memory usage.

        Requires ``psutil``.  If it is not installed or the call fails all
        values are set to ``float("nan")``.

        Returns:
            Dict with keys ``rss_mb``, ``vms_mb``, ``available_mb``.
        """
        try:
            import psutil

            proc = psutil.Process()
            mem = proc.memory_info()
            avail = psutil.virtual_memory().available

            return {
                "rss_mb": mem.rss / (1024 * 1024),
                "vms_mb": mem.vms / (1024 * 1024),
                "available_mb": avail / (1024 * 1024),
            }
        except Exception:
            return {"rss_mb": float("nan"), "vms_mb": float("nan"), "available_mb": float("nan")}

    # ── summary ─────────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return an aggregate overview of all recorded metrics + a memory snapshot.

        The ``metrics`` key maps each metric name to its aggregate stats.
        """
        with self._lock:
            names = list({p.name for p in self._buffer})

        return {
            "metrics": {name: self.aggregate(name) for name in sorted(names)},
            "memory_snapshot": self.memory_snapshot(),
            "buffer_size": len(self._buffer) if hasattr(self, "_buffer") else 0,  # type: ignore[arg-type]
        }


def default_monitor() -> PerformanceMonitor:
    """Return the module-level singleton ``PerformanceMonitor``.

    The singleton is created on first access in a thread-safe manner.
    """
    global _default_monitor
    if _default_monitor is None:
        with _default_monitor_lock:
            if _default_monitor is None:
                _default_monitor = PerformanceMonitor()
    return _default_monitor
