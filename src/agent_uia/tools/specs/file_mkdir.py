# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: file_mkdir."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agent_uia.tools.base import _ToolSpec

_Directory = Literal[
    "desktop",
    "documents",
    "downloads",
    "pictures",
    "music",
    "videos",
    "agent_uia_config",
]


class FileMkdirInput(_ToolSpec):
    """Create a new directory inside a user directory."""

    directory: _Directory = Field(
        ...,
        description="Which user directory to create the folder inside.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9 _\-\.]+$",
        description="Name of the new directory. Only safe characters allowed.",
    )

    @classmethod
    def tool_name(cls) -> str:
        return "file_mkdir"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Create a new directory inside one of the well-known user "
            "directories. Fails if the directory already exists."
        )
