# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: close_window."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class CloseWindowInput(_ToolSpec):
    """Close a top-level window."""

    window_id: str = Field(..., description="The window ID to close.")

    @classmethod
    def tool_name(cls) -> str:
        return "close_window"

    @classmethod
    def tool_description(cls) -> str:
        return "Close a top-level window. Sends WM_CLOSE or Alt+F4."
