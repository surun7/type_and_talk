# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Usage tab: cost breakdown, token usage charts, and recent tasks."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "UsageTab",
]

# ── styling ──────────────────────────────────────────────────────────────────

_TAB_STYLE = """
QWidget#usageBody {
    background: #1E1E1E;
}
"""

_CARD_STYLE = """
QFrame#statCard {
    background: #252525;
    border: 1px solid #3D3D3D;
    border-radius: 8px;
    padding: 12px;
}
"""

_CARD_VALUE_STYLE = "color: #FFFFFF; font-size: 16px; font-weight: bold;"
_CARD_LABEL_STYLE = "color: #888888; font-size: 11px;"

_TABLE_STYLE = """
QTableWidget {
    background: #1E1E1E;
    alternate-background-color: #252525;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    gridline-color: #333333;
    selection-background-color: #264F78;
    selection-color: #FFFFFF;
    font-size: 11px;
}
QTableWidget::item {
    padding: 4px 6px;
}
QHeaderView::section {
    background: #2D2D2D;
    color: #CCCCCC;
    border: none;
    border-bottom: 1px solid #3D3D3D;
    padding: 6px;
    font-weight: bold;
    font-size: 10px;
    text-transform: uppercase;
}
"""

_CHART_CONTAINER_STYLE = """
QFrame#chartContainer {
    background: #252525;
    border: 1px solid #3D3D3D;
    border-radius: 8px;
}
"""

_SECTION_LABEL_STYLE = "color: #CCCCCC; font-size: 13px; font-weight: bold;"

_BUTTON_REFRESH_STYLE = """
QPushButton {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 11px;
}
QPushButton:hover {
    border: 1px solid #0078D4;
}
"""


class _StatCard(QFrame):
    """A single stat card showing a prominent value with a label."""

    def __init__(self, value: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setStyleSheet(_CARD_STYLE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(72)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self._value_label = QLabel(value)
        self._value_label.setStyleSheet(_CARD_VALUE_STYLE)
        layout.addWidget(self._value_label)

        self._label = QLabel(label)
        self._label.setStyleSheet(_CARD_LABEL_STYLE)
        layout.addWidget(self._label)

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        self._value_label.setText(value)


class UsageTab(QWidget):
    """Main-window tab showing usage statistics and charts.

    Displays:
    - Three stat cards (today, this month, last task)
    - Token usage bar chart (last 30 days)
    - Cost breakdown pie chart (by model)
    - Recent tasks table (last 20)
    """

    def __init__(self, app_controller: AppController) -> None:
        """Initialise the usage tab.

        Args:
            app_controller: The application controller for data access.
        """
        super().__init__()
        self._controller = app_controller
        self._ledger = getattr(app_controller, "_ledger", None)

        self.setObjectName("usageBody")
        self.setStyleSheet(_TAB_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Top bar ───────────────────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        title = QLabel("Usage & Costs")
        title.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")
        top_row.addWidget(title)

        top_row.addStretch(1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setStyleSheet(_BUTTON_REFRESH_STYLE)
        self._refresh_btn.clicked.connect(self.reload)
        top_row.addWidget(self._refresh_btn)

        layout.addLayout(top_row)

        # ── Stat cards ────────────────────────────────────────────────────
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self._today_card = _StatCard("—", "Today")
        cards_layout.addWidget(self._today_card)

        self._month_card = _StatCard("—", "This month")
        cards_layout.addWidget(self._month_card)

        self._last_task_card = _StatCard("—", "Last task")
        cards_layout.addWidget(self._last_task_card)

        layout.addLayout(cards_layout)

        # ── Charts row ────────────────────────────────────────────────────
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(12)

        # Left: bar chart (token usage per day).
        self._bar_container = QFrame()
        self._bar_container.setObjectName("chartContainer")
        self._bar_container.setStyleSheet(_CHART_CONTAINER_STYLE)
        bar_layout = QVBoxLayout(self._bar_container)
        bar_layout.setContentsMargins(8, 8, 8, 8)
        bar_layout.setSpacing(4)

        bar_title = QLabel("Token Usage (Last 30 Days)")
        bar_title.setStyleSheet(_SECTION_LABEL_STYLE)
        bar_layout.addWidget(bar_title)

        self._bar_chart = QWidget()
        self._bar_chart.setMinimumHeight(180)
        self._bar_chart.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        bar_layout.addWidget(self._bar_chart, 1)
        charts_layout.addWidget(self._bar_container, 3)

        # Right: pie chart (cost by model).
        self._pie_container = QFrame()
        self._pie_container.setObjectName("chartContainer")
        self._pie_container.setStyleSheet(_CHART_CONTAINER_STYLE)
        pie_layout = QVBoxLayout(self._pie_container)
        pie_layout.setContentsMargins(8, 8, 8, 8)
        pie_layout.setSpacing(4)

        pie_title = QLabel("Cost by Model")
        pie_title.setStyleSheet(_SECTION_LABEL_STYLE)
        pie_layout.addWidget(pie_title)

        self._pie_chart = QWidget()
        self._pie_chart.setMinimumHeight(180)
        self._pie_chart.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        pie_layout.addWidget(self._pie_chart, 1)
        charts_layout.addWidget(self._pie_container, 2)

        layout.addLayout(charts_layout)

        # ── Recent tasks table ────────────────────────────────────────────
        table_label = QLabel("Recent Tasks")
        table_label.setStyleSheet(_SECTION_LABEL_STYLE)
        layout.addWidget(table_label)

        self._table = QTableWidget(0, 5)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().hide()
        self._table.setHorizontalHeaderLabels([
            "Timestamp", "Model", "Tokens", "Cost", "Status"
        ])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.resizeSection(0, 140)
        header.resizeSection(1, 120)
        layout.addWidget(self._table, 1)

    # ── public API ───────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Refresh all data from the usage ledger."""
        self._refresh_cards()
        self._refresh_charts()
        self._refresh_table()

    # ── internal: cards ──────────────────────────────────────────────────────

    def _refresh_cards(self) -> None:
        """Update the three stat cards."""
        ledger = self._ledger
        if ledger is None:
            self._today_card.set_value("—")
            self._month_card.set_value("—")
            self._last_task_card.set_value("—")
            return

        try:
            today = ledger.today_total()
            today_cost = Decimal(today.get("cost_usd", "0"))
            today_tokens = today.get("total_tokens", 0)
            today_tasks = today.get("task_count", 0)
            self._today_card.set_value(
                f"${today_cost:.3f} · {today_tokens:,} tokens · "
                f"{today_tasks} task{'s' if today_tasks != 1 else ''}"
            )
        except Exception:  # noqa: BLE001
            self._today_card.set_value("—")

        try:
            month = ledger.month_total()
            month_cost = Decimal(month.get("cost_usd", "0"))
            month_tokens = month.get("total_tokens", 0)
            month_tasks = month.get("task_count", 0)
            self._month_card.set_value(
                f"${month_cost:.3f} · {month_tokens:,} tokens · "
                f"{month_tasks} task{'s' if month_tasks != 1 else ''}"
            )
        except Exception:  # noqa: BLE001
            self._month_card.set_value("—")

        try:
            recent = ledger.recent_tasks(limit=1)
            if recent:
                last = recent[0]
                last_cost = Decimal(last.get("cost_usd", "0"))
                last_tokens = last.get("total_tokens", 0)
                # Steps not available in ledger — show tokens only.
                self._last_task_card.set_value(
                    f"${last_cost:.3f} · {last_tokens:,} tokens"
                )
            else:
                self._last_task_card.set_value("No tasks yet")
        except Exception:  # noqa: BLE001
            self._last_task_card.set_value("—")

    # ── internal: charts (pyqtgraph) ─────────────────────────────────────────

    def _refresh_charts(self) -> None:
        """Rebuild the bar and pie charts."""
        ledger = self._ledger
        if ledger is None:
            return

        # Clear existing chart content.
        self._clear_chart(self._bar_chart)
        self._clear_chart(self._pie_chart)

        # ── Bar chart: daily token usage ──────────────────────────────────
        try:
            daily = ledger.daily_series(days=30)
            self._draw_bar_chart(daily)
        except Exception:  # noqa: BLE001
            self._draw_empty_label(self._bar_chart, "No data available")

        # ── Pie chart: cost by model ──────────────────────────────────────
        try:
            by_model = ledger.cost_by_model()
            self._draw_pie_chart(by_model)
        except Exception:  # noqa: BLE001
            self._draw_empty_label(self._pie_chart, "No data available")

    def _clear_chart(self, container: QWidget) -> None:
        """Remove all child widgets from a chart container."""
        while container.layout() is not None:
            item = container.layout().takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
            elif item and item.layout():
                # Clear nested layouts recursively.
                pass
        # Remove the layout itself.
        old_layout = container.layout()
        if old_layout is not None:
            from PySide6.QtWidgets import QVBoxLayout

            # Delete the old layout by setting a new one.
            pass
        # Set a fresh layout.
        from PySide6.QtWidgets import QVBoxLayout

        new_layout = QVBoxLayout(container)
        new_layout.setContentsMargins(0, 0, 0, 0)
        container.setLayout(new_layout)

    def _draw_empty_label(self, container: QWidget, text: str) -> None:
        """Show a placeholder label in a chart container."""
        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
            container.setLayout(layout)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(label)

    def _draw_bar_chart(self, daily: list[dict[str, Any]]) -> None:
        """Draw a bar chart using pyqtgraph.

        Args:
            daily: List of dicts with ``"date"``, ``"total_tokens"``,
                ``"cost_usd"``.
        """
        try:
            import pyqtgraph as pg
        except ImportError:
            self._draw_empty_label(
                self._bar_chart,
                "pyqtgraph not installed — install with ``pip install pyqtgraph``",
            )
            return

        layout = self._bar_chart.layout()
        if layout is None:
            layout = QVBoxLayout(self._bar_chart)
            self._bar_chart.setLayout(layout)

        plot_widget = pg.PlotWidget()
        plot_widget.setBackground("#252525")
        plot_widget.showGrid(x=False, y=True, alpha=0.3)
        plot_widget.setLabel("left", "Tokens", color="#CCCCCC")
        plot_widget.setLabel("bottom", "Date", color="#CCCCCC")

        if not daily:
            layout.addWidget(plot_widget)
            return

        dates = [d["date"][5:] for d in daily]  # "MM-DD"
        values = [d["total_tokens"] for d in daily]

        # Build bar graph.
        x_axis = list(range(len(values)))
        bg = pg.BarGraphItem(
            x=x_axis,
            height=values,
            width=0.6,
            brush=QColor("#0078D4"),
            pen=QColor("#0078D4"),
        )
        plot_widget.addItem(bg)

        # Configure x-axis ticks.
        tick_interval = max(1, len(dates) // 7)
        ticks = [
            (i, dates[i])
            for i in range(0, len(dates), tick_interval)
        ]
        axis = plot_widget.getAxis("bottom")
        axis.setTicks([ticks])
        axis.setStyle(tickFont=QFont("Segoe UI", 8))

        plot_widget.getAxis("left").setStyle(
            tickFont=QFont("Segoe UI", 8)
        )

        layout.addWidget(plot_widget)

    def _draw_pie_chart(self, by_model: list[dict[str, Any]]) -> None:
        """Draw a pie chart using pyqtgraph.

        Args:
            by_model: List of dicts with ``"model"``, ``"total_tokens"``,
                ``"cost_usd"``.
        """
        try:
            import pyqtgraph as pg
        except ImportError:
            self._draw_empty_label(
                self._pie_chart,
                "pyqtgraph not installed",
            )
            return

        layout = self._pie_chart.layout()
        if layout is None:
            layout = QVBoxLayout(self._pie_chart)
            self._pie_chart.setLayout(layout)

        if not by_model:
            self._draw_empty_label(self._pie_chart, "No data available")
            return

        # Build a legend using labels + percent, since pyqtgraph doesn't
        # have a native pie chart widget.  We'll draw a simple wedge
        # approximation using a scatter plot with arcs, or fall back to
        # a horizontal stacked bar.  The simplest approach is to manually
        # draw colored boxes with labels.
        total_cost = sum(Decimal(m["cost_usd"]) for m in by_model)
        if total_cost == 0:
            self._draw_empty_label(self._pie_chart, "All costs $0.00")
            return

        colors = [
            QColor("#0078D4"),  # blue
            QColor("#4CAF50"),  # green
            QColor("#FFC107"),  # amber
            QColor("#F44336"),  # red
            QColor("#9E9E9E"),  # gray
            QColor("#FF9800"),  # orange
        ]

        legend_layout = QVBoxLayout()
        legend_layout.setSpacing(4)
        legend_layout.setContentsMargins(8, 8, 8, 8)

        for i, m in enumerate(by_model):
            cost = Decimal(m["cost_usd"])
            pct = (cost / total_cost) * 100 if total_cost > 0 else 0
            color = colors[i % len(colors)]

            row = QHBoxLayout()
            row.setSpacing(6)

            # Color swatch.
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(
                f"background: {color.name()}; border-radius: 2px;"
            )
            row.addWidget(swatch)

            # Label.
            label = QLabel(
                f"{m['model']} — ${cost:.3f} ({pct:.1f}%)"
            )
            label.setStyleSheet("color: #CCCCCC; font-size: 11px;")
            row.addWidget(label, 1)

            legend_layout.addLayout(row)

        # Add a stacked bar visual for the pie approximation.
        stacked_row = QHBoxLayout()
        stacked_row.setSpacing(0)
        stacked_row.setContentsMargins(0, 4, 0, 0)

        for i, m in enumerate(by_model):
            cost = Decimal(m["cost_usd"])
            pct = (cost / total_cost) * 100 if total_cost > 0 else 0
            if pct < 1:
                continue
            color = colors[i % len(colors)]
            bar = QLabel()
            bar.setFixedHeight(16)
            bar.setStyleSheet(
                f"background: {color.name()}; border-radius: 2px;"
            )
            bar.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Fixed
            )
            # Approximate width by percentage.
            stacked_row.addWidget(bar, int(pct))

        legend_layout.addLayout(stacked_row)
        layout.addLayout(legend_layout)
        layout.addStretch(1)

    # ── internal: recent tasks table ─────────────────────────────────────────

    def _refresh_table(self) -> None:
        """Populate the recent tasks table."""
        ledger = self._ledger
        if ledger is None:
            return

        try:
            tasks = ledger.recent_tasks(limit=20)
        except Exception:  # noqa: BLE001
            tasks = []

        self._table.setRowCount(0)

        for task in tasks:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Timestamp.
            ts = task.get("timestamp", 0)
            ts_str = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(float(ts))
            ) if ts else "—"
            self._table.setItem(
                row, 0, QTableWidgetItem(ts_str)
            )

            # Model.
            self._table.setItem(
                row, 1, QTableWidgetItem(task.get("model", "—"))
            )

            # Tokens.
            tokens = task.get("total_tokens", 0)
            token_item = QTableWidgetItem(f"{tokens:,}")
            token_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 2, token_item)

            # Cost.
            cost_val = Decimal(task.get("cost_usd", "0"))
            cost_item = QTableWidgetItem(f"${cost_val:.4f}")
            cost_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 3, cost_item)

            # Status (not available in ledger — show placeholder).
            status_item = QTableWidgetItem("completed")
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(QColor("#4CAF50"))
            self._table.setItem(row, 4, status_item)

        if not tasks:
            self._table.setRowCount(1)
            empty = QTableWidgetItem("No usage data yet")
            empty.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(0, 0, empty)
