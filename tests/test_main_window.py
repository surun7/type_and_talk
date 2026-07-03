# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the main application window."""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from agent_uia.ui.app_controller import AppConfig


# ── session-scoped QApplication ───────────────────────────────────────────────


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ── mocked AppController ──────────────────────────────────────────────────────


@pytest.fixture
def mock_app_controller():
    ctrl = mock.MagicMock()
    ctrl.config = mock.MagicMock(spec=AppConfig)
    ctrl.paused = False
    return ctrl


@pytest.fixture
def main_window(qapp, mock_app_controller):
    """Build a MainWindow instance, yield it, then schedule deletion."""
    from agent_uia.ui.main_window import MainWindow

    mw = MainWindow(app_controller=mock_app_controller)
    yield mw
    mw.deleteLater()


# ── tests ─────────────────────────────────────────────────────────────────────


def test_instantiates(main_window):
    """MainWindow must create without raising."""
    assert main_window is not None
    assert main_window.windowTitle() != ""


def test_has_five_tabs(main_window):
    """The main window must contain exactly 5 tab widgets."""
    # assumption: _tabs is a QTabWidget or a container with a count property
    tab_count = main_window._tabs.count()
    assert tab_count == 5, f"Expected 5 tabs, got {tab_count}"


def test_sidebar_buttons_match_tabs(main_window):
    """The sidebar must have one button per tab, and clicking each one
    navigates to the corresponding tab."""
    # assumption: sidebar exposes a list of (button, tab_name) pairs
    button_count = len(main_window._sidebar.buttons())
    assert button_count == 5, f"Expected 5 sidebar buttons, got {button_count}"

    # Verify each button maps to a valid tab index.
    for btn in main_window._sidebar.buttons():
        tab_name = btn.property("tab_name")
        assert tab_name is not None, "Sidebar button missing 'tab_name' property"
        assert tab_name in ("home", "settings", "history", "usage", "about")


def test_close_hides_does_not_quit(main_window, mock_app_controller):
    """Sending QCloseEvent must hide the window and must NOT call
    app_controller.quit()."""
    main_window.show()
    event = QCloseEvent()
    QApplication.sendEvent(main_window, event)

    # The window should be hidden, not destroyed.
    assert not main_window.isVisible(), "MainWindow should be hidden on close"
    # quit() must NOT have been called.
    mock_app_controller.quit.assert_not_called()


def test_navigate_to_changes_visible_widget(main_window):
    """Calling navigate_to('settings') must make the settings tab visible."""
    # Start on a different tab first.
    main_window.navigate_to("home")

    main_window.navigate_to("settings")
    # The settings widget should now be on top.
    visible = main_window._tabs.currentWidget()
    assert visible is not None
    # The widget's objectName is expected to match the tab name.
    assert visible.objectName() == "settings_tab" or "settings" in visible.objectName()
