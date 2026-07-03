# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: press_key."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class PressKeyInput(_ToolSpec):
    """Press a global key combination."""

    key: str = Field(..., description="Key name or combination, e.g. 'ctrl+a', 'Return', 'Escape'.")

    @classmethod
    def tool_name(cls) -> str:
        return "press_key"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Send a global key press or combination. "
            "Use for keyboard shortcuts like ctrl+a (select all), ctrl+c (copy), "
            "ctrl+v (paste), Return, Escape, Alt+F4, etc."
        )
