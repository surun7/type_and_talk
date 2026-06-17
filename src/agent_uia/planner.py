# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""ReAct planner — the LLM reasoning loop.

The Planner orchestrates the LLM ↔ executor interaction: it maintains the
conversation, dispatches tool calls, records results, and enforces safety
and budget guards.
"""

from __future__ import annotations

import json
import asyncio
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from loguru import logger
from pydantic import BaseModel, Field

from agent_uia.llm_client import (
    LLMClient,
    LLMConfig,
    LLMMessage,
    LLMResponse,
    LLMUsage,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage,
    ToolCall,
    UsageLedger,
)
from agent_uia.tools import (
    ALL_TOOL_SPECS,
    ToolDispatcher,
)
from agent_uia.safety import SafetyGate
from agent_uia.executor import UIAExecutor

__all__ = [
    "PlannerConfig",
    "TaskResult",
    "Planner",
    "PlannerEvent",
    "StepStarted",
    "LLMCalled",
    "ToolCallStarted",
    "ToolCallFinished",
    "FinalAnswerReady",
]


# ── config ───────────────────────────────────────────────────────────────────


class PlannerConfig(BaseModel):
    """Configuration for the ReAct planner.

    Fields:
        llm: LLM client configuration.
        max_steps: Maximum ReAct loop iterations (default 20).
        max_cost_usd_per_task: Maximum USD cost per task (default $0.10).
        system_prompt_file: Path to the Markdown system prompt.
        enable_streaming: Whether to stream LLM responses.
        planner_timeout_s: Overall timeout for a single task (default 120s).
    """

    model_config = {"frozen": True}

    llm: LLMConfig = Field(default_factory=LLMConfig)
    max_steps: int = 20
    max_cost_usd_per_task: Decimal = Field(default_factory=lambda: Decimal("0.10"))
    system_prompt_file: Path = Field(
        default=Path("src/agent_uia/prompts/system_prompt.md")
    )
    enable_streaming: bool = True
    planner_timeout_s: float = 120.0


# ── events ───────────────────────────────────────────────────────────────────


@dataclass
class StepStarted:
    """Fired at the top of each ReAct loop iteration."""

    step_number: int


@dataclass
class LLMCalled:
    """Fired after the LLM responds."""

    step_number: int
    response: LLMResponse


@dataclass
class ToolCallStarted:
    """Fired before a tool is dispatched."""

    step_number: int
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ToolCallFinished:
    """Fired after a tool returns."""

    step_number: int
    tool_name: str
    result: str
    ok: bool


@dataclass
class FinalAnswerReady:
    """Fired when the planner has a final answer for the user."""

    message: str


# Union type for event callbacks.
PlannerEvent = StepStarted | LLMCalled | ToolCallStarted | ToolCallFinished | FinalAnswerReady


# ── task result ──────────────────────────────────────────────────────────────


@dataclass
class TaskResult:
    """The outcome of a planning task.

    Attributes:
        status: ``"success"``, ``"failed"``, ``"blocked"``, ``"budget_exceeded"``,
            or ``"max_steps_exceeded"``.
        user_facing_message: The final message to show the user.
        steps_taken: Number of ReAct loop iterations.
        total_cost_usd: Total estimated USD cost.
        usage: Aggregated token usage.
        transcript: Full message history.
    """

    status: Literal[
        "success", "failed", "blocked", "budget_exceeded", "max_steps_exceeded"
    ]
    user_facing_message: str
    steps_taken: int
    total_cost_usd: Decimal
    usage: LLMUsage
    transcript: list[LLMMessage] = field(default_factory=list)


# ── planner ──────────────────────────────────────────────────────────────────


class Planner:
    """The ReAct reasoning loop.

    This is the brain of TNT. It:
    1. Loads the system prompt.
    2. Maintains the conversation with the LLM.
    3. Validates and dispatches tool calls to the ``ToolDispatcher``.
    4. Feeds tool results back to the LLM.
    5. Enforces max-steps and budget guards.
    6. Propagates BLOCK verdicts to the user.

    Args:
        config: Planner configuration.
        executor: The UIA executor (hands).
        safety_gate: The immutable safety gate (frontline).
        usage_ledger: Thread-safe cost tracker.
    """

    def __init__(
        self,
        config: PlannerConfig,
        executor: UIAExecutor,
        safety_gate: SafetyGate,
        usage_ledger: UsageLedger,
    ) -> None:
        self._config = config
        self._executor = executor
        self._safety = safety_gate
        self._ledger = usage_ledger

    # -- run -------------------------------------------------------------------

    async def run(
        self,
        user_instruction: str,
        *,
        on_event: Callable[[PlannerEvent], Awaitable[None]] | None = None,
        task_id: str | None = None,
    ) -> TaskResult:
        """Execute a user instruction through the ReAct loop.

        Args:
            user_instruction: The natural-language task.
            on_event: Optional async callback for progress events.
            task_id: Optional task identifier for usage tracking.

        Returns:
            A ``TaskResult`` with the outcome.
        """
        tid = task_id or str(uuid.uuid4())[:8]

        # 1. Load system prompt.
        system_prompt = self._load_system_prompt()

        # 2. Build initial message list.
        messages: list[LLMMessage] = [
            SystemMessage(content=system_prompt),
            UserMessage(content=user_instruction),
        ]

        # 3. Build LLM client.
        llm = LLMClient(config=self._config.llm, usage_ledger=self._ledger)

        # 4. Build tool dispatcher.
        tool_specs = _build_openai_tool_specs()
        dispatcher = ToolDispatcher(
            executor=self._executor, safety_gate=self._safety
        )

        # 5. Get starting cost for budget tracking.
        cost_before = self._ledger.total_cost()

        total_usage = LLMUsage(model=self._config.llm.model)
        blocked = False

        try:
            result = await asyncio.wait_for(
                self._run_loop(
                    llm=llm,
                    messages=messages,
                    tool_specs=tool_specs,
                    dispatcher=dispatcher,
                    cost_before=cost_before,
                    total_usage=total_usage,
                    on_event=on_event,
                ),
                timeout=self._config.planner_timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Planner timed out after {self._config.planner_timeout_s}s")
            return TaskResult(
                status="failed",
                user_facing_message=(
                    "The task took too long and was stopped. "
                    "Try breaking it into smaller steps."
                ),
                steps_taken=0,
                total_cost_usd=self._ledger.total_cost() - cost_before,
                usage=total_usage,
                transcript=messages,
            )

    # -- internal loop ---------------------------------------------------------

    async def _run_loop(
        self,
        *,
        llm: LLMClient,
        messages: list[LLMMessage],
        tool_specs: list[dict[str, Any]],
        dispatcher: ToolDispatcher,
        cost_before: Decimal,
        total_usage: LLMUsage,
        on_event: Callable[[PlannerEvent], Awaitable[None]] | None,
    ) -> TaskResult:
        """The core ReAct loop."""
        blocked = False
        steps_taken = 0

        for step in range(self._config.max_steps):
            steps_taken = step + 1

            if on_event:
                await on_event(StepStarted(step_number=steps_taken))

            # Budget guard.
            cost_so_far = self._ledger.total_cost() - cost_before
            if cost_so_far >= self._config.max_cost_usd_per_task:
                logger.warning(
                    f"Budget exceeded: ${cost_so_far} >= ${self._config.max_cost_usd_per_task}"
                )
                return TaskResult(
                    status="budget_exceeded",
                    user_facing_message=(
                        f"Task budget exceeded (${cost_so_far:.4f} of "
                        f"${self._config.max_cost_usd_per_task} limit). "
                        "The task was stopped to prevent excessive cost."
                    ),
                    steps_taken=steps_taken,
                    total_cost_usd=cost_so_far,
                    usage=total_usage,
                    transcript=messages,
                )

            # Call LLM.
            response = await llm.chat(messages, tools=tool_specs)
            messages.append(response.message)
            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens
            total_usage.total_tokens += response.usage.total_tokens
            total_usage.estimated_cost_usd += response.usage.estimated_cost_usd

            if on_event:
                await on_event(LLMCalled(step_number=steps_taken, response=response))

            # No tool calls → final answer.
            if not response.message.tool_calls:
                message_text = response.message.content or "Task completed."
                if on_event:
                    await on_event(FinalAnswerReady(message=message_text))
                cost_final = self._ledger.total_cost() - cost_before
                return TaskResult(
                    status="blocked" if blocked else "success",
                    user_facing_message=message_text,
                    steps_taken=steps_taken,
                    total_cost_usd=cost_final,
                    usage=total_usage,
                    transcript=messages,
                )

            # Dispatch tool calls (one per turn in practice, but handle multiple).
            for tc in response.message.tool_calls:
                if on_event:
                    await on_event(
                        ToolCallStarted(
                            step_number=steps_taken,
                            tool_name=tc.name,
                            arguments=tc.arguments,
                        )
                    )

                # Validate tool name.
                if tc.name not in dispatcher.known_tools():
                    result_str = json.dumps(
                        {"ok": False, "error": f"Unknown tool: {tc.name}"}
                    )
                    logger.warning(f"LLM called unknown tool: {tc.name}")
                else:
                    # Dispatch through the tool layer (which goes through safety gate).
                    try:
                        result_dict = dispatcher.dispatch(tc.name, tc.arguments)
                        result_str = json.dumps(result_dict, ensure_ascii=False)
                    except Exception as exc:
                        logger.exception(f"Tool dispatch failed: {tc.name}")
                        result_str = json.dumps(
                            {"ok": False, "error": str(exc)}
                        )

                # Check for BLOCK.
                if '"BLOCKED"' in result_str or '"BLOCKED:"' in result_str:
                    blocked = True
                    # Extract the block reason.
                    try:
                        ar = json.loads(result_str)
                        if ar.get("error", "").startswith("BLOCKED:"):
                            block_reason = ar["error"]
                            logger.warning(f"Tool blocked by safety gate: {block_reason}")
                    except Exception:
                        pass

                # Append tool result.
                messages.append(
                    ToolMessage(tool_call_id=tc.id, content=result_str)
                )

                if on_event:
                    ok = True
                    try:
                        ok = json.loads(result_str).get("ok", False)
                    except Exception:
                        pass
                    await on_event(
                        ToolCallFinished(
                            step_number=steps_taken,
                            tool_name=tc.name,
                            result=result_str,
                            ok=ok,
                        )
                    )

        # Max steps exceeded.
        cost_final = self._ledger.total_cost() - cost_before
        return TaskResult(
            status="max_steps_exceeded",
            user_facing_message=(
                f"Task reached the maximum of {self._config.max_steps} steps "
                f"without completing. Please try a simpler instruction."
            ),
            steps_taken=steps_taken,
            total_cost_usd=cost_final,
            usage=total_usage,
            transcript=messages,
        )

    # -- helpers ---------------------------------------------------------------

    def _load_system_prompt(self) -> str:
        """Load the system prompt from the configured Markdown file."""
        prompt_path = self._config.system_prompt_file
        if not prompt_path.exists():
            # Try relative to the package.
            alt = Path(__file__).parent / "prompts" / "system_prompt.md"
            if alt.exists():
                prompt_path = alt

        try:
            return prompt_path.read_text(encoding="utf-8")
        except Exception:
            logger.error(f"Could not load system prompt from {prompt_path}")
            # Fallback: inline minimal prompt.
            return (
                "You are Type and Talk (TNT), a Windows desktop agent. "
                "Use only the provided tools. Never invent information. "
                "If a tool is blocked, abort and tell the user."
            )


# ── internal helpers ─────────────────────────────────────────────────────────


def _build_openai_tool_specs() -> list[dict[str, Any]]:
    """Convert all tool spec models to OpenAI function-calling format."""
    return [spec.to_openai_spec() for spec in ALL_TOOL_SPECS]
