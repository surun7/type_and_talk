# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for SkillRegistry — loading, installing, uninstalling skills."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest import mock

import pytest

from agent_uia.skills.loader import (
    LoadedSkill,
    SkillRegistry,
    SkillSource,
    default_registry,
)


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    """Return a SkillRegistry with isolated user dir."""
    user_dir = tmp_path / "user_skills"
    user_dir.mkdir()
    return SkillRegistry(user_skills_dir=user_dir)


VALID_SKILL_YAML = """id: my-skill
name: My Skill
description: A test skill.
author: test
version: 1
steps:
  - id: step1
    kind: tool
    tool: click
    args:
      control_id: "btn1"
    depends_on: []
"""


# ── tests ──────────────────────────────────────────────────────────────────────


class TestLoadBuiltins:
    """Loading built-in skills."""

    def test_load_all_returns_skills(self, registry: SkillRegistry) -> None:
        """load_all() returns at least one skill (the built-ins)."""
        skills = registry.load_all()
        assert len(skills) > 0

    def test_load_builtins_count(self, registry: SkillRegistry) -> None:
        """There should be 5 built-in skills."""
        skills = registry.load_all()
        builtins = [s for s in skills if s.source == SkillSource.BUILTIN]
        assert len(builtins) == 5

    def test_builtin_ids_are_unique(self, registry: SkillRegistry) -> None:
        """All built-in skill ids are unique."""
        skills = registry.load_all()
        builtins = [s for s in skills if s.source == SkillSource.BUILTIN]
        ids = [s.skill.id for s in builtins]
        assert len(ids) == len(set(ids))

    def test_builtin_ids_known(self, registry: SkillRegistry) -> None:
        """The 5 built-in skills have the expected ids."""
        skills = registry.load_all()
        builtins = [s for s in skills if s.source == SkillSource.BUILTIN]
        ids = {s.skill.id for s in builtins}
        expected = {
            "click-fill-form",
            "launch-and-wait",
            "find-and-click",
            "confirm-then-act",
            "type-and-check",
        }
        assert ids == expected

    def test_load_builtin_specific(self, registry: SkillRegistry) -> None:
        """A specific built-in skill is loadable by id."""
        skill = registry.get("click-fill-form")
        assert skill is not None
        assert skill.skill.id == "click-fill-form"
        assert skill.source == SkillSource.BUILTIN

    def test_load_nonexistent_returns_none(self, registry: SkillRegistry) -> None:
        """Getting a non-existent skill returns None."""
        skill = registry.get("nonexistent-skill")
        assert skill is None


class TestInstallUserSkill:
    """Installing a user skill from a YAML file."""

    def test_install_and_reload(self, registry: SkillRegistry, tmp_path: Path) -> None:
        """Install a skill YAML, reload, verify it appears with source=USER."""
        yaml_path = tmp_path / "my-skill.yaml"
        yaml_path.write_text(VALID_SKILL_YAML)

        registry.install(yaml_path)
        skills = registry.load_all()
        user_skills = [s for s in skills if s.source == SkillSource.USER]
        assert len(user_skills) == 1
        assert user_skills[0].skill.id == "my-skill"

    def test_install_get_by_id(self, registry: SkillRegistry, tmp_path: Path) -> None:
        """After install, the skill should be retrievable by id."""
        yaml_path = tmp_path / "my-skill.yaml"
        yaml_path.write_text(VALID_SKILL_YAML)

        registry.install(yaml_path)
        skill = registry.get("my-skill")
        assert skill is not None
        assert skill.source == SkillSource.USER

    def test_install_invalid_yaml_raises(
        self, registry: SkillRegistry, tmp_path: Path
    ) -> None:
        """Installing an invalid YAML file should raise."""
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text("<<<garbage>>>")

        with pytest.raises(Exception):
            registry.install(yaml_path)


class TestUserOverridesBuiltin:
    """A user skill with the same id as a builtin should override it."""

    def test_user_overrides_builtin(
        self, registry: SkillRegistry, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """User skill with same id -> warning logged, user version loaded."""
        caplog.set_level(logging.WARNING)

        # Install a user skill with the same id as a builtin.
        user_yaml = """id: click-fill-form
name: Overridden Skill
description: User override of builtin.
author: user
version: 1
steps:
  - id: step1
    kind: tool
    tool: click
    args:
      control_id: "btn1"
    depends_on: []
"""
        yaml_path = tmp_path / "override.yaml"
        yaml_path.write_text(user_yaml)
        registry.install(yaml_path)

        loaded = registry.get("click-fill-form")
        assert loaded is not None
        assert loaded.source == SkillSource.USER
        assert loaded.skill.name == "Overridden Skill"

        # Check that a warning was logged.
        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("click-fill-form" in r.getMessage() for r in warning_records)


class TestInstallFromUrl:
    """Installing a skill from a URL."""

    @pytest.mark.asyncio
    async def test_install_from_url(self, registry: SkillRegistry) -> None:
        """A valid HTTPS URL should download and install the skill."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.text = VALID_SKILL_YAML
        mock_response.headers = {"content-length": str(len(VALID_SKILL_YAML))}

        with mock.patch("httpx.AsyncClient") as mock_client_class:
            mock_client = mock.AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            skill = await registry.install_from_url("https://example.com/skills/my-skill.yaml")

        assert skill is not None
        assert skill.skill.id == "my-skill"
        assert skill.source == SkillSource.USER

    @pytest.mark.asyncio
    async def test_install_from_url_caches(
        self, registry: SkillRegistry
    ) -> None:
        """A URL that was already installed should return cached skill."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.text = VALID_SKILL_YAML
        mock_response.headers = {"content-length": str(len(VALID_SKILL_YAML))}

        with mock.patch("httpx.AsyncClient") as mock_client_class:
            mock_client = mock.AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            skill1 = await registry.install_from_url(
                "https://example.com/skills/my-skill.yaml"
            )
            # Second call should use cache (no additional HTTP request).
            skill2 = await registry.install_from_url(
                "https://example.com/skills/my-skill.yaml"
            )

        assert skill1 is not None
        assert skill2 is not None
        assert skill1.skill.id == skill2.skill.id
        assert mock_client.get.await_count == 1  # Only one actual HTTP request


class TestInstallFromUrlRejectsHttp:
    """Non-HTTPS URLs should be rejected."""

    @pytest.mark.asyncio
    async def test_http_rejected(self, registry: SkillRegistry) -> None:
        """An HTTP (non-HTTPS) URL should be rejected."""
        with pytest.raises(ValueError, match="HTTPS"):
            await registry.install_from_url("http://example.com/skills/my-skill.yaml")

    @pytest.mark.asyncio
    async def test_ftp_rejected(self, registry: SkillRegistry) -> None:
        """An FTP URL should be rejected."""
        with pytest.raises(ValueError, match="HTTPS"):
            await registry.install_from_url("ftp://example.com/skills/my-skill.yaml")


class TestInstallFromUrlMaxSize:
    """Overly large responses should be rejected."""

    @pytest.mark.asyncio
    async def test_response_too_large(self, registry: SkillRegistry) -> None:
        """A response exceeding max_size should be rejected."""
        large_yaml = VALID_SKILL_YAML + ("\n" + " " * 1000) * 1000
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.text = large_yaml
        mock_response.headers = {"content-length": str(len(large_yaml))}

        with mock.patch("httpx.AsyncClient") as mock_client_class:
            mock_client = mock.AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            with pytest.raises(ValueError, match="too large|max size|exceeds"):
                await registry.install_from_url(
                    "https://example.com/skills/huge.yaml",
                    max_size=1024,
                )

    @pytest.mark.asyncio
    async def test_no_content_length_uses_default_limit(
        self, registry: SkillRegistry
    ) -> None:
        """If content-length is missing, the default max size should apply."""
        small_yaml = VALID_SKILL_YAML
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.text = small_yaml
        mock_response.headers = {}

        with mock.patch("httpx.AsyncClient") as mock_client_class:
            mock_client = mock.AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            skill = await registry.install_from_url(
                "https://example.com/skills/small.yaml"
            )
            assert skill is not None


class TestUninstall:
    """Uninstalling a user skill."""

    def test_uninstall_removes_file(
        self, registry: SkillRegistry, tmp_path: Path
    ) -> None:
        """After uninstall, the skill file should be removed and skill gone."""
        yaml_path = tmp_path / "my-skill.yaml"
        yaml_path.write_text(VALID_SKILL_YAML)
        registry.install(yaml_path)

        # Verify it exists.
        assert registry.get("my-skill") is not None

        # Uninstall.
        registry.uninstall("my-skill")
        assert registry.get("my-skill") is None

        # The file should be gone from the user skills dir.
        user_dir = registry._user_skills_dir
        skill_files = list(user_dir.glob("*.yaml")) + list(user_dir.glob("*.yml"))
        skill_ids = {f.stem for f in skill_files}
        assert "my-skill" not in skill_ids

    def test_uninstall_nonexistent_does_nothing(
        self, registry: SkillRegistry
    ) -> None:
        """Uninstalling a skill that doesn't exist should not raise."""
        # Should not raise.
        registry.uninstall("nonexistent-skill")

    def test_uninstall_builtin_raises(
        self, registry: SkillRegistry
    ) -> None:
        """Uninstalling a built-in skill should raise."""
        with pytest.raises(ValueError, match="builtin|built-in"):
            registry.uninstall("click-fill-form")

    def test_uninstall_then_reinstall(
        self, registry: SkillRegistry, tmp_path: Path
    ) -> None:
        """After uninstall, the same skill can be reinstalled."""
        yaml_path = tmp_path / "my-skill.yaml"
        yaml_path.write_text(VALID_SKILL_YAML)
        registry.install(yaml_path)
        registry.uninstall("my-skill")
        assert registry.get("my-skill") is None

        # Reinstall.
        registry.install(yaml_path)
        assert registry.get("my-skill") is not None
