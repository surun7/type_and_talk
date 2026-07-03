# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Type & Talk authors
#
"""Parse YAML skill files into :class:`agent_uia.skills.schema.Skill` instances."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import yaml

from agent_uia.skills.schema import (
    ALL_TOOL_SPECS,
    DecisionStep,
    Skill,
    SkillErrorPolicy,
    SkillStep,
    ToolStep,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SkillParseError(Exception):
    """Raised when a skill file cannot be parsed or validated."""

    def __init__(self, message: str, path: str = "<unknown>", cause: Exception | None = None) -> None:
        self.path = path
        self.cause = cause
        full = f"{path}: {message}" if path != "<unknown>" else message
        if cause:
            super().__init__(f"{full}\n  Caused by: {cause}")
        else:
            super().__init__(full)


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def _build_skill(data: dict, source: str) -> Skill:
    """Construct a :class:`Skill` from a raw dictionary, raising
    :class:`SkillParseError` on failure."""
    try:
        # Transform flat step dicts into {kind, payload} structure
        # expected by SkillStep's discriminated union.
        data = dict(data)
        raw_steps: list[dict] = data.get("steps", [])
        transformed_steps: list[dict] = []
        for step in raw_steps:
            kind = step.get("kind")
            if kind is None:
                raise ValueError("Each step must have a 'kind' field")
            # Build payload dict from all fields except 'kind'.
            payload = {k: v for k, v in step.items() if k != "kind"}
            transformed_steps.append({"kind": kind, "payload": payload})
        data["steps"] = transformed_steps
        return Skill(**data)
    except Exception as exc:
        raise SkillParseError(str(exc), path=source, cause=exc) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_skill_file(path: Path) -> Skill:
    """Read a YAML file from *path* and return a validated :class:`Skill`.

    Raises :class:`SkillParseError` if the file cannot be read or parsed.
    """
    source = str(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise SkillParseError(f"Cannot read file", path=source, cause=exc) from exc
    return parse_skill_yaml(raw, source=source)


def parse_skill_yaml(text: str, *, source: str = "<string>") -> Skill:
    """Parse *text* as YAML and return a validated :class:`Skill`.

    Raises :class:`SkillParseError` on any YAML or validation error.
    """
    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise SkillParseError("Invalid YAML", path=source, cause=exc) from exc

    if not isinstance(data, dict):
        raise SkillParseError(
            f"Expected a YAML mapping (dict) at top level, got {type(data).__name__}",
            path=source,
        )

    return _build_skill(data, source)


# ---------------------------------------------------------------------------
# Graph validation
# ---------------------------------------------------------------------------


def validate_skill_graph(skill: Skill) -> None:
    """Validate the step dependency graph of *skill*.

    Checks performed:
    * Every step id is unique.
    * Every value in ``depends_on`` references an existing step id.
    * The ``depends_on`` edges form a **directed acyclic graph** (no cycles).
    * Tool steps reference tools that exist in :data:`ALL_TOOL_SPECS`.

    Raises :class:`SkillParseError` (with ``path="<graph>"``) on failure.
    """
    _steps = skill.steps
    step_ids: List[str] = [s.payload.id for s in _steps]
    id_set: Set[str] = set(step_ids)

    # --- duplicate ids ---
    if len(step_ids) != len(id_set):
        seen: Dict[str, int] = {}
        for sid in step_ids:
            seen[sid] = seen.get(sid, 0) + 1
        dupes = [k for k, v in seen.items() if v > 1]
        raise SkillParseError(
            f"Duplicate step id(s): {', '.join(dupes)}", path="<graph>"
        )

    # --- depends_on references ---
    for step_wrapper in _steps:
        payload = step_wrapper.payload
        if isinstance(payload, ToolStep):
            deps = payload.depends_on
        elif isinstance(payload, DecisionStep):
            deps = payload.depends_on
        else:
            continue  # CompleteStep has depends_on too, handle generically

        for dep in deps:
            if dep not in id_set:
                raise SkillParseError(
                    f"Step {payload.id!r} depends on unknown step {dep!r}",
                    path="<graph>",
                )

    # --- cycle detection (DFS) ---
    adjacency: Dict[str, List[str]] = {sid: [] for sid in step_ids}
    for step_wrapper in _steps:
        payload = step_wrapper.payload
        deps: List[str] = getattr(payload, "depends_on", [])
        adjacency[payload.id] = deps

    WHITE, GRAY, BLACK = 0, 1, 2
    colour: Dict[str, int] = {sid: WHITE for sid in step_ids}

    def _dfs(node: str, path_stack: List[str]) -> None:
        colour[node] = GRAY
        path_stack.append(node)
        for neighbor in adjacency.get(node, []):
            if colour[neighbor] == GRAY:
                cycle = path_stack[path_stack.index(neighbor):] + [neighbor]
                raise SkillParseError(
                    f"Cycle detected in dependency graph: {' -> '.join(cycle)}",
                    path="<graph>",
                )
            if colour[neighbor] == WHITE:
                _dfs(neighbor, path_stack)
        path_stack.pop()
        colour[node] = BLACK

    for sid in step_ids:
        if colour[sid] == WHITE:
            _dfs(sid, [])

    # --- tool names in ALL_TOOL_SPECS ---
    if ALL_TOOL_SPECS:
        for step_wrapper in _steps:
            payload = step_wrapper.payload
            if isinstance(payload, ToolStep) and payload.tool not in ALL_TOOL_SPECS:
                raise SkillParseError(
                    f"Step {payload.id!r} references unknown tool {payload.tool!r}",
                    path="<graph>",
                )
