# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: list_windows."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class ListWindowsInput(_ToolSpec):
    """List all open top-level windows."""

    title_contains: str | None = Field(None, description="Optional substring filter on window title.")  # noqa: E501  # noqa: E501

    @classmethod
    def tool_name(cls) -> str:
        return "list_windows"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "List all currently open top-level windows. "
            "Capped at 50 results; if more windows exist, the result will indicate truncation. "
            "Use the optional title_contains filter to narrow results."
        )
