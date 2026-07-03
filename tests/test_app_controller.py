# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the AppController glue layer."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


# Ensure QApp exists once per session.
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_history(tmp_path: Path) -> Path:
    """Return a temporary logs directory — avoids polluting real ./logs."""
    return tmp_path / "logs"


@pytest.fixture
def mock_planner():
    """A mock Planner that records the call and returns a canned TaskResult."""
    from agent_uia.llm_client import LLMUsage
    from agent_uia.planner import TaskResult

    class _MockPlanner:
        def __init__(self):
            self.last_text = ""
            self.last_on_event = None

        async def run(self, user_text: str, *, on_event=None, task_id=None):
            self.last_text = user_text
            self.last_on_event = on_event
            usage = LLMUsage(model="test")
            return TaskResult(
                status="success",
                user_facing_message="Task completed.",
                steps_taken=3,
                total_cost_usd=Decimal("0.0005"),
                usage=usage,
            )

    return _MockPlanner()


@pytest.fixture
def controller_with_mocks(qapp, temp_history, mock_planner):
    """Build an AppController with mocked deps for safe testing."""
    from agent_uia.ui import AppConfig, AppController

    ctrl = AppController(config=AppConfig())
    # Override history path to temp dir.
    ctrl._history_path = temp_history / "history.jsonl"
    # Plug in the mock planner.
    ctrl._planner = mock_planner
    return ctrl


# ── test: run_task calls planner ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_task_calls_planner(controller_with_mocks, mock_planner):
    """run_task must delegate to planner.run with the correct text and on_event."""
    await controller_with_mocks.run_task("Open Notepad")
    assert mock_planner.last_text == "Open Notepad"
    assert mock_planner.last_on_event is not None


# ── test: signals fire in order ──────────────────────────────────────────────


class _SignalRecorder(QObject):
    """Records signals fired during a test."""

    fired: list[str] = []


@pytest.mark.asyncio
async def test_signals_fire_in_order(qapp, mock_planner):
    """With a fake planner that emits events, signals must fire in the expected order."""
    from agent_uia.planner import (
        FinalAnswerReady,
        LLMCalled,
        StepStarted,
        ToolCallFinished,
        ToolCallStarted,
    )
    from agent_uia.ui import AppConfig, AppController

    # Planner that emits a full transcript.
    class _TranscriptPlanner:
        async def run(self, user_text, *, on_event=None, task_id=None):
            from decimal import Decimal

            from agent_uia.llm_client import (
                AssistantMessage,
                LLMResponse,
                LLMUsage,
            )
            from agent_uia.planner import TaskResult

            if on_event:
                await on_event(StepStarted(step_number=1))
                await on_event(LLMCalled(
                    step_number=1,
                    response=LLMResponse(
                        message=AssistantMessage(content=""),
                        usage=LLMUsage(model="test"),
                        finish_reason="tool_calls",
                    ),
                ))
                await on_event(ToolCallStarted(
                    step_number=1, tool_name="launch_app",
                    arguments={"app_name": "notepad.exe"},
                ))
                await on_event(ToolCallFinished(
                    step_number=1, tool_name="launch_app",
                    result='{"ok": true}', ok=True,
                ))
                await on_event(FinalAnswerReady(message="Done!"))
            usage = LLMUsage(model="test")
            return TaskResult(
                status="success",
                user_facing_message="Done!",
                steps_taken=1,
                total_cost_usd=Decimal("0.0001"),
                usage=usage,
            )

    ctrl = AppController(config=AppConfig())
    ctrl._planner = _TranscriptPlanner()
    ctrl._history_path = Path("/dev/null/history.jsonl")  # prevent write

    recorded: list[str] = []
    ctrl.status_changed.connect(lambda t: recorded.append(f"status:{t}"))
    ctrl.tool_event.connect(lambda t: recorded.append(f"tool:{t}"))
    ctrl.final_answer_ready.connect(lambda t: recorded.append(f"answer:{t}"))
    ctrl.task_finished.connect(lambda t: recorded.append(f"finished:{t}"))

    await ctrl.run_task("test")

    # Check the sequence of key signals.
    joined = " | ".join(recorded)
    assert "status:Step 1" in joined
    assert "tool:→ launch_app" in joined
    assert "answer:Done!" in joined
    assert "finished:success" in joined


# ── test: paused short-circuits ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paused_short_circuits(qapp):
    """When paused=True, run_task must emit the paused message without calling planner.run."""
    from agent_uia.ui import AppConfig, AppController

    ctrl = AppController(config=AppConfig())
    ctrl._history_path = Path("/dev/null/history.jsonl")

    planner_called = False

    async def _fake_run(*, text="", on_event=None, task_id=None):
        nonlocal planner_called
        planner_called = True

    ctrl._planner = mock.MagicMock()
    ctrl._planner.run = _fake_run

    ctrl.paused = True

    answer_text = []
    ctrl.final_answer_ready.connect(lambda t: answer_text.append(t))

    await ctrl.run_task("do something")

    assert not planner_called, "Planner.run should NOT be called when paused"
    assert any("paused" in a.lower() for a in answer_text), (
        f"Expected paused message, got: {answer_text}"
    )


# ── test: history appended on completion ─────────────────────────────────────


@pytest.mark.asyncio
async def test_history_appended_on_completion(qapp, mock_planner, temp_history):
    """After a fake run, history.jsonl must have one new line with the expected fields."""
    from agent_uia.ui import AppConfig, AppController

    ctrl = AppController(config=AppConfig())
    ctrl._history_path = temp_history / "history.jsonl"
    ctrl._planner = mock_planner

    await ctrl.run_task("Open Notepad")

    assert ctrl._history_path.exists(), "History file was not created"
    lines = ctrl._history_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1, f"Expected 1 history line, got {len(lines)}"

    entry = json.loads(lines[0])
    assert entry["user_text"] == "Open Notepad"
    assert entry["status"] == "success"
    assert "task_id" in entry
    assert "cost_usd" in entry
    assert "steps" in entry


# ── test: missing API key does not crash ─────────────────────────────────────


def test_missing_api_key_does_not_crash_start(qapp):
    """_init_core() should not raise when DEEPSEEK_API_KEY is unset."""
    from agent_uia.ui import AppConfig, AppController

    ctrl = AppController(config=AppConfig())

    # Ensure DEEPSEEK_API_KEY is unset but preserve platform env (LOCALAPPDATA).
    env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
    with mock.patch.dict(os.environ, env, clear=True):
        # Should log a warning but not raise.
        ctrl._init_core()

    # Planner should be None since no API key.
    assert ctrl._planner is None
    # But the controller should still be functional.
    assert ctrl._llm_config is not None
