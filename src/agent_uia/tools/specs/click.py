# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: click."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class ClickInput(_ToolSpec):
    """Click a UIA control."""

    control_id: str = Field(..., description="The control ID from get_control_tree or wait_for_control.")  # noqa: E501  # noqa: E501
    button: str = Field("left", description="Mouse button: 'left', 'right', or 'middle'.")
    double: bool = Field(False, description="If true, perform a double-click.")

    @classmethod
    def tool_name(cls) -> str:
        return "click"

    @classmethod
    def tool_description(cls) -> str:
        return "Click a UI control. Supports left/right/middle buttons and single/double clicks."
