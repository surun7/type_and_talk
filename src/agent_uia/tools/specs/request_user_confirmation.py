# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: request_user_confirmation.

ALWAYS call this BEFORE any destructive/sensitive action. The Planner system
prompt requires this. Skipping this tool for a sensitive action will cause the
ToolDispatcher to refuse the subsequent tool call.
"""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class RequestUserConfirmationInput(_ToolSpec):
    """Ask the user to confirm a sensitive action.

    Must be called *before* any action whose type is in the always-confirm set
    (delete, send, pay, submit, transfer, purchase, close_account, etc.).
    The ToolDispatcher will refuse the sensitive action if this confirmation
    was not obtained first.
    """

    action_type: str = Field(
        ..., description="The type of action being confirmed, e.g. 'delete', 'send', 'pay', 'submit'."  # noqa: E501  # noqa: E501
    )
    target: str = Field(
        ..., description="A human-readable identifier for what will be acted on, e.g. 'Delete button in Outlook', 'Submit button on form'."  # noqa: E501  # noqa: E501
    )
    risk_explanation: str = Field(
        ..., description="A 1-2 sentence explanation of what will happen and why this is sensitive."
    )
    timeout_s: int = Field(
        30, description="How many seconds to wait for user confirmation before auto-refusing (default 30)."  # noqa: E501  # noqa: E501
    )

    @classmethod
    def tool_name(cls) -> str:
        return "request_user_confirmation"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Ask the user for explicit confirmation before performing a sensitive or "
            "destructive action. You MUST call this tool BEFORE any action whose type is "
            "in the always-confirm set (delete, send, pay, submit, transfer, purchase, "
            "close_account, etc.). The ToolDispatcher will refuse the sensitive action if "
            "this confirmation was not obtained first. Provide the action_type, a "
            "human-readable target description, a risk explanation, and an optional timeout."
        )
