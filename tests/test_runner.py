# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for SkillRunner with a mocked dispatcher."""

from __future__ import annotations

import pytest

from agent_uia.skills.context import SkillContext
from agent_uia.skills.runner import SkillResult, SkillRunner, SkillStatus
from agent_uia.skills.schema import (
    CompleteStep,
    DecisionStep,
    Skill,
    SkillInput,
    ToolStep,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def make_skill(
    *,
    steps: list | None = None,
    inputs: list | None = None,
) -> Skill:
    """Build a minimal Skill for testing."""
    return Skill(
        id="test-skill",
        name="Test Skill",
        description="A test skill.",
        author="test",
        version=1,
        inputs=inputs or [],
        steps=steps or [],
    )


def make_tool_step(
    *,
    step_id: str,
    tool: str = "click",
    args: dict | None = None,
    depends_on: list[str] | None = None,
    retry: int = 0,
    continue_on_error: bool = False,
    timeout_s: float | None = None,
) -> ToolStep:
    """Build a ToolStep."""
    return ToolStep(
        id=step_id,
        kind="tool",
        tool=tool,
        args=args or {},
        depends_on=depends_on or [],
        retry=retry,
        continue_on_error=continue_on_error,
        timeout_s=timeout_s,
    )


def make_decision_step(
    *,
    step_id: str,
    branches: list[tuple[str, str]] | None = None,
    default: str | None = None,
    depends_on: list[str] | None = None,
) -> DecisionStep:
    """Build a DecisionStep."""
    if_branches = []
    if branches:
        for match_expr, target in branches:
            if_branches.append({"match": match_expr, "target": target})
    return DecisionStep(
        id=step_id,
        kind="decision",
        if_branches=if_branches,
        default=default,
        depends_on=depends_on or [],
    )


def make_complete_step(
    *,
    step_id: str = "done",
    depends_on: list[str] | None = None,
) -> CompleteStep:
    """Build a CompleteStep."""
    return CompleteStep(
        id=step_id,
        kind="complete",
        depends_on=depends_on or [],
    )


def make_mock_dispatcher() -> "mock.AsyncMock":
    """Create an async mock dispatcher with a dispatch method."""
    from unittest import mock

    dispatcher = mock.AsyncMock()
    dispatcher.dispatch.return_value = {"ok": True, "observation": "done"}
    dispatcher.validate_tool_name.return_value = True
    dispatcher.known_tools.return_value = {"click", "type_text", "find_window"}
    return dispatcher


# ── tests ──────────────────────────────────────────────────────────────────────


class TestRunSuccess:
    """A successful run with all steps passing."""

    @pytest.mark.asyncio
    async def test_run_success(self) -> None:
        """All steps pass -> status=SUCCESS with correct step records."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click"),
            make_complete_step(step_id="done", depends_on=["step1"]),
        ]
        skill = make_skill(steps=steps)
        result: SkillResult = await runner.run(skill, inputs={"target": "btn1"})

        assert result.status == SkillStatus.SUCCESS
        assert len(result.steps) == 2
        assert result.steps[0].step_id == "step1"
        assert result.steps[0].status == "ok"
        assert result.steps[1].step_id == "done"
        assert result.steps[1].status == "ok"
        assert dispatcher.dispatch.await_count == 1

    @pytest.mark.asyncio
    async def test_run_with_inputs(self) -> None:
        """Inputs should be rendered into step args."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(
                step_id="find",
                tool="find_window",
                args={"title_contains": "{input.title}"},
            ),
            make_complete_step(step_id="done", depends_on=["find"]),
        ]
        skill = make_skill(
            steps=steps,
            inputs=[SkillInput(name="title", type="string", description="Window title")],
        )
        result = await runner.run(skill, inputs={"title": "Notepad"})

        assert result.status == SkillStatus.SUCCESS
        # The dispatcher should have been called with rendered args.
        call_args = dispatcher.dispatch.await_args_list[0]
        assert call_args[0][0] == "find_window"
        assert call_args[0][1] == {"title_contains": "Notepad"}


class TestBlockedStops:
    """A tool returning BLOCKED should stop execution."""

    @pytest.mark.asyncio
    async def test_blocked_stops(self) -> None:
        """A BLOCKED result should halt and produce status=BLOCKED."""
        dispatcher = make_mock_dispatcher()

        async def _dispatch(tool_name, args):
            return {"ok": False, "error": "BLOCKED: unsupported app"}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="launch_app"),
            make_tool_step(step_id="step2", tool="click", depends_on=["step1"]),
            make_complete_step(step_id="done", depends_on=["step2"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.BLOCKED
        assert len(result.steps) == 1
        assert result.steps[0].step_id == "step1"
        assert result.error is not None
        assert "BLOCKED" in result.error


class TestToolErrorFails:
    """A tool returning ok=false should fail the skill."""

    @pytest.mark.asyncio
    async def test_tool_error_fails(self) -> None:
        """A failed tool should produce status=FAILED."""
        dispatcher = make_mock_dispatcher()

        async def _dispatch(tool_name, args):
            return {"ok": False, "error": "Control not found"}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click"),
            make_complete_step(step_id="done", depends_on=["step1"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.FAILED
        assert len(result.steps) == 1
        assert result.error is not None


class TestRetryThenSucceed:
    """Retry logic: first two attempts fail, third succeeds."""

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self) -> None:
        """With retry=2, two failures then success -> status=SUCCESS, 3 calls."""
        dispatcher = make_mock_dispatcher()
        call_count = 0

        async def _dispatch(tool_name, args):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"ok": False, "error": "Transient error"}
            return {"ok": True, "observation": "Succeeded on retry"}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click", retry=2),
            make_complete_step(step_id="done", depends_on=["step1"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_fails(self) -> None:
        """When retries are exhausted, the skill should fail."""
        dispatcher = make_mock_dispatcher()
        dispatcher.dispatch.return_value = {"ok": False, "error": "Always fails"}
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click", retry=1),
            make_complete_step(step_id="done", depends_on=["step1"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.FAILED
        assert dispatcher.dispatch.await_count == 2  # 1 initial + 1 retry


class TestContinueOnError:
    """A failing tool with continue_on_error=true should not stop execution."""

    @pytest.mark.asyncio
    async def test_continue_on_error(self) -> None:
        """continue_on_error=true: failing step is skipped, subsequent steps run."""
        dispatcher = make_mock_dispatcher()

        call_log: list[str] = []

        async def _dispatch(tool_name, args):
            call_log.append(tool_name)
            if tool_name == "will_fail":
                return {"ok": False, "error": "Intentional failure"}
            return {"ok": True, "observation": "ok"}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(
                step_id="s1",
                tool="will_fail",
                continue_on_error=True,
            ),
            make_tool_step(
                step_id="s2",
                tool="click",
                depends_on=["s1"],
            ),
            make_complete_step(step_id="done", depends_on=["s2"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        assert "will_fail" in call_log
        assert "click" in call_log
        # The failing step record should have status "error" but not fail the run.
        assert result.steps[0].status == "error"
        assert result.steps[1].status == "ok"

    @pytest.mark.asyncio
    async def test_continue_on_error_still_records_error(self) -> None:
        """continue_on_error step should still record the error in step records."""
        dispatcher = make_mock_dispatcher()
        dispatcher.dispatch.return_value = {"ok": False, "error": "fail"}
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="s1", tool="click", continue_on_error=True),
            make_complete_step(step_id="done", depends_on=["s1"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        assert result.steps[0].status == "error"
        assert result.steps[0].error == "fail"


class TestDecisionBranch:
    """Decision step picks the correct branch."""

    @pytest.mark.asyncio
    async def test_decision_branch_true(self) -> None:
        """When the match expression evaluates to true, the matching branch runs."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click", args={"control_id": "btn1"}),
            make_decision_step(
                step_id="decide",
                branches=[("{{step1.ok}}", "success_branch")],
                default="fallback",
                depends_on=["step1"],
            ),
            make_tool_step(step_id="success_branch", tool="type_text", depends_on=["decide"]),
            make_tool_step(step_id="fallback", tool="click", depends_on=["decide"]),
            make_complete_step(step_id="done", depends_on=["success_branch"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        # The success_branch should have been executed, fallback should not.
        step_ids = [s.step_id for s in result.steps]
        assert "success_branch" in step_ids
        assert "fallback" not in step_ids

    @pytest.mark.asyncio
    async def test_decision_branch_false_uses_default(self) -> None:
        """When no branch matches, the default should be used."""
        dispatcher = make_mock_dispatcher()

        async def _dispatch(tool_name, args):
            return {"ok": False, "error": "step1 failed"}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click", continue_on_error=True),
            make_decision_step(
                step_id="decide",
                branches=[("{{step1.ok}}", "success_branch")],
                default="fallback",
                depends_on=["step1"],
            ),
            make_tool_step(step_id="success_branch", tool="type_text", depends_on=["decide"]),
            make_tool_step(step_id="fallback", tool="press_key", depends_on=["decide"]),
            make_complete_step(step_id="done", depends_on=["fallback"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        step_ids = [s.step_id for s in result.steps]
        assert "fallback" in step_ids
        assert "success_branch" not in step_ids


class TestDecisionDefault:
    """Decision step fallback when no branch matches."""

    @pytest.mark.asyncio
    async def test_decision_default_no_match(self) -> None:
        """When no branch matches but default is set, it jumps to default."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_decision_step(
                step_id="decide",
                branches=[("false", "never_runs")],
                default="always_run",
            ),
            make_tool_step(step_id="always_run", tool="click", depends_on=["decide"]),
            make_complete_step(step_id="done", depends_on=["always_run"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        step_ids = [s.step_id for s in result.steps]
        assert "always_run" in step_ids
        assert "never_runs" not in step_ids

    @pytest.mark.asyncio
    async def test_decision_no_default_and_no_match_errors(self) -> None:
        """When no branch matches and no default, the skill should fail."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_decision_step(
                step_id="decide",
                branches=[("false", "never_runs")],
                default=None,
            ),
            make_complete_step(step_id="done", depends_on=["decide"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.FAILED


class TestSandboxRejectsDunder:
    """The decision sandbox must reject dangerous expressions."""

    @pytest.mark.asyncio
    async def test_sandbox_rejects_dunder(self) -> None:
        """if_expr containing __import__ should be rejected."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click", continue_on_error=True),
            make_decision_step(
                step_id="decide",
                branches=[("__import__('os')", "malicious")],
                default="fallback",
                depends_on=["step1"],
            ),
            make_complete_step(step_id="fallback"),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        # The sandbox should reject the expression; the skill should not fail
        # but the branch should not match (safe fallback).
        assert result.status == SkillStatus.SUCCESS


class TestStepTimeout:
    """A step that exceeds timeout_s should fail."""

    @pytest.mark.asyncio
    async def test_step_timeout(self) -> None:
        """A tool step with timeout_s that hangs should produce FAILED."""
        dispatcher = make_mock_dispatcher()

        async def _dispatch(tool_name, args):
            import asyncio

            await asyncio.sleep(10)  # Simulate a hang
            return {"ok": True}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(
                step_id="step1",
                tool="click",
                timeout_s=0.01,  # Very short timeout
            ),
            make_complete_step(step_id="done", depends_on=["step1"]),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.FAILED
        assert "timeout" in (result.error or "").lower() or "timeout" in (
            result.steps[0].error or ""
        ).lower()

    @pytest.mark.asyncio
    async def test_step_timeout_records_in_step(self) -> None:
        """A timed-out step should record the timeout in its step record."""
        dispatcher = make_mock_dispatcher()

        async def _dispatch(tool_name, args):
            import asyncio

            await asyncio.sleep(10)
            return {"ok": True}

        dispatcher.dispatch.side_effect = _dispatch
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click", timeout_s=0.01),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.steps[0].status in ("error", "timeout")
        assert result.steps[0].error is not None


class TestRunnerEdgeCases:
    """Edge cases for the runner."""

    @pytest.mark.asyncio
    async def test_empty_steps(self) -> None:
        """A skill with no steps should succeed immediately."""
        dispatcher = make_mock_dispatcher()
        runner = SkillRunner(dispatcher=dispatcher)

        skill = make_skill(steps=[])
        result = await runner.run(skill)

        assert result.status == SkillStatus.SUCCESS
        assert len(result.steps) == 0

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self) -> None:
        """An unknown tool name in a step should fail."""
        dispatcher = make_mock_dispatcher()
        dispatcher.validate_tool_name.return_value = False
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="unknown_tool"),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.FAILED

    @pytest.mark.asyncio
    async def test_dispatcher_exception_handled(self) -> None:
        """If the dispatcher raises an exception, the runner should handle it."""
        dispatcher = make_mock_dispatcher()
        dispatcher.dispatch.side_effect = RuntimeError("Unexpected crash")
        runner = SkillRunner(dispatcher=dispatcher)

        steps = [
            make_tool_step(step_id="step1", tool="click"),
        ]
        skill = make_skill(steps=steps)
        result = await runner.run(skill)

        assert result.status == SkillStatus.FAILED
