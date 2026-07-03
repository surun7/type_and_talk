# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: type_text."""

from __future__ import annotations

from pydantic import Field, field_validator

from agent_uia.tools.base import _UNSAFE_CONTROL_RE, _ToolSpec


class TypeTextInput(_ToolSpec):
    """Type text into a control via keyboard simulation."""

    control_id: str = Field(..., description="The control ID to type into.")
    text: str = Field(..., description="The text to type. Newlines (\\n) and tabs (\\t) are preserved.")  # noqa: E501  # noqa: E501

    @field_validator("text")
    @classmethod
    def _strip_unsafe_control_chars(cls, value: str) -> str:
        """Remove control characters that could abuse SendKeys."""
        return _UNSAFE_CONTROL_RE.sub("", value)

    @classmethod
    def tool_name(cls) -> str:
        return "type_text"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Type text into a control by simulating keystrokes. "
            "Prefer set_value for Edit controls — it is faster and IME-safe."
        )
