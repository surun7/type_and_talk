# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the floating window widget."""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication


# Ensure QApp exists once per session.
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ── mock AppController ───────────────────────────────────────────────────────


class _MockController:
    """Minimal AppController stub for FloatingWindow tests."""

    def __init__(self) -> None:
        self.hide_called = False
        self.last_status = ""
        self.last_tool_event = ""
        self.last_final_answer = ""

    def hide_floating_window(self) -> None:
        self.hide_called = True

    def show_floating_window(self) -> None:
        pass

    @property
    def config(self):
        return mock.MagicMock(floating_window_hide_policy="never")


@pytest.fixture
def mock_controller():
    return _MockController()


# ── window flags ─────────────────────────────────────────────────────────────


def test_window_flags(qapp, mock_controller):
    """FloatingWindow must have frameless, always-on-top, and tool flags."""
    # Import after QApp exists.
    from agent_uia.ui.floating_window import FloatingWindow

    fw = FloatingWindow(mock_controller)
    flags = fw.windowFlags()
    assert flags & Qt.FramelessWindowHint, "Missing FramelessWindowHint"
    assert flags & Qt.WindowStaysOnTopHint, "Missing WindowStaysOnTopHint"
    assert flags & Qt.Tool, "Missing Tool flag"
    fw.deleteLater()


# ── input placeholder ────────────────────────────────────────────────────────


def test_input_field_placeholder(qapp, mock_controller):
    """The input field must have the correct placeholder text."""
    from agent_uia.ui.floating_window import FloatingWindow

    fw = FloatingWindow(mock_controller)
    placeholder = fw._input.placeholderText()
    assert "Ctrl+Shift+Space" in placeholder
    assert "Enter to send" in placeholder
    fw.deleteLater()


# ── close event behavior ─────────────────────────────────────────────────────


def test_close_event_ignored_and_hides(qapp, mock_controller):
    """QCloseEvent must be ignored and delegate to controller.hide_floating_window."""
    from agent_uia.ui.floating_window import FloatingWindow

    fw = FloatingWindow(mock_controller)
    fw.show()  # Must be visible for closeEvent to fire

    # Create and send a close event.
    event = QCloseEvent()
    QApplication.sendEvent(fw, event)

    assert mock_controller.hide_called, "hide_floating_window was not called"
    assert not event.isAccepted(), "closeEvent should not accept the event"

    fw.deleteLater()


# ── streaming: tool events + final answer ────────────────────────────────────


def test_streaming_final_answer(qapp, mock_controller):
    """Emitting tool_event and final_answer_ready signals must update QTextEdit."""
    from agent_uia.ui.floating_window import FloatingWindow

    fw = FloatingWindow(mock_controller)
    fw.show()

    # Simulate a tool event via the public API.
    fw.append_tool_event("→ launch_app: notepad.exe")
    fw.set_final_answer("Done! Notepad is open.")

    content = fw._response.toPlainText() if fw._response else ""
    assert "→ launch_app" in content, "Tool event not in response area"
    assert "Done!" in content, "Final answer not in response area"
    assert "Notepad" in content, "Expected content missing"

    fw.deleteLater()
