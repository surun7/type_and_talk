# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""TNT GUI layer — system tray, floating window, global hotkey.

Submodules:
    hotkey — Win32 RegisterHotKey via pure ctypes.
    tray — QSystemTrayIcon with programmatic icon.
    floating_window — Spotlight-like floating chat window.
    app_controller — Glue between UI and async Planner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppConfig, AppController


def __getattr__(name: str):
    """Lazy-import AppConfig / AppController to avoid circular deps."""
    if name in ("AppConfig", "AppController"):
        from agent_uia.ui.app_controller import AppConfig as _acfg
        from agent_uia.ui.app_controller import AppController as _actrl

        globals()["AppConfig"] = _acfg
        globals()["AppController"] = _actrl
        return _acfg if name == "AppConfig" else _actrl
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "AppConfig",
    "AppController",
]
