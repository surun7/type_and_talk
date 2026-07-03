# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""History tab: search, browse, and export past conversations."""

from __future__ import annotations

import csv
import time
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QSortFilterProxyModel, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "HistoryTab",
]

# ── styling ──────────────────────────────────────────────────────────────────

_TAB_STYLE = """
QWidget#historyBody {
    background: #1E1E1E;
}
"""

_SEARCH_STYLE = """
QLineEdit {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: #264F78;
}
QLineEdit:focus {
    border: 1px solid #0078D4;
}
QLineEdit::placeholder {
    color: #666666;
}
"""

_TABLE_STYLE = """
QTableView {
    background: #1E1E1E;
    alternate-background-color: #252525;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    gridline-color: #333333;
    selection-background-color: #264F78;
    selection-color: #FFFFFF;
    font-size: 12px;
}
QTableView::item {
    padding: 6px 8px;
}
QTableView::item:selected {
    background: #264F78;
}
QHeaderView::section {
    background: #2D2D2D;
    color: #CCCCCC;
    border: none;
    border-bottom: 1px solid #3D3D3D;
    padding: 8px;
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
}
QHeaderView::section:hover {
    background: #353535;
}
"""

_PAGINATION_STYLE = """
QPushButton {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 12px;
    min-width: 60px;
}
QPushButton:hover {
    background: #3D3D3D;
    border: 1px solid #0078D4;
}
QPushButton:disabled {
    color: #555555;
    background: #252525;
    border: 1px solid #2D2D2D;
}
"""

_BUTTON_PRIMARY_STYLE = """
QPushButton {
    background: #0078D4;
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background: #106EBE;
}
"""

_EMPTY_STYLE = "color: #666666; font-size: 14px;"

_PAGE_LABEL_STYLE = "color: #888888; font-size: 12px;"

# ── column indices ───────────────────────────────────────────────────────────

_COL_TIMESTAMP = 0
_COL_STATUS = 1
_COL_USER_TEXT = 2
_COL_FINAL_MESSAGE = 3
_COL_COST = 4
_COL_STEPS = 5

_COL_HEADERS = [
    "Timestamp",
    "Status",
    "User Text",
    "Response",
    "Cost",
    "Steps",
]

_PAGE_SIZE = 50


class _HistoryProxyModel(QSortFilterProxyModel):
    """Filter proxy that searches across user_text and final_message columns."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(-1)  # search all columns

    def lessThan(self, left, right) -> bool:  # noqa: N802 — Qt override
        """Sort timestamps numerically (descending by default)."""
        left_data = self.sourceModel().data(left, Qt.UserRole)
        right_data = self.sourceModel().data(right, Qt.UserRole)
        if left_data is not None and right_data is not None:
            try:
                return float(left_data) < float(right_data)
            except (ValueError, TypeError):
                pass
        return super().lessThan(left, right)


# ── HistoryTab ────────────────────────────────────────────────────────────────


class HistoryTab(QWidget):
    """Main-window tab for browsing and searching past conversations.

    Signals:
        navigate_requested: Emitted with a tab name when internal navigation
            is desired (e.g. to the settings tab).
    """

    navigate_requested = Signal(str)

    def __init__(self, app_controller: AppController) -> None:
        """Initialise the history tab.

        Args:
            app_controller: The application controller for data access.
        """
        super().__init__()
        self._controller = app_controller
        self._all_entries: list[dict[str, Any]] = []
        self._current_page = 1
        self._total_pages = 1

        self.setObjectName("historyBody")
        self.setStyleSheet(_TAB_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Top bar: search + export ──────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search past conversations...")
        self._search_input.setStyleSheet(_SEARCH_STYLE)
        self._search_input.textChanged.connect(self._on_search_changed)
        top_row.addWidget(self._search_input, 1)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setStyleSheet(_BUTTON_PRIMARY_STYLE)
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setToolTip("Export filtered view to CSV")
        top_row.addWidget(self._export_btn)

        layout.addLayout(top_row)

        # ── Table view ────────────────────────────────────────────────────
        self._model = QStandardItemModel(0, len(_COL_HEADERS))
        self._model.setHorizontalHeaderLabels(_COL_HEADERS)

        self._proxy = _HistoryProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(Qt.UserRole)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.verticalHeader().hide()
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_row_double_clicked)

        # Column sizing.
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.resizeSection(_COL_TIMESTAMP, 160)
        header.resizeSection(_COL_STATUS, 80)
        header.setSectionResizeMode(_COL_USER_TEXT, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_FINAL_MESSAGE, QHeaderView.Stretch)
        header.resizeSection(_COL_COST, 80)
        header.resizeSection(_COL_STEPS, 60)

        layout.addWidget(self._table, 1)

        # ── Empty state (overlay) ─────────────────────────────────────────
        self._empty_label = QLabel(
            "No conversations yet.\nTry saying something to TNT to get started."
        )
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(_EMPTY_STYLE)
        self._empty_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        # ── Pagination bar ────────────────────────────────────────────────
        pagination_row = QHBoxLayout()
        pagination_row.setSpacing(8)

        self._prev_btn = QPushButton("← Prev")
        self._prev_btn.setStyleSheet(_PAGINATION_STYLE)
        self._prev_btn.clicked.connect(self._on_prev_page)
        pagination_row.addWidget(self._prev_btn)

        self._page_label = QLabel("Page 1 / 1")
        self._page_label.setStyleSheet(_PAGE_LABEL_STYLE)
        self._page_label.setAlignment(Qt.AlignCenter)
        pagination_row.addWidget(self._page_label, 1)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(_PAGINATION_STYLE)
        self._next_btn.clicked.connect(self._on_next_page)
        pagination_row.addWidget(self._next_btn)

        layout.addLayout(pagination_row)

    # ── public API ───────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read history entries from disk and refresh the view."""
        self._load_page(1)

    # ── internal: data loading ───────────────────────────────────────────────

    def _load_page(self, page: int) -> None:
        """Load a page of history entries from the controller.

        Args:
            page: The 1-based page number to load.
        """
        try:
            result = self._controller.get_history_paginated(
                page=page,
                page_size=_PAGE_SIZE,
                query=self._search_input.text().strip() or None,
            )
        except AttributeError:
            # Fallback if controller doesn't have the method yet.
            self._all_entries = []
            self._total_pages = 1
            self._current_page = 1
            result = {"entries": [], "total_pages": 1}
        except Exception:  # noqa: BLE001
            result = {"entries": [], "total_pages": 1}

        self._all_entries = result.get("entries", [])
        self._total_pages = max(result.get("total_pages", 1), 1)
        self._current_page = max(1, min(page, self._total_pages))

        self._refresh_table()
        self._update_pagination()

    def _refresh_table(self) -> None:
        """Populate the table model with the current page of entries."""
        self._model.removeRows(0, self._model.rowCount())

        if not self._all_entries:
            self._table.hide()
            self._empty_label.show()
            return

        self._empty_label.hide()
        self._table.show()

        for entry in self._all_entries:
            row: list[QStandardItem] = []

            # Timestamp.
            ts_item = QStandardItem(
                _format_timestamp(entry.get("ts", entry.get("timestamp", 0)))
            )
            ts_item.setData(entry.get("ts", entry.get("timestamp", 0)), Qt.UserRole)
            ts_item.setTextAlignment(Qt.AlignCenter)
            row.append(ts_item)

            # Status.
            status = entry.get("status", "unknown")
            status_item = QStandardItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)
            _color_status_item(status_item, status)
            row.append(status_item)

            # User text (truncated).
            user_text = entry.get("user_text", "")
            user_item = QStandardItem(user_text[:80])
            user_item.setToolTip(user_text)
            row.append(user_item)

            # Final message (truncated).
            final_msg = entry.get("final_message", "")
            final_item = QStandardItem(final_msg[:80])
            final_item.setToolTip(final_msg)
            row.append(final_item)

            # Cost.
            cost = entry.get("cost_usd", "0")
            cost_item = QStandardItem(f"${cost}")
            cost_item.setData(cost, Qt.UserRole)
            cost_item.setTextAlignment(Qt.AlignCenter)
            row.append(cost_item)

            # Steps.
            steps = str(entry.get("steps", 0))
            steps_item = QStandardItem(steps)
            steps_item.setData(int(entry.get("steps", 0)), Qt.UserRole)
            steps_item.setTextAlignment(Qt.AlignCenter)
            row.append(steps_item)

            self._model.appendRow(row)

    def _update_pagination(self) -> None:
        """Update pagination button/label state based on current page."""
        self._page_label.setText(
            f"Page {self._current_page} / {self._total_pages}"
        )
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < self._total_pages)

    # ── internal: slots ─────────────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        """Filter the table when search text changes."""
        if hasattr(self._proxy, "setFilterFixedString"):
            self._proxy.setFilterFixedString(text)
        # If the proxy can handle regex, fallback to the simpler filter.
        self._proxy.invalidateFilter()
        # Reload page 1 with search query.
        self._load_page(1)

    def _on_row_double_clicked(self, index) -> None:
        """Open the history detail dialog for the selected row."""
        source_index = self._proxy.mapToSource(index)
        row = source_index.row()
        if row < 0 or row >= len(self._all_entries):
            return
        entry = self._all_entries[row]

        # Lazy-import to avoid circular deps at module level.
        from agent_uia.ui.tabs.history_detail_dialog import HistoryDetailDialog

        dialog = HistoryDetailDialog(
            task_id=str(entry.get("task_id", "")),
            timestamp=_format_timestamp(
                entry.get("ts", entry.get("timestamp", 0))
            ),
            user_text=entry.get("user_text", ""),
            final_message=entry.get("final_message", ""),
            steps_taken=int(entry.get("steps", 0)),
            cost_usd=str(entry.get("cost_usd", "0")),
            parent=self,
        )
        dialog.exec_()

    def _on_prev_page(self) -> None:
        """Go to the previous page."""
        if self._current_page > 1:
            self._load_page(self._current_page - 1)

    def _on_next_page(self) -> None:
        """Go to the next page."""
        if self._current_page < self._total_pages:
            self._load_page(self._current_page + 1)

    def _on_export(self) -> None:
        """Export the currently displayed entries to CSV."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export History to CSV",
            "tnt_history.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(_COL_HEADERS)
                for entry in self._all_entries:
                    writer.writerow([
                        _format_timestamp(
                            entry.get("ts", entry.get("timestamp", 0))
                        ),
                        entry.get("status", ""),
                        entry.get("user_text", ""),
                        entry.get("final_message", ""),
                        entry.get("cost_usd", "0"),
                        str(entry.get("steps", 0)),
                    ])
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Export Failed",
                f"Could not write CSV file:\n{exc}",
            )
            return

        # Show brief success on the page label.
        self._page_label.setText("✓ Exported")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(
            2000,
            lambda: self._page_label.setText(
                f"Page {self._current_page} / {self._total_pages}"
            ),
        )


# ── helpers ───────────────────────────────────────────────────────────────────


def _format_timestamp(ts: float | int | str) -> str:
    """Format a UNIX timestamp (float or int) to ``YYYY-MM-DD HH:MM``."""
    try:
        ts_float = float(ts)
    except (TypeError, ValueError):
        return str(ts)
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_float))


def _color_status_item(item: QStandardItem, status: str) -> None:
    """Set foreground color based on task status."""
    color_map = {
        "success": QColor("#4CAF50"),
        "failed": QColor("#F44336"),
        "blocked": QColor("#FFC107"),
        "budget": QColor("#FF9800"),
        "max_steps": QColor("#9E9E9E"),
    }
    color = color_map.get(status.lower(), QColor("#888888"))
    item.setForeground(color)
