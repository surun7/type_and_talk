# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the UIA executor module.

These tests mock ``uiautomation`` to avoid requiring a real desktop.
"""

from __future__ import annotations

from unittest import mock

import pytest

from agent_uia.executor import (
    UIAControlNode,
    UIAControlRef,
    UIAExecutor,
    UIAWindowInfo,
    _UIAHandleRegistry,
)
from agent_uia.safety import (
    SafetyConfig,
    SafetyGate,
    UnsupportedAppError,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _dummy_gate() -> SafetyGate:
    """Return a SafetyGate that allows everything (notepad defaults)."""
    return SafetyGate(SafetyConfig())


def _make_dummy_window() -> UIAWindowInfo:
    """Return a dummy UIAWindowInfo for testing."""
    return UIAWindowInfo(
        handle=12345,
        pid=9999,
        title="Test Window",
        class_name="TestClass",
        exe_name="notepad.exe",
        rect=(0, 0, 800, 600),
    )


# ── UIAHandleRegistry tests ──────────────────────────────────────────────────


class TestHandleRegistry:
    """Tests for the internal _UIAHandleRegistry."""

    def test_register_and_get(self) -> None:
        """Register an object and retrieve it by token."""
        reg = _UIAHandleRegistry()
        obj = {"name": "test"}
        token = reg.register(obj)
        retrieved = reg.get(token)
        assert retrieved is obj

    def test_get_missing_token(self) -> None:
        """Getting an unknown token returns None."""
        reg = _UIAHandleRegistry()
        assert reg.get("nonexistent") is None

    def test_get_collected_object(self) -> None:
        """Getting a garbage-collected object returns None."""
        reg = _UIAHandleRegistry()

        class _Ephemeral:
            pass

        obj = _Ephemeral()
        token = reg.register(obj)
        del obj
        # The weakref should now be dead.
        assert reg.get(token) is None

    def test_cleanup_removes_dead_entries(self) -> None:
        """cleanup() removes entries whose referent is dead."""
        reg = _UIAHandleRegistry()
        obj = {"value": 42}
        reg.register(obj)
        del obj
        removed = reg.cleanup()
        assert removed >= 1

    def test_tokens_are_unique(self) -> None:
        """Each register call returns a distinct token."""
        reg = _UIAHandleRegistry()
        t1 = reg.register({})
        t2 = reg.register({})
        assert t1 != t2


# ── UIAControlRef tests ──────────────────────────────────────────────────────


class TestUIAControlRef:
    """Tests for the opaque UIAControlRef."""

    def test_no_raw_uia_attributes_exposed(self) -> None:
        """UIAControlRef does NOT expose any attribute starting with _uia_ in dir()."""
        reg = _UIAHandleRegistry()
        fake_obj = mock.MagicMock()
        fake_obj.Name = "TestControl"
        fake_obj.ControlTypeName = "Button"
        fake_obj.AutomationId = "btn1"
        fake_obj.ClassName = "ButtonClass"
        fake_obj.BoundingRectangle = mock.MagicMock(
            left=10, top=20, width=lambda: 100, height=lambda: 50
        )
        fake_obj.IsEnabled = True
        fake_obj.IsOffscreen = False

        token = reg.register(fake_obj)
        ref = UIAControlRef(token, reg)

        # Public attributes ok.
        assert ref.name == "TestControl"
        assert ref.control_type == "Button"
        assert ref.automation_id == "btn1"

        # Verify _uia_* not in dir() — only _uia (private) is there.
        public_attrs = [a for a in dir(ref) if not a.startswith("_")]
        for attr in public_attrs:
            assert not attr.startswith("_uia_"), (
                f"Leaked raw UIA attribute: {attr}"
            )

    def test_get_text_from_value_pattern(self) -> None:
        """get_text reads ValuePattern.Value when available."""
        reg = _UIAHandleRegistry()
        fake_obj = mock.MagicMock()
        fake_vp = mock.MagicMock()
        fake_vp.Value = "hello world"
        fake_obj.GetValuePattern.return_value = fake_vp
        fake_obj.Name = "fallback"

        token = reg.register(fake_obj)
        ref = UIAControlRef(token, reg)
        assert ref.get_text() == "hello world"

    def test_get_text_falls_back_to_name(self) -> None:
        """get_text falls back to Name when ValuePattern unavailable."""
        reg = _UIAHandleRegistry()
        fake_obj = mock.MagicMock()
        fake_obj.GetValuePattern.return_value = None
        fake_obj.Name = "fallback_name"

        token = reg.register(fake_obj)
        ref = UIAControlRef(token, reg)
        assert ref.get_text() == "fallback_name"

    def test_rect_from_bounding_rectangle(self) -> None:
        """rect property decomposes BoundingRectangle correctly."""
        reg = _UIAHandleRegistry()
        fake_obj = mock.MagicMock()
        fake_rect = mock.MagicMock()
        fake_rect.left = 10
        fake_rect.top = 20
        fake_rect.width.return_value = 300
        fake_rect.height.return_value = 200
        fake_obj.BoundingRectangle = fake_rect

        token = reg.register(fake_obj)
        ref = UIAControlRef(token, reg)
        assert ref.rect == (10, 20, 300, 200)


# ── UIAControlNode tests ─────────────────────────────────────────────────────


class TestUIAControlNode:
    """Tests for the UIAControlNode tree type."""

    def test_to_compact_dict(self) -> None:
        """to_compact_dict returns a JSON-friendly tree representation."""
        reg = _UIAHandleRegistry()
        fake_root = mock.MagicMock()
        fake_root.Name = "root"
        fake_root.ControlTypeName = "Window"
        fake_root.AutomationId = ""
        fake_rect = mock.MagicMock(left=0, top=0, width=lambda: 100, height=lambda: 100)
        fake_root.BoundingRectangle = fake_rect

        root_token = reg.register(fake_root)
        root_ref = UIAControlRef(root_token, reg)
        root_node = UIAControlNode(ref=root_ref, depth=0)

        fake_child = mock.MagicMock()
        fake_child.Name = "child"
        fake_child.ControlTypeName = "Button"
        fake_child.AutomationId = "btn"
        fake_child.BoundingRectangle = fake_rect
        child_token = reg.register(fake_child)
        child_ref = UIAControlRef(child_token, reg)
        child_node = UIAControlNode(ref=child_ref, depth=1)
        root_node.children.append(child_node)

        d = root_node.to_compact_dict()
        assert d["name"] == "root"
        assert d["control_type"] == "Window"
        assert d["depth"] == 0
        assert len(d["children"]) == 1
        assert d["children"][0]["name"] == "child"
        assert d["children"][0]["depth"] == 1


# ── UIAExecutor tests (mocked uiautomation) ──────────────────────────────────


class TestUIAExecutorSafetyEnforcement:
    """Verify safety gate is called before any UIA action."""

    def test_safety_called_before_click(self) -> None:
        """click calls the safety gate first."""
        with mock.patch(
            "agent_uia.executor.assert_app_allowed"
        ) as mock_assert:
            mock_assert.side_effect = UnsupportedAppError("blocked")
            executor = UIAExecutor(safety_gate=_dummy_gate())
            reg = executor._registry  # noqa: SLF001
            fake_obj = mock.MagicMock()
            token = reg.register(fake_obj)
            ref = UIAControlRef(token, reg)

            with pytest.raises(UnsupportedAppError):
                executor.click(ref)

            mock_assert.assert_called_once()

    def test_click_blocked_by_safety(self) -> None:
        """click raises if safety gate blocks the target app."""
        gate = _dummy_gate()
        executor = UIAExecutor(safety_gate=gate)
        reg = executor._registry  # noqa: SLF001
        fake_obj = mock.MagicMock()
        token = reg.register(fake_obj)
        ref = UIAControlRef(token, reg)

        with mock.patch.object(gate, "check_app") as mock_check:
            from agent_uia.safety import SafetyDecision, SafetyVerdict
            mock_check.return_value = SafetyDecision(
                verdict=SafetyVerdict.BLOCK_UNSUPPORTED,
                reason="blocked",
            )
            with pytest.raises(UnsupportedAppError):
                executor.click(ref)

    def test_set_value_safety_called(self) -> None:
        """set_value calls the safety gate."""
        with mock.patch(
            "agent_uia.executor.assert_app_allowed"
        ) as mock_assert:
            executor = UIAExecutor(safety_gate=_dummy_gate())
            reg = executor._registry  # noqa: SLF001
            fake_obj = mock.MagicMock()
            fake_vp = mock.MagicMock()
            fake_obj.GetValuePattern.return_value = fake_vp
            token = reg.register(fake_obj)
            ref = UIAControlRef(token, reg)

            executor.set_value(ref, "test")
            mock_assert.assert_called()

    def test_invoke_safety_called(self) -> None:
        """invoke calls the safety gate."""
        with mock.patch(
            "agent_uia.executor.assert_app_allowed"
        ) as mock_assert:
            executor = UIAExecutor(safety_gate=_dummy_gate())
            reg = executor._registry  # noqa: SLF001
            fake_obj = mock.MagicMock()
            fake_ip = mock.MagicMock()
            fake_obj.GetInvokePattern.return_value = fake_ip
            token = reg.register(fake_obj)
            ref = UIAControlRef(token, reg)

            executor.invoke(ref)
            mock_assert.assert_called()


class TestUIAExecutorWindowOps:
    """Tests for window discovery methods (mocked)."""

    def test_find_window_returns_none_on_timeout(self) -> None:
        """find_window returns None when no window matches."""
        executor = UIAExecutor(safety_gate=_dummy_gate())
        with mock.patch.object(
            executor,
            "_iter_top_level_windows",
            return_value=[],
        ):
            result = executor.find_window(
                title_contains="NonexistentWindow",
                timeout=0.5,
            )
        assert result is None

    def test_wait_for_window_raises_timeout(self) -> None:
        """wait_for_window raises TimeoutError on timeout."""
        executor = UIAExecutor(safety_gate=_dummy_gate())
        with mock.patch.object(
            executor,
            "_iter_top_level_windows",
            return_value=[],
        ):
            with pytest.raises(TimeoutError, match="Timed out"):
                executor.wait_for_window(
                    title_contains="NonexistentWindow",
                    timeout=0.5,
                )

    def test_list_windows_empty(self) -> None:
        """list_windows returns empty list when no windows."""
        executor = UIAExecutor(safety_gate=_dummy_gate())
        with mock.patch.object(
            executor,
            "_iter_top_level_windows",
            return_value=[],
        ):
            result = executor.list_windows()
        assert result == []

    def test_wait_for_control_raises_timeout(self) -> None:
        """wait_for_control raises TimeoutError when no control found."""
        executor = UIAExecutor(safety_gate=_dummy_gate())
        window = _make_dummy_window()

        with mock.patch.object(
            executor,
            "_find_control_in",
            return_value=None,
        ):
            with pytest.raises(TimeoutError, match="Timed out"):
                executor.wait_for_control(
                    window,
                    name_contains="Missing",
                    timeout=0.5,
                )


class TestUIAWindowInfo:
    """Tests for the UIAWindowInfo dataclass."""

    def test_is_frozen(self) -> None:
        """UIAWindowInfo is immutable."""
        info = _make_dummy_window()
        with pytest.raises(Exception):
            info.title = "new"  # type: ignore[misc]

    def test_fields_accessible(self) -> None:
        """All expected fields are present."""
        info = _make_dummy_window()
        assert info.handle == 12345
        assert info.pid == 9999
        assert info.title == "Test Window"
        assert info.class_name == "TestClass"
        assert info.exe_name == "notepad.exe"
        assert info.rect == (0, 0, 800, 600)
