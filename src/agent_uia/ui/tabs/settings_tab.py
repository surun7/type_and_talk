# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Settings tab: API, hotkeys, voice/ASR, TTS, recording, planner, UI."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

__all__ = [
    "SettingsTab",
]

# ── styling ──────────────────────────────────────────────────────────────────

_TAB_STYLE = """
QWidget#settingsBody {
    background: #1E1E1E;
}
QGroupBox {
    background: #252525;
    border: 1px solid #3D3D3D;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-size: 13px;
    font-weight: bold;
    color: #CCCCCC;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 10px;
    color: #CCCCCC;
}
QLineEdit {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 12px;
    selection-background-color: #264F78;
}
QLineEdit:focus {
    border: 1px solid #0078D4;
}
QLineEdit::placeholder {
    color: #666666;
}
QLineEdit[invalid="true"] {
    border: 1px solid #F44336;
}
QComboBox {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 12px;
    min-width: 120px;
}
QComboBox:focus {
    border: 1px solid #0078D4;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    selection-background-color: #264F78;
}
QCheckBox {
    color: #E0E0E0;
    font-size: 12px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 2px solid #555555;
    background: #2D2D2D;
}
QCheckBox::indicator:checked {
    border: 2px solid #0078D4;
    background: #0078D4;
}
QSpinBox, QDoubleSpinBox {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
    min-width: 80px;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #0078D4;
}
"""

_BUTTON_PRIMARY_STYLE = """
QPushButton {
    background: #0078D4;
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: bold;
    min-width: 80px;
}
QPushButton:hover {
    background: #106EBE;
}
QPushButton:disabled {
    background: #3D3D3D;
    color: #666666;
}
"""

_BUTTON_SECONDARY_STYLE = """
QPushButton {
    background: #3D3D3D;
    color: #E0E0E0;
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 13px;
    min-width: 80px;
}
QPushButton:hover {
    background: #555555;
}
"""

_BUTTON_SMALL_STYLE = """
QPushButton {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 11px;
}
QPushButton:hover {
    border: 1px solid #0078D4;
}
"""

_LABEL_STYLE = "color: #AAAAAA; font-size: 12px;"
_SAVED_STYLE = "color: #4CAF50; font-size: 12px; font-weight: bold;"
_TEST_RESULT_STYLE = "color: #AAAAAA; font-size: 11px; padding-left: 8px;"
_TEST_PASS_STYLE = "color: #4CAF50; font-size: 11px; font-weight: bold;"
_TEST_FAIL_STYLE = "color: #F44336; font-size: 11px; font-weight: bold;"


class SettingsTab(QWidget):
    """Main-window tab for editing all application settings.

    Settings are grouped into collapsible sections within a ``QScrollArea``.
    Changes are applied on "Save" and discarded on "Discard".
    """

    def __init__(
        self,
        app_controller: AppController,
        config_store: Any | None = None,
    ) -> None:
        """Initialise the settings tab.

        Args:
            app_controller: The application controller for live config access.
            config_store: Optional ``ConfigStore`` instance for persistence.
                If omitted, a new one is created lazily.
        """
        super().__init__()
        self._controller = app_controller
        self._config_store = config_store
        self._original_config = app_controller.config
        self._modified = False
        self._save_timer: QTimer | None = None

        self.setObjectName("settingsBody")
        self.setStyleSheet(_TAB_STYLE)

        # ── Scroll area ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._scroll_layout.setContentsMargins(16, 16, 16, 16)
        self._scroll_layout.setSpacing(8)

        # ── Build sections ────────────────────────────────────────────────
        self._build_api_section()
        self._build_hotkeys_section()
        self._build_voice_section()
        self._build_tts_section()
        self._build_recording_section()
        self._build_planner_section()
        self._build_ui_section()

        # Spacer to push everything up.
        self._scroll_layout.addStretch(1)

        scroll.setWidget(scroll_content)

        # ── Outer layout ──────────────────────────────────────────────────
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(scroll, 1)

        # ── Bottom bar ────────────────────────────────────────────────────
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(16, 8, 16, 12)
        bottom_bar.setSpacing(8)

        self._saved_label = QLabel()
        self._saved_label.setStyleSheet(_SAVED_STYLE)
        bottom_bar.addWidget(self._saved_label)

        bottom_bar.addStretch(1)

        self._discard_btn = QPushButton("Discard")
        self._discard_btn.setStyleSheet(_BUTTON_SECONDARY_STYLE)
        self._discard_btn.clicked.connect(self._on_discard)
        bottom_bar.addWidget(self._discard_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setStyleSheet(_BUTTON_PRIMARY_STYLE)
        self._save_btn.clicked.connect(self._on_save)
        bottom_bar.addWidget(self._save_btn)

        outer_layout.addLayout(bottom_bar)

        # ── Populate fields from current config ───────────────────────────
        self._populate_from_config()

    # ── Section: API ─────────────────────────────────────────────────────────

    def _build_api_section(self) -> None:
        """Build the API configuration section."""
        group = QGroupBox("API")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        # API Key.
        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.Password)
        self._api_key_input.setPlaceholderText("sk-...")
        key_row.addWidget(self._api_key_input, 1)

        self._show_key_btn = QPushButton("Show")
        self._show_key_btn.setStyleSheet(_BUTTON_SMALL_STYLE)
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.toggled.connect(self._on_toggle_api_key_visibility)
        key_row.addWidget(self._show_key_btn)

        form.addRow("DeepSeek API Key", key_row)

        # Base URL.
        self._base_url_input = QLineEdit()
        self._base_url_input.setPlaceholderText("https://api.deepseek.com")
        form.addRow("Base URL", self._base_url_input)

        # Model.
        self._model_combo = QComboBox()
        self._model_combo.addItems(["deepseek-chat", "deepseek-flash"])
        form.addRow("Model", self._model_combo)

        # Test connection.
        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        self._test_connection_btn = QPushButton("Test connection")
        self._test_connection_btn.setStyleSheet(_BUTTON_SMALL_STYLE)
        self._test_connection_btn.clicked.connect(self._on_test_connection)
        test_row.addWidget(self._test_connection_btn)

        self._test_result_label = QLabel()
        self._test_result_label.setStyleSheet(_TEST_RESULT_STYLE)
        test_row.addWidget(self._test_result_label, 1)

        form.addRow("", test_row)
        self._scroll_layout.addWidget(group)

    # ── Section: Hotkeys ─────────────────────────────────────────────────────

    def _build_hotkeys_section(self) -> None:
        """Build the hotkey configuration section."""
        group = QGroupBox("Hotkeys")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        self._hotkey_widgets: dict[str, QKeySequenceEdit] = {}

        for label, key in [
            ("Toggle Window", "toggle_window"),
            ("Push-to-Talk (PTT)", "ptt"),
            ("Main Window", "main_window"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(6)

            ks_edit = QKeySequenceEdit()
            ks_edit.setStyleSheet(
                "QKeySequenceEdit {"
                "  background: #2D2D2D; color: #E0E0E0;"
                "  border: 1px solid #3D3D3D; border-radius: 4px;"
                "  padding: 4px 8px; font-size: 12px;"
                "}"
            )
            row.addWidget(ks_edit, 1)
            self._hotkey_widgets[key] = ks_edit

            test_btn = QPushButton("Test")
            test_btn.setStyleSheet(_BUTTON_SMALL_STYLE)
            test_btn.clicked.connect(
                lambda checked=False, k=key: self._on_test_hotkey(k)
            )
            row.addWidget(test_btn)

            form.addRow(label, row)

        self._hotkey_conflict_label = QLabel()
        self._hotkey_conflict_label.setStyleSheet(_TEST_RESULT_STYLE)
        form.addRow("", self._hotkey_conflict_label)

        self._scroll_layout.addWidget(group)

    # ── Section: Voice / ASR ─────────────────────────────────────────────────

    def _build_voice_section(self) -> None:
        """Build the voice/ASR configuration section."""
        group = QGroupBox("Voice / ASR")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        # Model size.
        self._asr_model_combo = QComboBox()
        self._asr_model_combo.addItems([
            "tiny", "base", "small", "medium", "large-v3"
        ])
        form.addRow("Model Size", self._asr_model_combo)

        # Mirror URL.
        self._mirror_input = QLineEdit()
        self._mirror_input.setPlaceholderText("https://huggingface.co")
        form.addRow("Mirror", self._mirror_input)

        # Model status.
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._model_status_btn = QPushButton("Show model status")
        self._model_status_btn.setStyleSheet(_BUTTON_SMALL_STYLE)
        self._model_status_btn.clicked.connect(self._on_show_model_status)
        status_row.addWidget(self._model_status_btn)
        self._model_status_label = QLabel()
        self._model_status_label.setStyleSheet(_TEST_RESULT_STYLE)
        status_row.addWidget(self._model_status_label, 1)
        form.addRow("", status_row)

        # Enable voice button (shown when opted out).
        self._enable_voice_btn = QPushButton("Enable voice")
        self._enable_voice_btn.setStyleSheet(_BUTTON_SMALL_STYLE)
        self._enable_voice_btn.clicked.connect(self._on_enable_voice)
        self._enable_voice_btn.hide()
        form.addRow("", self._enable_voice_btn)

        self._scroll_layout.addWidget(group)

    # ── Section: TTS ─────────────────────────────────────────────────────────

    def _build_tts_section(self) -> None:
        """Build the text-to-speech configuration section."""
        group = QGroupBox("Text-to-Speech (TTS)")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        self._tts_enable_check = QCheckBox("Enable TTS")
        self._tts_enable_check.toggled.connect(self._on_modified)
        form.addRow("", self._tts_enable_check)

        self._tts_voice_input = QLineEdit()
        self._tts_voice_input.setPlaceholderText("zh-CN-XiaoxiaoNeural")
        form.addRow("Voice", self._tts_voice_input)

        self._tts_rate_input = QLineEdit()
        self._tts_rate_input.setPlaceholderText("+0%")
        form.addRow("Rate", self._tts_rate_input)

        self._scroll_layout.addWidget(group)

    # ── Section: Recording ───────────────────────────────────────────────────

    def _build_recording_section(self) -> None:
        """Build the recording configuration section."""
        group = QGroupBox("Recording")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        self._silence_timeout_spin = QDoubleSpinBox()
        self._silence_timeout_spin.setRange(0.5, 5.0)
        self._silence_timeout_spin.setSingleStep(0.1)
        self._silence_timeout_spin.setValue(1.5)
        self._silence_timeout_spin.setSuffix(" s")
        form.addRow("Silence Timeout", self._silence_timeout_spin)

        self._max_duration_spin = QSpinBox()
        self._max_duration_spin.setRange(10, 300)
        self._max_duration_spin.setSingleStep(10)
        self._max_duration_spin.setValue(60)
        self._max_duration_spin.setSuffix(" s")
        form.addRow("Max Duration", self._max_duration_spin)

        self._scroll_layout.addWidget(group)

    # ── Section: Planner ─────────────────────────────────────────────────────

    def _build_planner_section(self) -> None:
        """Build the planner configuration section."""
        group = QGroupBox("Planner")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        self._max_steps_spin = QSpinBox()
        self._max_steps_spin.setRange(5, 50)
        self._max_steps_spin.setValue(20)
        form.addRow("Max Steps", self._max_steps_spin)

        self._max_cost_spin = QDoubleSpinBox()
        self._max_cost_spin.setRange(0.01, 1.0)
        self._max_cost_spin.setSingleStep(0.01)
        self._max_cost_spin.setValue(0.10)
        self._max_cost_spin.setPrefix("$")
        form.addRow("Max Cost", self._max_cost_spin)

        self._auto_hide_combo = QComboBox()
        self._auto_hide_combo.addItems([
            ("never", "Never"),
            ("on_success", "On Success"),
            ("always_after_5s", "Always (after 5s)"),
        ])
        form.addRow("Auto-hide", self._auto_hide_combo)

        self._scroll_layout.addWidget(group)

    # ── Section: UI ──────────────────────────────────────────────────────────

    def _build_ui_section(self) -> None:
        """Build the UI configuration section."""
        group = QGroupBox("UI")
        form = QFormLayout(group)
        form.setSpacing(8)
        form.setContentsMargins(12, 20, 12, 12)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        form.addRow("Theme", self._theme_combo)

        self._scroll_layout.addWidget(group)

    # ── public API ───────────────────────────────────────────────────────────

    def reload_config(self) -> None:
        """Reload config from the controller and refresh UI fields."""
        self._original_config = self._controller.config
        self._populate_from_config()
        self._modified = False
        self._update_save_state()

    # ── internal: populate / validate ─────────────────────────────────────────

    def _populate_from_config(self) -> None:
        """Fill all fields with values from the current config."""
        cfg = self._original_config

        # API.
        self._api_key_input.setText("")  # Don't expose the key in the UI.
        self._base_url_input.setText(
            getattr(cfg, "base_url", "https://api.deepseek.com")
        )
        model_idx = self._model_combo.findText(
            getattr(cfg, "model", "deepseek-chat")
        )
        if model_idx >= 0:
            self._model_combo.setCurrentIndex(model_idx)

        # Hotkeys.
        for key, ks_edit in self._hotkey_widgets.items():
            if key == "toggle_window":
                ks_edit.setKeySequence(
                    getattr(cfg, "hotkey", "ctrl+shift+space")
                )
            elif key == "ptt":
                ks_edit.setKeySequence(
                    getattr(cfg, "ptt_hotkey", "ctrl+shift+v")
                )

        # Voice.
        asr_idx = self._asr_model_combo.findText(
            getattr(cfg, "asr_model", "base")
        )
        if asr_idx >= 0:
            self._asr_model_combo.setCurrentIndex(asr_idx)
        self._mirror_input.setText(
            getattr(cfg, "download_mirror", "https://huggingface.co")
        )
        self._enable_voice_btn.setVisible(
            getattr(cfg, "voice_opted_out", False)
        )

        # TTS.
        self._tts_enable_check.setChecked(getattr(cfg, "enable_tts", False))
        self._tts_voice_input.setText(
            getattr(cfg, "tts_voice", "zh-CN-XiaoxiaoNeural")
        )
        self._tts_rate_input.setText(getattr(cfg, "tts_rate", "+0%"))

        # Recording.
        self._silence_timeout_spin.setValue(
            getattr(cfg, "ptt_release_silence_timeout_s", 1.5)
        )
        self._max_duration_spin.setValue(
            int(getattr(cfg, "ptt_max_duration_s", 60))
        )

        # Planner.
        self._max_steps_spin.setValue(getattr(cfg, "max_steps", 20))
        self._max_cost_spin.setValue(
            float(getattr(cfg, "max_cost_usd_per_task", 0.10))
        )
        hide_policy = getattr(cfg, "floating_window_hide_policy", "on_success")
        hide_idx = self._auto_hide_combo.findData(hide_policy)
        if hide_idx >= 0:
            self._auto_hide_combo.setCurrentIndex(hide_idx)

        # UI.
        theme_idx = self._theme_combo.findText(getattr(cfg, "theme", "dark"))
        if theme_idx >= 0:
            self._theme_combo.setCurrentIndex(theme_idx)

    def _gather_values(self) -> dict[str, Any]:
        """Read all field values into a dict for saving."""
        values: dict[str, Any] = {}

        # API.
        api_key = self._api_key_input.text().strip()
        if api_key:
            values["api_key"] = api_key
        base_url = self._base_url_input.text().strip()
        if base_url:
            values["base_url"] = base_url
        values["model"] = self._model_combo.currentText()

        # Hotkeys.
        for key, ks_edit in self._hotkey_widgets.items():
            seq = ks_edit.keySequence().toString().lower()
            if key == "toggle_window":
                values["hotkey"] = seq
            elif key == "ptt":
                values["ptt_hotkey"] = seq

        # Voice.
        values["asr_model"] = self._asr_model_combo.currentText()
        mirror = self._mirror_input.text().strip()
        if mirror:
            values["download_mirror"] = mirror

        # TTS.
        values["enable_tts"] = self._tts_enable_check.isChecked()
        values["tts_voice"] = self._tts_voice_input.text().strip()
        values["tts_rate"] = self._tts_rate_input.text().strip()

        # Recording.
        values["ptt_release_silence_timeout_s"] = (
            self._silence_timeout_spin.value()
        )
        values["ptt_max_duration_s"] = float(self._max_duration_spin.value())

        # Planner.
        values["max_steps"] = self._max_steps_spin.value()
        values["max_cost_usd_per_task"] = self._max_cost_spin.value()
        values["floating_window_hide_policy"] = (
            self._auto_hide_combo.currentData()
        )

        # UI.
        values["theme"] = self._theme_combo.currentText()

        return values

    def _validate(self) -> bool:
        """Validate fields; return True if all are valid."""
        valid = True

        # API key: show red border if empty.
        api_key = self._api_key_input.text().strip()
        if not api_key:
            self._api_key_input.setProperty("invalid", True)
            self._api_key_input.style().unpolish(self._api_key_input)
            self._api_key_input.style().polish(self._api_key_input)
            valid = False
        else:
            self._api_key_input.setProperty("invalid", False)
            self._api_key_input.style().unpolish(self._api_key_input)
            self._api_key_input.style().polish(self._api_key_input)

        return valid

    def _update_save_state(self) -> None:
        """Enable/disable the Save button based on validation and modification."""
        is_valid = self._validate()
        self._save_btn.setEnabled(is_valid and self._modified)

    # ── internal: slots ─────────────────────────────────────────────────────

    def _on_modified(self) -> None:
        """Mark settings as modified and update save state."""
        self._modified = True
        self._update_save_state()
        self._saved_label.clear()

    def _on_toggle_api_key_visibility(self, checked: bool) -> None:
        """Toggle password visibility for the API key field."""
        self._api_key_input.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password
        )
        self._show_key_btn.setText("Hide" if checked else "Show")

    def _on_test_connection(self) -> None:
        """Test the LLM connection with current credentials."""
        api_key = self._api_key_input.text().strip()
        if not api_key:
            self._test_result_label.setStyleSheet(_TEST_FAIL_STYLE)
            self._test_result_label.setText("✗ API key is empty")
            return

        self._test_result_label.setStyleSheet(_TEST_RESULT_STYLE)
        self._test_result_label.setText("Testing...")
        self._test_connection_btn.setEnabled(False)

        # Run the test asynchronously.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._do_test_connection())
            else:
                # Fallback: run sync test via a timer.
                QTimer.singleShot(100, self._do_test_connection_sync)
        except RuntimeError:
            QTimer.singleShot(100, self._do_test_connection_sync)

    async def _do_test_connection(self) -> None:
        """Async test: call LLM with a minimal ping."""
        try:
            from agent_uia.llm_client import LLMConfig, LLMClient

            config = LLMConfig(
                api_key=self._api_key_input.text().strip(),
                base_url=self._base_url_input.text().strip()
                or "https://api.deepseek.com",
                model=self._model_combo.currentText(),
            )
            client = LLMClient(config)
            from agent_uia.llm_client import UserMessage

            response = await client.chat(
                [UserMessage("Respond with exactly 'OK'.")]
            )
            if response and response.message and response.message.content:
                self._test_result_label.setStyleSheet(_TEST_PASS_STYLE)
                self._test_result_label.setText("✓ Connection successful")
            else:
                self._test_result_label.setStyleSheet(_TEST_FAIL_STYLE)
                self._test_result_label.setText("✗ Unexpected response")
        except Exception as exc:
            self._test_result_label.setStyleSheet(_TEST_FAIL_STYLE)
            self._test_result_label.setText(f"✗ {exc}")
        finally:
            self._test_connection_btn.setEnabled(True)

    def _do_test_connection_sync(self) -> None:
        """Fallback sync test (runs in a thread)."""
        import threading

        def _run() -> None:
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._do_test_connection())
            finally:
                loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _on_test_hotkey(self, key_name: str) -> None:
        """Simulate conflict detection for a hotkey."""
        ks_edit = self._hotkey_widgets.get(key_name)
        if ks_edit is None:
            return
        seq = ks_edit.keySequence().toString().lower()
        if not seq:
            self._hotkey_conflict_label.setStyleSheet(_TEST_FAIL_STYLE)
            self._hotkey_conflict_label.setText("✗ No key sequence set")
            return

        # Basic conflict check: parse and validate.
        try:
            from agent_uia.ui.hotkey import parse_hotkey

            parse_hotkey(seq)
            self._hotkey_conflict_label.setStyleSheet(_TEST_PASS_STYLE)
            self._hotkey_conflict_label.setText(f"✓ {seq} — valid")
        except Exception as exc:
            self._hotkey_conflict_label.setStyleSheet(_TEST_FAIL_STYLE)
            self._hotkey_conflict_label.setText(f"✗ {exc}")

    def _on_show_model_status(self) -> None:
        """Show the current ASR model installation status."""
        model_size = self._asr_model_combo.currentText()
        try:
            from agent_uia.audio.model_manager import ModelManager
            from agent_uia.paths import get_models_dir

            manager = ModelManager(
                models_dir=get_models_dir(),
                mirror=self._mirror_input.text().strip()
                or "https://huggingface.co",
            )
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._do_model_status(manager, model_size)
                )
            else:
                QTimer.singleShot(
                    100, lambda: self._do_model_status_sync(manager, model_size)
                )
        except Exception as exc:
            self._model_status_label.setStyleSheet(_TEST_FAIL_STYLE)
            self._model_status_label.setText(f"✗ {exc}")

    async def _do_model_status(
        self, manager: Any, model_size: str
    ) -> None:
        """Check model status asynchronously."""
        try:
            info = await manager.get_status(model_size)
            self._model_status_label.setStyleSheet(_TEST_RESULT_STYLE)
            self._model_status_label.setText(
                f"Model '{model_size}': {info.state.name}"
            )
        except Exception as exc:
            self._model_status_label.setStyleSheet(_TEST_FAIL_STYLE)
            self._model_status_label.setText(f"✗ {exc}")

    def _do_model_status_sync(self, manager: Any, model_size: str) -> None:
        """Fallback sync model status check."""
        import threading

        def _run() -> None:
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    self._do_model_status(manager, model_size)
                )
            finally:
                loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _on_enable_voice(self) -> None:
        """Re-enable voice when it was previously opted out."""
        self._enable_voice_btn.hide()
        self._on_modified()

    def _on_save(self) -> None:
        """Persist settings and update the controller config."""
        if not self._validate():
            return

        from agent_uia.config import ConfigStore

        store = self._config_store or ConfigStore()

        # Build new config.
        values = self._gather_values()
        new_config = self._original_config.model_copy(update=values)
        store.save(new_config)

        # Update the controller's config reference.
        try:
            self._controller._config = new_config
        except AttributeError:
            pass

        self._original_config = new_config
        self._modified = False
        self._update_save_state()

        # Show "✓ Saved" confirmation that fades.
        self._saved_label.setText("✓ Saved")
        if self._save_timer is not None:
            self._save_timer.stop()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._clear_saved_label)
        self._save_timer.start(2000)

    def _clear_saved_label(self) -> None:
        """Clear the saved confirmation label."""
        self._saved_label.clear()

    def _on_discard(self) -> None:
        """Discard changes and reload from config store."""
        from agent_uia.config import ConfigStore

        store = self._config_store or ConfigStore()
        loaded = store.load()
        self._original_config = loaded
        try:
            self._controller._config = loaded
        except AttributeError:
            pass
        self._populate_from_config()
        self._modified = False
        self._update_save_state()
        self._saved_label.clear()
