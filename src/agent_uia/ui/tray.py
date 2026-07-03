# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""
System tray icon for TNT.

Tray icon is rendered procedurally via ``QPainter``; no PNG asset dependency
in this prompt. Visual polish will come with the main-window prompt.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "State",
    "TrayIcon",
]


class State(Enum):
    """Tray icon state — determines color and tooltip."""

    IDLE = "idle"
    THINKING = "thinking"
    PAUSED = "paused"
    ERROR = "error"


# ── per-state assets ─────────────────────────────────────────────────────────

_STATE_COLORS: dict[State, QColor] = {
    State.IDLE: QColor("#4CAF50"),      # green
    State.THINKING: QColor("#FFC107"),  # amber
    State.PAUSED: QColor("#9E9E9E"),    # gray
    State.ERROR: QColor("#F44336"),     # red
}

_STATE_TOOLTIPS: dict[State, str] = {
    State.IDLE: "Type and Talk (TNT) — Idle",
    State.THINKING: "Type and Talk (TNT) — Thinking...",
    State.PAUSED: "Type and Talk (TNT) — Paused",
    State.ERROR: "Type and Talk (TNT) — Error",
}


def _make_icon(state: State) -> QIcon:
    """Render a 64×64 tray icon with a colored dot and 'TNT' wordmark."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Background circle.
    color = _STATE_COLORS[state]
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 60, 60)

    # "TNT" wordmark in white.
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", 18, QFont.Bold)
    painter.setFont(font)
    painter.drawText(QRect(0, 10, 64, 44), Qt.AlignCenter, "TNT")

    painter.end()
    return QIcon(pixmap)


# ── TrayIcon ─────────────────────────────────────────────────────────────────


class TrayIcon(QSystemTrayIcon):
    """System tray icon with state-driven appearance and context menu.

    Signals:
        toggle_window_requested: Emitted on left-click to toggle the floating
            window.
        _state_changed: Internal signal to marshal state updates to the Qt
            thread.
    """

    toggle_window_requested = Signal()
    _state_changed = Signal(object)

    def __init__(self, app_controller: AppController) -> None:  # noqa: F821 — circular import, resolved at runtime
        super().__init__(parent=None)
        self._controller = app_controller
        self._state = State.IDLE

        # Build icons for all states.
        self._icons: dict[State, QIcon] = {s: _make_icon(s) for s in State}

        self.setIcon(self._icons[State.IDLE])
        self.setToolTip(_STATE_TOOLTIPS[State.IDLE])

        # Context menu (right-click).
        self._menu = QMenu()
        self._open_floating_action = QAction("Floating window")
        self._open_floating_action.triggered.connect(self._on_open_floating)
        self._menu.addAction(self._open_floating_action)

        self._open_main_action = QAction("Open main window")
        self._open_main_action.triggered.connect(self._on_open_main)
        self._menu.addAction(self._open_main_action)

        self._menu.addSeparator()

        self._pause_action = QAction("Pause Agent")
        self._pause_action.setCheckable(True)
        self._pause_action.triggered.connect(self._on_toggle_paused)
        self._menu.addAction(self._pause_action)

        self._menu.addSeparator()

        self._quit_action = QAction("Quit")
        self._quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)

        # Left-click → toggle floating window.
        self.activated.connect(self._on_activated)

        # State updates are marshalled through this signal so that the actual
        # QIcon/QPixmap changes happen on the Qt thread.
        self._state_changed.connect(self._apply_state)

    # ── state setter (thread-safe) ───────────────────────────────────────

    def set_state(self, state: State) -> None:
        """Update icon and tooltip. Safe to call from any thread."""
        self._state = state
        self._state_changed.emit(state)

    def _apply_state(self, state: object) -> None:
        """Apply a state update on the Qt thread."""
        state = state if isinstance(state, State) else State.IDLE
        icon = self._icons.get(state, self._icons[State.IDLE])
        tooltip = _STATE_TOOLTIPS.get(state, _STATE_TOOLTIPS[State.IDLE])
        self.setIcon(icon)
        self.setToolTip(tooltip)

    # ── internal slots ───────────────────────────────────────────────────

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # left-click on Windows
            self.toggle_window_requested.emit()

    def _on_open_floating(self) -> None:
        self._controller.show_floating_window()

    def _on_open_main(self) -> None:
        self._controller.show_main_window()

    def _on_toggle_paused(self, checked: bool) -> None:
        self._controller.toggle_paused()

    def _on_quit(self) -> None:
        self._controller.quit()
