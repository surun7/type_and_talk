# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the ReAct planner module."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

from agent_uia.llm_client import (
    LLMConfig,
    LLMResponse,
    LLMUsage,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolCall,
    UsageLedger,
)
from agent_uia.planner import (
    Planner,
    PlannerConfig,
    TaskResult,
)
from agent_uia.safety import SafetyGate, SafetyConfig
from agent_uia.executor import UIAExecutor


# ── helpers ──────────────────────────────────────────────────────────────────


def _dummy_components():
    """Build a Planner with mocked dependencies."""
    from agent_uia.safety import SafetyGate, SafetyConfig
    from agent_uia.executor import UIAExecutor

    gate = SafetyGate(SafetyConfig())
    executor = UIAExecutor(safety_gate=gate)
    ledger = UsageLedger()

    config = PlannerConfig(
        llm=LLMConfig(api_key="sk-test", max_retries=0),  # type: ignore[arg-type]
        max_steps=5,
        max_cost_usd_per_task=Decimal("1.00"),
        system_prompt_file=Path("src/agent_uia/prompts/system_prompt.md"),
        enable_streaming=False,
    )

    planner = Planner(
        config=config,
        executor=executor,
        safety_gate=gate,
        usage_ledger=ledger,
    )
    return planner, gate, executor, ledger, config


def _make_llm_response(
    *,
    content: str = "",
    tool_calls: list[tuple[str, str, dict]] | None = None,
) -> LLMResponse:
    """Build a mock LLMResponse."""
    tcs = None
    if tool_calls:
        tcs = [
            ToolCall(id=f"call_{i}", name=name, arguments=args)
            for i, (name, _, args) in enumerate(tool_calls)
        ]
    return LLMResponse(
        message=AssistantMessage(content=content, tool_calls=tcs),
        usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15,
                       estimated_cost_usd=Decimal("0.00001")),
        finish_reason="tool_calls" if tcs else "stop",
    )


# ── planner tests ────────────────────────────────────────────────────────────


class TestPlannerBasic:
    """Tests for basic planner flow."""

    @pytest.mark.asyncio
    async def test_success_flow(self) -> None:
        """Planner stops on final answer with no tool calls."""
        planner, gate, executor, ledger, config = _dummy_components()

        call_count = 0

        async def mock_chat(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First turn: call a tool.
                return _make_llm_response(
                    tool_calls=[("read_screen_state", "read", {})]
                )
            else:
                # Second turn: final answer.
                return _make_llm_response(content="Done. Notepad is open.")

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ), mock.patch("agent_uia.planner.LLMClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.chat.side_effect = mock_chat

            with mock.patch.object(
                planner, "_run_loop",
                wraps=planner._run_loop,
            ) as _:
                # Directly replace llm client.
                result = await _run_planner_with_mock_llm(
                    planner, mock_chat, "Open Notepad"
                )

        assert result.status == "success"
        assert "Done" in result.user_facing_message
        assert result.steps_taken <= 5

    @pytest.mark.asyncio
    async def test_max_steps_guard(self) -> None:
        """Planner stops after max_steps."""
        planner, gate, executor, ledger, config = _dummy_components()
        config_dict = config.model_dump()
        config_dict["max_steps"] = 3
        new_config = PlannerConfig(**config_dict)  # type: ignore[arg-type]
        planner = Planner(
            config=new_config,
            executor=executor,
            safety_gate=gate,
            usage_ledger=ledger,
        )

        async def always_tool_call(messages, tools=None):
            return _make_llm_response(
                tool_calls=[("read_screen_state", "read", {})]
            )

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ):
            result = await _run_planner_with_mock_llm(
                planner, always_tool_call, "Do something"
            )

        assert result.status == "max_steps_exceeded"

    @pytest.mark.asyncio
    async def test_budget_guard(self) -> None:
        """Planner stops when cost exceeds budget."""
        planner, gate, executor, ledger, config = _dummy_components()

        # Set budget very low.
        config_dict = config.model_dump()
        config_dict["max_cost_usd_per_task"] = Decimal("0.000001")
        new_config = PlannerConfig(**config_dict)  # type: ignore[arg-type]
        planner = Planner(
            config=new_config,
            executor=executor,
            safety_gate=gate,
            usage_ledger=ledger,
        )

        # This response has cost $0.00001 which exceeds budget.
        async def expensive_call(messages, tools=None):
            return _make_llm_response(
                tool_calls=[("read_screen_state", "read", {})]
            )

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ):
            result = await _run_planner_with_mock_llm(
                planner, expensive_call, "Do something"
            )

        assert result.status == "budget_exceeded"

    @pytest.mark.asyncio
    async def test_block_propagation(self) -> None:
        """When a tool returns BLOCKED, the next LLM turn sees it and can abort."""
        planner, gate, executor, ledger, config = _dummy_components()

        call_count = 0

        async def mock_chat(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[("launch_app", "launch",
                                {"executable": "VALORANT-Win64-Shipping.exe"})]
                )
            else:
                # LLM should see the BLOCK and produce a final answer.
                return _make_llm_response(
                    content="Cannot launch VALORANT. This app is blocked."
                )

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ):
            result = await _run_planner_with_mock_llm(
                planner, mock_chat, "Launch VALORANT"
            )

        # The BLOCK is detected, LLM produces final answer.
        assert "blocked" in result.user_facing_message.lower() or \
               "cannot" in result.user_facing_message.lower()

    @pytest.mark.asyncio
    async def test_dispatch_order(self) -> None:
        """The planner dispatches tool calls in order and appends tool messages."""
        planner, gate, executor, ledger, config = _dummy_components()

        call_count = 0

        async def mock_chat(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[("launch_app", "launch", {"executable": "notepad.exe"})]
                )
            elif call_count == 2:
                return _make_llm_response(
                    tool_calls=[("read_screen_state", "read", {})]
                )
            else:
                return _make_llm_response(content="All done!")

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ), mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = await _run_planner_with_mock_llm(
                planner, mock_chat, "Open Notepad and check screen"
            )

        assert result.status == "success"
        assert result.steps_taken == 3
        assert len(result.transcript) > 0

    @pytest.mark.asyncio
    async def test_unknown_tool_handled(self) -> None:
        """When LLM calls an unknown tool, it's handled gracefully."""
        planner, gate, executor, ledger, config = _dummy_components()

        async def mock_chat(messages, tools=None):
            # LLM calls a tool not in the registry, then gives final answer.
            return _make_llm_response(
                tool_calls=[("nonexistent_tool", "bad", {})]
            )

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ):
            result = await _run_planner_with_mock_llm(
                planner, mock_chat, "Do something bad"
            )

        # Should hit max_steps since unknown tool never satisfies task.
        # But it won't crash.
        assert result.status in ("max_steps_exceeded",)

    @pytest.mark.asyncio
    async def test_event_callbacks_fired(self) -> None:
        """on_event callback receives all event types."""
        planner, gate, executor, ledger, config = _dummy_components()
        events = []

        async def on_event(event):
            events.append(type(event).__name__)

        async def mock_chat(messages, tools=None):
            return _make_llm_response(content="Done.")

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ):
            result = await _run_planner_with_mock_llm(
                planner, mock_chat, "Hi", on_event=on_event,
            )

        assert "StepStarted" in events
        assert "LLMCalled" in events
        assert "FinalAnswerReady" in events

    @pytest.mark.asyncio
    async def test_planner_timeout(self) -> None:
        """Planner respects the overall timeout."""
        planner, gate, executor, ledger, config = _dummy_components()
        config_dict = config.model_dump()
        config_dict["planner_timeout_s"] = 0.1
        new_config = PlannerConfig(**config_dict)  # type: ignore[arg-type]
        planner = Planner(
            config=new_config,
            executor=executor,
            safety_gate=gate,
            usage_ledger=ledger,
        )

        async def slow_chat(messages, tools=None):
            await asyncio.sleep(1.0)
            return _make_llm_response(content="Done.")

        with mock.patch.object(
            planner, "_load_system_prompt", return_value="You are TNT."
        ):
            result = await _run_planner_with_mock_llm(
                planner, slow_chat, "Do something"
            )

        assert result.status == "failed"
        assert "too long" in result.user_facing_message.lower()


# ── helper to run planner with mocked LLMClient.chat ──────────────────────────


async def _run_planner_with_mock_llm(
    planner: Planner,
    mock_chat_fn,
    instruction: str,
    on_event=None,
) -> TaskResult:
    """Run the planner with a mocked LLMClient.chat, using the real ToolDispatcher."""

    async def _patched_run_loop(**kwargs):
        """Intercepts _run_loop to inject the mock chat."""
        llm = kwargs["llm"]
        # Patch the client's chat method.
        llm.chat = mock_chat_fn  # type: ignore[method-assign]
        return await Planner._run_loop(planner, **kwargs)

    with mock.patch.object(planner, "_run_loop", _patched_run_loop):
        return await planner.run(instruction, on_event=on_event)
