# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the safety gate module."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from agent_uia.safety import (
    LoginDetectedError,
    SafetyConfig,
    SafetyDecision,
    SafetyEvent,
    SafetyGate,
    SafetyVerdict,
    UnsupportedAppError,
    assert_action_allowed,
    assert_app_allowed,
    default_gate,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _clean_default_gate() -> SafetyGate:
    """Return a fresh SafetyGate isolated from the singleton."""
    return SafetyGate(SafetyConfig())


# ── check_app tests ──────────────────────────────────────────────────────────


class TestCheckApp:
    """Tests for SafetyGate.check_app()."""

    def test_blocks_known_game_exe(self) -> None:
        """check_app with VALORANT exe returns BLOCK_UNSUPPORTED."""
        gate = _clean_default_gate()
        decision = gate.check_app(exe_name="VALORANT-Win64-Shipping.exe")
        assert decision.verdict == SafetyVerdict.BLOCK_UNSUPPORTED
        assert "blocklist" in decision.reason.lower()

    def test_blocks_steam(self) -> None:
        """check_app with steam.exe returns BLOCK_UNSUPPORTED."""
        gate = _clean_default_gate()
        decision = gate.check_app(exe_name="steam.exe")
        assert decision.verdict == SafetyVerdict.BLOCK_UNSUPPORTED

    def test_blocks_login_window(self) -> None:
        """Login title + recognized exe → BLOCK_GAME_LOGIN."""
        gate = _clean_default_gate()
        decision = gate.check_app(
            exe_name="LeagueClientUx.exe",
            window_title="League of Legends Login",
        )
        assert decision.verdict == SafetyVerdict.BLOCK_GAME_LOGIN
        assert "login" in decision.reason.lower()

    def test_allows_notepad(self) -> None:
        """Notepad is not blocked."""
        gate = _clean_default_gate()
        decision = gate.check_app(
            exe_name="notepad.exe",
            window_title="Untitled - Notepad",
        )
        assert decision.verdict == SafetyVerdict.ALLOW

    def test_case_insensitive_exe_match(self) -> None:
        """Blocklist matching is case-insensitive."""
        gate = _clean_default_gate()
        decision = gate.check_app(exe_name="VALORANT-Win64-Shipping.exe")
        assert decision.verdict == SafetyVerdict.BLOCK_UNSUPPORTED

    def test_case_insensitive_title_match(self) -> None:
        """Login keyword matching is case-insensitive."""
        gate = _clean_default_gate()
        decision = gate.check_app(
            exe_name="steam.exe",
            window_title="Steam SIGN IN",
        )
        assert decision.verdict == SafetyVerdict.BLOCK_GAME_LOGIN

    def test_none_exe_allows(self) -> None:
        """None exe_name with no login keywords → ALLOW."""
        gate = _clean_default_gate()
        decision = gate.check_app(window_title="Some Random Window")
        assert decision.verdict == SafetyVerdict.ALLOW

    def test_chinese_login_keyword(self) -> None:
        """Chinese '登录' keyword triggers BLOCK_GAME_LOGIN for recognized exes."""
        gate = _clean_default_gate()
        decision = gate.check_app(
            exe_name="wegame.exe",
            window_title="WeGame 登录",
        )
        assert decision.verdict == SafetyVerdict.BLOCK_GAME_LOGIN


# ── check_action tests ───────────────────────────────────────────────────────


class TestCheckAction:
    """Tests for SafetyGate.check_action()."""

    def test_requires_confirmation_for_delete(self) -> None:
        """delete_file action → REQUIRE_CONFIRMATION."""
        gate = _clean_default_gate()
        decision = gate.check_action("delete_file", "C:/temp/foo.txt")
        assert decision.verdict == SafetyVerdict.REQUIRE_CONFIRMATION
        assert decision.requires_user_confirm is True

    def test_allows_safe_action(self) -> None:
        """click action → ALLOW."""
        gate = _clean_default_gate()
        decision = gate.check_action("click", "Submit button")
        assert decision.verdict == SafetyVerdict.ALLOW
        assert decision.requires_user_confirm is False

    def test_requires_confirmation_for_send(self) -> None:
        """send_message → REQUIRE_CONFIRMATION."""
        gate = _clean_default_gate()
        decision = gate.check_action("send_message")
        assert decision.verdict == SafetyVerdict.REQUIRE_CONFIRMATION

    def test_requires_confirmation_for_transfer(self) -> None:
        """transfer_money → REQUIRE_CONFIRMATION."""
        gate = _clean_default_gate()
        decision = gate.check_action("transfer_money")
        assert decision.verdict == SafetyVerdict.REQUIRE_CONFIRMATION

    def test_none_target_is_ok(self) -> None:
        """None target for check_action is handled gracefully."""
        gate = _clean_default_gate()
        decision = gate.check_action("click", None)
        assert decision.verdict == SafetyVerdict.ALLOW


# ── audit log tests ──────────────────────────────────────────────────────────


class TestAuditLog:
    """Tests for audit log writing."""

    def test_audit_log_written(self, tmp_path: Path) -> None:
        """Multiple checks produce valid JSON lines in audit.log."""
        log_path = tmp_path / "audit.log"
        config = SafetyConfig(audit_log_path=log_path, enable_audit_log=True)
        gate = SafetyGate(config)

        gate.check_app(exe_name="notepad.exe", window_title="Untitled - Notepad")
        gate.check_app(exe_name="steam.exe")
        gate.check_action("click", "button")

        assert log_path.exists()
        lines = log_path.read_text("utf-8").strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            record = json.loads(line)
            assert "timestamp" in record
            assert "verdict" in record
            assert "reason" in record

    def test_audit_log_disabled(self, tmp_path: Path) -> None:
        """When enable_audit_log=False, no file is written."""
        log_path = tmp_path / "audit.log"
        config = SafetyConfig(
            audit_log_path=log_path, enable_audit_log=False
        )
        gate = SafetyGate(config)
        gate.check_app(exe_name="notepad.exe")
        assert not log_path.exists()

    def test_record_event_appends(self, tmp_path: Path) -> None:
        """record_event appends to in-memory log and disk."""
        log_path = tmp_path / "audit.log"
        config = SafetyConfig(audit_log_path=log_path)
        gate = SafetyGate(config)

        event = SafetyEvent(
            timestamp="2025-01-01T00:00:00Z",
            actor="test",
            action_type="test_action",
            target="test_target",
            verdict="ALLOW",
            reason="test reason",
        )
        gate.record_event(event)

        assert log_path.exists()
        lines = log_path.read_text("utf-8").strip().split("\n")
        assert len(lines) == 1


# ── assert_* convenience tests ───────────────────────────────────────────────


class TestAssertFunctions:
    """Tests for assert_app_allowed and assert_action_allowed."""

    def test_assert_app_allowed_raises_unsupported(self) -> None:
        """assert_app_allowed raises UnsupportedAppError for blocked apps."""
        gate = _clean_default_gate()
        with pytest.raises(UnsupportedAppError, match="blocklist"):
            assert_app_allowed(exe_name="steam.exe", gate=gate)

    def test_assert_app_allowed_raises_login(self) -> None:
        """assert_app_allowed raises LoginDetectedError for login screens."""
        gate = _clean_default_gate()
        with pytest.raises(LoginDetectedError, match="login"):
            assert_app_allowed(
                exe_name="steam.exe",
                window_title="Steam Login",
                gate=gate,
            )

    def test_assert_app_allowed_passes_for_notepad(self) -> None:
        """assert_app_allowed does not raise for Notepad."""
        gate = _clean_default_gate()
        # Should not raise.
        assert_app_allowed(
            exe_name="notepad.exe",
            window_title="Untitled - Notepad",
            gate=gate,
        )

    def test_assert_action_allowed_returns_decision(self) -> None:
        """assert_action_allowed returns a SafetyDecision."""
        gate = _clean_default_gate()
        decision = assert_action_allowed("click", "target", gate=gate)
        assert isinstance(decision, SafetyDecision)
        assert decision.verdict == SafetyVerdict.ALLOW


# ── singleton / config tests ─────────────────────────────────────────────────


class TestDefaultGate:
    """Tests for the default_gate singleton."""

    def test_default_gate_lazy_init(self) -> None:
        """Importing safety does NOT create the gate; first call does."""
        # Reset the singleton for this test.
        import agent_uia.safety as s

        with mock.patch.object(s, "_default_gate", None):
            gate1 = s.default_gate()
            gate2 = s.default_gate()
            assert gate1 is gate2

    def test_default_config_has_blocked_exes(self) -> None:
        """Default SafetyConfig has a non-empty blocked_executables set."""
        config = SafetyConfig()
        assert len(config.blocked_executables) >= 20

    def test_config_is_frozen(self) -> None:
        """SafetyConfig is immutable after construction."""
        config = SafetyConfig()
        with pytest.raises(Exception):
            config.blocked_executables = set()  # type: ignore[misc]


class TestSafetyVerdict:
    """Tests for the SafetyVerdict enum."""

    def test_verdict_values_are_distinct(self) -> None:
        """All verdict values are unique."""
        values = [v.value for v in SafetyVerdict]
        assert len(values) == len(set(values))

    def test_all_expected_verdicts_exist(self) -> None:
        """The five expected verdicts are present."""
        names = {v.name for v in SafetyVerdict}
        assert names >= {"ALLOW", "BLOCK_GAME_LOGIN", "BLOCK_UNSUPPORTED",
                          "REQUIRE_CONFIRMATION", "DENY"}
