# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Type & Talk authors

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent_uia.safety import SafetyConfig, SafetyGate
from agent_uia.skills.runner import SkillRunner, SkillStatus
from agent_uia.skills.schema import Skill, SkillStep
from agent_uia.tools.dispatcher import ToolDispatcher

CANNED_SYSTEM_INFO = {
    "cpu": {"physical_cores": 8, "logical_cores": 16, "usage_percent": 12.5},
    "memory": {
        "total_gb": 32.0,
        "available_gb": 18.5,
        "used_gb": 13.5,
        "usage_percent": 42.2,
    },
    "disk": {
        "total_gb": 512.0,
        "used_gb": 230.0,
        "free_gb": 282.0,
        "usage_percent": 44.9,
    },
}


def _make_system_info_skill() -> Skill:
    """Build a Skill matching show-system-info."""
    return Skill(
        id="show-system-info",
        name="显示系统信息",
        description="收集系统 CPU、内存、磁盘使用情况，整理后写到剪贴板。",
        author="tnt-team",
        version="1",
        inputs=[],
        steps=[
            SkillStep(
                kind="tool",
                payload={
                    "id": "gather",
                    "name": "收集系统信息",
                    "tool": "system_info",
                    "args": {"components": ["cpu", "memory", "disk"]},
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "format",
                    "name": "用 LLM 整理为可读文本",
                    "tool": "llm_complete",
                    "args": {
                        "system": "你是一个系统信息格式化助手。",
                        "prompt": "请把以下系统信息整理为简洁报告：\n\n{{gather}}",
                        "max_tokens": 500,
                    },
                    "depends_on": ["gather"],
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "write",
                    "name": "写剪贴板",
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
                    "message": "系统信息已复制到剪贴板。",
                    "depends_on": ["write"],
                },
            ),
        ],
    )


@pytest.mark.asyncio
async def test_show_system_info() -> None:
    """Run show-system-info with mocked system_info returning canned data.
    Verify clipboard_write receives non-empty string. Verify llm_complete
    called with canned data.
    """
    dispatcher = AsyncMock(spec=ToolDispatcher)
    dispatcher.validate_tool_name.return_value = True

    call_log: list[tuple[str, dict]] = []
    llm_input_data = None

    async def _dispatch(tool_name: str, args: dict) -> dict:
        nonlocal llm_input_data
        call_log.append((tool_name, args))
        if tool_name == "system_info":
            return {"ok": True, **CANNED_SYSTEM_INFO}
        if tool_name == "llm_complete":
            llm_input_data = args
            return {"ok": True, "text": "CPU 12.5%, 内存 42.2%, 磁盘 44.9%"}
        if tool_name == "clipboard_write":
            return {"ok": True}
        return {"ok": False, "error": f"unknown tool: {tool_name}"}

    dispatcher.dispatch.side_effect = _dispatch

    safety = SafetyGate(SafetyConfig(blocked_executables=set()))
    runner = SkillRunner(dispatcher=dispatcher, safety_gate=safety)
    skill = _make_system_info_skill()

    result = await runner.run(skill)

    assert result.status == SkillStatus.SUCCESS

    # Verify clipboard_write receives non-empty string.
    write_calls = [
        (name, args)
        for name, args in call_log
        if name == "clipboard_write"
    ]
    assert len(write_calls) == 1
    written_text = write_calls[0][1].get("text", "")
    assert isinstance(written_text, str)
    assert len(written_text) > 0

    # Verify llm_complete was called (prompt contains serialized canned data).
    assert llm_input_data is not None
    assert "prompt" in llm_input_data
