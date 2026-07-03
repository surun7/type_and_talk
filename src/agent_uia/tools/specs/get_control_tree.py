# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: get_control_tree."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class GetControlTreeInput(_ToolSpec):
    """Get the UIA control tree for a window."""

    window_id: str = Field(..., description="The window ID from find_window or list_windows.")
    max_depth: int = Field(6, ge=1, le=10, description="Maximum tree depth (1-10, default 6).")

    @classmethod
    def tool_name(cls) -> str:
        return "get_control_tree"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Get the accessibility control tree for a window. "
            "Returns a nested JSON structure with control names, types, automation IDs, "
            "and bounding boxes. Use this to discover what controls are available before "
            "clicking or typing."
        )
