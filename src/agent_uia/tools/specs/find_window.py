# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: find_window."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class FindWindowInput(_ToolSpec):
    """Find a top-level window matching criteria."""

    title_contains: str | None = Field(None, description="Substring to match in the window title.")
    class_name: str | None = Field(None, description="Exact window class name.")
    exe_name: str | None = Field(None, description="Executable basename to match.")
    timeout_s: float = Field(5.0, description="How long to poll in seconds.")

    @classmethod
    def tool_name(cls) -> str:
        return "find_window"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Find a top-level desktop window matching the given criteria. "
            "Returns a WindowRef if found, or null if not found within the timeout."
        )
