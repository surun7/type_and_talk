# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for SkillContext — template rendering and step-result storage."""

from __future__ import annotations

import pytest

from agent_uia.skills.context import SkillContext, SkillContextError


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> SkillContext:
    """Return a fresh SkillContext."""
    return SkillContext(inputs={})


# ── tests ──────────────────────────────────────────────────────────────────────


class TestRenderSimple:
    """Basic string interpolation."""

    def test_render_simple(self, ctx: SkillContext) -> None:
        """A simple {{name}} substitution should work."""
        result = ctx.render("hello {{name}}", {"name": "world"})
        assert result == "hello world"

    def test_render_multiple_vars(self, ctx: SkillContext) -> None:
        """Multiple {{var}} substitutions in one template should work."""
        result = ctx.render("{{a}} and {{b}}", {"a": "x", "b": "y"})
        assert result == "x and y"

    def test_render_no_vars(self, ctx: SkillContext) -> None:
        """A template with no placeholders should pass through unchanged."""
        result = ctx.render("plain text", {})
        assert result == "plain text"

    def test_render_non_string_coercion(self, ctx: SkillContext) -> None:
        """Non-string values should be coerced to strings."""
        result = ctx.render("value: {{n}}", {"n": 42})
        assert result == "value: 42"


class TestRenderNested:
    """Nested / dotted path access."""

    def test_render_nested(self, ctx: SkillContext) -> None:
        """A dotted path {{launch.pid}} should resolve into the dict."""
        result = ctx.render(
            "pid is {{launch.pid}}",
            {"launch": {"pid": 1234}},
        )
        assert result == "pid is 1234"

    def test_render_deeply_nested(self, ctx: SkillContext) -> None:
        """Deeply nested paths should resolve."""
        result = ctx.render(
            "{{a.b.c.d}}",
            {"a": {"b": {"c": {"d": "deep"}}}},
        )
        assert result == "deep"

    def test_render_nested_with_step_result(self, ctx: SkillContext) -> None:
        """Step results stored via set_step_result should be accessible by path."""
        ctx.set_step_result("launch", {"ok": True, "pid": 5678})
        result = ctx.render("{{launch.pid}}")
        assert result == "5678"

    def test_render_nested_list_index(self, ctx: SkillContext) -> None:
        """List index access in dotted path should work."""
        result = ctx.render(
            "first: {{items.0}}",
            {"items": ["a", "b"]},
        )
        assert result == "first: a"


class TestRenderMissingRaises:
    """Missing keys should raise SkillContextError."""

    def test_render_missing_raises(self, ctx: SkillContext) -> None:
        """An undefined {{missing}} variable should raise SkillContextError."""
        with pytest.raises(SkillContextError):
            ctx.render("{{missing}}", {})

    def test_render_missing_nested_raises(self, ctx: SkillContext) -> None:
        """A dotted path with a missing intermediate key should raise."""
        with pytest.raises(SkillContextError):
            ctx.render("{{a.b.c}}", {"a": {}})

    def test_render_missing_no_context_raises(self, ctx: SkillContext) -> None:
        """Calling render with no context and no stored results should raise."""
        with pytest.raises(SkillContextError):
            ctx.render("{{something}}")


class TestRenderArgsDeepWalk:
    """Deep substitution on argument dicts."""

    def test_render_args_simple(self, ctx: SkillContext) -> None:
        """render_args should substitute into string values."""
        args = {"control_id": "{{id}}"}
        context = {"id": "btn1"}
        result = ctx.render_args(args, context)
        assert result == {"control_id": "btn1"}

    def test_render_args_nested_list(self, ctx: SkillContext) -> None:
        """render_args should recursively walk lists."""
        args = {
            "items": ["{{a}}", "{{b}}", "plain"],
        }
        context = {"a": "x", "b": "y"}
        result = ctx.render_args(args, context)
        assert result == {"items": ["x", "y", "plain"]}

    def test_render_args_nested_dict(self, ctx: SkillContext) -> None:
        """render_args should recursively walk nested dicts."""
        args = {
            "outer": {
                "inner": "{{val}}",
            },
        }
        context = {"val": "hello"}
        result = ctx.render_args(args, context)
        assert result == {"outer": {"inner": "hello"}}

    def test_render_args_preserves_non_strings(self, ctx: SkillContext) -> None:
        """render_args should preserve booleans, numbers, None."""
        args = {
            "flag": True,
            "count": 42,
            "nothing": None,
            "text": "{{greeting}}",
        }
        context = {"greeting": "hi"}
        result = ctx.render_args(args, context)
        assert result == {
            "flag": True,
            "count": 42,
            "nothing": None,
            "text": "hi",
        }

    def test_render_args_missing_raises(self, ctx: SkillContext) -> None:
        """render_args should raise on missing keys."""
        args = {"a": "{{missing}}"}
        with pytest.raises(SkillContextError):
            ctx.render_args(args, {})


class TestSetGetStepResult:
    """Store and retrieve step results."""

    def test_set_get_success(self, ctx: SkillContext) -> None:
        """A stored step result should be retrievable."""
        ctx.set_step_result("step1", {"ok": True, "pid": 99})
        result = ctx.get_step_result("step1")
        assert result == {"ok": True, "pid": 99}

    def test_get_missing_returns_none(self, ctx: SkillContext) -> None:
        """Getting a non-existent step result should return None."""
        result = ctx.get_step_result("nonexistent")
        assert result is None

    def test_set_overwrites(self, ctx: SkillContext) -> None:
        """Setting the same step id twice should overwrite."""
        ctx.set_step_result("step1", {"ok": False})
        ctx.set_step_result("step1", {"ok": True})
        result = ctx.get_step_result("step1")
        assert result == {"ok": True}

    def test_set_step_result_integrates_with_render(self, ctx: SkillContext) -> None:
        """After set_step_result, render should find the values."""
        ctx.set_step_result("search", {"window": {"id": "win-1"}})
        result = ctx.render("{{search.window.id}}")
        assert result == "win-1"
