# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the dispatcher's confirmation guard."""

from __future__ import annotations

from unittest import mock

import pytest

from agent_uia.tools.dispatcher import ToolDispatcher


@pytest.fixture
def mock_executor():
    """A mock UIAExecutor that records calls."""
    exec_ = mock.MagicMock()
    exec_.list_windows.return_value = []
    return exec_


@pytest.fixture
def mock_safety():
    """A mock safety gate that allows everything."""
    from agent_uia.safety import SafetyConfig

    gate = mock.MagicMock()
    gate.config = SafetyConfig()
    gate.check_app.return_value = mock.MagicMock(verdict=mock.MagicMock(name="ALLOW"))
    gate.check_action.return_value = mock.MagicMock(verdict=mock.MagicMock(name="ALLOW"), requires_user_confirm=False)
    return gate


# ── sensitive action blocked without confirmation ────────────────────────────


@pytest.mark.asyncio
async def test_sensitive_action_blocked_without_confirmation(mock_executor, mock_safety):
    """A click with action_type='delete' without prior confirmation must be refused."""
    dispatcher = ToolDispatcher(executor=mock_executor, safety_gate=mock_safety)
    dispatcher._tool_messages = []  # Empty — no confirmation.

    # Use a real tool name ('press_key') with an action_type that's in
    # always_confirm_actions ('delete'). The guard checks arguments.action_type.
    result = await dispatcher.dispatch("press_key", {"key": "Return", "action_type": "delete", "target": "Delete button"})
    assert not result.get("ok", True), "Should be refused"
    assert "REFUSED" in result.get("error", ""), (
        f"Expected REFUSED error, got: {result.get('error')}"
    )


# ── sensitive action allowed with confirmation ───────────────────────────────


@pytest.mark.asyncio
async def test_sensitive_action_allowed_with_confirmation(mock_executor, mock_safety):
    """After a 'yes' confirmation for the same target, the action must be allowed."""
    dispatcher = ToolDispatcher(executor=mock_executor, safety_gate=mock_safety)

    # Seed a prior confirmation for this target.
    dispatcher._tool_messages = [
        {
            "name": "request_user_confirmation",
            "arguments": {"target": "Delete button", "action_type": "delete"},
            "result": {"ok": True, "confirmed": True, "user_response": "yes"},
        }
    ]

    # The action tool is not in always_confirm_actions, so no guard applies.
    result = await dispatcher.dispatch("press_key", {"key": "Return", "target": "Delete button"})
    assert result.get("ok", False), f"press_key should be allowed, got: {result}"


@pytest.mark.asyncio
async def test_sensitive_action_allowed_with_confirmation_for_same_target(mock_executor, mock_safety):
    """After a 'yes' confirmation matching the target, the sensitive action must be allowed."""
    dispatcher = ToolDispatcher(executor=mock_executor, safety_gate=mock_safety)

    # Seed a prior confirmation for 'delete' on this target.
    dispatcher._tool_messages = [
        {
            "name": "request_user_confirmation",
            "arguments": {"target": "Delete button in Outlook", "action_type": "delete"},
            "result": {"ok": True, "confirmed": True, "user_response": "yes"},
        }
    ]

    # Dispatch press_key with action_type='delete' and a matching target.
    result = await dispatcher.dispatch(
        "press_key",
        {"key": "Return", "action_type": "delete", "target": "Delete button in Outlook"},
    )
    assert result.get("ok", False), f"Should pass with confirmation, got: {result}"


# ── non-sensitive action, no confirmation needed ─────────────────────────────


@pytest.mark.asyncio
async def test_non_sensitive_action_no_confirmation_needed(mock_executor, mock_safety):
    """A non-sensitive action (not in always_confirm_actions) must pass without prior confirmation."""
    dispatcher = ToolDispatcher(executor=mock_executor, safety_gate=mock_safety)
    dispatcher._tool_messages = []

    # read_screen_state is not in always_confirm_actions.
    result = await dispatcher.dispatch("read_screen_state", {})
    assert result.get("ok", False), f"read_screen_state should pass, got: {result}"


# ── target mismatch blocks ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_target_mismatch_blocks(mock_executor, mock_safety):
    """Confirmation for 'Submit button' should not allow click on 'Delete button'."""
    dispatcher = ToolDispatcher(executor=mock_executor, safety_gate=mock_safety)

    # Seed confirmation for a different target.
    dispatcher._tool_messages = [
        {
            "name": "request_user_confirmation",
            "arguments": {"target": "Submit button on form", "action_type": "submit"},
            "result": {"ok": True, "confirmed": True, "user_response": "yes"},
        }
    ]

    # Try a delete action (in always_confirm_actions) with mismatched target.
    result = await dispatcher.dispatch(
        "press_key",
        {"key": "Return", "action_type": "delete", "target": "Delete button"},
    )
    assert not result.get("ok", False), "Mismatched target should be refused"
    assert "REFUSED" in result.get("error", "")


# ── empty target never bypasses guard ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_target_never_bypasses_guard(mock_executor, mock_safety):
    """A sensitive action with no target must not be allowed by any prior confirmation."""
    dispatcher = ToolDispatcher(executor=mock_executor, safety_gate=mock_safety)

    # Seed a prior confirmation.
    dispatcher._tool_messages = [
        {
            "name": "request_user_confirmation",
            "arguments": {"target": "Delete button", "action_type": "delete"},
            "result": {"ok": True, "confirmed": True, "user_response": "yes"},
        }
    ]

    # Dispatch a sensitive action without a target/control_id/window_id.
    result = await dispatcher.dispatch("press_key", {"key": "Return", "action_type": "delete"})
    assert not result.get("ok", True), "Empty target should not bypass guard"
    assert "REFUSED" in result.get("error", "")
