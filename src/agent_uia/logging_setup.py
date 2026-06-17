# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Logging setup via loguru.

Configures once: colorized stderr sink + rotating file sink.
Provides a ``redact()`` helper for masking sensitive fields in log output.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger

__all__ = ["configure_logging", "redact", "logger"]

# ── compiled patterns for sensitive-field redaction ──────────────────────────

_PASSWORD_RE = re.compile(
    r"(?:password|passwd|pwd)\s*[:=]\s*(\S{8,})",
    re.IGNORECASE,
)
_API_KEY_RE = re.compile(r"(?:sk|ds)-[a-zA-Z0-9]{16,}")
_PHONE_RE = re.compile(r"\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_APPDATA_PATH_RE = re.compile(
    re.escape(os.environ.get("APPDATA", "%APPDATA%")) + r"[\S]*",
    re.IGNORECASE,
)

_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (_PASSWORD_RE, r"password=***"),
    (_API_KEY_RE, "***API-KEY***"),
    (_PHONE_RE, "***PHONE***"),
    (_EMAIL_RE, "***EMAIL***"),
    (_APPDATA_PATH_RE, "%APPDATA%/***"),
]

_config_initialized: bool = False


def redact(value: str) -> str:
    """Mask sensitive substrings in *value* before logging.

    Covers: passwords (8+ chars after ``password=``), API keys (``sk-`` /
    ``ds-`` prefix), phone numbers, email addresses, and ``%APPDATA%`` paths.

    Args:
        value: The raw string that may contain sensitive data.

    Returns:
        A copy of *value* with all matched patterns replaced by placeholders.
    """
    result = value
    for pattern, replacement in _REDACT_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _redact_patcher(record: dict[str, Any]) -> None:
    """loguru patcher: apply ``redact()`` to the formatted message."""
    record["message"] = redact(str(record["message"]))


def configure_logging(*, level: str = "INFO") -> None:
    """Configure loguru sinks once (idempotent).

    - Stderr sink: colorized, level controlled by *level*.
    - File sink: rotating (10 MB × 5 files) at ``./logs/agent-uia.log``.

    Args:
        level: One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``.
            Overridable via ``AGENT_UIA_LOG_LEVEL`` env var.
    """
    global _config_initialized  # noqa: PLW0603
    if _config_initialized:
        return
    _config_initialized = True

    effective_level = os.environ.get("AGENT_UIA_LOG_LEVEL", level).upper()

    # Remove any default sink.
    logger.remove()

    # Stderr — colorized.
    logger.add(
        sys.stderr,
        level=effective_level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )

    # Rotating file sink.
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        logs_dir / "agent-uia.log",
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        compression=None,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        encoding="utf-8",
    )

    # Register the redaction patcher.
    logger.configure(patcher=_redact_patcher)
