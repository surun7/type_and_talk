# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the skill YAML schema models."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from agent_uia.skills.schema import (
    CompleteStep,
    DecisionStep,
    Skill,
    SkillErrorPolicy,
    SkillInput,
    SkillStep,
    SkillStepType,
    ToolStep,
)

# ── helpers ────────────────────────────────────────────────────────────────────

BUILTIN_SKILL_YAMLS: dict[str, str] = {
    "click-fill-form": """
id: click-fill-form
name: Click & Fill Form
description: Click controls and fill text fields in a form.
author: tnt
version: 1
steps:
  - id: click_field
    kind: tool
    tool: click
    args:
      control_id: "{form.field_id}"
    depends_on: []
  - id: fill_text
    kind: tool
    tool: type_text
    args:
      control_id: "{form.field_id}"
      text: "{form.value}"
    depends_on: [click_field]
""",
    "launch-and-wait": """
id: launch-and-wait
name: Launch & Wait
description: Launch an application and wait for its window.
author: tnt
version: 1
steps:
  - id: launch
    kind: tool
    tool: launch_app
    args:
      executable: "{app.exe}"
    depends_on: []
  - id: wait
    kind: tool
    tool: wait_for_window
    args:
      title_contains: "{app.title}"
    depends_on: [launch]
""",
    "find-and-click": """
id: find-and-click
name: Find & Click
description: Find a window and click a control.
author: tnt
version: 1
steps:
  - id: find
    kind: tool
    tool: find_window
    args:
      title_contains: "{target.title}"
    depends_on: []
  - id: click_it
    kind: tool
    tool: click
    args:
      control_id: "{target.control_id}"
    depends_on: [find]
""",
    "confirm-then-act": """
id: confirm-then-act
name: Confirm Then Act
description: Request user confirmation then perform an action.
author: tnt
version: 1
steps:
  - id: confirm
    kind: tool
    tool: request_user_confirmation
    args:
      action_type: "{action.type}"
      target: "{action.target}"
      risk_explanation: "{action.risk}"
    depends_on: []
  - id: decide
    kind: decision
    if:
      - match: "{{confirm.confirmed}}"
        target: perform
    default: abort
  - id: perform
    kind: tool
    tool: click
    args:
      control_id: "{action.control_id}"
    depends_on: [confirm]
  - id: abort
    kind: complete
    depends_on: [confirm]
""",
    "type-and-check": """
id: type-and-check
name: Type & Check
description: Type text and verify the result.
author: tnt
version: 1
steps:
  - id: type
    kind: tool
    tool: type_text
    args:
      control_id: "{input.control_id}"
      text: "{input.text}"
    depends_on: []
  - id: check
    kind: decision
    if:
      - match: "{{type.ok}}"
        target: done
    default: retry
  - id: retry
    kind: tool
    tool: type_text
    args:
      control_id: "{input.control_id}"
      text: "{input.text}"
    depends_on: [check]
    retry: 2
  - id: done
    kind: complete
    depends_on: [check]
""",
}

VALID_SKILL_IDS = [
    "simple",
    "with-numbers-123",
    "underscore_style",
    "mixed-case-With-Caps",
    "a",
    "123-starts-with-digits",
]

INVALID_SKILL_IDS = [
    "has spaces",
    "has@symbol",
    "has/slash",
    "has.dot",
    "",
    "has\nnewline",
]


# ── tests ──────────────────────────────────────────────────────────────────────


class TestBuiltinSkillsRoundtrip:
    """Parse each built-in YAML and verify the resulting Skill objects."""

    @pytest.mark.parametrize("skill_id", list(BUILTIN_SKILL_YAMLS.keys()))
    def test_roundtrip(self, skill_id: str) -> None:
        """Parse *skill_id* YAML and verify fields."""
        from agent_uia.skills.parser import parse_skill_yaml

        yaml_text = BUILTIN_SKILL_YAMLS[skill_id]
        skill = parse_skill_yaml(yaml_text)

        assert isinstance(skill, Skill)
        assert skill.id == skill_id
        assert isinstance(skill.name, str)
        assert len(skill.name) > 0
        assert isinstance(skill.description, str)
        assert len(skill.description) > 0
        assert skill.author == "tnt"
        assert skill.version == 1
        assert len(skill.steps) > 0

    def test_all_five_builtins_have_unique_ids(self) -> None:
        """All five built-in skill ids are distinct."""
        ids = list(BUILTIN_SKILL_YAMLS.keys())
        assert len(ids) == 5
        assert len(set(ids)) == 5


class TestSkillInputValidation:
    """Verify SkillInput validation rules."""

    def test_rejects_invalid_type_string(self) -> None:
        """A string value should be rejected for non-string input."""
        with pytest.raises(ValidationError):
            SkillInput(type="number", description="A number", default="not-a-number")

    def test_rejects_invalid_type_bool(self) -> None:
        """A boolean value should be rejected for non-boolean input."""
        with pytest.raises(ValidationError):
            SkillInput(type="boolean", description="A bool", default=123)

    def test_accepts_valid_inputs(self) -> None:
        """Valid SkillInputs should pass validation."""
        inputs = [
            SkillInput(type="string", description="A string", default="hello"),
            SkillInput(type="number", description="A number", default=42),
            SkillInput(type="boolean", description="A bool", default=True),
            SkillInput(type="string", description="No default"),
        ]
        for inp in inputs:
            assert isinstance(inp, SkillInput)

    def test_rejects_unknown_type(self) -> None:
        """An unknown type string should be rejected."""
        with pytest.raises(ValidationError):
            SkillInput(type="array", description="Unknown type")


class TestSkillIdRegex:
    """Verify skill id validation rules."""

    def _is_valid_id(self, sid: str) -> bool:
        """Check whether *sid* matches the expected id pattern."""
        # Ids must be non-empty, alphanumeric plus hyphens/underscores.
        return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", sid)) if sid else False

    @pytest.mark.parametrize("sid", VALID_SKILL_IDS)
    def test_valid_ids(self, sid: str) -> None:
        """Valid skill id should match the pattern."""
        assert self._is_valid_id(sid), f"Expected valid id: {sid!r}"

    @pytest.mark.parametrize("sid", INVALID_SKILL_IDS)
    def test_invalid_ids(self, sid: str) -> None:
        """Invalid skill id should not match the pattern."""
        assert not self._is_valid_id(sid), f"Expected invalid id: {sid!r}"


class TestSkillStepKind:
    """Verify ToolStep, DecisionStep, CompleteStep parse correctly from dict."""

    def test_tool_step_from_dict(self) -> None:
        """A tool step dict should produce a ToolStep."""
        data = {
            "id": "click_it",
            "kind": "tool",
            "tool": "click",
            "args": {"control_id": "btn1"},
            "depends_on": [],
        }
        step = SkillStep.from_step_dict(data)
        assert isinstance(step, ToolStep)
        assert step.id == "click_it"
        assert step.kind == SkillStepType.TOOL
        assert step.tool == "click"
        assert step.args == {"control_id": "btn1"}
        assert step.depends_on == []

    def test_decision_step_from_dict(self) -> None:
        """A decision step dict should produce a DecisionStep."""
        data = {
            "id": "decide",
            "kind": "decision",
            "if": [{"match": "{{step.ok}}", "target": "next"}],
            "default": "fallback",
            "depends_on": [],
        }
        step = SkillStep.from_step_dict(data)
        assert isinstance(step, DecisionStep)
        assert step.id == "decide"
        assert step.kind == SkillStepType.DECISION
        assert len(step.if_branches) == 1
        assert step.if_branches[0].match == "{{step.ok}}"
        assert step.if_branches[0].target == "next"
        assert step.default == "fallback"

    def test_complete_step_from_dict(self) -> None:
        """A complete step dict should produce a CompleteStep."""
        data = {
            "id": "done",
            "kind": "complete",
            "depends_on": ["prev"],
        }
        step = SkillStep.from_step_dict(data)
        assert isinstance(step, CompleteStep)
        assert step.id == "done"
        assert step.kind == SkillStepType.COMPLETE
        assert step.depends_on == ["prev"]

    def test_tool_step_with_retry(self) -> None:
        """A tool step with retry count should preserve it."""
        data = {
            "id": "retry_click",
            "kind": "tool",
            "tool": "click",
            "args": {"control_id": "btn1"},
            "depends_on": [],
            "retry": 3,
        }
        step = SkillStep.from_step_dict(data)
        assert isinstance(step, ToolStep)
        assert step.retry == 3

    def test_tool_step_with_timeout(self) -> None:
        """A tool step with timeout_s should preserve it."""
        data = {
            "id": "timed_click",
            "kind": "tool",
            "tool": "click",
            "args": {"control_id": "btn1"},
            "depends_on": [],
            "timeout_s": 5.0,
        }
        step = SkillStep.from_step_dict(data)
        assert isinstance(step, ToolStep)
        assert step.timeout_s == 5.0

    def test_tool_step_continue_on_error(self) -> None:
        """A tool step with continue_on_error=True should preserve it."""
        data = {
            "id": "optional",
            "kind": "tool",
            "tool": "click",
            "args": {"control_id": "btn1"},
            "depends_on": [],
            "continue_on_error": True,
        }
        step = SkillStep.from_step_dict(data)
        assert isinstance(step, ToolStep)
        assert step.continue_on_error is True
