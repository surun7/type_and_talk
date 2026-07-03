# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Type & Talk authors
#
"""Skill runner — executes a Skill as an orchestrated sequence of tool calls.

Public API
---------
- :class:`SkillStatus`
- :class:`SkillStepRecord`
- :class:`SkillResult`
- :class:`SkillRunner`
- Event dataclasses (``SkillStarted``, ``StepStarted``, ``StepFinished``,
  ``SkillFinished``)
- :class:`SkillInputError`
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from agent_uia.safety import SafetyGate
from agent_uia.skills.context import SkillContext, SkillContextError
from agent_uia.skills.schema import (
    CompleteStep,
    DecisionStep,
    Skill,
    SkillErrorPolicy,
    SkillStep,
    SkillStepType,
    ToolStep,
)
from agent_uia.tools.dispatcher import ToolDispatcher

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SkillInputError(Exception):
    """Raised when the provided inputs do not match the skill's input schema."""

    def __init__(self, message: str, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class _SkillExecutionError(Exception):
    """Internal exception for step execution failures (caught by the runner)."""

    def __init__(self, step_id: str, message: str) -> None:
        self.step_id = step_id
        super().__init__(message)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SkillStatus(str, Enum):
    """Outcome status of a completed skill run."""

    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    USER_ABORTED = "user_aborted"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Records & Results
# ---------------------------------------------------------------------------


@dataclass
class SkillStepRecord:
    """Record of a single step's execution."""

    step_id: str
    kind: str  # "tool" | "decision" | "complete"
    tool_name: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    ok: bool = True
    error: str | None = None
    result: dict[str, Any] | None = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this record to a JSON-compatible dict."""
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "tool_name": self.tool_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "error": self.error,
            "result": self.result,
        }


@dataclass
class SkillResult:
    """The result of a completed skill run."""

    skill_id: str
    skill_name: str
    status: SkillStatus
    message: str = ""
    steps: list[SkillStepRecord] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize this result to a JSON-compatible dict."""
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "status": self.status.value,
            "message": self.message,
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
        }


# ---------------------------------------------------------------------------
# Events (for on_event callback)
# ---------------------------------------------------------------------------


@dataclass
class SkillStarted:
    """Emitted when a skill run begins."""

    step_count: int


@dataclass
class StepStarted:
    """Emitted when a step begins execution."""

    step_id: str
    step_name: str


@dataclass
class StepFinished:
    """Emitted when a step finishes execution."""

    step_id: str
    ok: bool


@dataclass
class SkillFinished:
    """Emitted when the entire skill run finishes."""

    result: SkillResult


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\s*\}\}")


def _render_template(text: str, context: SkillContext) -> str:
    """Replace ``{{ variable }}`` placeholders with values from *context*."""

    def _lookup(match: re.Match) -> str:
        path = match.group(1).split(".")
        value: Any = None
        for key in path:
            try:
                value = context.get(key) if value is None else value[key]
            except (KeyError, IndexError, TypeError, AttributeError):
                logger.warning("Template variable %r not found in context", match.group(1))
                return ""
        return str(value) if value is not None else ""

    return _TEMPLATE_RE.sub(_lookup, text)


def _render_args(
    args: dict[str, Any], context: SkillContext
) -> dict[str, Any]:
    """Recursively render template strings in *args* dict values."""

    def _render(v: Any) -> Any:
        if isinstance(v, str):
            return _render_template(v, context)
        if isinstance(v, dict):
            return {k: _render(v) for k, v in v.items()}
        if isinstance(v, list):
            return [_render(item) for item in v]
        return v

    return {k: _render(v) for k, v in args.items()}


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def _topological_sort(steps: list[SkillStep]) -> list[str]:
    """Return step ids in dependency order (Kahn's algorithm).

    Raises ``_SkillExecutionError`` if a cycle is detected.
    """
    # Build adjacency: step_id -> list of step_ids that depend on it
    # (reverse of depends_on, so we can do Kahn's algorithm)
    step_ids: list[str] = [s.payload.id for s in steps]
    id_set: set[str] = set(step_ids)

    # Build in-degree: count of unfulfilled dependencies per step
    in_degree: dict[str, int] = {sid: 0 for sid in step_ids}
    # Adjacency: step_id -> list of step_ids that depend on it
    dependents: dict[str, list[str]] = {sid: [] for sid in step_ids}

    for step_wrapper in steps:
        payload = step_wrapper.payload
        deps: list[str] = getattr(payload, "depends_on", [])
        for dep in deps:
            if dep not in id_set:
                raise _SkillExecutionError(
                    payload.id,
                    f"Step {payload.id!r} depends on unknown step {dep!r}",
                )
            dependents.setdefault(dep, []).append(payload.id)
            in_degree[payload.id] = in_degree.get(payload.id, 0) + 1

    # Kahn's algorithm
    queue: list[str] = [sid for sid in step_ids if in_degree.get(sid, 0) == 0]
    ordered: list[str] = []

    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for dep_id in dependents.get(node, []):
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                queue.append(dep_id)

    if len(ordered) != len(step_ids):
        in_cycle = set(step_ids) - set(ordered)
        raise _SkillExecutionError(
            "<graph>",
            f"Cycle detected involving steps: {', '.join(sorted(in_cycle))}",
        )

    return ordered


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

def _safe_eval(expression: str, context: SkillContext) -> Any:
    """Evaluate a Python expression string safely using ``asteval``.

    The interpreter is given a restricted set of builtins and the current
    context variables.  NEVER uses ``eval()`` or ``exec()``.
    """
    from asteval import Interpreter

    # Collect context variables.
    ctx_vars: dict[str, Any] = {}
    # Try to get all keys from the context (best-effort — the context may
    # not expose a full keys list, so we supplement as we go).
    try:
        for key in context.keys():
            ctx_vars[key] = context.get(key)
    except (AttributeError, NotImplementedError):
        pass

    # Also add explicit common variables that the context may not list.
    for key in ("step_result", "steps", "input"):
        try:
            ctx_vars[key] = context.get(key)
        except (KeyError, AttributeError, SkillContextError):
            pass

    interp = Interpreter(
        users_knowledge=ctx_vars,
        max_time=0.5,
        use_numpy=False,
        minimal_builtins=True,
    )

    # Remove dangerous builtins from the interpreter's symbol table.
    dangerous = {"eval", "exec", "compile", "open", "__import__", "input"}
    for name in dangerous:
        interp.symtable.pop(name, None)

    result = interp.eval(expression)
    if interp.error:
        raise _SkillExecutionError(
            "<decision>",
            f"Expression {expression!r} raised: {interp.error}",
        )
    return result


# ---------------------------------------------------------------------------
# SkillRunner
# ---------------------------------------------------------------------------


class SkillRunner:
    """Executes a :class:`Skill` as an orchestrated sequence of tool calls.

    Args:
        dispatcher: The active :class:`ToolDispatcher` instance.
        safety_gate: The active :class:`SafetyGate` instance.
        app_controller: Optional app controller for advanced integration.
    """

    def __init__(
        self,
        dispatcher: ToolDispatcher,
        safety_gate: SafetyGate,
        app_controller: Any | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._safety = safety_gate
        self._app_controller = app_controller

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        skill: Skill,
        inputs: dict[str, Any] | None = None,
        *,
        on_event: Callable[[Any], None] | None = None,
    ) -> SkillResult:
        """Execute *skill* and return a :class:`SkillResult`.

        Args:
            skill: The skill definition to execute.
            inputs: Values for the skill's declared inputs.
            on_event: Optional callback invoked with event dataclass
                instances (``SkillStarted``, ``StepStarted``,
                ``StepFinished``, ``SkillFinished``).

        Returns:
            A :class:`SkillResult` summarising the run.
        """
        inputs = inputs or {}
        started_at = time.time()

        # 1. Validate inputs against the skill's input schema.
        self._validate_inputs(skill, inputs)

        # 2. Build runtime context.
        context = SkillContext(inputs=inputs)

        # 3. Topological sort of steps.
        try:
            step_order = _topological_sort(skill.steps)
        except _SkillExecutionError as exc:
            return SkillResult(
                skill_id=skill.id,
                skill_name=skill.name,
                status=SkillStatus.FAILED,
                message=f"Graph error: {exc}",
                started_at=started_at,
                finished_at=time.time(),
            )

        # Build step lookup.
        step_by_id: dict[str, SkillStep] = {s.payload.id: s for s in skill.steps}

        # 4. Emit SkillStarted.
        if on_event:
            on_event(SkillStarted(step_count=len(step_order)))

        # 5. Execute steps.
        step_records: list[SkillStepRecord] = []
        status = SkillStatus.SUCCESS
        final_message = ""
        visited: set[str] = set()
        idx = 0

        while 0 <= idx < len(step_order):
            step_id = step_order[idx]
            step_wrapper = step_by_id[step_id]

            # Prevent infinite loops — each step can be visited at most
            # once per run.  (Decision jumps that revisit a step are
            # not supported in this linear pass.)
            if step_id in visited:
                logger.warning(
                    "Step %r already executed; breaking loop", step_id
                )
                status = SkillStatus.FAILED
                final_message = f"Infinite loop detected at step {step_id!r}"
                break
            visited.add(step_id)

            payload = step_wrapper.payload
            record = SkillStepRecord(
                step_id=step_id,
                kind=step_wrapper.kind if isinstance(step_wrapper.kind, str) else str(step_wrapper.kind.value),
                started_at=time.time(),
            )

            if on_event:
                on_event(StepStarted(step_id=step_id, step_name=payload.name))

            try:
                if step_wrapper.kind == SkillStepType.TOOL:
                    result = await self._run_tool_step(
                        payload, context, record, skill
                    )
                elif step_wrapper.kind == SkillStepType.DECISION:
                    result = self._run_decision_step(
                        payload, context, record, step_order, step_by_id
                    )
                    idx, record = result  # unpack (new_idx, updated_record)
                    record.finished_at = time.time()
                    step_records.append(record)
                    if on_event:
                        on_event(StepFinished(step_id=step_id, ok=record.ok))
                    # Update context with step result.
                    try:
                        context.set(step_id, record.result)
                    except (AttributeError, SkillContextError):
                        pass
                    continue  # skip the default idx += 1 below
                elif step_wrapper.kind == SkillStepType.COMPLETE:
                    self._run_complete_step(payload, record)
                    status = SkillStatus.SUCCESS
                    final_message = payload.message
                    record.finished_at = time.time()
                    step_records.append(record)
                    if on_event:
                        on_event(StepFinished(step_id=step_id, ok=record.ok))
                    break  # terminal step

            except _SkillExecutionError as exc:
                record.ok = False
                record.error = str(exc)
                status, final_message = self._handle_error(
                    skill, step_id, str(exc)
                )
            except asyncio.TimeoutError:
                record.ok = False
                record.error = "Step timed out"
                status = SkillStatus.TIMEOUT
                final_message = f"Step {step_id!r} timed out"
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error in step %r", step_id)
                record.ok = False
                record.error = f"Unexpected error: {exc}"
                status, final_message = self._handle_error(
                    skill, step_id, str(exc)
                )

            record.finished_at = time.time()
            step_records.append(record)

            if on_event:
                on_event(StepFinished(step_id=step_id, ok=record.ok))

            # Update context with step result (tool / complete).
            try:
                context.set(step_id, record.result)
            except (AttributeError, SkillContextError):
                pass

            # Handle stop/abort policies.
            if status in (SkillStatus.FAILED, SkillStatus.BLOCKED,
                          SkillStatus.USER_ABORTED, SkillStatus.TIMEOUT):
                break

            idx += 1

        finished_at = time.time()
        result = SkillResult(
            skill_id=skill.id,
            skill_name=skill.name,
            status=status,
            message=final_message,
            steps=step_records,
            started_at=started_at,
            finished_at=finished_at,
            duration_s=finished_at - started_at,
        )

        if on_event:
            on_event(SkillFinished(result=result))

        return result

    # ------------------------------------------------------------------
    # Step execution helpers
    # ------------------------------------------------------------------

    async def _run_tool_step(
        self,
        payload: ToolStep,
        context: SkillContext,
        record: SkillStepRecord,
        skill: Skill,
    ) -> dict[str, Any]:
        """Execute a tool step and populate *record*."""
        record.tool_name = payload.tool

        rendered_args = _render_args(payload.args, context)
        timeout = payload.timeout_s

        retries = payload.retry
        last_error: str | None = None

        for attempt in range(retries + 1):
            try:
                if timeout is not None:
                    result = await asyncio.wait_for(
                        self._dispatcher.dispatch(payload.tool, rendered_args),
                        timeout=timeout,
                    )
                else:
                    result = await self._dispatcher.dispatch(
                        payload.tool, rendered_args
                    )
            except asyncio.TimeoutError:
                last_error = f"Timeout after {timeout}s (attempt {attempt + 1})"
                if attempt < retries:
                    logger.warning(
                        "Tool step %r timeout, retrying (%d/%d)",
                        payload.id, attempt + 1, retries,
                    )
                    continue
                raise

            if result.get("ok"):
                record.ok = True
                record.result = result
                return result

            last_error = result.get("error", "Unknown error")

            # Check for blocked / user-aborted.
            err_str = (last_error or "").lower()
            if "blocked" in err_str:
                status = SkillStatus.BLOCKED
                raise _SkillExecutionError(
                    payload.id, f"Blocked: {last_error}"
                )
            if "user aborted" in err_str:
                status = SkillStatus.USER_ABORTED
                raise _SkillExecutionError(
                    payload.id, f"User aborted: {last_error}"
                )

            if attempt < retries and payload.retry > 0:
                logger.warning(
                    "Tool step %r failed, retrying (%d/%d): %s",
                    payload.id, attempt + 1, payload.retry, last_error,
                )
                continue

            if payload.continue_on_error:
                logger.warning(
                    "Tool step %r failed but continue_on_error=True: %s",
                    payload.id, last_error,
                )
                record.ok = False
                record.error = last_error
                record.result = result
                return result

            raise _SkillExecutionError(payload.id, last_error or "Unknown error")

        # Should not reach here, but safety net.
        raise _SkillExecutionError(payload.id, last_error or "Max retries exceeded")

    def _run_decision_step(
        self,
        payload: DecisionStep,
        context: SkillContext,
        record: SkillStepRecord,
        step_order: list[str],
        step_by_id: dict[str, SkillStep],
    ) -> tuple[int, SkillStepRecord]:
        """Evaluate a decision step and return the new step index."""
        # Build id -> index mapping for jumps.
        id_to_idx: dict[str, int] = {sid: i for i, sid in enumerate(step_order)}

        for branch in payload.branches:
            try:
                matched = _safe_eval(branch.if_expr, context)
            except _SkillExecutionError as exc:
                record.ok = False
                record.error = str(exc)
                # Fall through to default or next branch.
                continue

            if matched:
                record.ok = True
                record.result = {"matched": branch.if_expr, "goto": branch.goto}
                target_idx = id_to_idx.get(branch.goto)
                if target_idx is None:
                    record.ok = False
                    record.error = f"Decision target {branch.goto!r} not found"
                    return (len(step_order), record)  # stop
                return (target_idx, record)

        # No branch matched — try default.
        if payload.default:
            record.ok = True
            record.result = {"matched": None, "goto": payload.default}
            target_idx = id_to_idx.get(payload.default)
            if target_idx is None:
                record.ok = False
                record.error = f"Decision default target {payload.default!r} not found"
                return (len(step_order), record)
            return (target_idx, record)

        # No default set — continue to next step.
        record.ok = True
        record.result = {"matched": None, "goto": None}
        return (step_order.index(payload.id) + 1, record)

    def _run_complete_step(
        self,
        payload: CompleteStep,
        record: SkillStepRecord,
    ) -> None:
        """Process a terminal complete step."""
        record.ok = True
        record.result = {"message": payload.message}

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _handle_error(
        self,
        skill: Skill,
        step_id: str,
        error_msg: str,
    ) -> tuple[SkillStatus, str]:
        """Map the skill's error policy to a status and message."""
        policy = skill.on_error
        if policy == SkillErrorPolicy.STOP:
            return (
                SkillStatus.FAILED,
                f"Step {step_id!r} failed: {error_msg}",
            )
        if policy == SkillErrorPolicy.ABORT:
            return (
                SkillStatus.FAILED,
                f"Step {step_id!r} aborted: {error_msg}",
            )
        if policy == SkillErrorPolicy.SKIP_STEP:
            logger.warning("Skipping failed step %r: %s", step_id, error_msg)
            return (SkillStatus.SUCCESS, f"Skipped step {step_id!r}")
        # RETRY_STEP is handled inline; fallback.
        return (
            SkillStatus.FAILED,
            f"Step {step_id!r} failed: {error_msg}",
        )

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(skill: Skill, inputs: dict[str, Any]) -> None:
        """Validate *inputs* against the skill's declared input schema.

        Raises :class:`SkillInputError` on any mismatch.
        """
        for inp in skill.inputs:
            if inp.name not in inputs:
                if inp.required:
                    raise SkillInputError(
                        f"Missing required input {inp.name!r}",
                        field=inp.name,
                    )
                continue

            value = inputs[inp.name]

            # Type-based validation.
            if inp.type == "string":
                if not isinstance(value, str):
                    raise SkillInputError(
                        f"Input {inp.name!r} should be string, got {type(value).__name__}",
                        field=inp.name,
                    )
            elif inp.type == "integer":
                if not isinstance(value, int):
                    raise SkillInputError(
                        f"Input {inp.name!r} should be integer, got {type(value).__name__}",
                        field=inp.name,
                    )
            elif inp.type == "float":
                if not isinstance(value, (int, float)):
                    raise SkillInputError(
                        f"Input {inp.name!r} should be numeric, got {type(value).__name__}",
                        field=inp.name,
                    )
            elif inp.type == "boolean":
                if not isinstance(value, bool):
                    raise SkillInputError(
                        f"Input {inp.name!r} should be boolean, got {type(value).__name__}",
                        field=inp.name,
                    )
            elif inp.type == "enum":
                if inp.choices and value not in inp.choices:
                    raise SkillInputError(
                        f"Input {inp.name!r} should be one of {inp.choices}, "
                        f"got {value!r}",
                        field=inp.name,
                    )

            # Validate default values are of the correct type.
            if value is None and inp.default is not None:
                inputs[inp.name] = inp.default
