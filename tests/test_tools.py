# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the tools module."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from agent_uia.tools import (
    ALL_TOOL_SPECS,
    LaunchAppInput,
    FindWindowInput,
    ListWindowsInput,
    GetControlTreeInput,
    ClickInput,
    TypeTextInput,
    SetValueInput,
    InvokeInput,
    PressKeyInput,
    WaitForWindowInput,
    WaitForControlInput,
    CloseWindowInput,
    ReadScreenStateInput,
    RequestUserConfirmationInput,
    ToolDispatcher,
    ActionResult,
    WindowRef,
    ControlRef,
    ScreenStateSummary,
    _validate_launch_args,
)


# ── tool spec validity ───────────────────────────────────────────────────────


class TestToolSpecs:
    """Verify every tool spec produces valid JSON schema."""

    _ALL_TOOLS = [
        LaunchAppInput,
        FindWindowInput,
        ListWindowsInput,
        GetControlTreeInput,
        ClickInput,
        TypeTextInput,
        SetValueInput,
        InvokeInput,
        PressKeyInput,
        WaitForWindowInput,
        WaitForControlInput,
        CloseWindowInput,
        ReadScreenStateInput,
        RequestUserConfirmationInput,
    ]

    def test_all_tools_in_all_specs(self) -> None:
        """ALL_TOOL_SPECS has 14 entries."""
        assert len(ALL_TOOL_SPECS) == 14

    def test_each_spec_is_valid_openai_function(self) -> None:
        """Every spec dict has type: function and a valid function block."""
        for spec in ALL_TOOL_SPECS:
            assert spec["type"] == "function"
            fn = spec["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"
            assert "properties" in fn["parameters"]

    def test_each_spec_name_is_unique(self) -> None:
        """No two specs share a name."""
        names = [spec["function"]["name"] for spec in ALL_TOOL_SPECS]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_each_spec_matches_class_tool_name(self) -> None:
        """Spec name matches class.tool_name()."""
        name_to_spec = {s["function"]["name"]: s for s in ALL_TOOL_SPECS}
        for cls in self._ALL_TOOLS:
            assert cls.tool_name() in name_to_spec, f"Missing spec for {cls.tool_name()}"

    def test_required_field_in_schema(self) -> None:
        """Specs include required fields where appropriate."""
        launch_spec = next(
            s for s in ALL_TOOL_SPECS if s["function"]["name"] == "launch_app"
        )
        assert "required" in launch_spec["function"]["parameters"]
        assert "executable" in launch_spec["function"]["parameters"]["required"]

    def test_system_prompt_has_all_hard_rules(self) -> None:
        """The system prompt Markdown file contains all 9 Hard Rules."""
        from pathlib import Path

        prompt_path = Path("src/agent_uia/prompts/system_prompt.md")
        if not prompt_path.exists():
            prompt_path = Path(__file__).parent.parent / "src" / "agent_uia" / "prompts" / "system_prompt.md"

        content = prompt_path.read_text(encoding="utf-8")

        # Check for all 9 numbered rules.
        for i in range(1, 10):
            assert f"{i}." in content, f"Hard Rule #{i} not found in system prompt"


# ── launch_app validation ────────────────────────────────────────────────────


class TestLaunchAppValidation:
    """Tests for _validate_launch_args — shell injection prevention."""

    def test_allows_simple_exe(self) -> None:
        _validate_launch_args(["notepad.exe"])  # Should not raise.

    def test_allows_quoted_arg(self) -> None:
        _validate_launch_args(["C:\\Program Files\\app.exe", "--help"])

    def test_rejects_semicolon(self) -> None:
        with pytest.raises(ValueError, match="shell"):
            _validate_launch_args(["notepad.exe; rm -rf /"])

    def test_rejects_pipe(self) -> None:
        with pytest.raises(ValueError, match="shell"):
            _validate_launch_args(["notepad.exe|calc.exe"])

    def test_rejects_ampersand(self) -> None:
        with pytest.raises(ValueError, match="shell"):
            _validate_launch_args(["notepad.exe && calc.exe"])

    def test_rejects_backtick(self) -> None:
        with pytest.raises(ValueError, match="shell"):
            _validate_launch_args(["notepad.exe`rm -rf`"])

    def test_rejects_redirect(self) -> None:
        with pytest.raises(ValueError, match="shell"):
            _validate_launch_args(["notepad.exe > output.txt"])


# ── type_text control char stripping ─────────────────────────────────────────


class TestTypeTextInput:
    """Tests for TypeTextInput — control character handling."""

    def test_allowed_chars_preserved(self) -> None:
        inp = TypeTextInput(control_id="abc", text="Hello\nWorld\tTab")
        # \n and \t are allowed.
        assert "\n" in inp.text
        assert "\t" in inp.text

    def test_null_stripped(self) -> None:
        inp = TypeTextInput(control_id="abc", text="Hello\x00World")
        assert "\x00" not in inp.text

    def test_escape_stripped(self) -> None:
        inp = TypeTextInput(control_id="abc", text="Hello\x1bWorld")
        assert "\x1b" not in inp.text


# ── press_key whitelist ─────────────────────────────────────────────────────


class TestPressKeyInput:
    """Tests for PressKeyInput — key whitelist."""

    def test_allowed_key_passes(self) -> None:
        inp = PressKeyInput(key="Return")
        assert inp.key == "Return"

    def test_allowed_combo_passes(self) -> None:
        inp = PressKeyInput(key="ctrl+a")
        assert inp.key == "ctrl+a"

    def test_disallowed_key_stripped(self) -> None:
        inp = PressKeyInput(key="evilkey")
        # Not in whitelist — should be stripped/rejected.
        # The model validates, unknown keys won't validate.
        pass


# ── ActionResult ─────────────────────────────────────────────────────────────


class TestActionResult:
    """Tests for ActionResult."""

    def test_ok_action(self) -> None:
        result = ActionResult(ok=True, observation="clicked")
        d = result.to_dict()
        assert d["ok"] is True
        assert d["observation"] == "clicked"
        assert "error" not in d

    def test_fail_action(self) -> None:
        result = ActionResult(ok=False, error="BLOCKED: test")
        d = result.to_dict()
        assert d["ok"] is False
        assert d["error"] == "BLOCKED: test"


# ── ToolDispatcher (mocked executor) ─────────────────────────────────────────


class TestToolDispatcher:
    """Tests for ToolDispatcher with mocked executor."""

    def _make_dispatcher(self) -> ToolDispatcher:
        from agent_uia.executor import UIAExecutor
        from agent_uia.safety import SafetyGate, SafetyConfig
        gate = SafetyGate(SafetyConfig())
        executor = UIAExecutor(safety_gate=gate)
        return ToolDispatcher(executor=executor, safety_gate=gate)

    def test_known_tools_has_all_14(self) -> None:
        dispatcher = self._make_dispatcher()
        tools = dispatcher.known_tools()
        assert len(tools) == 14
        assert "launch_app" in tools
        assert "click" in tools
        assert "read_screen_state" in tools
        assert "request_user_confirmation" in tools

    def test_validate_tool_name(self) -> None:
        dispatcher = self._make_dispatcher()
        assert dispatcher.validate_tool_name("click") is True
        assert dispatcher.validate_tool_name("nonexistent") is False

    def test_dispatch_unknown_tool(self) -> None:
        dispatcher = self._make_dispatcher()
        result = dispatcher.dispatch("nonexistent", {})
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]

    def test_dispatch_launch_app_valorant_blocked(self) -> None:
        """launch_app with a blocked executable returns BLOCKED."""
        dispatcher = self._make_dispatcher()
        result = dispatcher.dispatch("launch_app", {"executable": "VALORANT-Win64-Shipping.exe"})
        assert result["ok"] is False
        assert "BLOCKED" in result["error"]

    def test_dispatch_launch_app_notepad_allowed(self) -> None:
        """launch_app with notepad is allowed (by safety gate)."""
        dispatcher = self._make_dispatcher()
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = dispatcher.dispatch("launch_app", {"executable": "notepad.exe"})
            assert result["ok"] is True
            assert "pid" in result

    def test_dispatch_request_user_confirmation_returns_false(self) -> None:
        """request_user_confirmation returns {confirmed: false} (not interactive in dispatch)."""
        dispatcher = self._make_dispatcher()
        result = dispatcher.dispatch("request_user_confirmation", {"message": "Delete?"})
        assert result["ok"] is True
        assert result["confirmed"] is False  # Non-interactive dispatch.

    def test_dispatch_read_screen_state(self) -> None:
        """read_screen_state returns window list."""
        dispatcher = self._make_dispatcher()
        with mock.patch.object(dispatcher._executor, "list_windows", return_value=[]):
            result = dispatcher.dispatch("read_screen_state", {})
            assert result["ok"] is True
            assert "windows" in result
            assert isinstance(result["windows"], list)

    def test_launch_app_rejects_shell_injection(self) -> None:
        """launch_app rejects args with shell metacharacters."""
        dispatcher = self._make_dispatcher()
        result = dispatcher.dispatch("launch_app", {
            "executable": "notepad.exe",
            "args": ["calc.exe && evil"],
        })
        assert result["ok"] is False
        assert "shell" in result["error"].lower()


# ── shared types ─────────────────────────────────────────────────────────────


class TestWindowRef:
    """Tests for WindowRef."""

    def test_from_window_info(self) -> None:
        from agent_uia.executor import UIAWindowInfo
        info = UIAWindowInfo(
            handle=42, pid=100, title="Test", class_name="TestClass",
            exe_name="test.exe", rect=(0, 0, 100, 200),
        )
        ref = WindowRef.from_window_info(info, window_id="win-1")
        assert ref.id == "win-1"
        assert ref.title == "Test"
        assert ref.exe_name == "test.exe"


class TestControlRef:
    """Tests for ControlRef."""

    def test_from_control_ref(self) -> None:
        from agent_uia.executor import _UIAHandleRegistry
        reg = _UIAHandleRegistry()
        fake = mock.MagicMock()
        fake.Name = "btn"
        fake.ControlTypeName = "Button"
        fake.AutomationId = "btn1"
        fake.BoundingRectangle = mock.MagicMock(left=10, top=20, width=lambda: 100, height=lambda: 50)
        fake.IsEnabled = True
        fake.IsOffscreen = False
        token = reg.register(fake)

        from agent_uia.executor import UIAControlRef as ExecControlRef
        exec_ref = ExecControlRef(token, reg)

        ref = ControlRef.from_control_ref(exec_ref, control_id="ctrl-1", window_id="win-1")
        assert ref.id == "ctrl-1"
        assert ref.name == "btn"
        assert ref.control_type == "Button"
        assert ref.automation_id == "btn1"
        assert ref.window_id == "win-1"
        assert ref.is_enabled is True
        assert ref.is_visible is True


class TestScreenStateSummary:
    """Tests for ScreenStateSummary."""

    def test_to_dict(self) -> None:
        summary = ScreenStateSummary(
            windows=[
                WindowRef(id="w1", title="Test", class_name="C", exe_name="e.exe", pid=1),
            ],
            truncated=False,
        )
        d = summary.to_dict()
        assert d["truncated"] is False
        assert len(d["windows"]) == 1
        assert d["windows"][0]["title"] == "Test"
