# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Type & Talk authors
#
"""Loads skills from disk.

Public API
---------
- :class:`SkillSource` — origin of a loaded skill (BUILTIN or USER).
- :class:`LoadedSkill` — a skill paired with its source and path.
- :class:`SkillInstallError` — raised when installation fails.
- :class:`SkillRegistry` — scans, loads, installs, uninstalls skills.
- :func:`default_registry` — module-level singleton.
"""

from __future__ import annotations

import ipaddress
import shutil
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger

from agent_uia.paths import get_app_data_dir
from agent_uia.skills.parser import SkillParseError, parse_skill_file
from agent_uia.skills.schema import Skill

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SkillInstallError(Exception):
    """Raised when a skill cannot be installed or uninstalled."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SkillSource(str, Enum):
    """Origin of a loaded skill."""

    BUILTIN = "builtin"
    USER = "user"


# ---------------------------------------------------------------------------
# LoadedSkill
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadedSkill:
    """A skill loaded from disk, paired with its provenance metadata."""

    skill: Skill
    source: SkillSource
    path: Path


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Scans, loads, installs, and uninstalls skill YAML files.

    Args:
        builtin_dir: Directory containing built-in skill files.
        user_dir:    Directory for user-installed skills.  Defaults to
            ``get_app_data_dir() / "skills"``.
    """

    def __init__(
        self,
        builtin_dir: Path,
        user_dir: Path | None = None,
    ) -> None:
        self._builtin_dir = Path(builtin_dir).resolve()
        self._user_dir = (
            Path(user_dir).resolve()
            if user_dir is not None
            else get_app_data_dir() / "skills"
        )
        self._skills: dict[str, LoadedSkill] = {}
        self._loaded = False

    # ── public API ─────────────────────────────────────────────────────────

    def load_all(self) -> list[LoadedSkill]:
        """Scan both directories and return all loaded skills.

        User skills with the same ``id`` as a builtin skill override it
        (a warning is logged).  Results are sorted by skill id.
        """
        self._skills.clear()

        # 1. Load builtin skills.
        builtin_map: dict[str, LoadedSkill] = {}
        if self._builtin_dir.is_dir():
            for yaml_path in sorted(self._builtin_dir.rglob("*.yaml")):
                self._try_load(yaml_path, SkillSource.BUILTIN, builtin_map)
            for yaml_path in sorted(self._builtin_dir.rglob("*.yml")):
                self._try_load(yaml_path, SkillSource.BUILTIN, builtin_map)

        # 2. Load user skills (override builtins).
        user_map: dict[str, LoadedSkill] = {}
        self._user_dir.mkdir(parents=True, exist_ok=True)
        if self._user_dir.is_dir():
            for yaml_path in sorted(self._user_dir.rglob("*.yaml")):
                self._try_load(yaml_path, SkillSource.USER, user_map)
            for yaml_path in sorted(self._user_dir.rglob("*.yml")):
                self._try_load(yaml_path, SkillSource.USER, user_map)

        # 3. Merge: user overrides builtin.
        self._skills = dict(builtin_map)
        for skill_id, loaded in user_map.items():
            if skill_id in builtin_map:
                logger.warning(
                    "User skill %r overrides builtin skill from %s",
                    skill_id,
                    builtin_map[skill_id].path,
                )
            self._skills[skill_id] = loaded

        self._loaded = True

        # 4. Sort by id.
        sorted_skills = sorted(self._skills.values(), key=lambda ls: ls.skill.id)
        return list(sorted_skills)

    def get(self, skill_id: str) -> LoadedSkill | None:
        """Return the :class:`LoadedSkill` for *skill_id*, or ``None``.

        Calls :meth:`load_all` first if the registry has not been loaded yet.
        """
        if not self._loaded:
            self.load_all()
        return self._skills.get(skill_id)

    def install_from_file(self, src_path: Path) -> Path:
        """Copy a skill YAML file into the user directory.

        The file is validated (parsed) before copying.

        Args:
            src_path: Path to the source ``.yaml`` / ``.yml`` file.

        Returns:
            The destination path in the user directory.

        Raises:
            SkillInstallError: If the file cannot be read, parsed, or copied.
        """
        src = Path(src_path).resolve()
        if not src.is_file():
            raise SkillInstallError(f"Not a file: {src}")

        # Validate by parsing.
        try:
            parse_skill_file(src)
        except SkillParseError as exc:
            raise SkillInstallError(
                f"Invalid skill file {src}: {exc}"
            ) from exc

        # Copy to user directory.
        self._user_dir.mkdir(parents=True, exist_ok=True)
        dest = self._user_dir / src.name
        try:
            shutil.copy2(str(src), str(dest))
        except OSError as exc:
            raise SkillInstallError(
                f"Failed to copy {src} -> {dest}: {exc}"
            ) from exc

        logger.info("Installed skill from %s -> %s", src, dest)
        # Force reload so the new skill is available.
        self._loaded = False
        return dest

    def install_from_url(self, url: str) -> Path:
        """Download a skill YAML from *url* and save it to the user directory.

        Only ``https://`` URLs are accepted (SSRF protection via the
        :mod:`ipaddress` module).  Maximum download size is 64 KB.

        Args:
            url: The HTTPS URL to download from.

        Returns:
            The destination path in the user directory.

        Raises:
            SkillInstallError: On any URL, network, parse, or write failure.
        """
        import httpx

        # ── Scheme check ─────────────────────────────────────────────
        if not url.lower().startswith("https://"):
            raise SkillInstallError(
                "Only HTTPS URLs are allowed for skill installation"
            )

        # ── SSRF protection ──────────────────────────────────────────
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname is None:
            raise SkillInstallError(f"Could not parse hostname from URL: {url}")

        try:
            # Resolve the hostname to IP addresses.
            import socket

            addrs = socket.getaddrinfo(hostname, 443)
            for addr_family, _socktype, _proto, _canonname, sockaddr in addrs:
                ip_str = sockaddr[0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                except ValueError:
                    continue
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    raise SkillInstallError(
                        f"SSRF blocked: {hostname} resolves to private IP "
                        f"{ip_str} (URL: {url})"
                    )
        except OSError as exc:
            raise SkillInstallError(
                f"DNS resolution failed for {hostname}: {exc}"
            ) from exc

        # ── Download ─────────────────────────────────────────────────
        try:
            response = httpx.get(url, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SkillInstallError(
                f"Failed to download from {url}: {exc}"
            ) from exc

        content = response.content
        if len(content) > 64 * 1024:
            raise SkillInstallError(
                f"Downloaded file exceeds 64 KB limit ({len(content)} bytes)"
            )

        # ── Validate YAML ────────────────────────────────────────────
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillInstallError(
                f"Downloaded file is not valid UTF-8: {exc}"
            ) from exc

        from agent_uia.skills.parser import parse_skill_yaml

        try:
            skill = parse_skill_yaml(text, source=url)
        except SkillParseError as exc:
            raise SkillInstallError(
                f"Invalid skill YAML from {url}: {exc}"
            ) from exc

        # ── Save to disk ─────────────────────────────────────────────
        self._user_dir.mkdir(parents=True, exist_ok=True)
        dest = self._user_dir / f"{skill.id}.yaml"
        try:
            dest.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise SkillInstallError(
                f"Failed to write skill to {dest}: {exc}"
            ) from exc

        logger.info("Installed skill from URL %s -> %s", url, dest)
        self._loaded = False
        return dest

    def uninstall(self, skill_id: str) -> bool:
        """Remove a user-installed skill by id.

        Returns ``True`` if the skill was found and removed, ``False`` if
        no user skill with that id exists.

        Raises:
            SkillInstallError: If the skill is a builtin skill (cannot be
                uninstalled).
        """
        if not self._loaded:
            self.load_all()

        loaded = self._skills.get(skill_id)
        if loaded is None:
            return False

        if loaded.source == SkillSource.BUILTIN:
            raise SkillInstallError(
                f"Cannot uninstall builtin skill {skill_id!r}"
            )

        try:
            loaded.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SkillInstallError(
                f"Failed to remove {loaded.path}: {exc}"
            ) from exc

        # Remove from cache.
        self._skills.pop(skill_id, None)
        logger.info("Uninstalled skill %r (%s)", skill_id, loaded.path)
        return True

    def reload(self) -> None:
        """Force a full reload on the next ``load_all()`` or ``get()`` call."""
        self._loaded = False
        self._skills.clear()

    # ── internal helpers ─────────────────────────────────────────────

    def _try_load(
        self,
        yaml_path: Path,
        source: SkillSource,
        dest_map: dict[str, LoadedSkill],
    ) -> None:
        """Parse a single YAML file and store it in *dest_map* keyed by id.

        Silently skips files that cannot be parsed (they are logged as
        warnings).
        """
        try:
            skill = parse_skill_file(yaml_path)
            loaded = LoadedSkill(skill=skill, source=source, path=yaml_path)
            existing = dest_map.get(skill.id)
            if existing is not None:
                logger.warning(
                    "Duplicate skill id %r in %s source: %s and %s",
                    skill.id,
                    source.value,
                    existing.path,
                    yaml_path,
                )
            dest_map[skill.id] = loaded
        except SkillParseError as exc:
            logger.warning("Skipping invalid skill file %s: %s", yaml_path, exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unexpected error loading skill %s: %s", yaml_path, exc
            )


# ── Singleton ─────────────────────────────────────────────────────────────────

_default_registry: SkillRegistry | None = None
_default_registry_lock: threading.Lock = threading.Lock()


def default_registry() -> SkillRegistry:
    """Return the process-wide :class:`SkillRegistry` singleton.

    The registry is initialised lazily on first call.  The builtin directory
    is ``<package_dir>/skills/skills`` (a ``skills/`` sub-directory under the
    ``agent_uia/skills/`` package), and the user directory defaults to
    ``<app_data_dir>/skills``.

    Returns:
        The singleton :class:`SkillRegistry` instance.
    """
    global _default_registry  # noqa: PLW0603
    if _default_registry is None:
        with _default_registry_lock:
            if _default_registry is None:
                from agent_uia.paths import PACKAGE_DIR

                builtin_dir = PACKAGE_DIR / "skills" / "builtin"
                _default_registry = SkillRegistry(
                    builtin_dir=builtin_dir,
                )
    return _default_registry
