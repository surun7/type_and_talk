# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the history tab — table display, search filter, pagination, and CSV export."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from agent_uia.ui.app_controller import AppConfig


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def mock_app_controller():
    ctrl = mock.MagicMock()
    ctrl.config = AppConfig()
    return ctrl


def _write_history_jsonl(path: Path, entries: list[dict]) -> Path:
    """Write a list of dicts as JSON Lines to *path* and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


# ── table row count ───────────────────────────────────────────────────────────


def test_table_has_five_rows(qapp, mock_app_controller, tmp_path: Path):
    """Seeding history.jsonl with 5 entries must result in a table with 5
    data rows."""
    from agent_uia.ui.history_tab import HistoryTab

    entries = [
        {"ts": 1000, "task_id": f"t{i}", "user_text": f"task {i}",
         "status": "success", "final_message": "", "cost_usd": "0.01", "steps": 1}
        for i in range(5)
    ]
    history_path = _write_history_jsonl(tmp_path / "logs" / "history.jsonl", entries)

    tab = HistoryTab(app_controller=mock_app_controller, logs_dir=tmp_path / "logs")
    row_count = tab.table.rowCount()
    assert row_count == 5, f"Expected 5 rows, got {row_count}"
    tab.deleteLater()


# ── search filter ─────────────────────────────────────────────────────────────


def test_search_filter(qapp, mock_app_controller, tmp_path: Path):
    """Typing a search term must filter the table to matching rows."""
    from agent_uia.ui.history_tab import HistoryTab

    entries = [
        {"ts": 1000, "task_id": "t1", "user_text": "open notepad",
         "status": "success", "final_message": "", "cost_usd": "0.01", "steps": 1},
        {"ts": 2000, "task_id": "t2", "user_text": "open calculator",
         "status": "success", "final_message": "", "cost_usd": "0.01", "steps": 1},
        {"ts": 3000, "task_id": "t3", "user_text": "check weather",
         "status": "failed", "final_message": "", "cost_usd": "0.01", "steps": 1},
    ]
    _write_history_jsonl(tmp_path / "logs" / "history.jsonl", entries)

    tab = HistoryTab(app_controller=mock_app_controller, logs_dir=tmp_path / "logs")

    # Search for "notepad" — should yield 1 row.
    tab.search_field.setText("notepad")
    tab.search_field.returnPressed.emit()  # or however the filter triggers

    filtered = tab.table.rowCount()
    assert filtered == 1, f"Expected 1 filtered row for 'notepad', got {filtered}"

    tab.deleteLater()


# ── pagination ────────────────────────────────────────────────────────────────


def test_pagination(qapp, mock_app_controller, tmp_path: Path):
    """With 100 seeded entries and a page size of 50, the pagination label must
    read \"Page 1 / 2\"."""
    from agent_uia.ui.history_tab import HistoryTab

    entries = [
        {"ts": i, "task_id": f"t{i}", "user_text": f"entry {i}",
         "status": "success", "final_message": "", "cost_usd": "0.01", "steps": 1}
        for i in range(100)
    ]
    _write_history_jsonl(tmp_path / "logs" / "history.jsonl", entries)

    tab = HistoryTab(
        app_controller=mock_app_controller,
        logs_dir=tmp_path / "logs",
        page_size=50,
    )
    page_info = tab.page_label.text()
    assert "Page 1 / 2" in page_info, f"Expected 'Page 1 / 2', got {page_info!r}"

    tab.deleteLater()


# ── export to CSV ─────────────────────────────────────────────────────────────


def test_export_csv(qapp, mock_app_controller, tmp_path: Path):
    """Clicking Export must open a file-save dialog and write a CSV file."""
    from agent_uia.ui.history_tab import HistoryTab

    entries = [
        {"ts": 1000, "task_id": "t1", "user_text": "open notepad",
         "status": "success", "final_message": "Done", "cost_usd": "0.01", "steps": 1},
    ]
    _write_history_jsonl(tmp_path / "logs" / "history.jsonl", entries)

    export_path = tmp_path / "export.csv"

    with mock.patch(
        "agent_uia.ui.history_tab.QFileDialog.getSaveFileName",
        return_value=(str(export_path), "CSV (*.csv)"),
    ):
        tab = HistoryTab(
            app_controller=mock_app_controller,
            logs_dir=tmp_path / "logs",
        )
        tab.export_button.click()

    assert export_path.exists(), "CSV export file was not created"
    content = export_path.read_text(encoding="utf-8")
    assert "user_text" in content, "CSV missing header"
    assert "open notepad" in content, "CSV missing data row"

    tab.deleteLater()
