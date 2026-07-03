# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: set_value."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class SetValueInput(_ToolSpec):
    """Set the value of an Edit control directly."""

    control_id: str = Field(..., description="The control ID (must support ValuePattern, typically an Edit).")  # noqa: E501  # noqa: E501
    value: str = Field(..., description="The text value to set. Truncated at 50,000 characters.")

    @classmethod
    def tool_name(cls) -> str:
        return "set_value"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Set the value of a text/Edit control directly via the UIA ValuePattern. "
            "This is the preferred method for text input — it is instant and avoids IME issues."
        )
