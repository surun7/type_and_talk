# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the LLM client module."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest import mock

import pytest

from agent_uia.llm_client import (
    LLMClient,
    LLMConfig,
    LLMResponse,
    LLMUsage,
    LLMUnavailableError,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage,
    ToolCall,
    UsageLedger,
    _message_to_openai,
    _openai_response_to_llm,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _dummy_config() -> LLMConfig:
    return LLMConfig(
        api_key="sk-test-key",  # type: ignore[arg-type]
        model="deepseek-chat",
        max_retries=2,
        request_timeout_s=5.0,
    )


def _make_mock_openai_response(
    *,
    content: str = "Hello",
    finish_reason: str = "stop",
    prompt_tokens: int = 50,
    completion_tokens: int = 30,
    total_tokens: int = 80,
    tool_calls: list[dict] | None = None,
) -> mock.MagicMock:
    """Build a mock OpenAI chat completion response."""
    usage = mock.MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens

    msg = mock.MagicMock()
    msg.content = content
    msg.tool_calls = None
    if tool_calls:
        tc_objs = []
        for tc in tool_calls:
            tc_obj = mock.MagicMock()
            tc_obj.id = tc["id"]
            tc_obj.type = "function"
            tc_fn = mock.MagicMock()
            tc_fn.name = tc["name"]
            tc_fn.arguments = json.dumps(tc.get("arguments", {}))
            tc_obj.function = tc_fn
            tc_objs.append(tc_obj)
        msg.tool_calls = tc_objs

    choice = mock.MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason

    response = mock.MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


# ── message serialization ────────────────────────────────────────────────────


class TestMessageSerialization:
    """Tests for _message_to_openai."""

    def test_system_message(self) -> None:
        d = _message_to_openai(SystemMessage(content="You are helpful."))
        assert d == {"role": "system", "content": "You are helpful."}

    def test_user_message(self) -> None:
        d = _message_to_openai(UserMessage(content="Open Notepad"))
        assert d == {"role": "user", "content": "Open Notepad"}

    def test_assistant_message_content_only(self) -> None:
        d = _message_to_openai(AssistantMessage(content="Done."))
        assert d["role"] == "assistant"
        assert d["content"] == "Done."

    def test_assistant_message_with_tool_calls(self) -> None:
        msg = AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(id="call_1", name="click", arguments={"control_id": "abc"})
            ],
        )
        d = _message_to_openai(msg)
        assert d["role"] == "assistant"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["id"] == "call_1"
        assert d["tool_calls"][0]["function"]["name"] == "click"

    def test_tool_message(self) -> None:
        d = _message_to_openai(
            ToolMessage(tool_call_id="call_1", content='{"ok": true}')
        )
        assert d == {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}


# ── usage & cost ─────────────────────────────────────────────────────────────


class TestLLMUsage:
    """Tests for LLMUsage."""

    def test_from_openai_usage(self) -> None:
        mock_usage = mock.MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        mock_usage.total_tokens = 150

        usage = LLMUsage.from_openai_usage(mock_usage, model="deepseek-chat")
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150
        # deepseek-chat: $0.14/1M input, $0.28/1M output
        expected = Decimal("0.14") * Decimal(100) / Decimal(1_000_000) + \
                   Decimal("0.28") * Decimal(50) / Decimal(1_000_000)
        assert usage.estimated_cost_usd == expected

    def test_zero_tokens(self) -> None:
        usage = LLMUsage()
        assert usage.total_tokens == 0
        assert usage.estimated_cost_usd == Decimal("0")

    def test_flash_pricing(self) -> None:
        mock_usage = mock.MagicMock()
        mock_usage.prompt_tokens = 1_000_000
        mock_usage.completion_tokens = 1_000_000
        mock_usage.total_tokens = 2_000_000

        usage = LLMUsage.from_openai_usage(mock_usage, model="deepseek-flash")
        # $0.014/1M input + $0.028/1M output = $0.042
        assert usage.estimated_cost_usd == Decimal("0.042")

    def test_unknown_model_cost_zero(self) -> None:
        mock_usage = mock.MagicMock()
        mock_usage.prompt_tokens = 1000
        mock_usage.completion_tokens = 1000
        mock_usage.total_tokens = 2000
        usage = LLMUsage.from_openai_usage(mock_usage, model="nonexistent-model")
        assert usage.estimated_cost_usd == Decimal("0")


# ── chat (mocked) ────────────────────────────────────────────────────────────


class TestLLMClientChat:
    """Tests for LLMClient.chat() with mocked OpenAI."""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self) -> None:
        config = _dummy_config()
        client = LLMClient(config)

        mock_resp = _make_mock_openai_response(content="Task completed.", prompt_tokens=10, completion_tokens=5, total_tokens=15)

        with mock.patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_instance = mock_openai_cls.return_value
            mock_instance.chat.completions.create.return_value = mock_resp

            result = await client.chat(
                [SystemMessage(content="be helpful"), UserMessage(content="hi")]
            )

        assert isinstance(result, LLMResponse)
        assert result.message.content == "Task completed."
        assert result.usage.total_tokens == 15
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls(self) -> None:
        config = _dummy_config()
        client = LLMClient(config)

        mock_resp = _make_mock_openai_response(
            content="",
            finish_reason="tool_calls",
            tool_calls=[{"id": "call_1", "name": "click", "arguments": {"control_id": "abc"}}],
        )

        with mock.patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_instance = mock_openai_cls.return_value
            mock_instance.chat.completions.create.return_value = mock_resp

            result = await client.chat(
                [UserMessage(content="click the button")],
                tools=[{"type": "function", "function": {"name": "click", "parameters": {}}}],
            )

        assert result.message.tool_calls is not None
        assert len(result.message.tool_calls) == 1
        assert result.message.tool_calls[0].name == "click"

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self) -> None:
        import openai

        config = _dummy_config()
        client = LLMClient(config)

        mock_resp = _make_mock_openai_response(content="ok")

        with mock.patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_instance = mock_openai_cls.return_value
            # Fail twice, succeed on third.
            mock_instance.chat.completions.create.side_effect = [
                openai.RateLimitError(
                    "rate limit", response=mock.MagicMock(), body=None
                ),
                openai.RateLimitError(
                    "rate limit", response=mock.MagicMock(), body=None
                ),
                mock_resp,
            ]

            result = await client.chat([UserMessage(content="hi")])

        assert result.message.content == "ok"
        assert mock_instance.chat.completions.create.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self) -> None:
        import openai

        config = LLMConfig(
            api_key="sk-test",  # type: ignore[arg-type]
            max_retries=2,
        )
        client = LLMClient(config)

        with mock.patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_instance = mock_openai_cls.return_value
            mock_instance.chat.completions.create.side_effect = (
                openai.APIConnectionError("connection error")
            )

            with pytest.raises(LLMUnavailableError):
                await client.chat([UserMessage(content="hi")])

    @pytest.mark.asyncio
    async def test_api_key_not_logged(self) -> None:
        """Verify the API key is never present in error messages or logs."""
        config = LLMConfig(
            api_key="sk-secret-key-12345",  # type: ignore[arg-type]
            max_retries=0,
        )
        client = LLMClient(config)

        import openai

        with mock.patch("openai.AsyncOpenAI") as mock_openai_cls, \
             mock.patch("agent_uia.llm_client.logger") as mock_logger:
            mock_instance = mock_openai_cls.return_value
            mock_instance.chat.completions.create.side_effect = (
                openai.APIConnectionError("connection error")
            )

            with pytest.raises(LLMUnavailableError):
                await client.chat([UserMessage(content="hi")])

            # Check that "sk-secret" never appears in any logger call.
            for call_args in mock_logger.exception.call_args_list:
                arg_str = str(call_args)
                assert "sk-secret" not in arg_str, f"API key leaked in log: {arg_str}"
            for call_args in mock_logger.error.call_args_list:
                arg_str = str(call_args)
                assert "sk-secret" not in arg_str, f"API key leaked in log: {arg_str}"


# ── usage ledger ─────────────────────────────────────────────────────────────


class TestUsageLedger:
    """Tests for UsageLedger."""

    def test_record_and_summary(self, tmp_path) -> None:
        from pathlib import Path

        ledger_path = Path(tmp_path) / "usage.jsonl"
        ledger = UsageLedger(ledger_path=ledger_path)

        ledger.record(
            task_id="task-1",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150,
                           model="deepseek-chat",
                           estimated_cost_usd=Decimal("0.0001")),
        )
        ledger.record(
            task_id="task-2",
            usage=LLMUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300,
                           model="deepseek-chat",
                           estimated_cost_usd=Decimal("0.0002")),
        )

        assert ledger.total_cost() == Decimal("0.0003")

        summary = ledger.summary()
        assert summary["total_tokens"] == 450
        assert summary["task_count"] == 2
        assert summary["entry_count"] == 2

        # File should exist and contain 2 lines.
        assert ledger_path.exists()
        lines = ledger_path.read_text("utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert "task_id" in entry
            assert "total_tokens" in entry

    def test_record_no_task_id(self, tmp_path) -> None:
        from pathlib import Path

        ledger_path = Path(tmp_path) / "usage.jsonl"
        ledger = UsageLedger(ledger_path=ledger_path)
        ledger.record(task_id="", usage=LLMUsage(total_tokens=10))
        assert ledger.total_cost() == Decimal("0")

    def test_thread_safety(self, tmp_path) -> None:
        import concurrent.futures
        from pathlib import Path

        ledger_path = Path(tmp_path) / "usage.jsonl"
        ledger = UsageLedger(ledger_path=ledger_path)

        def _record(n: int) -> None:
            for i in range(n):
                ledger.record(
                    task_id=f"task-{i % 5}",
                    usage=LLMUsage(total_tokens=10, estimated_cost_usd=Decimal("0.0001")),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_record, 25) for _ in range(4)]
            concurrent.futures.wait(futures)

        summary = ledger.summary()
        assert summary["entry_count"] == 100
        assert summary["task_count"] == 5
        assert ledger.total_cost() == Decimal("0.0100")
