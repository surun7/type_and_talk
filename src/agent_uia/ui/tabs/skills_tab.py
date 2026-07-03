# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Skills tab — browse, search, install, and run community skills.

Provides a grid of skill cards with search, import, run, and management actions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from agent_uia.ui.app_controller import AppController

from agent_uia.skills.loader import SkillRegistry, SkillSource, default_registry
from agent_uia.skills.schema import Skill, SkillInput

__all__ = [
    "SkillsTab",
]

# ═══════════════════════════════════════════════════════════════════════════════
#  Styling
# ═══════════════════════════════════════════════════════════════════════════════

_SEARCH_STYLE = """
QLineEdit {
    background: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    padding: 8px 12px;
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

_CARD_STYLE = """
QFrame#skill_card {
    background: #2D2D30;
    border: 1px solid #3C3C3C;
    border-radius: 8px;
    padding: 12px;
}
QFrame#skill_card:hover {
    border: 1px solid #3B8EEA60;
    background: #323235;
}
"""

_CARD_TITLE_STYLE = """
color: #E8E8E8;
font-size: 14px;
font-weight: bold;
"""

_CARD_VERSION_STYLE = """
color: #5A5A5A;
font-size: 10px;
"""

_CARD_DESC_STYLE = """
color: #A0A0A0;
font-size: 11px;
line-height: 1.3;
"""

_TAG_CHIP_STYLE = """
QLabel {
    background: #3B8EEA20;
    color: #3B8EEA;
    border: 1px solid #3B8EEA40;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
}
"""

_SOURCE_BADGE_BUILTIN = """
QLabel {
    background: #2E7D3220;
    color: #3ECF8E;
    border: 1px solid #2E7D3240;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
}
"""

_SOURCE_BADGE_USER = """
QLabel {
    background: #3B8EEA20;
    color: #3B8EEA;
    border: 1px solid #3B8EEA40;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
}
"""

_ACTION_BUTTON_STYLE = """
QPushButton {
    background: #3B8EEA;
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 11px;
    font-weight: bold;
    min-height: 24px;
}
QPushButton:hover {
    background: #5BA0F0;
}
QPushButton:pressed {
    background: #2A6FBF;
}
"""

_MENU_BUTTON_STYLE = """
QPushButton {
    background: transparent;
    color: #A0A0A0;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 14px;
    min-height: 24px;
    min-width: 28px;
}
QPushButton:hover {
    background: #383838;
    color: #E8E8E8;
    border: 1px solid #3B8EEA;
}
"""

_TOOLBAR_BUTTON = """
QPushButton {
    background: #2D2D30;
    color: #E8E8E8;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 11px;
    min-height: 24px;
}
QPushButton:hover {
    background: #383838;
    border: 1px solid #3B8EEA;
}
QPushButton:pressed {
    background: #37373D;
}
"""

_EMPTY_CARD_STYLE = """
QFrame#empty_card {
    background: #2D2D30;
    border: 1px dashed #3C3C3C;
    border-radius: 8px;
    padding: 32px;
}
"""

_STATUS_FOOTER_STYLE = """
QFrame#status_footer {
    background: #252526;
    border-top: 1px solid #3C3C3C;
    padding: 8px 16px;
}
QLabel {
    color: #5A5A5A;
    font-size: 10px;
}
"""

_NOT_ACTIONABLE_LABEL = "color: #5A5A5A; font-size: 12px;"

# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

_TAG_COLORS: dict[str, str] = {
    "windows": "#3B8EEA",
    "utility": "#3ECF8E",
    "browser": "#F0A830",
    "developer": "#CE6FDF",
    "system": "#E85A4F",
    "editor": "#3ECF8E",
    "communication": "#3B8EEA",
    "media": "#F0A830",
    "productivity": "#3ECF8E",
    "automation": "#CE6FDF",
    "ai": "#F0A830",
    "game": "#E85A4F",
    "default": "#A0A0A0",
}

_DEFAULT_COLOR = QColor("#3B8EEA")


def _tag_color(tag: str) -> QColor:
    """Return a colour for the given tag."""
    hex_color = _TAG_COLORS.get(tag.lower(), _TAG_COLORS["default"])
    return QColor(hex_color)


def _make_icon(tags: list[str], size: int = 40) -> QIcon:
    """Paint a simple icon based on the first tag."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    tag = tags[0].lower() if tags else "default"
    colour = _tag_color(tag)

    # Draw a rounded rect base.
    painter.setBrush(colour)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 6, 6)

    # Draw a simple symbol (first letter or generic icon).
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", size // 2, QFont.Bold)
    painter.setFont(font)
    letter = tags[0][0].upper() if tags else "S"
    painter.drawText(
        painter.boundingRect(0, 0, size, size, Qt.AlignCenter, letter),
        Qt.AlignCenter,
        letter,
    )

    painter.end()
    return QIcon(pixmap)


# ═══════════════════════════════════════════════════════════════════════════════
#  SkillCard
# ═══════════════════════════════════════════════════════════════════════════════


class SkillCard(QFrame):
    """A single skill card in the grid."""

    run_requested = Signal(str)  # skill_id

    def __init__(
        self,
        skill: Skill,
        source: SkillSource,
        path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._skill = skill
        self._source = source
        self._path = path

        self.setObjectName("skill_card")
        self.setStyleSheet(_CARD_STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._build_ui()

    # ── public ─────────────────────────────────────────────────────────────

    @property
    def skill_id(self) -> str:
        return self._skill.id

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # ── Row 1: icon, title, version, menu ──────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        icon = QLabel()
        icon.setPixmap(_make_icon(self._skill.tags).pixmap(36, 36))
        icon.setFixedSize(36, 36)
        top_row.addWidget(icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)

        title_label = QLabel(self._skill.name)
        title_label.setStyleSheet(_CARD_TITLE_STYLE)
        title_label.setWordWrap(False)
        title_col.addWidget(title_label)

        version_label = QLabel(f"v{self._skill.version}")
        version_label.setStyleSheet(_CARD_VERSION_STYLE)
        title_col.addWidget(version_label)

        top_row.addLayout(title_col, 1)

        # Menu button.
        menu_btn = QPushButton("\u00B7\u00B7\u00B7")
        menu_btn.setObjectName("menu_btn")
        menu_btn.setStyleSheet(_MENU_BUTTON_STYLE)
        menu_btn.setFixedSize(28, 24)
        menu_btn.setCursor(Qt.PointingHandCursor)
        menu_btn.clicked.connect(self._show_menu)
        top_row.addWidget(menu_btn)

        layout.addLayout(top_row)

        # ── Description (2-3 lines) ────────────────────────────────────────
        desc_label = QLabel(self._skill.description)
        desc_label.setStyleSheet(_CARD_DESC_STYLE)
        desc_label.setWordWrap(True)
        desc_label.setMaximumHeight(48)  # ~3 lines
        layout.addWidget(desc_label)

        # ── Row 2: tag chips + source badge ────────────────────────────────
        tag_row = QHBoxLayout()
        tag_row.setSpacing(4)

        for tag in self._skill.tags[:5]:  # max 5 tags
            chip = QLabel(tag)
            chip.setStyleSheet(_TAG_CHIP_STYLE)
            chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            tag_row.addWidget(chip)

        tag_row.addStretch(1)

        source_label = QLabel(
            "builtin" if self._source == SkillSource.BUILTIN else "user"
        )
        source_label.setStyleSheet(
            _SOURCE_BADGE_BUILTIN
            if self._source == SkillSource.BUILTIN
            else _SOURCE_BADGE_USER
        )
        source_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        tag_row.addWidget(source_label)

        layout.addLayout(tag_row)

        # ── Row 3: Run button ──────────────────────────────────────────────
        run_row = QHBoxLayout()
        run_row.setSpacing(4)

        run_btn = QPushButton("Run")
        run_btn.setStyleSheet(_ACTION_BUTTON_STYLE)
        run_btn.setCursor(Qt.PointingHandCursor)
        run_btn.clicked.connect(self._on_run)
        run_row.addWidget(run_btn)

        run_row.addStretch(1)
        layout.addLayout(run_row)

    # ── slots ──────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        self.run_requested.emit(self._skill.id)

    def _show_menu(self) -> None:
        menu = QMenu(self)

        view_yaml = QAction("View YAML", self)
        view_yaml.triggered.connect(self._on_view_yaml)
        menu.addAction(view_yaml)

        reveal = QAction("Reveal in Folder", self)
        reveal.triggered.connect(self._on_reveal)
        menu.addAction(reveal)

        if self._source == SkillSource.USER:
            menu.addSeparator()
            uninstall = QAction("Uninstall", self)
            uninstall.setIcon(QIcon())
            uninstall.triggered.connect(self._on_uninstall)
            menu.addAction(uninstall)

        # Show the menu under the button.
        sender = self.sender()
        if sender is not None:
            menu.exec_(sender.mapToGlobal(sender.rect().bottomLeft()))

    def _on_view_yaml(self) -> None:
        """Open the YAML file in the default editor."""
        QDesktopServices.openUrl(self._path.as_uri())

    def _on_reveal(self) -> None:
        """Open the containing folder in the file manager."""
        QDesktopServices.openUrl(self._path.parent.as_uri())

    def _on_uninstall(self) -> None:
        """Request uninstall via the parent tab."""
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "_on_uninstall_skill"):
                parent._on_uninstall_skill(self._skill.id)  # type: ignore[union-attr]
                return
            parent = parent.parent()


# ═══════════════════════════════════════════════════════════════════════════════
#  SkillInputsDialog
# ═══════════════════════════════════════════════════════════════════════════════


class SkillInputsDialog(QDialog):
    """Modal dialog for providing skill input values."""

    def __init__(
        self,
        skill: Skill,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._skill = skill
        self._values: dict[str, Any] = {}
        self._widgets: dict[str, QWidget] = {}

        self.setWindowTitle(f"Run: {skill.name}")
        self.setMinimumWidth(400)
        self.setModal(True)

        self._build_ui()

    # ── public ─────────────────────────────────────────────────────────────

    @property
    def values(self) -> dict[str, Any]:
        return dict(self._values)

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header.
        header = QLabel(f"Provide inputs for <b>{self._skill.name}</b>")
        header.setStyleSheet("color: #E8E8E8; font-size: 14px;")
        layout.addWidget(header)

        # Form.
        form = QFormLayout()
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 0, 0)

        for inp in self._skill.inputs:
            label_text = inp.name
            if inp.required:
                label_text += " *"
            if inp.description:
                label_text += f"\n<span style='color: #888; font-size: 10px;'>{inp.description}</span>"

            widget = self._build_input_widget(inp)
            self._widgets[inp.name] = widget
            form.addRow(QLabel(label_text), widget)

        layout.addLayout(form)

        # Spacer.
        layout.addStretch(1)

        # Buttons.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Cancel | QDialogButtonBox.Ok,
            self,
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        btn_box.button(QDialogButtonBox.Ok).setText("Run")
        btn_box.button(QDialogButtonBox.Ok).setStyleSheet(
            "QPushButton { background: #3B8EEA; color: #FFFFFF; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #5BA0F0; }"
        )
        btn_box.button(QDialogButtonBox.Cancel).setStyleSheet(
            "QPushButton { background: #2D2D30; color: #E8E8E8; "
            "border: 1px solid #3C3C3C; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #383838; border: 1px solid #3B8EEA; }"
        )
        layout.addWidget(btn_box)

    def _build_input_widget(self, inp: SkillInput) -> QWidget:
        """Create the appropriate input widget for a SkillInput type."""
        if inp.type == "string":
            w = QLineEdit()
            w.setPlaceholderText(inp.description or "")
            if inp.default is not None:
                w.setText(str(inp.default))
            w.setStyleSheet(
                "QLineEdit { background: #2D2D2D; color: #E0E0E0; "
                "border: 1px solid #3C3C3C; border-radius: 4px; "
                "padding: 6px 8px; font-size: 12px; }"
                "QLineEdit:focus { border: 1px solid #3B8EEA; }"
            )
            return w

        if inp.type == "integer":
            w = QSpinBox()
            if inp.default is not None:
                w.setValue(int(inp.default))
            w.setRange(-2**31, 2**31 - 1)
            w.setStyleSheet(
                "QSpinBox { background: #2D2D2D; color: #E0E0E0; "
                "border: 1px solid #3C3C3C; border-radius: 4px; "
                "padding: 4px 6px; font-size: 12px; }"
                "QSpinBox:focus { border: 1px solid #3B8EEA; }"
            )
            return w

        if inp.type == "float":
            w = QDoubleSpinBox()
            if inp.default is not None:
                w.setValue(float(inp.default))
            w.setRange(-2**31, 2**31 - 1)
            w.setDecimals(4)
            w.setStyleSheet(
                "QDoubleSpinBox { background: #2D2D2D; color: #E0E0E0; "
                "border: 1px solid #3C3C3C; border-radius: 4px; "
                "padding: 4px 6px; font-size: 12px; }"
                "QDoubleSpinBox:focus { border: 1px solid #3B8EEA; }"
            )
            return w

        if inp.type == "boolean":
            w = QCheckBox(inp.description or inp.name)
            if inp.default is not None:
                w.setChecked(bool(inp.default))
            w.setStyleSheet(
                "QCheckBox { color: #E0E0E0; font-size: 12px; spacing: 8px; }"
                "QCheckBox::indicator { width: 16px; height: 16px; }"
            )
            return w

        if inp.type == "enum":
            w = QComboBox()
            if inp.choices:
                w.addItems(inp.choices)
            if inp.default is not None and inp.default in (inp.choices or []):
                w.setCurrentText(str(inp.default))
            w.setStyleSheet(
                "QComboBox { background: #2D2D2D; color: #E0E0E0; "
                "border: 1px solid #3C3C3C; border-radius: 4px; "
                "padding: 4px 6px; font-size: 12px; }"
                "QComboBox:focus { border: 1px solid #3B8EEA; }"
                "QComboBox::drop-down { border: none; }"
                "QComboBox QAbstractItemView { background: #2D2D2D; "
                "color: #E0E0E0; selection-background-color: #264F78; }"
            )
            return w

        # Fallback: string.
        w = QLineEdit()
        w.setPlaceholderText(inp.description or "")
        w.setStyleSheet(
            "QLineEdit { background: #2D2D2D; color: #E0E0E0; "
            "border: 1px solid #3C3C3C; border-radius: 4px; "
            "padding: 6px 8px; font-size: 12px; }"
            "QLineEdit:focus { border: 1px solid #3B8EEA; }"
        )
        return w

    def _on_accept(self) -> None:
        """Collect values from widgets and accept."""
        for inp in self._skill.inputs:
            w = self._widgets[inp.name]
            if inp.type == "string":
                self._values[inp.name] = w.text()
            elif inp.type == "integer":
                self._values[inp.name] = w.value()
            elif inp.type == "float":
                self._values[inp.name] = w.value()
            elif inp.type == "boolean":
                self._values[inp.name] = w.isChecked()
            elif inp.type == "enum":
                self._values[inp.name] = w.currentText()

        self.accept()


# ═══════════════════════════════════════════════════════════════════════════════
#  SkillsTab
# ═══════════════════════════════════════════════════════════════════════════════


class SkillsTab(QWidget):
    """Main-window tab for browsing, searching, and managing skills."""

    def __init__(
        self,
        app_controller: AppController,
        parent: QWidget | None = None,
        registry: SkillRegistry | None = None,
    ) -> None:
        """Initialise the Skills tab.

        Args:
            app_controller: The application controller.
            parent:         Optional parent widget.
            registry:       Optional skill registry (uses
                :func:`default_registry` if ``None``).
        """
        super().__init__(parent)
        self._controller = app_controller
        self._registry = registry or default_registry()
        self._skill_cards: list[SkillCard] = []
        self._all_skills: list[tuple[Skill, SkillSource, Path]] = []

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 0)
        outer.setSpacing(12)

        # ═══════════════════════════════════════════════════════════════════
        #  Top toolbar
        # ═══════════════════════════════════════════════════════════════════
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(
            "Search skills by name, id, or tag..."
        )
        self._search_input.setStyleSheet(_SEARCH_STYLE)
        self._search_input.setFixedHeight(32)
        self._search_input.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self._search_input, 1)

        # Import from file.
        import_file_btn = QPushButton("Import from file...")
        import_file_btn.setStyleSheet(_TOOLBAR_BUTTON)
        import_file_btn.clicked.connect(self._on_import_file)
        toolbar.addWidget(import_file_btn)

        # Import from URL.
        import_url_btn = QPushButton("Import from URL...")
        import_url_btn.setStyleSheet(_TOOLBAR_BUTTON)
        import_url_btn.clicked.connect(self._on_import_url)
        toolbar.addWidget(import_url_btn)

        # Reload.
        reload_btn = QPushButton("Reload")
        reload_btn.setStyleSheet(_TOOLBAR_BUTTON)
        reload_btn.clicked.connect(self._on_reload)
        toolbar.addWidget(reload_btn)

        outer.addLayout(toolbar)

        # ═══════════════════════════════════════════════════════════════════
        #  Scrollable card grid
        # ═══════════════════════════════════════════════════════════════════
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #3C3C3C; border-radius: 4px; "
            "min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: #5A5A5A; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        scroll_container = QWidget()
        self._grid_layout = QGridLayout(scroll_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(12)
        self._grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        scroll.setWidget(scroll_container)
        outer.addWidget(scroll, 1)

        # ═══════════════════════════════════════════════════════════════════
        #  Empty state card (layered on top, hidden by default)
        # ═══════════════════════════════════════════════════════════════════
        self._empty_card = QFrame()
        self._empty_card.setObjectName("empty_card")
        self._empty_card.setStyleSheet(_EMPTY_CARD_STYLE)
        self._empty_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._empty_card.hide()

        empty_layout = QVBoxLayout(self._empty_card)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(12)

        empty_icon = QLabel("\U0001F4E6")  # package emoji
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setStyleSheet("font-size: 48px;")
        empty_layout.addWidget(empty_icon)

        empty_title = QLabel("No skills installed yet")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_title.setStyleSheet(
            "color: #E8E8E8; font-size: 16px; font-weight: bold;"
        )
        empty_layout.addWidget(empty_title)

        empty_desc = QLabel(
            "Drop a <code>.yaml</code> file into the skills directory "
            "or click <b>Import from file...</b> to get started."
        )
        empty_desc.setAlignment(Qt.AlignCenter)
        empty_desc.setWordWrap(True)
        empty_desc.setStyleSheet("color: #A0A0A0; font-size: 12px;")
        empty_layout.addWidget(empty_desc)

        empty_import_btn = QPushButton("Import from file...")
        empty_import_btn.setStyleSheet(_ACTION_BUTTON_STYLE)
        empty_import_btn.setCursor(Qt.PointingHandCursor)
        empty_import_btn.clicked.connect(self._on_import_file)
        empty_layout.addWidget(empty_import_btn, alignment=Qt.AlignCenter)

        outer.addWidget(self._empty_card)

        # ═══════════════════════════════════════════════════════════════════
        #  Status footer
        # ═══════════════════════════════════════════════════════════════════
        footer = QFrame()
        footer.setObjectName("status_footer")
        footer.setStyleSheet(_STATUS_FOOTER_STYLE)
        footer.setFixedHeight(28)

        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 0, 16, 0)
        footer_layout.setSpacing(16)

        self._status_label = QLabel("Loading skills...")
        self._status_label.setStyleSheet("color: #5A5A5A; font-size: 10px;")
        footer_layout.addWidget(self._status_label)

        footer_layout.addStretch(1)

        outer.addWidget(footer)

        # ── Initial load ─────────────────────────────────────────────────
        self._load_skills()

    # ── public API ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload skills and refresh the display."""
        self._load_skills()

    # ── internal: data loading ────────────────────────────────────────────

    def _load_skills(self) -> None:
        """Load skills from the registry and populate the grid."""
        try:
            loaded = self._registry.load_all()
            self._all_skills = [
                (ls.skill, ls.source, ls.path) for ls in loaded
            ]
        except Exception as exc:
            logger.exception("Failed to load skills: %s", exc)
            self._all_skills = []
            self._status_label.setText("Error loading skills")

        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter cards by search text and rebuild the grid."""
        search = self._search_input.text().strip().lower()

        # Clear existing cards.
        self._clear_grid()

        # Filter.
        filtered: list[tuple[Skill, SkillSource, Path]] = []
        for skill, source, path in self._all_skills:
            if search:
                if (
                    search not in skill.id.lower()
                    and search not in skill.name.lower()
                    and not any(search in t.lower() for t in skill.tags)
                ):
                    continue
            filtered.append((skill, source, path))

        # Show empty state or cards.
        if not filtered:
            self._empty_card.show()
            self._status_label.setText("No skills match your search")
            return

        self._empty_card.hide()

        # Build cards in a grid (3 columns).
        cols = 3
        self._skill_cards.clear()

        for idx, (skill, source, path) in enumerate(filtered):
            card = SkillCard(skill, source, path, self)
            card.run_requested.connect(self._on_run_skill)
            self._skill_cards.append(card)

            row = idx // cols
            col = idx % cols
            self._grid_layout.addWidget(card, row, col)

        # Fill remaining cells with spacers to keep alignment.
        remainder = len(filtered) % cols
        if remainder:
            for _ in range(cols - remainder):
                spacer = QWidget()
                spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._grid_layout.addWidget(
                    spacer, len(filtered) // cols, cols - 1 - remainder
                )

        # Update status.
        builtin_count = sum(
            1 for _, s, _ in self._all_skills
            if s == SkillSource.BUILTIN
        )
        user_count = sum(
            1 for _, s, _ in self._all_skills
            if s == SkillSource.USER
        )
        total = len(self._all_skills)
        self._status_label.setText(
            f"{total} skill{'s' if total != 1 else ''} "
            f"({builtin_count} builtin, {user_count} user)"
        )

    def _clear_grid(self) -> None:
        """Remove all widgets from the grid layout."""
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        """Filter the grid when search text changes."""
        self._apply_filter()

    def _on_run_skill(self, skill_id: str) -> None:
        """Execute a skill, prompting for inputs if needed."""
        loaded = self._registry.get(skill_id)
        if loaded is None:
            QMessageBox.warning(
                self,
                "Skill Not Found",
                f"Skill {skill_id!r} could not be found.",
            )
            return

        skill = loaded.skill

        # If the skill has inputs, show the input dialog.
        if skill.inputs:
            dialog = SkillInputsDialog(skill, self)
            if dialog.exec() != QDialog.Accepted:
                return
            inputs = dialog.values
        else:
            inputs = {}

        # Run via the app controller.
        if hasattr(self._controller, "run_skill"):
            asyncio.create_task(
                self._controller.run_skill(skill_id, inputs)  # type: ignore[union-attr]
            )
        else:
            # Fallback: notify the user.
            QMessageBox.information(
                self,
                "Run Skill",
                f"Running skill {skill_id!r} with inputs: {inputs}",
            )

    def _on_import_file(self) -> None:
        """Pick a YAML file and install it."""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Skill from File",
            "",
            "YAML Files (*.yaml *.yml);;All Files (*)",
        )
        if not path_str:
            return

        src = Path(path_str)
        try:
            dest = self._registry.install_from_file(src)
            self._load_skills()
            QMessageBox.information(
                self,
                "Skill Installed",
                f"Installed skill from\n{src.name}\nto\n{dest}",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Install Failed",
                f"Could not install skill:\n{exc}",
            )

    def _on_import_url(self) -> None:
        """Prompt for a URL and install from it."""
        from PySide6.QtWidgets import QInputDialog

        url, ok = QInputDialog.getText(
            self,
            "Import Skill from URL",
            "Enter the HTTPS URL of a skill YAML file:",
        )
        if not ok or not url:
            return

        try:
            dest = self._registry.install_from_url(url)
            self._load_skills()
            QMessageBox.information(
                self,
                "Skill Installed",
                f"Installed skill from URL to\n{dest}",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Install Failed",
                f"Could not install from URL:\n{exc}",
            )

    def _on_reload(self) -> None:
        """Force reload all skills."""
        self._registry.reload()
        self._load_skills()

    def _on_uninstall_skill(self, skill_id: str) -> None:
        """Uninstall a user skill after confirmation."""
        reply = QMessageBox.question(
            self,
            "Uninstall Skill",
            f"Are you sure you want to uninstall skill {skill_id!r}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            ok = self._registry.uninstall(skill_id)
            if ok:
                self._load_skills()
                QMessageBox.information(
                    self,
                    "Skill Uninstalled",
                    f"Skill {skill_id!r} has been uninstalled.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Not Found",
                    f"Skill {skill_id!r} was not found.",
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Uninstall Failed",
                f"Could not uninstall skill:\n{exc}",
            )
