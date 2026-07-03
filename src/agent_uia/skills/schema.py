# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Type & Talk authors
#
"""
Pydantic models representing the skill YAML schema.

A skill file (``.yaml``) describes an executable graph of steps:

.. code-block:: yaml

    # sample skill ── open-notepad
    id: open-notepad
    name: Open Notepad
    description: Launch the Windows Notepad application.
    version: "1.0.0"
    author: TNT Team
    license: MIT
    tags: [windows, utility]
    inputs:
      - name: file
        type: string
        description: Optional file to open
        required: false
    permissions: [shell:exec]
    steps:
      - kind: tool
        id: launch
        name: Launch Notepad
        tool: shell.exec
        args:
          command: notepad {{ file }}
      - kind: complete
        id: done
        name: Complete
        message: Notepad has been opened.
    on_error: STOP
    on_block: STOP
    metadata:
      os: windows
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# ALL_TOOL_SPECS  (placeholder ─ the runner/registry provides the real value)
# ---------------------------------------------------------------------------

ALL_TOOL_SPECS: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SkillStepType(str, Enum):
    """Discriminator for the type of a skill step."""

    TOOL = "tool"
    DECISION = "decision"
    COMPLETE = "complete"


class SkillErrorPolicy(str, Enum):
    """What to do when a step errors or is blocked by a permission."""

    STOP = "STOP"
    RETRY_STEP = "RETRY_STEP"
    SKIP_STEP = "SKIP_STEP"
    ABORT = "ABORT"


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class SkillInput(BaseModel):
    """Declared input parameter for a skill."""

    name: str
    type: Literal["string", "integer", "float", "boolean", "enum"]
    description: Optional[str] = None
    default: Any = None
    choices: Optional[List[str]] = None  # only valid for type=enum
    required: bool = True

    model_config = {"frozen": False, "use_enum_values": True}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


class ToolStep(BaseModel):
    """A step that invokes a tool."""

    id: str
    name: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    timeout_s: Optional[float] = None
    retry: int = 0
    continue_on_error: bool = False
    description: Optional[str] = None

    model_config = {"frozen": True, "use_enum_values": True}

    @field_validator("tool")
    @classmethod
    def _validate_tool(cls, v: str) -> str:
        if ALL_TOOL_SPECS and v not in ALL_TOOL_SPECS:
            raise ValueError(
                f"Unknown tool {v!r}. Known tools: {sorted(ALL_TOOL_SPECS)}"
            )
        return v


class DecisionBranch(BaseModel):
    """One branch of a decision step."""

    if_expr: str = Field(alias="if")
    goto: str

    model_config = {"frozen": True, "use_enum_values": True, "populate_by_name": True}


class DecisionStep(BaseModel):
    """A step that branches based on variable expressions."""

    id: str
    name: str
    branches: List[DecisionBranch]
    default: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)

    model_config = {"frozen": True, "use_enum_values": True}


class CompleteStep(BaseModel):
    """A terminal step that marks the skill as finished."""

    id: str
    name: str
    message: str
    depends_on: List[str] = Field(default_factory=list)

    model_config = {"frozen": True, "use_enum_values": True}


# ---------------------------------------------------------------------------
# Discriminated step union
# ---------------------------------------------------------------------------


class SkillStep(BaseModel):
    """A single step in a skill, discriminated by ``kind``."""

    kind: SkillStepType
    payload: Union[ToolStep, DecisionStep, CompleteStep]

    model_config = {"frozen": True, "use_enum_values": True}

    @field_validator("payload", mode="before")
    @classmethod
    def _dispatch_payload(cls, v: Any, info: Any) -> Any:
        # If the caller already built the model, pass through.
        if isinstance(v, BaseModel):
            return v
        # Otherwise we need to peek at *both* the outer `kind` and the raw
        # payload dict to pick the right model.
        # `info.data` contains the fields already validated, but because
        # `kind` may not have been validated yet, we read from the raw data.
        kind_val = None
        if hasattr(info, "data") and info.data:
            kind_val = info.data.get("kind")
        if kind_val is None and isinstance(v, dict):
            # Fall back to the raw input data that was passed to the model.
            kind_val = v.get("kind") if isinstance(v, dict) else None

        if kind_val == SkillStepType.TOOL or kind_val == "tool":
            return ToolStep(**v)
        elif kind_val == SkillStepType.DECISION or kind_val == "decision":
            return DecisionStep(**v)
        elif kind_val == SkillStepType.COMPLETE or kind_val == "complete":
            return CompleteStep(**v)
        raise ValueError(f"Unknown step kind: {kind_val!r}")

    @model_validator(mode="after")
    def _check_kind_payload_match(self) -> SkillStep:
        kind = self.kind
        payload = self.payload
        if kind == SkillStepType.TOOL and not isinstance(payload, ToolStep):
            raise ValueError("kind is 'tool' but payload is not a ToolStep")
        if kind == SkillStepType.DECISION and not isinstance(payload, DecisionStep):
            raise ValueError("kind is 'decision' but payload is not a DecisionStep")
        if kind == SkillStepType.COMPLETE and not isinstance(payload, CompleteStep):
            raise ValueError("kind is 'complete' but payload is not a CompleteStep")
        return self


# ---------------------------------------------------------------------------
# Skill (root model)
# ---------------------------------------------------------------------------

_SKILL_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class Skill(BaseModel):
    """Root skill definition."""

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    description: str
    version: str
    author: str = ""
    license: str = "MIT"
    tags: List[str] = Field(default_factory=list)
    inputs: List[SkillInput] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    steps: List[SkillStep] = Field(...)
    on_error: SkillErrorPolicy = SkillErrorPolicy.STOP
    on_block: SkillErrorPolicy = SkillErrorPolicy.STOP
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True, "use_enum_values": True}
