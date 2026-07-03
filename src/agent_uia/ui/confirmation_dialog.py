# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Modal confirmation dialog for sensitive actions.

Matches the FloatingWindow visual style (dark, rounded, frameless).
Supports offscreen auto-confirm via ``TNT_TEST_AUTO_CONFIRM`` env var.
"""

from __future__ import annotations

import os
from typing import Literal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPixmap,
)
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
    "ConfirmationDialog",
]

# ── styling ──────────────────────────────────────────────────────────────────

_DIALOG_STYLE = """
QDialog#confirmBody {
    background: #1E1E1E;
    border-radius: 12px;
}
QPushButton#btnYes {
    background: #0078D4;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: bold;
    min-width: 100px;
}
QPushButton#btnYes:hover {
    background: #106EBE;
}
QPushButton#btnNo {
    background: #3D3D3D;
    color: #E0E0E0;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    min-width: 100px;
}
QPushButton#btnNo:hover {
    background: #555555;
}
QPushButton#btnStop {
    background: transparent;
    color: #F44336;
    border: 1px solid #F44336;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    min-width: 100px;
}
QPushButton#btnStop:hover {
    background: #3D0000;
}
"""

_ACTION_LABEL_STYLE = "color: #E0E0E0; font-size: 16px; font-weight: bold;"
_TARGET_LABEL_STYLE = "color: #888888; font-size: 13px; font-family: Consolas, monospace;"
_RISK_LABEL_STYLE = "color: #CCCCCC; font-size: 12px;"
_TIMER_LABEL_STYLE = "color: #FFC107; font-size: 11px;"


def _make_warning_icon(size: int = 48) -> QPixmap:
    """Draw a warning triangle icon via QPainter."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Triangle.
    path = __import__("PySide6.QtGui", fromlist=["QPainterPath"]).QPainterPath()
    path.moveTo(size // 2, 4)
    path.lineTo(size - 4, size - 4)
    path.lineTo(4, size - 4)
    path.closeSubpath()

    painter.setBrush(QColor("#FFC107"))
    painter.setPen(Qt.NoPen)
    painter.drawPath(path)

    # Exclamation mark.
    painter.setPen(QColor("#1E1E1E"))
    font = QFont("Segoe UI", 24, QFont.Bold)
    painter.setFont(font)
    painter.drawText(
        pixmap.rect().adjusted(0, -2, 0, 0),
        Qt.AlignCenter,
        "!",
    )
    painter.end()
    return pixmap


class ConfirmationDialog(QDialog):
    """Modal dialog asking the user to confirm a sensitive action.

    Three outcomes: ``"yes"``, ``"no"``, ``"stop"``. On timeout (default 30s),
    returned as ``"timeout"``.

    Under offscreen mode, uses ``TNT_TEST_AUTO_CONFIRM`` env var:
    - ``"yes"`` → auto-clicks Yes after 50ms
    - anything else → auto-clicks No after 50ms
    """

    def __init__(
        self,
        action_type: str,
        target: str,
        risk_explanation: str,
        timeout_s: int = 30,
    ) -> None:
        super().__init__()
        self._result: Literal["yes", "no", "stop", "timeout"] = "no"
        self._timeout_s = timeout_s
        self._remaining = timeout_s

        # ── window flags ────────────────────────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(True)
        self.resize(500, 260)

        # ── center on parent or screen ──────────────────────────────────
        self.setWindowTitle("TNT — Confirmation Required")

        # ── body ────────────────────────────────────────────────────────
        body = QWidget()
        body.setObjectName("confirmBody")
        body.setStyleSheet(_DIALOG_STYLE)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        # Top row: icon + action type.
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        icon_label = QLabel()
        icon_label.setPixmap(_make_warning_icon(48))
        icon_label.setFixedSize(48, 48)
        top_row.addWidget(icon_label)

        action_label = QLabel(action_type)
        action_label.setStyleSheet(_ACTION_LABEL_STYLE)
        top_row.addWidget(action_label, 1)
        layout.addLayout(top_row)

        # Target (monospace).
        target_label = QLabel(target)
        target_label.setStyleSheet(_TARGET_LABEL_STYLE)
        target_label.setWordWrap(True)
        layout.addWidget(target_label)

        # Risk explanation.
        risk_label = QLabel(risk_explanation)
        risk_label.setStyleSheet(_RISK_LABEL_STYLE)
        risk_label.setWordWrap(True)
        risk_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        layout.addWidget(risk_label)

        # Timer.
        self._timer_label = QLabel(f"Auto-refusing in {self._remaining}s...")
        self._timer_label.setStyleSheet(_TIMER_LABEL_STYLE)
        layout.addWidget(self._timer_label)

        # Buttons.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_no = QPushButton("No, skip")
        self._btn_no.setObjectName("btnNo")
        self._btn_no.clicked.connect(lambda: self._done("no"))
        self._btn_no.setShortcut(Qt.Key_Escape)
        btn_row.addWidget(self._btn_no)

        btn_row.addStretch()

        self._btn_yes = QPushButton("Yes, do it")
        self._btn_yes.setObjectName("btnYes")
        self._btn_yes.setDefault(True)
        self._btn_yes.clicked.connect(lambda: self._done("yes"))
        btn_row.addWidget(self._btn_yes)

        self._btn_stop = QPushButton("Stop the whole task")
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.clicked.connect(lambda: self._done("stop"))
        btn_row.addWidget(self._btn_stop)

        layout.addLayout(btn_row)

        # Outer layout.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)

        # ── timer ─────────────────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

        # ── offscreen auto-confirm ────────────────────────────────────
        auto = os.environ.get("TNT_TEST_AUTO_CONFIRM", "").lower()
        if auto:
            QTimer.singleShot(50, lambda: self._done("yes" if auto == "yes" else "no"))

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def result(self) -> Literal["yes", "no", "stop", "timeout"]:
        """The user's choice after the dialog closes."""
        return self._result

    @staticmethod
    def ask(
        parent: QWidget | None,
        *,
        action_type: str,
        target: str,
        risk_explanation: str,
        timeout_s: int = 30,
    ) -> Literal["yes", "no", "stop", "timeout"]:
        """Static factory: create, show modal, return result.

        This is a synchronous blocking call (runs the Qt event loop
        internally via ``exec_``). Safe to call from any thread.
        """
        dialog = ConfirmationDialog(
            action_type=action_type,
            target=target,
            risk_explanation=risk_explanation,
            timeout_s=timeout_s,
        )
        dialog.exec_()
        return dialog._result

    # ── internal ─────────────────────────────────────────────────────────────

    def _done(self, value: Literal["yes", "no", "stop", "timeout"]) -> None:
        """Stop timer, store result, close dialog."""
        self._timer.stop()
        self._result = value
        self.accept()

    def _on_tick(self) -> None:
        """Decrement the countdown; auto-refuse when it hits zero."""
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self._result = "timeout"
            self.reject()
            return
        self._timer_label.setText(f"Auto-refusing in {self._remaining}s...")
