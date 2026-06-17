# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Platform check — hard Windows guard.

This module MUST be imported before any UIA or Windows-specific code.
It raises RuntimeError on non-Windows platforms at import time.
"""

from __future__ import annotations

import sys

__all__ = ["assert_windows"]


def assert_windows() -> None:
    """Assert the current platform is Windows (win32).

    Raises:
        RuntimeError: If ``sys.platform`` is not ``"win32"``.
    """
    if sys.platform != "win32":
        raise RuntimeError("agent-uia requires Windows. Current platform: " + sys.platform)


# Execute at import time so no module can accidentally skip the guard.
assert_windows()
