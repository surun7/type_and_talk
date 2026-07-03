# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Type & Talk authors

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent_uia.safety import SafetyConfig, SafetyGate
from agent_uia.skills.runner import SkillRunner, SkillStatus
from agent_uia.skills.schema import Skill, SkillStep
from agent_uia.tools.dispatcher import ToolDispatcher


def _make_clipboard_skill() -> Skill:
    """Build a Skill matching clipboard-format-text."""
    return Skill(
        id="clipboard-format-text",
        name="格式化剪贴板文本",
        description="读取剪贴板内容，调用 LLM 整理后写回剪贴板。",
        author="tnt-team",
        version="1",
        inputs=[],
        steps=[
            SkillStep(
                kind="tool",
                payload={
                    "id": "read",
                    "name": "读取剪贴板",
                    "tool": "clipboard_read",
                    "args": {},
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "format",
                    "name": "调用 LLM 整理文本",
                    "tool": "llm_complete",
                    "args": {
                        "system": "你是一个文本整理助手。",
                        "prompt": "请整理以下文本：\n\n{{read.text}}",
                        "max_tokens": 2000,
                        "temperature": 0.1,
                    },
                    "depends_on": ["read"],
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "write",
                    "name": "写回剪贴板",
                    "tool": "clipboard_write",
                    "args": {"text": "{{format.text}}"},
                    "depends_on": ["format"],
                },
            ),
            SkillStep(
                kind="complete",
                payload={
                    "id": "done",
                    "name": "完成",
                    "message": "剪贴板文本已整理完成。",
                    "depends_on": ["write"],
                },
            ),
        ],
    )


@pytest.mark.asyncio
async def test_clipboard_format_text_success() -> None:
    """Run clipboard-format-text with mocked clipboard_read returning
    "hello\\nworld\\n\\n" and mocked llm_complete returning "hello world".
    Verify clipboard_write was called with "hello world". Verify
    status=SUCCESS.
    """
    dispatcher = AsyncMock(spec=ToolDispatcher)
    dispatcher.validate_tool_name.return_value = True

    call_log: list[tuple[str, dict]] = []

    async def _dispatch(tool_name: str, args: dict) -> dict:
        call_log.append((tool_name, args))
        if tool_name == "clipboard_read":
            return {"ok": True, "text": "hello\nworld\n\n"}
        if tool_name == "llm_complete":
            return {"ok": True, "text": "hello world"}
        if tool_name == "clipboard_write":
            return {"ok": True}
        return {"ok": False, "error": f"unknown tool: {tool_name}"}

    dispatcher.dispatch.side_effect = _dispatch

    safety = SafetyGate(SafetyConfig(blocked_executables=set()))
    runner = SkillRunner(dispatcher=dispatcher, safety_gate=safety)
    skill = _make_clipboard_skill()

    result = await runner.run(skill)

    assert result.status == SkillStatus.SUCCESS

    # Find the clipboard_write call and verify the text argument.
    write_calls = [
        (name, args) for name, args in call_log if name == "clipboard_write"
    ]
    assert len(write_calls) == 1
    assert write_calls[0][1]["text"] == "hello world"
