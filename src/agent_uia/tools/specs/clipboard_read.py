# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: clipboard_read."""

from __future__ import annotations

from agent_uia.tools.base import _ToolSpec


class ClipboardReadInput(_ToolSpec):
    """Read text from the system clipboard."""

    @classmethod
    def tool_name(cls) -> str:
        return "clipboard_read"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Read the current text contents of the system clipboard. "
            "Returns an empty string if the clipboard is empty or contains "
            "non-text data."
        )
