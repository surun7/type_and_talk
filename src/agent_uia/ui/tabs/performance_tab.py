# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Performance tab: latency breakdown charts, LLM call history, and event log."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
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
    "PerformanceTab",
]

# ── styling ──────────────────────────────────────────────────────────────────

_TAB_STYLE = """
QWidget#perfBody {
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

_BUTTON_EXPORT_STYLE = """
QPushButton {
    background: #1A3A5C;
    color: #3b8eea;
    border: 1px solid #3b8eea;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 11px;
}
QPushButton:hover {
    background: #264F78;
}
"""

_EMPTY_STYLE = "color: #666666; font-size: 14px;"


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


class PerformanceTab(QWidget):
    """Main-window tab showing performance statistics and charts.

    Displays:
    - Four stat cards (LLM call latency, tool action latency, task duration,
      memory usage)
    - Latency breakdown bar chart (p50/p95/p99 by phase)
    - LLM call count over time (last 24h)
    - Recent events table (last 50, sortable)
    """

    def __init__(self, app_controller: AppController) -> None:
        """Initialise the performance tab.

        Args:
            app_controller: The application controller for data access.
        """
        super().__init__()
        self._controller = app_controller

        self.setObjectName("perfBody")
        self.setStyleSheet(_TAB_STYLE)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)

        # ── Top bar ─────────────────────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        title = QLabel("Performance")
        title.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")
        top_row.addWidget(title)

        top_row.addStretch(1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setStyleSheet(_BUTTON_REFRESH_STYLE)
        self._refresh_btn.clicked.connect(self.reload)
        top_row.addWidget(self._refresh_btn)

        self._export_btn = QPushButton("Export to JSON")
        self._export_btn.setStyleSheet(_BUTTON_EXPORT_STYLE)
        self._export_btn.clicked.connect(self._export_to_json)
        top_row.addWidget(self._export_btn)

        self._layout.addLayout(top_row)

        # ── Stat cards ──────────────────────────────────────────────────────
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self._llm_card = _StatCard("—", "Avg LLM call")
        cards_layout.addWidget(self._llm_card)

        self._tool_card = _StatCard("—", "Avg tool action")
        cards_layout.addWidget(self._tool_card)

        self._task_card = _StatCard("—", "Avg task")
        cards_layout.addWidget(self._task_card)

        self._memory_card = _StatCard("—", "Memory")
        cards_layout.addWidget(self._memory_card)

        self._layout.addLayout(cards_layout)

        # ── Charts row ──────────────────────────────────────────────────────
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(12)

        # Left: latency breakdown bar chart (p50/p95/p99 by phase).
        self._latency_container = QFrame()
        self._latency_container.setObjectName("chartContainer")
        self._latency_container.setStyleSheet(_CHART_CONTAINER_STYLE)
        latency_layout = QVBoxLayout(self._latency_container)
        latency_layout.setContentsMargins(8, 8, 8, 8)
        latency_layout.setSpacing(4)

        latency_title = QLabel("Latency by Phase (p50 / p95 / p99)")
        latency_title.setStyleSheet(_SECTION_LABEL_STYLE)
        latency_layout.addWidget(latency_title)

        self._latency_chart = QWidget()
        self._latency_chart.setMinimumHeight(200)
        self._latency_chart.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        latency_layout.addWidget(self._latency_chart, 1)
        charts_layout.addWidget(self._latency_container, 3)

        # Right: LLM call count over time.
        self._llm_time_container = QFrame()
        self._llm_time_container.setObjectName("chartContainer")
        self._llm_time_container.setStyleSheet(_CHART_CONTAINER_STYLE)
        llm_time_layout = QVBoxLayout(self._llm_time_container)
        llm_time_layout.setContentsMargins(8, 8, 8, 8)
        llm_time_layout.setSpacing(4)

        llm_time_title = QLabel("LLM Calls Over Time (Last 24h)")
        llm_time_title.setStyleSheet(_SECTION_LABEL_STYLE)
        llm_time_layout.addWidget(llm_time_title)

        self._llm_time_chart = QWidget()
        self._llm_time_chart.setMinimumHeight(200)
        self._llm_time_chart.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        llm_time_layout.addWidget(self._llm_time_chart, 1)
        charts_layout.addWidget(self._llm_time_container, 2)

        self._layout.addLayout(charts_layout)

        # ── Events table ────────────────────────────────────────────────────
        table_label = QLabel("Recent Events (Last 50)")
        table_label.setStyleSheet(_SECTION_LABEL_STYLE)
        self._layout.addWidget(table_label)

        self._table = QTableWidget(0, 4)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().hide()
        self._table.setHorizontalHeaderLabels([
            "Timestamp", "Metric", "Value", "Tags"
        ])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.resizeSection(0, 140)
        header.resizeSection(1, 150)
        header.resizeSection(2, 100)
        self._table.setSortingEnabled(True)
        self._layout.addWidget(self._table, 1)

        # ── Empty state label (shown when no data) ──────────────────────────
        self._empty_label = QLabel("No performance data yet.")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(_EMPTY_STYLE)
        self._empty_label.setHidden(True)
        self._layout.addWidget(self._empty_label)

        # ── Auto-refresh timer ──────────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.setInterval(2000)  # 2 seconds
        self._timer.timeout.connect(self.reload)
        self._timer.start()

        # Initial data load.
        self.reload()

    # ── public API ─────────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Refresh all data from the performance monitor."""
        try:
            from agent_uia.ui.app_controller import default_monitor
            summary = default_monitor().summary()
        except Exception:  # noqa: BLE001
            self._show_empty(True)
            return

        if not summary or not any(
            v for k, v in summary.items() if isinstance(v, (int, float, str))
        ):
            self._show_empty(True)
            return

        self._show_empty(False)
        self._refresh_cards(summary)
        self._refresh_charts(summary)
        self._refresh_table(summary)

    # ── internal: empty state ─────────────────────────────────────────────────

    def _show_empty(self, empty: bool) -> None:
        """Toggle the empty-state label visibility."""
        self._empty_label.setVisible(empty)

    # ── internal: cards ───────────────────────────────────────────────────────

    def _refresh_cards(self, summary: dict[str, Any]) -> None:
        """Update the four stat cards."""
        # Avg LLM call.
        avg_llm = summary.get("avg_llm_call_ms", None)
        cache_hit = summary.get("avg_llm_call_cache_hit_ms", None)
        if avg_llm is not None:
            if cache_hit is not None:
                self._llm_card.set_value(
                    f"{avg_llm:.1f}s (cache hit: {cache_hit:.0f}ms)"
                )
            else:
                self._llm_card.set_value(f"{avg_llm:.1f}s")
        else:
            self._llm_card.set_value("—")

        # Avg tool action.
        avg_tool = summary.get("avg_tool_action_ms", None)
        if avg_tool is not None:
            self._tool_card.set_value(f"{avg_tool:.0f}ms")
        else:
            self._tool_card.set_value("—")

        # Avg task.
        avg_task_s = summary.get("avg_task_duration_s", None)
        avg_task_steps = summary.get("avg_task_steps", None)
        if avg_task_s is not None:
            steps_str = f" · {avg_task_steps} steps" if avg_task_steps is not None else ""
            self._task_card.set_value(f"{avg_task_s:.1f}s{steps_str}")
        else:
            self._task_card.set_value("—")

        # Memory.
        mem = summary.get("memory_mb", None)
        if mem is not None:
            self._memory_card.set_value(f"{mem:.0f} MB")
        else:
            self._memory_card.set_value("—")

    # ── internal: charts (pyqtgraph) ───────────────────────────────────────────

    def _refresh_charts(self, summary: dict[str, Any]) -> None:
        """Rebuild the latency breakdown and LLM-over-time charts."""
        self._clear_chart(self._latency_chart)
        self._clear_chart(self._llm_time_chart)

        phase_latencies = summary.get("phase_latencies")
        if phase_latencies:
            self._draw_latency_chart(phase_latencies)
        else:
            self._draw_empty_label(self._latency_chart, "No latency data")

        llm_calls = summary.get("llm_calls_over_time")
        if llm_calls:
            self._draw_llm_time_chart(llm_calls)
        else:
            self._draw_empty_label(self._llm_time_chart, "No call data")

    def _clear_chart(self, container: QWidget) -> None:
        """Remove all child widgets from a chart container."""
        while container.layout() is not None:
            item = container.layout().takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        old_layout = container.layout()
        if old_layout is not None:
            pass
        from PySide6.QtWidgets import QVBoxLayout

        new_layout = QVBoxLayout(container)
        new_layout.setContentsMargins(0, 0, 0, 0)
        container.setLayout(new_layout)

    def _draw_empty_label(self, container: QWidget, text: str) -> None:
        """Show a placeholder label in a chart container."""
        layout = container.layout()
        if layout is None:
            from PySide6.QtWidgets import QVBoxLayout
            layout = QVBoxLayout(container)
            container.setLayout(layout)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(label)

    def _draw_latency_chart(
        self, phase_latencies: dict[str, dict[str, float]]
    ) -> None:
        """Draw a grouped bar chart of p50/p95/p99 latencies by phase.

        Args:
            phase_latencies: Mapping of phase name -> {"p50": ..., "p95": ..., "p99": ...}
        """
        try:
            import pyqtgraph as pg
            import numpy as np
        except ImportError:
            self._draw_empty_label(
                self._latency_chart,
                "pyqtgraph not installed — install with ``pip install pyqtgraph``",
            )
            return

        layout = self._latency_chart.layout()
        if layout is None:
            from PySide6.QtWidgets import QVBoxLayout
            layout = QVBoxLayout(self._latency_chart)
            self._latency_chart.setLayout(layout)

        plot_widget = pg.PlotWidget()
        plot_widget.setBackground("#252525")
        plot_widget.showGrid(x=False, y=True, alpha=0.3)
        plot_widget.setLabel("left", "Latency (ms)", color="#CCCCCC")
        plot_widget.setLabel("bottom", "Phase", color="#CCCCCC")

        if not phase_latencies:
            layout.addWidget(plot_widget)
            return

        phases = list(phase_latencies.keys())
        n_phases = len(phases)
        bar_width = 0.2
        offsets = [-bar_width, 0, bar_width]  # p50, p95, p99

        colors = {
            "p50": QColor("#3b8eea"),
            "p95": QColor("#4CAF50"),
            "p99": QColor("#F44336"),
        }

        for idx, phase in enumerate(phases):
            latencies = phase_latencies[phase]
            x_center = idx
            for percentile, offset in zip(("p50", "p95", "p99"), offsets):
                value = latencies.get(percentile, 0)
                bar = pg.BarGraphItem(
                    x=[x_center + offset],
                    height=[value * 1000],  # convert to ms
                    width=bar_width * 0.8,
                    brush=colors[percentile],
                    pen=colors[percentile],
                )
                plot_widget.addItem(bar)

        # Configure x-axis ticks.
        ticks = [(i, p) for i, p in enumerate(phases)]
        axis = plot_widget.getAxis("bottom")
        axis.setTicks([ticks])
        axis.setStyle(tickFont=QFont("Segoe UI", 8))

        plot_widget.getAxis("left").setStyle(tickFont=QFont("Segoe UI", 8))

        # Add a small legend.
        legend = plot_widget.addLegend(offset=(-10, 10))
        for percentile, color in colors.items():
            line = pg.PlotDataItem(
                pen=color,
                name=percentile,
            )
            legend.addItem(line, percentile)

        layout.addWidget(plot_widget)

    def _draw_llm_time_chart(
        self, llm_calls: list[dict[str, Any]]
    ) -> None:
        """Draw a line chart of LLM call count over time.

        Args:
            llm_calls: List of dicts with ``"hour"`` and ``"count"``.
        """
        try:
            import pyqtgraph as pg
        except ImportError:
            self._draw_empty_label(
                self._llm_time_chart,
                "pyqtgraph not installed",
            )
            return

        layout = self._llm_time_chart.layout()
        if layout is None:
            from PySide6.QtWidgets import QVBoxLayout
            layout = QVBoxLayout(self._llm_time_chart)
            self._llm_time_chart.setLayout(layout)

        plot_widget = pg.PlotWidget()
        plot_widget.setBackground("#252525")
        plot_widget.showGrid(x=False, y=True, alpha=0.3)
        plot_widget.setLabel("left", "Calls", color="#CCCCCC")
        plot_widget.setLabel("bottom", "Hour", color="#CCCCCC")

        if not llm_calls:
            layout.addWidget(plot_widget)
            return

        hours = [c["hour"] for c in llm_calls]
        counts = [c["count"] for c in llm_calls]

        # Use short hour labels.
        short_labels = [h[-5:] if len(h) > 5 else h for h in hours]

        x_vals = list(range(len(counts)))
        pen = pg.mkPen(color=QColor("#3b8eea"), width=2)
        plot_widget.plot(x_vals, counts, pen=pen, symbol="o", symbolBrush=QColor("#3b8eea"))

        # Configure x-axis ticks.
        tick_interval = max(1, len(short_labels) // 6)
        ticks = [
            (i, short_labels[i])
            for i in range(0, len(short_labels), tick_interval)
        ]
        axis = plot_widget.getAxis("bottom")
        axis.setTicks([ticks])
        axis.setStyle(tickFont=QFont("Segoe UI", 8))

        plot_widget.getAxis("left").setStyle(tickFont=QFont("Segoe UI", 8))

        layout.addWidget(plot_widget)

    # ── internal: events table ─────────────────────────────────────────────────

    def _refresh_table(self, summary: dict[str, Any]) -> None:
        """Populate the events table from summary data."""
        events = summary.get("events", [])

        self._table.setRowCount(0)

        for event in events[-50:]:  # last 50
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Timestamp.
            ts = event.get("timestamp", 0)
            ts_str = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
                if ts else "—"
            )
            self._table.setItem(row, 0, QTableWidgetItem(ts_str))

            # Metric name.
            self._table.setItem(
                row, 1, QTableWidgetItem(event.get("metric", "—"))
            )

            # Value.
            val = event.get("value", "")
            val_item = QTableWidgetItem(str(val))
            val_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 2, val_item)

            # Tags.
            tags = event.get("tags", "")
            self._table.setItem(row, 3, QTableWidgetItem(str(tags)))

        if not events:
            self._table.setRowCount(1)
            empty = QTableWidgetItem("No performance data yet.")
            empty.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(0, 0, empty)

    # ── internal: export ───────────────────────────────────────────────────────

    def _export_to_json(self) -> None:
        """Export current performance data to a JSON file."""
        try:
            from agent_uia.ui.app_controller import default_monitor
            summary = default_monitor().summary()
        except Exception:  # noqa: BLE001
            summary = {}

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Performance Data",
            "performance_data.json",
            "JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except OSError:
            logger = __import__("logging").getLogger(__name__)
            logger.exception("Failed to export performance data to %s", file_path)
