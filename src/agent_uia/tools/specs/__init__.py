# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Import all tool specs so they are available for registry collection."""

from __future__ import annotations

from agent_uia.tools.specs.click import ClickInput
from agent_uia.tools.specs.clipboard_read import ClipboardReadInput
from agent_uia.tools.specs.clipboard_write import ClipboardWriteInput
from agent_uia.tools.specs.close_window import CloseWindowInput
from agent_uia.tools.specs.file_list import FileListInput
from agent_uia.tools.specs.file_mkdir import FileMkdirInput
from agent_uia.tools.specs.file_move import FileMoveInput
from agent_uia.tools.specs.find_window import FindWindowInput
from agent_uia.tools.specs.get_control_tree import GetControlTreeInput
from agent_uia.tools.specs.invoke import InvokeInput
from agent_uia.tools.specs.launch_app import LaunchAppInput
from agent_uia.tools.specs.list_windows import ListWindowsInput
from agent_uia.tools.specs.llm_complete import LlmCompleteInput
from agent_uia.tools.specs.press_key import PressKeyInput
from agent_uia.tools.specs.read_screen_state import ReadScreenStateInput
from agent_uia.tools.specs.request_user_confirmation import RequestUserConfirmationInput
from agent_uia.tools.specs.set_value import SetValueInput
from agent_uia.tools.specs.system_info import SystemInfoInput
from agent_uia.tools.specs.type_text import TypeTextInput
from agent_uia.tools.specs.wait_for_control import WaitForControlInput
from agent_uia.tools.specs.wait_for_window import WaitForWindowInput

__all__ = [
    "LaunchAppInput",
    "FindWindowInput",
    "ListWindowsInput",
    "GetControlTreeInput",
    "ClickInput",
    "ClipboardReadInput",
    "ClipboardWriteInput",
    "CloseWindowInput",
    "FileListInput",
    "FileMkdirInput",
    "FileMoveInput",
    "LlmCompleteInput",
    "SystemInfoInput",
    "TypeTextInput",
    "SetValueInput",
    "InvokeInput",
    "PressKeyInput",
    "WaitForWindowInput",
    "WaitForControlInput",
    "ReadScreenStateInput",
    "RequestUserConfirmationInput",
]
