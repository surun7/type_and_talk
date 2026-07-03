# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool / function-calling specifications — the contract between LLM and executor.

This package replaces the former monolithic ``tools.py`` with a modular layout.
All public API symbols are re-exported here so existing import paths continue
to work without changes.
"""

from __future__ import annotations

# Re-export shared types from base.
from agent_uia.tools.base import (
    _SAFE_EXE_RE,
    _SHELL_INJECTION_RE,
    _UNSAFE_CONTROL_RE,
    ALLOWED_KEYS,
    ActionResult,
    ControlRef,
    ScreenStateSummary,
    WindowRef,
    _control_ref_to_dict,
    _rect_to_bbox,
    _ToolSpec,
    _validate_launch_args,
    _window_ref_to_dict,
)

# Re-export the dispatcher.
from agent_uia.tools.dispatcher import ToolDispatcher

# Re-export the registry.
from agent_uia.tools.registry import _TOOL_CLASS_BY_NAME, ALL_TOOL_SPECS, build_dispatcher

# Re-export all spec classes (so ``from agent_uia.tools import ClickInput`` works).
from agent_uia.tools.specs import (
    ClickInput,
    CloseWindowInput,
    FindWindowInput,
    GetControlTreeInput,
    InvokeInput,
    LaunchAppInput,
    ListWindowsInput,
    PressKeyInput,
    ReadScreenStateInput,
    RequestUserConfirmationInput,
    SetValueInput,
    TypeTextInput,
    WaitForControlInput,
    WaitForWindowInput,
)

__all__ = [
    # Shared types
    "WindowRef",
    "ControlRef",
    "ActionResult",
    "ScreenStateSummary",
    # Dispatcher
    "ToolDispatcher",
    "ALL_TOOL_SPECS",
    "build_dispatcher",
    # Whitelist
    "ALLOWED_KEYS",
    # Base class
    "_ToolSpec",
    # Spec classes
    "LaunchAppInput",
    "FindWindowInput",
    "ListWindowsInput",
    "GetControlTreeInput",
    "ClickInput",
    "TypeTextInput",
    "SetValueInput",
    "InvokeInput",
    "PressKeyInput",
    "WaitForWindowInput",
    "WaitForControlInput",
    "CloseWindowInput",
    "ReadScreenStateInput",
    "RequestUserConfirmationInput",
    # Internal helpers (used by tests)
    "_validate_launch_args",
    "_window_ref_to_dict",
    "_control_ref_to_dict",
    "_rect_to_bbox",
    "_UNSAFE_CONTROL_RE",
    "_SHELL_INJECTION_RE",
    "_SAFE_EXE_RE",
    "_TOOL_CLASS_BY_NAME",
]
