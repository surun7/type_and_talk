# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool / function-calling specifications — the contract between LLM and executor.

Each tool spec is a Pydantic model with a ``to_openai_spec()`` method that
returns a dict in OpenAI function-calling JSON-schema format.

The ``ToolDispatcher`` class routes tool calls from the planner to the
executor, managing window/control registries and safety gate enforcement.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from agent_uia.executor import (
    UIAExecutor,
    UIAControlNode,
    UIAControlRef,
    UIAWindowInfo,
)
from agent_uia.safety import (
    LoginDetectedError,
    SafetyGate,
    UnsupportedAppError,
    default_gate,
)

__all__ = [
    "WindowRef",
    "ControlRef",
    "ActionResult",
    "ScreenStateSummary",
    "ToolDispatcher",
    "ALL_TOOL_SPECS",
    "ALLOWED_KEYS",
]


# ── shared types ─────────────────────────────────────────────────────────────


@dataclass
class WindowRef:
    """Reference to a top-level window, passed between tools.

    Attributes:
        id: Opaque window identifier.
        title: Window title.
        class_name: Window class name.
        exe_name: Executable basename.
        pid: Process id.
    """

    id: str
    title: str
    class_name: str
    exe_name: str
    pid: int

    @classmethod
    def from_window_info(cls, info: UIAWindowInfo, window_id: str) -> WindowRef:
        """Build from a ``UIAWindowInfo`` and an assigned id."""
        return cls(
            id=window_id,
            title=info.title,
            class_name=info.class_name,
            exe_name=info.exe_name,
            pid=info.pid,
        )


@dataclass
class ControlRef:
    """Reference to a UIA control, passed between tools.

    Attributes:
        id: Opaque control token from the executor's handle registry.
        name: Control Name.
        control_type: Control type name (e.g. "Button", "Edit").
        automation_id: Control AutomationId.
        window_id: The id of the parent window.
        bbox: Bounding box ``{x, y, w, h}``.
        is_enabled: Whether the control is enabled.
        is_visible: Whether the control is visible.
    """

    id: str
    name: str
    control_type: str
    automation_id: str
    window_id: str
    bbox: dict[str, int]
    is_enabled: bool
    is_visible: bool


@dataclass
class ActionResult:
    """Result of a tool execution.

    Attributes:
        ok: Whether the action succeeded.
        error: Error message if ``ok`` is ``False``.
        observation: Human-readable note about what happened.
    """

    ok: bool
    error: str | None = None
    observation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON."""
        d: dict[str, Any] = {"ok": self.ok}
        if self.error is not None:
            d["error"] = self.error
        if self.observation is not None:
            d["observation"] = self.observation
        return d


@dataclass
class ScreenStateSummary:
    """UIA-enumerated screen state — NOT a screenshot.

    Attributes:
        windows: List of window summaries.
        truncated: Whether the window list was truncated (hard cap).
    """

    windows: list[WindowRef]
    truncated: bool


# ── key whitelist ────────────────────────────────────────────────────────────

ALLOWED_KEYS: set[str] = {
    # Single keys
    "Return", "Enter", "Escape", "Tab", "Backspace", "Delete",
    "Home", "End", "PageUp", "PageDown",
    "Up", "Down", "Left", "Right",
    "Space", "PrintScreen", "Pause", "Menu", "Apps",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    # Modifier combinations
    "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y",
    "ctrl+f", "ctrl+h", "ctrl+n", "ctrl+o", "ctrl+p", "ctrl+s",
    "ctrl+w", "ctrl+t", "ctrl+Tab", "ctrl+Shift+Tab",
    "Alt+Tab", "Alt+F4", "Alt+Space", "Alt+Enter",
    "Win", "Win+d", "Win+e", "Win+r", "Win+l", "Win+m",
    "Shift+Tab",
}


# ── tool spec models ─────────────────────────────────────────────────────────


class _ToolSpec(BaseModel):
    """Base for tool specifications."""

    @classmethod
    def tool_name(cls) -> str:
        """The tool/function name."""
        raise NotImplementedError

    @classmethod
    def tool_description(cls) -> str:
        """Human-readable description."""
        raise NotImplementedError

    @classmethod
    def to_openai_spec(cls) -> dict[str, Any]:
        """Return an OpenAI function-calling JSON-schema dict."""
        schema = cls.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": cls.tool_name(),
                "description": cls.tool_description(),
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }


# ── 1. launch_app ──────────────────────────────────────────────────────────


_SHELL_INJECTION_RE = re.compile(r"[;&|`><$\\]")

# Whitelist: only these path characters allowed in executable names.
_SAFE_EXE_RE = re.compile(r"^[a-zA-Z0-9_\-\.\\/ :]+$")


class LaunchAppInput(_ToolSpec):
    """Launch an application by executable name.

    Example: ``{"executable": "notepad.exe", "args": []}``
    """

    executable: str = Field(..., description="Executable name or full path, e.g. 'notepad.exe'.")
    args: list[str] = Field(default_factory=list, description="Optional command-line arguments.")

    @classmethod
    def tool_name(cls) -> str:
        return "launch_app"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Launch a Windows application by executable name or path. "
            "Returns the PID and executable name of the launched process."
        )


def _validate_launch_args(args: list[str]) -> None:
    """Raise ``ValueError`` if any arg contains shell-injection vectors."""
    for arg in args:
        if _SHELL_INJECTION_RE.search(arg):
            raise ValueError(
                f"Argument contains forbidden shell characters: {arg!r}"
            )
    # Also check the executable.
    for arg in args:
        if not _SAFE_EXE_RE.match(arg):
            raise ValueError(
                f"Argument contains unsafe characters: {arg!r}"
            )


# ── 2. find_window ──────────────────────────────────────────────────────────


class FindWindowInput(_ToolSpec):
    """Find a top-level window matching criteria.

    Example: ``{"title_contains": "Notepad", "timeout_s": 5}``
    """

    title_contains: str | None = Field(None, description="Substring to match in the window title.")
    class_name: str | None = Field(None, description="Exact window class name.")
    exe_name: str | None = Field(None, description="Executable basename to match.")
    timeout_s: float = Field(5.0, description="How long to poll in seconds.")

    @classmethod
    def tool_name(cls) -> str:
        return "find_window"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Find a top-level desktop window matching the given criteria. "
            "Returns a WindowRef if found, or null if not found within the timeout."
        )


# ── 3. list_windows ─────────────────────────────────────────────────────────


class ListWindowsInput(_ToolSpec):
    """List all open top-level windows.

    Example: ``{"title_contains": null}``
    """

    title_contains: str | None = Field(None, description="Optional substring filter on window title.")

    @classmethod
    def tool_name(cls) -> str:
        return "list_windows"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "List all currently open top-level windows. "
            "Capped at 50 results; if more windows exist, the result will indicate truncation. "
            "Use the optional title_contains filter to narrow results."
        )


# ── 4. get_control_tree ─────────────────────────────────────────────────────


class GetControlTreeInput(_ToolSpec):
    """Get the UIA control tree for a window.

    Example: ``{"window_id": "win-abc123", "max_depth": 6}``
    """

    window_id: str = Field(..., description="The window ID from find_window or list_windows.")
    max_depth: int = Field(6, ge=1, le=10, description="Maximum tree depth (1-10, default 6).")

    @classmethod
    def tool_name(cls) -> str:
        return "get_control_tree"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Get the accessibility control tree for a window. "
            "Returns a nested JSON structure with control names, types, automation IDs, "
            "and bounding boxes. Use this to discover what controls are available before "
            "clicking or typing."
        )


# ── 5. click ────────────────────────────────────────────────────────────────


class ClickInput(_ToolSpec):
    """Click a UIA control.

    Example: ``{"control_id": "uia:5:abcdef", "button": "left", "double": false}``
    """

    control_id: str = Field(..., description="The control ID from get_control_tree or wait_for_control.")
    button: str = Field("left", description="Mouse button: 'left', 'right', or 'middle'.")
    double: bool = Field(False, description="If true, perform a double-click.")

    @classmethod
    def tool_name(cls) -> str:
        return "click"

    @classmethod
    def tool_description(cls) -> str:
        return "Click a UI control. Supports left/right/middle buttons and single/double clicks."


# ── 6. type_text ────────────────────────────────────────────────────────────


# Control characters to strip: everything except \n and \t.
_UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TypeTextInput(_ToolSpec):
    """Type text into a control via keyboard simulation.

    Example: ``{"control_id": "uia:5:abcdef", "text": "Hello world"}``
    """

    control_id: str = Field(..., description="The control ID to type into.")
    text: str = Field(..., description="The text to type. Newlines (\\n) and tabs (\\t) are preserved.")

    @classmethod
    def tool_name(cls) -> str:
        return "type_text"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Type text into a control by simulating keystrokes. "
            "Prefer set_value for Edit controls — it is faster and IME-safe."
        )


# ── 7. set_value ────────────────────────────────────────────────────────────


class SetValueInput(_ToolSpec):
    """Set the value of an Edit control directly.

    Example: ``{"control_id": "uia:5:abcdef", "value": "Hello world"}``
    """

    control_id: str = Field(..., description="The control ID (must support ValuePattern, typically an Edit).")
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


# ── 8. invoke ───────────────────────────────────────────────────────────────


class InvokeInput(_ToolSpec):
    """Invoke a Button/InvokePattern control.

    Example: ``{"control_id": "uia:5:abcdef"}``
    """

    control_id: str = Field(..., description="The control ID to invoke.")

    @classmethod
    def tool_name(cls) -> str:
        return "invoke"

    @classmethod
    def tool_description(cls) -> str:
        return "Invoke a Button or InvokePattern control (e.g. click a standard button)."


# ── 9. press_key ────────────────────────────────────────────────────────────


class PressKeyInput(_ToolSpec):
    """Press a global key combination.

    Example: ``{"key": "ctrl+a"}``
    """

    key: str = Field(..., description="Key name or combination, e.g. 'ctrl+a', 'Return', 'Escape'.")

    @classmethod
    def tool_name(cls) -> str:
        return "press_key"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Send a global key press or combination. "
            "Use for keyboard shortcuts like ctrl+a (select all), ctrl+c (copy), "
            "ctrl+v (paste), Return, Escape, Alt+F4, etc."
        )


# ── 10. wait_for_window ────────────────────────────────────────────────────


class WaitForWindowInput(_ToolSpec):
    """Wait for a window to appear.

    Example: ``{"title_contains": "Notepad", "timeout_s": 10}``
    """

    title_contains: str = Field(..., description="Substring to match in the window title.")
    timeout_s: float = Field(10.0, description="Maximum wait time in seconds.")

    @classmethod
    def tool_name(cls) -> str:
        return "wait_for_window"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Wait for a window whose title contains the given substring to appear. "
            "Polls every 500ms until found or timeout."
        )


# ── 11. wait_for_control ───────────────────────────────────────────────────


class WaitForControlInput(_ToolSpec):
    """Wait for a control to appear inside a window.

    Example: ``{"window_id": "win-abc", "control_type": "Edit", "timeout_s": 10}``
    """

    window_id: str = Field(..., description="The parent window ID.")
    name_contains: str | None = Field(None, description="Substring to match in the control name.")
    automation_id: str | None = Field(None, description="Exact AutomationId to match.")
    control_type: str | None = Field(None, description="Control type name, e.g. 'Edit', 'Button'.")
    timeout_s: float = Field(10.0, description="Maximum wait time in seconds.")

    @classmethod
    def tool_name(cls) -> str:
        return "wait_for_control"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Wait for a control matching the criteria to appear inside a window. "
            "Polls every 500ms until found or timeout."
        )


# ── 12. close_window ────────────────────────────────────────────────────────


class CloseWindowInput(_ToolSpec):
    """Close a top-level window.

    Example: ``{"window_id": "win-abc"}``
    """

    window_id: str = Field(..., description="The window ID to close.")

    @classmethod
    def tool_name(cls) -> str:
        return "close_window"

    @classmethod
    def tool_description(cls) -> str:
        return "Close a top-level window. Sends WM_CLOSE or Alt+F4."


# ── 13. read_screen_state ───────────────────────────────────────────────────


class ReadScreenStateInput(_ToolSpec):
    """Read the current screen state — UIA-enumerated windows only.

    Example: ``{}``
    """

    @classmethod
    def tool_name(cls) -> str:
        return "read_screen_state"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Return a summary of all currently open top-level windows. "
            "This is NOT a screenshot — it is UIA-enumerated window metadata only "
            "(title, class, executable). Use this to discover what applications are running."
        )


# ── 14. request_user_confirmation ──────────────────────────────────────────


class RequestUserConfirmationInput(_ToolSpec):
    """Ask the user to confirm a sensitive action.

    Example: ``{"message": "Delete C:\\temp\\data.txt?"}``
    """

    message: str = Field(..., description="The confirmation prompt to show the user.")

    @classmethod
    def tool_name(cls) -> str:
        return "request_user_confirmation"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Ask the user for explicit confirmation before performing a sensitive or "
            "destructive action. The tool returns whether the user confirmed or denied."
        )


# ── aggregate ────────────────────────────────────────────────────────────────

# All tool spec classes in registration order.
_TOOL_SPEC_CLASSES: list[type[_ToolSpec]] = [
    LaunchAppInput,
    FindWindowInput,
    ListWindowsInput,
    GetControlTreeInput,
    ClickInput,
    TypeTextInput,
    SetValueInput,
    InvokeInput,
    PressKeyInput,
    WaitForWindowInput,
    WaitForControlInput,
    CloseWindowInput,
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


# ── tool dispatcher ──────────────────────────────────────────────────────────


class ToolDispatcher:
    """Routes tool calls from the planner to the UIA executor.

    Maintains window and control registries that map opaque IDs to live
    executor objects. Every dispatch passes through the safety gate.

    Args:
        executor: The ``UIAExecutor`` instance.
        safety_gate: The ``SafetyGate`` instance.
    """

    def __init__(
        self,
        executor: UIAExecutor,
        safety_gate: SafetyGate | None = None,
    ) -> None:
        self._executor = executor
        self._safety = safety_gate or default_gate()
        # Window registry: id → UIAWindowInfo
        self._windows: dict[str, UIAWindowInfo] = {}

    # -- validation ------------------------------------------------------------

    def validate_tool_name(self, name: str) -> bool:
        """Check whether *name* is a registered tool."""
        return name in _TOOL_CLASS_BY_NAME

    def known_tools(self) -> set[str]:
        """Return the set of known tool names."""
        return set(_TOOL_CLASS_BY_NAME.keys())

    # -- dispatch --------------------------------------------------------------

    def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call and return a serializable result dict.

        Args:
            tool_name: The tool/function name.
            arguments: The JSON-decoded arguments dict.

        Returns:
            A dict with at minimum ``ok`` (bool) and ``error`` (str|None).
            Additional keys vary by tool.
        """
        if not self.validate_tool_name(tool_name):
            return {"ok": False, "error": f"Unknown tool: {tool_name!r}"}

        try:
            return self._dispatch_inner(tool_name, arguments)
        except UnsupportedAppError as exc:
            return {"ok": False, "error": f"BLOCKED: {exc}"}
        except LoginDetectedError as exc:
            return {"ok": False, "error": f"BLOCKED: {exc}"}
        except TimeoutError as exc:
            return {"ok": False, "error": f"Timed out: {exc}"}
        except Exception as exc:
            logger.exception(f"Tool dispatch error: {tool_name}")
            return {"ok": False, "error": f"Tool error: {exc}"}

    def _dispatch_inner(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Inner dispatch — exceptions are caught by ``dispatch()``."""
        if tool_name == "launch_app":
            return self._launch_app(**arguments)
        elif tool_name == "find_window":
            return self._find_window(**arguments)
        elif tool_name == "list_windows":
            return self._list_windows(**arguments)
        elif tool_name == "get_control_tree":
            return self._get_control_tree(**arguments)
        elif tool_name == "click":
            return self._click(**arguments)
        elif tool_name == "type_text":
            return self._type_text(**arguments)
        elif tool_name == "set_value":
            return self._set_value(**arguments)
        elif tool_name == "invoke":
            return self._invoke(**arguments)
        elif tool_name == "press_key":
            return self._press_key(**arguments)
        elif tool_name == "wait_for_window":
            return self._wait_for_window(**arguments)
        elif tool_name == "wait_for_control":
            return self._wait_for_control(**arguments)
        elif tool_name == "close_window":
            return self._close_window(**arguments)
        elif tool_name == "read_screen_state":
            return self._read_screen_state(**arguments)
        elif tool_name == "request_user_confirmation":
            return self._request_user_confirmation(**arguments)
        return {"ok": False, "error": f"Unhandled tool: {tool_name!r}"}

    # -- tool implementations --------------------------------------------------

    def _launch_app(
        self,
        executable: str,
        args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Launch a process. Validates against shell injection."""
        args = args or []
        _validate_launch_args([executable] + args)

        # Extract basename for safety check.
        import os
        exe_name = os.path.basename(executable)

        # Safety: check app.
        from agent_uia.safety import assert_app_allowed
        assert_app_allowed(exe_name=exe_name, gate=self._safety)

        cmd = [executable] + args
        proc = subprocess.Popen(cmd)
        return {
            "ok": True,
            "pid": proc.pid,
            "exe_name": exe_name,
            "observation": f"Launched {executable!r} with PID {proc.pid}.",
        }

    def _find_window(
        self,
        title_contains: str | None = None,
        class_name: str | None = None,
        exe_name: str | None = None,
        timeout_s: float = 5.0,
    ) -> dict[str, Any]:
        """Find a window and register it."""
        win = self._executor.find_window(
            title_contains=title_contains,
            class_name=class_name,
            exe_name=exe_name,
            timeout=timeout_s,
        )
        if win is None:
            return {"ok": True, "window": None, "observation": "No matching window found."}

        wid = self._register_window(win)
        ref = WindowRef.from_window_info(win, wid)
        return {
            "ok": True,
            "window": _window_ref_to_dict(ref),
            "observation": f"Found window: {win.title!r} (class={win.class_name!r}).",
        }

    def _list_windows(
        self,
        title_contains: str | None = None,
    ) -> dict[str, Any]:
        """List windows, cap at 50."""
        windows = self._executor.list_windows(title_contains=title_contains)
        truncated = len(windows) > 50
        if truncated:
            windows = windows[:50]

        refs: list[dict[str, Any]] = []
        for w in windows:
            wid = self._register_window(w)
            ref = WindowRef.from_window_info(w, wid)
            refs.append(_window_ref_to_dict(ref))

        result: dict[str, Any] = {
            "ok": True,
            "windows": refs,
            "count": len(refs),
        }
        if truncated:
            result["truncated"] = True
            result["observation"] = (
                f"Found {len(refs)}+ windows (truncated at 50). Narrow your filter."
            )
        else:
            result["observation"] = f"Found {len(refs)} windows."
        return result

    def _get_control_tree(
        self,
        window_id: str,
        max_depth: int = 6,
    ) -> dict[str, Any]:
        """Get the control tree for a registered window."""
        win = self._get_window(window_id)
        if win is None:
            return {"ok": False, "error": f"Window not found: {window_id!r}"}

        tree: UIAControlNode = self._executor.get_control_tree(
            win, max_depth=max_depth
        )
        return {
            "ok": True,
            "tree": tree.to_compact_dict(),
            "observation": (
                f"Control tree retrieved (depth={max_depth}). "
                f"Use control IDs for click/type/set_value/invoke."
            ),
        }

    def _click(
        self,
        control_id: str,
        button: str = "left",
        double: bool = False,
    ) -> dict[str, Any]:
        """Click a control by opaque id."""
        ctrl = self._get_control(control_id)
        if ctrl is None:
            return {"ok": False, "error": f"Control not found: {control_id!r}"}

        if button not in ("left", "right", "middle"):
            return {"ok": False, "error": f"Invalid button: {button!r}"}

        import typing
        b = typing.cast(typing.Literal["left", "right", "middle"], button)
        self._executor.click(ctrl, button=b, double=double)
        return {
            "ok": True,
            "observation": f"Clicked {ctrl.name!r} ({ctrl.control_type!r}).",
        }

    def _type_text(
        self,
        control_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Type text, stripping dangerous control characters."""
        ctrl = self._get_control(control_id)
        if ctrl is None:
            return {"ok": False, "error": f"Control not found: {control_id!r}"}

        # Strip dangerous control characters (keep \n, \t).
        safe_text = _UNSAFE_CONTROL_RE.sub("", text)
        if safe_text != text:
            logger.debug("Stripped unsafe control characters from type_text input")

        self._executor.type_text(ctrl, safe_text)
        return {
            "ok": True,
            "observation": f"Typed {len(safe_text)} characters into {ctrl.name!r}.",
        }

    def _set_value(
        self,
        control_id: str,
        value: str,
    ) -> dict[str, Any]:
        """Set value, truncating at 50k chars."""
        ctrl = self._get_control(control_id)
        if ctrl is None:
            return {"ok": False, "error": f"Control not found: {control_id!r}"}

        truncated = False
        if len(value) > 50_000:
            value = value[:50_000]
            truncated = True

        self._executor.set_value(ctrl, value)
        obs = f"Set value ({len(value)} characters) into {ctrl.name!r}."
        if truncated:
            obs += " Value was truncated to 50,000 characters."
        return {"ok": True, "observation": obs}

    def _invoke(self, control_id: str) -> dict[str, Any]:
        """Invoke a control."""
        ctrl = self._get_control(control_id)
        if ctrl is None:
            return {"ok": False, "error": f"Control not found: {control_id!r}"}

        self._executor.invoke(ctrl)
        return {
            "ok": True,
            "observation": f"Invoked {ctrl.name!r} ({ctrl.control_type!r}).",
        }

    def _press_key(self, key: str) -> dict[str, Any]:
        """Press a key, validating against the whitelist."""
        if key not in ALLOWED_KEYS:
            return {
                "ok": False,
                "error": (
                    f"Key {key!r} is not in the allowed key whitelist. "
                    f"Allowed keys include: Return, Escape, Tab, ctrl+a, ctrl+c, "
                    f"ctrl+v, Alt+F4, and others."
                ),
            }

        self._executor.press_key(key)
        return {"ok": True, "observation": f"Pressed key: {key}."}

    def _wait_for_window(
        self,
        title_contains: str,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        """Wait for a window to appear."""
        win = self._executor.wait_for_window(
            title_contains=title_contains,
            timeout=timeout_s,
        )
        wid = self._register_window(win)
        ref = WindowRef.from_window_info(win, wid)
        return {
            "ok": True,
            "window": _window_ref_to_dict(ref),
            "observation": f"Window appeared: {win.title!r}.",
        }

    def _wait_for_control(
        self,
        window_id: str,
        name_contains: str | None = None,
        automation_id: str | None = None,
        control_type: str | None = None,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        """Wait for a control to appear in a window."""
        win = self._get_window(window_id)
        if win is None:
            return {"ok": False, "error": f"Window not found: {window_id!r}"}

        ctrl = self._executor.wait_for_control(
            win,
            name_contains=name_contains,
            automation_id=automation_id,
            control_type=control_type,
            timeout=timeout_s,
        )
        ref = ControlRef(
            id=ctrl._token,  # noqa: SLF001
            name=ctrl.name,
            control_type=ctrl.control_type,
            automation_id=ctrl.automation_id,
            window_id=window_id,
            bbox=_rect_to_bbox(ctrl.rect),
            is_enabled=ctrl.is_enabled,
            is_visible=ctrl.is_visible,
        )
        return {
            "ok": True,
            "control": _control_ref_to_dict(ref),
            "observation": f"Control found: {ctrl.name!r} ({ctrl.control_type!r}).",
        }

    def _close_window(self, window_id: str) -> dict[str, Any]:
        """Close a window."""
        win = self._get_window(window_id)
        if win is None:
            return {"ok": False, "error": f"Window not found: {window_id!r}"}

        self._executor.close_window(win)
        self._windows.pop(window_id, None)
        return {
            "ok": True,
            "observation": f"Closed window: {win.title!r}.",
        }

    def _read_screen_state(self) -> dict[str, Any]:
        """Return UIA-enumerated window list."""
        windows = self._executor.list_windows()
        refs: list[dict[str, Any]] = []
        for w in windows:
            wid = self._register_window(w)
            ref = WindowRef.from_window_info(w, wid)
            refs.append(_window_ref_to_dict(ref))

        return {
            "ok": True,
            "windows": refs,
            "count": len(refs),
            "observation": f"Screen has {len(refs)} open top-level windows.",
        }

    def _request_user_confirmation(self, message: str) -> dict[str, Any]:
        """Ask user for confirmation (placeholder — real impl in Prompt 3).

        For now, logs the request and returns ``confirmed: false`` since
        there is no interactive input layer yet.
        """
        logger.warning(f"User confirmation requested: {message!r}")
        # NOTE: In Prompt 3, this will use the input layer to show a dialog.
        return {
            "ok": True,
            "confirmed": False,
            "observation": (
                "Confirmation requested but interactive mode not available. "
                "Use the CLI --confirm flag or interactive REPL (coming in next prompt)."
            ),
        }

    # -- registry helpers ------------------------------------------------------

    def _register_window(self, win: UIAWindowInfo) -> str:
        """Register a window and return its id."""
        # Check if already registered (by handle).
        for wid, existing in self._windows.items():
            if existing.handle == win.handle:
                return wid
        wid = f"win-{uuid.uuid4().hex[:8]}"
        self._windows[wid] = win
        return wid

    def _get_window(self, window_id: str) -> UIAWindowInfo | None:
        """Look up a registered window by id."""
        return self._windows.get(window_id)

    def _get_control(self, control_id: str) -> UIAControlRef | None:
        """Resolve a control by its opaque token.

        The token is stored in the executor's ``_UIAHandleRegistry``.
        """
        try:
            registry = self._executor._registry  # noqa: SLF001
            return UIAControlRef(control_id, registry)
        except Exception:
            return None


# ── serialization helpers ────────────────────────────────────────────────────


def _window_ref_to_dict(ref: WindowRef) -> dict[str, Any]:
    """Serialize a ``WindowRef`` to a plain dict."""
    return {
        "id": ref.id,
        "title": ref.title,
        "class_name": ref.class_name,
        "exe_name": ref.exe_name,
        "pid": ref.pid,
    }


def _control_ref_to_dict(ref: ControlRef) -> dict[str, Any]:
    """Serialize a ``ControlRef`` to a plain dict."""
    return {
        "id": ref.id,
        "name": ref.name,
        "control_type": ref.control_type,
        "automation_id": ref.automation_id,
        "window_id": ref.window_id,
        "bbox": ref.bbox,
        "is_enabled": ref.is_enabled,
        "is_visible": ref.is_visible,
    }


def _rect_to_bbox(rect: tuple[int, int, int, int]) -> dict[str, int]:
    """Convert ``(x, y, w, h)`` to ``{x, y, w, h}``."""
    return {"x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3]}
