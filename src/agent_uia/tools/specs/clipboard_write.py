# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: clipboard_write."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class ClipboardWriteInput(_ToolSpec):
    """Write text to the system clipboard."""

    text: str = Field(
        ...,
        min_length=0,
        max_length=100_000,
        description="Text to write to clipboard.",
    )

    @classmethod
    def tool_name(cls) -> str:
        return "clipboard_write"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Write text to the system clipboard, replacing any previous contents. "
            "Supports up to 100,000 characters."
        )
