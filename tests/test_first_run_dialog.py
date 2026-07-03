# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the first-launch onboarding dialog.

Runs under QT_QPA_PLATFORM=offscreen (enforced by tests/conftest.py).
"""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from agent_uia.ui.first_run_dialog import FirstRunDialog

# Offscreen already set by conftest.py.

__all__: list[str] = []


# ---------------------------------------------------------------------------
# Session-scoped QApplication fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """Return the singleton QApplication instance."""
    app = QApplication.instance() or QApplication([])
    return app


# ---------------------------------------------------------------------------
# Shown / skipped logic
# ---------------------------------------------------------------------------


class TestRunIfNeeded:
    """Tests for the ``run_if_needed`` static method."""

    def test_dialog_shown_on_first_run(self, qapp: QApplication) -> None:
        """When ``first_run_completed`` is False, the dialog is shown."""
        mock_controller = mock.MagicMock()
        mock_controller.config.first_run_completed = False

        # Verify that ``run_if_needed`` invokes ``exec_()`` on the dialog.
        with mock.patch(
            "agent_uia.ui.first_run_dialog.FirstRunDialog.exec_"
        ) as mock_exec:
            _ = FirstRunDialog.run_if_needed(None, app_controller=mock_controller)

        mock_exec.assert_called_once()

    def test_dialog_skipped_after_completed(self, qapp: QApplication) -> None:
        """When ``first_run_completed`` is True, the dialog is skipped."""
        mock_controller = mock.MagicMock()
        mock_controller.config.first_run_completed = True

        result = FirstRunDialog.run_if_needed(None, app_controller=mock_controller)

        assert result is None

    def test_skipped_when_config_missing_attribute(self, qapp: QApplication) -> None:
        """If config lacks ``first_run_completed``, dialog is shown (safe fallback)."""
        mock_controller = mock.MagicMock()
        del mock_controller.config.first_run_completed

        with mock.patch(
            "agent_uia.ui.first_run_dialog.FirstRunDialog.exec_"
        ) as mock_exec:
            _ = FirstRunDialog.run_if_needed(None, app_controller=mock_controller)

        mock_exec.assert_called_once()

    def test_return_value_on_download(self, qapp: QApplication) -> None:
        """When the user clicks 'Download', run_if_needed returns the expected tuple."""
        mock_controller = mock.MagicMock()
        mock_controller.config.first_run_completed = False

        def _click_download() -> None:
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, FirstRunDialog):
                    QTest.mouseClick(
                        widget._btn_download, Qt.MouseButton.LeftButton
                    )
                    return

        QTimer.singleShot(100, _click_download)

        result = FirstRunDialog.run_if_needed(None, app_controller=mock_controller)

        assert result is not None
        assert result[0] == "download"
        assert result[2] == "https://huggingface.co"

    def test_return_value_on_text_only(self, qapp: QApplication) -> None:
        """When the user clicks 'Use text only', run_if_needed returns 'text_only'."""
        mock_controller = mock.MagicMock()
        mock_controller.config.first_run_completed = False

        def _click_text_only() -> None:
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, FirstRunDialog):
                    QTest.mouseClick(
                        widget._btn_text_only, Qt.MouseButton.LeftButton
                    )
                    return

        QTimer.singleShot(100, _click_text_only)

        result = FirstRunDialog.run_if_needed(None, app_controller=mock_controller)

        assert result is not None
        assert result[0] == "text_only"
        assert result[2] == "https://huggingface.co"


# ---------------------------------------------------------------------------
# Widget structure
# ---------------------------------------------------------------------------


class TestWidgetStructure:
    """Verify the dialog has the expected UI elements."""

    def test_dialog_has_three_buttons(self, qapp: QApplication) -> None:
        """The dialog must have Quit, Use text only, and Download buttons."""
        dialog = FirstRunDialog()

        assert dialog._btn_quit is not None
        assert dialog._btn_text_only is not None
        assert dialog._btn_download is not None

        assert dialog._btn_quit.text() == "Quit"
        assert dialog._btn_text_only.text() == "Use text only"
        assert dialog._btn_download.text() == "Download"

        dialog.close()

    def test_default_model_size_is_base(self, qapp: QApplication) -> None:
        """The default selected size is 'base'."""
        dialog = FirstRunDialog()
        assert dialog._get_selected_size() == "base"
        dialog.close()

    def test_default_mirror_is_huggingface_co(self, qapp: QApplication) -> None:
        """The default mirror URL is https://huggingface.co."""
        dialog = FirstRunDialog()
        assert dialog._mirror == "https://huggingface.co"
        dialog.close()

    def test_window_flags(self, qapp: QApplication) -> None:
        """The dialog is frameless, always-on-top, and modal."""
        dialog = FirstRunDialog()
        flags = dialog.windowFlags()
        assert flags & Qt.FramelessWindowHint
        assert flags & Qt.WindowStaysOnTopHint
        assert flags & Qt.Dialog
        assert dialog.isModal()
        dialog.close()


# ---------------------------------------------------------------------------
# Button behaviour
# ---------------------------------------------------------------------------


class TestButtonBehaviour:
    """Verify clicking buttons sets the expected properties."""

    def test_use_text_only_button(self, qapp: QApplication) -> None:
        """Clicking 'Use text only' sets choice='text_only'."""
        dialog = FirstRunDialog()

        QTest.mouseClick(dialog._btn_text_only, Qt.MouseButton.LeftButton)

        assert dialog.choice == "text_only"
        dialog.close()

    def test_download_button(self, qapp: QApplication) -> None:
        """Clicking 'Download' sets choice='download' with model_size and mirror."""
        dialog = FirstRunDialog()

        # Select "small" before clicking Download.
        dialog._radio_small.setChecked(True)

        QTest.mouseClick(dialog._btn_download, Qt.MouseButton.LeftButton)

        assert dialog.choice == "download"
        assert dialog.model_size == "small"
        assert dialog.mirror == "https://huggingface.co"
        dialog.close()

    def test_quit_button(self, qapp: QApplication) -> None:
        """Clicking 'Quit' sets choice='quit'."""
        dialog = FirstRunDialog()

        QTest.mouseClick(dialog._btn_quit, Qt.MouseButton.LeftButton)

        assert dialog.choice == "quit"
        dialog.close()

    def test_model_size_selection(self, qapp: QApplication) -> None:
        """Selecting different radio buttons changes model_size."""
        dialog = FirstRunDialog()

        assert dialog._get_selected_size() == "base"

        dialog._radio_tiny.setChecked(True)
        assert dialog._get_selected_size() == "tiny"

        dialog._radio_small.setChecked(True)
        assert dialog._get_selected_size() == "small"

        dialog._radio_base.setChecked(True)
        assert dialog._get_selected_size() == "base"

        dialog.close()

    def test_mirror_url_sync(self, qapp: QApplication) -> None:
        """Changing the mirror URL text updates the internal mirror property."""
        dialog = FirstRunDialog()

        dialog._mirror_input.setText("https://hf-mirror.com")
        assert dialog.mirror == "https://hf-mirror.com"

        dialog.close()
