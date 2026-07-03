# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Right-side content area for the TNT main window.

Uses a ``QStackedWidget`` to host the six tab views (Home, History, Skills,
Settings, Usage, Performance) and provides a cross-fade animation when
switching between them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QStackedWidget, QWidget

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController
    from agent_uia.ui.tabs.home_tab import HomeTab
    from agent_uia.ui.tabs.history_tab import HistoryTab
    from agent_uia.ui.tabs.skills_tab import SkillsTab
    from agent_uia.ui.tabs.settings_tab import SettingsTab
    from agent_uia.ui.tabs.usage_tab import UsageTab
    from agent_uia.ui.tabs.performance_tab import PerformanceTab

__all__ = [
    "MainContent",
]

_FADE_DURATION_MS: int = 150
"""Duration of the tab-switch fade animation in milliseconds."""

_TAB_NAMES = ("home", "history", "skills", "settings", "usage", "performance")


class MainContent(QStackedWidget):
    """Right-side content pane with a stacked set of tab views.

    Usage::

        content = MainContent(app_controller)
        content.navigate_to("home")   # switch to Home tab with fade
    """

    def __init__(self, app_controller: AppController, parent: QWidget | None = None) -> None:
        """Initialise the content area and instantiate all tab widgets.

        Args:
            app_controller: The application controller, forwarded to each tab.
            parent:         Optional parent widget.
        """
        super().__init__(parent)
        self._controller = app_controller

        # Lazy imports for the tab classes.
        from agent_uia.ui.tabs.home_tab import HomeTab
        from agent_uia.ui.tabs.history_tab import HistoryTab
        from agent_uia.ui.tabs.skills_tab import SkillsTab
        from agent_uia.ui.tabs.settings_tab import SettingsTab
        from agent_uia.ui.tabs.usage_tab import UsageTab
        from agent_uia.ui.tabs.performance_tab import PerformanceTab

        # Build the six tab widgets.
        self._tabs: dict[str, QWidget] = {
            "home": HomeTab(app_controller, self),
            "history": HistoryTab(app_controller, self),
            "skills": SkillsTab(app_controller, self),
            "settings": SettingsTab(app_controller, self),
            "usage": UsageTab(app_controller, self),
            "performance": PerformanceTab(app_controller, self),
        }

        for tab_name in _TAB_NAMES:
            self.addWidget(self._tabs[tab_name])

        # Start at the Home tab.
        self.setCurrentWidget(self._tabs["home"])

        # ── fade animation ──────────────────────────────────────────────────
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.setDuration(_FADE_DURATION_MS)

    # ── public API ─────────────────────────────────────────────────────────────

    def navigate_to(self, tab_name: str) -> None:
        """Switch to a tab with a fade animation.

        Args:
            tab_name: One of ``"home"``, ``"history"``, ``"skills"``,
                ``"settings"``, ``"usage"``, ``"performance"``.

        Raises:
            KeyError: If *tab_name* is not a recognised tab.
        """
        target = self._tabs.get(tab_name)
        if target is None:
            msg = f"Unknown tab: {tab_name!r}. Choices: {', '.join(_TAB_NAMES)}"
            raise KeyError(msg)

        if self.currentWidget() is target:
            return  # already showing

        # Animate opacity: fade out → swap → fade in.
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._on_fade_out_done, Qt.UniqueConnection)
        self._fade.start()

        # Store the target for the callback.
        self._pending_tab = target

    def tab_widget(self, tab_name: str) -> QWidget:
        """Return the widget instance for a given tab name.

        Args:
            tab_name: One of the recognised tab names.

        Returns:
            The corresponding ``QWidget`` subclass.
        """
        return self._tabs[tab_name]

    # ── internal ───────────────────────────────────────────────────────────────

    def _on_fade_out_done(self) -> None:
        """Swap the visible widget and fade back in."""
        target = getattr(self, "_pending_tab", None)
        if target is None:
            self.setWindowOpacity(1.0)
            return

        self.setCurrentWidget(target)

        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.finished.connect(self._on_fade_in_done, Qt.UniqueConnection)
        self._fade.start()

    def _on_fade_in_done(self) -> None:
        """Clean up after the fade-in completes."""
        self._pending_tab = None
        self.setWindowOpacity(1.0)
