# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: wait_for_control."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class WaitForControlInput(_ToolSpec):
    """Wait for a control to appear inside a window."""

    window_id: str = Field(..., description="The parent window ID.")
    name_contains: str | None = Field(None, description="Substring to match in the control name.")
    automation_id: str | None = Field(None, description="Exact AutomationId to match.")
    control_type: str | None = Field(None, description="Control type name, e.g. 'Edit', 'Button'.")
    timeout_s: float = Field(10.0, description="Maximum wait time in seconds.")

    @classmethod
    def tool_name(cls) -> str:
        return "wait_for_control"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Wait for a control matching the criteria to appear inside a window. "
            "Polls every 500ms until found or timeout."
        )
