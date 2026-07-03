# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the sidebar widget — navigation buttons, pause toggle, and quit."""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def mock_app_controller():
    ctrl = mock.MagicMock()
    ctrl.paused = False
    return ctrl


@pytest.fixture
def sidebar(qapp, mock_app_controller):
    """Build a Sidebar instance, yield it, then clean up."""
    from agent_uia.ui.sidebar import Sidebar

    sb = Sidebar(app_controller=mock_app_controller)
    yield sb
    sb.deleteLater()


class TestSidebarNavigation:
    """Click each tab button and verify the controller receives the correct
    navigate_to call."""

    TAB_NAMES = ("home", "settings", "history", "usage", "about")

    @pytest.mark.parametrize("tab_name", TAB_NAMES)
    def test_click_tab_button_calls_navigate_to(
        self, sidebar, mock_app_controller, tab_name
    ):
        """Clicking a sidebar tab button must call
        app_controller.navigate_to(tab_name)."""
        btn = sidebar.button_for(tab_name)
        assert btn is not None, f"No sidebar button found for tab {tab_name!r}"

        btn.click()

        mock_app_controller.navigate_to.assert_called_with(tab_name)

    def test_click_pause_toggles_paused(self, sidebar, mock_app_controller):
        """Clicking the Pause button must toggle app_controller.paused."""
        btn = sidebar.button_for("pause")
        assert btn is not None, "No Pause button found in sidebar"

        # First click: pause.
        btn.click()
        assert mock_app_controller.paused is True

        # Second click: unpause.
        btn.click()
        assert mock_app_controller.paused is False

    def test_click_quit_calls_quit(self, sidebar, mock_app_controller):
        """Clicking the Quit button must call app_controller.quit()."""
        btn = sidebar.button_for("quit")
        assert btn is not None, "No Quit button found in sidebar"

        btn.click()
        mock_app_controller.quit.assert_called_once()
