# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: invoke."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class InvokeInput(_ToolSpec):
    """Invoke a Button/InvokePattern control."""

    control_id: str = Field(..., description="The control ID to invoke.")

    @classmethod
    def tool_name(cls) -> str:
        return "invoke"

    @classmethod
    def tool_description(cls) -> str:
        return "Invoke a Button or InvokePattern control (e.g. click a standard button)."
