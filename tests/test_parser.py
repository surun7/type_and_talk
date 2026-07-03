# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the skill YAML parser."""

from __future__ import annotations

import pytest

from agent_uia.skills.parser import (
    SkillParseError,
    parse_skill_yaml,
    validate_skill_graph,
)
from agent_uia.skills.schema import Skill, ToolStep


# ── valid YAML fixture ────────────────────────────────────────────────────────

VALID_YAML = """
id: test-skill
name: Test Skill
description: A skill used for parser tests.
author: test
version: 1
inputs:
  - name: target
    type: string
    description: The target control id
steps:
  - id: find
    kind: tool
    tool: find_window
    args:
      title_contains: "{target}"
    depends_on: []
  - id: click
    kind: tool
    tool: click
    args:
      control_id: "{find.window.id}"
    depends_on: [find]
"""

CYCLE_YAML = """
id: cycle-skill
name: Cycle Skill
description: Has a dependency cycle.
author: test
version: 1
steps:
  - id: a
    kind: tool
    tool: click
    args:
      control_id: "btn1"
    depends_on: [b]
  - id: b
    kind: tool
    tool: click
    args:
      control_id: "btn2"
    depends_on: [a]
"""

MISSING_REF_YAML = """
id: missing-ref
name: Missing Ref
description: depends_on references non-existent step.
author: test
version: 1
steps:
  - id: a
    kind: tool
    tool: click
    args:
      control_id: "btn1"
    depends_on: [nonexistent]
"""

INVALID_TOOL_YAML = """
id: invalid-tool
name: Invalid Tool
description: References an unknown tool.
author: test
version: 1
steps:
  - id: step1
    kind: tool
    tool: nonexistent_tool
    args: {}
    depends_on: []
"""

GARBAGE_YAML = """
<<<<garbage>>>>
  - not: yaml
"""


# ── tests ──────────────────────────────────────────────────────────────────────


class TestParseValidYaml:
    """Parse a valid YAML string and verify the result."""

    def test_parse_valid_yaml(self) -> None:
        """A well-formed skill YAML should parse into a Skill object."""
        skill = parse_skill_yaml(VALID_YAML)
        assert isinstance(skill, Skill)
        assert skill.id == "test-skill"
        assert skill.name == "Test Skill"
        assert skill.description == "A skill used for parser tests."
        assert skill.author == "test"
        assert skill.version == 1
        assert len(skill.inputs) == 1
        assert skill.inputs[0].name == "target"
        assert skill.inputs[0].type == "string"
        assert len(skill.steps) == 2

    def test_parsed_steps_order(self) -> None:
        """Steps maintain insertion order."""
        skill = parse_skill_yaml(VALID_YAML)
        assert skill.steps[0].id == "find"
        assert skill.steps[1].id == "click"

    def test_parsed_step_fields(self) -> None:
        """Each step has correct field values."""
        skill = parse_skill_yaml(VALID_YAML)
        find_step = skill.steps[0]
        assert isinstance(find_step, ToolStep)
        assert find_step.tool == "find_window"
        assert find_step.args == {"title_contains": "{target}"}
        assert find_step.depends_on == []

        click_step = skill.steps[1]
        assert isinstance(click_step, ToolStep)
        assert click_step.tool == "click"
        assert click_step.args == {"control_id": "{find.window.id}"}
        assert click_step.depends_on == ["find"]


class TestInvalidYamlRaises:
    """Garbage input should raise SkillParseError."""

    def test_garbage_yaml_raises(self) -> None:
        """Malformed YAML should raise SkillParseError."""
        with pytest.raises(SkillParseError):
            parse_skill_yaml(GARBAGE_YAML)

    def test_empty_string_raises(self) -> None:
        """An empty YAML string should raise SkillParseError."""
        with pytest.raises(SkillParseError):
            parse_skill_yaml("")

    def test_non_mapping_yaml_raises(self) -> None:
        """A YAML list at the top level should raise SkillParseError."""
        with pytest.raises(SkillParseError):
            parse_skill_yaml("- one\n- two\n")


class TestInvalidToolName:
    """YAML referencing an unknown tool should fail validation."""

    def test_invalid_tool_name_raises(self) -> None:
        """An unknown tool name should produce a SkillParseError."""
        with pytest.raises(SkillParseError):
            validate_skill_graph(parse_skill_yaml(INVALID_TOOL_YAML))


class TestCycleInDependsOn:
    """A→B→A cycle should be detected and rejected."""

    def test_cycle_detected(self) -> None:
        """A dependency cycle should raise SkillParseError."""
        with pytest.raises(SkillParseError):
            validate_skill_graph(parse_skill_yaml(CYCLE_YAML))

    def test_self_reference_cycle(self) -> None:
        """A step depending on itself should also be rejected."""
        self_ref_yaml = """
id: self-cycle
name: Self Cycle
description: Step depends on itself.
author: test
version: 1
steps:
  - id: a
    kind: tool
    tool: click
    args:
      control_id: "btn1"
    depends_on: [a]
"""
        with pytest.raises(SkillParseError):
            validate_skill_graph(parse_skill_yaml(self_ref_yaml))


class TestMissingDependsOnRef:
    """depends_on referencing a non-existent step id should fail."""

    def test_missing_ref_raises(self) -> None:
        """A non-existent depends_on target should raise SkillParseError."""
        with pytest.raises(SkillParseError):
            validate_skill_graph(parse_skill_yaml(MISSING_REF_YAML))


class TestValidateSkillGraphPasses:
    """A valid skill should pass without any error."""

    def test_validate_passes(self) -> None:
        """validate_skill_graph should return None for a valid skill."""
        skill = parse_skill_yaml(VALID_YAML)
        result = validate_skill_graph(skill)
        assert result is None

    def test_valid_skill_with_decision(self) -> None:
        """A skill with decision steps should also pass."""
        decision_yaml = """
id: decision-test
name: Decision Test
description: Skill with decision step.
author: test
version: 1
steps:
  - id: step1
    kind: tool
    tool: find_window
    args:
      title_contains: "test"
    depends_on: []
  - id: decide
    kind: decision
    if:
      - match: "{{step1.ok}}"
        target: done
    default: fallback
    depends_on: [step1]
  - id: done
    kind: complete
    depends_on: [decide]
  - id: fallback
    kind: complete
    depends_on: [decide]
"""
        skill = parse_skill_yaml(decision_yaml)
        result = validate_skill_graph(skill)
        assert result is None
