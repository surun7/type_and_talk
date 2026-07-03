# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Centralised styling for the TNT UI.

Provides the ``Theme`` enum (dark / light) and ``ThemeManager`` for applying
a full-application QSS stylesheet or retrieving per-component style snippets.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from PySide6.QtWidgets import QApplication

__all__ = [
    "Theme",
    "ThemeManager",
]


class Theme(Enum):
    """Application colour theme."""

    DARK = "dark"
    LIGHT = "light"


# ═══════════════════════════════════════════════════════════════════════════════
#  Design tokens
# ═══════════════════════════════════════════════════════════════════════════════

_DARK_TOKENS: dict[str, str] = {
    "bg_window": "#1E1E1E",
    "bg_panel": "#252526",
    "bg_card": "#2D2D30",
    "bg_input": "#2D2D2D",
    "bg_hover": "#383838",
    "bg_selected": "#37373D",
    "text_primary": "#E8E8E8",
    "text_secondary": "#A0A0A0",
    "text_disabled": "#5A5A5A",
    "accent": "#3B8EEA",
    "accent_hover": "#5BA0F0",
    "accent_pressed": "#2A6FBF",
    "success": "#3ECF8E",
    "warning": "#F0A830",
    "error": "#E85A4F",
    "border": "#3C3C3C",
    "border_focus": "#3B8EEA",
    "separator": "#2D2D30",
    "font_family": "Segoe UI",
    "font_size": "9pt",
    "radius_card": "8px",
    "radius_input": "6px",
    "radius_button": "6px",
}

_LIGHT_TOKENS: dict[str, str] = {
    "bg_window": "#F3F3F3",
    "bg_panel": "#FFFFFF",
    "bg_card": "#FAFAFA",
    "bg_input": "#FFFFFF",
    "bg_hover": "#E8E8E8",
    "bg_selected": "#E0E0E0",
    "text_primary": "#1A1A1A",
    "text_secondary": "#666666",
    "text_disabled": "#AAAAAA",
    "accent": "#3B8EEA",
    "accent_hover": "#5BA0F0",
    "accent_pressed": "#2A6FBF",
    "success": "#2EAB74",
    "warning": "#D08A20",
    "error": "#D94A3F",
    "border": "#D0D0D0",
    "border_focus": "#3B8EEA",
    "separator": "#E0E0E0",
    "font_family": "Segoe UI",
    "font_size": "9pt",
    "radius_card": "8px",
    "radius_input": "6px",
    "radius_button": "6px",
}


def _resolve(tokens: dict[str, str], key: str) -> str:
    """Return a token value, asserting the key exists."""
    val = tokens.get(key)
    if val is None:
        msg = f"Unknown design token: {key!r}"
        raise KeyError(msg)
    return val


def _build_stylesheet(tokens: dict[str, str]) -> str:
    """Build the full-application QSS stylesheet from design tokens."""
    t = tokens  # shorthand
    return f"""
        /* ── Window / Root ───────────────────────────────────── */
        QMainWindow, QDialog, QWidget#mainWindow {{
            background: {t["bg_window"]};
            color: {t["text_primary"]};
            font-family: {t["font_family"]};
            font-size: {t["font_size"]};
        }}

        /* ── Panels & Cards ──────────────────────────────────── */
        QFrame#panel {{
            background: {t["bg_panel"]};
            border: 1px solid {t["border"]};
            border-radius: {t["radius_card"]};
        }}

        QFrame#card {{
            background: {t["bg_card"]};
            border: 1px solid {t["border"]};
            border-radius: {t["radius_card"]};
            padding: 12px;
        }}

        /* ── Labels ──────────────────────────────────────────── */
        QLabel {{
            color: {t["text_primary"]};
            background: transparent;
            border: none;
        }}

        QLabel#secondary {{
            color: {t["text_secondary"]};
        }}

        QLabel#hero {{
            font-size: 22px;
            font-weight: bold;
            color: {t["text_primary"]};
        }}

        QLabel#tagline {{
            font-size: 12px;
            color: {t["text_secondary"]};
        }}

        /* ── Buttons (generic) ──────────────────────────────── */
        QPushButton {{
            background: {t["bg_card"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border"]};
            border-radius: {t["radius_button"]};
            padding: 6px 16px;
            font-size: {t["font_size"]};
            min-height: 28px;
        }}

        QPushButton:hover {{
            background: {t["bg_hover"]};
            border: 1px solid {t["border_focus"]};
        }}

        QPushButton:pressed {{
            background: {t["bg_selected"]};
        }}

        QPushButton:disabled {{
            color: {t["text_disabled"]};
            background: {t["bg_panel"]};
            border: 1px solid {t["border"]};
        }}

        QPushButton#primary {{
            background: {t["accent"]};
            color: #FFFFFF;
            border: none;
            font-weight: bold;
        }}

        QPushButton#primary:hover {{
            background: {t["accent_hover"]};
        }}

        QPushButton#primary:pressed {{
            background: {t["accent_pressed"]};
        }}

        QPushButton#success {{
            background: {t["success"]};
            color: #FFFFFF;
            border: none;
        }}

        QPushButton#warning {{
            background: {t["warning"]};
            color: #FFFFFF;
            border: none;
        }}

        QPushButton#error {{
            background: {t["error"]};
            color: #FFFFFF;
            border: none;
        }}

        QPushButton#link {{
            background: transparent;
            color: {t["accent"]};
            border: none;
            text-decoration: underline;
            padding: 2px 4px;
        }}

        QPushButton#link:hover {{
            color: {t["accent_hover"]};
        }}

        /* ── ToolButtons (sidebar) ──────────────────────────── */
        QToolButton {{
            background: transparent;
            color: {t["text_secondary"]};
            border: none;
            border-radius: {t["radius_button"]};
            padding: 8px 12px;
            text-align: left;
            font-size: {t["font_size"]};
        }}

        QToolButton:hover {{
            background: {t["bg_hover"]};
            color: {t["text_primary"]};
        }}

        QToolButton:checked {{
            background: {t["accent"]}30;
            color: {t["accent"]};
            font-weight: bold;
        }}

        /* ── Line Edit / Input ──────────────────────────────── */
        QLineEdit {{
            background: {t["bg_input"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border"]};
            border-radius: {t["radius_input"]};
            padding: 6px 10px;
            font-size: {t["font_size"]};
            selection-background-color: #264F78;
        }}

        QLineEdit:focus {{
            border: 1px solid {t["border_focus"]};
        }}

        QLineEdit::placeholder {{
            color: {t["text_disabled"]};
        }}

        /* ── Text Edit / Read-only ───────────────────────────── */
        QTextEdit {{
            background: transparent;
            color: {t["text_primary"]};
            border: none;
            font-size: {t["font_size"]};
            selection-background-color: #264F78;
        }}

        QTextEdit[readOnly="true"] {{
            background: transparent;
        }}

        /* ── Scroll bars ─────────────────────────────────────── */
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0;
        }}

        QScrollBar::handle:vertical {{
            background: {t["border"]};
            border-radius: 4px;
            min-height: 30px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {t["text_disabled"]};
        }}

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 0;
        }}

        QScrollBar::handle:horizontal {{
            background: {t["border"]};
            border-radius: 4px;
            min-width: 30px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background: {t["text_disabled"]};
        }}

        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0;
        }}

        /* ── Separators ───────────────────────────────────────── */
        QFrame#separator {{
            background: {t["separator"]};
            border: none;
            max-height: 1px;
        }}

        /* ── QStackedWidget ───────────────────────────────────── */
        QStackedWidget {{
            background: transparent;
            border: none;
        }}

        /* ── Status bar ───────────────────────────────────────── */
        QLabel#status {{
            color: {t["text_secondary"]};
            font-size: 10px;
        }}
    """


# ── per-component style snippets ───────────────────────────────────────────────

_COMPONENT_STYLES: dict[str, dict[str, str]] = {
    "sidebar": {
        Theme.DARK.value: (
            "QFrame#sidebar {"
            "  background: #252526;"
            "  border-right: 1px solid #3C3C3C;"
            "}"
            "QLabel#wordmark {"
            "  color: #3B8EEA; font-size: 18px; font-weight: bold;"
            "  padding: 16px 12px 4px 12px;"
            "}"
            "QLabel#version {"
            "  color: #5A5A5A; font-size: 10px;"
            "  padding: 0px 12px 12px 12px;"
            "}"
        ),
        Theme.LIGHT.value: (
            "QFrame#sidebar {"
            "  background: #FFFFFF;"
            "  border-right: 1px solid #D0D0D0;"
            "}"
            "QLabel#wordmark {"
            "  color: #3B8EEA; font-size: 18px; font-weight: bold;"
            "  padding: 16px 12px 4px 12px;"
            "}"
            "QLabel#version {"
            "  color: #AAAAAA; font-size: 10px;"
            "  padding: 0px 12px 12px 12px;"
            "}"
        ),
    },
    "card": {
        Theme.DARK.value: (
            "QFrame#card {"
            "  background: #2D2D30;"
            "  border: 1px solid #3C3C3C;"
            "  border-radius: 8px;"
            "  padding: 16px;"
            "}"
        ),
        Theme.LIGHT.value: (
            "QFrame#card {"
            "  background: #FAFAFA;"
            "  border: 1px solid #D0D0D0;"
            "  border-radius: 8px;"
            "  padding: 16px;"
            "}"
        ),
    },
    "hero_card": {
        Theme.DARK.value: (
            "QFrame#hero_card {"
            "  background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            "    stop:0 #1E2A3A, stop:1 #252526);"
            "  border: 1px solid #3B8EEA40;"
            "  border-radius: 8px;"
            "  padding: 24px;"
            "}"
        ),
        Theme.LIGHT.value: (
            "QFrame#hero_card {"
            "  background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            "    stop:0 #E8F0FE, stop:1 #FFFFFF);"
            "  border: 1px solid #3B8EEA40;"
            "  border-radius: 8px;"
            "  padding: 24px;"
            "}"
        ),
    },
    "action_button": {
        Theme.DARK.value: (
            "QPushButton {"
            "  background: #2D2D30;"
            "  color: #E8E8E8;"
            "  border: 1px solid #3C3C3C;"
            "  border-radius: 6px;"
            "  padding: 8px 16px;"
            "  font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "  background: #383838;"
            "  border: 1px solid #3B8EEA;"
            "}"
        ),
        Theme.LIGHT.value: (
            "QPushButton {"
            "  background: #FAFAFA;"
            "  color: #1A1A1A;"
            "  border: 1px solid #D0D0D0;"
            "  border-radius: 6px;"
            "  padding: 8px 16px;"
            "  font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "  background: #E8E8E8;"
            "  border: 1px solid #3B8EEA;"
            "}"
        ),
    },
    "footer": {
        Theme.DARK.value: (
            "QFrame#footer {"
            "  background: #252526;"
            "  border-top: 1px solid #3C3C3C;"
            "  padding: 8px 16px;"
            "}"
            "QLabel { color: #5A5A5A; font-size: 10px; }"
        ),
        Theme.LIGHT.value: (
            "QFrame#footer {"
            "  background: #FFFFFF;"
            "  border-top: 1px solid #D0D0D0;"
            "  padding: 8px 16px;"
            "}"
            "QLabel { color: #AAAAAA; font-size: 10px; }"
        ),
    },
    "placeholder_card": {
        Theme.DARK.value: (
            "QFrame#placeholder_card {"
            "  background: #2D2D30;"
            "  border: 1px dashed #3C3C3C;"
            "  border-radius: 8px;"
            "  padding: 32px;"
            "}"
        ),
        Theme.LIGHT.value: (
            "QFrame#placeholder_card {"
            "  background: #FAFAFA;"
            "  border: 1px dashed #D0D0D0;"
            "  border-radius: 8px;"
            "  padding: 32px;"
            "}"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
#  ThemeManager
# ═══════════════════════════════════════════════════════════════════════════════


class ThemeManager:
    """Static methods for applying and retrieving theme styles.

    Usage::

        ThemeManager.apply_to(app, Theme.DARK)
        card_style = ThemeManager.get_component_style("card", Theme.DARK)
    """

    STYLESHEET_DARK: Final[str] = _build_stylesheet(_DARK_TOKENS)
    """Full-application QSS for the dark theme."""

    STYLESHEET_LIGHT: Final[str] = _build_stylesheet(_LIGHT_TOKENS)
    """Full-application QSS for the light theme."""

    # ── class-level cache ──────────────────────────────────────────────────────

    _token_cache: dict[Theme, dict[str, str]] = {
        Theme.DARK: dict(_DARK_TOKENS),
        Theme.LIGHT: dict(_LIGHT_TOKENS),
    }

    # ── public API ─────────────────────────────────────────────────────────────

    @staticmethod
    def apply_to(app: QApplication, theme: Theme) -> None:
        """Set the application-wide stylesheet for *theme*.

        Args:
            app:   The running ``QApplication`` instance.
            theme: The theme to apply (``Theme.DARK`` or ``Theme.LIGHT``).
        """
        sheet = (
            ThemeManager.STYLESHEET_DARK
            if theme == Theme.DARK
            else ThemeManager.STYLESHEET_LIGHT
        )
        app.setStyleSheet(sheet)

    @staticmethod
    def get_component_style(component: str, theme: Theme) -> str:
        """Return a per-component QSS snippet for the given theme.

        Args:
            component: Component name (e.g. ``"sidebar"``, ``"card"``,
                ``"action_button"``).
            theme:     The theme to retrieve.

        Returns:
            A QSS string suitable for ``widget.setStyleSheet()``.

        Raises:
            KeyError: If *component* is not registered.
        """
        theme_map = _COMPONENT_STYLES.get(component)
        if theme_map is None:
            msg = f"Unknown component: {component!r}"
            raise KeyError(msg)
        return theme_map[theme.value]

    @staticmethod
    def token(key: str, theme: Theme) -> str:
        """Return the value of a single design token.

        Args:
            key:   Token name (e.g. ``"bg_window"``, ``"accent"``).
            theme: The theme to query.

        Returns:
            The token value (e.g. ``"#1E1E1E"``).
        """
        tokens = ThemeManager._token_cache[theme]
        return _resolve(tokens, key)
