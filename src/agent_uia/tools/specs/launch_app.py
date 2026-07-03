# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: launch_app."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class LaunchAppInput(_ToolSpec):
    """Launch an application by executable name."""

    executable: str = Field(..., description="Executable name or full path, e.g. 'notepad.exe'.")
    args: list[str] = Field(default_factory=list, description="Optional command-line arguments.")

    @classmethod
    def tool_name(cls) -> str:
        return "launch_app"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Launch a Windows application by executable name or path. "
            "Returns the PID and executable name of the launched process."
        )
