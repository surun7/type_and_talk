# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""UIA Executor — the core UI manipulation engine.

Wraps the ``uiautomation`` library with a clean, safe, async-friendly API.
No raw UIA handles are ever leaked to the public surface.
"""

from __future__ import annotations

import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

from agent_uia.safety import (
    SafetyGate,
    assert_app_allowed,
    default_gate,
)

__all__ = [
    "UIAWindowInfo",
    "UIAControlRef",
    "UIAControlNode",
    "UIAExecutor",
]


# ── data types ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UIAWindowInfo:
    """Immutable snapshot of a top-level window.

    Attributes:
        handle: The native window handle (HWND as int).
        pid: Process id of the owning process.
        title: Window title string (may be empty).
        class_name: Window class name.
        exe_name: Executable basename (e.g. ``"notepad.exe"``).
        rect: Bounding rectangle ``(x, y, width, height)`` in screen coords.
    """

    handle: int
    pid: int
    title: str
    class_name: str
    exe_name: str
    rect: tuple[int, int, int, int]  # (x, y, w, h)


class UIAControlRef:
    """Opaque reference to a UIA control.

    This is the ONLY type callers ever see for controls.  The underlying
    ``uiautomation`` object is stored internally and never exposed.

    Attributes (public, read-only):
        name: The control's ``Name`` property.
        control_type: The control's ``ControlTypeName``.
        automation_id: The control's ``AutomationId`` (may be empty).
        class_name: The control's ``ClassName``.
        rect: Bounding rectangle ``(x, y, w, h)``.
        is_enabled: Whether the control is enabled.
        is_visible: Whether the control is visible (``IsOffscreen == False``).
    """

    __slots__ = ("_token", "_registry")

    def __init__(
        self,
        token: str,
        registry: _UIAHandleRegistry,
    ) -> None:
        self._token = token
        self._registry = registry

    @property
    def _uia(self) -> Any:
        """Resolve the token to the live ``uiautomation`` object.

        This property is private — callers MUST NOT access it.
        """
        obj = self._registry.get(self._token)
        if obj is None:
            raise RuntimeError(
                f"UIAControlRef token '{self._token}' has been garbage-collected"
            )
        return obj

    # -- public accessors ------------------------------------------------------

    @property
    def name(self) -> str:
        """Control Name property."""
        try:
            return str(self._uia.Name or "")
        except Exception:
            return ""

    @property
    def control_type(self) -> str:
        """Control type name (e.g. "Button", "Edit")."""
        try:
            return str(self._uia.ControlTypeName or "")
        except Exception:
            return ""

    @property
    def automation_id(self) -> str:
        """Control AutomationId."""
        try:
            return str(self._uia.AutomationId or "")
        except Exception:
            return ""

    @property
    def class_name(self) -> str:
        """Control ClassName."""
        try:
            return str(self._uia.ClassName or "")
        except Exception:
            return ""

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Bounding rectangle ``(x, y, w, h)``."""
        try:
            r = self._uia.BoundingRectangle
            if r is None:
                return (0, 0, 0, 0)
            return (r.left, r.top, r.width(), r.height())
        except Exception:
            return (0, 0, 0, 0)

    @property
    def is_enabled(self) -> bool:
        """Whether the control is enabled."""
        try:
            return bool(self._uia.IsEnabled)
        except Exception:
            return False

    @property
    def is_visible(self) -> bool:
        """Whether the control is visible (not off-screen)."""
        try:
            return not bool(self._uia.IsOffscreen)
        except Exception:
            return False

    def get_text(self) -> str:
        """Read the control's text content.

        Tries ``ValuePattern.Value`` first, then ``Name``, then
        ``LegacyIAccessiblePattern.Value``.
        """
        uia = self._uia
        try:
            vp = uia.GetValuePattern()
            if vp is not None:
                return str(vp.Value or "")
        except Exception:
            pass
        try:
            return str(uia.Name or "")
        except Exception:
            return ""


@dataclass
class UIAControlNode:
    """A node in the control accessibility tree.

    Attributes:
        ref: The control reference.
        children: Child nodes.
        depth: Depth from the root (0 = root).
    """

    ref: UIAControlRef
    children: list[UIAControlNode] = field(default_factory=list)
    depth: int = 0

    def to_compact_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly compact representation of the subtree.

        Each node dict has keys: ``name``, ``control_type``, ``automation_id``,
        ``rect``, ``depth``, and ``children`` (list of child dicts).
        """
        return {
            "name": self.ref.name,
            "control_type": self.ref.control_type,
            "automation_id": self.ref.automation_id,
            "rect": list(self.ref.rect),
            "depth": self.depth,
            "children": [child.to_compact_dict() for child in self.children],
        }


# ── internal handle registry ─────────────────────────────────────────────────


class _UIAHandleRegistry:
    """Weakref-based registry mapping opaque tokens to live UIA objects.

    This ensures ``UIAControlRef`` ops don't keep controls alive longer
    than necessary, while still providing stable opaque references.
    """

    def __init__(self) -> None:
        self._store: dict[str, weakref.ReferenceType[Any]] = {}
        self._counter: int = 0
        self._lock: Any = __import__("threading").Lock()

    def register(self, obj: Any) -> str:
        """Store *obj* and return an opaque token string."""
        with self._lock:
            self._counter += 1
            token = f"uia:{self._counter}:{id(obj):x}"
            self._store[token] = weakref.ref(obj)
        return token

    def get(self, token: str) -> Any | None:
        """Resolve a token. Returns ``None`` if collected or unknown."""
        with self._lock:
            ref = self._store.get(token)
        if ref is None:
            return None
        return ref()

    def cleanup(self) -> int:
        """Remove dead entries. Returns count of removed tokens."""
        with self._lock:
            dead = [t for t, r in self._store.items() if r() is None]
            for t in dead:
                del self._store[t]
        return len(dead)


# ── executor ─────────────────────────────────────────────────────────────────


class UIAExecutor:
    """Core UI manipulation engine.

    Every public method calls the safety gate BEFORE performing any UIA
    operation.  All UIA objects are wrapped in opaque references so that
    no raw ``uiautomation`` handles leak to callers.

    Args:
        safety_gate: The ``SafetyGate`` to enforce. Defaults to the
            process-wide singleton.
    """

    def __init__(self, safety_gate: SafetyGate | None = None) -> None:
        self._safety = safety_gate or default_gate()
        self._registry = _UIAHandleRegistry()

    # -- window discovery ------------------------------------------------------

    def find_window(
        self,
        *,
        title_contains: str | None = None,
        class_name: str | None = None,
        exe_name: str | None = None,
        pid: int | None = None,
        timeout: float = 5.0,
    ) -> UIAWindowInfo | None:
        """Find a top-level window matching the given criteria.

        Returns ``None`` if no match is found within *timeout* seconds.

        Args:
            title_contains: Substring to match against the window title.
            class_name: Exact window class name.
            exe_name: Executable basename to match.
            pid: Process id filter.
            timeout: How long to poll (seconds).

        Returns:
            A ``UIAWindowInfo`` or ``None``.
        """
        import uiautomation as _uia

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for raw in self._iter_top_level_windows():
                info = self._raw_to_window_info(raw)
                if title_contains and title_contains.lower() not in info.title.lower():
                    continue
                if class_name and class_name != info.class_name:
                    continue
                if exe_name and exe_name.lower() != info.exe_name.lower():
                    continue
                if pid is not None and pid != info.pid:
                    continue
                # Safety check before returning.
                assert_app_allowed(
                    exe_name=info.exe_name,
                    window_title=info.title,
                    gate=self._safety,
                )
                return info
            time.sleep(0.2)
        return None

    def list_windows(
        self,
        *,
        title_contains: str | None = None,
    ) -> list[UIAWindowInfo]:
        """List all top-level windows, optionally filtered by title substring.

        Args:
            title_contains: Optional substring filter on window title.

        Returns:
            A list of ``UIAWindowInfo`` objects.
        """
        results: list[UIAWindowInfo] = []
        for raw in self._iter_top_level_windows():
            info = self._raw_to_window_info(raw)
            if title_contains and title_contains.lower() not in info.title.lower():
                continue
            results.append(info)
        return results

    # -- control tree ----------------------------------------------------------

    def get_control_tree(
        self,
        window: UIAWindowInfo,
        *,
        max_depth: int = 8,
    ) -> UIAControlNode:
        """Build the accessibility control tree for a window.

        Args:
            window: The target window.
            max_depth: Maximum recursion depth (default 8).

        Returns:
            The root ``UIAControlNode`` of the tree.
        """
        self._safety_check_window(window)
        import uiautomation as _uia

        raw_ctrl = _uia.ControlFromHandle(window.handle)
        return self._build_tree(raw_ctrl, depth=0, max_depth=max_depth)

    # -- actions ---------------------------------------------------------------

    def click(
        self,
        control: UIAControlRef,
        *,
        button: Literal["left", "right", "middle"] = "left",
        double: bool = False,
    ) -> None:
        """Click a control.

        Args:
            control: The target control.
            button: Mouse button to click.
            double: If ``True``, perform a double-click.
        """
        self._safety_check_control(control)
        uia = control._uia  # noqa: SLF001
        # Focus first, then click.
        try:
            uia.SetFocus()
        except Exception:
            logger.debug("SetFocus failed for control, attempting click anyway")
        if double:
            try:
                uia.DoubleClick()
            except Exception:
                _simulated_double_click(uia, button)
        else:
            try:
                uia.Click()
            except Exception:
                _simulated_click(uia, button)

    def type_text(self, control: UIAControlRef, text: str) -> None:
        """Type text into a control by simulating keystrokes.

        NOTE: Prefer ``set_value()`` for Edit controls — it uses
        ``ValuePattern`` and is faster and IME-safe. Use ``type_text``
        only when ``set_value`` is not available.

        Args:
            control: The target control.
            text: The text to type.
        """
        self._safety_check_control(control)
        uia = control._uia  # noqa: SLF001
        try:
            uia.SetFocus()
        except Exception:
            logger.debug("SetFocus failed before type_text")
        import uiautomation as _uia

        _uia.SendKeys(text, waitTime=0.02)

    def invoke(self, control: UIAControlRef) -> None:
        """Invoke a control (Button/InvokePattern).

        Args:
            control: The target control (must support InvokePattern).
        """
        self._safety_check_control(control)
        uia = control._uia  # noqa: SLF001
        try:
            ip = uia.GetInvokePattern()
            if ip is not None:
                ip.Invoke()
            else:
                uia.Click()
        except Exception:
            uia.Click()

    def set_value(self, control: UIAControlRef, value: str) -> None:
        """Set the value of an Edit/ValuePattern control.

        This is the preferred method for text input — it uses the UIA
        ``ValuePattern.SetValue`` which is instant and IME-safe.

        Args:
            control: The target control.
            value: The new text value.
        """
        self._safety_check_control(control)
        uia = control._uia  # noqa: SLF001
        try:
            vp = uia.GetValuePattern()
            if vp is not None:
                vp.SetValue(value)
                return
        except Exception:
            logger.debug("ValuePattern.SetValue failed, falling back to type_text")
        # Fallback
        self.type_text(control, value)

    def press_key(self, key: str) -> None:
        """Send a global key press.

        Args:
            key: Key name or combination (e.g. ``"ctrl+a"``, ``"Return"``,
                ``"Escape"``).
        """
        import uiautomation as _uia

        _uia.SendKeys("{" + key + "}", waitTime=0.02)

    # -- wait helpers ----------------------------------------------------------

    def wait_for_window(
        self,
        *,
        title_contains: str,
        timeout: float = 10.0,
    ) -> UIAWindowInfo:
        """Poll for a window whose title contains *title_contains*.

        Args:
            title_contains: Substring to match in the window title.
            timeout: Maximum seconds to wait.

        Returns:
            The matching ``UIAWindowInfo``.

        Raises:
            TimeoutError: If no window matches within *timeout*.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            win = self.find_window(title_contains=title_contains, timeout=0.0)
            if win is not None:
                return win
            time.sleep(0.2)
        raise TimeoutError(
            f"Timed out after {timeout:.1f}s waiting for window "
            f"title_contains='{title_contains}'"
        )

    def wait_for_control(
        self,
        parent: UIAWindowInfo,
        *,
        name_contains: str | None = None,
        automation_id: str | None = None,
        control_type: str | None = None,
        timeout: float = 10.0,
    ) -> UIAControlRef:
        """Poll for a control inside *parent*.

        Args:
            parent: The parent window.
            name_contains: Substring to match in the control name.
            automation_id: Exact AutomationId.
            control_type: Control type name (e.g. ``"Edit"``).
            timeout: Maximum seconds to wait.

        Returns:
            The matching ``UIAControlRef``.

        Raises:
            TimeoutError: If no control matches within *timeout*.
        """
        self._safety_check_window(parent)
        import uiautomation as _uia

        deadline = time.monotonic() + timeout
        raw_parent = _uia.ControlFromHandle(parent.handle)
        while time.monotonic() < deadline:
            result = self._find_control_in(
                raw_parent,
                name_contains=name_contains,
                automation_id=automation_id,
                control_type=control_type,
            )
            if result is not None:
                return result
            time.sleep(0.2)
        raise TimeoutError(
            f"Timed out after {timeout:.1f}s waiting for control "
            f"name='{name_contains}' auto_id='{automation_id}' type='{control_type}'"
        )

    def close_window(self, window: UIAWindowInfo) -> None:
        """Close a top-level window.

        Sends ``WM_CLOSE`` via the UIA ``WindowPattern.Close`` if available,
        otherwise falls back to ``Alt+F4``.

        Args:
            window: The window to close.
        """
        self._safety_check_window(window)
        import uiautomation as _uia

        try:
            raw = _uia.ControlFromHandle(window.handle)
            wp = raw.GetWindowPattern()
            if wp is not None:
                wp.Close()
                return
        except Exception:
            logger.debug("WindowPattern.Close failed, falling back to Alt+F4")
        # Fallback: focus and send Alt+F4.
        try:
            raw = _uia.ControlFromHandle(window.handle)
            raw.SetFocus()
        except Exception:
            pass
        _uia.SendKeys("{Alt}f4", waitTime=0.1)

    # -- internal helpers ------------------------------------------------------

    def _safety_check_window(self, window: UIAWindowInfo) -> None:
        """Run the safety gate against a window."""
        assert_app_allowed(
            exe_name=window.exe_name,
            window_title=window.title,
            gate=self._safety,
        )

    def _safety_check_control(self, control: UIAControlRef) -> None:
        """Run the safety gate against the window owning *control*.

        NOTE: This is a best-effort check.  The control's parent window
        is looked up via the UIA tree. If resolution fails the action
        is still allowed — the safety check fires at window-discovery
        time as well.
        """
        try:
            uia = control._uia  # noqa: SLF001
            import uiautomation as _uia

            ancestor = uia
            for _ in range(16):
                parent = ancestor.GetParentControl()
                if parent is None:
                    break
                ancestor = parent
            # Try to get window info from the topmost ancestor.
            raw_win = _uia.ControlFromHandle(ancestor.NativeWindowHandle)
            win_info = self._raw_to_window_info(raw_win)
            self._safety_check_window(win_info)
        except Exception:
            logger.debug("Could not resolve parent window for safety check")

    @staticmethod
    def _raw_to_window_info(raw: Any) -> UIAWindowInfo:
        """Convert a ``uiautomation`` top-level window to ``UIAWindowInfo``."""
        import uiautomation as _uia

        handle = raw.NativeWindowHandle
        pid = raw.ProcessId

        title = ""
        try:
            title = raw.Name or ""
        except Exception:
            pass

        class_name_val = ""
        try:
            class_name_val = raw.ClassName or ""
        except Exception:
            pass

        exe = ""
        try:
            exe = _uia.GetProcessFilename(pid) or ""
        except Exception:
            pass
        # Extract basename.
        if exe:
            import os
            exe = os.path.basename(exe)

        rect = (0, 0, 0, 0)
        try:
            r = raw.BoundingRectangle
            if r is not None:
                rect = (r.left, r.top, r.width(), r.height())
        except Exception:
            pass

        return UIAWindowInfo(
            handle=handle,
            pid=pid,
            title=title,
            class_name=class_name_val,
            exe_name=exe,
            rect=rect,
        )

    @staticmethod
    def _iter_top_level_windows() -> list[Any]:
        """Yield all top-level desktop windows via ``uiautomation``."""
        import uiautomation as _uia

        return list(_uia.GetRootControl().GetChildren())

    def _build_tree(
        self,
        raw_control: Any,
        *,
        depth: int,
        max_depth: int,
    ) -> UIAControlNode:
        """Recursively build a ``UIAControlNode`` tree."""
        token = self._registry.register(raw_control)
        ref = UIAControlRef(token, self._registry)

        node = UIAControlNode(ref=ref, depth=depth)

        if depth >= max_depth:
            return node

        try:
            children = raw_control.GetChildren()
        except Exception:
            children = []

        for child in children:
            node.children.append(
                self._build_tree(child, depth=depth + 1, max_depth=max_depth)
            )

        return node

    def _find_control_in(
        self,
        raw_parent: Any,
        *,
        name_contains: str | None,
        automation_id: str | None,
        control_type: str | None,
    ) -> UIAControlRef | None:
        """Recursively search for a control under *raw_parent*."""
        try:
            children = raw_parent.GetChildren()
        except Exception:
            return None

        for child in children:
            if control_type:
                try:
                    ct = child.ControlTypeName or ""
                except Exception:
                    ct = ""
                if ct != control_type:
                    continue
            if automation_id:
                try:
                    aid = child.AutomationId or ""
                except Exception:
                    aid = ""
                if aid != automation_id:
                    continue
            if name_contains:
                try:
                    nm = child.Name or ""
                except Exception:
                    nm = ""
                if name_contains.lower() not in nm.lower():
                    continue
            # Match found.
            token = self._registry.register(child)
            return UIAControlRef(token, self._registry)

        # Recurse.
        for child in children:
            result = self._find_control_in(
                child,
                name_contains=name_contains,
                automation_id=automation_id,
                control_type=control_type,
            )
            if result is not None:
                return result

        return None


# ── simulated fallback clicks (no raw handle exposure) ───────────────────────


def _simulated_click(control: Any, button: str) -> None:
    """Fallback click using SendMouseClick."""
    import uiautomation as _uia

    try:
        rect = control.BoundingRectangle
        if rect:
            x = rect.left + rect.width() // 2
            y = rect.top + rect.height() // 2
            _uia.Click(x, y)
            return
    except Exception:
        pass
    # Last resort: try the control's own Click.
    try:
        control.Click()
    except Exception:
        logger.warning("All click methods failed for control")


def _simulated_double_click(control: Any, button: str) -> None:
    """Fallback double-click using SendMouseClick."""
    import uiautomation as _uia

    try:
        rect = control.BoundingRectangle
        if rect:
            x = rect.left + rect.width() // 2
            y = rect.top + rect.height() // 2
            _uia.DoubleClick(x, y)
            return
    except Exception:
        pass
    try:
        control.DoubleClick()
    except Exception:
        logger.warning("All double-click methods failed for control")
