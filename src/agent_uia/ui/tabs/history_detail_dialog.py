# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Modal dialog showing full detail for a single history entry.

Used by ``HistoryTab`` when the user double-clicks a row.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "HistoryDetailDialog",
]

# ── styling ──────────────────────────────────────────────────────────────────

_DIALOG_STYLE = """
QDialog#detailBody {
    background: #1E1E1E;
    border-radius: 12px;
}
QPushButton#btnClose {
    background: #3D3D3D;
    color: #E0E0E0;
    border: none;
    border-radius: 6px;
    padding: 8px 24px;
    font-size: 13px;
    min-width: 100px;
}
QPushButton#btnClose:hover {
    background: #555555;
}
"""

_LABEL_STYLE = "color: #888888; font-size: 12px;"
_VALUE_STYLE = "color: #E0E0E0; font-size: 13px;"
_SECTION_STYLE = "color: #CCCCCC; font-size: 14px; font-weight: bold;"
_MONO_STYLE = (
    "color: #E0E0E0; font-size: 12px; font-family: Consolas, monospace; "
    "background: #2D2D2D; border-radius: 4px; padding: 8px;"
)


class HistoryDetailDialog(QDialog):
    """Modal dialog displaying the full detail of one history entry.

    All fields are read-only.  The dialog is dark-themed and matches the
    overall TNT visual style.
    """

    def __init__(
        self,
        *,
        task_id: str,
        timestamp: str,
        user_text: str,
        final_message: str,
        steps_taken: int,
        cost_usd: str,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the detail dialog.

        Args:
            task_id: Short unique identifier for the task.
            timestamp: Human-readable timestamp string.
            user_text: The full user instruction text.
            final_message: The full final response message.
            steps_taken: Number of steps executed.
            cost_usd: Estimated cost in USD (as a string, e.g. ``"0.0123"``).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("TNT — Task Detail")
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(True)
        self.setFixedSize(620, 520)

        # ── body ──────────────────────────────────────────────────────────
        body = QWidget()
        body.setObjectName("detailBody")
        body.setStyleSheet(_DIALOG_STYLE)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        # Title.
        title = QLabel("Task Detail")
        title.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # ── Task ID ───────────────────────────────────────────────────────
        layout.addWidget(QLabel("Task ID"))
        id_val = QLabel(task_id)
        id_val.setStyleSheet(_VALUE_STYLE)
        layout.addWidget(id_val)

        # ── Timestamp ─────────────────────────────────────────────────────
        layout.addWidget(QLabel("Timestamp"))
        ts_val = QLabel(timestamp)
        ts_val.setStyleSheet(_VALUE_STYLE)
        layout.addWidget(ts_val)

        # ── User Text ─────────────────────────────────────────────────────
        layout.addWidget(QLabel("User Text"))
        user_val = QLabel(user_text)
        user_val.setStyleSheet(_MONO_STYLE)
        user_val.setWordWrap(True)
        user_val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        layout.addWidget(user_val)

        # ── Final Message ─────────────────────────────────────────────────
        layout.addWidget(QLabel("Final Response"))
        msg_val = QLabel(final_message)
        msg_val.setStyleSheet(_MONO_STYLE)
        msg_val.setWordWrap(True)
        msg_val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        layout.addWidget(msg_val)

        # ── Steps / Cost row ──────────────────────────────────────────────
        meta_row = QHBoxLayout()
        meta_row.setSpacing(24)

        steps_label = QLabel(f"Steps Taken:  {steps_taken}")
        steps_label.setStyleSheet(_VALUE_STYLE)
        meta_row.addWidget(steps_label)

        cost_label = QLabel(f"Cost (USD):  ${cost_usd}")
        cost_label.setStyleSheet(_VALUE_STYLE)
        meta_row.addWidget(cost_label)

        meta_row.addStretch()
        layout.addLayout(meta_row)

        # ── Spacer ────────────────────────────────────────────────────────
        layout.addStretch(1)

        # ── Close button ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("btnClose")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # ── Outer layout ──────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)
