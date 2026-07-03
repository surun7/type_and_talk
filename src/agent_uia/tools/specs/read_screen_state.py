# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: read_screen_state."""

from __future__ import annotations

from agent_uia.tools.base import _ToolSpec


class ReadScreenStateInput(_ToolSpec):
    """Read the current screen state — UIA-enumerated windows only."""

    @classmethod
    def tool_name(cls) -> str:
        return "read_screen_state"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Return a summary of all currently open top-level windows. "
            "This is NOT a screenshot — it is UIA-enumerated window metadata only "
            "(title, class, executable). Use this to discover what applications are running."
        )
