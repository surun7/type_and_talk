# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the centralised path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_uia.paths import get_logs_dir, get_model_path, get_models_dir


def test_get_models_dir_uses_localappdata_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """When LOCALAPPDATA is set, get_models_dir() lives under it."""
    fake_local = "C:\\Users\\test\\AppData\\Local"
    monkeypatch.setenv("LOCALAPPDATA", fake_local)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\test")  # ensure fallback not used

    models_dir = get_models_dir()
    expected = Path(fake_local) / "agent-uia" / "models"
    assert models_dir == expected


def test_get_models_dir_fallback_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """When LOCALAPPDATA is absent, get_models_dir() falls back to ~/.agent-uia."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("HOME", raising=False)

    # Ensure we can control Path.home()
    fake_home = Path("/tmp/fake_home")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    models_dir = get_models_dir()
    expected = fake_home / ".agent-uia" / "models"
    assert models_dir == expected


def test_get_model_path_returns_models_dir_with_name() -> None:
    """get_model_path('base') returns <models_dir>/faster-whisper-base."""
    # We verify the composition without hitting the filesystem by checking
    # the relative path is correct.
    model_path = get_model_path("base")
    assert model_path.name == "faster-whisper-base"
    assert model_path.parent.name == "models"


def test_get_model_path_uses_get_models_dir() -> None:
    """get_model_path delegates its parent directory to get_models_dir()."""
    model_path = get_model_path("tiny")
    expected_parent = get_models_dir()
    assert model_path.parent == expected_parent


def test_directory_auto_creation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Calling get_models_dir() auto-creates the directory tree."""
    fake_app_data = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_app_data))

    models_dir = get_models_dir()
    assert models_dir.exists()
    assert models_dir.is_dir()
    # Verify the full chain was created
    assert (fake_app_data / "agent-uia" / "models").exists()


def test_directory_is_not_recreated_if_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Calling get_models_dir() on an already-existing directory does not fail."""
    fake_app_data = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_app_data))
    existing = fake_app_data / "agent-uia" / "models"
    existing.mkdir(parents=True)

    # Should not raise
    models_dir = get_models_dir()
    assert models_dir == existing
    assert models_dir.exists()


def test_get_logs_dir_returns_logs_in_app_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_logs_dir() returns <app_data_dir>/logs and creates it."""
    fake_app_data = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_app_data))

    logs_dir = get_logs_dir()
    expected = fake_app_data / "agent-uia" / "logs"
    assert logs_dir == expected
    assert logs_dir.exists()


def test_get_logs_dir_auto_creates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_logs_dir() creates the logs directory if it does not exist."""
    fake_app_data = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_app_data))

    target = fake_app_data / "agent-uia" / "logs"
    assert not target.exists()

    logs_dir = get_logs_dir()
    assert logs_dir == target
    assert target.exists()


def test_multiple_calls_return_same_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Repeated calls to get_models_dir() return the same Path object value."""
    fake_app_data = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_app_data))

    first = get_models_dir()
    second = get_models_dir()
    assert first == second

