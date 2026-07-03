# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the Win32 global hotkey module."""

from __future__ import annotations

from unittest import mock

import pytest

# Import directly from the submodule to avoid triggering the full UI
# dependency chain (PySide6 + pydantic circular import on Python 3.14).
from agent_uia.ui.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    GlobalHotkey,
    HotkeyError,
    parse_hotkey,
)

# ── known combo mapping ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hotkey_str", "expected_mod", "expected_vk"),
    [
        ("ctrl+shift+space", MOD_CONTROL | MOD_SHIFT, 0x20),
        ("alt+f4", MOD_ALT, 0x73),                      # F4
        ("ctrl+alt+f12", MOD_CONTROL | MOD_ALT, 0x7B),  # F12
        ("win+e", MOD_WIN, 0x45),                       # E
        ("ctrl+c", MOD_CONTROL, 0x43),                  # C
        ("ctrl+v", MOD_CONTROL, 0x56),                  # V
        ("alt+tab", MOD_ALT, 0x09),                     # TAB
        ("ctrl+shift+a", MOD_CONTROL | MOD_SHIFT, 0x41),
        ("shift+return", MOD_SHIFT, 0x0D),
        ("alt+space", MOD_ALT, 0x20),
        ("ctrl+0", MOD_CONTROL, 0x30),
        ("ctrl+9", MOD_CONTROL, 0x39),
        ("shift+f1", MOD_SHIFT, 0x70),
        ("ctrl+backspace", MOD_CONTROL, 0x08),
    ],
)
def test_parse_known_combinations(
    hotkey_str: str, expected_mod: int, expected_vk: int
) -> None:
    """Verify well-known combos produce the expected (modifiers, vk) tuples."""
    mod, vk = parse_hotkey(hotkey_str)
    assert mod == expected_mod, f"{hotkey_str}: mod {mod:#x} != {expected_mod:#x}"
    assert vk == expected_vk, f"{hotkey_str}: vk {vk:#x} != {expected_vk:#x}"


# ── reserved combos ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_combo",
    [
        "ctrl+alt+delete",
        "ctrl+escape",
        "win+l",
        "windows+l",
        "ctrl+win+l",
    ],
)
def test_rejects_reserved_combos(bad_combo: str) -> None:
    """Reserved system combos must raise HotkeyError."""
    with pytest.raises(HotkeyError, match="reserved"):
        parse_hotkey(bad_combo)


# ── invalid strings ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "space",               # no modifier
        "ctrl+",               # missing key
        "+space",              # leading +
        "ctrl++space",         # double +
        "unknownkey",          # single key no modifier
        "ctrl+superkey",       # unknown key
        "supmod+space",        # unknown modifier
    ],
)
def test_rejects_invalid_strings(bad_input: str) -> None:
    """Malformed or incomplete hotkey strings must raise HotkeyError."""
    with pytest.raises(HotkeyError):
        parse_hotkey(bad_input)


# ── start / stop idempotency ────────────────────────────────────────────────


class TestGlobalHotkeyLifecycle:
    """Test start/stop with mocked Win32 API calls."""

    def test_start_calls_register(self) -> None:
        """start() calls RegisterHotKey with the right args."""
        hk = GlobalHotkey("ctrl+shift+space")
        with (
            mock.patch.object(hk._user32, "RegisterHotKey", return_value=1) as mock_reg,
            mock.patch.object(hk._user32, "GetMessageW", return_value=0),  # immediate exit
        ):
            hk.start(lambda: None)
            mock_reg.assert_called_once_with(None, 1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x20)

    def test_start_raises_on_conflict(self) -> None:
        """If RegisterHotKey returns 0, start() raises HotkeyError."""
        hk = GlobalHotkey("alt+f4")
        with mock.patch.object(hk._user32, "RegisterHotKey", return_value=0), \
                pytest.raises(HotkeyError, match="Failed to register"):
            hk.start(lambda: None)

    def test_stop_calls_unregister(self) -> None:
        """stop() calls UnregisterHotKey and cleans up."""
        hk = GlobalHotkey("ctrl+shift+space")
        with (
            mock.patch.object(hk._user32, "RegisterHotKey", return_value=1) as mock_reg,
            mock.patch.object(hk._user32, "UnregisterHotKey") as mock_unreg,
            mock.patch.object(hk._user32, "GetMessageW", return_value=0),
            mock.patch.object(hk._user32, "PostThreadMessageW"),
        ):
            hk.start(lambda: None)
            mock_reg.assert_called_once()
            hk.stop()
            mock_unreg.assert_called_once_with(None, 1)

    def test_start_twice_is_noop(self) -> None:
        """start() when already registered does not re-register."""
        hk = GlobalHotkey("ctrl+shift+space")
        with (
            mock.patch.object(hk._user32, "RegisterHotKey", return_value=1) as mock_reg,
            mock.patch.object(hk._user32, "GetMessageW", return_value=0),
            mock.patch.object(hk._user32, "PostThreadMessageW"),
        ):
            hk.start(lambda: None)
            mock_reg.assert_called_once()
            hk.start(lambda: None)  # second call — no extra reg
            mock_reg.assert_called_once()

    def test_stop_before_start_is_safe(self) -> None:
        """stop() without prior start does not crash."""
        hk = GlobalHotkey("ctrl+shift+space")
        hk.stop()  # should be a no-op

    def test_is_registered_flag(self) -> None:
        """is_registered reflects registration state."""
        hk = GlobalHotkey("ctrl+shift+space")
        assert not hk.is_registered
        with (
            mock.patch.object(hk._user32, "RegisterHotKey", return_value=1),
            mock.patch.object(hk._user32, "GetMessageW", return_value=0),
            mock.patch.object(hk._user32, "PostThreadMessageW"),
        ):
            hk.start(lambda: None)
            assert hk.is_registered
            hk.stop()
            assert not hk.is_registered

    def test_start_after_stop_re_registers(self) -> None:
        """start() after stop() re-registers cleanly (new call to RegisterHotKey)."""
        hk = GlobalHotkey("ctrl+shift+space")
        with (
            mock.patch.object(hk._user32, "RegisterHotKey", return_value=1) as mock_reg,
            mock.patch.object(hk._user32, "GetMessageW", return_value=0),
            mock.patch.object(hk._user32, "PostThreadMessageW"),
        ):
            hk.start(lambda: None)
            hk.stop()
            hk.start(lambda: None)
            # Should have been called twice
            assert mock_reg.call_count == 2
