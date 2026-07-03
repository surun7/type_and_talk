# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: wait_for_window."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class WaitForWindowInput(_ToolSpec):
    """Wait for a window to appear."""

    title_contains: str = Field(..., description="Substring to match in the window title.")
    timeout_s: float = Field(10.0, description="Maximum wait time in seconds.")

    @classmethod
    def tool_name(cls) -> str:
        return "wait_for_window"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Wait for a window whose title contains the given substring to appear. "
            "Polls every 500ms until found or timeout."
        )
