# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""First-launch onboarding dialog for voice-ASR model download.

Shown once when the app starts and no ASR model is installed.  The user
may choose to download a model now, or opt out and use text only.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "FirstRunDialog",
]

# ── styling ──────────────────────────────────────────────────────────────────

_DIALOG_STYLE = """
QDialog#firstRunBody {
    background: #1E1E1E;
    border-radius: 12px;
}
QPushButton#btnDownload {
    background: #0078D4;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 10px 28px;
    font-size: 14px;
    font-weight: bold;
    min-width: 140px;
}
QPushButton#btnDownload:hover {
    background: #106EBE;
}
QPushButton#btnTextOnly {
    background: #3D3D3D;
    color: #E0E0E0;
    border: none;
    border-radius: 6px;
    padding: 10px 28px;
    font-size: 14px;
    min-width: 140px;
}
QPushButton#btnTextOnly:hover {
    background: #555555;
}
QPushButton#btnQuit {
    background: transparent;
    color: #F44336;
    border: none;
    font-size: 11px;
    text-decoration: underline;
    padding: 4px 8px;
}
QPushButton#btnQuit:hover {
    color: #FF6659;
}
QRadioButton {
    color: #E0E0E0;
    font-size: 13px;
    spacing: 8px;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #555555;
    background: #2D2D2D;
}
QRadioButton::indicator:checked {
    border: 2px solid #0078D4;
    background: #0078D4;
}
QRadioButton::indicator:hover {
    border: 2px solid #888888;
}
QLineEdit#mirrorUrl {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    selection-background-color: #264F78;
}
QLineEdit#mirrorUrl:focus {
    border: 1px solid #0078D4;
}
QLineEdit#mirrorUrl::placeholder {
    color: #666666;
}
"""

_HERO_STYLE = "color: #E0E0E0; font-size: 15px;"
_BODY_STYLE = "color: #AAAAAA; font-size: 12px;"
_LABEL_STYLE = "color: #CCCCCC; font-size: 12px;"
_ESTIMATED_STYLE = "color: #888888; font-size: 11px; font-style: italic;"
_MIRROR_HINT_STYLE = "color: #666666; font-size: 10px;"
_SUBTITLE_STYLE = "color: #888888; font-size: 11px; margin-bottom: 4px;"

ModelSize = Literal["tiny", "base", "small"]


class FirstRunDialog(QDialog):
    """First-launch onboarding dialog for ASR model selection and download.

    Allows the user to pick a voice model size, optionally configure a
    mirror URL, then either download, opt out (text only), or quit.
    """

    def __init__(self) -> None:
        super().__init__()

        # ── result slots ─────────────────────────────────────────────────
        self._choice: Literal["download", "text_only", "quit"] = "text_only"
        self._selected_size: ModelSize = "base"
        self._mirror: str = "https://huggingface.co"

        # ── window flags ─────────────────────────────────────────────────
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.Dialog
        )
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(True)
        self.setFixedSize(520, 420)

        # ── shadow ───────────────────────────────────────────────────────
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        # ── body ─────────────────────────────────────────────────────────
        body = QWidget()
        body.setObjectName("firstRunBody")
        body.setStyleSheet(_DIALOG_STYLE)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(10)

        # ── title ───────────────────────────────────────────────────────
        title = QLabel("Welcome to Type and Talk")
        title.setStyleSheet(
            "color: #FFFFFF; font-size: 22px; font-weight: bold;"
        )
        layout.addWidget(title)

        # ── hero text ────────────────────────────────────────────────────
        hero = QLabel(
            "Type and Talk lets you control your Windows desktop using "
            "voice commands.  Before you can speak to your computer, "
            "a small speech-recognition model needs to be downloaded "
            "once — after that everything runs locally."
        )
        hero.setStyleSheet(_HERO_STYLE)
        hero.setWordWrap(True)
        layout.addWidget(hero)

        body_label = QLabel(
            "Choose a model size below, or skip this step to use text only."
        )
        body_label.setStyleSheet(_BODY_STYLE)
        body_label.setWordWrap(True)
        layout.addWidget(body_label)

        # ── spacer ───────────────────────────────────────────────────────
        layout.addSpacing(4)

        # ── model size radio group ───────────────────────────────────────
        size_label = QLabel("Model Size")
        size_label.setStyleSheet(_SUBTITLE_STYLE)
        layout.addWidget(size_label)

        self._radio_group = QButtonGroup(self)
        self._radio_group.setExclusive(True)

        self._radio_tiny = QRadioButton("Tiny (75 MB) — fastest, lower accuracy")
        self._radio_base = QRadioButton("Base (140 MB) — recommended")
        self._radio_small = QRadioButton("Small (460 MB) — more accurate")

        self._radio_group.addButton(self._radio_tiny, 1)
        self._radio_group.addButton(self._radio_base, 2)
        self._radio_group.addButton(self._radio_small, 3)

        self._radio_base.setChecked(True)

        layout.addWidget(self._radio_tiny)
        layout.addWidget(self._radio_base)
        layout.addWidget(self._radio_small)

        # ── spacer ───────────────────────────────────────────────────────
        layout.addSpacing(4)

        # ── mirror URL ───────────────────────────────────────────────────
        mirror_label = QLabel("Download Mirror URL")
        mirror_label.setStyleSheet(_SUBTITLE_STYLE)
        layout.addWidget(mirror_label)

        self._mirror_input = QLineEdit()
        self._mirror_input.setObjectName("mirrorUrl")
        self._mirror_input.setText("https://huggingface.co")
        self._mirror_input.textChanged.connect(self._on_mirror_changed)
        layout.addWidget(self._mirror_input)

        mirror_hint = QLabel(
            "If you are in China, use https://hf-mirror.com for faster downloads."
        )
        mirror_hint.setStyleSheet(_MIRROR_HINT_STYLE)
        mirror_hint.setWordWrap(True)
        layout.addWidget(mirror_hint)

        # ── estimated time ───────────────────────────────────────────────
        est_label = QLabel("About 1–3 minutes on broadband")
        est_label.setStyleSheet(_ESTIMATED_STYLE)
        layout.addWidget(est_label)

        # ── spacer (pushes buttons down) ─────────────────────────────────
        layout.addStretch(1)

        # ── action buttons ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        # Quit (bottom-left, red link).
        self._btn_quit = QPushButton("Quit")
        self._btn_quit.setObjectName("btnQuit")
        self._btn_quit.setCursor(Qt.PointingHandCursor)
        self._btn_quit.clicked.connect(self._on_quit)
        btn_row.addWidget(self._btn_quit)

        btn_row.addStretch(1)

        # Use text only (secondary, default focus).
        self._btn_text_only = QPushButton("Use text only")
        self._btn_text_only.setObjectName("btnTextOnly")
        self._btn_text_only.clicked.connect(self._on_text_only)
        self._btn_text_only.setShortcut(Qt.Key_Escape)
        btn_row.addWidget(self._btn_text_only)

        # Download (primary, blue).
        self._btn_download = QPushButton("Download")
        self._btn_download.setObjectName("btnDownload")
        self._btn_download.setDefault(True)
        self._btn_download.clicked.connect(self._on_download)
        btn_row.addWidget(self._btn_download)

        layout.addLayout(btn_row)

        # ── outer layout wraps the body ──────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def choice(self) -> Literal["download", "text_only", "quit"]:
        """The user's action choice."""
        return self._choice

    @property
    def model_size(self) -> ModelSize:
        """The selected model size."""
        return self._selected_size

    @property
    def mirror(self) -> str:
        """The chosen download mirror URL."""
        return self._mirror

    @staticmethod
    def run_if_needed(
        parent: QWidget | None,
        app_controller: object | None = None,
    ) -> tuple[Literal["download", "text_only", "quit"], str, str] | None:
        """Show the dialog if ``first_run_completed`` is not set.

        Parameters
        ----------
        parent:
            Parent widget for centering.  May be ``None``.
        app_controller:
            Optional ``AppController`` instance.  If provided, the dialog
            checks ``app_controller.config.first_run_completed`` and skips
            when ``True``.

        Returns
        -------
        ``None`` if the dialog was skipped (already completed).
        Otherwise a tuple of ``(user_choice, model_size, mirror_url)``
        where *user_choice* is ``"download"``, ``"text_only"``, or
        ``"quit"``.

        The caller is responsible for persisting config changes based on
        the return value.
        """
        # Check whether the dialog should be skipped.
        if app_controller is not None:
            try:
                if app_controller.config.first_run_completed:  # type: ignore[union-attr]
                    return None
            except AttributeError:
                pass  # config doesn't have the attribute yet — show dialog

        dialog = FirstRunDialog()

        # Center on parent or screen.
        if parent is not None:
            parent_geo = parent.geometry()
            x = parent_geo.x() + (parent_geo.width() - dialog.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - dialog.height()) // 2
            dialog.move(x, y)
        else:
            screen = dialog.screen()
            if screen is not None:
                geo = screen.availableGeometry()
                x = geo.x() + (geo.width() - dialog.width()) // 2
                y = geo.y() + (geo.height() - dialog.height()) // 2
                dialog.move(x, y)

        dialog.exec_()

        choice = dialog.choice
        model_size = dialog.model_size
        mirror = dialog.mirror

        # Handle quit immediately.
        if choice == "quit" and app_controller is not None:
            app_controller.quit()  # type: ignore[union-attr]
            return ("quit", model_size, mirror)

        return (choice, model_size, mirror)

    # ── internal ─────────────────────────────────────────────────────────────

    def _get_selected_size(self) -> ModelSize:
        """Map radio button selection to a model size string."""
        checked_id = self._radio_group.checkedId()
        if checked_id == 1:
            return "tiny"
        elif checked_id == 3:
            return "small"
        return "base"

    def _on_mirror_changed(self, text: str) -> None:
        """Keep internal mirror URL in sync with the text field."""
        self._mirror = text.strip()

    def _on_download(self) -> None:
        """User chose to download."""
        self._choice = "download"
        self._selected_size = self._get_selected_size()
        self.accept()

    def _on_text_only(self) -> None:
        """User chose text-only mode."""
        self._choice = "text_only"
        self._selected_size = self._get_selected_size()
        self.accept()

    def _on_quit(self) -> None:
        """User chose to quit the application."""
        self._choice = "quit"
        self._selected_size = self._get_selected_size()
        self.accept()
