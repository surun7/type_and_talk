# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for platform_check module."""

from __future__ import annotations

import sys

import pytest


class TestPlatformCheck:
    """Tests for assert_windows()."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Only runs on Windows")
    def test_assert_windows_returns_none_on_windows(self) -> None:
        """On Windows, assert_windows() returns None (no exception)."""
        from agent_uia.platform_check import assert_windows

        result = assert_windows()
        assert result is None

    def test_assert_windows_raises_on_non_windows(self) -> None:
        """On non-Windows, assert_windows raises RuntimeError."""
        from unittest import mock

        with mock.patch("sys.platform", "linux"):
            # Re-import to trigger the guard with patched platform.
            import importlib
            import agent_uia.platform_check as pc

            with pytest.raises(RuntimeError, match="agent-uia requires Windows"):
                importlib.reload(pc)

    def test_reimport_does_not_re_raise_on_windows(self) -> None:
        """Re-importing the module does not cause a double raise."""
        import importlib
        import agent_uia.platform_check as pc

        # First import already happened. Reload should work fine on Windows.
        try:
            importlib.reload(pc)
        except RuntimeError:
            if sys.platform == "win32":
                pytest.fail("Re-import raised RuntimeError on Windows")
            # Expected on non-Windows — pass.
