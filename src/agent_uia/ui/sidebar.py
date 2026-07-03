# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Left navigation pane for the TNT main window.

Provides a fixed-width (180 px) sidebar with the TNT wordmark, six
navigation tabs in an exclusive QButtonGroup, and utility buttons at the
bottom (Pause, Help, Quit).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from agent_uia.ui.theme import Theme, ThemeManager

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "SIDEBAR_WIDTH",
    "Sidebar",
]

SIDEBAR_WIDTH: Final[int] = 180
"""Fixed width of the sidebar pane in pixels."""

_NAV_ITEMS: list[tuple[str, str, str]] = [
    # (label, emoji, tab_name)
    ("Home", "\U0001F3E0", "home"),
    ("History", "\U0001F4AC", "history"),
    ("Skills", "\u26A1", "skills"),
    ("Settings", "\u2699\uFE0F", "settings"),
    ("Usage", "\U0001F4CA", "usage"),
    ("Performance", "\U0001F4C8", "performance"),
]

_BOTTOM_BUTTONS: list[tuple[str, str, bool]] = [
    # (label, emoji, is_checkable)
    ("Pause Agent", "\u23F8", True),
    ("Help", "\u2753", False),
    ("Quit", "\U0001F6AA", False),
]


class Sidebar(QFrame):
    """Left-side navigation pane.

    Signals:
        navigate_to: Emitted with the tab name when a navigation button is
            clicked.
        pause_toggled: Emitted when the Pause button is toggled.
        help_requested: Emitted when the Help button is clicked.
        quit_requested: Emitted when the Quit button is clicked.
    """

    navigate_to = Signal(str)
    pause_toggled = Signal(bool)
    help_requested = Signal()
    quit_requested = Signal()

    def __init__(self, app_controller: AppController, parent: QWidget | None = None) -> None:
        """Initialise the sidebar.

        Args:
            app_controller: The application controller for state queries.
            parent:         Optional parent widget.
        """
        super().__init__(parent)
        self._controller = app_controller

        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        # ── apply component style ───────────────────────────────────────────
        theme = (
            Theme.DARK
            if self._controller.config.theme == "dark"
            else Theme.LIGHT
        )
        self.setStyleSheet(ThemeManager.get_component_style("sidebar", theme))

        # ── layout ──────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── top: wordmark + version ─────────────────────────────────────────
        wordmark = QLabel("TNT")
        wordmark.setObjectName("wordmark")
        font = QFont("Segoe UI", 18, QFont.Bold)
        wordmark.setFont(font)
        layout.addWidget(wordmark)

        version = QLabel("v0.1.0")
        version.setObjectName("version")
        layout.addWidget(version)

        layout.addSpacing(12)

        # ── middle: navigation buttons ──────────────────────────────────────
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QToolButton] = []

        for label, emoji, tab_name in _NAV_ITEMS:
            btn = QToolButton()
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setText(f"{emoji}  {label}")
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(36)

            # Store tab name as a dynamic property for lookup.
            btn.setProperty("tab_name", tab_name)

            self._nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        # Select the first tab (Home) by default.
        if self._nav_buttons:
            self._nav_buttons[0].setChecked(True)

        self._nav_group.idClicked.connect(self._on_nav_clicked)

        # ── spacer (pushes bottom buttons down) ─────────────────────────────
        layout.addStretch(1)

        # ── separator ───────────────────────────────────────────────────────
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        layout.addSpacing(4)

        # ── bottom: utility buttons ─────────────────────────────────────────
        for label, emoji, is_checkable in _BOTTOM_BUTTONS:
            btn = QToolButton()
            btn.setObjectName("bottomBtn")
            btn.setText(f"{emoji}  {label}")
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(36)

            if is_checkable:
                btn.setCheckable(True)
                btn.toggled.connect(self._on_pause_toggled)
            else:
                btn.clicked.connect(self._on_bottom_clicked)

            # Tag the button for identification in the slot.
            btn.setProperty("action", label.lower().replace(" ", "_"))

            layout.addWidget(btn)

        # ── bottom margin ───────────────────────────────────────────────────
        layout.addSpacing(8)

    # ── public helpers ─────────────────────────────────────────────────────────

    def select_tab(self, tab_name: str) -> None:
        """Programmatically select a navigation tab.

        Args:
            tab_name: One of ``"home"``, ``"history"``, ``"skills"``,
                ``"settings"``, ``"usage"``, ``"performance"``.
        """
        for btn in self._nav_buttons:
            if btn.property("tab_name") == tab_name:
                btn.setChecked(True)
                self.navigate_to.emit(tab_name)
                return

    # ── internal slots ─────────────────────────────────────────────────────────

    def _on_nav_clicked(self, button_id: int) -> None:
        """Emit ``navigate_to`` with the clicked tab's name."""
        btn = self._nav_group.button(button_id)
        if btn is None:
            return
        tab_name = btn.property("tab_name")
        if tab_name:
            self.navigate_to.emit(tab_name)

    def _on_pause_toggled(self, checked: bool) -> None:
        """Forward pause toggle to the controller and emit."""
        self._controller.toggle_paused()
        self.pause_toggled.emit(checked)

    def _on_bottom_clicked(self) -> None:
        """Handle Help / Quit bottom buttons."""
        btn = self.sender()
        if btn is None:
            return
        action = btn.property("action")

        if action == "help":
            self.help_requested.emit()
        elif action == "quit":
            self.quit_requested.emit()
