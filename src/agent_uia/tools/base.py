# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Base types, spec base class, and shared helpers for the tools package."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

__all__ = [
    "WindowRef",
    "ControlRef",
    "ActionResult",
    "ScreenStateSummary",
    "ALLOWED_KEYS",
    "_ToolSpec",
    "_validate_launch_args",
    "_window_ref_to_dict",
    "_control_ref_to_dict",
    "_rect_to_bbox",
    "_UNSAFE_CONTROL_RE",
    "_SHELL_INJECTION_RE",
    "_SAFE_EXE_RE",
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
    def from_window_info(cls, info: Any, window_id: str) -> WindowRef:
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

    @classmethod
    def from_control_ref(
        cls,
        ref: Any,
        *,
        control_id: str,
        window_id: str,
    ) -> ControlRef:
        """Build from an executor ``UIAControlRef``."""
        return cls(
            id=control_id,
            name=ref.name,
            control_type=ref.control_type,
            automation_id=ref.automation_id,
            window_id=window_id,
            bbox=_rect_to_bbox(ref.rect),
            is_enabled=ref.is_enabled,
            is_visible=ref.is_visible,
        )


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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "windows": [_window_ref_to_dict(w) for w in self.windows],
            "truncated": self.truncated,
        }


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


# ── regex patterns for input validation ─────────────────────────────────────

# Shell metacharacters that could be used for command injection if the arg
# list were ever joined into a shell string. Backslash is intentionally
# allowed because it is required for Windows paths.
_SHELL_INJECTION_RE = re.compile(r"[;&|`><$\(\)\r\n]")
_SAFE_EXE_RE = re.compile(r"^[a-zA-Z0-9_\-\.\\/ :]+$")
_UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _validate_launch_args(args: list[str]) -> None:
    """Raise ``ValueError`` if any arg contains shell-injection vectors."""
    for arg in args:
        if _SHELL_INJECTION_RE.search(arg):
            raise ValueError(
                f"Argument contains forbidden shell characters: {arg!r}"
            )
    for arg in args:
        if not _SAFE_EXE_RE.match(arg):
            raise ValueError(
                f"Argument contains unsafe characters: {arg!r}"
            )


def _normalize_exe_name(executable: str) -> str:
    """Return the lower-cased basename of *executable*.

    Handles both bare names (``"notepad.exe"``) and full paths
    (``"C:\\Windows\\notepad.exe"``).
    """
    import os

    return os.path.basename(executable).strip().lower()


# ── tool spec base class ────────────────────────────────────────────────────


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


# ── serialization helpers ───────────────────────────────────────────────────


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
