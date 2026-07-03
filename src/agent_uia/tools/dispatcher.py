# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool dispatcher — routes tool calls from the planner to the UIA executor."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import typing
from pathlib import Path
from typing import Any

from loguru import logger

from agent_uia.tools.base import (
    _UNSAFE_CONTROL_RE,
    ALLOWED_KEYS,
    ControlRef,
    WindowRef,
    _control_ref_to_dict,
    _rect_to_bbox,
    _validate_launch_args,
    _window_ref_to_dict,
)
from agent_uia.tools.registry import _TOOL_CLASS_BY_NAME
from agent_uia.paths import get_app_data_dir

__all__ = [
    "ToolDispatcher",
]

_ALLOWED_DIRS: dict[str, Path] = {
    "desktop": Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "pictures": Path.home() / "Pictures",
    "music": Path.home() / "Music",
    "videos": Path.home() / "Videos",
    "agent_uia_config": get_app_data_dir(),
}

_DANGEROUS_EXTENSIONS: set[str] = {
    ".exe", ".bat", ".cmd", ".ps1", ".sh", ".vbs", ".js", ".jar",
    ".scr", ".com", ".msi",
}


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
        executor: Any,
        safety_gate: Any | None = None,
        *,
        app_controller: Any | None = None,
    ) -> None:
        from agent_uia.safety import default_gate

        self._executor = executor
        self._safety = safety_gate or default_gate()
        # Window registry: id → UIAWindowInfo
        from agent_uia.executor import UIAWindowInfo
        self._windows: dict[str, UIAWindowInfo] = {}
        self._app_controller = app_controller
        # In-memory transcript of tool messages for confirmation guard.
        self._tool_messages: list[dict[str, Any]] = []

    # -- validation ------------------------------------------------------------

    def validate_tool_name(self, name: str) -> bool:
        """Check whether *name* is a registered tool."""
        return name in _TOOL_CLASS_BY_NAME

    def known_tools(self) -> set[str]:
        """Return the set of known tool names."""
        return set(_TOOL_CLASS_BY_NAME.keys())

    # -- dispatch --------------------------------------------------------------

    async def dispatch(
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

        from agent_uia.safety import (
            LoginDetectedError,
            UnsupportedAppError,
        )

        # ── Confirmation guard ──────────────────────────────────────────
        # Before dispatching, check if this action type requires prior
        # user confirmation and whether it was obtained.
        # (Skip the check for request_user_confirmation itself — that's
        #  how we OBTAIN confirmation.)
        if tool_name != "request_user_confirmation":
            # Determine the action type to check: either the tool name
            # itself (for hypothetical sensitive-named tools) or an
            # explicit action_type argument (for generic tools like click).
            sensitive_type: str | None = None
            if isinstance(arguments, dict):
                sensitive_type = arguments.get("action_type") or tool_name

            if sensitive_type:
                guard_config = self._safety.config
                if sensitive_type in guard_config.always_confirm_actions \
                        and not self._has_confirmation(sensitive_type, arguments):
                    logger.warning(
                        "Confirmation guard blocked %s: %r",
                        sensitive_type,
                        arguments,
                    )
                    return {
                        "ok": False,
                        "error": (
                            "REFUSED: this action requires user confirmation. "
                            "Call request_user_confirmation first with the "
                            "action_type, target, and risk_explanation."
                        ),
                    }

        # Strip internal-only keys before dispatching to actual tool methods.
        # action_type and target are used only by the confirmation guard.
        # (Keep them for request_user_confirmation — they are real params there.)
        internal_keys = {"action_type", "target"} if tool_name != "request_user_confirmation" else set()
        clean_args = {k: v for k, v in arguments.items()
                      if k not in internal_keys}
        try:
            if tool_name == "request_user_confirmation" and self._app_controller is not None:
                result = await self._app_controller.request_user_confirmation(**clean_args)
                # Normalize to the same shape the dispatcher normally returns.
                result = {
                    "ok": result not in ("no", "timeout", "stop"),
                    "confirmed": result == "yes",
                    "user_response": result,
                    "observation": f"user said {result}",
                }
                if result["user_response"] == "stop":
                    result["error"] = "user aborted the task"
                    result["ok"] = False
            elif tool_name == "llm_complete":
                result = await self._llm_complete(**clean_args)
            else:
                result = self._dispatch_inner(tool_name, clean_args)

            # Record the tool message for confirmation guard tracking.
            self._tool_messages.append(
                {"name": tool_name, "arguments": arguments, "result": result}
            )

            return result
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
        elif tool_name == "clipboard_read":
            return self._clipboard_read(**arguments)
        elif tool_name == "clipboard_write":
            return self._clipboard_write(**arguments)
        elif tool_name == "file_list":
            return self._file_list(**arguments)
        elif tool_name == "file_mkdir":
            return self._file_mkdir(**arguments)
        elif tool_name == "file_move":
            return self._file_move(**arguments)
        elif tool_name == "system_info":
            return self._system_info(**arguments)
        elif tool_name == "llm_complete":
            # Handled via async path in dispatch(); this is a safety fallback.
            return {"ok": False, "error": "llm_complete requires async dispatch"}
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
        # Validate arguments against the Pydantic tool spec first.
        from agent_uia.tools.specs.launch_app import LaunchAppInput

        validated = LaunchAppInput(executable=executable, args=args or [])
        executable = validated.executable
        args = list(validated.args)

        _validate_launch_args([executable] + args)

        import os
        exe_name = os.path.basename(executable)

        from agent_uia.safety import assert_app_allowed
        assert_app_allowed(exe_name=exe_name, gate=self._safety)

        cmd = [executable] + args
        proc = subprocess.Popen(cmd, shell=False)
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

        from agent_uia.executor import UIAControlNode
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

    # -- clipboard tools -------------------------------------------------------

    def _clipboard_read(self) -> dict[str, Any]:
        """Read text from the system clipboard."""
        try:
            import pyperclip

            text = pyperclip.paste()
            return {
                "ok": True,
                "text": text,
                "observation": f"Read {len(text)} character(s) from clipboard.",
            }
        except Exception as exc:
            return {"ok": False, "error": f"Failed to read clipboard: {exc}"}

    def _clipboard_write(self, text: str) -> dict[str, Any]:
        """Write text to the system clipboard."""
        server_len = len(text)
        if server_len > 100_000:
            return {
                "ok": False,
                "error": (
                    f"Clipboard text too long: {server_len} characters "
                    f"(max 100,000)."
                ),
            }
        try:
            import pyperclip

            pyperclip.copy(text)
            return {
                "ok": True,
                "observation": f"Wrote {server_len} character(s) to clipboard.",
            }
        except Exception as exc:
            return {"ok": False, "error": f"Failed to write clipboard: {exc}"}

    # -- file tools ------------------------------------------------------------

    @staticmethod
    def _resolve_dir(key: str) -> Path | None:
        """Resolve a directory key to an absolute Path, or None if unknown."""
        base = _ALLOWED_DIRS.get(key)
        if base is None:
            return None
        return base.resolve()

    def _file_list(
        self,
        directory: str,
        pattern: str = "*",
        limit: int = 200,
    ) -> dict[str, Any]:
        """List files in a directory."""
        dir_path = self._resolve_dir(directory)
        if dir_path is None:
            return {"ok": False, "error": f"Unknown directory: {directory!r}"}

        if not dir_path.is_dir():
            return {
                "ok": False,
                "error": f"Directory does not exist: {dir_path}",
            }

        import fnmatch

        entries: list[dict[str, Any]] = []
        try:
            with os.scandir(dir_path) as it:
                for i, entry in enumerate(it):
                    if i >= limit:
                        break
                    if fnmatch.fnmatch(entry.name, pattern):
                        import datetime

                        mtime = datetime.datetime.fromtimestamp(
                            entry.stat().st_mtime, tz=datetime.timezone.utc
                        )
                        entries.append({
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": entry.stat().st_size,
                            "modified": mtime.isoformat(),
                        })
        except PermissionError as exc:
            return {"ok": False, "error": f"Permission denied: {exc}"}
        except OSError as exc:
            return {"ok": False, "error": f"Failed to list directory: {exc}"}

        return {
            "ok": True,
            "directory": directory,
            "path": str(dir_path),
            "entries": entries,
            "count": len(entries),
            "observation": (
                f"Found {len(entries)} file(s) in {directory} "
                f"matching {pattern!r}."
            ),
        }

    def _file_mkdir(self, directory: str, name: str) -> dict[str, Any]:
        """Create a new directory."""
        dir_path = self._resolve_dir(directory)
        if dir_path is None:
            return {"ok": False, "error": f"Unknown directory: {directory!r}"}

        target = dir_path / name
        try:
            target.mkdir(exist_ok=False)
        except FileExistsError:
            return {
                "ok": False,
                "error": f"Directory already exists: {target}",
            }
        except PermissionError as exc:
            return {"ok": False, "error": f"Permission denied: {exc}"}
        except OSError as exc:
            return {"ok": False, "error": f"Failed to create directory: {exc}"}

        return {
            "ok": True,
            "path": str(target.resolve()),
            "observation": f"Created directory: {target}.",
        }

    def _file_move(
        self,
        source: str,
        source_directory: str,
        destination_directory: str,
        destination_subfolder: str | None = None,
    ) -> dict[str, Any]:
        """Move a file between directories, blocking dangerous extensions."""
        _, ext = os.path.splitext(source)
        if ext.lower() in _DANGEROUS_EXTENSIONS:
            return {
                "ok": False,
                "error": (
                    f"Refusing to move file with dangerous extension: {ext!r}. "
                    f"Blocked extensions: {sorted(_DANGEROUS_EXTENSIONS)}."
                ),
            }

        src_dir = self._resolve_dir(source_directory)
        dst_dir = self._resolve_dir(destination_directory)
        if src_dir is None:
            return {"ok": False, "error": f"Unknown source directory: {source_directory!r}"}
        if dst_dir is None:
            return {"ok": False, "error": f"Unknown destination directory: {destination_directory!r}"}

        src_path = src_dir / source
        if not src_path.exists():
            return {
                "ok": False,
                "error": f"Source file not found: {src_path}",
            }
        if src_path.is_dir():
            return {
                "ok": False,
                "error": f"Source is a directory, not a file: {src_path}",
            }

        dst_path = dst_dir / (destination_subfolder or "")
        if destination_subfolder:
            dst_path.mkdir(parents=True, exist_ok=True)
        dst_path = dst_path / source

        try:
            shutil.move(str(src_path), str(dst_path))
        except OSError as exc:
            return {"ok": False, "error": f"Failed to move file: {exc}"}

        return {
            "ok": True,
            "source": str(src_path),
            "destination": str(dst_path),
            "observation": f"Moved {source!r} to {dst_path}.",
        }

    # -- system_info tool ------------------------------------------------------

    def _system_info(self, components: list[str] | None = None) -> dict[str, Any]:
        """Query system resource information."""
        if components is None:
            components = ["cpu", "memory", "disk", "uptime"]

        result: dict[str, Any] = {"ok": True}
        try:
            import psutil
        except ImportError:
            return {"ok": False, "error": "psutil is not installed"}

        for comp in components:
            try:
                if comp == "cpu":
                    result["cpu"] = {
                        "percent": psutil.cpu_percent(interval=0.1),
                    }
                elif comp == "memory":
                    mem = psutil.virtual_memory()
                    result["memory"] = {
                        "total": mem.total,
                        "available": mem.available,
                        "percent": mem.percent,
                        "used": mem.used,
                        "free": mem.free,
                    }
                elif comp == "disk":
                    disk = psutil.disk_usage("/")
                    result["disk"] = {
                        "total": disk.total,
                        "used": disk.used,
                        "free": disk.free,
                        "percent": disk.percent,
                    }
                elif comp == "uptime":
                    import time

                    result["uptime"] = {
                        "seconds": time.time() - psutil.boot_time(),
                    }
            except Exception as exc:
                result[comp] = {"error": str(exc)}

        return result

    # -- llm_complete tool (async) ---------------------------------------------

    _llm_call_count: int = 0

    async def _llm_complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Send a prompt to the configured LLM and return the response."""
        from agent_uia.llm_client import LLMClient, LLMConfig, UserMessage, SystemMessage

        config = LLMConfig(
            max_tokens_per_call=max_tokens,
            temperature=temperature,
        )
        client = LLMClient(config)

        messages: list[Any] = [UserMessage(content=prompt)]
        if system:
            messages.insert(0, SystemMessage(content=system))

        try:
            response = await client.chat(messages)
        except Exception as exc:
            return {"ok": False, "error": f"LLM call failed: {exc}"}

        type(self)._llm_call_count += 1

        return {
            "ok": True,
            "response": response.message.content or "",
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "observation": (
                f"LLM completed ({response.usage.total_tokens} tokens, "
                f"{response.usage.estimated_cost_usd}$)."
            ),
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

    def _request_user_confirmation(
        self,
        action_type: str,
        target: str,
        risk_explanation: str,
        timeout_s: int = 30,
    ) -> dict[str, Any]:
        """CLI fallback for confirmation: always deny.

        When a GUI ``AppController`` is available, ``dispatch()`` calls its
        async confirmation bridge directly instead of this fallback.
        """
        logger.warning(
            "User confirmation requested but no GUI available: "
            "action=%r target=%r",
            action_type,
            target,
        )
        result = "no"

        # Log to safety audit if gate is available.
        try:
            self._safety._record(
                actor="user",
                action_type=f"request_user_confirmation:{action_type}",
                target=target,
                verdict=result.upper(),
                reason=f"User responded {result} to action {action_type!r} on {target!r}.",
                user_response=result,
            )
        except Exception:
            logger.exception("Failed to log confirmation to audit")

        return {
            "ok": True,
            "confirmed": False,
            "user_response": result,
            "observation": f"user said {result}",
        }

    # -- confirmation guard helper --------------------------------------------

    def _has_confirmation(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> bool:
        """Check whether the most recent confirmation covers this action.

        Scans recent tool messages looking for a ``request_user_confirmation``
        call whose ``target`` matches a key argument of the current action,
        and whose result was ``"yes"``.

        Both targets are normalized (stripped, lower-cased) and must match
        exactly. Empty targets never match, preventing accidental bypass.
        """

        def _normalize(value: Any) -> str:
            return str(value).strip().lower()

        action_target = _normalize(
            arguments.get("target")
            or arguments.get("control_id")
            or arguments.get("window_id")
            or ""
        )
        if not action_target:
            return False

        # Scan backwards — most recent confirmation first.
        for msg in reversed(self._tool_messages):
            if msg["name"] != "request_user_confirmation":
                continue
            result = msg["result"]
            if not result.get("ok") or result.get("user_response") != "yes":
                continue
            conf_target = _normalize(msg["arguments"].get("target", ""))
            if conf_target and conf_target == action_target:
                return True
        return False

    # -- window/control registry helpers ---------------------------------------

    def _register_window(self, win: Any) -> str:
        """Register a window and return an opaque id."""
        wid = f"win-{id(win):x}-{len(self._windows)}"
        self._windows[wid] = win
        return wid

    def _get_window(self, window_id: str) -> Any:
        """Retrieve a registered window by id."""
        return self._windows.get(window_id)

    def _get_control(self, control_id: str) -> Any:
        """Retrieve a control from the executor's handle registry."""
        return self._executor._UIAHandleRegistry.get(control_id)  # noqa: SLF001
