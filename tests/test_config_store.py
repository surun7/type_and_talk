# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the configuration store (TOML-backed persistent config)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from unittest import mock

import pytest

from agent_uia.config import ConfigStore
from agent_uia.ui.app_controller import AppConfig


@pytest.fixture
def store_cls():
    """Return the ConfigStore class."""
    return ConfigStore


def test_load_default_when_file_missing(tmp_path: Path, store_cls):
    """When the config file does not exist, load() must return default AppConfig."""
    config_path = tmp_path / "config.toml"
    store = store_cls(config_path)
    config = store.load()
    assert isinstance(config, AppConfig)
    # Verify sensible defaults.
    assert config.theme == "dark"
    assert config.asr_model == "base"
    assert config.hotkey == "ctrl+shift+space"


def test_round_trip(tmp_path: Path, store_cls):
    """Save a config with modified fields, load it back, and verify they match."""
    config_path = tmp_path / "config.toml"
    store = store_cls(config_path)

    original = AppConfig(
        hotkey="alt+space",
        asr_model="small",
        theme="light",
        enable_tts=True,
        tts_voice="en-US-JennyNeural",
    )
    store.save(original)

    loaded = store.load()
    assert loaded.hotkey == "alt+space"
    assert loaded.asr_model == "small"
    assert loaded.theme == "light"
    assert loaded.enable_tts is True
    assert loaded.tts_voice == "en-US-JennyNeural"


def test_partial_config_uses_defaults(tmp_path: Path, store_cls):
    """A TOML file with only the [api] section must fall back to defaults for
    all other fields."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[api]\nkey = \"sk-test\"\nbase_url = \"https://api.example.com/v1\"\n",
        encoding="utf-8",
    )

    store = store_cls(config_path)
    config = store.load()
    # [api] fields should be present if AppConfig has them; for fields
    # not covered by the partial file, the store returns defaults.
    assert config.theme == "dark"
    assert config.asr_model == "base"


def test_corrupt_file_backed_up(tmp_path: Path, store_cls):
    """When the config file contains invalid TOML, load() must raise
    ConfigCorruptError and create a .corrupt-<timestamp>.bak backup."""
    from agent_uia.config import ConfigCorruptError

    config_path = tmp_path / "config.toml"
    config_path.write_text("[[[garbage]]]\nkey = broken", encoding="utf-8")

    store = store_cls(config_path)
    with pytest.raises(ConfigCorruptError):
        store.load()

    # Verify a backup file was created alongside the original.
    backup_files = list(tmp_path.glob("config.corrupt-*.bak"))
    assert len(backup_files) == 1, "Expected exactly one backup file"

    # The backup should contain the original garbage content.
    backup_content = backup_files[0].read_text(encoding="utf-8")
    assert "garbage" in backup_content

    # The original file might have been renamed to the backup. Either way,
    # at least the backup file exists with the original content.
    assert backup_files[0].exists()


def test_atomic_write_no_partial_files(tmp_path: Path, store_cls):
    """If os.replace raises mid-write, the original config file must remain
    unchanged."""
    config_path = tmp_path / "config.toml"
    # Write an initial valid config.
    config_path.write_text("theme = \"light\"\n", encoding="utf-8")

    store = store_cls(config_path)

    original_content = config_path.read_text(encoding="utf-8")

    with mock.patch("os.replace", side_effect=OSError("rename failed")):
        with pytest.raises(OSError, match="rename failed"):
            store.save(AppConfig(theme="dark"))

    # Original file must be untouched.
    assert config_path.read_text(encoding="utf-8") == original_content
