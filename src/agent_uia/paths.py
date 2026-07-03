# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Centralized path helpers for agent-uia.

All persistent data (logs, audit trail, usage ledger, history) lives under a
single application data directory instead of the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "PACKAGE_DIR",
    "get_app_data_dir",
    "get_logs_dir",
    "get_models_dir",
    "get_model_path",
]

PACKAGE_DIR = Path(__file__).parent.resolve()


def get_app_data_dir() -> Path:
    """Return the root directory for agent-uia persistent data.

    On Windows this is ``%LOCALAPPDATA%\\agent-uia``. On other platforms it
    falls back to ``~/.agent-uia``.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data) / "agent-uia"
    else:
        base = Path.home() / ".agent-uia"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_logs_dir() -> Path:
    """Return the directory for log files.

    Creates the directory if it does not exist.
    """
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_models_dir() -> Path:
    """Return the directory for downloaded model weights.

    Models live outside the git repo entirely.  The directory is auto-created
    on first call.
    """
    models_dir = get_app_data_dir() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_model_path(model_size: str) -> Path:
    """Return the expected local path for a given model size.

    Args:
        model_size: One of ``"tiny"``, ``"base"``, ``"small"``,
            ``"medium"``, ``"large-v3"``.

    Returns:
        ``<models_dir>/faster-whisper-<model_size>/``
    """
    return get_models_dir() / f"faster-whisper-{model_size}"
