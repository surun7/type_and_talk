# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the home tab — recent activity, quick actions, and quick input."""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from agent_uia.ui.app_controller import AppConfig


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def mock_app_controller():
    ctrl = mock.MagicMock()
    ctrl.config = mock.MagicMock(spec=AppConfig)
    return ctrl


@pytest.fixture
def home_tab(qapp, mock_app_controller):
    """Build a HomeTab with three seed history entries."""
    from agent_uia.ui.home_tab import HomeTab

    ht = HomeTab(app_controller=mock_app_controller)
    yield ht
    ht.deleteLater()


class TestRecentActivity:
    """The "Recent activity" card must display seeded history entries."""

    def test_three_history_entries_shown(self, qapp, mock_app_controller):
        """Seeding 3 history entries must result in 3 items rendered in the
        recent-activity card."""
        from agent_uia.ui.home_tab import HomeTab

        seed = [
            {"task": "Open Notepad", "status": "success", "ts": 1000},
            {"task": "Calculator", "status": "success", "ts": 2000},
            {"task": "Check weather", "status": "failed", "ts": 3000},
        ]

        ht = HomeTab(app_controller=mock_app_controller, history=seed)
        item_count = ht.recent_activity_count()
        assert item_count == 3, f"Expected 3 recent activity items, got {item_count}"
        ht.deleteLater()


class TestQuickActions:
    """Quick-action buttons must delegate to the controller."""

    def test_quick_action_runs_task(self, qapp, mock_app_controller):
        """Clicking a quick-action button (e.g. "Open Calculator") must call
        app_controller.run_task with the correct instruction string."""
        from agent_uia.ui.home_tab import HomeTab

        ht = HomeTab(app_controller=mock_app_controller)

        calc_btn = ht.quick_action_button("Open Calculator")
        assert calc_btn is not None, "Expected a quick-action button labelled 'Open Calculator'"

        calc_btn.click()
        mock_app_controller.run_task.assert_called_once()
        call_args = mock_app_controller.run_task.call_args[0][0]
        assert "calculator" in call_args.lower() or "Calculator" in call_args

        ht.deleteLater()


class TestQuickInput:
    """The quick-input field must submit on Enter."""

    def test_quick_input_enter_submits(self, qapp, mock_app_controller):
        """Pressing Enter in the quick-input line edit must submit the text
        via app_controller.run_task."""
        from agent_uia.ui.home_tab import HomeTab

        ht = HomeTab(app_controller=mock_app_controller)
        input_field = ht.quick_input()

        input_field.setText("launch notepad")
        input_field.returnPressed.emit()

        mock_app_controller.run_task.assert_called_once_with("launch notepad")

        ht.deleteLater()
