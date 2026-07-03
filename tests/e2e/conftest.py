# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Type & Talk authors

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_uia.safety import SafetyConfig, SafetyGate
from agent_uia.skills.loader import default_registry
from agent_uia.tools.dispatcher import ToolDispatcher


class FakeExecutor:
    """A fake UIA executor that returns canned responses for all tools."""

    def __init__(self) -> None:
        self.canned: dict[str, object] = {}
        self.calls: list[dict[str, object]] = []

    def set_canned(self, tool: str, response: object) -> None:
        self.canned[tool] = response

    def execute(self, tool: str, args: dict[str, object] | None = None) -> object:
        self.calls.append({"tool": tool, "args": args or {}})
        if tool in self.canned:
            return self.canned[tool]
        return None

    def assert_tool_called(self, tool: str) -> bool:
        return any(c["tool"] == tool for c in self.calls)

    def assert_tool_called_with(self, tool: str, **expected_args: object) -> bool:
        return any(
            c["tool"] == tool and c["args"] == expected_args
            for c in self.calls
        )


@pytest.fixture
def mock_executor() -> FakeExecutor:
    """A fake executor that returns canned responses for all tools."""
    return FakeExecutor()


@pytest.fixture
def mock_dispatcher(mock_executor: FakeExecutor) -> ToolDispatcher:
    """ToolDispatcher with mocked executor."""
    return ToolDispatcher(executor=mock_executor)


@pytest.fixture
def mock_safety() -> SafetyGate:
    """SafetyGate with SafetyConfig that allows everything."""
    config = SafetyConfig(
        blocked_executables=set(),
        login_window_keywords=set(),
        always_confirm_actions=set(),
    )
    return SafetyGate(config)


@pytest.fixture
def skill_registry():
    """default_registry() with all builtin skills loaded."""
    return default_registry()
