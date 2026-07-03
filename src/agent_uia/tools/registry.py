# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool registry — collects all spec classes and exposes aggregate lists.

Importing this module triggers loading of ``tools.specs`` so all 21 tool
specs are available for inspection.
"""

from __future__ import annotations

from typing import Any

from agent_uia.tools.base import _ToolSpec
from agent_uia.tools.specs import (  # noqa: F401 — trigger import of all specs
    ClickInput,
    ClipboardReadInput,
    ClipboardWriteInput,
    CloseWindowInput,
    FileListInput,
    FileMkdirInput,
    FileMoveInput,
    FindWindowInput,
    GetControlTreeInput,
    InvokeInput,
    LaunchAppInput,
    ListWindowsInput,
    LlmCompleteInput,
    PressKeyInput,
    ReadScreenStateInput,
    RequestUserConfirmationInput,
    SetValueInput,
    SystemInfoInput,
    TypeTextInput,
    WaitForControlInput,
    WaitForWindowInput,
)

__all__ = [
    "ALL_TOOL_SPECS",
    "build_dispatcher",
    "_TOOL_CLASS_BY_NAME",
]

# All tool spec classes in registration order (matching the original).
_TOOL_SPEC_CLASSES: list[type[_ToolSpec]] = [
    LaunchAppInput,
    FindWindowInput,
    ListWindowsInput,
    GetControlTreeInput,
    ClickInput,
    ClipboardReadInput,
    ClipboardWriteInput,
    CloseWindowInput,
    FileListInput,
    FileMkdirInput,
    FileMoveInput,
    LlmCompleteInput,
    SystemInfoInput,
    TypeTextInput,
    SetValueInput,
    InvokeInput,
    PressKeyInput,
    WaitForWindowInput,
    WaitForControlInput,
    ReadScreenStateInput,
    RequestUserConfirmationInput,
]

# Pre-computed OpenAI specs for passing to the LLM.
ALL_TOOL_SPECS: list[dict[str, Any]] = [
    cls.to_openai_spec() for cls in _TOOL_SPEC_CLASSES
]

# Map tool name → spec class.
_TOOL_CLASS_BY_NAME: dict[str, type[_ToolSpec]] = {
    cls.tool_name(): cls for cls in _TOOL_SPEC_CLASSES
}


def build_dispatcher(
    executor: Any,  # UIAExecutor, avoid top-level import
    safety_gate: Any,  # SafetyGate, avoid top-level import
) -> Any:  # ToolDispatcher
    """Factory to construct a ``ToolDispatcher``.

    Args:
        executor: The ``UIAExecutor`` instance.
        safety_gate: The ``SafetyGate`` instance.

    Returns:
        A new ``ToolDispatcher``.
    """
    from agent_uia.tools.dispatcher import ToolDispatcher

    return ToolDispatcher(executor=executor, safety_gate=safety_gate)
