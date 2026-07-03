# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Main application window for TNT.

Provides a sidebar-navigation layout with four tabs:
- History — browse/search past conversations.
- Usage — cost breakdown, token charts, recent tasks.
- Settings — all configurable options.
- (Future tabs can be added by appending to the sidebar and the stack.)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "MainWindow",
]

logger = logging.getLogger(__name__)

# ── styling ──────────────────────────────────────────────────────────────────

_SIDEBAR_STYLE = """
QWidget#sidebar {
    background: #252525;
    border-right: 1px solid #333333;
}
"""

_SIDEBAR_BTN_BASE = (
    "QPushButton {{"
    "    background: transparent;"
    "    color: #AAAAAA;"
    "    border: none;"
    "    border-radius: 6px;"
    "    padding: 10px 12px;"
    "    font-size: 13px;"
    "    text-align: left;"
    "}}"
    "QPushButton:hover {{"
    "    background: #333333;"
    "    color: #E0E0E0;"
    "}}"
    "QPushButton:checked {{"
    "    background: #0078D4;"
    "    color: #FFFFFF;"
    "    font-weight: bold;"
    "}}"
)

_SIDEBAR_TITLE_STYLE = "color: #888888; font-size: 11px; font-weight: bold; text-transform: uppercase; padding: 8px 12px 4px 12px;"

_MAIN_STYLE = """
QWidget#mainContent {
    background: #1E1E1E;
}
"""

_WINDOW_STYLE = """
QMainWindow {
    background: #1E1E1E;
}
"""

# ── icon generation (reuses pattern from tray.py) ────────────────────────────


def _make_window_icon() -> QIcon:
    """Render a 64×64 window icon with a blue "TNT" wordmark.

    Reuses the same ``QPainter`` pattern as the tray icon but uses the
    accent blue color instead of the state-based color.
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Background circle.
    painter.setBrush(QColor("#0078D4"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 60, 60)

    # "TNT" wordmark in white.
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", 18, QFont.Bold)
    painter.setFont(font)
    painter.drawText(
        pixmap.rect().adjusted(0, 10, 0, -10),
        Qt.AlignCenter,
        "TNT",
    )

    painter.end()
    return QIcon(pixmap)


# ── sidebar button ───────────────────────────────────────────────────────────


class _SidebarButton(QPushButton):
    """A toggleable sidebar navigation button.

    Visually indicates the active tab via the ``checked`` state.
    """

    def __init__(self, text: str, tab_name: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._tab_name = tab_name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_SIDEBAR_BTN_BASE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(38)

    @property
    def tab_name(self) -> str:
        """Return the tab identifier associated with this button."""
        return self._tab_name


# ── MainWindow ───────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    """Primary application window with sidebar navigation.

    Manages four tabs (History, Usage, Settings, and a placeholder for
    future tabs).  The window hides to the system tray on close rather
    than quitting.
    """

    def __init__(
        self,
        app_controller: AppController,
        config: Any | None = None,
        config_store: Any | None = None,
    ) -> None:
        """Initialise the main window.

        Args:
            app_controller: The application controller for data access
                and signal subscriptions.
            config: Optional ``AppConfig`` instance (read from
                ``app_controller.config`` if omitted).
            config_store: Optional ``ConfigStore`` instance for settings
                persistence.
        """
        super().__init__()
        self._controller = app_controller
        self._config = config or app_controller.config
        self._config_store = config_store

        # ── window properties ────────────────────────────────────────────
        self.setWindowTitle("Type and Talk (TNT)")
        self.setWindowIcon(_make_window_icon())
        self.resize(1100, 720)
        self.setMinimumSize(800, 500)
        self.setStyleSheet(_WINDOW_STYLE)

        # ── central widget ───────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── sidebar ──────────────────────────────────────────────────────
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setStyleSheet(_SIDEBAR_STYLE)
        self._sidebar.setFixedWidth(180)

        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(2)

        # App title in sidebar.
        title_label = QLabel("TNT")
        title_label.setStyleSheet(
            "color: #FFFFFF; font-size: 18px; font-weight: bold; "
            "padding: 4px 12px 12px 12px;"
        )
        sidebar_layout.addWidget(title_label)

        # Navigation label.
        nav_label = QLabel("Navigation")
        nav_label.setStyleSheet(_SIDEBAR_TITLE_STYLE)
        sidebar_layout.addWidget(nav_label)

        # Tab buttons.
        self._nav_buttons: list[_SidebarButton] = []
        self._nav_button_group: list[_SidebarButton] = []

        self._btn_history = self._add_nav_button("📋  History", "history")
        self._btn_usage = self._add_nav_button("📊  Usage", "usage")
        self._btn_settings = self._add_nav_button("⚙  Settings", "settings")

        sidebar_layout.addStretch(1)

        main_layout.addWidget(self._sidebar)

        # ── main content (stacked widget) ────────────────────────────────
        self._content = QStackedWidget()
        self._content.setObjectName("mainContent")
        self._content.setStyleSheet(_MAIN_STYLE)
        main_layout.addWidget(self._content, 1)

        # ── build tabs ───────────────────────────────────────────────────
        self._tabs: dict[str, QWidget] = {}
        self._build_tabs()

        # ── default to history tab ───────────────────────────────────────
        self.navigate_to("history")

        # ── subscribe to task_finished for auto-refresh ──────────────────
        try:
            self._controller.task_finished.connect(self._on_task_finished)
        except AttributeError:
            pass

        logger.debug("MainWindow initialised.")

    # ── tab building ─────────────────────────────────────────────────────────

    def _add_nav_button(self, text: str, tab_name: str) -> _SidebarButton:
        """Create a sidebar button and wire its click handler.

        Args:
            text: Display text for the button.
            tab_name: Identifier for the target tab.

        Returns:
            The newly created button.
        """
        btn = _SidebarButton(text, tab_name)
        btn.clicked.connect(lambda checked=False, t=tab_name: self.navigate_to(t))
        self._nav_buttons.append(btn)
        sidebar_layout = self._sidebar.layout()
        # Insert before the stretch (last item).
        if sidebar_layout is not None:
            sidebar_layout.insertWidget(
                sidebar_layout.count() - 1, btn
            )
        return btn

    def _build_tabs(self) -> None:
        """Create all tab widgets and add them to the stacked widget."""
        # Lazy imports to avoid circular dependencies at module level.
        from agent_uia.ui.tabs.history_tab import HistoryTab
        from agent_uia.ui.tabs.settings_tab import SettingsTab
        from agent_uia.ui.tabs.usage_tab import UsageTab

        # History tab.
        self._history_tab = HistoryTab(self._controller)
        self._tabs["history"] = self._history_tab
        self._content.addWidget(self._history_tab)

        # Usage tab.
        self._usage_tab = UsageTab(self._controller)
        self._tabs["usage"] = self._usage_tab
        self._content.addWidget(self._usage_tab)

        # Settings tab.
        self._settings_tab = SettingsTab(
            self._controller, self._config_store
        )
        self._tabs["settings"] = self._settings_tab
        self._content.addWidget(self._settings_tab)

    # ── public API ───────────────────────────────────────────────────────────

    def navigate_to(self, tab_name: str) -> None:
        """Switch to the specified tab.

        Args:
            tab_name: One of ``"history"``, ``"usage"``, ``"settings"``.
        """
        widget = self._tabs.get(tab_name)
        if widget is None:
            logger.warning("Unknown tab: %s", tab_name)
            return

        self._content.setCurrentWidget(widget)

        # Update sidebar button states.
        for btn in self._nav_buttons:
            btn.setChecked(btn.tab_name == tab_name)

        logger.debug("Navigated to tab: %s", tab_name)

    def reload_history(self) -> None:
        """Trigger a reload of the history tab data."""
        if hasattr(self._history_tab, "reload"):
            self._history_tab.reload()

    def reload_usage(self) -> None:
        """Trigger a reload of the usage tab data."""
        if hasattr(self._usage_tab, "reload"):
            self._usage_tab.reload()

    # ── event overrides ─────────────────────────────────────────────────

    def closeEvent(self, event):  # noqa: N802 — Qt override
        """Override close: hide to tray instead of quitting.

        The application continues running in the system tray.  The user
        must use the tray menu's "Quit" action to fully exit.
        """
        logger.debug("MainWindow closeEvent — hiding to tray")
        self.hide()
        event.ignore()

    def showEvent(self, event):  # noqa: N802 — Qt override
        """Override show: reload data when the window becomes visible."""
        super().showEvent(event)
        self.reload_history()
        self.reload_usage()

    # ── internal slots ─────────────────────────────────────────────────

    def _on_task_finished(self, status: str) -> None:
        """Auto-refresh history and usage when a task completes.

        Args:
            status: Outcome string (``"success"``, ``"failed"``, etc.).
        """
        logger.debug("Task finished (%s) — auto-refreshing tabs", status)
        # Use a short timer to allow the history file write to complete.
        QTimer.singleShot(1000, self.reload_history)
        QTimer.singleShot(500, self.reload_usage)
