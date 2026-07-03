# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Type & Talk authors

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent_uia.safety import SafetyConfig, SafetyGate
from agent_uia.skills.runner import SkillRunner, SkillStatus
from agent_uia.skills.schema import Skill, SkillInput, SkillStep
from agent_uia.tools.dispatcher import ToolDispatcher


def _make_organize_skill() -> Skill:
    """Build a Skill matching organize-desktop-files."""
    return Skill(
        id="organize-desktop-files",
        name="整理桌面文件",
        description="把桌面上的文件按扩展名归类。",
        author="tnt-team",
        version="1",
        inputs=[
            SkillInput(
                name="dry_run",
                type="boolean",
                description="如果是 true，只列出将要移动的文件而不实际移动",
                default=True,
                required=False,
            ),
        ],
        steps=[
            SkillStep(
                kind="tool",
                payload={
                    "id": "list",
                    "name": "列出桌面文件",
                    "tool": "file_list",
                    "args": {
                        "directory": "desktop",
                        "pattern": "*",
                        "limit": 500,
                    },
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "mkdir_docs",
                    "name": "创建文档文件夹",
                    "tool": "file_mkdir",
                    "args": {"directory": "desktop", "name": "文档_已整理"},
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "mkdir_pics",
                    "name": "创建图片文件夹",
                    "tool": "file_mkdir",
                    "args": {"directory": "desktop", "name": "图片_已整理"},
                },
            ),
            SkillStep(
                kind="tool",
                payload={
                    "id": "mkdir_other",
                    "name": "创建其他文件夹",
                    "tool": "file_mkdir",
                    "args": {"directory": "desktop", "name": "其他_已整理"},
                },
            ),
            SkillStep(
                kind="complete",
                payload={
                    "id": "done",
                    "name": "完成",
                    "message": "已在桌面创建三个整理文件夹。",
                    "depends_on": [
                        "mkdir_docs",
                        "mkdir_pics",
                        "mkdir_other",
                    ],
                },
            ),
        ],
    )


@pytest.mark.asyncio
async def test_dry_run_organize_desktop() -> None:
    """Run organize-desktop-files with dry_run=true. Verify file_mkdir called
    3 times. Verify file_move NOT called.
    """
    dispatcher = AsyncMock(spec=ToolDispatcher)
    dispatcher.validate_tool_name.return_value = True

    call_log: list[tuple[str, dict]] = []

    async def _dispatch(tool_name: str, args: dict) -> dict:
        call_log.append((tool_name, args))
        if tool_name == "file_list":
            return {"ok": True, "files": []}
        if tool_name == "file_mkdir":
            return {"ok": True}
        return {"ok": False, "error": f"unknown tool: {tool_name}"}

    dispatcher.dispatch.side_effect = _dispatch

    safety = SafetyGate(SafetyConfig(blocked_executables=set()))
    runner = SkillRunner(dispatcher=dispatcher, safety_gate=safety)
    skill = _make_organize_skill()

    result = await runner.run(skill, inputs={"dry_run": True})

    assert result.status == SkillStatus.SUCCESS

    # Verify file_mkdir called 3 times.
    mkdir_calls = [
        (name, args)
        for name, args in call_log
        if name == "file_mkdir"
    ]
    assert len(mkdir_calls) == 3

    # Verify file_move NOT called.
    move_calls = [
        (name, args)
        for name, args in call_log
        if name == "file_move"
    ]
    assert len(move_calls) == 0


@pytest.mark.asyncio
async def test_move_exe_rejected() -> None:
    """Try to move a .exe file — rejected by dispatcher."""
    dispatcher = AsyncMock(spec=ToolDispatcher)
    dispatcher.validate_tool_name.return_value = True

    async def _dispatch(tool_name: str, args: dict) -> dict:
        if tool_name == "file_move":
            return {
                "ok": False,
                "error": "BLOCKED: .exe files are not allowed",
            }
        return {"ok": True}

    dispatcher.dispatch.side_effect = _dispatch

    safety = SafetyGate(SafetyConfig(blocked_executables=set()))
    runner = SkillRunner(dispatcher=dispatcher, safety_gate=safety)

    skill = Skill(
        id="test-move-exe",
        name="测试移动 exe",
        description="尝试移动 exe 文件。",
        author="test",
        version="1",
        inputs=[],
        steps=[
            SkillStep(
                kind="tool",
                payload={
                    "id": "move",
                    "name": "移动文件",
                    "tool": "file_move",
                    "args": {
                        "source": "setup.exe",
                        "source_directory": "desktop",
                        "destination_directory": "documents",
                    },
                },
            ),
        ],
    )

    result = await runner.run(skill)

    assert result.status in (SkillStatus.FAILED, SkillStatus.BLOCKED)
