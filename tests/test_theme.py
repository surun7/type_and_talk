# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the theme module (dark / light stylesheet application)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

# The conftest sets QT_QPA_PLATFORM=offscreen before any Qt import.


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication instance."""
    app = QApplication.instance() or QApplication([])
    return app


def _import_theme():
    """Lazy-import the theme module (avoids import-time side effects)."""
    from agent_uia.ui.theme import Theme, ThemeManager

    return Theme, ThemeManager.apply_to


def test_apply_dark(qapp):
    """apply_to(app, Theme.DARK) must set a stylesheet containing the dark
    accent colour #3b8eea."""
    Theme, apply_to = _import_theme()

    apply_to(qapp, Theme.DARK)
    ss = qapp.styleSheet()
    assert "#3B8EEA" in ss or "#3b8eea" in ss, "Dark stylesheet should contain the accent colour"


def test_apply_light(qapp):
    """apply_to(app, Theme.LIGHT) must set a stylesheet — content varies by
    implementation, but the method should not raise."""
    Theme, apply_to = _import_theme()

    apply_to(qapp, Theme.LIGHT)
    ss = qapp.styleSheet()
    assert isinstance(ss, str) and len(ss) > 0, "Light stylesheet must not be empty"


def test_stylesheet_strings_non_empty():
    """Both STYLESHEET_DARK and STYLESHEET_LIGHT class constants must be
    > 1 000 characters."""
    from agent_uia.ui.theme import ThemeManager

    assert len(ThemeManager.STYLESHEET_DARK) > 1000, (
        f"STYLESHEET_DARK too short ({len(ThemeManager.STYLESHEET_DARK)} chars)"
    )
    assert len(ThemeManager.STYLESHEET_LIGHT) > 1000, (
        f"STYLESHEET_LIGHT too short ({len(ThemeManager.STYLESHEET_LIGHT)} chars)"
    )
