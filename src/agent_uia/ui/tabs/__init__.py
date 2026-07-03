# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tab views for the TNT main window.

This module provides lazy re-exports so that importing any tab class does
not force loading of all tab modules at once.

Usage::

    from agent_uia.ui.tabs import HomeTab
    from agent_uia.ui.tabs.home_tab import HomeTab  # same thing, direct import
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_uia.ui.tabs.home_tab import HomeTab
    from agent_uia.ui.tabs.history_tab import HistoryTab
    from agent_uia.ui.tabs.history_detail_dialog import HistoryDetailDialog
    from agent_uia.ui.tabs.skills_tab import SkillsTab
    from agent_uia.ui.tabs.settings_tab import SettingsTab
    from agent_uia.ui.tabs.usage_tab import UsageTab
    from agent_uia.ui.tabs.performance_tab import PerformanceTab


def __getattr__(name: str):
    """Lazy-import tab classes to avoid circular imports."""
    _lazy: dict[str, tuple[str, str]] = {
        "HomeTab": ("agent_uia.ui.tabs.home_tab", "HomeTab"),
        "HistoryTab": ("agent_uia.ui.tabs.history_tab", "HistoryTab"),
        "HistoryDetailDialog": (
            "agent_uia.ui.tabs.history_detail_dialog",
            "HistoryDetailDialog",
        ),
        "SkillsTab": ("agent_uia.ui.tabs.skills_tab", "SkillsTab"),
        "SettingsTab": ("agent_uia.ui.tabs.settings_tab", "SettingsTab"),
        "UsageTab": ("agent_uia.ui.tabs.usage_tab", "UsageTab"),
        "PerformanceTab": ("agent_uia.ui.tabs.performance_tab", "PerformanceTab"),
    }

    entry = _lazy.get(name)
    if entry is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

    module_path, cls_name = entry
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    globals()[name] = cls
    return cls


__all__ = [
    "HomeTab",
    "HistoryTab",
    "HistoryDetailDialog",
    "SkillsTab",
    "SettingsTab",
    "UsageTab",
    "PerformanceTab",
]
