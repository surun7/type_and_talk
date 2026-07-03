# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Spotlight-like floating chat window for TNT.

Frameless, translucent, always-on-top. Fades in on show, fades out on hide.
Esc hides; focus-out hides if no task is running.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)  # fmt: skip
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QShowEvent,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "FloatingWindow",
]

# ── styling ──────────────────────────────────────────────────────────────────

_WINDOW_STYLE = """
QWidget#floatingBody {
    background: #1E1E1E;
    border-radius: 12px;
}
"""

_INPUT_STYLE = """
QLineEdit {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    selection-background-color: #264F78;
}
QLineEdit:focus {
    border: 1px solid #0078D4;
}
QLineEdit::placeholder {
    color: #666666;
}
"""

_RESPONSE_STYLE = """
QTextEdit {
    background: transparent;
    color: #E0E0E0;
    border: none;
    font-size: 13px;
    selection-background-color: #264F78;
}
QTextEdit[readOnly="true"] {
    background: transparent;
}
"""

_STATUS_STYLE = "color: #888888; font-size: 11px;"

_SEPARATOR_STYLE = "color: #3D3D3D;"

_MIC_BUTTON_STYLE = (
    "QPushButton {{"
    "    background: {bg};"
    "    color: {fg};"
    "    border: 1px solid {border};"
    "    border-radius: 6px;"
    "    padding: 4px 8px;"
    "    font-size: 16px;"
    "    min-width: 32px;"
    "    min-height: 28px;"
    "}}"
    "QPushButton:hover {{"
    "    border: 1px solid #0078D4;"
    "}}"
)


class FloatingWindow(QWidget):
    """Spotlight-like floating input/response window.

    Signals:
        submit_requested: Emitted when the user presses Enter (no Shift)
            with the input text.
        mic_clicked: Emitted when the microphone button is clicked.
        recording_cancelled: Emitted when ESC is pressed during recording.
    """

    submit_requested = Signal(str)
    mic_clicked = Signal()
    recording_cancelled = Signal()

    # Pre-warming support: when True the window is fully constructed but hidden.
    _pre_warmed = False

    def __init__(self, app_controller: AppController) -> None:
        super().__init__()
        self._controller = app_controller
        self._task_running = False
        self._hide_policy = "on_success"  # updated by controller
        self._recording_active = False
        self._mic_state = "IDLE"

        # ── window flags ────────────────────────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # no taskbar entry
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)

        # ── size / position ─────────────────────────────────────────────
        self.resize(720, 220)

        # ── shadow ──────────────────────────────────────────────────────
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        # ── body widget (solid background for the rounded rect) ────────
        self._body = QWidget()
        self._body.setObjectName("floatingBody")
        self._body.setStyleSheet(_WINDOW_STYLE)

        # ── layout inside body ──────────────────────────────────────────
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(16, 12, 16, 12)
        body_layout.setSpacing(8)

        # Status bar.
        self._status = QLabel("Ready")
        self._status.setStyleSheet(_STATUS_STYLE)
        self._status.setFixedHeight(20)
        body_layout.addWidget(self._status)

        # Input row (mic button + input field).
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._mic_button = QPushButton("🎤")
        self._mic_button.setStyleSheet(
            _MIC_BUTTON_STYLE.format(
                bg="#2D2D2D", fg="#E0E0E0", border="#3D3D3D"
            )
        )
        self._mic_button.setToolTip("Click to start voice input")
        self._mic_button.setCursor(Qt.PointingHandCursor)
        self._mic_button.clicked.connect(self._on_mic_clicked)
        input_row.addWidget(self._mic_button)

        self._input = QLineEdit()
        self._input.setStyleSheet(_INPUT_STYLE)
        self._input.setPlaceholderText(
            "Type or speak — Ctrl+Shift+Space to toggle · Enter to send "
            "· Shift+Enter for newline"
        )
        self._input.returnPressed.connect(self._on_enter_pressed)
        input_row.addWidget(self._input)

        body_layout.addLayout(input_row)

        # Response area.
        self._response = QTextEdit()
        self._response.setStyleSheet(_RESPONSE_STYLE)
        self._response.setReadOnly(True)
        self._response.setMaximumHeight(240)
        self._response.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._response.hide()
        body_layout.addWidget(self._response)

        # ── outer layout wraps the body ─────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._body)

        # ── keyboard ────────────────────────────────────────────────────
        self.setFocusPolicy(Qt.StrongFocus)

        # ── fade animation ──────────────────────────────────────────────
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.setDuration(150)

        # ── pulse timer for recording animation ─────────────────────────
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(500)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)
        self._pulse_opacity_on = True

        self._pulse_opacity_effect = QGraphicsOpacityEffect()
        self._pulse_opacity_effect.setOpacity(1.0)
        self._mic_button.setGraphicsEffect(self._pulse_opacity_effect)

    # ── public API ───────────────────────────────────────────────────────────

    def set_status(self, text: str) -> None:
        """Update the status bar text."""
        self._status.setText(text)

    def set_ptt_status(self, text: str) -> None:
        """Show PTT/voice status in the status bar."""
        self._status.setText(text)

    def set_mic_state(self, state: str, progress: str = "") -> None:
        """Update the mic button appearance.

        Args:
            state: One of IDLE, RECORDING, TRANSCRIBING, MODEL_DOWNLOADING,
                   MODEL_NOT_READY.
            progress: Optional progress text to overlay (e.g. "47%").
        """
        self._mic_state = state

        if state == "IDLE":
            self._mic_button.setText("🎤")
            self._mic_button.setStyleSheet(
                _MIC_BUTTON_STYLE.format(
                    bg="#2D2D2D", fg="#E0E0E0", border="#3D3D3D"
                )
            )
            self._mic_button.setToolTip("Click to start voice input")
            self._stop_pulse()

        elif state == "RECORDING":
            self._mic_button.setText("🔴")
            self._mic_button.setStyleSheet(
                _MIC_BUTTON_STYLE.format(
                    bg="#3D2020", fg="#FF4444", border="#3D3D3D"
                )
            )
            self._mic_button.setToolTip("Recording... click to stop")
            self._start_pulse()

        elif state == "TRANSCRIBING":
            self._mic_button.setText("⏳")
            self._mic_button.setStyleSheet(
                _MIC_BUTTON_STYLE.format(
                    bg="#3D3520", fg="#FFD700", border="#3D3D3D"
                )
            )
            self._mic_button.setToolTip("Transcribing...")
            self._stop_pulse()

        elif state == "MODEL_DOWNLOADING":
            text = "⬇"
            if progress:
                text = f"⬇ {progress}"
            self._mic_button.setText(text)
            self._mic_button.setStyleSheet(
                _MIC_BUTTON_STYLE.format(
                    bg="#20283D", fg="#4A9EFF", border="#3D3D3D"
                )
            )
            self._mic_button.setToolTip(f"Downloading model... {progress}")
            self._stop_pulse()

        elif state == "MODEL_NOT_READY":
            self._mic_button.setText("⚠")
            self._mic_button.setStyleSheet(
                _MIC_BUTTON_STYLE.format(
                    bg="#2D2D2D", fg="#888888", border="#3D3D3D"
                )
            )
            self._mic_button.setToolTip("Voice not ready — click to download")
            self._stop_pulse()

    def show_model_progress(self, percent: float) -> None:
        """Update the mic button to show download progress.

        Updates both the button appearance and the status bar.
        """
        progress_str = f"{int(percent)}%"
        self.set_mic_state("MODEL_DOWNLOADING", progress_str)
        self.set_ptt_status(f"Voice: downloading {progress_str}")

    def set_recording_active(self, active: bool) -> None:
        """Set whether recording is currently active.

        When True, pressing ESC will cancel recording and emit
        recording_cancelled.
        """
        self._recording_active = active

    def set_mic_visible(self, visible: bool) -> None:
        """Show or hide the microphone button."""
        self._mic_button.setVisible(visible)

    def append_tool_event(self, text: str) -> None:
        """Append a dimmed tool-call line to the response area."""
        self._response.show()
        cursor = self._response.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(
            f'<p style="color:#888888; margin:0;">{text}</p>'
        )
        self._scroll_to_end()

    def set_final_answer(self, text: str) -> None:
        """Append the final answer, separated by a horizontal rule."""
        self._response.show()
        cursor = self._response.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('<hr style="border:0; border-top:1px solid #3D3D3D;">')
        cursor.insertHtml(
            f'<p style="color:#E0E0E0; margin:4px 0;">{text}</p>'
        )
        self._scroll_to_end()

    def set_task_running(self, running: bool) -> None:
        """Track whether a Planner task is in flight (affects focus-out)."""
        self._task_running = running

    def clear_input(self) -> None:
        """Clear the input field."""
        self._input.clear()

    def clear_response(self) -> None:
        """Clear the response area."""
        self._response.clear()
        self._response.hide()

    # ── pre-warming ────────────────────────────────────────────────────────────

    def set_pre_warmed(self, ready: bool) -> None:
        """Mark this window as pre-warmed (constructed but hidden).

        When ``True`` the window is already fully built and the first
        ``show()`` call will skip the initial construction cost.  The
        existing show/hide fade logic handles visibility normally.
        """
        self._pre_warmed = ready

    # ── show / hide with fade ────────────────────────────────────────────────

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 — Qt override
        """Fade in on show."""
        super().showEvent(event)
        self._center_on_screen()
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._input.setFocus()

    def hide_with_fade(self) -> None:
        """Fade out, then hide."""
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._on_fade_out_finished, Qt.UniqueConnection)
        self._fade.start()

    def _on_fade_out_finished(self) -> None:
        self.hide()

    # ── event overrides ─────────────────────────────────────────────────

    def closeEvent(self, event):  # noqa: N802 — Qt override
        """Do not close — just hide."""
        self._controller.hide_floating_window()
        event.ignore()

    def focusOutEvent(self, event):  # noqa: N802 — Qt override
        """Hide on focus loss unless a task is running."""
        super().focusOutEvent(event)
        if not self._task_running:
            self._controller.hide_floating_window()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Esc → hide or cancel recording."""
        if event.key() == Qt.Key_Escape:
            if self._recording_active:
                self._recording_active = False
                self._stop_pulse()
                self.recording_cancelled.emit()
            self._controller.hide_floating_window()
        else:
            super().keyPressEvent(event)

    # ── internal ─────────────────────────────────────────────────────────────

    def _on_enter_pressed(self) -> None:
        text = self._input.text().strip()
        if text:
            self.submit_requested.emit(text)

    def _on_mic_clicked(self) -> None:
        self.mic_clicked.emit()

    def _on_pulse_tick(self) -> None:
        """Toggle mic button opacity for recording pulse effect."""
        self._pulse_opacity_on = not self._pulse_opacity_on
        opacity = 0.5 if self._pulse_opacity_on else 1.0
        self._pulse_opacity_effect.setOpacity(opacity)

    def _start_pulse(self) -> None:
        """Start the recording pulse animation."""
        self._pulse_opacity_on = True
        self._pulse_opacity_effect.setOpacity(1.0)
        self._pulse_timer.start()

    def _stop_pulse(self) -> None:
        """Stop the recording pulse animation."""
        self._pulse_timer.stop()
        self._pulse_opacity_effect.setOpacity(1.0)

    def _center_on_screen(self) -> None:
        """Position horizontally centered, ~30% from top of primary screen."""
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + int(geo.height() * 0.3)
        self.move(x, y)

    def _scroll_to_end(self) -> None:
        scrollbar = self._response.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())
