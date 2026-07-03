# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Home tab — the default landing view for the TNT main window.

Provides a hero card, quick-input box, recent-activity preview, quick-action
buttons, and a status footer.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from agent_uia.ui.theme import Theme, ThemeManager

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "HomeTab",
]

# ── styling ──────────────────────────────────────────────────────────────────

_HERO_CARD_STYLE = """
QFrame#hero_card {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1E2A3A, stop:1 #252526);
    border: 1px solid #3B8EEA40;
    border-radius: 8px;
    padding: 24px;
}
"""

_CARD_STYLE = """
QFrame#card {
    background: #2D2D30;
    border: 1px solid #3C3C3C;
    border-radius: 8px;
    padding: 16px;
}
"""

_INPUT_STYLE = """
QLineEdit {
    background: #2D2D2D;
    color: #E8E8E8;
    border: 1px solid #3C3C3C;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 13px;
    selection-background-color: #264F78;
}
QLineEdit:focus {
    border: 1px solid #3B8EEA;
}
QLineEdit::placeholder {
    color: #5A5A5A;
}
"""

_ACTION_BUTTON_STYLE = """
QPushButton {
    background: #2D2D30;
    color: #E8E8E8;
    border: 1px solid #3C3C3C;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
}
QPushButton:hover {
    background: #383838;
    border: 1px solid #3B8EEA;
}
"""

_FOOTER_STYLE = """
QFrame#footer {
    background: #252526;
    border-top: 1px solid #3C3C3C;
    padding: 8px 16px;
}
QLabel {
    color: #5A5A5A;
    font-size: 10px;
}
"""

_LINK_STYLE = """
QPushButton#link {
    background: transparent;
    color: #3B8EEA;
    border: none;
    text-decoration: underline;
    padding: 2px 4px;
    font-size: 12px;
}
QPushButton#link:hover {
    color: #5BA0F0;
}
"""

_STATUS_FOOTER_LABEL = "color: #5A5A5A; font-size: 10px; padding: 0 4px;"

_HISTORY_ENTRY_STYLE = """
QFrame#history_entry {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 6px 8px;
}
QFrame#history_entry:hover {
    background: #383838;
}
"""


class HomeTab(QWidget):
    """Home tab — the default landing view.

    Shows a hero card, quick input field, recent activity, quick-action
    buttons, and a status footer.
    """

    def __init__(self, app_controller: AppController, parent: QWidget | None = None) -> None:
        """Initialise the Home tab.

        Args:
            app_controller: The application controller for running tasks.
            parent:         Optional parent widget.
        """
        super().__init__(parent)
        self._controller = app_controller

        # ── root layout ────────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 0)
        outer.setSpacing(16)

        # ═══════════════════════════════════════════════════════════════════════
        #  Hero card
        # ═══════════════════════════════════════════════════════════════════════
        hero = QFrame()
        hero.setObjectName("hero_card")
        hero.setStyleSheet(_HERO_CARD_STYLE)
        hero.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 20, 24, 20)
        hero_layout.setSpacing(4)

        title_label = QLabel("Type and Talk")
        title_label.setStyleSheet(
            "color: #FFFFFF; font-size: 24px; font-weight: bold;"
        )
        hero_layout.addWidget(title_label)

        version_row = QHBoxLayout()
        version_row.setSpacing(8)

        version_label = QLabel("v0.1.0")
        version_label.setStyleSheet(
            "color: #3B8EEA; font-size: 13px; font-weight: bold;"
        )
        version_row.addWidget(version_label)

        tagline_label = QLabel(
            "Your AI-powered Windows desktop agent. "
            "Ask me to open apps, search the web, or automate tasks."
        )
        tagline_label.setStyleSheet(
            "color: #A0A0A0; font-size: 13px;"
        )
        tagline_label.setWordWrap(True)
        version_row.addWidget(tagline_label, 1)

        hero_layout.addLayout(version_row)

        outer.addWidget(hero)

        # ═══════════════════════════════════════════════════════════════════════
        #  Quick input
        # ═══════════════════════════════════════════════════════════════════════
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Type a task and press Enter...  (Ctrl+Shift+Space for floating window)"
        )
        self._input.setStyleSheet(_INPUT_STYLE)
        self._input.setFixedHeight(40)
        self._input.returnPressed.connect(self._on_submit)
        outer.addWidget(self._input)

        # ═══════════════════════════════════════════════════════════════════════
        #  Recent activity card
        # ═══════════════════════════════════════════════════════════════════════
        recent_card = QFrame()
        recent_card.setObjectName("card")
        recent_card.setStyleSheet(_CARD_STYLE)
        recent_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(16, 12, 16, 12)
        recent_layout.setSpacing(8)

        recent_header = QLabel("Recent Activity")
        recent_header.setStyleSheet(
            "color: #E8E8E8; font-size: 14px; font-weight: bold;"
        )
        recent_layout.addWidget(recent_header)

        self._recent_container = QVBoxLayout()
        self._recent_container.setSpacing(4)
        recent_layout.addLayout(self._recent_container)

        # "View all" link
        view_all_btn = QPushButton("View all in History →")
        view_all_btn.setObjectName("link")
        view_all_btn.setStyleSheet(_LINK_STYLE)
        view_all_btn.setCursor(Qt.PointingHandCursor)
        view_all_btn.clicked.connect(self._on_view_all_history)
        recent_layout.addWidget(view_all_btn, alignment=Qt.AlignRight)

        outer.addWidget(recent_card)

        # ═══════════════════════════════════════════════════════════════════════
        #  Quick-action buttons
        # ═══════════════════════════════════════════════════════════════════════
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.setContentsMargins(0, 0, 0, 0)

        quick_actions = [
            ("Open Calculator", "calc"),
            ("Open Notepad", "notepad"),
            ("What's my IP", "ip"),
        ]

        for label_text, action_id in quick_actions:
            btn = QPushButton(label_text)
            btn.setStyleSheet(_ACTION_BUTTON_STYLE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("action_id", action_id)
            btn.clicked.connect(self._on_quick_action)
            action_row.addWidget(btn)

        action_row.addStretch()
        outer.addLayout(action_row)

        # ═══════════════════════════════════════════════════════════════════════
        #  Spacer (pushes footer down)
        # ═══════════════════════════════════════════════════════════════════════
        outer.addStretch(1)

        # ═══════════════════════════════════════════════════════════════════════
        #  Status footer
        # ═══════════════════════════════════════════════════════════════════════
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setStyleSheet(_FOOTER_STYLE)
        footer.setFixedHeight(32)
        footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 0, 16, 0)
        footer_layout.setSpacing(16)

        self._footer_agent = QLabel("Agent: Idle")
        self._footer_agent.setStyleSheet(_STATUS_FOOTER_LABEL)
        footer_layout.addWidget(self._footer_agent)

        self._footer_model = QLabel("Model: deepseek-chat")
        self._footer_model.setStyleSheet(_STATUS_FOOTER_LABEL)
        footer_layout.addWidget(self._footer_model)

        self._footer_asr = QLabel("ASR: base")
        self._footer_asr.setStyleSheet(_STATUS_FOOTER_LABEL)
        footer_layout.addWidget(self._footer_asr)

        self._footer_theme = QLabel("Theme: dark")
        self._footer_theme.setStyleSheet(_STATUS_FOOTER_LABEL)
        footer_layout.addWidget(self._footer_theme)

        footer_layout.addStretch(1)

        outer.addWidget(footer)

        # ── populate recent activity on construction ─────────────────────────
        self._refresh_recent_activity()

    # ── public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload recent activity and footer status."""
        self._refresh_recent_activity()
        self._refresh_footer()

    # ── internal: recent activity ──────────────────────────────────────────────

    def _refresh_recent_activity(self) -> None:
        """Load the last 3 history entries and display them."""
        # Clear existing entries.
        self._clear_layout(self._recent_container)

        entries = self._load_recent_entries(limit=3)

        if not entries:
            placeholder = QLabel("No recent activity. Try asking something!")
            placeholder.setStyleSheet(
                "color: #5A5A5A; font-size: 12px; padding: 8px;"
            )
            self._recent_container.addWidget(placeholder)
            return

        for entry in entries:
            entry_frame = QFrame()
            entry_frame.setObjectName("history_entry")
            entry_frame.setStyleSheet(_HISTORY_ENTRY_STYLE)
            entry_frame.setCursor(Qt.PointingHandCursor)
            entry_frame.mousePressEvent = lambda _event, e=entry: self._on_history_click(  # type: ignore[assignment]
                e
            )

            entry_layout = QHBoxLayout(entry_frame)
            entry_layout.setContentsMargins(0, 0, 0, 0)
            entry_layout.setSpacing(8)

            # Timestamp + status badge.
            ts = entry.get("ts", entry.get("timestamp", 0))
            ts_str = self._format_ts(ts)
            ts_label = QLabel(ts_str)
            ts_label.setStyleSheet("color: #888888; font-size: 11px; min-width: 90px;")
            entry_layout.addWidget(ts_label)

            status = entry.get("status", "unknown")
            status_label = QLabel(status)
            status_color = {
                "success": "#3ECF8E",
                "failed": "#E85A4F",
                "blocked": "#F0A830",
                "budget": "#F0A830",
                "max_steps": "#888888",
            }.get(status, "#888888")
            status_label.setStyleSheet(
                f"color: {status_color}; font-size: 11px; font-weight: bold; "
                f"min-width: 60px;"
            )
            entry_layout.addWidget(status_label)

            # Preview text.
            text = entry.get("user_text", "")
            preview = text[:80] + ("..." if len(text) > 80 else "")
            text_label = QLabel(preview)
            text_label.setStyleSheet("color: #C8C8C8; font-size: 12px;")
            text_label.setWordWrap(False)
            entry_layout.addWidget(text_label, 1)

            self._recent_container.addWidget(entry_frame)

    def _load_recent_entries(self, limit: int = 3) -> list[dict[str, Any]]:
        """Read the last *limit* entries from the history JSONL file.

        Returns:
            A list of dicts, newest first, at most *limit* items.
        """
        try:
            history_path = self._get_history_path()
            if not history_path or not history_path.exists():
                return []

            lines = history_path.read_text(encoding="utf-8").strip().splitlines()
            entries: list[dict[str, Any]] = []
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(entries) >= limit:
                    break
            return entries
        except (OSError, json.JSONDecodeError):
            return []

    def _get_history_path(self) -> Path | None:
        """Return the path to the history JSONL file.

        Uses the controller's internal ``_history_path`` if available,
        otherwise falls back to the default location.
        """
        try:
            return self._controller._history_path  # type: ignore[union-attr]
        except AttributeError:
            from agent_uia.paths import get_logs_dir

            path = get_logs_dir() / "history.jsonl"
            return path if path.exists() else None

    def _on_history_click(self, entry: dict[str, Any]) -> None:
        """Navigate to the History tab when a recent entry is clicked."""
        # Find the parent MainContent QStackedWidget and navigate.
        parent = self.parent()
        if parent is not None and hasattr(parent, "navigate_to"):
            parent.navigate_to("history")  # type: ignore[union-attr]

    def _on_view_all_history(self) -> None:
        """Navigate to the full History tab."""
        parent = self.parent()
        if parent is not None and hasattr(parent, "navigate_to"):
            parent.navigate_to("history")  # type: ignore[union-attr]

    # ── internal: quick actions ────────────────────────────────────────────────

    def _on_quick_action(self) -> None:
        """Run a hardcoded quick-action task."""
        btn = self.sender()
        if btn is None:
            return
        action_id = btn.property("action_id")

        task_map = {
            "calc": "Open the calculator app",
            "notepad": "Open Notepad",
            "ip": "What is my public IP address?",
        }
        text = task_map.get(action_id, "")
        if text:
            asyncio.create_task(self._controller.run_task(text))

    # ── internal: submit ───────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        """Submit the quick-input text to the controller."""
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        asyncio.create_task(self._controller.run_task(text))

    # ── internal: footer ───────────────────────────────────────────────────────

    def _refresh_footer(self) -> None:
        """Update the status footer labels from the current config and state."""
        config = self._controller.config

        paused = self._controller.paused
        agent_state = "Paused" if paused else "Idle"
        self._footer_agent.setText(f"Agent: {agent_state}")

        # Model info is read from environment by the controller — best-effort.
        model = getattr(self._controller, "_llm_config", None)
        model_name = model.model if model else "deepseek-chat"
        self._footer_model.setText(f"Model: {model_name}")

        self._footer_asr.setText(f"ASR: {config.asr_model}")
        self._footer_theme.setText(f"Theme: {config.theme}")

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_ts(ts: float | int | str) -> str:
        """Format a UNIX timestamp to a short ``HH:MM`` or ``YYYY-MM-DD`` string.
        
        Recent entries (today) show the time only; older entries show the date.
        """
        import time

        try:
            ts_float = float(ts)
        except (TypeError, ValueError):
            return str(ts)

        now = time.time()
        is_today = time.strftime("%Y-%m-%d", time.localtime(ts_float)) == time.strftime(
            "%Y-%m-%d", time.localtime(now)
        )
        fmt = "%H:%M" if is_today else "%m-%d"
        return time.strftime(fmt, time.localtime(ts_float))

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        """Remove all items from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
