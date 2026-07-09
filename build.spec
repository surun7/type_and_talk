# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Type and Talk (TNT) — Windows desktop AI agent."""

import sys
from pathlib import Path

BLOCK_CIPHER = None

a = Analysis(
    ['src/agent_uia/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Prompts / system prompt
        ('src/agent_uia/prompts/*.md', 'agent_uia/prompts'),
        # Pricing table
        ('src/agent_uia/pricing.json', 'agent_uia'),
        # Built-in skill YAML files
        ('src/agent_uia/skills/builtin/*.yaml', 'agent_uia/skills/builtin'),
    ],
    hiddenimports=[
        # qasync
        'qasync',
        # Audio
        'sounddevice',
        'numpy',
        'silero_vad',
        'torch',
        'edge_tts',
        # GUI
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        # YAML
        'yaml',
        # Config
        'tomllib',
        'tomli_w',
        # Network
        'openai',
        'huggingface_hub',
        'httpx',
        # Clipboard
        'pyperclip',
        # System
        'psutil',
        # Safety eval
        'asteval',
        # UIA
        'uiautomation',
        # Logging
        'loguru',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'cv2',
        'PyQt5',
        'pytest',
        'IPython',
        'jupyter',
        'nbdime',
    ],
    runtime_hooks=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='tnt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='docs/icon.ico' if Path('docs/icon.ico').exists() else None,
)

# Also produce a console version for CLI commands
exe_debug = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='tnt-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,         # CLI mode — show console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
