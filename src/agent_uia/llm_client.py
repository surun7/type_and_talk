# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""DeepSeek-compatible OpenAI client wrapper.

Provides ``LLMClient`` for async chat + streaming, ``UsageLedger`` for
thread-safe cost tracking, and ``LLMConfig`` for configuration.
No planning logic — pure network + serialization.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from loguru import logger
from pydantic import BaseModel, Field, SecretStr

__all__ = [
    "LLMConfig",
    "LLMUsage",
    "LLMResponse",
    "LLMMessage",
    "SystemMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolMessage",
    "ToolCall",
    "LLMClient",
    "LLMUnavailableError",
    "UsageLedger",
]


# ── pricing ──────────────────────────────────────────────────────────────────


def _load_pricing() -> dict[str, dict[str, Any]]:
    """Load pricing.json from the package directory."""
    pricing_path = Path(__file__).parent / "pricing.json"
    try:
        with open(pricing_path, encoding="utf-8") as f:
            data = json.load(f)
        # Drop the _comment key.
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        logger.warning("Could not load pricing.json; cost estimates will be 0.")
        return {}


_PRICING: dict[str, dict[str, Any]] = _load_pricing()


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate USD cost from token counts using the pricing table.

    Args:
        model: Model name (e.g. ``"deepseek-chat"``).
        prompt_tokens: Number of input/prompt tokens.
        completion_tokens: Number of output/completion tokens.

    Returns:
        Estimated cost in USD as a ``Decimal``.
    """
    info = _PRICING.get(model)
    if info is None:
        return Decimal("0")
    input_cost = Decimal(str(info["input_per_1m"])) * Decimal(prompt_tokens) / Decimal(1_000_000)
    output_cost = Decimal(str(info["output_per_1m"])) * Decimal(completion_tokens) / Decimal(1_000_000)
    return input_cost + output_cost


# ── errors ───────────────────────────────────────────────────────────────────


class LLMUnavailableError(Exception):
    """Raised when the LLM is unreachable after all retries."""


# ── config ───────────────────────────────────────────────────────────────────


class LLMConfig(BaseModel):
    """Configuration for the DeepSeek-compatible LLM client.

    Fields:
        api_key: DeepSeek API key (loaded from ``DEEPSEEK_API_KEY`` env var).
        base_url: API base URL.
        model: Model name (default ``"deepseek-chat"``).
        max_tokens_per_call: Maximum completion tokens per request.
        temperature: Sampling temperature (low for deterministic tool calling).
        request_timeout_s: HTTP request timeout in seconds.
        max_retries: Maximum retry count with exponential backoff.
    """

    model_config = {"frozen": True}

    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    max_tokens_per_call: int = 2048
    temperature: float = 0.2
    request_timeout_s: float = 30.0
    max_retries: int = 3


# ── usage ────────────────────────────────────────────────────────────────────


@dataclass
class LLMUsage:
    """Token usage and cost for a single LLM call.

    Attributes:
        prompt_tokens: Input tokens consumed.
        completion_tokens: Output tokens generated.
        total_tokens: Sum of prompt + completion.
        model: Model name used for cost estimation.
        estimated_cost_usd: Estimated USD cost.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = "deepseek-chat"
    estimated_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    @classmethod
    def from_openai_usage(
        cls,
        usage: Any,
        *,
        model: str = "deepseek-chat",
    ) -> LLMUsage:
        """Build from an OpenAI-style usage object.

        Args:
            usage: An object with ``prompt_tokens``, ``completion_tokens``,
                ``total_tokens`` attributes.
            model: The model name for cost estimation.
        """
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        total = getattr(usage, "total_tokens", 0) or (prompt + completion)
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            model=model,
            estimated_cost_usd=_estimate_cost(model, prompt, completion),
        )


# ── messages ─────────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """A single tool call requested by the LLM.

    Attributes:
        id: Unique call identifier.
        name: Tool/function name.
        arguments: JSON-decoded arguments dict.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class SystemMessage:
    """System-level instruction message.

    Attributes:
        content: The system prompt text.
    """

    content: str
    role: Literal["system"] = "system"


@dataclass
class UserMessage:
    """User input message.

    Attributes:
        content: The user's natural-language instruction.
    """

    content: str
    role: Literal["user"] = "user"


@dataclass
class AssistantMessage:
    """Assistant response message.

    Attributes:
        content: The assistant's text response (may be empty if only tool calls).
        tool_calls: Optional list of tool calls requested.
    """

    content: str | None
    tool_calls: list[ToolCall] | None = None
    role: Literal["assistant"] = "assistant"


@dataclass
class ToolMessage:
    """Result of executing a tool call, sent back to the LLM.

    Attributes:
        tool_call_id: The id of the original tool call.
        content: Serialized result (JSON string).
    """

    tool_call_id: str
    content: str
    role: Literal["tool"] = "tool"


# Union type for convenience.
LLMMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


# ── response ─────────────────────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """The result of a single LLM chat completion call.

    Attributes:
        message: The assistant's message (with optional tool calls).
        usage: Token usage and cost.
        finish_reason: Why the completion stopped
            (``"stop"``, ``"tool_calls"``, ``"length"``).
    """

    message: AssistantMessage
    usage: LLMUsage
    finish_reason: str


@dataclass
class LLMResponseChunk:
    """A streaming delta chunk.

    Attributes:
        content_delta: Incremental text content (may be empty).
        tool_call_delta: Partial tool call data (may be None).
        finish_reason: Set on the final chunk.
        usage: Set on the final chunk (may be None for intermediate chunks).
    """

    content_delta: str | None = None
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: LLMUsage | None = None


# ── helper: build OpenAI-compatible dicts ────────────────────────────────────


def _message_to_openai(msg: LLMMessage) -> dict[str, Any]:
    """Convert a ``LLMMessage`` to an OpenAI-compatible dict."""
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content}
    elif isinstance(msg, UserMessage):
        return {"role": "user", "content": msg.content}
    elif isinstance(msg, AssistantMessage):
        d: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]
        return d
    else:
        # ToolMessage
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id,
            "content": msg.content,
        }


def _openai_response_to_llm(response: Any, *, model: str) -> LLMResponse:
    """Convert an OpenAI chat completion response to ``LLMResponse``."""
    choice = response.choices[0]
    finish = choice.finish_reason or "stop"

    content = choice.message.content or ""
    tool_calls: list[ToolCall] = []
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, arguments=args)
            )

    usage = LLMUsage.from_openai_usage(response.usage, model=model)

    return LLMResponse(
        message=AssistantMessage(content=content, tool_calls=tool_calls or None),
        usage=usage,
        finish_reason=finish,
    )


# ── client ───────────────────────────────────────────────────────────────────


class LLMClient:
    """Async DeepSeek-compatible OpenAI client with retry and cost tracking.

    Args:
        config: LLM configuration.
        usage_ledger: Optional ``UsageLedger`` for session-level cost tracking.
    """

    def __init__(
        self,
        config: LLMConfig,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self._config = config
        self._ledger = usage_ledger

    # -- chat ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return the full response.

        Args:
            messages: The conversation history.
            tools: Optional list of OpenAI-format tool specs.

        Returns:
            An ``LLMResponse`` with the assistant message and usage.

        Raises:
            LLMUnavailableError: After exhausting all retries.
        """
        openai_messages = [_message_to_openai(m) for m in messages]
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": openai_messages,
            "max_tokens": self._config.max_tokens_per_call,
            "temperature": self._config.temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                import openai

                client = openai.AsyncOpenAI(
                    api_key=self._config.api_key.get_secret_value(),
                    base_url=self._config.base_url,
                    timeout=self._config.request_timeout_s,
                    max_retries=0,  # We handle retries ourselves.
                )
                response = await client.chat.completions.create(**body)
                result = _openai_response_to_llm(response, model=self._config.model)

                # Record usage.
                if self._ledger:
                    self._ledger.record(task_id="", usage=result.usage)

                logger.debug(
                    "LLM chat completed",
                    model=self._config.model,
                    tokens=result.usage.total_tokens,
                    cost=str(result.usage.estimated_cost_usd),
                )
                return result

            except Exception as exc:
                last_exc = exc
                # Classify the error for retry decisions.
                import openai

                retryable = isinstance(
                    exc,
                    (
                        openai.RateLimitError,
                        openai.APIConnectionError,
                        openai.APITimeoutError,
                    ),
                )
                if not retryable:
                    logger.exception("Non-retryable LLM error")
                    raise

                if attempt < self._config.max_retries:
                    wait = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        f"LLM call failed (attempt {attempt + 1}), "
                        f"retrying in {wait}s: {exc}"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"LLM unavailable after {self._config.max_retries + 1} attempts")
                    raise LLMUnavailableError(
                        f"LLM unavailable after {self._config.max_retries + 1} attempts"
                    ) from last_exc

        raise LLMUnavailableError("LLM unavailable") from last_exc

    # -- stream_chat -----------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMResponseChunk]:
        """Stream a chat completion, yielding incremental chunks.

        Args:
            messages: The conversation history.
            tools: Optional list of OpenAI-format tool specs.

        Yields:
            ``LLMResponseChunk`` objects with content deltas, tool call deltas,
            and final usage metadata.
        """
        openai_messages = [_message_to_openai(m) for m in messages]
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": openai_messages,
            "max_tokens": self._config.max_tokens_per_call,
            "temperature": self._config.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                import openai

                client = openai.AsyncOpenAI(
                    api_key=self._config.api_key.get_secret_value(),
                    base_url=self._config.base_url,
                    timeout=self._config.request_timeout_s,
                    max_retries=0,
                )
                stream = await client.chat.completions.create(**body)

                tool_call_acc: dict[int, dict[str, Any]] = {}
                final_usage: LLMUsage | None = None

                async for event in stream:
                    if event.choices:
                        delta = event.choices[0].delta
                        finish = event.choices[0].finish_reason

                        content = delta.content or ""

                        tool_delta: dict[str, Any] | None = None
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in tool_call_acc:
                                    tool_call_acc[idx] = {
                                        "id": tc.id or "",
                                        "name": "",
                                        "arguments": "",
                                    }
                                if tc.id:
                                    tool_call_acc[idx]["id"] = tc.id
                                if tc.function and tc.function.name:
                                    tool_call_acc[idx]["name"] += tc.function.name
                                if tc.function and tc.function.arguments:
                                    tool_call_acc[idx]["arguments"] += tc.function.arguments
                            # Send the latest accumulated state.
                            latest = max(tool_call_acc.keys())
                            tool_delta = {
                                "index": latest,
                                "id": tool_call_acc[latest]["id"],
                                "name": tool_call_acc[latest]["name"],
                                "arguments": tool_call_acc[latest]["arguments"],
                            }

                        yield LLMResponseChunk(
                            content_delta=content or None,
                            tool_call_delta=tool_delta,
                            finish_reason=finish,
                        )

                    if hasattr(event, "usage") and event.usage:
                        final_usage = LLMUsage.from_openai_usage(
                            event.usage, model=self._config.model
                        )

                # Yield final chunk with usage.
                yield LLMResponseChunk(usage=final_usage)

                # Record usage.
                if self._ledger and final_usage:
                    self._ledger.record(task_id="", usage=final_usage)

                return

            except Exception as exc:
                last_exc = exc
                import openai

                retryable = isinstance(
                    exc,
                    (
                        openai.RateLimitError,
                        openai.APIConnectionError,
                        openai.APITimeoutError,
                    ),
                )
                if not retryable:
                    logger.exception("Non-retryable LLM streaming error")
                    raise

                if attempt < self._config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        f"LLM stream failed (attempt {attempt + 1}), "
                        f"retrying in {wait}s: {exc}"
                    )
                    await asyncio.sleep(wait)
                else:
                    raise LLMUnavailableError(
                        f"LLM unavailable after {self._config.max_retries + 1} attempts"
                    ) from last_exc

        raise LLMUnavailableError("LLM unavailable") from last_exc


# ── usage ledger ─────────────────────────────────────────────────────────────


class UsageLedger:
    """Thread-safe append-only cost ledger.

    Records ``LLMUsage`` per task to an in-memory list and a JSON-lines
    file at ``./logs/usage.jsonl``.

    Methods:
        record: Append a usage entry.
        total_cost: Sum of all estimated costs.
        summary: Dict with total_tokens, total_cost, task_count.
    """

    def __init__(self, ledger_path: Path = Path("./logs/usage.jsonl")) -> None:
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, task_id: str, usage: LLMUsage) -> None:
        """Append a usage entry to memory and disk.

        Args:
            task_id: Identifier for the task (may be empty for untracked calls).
            usage: The ``LLMUsage`` to record.
        """
        entry = {
            "timestamp": time.time(),
            "task_id": task_id,
            "model": usage.model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "estimated_cost_usd": str(usage.estimated_cost_usd),
        }
        with self._lock:
            self._entries.append(entry)
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                logger.exception("Failed to write usage ledger entry")

    def total_cost(self) -> Decimal:
        """Return the sum of all estimated costs."""
        with self._lock:
            total = Decimal("0")
            for e in self._entries:
                total += Decimal(e["estimated_cost_usd"])
            return total

    def summary(self) -> dict[str, Any]:
        """Return a summary dict with totals and task count."""
        with self._lock:
            total_tokens = sum(e["total_tokens"] for e in self._entries)
            total_cost_val = self.total_cost()
            task_ids = {e["task_id"] for e in self._entries if e["task_id"]}
            return {
                "total_tokens": total_tokens,
                "total_cost_usd": str(total_cost_val),
                "task_count": len(task_ids),
                "entry_count": len(self._entries),
            }
