# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: system_info."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agent_uia.tools.base import _ToolSpec

_Component = Literal["cpu", "memory", "disk", "uptime"]


class SystemInfoInput(_ToolSpec):
    """Query system resource information."""

    components: list[_Component] = Field(
        default_factory=lambda: ["cpu", "memory", "disk", "uptime"],
        description=(
            "Which system components to query. "
            "Defaults to all: cpu, memory, disk, uptime."
        ),
    )

    @classmethod
    def tool_name(cls) -> str:
        return "system_info"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Query system resource information including CPU usage, "
            "memory usage, disk usage, and system uptime."
        )
