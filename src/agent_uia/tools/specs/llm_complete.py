# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: llm_complete."""

from __future__ import annotations

from pydantic import Field

from agent_uia.tools.base import _ToolSpec


class LlmCompleteInput(_ToolSpec):
    """Send a prompt to the configured LLM and return the response text."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The prompt text to send to the LLM (1–4000 characters).",
    )
    system: str | None = Field(
        None,
        description="Optional system prompt to override the default.",
    )
    max_tokens: int = Field(
        default=512,
        ge=1,
        le=2000,
        description="Maximum tokens in the response (1–2000).",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.0–2.0).",
    )

    @classmethod
    def tool_name(cls) -> str:
        return "llm_complete"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Send a text prompt to the configured language model and return "
            "the generated response. Useful for text generation, summarization, "
            "or reasoning outside of the normal tool-calling loop."
        )
