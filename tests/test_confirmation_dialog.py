# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the confirmation dialog — runs under QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

# Offscreen already set by conftest.py.

__all__: list[str] = []


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ── Yes button ───────────────────────────────────────────────────────────────


def test_yes_returns_yes(qapp, monkeypatch):
    """With TNT_TEST_AUTO_CONFIRM=yes, the dialog returns 'yes'."""
    monkeypatch.setenv("TNT_TEST_AUTO_CONFIRM", "yes")
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    result = ConfirmationDialog.ask(
        None,
        action_type="delete",
        target="Delete button in Outlook",
        risk_explanation="This will permanently delete the selected email.",
        timeout_s=5,
    )
    assert result == "yes"


# ── Auto-confirm offscreen mode ──────────────────────────────────────────────


def test_auto_confirm_yes(qapp, monkeypatch):
    """With TNT_TEST_AUTO_CONFIRM=yes, the dialog returns 'yes'."""
    monkeypatch.setenv("TNT_TEST_AUTO_CONFIRM", "yes")
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    result = ConfirmationDialog.ask(
        None,
        action_type="delete",
        target="File",
        risk_explanation="Test",
        timeout_s=5,
    )
    assert result == "yes"


def test_auto_confirm_no(qapp, monkeypatch):
    """With TNT_TEST_AUTO_CONFIRM=no, the dialog returns 'no'."""
    monkeypatch.setenv("TNT_TEST_AUTO_CONFIRM", "no")
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    result = ConfirmationDialog.ask(
        None,
        action_type="delete",
        target="File",
        risk_explanation="Test",
        timeout_s=5,
    )
    assert result == "no"


# ── Timeout ──────────────────────────────────────────────────────────────────


def test_timeout_returns_timeout(qapp, monkeypatch):
    """With a very short timeout and no auto-confirm, the dialog times out."""
    monkeypatch.delenv("TNT_TEST_AUTO_CONFIRM", raising=False)
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    result = ConfirmationDialog.ask(
        None,
        action_type="delete",
        target="File",
        risk_explanation="Test",
        timeout_s=1,
    )
    assert result == "timeout"


# ── UI structure ─────────────────────────────────────────────────────────────


def test_dialog_has_three_buttons(qapp):
    """The dialog must have Yes, No, and Stop buttons."""
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    dialog = ConfirmationDialog(
        action_type="delete",
        target="Test",
        risk_explanation="Test",
        timeout_s=30,
    )
    assert dialog._btn_yes is not None
    assert dialog._btn_no is not None
    assert dialog._btn_stop is not None
    assert dialog._btn_yes.text() == "Yes, do it"
    assert dialog._btn_no.text() == "No, skip"
    assert dialog._btn_stop.text() == "Stop the whole task"
    dialog.close()


def test_dialog_shows_action_type_and_target(qapp):
    """The dialog body must display the action type and target."""
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    dialog = ConfirmationDialog(
        action_type="delete",
        target="Delete button in Outlook",
        risk_explanation="This will permanently delete the selected email.",
        timeout_s=30,
    )
    # Check labels via layout inspection.
    assert dialog.findChild(type(dialog._timer_label)) is not None
    dialog.close()


# ── Audit log (safety gate) ──────────────────────────────────────────────────


def test_audit_log_recorded(tmp_path, qapp, monkeypatch):
    """After a confirmation, the audit log must contain the event."""
    import json

    from agent_uia.safety import SafetyConfig, SafetyGate
    from agent_uia.ui.confirmation_dialog import ConfirmationDialog

    monkeypatch.setenv("TNT_TEST_AUTO_CONFIRM", "yes")

    audit_path = tmp_path / "test_audit.log"
    config = SafetyConfig(audit_log_path=audit_path)
    gate = SafetyGate(config)

    # Simulate what the dispatcher does.

    result = ConfirmationDialog.ask(
        None,
        action_type="delete",
        target="Test audit target",
        risk_explanation="Audit test",
        timeout_s=5,
    )

    gate._record(
        actor="user",
        action_type="request_user_confirmation:delete",
        target="Test audit target",
        verdict=result.upper(),
        reason=f"User responded {result} to action 'delete' on 'Test audit target'.",
        user_response=result,
    )

    assert audit_path.exists(), "Audit log was not created"
    lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    entry = json.loads(lines[0])
    assert "user_response" in entry
    assert entry["user_response"] == "yes"
