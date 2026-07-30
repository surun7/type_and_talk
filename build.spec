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
        ('src/agent_uia/prompts/*.md', 'agent_uia/prompts'),
        ('src/agent_uia/pricing.json', 'agent_uia'),
        ('src/agent_uia/skills/builtin/*.yaml', 'agent_uia/skills/builtin'),
    ],
    hiddenimports=[
        'qasync',
        'sounddevice', 'numpy', 'silero_vad', 'torch', 'edge_tts',
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtSvg',
        'yaml', 'tomllib', 'tomli_w',
        'openai', 'huggingface_hub', 'httpx',
        'pyperclip', 'psutil', 'asteval',
        'uiautomation', 'loguru', 'dotenv',
        'pyqtgraph',
    ],
    hookspath=[],
    hooksconfig={},
    excludes=['tkinter', 'matplotlib', 'PIL', 'cv2', 'PyQt5', 'pytest', 'IPython', 'jupyter', 'nbdime'],
    runtime_hooks=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='tnt',
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=None,
)
