# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the usage tab — stat cards, daily-series chart, and recent tasks table."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from agent_uia.ui.app_controller import AppConfig


# ── helpers ────────────────────────────────────────────────────────────────────


def _seed_usage_jsonl(path: Path, count: int, span_days: int = 5) -> None:
    """Write *count* usage entries spread evenly over *span_days* days."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    entries: list[dict] = []
    for i in range(count):
        day_offset = (i * span_days / count) if count > 1 else 0
        entries.append(
            {
                "ts": now - day_offset * 86400,
                "task_id": f"u{i:04d}",
                "user_text": f"task {i}",
                "status": "success",
                "cost_usd": f"{0.01 + (i % 5) * 0.005:.4f}",
                "steps": (i % 10) + 1,
                "model": "deepseek-chat",
                "tokens_in": 50 + i,
                "tokens_out": 100 + i,
            }
        )
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def mock_app_controller():
    ctrl = mock.MagicMock()
    ctrl.config = AppConfig()
    return ctrl


# ── stat cards ────────────────────────────────────────────────────────────────


def test_stat_cards_show_totals(qapp, mock_app_controller, tmp_path: Path):
    """With 10 usage entries spanning 5 days, the stat cards must reflect the
    correct aggregate totals."""
    from agent_uia.ui.usage_tab import UsageTab

    _seed_usage_jsonl(tmp_path / "logs" / "usage.jsonl", count=10, span_days=5)

    tab = UsageTab(
        app_controller=mock_app_controller,
        logs_dir=tmp_path / "logs",
    )

    # Expected: 10 tasks, total cost = sum of costs, etc.
    total_tasks = tab.total_tasks_card.value()
    assert total_tasks == 10, f"Expected 10 total tasks, got {total_tasks}"

    total_cost = tab.total_cost_card.value()
    assert total_cost > 0, "Total cost should be positive"

    tab.deleteLater()


# ── daily-series chart ────────────────────────────────────────────────────────


def test_daily_series_chart_has_five_bars(qapp, mock_app_controller, tmp_path: Path):
    """With 10 entries spread over 5 days, the daily-series chart must display
    5 bars (one per day)."""
    from agent_uia.ui.usage_tab import UsageTab

    _seed_usage_jsonl(tmp_path / "logs" / "usage.jsonl", count=10, span_days=5)

    tab = UsageTab(
        app_controller=mock_app_controller,
        logs_dir=tmp_path / "logs",
    )

    bar_count = tab.chart.bar_count()
    assert bar_count == 5, f"Expected 5 daily bars, got {bar_count}"

    tab.deleteLater()


# ── recent tasks table ─────────────────────────────────────────────────────────


def test_recent_tasks_table_has_twenty_rows(qapp, mock_app_controller, tmp_path: Path):
    """With enough seeded entries, the recent-tasks table must display exactly
    20 rows (capped)."""
    from agent_uia.ui.usage_tab import UsageTab

    # Seed 30 entries to ensure the cap of 20 is tested.
    _seed_usage_jsonl(tmp_path / "logs" / "usage.jsonl", count=30, span_days=5)

    tab = UsageTab(
        app_controller=mock_app_controller,
        logs_dir=tmp_path / "logs",
        max_recent_tasks=20,
    )

    row_count = tab.recent_tasks_table.rowCount()
    assert row_count == 20, f"Expected 20 recent-task rows, got {row_count}"

    tab.deleteLater()
