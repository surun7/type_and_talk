# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""
Global hotkey via Win32 ``RegisterHotKey`` — pure ctypes, no input injection.

We use Win32 RegisterHotKey (a notification-only API) instead of an
input-injection library like ``keyboard``/``pynput`` so we never synthesize
key/click events. TNT is an observer, not an actor, at the OS input layer.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

__all__ = [
    "HotkeyError",
    "HotkeyGroupError",
    "GlobalHotkey",
    "GlobalHotkeyGroup",
    "parse_hotkey",
]

# ── Win32 constants (from winuser.h) ─────────────────────────────────────────

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# VK codes (subset needed for hotkey parsing)
_VK_MAP: dict[str, int] = {
    # Letters a-z (lowercased input matches lowercase keys)
    **{chr(0x61 + i): 0x41 + i for i in range(26)},
    # Digits 0-9
    **{str(i): 0x30 + i for i in range(10)},
    # Function keys
    **{f"f{i}": 0x70 + i - 1 for i in range(1, 13)},
    # Named keys
    "space": 0x20,
    "tab": 0x09,
    "escape": 0x1B,
    "return": 0x0D,
    "backspace": 0x08,
    "delete": 0x2E,
}

_MOD_MAP: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}


# ── errors ───────────────────────────────────────────────────────────────────


class HotkeyError(Exception):
    """Raised when hotkey registration fails or a combination is reserved."""


class HotkeyGroupError(Exception):
    """Raised when a hotkey-group operation fails."""


# ── parsing ──────────────────────────────────────────────────────────────────


def parse_hotkey(s: str) -> tuple[int, int]:
    """Parse a hotkey string into ``(fsModifiers, vk_code)``.

    Accepts ``"ctrl+shift+space"``, ``"alt+f4"``, etc. Modifier order does not
    matter. Modifiers: ``ctrl``/``control``, ``shift``, ``alt``, ``win``/``windows``.
    Keys: letters ``a``-``z``, digits ``0``-``9``, ``F1``-``F12``, ``space``,
    ``tab``, ``escape``, ``return``, ``backspace``, ``delete``.

    Raises ``HotkeyError`` for reserved combinations:
    - ``ctrl+alt+delete`` (Winlogon secure attention sequence)
    - ``ctrl+escape`` (Start menu)
    - Any combination including ``win+l`` (Windows lock screen)
    """
    parts = [p.strip().lower() for p in s.split("+")]
    if len(parts) < 2:
        raise HotkeyError(
            f"Invalid hotkey {s!r}: must be modifier+key, e.g. 'ctrl+shift+space'"
        )

    modifiers = 0
    key_part = parts[-1]
    for mod_name in parts[:-1]:
        mod_val = _MOD_MAP.get(mod_name)
        if mod_val is None:
            raise HotkeyError(
                f"Unknown modifier {mod_name!r} in hotkey {s!r}. "
                f"Supported: ctrl, alt, shift, win"
            )
        modifiers |= mod_val

    vk = _VK_MAP.get(key_part)
    if vk is None:
        raise HotkeyError(
            f"Unknown key {key_part!r} in hotkey {s!r}. "
            f"Supported: a-z, 0-9, F1-F12, space, tab, escape, "
            f"return, backspace, delete"
        )

    # Reserved combinations.
    reserved = (
        # ctrl+alt+delete
        (modifiers & (MOD_CONTROL | MOD_ALT) == (MOD_CONTROL | MOD_ALT)
         and vk == 0x2E)
        or
        # ctrl+escape
        (modifiers & MOD_CONTROL and vk == 0x1B)
        or
        # any combination with win+l
        (modifiers & MOD_WIN and vk == 0x4C)
    )
    if reserved:
        raise HotkeyError(
            f"Hotkey {s!r} is reserved by Windows and cannot be used."
        )

    return modifiers, vk


# ── GlobalHotkey ─────────────────────────────────────────────────────────────


class GlobalHotkey:
    """Win32 global hotkey registration.

    Usage::

        hotkey = GlobalHotkey("ctrl+shift+space")
        hotkey.start(on_activate)
        # ...
        hotkey.stop()
    """

    def __init__(self, key_combination: str) -> None:
        self._key_combo = key_combination
        self._modifiers, self._vk = parse_hotkey(key_combination)
        self._registered = False
        self._thread: threading.Thread | None = None
        self._callback: Callable[[], None] | None = None
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

    # ── public API ───────────────────────────────────────────────────────

    def start(self, callback: Callable[[], None]) -> None:
        """Register the hotkey and start the message-pump thread.

        Args:
            callback: Zero-arg callable invoked on each hotkey press.

        Raises:
            HotkeyError: If ``RegisterHotKey`` fails (conflict, etc.).
        """
        if self._registered:
            logger.warning(f"Hotkey {self._key_combo!r} already registered.")
            return

        self._callback = callback

        # RegisterHotKey(NULL, id, modifiers, vk)
        result = self._user32.RegisterHotKey(
            None,  # hWnd = NULL (thread-level)
            1,  # id
            self._modifiers | MOD_NOREPEAT,
            self._vk,
        )
        if not result:
            raise HotkeyError(
                f"Failed to register hotkey {self._key_combo!r}. "
                f"Another application may already use this combination."
            )

        self._registered = True
        self._thread = threading.Thread(
            target=self._pump,
            name=f"hotkey-{self._key_combo}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Hotkey {self._key_combo!r} registered.")

    def stop(self) -> None:
        """Unregister the hotkey and signal the pump thread to exit."""
        if not self._registered:
            return

        self._user32.UnregisterHotKey(None, 1)
        self._registered = False

        # Post WM_QUIT to the pump thread so GetMessage returns 0.
        if self._thread and self._thread.is_alive():
            tid = self._thread.ident
            if tid is not None:
                self._user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=2.0)

        self._thread = None
        self._callback = None
        logger.info(f"Hotkey {self._key_combo!r} unregistered.")

    @property
    def is_registered(self) -> bool:
        return self._registered

    # ── internal ─────────────────────────────────────────────────────────

    def _pump(self) -> None:
        """Daemon thread: message pump for WM_HOTKEY."""
        msg = ctypes.wintypes.MSG()
        callback = self._callback  # local ref for thread safety

        while self._registered:
            # GetMessageW blocks, releasing the GIL while waiting.
            ret = self._user32.GetMessageW(
                ctypes.byref(msg),
                None,  # hWnd = NULL (thread messages)
                0,  # wMsgFilterMin
                0,  # wMsgFilterMax
            )
            # GetMessage returns 0 on WM_QUIT, -1 on error.
            if ret <= 0:
                break

            if msg.message == WM_HOTKEY:
                try:
                    if callback:
                        callback()
                except Exception:
                    logger.exception("Error in hotkey callback")

        logger.debug("Hotkey pump thread exiting.")


# ── GlobalHotkeyGroup ────────────────────────────────────────────────────────


@dataclass
class _Registration:
    """Internal holder for a single hotkey registration in a group."""

    id: int
    modifiers: int
    vk: int
    callback: Callable[[], None] | None = None


class GlobalHotkeyGroup:
    """Manages multiple global hotkeys sharing a single message-pump thread.

    More efficient than multiple ``GlobalHotkey`` instances because all
    hotkeys share one background thread.

    Usage::

        group = GlobalHotkeyGroup()
        id1 = group.add("ctrl+shift+space", on_activate)
        id2 = group.add("alt+f4", on_quit)
        group.start()
        # ...
        group.remove(id1)
        # ...
        group.stop()
    """

    def __init__(self) -> None:
        self._next_id = 1
        self._registrations: list[_Registration] = []
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._user32 = ctypes.windll.user32

    # ── public API ───────────────────────────────────────────────────────

    def add(self, key_combination: str, callback: Callable[[], None]) -> int:
        """Register a hotkey and return its id (unique, 1-based).

        If the group is already running the hotkey is registered with Windows
        immediately. Works before ``start()`` too — all accumulated hotkeys
        are registered at once when ``start()`` is called.

        Raises:
            HotkeyGroupError: If ``RegisterHotKey`` fails (conflict, etc.).
        """
        modifiers, vk = parse_hotkey(key_combination)

        with self._lock:
            reg_id = self._next_id
            self._next_id += 1

            reg = _Registration(
                id=reg_id,
                modifiers=modifiers,
                vk=vk,
                callback=callback,
            )
            self._registrations.append(reg)
            self._callbacks[reg_id] = callback

            if self._running:
                result = self._user32.RegisterHotKey(
                    None,
                    reg_id,
                    modifiers | MOD_NOREPEAT,
                    vk,
                )
                if not result:
                    # Rollback local state.
                    self._registrations.remove(reg)
                    self._callbacks.pop(reg_id, None)
                    raise HotkeyGroupError(
                        f"Failed to register hotkey {key_combination!r}. "
                        f"Another application may already use this combination."
                    )

        return reg_id

    def remove(self, id: int) -> None:
        """Unregister a specific hotkey by id.

        If the group is running the hotkey is unregistered from Windows
        immediately. Silently no-ops if the id does not exist.
        """
        with self._lock:
            reg = next((r for r in self._registrations if r.id == id), None)
            if reg is None:
                logger.warning(f"No hotkey with id {id} to remove.")
                return

            self._registrations.remove(reg)
            self._callbacks.pop(id, None)

            if self._running:
                self._user32.UnregisterHotKey(None, id)

    def start(self) -> None:
        """Register all hotkeys and start the shared message-pump thread.

        Raises:
            HotkeyGroupError: If any ``RegisterHotKey`` call fails. All
                previously registered hotkeys are unrolled on failure.
        """
        with self._lock:
            if self._running:
                logger.warning("Hotkey group already started.")
                return

            registered_ids: list[int] = []
            try:
                for reg in self._registrations:
                    result = self._user32.RegisterHotKey(
                        None,
                        reg.id,
                        reg.modifiers | MOD_NOREPEAT,
                        reg.vk,
                    )
                    if not result:
                        raise HotkeyGroupError(
                            f"Failed to register hotkey (id={reg.id}). "
                            f"Another application may already use this "
                            f"combination."
                        )
                    registered_ids.append(reg.id)
            except HotkeyGroupError:
                # Unroll every registration that succeeded.
                for rid in registered_ids:
                    self._user32.UnregisterHotKey(None, rid)
                raise

            self._running = True

        self._thread = threading.Thread(
            target=self._pump,
            name="hotkey-group-pump",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"Hotkey group started with {len(self._registrations)} "
            f"registration(s)."
        )

    def stop(self) -> None:
        """Unregister all hotkeys and stop the shared pump thread."""
        with self._lock:
            if not self._running:
                return

            self._running = False

            for reg in self._registrations:
                self._user32.UnregisterHotKey(None, reg.id)

        # Post WM_QUIT to the pump thread so GetMessageW returns 0.
        if self._thread and self._thread.is_alive():
            tid = self._thread.ident
            if tid is not None:
                self._user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=2.0)

        self._thread = None
        logger.info("Hotkey group stopped.")

    # ── internal ─────────────────────────────────────────────────────────

    def _pump(self) -> None:
        """Shared daemon thread: message pump for WM_HOTKEY."""
        msg = ctypes.wintypes.MSG()

        while self._running:
            ret = self._user32.GetMessageW(
                ctypes.byref(msg),
                None,
                0,
                0,
            )
            if ret <= 0:
                break

            if msg.message == WM_HOTKEY:
                hotkey_id = msg.wParam
                with self._lock:
                    cb = self._callbacks.get(hotkey_id)
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        logger.exception("Error in hotkey callback")

        logger.debug("Hotkey group pump thread exiting.")
